"""KalshiStrikeSelector — Crypto-only spot-to-strike alignment pipeline.

Filters Kalshi crypto contracts by proximity to current spot price,
rejecting irrelevant or deep-OTM contracts unless explicitly allowed
with capped risk. Used by both KalshiTradingAgent and the continuous
trader to guarantee tight strike selection anchored to live spot.

IMPORTANT: This selector is CRYPTO-ONLY. Macro markets (e.g., KXFED-*)
are explicitly not supported and will be skipped without producing ERROR logs.

Logging semantics for asset matching:
- ERROR: True cross-asset mismatch (e.g., expected BTC but ticker is ETH).
       This indicates a wiring/configuration bug that needs immediate attention.
- WARNING: Expected crypto asset known, but ticker asset cannot be inferred.
       Indicates missing ticker mapping or data issue, but not a hard failure.
- DEBUG (or no log): Macro/non-crypto markets (e.g., KXFED-*) or when both
       expected and inferred assets are unknown. Expected behavior, not an error.

Design constraints:
- Hard reject contracts outside configured max_spot_to_strike_pct.
- Optional deep-OTM allowance with separate risk cap.
- Per-asset/timeframe thresholds from YAML config or code defaults.
- Structured logging for every rejection (reason, asset, ticker, distance).
- No fallback to arbitrary contracts; if no suitable strike → log & skip.
- Crypto-only: Macro markets bypass strike selection entirely.

Config keys (in ``kalshi_agent_grid.yaml`` per agent or global):

    strike_selection:
      max_spot_to_strike_pct: 0.08     # max |spot-strike|/strike (fraction)
      target_spot_band_pct: 0.03       # preferred ATM band (fraction)
      deep_otm_allowed: false
      deep_otm_max_risk_pct: 0.005     # max risk per trade when deep OTM

Regression guard: This module was fixed to eliminate false-positive
STRIKE_ASSET_MISMATCH ERROR spam from macro markets (41+ repeating errors
per minute for KXFED-* tickers). See tests for coverage.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config.kalshi_crypto_series_meta import SERIES_META_BY_TICKER, infer_asset_from_kalshi_market_ticker
from monitoring.metrics import get_metrics_registry
from utils.logger import get_logger

# BTC-Anchored Model for dynamic strike distance (Task 4: wire to NearSpotSelector)
try:
    from merid.signals.btc_anchored_move import get_btc_anchored_model
    _BTC_ANCHORED_AVAILABLE = True
except ImportError:
    _BTC_ANCHORED_AVAILABLE = False

logger = get_logger("merid.prediction.kalshi_strike_selector")

# ═══════════════════════════════════════════════════════════════════════════
# "No Surprises" Integration: Centralized Config for 15m Execution Guards
# ═══════════════════════════════════════════════════════════════════════════
# For 15m markets, use the canonical distance config from kalshi_distance.yaml.
# Non-15m markets (signal-only) continue to use the wider legacy defaults.

_15m_cfg: Optional[Any] = None

def _get_15m_distance_config() -> Optional[Any]:
    """Get centralized distance config for 15m markets."""
    global _15m_cfg
    if _15m_cfg is None:
        try:
            from merid.prediction.kalshi_distance_config import get_distance_config
            _15m_cfg = get_distance_config()
        except Exception as e:
            logger.debug("Could not load centralized distance config: %s", e)
            _15m_cfg = None
    return _15m_cfg


def get_max_distance_for_15m(asset: str) -> float:
    """Get max distance for 15m markets (tight execution guard values).
    
    Uses centralized config if available, otherwise falls back to inline defaults
    matching the execution guards in trading_agent.py.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        
    Returns:
        Max distance as fraction (e.g., 0.04 for 4.0%)
    """
    cfg = _get_15m_distance_config()
    if cfg is not None:
        return cfg.max_delta_pct.get(asset, 0.065)  # Default 6.5% if unknown
    
    # Fallback to inline defaults (OPTIMIZED 2026-05-10: aligned with kalshi_distance.yaml)
    return {
        "BTC": 0.04,     # 4.0% - aligned with strike selector
        "ETH": 0.05,     # 5.0% - aligned with strike selector
        "SOL": 0.06,     # 6.0% - aligned with strike selector
        "XRP": 0.065,    # 6.5% - aligned with strike selector
        "DOGE": 0.065,   # 6.5% - aligned with strike selector
    }.get(asset, 0.065)

# ═══════════════════════════════════════════════════════════════════════════
# Crypto-only guard
# ═══════════════════════════════════════════════════════════════════════════

# Recognized crypto ticker prefixes for Kalshi crypto markets
CRYPTO_TICKER_PREFIXES: Tuple[str, ...] = (
    "KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE",
)


def is_crypto_market(ticker: str) -> bool:
    """Return True if ticker is a recognized Kalshi crypto market.
    
    Macro markets (e.g., KXFED-*, KXECON-*) return False and should bypass
    the crypto-only strike selector without producing ERROR logs.
    """
    if not ticker:
        return False
    upper = ticker.strip().upper()
    return any(upper.startswith(prefix) for prefix in CRYPTO_TICKER_PREFIXES)

# Import calibrator for data-driven thresholds (lazy to avoid circular deps)
_calibrator_imported = False
_calibrator = None

def _get_calibrator():
    global _calibrator_imported, _calibrator
    if not _calibrator_imported:
        try:
            from merid.prediction.kalshi_strike_calibrator import get_calibrator
            _calibrator = get_calibrator()
        except Exception:
            _calibrator = None
        _calibrator_imported = True
    return _calibrator

# P0-002: Asset-ticker mismatch counter (initialized lazily)
_strike_asset_mismatch_counter = None

def _get_strike_asset_mismatch_counter():
    global _strike_asset_mismatch_counter
    if _strike_asset_mismatch_counter is None:
        registry = get_metrics_registry()
        _strike_asset_mismatch_counter = registry.counter(
            "merid_pm_strike_asset_mismatch_total",
            "Total asset-ticker mismatches in strike selection (indicates cross-asset mispairing)",
            ["asset", "ticker", "inferred_asset"],
        )
    return _strike_asset_mismatch_counter


def asset_in_ticker(ticker: str, expected_asset: str) -> bool:
    """Validate that the expected asset matches the asset inferred from the ticker.

    P0-002: Hard validation to prevent cross-asset mispairing (e.g., BTC spot used for ETH market).

    Logging semantics:
    - ERROR: True cross-asset mismatch (expected BTC, inferred ETH) - wiring bug.
    - WARNING: Expected crypto asset known, but ticker asset cannot be inferred.
    - DEBUG: Macro/non-crypto markets or both assets unknown - expected behavior.

    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-27APR-T101500").
        expected_asset: Expected asset (e.g., "BTC").

    Returns:
        True if ticker contains expected asset, False otherwise.
    """
    if not ticker:
        return False
    
    ticker_upper = ticker.strip().upper()
    expected_upper = (expected_asset or "").upper()
    
    # Case 1: Neither expected nor can we infer - likely macro market
    # Log at DEBUG only (expected behavior for non-crypto markets)
    if not expected_upper:
        inferred = infer_asset_from_kalshi_market_ticker(ticker)
        if inferred is None:
            # Try series-level lookup for crypto markets
            series_part = ticker_upper.split("-")[0] if "-" in ticker_upper else ticker_upper
            meta = SERIES_META_BY_TICKER.get(series_part)
            inferred = meta.asset if meta else None
        
        if inferred is None:
            logger.debug(
                "[STRIKE_ASSET_NONE] ticker=%s - no expected asset, ticker not recognized "
                "as crypto (expected for macro markets like KXFED-*)",
                ticker,
            )
        return False

    # We have an expected asset - try to infer from ticker
    inferred = infer_asset_from_kalshi_market_ticker(ticker)
    if inferred is None:
        # Try series-level lookup
        series_part = ticker_upper.split("-")[0] if "-" in ticker_upper else ticker_upper
        meta = SERIES_META_BY_TICKER.get(series_part)
        inferred = meta.asset if meta else None

    # Case 2: Expected asset known, but cannot infer from ticker
    # This is a WARNING - potential config/data issue but not a hard failure
    if inferred is None:
        # Record metric for observability but not as an error
        counter = _get_strike_asset_mismatch_counter()
        counter.inc(labels={
            "asset": expected_upper,
            "ticker": ticker,
            "inferred_asset": "UNK",
        })
        logger.warning(
            "[STRIKE_ASSET_UNKNOWN] asset=%s ticker=%s - expected crypto asset "
            "but ticker asset cannot be inferred (missing mapping or non-crypto ticker)",
            expected_upper,
            ticker,
        )
        return False

    # Case 3: Both known and match - success
    if inferred == expected_upper:
        return True

    # Case 3.5: Both are UNK/unknown - macro market without asset mapping
    # This is DEBUG only - expected behavior for non-crypto markets like KXFED-*
    # The crypto-only guard in select_strike() should have caught this, but if
    # an agent passes asset="UNK" for a macro market, we handle it gracefully.
    if expected_upper in ("UNK", "UNKNOWN", "") or inferred in ("UNK", "UNKNOWN"):
        logger.debug(
            "[STRIKE_ASSET_SKIP] asset=%s ticker=%s inferred=%s — "
            "macro/non-crypto market, skipping strike selection",
            expected_upper,
            ticker,
            inferred,
        )
        return False

    # Case 4: TRUE CROSS-ASSET MISMATCH - both known but different
    # This is an ERROR - indicates wiring/configuration bug (e.g., BTC spot for ETH market)
    counter = _get_strike_asset_mismatch_counter()
    counter.inc(labels={
        "asset": expected_upper,
        "ticker": ticker,
        "inferred_asset": inferred,
    })
    logger.error(
        "[STRIKE_ASSET_MISMATCH] asset=%s ticker=%s inferred=%s — "
        "TRUE cross-asset mispairing detected (wiring bug), rejecting trade",
        expected_upper,
        ticker,
        inferred,
    )
    return False

# ── Default per-asset/timeframe max distance bands ────────────────────
# CALIBRATED FOR INTRADAY OPTIONS TRADING (v1, 2026-04-14)
#
# Design rationale:
# - Intraday profitable flow clusters around ATM to slightly OTM
# - Far OTM options have low delta and tend not to move enough
# - Shorter timeframes = tighter % bands, higher-vol assets = slightly wider
# - BTC, SOL higher-vol; XRP, DOGE lower-vol but spiky
#
# Calibration source: Interactive Brokers options guidance + Reddit 0DTE best practices
# Focus: ATM/slightly OTM for intraday, avoid deep OTM unless explicit tail bets
#
# Operational guidelines:
# - Start in lower half of each range (e.g., BTC 15m = 4-5%, not 6%)
# - After paper/live sessions, pull realized distance vs PnL distributions
# - Adjust per asset/timeframe based on hit-rate (e.g., if winning at 5%, try 6%)
#
# v1 values (per-side absolute % distance from spot):
# │ Asset │ 15m  │ 1h   │Daily │
# │ BTC   │ 0.06 │ 0.08 │ 0.12 │
# │ ETH   │ 0.06 │ 0.08 │ 0.12 │
# │ SOL   │ 0.08 │ 0.09 │ 0.15 │
# │ XRP   │ 0.08 │ 0.07 │ 0.15 │
# │ DOGE  │ 0.06 │ 0.08 │ 0.12 │  # Calibrated to volatility (~2-3x BTC)|
#
# These are BOOTSTRAP DEFAULTS. The calibrator (kalshi_strike_calibrator.py)
# will override these once MIN_OBS observations accumulate per (asset, timeframe).

DEFAULT_MAX_DISTANCE: Dict[Tuple[str, str], float] = {
    # PRODUCTION FIX (2026-05-01): Sweet spot calibration for profitable trading
    # Previous extreme widening (35-50% for hourly) allowed strikes too far from the money,
    # causing poor risk/reward and edge decay before position could profit.
    # 
    # New bands calibrated for optimal edge capture:
    # - 15m: 5-8% (tight precision for quick scalps)
    # - Hourly: 15-20% (sweet spot for directional edge - close enough for quick moves)
    # - Daily: 25-30% (allows overnight moves but still actionable)
    # - Weekly+: 35-50% (longer holds need more room, but capped for risk management)
    # - Monthly/Annual: 50-75% (extreme moves only, primarily for hedging)
    #
    # These values ensure contracts are close enough to spot for effective theta capture
    # while still allowing practical market selection from available Kalshi strikes.
    #
    # Intraday - 15m: tight bands for micro-scalping precision
    ("BTC", "15m"): 0.05,     # 5% - tight for BTC stability
    ("ETH", "15m"): 0.06,     # 6% - slightly wider for ETH volatility
    ("SOL", "15m"): 0.07,     # 7% - SOL volatility
    ("XRP", "15m"): 0.08,     # 8% - XRP higher volatility
    ("DOGE", "15m"): 0.08,    # 8% - DOGE meme volatility
    # Hourly - SWEET SPOT: 15-20% max for effective directional trading
    ("BTC", "1h"): 0.15,      # 15% - optimal for hourly BTC momentum
    ("ETH", "1h"): 0.18,      # 18% - ETH hourly needs slightly more room
    ("SOL", "1h"): 0.20,      # 20% - SOL volatility requires wider band
    ("XRP", "1h"): 0.20,      # 20% - XRP hourly volatility
    ("DOGE", "1h"): 0.25,     # 25% - DOGE extreme volatility, but capped
    # Daily - 25-30% for overnight directional holds
    ("BTC", "daily"): 0.25,   # 25% - daily BTC moves
    ("ETH", "daily"): 0.28,   # 28% - daily ETH volatility
    ("SOL", "daily"): 0.30,    # 30% - SOL daily moves
    ("XRP", "daily"): 0.30,    # 30% - XRP daily
    ("DOGE", "daily"): 0.35,   # 35% - DOGE daily (capped for risk)
    # Weekly - 35-45% for multi-day holds
    ("BTC", "weekly"): 0.35,   # 35% - weekly BTC
    ("ETH", "weekly"): 0.40,   # 40% - weekly ETH
    ("SOL", "weekly"): 0.45,   # 45% - weekly SOL volatility
    ("XRP", "weekly"): 0.45,   # 45% - weekly XRP
    ("DOGE", "weekly"): 0.50,   # 50% - weekly DOGE (extreme moves only)
    # Monthly/Annual - 50-75% for long-tenor, primarily hedging
    ("BTC", "monthly"): 0.50, ("BTC", "annual"): 0.60,
    ("ETH", "monthly"): 0.55, ("ETH", "annual"): 0.70,
    ("SOL", "monthly"): 0.60, ("SOL", "annual"): 0.75,
    ("XRP", "monthly"): 0.60, ("XRP", "annual"): 0.75,
    ("DOGE", "monthly"): 0.65, ("DOGE", "annual"): 0.75,  # Capped for risk management
}

# Default preferred ATM band (fraction of spot).
# Target band is the "sweet spot" for strike selection - contracts inside this
# band are preferred over those further out but still within max distance.
# Calibrated to roughly 40-50% of max distance for intraday ATM focus.
DEFAULT_TARGET_BAND: Dict[Tuple[str, str], float] = {
    # Intraday: tighter ATM bands (40-50% of max distance)
    # v3 (2026-04-19): Updated to match v3 max distances
    ("BTC", "15m"):   0.025, ("BTC", "1h"):   0.035,   # max: 0.06, 0.08
    ("ETH", "15m"):   0.025, ("ETH", "1h"):   0.035,   # max: 0.06, 0.08
    ("SOL", "15m"):   0.030, ("SOL", "1h"):   0.040,   # max: 0.07, 0.09
    ("XRP", "15m"):   0.030, ("XRP", "1h"):   0.040,   # max: 0.08, 0.08 (~30-40% ratio)
    ("DOGE", "15m"):  0.025, ("DOGE", "1h"):  0.035,   # max: 0.065, 0.085
    # Daily: moderate bands
    ("BTC", "daily"): 0.040, ("BTC", "weekly"): 0.060,
    ("BTC", "monthly"): 0.080, ("BTC", "annual"): 0.100,
    ("ETH", "daily"): 0.040, ("ETH", "weekly"): 0.060,
    ("ETH", "monthly"): 0.080, ("ETH", "annual"): 0.100,
    ("SOL", "daily"): 0.050, ("SOL", "weekly"): 0.075,
    ("SOL", "monthly"): 0.100, ("SOL", "annual"): 0.125,
    ("XRP", "daily"): 0.035, ("XRP", "weekly"): 0.050,
    ("XRP", "monthly"): 0.060, ("XRP", "annual"): 0.080,
    ("DOGE", "daily"): 0.040, ("DOGE", "weekly"): 0.060,
    ("DOGE", "monthly"): 0.080, ("DOGE", "annual"): 0.100,
}

# Global fallback when asset/timeframe combo is not in the default tables.
# PRODUCTION FIX v5 (2026-04-26): Widened fallback to allow unknown asset/tf combos
FALLBACK_MAX_DISTANCE_PCT = 0.50   # Was 0.125 - allow 50% distance as safe default
FALLBACK_TARGET_BAND_PCT = 0.10  # Was 0.05


# ── Config dataclass ─────────────────────────────────────────────────

@dataclass
class StrikeSelectionConfig:
    """Per-agent or global strike selection parameters.

    Populated from YAML ``strike_selection:`` block or defaults.
    """
    max_spot_to_strike_pct: Optional[float] = None  # None = use per-asset/tf default
    target_spot_band_pct: Optional[float] = None     # None = use per-asset/tf default
    deep_otm_allowed: bool = False
    deep_otm_max_risk_pct: float = 0.005  # 0.5% of bankroll max when deep OTM
    rejection_log_throttle_seconds: float = 30.0  # throttle STRIKE_REJECT logs
    # Directional markets (15m up/down) have no strike price by design.
    # When True, pass them through instead of rejecting as missing_strike.
    allow_directional_passthrough: bool = True
    # Per-asset/timeframe overrides: {("BTC","15m"): 0.06, ...}
    per_asset_tf_max_distance: Dict[Tuple[str, str], float] = field(default_factory=dict)
    per_asset_tf_target_band: Dict[Tuple[str, str], float] = field(default_factory=dict)


# ── Rejection reasons ────────────────────────────────────────────────

class RejectionReason:
    ASSET_TICKER_MISMATCH = "asset_ticker_mismatch"  # P0-002: Cross-asset mispairing
    NON_CRYPTO_MARKET = "non_crypto_market"  # Selector is crypto-only; macro markets skip
    MISSING_SPOT = "missing_spot"
    MISSING_STRIKE = "missing_strike"
    ZERO_STRIKE = "zero_strike"
    EXCEEDS_MAX_DISTANCE = "exceeds_max_distance"
    DEEP_OTM_NOT_ALLOWED = "deep_otm_not_allowed"
    DIRECTIONAL_NO_SPOT = "directional_no_spot"  # directional market, spot unavailable


# ── Selection result ─────────────────────────────────────────────────

@dataclass
class StrikeSelectionResult:
    """Result for a single contract evaluation."""
    ticker: str
    asset: str
    timeframe: str
    accepted: bool
    spot: Optional[float] = None
    strike: Optional[float] = None
    distance_pct: Optional[float] = None  # |spot - strike| / SPOT (consistent measure)
    max_allowed_pct: Optional[float] = None
    target_band_pct: Optional[float] = None
    in_target_band: bool = False
    is_deep_otm: bool = False
    is_directional: bool = False  # True for markets with no strike (up/down directional)
    rejection_reason: Optional[str] = None
    risk_capped: bool = False  # True if accepted with deep-OTM risk cap
    # WARNING: This is metadata only. The actual risk cap must be enforced by
    # the calling code (KalshiRiskManager or position sizing logic).
    # See: apply_deep_otm_risk_cap() helper below for wiring pattern.

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "ticker": self.ticker,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "accepted": self.accepted,
        }
        if self.spot is not None:
            d["spot"] = round(self.spot, 2)
        if self.strike is not None:
            d["strike"] = round(self.strike, 2)
        if self.distance_pct is not None:
            d["distance_pct"] = round(self.distance_pct, 6)
        if self.max_allowed_pct is not None:
            d["max_allowed_pct"] = round(self.max_allowed_pct, 4)
        if self.in_target_band:
            d["in_target_band"] = True
        if self.is_deep_otm:
            d["is_deep_otm"] = True
        if self.rejection_reason:
            d["rejection_reason"] = self.rejection_reason
        if self.is_directional:
            d["is_directional"] = True
        if self.risk_capped:
            d["risk_capped"] = True
        return d


@dataclass
class BatchSelectionResult:
    """Result of evaluating a batch of contracts."""
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    in_target_band: int = 0
    deep_otm_allowed: int = 0
    results: List[StrikeSelectionResult] = field(default_factory=list)
    rejection_reasons: Dict[str, int] = field(default_factory=dict)

    def accepted_results(self) -> List[StrikeSelectionResult]:
        return [r for r in self.results if r.accepted]

    def rejected_results(self) -> List[StrikeSelectionResult]:
        return [r for r in self.results if not r.accepted]

    def summary(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "in_target_band": self.in_target_band,
            "deep_otm_allowed": self.deep_otm_allowed,
            "rejection_reasons": dict(self.rejection_reasons),
        }


# ── Core selector ────────────────────────────────────────────────────

class KalshiStrikeSelector:
    """Evaluates contracts against spot-to-strike distance thresholds.

    Thread-safe (stateless per call; config is immutable after init).

    Usage::

        selector = KalshiStrikeSelector(config)
        result = selector.evaluate("KXBTC15M-27APR-T101500", "BTC", "15m",
                                   spot=101200.0, strike=101500.0)
        if result.accepted:
            # proceed to edge/sizing
        else:
            logger.info("Rejected: %s", result.rejection_reason)
    """

    def __init__(self, config: Optional[StrikeSelectionConfig] = None) -> None:
        self._config = config or StrikeSelectionConfig()
        # Throttle rejection logging (key -> last_log_time)
        self._log_throttle: Dict[str, float] = {}
        self._log_interval_s = self._config.rejection_log_throttle_seconds

    @property
    def config(self) -> StrikeSelectionConfig:
        return self._config

    # ── Single contract evaluation ────────────────────────────────────

    def evaluate(
        self,
        ticker: str,
        asset: str,
        timeframe: str,
        spot: Optional[float],
        strike: Optional[float],
    ) -> StrikeSelectionResult:
        """Evaluate a single contract against strike selection thresholds.

        CRYPTO-ONLY: This selector skips non-crypto markets (e.g., KXFED-*)
        without producing ERROR logs. Macro markets return rejected with
        reason NON_CRYPTO_MARKET at DEBUG level only.

        Args:
            ticker: Kalshi market ticker.
            asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE).
            timeframe: Market timeframe (15m, 1h, daily, weekly, monthly, annual).
            spot: Current spot price in USD.  None → reject.
            strike: Contract strike price in USD.  None → reject.

        Returns:
            StrikeSelectionResult with accepted/rejected status and reason.
        """
        asset_upper = (asset or "").upper()
        tf_lower = (timeframe or "").lower()

        # Crypto-only guard: Skip non-crypto markets without ERROR spam
        if not is_crypto_market(ticker):
            logger.debug(
                "[STRIKE_SELECTOR_SKIP] ticker=%s - non-crypto market, "
                "bypassing crypto strike selector",
                ticker,
            )
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset_upper,
                timeframe=tf_lower,
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason=RejectionReason.NON_CRYPTO_MARKET,
            )

        # P0-002: Hard validation — asset must match ticker
        if not asset_in_ticker(ticker, asset_upper):
            return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                RejectionReason.ASSET_TICKER_MISMATCH)

        # Gate: missing spot
        if spot is None or spot <= 0:
            return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                RejectionReason.MISSING_SPOT)

        # Gate: missing strike — directional markets have no strike by design
        if strike is None:
            if self._config.allow_directional_passthrough:
                # Directional market (e.g. 15m up/down): no strike to measure
                # distance against.  Pass through with is_directional=True so
                # downstream knows this is not a threshold/bracket contract.
                if spot is not None and spot > 0:
                    return StrikeSelectionResult(
                        ticker=ticker,
                        asset=asset_upper,
                        timeframe=tf_lower,
                        accepted=True,
                        spot=spot,
                        strike=None,
                        is_directional=True,
                    )
                else:
                    return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                        RejectionReason.DIRECTIONAL_NO_SPOT)
            return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                RejectionReason.MISSING_STRIKE)

        # Gate: zero strike or None
        if strike is None or strike <= 0:
            return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                RejectionReason.ZERO_STRIKE)

        # Gate: None spot before division
        if spot is None or spot <= 0:
            return self._reject(ticker, asset_upper, tf_lower, spot, strike,
                                RejectionReason.MISSING_SPOT)

        # Compute distance: percentage relative to SPOT (not strike)
        # This ensures consistent distance measurement regardless of strike level
        distance_pct = abs(spot - strike) / spot

        # SAFETY CLAMP: Reject pathological tickers where strike is extremely far.
        # For assets with deep_otm_allowed (e.g., DOGE), use a higher threshold (3x/300%)
        # to accommodate volatility. For other assets, use conservative 50% clamp.
        # This catches mis-parsed or corrupted tickers while respecting config.
        if self._config.deep_otm_allowed:
            # Deep OTM allowed: use 300% clamp (strike can be 4x spot or 0.25x spot)
            safety_threshold = 3.0  # 300%
            if distance_pct > safety_threshold:
                return self._reject(
                    ticker, asset_upper, tf_lower, spot, strike,
                    RejectionReason.EXCEEDS_MAX_DISTANCE,
                    distance_pct=distance_pct,
                    max_allowed_pct=safety_threshold,
                )
        else:
            # Safety clamp: use the larger of 50% or the configured per-asset
            # max_distance so this clamp never contradicts explicit config.
            # Without this, widened per-asset limits (e.g. DOGE 1h = 200%) are
            # dead code because the old hard 50% clamp fires first.
            _cfg_max = self._resolve_max_distance(asset_upper, tf_lower)
            _safety_pct = max(0.50, _cfg_max)
            _low = spot * (1.0 - _safety_pct)
            _high = spot * (1.0 + _safety_pct)
            if strike < _low or strike > _high:
                return self._reject(
                    ticker, asset_upper, tf_lower, spot, strike,
                    RejectionReason.EXCEEDS_MAX_DISTANCE,
                    distance_pct=distance_pct,
                    max_allowed_pct=_safety_pct,
                )

        # Log observation for calibration (fire-and-forget)
        calibrator = _get_calibrator()
        if calibrator is not None and spot is not None and strike is not None:
            try:
                calibrator.log_observation(
                    asset=asset_upper,
                    timeframe=tf_lower,
                    spot=spot,
                    strike=strike,
                    ticker=ticker,
                )
            except Exception:
                pass  # Don't fail evaluation on logging

        # Resolve thresholds
        max_dist = self._resolve_max_distance(asset_upper, tf_lower)
        target_band = self._resolve_target_band(asset_upper, tf_lower)
        in_target = distance_pct <= target_band

        # Gate: exceeds max distance
        if distance_pct > max_dist:
            # Check deep OTM allowance
            if self._config.deep_otm_allowed:
                result = StrikeSelectionResult(
                    ticker=ticker,
                    asset=asset_upper,
                    timeframe=tf_lower,
                    accepted=True,
                    spot=spot,
                    strike=strike,
                    distance_pct=distance_pct,
                    max_allowed_pct=max_dist,
                    target_band_pct=target_band,
                    in_target_band=False,
                    is_deep_otm=True,
                    risk_capped=True,
                )
                self._log_deep_otm_acceptance(result)
                return result
            else:
                return self._reject(
                    ticker, asset_upper, tf_lower, spot, strike,
                    RejectionReason.EXCEEDS_MAX_DISTANCE,
                    distance_pct=distance_pct,
                    max_allowed_pct=max_dist,
                )

        return StrikeSelectionResult(
            ticker=ticker,
            asset=asset_upper,
            timeframe=tf_lower,
            accepted=True,
            spot=spot,
            strike=strike,
            distance_pct=distance_pct,
            max_allowed_pct=max_dist,
            target_band_pct=target_band,
            in_target_band=in_target,
        )

    # ── Signal-aware evaluation ─────────────────────────────────────────

    def evaluate_with_signal_context(
        self,
        ticker: str,
        asset: str,
        timeframe: str,
        spot: float,
        strike: Optional[float],
        fused_signal: Any,  # FusedClusterSignal
        market_structure: Any,  # MarketStructure
        regime_engine: Any,  # RegimeEngine
    ) -> StrikeSelectionResult:
        """
        Evaluate contract with full TA signal context.

        Incorporates multi-timeframe signals, regime classification, and
        market structure to dynamically adjust strike distance thresholds.

        Args:
            ticker: Kalshi market ticker.
            asset: Underlying asset.
            timeframe: Market timeframe.
            spot: Current spot price.
            strike: Contract strike (None for directional markets).
            fused_signal: FusedClusterSignal with direction, quality, confidence.
            market_structure: MarketStructure with trend/vol/liquidity regimes.
            regime_engine: RegimeEngine for dynamic distance calculations.

        Returns:
            StrikeSelectionResult with signal-aware rejection reasons.
        """
        asset_upper = (asset or "").upper()
        tf_lower = (timeframe or "").lower()

        # SHARED GUARDS: Same as evaluate() — crypto-only + asset match
        # Prevents cross-asset bugs and macro market leakage on this path too
        if not is_crypto_market(ticker):
            logger.debug(
                "[STRIKE_SELECTOR_SKIP_SIGNAL] ticker=%s - non-crypto market, "
                "bypassing crypto strike selector",
                ticker,
            )
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset_upper,
                timeframe=tf_lower,
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason=RejectionReason.NON_CRYPTO_MARKET,
            )

        # P0-002: Hard validation — asset must match ticker
        if not asset_in_ticker(ticker, asset_upper):
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset_upper,
                timeframe=tf_lower,
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason=RejectionReason.ASSET_TICKER_MISMATCH,
            )

        # Gate: missing/invalid spot
        if spot is None or spot <= 0:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset_upper,
                timeframe=tf_lower,
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason=RejectionReason.MISSING_SPOT,
            )

        # Import here to avoid circular deps at module load
        from merid.signals.ta_models import FusedClusterSignal, MarketStructure

        # Validate signal
        if not isinstance(fused_signal, FusedClusterSignal):
            logger.error("[STRIKE_SIGNAL_ERROR] fused_signal must be FusedClusterSignal")
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason="INVALID_FUSED_SIGNAL_TYPE",
            )

        # Signal direction check
        if fused_signal.direction == "flat":
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason="SIGNAL_FLAT",
            )

        # Signal quality check
        if fused_signal.rejection_reason:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason=f"FUSION_REJECT:{fused_signal.rejection_reason}",
            )

        if not fused_signal.is_tradeable():
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason="SIGNAL_NOT_TRADEABLE",
            )

        # Get base max distance
        base_max = self._resolve_max_distance(asset.upper(), timeframe.lower())

        # Calculate dynamic multiplier from regime engine
        if regime_engine and isinstance(market_structure, MarketStructure):
            multiplier = regime_engine.get_dynamic_distance_multiplier(
                asset.upper(),
                base_max,
                fused_signal.quality_score,
                market_structure,
            )
        else:
            multiplier = 1.0

        # Apply multiplier
        dynamic_max = base_max * multiplier

        # Hard cap at 1.5x base
        dynamic_max = min(dynamic_max, base_max * 1.5)

        # Directional markets pass through if signal is valid
        if strike is None or strike <= 0:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=True,
                spot=spot,
                strike=None,
                is_directional=True,
            )

        # Gate: None spot or strike before division
        if spot is None or spot <= 0:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                rejection_reason="MISSING_SPOT_FOR_DISTANCE",
            )
        if strike is None:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=None,
                rejection_reason="MISSING_STRIKE_FOR_DISTANCE",
            )

        # Distance calculation: percentage relative to SPOT (not strike)
        distance_pct = abs(spot - strike) / spot

        # SAFETY CLAMP: Hard reject if strike is extremely far (>50% from spot)
        if strike < spot * 0.5 or strike > spot * 1.5:
            return StrikeSelectionResult(
                ticker=ticker,
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                accepted=False,
                spot=spot,
                strike=strike,
                distance_pct=distance_pct,
                max_allowed_pct=0.5,
                rejection_reason="EXTREME_STRIKE_CLAMP",
            )

        # Check against dynamic threshold
        if distance_pct > dynamic_max:
            # Check if deep OTM is allowed
            if self._config.deep_otm_allowed:
                result = StrikeSelectionResult(
                    ticker=ticker,
                    asset=asset.upper(),
                    timeframe=timeframe.lower(),
                    accepted=True,
                    spot=spot,
                    strike=strike,
                    distance_pct=distance_pct,
                    max_allowed_pct=dynamic_max,
                    is_deep_otm=True,
                    risk_capped=True,
                )
                self._log_deep_otm_acceptance(result)
                return result
            else:
                return StrikeSelectionResult(
                    ticker=ticker,
                    asset=asset.upper(),
                    timeframe=timeframe.lower(),
                    accepted=False,
                    spot=spot,
                    strike=strike,
                    distance_pct=distance_pct,
                    max_allowed_pct=dynamic_max,
                    rejection_reason="SIGNAL_DISTANCE_EXCEEDS_DYNAMIC_MAX",
                )

        # Contract accepted
        return StrikeSelectionResult(
            ticker=ticker,
            asset=asset.upper(),
            timeframe=timeframe.lower(),
            accepted=True,
            spot=spot,
            strike=strike,
            distance_pct=distance_pct,
            max_allowed_pct=dynamic_max,
            target_band_pct=self._resolve_target_band(asset.upper(), timeframe.lower()),
            in_target_band=False,  # Could calculate
        )

    # ── Batch evaluation ──────────────────────────────────────────────

    def evaluate_batch(
        self,
        contracts: List[Dict[str, Any]],
    ) -> BatchSelectionResult:
        """Evaluate a batch of contracts.

        Each dict must have keys: ticker, asset, timeframe, spot, strike.

        Returns:
            BatchSelectionResult with per-contract results and aggregate stats.
        """
        batch = BatchSelectionResult()
        batch.total = len(contracts)

        for c in contracts:
            result = self.evaluate(
                ticker=c.get("ticker", ""),
                asset=c.get("asset", ""),
                timeframe=c.get("timeframe", ""),
                spot=c.get("spot"),
                strike=c.get("strike"),
            )
            batch.results.append(result)
            if result.accepted:
                batch.accepted += 1
                if result.in_target_band:
                    batch.in_target_band += 1
                if result.is_deep_otm:
                    batch.deep_otm_allowed += 1
            else:
                batch.rejected += 1
                reason = result.rejection_reason or "unknown"
                batch.rejection_reasons[reason] = batch.rejection_reasons.get(reason, 0) + 1

        return batch

    # ── Threshold resolution ──────────────────────────────────────────

    def _resolve_max_distance(self, asset: str, timeframe: str) -> float:
        """Resolve max distance for an asset/timeframe combo.

        Priority:
        1. 15m canonical config (tight execution guard values from kalshi_distance.yaml)
        2. Config override (per_asset_tf_max_distance)
        3. Config override (max_spot_to_strike_pct)
        4. Calibrated threshold (if data available, see kalshi_strike_calibrator.py)
        5. Bootstrap defaults (DEFAULT_MAX_DISTANCE - wide for non-15m signal-only)
        6. FALLBACK_MAX_DISTANCE_PCT
        """
        # 1. 15m canonical config: tight execution guard values
        # This ensures strike selector and execution guards are aligned for 15m markets
        if timeframe == "15m":
            canonical_distance = get_max_distance_for_15m(asset)
            logger.debug(
                "[STRIKE_SELECTOR_15M] %s/%s using canonical max_distance=%.4f (%.2f%%)",
                asset, timeframe, canonical_distance, canonical_distance * 100
            )
            return canonical_distance
        
        key = (asset, timeframe)
        if key in self._config.per_asset_tf_max_distance:
            return self._config.per_asset_tf_max_distance[key]
        if self._config.max_spot_to_strike_pct is not None:
            return self._config.max_spot_to_strike_pct

        # 4. Data-driven calibration (if available)
        calibrator = _get_calibrator()
        if calibrator is not None:
            calibrated = calibrator.get_max_distance(asset, timeframe)
            # Only use calibrated if it's from sufficient data (not bootstrap fallback)
            summary = calibrator.get_calibration_summary()
            count = summary.get("observation_counts", {}).get(f"{asset},{timeframe}", 0)
            if count >= 500:  # MIN_OBS threshold
                return calibrated
            # Log first-time fallback to help operators see calibration progress
            if count > 0 and count < 100:
                logger.debug(
                    "[STRIKE_CALIBRATION] %s/%s using bootstrap (obs=%d, need=500)",
                    asset, timeframe, count,
                )

        # 5. Bootstrap defaults (wide bands for non-15m signal-only markets)
        base_distance = DEFAULT_MAX_DISTANCE.get(key, FALLBACK_MAX_DISTANCE_PCT)

        # 6. BTC-Anchored adjustment for alt-coins (Task 4 wiring)
        # When BTC ATR is elevated, high-beta alts need wider strike bands
        if asset != "BTC" and _BTC_ANCHORED_AVAILABLE:
            btc_adjusted = self._get_btc_anchored_distance(asset, timeframe, base_distance)
            if btc_adjusted != base_distance:
                logger.debug(
                    "[STRIKE_SELECTOR_BTC_ANCHORED] %s/%s: base=%.2f%% adjusted=%.2f%%",
                    asset, timeframe, base_distance * 100, btc_adjusted * 100,
                )
                return btc_adjusted

        return base_distance

    def _get_btc_anchored_distance(self, asset: str, timeframe: str, base_distance: float) -> float:
        """Get BTC-anchored strike distance suggestion for alt-coins.

        When BTC volatility is elevated, alts with high beta to BTC should have
        wider strike distance bands to account for expected co-movement.

        Args:
            asset: Alt asset symbol (ETH, SOL, XRP, DOGE)
            timeframe: Market timeframe
            base_distance: Base max distance from config

        Returns:
            Suggested distance (may be same as base if no adjustment needed)
        """
        if not _BTC_ANCHORED_AVAILABLE or asset == "BTC":
            return base_distance

        try:
            model = get_btc_anchored_model()

            # Get BTC's current ATR from indicator stack (if available)
            btc_atr_pct = self._get_btc_atr_pct(timeframe)
            if btc_atr_pct is None:
                return base_distance

            # Get suggested distance from model
            suggested = model.suggested_strike_distance_pct(
                asset=asset,
                timeframe=timeframe,
                btc_atr_pct=btc_atr_pct,
                base_distance_pct=base_distance,
            )

            # Cap at 3x base to avoid runaway widening
            return min(suggested, base_distance * 3.0)

        except Exception as exc:
            logger.debug("[BTC_ANCHORED_DISTANCE] %s/%s: error getting suggestion: %s", asset, timeframe, exc)
            return base_distance

    def _get_btc_atr_pct(self, timeframe: str) -> Optional[float]:
        """Get BTC ATR as percentage of price from indicator stack.

        Returns None if indicator stack unavailable.
        """
        try:
            from merid.signals.crypto_15m_indicators import get_indicator_stack
            stack = get_indicator_stack()
            if stack is None:
                return None

            snap = stack.snapshot("BTC", timeframe)
            if snap is None or snap.atr is None or snap.price is None or snap.price <= 0:
                return None

            return snap.atr / snap.price
        except Exception:
            return None

    def _resolve_target_band(self, asset: str, timeframe: str) -> float:
        """Resolve target ATM band for an asset/timeframe combo.

        Priority: config.per_asset_tf_target_band → config.target_spot_band_pct
                  → DEFAULT_TARGET_BAND → FALLBACK_TARGET_BAND_PCT
        """
        key = (asset, timeframe)
        if key in self._config.per_asset_tf_target_band:
            return self._config.per_asset_tf_target_band[key]
        if self._config.target_spot_band_pct is not None:
            return self._config.target_spot_band_pct
        return DEFAULT_TARGET_BAND.get(key, FALLBACK_TARGET_BAND_PCT)

    def get_thresholds(self, asset: str, timeframe: str) -> Dict[str, Any]:
        """Return resolved thresholds for observability/diagnostics."""
        return {
            "max_distance_pct": self._resolve_max_distance(asset, timeframe),
            "target_band_pct": self._resolve_target_band(asset, timeframe),
            "deep_otm_allowed": self._config.deep_otm_allowed,
            "deep_otm_max_risk_pct": self._config.deep_otm_max_risk_pct,
        }

    # ── Internal helpers ──────────────────────────────────────────────

    def _reject(
        self,
        ticker: str,
        asset: str,
        timeframe: str,
        spot: Optional[float],
        strike: Optional[float],
        reason: str,
        distance_pct: Optional[float] = None,
        max_allowed_pct: Optional[float] = None,
    ) -> StrikeSelectionResult:
        result = StrikeSelectionResult(
            ticker=ticker,
            asset=asset,
            timeframe=timeframe,
            accepted=False,
            spot=spot,
            strike=strike,
            distance_pct=distance_pct,
            max_allowed_pct=max_allowed_pct,
            rejection_reason=reason,
        )
        self._log_rejection(result)
        return result

    def _log_rejection(self, result: StrikeSelectionResult) -> None:
        """Structured rejection log, throttled per ticker."""
        throttle_key = f"{result.ticker}|{result.rejection_reason}"
        now = time.monotonic()
        last = self._log_throttle.get(throttle_key, 0.0)
        if now - last < self._log_interval_s:
            return
        self._log_throttle[throttle_key] = now
        logger.info(
            "[STRIKE_REJECT] %s",
            json.dumps(result.to_dict(), default=str, sort_keys=True),
        )

    def _log_deep_otm_acceptance(self, result: StrikeSelectionResult) -> None:
        """Log when a deep-OTM contract is accepted with risk cap."""
        throttle_key = f"deep_otm|{result.ticker}"
        now = time.monotonic()
        last = self._log_throttle.get(throttle_key, 0.0)
        if now - last < self._log_interval_s:
            return
        self._log_throttle[throttle_key] = now
        logger.warning(
            "[STRIKE_DEEP_OTM_ACCEPT] %s — risk capped at %.2f%%",
            json.dumps(result.to_dict(), default=str, sort_keys=True),
            self._config.deep_otm_max_risk_pct * 100,
        )


# ── Risk cap wiring helper (for downstream integration) ────────────────

def apply_deep_otm_risk_cap(
    base_notional_cents: int,
    selector_result: StrikeSelectionResult,
    bankroll_cents: int,
) -> int:
    """Apply deep-OTM risk cap to position sizing.

    This is the wiring pattern for enforcing `risk_capped` metadata from
    StrikeSelectionResult. Call this in your position sizing logic when
    selector_result.risk_capped is True.

    Args:
        base_notional_cents: The normally-calculated notional (e.g., from Kelly).
        selector_result: The StrikeSelectionResult with risk_capped=True.
        bankroll_cents: Current bankroll in cents for pct-based cap.

    Returns:
        Capped notional in cents, never exceeding base_notional.

    Example::
        result = selector.evaluate(ticker, asset, tf, spot, strike)
        if result.accepted:
            raw_size = kelly_size(...)  # Your normal sizing
            final_size = apply_deep_otm_risk_cap(
                raw_size, result, bankroll_cents
            )
            # Now final_size respects the deep-OTM cap
    """
    if not selector_result.risk_capped:
        return base_notional_cents

    # Deep OTM cap: 0.5% of bankroll (from config default)
    deep_otm_max_risk_pct = 0.005  # 0.5%
    max_notional = int(bankroll_cents * deep_otm_max_risk_pct)

    capped = min(base_notional_cents, max_notional)
    if capped < base_notional_cents:
        logger.info(
            "[DEEP_OTM_RISK_CAP] %s: notional %d¢ -> %d¢ (cap=%.2f%% of bankroll)",
            selector_result.ticker,
            base_notional_cents,
            capped,
            deep_otm_max_risk_pct * 100,
        )
    return capped


# ── Config parser (for YAML integration) ─────────────────────────────

def parse_strike_selection_config(
    raw: Optional[Dict[str, Any]],
) -> StrikeSelectionConfig:
    """Parse a ``strike_selection:`` YAML block into StrikeSelectionConfig.

    Returns default config if raw is None or empty.
    """
    if not raw or not isinstance(raw, dict):
        return StrikeSelectionConfig()

    per_asset_tf_max: Dict[Tuple[str, str], float] = {}
    per_asset_tf_band: Dict[Tuple[str, str], float] = {}

    # Parse per-asset/timeframe overrides if present
    overrides = raw.get("per_asset_timeframe", {})
    if isinstance(overrides, dict):
        for key_str, vals in overrides.items():
            # key_str format: "BTC_15m" or "ETH_daily"
            parts = key_str.split("_", 1)
            if len(parts) != 2:
                continue
            asset, tf = parts[0].upper(), parts[1].lower()
            if isinstance(vals, dict):
                if "max_distance_pct" in vals:
                    per_asset_tf_max[(asset, tf)] = float(vals["max_distance_pct"])
                if "target_band_pct" in vals:
                    per_asset_tf_band[(asset, tf)] = float(vals["target_band_pct"])

    return StrikeSelectionConfig(
        max_spot_to_strike_pct=_float_or_none(raw.get("max_spot_to_strike_pct")),
        target_spot_band_pct=_float_or_none(raw.get("target_spot_band_pct")),
        deep_otm_allowed=bool(raw.get("deep_otm_allowed", False)),
        deep_otm_max_risk_pct=float(raw.get("deep_otm_max_risk_pct", 0.005)),
        rejection_log_throttle_seconds=float(raw.get("rejection_log_throttle_seconds", 30.0)),
        allow_directional_passthrough=bool(raw.get("allow_directional_passthrough", True)),
        per_asset_tf_max_distance=per_asset_tf_max,
        per_asset_tf_target_band=per_asset_tf_band,
    )


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── Singleton (lazy, used by trading agent) ───────────────────────────

_selector: Optional[KalshiStrikeSelector] = None


def get_strike_selector() -> KalshiStrikeSelector:
    """Get or create the global KalshiStrikeSelector (default config).

    Trading agents should prefer creating their own selector with
    per-agent config; this singleton uses global defaults.
    """
    global _selector
    if _selector is None:
        _selector = KalshiStrikeSelector()
    return _selector


def get_strike_selector_for_agent(
    agent_config: Any,
) -> KalshiStrikeSelector:
    """Create a KalshiStrikeSelector from an AgentConfig's strike_selection block.

    Falls back to global defaults if the agent has no strike_selection config.
    """
    raw = getattr(agent_config, "strike_selection", None)
    if raw and isinstance(raw, dict):
        config = parse_strike_selection_config(raw)
    elif isinstance(raw, StrikeSelectionConfig):
        config = raw
    else:
        config = StrikeSelectionConfig()
    return KalshiStrikeSelector(config)
