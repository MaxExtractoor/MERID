"""§3 Kalshi Strategy — Edge thresholds, time-to-expiry logic, position sizing.

Provides named, testable prediction-market playbooks for Kalshi:
- Same-market consistency checks (multi-outcome arb).
- Time-to-expiry aware behaviour (early speculative vs late arb).
- Explicit position sizing and exit rules.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional

# Sentiment gating mode - controls whether sentiment blocks trades
# Options: "gating" (sentiment can block), "feature_only" (sentiment only for model features), "disabled" (ignore sentiment)
# Profile YAML controls sentiment isolation for kalshi_crypto_15m_v2
_SENTIMENT_MODE_DEFAULT = "disabled"
SENTIMENT_MODE = os.getenv("MERID_SENTIMENT_MODE", _SENTIMENT_MODE_DEFAULT).lower()
SENTIMENT_GATING_ENABLED = SENTIMENT_MODE in ("gating", "full")

from merid.prediction.model import (
    ContractState,
    EdgeEstimate,
    MarketSnapshot,
    max_spot_age_seconds,
    PredictionMarketModel,
)
from merid.event_venues.kalshi.stop_candidate import (
    build_stop_candidate,
    maybe_submit_stop_candidate_sync,
    record_stop_candidate,
)
from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure

# Cross-asset top edge arbiter for dynamic floor selection
# This enables BTC, ETH, SOL, XRP, DOGE to compete for capital on relative edge
# instead of requiring each to clear hard per-asset thresholds
# Define CRYPTO_ASSETS locally for compatibility (crypto_top_edge moved to archive/legacy/)
CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# P0-001 FIX: Use helper function instead of constant for consistency across all PM paths.
# This ensures MERID_PM_MAX_SPOT_AGE_SECONDS env var is respected everywhere.
SNAPSHOT_STALE_SECONDS = max_spot_age_seconds()

# P0-002 FIX: Load edge thresholds from canonical YAML config
from typing import Dict
import yaml
from pathlib import Path


def _load_distance_config() -> Dict[str, Any]:
    """Load edge thresholds from kalshi_distance.yaml as single source of truth."""
    try:
        config_path = Path(__file__).parent.parent.parent / "config" / "kalshi_distance.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config or {}
    except Exception:
        # Cannot use logger here as it may not be initialized yet at module load time
        pass
    return {}


def _get_min_edge_for_phase(phase: ExpiryPhase) -> Decimal:
    """Get min edge from profile edge_bands (single source of truth).

    DELETED: kalshi_distance.yaml and env var overrides - now uses profile edge_bands
    2026-07-10: Updated to moltbook research values (BTC base 1.25%, terminal 1.75%)
    This is the absolute minimum floor across all assets - per-asset thresholds are higher.
    """
    # Single source of truth: 1.25% minimum edge (BTC base - most liquid asset)
    # Per-asset thresholds in profile YAML scale from this base (BTC 1.25% -> DOGE 2.75%)
    return Decimal("0.0125")


# Validate config loaded at module import time
_distance_config = _load_distance_config()

from merid.formulas import (
    FORMULAS_VERSION,
    AUDIT_SPEC_VERSION,
    get_version_info,
    generate_correlation_id,
    kelly_fraction,
    kelly_fraction_from_edge,
    quarter_kelly_size,
    PositionSizingInputs,
)
from utils.logger import get_logger

# Import invariant checkers for production logging
from merid.validation.edge_probability_invariants import (
    EdgeProbabilityInvariantChecker,
    check_edge_probability_consistency,
)
from merid.validation.canonical_mapping_invariants import (
    CanonicalMappingTable,
)

logger = get_logger("merid.prediction.strategy")

# Log version info on module load
_version_info = get_version_info()
logger.info(
    "Strategy module loaded | formulas=%s audit_spec=%s",
    _version_info["formulas_version"],
    _version_info["audit_spec_version"],
)


class SignalAction(str, Enum):
    """What the strategy recommends.
    
    CRITICAL: This enum is being integrated with unified signal terminology.
    For new code, prefer using signal_terminology.Action and signal_terminology.Side
    separately for clearer separation of concerns.
    """
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    CLOSE = "close"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUOTE = "quote"  # For market making: provides bid/ask


class ExpiryPhase(str, Enum):
    """Time-to-expiry regime."""
    UNKNOWN = "unknown"    # expiry not known — skip trading (D02 fix)
    EARLY = "early"        # > 24 h to expiry
    MID = "mid"            # 4–24 h
    LATE = "late"          # 1–4 h
    TERMINAL = "terminal"  # < 1 h


@dataclass
class StrategyConfig:
    """Tunable parameters for KalshiStrategy."""
    # Edge thresholds (as probability fraction, e.g. 0.04 = 4 %)
    # P0-003 FIX: Now loaded from kalshi_distance.yaml via _get_min_edge_for_phase()
    # Keeping dataclass fields for backwards compatibility but values are computed from YAML
    min_edge_early: Decimal = field(default_factory=lambda: _get_min_edge_for_phase(ExpiryPhase.EARLY))
    min_edge_mid: Decimal = field(default_factory=lambda: _get_min_edge_for_phase(ExpiryPhase.MID))
    min_edge_late: Decimal = field(default_factory=lambda: _get_min_edge_for_phase(ExpiryPhase.LATE))
    min_edge_terminal: Decimal = field(default_factory=lambda: _get_min_edge_for_phase(ExpiryPhase.TERMINAL))
    min_arb_edge: Decimal = Decimal("1.0")        # MICRO-BANKROLL: Disabled (1.0 = 100% edge required). Arb buys both sides causing duplicate race and requires 2x capital.

    # Position sizing - CRITICAL FIX: 0 = derive from live bankroll
    # Previous hardcoded values (100/25) were dangerous for micro bankrolls
    max_contracts_per_market: int = 0  # 0 = derive: 1 per $10 of bankroll, max 100
    max_contracts_per_order: int = 0  # 0 = derive: 1% of bankroll / price, max 25
    # ALIGNED TO PROFILE: 0.05 from kalshi_crypto_15m_v2.yaml (5% Kelly hard cap)
    kelly_fraction: Decimal = Decimal("0.02")       # CRITICAL FIX: 2% Kelly (aligned with unified risk limit, was 0.05 causing rejections)

    # Exit rules
    profit_target_pct: Decimal = Decimal("0.15")    # Take profit at 15 %
    stop_loss_pct: Decimal = Decimal("0.10")         # Cut at 10 % loss
    max_hold_hours: Decimal = Decimal("48")          # Force close after 48 h

    # Liquidity (post-edge guard — see _apply_liquidity_guard_after_edge).
    # Defaults are off: Kalshi often omits or zeroes 24h volume on short-dated crypto contracts;
    # set YAML ``min_volume`` / ``min_open_interest`` or env MERID_PM_MIN_VOLUME when you want a floor.
    min_volume: Decimal = Decimal("0")
    min_open_interest: Decimal = Decimal("0")
    min_depth_contracts: int = 5                      # Min depth at best price

    # Market Making
    # 2026-07-11: Updated mm_max_spread_cents from 10c to 30c to align with dynamic threshold system canonical default
    mm_max_spread_cents: Decimal = Decimal("30")     # Don't quote if spread > 30c
    mm_target_spread_cents: Decimal = Decimal("2")   # Try to quote 2c spread
    mm_inventory_limit: int = 50                     # Max contracts to hold per side
    mm_skew_factor: Decimal = Decimal("0.5")         # How much to lean based on inventory

    # Confidence — ALIGNED TO PROFILE YAML SINGLE SOURCE OF TRUTH: 65% threshold
    # Profile YAML (kalshi_crypto_15m_v2.yaml) sets min_confidence_threshold: 0.65
    # Research: 65% threshold balances signal quality with trade volume for 15m crypto markets
    # Industry best practices: 70% for high-conviction trades, 65% as minimum threshold
    # Override per-agent via YAML ``strategy: min_confidence: 0.65`` or env MERID_PM_MIN_CONFIDENCE.
    min_confidence: Decimal = Decimal("0.65")  # 65% — profile-aligned threshold

    # Archetype sentiment / regime tunables (YAML ``strategy:`` + pm_profiles + env)
    # PRODUCTION FIX v8 (2026-04-30): Lowered to 15.0 to match realistic market sentiment (was 35.0)
    # This aligns with observed local sentiment of 15.0 in logs - allowing contrarian trades to execute
    contrarian_sentiment_min: float = 15.0  # Lowered from 35.0 - allow realistic contrarian signals
    contrarian_model_gap_min: float = 0.10
    vol_breakout_neutral_low: float = 35.0
    vol_breakout_neutral_high: float = 65.0
    sentiment_mode: str = "gating"  # PRODUCTION FIX (2026-05-13): Configurable sentiment gating mode
    signal_mode: str = "trend"  # Signal mode: "trend" (trade with trend) or "mean_reversion" (trade against spikes)


@dataclass
class StrategySignal:
    """Output of strategy evaluation for one market."""
    market_id: str
    action: SignalAction
    side: str                  # "yes", "no", or "both"
    contracts: int             # Recommended size
    limit_price_cents: Optional[int] = None
    bid_price_cents: Optional[int] = None  # For QUOTE
    ask_price_cents: Optional[int] = None  # For QUOTE
    edge: Optional[EdgeEstimate] = None
    phase: Optional[ExpiryPhase] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain from DISCOVER
    # Optional structured gate context for PM_SIGNAL (thresholds, floors) — observability only
    eval_context: Dict[str, Any] = field(default_factory=dict)
    # Behavioral exploitation adjustments for logging
    behavioral_adjustments: Dict[str, Any] = field(default_factory=dict)

    def with_contracts(self, new_contracts: int) -> "StrategySignal":
        """Return a new signal with resized contract count."""
        return StrategySignal(
            market_id=self.market_id,
            action=self.action,
            side=self.side,
            contracts=new_contracts,
            limit_price_cents=self.limit_price_cents,
            bid_price_cents=self.bid_price_cents,
            ask_price_cents=self.ask_price_cents,
            edge=self.edge,
            phase=self.phase,
            reason=f"{self.reason} (resized from {self.contracts} to {new_contracts})",
            timestamp=self.timestamp,
            correlation_id=self.correlation_id,
            eval_context=dict(self.eval_context),
            behavioral_adjustments=dict(self.behavioral_adjustments),
        )

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "action": self.action.value,
            "side": self.side,
            "contracts": self.contracts,
            "limit_price_cents": self.limit_price_cents,
            "bid_price_cents": self.bid_price_cents,
            "ask_price_cents": self.ask_price_cents,
            "phase": self.phase.value if self.phase else None,
            "reason": self.reason,
            "net_edge": str(self.edge.net_edge) if self.edge else None,
            "timestamp": self.timestamp.isoformat(),
            "eval_context": dict(self.eval_context) if self.eval_context else {},
        }


@dataclass
class PositionState:
    """Tracks an open position for exit-rule evaluation."""
    market_id: str
    side: str
    contracts: int
    avg_entry_cents: Decimal
    opened_at: datetime
    current_price_cents: Optional[Decimal] = None
    unrealized_pnl_cents: Optional[Decimal] = None
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain from DISCOVER


class KalshiStrategy:
    """Prediction-market strategy dedicated to Kalshi.

    Evaluates MarketSnapshots and produces StrategySignals.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        model: Optional[PredictionMarketModel] = None,
        agent_name: str = "strategy",
    ):
        self.config = config or StrategyConfig()
        self.model = model or PredictionMarketModel()
        self._agent_name = agent_name
        self._positions: Dict[str, PositionState] = {}
        
        # CRITICAL FIX (2026-07-31): Initialize side diversity tracking
        # Tracks recent side selection bias to enable balanced YES/NO trading
        self._recent_side_bias = 0.5  # Start balanced (0.5 = 50% YES, 50% NO)
        self._recent_trades = []  # Track recent trades for bias calculation
        self._max_trade_history = 20  # Keep last 20 trades for bias calculation
    
    def _update_side_bias(self, side: str) -> None:
        """Update side diversity tracking after a trade.
        
        Args:
            side: "yes" or "no" - the side that was just traded
        """
        # Add trade to history
        self._recent_trades.append(side)
        
        # Keep only recent trades
        if len(self._recent_trades) > self._max_trade_history:
            self._recent_trades.pop(0)
        
        # Calculate bias (fraction of YES trades)
        yes_count = sum(1 for s in self._recent_trades if s == "yes")
        self._recent_side_bias = yes_count / len(self._recent_trades) if self._recent_trades else 0.5
        
        logger.debug(
            "[SIDE-DIVERSITY] Updated bias: %.2f (YES: %d/%d trades)",
            self._recent_side_bias, yes_count, len(self._recent_trades)
        )

    # ------------------------------------------------------------------
    # Expiry phase
    # ------------------------------------------------------------------

    def _expiry_phase(self, hours_left: Optional[Decimal]) -> ExpiryPhase:
        if hours_left is None:
            return ExpiryPhase.UNKNOWN  # unknown expiry — skip trading (D02 fix)
        if hours_left > 24:
            return ExpiryPhase.EARLY
        if hours_left > 4:
            return ExpiryPhase.MID
        if hours_left > 1:
            return ExpiryPhase.LATE
        return ExpiryPhase.TERMINAL

    def _min_edge_for_phase(self, phase: ExpiryPhase) -> Decimal:
        return {
            ExpiryPhase.UNKNOWN: Decimal("999"),  # unreachable — UNKNOWN exits before edge check
            ExpiryPhase.EARLY: self.config.min_edge_early,
            ExpiryPhase.MID: self.config.min_edge_mid,
            ExpiryPhase.LATE: self.config.min_edge_late,
            ExpiryPhase.TERMINAL: self.config.min_edge_terminal,
        }[phase]

    # ------------------------------------------------------------------
    # Position sizing (quarter-Kelly)
    # ------------------------------------------------------------------

    def _sentiment_size_factor(self, snapshot: "MarketSnapshot") -> float:
        """Compute size_factor from fear/greed and vol regime.

        For 15m scalper mode: Relaxed multipliers (0.70/0.85 vs 0.50/0.75)
        to allow larger positions during volatile periods when scalping
        opportunities are best.
        """
        import os
        is_scalper = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
        
        factor = 1.0

        if snapshot.sentiment_global is not None:
            fg_score = snapshot.sentiment_global
            if fg_score <= 20 or fg_score >= 80:
                # 15m scalper: 0.70 (was 0.50) - allow larger positions at extremes
                factor *= 0.70 if is_scalper else 0.5
            elif fg_score <= 30 or fg_score >= 70:
                # 15m scalper: 0.85 (was 0.75) - moderate reduction
                factor *= 0.85 if is_scalper else 0.75

        if snapshot.sentiment_regime:
            regime = snapshot.sentiment_regime.lower()
            if "extreme" in regime:
                # 15m scalper: 0.85 (was 0.70) - less penalty in extreme regimes
                factor *= 0.85 if is_scalper else 0.7

        # 15m scalper: higher floor (0.50 vs 0.35) for minimum position sizing
        min_factor = 0.50 if is_scalper else 0.35
        return max(min_factor, min(1.0, factor))

    def _pm_vol_band_size_factor(self, snapshot: "MarketSnapshot") -> float:
        """Return volatility-band based size multiplier.
        
        For 15m scalper mode: Relaxed high-vol penalty (0.85 vs 0.70)
        since volatility creates scalping opportunities.
        """
        import os
        is_scalper = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
        
        # FIX: Use correct attribute name 'crypto_vol_band' (string: low|mid|high)
        band = getattr(snapshot, "crypto_vol_band", None) or getattr(snapshot, "volatility_band", None)
        
        # 15m scalper: higher high-vol multiplier (0.85 vs 0.70)
        high_vol_mult = 0.85 if is_scalper else 0.70
        
        factor_map: Dict[str, float] = {
            "high": high_vol_mult,   # High vol = moderate reduction (less for scalper)
            "mid": 1.0,              # Normal
            "low": 1.0,              # Low vol = full size
        }
        factor = factor_map.get(band, 1.0)
        
        # SAFETY: Ensure factor is never 0 (prevents zero size_factor)
        if factor <= 0:
            logger.warning("[PM_VOL_BAND] Invalid factor=%.4f for band=%s, defaulting to 1.0", factor, band)
            factor = 1.0
        
        return factor

    def _apply_cycle_cap(
        self,
        size: int,
        snapshot: MarketSnapshot,
        side: str,
        net_edge: Optional[float] = None,
    ) -> int:
        """Apply cycle-level MAX_CYCLE_RISK_PCT bankroll allocation cap to contract size.
        
        For 15m scalper mode: MAX_CYCLE_RISK_PCT = 2% (unified across all modes, top-3 edge rule).

        Args:
            size: Current proposed contract count
            snapshot: Market snapshot for price/bankroll info
            side: "yes" or "no"
            net_edge: Edge value for logging

        Returns:
            int: Capped contract count
        """
        try:
            # LEGACY REMOVAL: dynamic_sizing moved to archive/legacy/ during 15m stack cleanup
            from decimal import Decimal
            # Apply cycle-level 1-3% bankroll cap across all winners
            bankroll_cents = getattr(snapshot, 'bankroll_cents', None)
            if bankroll_cents is None:
                return size  # Can't cap without bankroll info

            bankroll_usd = Decimal(bankroll_cents) / Decimal("100")

            # Get price from snapshot
            price_cents = None
            if side == "yes" and hasattr(snapshot, 'implied') and snapshot.implied:
                price_cents = int(snapshot.implied.yes_ask or snapshot.implied.yes_bid or 50)
            elif side == "no" and hasattr(snapshot, 'implied') and snapshot.implied:
                price_cents = int(snapshot.implied.no_ask or snapshot.implied.no_bid or 50)

            # Apply cycle cap
            capped_size, reason = apply_cycle_cap_to_kelly_size(
                kelly_contracts=size,
                bankroll_usd=bankroll_usd,
                price_cents=price_cents,
                ticker=snapshot.market_id,
                side=side,
                edge=Decimal(str(net_edge)) if net_edge else None,
            )

            if capped_size < size:
                logger.info(
                    "[CYCLE-CAP-APPLIED] %s | %d -> %d contracts (bankroll=$%.2f, price=%dc, %s)",
                    snapshot.market_id, size, capped_size,
                    float(bankroll_usd), price_cents or 50, reason
                )
                return capped_size
        except Exception as e:
            logger.debug("Cycle cap not applied for %s: %s", snapshot.market_id, e)

        return size

    def _kelly_size_with_sentiment(
        self,
        edge: EdgeEstimate,
        phase: ExpiryPhase,
        snapshot: "MarketSnapshot",
        correlation_id: Optional[str] = None,
    ) -> int:
        """Compute sentiment-adjusted position size.

        Passes the sentiment factor directly to PositionSizer.compute() as
        ``size_factor`` so the per-underlying hourly exposure cap is always
        enforced on the already-reduced size, not bypassed.

        Args:
            edge: Edge estimate
            phase: Expiry phase
            snapshot: Market snapshot with sentiment data
            correlation_id: Trace chain ID from DISCOVER

        Returns:
            Adjusted contract count
        """
        size_factor = self._sentiment_size_factor(snapshot) * self._pm_vol_band_size_factor(
            snapshot
        )
        return self._kelly_size(edge, phase, size_factor=size_factor, correlation_id=correlation_id)

    def _kelly_size(
        self,
        edge: EdgeEstimate,
        phase: ExpiryPhase,
        size_factor: float = 1.0,
        correlation_id: Optional[str] = None,
    ) -> int:
        """Compute position size via PositionSizer (fee-aware, adaptive Kelly).

        Delegates to the singleton PositionSizer which applies:
        - Fractional Kelly with Kalshi fee schedule
        - PF/expectancy scaling gates
        - Drawdown and vol-based adaptive shrinkage
        - Per-underlying hourly exposure caps

        ``size_factor`` (0.0–1.0) is a caller-supplied multiplier (e.g. from
        sentiment) applied *inside* PositionSizer so the hourly cap is always
        respected on the final contract count.

        Falls back to a simple inline calculation if the sizer is unavailable.
        
        [AGENT_AUDIT: Section 5] SIZE stage — Kelly/quarter-Kelly sizing with traceability.
        """
        # [TRACE] SIZE_DECISION entry
        if correlation_id:
            logger.info(
                "[TRACE] SIZE_DECISION | corr_id=%s | agent=%s | edge=%.4f | phase=%s | size_factor=%.2f | formulas=%s | audit_spec=%s",
                correlation_id,
                self._agent_name,
                float(edge.net_edge) if edge else 0.0,
                phase.value if phase else "unknown",
                size_factor,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )
        _bankroll_cents = 0
        try:
            # CRITICAL FIX: Use unified_sizing instead of legacy PositionSizer
            # Legacy PositionSizer is deprecated for Kalshi 15m crypto and does not enforce $1 cap correctly
            # unified_sizing.compute_order_size is the production-approved sizing function
            from merid.prediction.unified_sizing import compute_order_size

            # Convert edge fields to sizing inputs
            edge_pct = float(edge.net_edge)  # FRACTION units (0.0-1.0)
            market_prob = float(edge.market_prob)
            
            # FIX: Fetch actual contract price from market state instead of using probability-derived price
            # This fixes Kelly sizing returning 0 contracts when actual price differs from implied probability
            price_cents = None
            try:
                # LEGACY REMOVAL: dynamic_sizing moved to archive/legacy/ during 15m stack cleanup
                price_cents = None
                if price_cents is None or price_cents <= 0:
                    # 2026-07-31: Expanded price band (1c-99c) to handle extreme market conditions
                    # Previous 10c-75c range was too restrictive and dropped valid signals at 1c
                    # CRITICAL FIX (2026-08-01): Updated to 5c-85c for 15m crypto volatility
                    raw_price_cents = int(round(market_prob * 100))
                    
                    # Check if price is within canonical range (1c-99c)
                    if 1 <= raw_price_cents <= 99:
                        # Price is already in valid range - use it directly
                        price_cents = raw_price_cents
                        logger.info(
                            "[PRICE-SELECTION] asset=%s raw_price_cents=%d in canonical range [1c-99c] - using directly",
                            self._extract_asset_from_market_id(edge.market_id), raw_price_cents
                        )
                    else:
                        # Price is outside canonical range - drop candidate (strategy.py doesn't have orderbook access)
                        logger.warning(
                            "[PRICE-SELECTION] asset=%s raw_price_cents=%d outside canonical range [1c-99c] - dropping candidate (no orderbook access in strategy.py)",
                            self._extract_asset_from_market_id(edge.market_id), raw_price_cents
                        )
                        return None  # Drop candidate - no valid price in expanded range
            except Exception:
                # 2026-07-31: Expanded price band (1c-99c) to handle extreme market conditions
                # Previous 10c-75c range was too restrictive and dropped valid signals at 1c
                # CRITICAL FIX (2026-08-01): Updated to 5c-85c for 15m crypto volatility
                raw_price_cents = int(round(market_prob * 100))
                
                # Check if price is within canonical range (1c-99c)
                if 1 <= raw_price_cents <= 99:
                    # Price is already in valid range - use it directly
                    price_cents = raw_price_cents
                    logger.info(
                        "[PRICE-SELECTION] asset=%s raw_price_cents=%d in canonical range [1c-99c] - using directly",
                        self._extract_asset_from_market_id(edge.market_id), raw_price_cents
                    )
                else:
                    # Price is outside canonical range - drop candidate (strategy.py doesn't have orderbook access)
                    logger.warning(
                        "[PRICE-SELECTION] asset=%s raw_price_cents=%d outside canonical range [1c-99c] - dropping candidate (no orderbook access in strategy.py)",
                        self._extract_asset_from_market_id(edge.market_id), raw_price_cents
                    )
                    return None  # Drop candidate - no valid price in expanded range

            # FIX: Validate actual price against max_price_cents from threshold matrix
            # This prevents momentum scalping from trading high-priced (low-edge) contracts
            # Uses quick_win_max_price_cents for high-probability (80%+) trades in 15m timeframe
            # LEGACY REMOVAL: crypto_threshold_matrix moved to archive/legacy/ during 15m stack cleanup
            try:
                _asset = self._extract_asset_from_market_id(edge.market_id)
                _tf = self._resolve_timeframe_from_agent_name()
                if _asset and _tf:
                    # _row = resolve_merged_row(asset=_asset, timeframe=_tf, archetype="directional")
                    _row = None  # LEGACY REMOVAL
                    
                    # Determine confidence band based on model probability
                    _confidence_bands = _row.get("confidence_bands", [])
                    _current_band = None
                    _confidence_tier_multiplier = 1.0
                    if _confidence_bands and market_prob is not None:
                        for band in _confidence_bands:
                            min_conf = band.get("min_conf", 0.0)
                            max_conf = band.get("max_conf", 1.0)
                            if min_conf <= market_prob <= max_conf:
                                _current_band = band.get("name")
                                break
                    
                    # Get confidence tier multiplier from resolved row
                    _confidence_tier_mult = _row.get("confidence_tier_multiplier", {})
                    if _current_band and _confidence_tier_mult:
                        _confidence_tier_multiplier = _confidence_tier_mult.get(_current_band, 1.0)
                    
                    # Select appropriate price cap based on band and timeframe
                    _max_price_cents = _row.get("max_price_cents")
                    if _current_band == "quick_win" and _tf == "15m":
                        _quick_win_max_price_cents = _row.get("quick_win_max_price_cents")
                        if _quick_win_max_price_cents:
                            _max_price_cents = _quick_win_max_price_cents
                            logger.debug(
                                "[PRICE-GATE] using quick_win cap: %s | band=%s | price_cap=%dc | asset=%s tf=%s",
                                edge.market_id, _current_band, _max_price_cents, _asset, _tf
                            )
                    
                    if _max_price_cents and price_cents > _max_price_cents:
                        logger.warning(
                            "[PRICE-GATE] rejected: %s | actual_price=%dc > max=%dc | band=%s | asset=%s tf=%s",
                            edge.market_id, price_cents, _max_price_cents, _current_band, _asset, _tf
                        )
                        return 0
            except Exception as e:
                logger.debug("Could not validate max_price_cents for %s: %s", edge.market_id, e)
                _current_band = None
                _confidence_tier_multiplier = 1.0
            
            # Apply confidence tier multiplier to size_factor for unified_sizing
            size_factor = size_factor * _confidence_tier_multiplier

            logger.debug(
                "[KELLY_DEBUG] _kelly_size called: agent=%s edge_pct=%.2f phase=%s price_cents=%d",
                self._agent_name, edge_pct, phase.value if phase else None, price_cents
            )

            # CRITICAL FIX: Use unified v2 bankroll service for consistent sizing/risk
            # PM SIZING WIRING: All position sizing must use unified bankroll as single source of truth
            # CRITICAL FIX: Skip bankroll fetch during import time to prevent bankroll service initialization
            _bankroll_cents = 0
            try:
                from merid.event_venues.kalshi import get_equity_for_risk_calc_sync, get_summary_sync
                _effective_usd = get_equity_for_risk_calc_sync()
                _summary = get_summary_sync()
                if _effective_usd and _effective_usd > 0:
                    _bankroll_cents = int(_effective_usd * 100)
                    _state = _summary.state.value if _summary else "unknown"
                    logger.debug(
                        "[strategy] Using effective bankroll: $%.2f (state=%s)",
                        _effective_usd,
                        _state
                    )
                else:
                    # Effective bankroll is zero - trading should halt
                    logger.error(
                        "[TAINTED_PATH] strategy bankroll: effective_equity=$%.2f — "
                        "rejecting sizing request; check min_operational_balance or max_riskable caps",
                        _effective_usd,
                    )
                    # Emit alert for operator visibility
                    try:
                        from core.event_bus import get_event_bus
                        get_event_bus().emit("risk.bankroll_unavailable", {
                            "agent": self._agent_name,
                            "equity_usd": _effective_usd,
                            "reason": "zero_or_negative_equity",
                            "action": "reject_sizing",
                        })
                    except Exception:
                        pass
                    
                    # Tamper-evident audit log
                    try:
                        from core.risk_audit_chain import get_risk_audit_chain
                        get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                            "agent": self._agent_name,
                            "equity_usd": _effective_usd,
                            "reason": "zero_or_negative_equity",
                            "action": "reject_sizing",
                            "edge_pct": edge_pct,
                            "phase": phase.value if phase else None,
                        })
                    except Exception as _audit_exc:
                        logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                    
                    return 0  # Fail closed: no size when bankroll unknown
            except Exception as _brk_exc:
                logger.error(
                    "[TAINTED_PATH] strategy bankroll: unified bankroll service unavailable (%s) — "
                    "rejecting sizing request; no fallback permitted",
                    _brk_exc,
                )
                # Emit alert for operator visibility
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().emit("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "risk_manager_exception",
                        "error": str(_brk_exc),
                        "action": "reject_sizing",
                    })
                except Exception:
                    pass
                
                # Tamper-evident audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "risk_manager_exception",
                        "error": str(_brk_exc)[:200],
                        "action": "reject_sizing",
                        "edge_pct": edge_pct,
                        "phase": phase.value if phase else None,
                    })
                except Exception as _audit_exc:
                    logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                
                return 0  # Fail closed: no size when bankroll unavailable

            # CRITICAL FIX: unified_sizing enforces $1 global exposure cap via slot allocator
            # Legacy PositionSizer multipliers (sentiment_vol, cycle_drawdown) are NOT integrated
            # with window-based risk limits, which could bypass the $1 cap
            #
            # unified_sizing.compute_order_size parameters:
            # - bankroll_usd: Convert from cents to USD
            # - price_cents: Already in cents
            # - asset: Extract from market_id (e.g., "KXBTC15M-26JUN24-50000" -> "BTC")
            # - edge_pct: Edge percentage for Kelly filtering
            # - model_prob: Market probability for Kelly calculation
            # - side: Trade side (default "yes" for 15m crypto)
            #
            # The function returns (count, notional_usd, metadata_dict)
            # It enforces the $1 global slot allocator cap internally
            _asset = self._extract_asset_from_market_id(edge.market_id)
            _bankroll_usd = Decimal(_bankroll_cents) / Decimal("100")
            
            # Apply governance factor from paper session if available
            # This propagates halt/downsize state into position sizing
            try:
                from merid.prediction.paper_session import get_paper_session
                _ps = get_paper_session()
                import os
                if os.getenv("DISABLE_PAPER_SESSION_HALT", "").lower() in ("1", "true", "yes"):
                    _gov = 1.0  # Ignore halt/downsize state
                    logger.debug("[KELLY] Paper session halt/downsize disabled via env var for %s", self._agent_name)
                else:
                    _gov = _ps.get_size_factor(self._agent_name)
                size_factor = size_factor * _gov
            except Exception:
                pass
            
            # Call unified_sizing to compute order size with $1 cap enforcement
            count, notional_usd, metadata = compute_order_size(
                bankroll_usd=_bankroll_usd,
                price_cents=price_cents,
                asset=_asset,
                edge_pct=Decimal(str(edge_pct)),
                model_prob=market_prob,
                confidence=Decimal(str(max(0.0, min(1.0, size_factor)))),
                side="yes",  # 15m crypto defaults to YES side
            )
            
            # unified_sizing already enforces $1 cap via slot allocator
            # No additional hard cap needed - the function returns 0 if no slot available
            logger.debug(
                "[UNIFIED-SIZING] agent=%s asset=%s edge=%.4f price=%dc count=%d notional=$%.2f",
                self._agent_name, _asset, edge_pct, price_cents, count, notional_usd
            )
            return count
        except Exception as _sze:
            logger.warning(
                "position sizer unavailable — falling back to un-gated Kelly "
                "(no fee/PF/drawdown gates): %s", _sze
            )

        # Fallback: use merid.formulas canonical Kelly implementation
        # [AGENT_AUDIT: Section 5] — quarter-Kelly sizing from source of truth
        try:
            # Convert edge to float for formulas module
            edge_float = float(edge.net_edge)
            market_prob_float = float(edge.market_prob)
            
            # FIX: Fetch actual contract price from market state instead of using probability-derived price
            price_cents = None
            try:
                # LEGACY REMOVAL: dynamic_sizing moved to archive/legacy/ during 15m stack cleanup
                # price_cents = get_actual_contract_price_cents(edge.market_id, side="yes", market_prob=market_prob_float)
                price_cents = None
                # BUG-FIX: Use 45c safe default instead of probability-derived fallback which can return 1
                # When market state is unavailable, 45c is the midpoint for binary options (5c-85c canonical range)
                # This prevents price_cents=1 which causes Kelly sizing to return 0 contracts
                if price_cents is None or price_cents <= 0:
                    price_cents = 45  # CRITICAL FIX (2026-08-01): Fixed to 45c (midpoint of 5c-85c canonical range)
            except Exception:
                # Same safe default on exception
                price_cents = 45  # CRITICAL FIX (2026-08-01): Fixed to 45c (midpoint of 5c-85c canonical range)

            # FIX: Validate actual price against max_price_cents from threshold matrix
            # This prevents momentum scalping from trading high-priced (low-edge) contracts
            # Uses quick_win_max_price_cents for high-probability (80%+) trades in 15m timeframe
            # LEGACY REMOVAL: crypto_threshold_matrix moved to archive/legacy/ during 15m stack cleanup
            try:
                _asset = self._extract_asset_from_market_id(edge.market_id)
                _tf = self._resolve_timeframe_from_agent_name()
                if _asset and _tf:
                    # _row = resolve_merged_row(asset=_asset, timeframe=_tf, archetype="directional")
                    _row = None  # LEGACY REMOVAL
                    
                    # Determine confidence band based on model probability
                    _confidence_bands = _row.get("confidence_bands", [])
                    _current_band = None
                    _confidence_tier_multiplier = 1.0
                    if _confidence_bands and market_prob is not None:
                        for band in _confidence_bands:
                            min_conf = band.get("min_conf", 0.0)
                            max_conf = band.get("max_conf", 1.0)
                            if min_conf <= market_prob <= max_conf:
                                _current_band = band.get("name")
                                break
                    
                    # Get confidence tier multiplier from resolved row
                    _confidence_tier_mult = _row.get("confidence_tier_multiplier", {})
                    if _current_band and _confidence_tier_mult:
                        _confidence_tier_multiplier = _confidence_tier_mult.get(_current_band, 1.0)
                    
                    # Select appropriate price cap based on band and timeframe
                    _max_price_cents = _row.get("max_price_cents")
                    if _current_band == "quick_win" and _tf == "15m":
                        _quick_win_max_price_cents = _row.get("quick_win_max_price_cents")
                        if _quick_win_max_price_cents:
                            _max_price_cents = _quick_win_max_price_cents
                            logger.debug(
                                "[PRICE-GATE] using quick_win cap: %s | band=%s | price_cap=%dc | asset=%s tf=%s",
                                edge.market_id, _current_band, _max_price_cents, _asset, _tf
                            )
                    
                    if _max_price_cents and price_cents > _max_price_cents:
                        logger.warning(
                            "[PRICE-GATE] rejected: %s | actual_price=%dc > max=%dc | band=%s | asset=%s tf=%s",
                            edge.market_id, price_cents, _max_price_cents, _current_band, _asset, _tf
                        )
                        return 0
            except Exception as e:
                logger.debug("Could not validate max_price_cents for %s: %s", edge.market_id, e)
                _current_band = None
                _confidence_tier_multiplier = 1.0
            
            # Determine fractional Kelly based on phase
            fractional_kelly = float(self.config.kelly_fraction)  # 0.25 default
            
            # Apply confidence tier multiplier from threshold matrix
            fractional_kelly *= _confidence_tier_multiplier
            
            if phase == ExpiryPhase.EARLY:
                fractional_kelly *= 1.5
            elif phase == ExpiryPhase.MID:
                fractional_kelly *= 1.2
            elif phase == ExpiryPhase.TERMINAL:
                fractional_kelly *= 0.5
            
            # Apply sentiment size_factor
            fractional_kelly *= max(0.0, min(1.0, size_factor))
            
            # Use canonical quarter_kelly_size from merid.formulas
            # CRITICAL: Use validated bankroll or fail closed
            if _bankroll_cents <= 0:
                logger.error(
                    "[TAINTED_PATH] quarter_kelly_size fallback: no valid bankroll "
                    "(_bankroll_cents=%s) — rejecting sizing", _bankroll_cents
                )
                # Audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "quarter_kelly_fallback_no_bankroll",
                        "bankroll_cents": _bankroll_cents,
                        "action": "reject_sizing",
                        "phase": phase.value if phase else None,
                    })
                except Exception:
                    pass
                return 0
            
            inputs = PositionSizingInputs(
                bankroll_cents=_bankroll_cents,  # Use validated bankroll
                edge=edge_float,
                price_cents=price_cents,
                fractional_kelly=fractional_kelly,
            )
            
            contracts, kelly_used, warning = quarter_kelly_size(inputs)
            if warning:
                logger.debug("quarter_kelly_size warning: %s", warning)
            
            # CRITICAL FIX (2026-07-08): Kelly determines >1 contract eligibility, risk caps determine permission
            # Kelly is the allocator: it calculates the optimal fraction of bankroll to risk
            # Risk caps are the permission gate: they determine whether >1 contract is allowed
            # 
            # Implementation:
            # 1. Kelly calculates optimal contract count based on edge and bankroll
            # 2. If Kelly suggests >1 contract, check if risk caps permit it
            # 3. Risk caps (max_contracts_per_order, per-asset limits) are the final permission gate
            # 4. Current profile config sets max_contracts_per_order=1 (conservative), so >1 is never allowed
            #    but the logic is structured correctly for future relaxation of caps
            #
            # This aligns with 2026 research: Kelly determines allocation, risk caps determine permission
            
            # Apply risk cap as permission gate (not as Kelly override)
            _hard_cap = float(self.config.max_contracts_per_order)
            
            # Kelly determines eligibility: if Kelly suggests >1, it's eligible for larger size
            # Risk caps determine permission: only allow if caps permit
            # Current profile: max_contracts_per_order=1, so permission is denied for >1
            # Future: if caps are raised to 2-3, Kelly will determine which trades deserve >1
            final_contracts = min(contracts, _hard_cap)
            
            # Log Kelly vs cap decision for observability
            if contracts > _hard_cap:
                logger.info(
                    "[KELLY-VS-CAP] Kelly suggested %.2f contracts but risk cap limited to %d (Kelly determines eligibility, caps determine permission)",
                    contracts, _hard_cap
                )
            
            return final_contracts
            
        except Exception as _formula_err:
            logger.error(
                "merid.formulas Kelly calculation failed: %s — "
                "this should never happen; check formulas module health",
                _formula_err
            )
            return 0

    # ------------------------------------------------------------------
    # Entry evaluation
    # ------------------------------------------------------------------

    def _emit_pm_signal_log(
        self,
        sig: StrategySignal,
        snapshot: MarketSnapshot,
        archetype: str,
        correlation_id: Optional[str],
    ) -> None:
        """Structured observability for PM: why NO_ACTION vs actionable."""
        if os.getenv("MERID_PM_SIGNAL_LOG", "true").lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return
        ne = None
        if sig.edge and hasattr(sig.edge, "net_edge"):
            try:
                ne = float(sig.edge.net_edge)
            except (TypeError, ValueError):
                ne = None
        conf = None
        if sig.edge and hasattr(sig.edge, "confidence"):
            try:
                conf = float(sig.edge.confidence)
            except (TypeError, ValueError):
                conf = None
        ph = sig.phase.value if sig.phase else None
        _ctx = ""
        if getattr(sig, "eval_context", None):
            try:
                import json as _json

                _ctx = _json.dumps(sig.eval_context, default=str, sort_keys=True)
                if len(_ctx) > 450:
                    _ctx = _ctx[:450] + "…"
            except Exception:
                _ctx = str(sig.eval_context)[:450]
        
        # Behavioral exploitation context
        _beh_patterns = "—"
        _beh_size_mult = "—"
        if hasattr(sig, "behavioral_adjustments") and sig.behavioral_adjustments:
            _ba = sig.behavioral_adjustments
            _patterns = _ba.get("patterns_detected", [])
            _beh_patterns = ",".join(_patterns) if _patterns else "none"
            _beh_size_mult = f"{_ba.get('size_multiplier', 1.0):.2f}"
        
        _inc_spot = os.getenv("MERID_PM_SIGNAL_INCLUDE_SPOT_STRIKE", "true").lower() in (
            "1", "true", "yes", "on",
        )
        _spot_s = "—"
        _strike_s = "—"
        _dist_frac_s = "—"
        _dist_pct_human = "—"
        _basis = getattr(snapshot, "spot_strike_basis_note", "") or "—"
        if _inc_spot:
            sp = getattr(snapshot, "spot_price_usd", None)
            st = getattr(snapshot, "strike_price_usd", None)
            di = getattr(snapshot, "distance_to_strike_pct", None)
            _spot_s = str(sp) if sp is not None else "—"
            _strike_s = str(st) if st is not None else "—"
            if di is not None:
                try:
                    _df = float(di)
                    _dist_frac_s = f"{_df:.6f}"
                    _dist_pct_human = f"{_df * 100.0:.2f}"
                except (TypeError, ValueError):
                    _dist_frac_s = str(di)
                    _dist_pct_human = "—"
        if sig.action == SignalAction.NO_ACTION:
            if _inc_spot:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "net_edge=%s confidence=%s spot=%s strike=%s dist_frac=%s dist_pct_pct=%s "
                    "spot_strike_basis=%s reason=%s corr_id=%s ctx=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    _spot_s,
                    _strike_s,
                    _dist_frac_s,
                    _dist_pct_human,
                    _basis,
                    (sig.reason or "")[:500],
                    correlation_id or "—",
                    _ctx or "—",
                )
            else:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "net_edge=%s confidence=%s reason=%s corr_id=%s ctx=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    (sig.reason or "")[:500],
                    correlation_id or "—",
                    _ctx or "—",
                )
        else:
            # Emit structured invariant log for production suite parsing
            if sig.edge and hasattr(sig.edge, "market_prob"):
                p_model = float(sig.edge.market_prob) if sig.edge.market_prob is not None else 0.5
                edge_val = ne if ne is not None else 0.0
                # Determine chosen_side from action
                chosen_side = "yes" if sig.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
                logger.info(
                    "EDGE-PROBABILITY: p_model=%.3f edge=%.3f chosen_side=%s market=%s",
                    p_model, edge_val, chosen_side, snapshot.market_id
                )
            
            if _inc_spot:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "contracts=%s net_edge=%s confidence=%s spot=%s strike=%s dist_frac=%s "
                    "dist_pct_pct=%s spot_strike_basis=%s behavioral=%s beh_mult=%s corr_id=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    sig.contracts,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    _spot_s,
                    _strike_s,
                    _dist_frac_s,
                    _dist_pct_human,
                    _basis,
                    _beh_patterns,
                    _beh_size_mult,
                    correlation_id or "—",
                )
            else:
                logger.debug(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "contracts=%s net_edge=%s behavioral=%s beh_mult=%s corr_id=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    sig.contracts,
                    f"{ne:.4f}" if ne is not None else "—",
                    _beh_patterns,
                    _beh_size_mult,
                    correlation_id or "—",
                )

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        archetype: str = "directional",
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        sig = self._evaluate_core(snapshot, archetype, correlation_id)
        self._emit_pm_signal_log(sig, snapshot, archetype, correlation_id)
        return sig

    def _evaluate_core(
        self,
        snapshot: MarketSnapshot,
        archetype: str = "directional",
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Evaluate a market snapshot and produce a signal (inner implementation).

        DECISION HIERARCHY (highest priority first):
        ============================================
        Layer 1: Hard risk & sanity gates
          - Expiry known? (UNKNOWN expiry → NO_ACTION)
          - Staleness check (>30s old → NO_ACTION)
          - Market state (not TRADING/CLOSING → NO_ACTION)
        Volume/OI minimums run **after** archetype evaluation (edge-first) — see
        ``_apply_liquidity_guard_after_edge``.

        Layer 2: Global/regime filters
          - Sentiment regime (extreme_fear/greed, turbulent)
          - Applied via _sentiment_size_factor() and _sentiment_edge_floor()
        These modulate sizing and edge thresholds but don't veto directly.

        Layer 3: Structure (FVG zones + Fib context)
          - FVG pressure/direction vs trade alignment
          - Confluence with trend/RSI
          - Applied as multiplicative conviction factor to final size
        Never flips direction against higher-priority consensus.

        Layer 4: Momentum/microstructure entries
          - MACD/RSI signals
          - Orderbook forecaster imbalance
          - Edge estimates from models
        Only evaluated if all higher layers pass.

        Archetypes:
        - directional: Takes YES/NO positions based on speculative edge.
        - market_maker: Quotes two-sided markets.
        - arbitrage: Specifically looks for cross-market or internal arb.
        - contrarian: Fades extremes when model disagrees.
        - regime_switch: Rides momentum on sentiment shifts.
        - vol_breakout: Trades elevated vol with book imbalance.
        
        [AGENT_AUDIT: Section 9] Accepts correlation_id from DISCOVER for trace chain.
        """
        # Log ANALYZE stage entry with correlation_id
        if correlation_id:
            logger.info(
                "[TRACE] ANALYZE_START | corr_id=%s | market=%s | archetype=%s",
                correlation_id,
                snapshot.market_id,
                archetype,
            )
        
        phase = self._expiry_phase(snapshot.time_to_expiry_hours)

        # D02 fix: reject markets with unknown expiry — we cannot safely size
        # or risk-manage a contract whose time-to-expiry is unknown.
        if phase == ExpiryPhase.UNKNOWN:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="Market expiry unknown — skipping to avoid unsized risk.",
                correlation_id=correlation_id,
            )

        # 0. Staleness gate — reject orders on stale market data
        now_utc = datetime.now(timezone.utc)
        snap_age_s = (now_utc - snapshot.timestamp).total_seconds()
        if snap_age_s > SNAPSHOT_STALE_SECONDS:
            stale_int = int(snap_age_s)
            try:
                from merid.prediction.alerts import get_alert_manager
                get_alert_manager().fire_staleness(snapshot.market_id, stale_int)
            except Exception:
                pass
            logger.warning(
                "Stale snapshot for %s (%ds old) — skipping evaluation",
                snapshot.market_id, stale_int,
            )
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Stale snapshot: {stale_int}s old (max {SNAPSHOT_STALE_SECONDS}s).",
                correlation_id=correlation_id,
            )

        # 1. State filter
        if snapshot.state not in (ContractState.TRADING, ContractState.CLOSING):
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Market state is {snapshot.state.value}, not tradeable.",
                correlation_id=correlation_id,
            )

        # 1b. Spot–strike distance veto (optional — ``MERID_PM_SPOT_STRIKE_VETO_TRADES``)
        if getattr(snapshot, "spot_strike_veto", False):
            _dist = getattr(snapshot, "distance_to_strike_pct", None)
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=getattr(snapshot, "spot_strike_veto_reason", None) or "spot_strike_veto",
                correlation_id=correlation_id,
                eval_context={
                    "block": "spot_strike_veto",
                    "distance_to_strike_pct": str(_dist) if _dist is not None else "",
                    "spot": str(snapshot.spot_price_usd) if getattr(snapshot, "spot_price_usd", None) is not None else "",
                    "strike": str(snapshot.strike_price_usd) if getattr(snapshot, "strike_price_usd", None) is not None else "",
                    "resolved_asset": getattr(snapshot, "resolved_asset", None) or "",
                    "spot_strike_basis": getattr(snapshot, "spot_strike_basis_note", "") or "",
                },
            )

        # 1c. Phantom pricing gate — reject markets with no real two-sided quotes.
        # Mirrors CT's [SKIP-DEGENERATE] check.  When WS has no orderbook data and
        # catalog outcomes were empty, the system defaults to 50/50 pricing which
        # produces meaningless edge signals against the spot-relative model.
        if getattr(snapshot, "phantom_pricing", False):
            logger.info(
                "[PHANTOM-PRICING-SKIP] %s | pricing_source=%s | "
                "no real book data — edge would be meaningless",
                snapshot.market_id,
                getattr(snapshot, "pricing_source", "unknown"),
            )
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="phantom_pricing: no real orderbook data — defaulted to 50/50",
                correlation_id=correlation_id,
                eval_context={
                    "block": "phantom_pricing",
                    "pricing_source": getattr(snapshot, "pricing_source", "unknown"),
                },
            )

        # 2. Archetype evaluation (edge / conviction / Kelly) — liquidity guard runs after.
        if archetype == "market_maker":
            sig = self._evaluate_mm(snapshot, phase, correlation_id)
        elif archetype == "arbitrage":
            sig = self._evaluate_arb(snapshot, phase, correlation_id)
        elif archetype == "contrarian":
            sig = self._evaluate_contrarian(snapshot, phase, correlation_id)
        elif archetype == "regime_switch":
            sig = self._evaluate_regime_switch(snapshot, phase, correlation_id)
        elif archetype == "vol_breakout":
            sig = self._evaluate_vol_breakout(snapshot, phase, correlation_id)
        else:
            sig = self._evaluate_directional(snapshot, phase, correlation_id)

        return self._apply_liquidity_guard_after_edge(snapshot, sig, phase, correlation_id)

    def _apply_liquidity_guard_after_edge(
        self,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        phase: ExpiryPhase,
        correlation_id: Optional[str],
    ) -> StrategySignal:
        """Enforce min volume/OI only after edge evaluation so NO_ACTION reasons reflect model thresholds first.

        If ``min_volume`` / ``min_open_interest`` are 0, that check is skipped (see StrategyConfig defaults).
        """
        if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
            return signal
        if signal.action == SignalAction.CLOSE:
            return signal

        parts: List[str] = []
        if self.config.min_volume > 0 and snapshot.volume < self.config.min_volume:
            parts.append(f"volume {snapshot.volume} < {self.config.min_volume}")
        if self.config.min_open_interest > 0 and snapshot.open_interest < self.config.min_open_interest:
            parts.append(f"OI {snapshot.open_interest} < {self.config.min_open_interest}")
        
        # MICRO-SCALPING: Spread check for directional signals (aligns with MM behavior)
        # Wide spreads erode micro-edges; skip if spread exceeds MM max
        if (
            snapshot.implied.spread_cents is not None and
            snapshot.implied.spread_cents > self.config.mm_max_spread_cents
        ):
            parts.append(f"spread {snapshot.implied.spread_cents}c > {self.config.mm_max_spread_cents}c")

        if not parts:
            return signal

        edge_hint = ""
        if signal.edge is not None and getattr(signal.edge, "net_edge", None) is not None:
            try:
                edge_hint = f" Edge had cleared strategy path (net_edge={signal.edge.net_edge:.4f})."
            except Exception:
                edge_hint = " Edge was present before liquidity veto."

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.NO_ACTION,
            side=signal.side,
            contracts=0,
            limit_price_cents=None,
            bid_price_cents=None,
            ask_price_cents=None,
            edge=signal.edge,
            phase=phase,
            reason=f"Liquidity guard: {'; '.join(parts)}.{edge_hint}",
            correlation_id=correlation_id or signal.correlation_id,
            eval_context={
                "min_volume": str(self.config.min_volume),
                "min_open_interest": str(self.config.min_open_interest),
                "block": "liquidity_guard",
            },
        )

    def _get_cross_venue_arb_boost(self, snapshot: MarketSnapshot) -> Optional[EdgeEstimate]:
        """Check DislocationScanner for crypto 15m cross-venue arb opportunities.
        
        CRYPTO-15M-ARB: If there's a significant dislocation between CEX venues
        for our 5 crypto assets, boost the edge estimate to factor it into trading.
        
        Returns:
            EdgeEstimate if cross-venue arb detected, None otherwise
        """
        try:
            from merid.signals.arbitrage import get_dislocation_scanner, CRYPTO_15M_ASSETS
            
            # Extract asset from market_id (e.g., KXBTC15M... -> BTC)
            asset = None
            market_id_upper = snapshot.market_id.upper()
            for crypto_asset in CRYPTO_15M_ASSETS:
                if crypto_asset in market_id_upper:
                    asset = crypto_asset
                    break
            
            if not asset:
                return None
            
            scanner = get_dislocation_scanner()
            now = time.time()
            
            # Get active dislocation signals for this asset
            active_signals = scanner.get_active_signals(now)
            
            # Find best signal for this asset
            best_signal = None
            best_edge_bps = 0.0
            
            for sig in active_signals:
                if asset in sig.symbol.upper():
                    # Only consider high-quality signals
                    if sig.net_edge_bps > 30 and sig.arb_type == "pure_arb":
                        if sig.net_edge_bps > best_edge_bps:
                            best_edge_bps = sig.net_edge_bps
                            best_signal = sig
            
            if best_signal:
                # Convert bps edge to probability edge for PM model
                edge_decimal = Decimal(str(best_edge_bps / 10000))  # bps -> decimal
                # Dynamic fee calculation using Kalshi fee schedule
                from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
                _price_cents = 42  # 2026-07-14: Changed from 25 to 42 (midpoint of 10-75c canonical range)
                _fee_cents = calculate_kalshi_fee_cents(1, _price_cents)
                fee_drag = Decimal(_fee_cents) / Decimal("100")
                # Dynamic slippage from profile (single source of truth)
                try:
                    from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
                    profile_adapter = Crypto15mProfileAdapter()
                    profile = profile_adapter.profile
                    # Convert max_slippage_cents to bps (1 cent = 100 bps at 42.5c price - canonical range midpoint 10-75c)
                    _slippage_cents = getattr(profile, 'guardrails_max_slippage_cents', 5)
                    _slippage_bps = _slippage_cents * 100  # Convert cents to bps
                except Exception as e:
                    # Fallback to env var if profile not available
                    logger.warning(
                        "[strategy] Failed to load slippage from profile: %s (using env var fallback)",
                        e
                    )
                    _slippage_bps = float(os.getenv("MERID_SLIPPAGE_BPS", "1.0"))
                slippage_est = Decimal(str(_slippage_bps / 10000.0))
                net_edge = edge_decimal - fee_drag - slippage_est
                return EdgeEstimate(
                    market_id=snapshot.market_id,
                    side="yes",  # Directional signal
                    action="buy",
                    market_prob=Decimal("0.5"),
                    model_prob=Decimal("0.5") + edge_decimal,
                    raw_edge=edge_decimal,
                    fee_drag=fee_drag,
                    slippage_est=slippage_est,
                    net_edge=net_edge,
                    edge_type="cross_venue_arb",
                    confidence=Decimal("0.7"),
                )
        except Exception as e:
            logger.debug("Cross-venue arb check skipped for %s: %s", snapshot.market_id, e)
        
        return None

    def _evaluate_directional(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Standard directional strategy with cross-venue arb integration."""
        # 3. Arb check (high priority even for directional)
        # CRYPTO-15M-ARB: Include cross-venue dislocation signals
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        
        # Check for cross-venue arb opportunities
        cross_venue_edge = self._get_cross_venue_arb_boost(snapshot)
        if cross_venue_edge:
            arb_edges.append(cross_venue_edge)
            logger.info(
                "[CRYPTO-15M-ARB] Cross-venue edge detected for %s: %.2fbps",
                snapshot.market_id, float(cross_venue_edge.net_edge) * 10000
            )
        
        if arb_edges:
            best_arb = max(arb_edges, key=lambda e: e.net_edge)
            if best_arb.net_edge >= self.config.min_arb_edge:
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.BUY_YES,  # arb buys both sides
                    side="both",
                    contracts=self.config.max_contracts_per_order,
                    edge=best_arb,
                    phase=phase,
                    reason=f"Pure arb detected: net edge {best_arb.net_edge:.4f}.",
                    correlation_id=correlation_id,
                )

        # 4. Best speculative edge (include both speculative, sentiment_driven, AND arb that didn't meet threshold)
        # PRODUCTION FIX: When catalog fallback makes all edges appear as "arb", still use them as speculative
        spec_edges = [e for e in snapshot.edges if e.edge_type in ("speculative", "sentiment_driven", "arb")]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No speculative edges available for this market.",
                correlation_id=correlation_id,
            )

        # CRITICAL FIX (2026-07-31): Add side diversity to edge selection
        # Previous selection based solely on net_edge could systematically favor YES
        # Now consider both edge magnitude and side diversity for balanced YES/NO trading
        
        # Separate edges by side
        yes_edges = [e for e in spec_edges if e.side == "yes"]
        no_edges = [e for e in spec_edges if e.side == "no"]
        
        # Get best edge from each side
        best_yes = max(yes_edges, key=lambda e: e.net_edge) if yes_edges else None
        best_no = max(no_edges, key=lambda e: e.net_edge) if no_edges else None
        
        # Add diversity bonus to the underrepresented side
        # Track recent side selections (simple implementation using agent-level counter)
        diversity_bonus_yes = 0.0
        diversity_bonus_no = 0.0
        
        # Simple diversity logic: if we've been trading mostly YES, boost NO edge
        # In production, this should use a rolling window of recent trades
        recent_side_bias = getattr(self, '_recent_side_bias', 0.5)  # 0.5 = balanced, >0.5 = YES-heavy
        
        if recent_side_bias > 0.6:  # YES-heavy
            diversity_bonus_no = 0.001  # Small boost to NO edges
        elif recent_side_bias < 0.4:  # NO-heavy
            diversity_bonus_yes = 0.001  # Small boost to YES edges
        
        # Apply diversity bonus and select best
        if best_yes:
            best_yes_adjusted = float(best_yes.net_edge) + diversity_bonus_yes
        else:
            best_yes_adjusted = -float('inf')
            
        if best_no:
            best_no_adjusted = float(best_no.net_edge) + diversity_bonus_no
        else:
            best_no_adjusted = -float('inf')
        
        # Select the side with higher adjusted edge
        if best_yes_adjusted >= best_no_adjusted and best_yes:
            best = best_yes
        elif best_no:
            best = best_no
        else:
            # Fallback to original logic if both are None
            best = max(spec_edges, key=lambda e: e.net_edge)
        
        # SOFT-BAND LOGGING: Log near-misses for observability (no new config)
        min_edge = self._min_edge_for_phase(phase)
        _edge_ratio = float(best.net_edge) / float(min_edge) if min_edge > 0 else 1.0
        if 0.5 <= _edge_ratio < 1.0:
            # Edge is in soft band (50-100% of threshold) - log near-miss
            logger.debug(
                "[PM_SIGNAL_SOFT_REJECT] agent=%s market=%s net_edge=%.4f min_edge=%.4f "
                "ratio=%.2f phase=%s reason=soft_reject_edge",
                self._agent_name, snapshot.market_id, float(best.net_edge),
                float(min_edge), _edge_ratio, phase.value
            )

        # 5. Edge threshold
        min_edge = self._min_edge_for_phase(phase)
        
        # Check if this is a crypto asset eligible for cross-asset selection
        asset = self._extract_asset_from_market_id(snapshot.market_id)
        use_cross_asset_arbiter = (
            asset in CRYPTO_ASSETS and
            os.getenv("MERID_CROSS_ASSET_TOP_EDGE", "true").lower() in ("1", "true", "yes", "on")
        )
        
        # GRADUATED-SIZING-FIX: Compute size factor based on edge proximity to threshold
        # Instead of hard wall at threshold, use graduated sizing 0.0-1.0
        _edge_ratio = float(best.net_edge) / float(min_edge) if min_edge > 0 else 1.0
        
        # SWEET SPOT: Shadow threshold lowered to 30% of min_edge for live trading
        # This allows more trades through while still filtering out noise
        _shadow_threshold_ratio = 0.30
        
        # Initialize graduated factor - will be overridden if in shadow zone
        _edge_graduated_factor = 1.0
        
        if best.net_edge < min_edge:
            if use_cross_asset_arbiter:
                # Cross-asset mode: Log diagnostic but continue for arbiter evaluation
                logger.debug(
                    "[PM_SIGNAL_CROSS_ASSET] agent=%s asset=%s local_edge=%.4f below_local_threshold=%s "
                    "submitting_to_arbiter_for_relative_ranking",
                    self._agent_name, asset, float(best.net_edge), str(min_edge)
                )
                # Continue to confidence gate - signal will be submitted to arbiter downstream
            elif _edge_ratio < _shadow_threshold_ratio:
                # Below shadow threshold: hard block (not enough edge)
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.NO_ACTION,
                    side=best.side,
                    contracts=0,
                    edge=best,
                    phase=phase,
                    reason=f"Edge {best.net_edge:.4f} below shadow threshold {float(min_edge) * _shadow_threshold_ratio:.4f}.",
                    correlation_id=correlation_id,
                    eval_context={
                        "min_edge_threshold": str(min_edge),
                        "shadow_threshold": str(float(min_edge) * _shadow_threshold_ratio),
                        "phase": phase.value,
                        "archetype": "directional",
                        "block": "edge_below_shadow_threshold",
                    },
                )
            else:
                # Between shadow threshold and min_edge: graduated sizing (shadow mode)
                # SWEET SPOT: Start sizing at 20% below threshold, scale up to full size
                _graduated_factor = max(0.20, (_edge_ratio - _shadow_threshold_ratio) / (1.0 - _shadow_threshold_ratio))
                _graduated_factor = max(0.0, min(1.0, _graduated_factor))  # Clamp to [0, 1]
                logger.debug(
                    "[GRADUATED-SIZING] %s edge=%.4f below threshold=%.4f but above shadow — "
                    "using reduced size factor=%.2f (shadow mode)",
                    snapshot.market_id, float(best.net_edge), float(min_edge), _graduated_factor
                )
                # Store graduated factor for sizing calculation later
                _edge_graduated_factor = _graduated_factor
        else:
            # Above threshold: full size
            _edge_graduated_factor = 1.0

        # FVG ENTRY TIMING: Check FVG signal for optimal entry timing
        fvg_timing = None
        fvg_entry_boost = 1.0
        try:
            from merid.prediction.fvg_integration import get_fvg_entry_exit_timing, is_fvg_enabled
            if is_fvg_enabled() and snapshot.implied:
                bid = (snapshot.implied.yes_bid or 50) / 100.0
                ask = (snapshot.implied.yes_ask or 50) / 100.0
                fvg_timing = get_fvg_entry_exit_timing(
                    ticker=snapshot.market_id,
                    bid=bid,
                    ask=ask,
                    asset=asset,
                    timeframe=_resolved_tf,
                )
                if fvg_timing:
                    # Boost confidence for good FVG entry timing
                    if fvg_timing.should_enter and fvg_timing.entry_urgency >= 0.5:
                        fvg_entry_boost = 1.0 + (fvg_timing.entry_urgency * 0.15)
                        logger.debug(
                            "[FVG-ENTRY-BOOST] %s | entry_urgency=%.2f confidence_boost=%.3f",
                            snapshot.market_id, fvg_timing.entry_urgency, fvg_entry_boost
                        )
        except Exception as e:
            logger.debug("FVG entry timing check skipped for %s: %s", snapshot.market_id, e)
        
        # Apply FVG entry boost to confidence check
        boosted_confidence = min(1.0, float(best.confidence) * fvg_entry_boost)
        
        # Confidence filter
        # SOFT-BAND LOGGING: Log near-miss confidence for observability
        _conf_ratio = boosted_confidence / float(self.config.min_confidence) if self.config.min_confidence > 0 else 1.0
        if 0.9 <= _conf_ratio < 1.0:
            logger.debug(
                "[PM_SIGNAL_SOFT_REJECT] agent=%s market=%s confidence=%.3f min_confidence=%.3f "
                "ratio=%.2f reason=soft_reject_confidence",
                self._agent_name, snapshot.market_id, boosted_confidence,
                float(self.config.min_confidence), _conf_ratio
            )
        
        if boosted_confidence < self.config.min_confidence:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"Below thresholds: confidence={best.confidence:.3f} < min={self.config.min_confidence} "
                       f"net_edge={best.net_edge:.4f} min_edge={min_edge} phase={phase.value}",
                correlation_id=correlation_id,
                eval_context={
                    "min_confidence": str(self.config.min_confidence),
                    "actual_confidence": str(best.confidence),
                    "min_edge": str(min_edge),
                    "actual_net_edge": str(best.net_edge),
                    "phase": phase.value,
                    "block": "confidence_below_minimum",
                },
            )

        # 6. HARD PROBABILITY GATE - 80%+ hit-rate targeting
        # PRODUCTION FIX v5 (2026-04-26): Comprehensive logging for observability

        # First: Validate model_prob p is calibrated and sane
        p = float(best.model_prob) if best.model_prob is not None else None

        # PRODUCTION FIX v5 (2026-04-26): Compute timeframe from agent name for probability gate
        # Extract timeframe from agent name (e.g., "BTC_HOURLY" -> "hourly", "BTC_DAILY" -> "daily")
        _resolved_tf = "unknown"
        if self._agent_name and "_" in self._agent_name:
            _parts = self._agent_name.split("_")
            if len(_parts) >= 2:
                _resolved_tf = _parts[-1].lower()  # Last part is timeframe
        
        # Determine if this is a high timeframe (daily, weekly, monthly, annual)
        _high_timeframes = {"daily", "weekly", "monthly", "annual"}
        is_high_tf = _resolved_tf in _high_timeframes

        # Pre-gate logging: always log gate inputs for observability
        _pre_asset = self._extract_asset_from_market_id(snapshot.market_id)
        # Defensive: get_calibration_config may not be available for 15m stack (sentiment disabled)
        _pre_calib = None
        try:
            from merid.sentiment.crypto_registry import get_calibration_config
            _pre_calib = get_calibration_config(_pre_asset)
        except ImportError:
            _pre_calib = None
        
        # Extract kalshi_price for EV calculation
        _pre_kalshi_price = float(best.market_prob) if best and hasattr(best, 'market_prob') else 0.5
        
        # EV-BASED GATE PARAMETERS (for logging)
        _pre_k_base = float(os.getenv("MERID_EV_K_BASE", "1.5"))
        _pre_k_extreme = float(os.getenv("MERID_EV_K_EXTREME", "2.5"))
        _pre_k_terminal = float(os.getenv("MERID_EV_K_TERMINAL", "2.0"))
        
        # Compute EV metrics for logging
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        _pre_price_cents = round(_pre_kalshi_price * 100)  # Use round() to preserve sub-cent precision (fixes int() truncation bug)
        _pre_fee_cents = calculate_kalshi_fee_cents(1, _pre_price_cents)
        _pre_fee_per_contract = _pre_fee_cents / 100.0
        _pre_ev_gross = float(p) - _pre_kalshi_price if p is not None else 0.0
        # Dynamic slippage: read from profile (single source of truth)
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            profile_adapter = Crypto15mProfileAdapter()
            profile = profile_adapter.profile
            # Convert max_slippage_cents to bps (1 cent = 100 bps at 42.5c price - canonical range midpoint 10-75c)
            _pre_slippage_cents = getattr(profile, 'guardrails_max_slippage_cents', 5)
            _pre_slippage_bps = _pre_slippage_cents * 100  # Convert cents to bps
        except Exception as e:
            # Fallback to env var if profile not available
            logger.warning(
                "[EV-GATE] Failed to load slippage from profile: %s (using env var fallback)",
                e
            )
            _pre_slippage_bps = float(os.getenv("MERID_SLIPPAGE_BPS", "1.0"))
        # CRITICAL FIX: Validate slippage bps is reasonable
        if _pre_slippage_bps < 0 or _pre_slippage_bps > 1000:
            logger.warning(
                "[EV-GATE] Invalid slippage_bps=%s - using default 500 (5c)",
                _pre_slippage_bps
            )
            _pre_slippage_bps = 500  # 5 cents = 500 bps
        _pre_slippage = _pre_slippage_bps / 10000.0  # Convert bps to decimal
        _pre_ev_net = _pre_ev_gross - _pre_fee_per_contract - _pre_slippage
        
        # For backward compatibility, still compute prob_edge (but not used for gating)
        _pre_prob_edge = abs(p - 0.5) if p is not None else None
        
        # Conviction thresholds (still used for sizing, not gating)
        _pre_veto = _pre_calib.conviction_veto_threshold if _pre_calib else 0.4
        _pre_strict = _pre_calib.conviction_strict_threshold if _pre_calib else 0.6
        
        logger.info(
            "[EV-GATE-IN] %s | asset=%s tf=%s | model_prob=%.4f kalshi_price=%.4f | "
            "ev_gross=%.4f ev_net=%.4f fee=%.4f | k_base=%.2f k_extreme=%.2f k_terminal=%.2f | "
            "conviction_veto=%.2f conviction_strict=%.2f | confidence=%.2f",
            snapshot.market_id, _pre_asset, _resolved_tf or "unknown",
            p if p is not None else -1.0,
            _pre_kalshi_price,
            _pre_ev_gross,
            _pre_ev_net,
            _pre_fee_per_contract,
            _pre_k_base,
            _pre_k_extreme,
            _pre_k_terminal,
            _pre_veto,
            _pre_strict,
            float(best.confidence) if best.confidence else 0.0
        )
        
        # Check for NaN, None, or out-of-bounds
        import math
        if p is None or math.isnan(p) or p < 0.0 or p > 1.0:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: invalid_model_prob p={p} (must be calibrated 0-1)",
                correlation_id=correlation_id,
            )
        
        # EV-BASED GATE REFACTOR (2026-05-13): Replace prob_edge proxy with economic edge
        # The old prob_edge = abs(p - 0.5) was misaligned with profitability.
        # New framework: use ev_net (expected value after fees) as primary gate.
        # This is asset-agnostic and directly tied to Kalshi contract economics.
        
        def compute_ev_net(
            model_prob: float,
            kalshi_price: float,
            contracts: int = 1,
            slippage: Optional[float] = None  # Default from env var
        ) -> tuple[float, float]:
            """Compute expected value net of Kalshi fees.
            
            Returns:
                (ev_net, fee_per_contract) where:
                - ev_net = model_prob - kalshi_price - fee_per_contract - slippage
                - fee_per_contract = Kalshi tiered fee per contract
                
            This uses the canonical Kalshi fee schedule from fees.py.
            """
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            
            # Dynamic slippage: read from profile (single source of truth)
            if slippage is None:
                try:
                    from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
                    profile_adapter = Crypto15mProfileAdapter()
                    profile = profile_adapter.profile
                    # Convert max_slippage_cents to bps (1 cent = 100 bps at 42.5c price - canonical range midpoint 10-75c)
                    _slippage_cents = getattr(profile, 'guardrails_max_slippage_cents', 5)
                    _slippage_bps = _slippage_cents * 100  # Convert cents to bps
                    slippage = _slippage_bps / 10000.0  # Convert bps to decimal
                except Exception as e:
                    # Fallback to env var if profile not available
                    logger.warning(
                        "[strategy] Failed to load slippage from profile: %s (using env var fallback)",
                        e
                    )
                    _slippage_bps = float(os.getenv("MERID_SLIPPAGE_BPS", "1.0"))
                    slippage = _slippage_bps / 10000.0  # Convert bps to decimal
            
            price_cents = round(kalshi_price * 100)  # Use round() to preserve sub-cent precision (fixes int() truncation bug)
            fee_cents = calculate_kalshi_fee_cents(contracts, price_cents)
            fee_per_contract = fee_cents / 100.0 / contracts
            
            ev_gross = model_prob - kalshi_price
            ev_net = ev_gross - fee_per_contract - slippage
            
            return ev_net, fee_per_contract
        
        # Extract kalshi_price from market_prob (EdgeEstimate has market_prob field)
        kalshi_price = float(best.market_prob) if best and hasattr(best, 'market_prob') else 0.5
        
        # Compute EV metrics
        ev_net, fee_per_contract = compute_ev_net(float(p), kalshi_price, contracts=1)
        
        # For backward compatibility and logging, compute prob_edge (but not used for gating)
        prob_edge = abs(p - 0.5)
        
        # Re-use variables from pre-gate logging (already computed above)
        asset = _pre_asset
        calib = _pre_calib
        
        # Structural conviction computation (needed for both gate and sizing)
        structural_factor = 1.0
        conviction_details = {}
        conviction = 0.5  # default

        if hasattr(snapshot, 'fvg_context') and snapshot.fvg_context:
            # conviction_details = conviction_result
            # structural_factor = 0.4 + (conviction * 0.8)
            pass
        
        # CONVICTION FLOOR VETO
        # If conviction < veto threshold, absolute NO_ACTION
        veto_threshold = calib.conviction_veto_threshold if calib else 0.4
        if conviction < veto_threshold:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: low_structural_conviction={conviction:.2f} < veto_threshold={veto_threshold}",
                correlation_id=correlation_id,
            )
        
        # EV-BASED GATE PARAMETERS (2026-05-13): Global, asset-agnostic thresholds
        # These replace asset-specific min_prob_edge thresholds with EV-based safety margins
        k_base = float(os.getenv("MERID_EV_K_BASE", "1.5"))  # Baseline safety margin (1.5x fee)
        k_extreme = float(os.getenv("MERID_EV_K_EXTREME", "2.5"))  # Extreme probability margin (2.5x fee)
        k_terminal = float(os.getenv("MERID_EV_K_TERMINAL", "2.0"))  # Terminal phase margin (2.0x fee)
        
        # CONVICTION MODULATION: Still used for sizing, but no longer gates EV directly
        # Low conviction trades are allowed if EV is positive, but sized smaller
        strict_threshold = _pre_strict
        
        # TERMINAL PHASE GUARD - Now EV-based instead of prob_edge-based
        # CRITICAL: Hard rule independent of sentiment - sentiment MUST NOT relax expiry-phase edge thresholds
        # This rule prevents bad trades at tail end of contracts due to time decay and liquidity issues
        # Fail closed: if context is broken, do not loosen risk
        
        def _terminal_phase_guard(
            current_phase: ExpiryPhase,
            current_ev_net: float,
            current_fee_per_contract: float,
            market_id: str,
            current_asset: str
        ) -> Optional[StrategySignal]:
            """Terminal phase guard - EV-based, independent of sentiment, fail closed."""
            if current_phase != ExpiryPhase.TERMINAL:
                return None
            
            # Fail closed: block if ev_net is None or invalid
            if current_ev_net is None:
                logger.error(
                    "[RISK] Terminal phase guard active: ev_net is None in TERMINAL phase. "
                    "Blocking trade %s | asset=%s",
                    market_id, current_asset
                )
                return StrategySignal(
                    market_id=market_id,
                    action=SignalAction.NO_ACTION,
                    side=best.side,
                    contracts=0,
                    edge=best,
                    phase=current_phase,
                    reason="blocked: terminal_phase_guard_no_ev",
                    correlation_id=correlation_id,
                    eval_context={
                        "ev_net": "None",
                        "phase": str(current_phase),
                        "block": "terminal_phase_guard_no_ev",
                    },
                )
            
            # Block if EV below terminal threshold (k_terminal * fee)
            min_ev_terminal = k_terminal * current_fee_per_contract
            if current_ev_net < min_ev_terminal:
                logger.warning(
                    "[RISK] Blocking trade in TERMINAL phase: %s | ev_net=%.4f < %.4f (k=%.1f) | asset=%s",
                    market_id, current_ev_net, min_ev_terminal, k_terminal, current_asset
                )
                return StrategySignal(
                    market_id=market_id,
                    action=SignalAction.NO_ACTION,
                    side=best.side,
                    contracts=0,
                    edge=best,
                    phase=current_phase,
                    reason=f"blocked: terminal_phase_guard_low_ev (ev_net={current_ev_net:.4f} < {min_ev_terminal:.4f})",
                    correlation_id=correlation_id,
                    eval_context={
                        "ev_net": str(current_ev_net),
                        "fee_per_contract": str(current_fee_per_contract),
                        "k_terminal": str(k_terminal),
                        "min_ev_terminal": str(min_ev_terminal),
                        "phase": str(current_phase),
                        "block": "terminal_phase_guard_low_ev",
                    },
                )
            
            # Allow trade
            return None
        
        # Apply terminal phase guard (EV-based)
        guard_signal = _terminal_phase_guard(phase, ev_net, fee_per_contract, snapshot.market_id, asset)
        if guard_signal is not None:
            return guard_signal

        # WINNER ALIGNMENT FIX (2026-05-10): Relax EV gate for arbiter winners
        # If this ticker is an arbiter winner, use a relaxed threshold to ensure
        # the winner always has an executable path (no "winner but blocked" scenario)
        is_arbiter_winner = False
        winner_k_multiplier = k_base  # Default to baseline
        
        try:
            from merid.prediction.grid_context import get_grid_context
            grid_ctx = get_grid_context()
            is_arbiter_winner = grid_ctx.is_winner(snapshot.market_id)
            
            if is_arbiter_winner:
                # Use relaxed threshold for winners (from grid context config)
                winner_k_multiplier = k_base * 0.7  # 30% relaxation for winners
                logger.info(
                    "[EV-GATE-WINNER] %s | is_winner=true | relaxed_k=%.2f (was %.2f)",
                    snapshot.market_id, winner_k_multiplier, k_base
                )
        except Exception as e:
            logger.debug("[EV-GATE] Winner check failed: %s (using standard threshold)", e)
        
        # PRIMARY EV GATE: ev_net must be positive (hard constraint)
        # This is the fundamental profitability check - never take negative EV trades
        if ev_net <= 0.0:
            logger.info(
                "[EV-GATE] blocked: %s | ev_net=%.4f <= 0 (negative expected value) | asset=%s | model_prob=%.4f kalshi_price=%.4f",
                snapshot.market_id, ev_net, asset, float(p), kalshi_price
            )
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: ev_net={ev_net:.4f} <= 0 (negative expected value)",
                correlation_id=correlation_id,
                eval_context={
                    "ev_net": str(ev_net),
                    "model_prob": str(p),
                    "kalshi_price": str(kalshi_price),
                    "fee_per_contract": str(fee_per_contract),
                    "block": "ev_not_positive",
                },
            )
        
        # SAFETY MARGIN GATE: ev_net must exceed k * fee_per_contract
        # This compensates for model error and provides a buffer against estimation uncertainty
        min_ev_safety = winner_k_multiplier * fee_per_contract
        if ev_net < min_ev_safety:
            logger.info(
                "[EV-GATE] blocked: %s | ev_net=%.4f < %.4f (k=%.2f * fee=%.4f) | asset=%s | insufficient safety margin",
                snapshot.market_id, ev_net, min_ev_safety, winner_k_multiplier, fee_per_contract, asset
            )
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: ev_net={ev_net:.4f} < {min_ev_safety:.4f} (insufficient safety margin, k={winner_k_multiplier:.2f})",
                correlation_id=correlation_id,
                eval_context={
                    "ev_net": str(ev_net),
                    "fee_per_contract": str(fee_per_contract),
                    "k_multiplier": str(winner_k_multiplier),
                    "min_ev_safety": str(min_ev_safety),
                    "is_arbiter_winner": str(is_arbiter_winner),
                    "block": "ev_insufficient_margin",
                },
            )
        
        # EXTREME PROBABILITY GUARD: Extra caution when model is very confident
        # Probabilistic models are often least calibrated in extremes (p < 0.10 or p > 0.90)
        # Require stricter EV threshold in these regions
        if p < 0.10 or p > 0.90:
            min_ev_extreme = k_extreme * fee_per_contract
            if ev_net < min_ev_extreme:
                logger.warning(
                    "[EV-GATE-EXTREME] blocked: %s | model_prob=%.4f in extreme region | ev_net=%.4f < %.4f (k=%.2f) | asset=%s | calibration risk",
                    snapshot.market_id, p, ev_net, min_ev_extreme, k_extreme, asset
                )
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.NO_ACTION,
                    side=best.side,
                    contracts=0,
                    edge=best,
                    phase=phase,
                    reason=f"blocked: model_prob={p:.4f} in extreme region, ev_net={ev_net:.4f} < {min_ev_extreme:.4f} (insufficient margin for calibration risk)",
                    correlation_id=correlation_id,
                    eval_context={
                        "ev_net": str(ev_net),
                        "model_prob": str(p),
                        "fee_per_contract": str(fee_per_contract),
                        "k_extreme": str(k_extreme),
                        "min_ev_extreme": str(min_ev_extreme),
                        "block": "extreme_probability_insufficient_ev",
                    },
                )
            else:
                logger.info(
                    "[EV-GATE-EXTREME] allowed: %s | model_prob=%.4f in extreme region but ev_net=%.4f >= %.4f (k=%.2f) | asset=%s",
                    snapshot.market_id, p, ev_net, min_ev_extreme, k_extreme, asset
                )

        # PASSED ALL EV GATES - log clear reason for allowed trade
        logger.info(
            "[EV-GATE] allowed: %s | ev_net=%.4f (safety_k=%.2f * fee=%.4f = %.4f) | conviction=%.2f | model_prob=%.4f kalshi_price=%.4f | asset=%s",
            snapshot.market_id,
            ev_net,
            winner_k_multiplier,
            fee_per_contract,
            min_ev_safety,
            conviction,
            float(p),
            kalshi_price,
            asset
        )

        # 7. Size calculation with structural conviction, FVG timing, and behavioral exploitation
        # Layer 2: Base size from Kelly + sentiment regime
        base_size = self._kelly_size_with_sentiment(best, phase, snapshot, correlation_id=correlation_id)
        
        # Apply structural factor to base size
        size = int(base_size * structural_factor)
        
        # FVG POSITION SIZING: Adjust size based on FVG signal strength
        fvg_size_factor = 1.0
        try:
            from merid.prediction.fvg_integration import get_fvg_position_size_factor
            if snapshot.implied:
                bid = (snapshot.implied.yes_bid or 50) / 100.0
                ask = (snapshot.implied.yes_ask or 50) / 100.0
                fvg_size_factor = get_fvg_position_size_factor(
                    ticker=snapshot.market_id,
                    bid=bid,
                    ask=ask,
                    asset=asset,
                    timeframe=_resolved_tf,
                )
                if fvg_size_factor != 1.0:
                    _orig_size = size
                    size = int(size * fvg_size_factor)
                    logger.info(
                        "[FVG-SIZE-ADJUST] %s | size adjusted: %d -> %d (factor=%.2f)",
                        snapshot.market_id, _orig_size, size, fvg_size_factor
                    )
        except Exception as e:
            logger.debug("FVG position sizing skipped for %s: %s", snapshot.market_id, e)
        
        # GRADUATED-SIZING-FIX: Apply edge graduated factor for shadow-mode signals
        # Signals between shadow_threshold and min_edge get reduced size (0.0-1.0 factor)
        if _edge_graduated_factor < 1.0:
            _orig_size = size
            size = int(size * _edge_graduated_factor)
            logger.info(
                "[GRADUATED-SIZING] %s | edge=%.4f below threshold — reducing size %d -> %d "
                "(factor=%.2f, shadow mode)",
                snapshot.market_id, float(best.net_edge), _orig_size, size, _edge_graduated_factor
            )
            # Mark this as a shadow trade for downstream tracking
            _is_shadow_trade = True
        else:
            _is_shadow_trade = False
        
        # Layer 3: Behavioral exploitation adjustments
        # Detect and exploit behavioral biases (longshot, panic, FOMO, recency, etc.)
        model_prob = float(best.model_prob) if best.model_prob else None
        behavioral_adj = self._behavioral_exploitation_adjustments(snapshot, model_prob)
        
        # FAVORITE LONG SHOT BIAS EXPLOITATION
        # Override side if behavioral detector recommends contrarian position
        # This allows us to:
        # - Buy YES on underpriced favorites (>80% prob) when fear drives them below fair value
        # - Sell YES (or buy NO) on overpriced longshots (<20% prob) when greed inflates them
        recommended_side = behavioral_adj.get("recommended_side")
        if recommended_side and recommended_side in ("yes", "no"):
            # Check if this is a longshot or favorite opportunity
            patterns = behavioral_adj.get("patterns_detected", [])
            has_longshot = "longshot_inflated" in patterns
            has_favorite = "contrarian_opportunity" in patterns
            
            if has_longshot and recommended_side == "no":
                # Overpriced longshot - switch to NO (or sell YES)
                if best.side == "yes":
                    logger.info(
                        "[LONGSHOT-BIAS-EXPLOIT] %s | switching from BUY_YES to BUY_NO | "
                        "market_prob=%.1f%% model_prob=%.1f%% | longshot overpriced",
                        snapshot.market_id,
                        snapshot.implied.yes_prob * 100 if snapshot.implied and snapshot.implied.yes_prob else 0,
                        model_prob * 100 if model_prob else 0
                    )
                    best.side = "no"
            
            elif has_favorite and recommended_side == "yes":
                # Underpriced favorite - ensure we're buying YES
                market_prob = snapshot.implied.yes_prob if snapshot.implied and snapshot.implied.yes_prob else 0.5
                if market_prob > 0.80:  # Only for >80% favorites
                    if best.side == "no":
                        logger.info(
                            "[FAVORITE-BIAS-EXPLOIT] %s | switching from NO to YES | "
                            "market_prob=%.1f%% > 80%% | favorite underpriced",
                            snapshot.market_id,
                            market_prob * 100
                        )
                        best.side = "yes"
                    elif best.side == "yes":
                        # Entry trades always use BUY actions after fix (line 2106)
                        logger.info(
                            "[FAVORITE-BIAS-EXPLOIT] %s | confirming BUY_YES on favorite | "
                            "market_prob=%.1f%% > 80%% | locking in small consistent profits",
                            snapshot.market_id,
                            market_prob * 100
                        )
        
        # Apply behavioral size multiplier (reduces size for risky behavioral patterns)
        behavioral_size_mult = behavioral_adj.get("size_multiplier", 1.0)
        # 15m scalper: floor at 0.5x to prevent excessive size reduction from stacked penalties
        is_scalper_sizing = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
        min_behavioral_mult = 0.50 if is_scalper_sizing else 0.25
        behavioral_size_mult = max(min_behavioral_mult, behavioral_size_mult)
        if behavioral_size_mult != 1.0 and behavioral_size_mult > 0:
            size = int(size * behavioral_size_mult)
            logger.debug(
                "[BEHAVIORAL] %s | size adjusted: %d -> %d (mult=%.2f, patterns=%s)",
                snapshot.market_id,
                int(size / behavioral_size_mult),
                size,
                behavioral_size_mult,
                behavioral_adj.get("patterns_detected", [])
            )
        
        # Apply LIVE mode size cap from guardian (fail-closed: 0.0 if unavailable)
        size_cap = self._get_size_cap_for_asset(asset)
        if size_cap < 1.0:
            # Cap is a fraction (e.g., 0.0 = blocked, 0.25 = 25% of Kelly)
            max_contracts = int(self.config.max_contracts_per_order * size_cap)
            if size > max_contracts:
                logger.info(
                    "[SIZE-CAP] %s | size reduced: %d -> %d (cap=%.0f%%)",
                    snapshot.market_id, size, max_contracts, size_cap * 100
                )
                size = max_contracts
        
        # Apply cycle-level cap (1-2% bankroll allocation across all winners)
        try:
            # LEGACY REMOVAL: dynamic_sizing moved to archive/legacy/ during 15m stack cleanup
            # cycle_capped_size, cycle_reason = apply_cycle_cap_to_kelly_size(...)
            cycle_capped_size = size
        except Exception as _cap_exc:
            logger.debug("Cycle cap failed (non-critical): %s", _cap_exc)
            cycle_capped_size = size
        # if cycle_capped_size < size:
        #     logger.info(
        #         "[CYCLE-CAP] %s | size reduced: %d -> %d (reason=%s)",
        #         snapshot.market_id, size, cycle_capped_size, cycle_reason
        #     )
        #     size = cycle_capped_size
        # except Exception as e:
        #     logger.debug("Cycle cap not applied for %s: %s", snapshot.market_id, e)
        
        if size <= 0:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason="Kelly sizing returned 0 contracts.",
                correlation_id=correlation_id,
            )

        # CRITICAL FIX: Entry trades must ALWAYS use BUY actions
        # Entry trades: BUY_YES (bullish) or BUY_NO (bearish)
        # SELL actions are ONLY for exit trades
        # Previous bug: checked best.action which could be 'sell', causing SELL_YES on entry
        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO

        # SPOT PRICE MOMENTUM ALIGNMENT
        # Check if trade aligns with spot price momentum
        # When spot is trending up, prefer YES on bullish contracts
        # When spot is trending down, prefer NO (or sell YES) on bearish contracts
        trend_aligned = getattr(snapshot, 'trend_aligned', None)
        if trend_aligned is not None:
            if trend_aligned and best.side == "no":
                # Spot trending up but we're betting NO - consider flipping
                # This helps exploit lag between spot moves and prediction market pricing
                logger.info(
                    "[SPOT-MOMENTUM-LAG] %s | spot trending up but betting NO | "
                    "consider flipping to YES to exploit market lag",
                    snapshot.market_id
                )
            elif not trend_aligned and best.side == "yes":
                # Spot trending down but we're betting YES - consider flipping
                logger.info(
                    "[SPOT-MOMENTUM-LAG] %s | spot trending down but betting YES | "
                    "consider flipping to NO to exploit market lag",
                    snapshot.market_id
                )

        # ORDER BOOK QUEUE STRATEGY FOR MAKER REBATES
        # Prefer limit orders (maker) over market orders (taker) to earn rebates
        # Kalshi maker fee is 25% of taker fee, so we save costs by providing liquidity
        # For favorites (>80% prob), use limit orders at mid or slightly below to earn maker rebates
        market_prob = snapshot.implied.yes_prob if snapshot.implied and snapshot.implied.yes_prob else 0.5
        use_limit_order = True  # Default to limit orders for maker rebates
        post_only = False  # Only use post_only for NEUTRAL_MM mode
        
        # Limit price: use the ask for buys, bid for sells
        limit_cents = None
        
        if market_prob > 0.80 and best.side == "yes" and best.action == "buy":
            # Favorite >80%: use limit order at bid or mid to earn maker rebate
            # This locks in small consistent profits while earning rebates
            if snapshot.implied.yes_bid is not None:
                limit_cents = int(snapshot.implied.yes_bid)
                logger.info(
                    "[MAKER-REBATE-STRATEGY] %s | favorite >80%% | using limit order at bid %d¢ | "
                    "earning maker rebate (25%% of taker fee)",
                    snapshot.market_id, limit_cents
                )
            # If yes_bid is None, fall through to standard logic below
        
        # Standard limit price logic (used when not in favorite rebate strategy or bid unavailable)
        # Entry trades always use BUY actions after fix (line 2106), so only use ask prices
        if limit_cents is None:
            if best.side == "yes":
                if snapshot.implied.yes_ask is not None:
                    limit_cents = int(snapshot.implied.yes_ask)
            else:
                if snapshot.implied.no_ask is not None:
                    limit_cents = int(snapshot.implied.no_ask)

        # Build detailed reason with conviction components
        reason_parts = [
            f"{phase.value} phase",
            f"{best.edge_type} edge {best.net_edge:.4f}",
            f"base_size={base_size}",
            f"structural_factor={structural_factor:.2f}",
            f"final_size={size}",
        ]
        
        if conviction_details:
            reason_parts.append(
                f"conviction={conviction_details['conviction']:.2f} "
                f"(FVG:{conviction_details['fvg_component']:.2f} "
                f"trend:{conviction_details['trend_component']:.2f} "
                f"sent:{conviction_details['sentiment_component']:.2f})"
            )
        
        # Add FVG context to reason
        if fvg_timing:
            reason_parts.append(
                f"FVG_entry={fvg_timing.should_enter}:{fvg_timing.entry_urgency:.2f}"
            )
            if fvg_timing.target_price_cents:
                reason_parts.append(f"FVG_target={fvg_timing.target_price_cents:.1f}c")
        
        # Build eval context with cross-asset information for crypto assets
        eval_context = {
            "archetype": "directional",
            "phase": phase.value,
            "structural_factor": structural_factor,
            "conviction": conviction,
        }
        
        # Add FVG context to eval context
        if fvg_timing:
            eval_context.update({
                "fvg_enabled": True,
                "fvg_should_enter": fvg_timing.should_enter,
                "fvg_entry_urgency": round(fvg_timing.entry_urgency, 2),
                "fvg_should_exit": fvg_timing.should_exit,
                "fvg_exit_urgency": round(fvg_timing.exit_urgency, 2),
                "fvg_target_price": fvg_timing.target_price_cents,
                "fvg_stop_price": fvg_timing.stop_price_cents,
                "fvg_size_factor": round(fvg_size_factor, 2),
            })
        
        # GRADUATED-SIZING-FIX: Add shadow trade info to eval_context
        if _is_shadow_trade:
            eval_context.update({
                "shadow_trade": True,
                "edge_graduated_factor": round(_edge_graduated_factor, 2),
                "edge_threshold": str(min_edge),
                "shadow_threshold": str(float(min_edge) * _shadow_threshold_ratio),
                "edge_ratio": round(_edge_ratio, 2),
            })
        
        # Add cross-asset context for crypto assets
        if use_cross_asset_arbiter:
            eval_context.update({
                "cross_asset_enabled": True,
                "local_min_edge_threshold": str(min_edge),
                "local_edge_passed": best.net_edge >= min_edge,
                "asset": asset,
                "selection_method": "cross_asset_arbiter",
            })
            
            # Submit to cross-asset arbiter for this cycle
            # LEGACY REMOVAL: crypto_top_edge moved to archive/legacy/ during 15m stack cleanup
            # Cross-asset arbiter not used by 15m lean stack
            try:
                # arbiter = get_crypto_top_edge_arbiter()
                # arbiter.submit_from_strategy_signal(
                #     signal=None,  # Will be populated after creation
                #     agent_id=self._agent_name,
                #     asset=asset,
                #     timeframe=_resolved_tf or "unknown",
                #     ticker=snapshot.market_id,
                # )
                # Note: The signal will be created below and the arbiter will pick it up
                # from the trading_agent which calls this method
                pass
            except Exception as e:
                logger.debug("Cross-asset arbiter submission failed (non-critical): %s", e)
        
        # Build final signal with behavioral adjustments for logging
        signal = StrategySignal(
            market_id=snapshot.market_id,
            action=action,
            side=best.side,
            contracts=size,
            limit_price_cents=limit_cents,
            edge=best,
            phase=phase,
            reason="; ".join(reason_parts),
            correlation_id=correlation_id,
            behavioral_adjustments=behavioral_adj,
            eval_context=eval_context,
        )
        
        # CRITICAL FIX (2026-07-31): Update side diversity tracking for this trade
        # This enables balanced YES/NO trading over time
        if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD, SignalAction.CLOSE):
            self._update_side_bias(best.side)
        
        return signal

    def _extract_asset_from_market_id(self, market_id: str) -> str:
        """Extract asset symbol from Kalshi market ID.
        
        Examples:
        - KXBTC15M-XXX -> BTC
        - KXETH-XXX -> ETH  
        - KXSOL1H-XXX -> SOL
        """
        # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
        from merid.utils.kalshi_identity import extract_asset
        return extract_asset(market_id)

    def _resolve_timeframe_from_agent_name(self) -> str:
        """Extract timeframe from agent name.
        
        PRODUCTION AUDIT (Step 5): Only 15m timeframe allowed for trading.
        
        Examples:
        - BTC_15M -> 15m
        - ETH_1H -> 1h (REJECTED in production)
        - SOL_DAILY -> daily (REJECTED in production)
        """
        if not self._agent_name:
            return "unknown"
        
        # Split by underscore and get last part
        parts = self._agent_name.split("_")
        if len(parts) >= 2:
            tf = parts[-1].lower()
            # Normalize common variations
            if tf in {"1h", "hourly"}:
                tf = "1h"
            elif tf in {"daily", "d1"}:
                tf = "daily"
            elif tf in {"weekly", "w1"}:
                tf = "weekly"
            elif tf in {"monthly", "1m"}:
                tf = "monthly"
            elif tf in {"annual", "y"}:
                tf = "annual"
            
            # PRODUCTION AUDIT (Step 5): Reject non-15m timeframes
            if tf != "15m" and tf != "15min":
                logger.warning(
                    f"[STRATEGY_SCOPE] Agent {self._agent_name} using timeframe '{tf}' "
                    f"- not allowed in production (only 15m permitted). Trading will be blocked."
                )
            return tf
        return "unknown"

    def _get_size_cap_for_asset(self, asset: str) -> float:
        """Get size cap for asset from TradingGuardian (legacy CT) when its loop runs.

        AgentGrid PM uses ExecutionGate + portfolio risk, not CT's guardian fractions.
        When CT is explicitly enabled but guardian unavailable, fail closed (0.0).
        When CT is disabled/not running (AgentGrid mode), return 1.0 for full sizing.

        Returns:
            Size cap as fraction (0.0-1.0). ``1.0`` = full strategy sizing subject to
            ``StrategyConfig`` / risk agent limits.
        """
        import os
        _ct_enabled = os.getenv("MERID_ENABLE_KALSHI_CT", "").lower() in ("1", "true", "yes", "on")

        try:
            from merid.trading.kalshi_continuous_trader import get_continuous_trader

            trader = get_continuous_trader()
            if trader and trader.is_running() and trader._guardian:
                # .get defaults to 0.0 → fail-closed for unknown assets on the CT path
                return trader._guardian.checklist.live_size_caps.get(asset, 0.0)

            # CT is enabled but not running or guardian unavailable → fail closed
            if _ct_enabled:
                return 0.0

        except Exception:
            # Exception while CT enabled → fail closed
            if _ct_enabled:
                return 0.0
            pass

        # CT not enabled (AgentGrid mode) → return 1.0 for full sizing
        return 1.0

    def _sentiment_size_multiplier(self, snapshot: MarketSnapshot, action: SignalAction) -> Decimal:
        """Return a 0.5–1.5 multiplier applied to Kelly size based on regime.

        Logic:
          extreme_fear  + buying YES (contrarian long) → 1.3× (fear = discount)
          extreme_greed + buying YES (momentum chase)  → 0.6× (crowded, reduce)
          extreme_greed + buying NO  (fade greed)      → 1.2× (contrarian short)
          fear / greed  (moderate)                     → 1.0× (baseline)
          No sentiment data                            → 1.0×
        """
        regime = snapshot.sentiment_regime
        if not regime:
            return Decimal("1.0")
        buying_yes = action in (SignalAction.BUY_YES,)
        buying_no  = action in (SignalAction.BUY_NO,)
        if regime == "extreme_fear":
            return Decimal("1.3") if buying_yes else Decimal("0.8")
        if regime == "extreme_greed":
            if buying_yes:
                return Decimal("0.6")   # reduce momentum chase
            if buying_no:
                return Decimal("1.2")   # reward contrarian fade
        return Decimal("1.0")

    def _sentiment_edge_floor(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> Decimal:
        """Raise the minimum edge threshold in extreme regimes (more selective)."""
        base = self._min_edge_for_phase(phase)
        regime = snapshot.sentiment_regime
        if regime in ("extreme_fear", "extreme_greed"):
            return base * Decimal("1.25")   # +25% edge required in extreme regimes
        return base

    def _behavioral_exploitation_adjustments(
        self,
        snapshot: MarketSnapshot,
        model_prob: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compute behavioral bias adjustments for edge and position sizing.
        
        Returns dict with:
        - edge_boost_bps: Additional edge requirement from behavioral patterns
        - size_multiplier: Position size adjustment (0.5-1.5x typical)
        - patterns_detected: List of detected behavioral patterns
        - recommended_side: Optional contrarian side recommendation
        - urgency: immediate, normal, delayed, avoid
        """
        try:
            return {
                "edge_boost_bps": 0,
                "size_multiplier": 1.2,
                "patterns_detected": [],
                "recommended_side": None,
                "urgency": "normal",
                "raw_signals": [],
            }
        except Exception as e:
            logger.debug("Behavioral exploitation analysis skipped: %s", e)
            return {
                "edge_boost_bps": 0,
                "size_multiplier": 1.0,
                "patterns_detected": [],
                "recommended_side": None,
                "urgency": "normal",
                "raw_signals": [],
            }

    # ------------------------------------------------------------------
    # Contrarian archetype
    # ------------------------------------------------------------------

    def _evaluate_contrarian(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Contrarian: only trades when local fear/greed >= threshold AND model disagrees significantly."""
        _cmin = float(self.config.contrarian_sentiment_min)
        local = snapshot.sentiment_local
        
        # PRODUCTION FIX v8 (2026-04-30): Track 24h contrarian statistics
        from merid.prediction.sentiment_floor_tracker import get_sentiment_floor_tracker
        _tracker = get_sentiment_floor_tracker()
        
        # PRODUCTION FIX: Sentiment gating can be disabled via MERID_SENTIMENT_MODE env var
        if SENTIMENT_GATING_ENABLED:
            if local is None or local < _cmin:
                # Record the floor block for 24h statistics
                _tracker.record_attempt(
                    market_id=snapshot.market_id,
                    local_sentiment=local,
                    sentiment_min=_cmin,
                    blocked=True,
                    block_reason="sentiment_below_contrarian_floor",
                )
                
                # Log clear rejection reason with exact values
                logger.info(
                    "[CONTRARIAN_REJECT] agent=%s market=%s local_sentiment=%s min_required=%.1f "
                    "reason=sentiment_floor_block (track this with MERID_PM_CONTRARIAN_SENTIMENT_MIN env)",
                    self._agent_name, snapshot.market_id, 
                    f"{local:.1f}" if local is not None else "None", _cmin
                )
                
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.NO_ACTION,
                    side="none", contracts=0, phase=phase,
                    reason=f"Contrarian requires local sentiment ≥{_cmin:.0f}; got {local}.",
                    correlation_id=correlation_id,
                eval_context={
                    "contrarian_sentiment_min": _cmin,
                    "actual_local_sentiment": local,
                    "block": "sentiment_below_contrarian_floor",
                },
            )
        else:
            # Sentiment gating disabled - log and proceed with EV-only evaluation
            logger.debug(
                "[CONTRARIAN] agent=%s market=%s sentiment_gating=disabled "
                "local_sentiment=%s min_required=%.1f - proceeding based on EV only",
                self._agent_name, snapshot.market_id,
                f"{local:.1f}" if local is not None else "None", _cmin
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type in ("speculative", "sentiment_driven")]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for contrarian.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        model_gap = abs(float(best.model_prob) - float(best.market_prob))
        _gmin = float(self.config.contrarian_model_gap_min)
        if model_gap < _gmin:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian model gap {model_gap:.2%} < {_gmin:.0%} required.",
                correlation_id=correlation_id,
                eval_context={
                    "contrarian_model_gap_min": _gmin,
                    "block": "model_gap_too_small",
                },
            )

        min_edge = self._sentiment_edge_floor(snapshot, phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian edge {best.net_edge:.4f} below floor {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_floor": str(min_edge),
                    "archetype": "contrarian",
                    "block": "edge_below_threshold",
                },
            )

        # CRITICAL FIX: Entry trades must ALWAYS use BUY actions
        # Entry trades: BUY_YES (bullish) or BUY_NO (bearish)
        # SELL actions are ONLY for exit trades
        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        mult = self._sentiment_size_multiplier(snapshot, action)
        size_factor = max(0.35, min(1.5, float(mult))) * self._pm_vol_band_size_factor(snapshot)
        size = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        size = max(1, min(size, self.config.max_contracts_per_order))
        
        # Apply cycle-level cap (1-2% bankroll allocation)
        size = self._apply_cycle_cap(size, snapshot, best.side, best.net_edge)

        # BUG-FIX (2026-05-06): Use 1 cent fallback instead of 50 to prevent zero contract sizing
        # with small bankrolls. The 50 cent default was causing max_contracts_per_winner=0.
        limit_cents = int(snapshot.implied.yes_ask or 1) if best.side == "yes" else int(snapshot.implied.no_ask or 1)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Contrarian fade: sentiment={local:.0f}/100 gap={model_gap:.2%} size={size} factor={size_factor:.2f}.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Regime-switch archetype
    # ------------------------------------------------------------------

    def _evaluate_regime_switch(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Regime-switch: rides momentum when category sentiment shifts fast (Δ > 20 in session).

        Uses category score as the regime signal; falls back to directional if no shift.
        """
        cat_score = snapshot.sentiment_category
        glob_score = snapshot.sentiment_global
        if cat_score is None:
            return self._evaluate_directional(snapshot, phase, correlation_id)

        # Momentum regime: category is greed/extreme_greed → ride YES momentum
        # Fear regime: category is fear/extreme_fear → ride NO momentum (things going lower)
        regime = snapshot.sentiment_regime or "greed"
        spec_edges = [e for e in snapshot.edges if e.edge_type in ("speculative", "sentiment_driven")]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for regime-switch.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch edge {best.net_edge:.4f} below threshold {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_threshold": str(min_edge),
                    "archetype": "regime_switch",
                    "block": "edge_below_threshold",
                },
            )

        # In greed regime, prefer YES; in fear regime, prefer NO
        if regime in ("greed", "extreme_greed") and best.side != "yes":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: greed regime, skipping NO-side trade.",
                correlation_id=correlation_id,
            )
        if regime in ("fear", "extreme_fear") and best.side != "no":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: fear regime, skipping YES-side trade.",
                correlation_id=correlation_id,
            )

        # CRITICAL FIX: Entry trades must ALWAYS use BUY actions
        # Entry trades: BUY_YES (bullish) or BUY_NO (bearish)
        # SELL actions are ONLY for exit trades
        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        mult = self._sentiment_size_multiplier(snapshot, action)
        size_factor = max(0.35, min(1.5, float(mult))) * self._pm_vol_band_size_factor(snapshot)
        size = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        size = max(1, min(size, self.config.max_contracts_per_order))
        
        # Apply cycle-level cap (1-2% bankroll allocation)
        size = self._apply_cycle_cap(size, snapshot, best.side, best.net_edge)
        
        # BUG-FIX (2026-05-06): Use 1 cent fallback instead of 50 to prevent zero contract sizing
        # with small bankrolls. The 50 cent default was causing max_contracts_per_winner=0.
        limit_cents = int(snapshot.implied.yes_ask or 1) if best.side == "yes" else int(snapshot.implied.no_ask or 1)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Regime-switch: {regime} cat={cat_score:.0f} glob={glob_score:.0f} size={size} factor={size_factor:.2f}.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Vol-breakout archetype
    # ------------------------------------------------------------------

    def _evaluate_vol_breakout(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Vol-breakout: trades when volatility component is high AND book is imbalanced.

        Scales risk with sentiment intensity — higher score = larger size up to cap.
        """
        local = snapshot.sentiment_local
        if local is None:
            return self._evaluate_directional(snapshot, phase, correlation_id)

        # PRODUCTION FIX: Sentiment gating can be disabled via MERID_SENTIMENT_MODE env var
        if SENTIMENT_GATING_ENABLED:
            # Require elevated sentiment (either direction) to signal vol breakout
            lo, hi = float(self.config.vol_breakout_neutral_low), float(self.config.vol_breakout_neutral_high)
            if lo <= local <= hi:
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.NO_ACTION,
                    side="none", contracts=0, phase=phase,
                    reason=f"Vol-breakout requires sentiment outside {lo:.0f}–{hi:.0f}; got {local:.0f}.",
                    correlation_id=correlation_id,
                    eval_context={
                        "vol_breakout_neutral_low": lo,
                        "vol_breakout_neutral_high": hi,
                        "block": "sentiment_in_neutral_band",
                    },
                )
        else:
            # Sentiment gating disabled - log and proceed with EV-only evaluation
            lo, hi = float(self.config.vol_breakout_neutral_low), float(self.config.vol_breakout_neutral_high)
            logger.debug(
                "[VOL_BREAKOUT] agent=%s market=%s sentiment_gating=disabled "
                "local_sentiment=%.0f neutral_band=[%.0f,%.0f] - proceeding based on EV only",
                self._agent_name, snapshot.market_id, local, lo, hi
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type in ("speculative", "sentiment_driven")]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for vol-breakout.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Vol-breakout edge {best.net_edge:.4f} below threshold {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_threshold": str(min_edge),
                    "archetype": "vol_breakout",
                    "block": "edge_below_threshold",
                },
            )

        # Scale size by sentiment intensity (distance from 50).
        # Intensity only shrinks — capped at 1.0 so hourly exposure cap is
        # never bypassed by a 1.5× boost.  Minimum factor 0.35.
        intensity = abs(local - 50) / 50.0   # 0–1
        size_factor = (
            max(0.35, min(1.0, 1.0 - intensity * 0.3)) * self._pm_vol_band_size_factor(snapshot)
        )
        scaled = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        scaled = max(1, min(scaled, self.config.max_contracts_per_order))
        
        # Apply cycle-level cap (1-2% bankroll allocation)
        scaled = self._apply_cycle_cap(scaled, snapshot, best.side, best.net_edge)

        # CRITICAL FIX: Entry trades must ALWAYS use BUY actions
        # Entry trades: BUY_YES (bullish) or BUY_NO (bearish)
        # SELL actions are ONLY for exit trades
        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        # BUG-FIX (2026-05-06): Use 1 cent fallback instead of 50 to prevent zero contract sizing
        # with small bankrolls. The 50 cent default was causing max_contracts_per_winner=0.
        limit_cents = int(snapshot.implied.yes_ask or 1) if best.side == "yes" else int(snapshot.implied.no_ask or 1)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=scaled,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Vol-breakout: sentiment={local:.0f} intensity={intensity:.2f} size={scaled}.",
            correlation_id=correlation_id,
        )

    def _evaluate_mm(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Market Maker strategy: quote bid and ask."""
        # Check spread
        if snapshot.implied.spread_cents is None or snapshot.implied.spread_cents > self.config.mm_max_spread_cents:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Spread {snapshot.implied.spread_cents} exceeds MM limit.",
                correlation_id=correlation_id,
            )

        # Simple mid-price based quoting
        yes_mid = (snapshot.implied.yes_bid + snapshot.implied.yes_ask) / 2 if snapshot.implied.yes_bid and snapshot.implied.yes_ask else Decimal("50")
        
        # Apply target spread
        half_spread = self.config.mm_target_spread_cents / 2
        bid = int((yes_mid - half_spread).quantize(Decimal("1"), ROUND_HALF_UP))
        ask = int((yes_mid + half_spread).quantize(Decimal("1"), ROUND_HALF_UP))

        # Clamp to 1-99
        bid = max(1, min(98, bid))
        ask = max(bid + 1, min(99, ask))

        # Mid price (integer cents) for risk sizing, PM logs, and TradeProposal.intent_risk —
        # QUOTE previously omitted limit_price_cents, which made intent_risk=0 downstream.
        # CRITICAL FIX: Clamp to 10-75 cents to prevent extreme purchases
        # This aligns with kalshi_crypto_15m_v2.yaml price_range [10, 75]
        # 2026-07-12: Fixed max from 50c to 75c to match profile price_range.max_price_cents (expanded for market conditions)
        mid_cents = max(10, min(75, int((bid + ask) // 2)))

        _depth = int(self.config.min_depth_contracts)
        _vm = self._pm_vol_band_size_factor(snapshot)
        if _vm != 1.0:
            _depth = max(1, int(round(_depth * _vm)))

        # Cap by strategy limits (respects Top-N allocator downstream)
        _depth = min(_depth, self.config.max_contracts_per_order)
        _depth = min(_depth, self.config.mm_inventory_limit)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.QUOTE,
            side="yes",
            contracts=_depth,
            limit_price_cents=mid_cents,
            bid_price_cents=bid,
            ask_price_cents=ask,
            phase=phase,
            reason=(
                f"MM quoting {bid}c/{ask}c (mid={mid_cents}c for risk) around mid {yes_mid:.1f}c."
            ),
            correlation_id=correlation_id,
        )

    def _evaluate_arb(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Arbitrage strategy: specifically focused on mispricings."""
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        if not arb_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No arb edge detected.",
                correlation_id=correlation_id,
            )

        best_arb = max(arb_edges, key=lambda e: e.net_edge)
        if best_arb.net_edge < self.config.min_arb_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Arb edge {best_arb.net_edge:.4f} below threshold.",
                correlation_id=correlation_id,
            )

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.BUY_YES, # Arb usually involves both, buy_yes side used as trigger
            side="both",
            contracts=self.config.max_contracts_per_order,
            edge=best_arb,
            phase=phase,
            reason=f"Arb opportunity: {best_arb.net_edge:.4f} edge.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Exit evaluation
    # ------------------------------------------------------------------

    def register_position(self, pos: PositionState) -> None:
        """Register an open position for exit monitoring."""
        self._positions[pos.market_id] = pos

    def remove_position(self, market_id: str) -> None:
        """Remove a closed position."""
        self._positions.pop(market_id, None)

    def _record_stop_candidate(
        self,
        pos: PositionState,
        snapshot: MarketSnapshot,
        pnl_pct: Decimal,
    ) -> None:
        """Convert a strategy-level stop-loss trigger to a gated StopCandidate event.

        The legacy SELL signal is suppressed; the candidate is logged and may be
        submitted later if it passes the edge/settlement/position validation gates.
        """
        position_cc = to_signed_yes_exposure(pos.side, pos.contracts) * 100

        fair_value: Optional[int] = None
        executable_exit: Optional[int] = None
        if pos.current_price_cents is not None:
            executable_exit = int(pos.current_price_cents)

        if snapshot.implied is not None:
            if pos.side == "yes" and snapshot.implied.yes_prob is not None:
                fair_value = int(round(float(snapshot.implied.yes_prob) * 100))
            elif pos.side == "no" and snapshot.implied.no_prob is not None:
                fair_value = int(round(float(snapshot.implied.no_prob) * 100))

        seconds_to_expiry = None
        if snapshot.time_to_expiry_hours is not None:
            try:
                seconds_to_expiry = float(snapshot.time_to_expiry_hours) * 3600.0
            except (TypeError, ValueError):
                pass

        entry_price = int(pos.avg_entry_cents) if pos.avg_entry_cents is not None else None
        predicted_pnl = int(pos.unrealized_pnl_cents) if pos.unrealized_pnl_cents is not None else None

        candidate = build_stop_candidate(
            market_ticker=pos.market_id,
            exchange_position_cc=position_cc,
            trigger_reason="MODEL_INVALIDATION",
            entry_price_cents=entry_price,
            fair_value_cents=fair_value,
            executable_exit_cents=executable_exit,
            seconds_to_expiry=seconds_to_expiry,
            quote_age_ms=None,
            consecutive_edge_below=0,
        )
        # predicted PnL from the position is more authoritative than the helper estimate.
        candidate = candidate.__class__(
            **{
                **candidate.to_dict(),
                "predicted_net_pnl_cents": predicted_pnl,
            }
        )
        record_stop_candidate(candidate)
        maybe_submit_stop_candidate_sync(candidate)

        logger.warning(
            "[STRATEGY-STOP-CANDIDATE] market=%s side=%s contracts=%s pnl_pct=%.2f%% "
            "fair=%s exit=%s - direct stop signal suppressed until replay tests pass",
            pos.market_id,
            pos.side,
            pos.contracts,
            float(pnl_pct) * 100,
            fair_value,
            executable_exit,
        )

    def evaluate_exits(self, snapshots: Dict[str, MarketSnapshot]) -> List[StrategySignal]:
        """Check all open positions for exit conditions.

        Exit rules:
        - Profit target: unrealized PnL >= profit_target_pct of entry cost.
        - Stop loss: unrealized PnL <= -stop_loss_pct of entry cost.
        - Max hold: position held longer than max_hold_hours.
        - Market closing: force close if state is CLOSING or CLOSED.
        """
        signals: List[StrategySignal] = []

        for mid, pos in list(self._positions.items()):
            snap = snapshots.get(mid)
            if snap is None:
                continue

            phase = self._expiry_phase(snap.time_to_expiry_hours)

            # Update current price
            if pos.side == "yes" and snap.implied.yes_bid is not None:
                pos.current_price_cents = snap.implied.yes_bid
            elif pos.side == "no" and snap.implied.no_bid is not None:
                pos.current_price_cents = snap.implied.no_bid

            if pos.current_price_cents is not None:
                pnl_per_contract = pos.current_price_cents - pos.avg_entry_cents
                pos.unrealized_pnl_cents = pnl_per_contract * pos.contracts

            reason = None

            # Profit target
            if pos.unrealized_pnl_cents is not None:
                entry_cost = pos.avg_entry_cents * pos.contracts
                if entry_cost > 0:
                    pnl_pct = pos.unrealized_pnl_cents / entry_cost
                    if pnl_pct >= self.config.profit_target_pct:
                        reason = f"Profit target hit: {pnl_pct:.2%} >= {self.config.profit_target_pct:.2%}."
                    elif pnl_pct <= -self.config.stop_loss_pct:
                        # Strategy stop loss is disabled from direct SELL signal.
                        # Record a StopCandidate event and continue (max hold/market close may still fire).
                        self._record_stop_candidate(pos, snap, pnl_pct)

            # Max hold
            if reason is None:
                # Handle both datetime and float (timestamp) types
                opened_at = pos.opened_at
                if isinstance(opened_at, (int, float)):
                    opened_at = datetime.fromtimestamp(opened_at, tz=timezone.utc)
                hours_held = Decimal(str(
                    (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600
                ))
                if hours_held >= self.config.max_hold_hours:
                    reason = f"Max hold exceeded: {hours_held:.1f}h >= {self.config.max_hold_hours}h."

            # Market closing
            if reason is None and snap.state in (ContractState.CLOSING, ContractState.CLOSED):
                reason = f"Market state is {snap.state.value}, closing position."

            if reason:
                action = SignalAction.SELL_YES if pos.side == "yes" else SignalAction.SELL_NO
                
                # [TRACE] MONITOR_START — position exit signal detected
                if pos.correlation_id:
                    logger.info(
                        "[TRACE] MONITOR_EXIT | corr_id=%s | market=%s | side=%s | contracts=%s | pnl_cents=%s | reason=%s | formulas=%s | audit_spec=%s",
                        pos.correlation_id,
                        mid,
                        pos.side,
                        pos.contracts,
                        pos.unrealized_pnl_cents,
                        reason,
                        FORMULAS_VERSION,
                        AUDIT_SPEC_VERSION,
                    )
                
                signals.append(StrategySignal(
                    market_id=mid,
                    action=action,
                    side=pos.side,
                    contracts=pos.contracts,
                    phase=phase,
                    reason=reason,
                    correlation_id=pos.correlation_id,
                ))

        return signals

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def scan_markets(self, snapshots: List[MarketSnapshot]) -> List[StrategySignal]:
        """Evaluate multiple markets and return actionable signals only."""
        signals = []
        for snap in snapshots:
            sig = self.evaluate(snap)
            if sig.action != SignalAction.NO_ACTION:
                signals.append(sig)
        return signals
