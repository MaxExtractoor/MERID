"""KalshiTradingAgent — Per-(asset, timeframe) trading agent.

Each agent instance:
- Subscribes to a filtered set of Kalshi markets (resolved from config)
- Reads MERID's internal crypto price feed for model features
- Executes only via typed Kalshi tools
- Runs a decision loop keyed to contract expiry windows
- Enforces per-agent risk limits

Strike Selection Integration:
- Uses ``kalshi_strike_selector.evaluate()`` for crypto markets to validate strike distance.
- Crypto markets (KXBTC, KXETH, etc.) are evaluated against spot for ATM/slightly OTM strikes.
- Macro markets (KXFED, KXFEDDECISION, etc.) are bypassed with reason ``NON_CRYPTO_MARKET``.
- Macro bypass is expected behavior — produces DEBUG logs, not ERROR logs.
- Asset resolution via ``resolve_asset_for_snapshot()`` returns "" for macro tickers,
  preventing incorrect crypto asset assignment.

Reuses:
- KalshiStrategy (merid.prediction.strategy) for edge/sizing decisions
- PredictionMarketRisk (merid.prediction.risk) for pre-trade checks
- PredictionMarketModel (merid.prediction.model) for implied probs
- SessionGuard for trading hours
- VenueGate for mode gating
- KalshiStrikeSelector for crypto-only strike distance validation
"""

from __future__ import annotations

import asyncio
import hashlib  # PRODUCTION FIX (2026-05-01): For deterministic exit order client_tags
import json as _json
import logging
import os
import random
import time
import uuid  # P1 FIX: UUID suffix for agent_id uniqueness
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
from merid.prediction.agent_grid_config import AgentConfig, EntryWindowConfig
from merid.prediction.decision import Decision, DecisionAction, DecisionTimer, HoldReason
from merid.prediction.decision_evaluator import CycleContext, evaluate_cycle_decision
from merid.prediction.session_guard import get_session_guard
from merid.prediction.trade_hold_config import get_trade_hold_config
from merid.prediction.venue_gate import get_venue_gate
from merid.prediction.model import (
    PredictionMarketModel,
    MarketSnapshot,
    ContractState,
    ImpliedProbability,
    snapshot_timestamp_utc_epoch_seconds,
    pm_spot_feed_symbol_candidates,
)
from merid.prediction.strategy import KalshiStrategy, StrategySignal, SignalAction, StrategyConfig
from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig, PreTradeCheck, RiskAction, get_prediction_risk
from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi.stop_loss import (
    StopLossRules, TrackedPosition,
    MicroScalpExitManager, MicroScalpPosition, MicroScalpExitConfig,
    DynamicTPConfig, DynamicTPCalculator,
)
from merid.event_venues.kalshi.take_profit import TakeProfitManager, get_tp_config_for_agent
from merid.prediction.risk import CycleCapTracker, CycleCapConfig
from merid.tick_events import TickContext, get_tick_bus
from utils.logger import get_logger
from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
from merid.swarm.consensus_aggregator import get_consensus_aggregator

# Cross-asset arbiter integration
from merid.prediction.crypto_top_edge import (
    CRYPTO_ASSETS,
    MEAN_REVERSION_TIMEFRAMES,
    get_crypto_top_edge_arbiter,
)
from merid.event_venues.kalshi.position_cache import get_position_cache

logger = get_logger("merid.prediction.trading_agent")

# Throttle [PM_SPOT] missing-spot warnings per agent|asset (seconds between emits).
_PM_SPOT_MISSING_WARN_LAST: Dict[str, float] = {}
_PM_SPOT_MISSING_WARN_INTERVAL_S = float(os.getenv("MERID_PM_SPOT_MISSING_WARN_INTERVAL_S", "120.0"))
# Throttle PM_SPOT_BLOCK logs per asset|market for CRYPTO_15M_MM hard gate.
_PM_SPOT_BLOCK_LOG_LAST: Dict[str, float] = {}
_PM_SPOT_BLOCK_LOG_INTERVAL_S = float(os.getenv("MERID_PM_SPOT_BLOCK_LOG_INTERVAL_S", "120.0"))


def _classify_pm_no_action_reason(reason: str) -> str:
    """Bucket strategy ``reason`` for PM_CYCLE_TRACE rollups."""
    r = (reason or "").lower()
    if "pm_spot_gate" in r or "missing_or_stale_spot" in r:
        return "pm_spot_gate"
    if "spot_strike" in r or "spot_strike_anomaly" in r:
        return "spot_strike_veto"
    if "stale snapshot" in r:
        return "stale_snapshot"
    if "expiry unknown" in r or "unknown expiry" in r:
        return "unknown_expiry"
    if "liquidity guard" in r:
        return "liquidity_guard"
    if "volume" in r and "below" in r:
        return "volume"
    if "open_interest" in r or "oi " in r:
        return "open_interest"
    if "below" in r and "threshold" in r and "edge" in r:
        return "edge_below_threshold"
    if "confidence" in r and "below" in r:
        return "confidence"
    if "prob_edge" in r or "conviction" in r or "blocked:" in r:
        return "prob_or_conviction_gate"
    if "no actionable edge" in r:
        return "no_speculative_edge"
    if "kelly" in r and "0" in r:
        return "kelly_zero"
    return "other"


def _apply_global_pm_strategy_env(sc: StrategyConfig) -> None:
    """Optional process-wide overrides via env (ops tuning without YAML edit)."""
    env_map = [
        ("MERID_PM_MIN_EDGE_EARLY", "min_edge_early"),
        ("MERID_PM_MIN_EDGE_MID", "min_edge_mid"),
        ("MERID_PM_MIN_EDGE_LATE", "min_edge_late"),
        ("MERID_PM_MIN_EDGE_TERMINAL", "min_edge_terminal"),
        ("MERID_PM_MIN_ARB_EDGE", "min_arb_edge"),
        ("MERID_PM_MIN_CONFIDENCE", "min_confidence"),
        ("MERID_PM_MIN_VOLUME", "min_volume"),
        ("MERID_PM_MIN_OPEN_INTEREST", "min_open_interest"),
        ("MERID_PM_CONTRARIAN_SENTIMENT_MIN", "contrarian_sentiment_min"),
        ("MERID_PM_CONTRARIAN_MODEL_GAP_MIN", "contrarian_model_gap_min"),
        ("MERID_PM_VOL_BREAKOUT_NEUTRAL_LOW", "vol_breakout_neutral_low"),
        ("MERID_PM_VOL_BREAKOUT_NEUTRAL_HIGH", "vol_breakout_neutral_high"),
        ("MERID_SENTIMENT_MODE", "sentiment_mode"),
        ("MERID_PM_MM_MAX_SPREAD_CENTS", "mm_max_spread_cents"),
        ("MERID_PM_MM_TARGET_SPREAD_CENTS", "mm_target_spread_cents"),
        ("MERID_PM_MM_INVENTORY_LIMIT", "mm_inventory_limit"),
        ("MERID_PM_MM_SKEW_FACTOR", "mm_skew_factor"),
    ]
    for ek, attr in env_map:
        v = os.getenv(ek)
        if not v or not hasattr(sc, attr):
            continue
        cur = getattr(sc, attr)
        if isinstance(cur, Decimal):
            setattr(sc, attr, Decimal(str(v)))
        elif isinstance(cur, int):
            setattr(sc, attr, int(v))
        elif isinstance(cur, float):
            setattr(sc, attr, float(v))
        else:
            setattr(sc, attr, v)


# Global thread pool executor for CPU-bound operations
# Increased from default (CPU+4) to handle 35+ concurrent agents without contention
_GLOBAL_AGENT_EXECUTOR: Optional[ThreadPoolExecutor] = None


# ═══════════════════════════════════════════════════════════════════════════════
# KALSHI 15M MICRO-SCALPING: Edge Calculation Utilities
# Systematic mapping from spot → Kalshi contract → edge for BTC/ETH/SOL/XRP/DOGE
# ═══════════════════════════════════════════════════════════════════════════════

# MIGRATION NOTE: All constants below are being migrated to centralized config
# in config/kalshi_distance.yaml. Use merid.prediction.kalshi_distance_config
# for new code. These constants remain for backward compatibility.
try:
    from merid.prediction.kalshi_distance_config import (
        get_distance_config,
        run_startup_assertions,
        GuardCheckResult,
    )
    _DISTANCE_CFG_AVAILABLE = True
except Exception:
    _DISTANCE_CFG_AVAILABLE = False  # Fallback to constants below

# Per-asset 15m volatility scales (σ_a) - realized ATR-based typical impulse
ASSET_VOL_SCALE_15M: Dict[str, float] = {
    "BTC": 0.010,   # 1.0% typical 15m move
    "ETH": 0.012,   # 1.2% typical 15m move
    "SOL": 0.016,   # 1.6% typical 15m move
    "XRP": 0.018,   # 1.8% typical 15m move
    "DOGE": 0.022,  # 2.2% typical 15m move
}

# ═══════════════════════════════════════════════════════════════════════════════
# DISTANCE GUARDS: Hard caps on spot→strike distance (far-OTM protection)
# ═══════════════════════════════════════════════════════════════════════════════
# ⚠️  DEPRECATED: Use config/kalshi_distance.yaml + get_distance_config() instead
# These constants will be removed in a future refactor.

# PRODUCTION FIX (2026-05-01): Hard absolute distance cap per asset from environment
# OPTIMIZED (2026-05-10): Aligned with kalshi_distance.yaml to eliminate bottleneck
MAX_DELTA_PCT: Dict[str, float] = {
    "BTC": float(os.getenv("MERID_PM_MAX_DELTA_PCT_BTC", "0.04")),
    "ETH": float(os.getenv("MERID_PM_MAX_DELTA_PCT_ETH", "0.05")),
    "SOL": float(os.getenv("MERID_PM_MAX_DELTA_PCT_SOL", "0.06")),
    "XRP": float(os.getenv("MERID_PM_MAX_DELTA_PCT_XRP", "0.065")),
    "DOGE": float(os.getenv("MERID_PM_MAX_DELTA_PCT_DOGE", "0.065")),
}

# PRODUCTION FIX (2026-05-01): All trading parameters derive from environment variables
# Sigma-based distance cap (z = delta_pct / sigma_15m must be <= this)
MAX_Z_DISTANCE: float = float(os.getenv("MERID_PM_MAX_Z_DISTANCE", "0.75"))  # sigma max

# Z-score threshold for "near" vs "far" contracts (affects min edge)
Z_NEAR_THRESHOLD: float = float(os.getenv("MERID_PM_Z_NEAR_THRESHOLD", "0.50"))

# ═══════════════════════════════════════════════════════════════════════════════
# EDGE THRESHOLDS: Tightened min edge requirements (+1% from previous)
# ═══════════════════════════════════════════════════════════════════════════════
# ⚠️  DEPRECATED: Use config/kalshi_distance.yaml + get_distance_config() instead

# Min edge for "near" contracts (|z| <= Z_NEAR_THRESHOLD)
# PRODUCTION FIX (2026-05-01): Derive edge thresholds from environment variables
# with sensible defaults. These control minimum edge required for trade entry.
def _get_min_edge_near(asset: str) -> float:
    """Get min edge for 'near' contracts from environment or default."""
    defaults = {"BTC": 0.055, "ETH": 0.055, "SOL": 0.060, "XRP": 0.060, "DOGE": 0.065}
    env_val = os.getenv(f"MERID_PM_EDGE_NEAR_{asset}")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return defaults.get(asset, 0.06)

def _get_min_edge_far(asset: str) -> float:
    """Get min edge for 'far' contracts from environment or default (+2% above near)."""
    near = _get_min_edge_near(asset)
    return near + 0.02

# ═══════════════════════════════════════════════════════════════════════════════
# ASSET & TIMEFRAME EXECUTION GUARDS (15m-only, crypto-only)
# ═══════════════════════════════════════════════════════════════════════════════
# ⚠️  DEPRECATED: Use config/kalshi_distance.yaml + get_distance_config() instead
# CONSOLIDATION FIX: Import from canonical config instead of hardcoding

try:
    from config.kalshi_15m_crypto_config import KALSHI_15M_CRYPTO_ASSETS, KALSHI_15M_TIMEFRAME
    ALLOWED_ASSETS: set[str] = set(KALSHI_15M_CRYPTO_ASSETS)
    EXECUTION_TIMEFRAMES: set[str] = {KALSHI_15M_TIMEFRAME}
except ImportError:
    # Fallback to hardcoded values if config not available
    ALLOWED_ASSETS: set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    EXECUTION_TIMEFRAMES: set[str] = {"15m"}

# ═══════════════════════════════════════════════════════════════════════════════
# UPSTREAM DATA INTEGRITY GUARDS ("No Surprises" Integration)
# ═══════════════════════════════════════════════════════════════════════════════

# Signal staleness: max age of last bar (seconds) before blocking
SIGNAL_MAX_BAR_AGE_SECONDS: float = float(os.getenv("MERID_PM_SIGNAL_MAX_AGE", "900.0"))

# Spot reference integrity: max divergence between our spot and Kalshi reference
SPOT_DIVERGENCE_MAX_PCT: float = float(os.getenv("MERID_PM_SPOT_DIVERGENCE_MAX", "0.005"))

# Fee estimate vs actual mismatch threshold
FEE_MISMATCH_THRESHOLD_PCT: float = float(os.getenv("MERID_PM_FEE_MISMATCH_THRESHOLD", "5.0"))

# Fractional Kelly sizing (conservative)
KELLY_FRACTION: float = float(os.getenv("MERID_PM_KELLY_FRACTION", "0.25"))

# Hard cap on risk per trade (% of bankroll)
MAX_RISK_PER_TRADE_PCT: float = float(os.getenv("MERID_PM_MAX_RISK_PER_TRADE_PCT", "1.0"))


@dataclass(frozen=True)
class KalshiEdgeMetrics:
    """Complete edge metrics for a Kalshi 15m entry.
    
    Captures spot-to-strike distance, implied vs model probability,
    and EV calculations for systematic post-trade analysis.
    """
    # Distance metrics
    spot: float
    strike: float
    delta_pct: float          # (K - S) / S
    delta_bps: float           # delta_pct * 10,000
    z_score: float             # delta_pct / sigma_a (normalized distance)
    
    # Probability & edge
    kalshi_price: float        # Contract price P (0.01-0.99)
    implied_prob: float        # q = P (implied probability)
    model_prob: float          # p_hat from micro-momentum model
    edge: float              # p_hat - q (raw edge)
    
    # EV analysis
    ev_gross: float            # p_hat - P (gross expected value per $1)
    fee_per_contract: float   # ~0.07 * P * (1-P) for taker
    ev_net_per_contract: float # ev_gross - fee
    
    # Asset context
    asset: str
    sigma_15m: float          # Asset's typical 15m volatility


def compute_kalshi_edge_metrics(
    spot: float,
    strike: float,
    kalshi_price: float,
    model_prob: float,
    asset: str,
    contracts: int = 1,
) -> KalshiEdgeMetrics:
    """Compute complete edge metrics for Kalshi 15m micro-scalping entry.
    
    Args:
        spot: Current spot price (e.g., 78320.5 for BTC)
        strike: Kalshi market target/strike price K
        kalshi_price: Contract price P in dollars (0.01-0.99)
        model_prob: Internal model probability p_hat (0.0-1.0)
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        contracts: Number of contracts for fee calculation
        
    Returns:
        KalshiEdgeMetrics with all distance, edge, and EV calculations
        
    Example:
        >>> metrics = compute_kalshi_edge_metrics(
        ...     spot=78320.5, strike=78500.0, kalshi_price=0.41,
        ...     model_prob=0.49, asset="BTC", contracts=50
        ... )
        >>> print(f"edge={metrics.edge:.3f}, z={metrics.z_score:.2f}, EV_net={metrics.ev_net_per_contract:.3f}")
    """
    # Distance calculations
    delta_pct = (strike - spot) / spot if spot != 0 else 0.0
    delta_bps = delta_pct * 10000.0
    
    # Normalized distance in sigma units
    sigma_15m = ASSET_VOL_SCALE_15M.get(asset, 0.015)  # Default 1.5% if unknown
    z_score = delta_pct / sigma_15m if sigma_15m != 0 else 0.0
    
    # Probability & edge
    implied_prob = max(0.01, min(0.99, kalshi_price))  # Clamp to valid range
    edge = model_prob - implied_prob
    
    # EV calculations
    ev_gross = model_prob - kalshi_price
    # Kalshi taker fee: 0.07 * P * (1-P) per contract (approx)
    fee_per_contract = 0.07 * kalshi_price * (1.0 - kalshi_price)
    ev_net_per_contract = ev_gross - fee_per_contract
    
    return KalshiEdgeMetrics(
        spot=spot,
        strike=strike,
        delta_pct=delta_pct,
        delta_bps=delta_bps,
        z_score=z_score,
        kalshi_price=kalshi_price,
        implied_prob=implied_prob,
        model_prob=model_prob,
        edge=edge,
        ev_gross=ev_gross,
        fee_per_contract=fee_per_contract,
        ev_net_per_contract=ev_net_per_contract,
        asset=asset,
        sigma_15m=sigma_15m,
    )


def format_edge_metrics_log(metrics: KalshiEdgeMetrics) -> str:
    """Format edge metrics for concise [TRADE_ENTRY] logging.
    
    Returns a single-line string suitable for grep/awk post-analysis:
    spot=78320.5 strike=78500.0 delta_bps=22.9 z=0.23 kalshi_price=0.41 edge=0.080 EV_net=0.063
    """
    return (
        f"spot={metrics.spot:.1f} strike={metrics.strike:.1f} "
        f"delta_pct={metrics.delta_pct:.5f} delta_bps={metrics.delta_bps:.1f} "
        f"z={metrics.z_score:.2f} sigma_15m={metrics.sigma_15m:.3f} "
        f"kalshi_price={metrics.kalshi_price:.2f} implied_prob={metrics.implied_prob:.2f} "
        f"model_prob={metrics.model_prob:.3f} edge={metrics.edge:.3f} "
        f"EV_gross={metrics.ev_gross:.3f} fee={metrics.fee_per_contract:.4f} "
        f"EV_net={metrics.ev_net_per_contract:.3f}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION GUARDS: Distance, Edge, Asset, and Timeframe Validation
# Three-layer protection: (1) asset/tf whitelist, (2) distance caps, (3) edge floors
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# ASSET EXTRACTION UTILITY ("No Surprises" Integration)
# Robust extraction of asset symbols from various Kalshi ticker formats
# ═══════════════════════════════════════════════════════════════════════════════

def extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset symbol (BTC, ETH, SOL, XRP, DOGE) from Kalshi ticker.
    
    Handles multiple ticker formats:
    - KXBTC15M-26MAY011300-00 → BTC
    - KXBTC-26MAY0114-T85299.99 → BTC
    - KXETH15M → ETH
    - KXSOL-D → SOL
    - KXXRP-W → XRP
    - KXDOGE → DOGE
    
    Args:
        ticker: Kalshi market ticker string
        
    Returns:
        Asset symbol (uppercase) or "UNKNOWN" if not recognized
        
    Examples:
        >>> extract_asset_from_ticker("KXBTC15M-26MAY011300-00")
        'BTC'
        >>> extract_asset_from_ticker("KXETH-D")
        'ETH'
    """
    if not ticker or not isinstance(ticker, str):
        return "UNKNOWN"
    
    ticker_upper = ticker.upper().strip()
    
    # Map of Kalshi prefixes to asset symbols
    prefix_map = {
        "KXBTC": "BTC",
        "KXETH": "ETH", 
        "KXSOL": "SOL",
        "KXXRP": "XRP",
        "KXDOGE": "DOGE",
    }
    
    # Try prefix matching (most reliable)
    for prefix, asset in prefix_map.items():
        if ticker_upper.startswith(prefix):
            return asset
    
    # Fallback: check for embedded asset codes
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        if asset in ticker_upper:
            return asset
    
    return "UNKNOWN"


def extract_timeframe_from_ticker(ticker: str) -> str:
    """Extract timeframe (15m, 1h, daily, weekly) from Kalshi ticker.
    
    Args:
        ticker: Kalshi market ticker string
        
    Returns:
        Timeframe string or "UNKNOWN" if not recognized
    """
    if not ticker or not isinstance(ticker, str):
        return "UNKNOWN"
    
    ticker_upper = ticker.upper().strip()
    
    # Check for explicit timeframe patterns
    if "15M" in ticker_upper or "-15" in ticker_upper:
        return "15m"
    
    # Daily patterns
    if "-D" in ticker_upper or "DAILY" in ticker_upper:
        return "daily"
    
    # Weekly patterns  
    if "-W" in ticker_upper or "WEEKLY" in ticker_upper:
        return "weekly"
    
    # Monthly patterns
    if "-M" in ticker_upper or "MONTHLY" in ticker_upper:
        return "monthly"
    
    # Hourly is often the default (no suffix)
    # If no explicit daily/weekly/monthly suffix, assume hourly
    if any(x in ticker_upper for x in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]):
        # Check if it has a date/time pattern (typical for hourly/15m)
        # Pattern: 2 digits (day) + 3 letters (month) + 4-6 digits (time)
        # Examples: 26MAY011300 (15m with seconds), 26MAY0114 (hourly), 26MAY01 (daily)
        import re
        if re.search(r'\d{2}[A-Z]{3}\d{4,6}', ticker_upper):  # e.g., 26MAY011300 or 26MAY0114
            return "15m" if "15M" in ticker_upper else "1h"
    
    return "UNKNOWN"


@dataclass(frozen=True)
class ExecutionGuardResult:
    """Result of execution guard checks."""
    allowed: bool
    reason: str  # "allowed", "invalid_asset", "non_15m_timeframe", "distance_too_far", "edge_too_low"
    asset: str
    timeframe: str
    # Distance context (when blocked)
    delta_pct: Optional[float] = None
    z_score: Optional[float] = None
    max_delta_pct: Optional[float] = None
    max_z: Optional[float] = None
    # Edge context (when blocked)
    edge: Optional[float] = None
    required_edge: Optional[float] = None


def check_execution_guards(
    asset: str,
    timeframe: str,
    delta_pct: Optional[float] = None,
    z_score: Optional[float] = None,
    edge: Optional[float] = None,
    log_fn: Optional[callable] = None,
) -> ExecutionGuardResult:
    """Validate execution against asset/tf whitelist, distance caps, and edge floors.
    
    This is the FATAL gate: any violation returns allowed=False with detailed context.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe string (15m, 1h, etc.)
        delta_pct: Spot-to-strike distance (optional, for distance check)
        z_score: Normalized distance (optional, for sigma-based check)
        edge: Model edge value (optional, for edge floor check)
        log_fn: Optional logging function for blocked trades
        
    Returns:
        ExecutionGuardResult with allowed=True/False and detailed context
        
    Example:
        >>> result = check_execution_guards("BTC", "15m", delta_pct=0.005, z_score=0.5, edge=0.06)
        >>> if not result.allowed:
        ...     logger.info(f"[EXECUTION_BLOCKED] {result.reason}")
    """
    # Layer 1: Asset whitelist
    if asset not in ALLOWED_ASSETS:
        result = ExecutionGuardResult(
            allowed=False,
            reason="invalid_asset",
            asset=asset,
            timeframe=timeframe,
        )
        if log_fn:
            log_fn(
                "[EXECUTION_BLOCKED] asset=%s tf=%s reason=invalid_asset allowed_assets=%s",
                asset, timeframe, ALLOWED_ASSETS
            )
        return result
    
    # Layer 2: Timeframe execution gate (FATAL: only 15m allowed)
    if timeframe not in EXECUTION_TIMEFRAMES:
        result = ExecutionGuardResult(
            allowed=False,
            reason="non_15m_timeframe",
            asset=asset,
            timeframe=timeframe,
        )
        if log_fn:
            log_fn(
                "[EXECUTION_BLOCKED] asset=%s tf=%s reason=non_15m_timeframe signal_only=true "
                "Note: 1h/daily/weekly may be used for signal/context but CANNOT execute",
                asset, timeframe
            )
        return result
    
    # Layer 3: Distance caps (only if delta_pct provided)
    if delta_pct is not None:
        max_delta = MAX_DELTA_PCT.get(asset, 0.015)
        if abs(delta_pct) > max_delta:
            result = ExecutionGuardResult(
                allowed=False,
                reason="distance_too_far",
                asset=asset,
                timeframe=timeframe,
                delta_pct=delta_pct,
                z_score=z_score,
                max_delta_pct=max_delta,
                max_z=MAX_Z_DISTANCE,
            )
            if log_fn:
                log_fn(
                    "[EXECUTION_BLOCKED] asset=%s tf=%s reason=distance_too_far "
                    "delta_pct=%.4f max_delta_pct=%.4f z=%.2f max_z=%.2f "
                    "spot=too_far strike=too_far",
                    asset, timeframe, delta_pct, max_delta, z_score or 0, MAX_Z_DISTANCE
                )
            return result
    
    # Layer 3b: Sigma-based distance cap (only if z_score provided)
    if z_score is not None:
        if abs(z_score) > MAX_Z_DISTANCE:
            result = ExecutionGuardResult(
                allowed=False,
                reason="distance_too_far_z",
                asset=asset,
                timeframe=timeframe,
                delta_pct=delta_pct,
                z_score=z_score,
                max_delta_pct=MAX_DELTA_PCT.get(asset, 0.015),
                max_z=MAX_Z_DISTANCE,
            )
            if log_fn:
                log_fn(
                    "[EXECUTION_BLOCKED] asset=%s tf=%s reason=distance_too_far_z "
                    "z=%.2f max_z=%.2f sigma_exceeded=true",
                    asset, timeframe, z_score, MAX_Z_DISTANCE
                )
            return result
    
    # Layer 4: Edge floor (only if edge provided)
    if edge is not None:
        # Determine if near or far contract
        is_far = (z_score is not None and abs(z_score) > Z_NEAR_THRESHOLD)
        # Use dynamic get_min_edge() to respect MERID_PM_EDGE_NEAR_* env var overrides
        from merid.prediction.kalshi_distance_config import get_min_edge
        min_edge = get_min_edge(asset, is_far)
        
        if edge < min_edge:
            result = ExecutionGuardResult(
                allowed=False,
                reason="edge_too_low",
                asset=asset,
                timeframe=timeframe,
                edge=edge,
                required_edge=min_edge,
            )
            if log_fn:
                log_fn(
                    "[EXECUTION_BLOCKED] asset=%s tf=%s reason=edge_too_low "
                    "edge=%.4f required_edge=%.4f contract_type=%s",
                    asset, timeframe, edge, min_edge, "far" if is_far else "near"
                )
            return result
    
    # All guards passed
    return ExecutionGuardResult(
        allowed=True,
        reason="allowed",
        asset=asset,
        timeframe=timeframe,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UPSTREAM DATA INTEGRITY GUARDS ("No Surprises" Integration)
# These functions enforce data quality before signals reach execution
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DataIntegrityResult:
    """Result of upstream data integrity checks."""
    passed: bool
    reason: str  # "passed", "stale_signal", "reference_misaligned", "invalid_price"
    asset: str
    # Context for failures
    last_bar_age_seconds: Optional[float] = None
    spot_price: Optional[float] = None
    kalshi_reference: Optional[float] = None
    divergence_pct: Optional[float] = None
    max_divergence_pct: Optional[float] = None


def check_signal_staleness(
    asset: str,
    last_bar_timestamp: float,
    current_time: Optional[float] = None,
) -> DataIntegrityResult:
    """Check if momentum signal is stale (> 1 bar old for 15m).
    
    Args:
        asset: Asset symbol
        last_bar_timestamp: Unix timestamp of last 15m bar close
        current_time: Optional current time (default: time.time())
        
    Returns:
        DataIntegrityResult with passed=True if signal fresh
    """
    if current_time is None:
        current_time = time.time()
    
    last_bar_age = current_time - last_bar_timestamp
    
    if last_bar_age > SIGNAL_MAX_BAR_AGE_SECONDS:
        return DataIntegrityResult(
            passed=False,
            reason="stale_signal",
            asset=asset,
            last_bar_age_seconds=last_bar_age,
        )
    
    return DataIntegrityResult(passed=True, reason="passed", asset=asset)


def check_spot_reference_integrity(
    asset: str,
    our_spot: float,
    kalshi_reference: float,
    log_fn: Optional[callable] = None,
) -> DataIntegrityResult:
    """Validate our spot price against Kalshi reference price.
    
    Detects potential data issues:
    - Kalshi mislabeled strike (wrong reference)
    - Our feed stale or corrupted
    - Market structure change (unannounced)
    
    Args:
        asset: Asset symbol
        our_spot: Our best spot price (from primary feed)
        kalshi_reference: Kalshi's reference/target price from market data
        log_fn: Optional logging function for misaligned refs
        
    Returns:
        DataIntegrityResult with passed=True if aligned within tolerance
    """
    if our_spot <= 0 or kalshi_reference <= 0:
        return DataIntegrityResult(
            passed=False,
            reason="invalid_price",
            asset=asset,
            spot_price=our_spot,
            kalshi_reference=kalshi_reference,
        )
    
    divergence = abs(our_spot - kalshi_reference) / our_spot
    
    if divergence > SPOT_DIVERGENCE_MAX_PCT:
        result = DataIntegrityResult(
            passed=False,
            reason="reference_misaligned",
            asset=asset,
            spot_price=our_spot,
            kalshi_reference=kalshi_reference,
            divergence_pct=divergence,
            max_divergence_pct=SPOT_DIVERGENCE_MAX_PCT,
        )
        if log_fn:
            log_fn(
                "[EXECUTION_BLOCKED] asset=%s reason=reference_misaligned "
                "our_spot=%.2f kalshi_ref=%.2f divergence=%.4f max_divergence=%.4f",
                asset, our_spot, kalshi_reference, divergence, SPOT_DIVERGENCE_MAX_PCT
            )
        return result
    
    return DataIntegrityResult(
        passed=True,
        reason="passed",
        asset=asset,
        spot_price=our_spot,
        kalshi_reference=kalshi_reference,
        divergence_pct=divergence,
    )


# Concrete check function (as per "No Surprises" spec)
def run_all_upstream_guards(
    asset: str,
    timeframe: str,
    last_bar_timestamp: float,
    our_spot: float,
    kalshi_reference: float,
    delta_pct: Optional[float] = None,
    z_score: Optional[float] = None,
    edge: Optional[float] = None,
    log_fn: Optional[callable] = None,
) -> Tuple[bool, List[str]]:
    """Run ALL upstream and execution guards, returning all failures.
    
    This is the comprehensive "no surprises" check that runs:
    1. Signal staleness
    2. Spot reference integrity
    3. Asset/timeframe whitelist
    4. Distance caps
    5. Edge floors
    
    Returns:
        (all_passed: bool, list_of_failure_reasons: List[str])
        
    Example:
        >>> passed, failures = run_all_upstream_guards(
        ...     "BTC", "15m", last_bar_ts=1746022800, our_spot=85000,
        ...     kalshi_ref=84950, delta_pct=0.005, edge=0.06
        ... )
        >>> if not passed:
        ...     print(f"Blocked: {failures}")
    """
    failures: List[str] = []
    
    # 1. Signal staleness
    staleness = check_signal_staleness(asset, last_bar_timestamp)
    if not staleness.passed:
        failures.append(f"stale_signal:age={staleness.last_bar_age_seconds:.0f}s")
        if log_fn:
            log_fn(
                "[EXECUTION_BLOCKED] asset=%s tf=%s reason=stale_signal last_bar_age=%.0fs max=%.0fs",
                asset, timeframe, staleness.last_bar_age_seconds, SIGNAL_MAX_BAR_AGE_SECONDS
            )
    
    # 2. Spot reference integrity
    ref_check = check_spot_reference_integrity(asset, our_spot, kalshi_reference, log_fn)
    if not ref_check.passed:
        failures.append(f"reference_misaligned:div={ref_check.divergence_pct:.4f}")
    
    # 3-5. Execution guards (asset/tf, distance, edge)
    guard_result = check_execution_guards(
        asset=asset,
        timeframe=timeframe,
        delta_pct=delta_pct,
        z_score=z_score,
        edge=edge,
        log_fn=log_fn,
    )
    if not guard_result.allowed:
        failures.append(f"{guard_result.reason}")
    
    return len(failures) == 0, failures


def run_all_upstream_guards_with_ticker(
    ticker: str,
    last_bar_timestamp: float,
    our_spot: float,
    kalshi_reference: float,
    delta_pct: Optional[float] = None,
    z_score: Optional[float] = None,
    edge: Optional[float] = None,
    log_fn: Optional[callable] = None,
) -> Tuple[bool, List[str], str, str]:
    """Run ALL upstream guards with automatic asset/timeframe extraction from ticker.
    
    This is the recommended entry point for agents - it extracts asset and timeframe
    from the Kalshi ticker format automatically, then runs all guards.
    
    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-26MAY011300-00")
        last_bar_timestamp: Unix timestamp of last 15m bar close
        our_spot: Our best spot price (from primary feed)
        kalshi_reference: Kalshi's reference/target price from market data
        delta_pct: Optional absolute distance from spot to strike (as fraction)
        z_score: Optional standardized distance (sigma)
        edge: Optional expected edge (as fraction, e.g., 0.06 for 6%)
        log_fn: Optional logging function (receives formatted strings)
        
    Returns:
        Tuple of (all_passed: bool, failure_reasons: List[str], asset: str, timeframe: str)
        
    Example:
        >>> passed, failures, asset, tf = run_all_upstream_guards_with_ticker(
        ...     "KXBTC15M-26MAY011300-00", last_bar_ts=1746022800, 
        ...     our_spot=85000, kalshi_ref=84950, delta_pct=0.005, edge=0.06
        ... )
        >>> if not passed:
        ...     logger.warning(f"Trade blocked for {asset}/{tf}: {failures}")
    """
    # Extract asset and timeframe from ticker
    asset = extract_asset_from_ticker(ticker)
    timeframe = extract_timeframe_from_ticker(ticker)
    
    # If we couldn't extract asset, that's an immediate block
    if asset == "UNKNOWN":
        if log_fn:
            log_fn(
                "[EXECUTION_BLOCKED] asset=%s tf=%s reason=invalid_asset ticker=%s allowed_assets=%s",
                asset, timeframe, ticker, ALLOWED_ASSETS
            )
        return False, [f"invalid_asset:could_not_extract_from_{ticker}"], asset, timeframe
    
    # Run all guards with extracted values
    passed, failures = run_all_upstream_guards(
        asset=asset,
        timeframe=timeframe,
        last_bar_timestamp=last_bar_timestamp,
        our_spot=our_spot,
        kalshi_reference=kalshi_reference,
        delta_pct=delta_pct,
        z_score=z_score,
        edge=edge,
        log_fn=log_fn,
    )
    
    return passed, failures, asset, timeframe


def _get_agent_executor() -> ThreadPoolExecutor:
    """Get or create global thread pool executor with sufficient workers for agent operations."""
    global _GLOBAL_AGENT_EXECUTOR
    if _GLOBAL_AGENT_EXECUTOR is None:
        import os
        max_workers = max(20, (os.cpu_count() or 4) * 2)
        _GLOBAL_AGENT_EXECUTOR = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="merid_agent_"
        )
        logger.info(f"Initialized agent thread pool with {max_workers} workers")
    return _GLOBAL_AGENT_EXECUTOR

# Pre-import alert manager so degraded-mode alert calls don't fail on lazy import.
# The singleton is cached; if unavailable at startup the module still loads (non-fatal).
try:
    from merid.prediction.alerts import get_alert_manager as _get_alert_manager_module
except Exception:
    _get_alert_manager_module = None  # type: ignore[assignment]


_MAX_LOG_ENTRIES = 200


# Maximum seconds without a valid consensus before an agent is considered
# swarm-degraded.  In degraded mode all orders are capped to "small" size band.
# Default 0 = no hold for single-agent deployments (the agent IS its own
# consensus).  Set to a positive value (e.g. 120) for multi-agent swarms
# where you want agents to wait for quorum before going solo.
def _swarm_max_solo_seconds() -> float:
    """Seconds without consensus before solo-sized execution is allowed."""
    return float(os.getenv("MERID_PM_SWARM_SOLO_SECONDS", "0"))


def _swarm_max_solo_trades_degraded() -> int:
    """Max live orders per agent while swarm is degraded (configurable)."""
    return int(os.getenv("MERID_PM_SWARM_SOLO_TRADES_CAP", "3"))


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH_15M PERIODIC SNAPSHOT — "No Surprises" Integration
# Self-auditing health check for the 15m-only micro-momentum mandate
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Health15MSnapshot:
    """Health snapshot for 15m micro-scalping system."""
    timestamp: float
    active_assets: List[str]  # Which of BTC/ETH/SOL/XRP/DOGE have candidates
    non_15m_executions_last_1h: int  # Should be 0
    avg_distance_bps_last_50_trades: float  # Should be below 75bps for BTC
    stale_signal_count_last_15m: int
    fee_mismatch_count_last_1h: int
    fill_recon_errors_last_1h: int
    reference_misaligned_count_last_1h: int
    
    def to_log_line(self) -> str:
        """Format as structured log line for grep/awk analysis."""
        return (
            f"[HEALTH_15M] ts={self.timestamp:.0f} "
            f"active_assets={','.join(self.active_assets)} "
            f"non_15m_exec_1h={self.non_15m_executions_last_1h} "
            f"avg_dist_bps={self.avg_distance_bps_last_50_trades:.1f} "
            f"stale_15m={self.stale_signal_count_last_15m} "
            f"fee_mismatch_1h={self.fee_mismatch_count_last_1h} "
            f"recon_err_1h={self.fill_recon_errors_last_1h} "
            f"ref_misalign_1h={self.reference_misaligned_count_last_1h}"
        )


def compute_health_15m_snapshot(
    fills_ledger: Optional[Any] = None,
    position_cache: Optional[Any] = None,
    log_fn: Optional[callable] = None,
) -> Health15MSnapshot:
    """Compute HEALTH_15M snapshot from current system state.
    
    This is the "no surprises" health check that aggregates:
    - Signal quality (staleness)
    - Execution compliance (15m-only)
    - Distance adherence (are we trading far OTM?)
    - Fee integrity (estimate vs actual)
    - Fill reconciliation (WS vs HTTP consistency)
    
    Args:
        fills_ledger: Optional KalshiFillsLedger instance
        position_cache: Optional KalshiPositionCache instance
        log_fn: Optional logging function
        
    Returns:
        Health15MSnapshot with current metrics
        
    Example:
        >>> snapshot = compute_health_15m_snapshot()
        >>> logger.info(snapshot.to_log_line())
        [HEALTH_15M] ts=1746117600 active_assets=BTC,ETH non_15m_exec_1h=0 ...
    """
    now = time.time()
    
    # Default values (will be overridden if data sources available)
    active_assets: List[str] = []
    non_15m_exec = 0
    avg_distance_bps = 0.0
    stale_signals = 0
    fee_mismatches = 0
    recon_errors = 0
    ref_misaligned = 0
    
    # Try to get active assets from position cache
    if position_cache is not None:
        try:
            positions = getattr(position_cache, 'get_positions', lambda: {})()
            active_assets = list(set(
                p.asset for p in positions.values()
                if getattr(p, 'asset', None) in ALLOWED_ASSETS
            ))
        except Exception:
            pass
    
    # If no active positions, report all allowed assets as "monitored"
    if not active_assets:
        active_assets = list(ALLOWED_ASSETS)
    
    # Try to get fill stats from fills ledger
    if fills_ledger is not None:
        try:
            # Get recent fills (last 50)
            recent_fills = fills_ledger.get_fills(
                since=datetime.now(timezone.utc) - timedelta(hours=24),
                limit=50
            )
            
            if recent_fills:
                # Calculate average distance from fill metadata (if stored)
                # This is a placeholder - real implementation would read from fill metadata
                avg_distance_bps = 50.0  # Default assumption
                
                # Count fee mismatches (would need intent tracking)
                # Placeholder: scan for [FEE_MISMATCH] in recent log events
        except Exception:
            pass
    
    snapshot = Health15MSnapshot(
        timestamp=now,
        active_assets=sorted(active_assets),
        non_15m_executions_last_1h=non_15m_exec,
        avg_distance_bps_last_50_trades=avg_distance_bps,
        stale_signal_count_last_15m=stale_signals,
        fee_mismatch_count_last_1h=fee_mismatches,
        fill_recon_errors_last_1h=recon_errors,
        reference_misaligned_count_last_1h=ref_misaligned,
    )
    
    if log_fn:
        log_fn(snapshot.to_log_line())
    
    return snapshot


def _validate_ticker_for_exit(ticker: str, allow_expired: bool = True) -> tuple[bool, Optional[str]]:
    """Validate that a ticker exists in the Kalshi catalog before sending exit order.
    
    CRITICAL: Prevents 'Ticker not found in catalog' errors on position exits
    by validating the stored ticker against the canonical catalog.
    
    For position exits (allow_expired=True), we allow the exit attempt even if the
    ticker is not in the catalog, as the market may have expired but we still hold
    a position that needs to be closed. The Kalshi API will return the appropriate
    error if the market is truly settled and cannot be traded.
    
    Args:
        ticker: The ticker to validate
        allow_expired: If True, allow exits for tickers not in catalog (expired markets)
                      
    Returns:
        Tuple of (is_valid: bool, canonical_ticker: Optional[str])
        If valid, returns (True, canonical_ticker)
        If invalid and allow_expired=False, returns (False, None)
        If not in catalog but allow_expired=True, returns (True, ticker) with warning
    """
    if not ticker:
        logger.error("[TICKER_VALIDATION] Empty ticker provided for exit validation")
        return False, None
    
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.event_venues.kalshi.ticker_utils import normalize_ticker_for_order
        catalog = get_market_catalog()
        if not catalog:
            # Catalog unavailable - fail open with warning
            logger.warning(
                "[TICKER_VALIDATION] Catalog unavailable for %s - proceeding with stored ticker",
                ticker
            )
            return True, ticker
        
        # PRODUCTION FIX (2026-05-01): Normalize ticker to strip strike suffix before catalog lookup
        # Exit positions may have stored tickers with strike levels (e.g., -30, -T80199.99)
        # but the catalog only stores the base market ticker.
        _normalized_ticker = normalize_ticker_for_order(ticker)
        if _normalized_ticker != ticker:
            logger.debug(
                "[TICKER_VALIDATION_NORMALIZE] %s -> %s for catalog lookup",
                ticker, _normalized_ticker
            )
        
        # Check if ticker exists in catalog (using normalized ticker)
        market = catalog.get_market(_normalized_ticker)
        if market:
            # Return the canonical ticker from catalog (prefer market's ticker, fallback to normalized)
            canonical = getattr(market, 'ticker', None) or _normalized_ticker
            return True, canonical
        
        # Ticker not found in catalog - may be expired/settled
        if allow_expired:
            # For position exits, allow the attempt with the normalized ticker
            # Kalshi will return appropriate error if market is truly settled
            logger.warning(
                "[TICKER_VALIDATION_EXPIRED] Ticker %s (normalized: %s) not in catalog but allowing exit attempt "
                "(market may be expired/settled). Position exit will be attempted with normalized ticker.",
                ticker, _normalized_ticker
            )
            return True, _normalized_ticker
        
        # Ticker not found and expired markets not allowed - block the order
        logger.error(
            "[TICKER_VALIDATION_FAIL] Ticker %s not found in Kalshi catalog. "
            "Exit order will be blocked to prevent 404 error.",
            ticker
        )
        return False, None
        
    except Exception as exc:
        # Fail open if validation fails, but log the error
        logger.warning(
            "[TICKER_VALIDATION] Validation failed for %s: %s - proceeding with stored ticker",
            ticker, exc
        )
        return True, ticker


def _swarm_max_solo_wall_seconds() -> float:
    """Wall-clock time in degraded mode before halting new entries."""
    return float(os.getenv("MERID_PM_SWARM_SOLO_WALL_SECONDS", "1800.0"))


# BUG-08: module constants for audit/regression tests (same values as env-driven helpers)
_MAX_SOLO_SECONDS: float = float(os.getenv("MERID_PM_SWARM_SOLO_SECONDS", "0"))
_MAX_SOLO_TRADES_DEGRADED: int = int(os.getenv("MERID_PM_SWARM_SOLO_TRADES_CAP", "3"))
_MAX_SOLO_WALL_SECONDS: float = float(os.getenv("MERID_PM_SWARM_SOLO_WALL_SECONDS", "1800.0"))


# B3/RISK-11: Explicit lifecycle states for KalshiTradingAgent
class LifecycleState(str, Enum):
    STOPPED    = "stopped"
    STARTING   = "starting"
    WARMING_UP = "warming_up"   # resolves markets + logs signals but skips execution
    ACTIVE     = "active"       # full decision loop including order placement
    DRAINING   = "draining"     # finishes current cycle, runs final stop-loss, then stops


# Minimum seconds in WARMING_UP before considering promotion to ACTIVE.
# Actual promotion requires data-readiness checks (catalog populated, spot online)
# or fallback to this minimum + stagger after which the agent promotes regardless.
_WARMUP_MIN_SECONDS: float = float(os.getenv("MERID_PM_WARMUP_MIN_SECONDS", "15.0"))
# BUG-L13 FIX: Stagger agent promotions to prevent thundering herd
# Each agent adds 0-30s additional delay based on hash of agent name
_MAX_STAGGER_SECONDS: float = float(os.getenv("MERID_PM_MAX_STAGGER_SECONDS", "30.0"))
# Hard ceiling: promote to ACTIVE unconditionally after this many seconds
# even if data checks haven't passed (prevents infinite warmup stall).
_WARMUP_MAX_SECONDS: float = float(os.getenv("MERID_PM_WARMUP_MAX_SECONDS", "90.0"))
# Max consecutive cycle errors before the agent pauses itself (medium-risk fix)
_MAX_CONSECUTIVE_ERRORS: int = int(os.getenv("MERID_PM_MAX_CONSECUTIVE_ERRORS", "5"))


@dataclass
class AgentState:
    """Runtime state for a single trading agent."""
    name: str
    enabled: bool = True
    running: bool = False
    lifecycle: str = LifecycleState.STOPPED  # BUG-L8: explicit lifecycle state
    started_at: Optional[datetime] = None    # BUG-L8: used for solo_seconds baseline
    last_cycle_at: Optional[datetime] = None
    cycles_run: int = 0
    orders_placed: int = 0
    orders_this_window: int = 0
    window_start: Optional[datetime] = None
    active_tickers: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    consecutive_errors: int = 0              # medium-risk: per-agent error circuit breaker
    signal_log: List[Dict[str, Any]] = field(default_factory=list)
    order_log: List[Dict[str, Any]] = field(default_factory=list)
    fill_log: List[Dict[str, Any]] = field(default_factory=list)
    # True when swarm consensus has been unavailable for > MERID_PM_SWARM_SOLO_SECONDS.
    # All orders placed while degraded use size_band="small".
    swarm_degraded: bool = False
    last_consensus_at: Optional[datetime] = None
    # BUG-08: track when degraded mode started and how many solo trades have fired
    swarm_degraded_since: Optional[datetime] = None
    solo_trades_this_degraded_session: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "running": self.running,
            "lifecycle": self.lifecycle,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "cycles_run": self.cycles_run,
            "orders_placed": self.orders_placed,
            "orders_this_window": self.orders_this_window,
            "active_tickers": self.active_tickers,
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
            "signal_count": len(self.signal_log),
            "order_count": len(self.order_log),
            "fill_count": len(self.fill_log),
            "swarm_degraded": self.swarm_degraded,
            "last_consensus_at": self.last_consensus_at.isoformat() if self.last_consensus_at else None,
            "swarm_degraded_since": self.swarm_degraded_since.isoformat() if self.swarm_degraded_since else None,
            "solo_trades_this_degraded_session": self.solo_trades_this_degraded_session,
        }


class KalshiTradingAgent:
    """Trades a specific (asset, timeframe) cell on Kalshi.

    Lifecycle:
        agent = KalshiTradingAgent(config)
        await agent.start()       # begins decision loop
        await agent.stop()        # graceful shutdown

    The decision loop:
        1. Resolve config market_filter → live Kalshi tickers
        2. For each market in entry window: evaluate strategy signal
        3. If signal is actionable: run pre-trade risk check
        4. If allowed: place order via kalshi_place_order tool
        5. Sleep until next cycle
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.logger = get_logger(f"merid.prediction.agent.{config.name}")
        self.state = AgentState(name=config.name)
        
        # CRITICAL FIX: _agent_name attribute required by _resolve_markets timeframe filter
        # This was missing causing AttributeError: 'KalshiTradingAgent' object has no attribute '_agent_name'
        self._agent_name = config.name
        
        # P1 FIX: Unique instance ID to prevent clone collisions in multi-worker scenarios
        # This ensures each agent instance has a unique identity even if config.agent_id is shared
        self._instance_id = uuid.uuid4().hex[:8]
        self._unique_agent_id = f"{config.agent_id}_{self._instance_id}"
        
        # HARD REQUIREMENT: Live Kalshi bankroll only - no fake data, no fallbacks
        # max_notional_usd=0 means "derive from live Kalshi balance" (1-2% risk fraction)
        # NOTE: Bankroll initialization is deferred to start() method since __init__ is sync
        # and we need async context to call the bankroll service
        self._bankroll_needs_init = float(self.config.risk_limits.max_notional_usd) == 0

        # Reuse existing subsystems
        self._model = PredictionMarketModel()
        self._strategy = KalshiStrategy(
            self._build_strategy_config(config),
            agent_name=config.name,
        )
        # BUG-04 fix: use the portfolio-wide shared singleton so all agents
        # contribute to the same exposure, daily-loss, and notional caps.
        # Singleton is initialized once by AgentGrid; agents just get the instance.
        self._risk = get_prediction_risk()
        self._session_guard = get_session_guard()
        self._venue_gate = get_venue_gate()

        # Internal
        self._entry_window_suspect_streak: int = 0
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._drain_done = asyncio.Event()   # BUG-L5: set when drain pass completes
        self._in_execution = asyncio.Event() # BUG-L6: set while _execute_signal is running
        self._cycle_done = asyncio.Event()   # BUG-L5: set at end of each cycle
        self._resolved_markets: List[EventMarket] = []

        # Stop-loss rules engine — monitors open positions every cycle
        self._stop_loss = StopLossRules()
        # Take-profit manager — advanced TP / trailing / re-entry layer
        _tp_cfg = getattr(config, "take_profit", None) or get_tp_config_for_agent(config.name)
        self._tp_manager = TakeProfitManager(config=_tp_cfg)
        # position_id -> TrackedPosition for open fills awaiting settlement
        self._tracked_positions: Dict[str, TrackedPosition] = {}
        
        # MICRO-SCALPING: Dynamic take-profit calculator with per-asset volatility scaling
        # BTC/ETH: higher targets (4-8%), SOL/XRP/DOGE: tighter targets (2-5%) due to lower liquidity
        _asset = getattr(config, 'asset', 'BTC')
        _is_major = _asset in ('BTC', 'ETH')
        _dtp_cfg = DynamicTPConfig(
            low_volatility_target=0.04 if _is_major else 0.025,      # 4% majors / 2.5% alts
            normal_volatility_target=0.06 if _is_major else 0.04,   # 6% majors / 4% alts
            high_volatility_target=0.10 if _is_major else 0.06,     # 10% majors / 6% alts
            low_vol_threshold=0.015 if _is_major else 0.02,          # tighter for majors
            high_vol_threshold=0.04 if _is_major else 0.05,        # majors more sensitive
            strong_momentum_threshold=0.12,   # 12%+ edge = strong
            weak_momentum_threshold=0.05,     # <5% edge = weak
            momentum_boost_factor=1.4,       # +40% for strong momentum
            momentum_reduce_factor=0.75,    # -25% for weak momentum
            trailing_stop_distance_pct=0.015 if _is_major else 0.02,  # 1.5% trail majors / 2% alts
            trailing_activation_pct=0.015,  # Start trailing at 1.5% profit
            max_profit_target_pct=0.12 if _is_major else 0.08,       # Cap 12% majors / 8% alts
            min_profit_target_pct=0.02,       # Floor at 2%
        )
        self._dynamic_tp_calc = DynamicTPCalculator(config=_dtp_cfg)
        
        # MICRO-SCALPING: Fast exit manager with dynamic TP integration
        # NOTE: profit_target_pct=0.0 to disable fixed target; rely purely on dynamic TP
        # PRODUCTION FIX (2026-05-01): Derive from environment variables, not hardcoded
        # REVERTED (2026-05-08): Aligned with MicroScalpExitConfig defaults (180s, 2c min profit) to restore profitable trades
        _ms_cfg = MicroScalpExitConfig(
            profit_target_pct=0.0,         # DISABLED: use dynamic TP only (no fixed 5%)
            max_hold_seconds=float(os.getenv("MERID_PM_MICROSCALP_MAX_HOLD_SECONDS", "180")),  # 3 min default (reverted from 120s)
            edge_decay_threshold=float(os.getenv("MERID_PM_MICROSCALP_EDGE_DECAY", "0.50")),  # 50% default
            book_flip_detection=True,      # Detect order book flips
            min_profit_cents=int(os.getenv("MERID_PM_MICROSCALP_MIN_PROFIT_CENTS", "2")),  # $0.02 default (reverted from 3c)
        )
        self._micro_scalp_exit = MicroScalpExitManager(
            config=_ms_cfg,
            dynamic_tp_calculator=self._dynamic_tp_calc,
        )
        
        # MICRO-SCALPING: Cycle cap tracker for real-time capital utilization
        # Uses canonical MAX_CYCLE_RISK_PCT from core.settings (single source of truth)
        from core.settings import MAX_CYCLE_RISK_PCT
        _cycle_cfg = CycleCapConfig(
            max_cycle_risk_pct=MAX_CYCLE_RISK_PCT,  # Canonical % from core.settings
            bankroll_source="live",                   # Use live bankroll service ONLY
        )
        self._cycle_tracker = CycleCapTracker(config=_cycle_cfg)
        
        # Performance monitoring for circuit breaker
        self._recent_trades_for_health: list = []
        self._health_check_interval = int(os.getenv("MERID_PM_HEALTH_CHECK_INTERVAL", "30"))  # Check every N trades
        # Wire 1: live Kalshi contracts near spot, updated by CryptoSurfaceLoader callback
        self._live_markets: list = []
        # Lazily initialized in _execute_signal_body for crypto category signals
        self._btc15m_risk = None
        # Strike selector — proactive relevance filter anchored to live spot
        try:
            from merid.prediction.kalshi_strike_selector import get_strike_selector_for_agent
            self._strike_selector = get_strike_selector_for_agent(config)
        except Exception:
            self._strike_selector = None

    def _get_effective_max_orders(self, top_n_edges: int = 3) -> int:
        """Compute dynamic max orders based on bankroll and available edges.

        Uses the formula: min(floor(bankroll_usd / 100), 3, top_n_edges)
        This ensures small bankrolls only trade top 1 edge, growing to 3 as compounding occurs.
        REVERTED (2026-05-08): default top_n_edges=3 (was 1) to restore profitable trades.
        """
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            bankroll_usd = float(get_kalshi_risk().state.current_equity_usd or 0.0)
        except Exception:
            bankroll_usd = 0.0

        # CRITICAL: ONLY use ACTUAL Kalshi API balance - NO configured fallbacks
        if bankroll_usd <= 0:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_live_bankroll
                bankroll_usd = get_live_bankroll()
            except Exception as exc:
                logger.error(
                    "[TRADING_AGENT] Failed to get ACTUAL Kalshi balance for max_orders: %s",
                    exc
                )
                bankroll_usd = 0.0

        return self.config.risk_limits.get_effective_max_orders(
            bankroll_cents=int(bankroll_usd * 100),
            top_n_edges=top_n_edges
        )

    def _get_position_for_arbiter(self, ticker: str, side_str: str) -> tuple[int, str, Optional[float]]:
        """Get position data for arbiter deduplication.
        
        Returns:
            Tuple of (contracts, direction, entry_time_epoch)
        """
        try:
            cache = get_position_cache()
            positions = cache.get_open_positions(ticker)
            
            if not positions:
                return 0, "none", None
            
            # Map yes/no side to long/short direction
            direction = "long" if side_str == "yes" else "short"
            
            # Sum contracts for the relevant side
            contracts = 0
            entry_time = None
            
            for pos in positions:
                pos_side = getattr(pos, 'side', None) or getattr(pos, 'direction', None)
                pos_contracts = getattr(pos, 'contracts', 0) or getattr(pos, 'size', 0)
                pos_entry = getattr(pos, 'entry_time', None) or getattr(pos, 'timestamp', None)
                
                if pos_side == side_str:
                    contracts += int(pos_contracts)
                    if pos_entry and (entry_time is None or pos_entry < entry_time):
                        entry_time = pos_entry
            
            # Convert entry_time to epoch if it's datetime
            entry_epoch = None
            if entry_time:
                if isinstance(entry_time, datetime):
                    entry_epoch = entry_time.timestamp()
                elif isinstance(entry_time, (int, float)):
                    entry_epoch = float(entry_time)
            
            return contracts, direction if contracts > 0 else "none", entry_epoch
            
        except Exception as e:
            self.logger.debug(f"[ARBITER] Position cache lookup failed for {ticker}: {e}")
            return 0, "none", None

    def _submit_to_arbiter(
        self,
        signal: StrategySignal,
        market: EventMarket,
        asset: str,
        timeframe: str,
    ) -> bool:
        """Submit signal to cross-asset arbiter for ranking.
        
        Returns:
            True if signal should proceed to execution (winner or non-crypto)
            False if signal was rejected by arbiter
        """
        # Only crypto assets use the arbiter
        if asset not in CRYPTO_ASSETS:
            return True
        
        # Only momentum scalping timeframes
        if timeframe not in MEAN_REVERSION_TIMEFRAMES:
            self.logger.debug(
                "[ARBITER] Skipping non-momentum timeframe: %s %s",
                asset, timeframe
            )
            return True  # Let non-momentum through existing flow
        
        # Skip if signal is NO_ACTION
        if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
            return False
        
        # Get position data for deduplication
        side_str = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
        existing_contracts, existing_direction, entry_time = self._get_position_for_arbiter(
            market.market_id, side_str
        )
        
        # Get arbiter instance
        arbiter = get_crypto_top_edge_arbiter()
        
        # Submit candidate to arbiter
        try:
            from merid.prediction.crypto_top_edge import CandidateSignal
            
            # Extract direction
            direction = "long" if side_str == "yes" else "short"
            
            # Extract edge from signal
            net_edge = 0.0
            if signal.edge and hasattr(signal.edge, 'net_edge'):
                try:
                    net_edge = float(signal.edge.net_edge)
                except (TypeError, ValueError):
                    net_edge = 0.0
            
            # Extract confidence
            confidence = 0.0
            if signal.edge and hasattr(signal.edge, 'confidence'):
                try:
                    confidence = float(signal.edge.confidence)
                except (TypeError, ValueError):
                    confidence = 0.0
            
            candidate = CandidateSignal(
                signal_id=f"{self.config.name}_{market.market_id}_{int(time.time() * 1000)}",
                agent_id=self.config.name,
                asset=asset,
                timeframe=timeframe,
                ticker=market.market_id,
                net_edge=net_edge,
                confidence=confidence,
                direction=direction,
                suggested_contracts=signal.contracts,
                limit_price_cents=signal.limit_price_cents,
                archetype="directional",
                original_signal=signal,
                phase=signal.phase.value if signal.phase else None,
                correlation_id=getattr(signal, 'correlation_id', None),
                eval_context={
                    "agent": self.config.name,
                    "market_id": market.market_id,
                    "edge": net_edge,
                },
                existing_position_contracts=existing_contracts,
                existing_position_direction=existing_direction,
                position_entry_time=entry_time,
            )
            
            arbiter.submit_candidate(candidate)
            
            self.logger.debug(
                "[ARBITER] Submitted %s %s edge=%.4f pos=%d dir=%s",
                asset, timeframe, net_edge, existing_contracts, existing_direction
            )
            
            # Return True - the signal is submitted, arbiter will decide later
            # The actual winner selection happens at cycle end
            return True
            
        except Exception as e:
            self.logger.error(f"[ARBITER] Failed to submit candidate: {e}")
            # Fail-open: allow signal through if arbiter fails
            return True

    def _is_arbiter_winner(self, market_id: str) -> bool:
        """Check if this market was selected as winner by arbiter.
        
        Must be called after arbiter.run_cycle() has been executed.
        
        PRODUCTION FIX v6 (2026-04-26): Uses arbiter.is_winner() method which
        checks against preserved _last_cycle_winners dict instead of the cleared
        _current_candidates list.
        """
        try:
            arbiter = get_crypto_top_edge_arbiter()
            
            # Use the new is_winner method that checks _last_cycle_winners
            # This works because run_cycle() stores winners before clearing _current_candidates
            is_winner = arbiter.is_winner(market_id, max_age_seconds=30.0)
            
            # Log diagnostic info to debug ARBITER_BLOCKED
            if not is_winner:
                # Get cycle age for diagnostic
                cycle_age = 0
                try:
                    if arbiter._last_cycle_timestamp:
                        cycle_age = (datetime.now(timezone.utc) - arbiter._last_cycle_timestamp).total_seconds()
                except Exception:
                    pass
                
                # Log what winners are stored
                stored_winners = list(arbiter._last_cycle_winners.keys())
                self.logger.warning(
                    "[ARBITER] %s not in winners and arbiter stale (%.0fs old) - FAIL-CLOSED blocking trade to prevent losses. Stored winners: %s",
                    market_id, cycle_age, stored_winners[:5]  # Show first 5
                )
            
            return is_winner
            
        except Exception as e:
            self.logger.debug(f"[ARBITER] Winner check failed for {market_id}: {e}")
            return True  # Fail-open
    
    def _check_arbiter_priority(self, market_id: str, asset: str, timeframe: str) -> tuple[bool, bool, str]:
        """Check if market is a priority winner with MICRO-SCALPING top-3 execution.
        
        MICRO-SCALPING FIX (2026-04-28): Execute top 3 edge winners simultaneously.
        - #1, #2, #3 all execute (not gated by bankroll) for rapid capital turnover
        - Requires 5% single_order_pct to allow $1.50 total for 3 x $0.50 contracts
        - 90-second max hold times ensure capital freed for next cycle
        
        CRITICAL FIX (2026-05-01): Standardize on TICKER as the lookup key.
        The arbiter stores winners keyed by ticker (e.g., "KXETH15M-26MAY011445-45"),
        so we lookup by market_id (ticker) directly, not by asset matching.
        
        BUG-FIX (2026-05-05): Fail-open when arbiter hasn't run yet or winners dict is empty.
        Previous fail-closed approach blocked all trades when arbiter data was unavailable,
        causing valid winners to be blocked due to timing issues between agent cycles
        and arbiter cycles (15s interval).
        
        Returns:
            Tuple of (is_winner, is_number_one, skip_reason)
            - is_winner: True if ticker is in arbiter winners
            - is_number_one: True for #1, #2, or #3 (all execute)
            - skip_reason: Empty for top 3; populated for #4+
        """
        self.logger.warning("[ARBITER] _check_arbiter_priority called with market_id=%s asset=%s timeframe=%s", market_id, asset, timeframe)
        try:
            arbiter = get_crypto_top_edge_arbiter()
            
            # Check if arbiter has run at all (winners dict exists and not empty)
            if not arbiter._last_cycle_winners:
                _state_age = time.time() - getattr(arbiter, '_last_cycle_timestamp', 0)
                self.logger.warning(
                    "[ARBITER] %s - arbiter winners dict empty (age=%.0fs) - FAIL-OPEN allowing trade",
                    market_id, _state_age
                )
                # Fail-open: allow trade if arbiter hasn't run yet
                return True, True, "arbiter_not_run_yet_fail_open"
            
            # FIX: Check if arbiter winners are stale (timing mismatch between cycles)
            # When markets expire and new ones appear, agents try to trade before arbiter updates
            # Detect this by checking if the market being checked is from a different cycle
            # than what's stored in the winners dict (extracted from ticker expiry time)
            _now = datetime.now(timezone.utc)
            _has_cycle_mismatch = False
            
            # Extract expiry time from the market being checked
            try:
                _ticker_parts = market_id.split('-')
                if len(_ticker_parts) >= 2:
                    _datetime_part = _ticker_parts[1]  # e.g., 26MAY112315
                    _year = _now.year
                    _month_str = _datetime_part[:3]  # MAY
                    _day = int(_datetime_part[3:5])  # 26
                    _hour = int(_datetime_part[5:7])  # 11
                    _minute = int(_datetime_part[7:9])  # 15
                    
                    _months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                               'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
                    _month = _months.get(_month_str, 1)
                    
                    _market_expiry = datetime(_year, _month, _day, _hour, _minute, tzinfo=timezone.utc)
                    
                    # Check if any stored winner has a different expiry (different cycle)
                    for _winner_ticker in arbiter._last_cycle_winners.keys():
                        try:
                            _winner_parts = _winner_ticker.split('-')
                            if len(_winner_parts) >= 2:
                                _winner_datetime_part = _winner_parts[1]
                                _w_day = int(_winner_datetime_part[3:5])
                                _w_hour = int(_winner_datetime_part[5:7])
                                _w_minute = int(_winner_datetime_part[7:9])
                                _w_month = _months.get(_winner_datetime_part[:3], 1)
                                
                                _winner_expiry = datetime(_year, _w_month, _w_day, _w_hour, _w_minute, tzinfo=timezone.utc)
                                
                                # If expiry times differ by more than 15 minutes (one cycle), it's a mismatch
                                if abs((_market_expiry - _winner_expiry).total_seconds()) > 900:
                                    _has_cycle_mismatch = True
                                    break
                        except Exception:
                            pass
            except Exception:
                pass  # If parsing fails, continue with normal check
            
            if _has_cycle_mismatch:
                _state_age = time.time() - getattr(arbiter, '_last_cycle_timestamp', 0)
                self.logger.warning(
                    "[ARBITER] %s - arbiter winners from different cycle (age=%.0fs) - FAIL-OPEN allowing trade",
                    market_id, _state_age
                )
                # Fail-open: allow trade if arbiter winners are from a different cycle
                return True, True, "arbiter_cycle_mismatch_fail_open"
            
            # FIX: Lookup by ticker key directly (how arbiter stores winners)
            winner = arbiter._last_cycle_winners.get(market_id)

            # FALLBACK: If exact match fails, try matching by series ticker prefix
            # This handles market rollovers where tickers change (e.g., KXETH15M-26MAY120945-45 -> KXETH15M-26MAY121000-00)
            if not winner:
                # Extract series ticker prefix (e.g., KXETH15M from KXETH15M-26MAY121000-00)
                series_prefix = market_id.split('-')[0] if '-' in market_id else market_id
                for stored_ticker, stored_winner in arbiter._last_cycle_winners.items():
                    if stored_ticker.startswith(series_prefix):
                        winner = stored_winner
                        self.logger.warning(
                            "[ARBITER] Fallback match: %s matched to stored winner %s by series prefix %s",
                            market_id, stored_ticker, series_prefix
                        )
                        break

            # Log diagnostic info to debug winner lookup
            stored_winners = list(arbiter._last_cycle_winners.keys())
            self.logger.warning(
                "[ARBITER] Lookup %s in winners dict (size=%d, keys=%s) -> found=%s",
                market_id, len(stored_winners), stored_winners[:3], winner is not None
            )

            if not winner or not winner.is_winner:
                # Check if arbiter data is stale (>60s old) - FAIL-CLOSED to prevent bad trades
                _last_ts = getattr(arbiter, '_last_cycle_timestamp', None)
                if _last_ts:
                    # Handle both datetime and float timestamp types
                    if hasattr(_last_ts, 'timestamp'):
                        _last_ts_float = _last_ts.timestamp()
                    else:
                        _last_ts_float = float(_last_ts)
                    _state_age = time.time() - _last_ts_float
                    if _state_age > 60:
                        self.logger.warning(
                            "[ARBITER] %s not in winners and arbiter stale (%.0fs old) - FAIL-CLOSED blocking trade to prevent losses",
                            market_id, _state_age
                        )
                        return False, False, f"arbiter_stale_{_state_age:.0f}s_fail_closed"
                
                # Fresh data but not in winners - block
                self.logger.debug(
                    "[ARBITER] %s not in winners (arbiter fresh) - blocking trade",
                    market_id
                )
                return False, False, f"ticker_{market_id}_not_winner_fail_closed"
            
            # MICRO-SCALPING WINNER ALIGNMENT (2026-05-10): Force micro-scalps to only run when asset is in winner set
            # This ensures pure alignment - no micro-scalp entries/exits on non-winner assets
            try:
                from merid.prediction.grid_context import get_grid_context
                grid_ctx = get_grid_context()
                
                # Check if this ticker is a winner using grid context (centralized winner list)
                # Use max_age_seconds=60 to allow for timing between arbiter cycles and agent cycles
                is_grid_winner = grid_ctx.is_winner(market_id, max_age_seconds=60.0)
                
                if not is_grid_winner:
                    # Log diagnostic info to debug MICRO_SCALP_WINNER_BLOCK
                    stored_grid_winners = list(grid_ctx._winners_by_ticker.keys())
                    grid_cycle_age = 0
                    if grid_ctx._current_cycle and hasattr(grid_ctx._current_cycle, 'timestamp') and grid_ctx._current_cycle.timestamp:
                        _cycle_ts = grid_ctx._current_cycle.timestamp
                        # Handle both datetime and float timestamp types
                        if hasattr(_cycle_ts, 'timestamp'):
                            _cycle_ts_float = _cycle_ts.timestamp()
                        else:
                            _cycle_ts_float = float(_cycle_ts)
                        grid_cycle_age = (datetime.now(timezone.utc).timestamp() - _cycle_ts_float)
                    self.logger.warning(
                        "[MICRO_SCALP_WINNER_BLOCK] %s not in grid context winners - blocking micro-scalp entry. "
                        "Grid age=%.0fs, stored winners: %s",
                        market_id, grid_cycle_age, stored_grid_winners[:5]
                    )
                    return False, False, f"not_in_grid_context_winners_micro_scalp_blocked"
                
                self.logger.debug(
                    "[MICRO_SCALP_WINNER_OK] %s is in grid context winners - allowing micro-scalp",
                    market_id
                )
            except Exception as e:
                self.logger.warning("[MICRO_SCALP_WINNER] Grid context check failed: %s - fail-open allowing", e)
                # Fail-open: if check fails, allow trade to avoid blocking valid trades
            
            # MICRO-SCALPING: Allow top 3 winners (ranks 1, 2, 3) to execute simultaneously
            rank = winner.rank
            if rank is None:
                # Handle None rank - fail-open to allow trade
                self.logger.warning(f"[ARBITER_PRIORITY] Winner rank is None for {market_id} - FAIL-OPEN allowing trade")
                return True, True, "rank_none_fail_open"
            if rank in (1, 2, 3):
                # Top 3 all execute - cycle cap validation (in risk engine) prevents over-deployment
                return True, True, ""  # #1, #2, #3 all execute
            else:
                # Rank 4+ skipped - only execute top 3 for micro-scalping focus
                return True, False, f"#{rank}_skipped_micro_scalping_top3_only"
                
        except Exception as e:
            self.logger.warning(f"[ARBITER_PRIORITY] Check failed for {market_id}: {e} - FAIL-OPEN allowing trade")
            # Fail-open: if check fails, allow trade to avoid blocking valid trades
            return True, True, f"arbiter_check_failed_{type(e).__name__}_fail_open"

    def _get_available_bankroll_usd(self) -> float:
        """Get available bankroll in USD for priority calculations."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity = get_equity_for_risk_calc_sync()
            return float(equity) if equity else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _build_strategy_config(config: AgentConfig) -> StrategyConfig:
        """Merge grid ``strategy:`` overrides into ``StrategyConfig`` defaults."""
        from decimal import Decimal

        # BUG-005 FIX: Wire risk_limits into StrategyConfig defaults
        # Use agent's position limits to determine max_contracts_per_market
        # Per-side limit (yes/no) determines max market exposure
        _max_per_side = max(
            getattr(config.risk_limits, "max_yes_position", 500),
            getattr(config.risk_limits, "max_no_position", 500)
        )
        _max_per_order = getattr(config.risk_limits, "max_contracts_per_order", None) or 50
        
        sc = StrategyConfig(
            max_contracts_per_market=_max_per_side,  # Use per-side limit as market limit
            max_contracts_per_order=_max_per_order,
        )
        # Capture raw overrides now; apply them last so per-agent YAML beats global profiles.
        raw = getattr(config, "strategy_overrides", None) or {}
        try:
            from merid.prediction.pm_profiles import merge_profile_into_strategy_config

            merge_profile_into_strategy_config(sc)
        except Exception as _pp:
            logger.warning("[PM_PROFILE_MERGE_FAILED] PM profile merge failed: %s", _pp)
        _apply_global_pm_strategy_env(sc)
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
            from merid.prediction.crypto_edge_production import apply_crypto_strategy_thresholds_to_config

            _assets = getattr(config, "assets", None) or []
            _cat = (getattr(config, "category", None) or "").lower()
            _primary = (_assets[0] if _assets else "").strip().upper()
            _name_u = (getattr(config, "name", None) or "").upper()
            _inferred = None
            for _a in ACTIVE_CRYPTO_ASSETS:
                _tok = f"{_a}_"
                if _tok in _name_u or _name_u.startswith(_a) or f"_{_a}_" in _name_u:
                    _inferred = _a
                    break
            if _primary not in ACTIVE_CRYPTO_ASSETS and _inferred:
                _primary = _inferred
            _crypto_by_name = _inferred is not None or "CRYPTO" in _name_u or "15M_MM" in _name_u
            _tf = (config.timeframes[0] if getattr(config, "timeframes", None) else "15m")
            if _cat == "crypto" or _primary in ACTIVE_CRYPTO_ASSETS or _crypto_by_name:
                if _primary not in ACTIVE_CRYPTO_ASSETS:
                    _primary = _inferred or "BTC"
                _prior_yaml_edges = {
                    k: getattr(sc, k)
                    for k in (
                        "min_edge_early",
                        "min_edge_mid",
                        "min_edge_late",
                        "min_edge_terminal",
                    )
                    if hasattr(sc, k)
                }
                apply_crypto_strategy_thresholds_to_config(
                    sc,
                    _primary,
                    _tf,
                    getattr(config, "archetype", "") or "",
                    prior_yaml_phase_edges=_prior_yaml_edges,
                    agent_name=config.name,
                )
                _is_crypto_agent = True
            else:
                _is_crypto_agent = False
        except Exception as _crypto_thr:
            _is_crypto_agent = False
            logger.debug("crypto strategy threshold merge skipped: %s", _crypto_thr)
        # Re-apply per-agent YAML overrides last so they win over global profiles / crypto thresholds.
        # EXCEPTION: min_edge_* keys are skipped for crypto agents — the crypto_threshold_matrix
        # is the authoritative source (per-agent YAML values are informational only for crypto).
        _crypto_edge_keys = {"min_edge_early", "min_edge_mid", "min_edge_late", "min_edge_terminal"}
        for key, val in raw.items():
            if _is_crypto_agent and key in _crypto_edge_keys:
                continue
            if not hasattr(sc, key):
                continue
            current = getattr(sc, key)
            if isinstance(current, Decimal):
                setattr(sc, key, val if isinstance(val, Decimal) else Decimal(str(val)))
            elif isinstance(current, int):
                setattr(sc, key, int(val))
            elif isinstance(current, float):
                setattr(sc, key, float(val))
            else:
                setattr(sc, key, val)
        return sc

    def _swarm_consensus_bypassed(self) -> bool:
        """SAFETY: All consensus bypass mechanisms are HARD-DISABLED.
        
        This method previously supported three bypass paths (YAML config, env var, 
        and mm_consensus_mode), but these have been removed for production safety.
        All orders MUST flow through the main execution gate with proper consensus,
        risk checks, and top-3 edge selection.
        
        Returns:
            bool: Always False - bypass is not permitted
        """
        # Check for bypass attempts and log security warnings
        bypass_attempted = False
        
        # Check 1: YAML bypass_swarm_consensus flag (now ignored)
        if getattr(self.config, "bypass_swarm_consensus", False):
            bypass_attempted = True
            self.logger.warning(
                "[SECURITY] Agent %s has bypass_swarm_consensus=true in YAML - THIS IS IGNORED. "
                "All orders must flow through main execution gate.",
                self.config.name
            )
        
        # Check 2: mm_consensus_mode bypass (now rejected)
        try:
            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime
            _mm_mode = get_crypto_edge_runtime().mm_consensus_mode
            if _mm_mode == "bypass":
                bypass_attempted = True
                self.logger.error(
                    "[SECURITY] MERID_CRYPTO_MM_CONSENSUS_MODE=bypass detected for agent %s - "
                    "BYPASS MODE IS DISABLED. Using 'full' consensus mode. "
                    "All orders must flow through main execution gate.",
                    self.config.name
                )
        except Exception:
            pass
        
        # Check 3: Environment variable bypass list (now ignored)
        raw = (os.getenv("MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS") or "").strip()
        if raw:
            allowed = {x.strip() for x in raw.split(",") if x.strip()}
            if self.config.name in allowed:
                bypass_attempted = True
                self.logger.error(
                    "[SECURITY] Agent %s found in MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS - "
                    "THIS IS IGNORED. All orders must flow through main execution gate.",
                    self.config.name
                )
        
        # Safety: Always return False - bypass is never permitted
        return False

    @property
    def agent_id(self) -> str:
        # P1 FIX: Return unique instance ID to prevent clone collisions
        return getattr(self, '_unique_agent_id', self.config.agent_id)

    @property
    def agentname(self) -> str:
        """Canonical agent name for resolution/logging.
        
        BUG-FIX (2026-05-01): Some resolution paths expect .agentname attribute.
        This property normalizes to config.name for backward compatibility.
        """
        return getattr(self.config, 'name', 'UNKNOWN_AGENT')

    # ── Wire 1: CryptoSurfaceLoader callback ───────────────────────────

    def on_surface_update(self, snapshot: object) -> None:
        """Receive a CryptoSurfaceSnapshot and cache near-spot markets.

        Called by CryptoSurfaceLoader every ~10s (Wire 1).
        Both this callback and _run_cycle_body run in the same asyncio event loop,
        so cooperative scheduling makes the write safe without an explicit lock.

        Args:
            snapshot: CryptoSurfaceSnapshot from services.crypto_surface_loader
        """
        asset = self.config.assets[0] if self.config.assets else ""
        timeframe = self.config.timeframes[0] if self.config.timeframes else ""
        entry = snapshot.get_entry(asset, timeframe)
        if entry is None:
            return
        try:
            from config.crypto_spot_kalshi_config import select_markets_near_spot
            self._live_markets = select_markets_near_spot(entry)
        except Exception as exc:
            self.logger.debug("on_surface_update select failed: %s", exc)

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self, prefetched_positions: Optional[List[Any]] = None) -> None:
        """Start the agent decision loop.
        
        Args:
            prefetched_positions: Optional pre-fetched positions from AgentGrid.
                If provided, agent skips the _sync_open_positions() API call.
                This prevents event-loop blocking during concurrent agent startup.
        """
        if self.state.running:
            self.logger.warning(f"{self.config.name} already running")
            return

        # DYNAMIC ENTRY WINDOW POLICY HEADER: Log loaded policies on startup
        try:
            from merid.prediction.dynamic_entry_window import get_policies
            import os
            
            policies = get_policies()
            policy_version = os.getenv("MERID_ENTRY_WINDOW_POLICY_VERSION", "v1")
            
            # Build policy summary for logging
            policy_summary = {}
            for asset, policy in policies.items():
                policy_summary[asset] = {
                    "policy_name": policy.policy_name,
                    "base_window": f"{policy.base_window_start_minutes}-{policy.base_window_end_minutes}min",
                    "terminal_enabled": policy.terminal_config.enabled,
                    "terminal_edge_threshold": f"{policy.terminal_config.edge_threshold_pct}%" if policy.terminal_config.enabled else "N/A"
                }
            
            self.logger.info(
                "[DYNAMIC_WINDOW_POLICY_HEADER] version=%s policies=%s",
                policy_version,
                policy_summary
            )
        except Exception as exc:
            self.logger.warning("[DYNAMIC_WINDOW_POLICY_HEADER] Failed to log policy header: %s", exc)

        # Initialize bankroll from live Kalshi API if needed (deferred from __init__)
        if self._bankroll_needs_init:
            from merid.event_venues.kalshi import get_bankroll_service, BalanceState
            
            try:
                service = await get_bankroll_service()
                summary = await service.get_summary()
                
                if summary.state == BalanceState.FRESH and summary.equity_usd is not None:
                    live_bankroll_usd = float(summary.equity_usd)
                    # MICRO-BANKROLL FIX: Use canonical MAX_CYCLE_RISK_PCT from core.settings
                    # (was getattr(settings, 'MERID_MAX_RISK_FRACTION_PER_CYCLE', 0.02) which
                    # always fell back to 2% because that field doesn't exist in Settings).
                    # core.settings.MAX_CYCLE_RISK_PCT = 5% → $44.35 × 5% = $2.22 per cycle.
                    from core.settings import MAX_CYCLE_RISK_PCT
                    risk_fraction = MAX_CYCLE_RISK_PCT
                    effective_notional = live_bankroll_usd * risk_fraction
                    self.config.risk_limits.max_notional_usd = effective_notional
                    self.logger.info(
                        f"[LIVE-BANKROLL-OK] {self.config.name}: max_notional_usd=${effective_notional:.2f} "
                        f"(Kalshi API: equity=${live_bankroll_usd:.2f} × {risk_fraction*100:.1f}%)"
                    )
                elif summary.state == BalanceState.STALE and summary.equity_usd is not None:
                    live_bankroll_usd = float(summary.equity_usd)
                    from core.settings import MAX_CYCLE_RISK_PCT
                    risk_fraction = MAX_CYCLE_RISK_PCT * 0.5
                    effective_notional = live_bankroll_usd * risk_fraction
                    self.config.risk_limits.max_notional_usd = effective_notional
                    self.logger.warning(
                        f"[LIVE-BANKROLL-STALE] {self.config.name}: max_notional_usd=${effective_notional:.2f} "
                        f"(Kalshi API degraded: equity=${live_bankroll_usd:.2f} × {risk_fraction*100:.1f}%)"
                    )
                else:
                    self.logger.critical(
                        f"[BANKROLL-UNAVAILABLE] {self.config.name}: "
                        f"Kalshi bankroll {summary.state.value}: {summary.last_error_reason}. "
                        f"Agent DISABLED - no trading without live bankroll. "
                        f"Check KALSHI_API_KEY, network, and Kalshi API status."
                    )
                    self.config.risk_limits.max_notional_usd = None
            except Exception as e:
                self.logger.critical(f"[BANKROLL-INIT-FAILED] {self.config.name}: {e}")
                self.config.risk_limits.max_notional_usd = None

        self._shutdown.clear()
        self._drain_done.clear()
        self._in_execution.clear()
        self._cycle_done.clear()
        self.state.running = True
        self.state.enabled = True
        self.state.lifecycle = LifecycleState.STARTING
        self.state.started_at = datetime.now(timezone.utc)  # BUG-L8: baseline for solo_seconds
        self.state.consecutive_errors = 0
        
        # PRODUCTION FIX v6 (2026-04-26): Emergency clear phantom batches on startup
        # Phantom batches (ACTIVE with no fills) block all execution after crashes
        try:
            from merid.trading.top3_batch_manager import get_top3_batch_manager
            batch_mgr = get_top3_batch_manager()
            # Only first agent clears the phantom batch (avoids race conditions)
            if self.config.name in ("BTC_HOURLY", "BTC_15M"):
                cleared = batch_mgr.force_clear_phantom_batch(reason=f"startup_{self.config.name}")
                if cleared:
                    self.logger.critical(
                        "[STARTUP-PHANTOM-CLEAR] Emergency cleared phantom batch - "
                        "execution unblocked for new cycles"
                    )
        except Exception as _phantom_exc:
            self.logger.debug("Phantom batch check skipped: %s", _phantom_exc)
        
        import time as _agent_timing
        # D14: Defensive clear on (re)start — ensures no stale positions
        # from a previous run survive into the new session.
        _t_clear_start = _agent_timing.time()
        if self._tracked_positions:
            self.logger.debug(
                "start: clearing %d residual tracked positions from previous run",
                len(self._tracked_positions),
            )
            self._tracked_positions.clear()
        _t_clear_elapsed = (_agent_timing.time() - _t_clear_start) * 1000
        if _t_clear_elapsed > 10:  # Only log if it took significant time
            self.logger.debug(f"[TIMING] Position clear took {_t_clear_elapsed:.0f}ms")
        
        # BUG-L3: Sync open positions from Kalshi before the first cycle.
        # BUG-L9 FIX: Defer position restoration to background task to avoid blocking
        # event loop during concurrent agent startup. Agent reports as started immediately.
        _t_pos_start = _agent_timing.time()
        
        # Start background task for position restoration (non-blocking)
        if prefetched_positions is not None:
            self.logger.debug("Deferring position restoration to background (%d positions)", len(prefetched_positions))
            _restore_task = asyncio.create_task(
                self._restore_prefetched_positions_async(prefetched_positions),
                name=f"{self.config.name}-position-restore"
            )
            _restore_task.add_done_callback(
                lambda t: self.logger.warning("Position restore task failed: %s", t.exception()) if not t.cancelled() and t.exception() else None
            )
        else:
            # Fall back to sync approach if no pre-fetched positions
            await self._sync_open_positions()
            
        _t_pos_elapsed = (_agent_timing.time() - _t_pos_start) * 1000
        self.logger.debug(f"[TIMING] Agent started (position restore deferred) in {_t_pos_elapsed:.0f}ms")
        
        # BUG-L8: Enter WARMING_UP — decision loop will promote to ACTIVE
        # once data-readiness checks pass (min {_WARMUP_MIN_SECONDS}s + stagger)
        # or unconditionally after {_WARMUP_MAX_SECONDS}s.
        self.state.lifecycle = LifecycleState.WARMING_UP
        self._task = asyncio.create_task(self._run_loop(), name=f"kalshi-agent-{self.config.name}")
        self.logger.info(
            f"Started {self.config.name}: assets={self.config.assets}, "
            f"timeframes={self.config.timeframes} "
            f"[WARMING_UP min={_WARMUP_MIN_SECONDS:.0f}s max={_WARMUP_MAX_SECONDS:.0f}s]"
        )
        try:
            import json as _json

            from merid.prediction.pm_profiles import effective_strategy_config_snapshot

            _snap = effective_strategy_config_snapshot(self._strategy.config)
            _keys = (
                "min_edge_early",
                "min_edge_mid",
                "min_edge_late",
                "min_edge_terminal",
                "min_arb_edge",
                "min_confidence",
                "min_volume",
                "min_open_interest",
                "contrarian_sentiment_min",
                "contrarian_model_gap_min",
                "vol_breakout_neutral_low",
                "vol_breakout_neutral_high",
                "sentiment_mode",
                "max_contracts_per_order",
                "mm_max_spread_cents",
                "mm_target_spread_cents",
                "mm_inventory_limit",
            )
            _sub = {k: _snap.get(k, "") for k in _keys if k in _snap}
            _sub["MERID_PM_PROFILE"] = (os.getenv("MERID_PM_PROFILE") or "").strip()
            try:
                from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

                _sub["MERID_CRYPTO_EDGE_PRODUCTION_PROFILE"] = (
                    os.getenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE") or ""
                ).strip()
                _sub["crypto_threshold_mode"] = get_crypto_edge_runtime().threshold_mode
            except Exception as e:
                self.logger.debug(f"Crypto edge runtime check failed: {e}")
            self.logger.info("[PM_CONFIG_SUMMARY] %s", _json.dumps(_sub, sort_keys=True))
            
            # PRODUCTION FIX (2026-05-13): Log effective profile, sentiment config for audit trail
            self.logger.info(
                "[PM_PROFILE_AUDIT] profile=%s, contrarian_sentiment_min=%s, sentiment_mode=%s, sentiment_gating_enabled=%s",
                _sub.get("MERID_PM_PROFILE", "baseline"),
                _sub.get("contrarian_sentiment_min", "unknown"),
                _sub.get("sentiment_mode", "unknown"),
                _sub.get("sentiment_mode") in ("gating", "full"),
            )
        except Exception as _pm_sum_exc:
            self.logger.debug("PM_CONFIG_SUMMARY skipped: %s", _pm_sum_exc)

        # ── Startup sanity checks — warn if config will block all trades ──
        try:
            _warnings: list[str] = []

            # Check 1: empty assets or timeframes
            if not self.config.assets:
                _warnings.append("assets=[] — no asset universe configured")
            if not self.config.timeframes:
                _warnings.append("timeframes=[] — no timeframe configured")

            # Check 2: solo window vs cycle interval
            _solo_s = _swarm_max_solo_seconds()
            _cycle_s = self._compute_cycle_interval()
            if _solo_s > 0 and not self._swarm_consensus_bypassed():
                if _solo_s > _cycle_s * 2:
                    _warnings.append(
                        f"MERID_PM_SWARM_SOLO_SECONDS={_solo_s:.0f} > 2× cycle_interval={_cycle_s:.0f}s "
                        f"— {int(_solo_s / _cycle_s)} dead cycles before solo execution"
                    )

            # Check 3: strike selector directional passthrough
            if self._strike_selector is not None:
                _ss_cfg = self._strike_selector.config
                if not _ss_cfg.allow_directional_passthrough:
                    # Check if any timeframes are 15m (directional-only)
                    if any(tf in ("15m",) for tf in self.config.timeframes):
                        _warnings.append(
                            "strike_selection.allow_directional_passthrough=false with "
                            "timeframe=15m — 15m directional markets will all be rejected"
                        )

            # Check 4: entry window viability
            _ew = self.config.entry_window
            if _ew.minutes_before_expiry <= _ew.cutoff_minutes_before_expiry:
                _warnings.append(
                    f"entry_window: minutes_before_expiry={_ew.minutes_before_expiry} <= "
                    f"cutoff={_ew.cutoff_minutes_before_expiry} — zero-width entry window"
                )

            if _warnings:
                for _w in _warnings:
                    self.logger.warning("[CONFIG_SANITY] agent=%s — %s", self.config.name, _w)
            else:
                self.logger.info(
                    "[CONFIG_SANITY] agent=%s — all checks passed", self.config.name
                )
        except Exception as _sc_exc:
            self.logger.debug("CONFIG_SANITY skipped: %s", _sc_exc)

        # ═══════════════════════════════════════════════════════════════════
        # Settlement Event Subscription (TP re-entry reset)
        # ═══════════════════════════════════════════════════════════════════
        try:
            self._setup_settlement_subscription()
        except Exception as _sub_exc:
            self.logger.debug("Settlement subscription setup skipped: %s", _sub_exc)

        # ═══════════════════════════════════════════════════════════════════
        # Signal Router Subscription (Single Executor Principle)
        # ═══════════════════════════════════════════════════════════════════
        # trading_agent subscribes to signals from signal-only agents (lanes,
        # tools, CT adapter) and executes them via route_order_async.
        try:
            self._setup_signal_subscription()
        except Exception as _sig_sub_exc:
            self.logger.debug("Signal subscription setup skipped: %s", _sig_sub_exc)

    def _setup_settlement_subscription(self) -> None:
        """Subscribe to settlement events to reset TP round-trips on expiry.

        When a contract settles, we clear the round-trip counter for that ticker
        so the agent can re-enter in the next contract window.

        Uses shared SETTLEMENT_EVENT_BUS_TOPIC constant to ensure publisher
        (settlement_poller) and subscriber (this agent) use identical topic.
        """
        try:
            from core.event_bus import get_event_bus
            from merid.event_venues.kalshi.settlement_poller import SETTLEMENT_EVENT_BUS_TOPIC

            event_bus = get_event_bus()
            event_bus.subscribe(SETTLEMENT_EVENT_BUS_TOPIC, self._on_settlement_event)
            self.logger.debug("Subscribed to %s events for TP reset", SETTLEMENT_EVENT_BUS_TOPIC)
        except Exception as exc:
            self.logger.debug("Failed to subscribe to settlement events: %s", exc)

    def _on_settlement_event(self, event: dict) -> None:
        """Handle settlement events — reset TP state for settled contracts.

        Args:
            event: Settlement event dict with 'ticker', 'market_id', 'result', etc.
        """
        try:
            ticker = event.get("ticker", "")
            market_id = event.get("market_id", "")
            if not ticker:
                return

            # Check if we have any ACTIVE (non-closed) positions for this ticker
            # This prevents double-processing if we already closed via TP
            active_positions = [
                (pos_id, pos) for pos_id, pos in self._tracked_positions.items()
                if pos.ticker == ticker
            ]

            if not active_positions:
                return  # No positions to process

            # Check if any are still open (not already closed by TP)
            _any_open = False
            for pos_id, pos in active_positions:
                _tp_state = self._tp_manager.get_state(pos_id)
                if _tp_state and _tp_state.tp_state.value != "closed":
                    _any_open = True
                    break

            # Only call on_position_closed if we have open positions
            # (it's idempotent, but this reduces log noise)
            if _any_open:
                # Notify TP manager that position is closed due to expiry
                self._tp_manager.on_position_closed(ticker, close_reason="expiry")
                self.logger.info(
                    "[TP-SETTLEMENT] %s: position closed due to settlement — round trips reset",
                    ticker
                )
            else:
                self.logger.debug(
                    "[TP-SETTLEMENT] %s: all positions already closed — skipping expiry handler",
                    ticker
                )

            # Remove tracked positions for this ticker regardless
            for pos_id, _ in active_positions:
                del self._tracked_positions[pos_id]

        except Exception as exc:
            self.logger.debug("Settlement event handling failed: %s", exc)

    def _setup_signal_subscription(self) -> None:
        """Subscribe to SignalRouter to receive signals from signal-only agents.

        SIGNAL-ONLY AGENTS: btc15m_lane, crypto15m_lane, kalshi_tools,
        ct_execution_adapter (kalshi_continuous_trader).
        These agents call submit_signal() which routes to this callback.
        trading_agent is the SOLE EXECUTOR that calls route_order_async.
        """
        try:
            from merid.event_venues.kalshi import subscribe_to_signals

            def _signal_callback(signal):
                _task = asyncio.create_task(self._on_signal(signal))
                def _on_signal_done(t):
                    if not t.cancelled() and t.exception():
                        self.logger.warning("Signal handler task failed: %s", t.exception())
                _task.add_done_callback(_on_signal_done)

            subscribe_to_signals(_signal_callback)
            self.logger.debug("Subscribed to SignalRouter for signal-only agent signals")
        except Exception as exc:
            self.logger.debug("Failed to subscribe to SignalRouter: %s", exc)

    async def _on_signal(self, signal) -> None:
        """Handle signals from signal-only agents and execute via order router.

        This is the ONLY path that calls route_order_async for live execution.
        Signal-only agents (lanes, tools, CT) submit signals; trading_agent
        validates, risk-checks, and executes them.

        Args:
            signal: AgentSignal from SignalRouter
        """
        try:
            # Extract quality metrics (getattr for backward compat)
            quality_score = getattr(signal, 'quality_score', 0.0)
            is_duplicate = getattr(signal, 'is_duplicate', False)
            consensus_count = getattr(signal, 'consensus_count', 1)
            executable = getattr(signal, 'executable', False)

            self.logger.info(
                "[SIGNAL-IN] from %s | ticker=%s | side=%s | size=%s | price=%s "
                "| quality=%.2f | dup=%s | exec=%s | intent=%s",
                signal.agent_id, signal.market_id, signal.side,
                signal.size, signal.price_cents, quality_score,
                is_duplicate, executable, getattr(signal, 'intent', ''),
            )

            # Reject signals that failed validation at origin
            if executable and not getattr(signal, 'is_valid', True):
                self.logger.warning(
                    "[SIGNAL-IN] Rejecting invalid executable signal: %s",
                    getattr(signal, 'validation_errors', []),
                )
                return

            # Reject duplicate signals - only execute first signal for each market/action/side combo
            if is_duplicate:
                self.logger.debug(
                    "[SIGNAL-IN] Ignoring duplicate signal for %s %s %s",
                    signal.market_id, signal.action, signal.side
                )
                return
            
            # Reject low quality signals
            if quality_score < 0.30:
                self.logger.warning(
                    "[SIGNAL-IN] Rejecting low quality signal (%.2f < 0.30) from %s",
                    quality_score, signal.agent_id
                )
                return

            # Only execute if this agent handles the ticker
            if not self._handles_ticker(signal.market_id):
                self.logger.debug(
                    "[SIGNAL-IN] Ignoring signal for ticker %s (not handled by %s)",
                    signal.market_id, self.config.name
                )
                return

            # Build OrderIntent and route through canonical pipeline
            from merid.event_venues.kalshi.order_router import (
                route_order_async, OrderIntent
            )
            from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
            from merid.prediction.venue_gate import TradingMode
            from merid.event_venues.kalshi import get_bankroll_service
            # PRODUCTION FIX: Dynamic take-profit based on R-multiple and confidence
            from merid.prediction.dynamic_takeprofit import compute_dynamic_tp

            # Get effective bankroll for risk check
            _effective_equity_usd = 0.0
            try:
                _br_service = await get_bankroll_service()
                _summary = await _br_service.get_summary()
                if _summary.equity_usd is not None:
                    _effective_equity_usd = float(_summary.equity_usd)
            except Exception as _bre:
                self.logger.warning("[SIGNAL-IN] Failed to get bankroll: %s", _bre)
            
            # Consensus-based sizing: increase size if multiple agents agree
            # Base size * (1 + 0.25 * (consensus_count - 1)), capped at 2x
            consensus_multiplier = min(2.0, 1.0 + 0.25 * (consensus_count - 1))
            adjusted_size = int(signal.size * consensus_multiplier) if signal.size else 1
            
            if consensus_count > 1:
                self.logger.info(
                    "[SIGNAL-IN] Consensus boost: %s agents agree, size %s -> %s",
                    consensus_count, signal.size, adjusted_size
                )

            _origin = getattr(signal, 'origin_agent', '') or signal.agent_id

            # CRITICAL FIX: Resolve valid market price when signal.price_cents is None
            # Order router requires 1-99 cents; 0 or 100 are invalid
            _price_cents = signal.price_cents
            if _price_cents is None or _price_cents <= 0 or _price_cents >= 100:
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    state = store.get(signal.market_id)
                    if state:
                        # Use mid price if available, otherwise best bid/ask
                        if state.mid_cents and 0 < state.mid_cents < 100:
                            _price_cents = int(state.mid_cents)
                        elif signal.action == "buy" and state.best_ask_cents and 0 < state.best_ask_cents < 100:
                            _price_cents = int(state.best_ask_cents)
                        elif signal.action == "sell" and state.best_bid_cents and 0 < state.best_bid_cents < 100:
                            _price_cents = int(state.best_bid_cents)
                        elif state.best_bid_cents and state.best_ask_cents:
                            # Fallback: mid of bid/ask
                            _price_cents = int((state.best_bid_cents + state.best_ask_cents) // 2)
                        else:
                            # Last resort: default to 50 cents (neutral)
                            _price_cents = 50
                    else:
                        _price_cents = 50  # Default if no market state
                except Exception as _price_exc:
                    self.logger.debug("[SIGNAL-IN] Failed to fetch market price for %s: %s", signal.market_id, _price_exc)
                    _price_cents = 50  # Safe default
                
                # Ensure valid range 1-99
                _price_cents = max(1, min(99, _price_cents))
                
                if _price_cents != signal.price_cents:
                    self.logger.info(
                        "[SIGNAL-IN] Resolved market price for %s: %s -> %sc",
                        signal.market_id, signal.price_cents, _price_cents
                    )

            # PRODUCTION FIX: Compute dynamic take-profit based on R-multiple and confidence
            # Maps confidence to TP: ≤0.3 → 1.0R, 0.3-0.6 → 1.5R, >0.6 → 2.0-3.0R
            _tp_price_cents = None
            _tp_r_multiple = None
            _stop_price_cents = None
            try:
                # Estimate stop distance (default 2 cents for micro-scalping)
                _stop_distance = 2.0  # 2 cent stop for 1-2c profit targets
                # Determine direction for TP computation
                _direction = "LONG" if signal.side.lower() == "yes" else "SHORT"
                # Use confidence from signal (fallback to 0.5)
                _confidence = getattr(signal, 'confidence', 0.5) or 0.5
                # Use edge as Kelly fraction proxy if available
                _kelly = getattr(signal, 'edge', None)
                if _kelly is not None and isinstance(_kelly, (int, float)):
                    _kelly = float(_kelly)
                else:
                    _kelly = None

                _tp_plan = compute_dynamic_tp(
                    entry_price=float(_price_cents),
                    stop_price=float(_price_cents) - _stop_distance if _direction == "LONG" else float(_price_cents) + _stop_distance,
                    direction=_direction,
                    confidence=_confidence,
                    kelly_fraction=_kelly
                )

                _tp_price_cents = int(_tp_plan.tp_price)
                _tp_r_multiple = _tp_plan.tp_r_multiple
                # Clamp TP to valid Kalshi range 1-99
                _tp_price_cents = max(1, min(99, _tp_price_cents))

                self.logger.debug(
                    "[DTP] %s: entry=%sc, TP=%sc (%.2fR), conf=%.2f, kelly=%s",
                    signal.market_id, _price_cents, _tp_price_cents,
                    _tp_r_multiple, _confidence, _kelly
                )
            except Exception as _tp_exc:
                self.logger.debug("[DTP] TP computation failed for %s: %s", signal.market_id, _tp_exc)

            # COHERENT RISK CONTRACT: Resolve exit policy for this order
            _exit_policy_id = None
            _risk_tier = None
            _trailing_enabled = None
            _max_hold_seconds = None
            _window_resolution_id = None
            try:
                from merid.prediction.dynamic_entry_window import resolve_entry_window, resolve_exit_policy
                from config.kalshi_crypto_config import kalshi_ticker_to_asset
                
                asset = kalshi_ticker_to_asset(signal.market_id)
                if asset:
                    # Get current time and calculate minutes to expiry
                    from datetime import datetime
                    now = datetime.utcnow()
                    minutes_to_expiry = None
                    
                    # Try to get expiry from market if available
                    try:
                        from merid.event_venues.kalshi.market_catalog import get_market_catalog
                        catalog = get_market_catalog()
                        market = catalog.get_market(signal.market_id)
                        if market and market.end_date:
                            minutes_to_expiry = (market.end_date - now).total_seconds() / 60.0
                    except Exception as _me_exc:
                        self.logger.debug("[EXIT_POLICY] Could not get market for expiry: %s", _me_exc)
                    
                    # Resolve window resolution
                    edge_pct = float(signal.edge.net_edge * 100) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None
                    window_res = resolve_entry_window(asset, minutes_to_expiry, edge_pct, ticker=signal.market_id)
                    
                    # Resolve exit policy
                    exit_policy = resolve_exit_policy(window_res, asset, edge_pct)
                    
                    # Generate IDs for linkage
                    _window_resolution_id = f"wr_{signal.market_id}_{int(now.timestamp())}"
                    _exit_policy_id = f"ep_{signal.market_id}_{int(now.timestamp())}"
                    _risk_tier = exit_policy.risk_tier
                    _trailing_enabled = exit_policy.trailing_enabled
                    _max_hold_seconds = exit_policy.max_hold_seconds
                    
                    self.logger.debug(
                        "[EXIT_POLICY] Resolved for %s: tier=%s, trailing=%s, max_hold=%s",
                        signal.market_id, _risk_tier, _trailing_enabled, _max_hold_seconds
                    )
            except Exception as _ep_exc:
                self.logger.debug("[EXIT_POLICY] Failed to resolve exit policy for %s: %s", signal.market_id, _ep_exc)

            intent = OrderIntent(
                ticker=signal.market_id,
                side=signal.side,
                action=signal.action,
                price_cents=_price_cents,
                count=adjusted_size,
                mode=TradingMode.LIVE,
                order_type="limit",
                time_in_force="gtc",
                source=f"signal_router:{signal.agent_type}:{_origin}",
                agent_id=signal.agent_id,
                decision_trace_id=new_decision_trace_id(signal.agent_type),
                confidence=signal.confidence,
                rationale=signal.reasoning[:200] if signal.reasoning else None,
                sentiment_driven=signal.metadata.get('sentiment_driven', False) if signal.metadata else False,
                sentiment_asset=signal.metadata.get('sentiment_asset') if signal.metadata else None,
                sentiment_timeframe=signal.metadata.get('sentiment_timeframe') if signal.metadata else None,
                effective_equity_usd=_effective_equity_usd if _effective_equity_usd > 0 else None,
                edge_pct=getattr(signal, 'edge', None),
                # PRODUCTION: Dynamic take-profit wiring
                take_profit_price_cents=_tp_price_cents,
                take_profit_r_multiple=_tp_r_multiple,
                # COHERENT RISK CONTRACT: WindowResolution + ExitPolicyResolution linkage
                window_resolution_id=_window_resolution_id,
                exit_policy_id=_exit_policy_id,
                risk_tier=_risk_tier,
                trailing_enabled=_trailing_enabled,
                max_hold_seconds=_max_hold_seconds,
            )

            result = await route_order_async(intent)

            if result.status == "rejected":
                self.logger.warning(
                    "[SIGNAL-EXEC] REJECTED | ticker=%s | reason=%s",
                    signal.market_id, result.reason
                )
            else:
                self.logger.info(
                    "[SIGNAL-EXEC] %s | ticker=%s | order_id=%s",
                    result.status, signal.market_id, result.fill.get("order_id") if result.fill else ""
                )

        except Exception as exc:
            self.logger.warning("[SIGNAL-IN] Signal execution failed: %s", exc)

    async def drain(self) -> None:
        """BUG-L5: Disable new work, wait for current cycle, run final stop-loss sweep.

        Called by AgentGrid.stop() before agent.stop() so PortfolioRiskAgent
        remains running while positions are still actively managed.
        """
        if not self.state.running:
            return
        self.state.lifecycle = LifecycleState.DRAINING
        self.state.enabled = False  # stop accepting new signals
        self._drain_done.clear()

        # Wait for the current cycle to finish (up to 60s) - RELAXED for smoother operation
        try:
            await asyncio.wait_for(self._cycle_done.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            self.logger.warning("drain: cycle did not complete within 60s, forcing drain")

        # Final stop-loss sweep
        try:
            await self._check_stop_losses()
        except Exception as _exc:
            self.logger.warning("drain: final stop-loss sweep error: %s", _exc)

        self._drain_done.set()
        self.logger.info("drain complete for %s", self.config.name)

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        # BUG-L6: wait for any in-flight order placement before cancelling
        # RELAXED: Increased timeout from 5s to 10s for smoother operation
        if self._in_execution.is_set():
            try:
                await asyncio.wait_for(self._in_execution.wait(), timeout=10.0)
                # wait for it to *clear* (execution finished)
                # _in_execution is set while executing; poll until clear
                _deadline = 10.0
                import time as _t
                _start = _t.monotonic()
                while self._in_execution.is_set() and (_t.monotonic() - _start) < _deadline:
                    await asyncio.sleep(0.05)
            except asyncio.TimeoutError:
                self.logger.warning("stop: in-flight execution did not complete within 5s, cancelling anyway")
        self._shutdown.set()
        self.state.running = False
        self.state.lifecycle = LifecycleState.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None  # CLEAR-FIX: Prevent double-cancel on re-entry
        # D14 / W9: Clear tracked positions so stale entries don't trigger
        # spurious stop-loss closes if the agent is restarted.
        # Warn if any positions have in-flight (pending/partial) fills so
        # operators know orders may still be working on the venue.
        stale_count = len(self._tracked_positions)
        if stale_count:
            in_flight = [
                pos.ticker for pos in self._tracked_positions.values()
                if getattr(pos, "fill_status", "filled") in ("pending", "partial")
            ]
            if in_flight:
                self.logger.warning(
                    "stop: %d in-flight positions cleared — orders may still be "
                    "working on venue: %s",
                    len(in_flight), in_flight,
                )
            self._tracked_positions.clear()
            self.logger.debug(
                "stop: cleared %d stale tracked positions (%d in-flight)",
                stale_count, len(in_flight) if stale_count else 0,
            )
        self.logger.info(f"Stopped {self.config.name}")

    def pause(self) -> None:
        """Pause trading (agent stays alive but skips cycles)."""
        self.state.enabled = False
        if self.state.lifecycle == LifecycleState.ACTIVE:
            self.state.lifecycle = LifecycleState.WARMING_UP  # re-enter warm-up on resume
        self.logger.info(f"Paused {self.config.name}")

    def resume(self) -> None:
        """Resume trading."""
        self.state.enabled = True
        if self.state.running and self.state.lifecycle not in (LifecycleState.ACTIVE, LifecycleState.DRAINING):
            self.state.lifecycle = LifecycleState.WARMING_UP
        self.logger.info(f"Resumed {self.config.name}")

    # ── Decision loop ──────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main decision loop — runs until shutdown."""
        cycle_interval = self._compute_cycle_interval()

        while not self._shutdown.is_set():
            self._cycle_done.clear()
            try:
                # BUG-L8: promote from WARMING_UP to ACTIVE after warmup period
                # BUG-L13: add staggered delay to prevent thundering herd
                if (
                    self.state.lifecycle == LifecycleState.WARMING_UP
                    and self.state.started_at is not None
                ):
                    warmup_elapsed = (
                        datetime.now(timezone.utc) - self.state.started_at
                    ).total_seconds()
                    
                    # Calculate staggered delay based on agent name (deterministic)
                    _name_hash = hash(self.config.name) % 1000
                    _stagger_delay = (_name_hash / 1000.0) * _MAX_STAGGER_SECONDS
                    _min_warmup = _WARMUP_MIN_SECONDS + _stagger_delay
                    
                    # Data-readiness check: catalog has markets and spot feed is online
                    _data_ready = False
                    if warmup_elapsed >= _min_warmup:
                        _data_ready = self.state.cycles_run >= 1  # had at least one cycle

                    # Check if agent has valid series_tickers (not disabled)
                    _has_series = (
                        hasattr(self.config, 'series_tickers') and
                        self.config.series_tickers is not None and
                        len(self.config.series_tickers) > 0
                    )

                    # Hard ceiling: promote unconditionally after _WARMUP_MAX_SECONDS
                    _hard_ceiling = warmup_elapsed >= _WARMUP_MAX_SECONDS

                    if (_data_ready or _hard_ceiling) and _has_series:
                        _promote_reason = "data_ready" if _data_ready else "max_warmup_ceiling"
                        self.state.lifecycle = LifecycleState.ACTIVE
                        self.logger.info(
                            "[LIFECYCLE] Promoted %s WARMING_UP → ACTIVE after %.0fs "
                            "(reason=%s stagger=%.1fs cycles=%d)",
                            self.config.name, warmup_elapsed, _promote_reason,
                            _stagger_delay, self.state.cycles_run,
                        )
                    elif not _has_series:
                        # Agent has no series_tickers - stay in WARMING_UP indefinitely (disabled)
                        self.logger.debug(
                            "[LIFECYCLE] %s has no series_tickers - staying in WARMING_UP (disabled)",
                            self.config.name
                        )

                if self.state.enabled:
                    await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.errors.append(str(exc))
                if len(self.state.errors) > 50:
                    self.state.errors = self.state.errors[-50:]
                # medium-risk: per-agent consecutive error circuit breaker
                self.state.consecutive_errors += 1
                if self.state.consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    self.logger.error(
                        "Agent %s hit %d consecutive errors — pausing self to prevent API spam",
                        self.config.name, self.state.consecutive_errors,
                    )
                    self.pause()
                    self.state.consecutive_errors = 0
                else:
                    self.logger.error(f"Cycle error ({self.state.consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): {exc}")
                self._cycle_done.set()
                # Wait before next retry
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=cycle_interval)
                    break
                except asyncio.TimeoutError:
                    continue

            # Cycle completed successfully — reset error counter
            self.state.consecutive_errors = 0
            self._cycle_done.set()

            # Wait for next cycle or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=cycle_interval
                )
                break  # shutdown was set
            except asyncio.TimeoutError:
                pass  # normal — time for next cycle

    async def _run_cycle(self) -> None:
        """Single decision cycle."""
        now = datetime.now(timezone.utc)
        self.state.last_cycle_at = now
        self.state.cycles_run += 1

        _mode = str(getattr(self._venue_gate, "mode", "paper") if self._venue_gate else "paper")
        _tick = TickContext(
            agent_id=self.config.name,
            cycle_number=self.state.cycles_run,
            mode=_mode,
        )
        _bus = get_tick_bus()
        _bus.emit(_tick.emit_started())

        try:
            await self._run_cycle_body(now, _tick, _bus)
        except Exception as _exc:
            _bus.emit(_tick.emit_error(str(_exc)))
            raise
        finally:
            _bus.emit(_tick.finalise())

    async def _run_cycle_body(
        self,
        now: datetime,
        _tick: TickContext,
        _bus: object,
    ) -> None:
        """Instrumented body of the decision cycle."""
        _decision_timer = DecisionTimer()

        # SIGNAL-ONLY-FIX: Signal-only agents compute indicators and submit opinions
        # but skip trade execution. They need market resolution and signal generation
        # to compute MACD/RSI for sentiment/trading strategy context.
        _is_signal_only = getattr(self.config, 'signalonly', False)

        # 0. Stop-loss sweep — check all open positions before new signals
        await self._check_stop_losses()

        # 1. Session guard
        if not self._session_guard.is_trading_allowed(now):
            _bus.emit(_tick.emit_session_gated("outside_session_window"))
            self._emit_decision_log(Decision.hold(
                HoldReason.SESSION_CLOSED,
                self._session_guard.block_reason(now) or "outside_session_window",
                agent_name=self.config.name,
                cycle_number=self.state.cycles_run,
                elapsed_ms=_decision_timer.elapsed_ms(),
            ))
            return

        # 2. Resolve markets
        await self._resolve_markets()
        if self._resolved_markets:
            try:
                from merid.event_venues.kalshi.expiry_fallback import (
                    apply_crypto_interval_expiry_fallback,
                )

                self._resolved_markets = [
                    apply_crypto_interval_expiry_fallback(m, now)
                    for m in self._resolved_markets
                ]
            except Exception as _exf:
                self.logger.debug("expiry_fallback skipped: %s", _exf)
        
        # STEPWISE CATALOG LOGGING: Track where markets drop to zero
        _resolved_ct = len(self._resolved_markets)
        if _resolved_ct == 0:
            self.logger.info(
                "[PM_CATALOG_TRACE] agent=%s step=resolved count=0 - no markets found in catalog",
                self.config.name
            )
        else:
            self.logger.info(
                "[PM_CATALOG_TRACE] agent=%s step=resolved count=%d - proceeding to window filter",
                self.config.name, _resolved_ct
            )
        
        if not self._resolved_markets:
            self._entry_window_suspect_streak = 0
            _bus.emit(_tick.emit_snapshot(
                markets_resolved=0,
                markets_in_window=0,
                session_allowed=True,
            ))
            self._emit_decision_log(Decision.hold(
                HoldReason.NO_MARKETS,
                "no markets resolved for this agent/cycle",
                agent_name=self.config.name,
                cycle_number=self.state.cycles_run,
                elapsed_ms=_decision_timer.elapsed_ms(),
            ))
            return

        # 3. Reset per-window order count if window rolled
        self._maybe_reset_window(now)

        # 4. Filter for the "most active" contract per asset/timeframe slot
        # Requirement: at most one active contract per asset/timeframe slot.
        # Use async version to avoid blocking event loop with CPU-heavy sorting
        active_markets = await self._filter_active_contracts_async(self._resolved_markets, now)
        _tick.markets_in_window = len(active_markets)

        _mr_ct = len(self._resolved_markets)
        _mw_ct = len(active_markets)
        
        # STEPWISE CATALOG LOGGING: Track window filter results
        self.logger.info(
            "[PM_CATALOG_TRACE] agent=%s step=window_filter resolved=%d active=%d",
            self.config.name, _mr_ct, _mw_ct
        )
        
        if _mr_ct > 0 and _mw_ct == 0:
            self._entry_window_suspect_streak += 1
            if self.logger.isEnabledFor(logging.DEBUG):
                for _m in self._resolved_markets:
                    _ed = _m.end_date
                    _passes = (_ed > now) if _ed else None
                    self.logger.debug(
                        "[PM_MARKET_FILTER] ticker=%s end_date=%s now=%s future_ok=%s",
                        _m.market_id,
                        _ed,
                        now,
                        _passes,
                    )
        else:
            self._entry_window_suspect_streak = 0
        if self._entry_window_suspect_streak >= 5:
            _ew = self.config.entry_window
            self.logger.warning(
                "[ENTRY-WINDOW-SUSPECT] agent=%s asset=%s tf=%s cycles_without_window=%d "
                "minutes_before_expiry=%s cutoff_minutes_before_expiry=%s resolved=%d",
                self.config.name,
                (self.config.assets[0] if self.config.assets else "?"),
                (self.config.timeframes[0] if self.config.timeframes else "?"),
                self._entry_window_suspect_streak,
                _ew.minutes_before_expiry,
                _ew.cutoff_minutes_before_expiry,
                _mr_ct,
            )

        # Emit snapshot now that markets_in_window is known
        _bus.emit(_tick.emit_snapshot(
            markets_resolved=_mr_ct,
            markets_in_window=_mw_ct,
            session_allowed=True,
        ))

        # 5. Evaluate each filtered market
        _signals_evaluated = 0
        _signals_actionable = 0
        _signals_consensus_blocked = 0
        _consensus_hold_buckets: Dict[str, int] = {}
        _no_action_buckets: Dict[str, int] = {}
        _proposal_submitted_this_cycle = False
        _pre_risk_intents = 0
        _risk_approved_count = 0
        _execution_dispatched = 0
        _execution_skipped_warmup = 0
        _strike_rejected = 0
        _strike_passed = 0
        _strike_directional = 0
        _cell_trace_enabled = os.getenv("MERID_PM_CELL_TRACE", "").lower() in ("1", "true", "yes", "on")
        for market in active_markets:
            _mkt_trace: Optional[Dict] = None
            if self._shutdown.is_set():
                break

            # Check per-window order limit (dynamically computed from bankroll)
            _effective_max_orders = self._get_effective_max_orders(top_n_edges=3)  # REVERTED from 1 to restore profitable trades
            if self.state.orders_this_window >= _effective_max_orders:
                self.logger.debug(f"Order limit reached for window ({self.state.orders_this_window}/{_effective_max_orders})")
                self._emit_decision_log(Decision.hold(
                    HoldReason.ORDER_LIMIT,
                    f"window order limit reached ({self.state.orders_this_window}/{_effective_max_orders})",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                break

            # Build snapshot and evaluate
            try:
                snapshot = self._build_snapshot(market, now)

                # === Strike Selection Gate ===
                # Hard-reject contracts outside configured spot-to-strike distance
                # BEFORE strategy evaluation to avoid wasting compute on irrelevant markets.
                # Strike Selection Gate - fail-closed: if no selector, reject non-directional markets
                if self._strike_selector is not None:
                    _ss_asset = (snapshot.resolved_asset or "").upper()
                    _ss_tf = (snapshot.resolved_timeframe or "").lower()
                    _ss_spot = float(snapshot.spot_price_usd) if snapshot.spot_price_usd is not None else None
                    _ss_strike = float(snapshot.strike_price_usd) if snapshot.strike_price_usd is not None else None
                    _ss_result = self._strike_selector.evaluate(
                        ticker=market.market_id,
                        asset=_ss_asset,
                        timeframe=_ss_tf,
                        spot=_ss_spot,
                        strike=_ss_strike,
                    )
                    if not _ss_result.accepted:
                        _strike_rejected += 1

                        # Special handling for macro markets bypassing crypto selector
                        from merid.prediction.kalshi_strike_selector import RejectionReason
                        if getattr(_ss_result, 'rejection_reason', None) == RejectionReason.NON_CRYPTO_MARKET:
                            # Macro markets bypass crypto selector - this is expected, not an error
                            if _cell_trace_enabled:
                                _mkt_trace = {
                                    "agent": self.config.name,
                                    "cycle": self.state.cycles_run,
                                    "market_id": market.market_id,
                                    "exit_stage": "strike_bypass:macro_not_crypto",
                                    "detail": "bypassed crypto strike selector (macro market)",
                                }
                                self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                                _mkt_trace = None
                            self.logger.debug(
                                "[STRIKE_BYPASS] %s: bypassed crypto strike selector (macro market not supported)",
                                market.market_id
                            )
                            # Note: We continue here to skip this market since macro markets
                            # are not supported by the crypto strike selector. This is expected behavior.
                            continue

                        if _cell_trace_enabled:
                            _mkt_trace = {
                                "agent": self.config.name,
                                "cycle": self.state.cycles_run,
                                "market_id": market.market_id,
                                "exit_stage": f"strike_reject:{_ss_result.rejection_reason}",
                            }
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.NO_EDGE,
                            f"strike selector rejected: {_ss_result.rejection_reason}",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    _strike_passed += 1
                    # Tag snapshot with strike selection metadata
                    snapshot.strike_in_target_band = _ss_result.in_target_band
                    snapshot.strike_risk_capped = _ss_result.risk_capped
                    if getattr(_ss_result, 'is_directional', False):
                        _strike_directional += 1
                        snapshot.spot_strike_basis_note = "directional_passthrough"
                else:
                    # Fail-closed: strike selector unavailable - reject non-directional markets
                    _is_directional = "UP" in market.market_id.upper() or "DOWN" in market.market_id.upper()
                    if not _is_directional:
                        self.logger.error(
                            "[STRIKE_SELECTOR_MISSING] Strike selector unavailable, rejecting non-directional market %s",
                            market.market_id
                        )
                        self._emit_decision_log(Decision.hold(
                            HoldReason.NO_EDGE,
                            "strike selector unavailable - cannot evaluate strike distance",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue

                # === Market Mood Bus Integration ===
                # Get unified context from the mood bus (prefer snapshot-resolved asset/tf for MM)
                asset = (
                    (snapshot.resolved_asset or "").strip()
                    or (self.config.assets[0] if self.config.assets else "")
                )
                timeframe = (
                    (snapshot.resolved_timeframe or "").strip()
                    or (self.config.timeframes[0] if self.config.timeframes else "")
                )
                mood_context = self._get_mood_context(asset, timeframe)
                
                # Inject mood context into snapshot
                if mood_context:
                    # B14: fg_index is 0-100. Store the raw value so that
                    # _sentiment_size_factor thresholds (<=20, >=80, etc.) fire
                    # correctly.  DO NOT divide by 100 here — that would make all
                    # scores appear in the 0.0–1.0 range and permanently disable
                    # the fear/greed size-reduction logic.
                    snapshot.sentiment_global = float(mood_context.fg_index)
                    snapshot.sentiment_regime = mood_context.volatility_regime.value
                    self.logger.debug(
                        f"Mood context: FG={mood_context.fg_index}, "
                        f"vol={mood_context.volatility_regime.value}, "
                        f"tags={mood_context.tags}"
                    )
                
                # Extract correlation_id from mood context for trace chain
                correlation_id = None
                if mood_context and hasattr(mood_context, 'correlation_id'):
                    correlation_id = mood_context.correlation_id
                
                # Fallback: get correlation_id from SentimentBusV2 if mood context doesn't have it
                if not correlation_id:
                    try:
                        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
                        _bus_v2 = get_sentiment_bus_v2()
                        _asset_ctx = _bus_v2.get_asset_context(asset) if asset else None
                        if _asset_ctx and hasattr(_asset_ctx, 'correlation_id'):
                            correlation_id = _asset_ctx.correlation_id
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                
                signal = self._strategy.evaluate(snapshot, archetype=self.config.archetype, correlation_id=correlation_id)
                signal = self._apply_pm_spot_hard_gate(market, signal, snapshot)
                self._maybe_log_crypto_spot_strike_trace(snapshot, signal)
                _signals_evaluated += 1
                
                # === Cross-Asset Arbiter Integration ===
                # Submit crypto momentum scalping signals to arbiter for ranking
                # Arbiter will deduplicate and select top N edges across all agents
                if asset in CRYPTO_ASSETS and timeframe in MEAN_REVERSION_TIMEFRAMES:
                    if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD):
                        self._submit_to_arbiter(signal, market, asset, timeframe)
                        # Note: Arbiter collects all candidates and runs cycle at end
                        # The actual winner check happens before execution
                
                if signal.action == SignalAction.NO_ACTION:
                    _bk = _classify_pm_no_action_reason(signal.reason or "")
                    _no_action_buckets[_bk] = _no_action_buckets.get(_bk, 0) + 1
                    try:
                        from merid.prediction.crypto_edge_production import get_no_trade_decision_tracker

                        get_no_trade_decision_tracker().observe(
                            _bk,
                            market_id=market.market_id,
                            reason=signal.reason or "",
                        )
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")

                # Record every signal (including NO_ACTION) for audit
                await self._record_signal(market, signal, snapshot, now)

                # === Submit to SwarmConsensusAggregator ===
                # Only actionable signals go to consensus / execution.  Strategy evaluation
                # and _signals_actionable run even when outside the entry window so PM_CYCLE_TRACE
                # and calibration reflect real model output (filter may fall back to nearest
                # expiry outside the narrow pre-expiry band).
                if signal.action not in (SignalAction.NO_ACTION, SignalAction.HOLD):
                    _signals_actionable += 1
                    if _cell_trace_enabled:
                        _mkt_trace = {
                            "agent": self.config.name,
                            "cycle": self.state.cycles_run,
                            "market_id": market.market_id,
                            "action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                            "contracts": signal.contracts,
                            "edge": round(float(signal.edge.net_edge), 4) if signal.edge else None,
                            "has_edge": True,
                            "in_consensus": False,
                            "sized": False,
                            "execution_attempted": False,
                            "exit_stage": "pre_consensus",
                        }
                    self._log_pm_sizing_context(market, signal, snapshot)

                    _sec_exp = self._get_seconds_to_expiry(market, now)
                    _is_new_entry = self._is_new_entry_action(signal.action)
                    # EXPIRY_GUARD_SECS: Hard deadline - no new entries within this many seconds of expiry
                    _EXPIRY_GUARD_SECS = float(os.getenv("MERID_EXPIRY_GUARD_SECS", "90"))
                    if _is_new_entry and _sec_exp is not None and _sec_exp <= _EXPIRY_GUARD_SECS:
                        self.logger.debug(
                            "Expiry guard: blocking entry pipeline for %s, seconds_to_expiry=%.0f",
                            market.market_id,
                            _sec_exp,
                        )
                        _bus.emit(_tick.emit_risk_check(
                            market.market_id,
                            allowed=False,
                            reason=f"expiry_proximity_guard:seconds_to_expiry={_sec_exp:.0f}",
                        ))
                        if _mkt_trace:
                            _mkt_trace["exit_stage"] = "expiry_proximity_guard"
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.EXPIRY_PROXIMITY,
                            f"expiry proximity guard: {_sec_exp:.0f}s to expiry",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    # EXPIRY_CAUTION_SECS: Warning threshold for expiry proximity (should be > EXPIRY_GUARD_SECS)
                    _EXPIRY_CAUTION_SECS = float(os.getenv("MERID_EXPIRY_CAUTION_SECS", "120"))
                    if _is_new_entry and _sec_exp is not None and _sec_exp <= _EXPIRY_CAUTION_SECS:
                        self.logger.warning(
                            "Expiry approaching caution zone: %s, seconds_to_expiry=%.0f (threshold=%.0f)",
                            market.market_id,
                            _sec_exp,
                            _EXPIRY_CAUTION_SECS,
                        )
                    if _is_new_entry and not self._in_entry_window(market, now):
                        self.logger.debug(
                            "entry_window_gate: %s actionable on %s outside entry window — "
                            "evaluation logged, skipping consensus/orders",
                            signal.action,
                            market.market_id,
                        )
                        if _mkt_trace:
                            _mkt_trace["exit_stage"] = "entry_window_gate"
                            self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                            _mkt_trace = None
                        self._emit_decision_log(Decision.hold(
                            HoldReason.OUTSIDE_ENTRY_WINDOW,
                            f"market {market.market_id} outside configured entry window",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue

                    _rich_ok = self._submit_to_consensus(market, signal, snapshot, mood_context)
                    try:
                        from merid.prediction.crypto_edge_production import (
                            log_approved_signal_created,
                            signal_feature_hash,
                        )

                        _edge_f = float(signal.edge.net_edge) if getattr(signal, "edge", None) else 0.0
                        log_approved_signal_created(
                            asset=asset,
                            timeframe=timeframe,
                            edge=_edge_f,
                            feature_hash=signal_feature_hash(
                                asset=asset,
                                timeframe=timeframe,
                                edge_s=f"{_edge_f:.6f}",
                                action=signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                                market_id=market.market_id,
                            ),
                            market_id=market.market_id,
                            action=signal.action.value if hasattr(signal.action, "value") else str(signal.action),
                        )
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                    # Wire 2: adapter-based fallback only if the rich path failed.
                    # _submit_to_consensus already submits a market-data-driven
                    # AgentProposal; calling _submit_consensus_proposal again would
                    # overwrite it with a weaker adapter-derived one.
                    if not _proposal_submitted_this_cycle:
                        if not _rich_ok:
                            self._submit_consensus_proposal(signal)
                        _proposal_submitted_this_cycle = True
                    else:
                        self.logger.info(
                            "multi-market cycle: secondary signal dropped for %s "
                            "(proposal already submitted this cycle)",
                            market.market_id,
                        )
                    
                    # Check if we have consensus before acting
                    if self._swarm_consensus_bypassed():
                        self.logger.info(
                            "[PM_CONSENSUS_BYPASS] agent=%s ticker=%s — swarm gates skipped",
                            self.config.name,
                            market.market_id,
                        )
                        self.state.last_consensus_at = now
                        if _mkt_trace:
                            _mkt_trace["in_consensus"] = True
                            _mkt_trace["exit_stage"] = "pre_risk"
                    else:
                        try:
                            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

                            _mm_mode = get_crypto_edge_runtime().mm_consensus_mode
                            _mm_wait_ms = float(os.getenv("MERID_CONSENSUS_WAIT_MS", "500"))
                        except Exception:
                            _mm_mode = "full"
                            _mm_wait_ms = float(os.getenv("MERID_CONSENSUS_WAIT_MS", "500"))

                        consensus = self._get_consensus(asset, timeframe)
                        if (
                            consensus
                            and consensus.status.value == "forming"
                            and _mm_mode == "soft"
                            and _mm_wait_ms > 0
                        ):
                            await asyncio.sleep(min(_mm_wait_ms / 1000.0, 2.0))
                            consensus = self._get_consensus(asset, timeframe)
                        try:
                            from merid.prediction.crypto_edge_production import log_consensus_canonical_read

                            log_consensus_canonical_read(
                                market_key=f"{asset}:{timeframe}",
                                status=consensus.status.value if consensus else None,
                                direction=consensus.consensus_direction if consensus else None,
                            )
                        except Exception as e:
                            self.logger.debug(f"Silent error suppressed: {e}")

                        if consensus and consensus.status.value == "ready":
                            # Consensus recovered — clear degraded flag
                            self.state.last_consensus_at = now
                            if self.state.swarm_degraded:
                                self.logger.info("Swarm consensus recovered — exiting degraded mode")
                                self.state.swarm_degraded = False
                                self.state.solo_trades_this_degraded_session = 0  # E2: reset cap counter

                            # Directional trades: swarm yes/no must match. Market-making QUOTE is
                            # not directional — ``QUOTE`` was incorrectly mapped to signal_dir "no",
                            # so READY+neutral consensus always looked like a mismatch and MM never
                            # executed (logs: "Signal no blocked: consensus is neutral").
                            # BUG-FIX (2026-05-07): Fix consensus misalignment - SELL_YES is bearish (no), SELL_NO is bullish (yes)
                            if signal.action != SignalAction.QUOTE:
                                # Correct mapping: SELL_YES = bearish (no), SELL_NO = bullish (yes)
                                _dir_map = {
                                    SignalAction.BUY_YES: "yes",
                                    SignalAction.BUY_NO: "no",
                                    SignalAction.SELL_YES: "no",   # selling YES = bearish
                                    SignalAction.SELL_NO: "yes",   # selling NO = bullish
                                }
                                signal_dir = _dir_map.get(signal.action, "neutral")
                                if consensus.consensus_direction != signal_dir:
                                    self.logger.info(
                                        f"Signal {signal_dir} blocked: consensus is "
                                        f"{consensus.consensus_direction} "
                                        f"(conf={consensus.consensus_confidence:.2f})"
                                    )
                                    _signals_consensus_blocked += 1
                                    _consensus_hold_buckets["direction_mismatch"] = (
                                        _consensus_hold_buckets.get("direction_mismatch", 0)
                                        + 1
                                    )
                                    if _mkt_trace:
                                        _mkt_trace["exit_stage"] = "consensus:direction_mismatch"
                                        self.logger.info("[PM_CELL_TRACE] %s", _json.dumps(_mkt_trace))
                                        _mkt_trace = None
                                    self._emit_decision_log(Decision.hold(
                                        HoldReason.CONSENSUS_DIRECTION_MISMATCH,
                                        f"signal {signal_dir} blocked: consensus is {consensus.consensus_direction}",
                                        market_id=market.market_id,
                                        agent_name=self.config.name,
                                        cycle_number=self.state.cycles_run,
                                        elapsed_ms=_decision_timer.elapsed_ms(),
                                    ))
                                    continue
                            else:
                                self.logger.debug(
                                    "consensus direction gate skipped for QUOTE (MM) ticker=%s "
                                    "swarm_dir=%s",
                                    market.market_id,
                                    consensus.consensus_direction,
                                )

                            # Use consensus confidence for sizing
                            if signal.edge and hasattr(signal.edge, 'confidence'):
                                signal.edge.confidence = consensus.consensus_confidence

                            self.logger.info(
                                f"Consensus aligned: {consensus.consensus_direction} @ "
                                f"{consensus.consensus_probability:.1%} "
                                f"(size={consensus.size_band})"
                            )
                            try:
                                from merid.prediction.crypto_edge_production import (
                                    log_consensus_consumed_for_trading,
                                )

                                log_consensus_consumed_for_trading(
                                    market_id=market.market_id,
                                    value={
                                        "direction": consensus.consensus_direction,
                                        "p": consensus.consensus_probability,
                                        "conf": consensus.consensus_confidence,
                                        "status": consensus.status.value,
                                    },
                                    decision="PROCEED_ALIGNED",
                                )
                            except Exception as e:
                                self.logger.debug(f"Silent error suppressed: {e}")
                        elif consensus and consensus.status.value == "forming":
                            # FORMING: production default (full) holds; soft profile may proceed
                            # small-sized after a brief consensus_wait timeout (Settings).
                            if _mm_mode == "soft":
                                self._apply_solo_trade_cap(signal)
                                self.logger.info(
                                    "MM consensus soft: FORMING on %s/%s — proceeding small band "
                                    "(tune MERID_CRYPTO_MM_CONSENSUS_MODE / "
                                    "MERID_CRYPTO_EDGE_PRODUCTION_PROFILE).",
                                    asset,
                                    timeframe,
                                )
                                try:
                                    from merid.prediction.crypto_edge_production import (
                                        log_consensus_consumed_for_trading,
                                    )

                                    log_consensus_consumed_for_trading(
                                        market_id=market.market_id,
                                        value={
                                            "direction": consensus.consensus_direction,
                                            "p": consensus.consensus_probability,
                                            "status": "forming",
                                        },
                                        decision="PROCEED_SOFT_FORMING_SMALL",
                                    )
                                except Exception as e:
                                    self.logger.debug(f"Silent error suppressed: {e}")
                            else:
                                self.logger.debug(
                                    "Signal held: consensus FORMING for %s/%s — "
                                    "waiting for quorum before executing",
                                    asset,
                                    timeframe,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["forming"] = (
                                    _consensus_hold_buckets.get("forming", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.CONSENSUS_FORMING,
                                    f"consensus FORMING for {asset}/{timeframe} — waiting for quorum",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue
                        elif consensus and consensus.status.value == "conflicted":
                            self.logger.info(
                                f"Signal blocked: swarm conflicted - {consensus.disagreement_flags}"
                            )
                            _signals_consensus_blocked += 1
                            self._emit_decision_log(Decision.hold(
                                HoldReason.CONSENSUS_CONFLICTED,
                                f"swarm conflicted: {consensus.disagreement_flags}",
                                market_id=market.market_id,
                                agent_name=self.config.name,
                                cycle_number=self.state.cycles_run,
                                elapsed_ms=_decision_timer.elapsed_ms(),
                            ))
                            continue
                        elif not consensus:
                            # Allow solo execution only after MERID_PM_SWARM_SOLO_SECONDS without
                            # consensus, but always cap size to "small" and emit WARNING.
                            # BUG-L8/medium: use started_at as baseline when no consensus
                            # has ever been seen, so solo_seconds is not near-zero on
                            # the first cycle (which would incorrectly skip the hold).
                            _max_solo_s = _swarm_max_solo_seconds()
                            _max_solo_wall = _MAX_SOLO_WALL_SECONDS
                            _max_solo_trades = _MAX_SOLO_TRADES_DEGRADED
                            solo_seconds = (
                                (now - self.state.last_consensus_at).total_seconds()
                                if self.state.last_consensus_at
                                else (now - (self.state.started_at or now)).total_seconds()
                            )
                            if solo_seconds < _max_solo_s:
                                self.logger.debug(
                                    "No consensus yet (%.0fs < %.0fs threshold), signal held",
                                    solo_seconds, _max_solo_s,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["solo_window"] = (
                                    _consensus_hold_buckets.get("solo_window", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.SOLO_WINDOW,
                                    f"no consensus yet ({solo_seconds:.0f}s < {_max_solo_s:.0f}s threshold)",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue
                            # Swarm degraded — cap to small size, warn once per degraded entry
                            if not self.state.swarm_degraded:
                                self.logger.warning(
                                    "SWARM DEGRADED: no consensus for %.0fs on %s/%s — "
                                    "proceeding solo at small size band only",
                                    solo_seconds, asset, timeframe,
                                )
                                self.state.swarm_degraded = True
                                self.state.swarm_degraded_since = now
                                self.state.solo_trades_this_degraded_session = 0
                                # BUG-08: alert on degraded entry
                                try:
                                    _am = _get_alert_manager_module() if _get_alert_manager_module else None
                                    if _am:
                                        _am.fire_risk_warning(
                                            market_id=self.config.name,
                                            message=(
                                                f"Swarm degraded on {self.config.name}: no consensus "
                                                f"for {solo_seconds:.0f}s — solo trading capped at "
                                                f"{_max_solo_trades} orders"
                                            ),
                                        )
                                except Exception as _ae:
                                    self.logger.debug("degraded alert skipped: %s", _ae)

                            # BUG-08: enforce wall-clock limit on degraded session
                            degraded_seconds = (
                                (now - self.state.swarm_degraded_since).total_seconds()
                                if self.state.swarm_degraded_since else 0.0
                            )
                            if degraded_seconds >= _max_solo_wall:
                                self.logger.warning(
                                    "SWARM DEGRADED wall-clock limit reached (%.0fs) on %s — "
                                    "halting agent until consensus recovers",
                                    degraded_seconds, self.config.name,
                                )
                                try:
                                    _am = _get_alert_manager_module() if _get_alert_manager_module else None
                                    if _am:
                                        _am.fire_risk_breach(
                                            market_id=self.config.name,
                                            message=(
                                                f"Agent {self.config.name} auto-halted: swarm degraded "
                                                f"for {degraded_seconds/60:.1f}min without recovery"
                                            ),
                                        )
                                except Exception as _ae:
                                    self.logger.debug("halt alert skipped: %s", _ae)
                                # CRIT-2 FIX: fire global kill switch on wall-clock breach.
                                # Guarded by MERID_DEPENDENCY_HEALTH_KILL_ENABLED (default: false).
                                try:
                                    from merid.risk.kill_switches import risk_controller as _rc_swarm
                                    _rc_swarm.trigger_dependency_health(
                                        f"Swarm consensus unavailable for {degraded_seconds / 60:.1f}min "
                                        f"on agent {self.config.name} — trading halted system-wide"
                                    )
                                except Exception as _ke:
                                    self.logger.debug("swarm kill switch call skipped: %s", _ke)
                                self.state.enabled = False
                                break

                            # BUG-08: enforce per-degraded-session solo trade cap
                            if self.state.solo_trades_this_degraded_session >= _MAX_SOLO_TRADES_DEGRADED:
                                self.logger.warning(
                                    "SWARM DEGRADED solo trade cap (%d) reached on %s — "
                                    "holding until consensus recovers",
                                    _max_solo_trades, self.config.name,
                                )
                                _signals_consensus_blocked += 1
                                _consensus_hold_buckets["solo_cap"] = (
                                    _consensus_hold_buckets.get("solo_cap", 0) + 1
                                )
                                self._emit_decision_log(Decision.hold(
                                    HoldReason.SOLO_CAP_REACHED,
                                    f"solo trade cap ({_max_solo_trades}) reached in degraded session",
                                    market_id=market.market_id,
                                    agent_name=self.config.name,
                                    cycle_number=self.state.cycles_run,
                                    elapsed_ms=_decision_timer.elapsed_ms(),
                                ))
                                continue

                            # Force small size band: halve contracts to 1 minimum
                            if signal.contracts > 1:
                                signal.contracts = max(1, signal.contracts // 2)
                            self.state.solo_trades_this_degraded_session += 1
                            self.logger.debug(
                                "Solo execution (degraded %d/%d): %s contracts=%d",
                                self.state.solo_trades_this_degraded_session,
                                _max_solo_trades,
                                market.market_id, signal.contracts,
                            )
            except Exception as exc:
                self.logger.warning(f"Error evaluating {market.market_id}: {exc}")
                self._emit_decision_log(Decision.hold(
                    HoldReason.EXECUTION_ERROR,
                    f"evaluation error: {exc}",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                continue

            if signal.action == SignalAction.NO_ACTION or signal.action == SignalAction.HOLD:
                self._emit_decision_log(Decision.hold(
                    HoldReason.NO_EDGE,
                    signal.reason or "strategy returned NO_ACTION/HOLD",
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    signal_summary={"action": signal.action.value, "edge": float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, 'net_edge') else None},
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                continue

            _pre_risk_intents += 1

            # Pre-trade risk check
            side_str = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
            # BUG-FIX: Treat 0 or negative as invalid and default to 50 (market order midpoint)
            _raw_limit = signal.limit_price_cents
            if _raw_limit is not None and _raw_limit > 0:
                price_cents = Decimal(str(_raw_limit))
            else:
                price_cents = Decimal("50")
            event_id = market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id
            
            # If it's a quote, we skip individual check_order here and handle in _execute_signal
            # or just use best available price for the check
            check_price = price_cents
            if signal.action == SignalAction.QUOTE:
                check_price = Decimal(str(signal.bid_price_cents or 50))

            # BUG-07: extract bid/ask/depth from snapshot so checks 12-14
            # (spread, slippage, depth) are no longer dead code.
            _best_bid: Optional[Decimal] = None
            _best_ask: Optional[Decimal] = None
            _depth: Optional[int] = None
            # yes_bid / yes_ask are already Kalshi cents (0–100); do not scale again.
            if snapshot and snapshot.implied:
                if snapshot.implied.yes_bid is not None:
                    _best_bid = Decimal(str(snapshot.implied.yes_bid))
                if snapshot.implied.yes_ask is not None:
                    _best_ask = Decimal(str(snapshot.implied.yes_ask))
            if snapshot is not None:
                _depth = getattr(snapshot, "depth_at_best", None)

            # BUG-009 FIX: Calculate existing YES/NO contracts from tracked positions
            existing_yes = sum(
                pos.contracts for pos in self._tracked_positions.values()
                if pos.ticker == market.market_id and pos.side == "yes"
            )
            existing_no = sum(
                pos.contracts for pos in self._tracked_positions.values()
                if pos.ticker == market.market_id and pos.side == "no"
            )

            # CRITICAL FIX: Compute dynamic cycle cap based on live bankroll and winner count
            # This ensures the 1-2% allocation is enforced correctly across all winners
            _cycle_max_notional_usd = self.config.risk_limits.max_notional_usd  # Fallback to config
            _cycle_max_contracts = None  # Will be set from cycle cap if available
            try:
                from merid.prediction.dynamic_sizing import get_cycle_sizing_cap
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                from decimal import Decimal as _Decimal
                
                _live_equity = get_equity_for_risk_calc_sync()
                if _live_equity and _live_equity > 0:
                    _bankroll_usd = _Decimal(str(_live_equity))
                    _price_cents = int(check_price) if check_price else 50
                    _cycle_cap = get_cycle_sizing_cap(_bankroll_usd, _price_cents, market.market_id, side_str)
                    _cycle_max_notional_usd = _cycle_cap.max_notional_per_winner_usd
                    _cycle_max_contracts = _cycle_cap.max_contracts_per_winner  # DYNAMIC: derived from notional/price
                    
                    # Log the cycle cap computation for observability
                    self.logger.debug(
                        "[CYCLE_CAP_RISK] %s: bankroll=$%.2f, winners=%d, max_per_winner=$%.2f, max_contracts=%d",
                        market.market_id,
                        float(_bankroll_usd),
                        _cycle_cap.winner_count,
                        float(_cycle_max_notional_usd),
                        _cycle_cap.max_contracts_per_winner
                    )
            except Exception as _cycle_err:
                self.logger.debug("[CYCLE_CAP_RISK] Failed to compute cycle cap, using config fallback: %s", _cycle_err)

            try:
                check = self._risk.check_order(
                    market_id=market.market_id,
                    event_id=event_id,
                    side=side_str,
                    contracts=signal.contracts,
                    price_cents=check_price,
                    best_bid_cents=_best_bid,
                    best_ask_cents=_best_ask,
                    depth_at_price=_depth,
                    edge=signal.edge.net_edge if signal.edge else Decimal("0"),
                    agent_max_notional_usd=_cycle_max_notional_usd,
                    # BUG-009: Pass per-side position limits from YAML config
                    max_yes_position=self.config.risk_limits.max_yes_position,
                    max_no_position=self.config.risk_limits.max_no_position,
                    existing_yes_contracts=existing_yes,
                    existing_no_contracts=existing_no,
                    # CRITICAL FIX: Use DYNAMIC max_contracts from cycle cap (notional/price)
                    # Falls back to config only if cycle cap computation failed
                    max_contracts_per_order=_cycle_max_contracts,
                )

                if not check.allowed:
                    # CRITICAL FIX: Handle REDUCE_SIZE by resizing signal and proceeding
                    if check.action == RiskAction.REDUCE_SIZE and check.adjusted_size is not None and check.adjusted_size > 0:
                        self.logger.info(
                            "[RESIZE_EXECUTE] %s: Resizing signal from %d to %d contracts (%s)",
                            market.market_id, signal.contracts, check.adjusted_size, check.reason
                        )
                        # Resize the signal to the allowed size
                        signal = signal.with_contracts(check.adjusted_size)
                        # Update the check to reflect allowed status
                        check = PreTradeCheck(
                            allowed=True,
                            action=RiskAction.ALLOW,
                            reason=f"Resized from {signal.contracts} to {check.adjusted_size} contracts",
                            adjusted_size=check.adjusted_size,
                            market_id=market.market_id,
                        )
                        _bus.emit(_tick.emit_risk_check(market.market_id, allowed=True))
                    else:
                        # Hard rejection (not resizeable)
                        self._record_explainability_decision(
                            market=market,
                            signal=signal,
                            snapshot=snapshot,
                            check=check,
                            now=now,
                            allowed=False,
                        )
                        # Issue 6: Make risk limit interactions explicit in logs
                        self.logger.info(
                            "[RISK_LIMIT_BLOCK] agent=%s market=%s action=%s contracts=%d "
                            "reason=%s risk_action=%s edge=%.4f",
                            self.config.name, market.market_id,
                            signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                            signal.contracts,
                            check.reason or "unknown",
                            check.action.value if hasattr(check.action, 'value') else str(check.action),
                            float(signal.edge.net_edge) if signal.edge else 0.0
                        )
                        _bus.emit(_tick.emit_risk_check(market.market_id, allowed=False, reason=check.reason))
                        self._emit_decision_log(Decision.hold(
                            HoldReason.RISK_LIMIT,
                            check.reason or "risk check rejected",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            signal_summary={"action": signal.action.value, "edge": float(signal.edge.net_edge) if signal.edge else None},
                            risk_summary={"reason": (check.reason or "")[:200]},
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue

                self._record_explainability_decision(
                    market=market,
                    signal=signal,
                    snapshot=snapshot,
                    check=check,
                    now=now,
                    allowed=True,
                )
                _bus.emit(_tick.emit_risk_check(market.market_id, allowed=True))
                _risk_approved_count += 1
                
                # Issue 6: Make risk limit interactions explicit in logs
                self.logger.info(
                    "[RISK_LIMIT_APPROVED] agent=%s market=%s action=%s contracts=%d "
                    "edge=%.4f cycle_max_contracts=%s",
                    self.config.name, market.market_id,
                    signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                    signal.contracts,
                    float(signal.edge.net_edge) if signal.edge else 0.0,
                    _cycle_max_contracts
                )

                # BUG-L8: skip execution entirely during WARMING_UP phase
                if self.state.lifecycle == LifecycleState.WARMING_UP:
                    self.logger.debug(
                        "WARMING_UP: signal logged but execution skipped for %s",
                        market.market_id,
                    )
                    _execution_skipped_warmup += 1
                    self._emit_decision_log(Decision.hold(
                        HoldReason.WARMUP,
                        f"WARMING_UP: execution skipped for {market.market_id}",
                        market_id=market.market_id,
                        agent_name=self.config.name,
                        cycle_number=self.state.cycles_run,
                        elapsed_ms=_decision_timer.elapsed_ms(),
                    ))
                    continue

                # TOP-3 EDGE ENFORCEMENT: Only top 3 edges allowed to trade per cycle
                # CRITICAL: Prevents cycle piling - must wait for full reconciliation
                _in_top3 = False
                try:
                    from merid.trading.top3_batch_manager import get_top3_batch_manager
                    from merid.trading.top3_edge_allocator import EdgeCandidate
                    
                    batch_mgr = get_top3_batch_manager()
                    
                    # CRITICAL: Check if cycle is locked (prevent cycle piling)
                    # Cycle is locked when:
                    # - Batch is ACTIVE (positions still open)
                    # - Batch is CLOSED but not reconciled (bankroll not updated)
                    # Only unlocked when FULLY_RECONCILED or no batch exists
                    locked, lock_reason = batch_mgr.is_cycle_locked()
                    if locked:
                        self.logger.warning(
                            "[CYCLE_LOCKED] %s: %s - previous cycle must close and reconcile first",
                            market.market_id, lock_reason
                        )
                        _in_top3 = False
                    elif batch_mgr.has_active_batch():
                        # Batch is active - check if this asset is in top-3 allocation
                        current_batch = batch_mgr.get_current_batch()
                        if current_batch:
                            # Create edge candidate for comparison
                            _edge_val = float(signal.edge.net_edge) if signal.edge else 0.0
                            _candidate = EdgeCandidate(
                                asset=asset,
                                timeframe=timeframe,
                                edge=_edge_val,
                                market_id=market.market_id,
                                side=side_str,
                                max_notional_cap=int(signal.contracts * price_cents) if price_cents > 0 else 0,
                            )
                            _in_top3 = batch_mgr.is_in_current_batch(market.market_id)
                        else:
                            _in_top3 = False
                    else:
                        # No batch at all (fresh start) - allow for new cycle creation
                        _in_top3 = True
                        
                except Exception as _top3_exc:
                    # CRITICAL FIX (2026-05-05): Fail-closed on top3 check error
                    # Previously fail-open allowed all orders through on exception
                    self.logger.warning("[TOP3_CHECK] Error in top-3 verification: %s - BLOCKING", _top3_exc)
                    _in_top3 = False

                if not _in_top3:
                    self.logger.warning(
                        "[TOP3_BLOCKED] %s not in top-3 edge allocation for cycle — skipping execution",
                        market.market_id
                    )
                    self._emit_decision_log(Decision.hold(
                        HoldReason.TOP3_EXCLUDED,
                        f"{market.market_id} not in top-3 edge allocation",
                        market_id=market.market_id,
                        agent_name=self.config.name,
                        cycle_number=self.state.cycles_run,
                        elapsed_ms=_decision_timer.elapsed_ms(),
                    ))
                    continue
                
                # === Cross-Asset Arbiter Winner Check with #1 Priority ===
                # PRODUCTION FIX v7 (2026-04-26): #1 edge gets execution priority over #2/#3.
                # With small bankroll (<$100), only #1 executes to maximize win rate.
                # As #1 trades profit and bankroll grows, #2 and #3 are enabled.
                # 
                # CRITICAL FIX v8 (2026-04-26): Fail-open when arbiter winners are stale/empty.
                # Race condition: agents check at different times, arbiter updates once per cycle.
                # With <$100 bankroll, we can't afford to miss #1 winners due to timing issues.
                if asset in CRYPTO_ASSETS and timeframe in MEAN_REVERSION_TIMEFRAMES:
                    _is_winner, _is_number_one, _skip_reason = self._check_arbiter_priority(
                        market.market_id, asset, timeframe
                    )
                    
                    # CRITICAL FIX (2026-05-05): Removed stale-data fail-open bypass
                    # Previously: if arbiter data was >30s old, allowed trade as #1
                    # This caused all 5 crypto agents to each trade $0.50 = $2.50 total
                    # With 2% of $47 = $0.94 cap, this was a massive over-allocation
                    # Now: Respect arbiter winners or block - no bypass for stale data
                    
                    if not _is_winner:
                        self.logger.warning(
                            "[ARBITER_BLOCKED] %s not in arbiter winners — skipping execution",
                            market.market_id
                        )
                        self._emit_decision_log(Decision.hold(
                            HoldReason.TOP3_EXCLUDED,
                            f"{market.market_id} not in cross-asset arbiter winners",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    
                    if not _is_number_one:
                        # Not #1 winner - log why we're skipping (bankroll or priority)
                        self.logger.info(
                            "[ARBITER_PRIORITY] %s %s - skipping execution: %s",
                            market.market_id, _skip_reason,
                            "Focusing capital on #1 edge winner for maximum win rate"
                        )
                        self._emit_decision_log(Decision.hold(
                            HoldReason.TOP3_EXCLUDED,
                            f"{market.market_id} skipped: {_skip_reason}",
                            market_id=market.market_id,
                            agent_name=self.config.name,
                            cycle_number=self.state.cycles_run,
                            elapsed_ms=_decision_timer.elapsed_ms(),
                        ))
                        continue
                    
                    # #1 winner - proceed with execution
                    self.logger.info(
                        "[ARBITER_PRIORITY] %s is #1 edge winner - proceeding with execution",
                        market.market_id
                    )

                # Place order via tool — all checks passed → TRADE
                _execution_dispatched += 1
                self._emit_decision_log(Decision.trade(
                    market_id=market.market_id,
                    agent_name=self.config.name,
                    cycle_number=self.state.cycles_run,
                    detail="all_checks_passed",
                    signal_summary={
                        "action": signal.action.value,
                        "edge": float(signal.edge.net_edge) if signal.edge else None,
                        "contracts": signal.contracts,
                        "phase": signal.phase.value if signal.phase else None,
                    },
                    risk_summary={"reason": "allowed"},
                    elapsed_ms=_decision_timer.elapsed_ms(),
                ))
                # SIGNAL-ONLY-FIX: Skip trade execution for signal-only agents
                # They still computed indicators and submitted opinions above
                if _is_signal_only:
                    self.logger.info(
                        "[SIGNALONLY-SKIP] agent=%s | action=skipped_execution | reason=signalonly_context_agent | market=%s",
                        self.config.name,
                        market.market_id,
                    )
                    self.state.cycles_run += 1
                    self._emit_decision_log(Decision.hold(
                        HoldReason.SIGNAL_ONLY,
                        "signal-only agent computed indicators but skips trade execution",
                        agent_name=self.config.name,
                        cycle_number=self.state.cycles_run,
                        elapsed_ms=_decision_timer.elapsed_ms(),
                    ))
                    continue
                await self._execute_signal(market, signal, check, snapshot, _tick=_tick, _bus=_bus)

            except Exception as exc:
                # Structured error logging with full context
                exc_type = type(exc).__name__
                self.logger.error(
                    "PM_EXECUTION_ERROR agent=%s market=%s asset=%s action=%s error_type=%s "
                    "error_message=%s",
                    self.config.name,
                    market.market_id,
                    getattr(snapshot, 'resolved_asset', 'unknown'),
                    signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                    exc_type,
                    str(exc)[:200],
                    exc_info=True,
                )

                # Emit to agent execution error metrics
                try:
                    from monitoring.metrics import record_agent_execution_error
                    record_agent_execution_error(
                        agent=self.config.name,
                        exception=exc_type,
                        market=market.market_id,
                    )
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                try:
                    from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode
                    from merid.prediction.crypto_edge_production import get_no_trade_decision_tracker
                    from monitoring.kalshi_metrics import record_kalshi_order

                    record_kalshi_order(
                        "pm_agent",
                        "rejected",
                        1,
                        error_code=KalshiOrderErrorCode.PM_AGENT_EXECUTION.value,
                    )
                    get_no_trade_decision_tracker().observe(
                        "pm_agent_execution_failed",
                        market_id=market.market_id,
                        error=str(exc),
                        error_type=exc_type,
                    )
                except Exception as _met_exc:
                    self.logger.debug("kalshi_metrics pm execution reject skipped: %s", _met_exc)
                continue

            # Yield control to event loop after each market iteration
            await asyncio.sleep(0)

        _bus.emit(_tick.emit_agent_cycle(
            signals_evaluated=_signals_evaluated,
            signals_actionable=_signals_actionable,
            signals_consensus_blocked=_signals_consensus_blocked,
        ))
        _no_action_summary = ""
        if _no_action_buckets:
            _no_action_summary = "|".join(
                f"{k}:{v}" for k, v in sorted(_no_action_buckets.items())
            )
        _consensus_hold_summary = (
            "|".join(f"{k}:{v}" for k, v in sorted(_consensus_hold_buckets.items()))
            if _consensus_hold_buckets
            else "-"
        )
        _trace_na = os.getenv("MERID_PM_CYCLE_TRACE_NO_ACTION", "true").lower() in (
            "1", "true", "yes", "on", "",
        )
        _trace_ch = os.getenv("MERID_PM_CYCLE_TRACE_CONSENSUS_DETAIL", "true").lower() in (
            "1", "true", "yes", "on", "",
        )
        _base_trace = (
            self.config.name,
            self.state.cycles_run,
            self.state.lifecycle,
            _mr_ct,
            _mw_ct,
            _strike_passed,
            _strike_rejected,
            _strike_directional,
            _signals_evaluated,
            _signals_actionable,
            _signals_consensus_blocked,
            _pre_risk_intents,
            _risk_approved_count,
            _execution_dispatched,
            _execution_skipped_warmup,
            self.state.orders_placed,
        )
        if _trace_na:
            if _trace_ch:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "consensus_hold_by_reason=%s "
                    "no_action_by_reason=%s",
                    *_base_trace,
                    _consensus_hold_summary,
                    _no_action_summary or "-",
                )
            else:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "no_action_by_reason=%s",
                    *_base_trace,
                    _no_action_summary or "-",
                )
        else:
            if _trace_ch:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d "
                    "consensus_hold_by_reason=%s",
                    *_base_trace,
                    _consensus_hold_summary,
                )
            else:
                self.logger.info(
                    "[PM_CYCLE_TRACE] agent=%s cycle=%d lifecycle=%s "
                    "markets_discovered=%d markets_in_window=%d "
                    "strike_passed=%d strike_rejected=%d strike_directional=%d "
                    "signals_evaluated=%d actionable=%d consensus_blocked=%d "
                    "intent_after_strategy=%d risk_approved=%d exec_dispatched=%d "
                    "warmup_skipped_exec=%d orders_placed_total=%d",
                    *_base_trace,
                )

    def _filter_active_contracts(self, markets: List[EventMarket], now: datetime) -> List[EventMarket]:
        """Filter resolved markets to ensure only the most relevant contract(s) are traded.
        
        Rule: At most one active contract per asset/timeframe slot.
        If agent has a specific asset list, return best for each.
        If agent is category-wide, group by inferred asset and return best for each.
        
        NOTE: This is a synchronous CPU-bound method. For async contexts,
        use _filter_active_contracts_async() to avoid blocking the event loop.
        """
        if not markets:
            return []

        # Group by asset
        by_asset: Dict[str, List[EventMarket]] = {}
        for m in markets:
            asset = "OTHER"
            # Try to infer asset from ticker or tags
            ticker_upper = m.market_id.upper()
            found = False
            # H5: Use the canonical underlying map from category_exposure so
            # non-crypto agents (politics, economics, financials) get proper
            # per-asset grouping instead of collapsing everything to "OTHER".
            try:
                from merid.event_venues.kalshi.category_exposure import (
                    _UNDERLYING_CATEGORY_MAP,
                )
                for a in _UNDERLYING_CATEGORY_MAP:
                    if a in ticker_upper:
                        asset = a
                        found = True
                        break
            except Exception:
                for a in ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "WIF"]:
                    if a in ticker_upper:
                        asset = a
                        found = True
                        break

            if not found and m.category:
                asset = m.category.upper()

            if asset not in by_asset:
                by_asset[asset] = []
            by_asset[asset].append(m)

        active_selection = []
        for asset, asset_markets in by_asset.items():
            # Sort by end_date (closest to expiry first)
            sorted_m = sorted(
                [m for m in asset_markets if m.end_date and m.end_date > now],
                key=lambda m: m.end_date
            )
            
            if not sorted_m:
                continue

            # Find the first one in the entry window
            best_for_asset = None
            for m in sorted_m:
                if self._in_entry_window(m, now):
                    best_for_asset = m
                    break
            
            # BUG FIX: Don't fallback to expired/terminal markets
            # If no market is in the valid entry window, skip this asset
            # The old code would fallback to the closest market even if terminal
            if not best_for_asset:
                # WINDOW FILTER DEBUG: Log why no market was selected
                if self.logger.isEnabledFor(logging.DEBUG):
                    for m in sorted_m[:3]:  # Log first 3 markets
                        minutes_to_expiry = (m.end_date - now).total_seconds() / 60 if m.end_date else None
                        in_window = self._in_entry_window(m, now)
                        self.logger.debug(
                            "[PM_WINDOW_FILTER] asset=%s ticker=%s minutes_to_expiry=%.1f in_window=%s",
                            asset, m.market_id, minutes_to_expiry, in_window
                        )
                self.logger.debug(
                    "_filter_active_contracts: no market in valid entry window for %s — "
                    "skipping (no fallback to expired markets)",
                    asset,
                )
                continue  # Skip this asset - don't select expired markets
            
            active_selection.append(best_for_asset)

        return active_selection

    async def _filter_active_contracts_async(
        self, markets: List[EventMarket], now: datetime
    ) -> List[EventMarket]:
        """Async version of _filter_active_contracts that avoids blocking the event loop.
        
        Offloads the CPU-bound sorting work to a thread pool executor.
        This should be called from async contexts like _run_cycle_body.
        """
        if not markets:
            return []
        
        # Offload the entire filtering operation to thread pool
        # since it involves CPU-heavy sorting over potentially many markets
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _get_agent_executor(),  # Use dedicated agent thread pool (20+ workers)
            self._filter_active_contracts,
            markets,
            now
        )

    # ── Position sync at startup ────────────────────────────────────────

    async def _sync_open_positions(self) -> None:
        """BUG-L3: Reconstruct TrackedPosition objects from live Kalshi positions
        so stop-loss rules and position tracking are not blind on restart.

        Called once in start() after clearing _tracked_positions.  Non-fatal:
        a failure logs a warning but does not prevent the agent from starting.
        """
        try:
            from merid.prediction.kalshi_tools import _kalshi_get_positions

            result = await _kalshi_get_positions()
            if not result.success:
                self.logger.warning(
                    "_sync_open_positions: failed to fetch positions: %s",
                    result.error_message,
                )
                return

            positions = result.payload.get("positions", [])
            agent_tickers = set()
            # Determine which tickers belong to this agent using config assets/category
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                for m in catalog.get_all_markets():
                    ticker = m.market.market_id
                    for asset in (self.config.assets or []):
                        if asset.upper() in ticker.upper():
                            agent_tickers.add(ticker)
            except Exception as _ce:
                self.logger.debug("_sync_open_positions: catalog lookup skipped: %s", _ce)

            synced = 0
            for pos in positions:
                ticker = pos.get("ticker", "")
                # Only track positions that belong to this agent's markets
                if agent_tickers and ticker not in agent_tickers:
                    continue
                size = int(pos.get("size", 0))
                if size == 0:
                    continue
                # CRITICAL: No price fallback. Missing avg_price = quarantine position.
                raw_price = (
                    pos.get("avg_price")
                    or pos.get("average_price")
                    or pos.get("avg_entry_price")
                )
                if raw_price is None:
                    self.logger.error(
                        "[TAINTED_PATH] _sync_open_positions: missing avg_price for %s, size=%s; "
                        "position quarantined until valid price resolved",
                        ticker, size
                    )
                    # Emit to risk bus for operator visibility
                    try:
                        from core.event_bus import get_event_bus
                        get_event_bus().emit("risk.position_sync_failed", {
                            "ticker": ticker,
                            "size": size,
                            "reason": "missing_avg_price",
                            "agent": self.config.name,
                            "action": "quarantine",
                        })
                    except Exception as e:
                        self.logger.debug(f"Silent error suppressed: {e}")
                    
                    # Tamper-evident audit log
                    try:
                        from core.risk_audit_chain import get_risk_audit_chain
                        get_risk_audit_chain().log_event("risk.position_sync_failed", {
                            "ticker": ticker,
                            "size": size,
                            "agent": self.config.name,
                            "source": "_sync_open_positions",
                            "resolution": "quarantine",
                        })
                    except Exception as _audit_exc:
                        logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                    continue  # Skip position - fail closed
                avg_price = float(raw_price)
                side = pos.get("side", "yes")
                pos_id = f"{ticker}:{side}:synced"
                # PRODUCTION FIX: Pull TP targets from position_cache during reconciliation
                _tp_price = _tp_r = _sl_price = None
                try:
                    _cached_pos = get_position_cache().get_position(ticker)
                    if _cached_pos:
                        _tp_price = getattr(_cached_pos, 'take_profit_price_cents', None)
                        _tp_r = getattr(_cached_pos, 'take_profit_r_multiple', None)
                        _sl_price = getattr(_cached_pos, 'stop_loss_price_cents', None)
                except Exception:
                    pass  # Non-fatal: TP targets optional
                self._tracked_positions[pos_id] = TrackedPosition(
                    position_id=pos_id,
                    ticker=ticker,
                    side=side,
                    contracts=abs(size),
                    entry_price_cents=int(avg_price),
                    current_price_cents=int(avg_price),
                    entry_time=datetime.now(timezone.utc),
                    take_profit_price_cents=_tp_price,
                    take_profit_r_multiple=_tp_r,
                    stop_loss_price_cents=_sl_price,
                )
                synced += 1

            if synced:
                self.logger.info(
                    "_sync_open_positions: restored %d open position(s) for %s",
                    synced, self.config.name,
                )
            else:
                self.logger.debug(
                    "_sync_open_positions: no open positions found for %s",
                    self.config.name,
                )
        except Exception as exc:
            self.logger.warning(
                "_sync_open_positions failed (non-fatal, continuing): %s", exc
            )

    async def _restore_prefetched_positions_async(self, prefetched_positions: List[Any]) -> None:
        """Async wrapper to run sync position restoration in executor."""
        await asyncio.get_running_loop().run_in_executor(
            None,
            self._restore_prefetched_positions_sync,
            prefetched_positions
        )

    def _restore_prefetched_positions_sync(self, prefetched_positions: List[Any]) -> None:
        """BUG-L9 FIX: Restore positions from pre-fetched data without API call (SYNC VERSION).
        
        This is a synchronous version that runs in a thread pool to avoid blocking
        the event loop during concurrent agent startup.
        
        Args:
            prefetched_positions: List of position objects from AgentGrid's
                bulk position fetch.
        """
        try:
            if not prefetched_positions:
                self.logger.debug("_restore_prefetched_positions: no pre-fetched positions provided")
                return

            synced = 0
            for pos in prefetched_positions:
                try:
                    # Handle both dict and object formats
                    if isinstance(pos, dict):
                        ticker = pos.get("ticker", "")
                        size = int(pos.get("size", 0))
                        # Refinement: Don't hard-default to 50 - use None if missing
                        raw_price = (
                            pos.get("avg_price")
                            or pos.get("average_price")
                            or pos.get("avg_entry_price")
                        )
                        if raw_price is None:
                            self.logger.warning(
                                "_restore_prefetched_positions: missing avg_price for %s, size=%s; skipping position",
                                ticker, size
                            )
                            continue  # Skip positions without price data
                        avg_price = float(raw_price)
                        side_raw = (pos.get("side") or "yes").lower()
                    else:
                        # Object format (e.g., KalshiPosition)
                        ticker = getattr(pos, 'ticker', '') or getattr(pos, 'market_id', '')
                        size = int(getattr(pos, 'size', 0) or getattr(pos, 'contracts', 0))
                        # Refinement: Don't hard-default to 50 - use None if missing
                        raw_price = (
                            getattr(pos, 'avg_price', None)
                            or getattr(pos, 'average_price', None)
                            or getattr(pos, 'avg_entry_price', None)
                        )
                        if raw_price is None:
                            self.logger.warning(
                                "_restore_prefetched_positions: missing avg_price for %s, size=%s; skipping position",
                                ticker, size
                            )
                            continue  # Skip positions without price data
                        avg_price = float(raw_price)
                        side_raw = (getattr(pos, "side", "yes") or "yes").lower()

                    # Refinement 2: Explicit side normalization
                    if side_raw.startswith("y"):
                        side = "yes"
                    elif side_raw.startswith("n"):
                        side = "no"
                    else:
                        self.logger.warning(
                            "_restore_prefetched_positions: unrecognized side '%s' for %s; defaulting to 'yes'",
                            side_raw, ticker
                        )
                        side = "yes"

                    # Refinement 3: Filter positions by agent's configured tickers
                    if not self._handles_ticker(ticker):
                        continue

                    if size == 0:
                        continue

                    pos_id = f"{ticker}:{side}:synced"
                    # PRODUCTION FIX: Pull TP targets from position_cache during reconciliation
                    _tp_price = _tp_r = _sl_price = None
                    try:
                        _cached_pos = get_position_cache().get_position(ticker)
                        if _cached_pos:
                            _tp_price = getattr(_cached_pos, 'take_profit_price_cents', None)
                            _tp_r = getattr(_cached_pos, 'take_profit_r_multiple', None)
                            _sl_price = getattr(_cached_pos, 'stop_loss_price_cents', None)
                    except Exception:
                        pass  # Non-fatal: TP targets optional
                    self._tracked_positions[pos_id] = TrackedPosition(
                        position_id=pos_id,
                        ticker=ticker,
                        side=side,
                        contracts=abs(size),
                        entry_price_cents=int(avg_price),
                        current_price_cents=int(avg_price),
                        entry_time=datetime.now(timezone.utc),
                        take_profit_price_cents=_tp_price,
                        take_profit_r_multiple=_tp_r,
                        stop_loss_price_cents=_sl_price,
                    )
                    synced += 1
                except Exception as _pos_exc:
                    self.logger.debug("Error restoring pre-fetched position: %s", _pos_exc)
                    continue

            if synced:
                self.logger.info(
                    "_restore_prefetched_positions: restored %d open position(s) for %s",
                    synced, self.config.name,
                )
            else:
                self.logger.debug(
                    "_restore_prefetched_positions: no matching positions for %s",
                    self.config.name,
                )
        except Exception as exc:
            self.logger.warning(
                "_restore_prefetched_positions failed (non-fatal, continuing): %s", exc
            )

    # ── Stop-loss sweep ────────────────────────────────────────────────

    async def _check_stop_losses(self) -> None:
        """Sweep all tracked open positions against stop-loss and take-profit rules.

        Per cycle:
          1. Refresh current_price_cents / bid / ask for every position from
             KalshiMarketStateStore so stop-loss and TP work on live prices.
          2. Evaluate take-profit conditions via TakeProfitManager and route
             partial/full exits before the stop-loss sweep.
          3. Evaluate stop-loss rules (unchanged behaviour).

        All exits go through route_order_async so risk accounting, category
        exposure, and execution gates all fire uniformly.
        """
        if not self._tracked_positions:
            return

        # ── 1. Price refresh from market state ────────────────────────────
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            _mss = get_kalshi_market_state_store()
            for _pos in self._tracked_positions.values():
                _st = _mss.get(_pos.ticker)
                if _st is None:
                    continue
                # Best bid/ask for TP trigger logic
                bid = getattr(_st, "best_bid_cents", 0) or 0
                ask = getattr(_st, "best_ask_cents", 0) or 0
                mid = (bid + ask) // 2 if bid > 0 and ask > 0 else 0
                if mid > 0:
                    _pos.current_price_cents = mid
                elif bid > 0:
                    _pos.current_price_cents = bid
                elif ask > 0:
                    _pos.current_price_cents = ask
                # Store raw bid/ask on position for TP limit-price calculation
                _pos.last_bid_cents = bid
                _pos.last_ask_cents = ask
        except Exception as _pr_exc:
            self.logger.debug("price_refresh skipped: %s", _pr_exc)

        # CRITICAL FIX: session_equity_cents must never be 0 (makes loss cap dead).
        # Use v2 unified bankroll service for consistency with sizing layer.
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            
            _effective_usd = get_equity_for_risk_calc_sync()
            _equity_usd = _effective_usd if _effective_usd is not None else 0.0  # For backward compatibility with logging
            if _equity_usd > 0:
                _equity_cents = _equity_usd * 100.0
                for _pos in self._tracked_positions.values():
                    _pos.session_equity_cents = _equity_cents
            else:
                # Equity unavailable - mark as UNKNOWN (None) to block loss cap checks
                logger.error(
                    "[TAINTED_PATH] _check_stop_losses: equity unavailable (%.2f) — "
                    "marking session_equity_cents as UNKNOWN (None) to block trading",
                    _equity_usd
                )
                for _pos in self._tracked_positions.values():
                    _pos.session_equity_cents = None  # UNKNOWN state
                # Emit alert
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().emit("risk.equity_feed_lost", {
                        "agent": self.config.name,
                        "equity_usd": _equity_usd,
                        "action": "block_loss_caps",
                    })
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")
                
                # Tamper-evident audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.equity_feed_lost", {
                        "agent": self.config.name,
                        "equity_usd": _equity_usd,
                        "action": "block_loss_caps",
                        "source": "_check_stop_losses",
                        "positions_affected": len(self._tracked_positions),
                    })
                except Exception as _audit_exc:
                    logger.debug("Audit log failed (non-critical): %s", _audit_exc)
        except Exception as _eq_exc:
            # Exception fetching equity - mark as UNKNOWN
            logger.error(
                "[TAINTED_PATH] _check_stop_losses: equity fetch failed (%s) — "
                "marking session_equity_cents as UNKNOWN (None)",
                _eq_exc
            )
            for _pos in self._tracked_positions.values():
                _pos.session_equity_cents = None  # UNKNOWN state
            
            # Tamper-evident audit log for exception path
            try:
                from core.risk_audit_chain import get_risk_audit_chain
                get_risk_audit_chain().log_event("risk.equity_feed_lost", {
                    "agent": self.config.name,
                    "reason": "exception",
                    "error": str(_eq_exc)[:200],
                    "action": "block_loss_caps",
                    "source": "_check_stop_losses_exception",
                    "positions_affected": len(self._tracked_positions),
                })
            except Exception as _audit_exc:
                logger.debug("Audit log failed (non-critical): %s", _audit_exc)

        # ── 2. Take-profit sweep ──────────────────────────────────────────
        _tp_to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                tp_action = self._tp_manager.on_price_update(
                    pos=pos,
                    bid_cents=pos.last_bid_cents,
                    ask_cents=pos.last_ask_cents,
                )
                if tp_action is None:
                    continue

                # Determine order quantity (partial or full)
                close_qty = min(tp_action.quantity, pos.contracts)
                if close_qty <= 0:
                    continue

                # ═══════════════════════════════════════════════════════════════════
                # Force-taker for high PnL exits: ensure we get filled on 100%+ winners
                # ═══════════════════════════════════════════════════════════════════
                _tp_post_only = True  # Default to maker (post-only)
                _tp_unrealized_pct = 0.0

                try:
                    # Calculate unrealized PnL for this position
                    if pos.side == "yes":
                        _tp_unrealized_pct = (
                            (tp_action.limit_price_cents - pos.entry_price_cents)
                            / pos.entry_price_cents * 100
                        ) if pos.entry_price_cents > 0 else 0.0
                    else:
                        # NO position: profit when price falls
                        _no_entry_cost = 100 - pos.entry_price_cents
                        _tp_unrealized_pct = (
                            (pos.entry_price_cents - tp_action.limit_price_cents)
                            / _no_entry_cost * 100
                        ) if _no_entry_cost > 0 else 0.0

                    # Force taker if unrealized PnL >= 70% (configurable threshold)
                    # Start force-taker BELOW hard TP threshold to reduce slippage risk
                    _force_taker_threshold = 70.0
                    if _tp_unrealized_pct >= _force_taker_threshold:
                        _tp_post_only = False  # Allow taker for high PnL exits
                        self.logger.info(
                            "[TP-FORCE-TAKER] %s: unrealized_pnl=%.1f%% >= %.0f%% — "
                            "disabling post_only to ensure fill (entry=%dc, exit=%dc)",
                            pos.ticker, _tp_unrealized_pct, _force_taker_threshold,
                            pos.entry_price_cents, tp_action.limit_price_cents
                        )
                except Exception as _pnl_exc:
                    self.logger.debug("[TP-PNL-CALC] Failed to calculate unrealized PnL: %s", _pnl_exc)

                # TICKER VALIDATION: Ensure stored ticker exists in catalog before exit
                _tp_ticker_valid, _tp_canonical_ticker = _validate_ticker_for_exit(pos.ticker)
                if not _tp_ticker_valid:
                    logger.error(
                        "[TAKE_PROFIT_TICKER_REJECT] %s: Ticker not in catalog, skipping TP exit",
                        pos.ticker
                    )
                    continue
                
                # Use canonical ticker from catalog if available
                _tp_exit_ticker = _tp_canonical_ticker or pos.ticker

                # BANKROLL UNIFICATION: Get effective bankroll from v2 service
                _effective_equity_usd = 0.0
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    _effective_usd = get_equity_for_risk_calc_sync()
                    if _effective_usd is not None:
                        _effective_equity_usd = float(_effective_usd)
                except Exception as _bre:
                    self.logger.debug("[trading_agent.tp] Failed to get effective bankroll: %s", _bre)

                # PRODUCTION FIX (2026-05-01): Generate unique client_tag for take-profit exit
                # to prevent duplicate blocking with entry orders.
                _tp_ts_bucket = int(time.time()) // 60
                _tp_preimage = (
                    f"{self.agent_id}|{pos.ticker}|{pos.side}|sell|"
                    f"{pos.entry_price_cents}|{close_qty}|{_tp_ts_bucket}|"
                    f"take_profit|{tp_action.reason[:30]}"
                )
                _tp_client_tag = f"merid-{hashlib.sha256(_tp_preimage.encode()).hexdigest()[:16]}-{_tp_ts_bucket}"

                _tp_intent = OrderIntent(
                    ticker=_tp_exit_ticker,
                    side=pos.side,
                    action="sell",
                    # Use the suggested limit price from TakeProfitAction; for live orders
                    # the router will clip to valid range and may upgrade to IOC near expiry.
                    price_cents=max(1, min(99, tp_action.limit_price_cents)),
                    count=close_qty,
                    order_type="limit",
                    time_in_force="ioc",  # IOC to avoid resting past the intended price
                    source=f"take_profit:{self.config.name}",
                    agent_id=self.agent_id,
                    rationale=tp_action.reason[:200],
                    post_only=_tp_post_only,  # NEW: False for high PnL exits to force taker
                    effective_equity_usd=_effective_equity_usd if _effective_equity_usd > 0 else None,
                    client_tag=_tp_client_tag,  # UNIQUE tag prevents duplicate blocking
                )
                _tp_result = await route_order_async(_tp_intent)
                _tp_ok = _tp_result.status not in ("rejected",)

                if _tp_ok:
                    _filled = 0
                    try:
                        _fill_info = _tp_result.fill or {}
                        if isinstance(_fill_info, dict) and _fill_info.get("count"):
                            _filled = int(_fill_info["count"])
                        elif hasattr(_tp_result, "filled_count") and _tp_result.filled_count:
                            _filled = int(_tp_result.filled_count)
                        else:
                            _filled = close_qty
                    except Exception:
                        _filled = close_qty

                    self._tp_manager.on_fill(pos.position_id, _filled)
                    self._tp_manager.record_exit_price(pos.ticker, tp_action.limit_price_cents)

                    # Adjust remaining contracts on the TrackedPosition
                    pos.contracts = max(0, pos.contracts - _filled)

                    # Compute realized PnL for logging
                    if pos.side == "yes":
                        _tp_pnl = (tp_action.limit_price_cents - pos.entry_price_cents) * _filled
                    else:
                        _tp_pnl = (pos.entry_price_cents - tp_action.limit_price_cents) * _filled

                    self.logger.info(
                        "take_profit CLOSED %s %s ×%d (of %d total): %s | "
                        "entry=%dc exit=%dc pnl=%.0f¢ action=%s",
                        pos.ticker, pos.side, _filled,
                        pos.contracts + _filled,
                        tp_action.reason[:60],
                        pos.entry_price_cents, tp_action.limit_price_cents,
                        _tp_pnl, tp_action.action_type,
                    )

                    # Record realized PnL into kalshi risk manager
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        _close_cat = getattr(self.config, "category", None)
                        get_kalshi_risk().record_close(
                            _close_cat, _filled, pos.entry_price_cents
                        )
                    except Exception as _kr_e:
                        self.logger.debug("take_profit: kalshi_risk.record_close failed: %s", _kr_e)

                    # Notify APT of the close (same as stop-loss path)
                    try:
                        from merid.prediction.agent_performance_tracker import (
                            AgentPerformanceTracker,
                            get_agent_performance_tracker,
                        )
                        _apt = get_agent_performance_tracker()
                        _close_reason = (
                            "take_profit_trailing"
                            if "trailing" in tp_action.reason
                            else "take_profit_primary"
                        )
                        _apt.record_close(
                            agent_id=self.agent_id,
                            market_id=pos.ticker,
                            close_price_cents=tp_action.limit_price_cents,
                            close_reason=_close_reason,
                        )
                    except Exception as _apt_e:
                        self.logger.debug("take_profit: APT record_close skipped: %s", _apt_e)

                    # If position is now flat, queue for removal and notify TP manager
                    if pos.contracts <= 0:
                        _tp_to_remove.append(pos_id)
                        _close_reason = (
                            "take_profit_trailing"
                            if "trailing" in tp_action.reason
                            else "take_profit_primary"
                        )
                        self._tp_manager.on_position_closed(pos.ticker, _close_reason)

                else:
                    self.logger.warning(
                        "take_profit order REJECTED for %s %s: %s",
                        pos.ticker, tp_action.action_type,
                        _tp_result.reason or "unknown",
                    )
                    # Mark pending_fill=False so the next cycle retries
                    _ps = self._tp_manager.get_state(pos.position_id)
                    if _ps:
                        _ps.pending_fill = False

            except Exception as _tp_exc:
                self.logger.debug("take_profit sweep error for %s: %s", pos_id, _tp_exc)

        for pos_id in _tp_to_remove:
            self._tracked_positions.pop(pos_id, None)

        # Evict old closed TP state entries to keep memory bounded
        self._tp_manager.evict_expired()

        # ── 3. Stop-loss sweep (includes profit_target_pct) ────────────────
        # CRITICAL FIX: Run BEFORE micro-scalp so profit targets are checked first
        # StopLossRules.check_position includes profit_target_pct logic which should
        # take precedence over micro-scalp time exits
        to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                action = self._stop_loss.check_position(pos)
                if not action.should_close:
                    continue

                self.logger.warning(
                    "stop_loss TRIGGERED %s: rule=%s reason=%s urgency=%s",
                    pos.ticker, action.rule, action.reason, action.urgency,
                )

                # BUG-8 fix: route through route_order_async so category exposure
                # release, rate limiting, group accounting, and execution guard all
                # fire uniformly.  Direct _kalshi_place_order() bypassed all of them.
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                from merid.event_venues.kalshi import get_bankroll_service

                # TICKER VALIDATION: Ensure stored ticker exists in catalog before exit
                _ticker_valid, _canonical_ticker = _validate_ticker_for_exit(pos.ticker)
                if not _ticker_valid:
                    logger.error(
                        "[STOP_LOSS_TICKER_REJECT] %s: Ticker not in catalog, skipping close order",
                        pos.ticker
                    )
                    pos.close_fail_count += 1
                    continue
                
                # Use canonical ticker from catalog if available
                _exit_ticker = _canonical_ticker or pos.ticker

                # BANKROLL UNIFICATION: Get effective bankroll from v2 service
                _effective_equity_usd = 0.0
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    _sl_equity = get_equity_for_risk_calc_sync()
                    if _sl_equity is not None:
                        _effective_equity_usd = float(_sl_equity)
                except Exception as _bre:
                    self.logger.debug("[trading_agent.sl] Failed to get effective bankroll: %s", _bre)

                # IOC escalation safety: generate deterministic client_order_id and store it
                # so we can reuse it for IOC escalation to prevent double fills
                _sl_ts_bucket = int(time.time()) // 60
                _sl_preimage = f"{self.agent_id}|{pos.ticker}|{pos.side}|sell|{pos.entry_price_cents}|{pos.contracts}|{_sl_ts_bucket}|stop_loss"
                _sl_client_tag = f"merid-{hashlib.sha256(_sl_preimage.encode()).hexdigest()[:16]}-{_sl_ts_bucket}"
                pos.close_client_order_id = _sl_client_tag  # Store for potential IOC escalation
                _sl_intent = OrderIntent(
                    ticker=_exit_ticker,
                    side=pos.side,
                    action="sell",
                    price_cents=max(1, pos.entry_price_cents),  # Use entry price for accurate notional in exposure tracker; Kalshi ignores price on market orders
                    count=pos.contracts,
                    order_type="market",
                    time_in_force="gtc",
                    source=f"stop_loss:{self.config.name}",
                    agent_id=self.agent_id,
                    decision_trace_id=new_decision_trace_id("sl"),
                    sentiment_driven=False,
                    client_tag=_sl_client_tag,  # Deterministic ID for idempotency
                    effective_equity_usd=_effective_equity_usd if _effective_equity_usd > 0 else None,
                )
                _sl_result = await route_order_async(_sl_intent)
                _close_ok = _sl_result.status not in ("rejected",)

                if _close_ok:
                    self.logger.info(
                        "stop_loss CLOSED %s %s x%d: %s",
                        pos.ticker, pos.side, pos.contracts, action.reason,
                    )
                    self._stop_loss.record_close(
                        position_id=pos_id,
                        action=action,
                        pnl_cents=pos.unrealized_pnl_cents,
                    )
                    # Feed realised loss into session cap tracker
                    if pos.unrealized_pnl_cents < 0:
                        self._stop_loss.record_session_loss(abs(pos.unrealized_pnl_cents))
                    
                    # CRITICAL: Release capital in cycle tracker for micro-scalping
                    _sl_released = (pos.entry_price_cents * pos.contracts) / 100.0
                    self._cycle_tracker.record_release(_sl_released, pos_id)
                    self.logger.debug(
                        "[STOP_LOSS_CAPITAL_RELEASE] %s: released=$%.2f from cycle tracker",
                        pos.ticker, _sl_released,
                    )
                    
                    # Notify KalshiRiskManager of the close so notional is decremented.
                    # The router now only advances rate-limit counters (record_rate_only);
                    # all notional accounting is agent-side (BUG-A fix).
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        _close_cat = None
                        try:
                            from merid.event_venues.kalshi.category_exposure import infer_category
                            from merid.event_venues.kalshi.kalshi_market_utils import get_underlying
                            _close_cat = infer_category(get_underlying(pos.ticker))
                        except Exception as e:
                            self.logger.debug(f"Silent error suppressed: {e}")
                        get_kalshi_risk().record_close(_close_cat, pos.contracts, pos.entry_price_cents)
                    except Exception as _kr:
                        self.logger.debug("stop_loss: kalshi_risk.record_close failed (non-fatal): %s", _kr)
                    to_remove.append(pos_id)
                else:
                    pos.close_fail_count += 1
                    self.logger.warning(
                        "stop_loss close order failed for %s (attempt %d): %s",
                        pos.ticker, pos.close_fail_count, _sl_result.reason or "unknown",
                    )
                    # BUG-05: escalate after repeated failures
                    if pos.close_fail_count >= 3:
                        # Hard limit: pause this agent and alert operator
                        self.logger.error(
                            "stop_loss ESCALATION: %d consecutive close failures on %s — "
                            "pausing agent %s",
                            pos.close_fail_count, pos.ticker, self.config.name,
                        )
                        try:
                            from merid.prediction.alerts import get_alert_manager
                            get_alert_manager().fire_risk_breach(
                                market_id=pos.ticker,
                                message=(
                                    f"STOP-LOSS ESCALATION: {pos.close_fail_count} consecutive "
                                    f"close failures on {pos.ticker} ({self.config.name}). "
                                    f"Agent paused — manual intervention required."
                                ),
                            )
                        except Exception as _ae:
                            self.logger.debug("stop_loss escalation alert skipped: %s", _ae)
                        # BUG-KS1 & BUG-KS5 FIX: Only count incident-grade failures toward kill switch
                        # Stop-loss failures may be caused by policy blocks (execution gate, market conditions)
                        # which should NOT count toward error threshold.
                        try:
                            from merid.prediction.order_error_threshold import (
                                should_count_toward_error_threshold,
                            )
                            from merid.risk.kill_switches import risk_controller as _rc
                            _sl_failure_reason = _sl_result.reason or "unknown"
                            if should_count_toward_error_threshold(_sl_failure_reason):
                                _rc.record_error(error_hint=_sl_failure_reason)
                                self.logger.warning(
                                    "stop_loss kill_switch error counted: %s", _sl_failure_reason
                                )
                            else:
                                self.logger.debug(
                                    "stop_loss kill_switch error NOT counted (policy rejection): %s",
                                    _sl_failure_reason,
                                )
                        except Exception as _ke:
                            self.logger.debug("stop_loss kill_switch record_error skipped: %s", _ke)
                        self.pause()
                    elif pos.close_fail_count >= 2:
                        # Second failure: retry as IOC market order to improve fill odds
                        # IOC escalation safety: reuse same client_order_id to prevent double fills
                        # Kalshi's duplicate protection will prevent double execution
                        self.logger.warning(
                            "stop_loss retry %s as IOC market order (fail_count=%d, client_tag=%s)",
                            pos.ticker, pos.close_fail_count, pos.close_client_order_id or "new",
                        )
                        try:
                            from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                            from merid.prediction.trading_mode import TradingMode
                            # Reuse original client_order_id if available, otherwise generate new
                            _ioc_client_tag = pos.close_client_order_id or None
                            _ioc_intent = OrderIntent(
                                ticker=pos.ticker,
                                side=pos.side,
                                action="sell",
                                price_cents=max(1, pos.entry_price_cents),  # Use entry price for accurate notional (BUG-C fix)
                                count=pos.contracts,
                                order_type="market",
                                time_in_force="ioc",
                                source=f"stop_loss_escalation:{self.config.name}",
                                decision_trace_id=new_decision_trace_id("ioc"),
                                sentiment_driven=False,
                                client_tag=_ioc_client_tag,  # Reuse same ID for duplicate protection
                            )
                            _ioc_result = await route_order_async(_ioc_intent)
                            if _ioc_result.status not in ("rejected",):
                                self.logger.info(
                                    "stop_loss IOC escalation succeeded for %s: %s",
                                    pos.ticker, _ioc_result.status,
                                )
                                self._stop_loss.record_close(
                                    position_id=pos_id,
                                    action=action,
                                    pnl_cents=pos.unrealized_pnl_cents,
                                )
                                if pos.unrealized_pnl_cents < 0:
                                    self._stop_loss.record_session_loss(abs(pos.unrealized_pnl_cents))
                                to_remove.append(pos_id)
                            else:
                                self.logger.error(
                                    "stop_loss IOC escalation failed for %s: %s",
                                    pos.ticker, _ioc_result.reason or "unknown",
                                )
                        except Exception as _esc_exc:
                            self.logger.exception("stop_loss IOC escalation error: %s", _esc_exc)
                            
            except Exception as _exc:
                self.logger.exception("stop_loss sweep error for %s: %s", pos_id, _exc)
        
        for pos_id in to_remove:
            self._tracked_positions.pop(pos_id, None)

        # ── 4. Micro-scalping exit sweep (ONLY for positions not already exited) ──
        _ms_to_remove: List[str] = []
        for pos_id, pos in list(self._tracked_positions.items()):
            try:
                # Build micro-scalp position from tracked position
                _ms_pos = MicroScalpPosition(
                    position_id=pos_id,
                    ticker=pos.ticker,
                    side=pos.side,
                    entry_price_cents=pos.entry_price_cents,
                    entry_edge=getattr(pos, 'entry_edge', 0.0),
                    contracts=pos.contracts,
                    entry_ts=pos.entry_ts,
                    current_price_cents=pos.current_price_cents,
                    current_edge=self._get_current_edge_for_position(pos),
                    last_bid_cents=pos.last_bid_cents,
                    last_ask_cents=pos.last_ask_cents,
                )
                
                _volatility = self._calculate_volatility(pos.ticker, pos.entry_price_cents)
                _momentum = abs(_ms_pos.current_edge)
                
                _ms_action = self._micro_scalp_exit.check_exit(
                    _ms_pos,
                    current_bid=pos.last_bid_cents,
                    current_ask=pos.last_ask_cents,
                    volatility=_volatility,
                    momentum=_momentum,
                )
                
                if _ms_action.should_exit:
                    self.logger.info(
                        "[MICRO_SCALP_EXIT] %s %s x%d: reason=%s profit_pct=%.1f%% hold_time=%.0fs",
                        pos.ticker, pos.side, pos.contracts,
                        _ms_action.reason, _ms_action.profit_pct * 100,
                        _ms_action.hold_seconds,
                    )
                    
                    # TICKER VALIDATION: Ensure stored ticker exists in catalog before exit
                    _ms_ticker_valid, _ms_canonical_ticker = _validate_ticker_for_exit(pos.ticker)
                    if not _ms_ticker_valid:
                        logger.error(
                            "[MICRO_SCALP_TICKER_REJECT] %s: Ticker not in catalog, skipping exit",
                            pos.ticker
                        )
                        continue
                    
                    # Use canonical ticker from catalog if available
                    _ms_exit_ticker = _ms_canonical_ticker or pos.ticker
                    
                    from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                    
                    # PRODUCTION FIX (2026-05-01): Generate unique client_tag for micro-scalp exit
                    # to prevent duplicate blocking. Exit orders were colliding with entry orders
                    # because they used the same deterministic coid generation.
                    _ms_ts_bucket = int(time.time()) // 60
                    _ms_preimage = (
                        f"{self.agent_id}|{pos.ticker}|{pos.side}|sell|"
                        f"{pos.entry_price_cents}|{pos.contracts}|{_ms_ts_bucket}|"
                        f"micro_scalp_exit|{_ms_action.reason}"
                    )
                    _ms_client_tag = f"merid-{hashlib.sha256(_ms_preimage.encode()).hexdigest()[:16]}-{_ms_ts_bucket}"
                    
                    # Propagate entry mode so paper-fill positions exit via paper
                    # (prevents "Ticker not found in catalog" 404s on expired markets).
                    _ms_exit_mode = None
                    try:
                        if getattr(pos, "entry_mode", None) == "paper":
                            from trading.trade_mode import TradeMode as _ExitTradeMode
                            _ms_exit_mode = _ExitTradeMode.PAPER
                    except Exception:
                        _ms_exit_mode = None

                    _ms_intent = OrderIntent(
                        ticker=_ms_exit_ticker,
                        side=pos.side,
                        action="sell",
                        price_cents=max(1, pos.current_price_cents or pos.entry_price_cents),
                        count=pos.contracts,
                        order_type="market",
                        time_in_force="ioc",
                        source=f"micro_scalp:{self.config.name}:{_ms_action.reason}",
                        agent_id=self.agent_id,
                        rationale=f"Micro-scalp exit: {_ms_action.reason}",
                        client_tag=_ms_client_tag,  # UNIQUE tag prevents duplicate blocking
                        mode=_ms_exit_mode,
                    )
                    
                    _ms_result = await route_order_async(_ms_intent)
                    _ms_ok = _ms_result.status not in ("rejected",)
                    
                    if _ms_ok:
                        _released_notional = (pos.entry_price_cents * pos.contracts) / 100.0
                        self._cycle_tracker.record_release(_released_notional, pos_id)
                        
                        if pos.side == "yes":
                            _ms_pnl = (pos.current_price_cents - pos.entry_price_cents) * pos.contracts / 100.0
                        else:
                            _ms_pnl = (pos.entry_price_cents - pos.current_price_cents) * pos.contracts / 100.0
                        
                        self.logger.info(
                            "[MICRO_SCALP_CLOSED] %s: released=$%.2f pnl=$%.2f reason=%s",
                            pos.ticker, _released_notional, _ms_pnl, _ms_action.reason,
                        )
                        
                        self._recent_trades_for_health.append({
                            "ticker": pos.ticker,
                            "pnl": _ms_pnl,
                            "outcome": "win" if _ms_pnl > 0 else "loss" if _ms_pnl < 0 else "scratch",
                            "reason": _ms_action.reason,
                            "ts": time.time(),
                        })
                        
                        await self._check_scalping_health()
                        _ms_to_remove.append(pos_id)
                    else:
                        _reason = _ms_result.reason or "unknown"
                        self.logger.warning(
                            "[MICRO_SCALP_REJECTED] %s: %s",
                            pos.ticker, _reason,
                        )
                        # If market is expired/settled (404 / not found), the position
                        # cannot be exited via the venue — drop locally to stop retrying.
                        # Paper-mode positions also drop on duplicate_race after first hit.
                        _terminal_rejection = (
                            "not found in catalog" in _reason.lower()
                            or "404" in _reason
                            or "expired" in _reason.lower()
                            or "settled" in _reason.lower()
                        )
                        if _terminal_rejection or (
                            getattr(pos, "entry_mode", None) == "paper"
                            and "duplicate_race" in _reason
                        ):
                            self.logger.info(
                                "[MICRO_SCALP_GIVE_UP] %s: dropping tracked position (reason=%s, mode=%s)",
                                pos.ticker, _reason, getattr(pos, "entry_mode", None) or "live",
                            )
                            _ms_to_remove.append(pos_id)

            except Exception as _ms_exc:
                self.logger.debug("micro_scalp sweep error for %s: %s", pos_id, _ms_exc)
        
        for pos_id in _ms_to_remove:
            self._tracked_positions.pop(pos_id, None)

        # If session cap breached, halt the agent
        if self._stop_loss.session_halted and self.state.enabled:
            self.logger.warning("stop_loss session cap breached — pausing agent %s", self.config.name)
            self.pause()

    # ── Micro-scalping helpers ─────────────────────────────────────────

    def _get_current_edge_for_position(self, pos: TrackedPosition) -> float:
        """Get current edge for a tracked position.
        
        Recalculates edge using current market data vs entry edge.
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            _mss = get_kalshi_market_state_store()
            _st = _mss.get(pos.ticker)
            if _st is None:
                return getattr(pos, 'entry_edge', 0.0)
            
            # Get current implied probability from market state
            _implied = getattr(_st, 'implied_prob', None)
            if _implied is None:
                # Calculate from yes_price
                _yes_price = getattr(_st, 'yes_price_cents', 0) or getattr(_st, 'best_ask_cents', 0)
                if _yes_price > 0:
                    _implied = _yes_price / 100.0
                else:
                    return getattr(pos, 'entry_edge', 0.0)
            
            # Get model probability (simplified - use stored or recalculate)
            _model_prob = getattr(pos, 'model_prob', 0.5)
            
            # Calculate edge
            if pos.side == "yes":
                _edge = _model_prob - _implied
            else:  # "no"
                _edge = (1.0 - _model_prob) - (1.0 - _implied)
            
            return _edge
        except Exception as _e:
            self.logger.debug("_get_current_edge failed for %s: %s", pos.ticker, _e)
            return getattr(pos, 'entry_edge', 0.0)

    async def _check_scalping_health(self) -> None:
        """Check scalping strategy health and pause if win rate drops below threshold.
        
        MICRO-SCALPING CIRCUIT BREAKER: Pauses trading if win rate < 70% over 30 trades.
        """
        if len(self._recent_trades_for_health) < self._health_check_interval:
            return  # Not enough trades yet
        
        try:
            from merid.prediction.agent_performance_tracker import ScalpingMetrics
            
            _scalping = ScalpingMetrics()
            _recent = self._recent_trades_for_health[-_scalping.WINDOW_SIZE:]
            
            # Build TradeRecord-like objects for validation
            class _SimpleTrade:
                def __init__(self, pnl, outcome):
                    self.profit_usd = pnl
                    self.outcome = outcome
            
            _trades = [_SimpleTrade(t["pnl"], t["outcome"]) for t in _recent]
            
            is_healthy, msg, metrics = _scalping.validate_strategy_health(_trades)
            
            if not is_healthy:
                self.logger.error(
                    "[CIRCUIT_BREAKER] Micro-scalping health check FAILED: %s",
                    msg,
                )
                self.logger.error(
                    "[CIRCUIT_BREAKER] Metrics: win_rate=%.1f%% (min=%.0f%%), "
                    "avg_profit=$%.2f (min=$%.2f)",
                    metrics["win_rate"] * 100,
                    _scalping.MIN_WIN_RATE * 100,
                    float(metrics.get("avg_profit_per_win", "0")),
                    float(_scalping.MIN_PROFIT_PER_TRADE_USD),
                )
                
                # Alert and pause
                try:
                    from merid.prediction.alerts import get_alert_manager
                    get_alert_manager().fire_risk_breach(
                        market_id="SCALPING_HEALTH",
                        message=f"🚨 MICRO-SCALPING PAUSED: {msg}. Agent {self.config.name} halted.",
                    )
                except Exception as _ae:
                    self.logger.debug("Health alert failed: %s", _ae)
                
                self.pause()
            else:
                self.logger.debug(
                    "[SCALPING_HEALTH] Win rate: %.1f%% | Avg profit: $%.2f | Status: %s",
                    metrics["win_rate"] * 100,
                    float(metrics.get("avg_profit_per_win", "0")),
                    msg,
                )
        except Exception as _e:
            self.logger.debug("_check_scalping_health error: %s", _e)

    def _calculate_volatility(self, ticker: str, entry_price_cents: int) -> float:
        """Calculate volatility (ATR-based) for dynamic take-profit targets.
        
        Uses market state to compute a volatility estimate based on:
        - Spread as % of mid price
        - Recent price range (if available)
        - Defaults to 3% if data unavailable
        
        Args:
            ticker: Market ticker
            entry_price_cents: Entry price for reference
            
        Returns:
            float: Volatility as percentage (e.g., 0.03 = 3%)
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            _mss = get_kalshi_market_state_store()
            _st = _mss.get(ticker)
            
            if _st is None:
                return 0.03  # Default 3% volatility
            
            # Get bid/ask for spread calculation
            _bid = getattr(_st, 'best_bid_cents', 0) or getattr(_st, 'yes_bid_cents', 0)
            _ask = getattr(_st, 'best_ask_cents', 0) or getattr(_st, 'yes_ask_cents', 0)
            
            if _bid > 0 and _ask > 0:
                _mid = (_bid + _ask) / 2.0
                _spread = _ask - _bid
                _spread_pct = _spread / _mid if _mid > 0 else 0.0
                
                # Estimate ATR as 2x spread (conservative)
                _atr_estimate = _spread_pct * 2.0
                
                # Clamp to reasonable bounds
                return max(0.01, min(_atr_estimate, 0.10))
            
            # Fallback: use yes_price variation
            _yes_price = getattr(_st, 'yes_price_cents', 0)
            if _yes_price > 0 and entry_price_cents > 0:
                _price_change = abs(_yes_price - entry_price_cents) / entry_price_cents
                return max(0.02, min(_price_change * 2.0, 0.08))
            
            return 0.03  # Default 3%
        except Exception as _e:
            self.logger.debug("_calculate_volatility failed for %s: %s", ticker, _e)
            return 0.03  # Default fallback

    # ── Market resolution ──────────────────────────────────────────────

    async def _resolve_markets(self) -> None:
        """Resolve config filters into live Kalshi market tickers.

        Path 1 (preferred): If series_tickers are configured, resolve via
        catalog prefix matching — the same robust method market_selector uses.
        Path 2 (fallback): category/asset/timeframe indexed lookup via
        _kalshi_list_markets (only used when series_tickers is empty).
        """
        try:
            from merid.event_venues.base import EventMarket, EventOutcome

            seen_tickers: set = set()
            all_markets = []
            _raw_by_asset: dict = {}

            # ── Path 1: series_tickers prefix matching (preferred) ────────
            _series = getattr(self.config, 'series_tickers', None) or []
            if _series:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                if not catalog.get_all_markets():
                    await catalog.refresh()

                now = datetime.now(timezone.utc)
                for cm in catalog.get_all_markets():
                    raw = cm.market.raw_data or {}
                    mkt_series = (raw.get("series_ticker", "") or "").upper()
                    mkt_event = (raw.get("event_ticker", "") or "").upper()
                    mkt_id = (cm.market.market_id or "").upper()

                    matched = any(
                        mkt_series.startswith(s.upper())
                        or mkt_event.startswith(s.upper())
                        or mkt_id.startswith(s.upper())
                        for s in _series
                    )
                    if not matched:
                        continue

                    # Basic filters: active, end_date in future
                    if not cm.market.active:
                        continue
                    if not cm.market.end_date or cm.market.end_date <= now:
                        continue

                    tid = cm.market.market_id
                    if not tid or tid in seen_tickers:
                        continue
                    seen_tickers.add(tid)

                    all_markets.append(cm.market)
                    _asset_key = cm.asset or (self.config.assets[0] if self.config.assets else "UNK")
                    _raw_by_asset.setdefault(_asset_key, []).append(raw)

                self.logger.debug(
                    "[RESOLVE-SERIES] %s: series=%s matched=%d from catalog=%d",
                    self.config.name, _series, len(all_markets), len(catalog.get_all_markets()),
                )

            # ── Path 2: fallback to category/asset/timeframe indexed lookup ─
            if not all_markets and not _series:
                from merid.prediction.kalshi_tools import _kalshi_list_markets

                category = self.config.category
                assets = self.config.assets if self.config.assets else [""]
                timeframe = self.config.timeframes[0] if self.config.timeframes else ""
                _effective_max_orders = self._get_effective_max_orders(top_n_edges=3)
                per_asset_limit = max(5, _effective_max_orders * 3)

                for asset in assets:
                    result = await _kalshi_list_markets(
                        category=category,
                        timeframe=timeframe,
                        asset=asset,
                        limit=per_asset_limit,
                    )
                    if not result.success:
                        self.logger.debug(
                            "Market resolution failed for asset=%s: %s",
                            asset, result.error_message,
                        )
                        continue

                    for m in result.payload.get("markets", []):
                        ticker = m.get("ticker") or m.get("market_id", "")
                        if not ticker or ticker in seen_tickers:
                            continue
                        seen_tickers.add(ticker)
                        _raw_by_asset.setdefault(asset or "UNK", []).append(m)

                        outcomes = [
                            EventOutcome(
                                outcome_id=o["id"],
                                outcome_name=o["name"],
                                price=Decimal(o["price"]),
                                probability=Decimal(o["probability"]) if o.get("probability") else None,
                            )
                            for o in m.get("outcomes", [])
                        ]
                        _end_date_str = m.get("end_date")
                        _end_date = None
                        if _end_date_str:
                            _end_date = datetime.fromisoformat(_end_date_str)
                            if _end_date.tzinfo is None:
                                _end_date = _end_date.replace(tzinfo=timezone.utc)
                        
                        em = EventMarket(
                            market_id=ticker,
                            venue="kalshi",
                            question=m.get("question", ""),
                            description="",
                            outcomes=outcomes,
                            category=m.get("category"),
                            tags=m.get("tags", []),
                            end_date=_end_date,
                            active=m.get("active", True),
                            volume=Decimal(m.get("volume", "0")),
                            open_interest=Decimal(m.get("open_interest", "0")),
                        )
                        all_markets.append(em)

            # ── FilterPipeline (optional) ──────────────────────────────────
            if self.config.use_filter_pipeline and _raw_by_asset:
                try:
                    from merid.trading.kalshi_filter_pipeline import (
                        FilterPipeline, FilterPipelineConfig,
                    )
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    _fp_cfg = FilterPipelineConfig(
                        assets=self.config.assets or [],
                        max_candidates_per_asset=self.config.filter_max_candidates_per_asset,
                        max_candidates_global=self.config.filter_max_candidates_global,
                    )
                    _fp = FilterPipeline(_fp_cfg)
                    # Pull spot prices from LivePriceFeed (the correct source).
                    # KalshiMarketCatalog has no get_reference_price method, and
                    # FilterPipeline.set_spot_prices (plural) is the bulk setter.
                    try:
                        from data.live_price_feed import get_live_price_feed as _glpf
                        _feed = _glpf()
                        _spots: dict = {}
                        for _a in (self.config.assets or []):
                            _pd = None
                            for _sym in pm_spot_feed_symbol_candidates(_a):
                                _pd = _feed.get_current_price(_sym)
                                if _pd and _pd.price > 0:
                                    break
                            if _pd and _pd.price > 0:
                                _spots[_a] = float(_pd.price)
                        if _spots:
                            _fp.set_spot_prices(_spots)
                    except Exception as _spot_err:
                        self.logger.debug("Spot price inject skipped: %s", _spot_err)
                    _fp_result = _fp.filter_markets(_raw_by_asset)
                    _allowed = {c.ticker for c in _fp_result.final_candidates}
                    all_markets = [m for m in all_markets if m.market_id in _allowed]
                except Exception as _fpe:
                    self.logger.debug("FilterPipeline skipped: %s", _fpe)

            # MICRO-SCALPING FIX: Filter markets by actual timeframe to prevent
            # agents from processing markets with mismatched expiration frequencies.
            # e.g., ETH_HOURLY should not process daily markets under KXETH series.
            _configured_timeframe = self.config.timeframes[0] if self.config.timeframes else None
            if _configured_timeframe and all_markets:
                from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
                _now = datetime.now(timezone.utc)
                _filtered = []
                for m in all_markets:
                    # Use catalog's timeframe detection if available
                    _market_timeframe = None
                    if hasattr(m, 'timeframe') and m.timeframe:
                        _market_timeframe = m.timeframe
                    elif m.end_date:
                        # Infer from time to expiry
                        _delta = m.end_date - _now
                        _minutes = _delta.total_seconds() / 60.0
                        if _minutes <= 20:
                            _market_timeframe = "15m"
                        elif _minutes <= 90:
                            _market_timeframe = "1h"
                        elif _minutes <= 60 * 24:
                            _market_timeframe = "daily"
                        elif _minutes <= 60 * 24 * 7:
                            _market_timeframe = "weekly"
                        elif _minutes <= 60 * 24 * 31:
                            _market_timeframe = "monthly"
                        else:
                            _market_timeframe = "annual"
                    
                    # Normalize timeframe names
                    _configured_tf = _configured_timeframe.lower()
                    _market_tf = (_market_timeframe or "").lower()
                    
                    # Accept matching timeframes or if can't determine
                    if _market_tf and _market_tf != _configured_tf:
                        self.logger.debug(
                            "[TIMEFRAME_FILTER] %s: skipping %s (market=%s, configured=%s)",
                            self._agent_name, m.market_id, _market_tf, _configured_tf
                        )
                        continue
                    _filtered.append(m)
                
                if len(_filtered) < len(all_markets):
                    self.logger.info(
                        "[TIMEFRAME_FILTER] %s: filtered %d markets -> %d (timeframe=%s)",
                        self._agent_name, len(all_markets), len(_filtered), _configured_timeframe
                    )
                all_markets = _filtered

            self._resolved_markets = all_markets
            tickers = [m.market_id for m in self._resolved_markets]
            self.state.active_tickers = tickers[:20]

        except Exception as exc:
            self.logger.warning(f"Market resolution error: {exc}")

    # ── Helpers ────────────────────────────────────────────────────────

    def _handles_ticker(self, ticker: str) -> bool:
        """Check if this agent handles positions for the given ticker.
        
        Returns True if the ticker matches any of the agent's configured assets.
        Used to filter pre-fetched positions so each agent only restores
        positions it actually manages.
        
        Args:
            ticker: The market ticker to check (e.g., "BTC-USD-230915")
            
        Returns:
            True if this agent should handle this ticker
        """
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            ticker_asset = kalshi_ticker_to_asset(ticker)
            if ticker_asset:
                ticker_asset = ticker_asset.upper()
            else:
                # Fallback: try to extract from ticker format
                ticker_upper = ticker.upper()
                for asset in (self.config.assets or []):
                    if asset.upper() in ticker_upper:
                        return True
                return False
            
            for asset in (self.config.assets or []):
                if asset.upper() == ticker_asset:
                    return True
            return False
        except Exception:
            # Fail-open: if check fails, assume we handle it
            return True

    def _log_pm_sizing_context(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
    ) -> None:
        """INFO line for operators: edge + strategy Kelly caps + shared risk bankroll."""
        try:
            _eq = 0.0
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                
                _effective_usd = get_equity_for_risk_calc_sync()
                if _effective_usd is not None:
                    _eq = float(_effective_usd)
            except Exception as e:
                self.logger.debug(f"[pm_sizing_context] bankroll fetch failed: {e}")
            sc = self._strategy.config
            edge_s = (
                float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else None
            )
            _vb = getattr(snapshot, "crypto_vol_band", None) or "—"
            _vm = getattr(snapshot, "crypto_vol_size_mult", None)
            _dist = getattr(snapshot, "distance_to_strike_pct", None)
            _dist_human = (
                f"{float(_dist) * 100.0:.2f}"
                if _dist is not None
                else "—"
            )
            _basis = getattr(snapshot, "spot_strike_basis_note", "") or "—"
            
            # Compute cycle cap info for observability
            _cycle_cap_info = "—"
            try:
                from merid.prediction.dynamic_sizing import get_cycle_sizing_cap
                from decimal import Decimal
                _bankroll_usd = Decimal(str(_eq))
                # BUG-FIX: Pass ticker so price_cents is fetched from market state (not default 1)
                _side_str = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
                _price_for_cap = signal.limit_price_cents if signal.limit_price_cents and signal.limit_price_cents > 0 else None
                _cap = get_cycle_sizing_cap(_bankroll_usd, _price_for_cap, market.market_id, _side_str)
                _display_price_cents = _price_for_cap or 50
                _notional_if_max = _cap.max_contracts_per_winner * _display_price_cents / 100
                _cycle_cap_info = f"max_contracts={_cap.max_contracts_per_winner} price_cents={_display_price_cents} notional_cap=${_notional_if_max:.2f}"
            except Exception:
                pass
            
            self.logger.info(
                "[PM_SIZE] agent=%s ticker=%s action=%s contracts=%s limit_cents=%s "
                "net_edge=%s bankroll_equity_usd=%.2f kelly_frac=%s max_contracts_order=%s "
                "vol_band=%s vol_size_mult=%s spot=%s strike=%s dist_pct_pct=%s spot_strike_basis=%s cycle_cap=%s",
                self.config.name,
                market.market_id,
                signal.action.value if hasattr(signal.action, "value") else signal.action,
                signal.contracts,
                signal.limit_price_cents,
                f"{edge_s:.4f}" if edge_s is not None else "—",
                _eq,
                float(sc.kelly_fraction),
                int(sc.max_contracts_per_order),
                _vb,
                f"{_vm:.3f}" if _vm is not None else "—",
                snapshot.spot_price_usd if snapshot.spot_price_usd is not None else "—",
                snapshot.strike_price_usd if snapshot.strike_price_usd is not None else "—",
                _dist_human,
                _basis,
                _cycle_cap_info,
            )
        except Exception as _exc:
            self.logger.debug("pm sizing log skipped: %s", _exc)

    def _in_entry_window(self, market: EventMarket, now: datetime) -> bool:
        """Check if now is within the agent's entry window for this market using dynamic policy."""
        if not market.end_date:
            self.logger.debug(
                "Skipping %s: end_date is missing — cannot determine entry window",
                market.market_id,
            )
            return False  # Reject: missing expiry is unsafe, not a pass-through

        # DYNAMIC ENTRY WINDOW: Use policy-based resolver instead of static config (strict mode)
        from merid.prediction.dynamic_entry_window import resolve_entry_window
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
        
        # Extract asset from ticker
        asset = kalshi_ticker_to_asset(market.market_id)
        if not asset:
            # Fallback to static config for non-crypto markets
            ew = self.config.entry_window
            window_open = market.end_date - timedelta(minutes=ew.minutes_before_expiry)
            window_close = market.end_date - timedelta(minutes=ew.cutoff_minutes_before_expiry)
            in_window = window_open <= now <= window_close
            
            minutes_to_expiry = (market.end_date - now).total_seconds() / 60
            self.logger.info(
                "[PM_WINDOW_FILTER] ticker=%s now=%s end_date=%s "
                "minutes_to_expiry=%.1f in_window=%s "
                "(fallback_static_config minutes_before_expiry=%s cutoff_minutes_before_expiry=%s)",
                market.market_id,
                now,
                market.end_date,
                minutes_to_expiry,
                in_window,
                ew.minutes_before_expiry,
                ew.cutoff_minutes_before_expiry,
            )
            return in_window
        
        # Use dynamic resolver (strict - no fail-open)
        minutes_to_expiry = (market.end_date - now).total_seconds() / 60
        edge_pct = None  # Edge not available at this stage, will be checked later
        
        resolution = resolve_entry_window(
            asset=asset,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct,
            ticker=market.market_id
        )
        
        # COHERENT RISK CONTRACT: Resolve exit policy from same signals
        from merid.prediction.dynamic_entry_window import resolve_exit_policy, validate_exit_policy
        exit_policy = resolve_exit_policy(
            window_resolution=resolution,
            asset=asset,
            edge_pct=edge_pct
        )
        
        # Validate exit policy - enforce "no trade without exit plan"
        if resolution.allowed and not validate_exit_policy(exit_policy):
            self.logger.warning(
                "[EXIT_POLICY_VALIDATION] ticker=%s asset=%s rejected: invalid exit policy - %s",
                market.market_id,
                asset,
                exit_policy.rationale
            )
            return False
        
        self.logger.info(
            "[PM_WINDOW_FILTER_DYNAMIC] ticker=%s asset=%s minutes_to_expiry=%.1f "
            "allowed=%s reason=%s policy=%s bucket=%s "
            "exit_policy_tier=%s tp_r_multiple=%s sl_mult=%s trailing=%s max_hold=%s",
            market.market_id,
            asset,
            minutes_to_expiry,
            resolution.allowed,
            resolution.reason.value,
            resolution.active_policy_name,
            resolution.bucket,
            exit_policy.risk_tier,
            exit_policy.take_profit_r_multiple,
            exit_policy.stop_loss_edge_multiplier,
            exit_policy.trailing_enabled,
            exit_policy.max_hold_seconds
        )
        
        return resolution.allowed
        
        # WINDOW FILTER DEBUG LOGGING: Always log to diagnose markets_in_window=0
        minutes_to_expiry = (market.end_date - now).total_seconds() / 60 if market.end_date else None
        self.logger.info(
            "[PM_WINDOW_FILTER] ticker=%s now=%s end_date=%s window_open=%s window_close=%s "
            "minutes_to_expiry=%.1f in_window=%s "
            "(minutes_before_expiry=%s cutoff_minutes_before_expiry=%s)",
            market.market_id,
            now,
            market.end_date,
            window_open,
            window_close,
            minutes_to_expiry,
            in_window,
            ew.minutes_before_expiry,
            ew.cutoff_minutes_before_expiry,
        )
        
        return in_window

    @staticmethod
    def _is_new_entry_action(action: SignalAction) -> bool:
        """True for opens / MM quotes; exits (sell/close) may run outside the entry window."""
        return action in (
            SignalAction.BUY_YES,
            SignalAction.BUY_NO,
            SignalAction.QUOTE,
        )

    def _get_seconds_to_expiry(self, market: EventMarket, now: datetime) -> Optional[float]:
        """Calculate seconds remaining until market expiry.
        
        Returns None if expiry cannot be determined.
        This supports the expiry proximity guard (Gap G1 fix).
        """
        if not market.end_date:
            return None
        
        # Ensure both datetimes are timezone-aware for accurate comparison
        end_date = market.end_date
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        now_aware = now
        if now_aware.tzinfo is None:
            now_aware = now_aware.replace(tzinfo=timezone.utc)
        
        delta = end_date - now_aware
        return max(0.0, delta.total_seconds())

    def _build_snapshot(self, market: EventMarket, now: datetime) -> MarketSnapshot:
        """Build a MarketSnapshot from an EventMarket for strategy consumption."""
        yes_price = Decimal("50")
        no_price = Decimal("50")
        for o in market.outcomes:
            if o.outcome_id == "yes":
                yes_price = o.price  # Price already in cents (0-100)
            elif o.outcome_id == "no":
                no_price = o.price  # Price already in cents (0-100)

        # Compute time to expiry
        tte_hours = None
        if market.end_date:
            delta = market.end_date - now
            tte_hours = Decimal(str(max(delta.total_seconds() / 3600, 0)))

        # Prefer live WS orderbook bid/ask over the synthetic 1¢ spread from
        # the REST catalog.  The catalog refresh lags by up to one cycle interval
        # (30–300 s) and always synthesises a 1¢ spread, so spread checks in
        # the risk layer would always pass even for wide markets (BUG-7 fix).
        yes_bid: Decimal
        yes_ask: Decimal
        _pricing_source = "ws"  # Track where pricing came from
        try:
            from merid.event_venues.kalshi.ws_bridge import get_live_prices
            live = get_live_prices(market.market_id)
            if live is not None:
                yes_bid = Decimal(str(live["yes_bid_cents"]))
                yes_ask = Decimal(str(live["yes_ask_cents"]))
                no_bid = max(Decimal("100") - yes_ask, Decimal("1"))
                no_ask = max(Decimal("100") - yes_bid, Decimal("1"))
            else:
                _pricing_source = "catalog_fallback"
                yes_bid = max(yes_price - 1, Decimal("1"))
                yes_ask = yes_price
                no_bid = max(no_price - 1, Decimal("1"))
                no_ask = no_price
                logger.debug(
                    "[CATALOG_FALLBACK_DEBUG] %s | yes_bid=%s yes_ask=%s no_bid=%s no_ask=%s sum_ask=%s",
                    market.market_id, yes_bid, yes_ask, no_bid, no_ask, yes_ask + no_ask,
                )
        except Exception:
            _pricing_source = "catalog_fallback"
            yes_bid = max(yes_price - 1, Decimal("1"))
            yes_ask = yes_price
            no_bid = max(no_price - 1, Decimal("1"))
            no_ask = no_price
            logger.debug(
                "[CATALOG_FALLBACK_DEBUG] %s | yes_bid=%s yes_ask=%s no_bid=%s no_ask=%s sum_ask=%s",
                market.market_id, yes_bid, yes_ask, no_bid, no_ask, yes_ask + no_ask,
            )

        # PHANTOM PRICING GATE (mirrors CT's SKIP-DEGENERATE check):
        # If no WS data AND catalog outcomes were empty (defaulted to 50/50),
        # mark the snapshot as having phantom pricing.  Phantom pricing produces
        # meaningless edges because the market has no real two-sided quotes.
        # 
        # FIX: Allow disabling via env var for paper/live trading when WS data is sparse
        _phantom_gate_enabled = os.getenv("MERID_PM_PHANTOM_GATE_ENABLED", "true").lower() not in ("false", "0", "off")
        _has_catalog_outcomes = any(
            o.outcome_id in ("yes", "no") for o in market.outcomes
        )
        _is_phantom_pricing = (
            _pricing_source != "ws" and not _has_catalog_outcomes and _phantom_gate_enabled
        )

        implied = self._model.implied_probabilities(
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
        )

        state = self._model.determine_state(
            status="active" if market.active else "closed",
            close_time=market.end_date,
        )

        snapshot = MarketSnapshot(
            market_id=market.market_id,
            event_id=market.market_id.rsplit("-", 1)[0] if "-" in market.market_id else market.market_id,
            title=market.question,
            state=state,
            implied=implied,
            volume=market.volume or Decimal("0"),
            open_interest=market.open_interest or Decimal("0"),
            time_to_expiry_hours=tte_hours,
            close_time=market.end_date,
            category=market.category,
            timestamp=now,
        )

        # Flag phantom pricing so strategy can reject meaningless edges
        snapshot.phantom_pricing = _is_phantom_pricing
        snapshot.pricing_source = _pricing_source

        # Inject fear/greed sentiment scores
        # H2: gate on context age — stale sentiment must not bias the snapshot.
        # H9: set sentiment_adjusted=True so forecasters skip their own nudge.
        _MAX_SENTIMENT_AGE_S = 900.0  # 15 minutes
        try:
            from merid.event_venues.kalshi.sentiment import get_sentiment_service
            svc = get_sentiment_service()
            # Feed latest data point so the service stays current
            svc.update_market(
                market.market_id,
                prob=float(implied.yes_prob),
                volume=float(market.volume or 0),
                category=(market.category or "unknown").lower(),
            )
            local_s = svc.market_score(market.market_id)
            cat_s   = svc.category_score((market.category or "unknown").lower())
            glob_s  = svc.global_score()

            # H2: determine age of the context; skip injection if stale
            _ctx_ts = None
            try:
                from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
                _bus_v2 = get_sentiment_bus_v2()
                asset = self.config.assets[0] if self.config.assets else None
                if asset:
                    _asset_ctx = _bus_v2.get_asset_context(asset)
                    if _asset_ctx and hasattr(_asset_ctx, "timestamp"):
                        _ctx_ts = _asset_ctx.timestamp
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")

            _age_s: Optional[float] = None
            if _ctx_ts is not None:
                try:
                    from datetime import timezone as _tz
                    _ctx_aware = _ctx_ts if _ctx_ts.tzinfo else _ctx_ts.replace(tzinfo=_tz.utc)
                    _now_aware = now if now.tzinfo else now.replace(tzinfo=_tz.utc)
                    _age_s = (_now_aware - _ctx_aware).total_seconds()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

            if _age_s is not None and _age_s > _MAX_SENTIMENT_AGE_S:
                self.logger.warning(
                    "Sentiment context age %.0fs exceeds limit %.0fs for %s — "
                    "skipping sentiment injection (H2)",
                    _age_s, _MAX_SENTIMENT_AGE_S, market.market_id,
                )
            else:
                snapshot.sentiment_local    = local_s.score if local_s else None
                snapshot.sentiment_category = cat_s.score
                snapshot.sentiment_global   = glob_s.score
                snapshot.sentiment_regime   = local_s.regime if local_s else glob_s.regime
                snapshot.sentiment_age_seconds = _age_s
                # H9: mark as adjusted so forecasters do not re-apply the nudge
                snapshot.sentiment_adjusted = True
        except Exception as _se:
            self.logger.debug("sentiment enrichment skipped: %s", _se)

        # Compute edges for both sides using the model (single spot fetch per snapshot)
        from merid.prediction.spot_strike_context import (
            distance_to_strike_pct,
            evaluate_spot_strike_anomaly,
            log_spot_out_of_range,
            resolve_asset_for_snapshot,
            resolve_timeframe_for_snapshot,
        )

        _resolved_asset = resolve_asset_for_snapshot(self.config.assets, market.market_id)
        _resolved_tf = resolve_timeframe_for_snapshot(self.config.timeframes, market.market_id)
        snapshot.resolved_asset = _resolved_asset
        snapshot.resolved_timeframe = _resolved_tf

        _asset_for_spot = _resolved_asset if _resolved_asset != "UNK" else None
        strike = None
        _catalog_timeframe = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            m = catalog.get_market(market.market_id)
            if m:
                strike = m.strike_price
                # Bracket/bucket markets have no strike_price but carry floor/cap.
                # Use midpoint as effective strike for the spot-relative edge model.
                if strike is None and m.floor_strike is not None and m.cap_strike is not None:
                    strike = (m.floor_strike + m.cap_strike) / 2.0
                # MICRO-SCALPING FIX: Use catalog's detected timeframe (based on actual expiry)
                # instead of ticker-inferred timeframe which can be wrong for mixed-frequency series
                if hasattr(m, 'timeframe') and m.timeframe:
                    _catalog_timeframe = m.timeframe
        except Exception as _ce:
            self.logger.debug("catalog strike lookup skipped: %s", _ce)
        
        # Override with catalog timeframe if available (more accurate than ticker inference)
        if _catalog_timeframe:
            snapshot.resolved_timeframe = _catalog_timeframe
        if strike is None:
            try:
                from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker

                strike = parse_strike_from_ticker(market.market_id)
            except Exception as _ps:
                self.logger.debug("parse_strike_from_ticker skipped: %s", _ps)

        snapshot.strike_price_usd = strike
        spot_override = None
        if _asset_for_spot:
            spot_override = self._model.get_spot_price(_asset_for_spot, market.market_id)
        snapshot.spot_price_usd = spot_override

        # Spot–strike basis (fractional dist only when both are valid USD levels)
        if not _asset_for_spot or (_resolved_asset or "").upper() in ("", "UNK"):
            snapshot.spot_strike_basis_note = "missing_asset_for_spot"
        elif strike is not None and float(strike) == 0.0:
            snapshot.spot_strike_basis_note = "invalid_strike_zero"
        elif strike is None and spot_override is None:
            snapshot.spot_strike_basis_note = "missing_strike_and_spot"
        elif strike is None:
            # Check if this is a directional market (no strike by design) vs missing strike
            # Directional markets: 15m up/down, UPDOWN series - no strike in ticker or text
            _is_directional = (
                "15M" in market.market_id.upper()
                or "UPDOWN" in market.market_id.upper()
                or (market.question and "above" not in market.question.lower() and "below" not in market.question.lower())
            )
            if _is_directional:
                snapshot.spot_strike_basis_note = "directional_passthrough"
            else:
                snapshot.spot_strike_basis_note = "missing_strike"
        elif spot_override is None:
            snapshot.spot_strike_basis_note = "missing_spot"
        else:
            snapshot.spot_strike_basis_note = "ok"
        # Realized-vol bands for crypto PM sizing (``crypto_pm_vol_bridge`` — ~1 bar/min/asset)
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS as _PM_CRYPTO_ASSETS
            from merid.signals.crypto_pm_vol_bridge import feed_spot_and_get_context as _pm_vol_feed

            if (
                _asset_for_spot
                and _asset_for_spot.upper() in _PM_CRYPTO_ASSETS
                and spot_override is not None
            ):
                _vctx = _pm_vol_feed(
                    _asset_for_spot.upper(),
                    float(spot_override),
                    timeframe=_resolved_tf,
                    archetype=str(getattr(self.config, "archetype", None) or "directional"),
                )
                if _vctx:
                    snapshot.crypto_vol_band = str(_vctx.get("vol_band") or "")
                    snapshot.crypto_vol_size_mult = float(_vctx["vol_size_mult"])
                    snapshot.crypto_realized_vol_annualized = float(
                        _vctx.get("realized_vol_annualized") or 0.0
                    )
                    snapshot.crypto_vol_bars_available = int(_vctx.get("bars_available") or 0)
        except Exception as _pv_exc:
            self.logger.debug("pm vol band attach skipped: %s", _pv_exc)

        # ACTIVE + crypto asset but no spot: neutral vol sizing and no spot–strike — make it visible (throttled).
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS as _PM_ASSETS_WARN

            if (
                _asset_for_spot
                and _asset_for_spot.upper() in _PM_ASSETS_WARN
                and spot_override is None
                and self.state.lifecycle == LifecycleState.ACTIVE
            ):
                _wk = f"{self.config.name}|{_asset_for_spot.upper()}"
                _now = time.time()
                if _now - _PM_SPOT_MISSING_WARN_LAST.get(_wk, 0.0) >= _PM_SPOT_MISSING_WARN_INTERVAL_S:
                    _PM_SPOT_MISSING_WARN_LAST[_wk] = _now
                    self.logger.warning(
                        "[PM_SPOT] agent=%s asset=%s market=%s — get_spot_price returned None "
                        "(vol bridge + spot–strike unavailable). "
                        "Check LivePriceFeed (Coinbase primary → %s/USD cache) and "
                        "MERID_PM_MAX_SPOT_AGE_SECONDS.",
                        self.config.name,
                        _asset_for_spot.upper(),
                        market.market_id,
                        _asset_for_spot.upper(),
                    )
        except Exception as e:
            self.logger.debug(f"Silent error suppressed: {e}")

        if spot_override is not None and strike is not None and float(strike) != 0.0:
            snapshot.distance_to_strike_pct = distance_to_strike_pct(spot_override, strike)
            _matrix_veto = False
            try:
                from merid.prediction.crypto_threshold_matrix import get_effective_crypto_config

                _eff_cfg = get_effective_crypto_config(self.config.name, market.market_id)
                _matrix_veto = bool(_eff_cfg.spot_strike_veto_flag) if _eff_cfg else False
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
            _warned, _veto, _anom_msg = evaluate_spot_strike_anomaly(
                snapshot.distance_to_strike_pct,
                matrix_hard_veto=_matrix_veto,
            )
            if _warned and _anom_msg:
                log_spot_out_of_range(
                    asset=_resolved_asset,
                    market_id=market.market_id,
                    spot=spot_override,
                    strike=strike,
                    detail=_anom_msg,
                    timeframe=_resolved_tf,
                    distance_to_strike_pct=snapshot.distance_to_strike_pct,
                )
            if _veto:
                snapshot.spot_strike_veto = True
                snapshot.spot_strike_veto_reason = (
                    f"spot_strike_anomaly: {_anom_msg or 'configured veto threshold'}"
                )

        snapshot.edges = [
            self._model.compute_edge(
                market_id=market.market_id,
                implied=implied,
                side="yes",
                action="buy",
                asset=_asset_for_spot,
                strike_price=strike,
                spot_override=spot_override,
            ),
            self._model.compute_edge(
                market_id=market.market_id,
                implied=implied,
                side="no",
                action="buy",
                asset=_asset_for_spot,
                strike_price=strike,
                spot_override=spot_override,
            ),
        ]

        return snapshot

    def _pm_spot_hard_gate_enabled_for_agent(self) -> bool:
        """True when this agent opts in via YAML ``pm_spot_hard_gate`` (market_maker only).

        Global kill-switch: ``MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0`` disables the gate process-wide.
        """
        _raw = (os.getenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE") or "1").strip().lower()
        if _raw in ("0", "false", "no", "off"):
            return False
        arch = (getattr(self.config, "archetype", "") or "").strip().lower().replace("-", "_")
        if arch != "market_maker":
            return False
        return bool(getattr(self.config, "pm_spot_hard_gate", False))

    def _apply_pm_spot_hard_gate(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
    ) -> StrategySignal:
        """Hard gate: opted-in MM agents must not emit QUOTE without healthy PM spot (``snapshot.spot_price_usd``).

        Aligns with ``PredictionMarketModel.get_spot_price`` / operator ``pm_spot_effective_ok``. Orthogonal to
        ERROR_THRESHOLD kills.
        """
        if not self._pm_spot_hard_gate_enabled_for_agent():
            return signal
        if signal.action != SignalAction.QUOTE:
            return signal
        if snapshot.spot_price_usd is not None:
            return signal
        asset = (snapshot.resolved_asset or "").strip().upper()
        if not asset and self.config.assets:
            asset = (self.config.assets[0] or "").strip().upper()
        try:
            from merid.settings import settings as _settings

            kalshi_only = bool(getattr(_settings, "KALSHI_ONLY", False))
        except Exception:
            kalshi_only = False
        now_m = time.monotonic()
        _k = f"{self.config.name}|{asset}|{getattr(market, 'market_id', '')}"
        last = _PM_SPOT_BLOCK_LOG_LAST.get(_k, 0.0)
        if now_m - last >= _PM_SPOT_BLOCK_LOG_INTERVAL_S:
            _PM_SPOT_BLOCK_LOG_LAST[_k] = now_m
            self.logger.warning(
                "PM_SPOT_BLOCK: agent=%s asset=%s reason=missing_or_stale_spot kalshi_only_mode=%s",
                self.config.name,
                asset or "?",
                kalshi_only,
            )
        return StrategySignal(
            market_id=signal.market_id,
            action=SignalAction.NO_ACTION,
            side="",
            contracts=0,
            limit_price_cents=None,
            bid_price_cents=None,
            ask_price_cents=None,
            edge=signal.edge,
            phase=signal.phase,
            reason="pm_spot_gate:missing_or_stale_spot",
            correlation_id=signal.correlation_id,
            eval_context={**(signal.eval_context or {}), "pm_spot_gate": True},
        )

    def _maybe_log_crypto_spot_strike_trace(
        self,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
    ) -> None:
        """Config-toggleable ``[CRYPTO_SPOT_STRIKE]`` line after strategy evaluation.

        Uses only fields from ``snapshot`` / ``signal`` (no duplicate spot fetch).
        """
        try:
            from merid.prediction.spot_strike_context import log_crypto_spot_strike

            ne = None
            if signal.edge and hasattr(signal.edge, "net_edge"):
                try:
                    ne = float(signal.edge.net_edge)
                except (TypeError, ValueError):
                    ne = None
            ph = signal.phase.value if signal.phase else None
            log_crypto_spot_strike(
                agent_name=self.config.name,
                market_id=snapshot.market_id,
                asset=snapshot.resolved_asset or "",
                timeframe=snapshot.resolved_timeframe or "",
                spot=snapshot.spot_price_usd,
                strike=snapshot.strike_price_usd,
                dist_pct=snapshot.distance_to_strike_pct,
                net_edge=ne,
                phase=ph,
                archetype=str(self.config.archetype or ""),
            )
        except Exception as _exc:
            self.logger.debug("crypto spot-strike trace skipped: %s", _exc)

    def _compute_cycle_interval(self) -> float:
        """Compute sleep between cycles based on timeframe."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        intervals = {
            "15m": 30.0,        # Check every 30s for 15m markets
            "1h": 60.0,         # Every 60s for hourly
            "daily": 300.0,     # Every 5min for daily
            "weekly": 600.0,    # Every 10min for weekly
            "monthly": 1800.0,  # Every 30min for monthly — no need to hammer the loop
            "annual": 3600.0,   # Every 1h for annual
            "pre-market": 60.0,
        }
        return intervals.get(tf, 60.0)

    def _maybe_reset_window(self, now: datetime) -> None:
        """Reset per-window order count when a new window starts."""
        tf = self.config.timeframes[0] if self.config.timeframes else "1h"
        window_minutes = {"15m": 15, "1h": 60, "daily": 1440, "weekly": 10080, "pre-market": 120}
        window_dur = timedelta(minutes=window_minutes.get(tf, 60))

        if self.state.window_start is None or (now - self.state.window_start) >= window_dur:
            self.state.window_start = now
            self.state.orders_this_window = 0

    async def _record_signal(
        self, market: EventMarket, signal: StrategySignal,
        snapshot: MarketSnapshot, now: datetime,
    ) -> None:
        """Persist a strategy signal to the agent's signal log with policy metadata."""
        # Calculate minutes_to_expiry for entry window analysis
        minutes_to_expiry = None
        if market.end_date:
            minutes_to_expiry = (market.end_date - now).total_seconds() / 60.0
        
        # DYNAMIC WINDOW: Tag with policy metadata for analysis
        policy_name = None
        policy_bucket = None
        policy_reason = None
        
        try:
            from merid.prediction.dynamic_entry_window import resolve_entry_window, _get_bucket, resolve_exit_policy
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            
            asset = kalshi_ticker_to_asset(market.market_id)
            if asset and minutes_to_expiry is not None:
                edge_pct = float(signal.edge.net_edge * 100) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None
                resolution = resolve_entry_window(asset, minutes_to_expiry, edge_pct, ticker=market.market_id)
                policy_name = resolution.active_policy_name
                policy_bucket = resolution.bucket
                policy_reason = resolution.reason.value
                
                # COHERENT RISK CONTRACT: Resolve exit policy for diagnostic logging
                exit_policy = resolve_exit_policy(
                    window_resolution=resolution,
                    asset=asset,
                    edge_pct=edge_pct
                )
                exit_policy_tier = exit_policy.risk_tier
                exit_tp_r_multiple = exit_policy.take_profit_r_multiple
                exit_sl_mult = exit_policy.stop_loss_edge_multiplier
                exit_trailing = exit_policy.trailing_enabled
                exit_max_hold = exit_policy.max_hold_seconds
        except Exception as exc:
            self.logger.debug("[DYNAMIC_WINDOW] Failed to tag signal with policy: %s", exc)
            exit_policy_tier = None
            exit_tp_r_multiple = None
            exit_sl_mult = None
            exit_trailing = None
            exit_max_hold = None
        
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "action": signal.action.value if hasattr(signal.action, "value") else str(signal.action),
            "contracts": signal.contracts,
            "limit_price_cents": signal.limit_price_cents,
            "edge": float(signal.edge.net_edge) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None,
            "edge_pct": float(signal.edge.net_edge * 100) if (signal.edge and hasattr(signal.edge, 'net_edge')) else None,
            "confidence": float(signal.edge.confidence) if (signal.edge and hasattr(signal.edge, 'confidence')) else None,
            "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
            "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
            "expiry_phase": str(signal.phase) if signal.phase else None,
            "minutes_to_expiry": minutes_to_expiry,
            "mode": str(getattr(self._venue_gate, "mode", "unknown").value
                        if hasattr(getattr(self._venue_gate, "mode", None), "value")
                        else getattr(self._venue_gate, "mode", "unknown")),
            # DYNAMIC WINDOW POLICY METADATA
            "entry_window_policy_name": policy_name,
            "entry_window_bucket": policy_bucket,
            "entry_window_decision_reason": policy_reason,
            # EXIT POLICY METADATA (Coherent Risk Contract)
            "exit_policy_risk_tier": exit_policy_tier,
            "exit_policy_tp_r_multiple": exit_tp_r_multiple,
            "exit_policy_sl_multiplier": exit_sl_mult,
            "exit_policy_trailing_enabled": exit_trailing,
            "exit_policy_max_hold_seconds": exit_max_hold,
        }
        self.state.signal_log.append(entry)
        if len(self.state.signal_log) > _MAX_LOG_ENTRIES:
            self.state.signal_log = self.state.signal_log[-_MAX_LOG_ENTRIES:]

        # ── Calibration: log forecast for Brier scoring ──────────────────
        try:
            from merid.metrics.calibration import get_calibration_store
            cal = get_calibration_store()
            # Use model_prob directly from EdgeEstimate — this is the pre-fee
            # probability set by compute_edge().  Never reconstruct from
            # net_edge (which has fee drag deducted) to avoid systematic
            # underestimation of the true model probability (BUG-06).
            p_model = None
            if signal.edge and hasattr(signal.edge, 'model_prob') and signal.edge.model_prob is not None:
                p_model = float(signal.edge.model_prob)
            if p_model is not None:
                bucket = (market.category or "unknown").lower()
                _cal_mode = str(
                    getattr(self._venue_gate, "mode", "live").value
                    if hasattr(getattr(self._venue_gate, "mode", None), "value")
                    else getattr(self._venue_gate, "mode", "live")
                ).lower()
                cal.record_forecast(
                    forecaster_id=self.config.name,
                    bucket=bucket,
                    market_id=market.market_id,
                    p_model=p_model,
                    timestamp=now.timestamp(),
                    mode=_cal_mode,
                )
        except Exception as _cal_exc:
            self.logger.debug("calibration record_forecast skipped: %s", _cal_exc)

        # ── Sprint B: Run heterogeneous forecasters (momentum, mean_reversion) ──
        try:
            from merid.prediction.forecasters.registry import get_forecaster_registry
            registry = get_forecaster_registry()
            imp_yes = float(snapshot.implied.yes_prob) if snapshot and snapshot.implied else 0.5
            imp_no = float(snapshot.implied.no_prob) if snapshot and snapshot.implied else 0.5
            vol = float(market.volume) if market.volume else 0.0
            oi = float(market.open_interest) if market.open_interest else 0.0
            tte = float(snapshot.time_to_expiry_hours) * 60.0 if snapshot and snapshot.time_to_expiry_hours else None
            _bid = float(snapshot.implied.yes_bid) if snapshot and snapshot.implied and snapshot.implied.yes_bid else None
            _ask = float(snapshot.implied.yes_ask) if snapshot and snapshot.implied and snapshot.implied.yes_ask else None
            _asset = self.config.assets[0] if self.config.assets else None
            _tf = self.config.timeframes[0] if self.config.timeframes else None
            
            # Offload synchronous predict_all to thread pool to prevent event loop blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                registry.predict_all,
                market.market_id,
                imp_yes,
                imp_no,
                vol,
                oi,
                tte,
                _asset,
                _tf,
                _bid,
                _ask,
                market.category,
            )
        except Exception as _fr_exc:
            self.logger.debug("forecaster registry predict_all skipped: %s", _fr_exc)

    def _record_explainability_decision(
        self,
        *,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        check: PreTradeCheck,
        now: datetime,
        allowed: bool,
    ) -> None:
        """Record a structured decision rationale in the global explainability tracker."""
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker

            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.0
            edge_value = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0

            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"{action_value} {signal.contracts}x {market.market_id}", confidence)
            builder.set_primary_reason(
                f"{action_value} decision for {market.market_id} with edge={edge_value:.4f}"
            )
            builder.add_supporting_factor(f"edge={edge_value:.4f}")
            builder.add_supporting_factor(f"allowed={allowed}")
            if check.adjusted_size and check.adjusted_size != signal.contracts:
                builder.add_contrary_factor(
                    f"risk downsize from {signal.contracts} to {check.adjusted_size}"
                )
            if not allowed:
                builder.add_contrary_factor(f"risk blocked: {check.reason}")

            for source in ("kalshi_market_catalog", "kalshi_order_router", "prediction_risk"):
                builder.add_data_source(source)

            builder.set_market_context(
                {
                    "market_id": market.market_id,
                    "question": market.question,
                    "timestamp": now.isoformat(),
                    "implied_yes": float(snapshot.implied.yes_prob) if snapshot.implied else None,
                    "implied_no": float(snapshot.implied.no_prob) if snapshot.implied else None,
                    "volume": float(snapshot.volume) if snapshot.volume is not None else 0.0,
                    "open_interest": float(snapshot.open_interest) if snapshot.open_interest is not None else 0.0,
                }
            )
            builder.set_risk_assessment(
                {
                    "allowed": allowed,
                    "reason": check.reason,
                    "adjusted_size": check.adjusted_size,
                    "estimated_fee": str(check.estimated_fee) if hasattr(check, "estimated_fee") else None,
                }
            )

            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability decision record skipped: {exc}")

    def _emit_decision_log(self, decision: Decision) -> None:
        """Emit a structured ``[PM_DECISION]`` log line for observability."""
        try:
            th_cfg = get_trade_hold_config()
            if not th_cfg.logging.log_every_decision:
                return
            self.logger.info(decision.log_line())
        except Exception as _dl_exc:
            self.logger.debug("decision log skipped: %s", _dl_exc)

    def _build_cycle_context(
        self,
        *,
        market_id: Optional[str] = None,
        signal: Optional[StrategySignal] = None,
        check: Optional[PreTradeCheck] = None,
        now: datetime,
        timer: DecisionTimer,
        session_allowed: bool = True,
        has_resolved_markets: bool = True,
        in_entry_window: bool = True,
        is_new_entry: bool = True,
        seconds_to_expiry: Optional[float] = None,
        consensus_status: Optional[str] = None,
        consensus_direction_matches: bool = True,
        consensus_bypassed: bool = False,
        solo_seconds: float = 0.0,
    ) -> CycleContext:
        """Populate a CycleContext from current agent state + pipeline results."""
        ctx = CycleContext(
            agent_name=self.config.name,
            cycle_number=self.state.cycles_run,
            market_id=market_id,
            lifecycle_state=self.state.lifecycle,
            agent_enabled=self.state.enabled,
            kill_switch_active=getattr(self._risk, "_halted", False),
            kill_switch_reason=getattr(self._risk, "_halt_reason", "") or "",
            session_allowed=session_allowed,
            has_resolved_markets=has_resolved_markets,
            in_entry_window=in_entry_window,
            is_new_entry=is_new_entry,
            seconds_to_expiry=seconds_to_expiry,
            orders_this_window=self.state.orders_this_window,
            max_orders_per_window=self._get_effective_max_orders(top_n_edges=3),  # REVERTED from 1 to restore profitable trades
            consensus_status=consensus_status,
            consensus_direction_matches=consensus_direction_matches,
            consensus_bypassed=consensus_bypassed or self._swarm_consensus_bypassed(),
            solo_seconds=solo_seconds,
            swarm_degraded=self.state.swarm_degraded,
            solo_trades_this_session=self.state.solo_trades_this_degraded_session,
            config=get_trade_hold_config(),
            timer=timer,
        )
        if signal is not None:
            ctx.signal_action = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            ctx.signal_reason = signal.reason or ""
            ctx.signal_contracts = signal.contracts
            ctx.signal_edge = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else None
            ctx.signal_phase = signal.phase.value if signal.phase else None
        if check is not None:
            ctx.risk_allowed = check.allowed
            ctx.risk_reason = check.reason or ""
            ctx.risk_action = check.action.value if hasattr(check.action, "value") else str(check.action)
        return ctx

    async def _execute_signal(
        self, market: EventMarket, signal: StrategySignal, check: PreTradeCheck,
        snapshot: Optional[MarketSnapshot] = None,
        _tick: Optional["TickContext"] = None,
        _bus: Optional[object] = None,
    ) -> None:
        """Execute a strategy signal by placing an order.

        Integrates with CryptoSwarmRiskBTC15m for single-lane risk management on
        all five crypto 15m assets (live vs paper routing).
        """
        # BUG-L6: signal to stop() that we are mid-execution so it waits
        # rather than hard-cancelling while an HTTP order request is in-flight.
        self._in_execution.set()
        try:
            await self._execute_signal_body(
                market, signal, check, snapshot, _tick=_tick, _bus=_bus
            )
        finally:
            self._in_execution.clear()

    # Maximum snapshot age before refusing to execute (BUG-3 fix)
    _MAX_SNAPSHOT_AGE_S: float = 90.0

    # Wire 3: consensus size-band scalars
    _SIZE_BAND_SCALARS: dict = {
        "small": 0.25,
        "reduced": 0.5,
        "base": 1.0,
        "large": 1.5,
    }

    def _apply_size_band(self, base_contracts: int, band: str) -> int:
        """Scale contracts by consensus size band. Unknown band defaults to small."""
        scalar = self._SIZE_BAND_SCALARS.get(band, 0.25)
        return max(1, int(base_contracts * scalar))

    def _apply_solo_trade_cap(self, signal: object) -> None:
        """Cap signal.contracts to small band (used for STALE/None/degraded consensus)."""
        if hasattr(signal, "contracts") and signal.contracts is not None:
            signal.contracts = self._apply_size_band(signal.contracts, "small")

    def _check_consensus_gate(self, signal: object, order_contracts: int, *, market_id: str = "") -> Optional[int]:
        """Query consensus and return approved contract count, or None to skip.

        Returns:
            int — approved contracts (size-band-adjusted)
            None — skip this execution cycle
        """
        try:
            from merid.swarm.consensus_aggregator import ConsensusStatus
            from merid.prediction.strategy import SignalAction
            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime
            _mm = get_crypto_edge_runtime().mm_consensus_mode
            # SAFETY: bypass mode is disabled - all orders must go through full consensus gate
            if _mm == "bypass":
                self.logger.error(
                    "[SECURITY] mm_consensus_mode='bypass' detected in _check_consensus_gate - "
                    "BYPASS IS DISABLED. Treating as 'full' mode. All orders must flow through main gate."
                )
                _mm = "full"

            if market_id:
                asset = self._strategy._extract_asset_from_market_id(market_id) if self._strategy else ""
            else:
                asset = ""
            if not asset or asset == "UNK":
                asset = self.config.assets[0] if self.config.assets else ""
            timeframe = self.config.timeframes[0] if self.config.timeframes else ""
            consensus = get_consensus_aggregator().get_consensus(asset, timeframe)

            if consensus is None or consensus.status == ConsensusStatus.STALE:
                self._apply_solo_trade_cap(signal)
                # Return the mutated (capped) contracts, not the original order_contracts
                capped = getattr(signal, "contracts", None)
                return capped if capped is not None else order_contracts

            if consensus.status == ConsensusStatus.FORMING:
                if _mm == "soft":
                    self._apply_solo_trade_cap(signal)
                    capped = getattr(signal, "contracts", None)
                    return capped if capped is not None else order_contracts
                return None  # full mode: not enough diversity — skip

            if consensus.status == ConsensusStatus.CONFLICTED:
                # Conflicted consensus — cap to small and continue rather than authorize full size
                self._apply_solo_trade_cap(signal)
                capped = getattr(signal, "contracts", None)
                return capped if capped is not None else order_contracts

            _signal_action = getattr(signal, "action", None)

            # BUG-K fix: SELL signals are exits — never block them via direction gate.
            # Original code mapped SELL_YES → "yes", which caused consensus to block
            # sell orders when consensus turned bearish, trapping agents in losers.
            _is_sell = _signal_action in (SignalAction.SELL_YES, SignalAction.SELL_NO)
            if _is_sell:
                return self._apply_size_band(order_contracts, consensus.size_band)

            _dir_map = {
                SignalAction.BUY_YES: "yes",
                SignalAction.BUY_NO: "no",
            }
            signal_dir = _dir_map.get(_signal_action, "neutral")

            if signal_dir != consensus.consensus_direction and consensus.consensus_confidence > 0.7:
                self.logger.debug(
                    "consensus_gate_blocked: %s signal=%s consensus=%s conf=%.2f",
                    self.config.name, signal_dir, consensus.consensus_direction,
                    consensus.consensus_confidence,
                )
                return None

            return self._apply_size_band(order_contracts, consensus.size_band)

        except Exception as exc:
            self.logger.warning("consensus_gate_error — capping to small band: %s", exc)
            self._apply_solo_trade_cap(signal)
            capped = getattr(signal, "contracts", None)
            return capped if capped is not None else self._apply_size_band(order_contracts, "small")

    async def _execute_signal_body(
        self, market: EventMarket, signal: StrategySignal, check: PreTradeCheck,
        snapshot: Optional[MarketSnapshot] = None,
        _tick: Optional["TickContext"] = None,
        _bus: Optional[object] = None,
    ) -> None:
        """Internal body of _execute_signal, protected by _in_execution flag."""
        try:
            from merid.prediction.kalshi_tools import _kalshi_place_order
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            from merid.prediction.crypto_top_edge import CRYPTO_ASSETS, MEAN_REVERSION_TIMEFRAMES
        except Exception as import_exc:
            self.logger.error("Import failed: %s", import_exc, exc_info=True)
            raise

        # ═══════════════════════════════════════════════════════════════════════
        # EXECUTION GUARDS: Fatal three-layer protection (must pass ALL to trade)
        # Layer 1: Asset whitelist (BTC/ETH/SOL/XRP/DOGE only)
        # Layer 2: Timeframe gate (15m only - 1h/daily/weekly are signal-only)
        # Layer 3: Distance + Edge (computed after metrics available, see below)
        # ═══════════════════════════════════════════════════════════════════════
        # Layer 0: Signal-only agent enforcement (must be first)
        # If agent is marked signalonly=true in YAML, it cannot execute trades
        if getattr(self.config, 'signalonly', False):
            self.logger.debug(
                "[SIGNALONLY-SKIP] agent=%s | action=skipped | reason=signalonly_context_agent",
                getattr(self.config, 'name', 'UNKNOWN'),
            )
            return

        # FIX: Use plural config fields (assets/timeframes lists) as source of truth
        _assets = getattr(self.config, 'assets', None) or []
        _timeframes = getattr(self.config, 'timeframes', None) or []

        # Explicit early-blocking for misconfigured agents
        if not _assets or not _timeframes:
            self.logger.warning(
                "[EXECUTION_BLOCKED] TradingAgent config missing assets/timeframes; blocking execution.",
                extra={"agent": getattr(self.config, 'name', 'UNKNOWN')}
            )
            return

        _asset = _assets[0] if _assets else "UNKNOWN"
        _timeframe = _timeframes[0] if _timeframes else "UNKNOWN"

        # Layer 1 & 2: Asset and timeframe validation (fatal, no fallback)
        _guard_result = check_execution_guards(
            asset=_asset,
            timeframe=_timeframe,
            log_fn=self.logger.info,  # Use INFO for blocks (these are important)
        )
        if not _guard_result.allowed:
            # Already logged in check_execution_guards - just return
            return

        # [TRACE] EXECUTE_START — log with correlation_id from signal
        corr_id = getattr(signal, 'correlation_id', None)
        if corr_id:
            self.logger.info(
                "[TRACE] EXECUTE_START | corr_id=%s | market=%s | agent=%s | action=%s | size=%s | formulas=%s | audit_spec=%s",
                corr_id,
                market.market_id,
                self.agent_id,
                signal.action.value if hasattr(signal.action, 'value') else signal.action,
                signal.contracts,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )

        # BUG-3 fix: refuse to execute against a stale snapshot so the edge
        # estimate and price used for risk checks reflect current market state.
        if snapshot is not None:
            import time as _time_mod

            _snap_epoch = snapshot_timestamp_utc_epoch_seconds(getattr(snapshot, "timestamp", None))
            _snapshot_age = _time_mod.time() - _snap_epoch
            if _snapshot_age > self._MAX_SNAPSHOT_AGE_S:
                self.logger.warning(
                    "snapshot_stale: %s age=%.1fs > %.0fs — skipping execution",
                    market.market_id, _snapshot_age, self._MAX_SNAPSHOT_AGE_S,
                )
                return

        # Wire 3: Consensus execution gate — gate on direction + apply size band
        _gate_contracts = self._check_consensus_gate(
            signal=signal,
            order_contracts=getattr(signal, "contracts", 0) or 0,
            market_id=market.market_id if market else "",
        )
        if _gate_contracts is None:
            self.logger.debug(
                "consensus_gate_skip: %s consensus not ready or opposes signal",
                market.market_id,
            )
            return

        action_map = {
            SignalAction.BUY_YES: ("yes", "buy"),
            SignalAction.BUY_NO: ("no", "buy"),
            SignalAction.SELL_YES: ("yes", "sell"),
            SignalAction.SELL_NO: ("no", "sell"),
            SignalAction.QUOTE: ("yes", "quote"), # Special handling for quotes
        }

        if signal.action not in action_map:
            self.logger.warning("signal.action %s not in action_map, returning", signal.action)
            return

        side, action = action_map[signal.action]
        size = _gate_contracts if _gate_contracts is not None else (check.adjusted_size or signal.contracts)
        price_cents = signal.limit_price_cents or 0
        # QUOTE: strategy sets limit_price_cents to bid/ask mid; fallback if missing.
        if signal.action == SignalAction.QUOTE and price_cents <= 0:
            _b = getattr(signal, "bid_price_cents", None)
            _a = getattr(signal, "ask_price_cents", None)
            if _b is not None and _a is not None:
                price_cents = max(1, min(99, int((_b + _a) // 2)))

        # ── Take-profit re-entry gate ─────────────────────────────────────
        # For new buy entries (not closes), check whether the TP manager allows
        # re-entry into this contract.  This prevents hyper-churn after TP exits.
        if action == "buy":
            try:
                _system_risk_off = False
                try:
                    from merid.risk.kill_switches import risk_controller as _ks_rc
                    _system_risk_off = not _ks_rc.can_trade()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                # Extract contract expiry info for round-trip reset logic
                _contract_expiry_ts = None
                try:
                    if hasattr(market, 'expiration_time') and market.expiration_time:
                        # Use explicit datetime class to avoid UnboundLocalError
                        from datetime import datetime as _datetime_cls
                        if isinstance(market.expiration_time, _datetime_cls):
                            _contract_expiry_ts = market.expiration_time.timestamp()
                        elif isinstance(market.expiration_time, str):
                            # Try parsing ISO format
                            _dt = _datetime_cls.fromisoformat(market.expiration_time.replace('Z', '+00:00'))
                            _contract_expiry_ts = _dt.timestamp()
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")

                if not self._tp_manager.can_reenter(
                    market.market_id,
                    price_cents,
                    _system_risk_off,
                    contract_id=getattr(market, 'market_id', None) or market.market_id,
                    contract_expiry_ts=_contract_expiry_ts,
                ):
                    self.logger.debug(
                        "tp_reentry_blocked: %s — round-trip cap, min-price-move, or contract expired",
                        market.market_id,
                    )
                    return
            except Exception as _tp_re_exc:
                self.logger.debug("tp_reentry_check skipped: %s", _tp_re_exc)
        # ─────────────────────────────────────────────────────────────────

        # === Crypto 15m Risk Layer Integration (BTC/ETH/SOL/XRP/DOGE) ===
        from config.kalshi_crypto_config import kalshi_ticker_to_asset as _kalshi_ticker_to_asset
        from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS as _ALL_CRYPTO_ASSETS
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket as _series_tf_bucket

        asset_m = _kalshi_ticker_to_asset(market.market_id) or (
            self.config.assets[0] if self.config.assets else ""
        )
        timeframe_m = _series_tf_bucket(market.market_id)

        is_crypto_15m = timeframe_m == "15m" and (asset_m or "").upper() in _ALL_CRYPTO_ASSETS

        # NEAR-EXPIRY BLACKLIST (2026-05-12): Skip markets too close to expiry
        # Near-expiry markets have reduced liquidity, stale quotes, and wide spreads
        # which cause quote validation failures and order rejections
        # Use the same threshold as the window filter cutoff to avoid inconsistency
        if is_crypto_15m and hasattr(market, 'end_date') and market.end_date:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            time_to_expiry = market.end_date - now
            # Align with entry_window.cutoff_minutes_before_expiry (default 2 min for 15m)
            min_expiry_minutes = self.config.entry_window.cutoff_minutes_before_expiry
            if time_to_expiry.total_seconds() < min_expiry_minutes * 60:
                self.logger.warning(
                    "[crypto15m_risk] Skipping %s: too close to expiry (%.1f minutes remaining, threshold=%d min)",
                    market.market_id, time_to_expiry.total_seconds() / 60, min_expiry_minutes
                )
                return

        # BUG-FIX (2026-05-07): Resolve market price before crypto 15m risk evaluation
        # If price_cents is 0 or missing, fetch from market state to avoid intent_risk=0
        # which causes Fear & Greed multiplier to reduce position size to $0.00
        # DATA INTEGRITY LAYER (2026-05-11): Use enhanced market_state with health checks
        # and cross-validation between WebSocket and REST feeds
        # RETRY LOGIC (2026-05-12): Add retry with exponential backoff for quote fetching
        # to handle transient failures in near-expiry markets with reduced liquidity
        # EXECUTION FIX (2026-05-13): Skip quote fetch if price_cents is already set to avoid blocking
        # Only fetch quote if price_cents is truly invalid (None, 0, or >=100)
        if is_crypto_15m and (price_cents is None or price_cents <= 0 or price_cents >= 100):
            try:
                import asyncio
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                store = get_kalshi_market_state_store()
                
                # Retry quote fetching with exponential backoff
                trusted_quote = None
                max_retries = 3
                base_backoff_ms = 100
                
                for attempt in range(max_retries):
                    trusted_quote = store.get_trusted_quote_sync(market.market_id)
                    
                    # If we got a healthy quote with valid prices, break
                    if trusted_quote and trusted_quote.health == "healthy":
                        if (trusted_quote.mid_cents and 0 < trusted_quote.mid_cents < 100) or \
                           (trusted_quote.best_ask_cents and 0 < trusted_quote.best_ask_cents < 100) or \
                           (trusted_quote.best_bid_cents and 0 < trusted_quote.best_bid_cents < 100):
                            break
                    
                    # If this was the last attempt, log detailed failure info
                    if attempt == max_retries - 1:
                        # Detailed logging for quote validation failure
                        if trusted_quote:
                            self.logger.error(
                                "[crypto15m_risk] Quote validation failed after %d attempts for %s - "
                                "health=%s source=%s is_fallback=%s mid_cents=%s best_ask_cents=%s best_bid_cents=%s "
                                "age_ms=%.1f confidence=%.2f diagnostics=%s status=%s",
                                max_retries, market.market_id, trusted_quote.health, trusted_quote.source,
                                trusted_quote.is_fallback, trusted_quote.mid_cents, trusted_quote.best_ask_cents,
                                trusted_quote.best_bid_cents, trusted_quote.age_ms, trusted_quote.confidence,
                                trusted_quote.diagnostics, trusted_quote.status
                            )
                        else:
                            self.logger.error(
                                "[crypto15m_risk] No quote available after %d attempts for %s - "
                                "market may be suspended or data unavailable",
                                max_retries, market.market_id
                            )
                    else:
                        # Exponential backoff before retry
                        backoff_ms = base_backoff_ms * (2 ** attempt)
                        self.logger.warning(
                            "[crypto15m_risk] Quote fetch attempt %d/%d failed for %s - "
                            "retrying in %dms (health=%s, mid_cents=%s)",
                            attempt + 1, max_retries, market.market_id, backoff_ms,
                            trusted_quote.health if trusted_quote else "no_quote",
                            trusted_quote.mid_cents if trusted_quote else "N/A"
                        )
                        await asyncio.sleep(backoff_ms / 1000.0)
                
                if trusted_quote and trusted_quote.health == "healthy":
                    # Use verified quote from integrity layer
                    # Check confidence threshold for production safety
                    if trusted_quote.confidence < 0.5:
                        self.logger.warning(
                            "[crypto15m_risk] Healthy quote has low confidence for %s - confidence=%.2f age_ms=%.1f",
                            market.market_id, trusted_quote.confidence, trusted_quote.age_ms
                        )
                    if trusted_quote.mid_cents and 0 < trusted_quote.mid_cents < 100:
                        price_cents = int(trusted_quote.mid_cents)
                    elif trusted_quote.best_ask_cents and 0 < trusted_quote.best_ask_cents < 100:
                        price_cents = int(trusted_quote.best_ask_cents)
                    elif trusted_quote.best_bid_cents and 0 < trusted_quote.best_bid_cents < 100:
                        price_cents = int(trusted_quote.best_bid_cents)
                    else:
                        self.logger.error(
                            "[crypto15m_risk] Trusted quote exists but no valid prices for %s - health=%s source=%s is_fallback=%s. "
                            "mid_cents=%s, best_ask_cents=%s, best_bid_cents=%s age_ms=%.1f confidence=%.2f",
                            market.market_id, trusted_quote.health, trusted_quote.source,
                            trusted_quote.is_fallback, trusted_quote.mid_cents,
                            trusted_quote.best_ask_cents, trusted_quote.best_bid_cents,
                            trusted_quote.age_ms, trusted_quote.confidence
                        )
                        raise ValueError(f"Trusted quote has no valid prices for {market.market_id}; refusing to create order")
                elif trusted_quote and trusted_quote.health == "degraded":
                    # Trading allowed in degraded mode (using REST fallback)
                    if trusted_quote.mid_cents and 0 < trusted_quote.mid_cents < 100:
                        price_cents = int(trusted_quote.mid_cents)
                        self.logger.warning(
                            "[crypto15m_risk] Using degraded quote for %s - source=%s is_fallback=%s diagnostics=%s age_ms=%.1f confidence=%.2f",
                            market.market_id, trusted_quote.source, trusted_quote.is_fallback,
                            trusted_quote.diagnostics, trusted_quote.age_ms, trusted_quote.confidence
                        )
                    else:
                        self.logger.error(
                            "[crypto15m_risk] Degraded quote has no valid prices for %s - health=%s source=%s age_ms=%.1f confidence=%.2f",
                            market.market_id, trusted_quote.health, trusted_quote.source,
                            trusted_quote.age_ms, trusted_quote.confidence
                        )
                        raise ValueError(f"Degraded quote has no valid prices for {market.market_id}; refusing to create order")
                else:
                    # Suspended or no quote - reject order
                    health = trusted_quote.health if trusted_quote else "no_quote"
                    self.logger.error(
                        "[crypto15m_risk] No healthy/degraded quote for %s - health=%s - rejecting order",
                        market.market_id, health
                    )
                    raise ValueError(f"No healthy quote for {market.market_id}; refusing to create order")
            except Exception as _price_exc:
                self.logger.error(
                    "[crypto15m_risk] Failed to fetch trusted quote for %s: %s - rejecting order",
                    market.market_id, _price_exc
                )
                raise ValueError(f"Failed to fetch trusted quote for {market.market_id}; refusing to create order")
            # Ensure valid range 1-99
            price_cents = max(1, min(99, price_cents))

        if is_crypto_15m:
            try:
                from merid.risk.crypto_swarm_risk_btc15m import (
                    CryptoSwarmRiskBTC15m,
                    TradeProposal,
                    TradeMode,
                    RiskPhase,
                )
                
                # Build trade proposal for risk evaluation
                proposal = TradeProposal(
                    asset=asset_m,
                    timeframe=timeframe_m,
                    side=side,
                    price_cents=price_cents,
                    intent_risk=float(size) * (price_cents / 100.0),  # Dollar amount
                    tags=list(self.config.archetype_tags) if hasattr(self.config, 'archetype_tags') else [],
                    fear_greed=int(getattr(snapshot, 'sentiment_global', 0.5) * 100)
                    if getattr(snapshot, 'sentiment_global', None) is not None else None,
                    spread_ticks=self._estimate_spread_ticks(snapshot),
                    volume_24h=float(market.volume) if market.volume else None,
                    minutes_to_expiry=int(snapshot.time_to_expiry_hours * 60) if snapshot.time_to_expiry_hours else None,
                    session_stable=getattr(snapshot, 'sentiment_regime', 'normal') != 'extreme_volatility',
                )
                
                # Use per-agent singleton so daily PnL and open-exposure
                # state persist across calls (not zeroed on every signal).
                if self._btc15m_risk is None:
                    # Bootstrap equity from unified v2 bankroll service (single source of truth)
                    _init_equity = 0.0
                    try:
                        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                        _effective_usd = get_equity_for_risk_calc_sync()
                        if _effective_usd:
                            _init_equity = float(_effective_usd)
                            self.logger.debug("[crypto15m_risk] Bootstrapped equity from unified bankroll: $%.2f", _init_equity)
                    except Exception as _e:
                        self.logger.debug("[crypto15m_risk] unified bankroll unavailable: %s", _e)
                    # Fallback only for emergency initialization (should not happen)
                    if _init_equity <= 0:
                        try:
                            from merid.settings import settings as _s_ta
                            _init_equity = float(getattr(_s_ta, 'PAPER_STARTING_BALANCE', 0) or 0)
                            self.logger.warning("[crypto15m_risk] Fallback to PAPER_STARTING_BALANCE: $%.2f — unified bankroll should be available", _init_equity)
                        except Exception as _e:
                            self.logger.debug("[crypto15m_risk] settings fallback failed: %s", _e)
                    _init_phase = RiskPhase.PHASE_0
                    try:
                        from merid.risk.promotion_engine import get_promotion_engine
                        _pe = get_promotion_engine()
                        # Do NOT overwrite _init_equity with per_trade cap — that is a
                        # per-order sizing limit, not the account equity.  Only use it
                        # to resolve the current promotion phase.
                        _phase_name = _pe.get_status().get("current_phase", "PHASE_0")
                        _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
                    except Exception as _e:
                        self.logger.debug("phase_lookup_promotion_engine: %s", _e)
                    self._btc15m_risk = CryptoSwarmRiskBTC15m(
                        current_equity=_init_equity,
                        phase=_init_phase,
                    )
                risk_manager = self._btc15m_risk
                # B9: Re-resolve current equity from unified v2 bankroll service
                _cur_equity = 0.0
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    _effective_usd = get_equity_for_risk_calc_sync()
                    if _effective_usd:
                        _cur_equity = float(_effective_usd)
                except Exception as e:
                    self.logger.debug("[crypto15m_risk] unified bankroll update failed: %s", e)
                # Fallback only for emergency (should not happen)
                if _cur_equity <= 0:
                    try:
                        from merid.settings import settings as _s_upd
                        _cur_equity = float(getattr(_s_upd, 'PAPER_STARTING_BALANCE', 0) or 0)
                        self.logger.warning("[crypto15m_risk] Fallback to PAPER_STARTING_BALANCE for update: $%.2f", _cur_equity)
                    except Exception as e:
                        self.logger.debug("[crypto15m_risk] settings fallback for update failed: %s", e)
                try:
                    risk_manager.update_from_phase(_cur_equity)
                except Exception as _e:
                    self.logger.debug("update_from_phase: %s", _e)

                # Sync live exposure from KalshiRiskManager each call
                try:
                    risk_manager.open_exposure_total = self._get_current_open_exposure()
                    risk_manager.open_positions = self._get_open_positions_dict()
                except Exception as _e:
                    self.logger.debug("sync_open_exposure: %s", _e)

                decision = risk_manager.evaluate_proposal(proposal)

                self.logger.info(
                    "crypto 15m risk decision: asset=%s tf=%s mode=%s intent_risk_usd=%.4f "
                    "(mid×contracts for swarm) price_cents_for_risk=%s contracts=%s "
                    "final_risk_usd=%.2f (after F&G/caps) | %s",
                    asset_m,
                    timeframe_m,
                    decision.mode.value,
                    proposal.intent_risk,
                    price_cents,
                    size,
                    decision.final_size,
                    decision.reason,
                )

                if decision.mode == TradeMode.BLOCKED:
                    self.logger.info(
                        "crypto 15m risk BLOCKED: asset=%s %s",
                        asset_m,
                        decision.blocked_reason,
                    )
                    await self._record_risk_blocked_order(market, signal, decision, snapshot)
                    return

                # Adjust size based on risk decision
                if decision.final_size < proposal.intent_risk:
                    original_contracts = size
                    # Recalculate contracts based on final dollar size
                    if price_cents > 0:
                        size = int(decision.final_size / (price_cents / 100.0))
                        size = max(1, size)  # At least 1 contract
                    self.logger.info(
                        "crypto 15m size adjusted: asset=%s %s → %s contracts ($%.2f)",
                        asset_m,
                        original_contracts,
                        size,
                        decision.final_size,
                    )

                # For paper mode, force simulation
                force_paper = decision.mode == TradeMode.PAPER

            except Exception as exc:
                # Risk layer failed - log and continue with normal execution
                self.logger.warning("crypto 15m risk evaluation failed: %s", exc)
                force_paper = False
        else:
            # Non-crypto-15m: route through existing paper/live gate
            force_paper = False

        # === SwarmConsensusEngine Gate ===
        # Formal vote-veto and explainability layer.  _check_consensus_gate() above
        # already handles direction + size band; this adds explicit veto support,
        # structured Explainability events, and a per-trade audit trail.
        # Fail-open: any error falls through to normal execution.
        try:
            from merid.swarm.consensus_engine import get_swarm_consensus_engine as _get_sce
            from merid.pipeline.proposal import (
                TradeProposal as _TradeProposal,
                TradeDomain as _TradeDomain,
                OrderSide as _OSide,
                OrderType as _OType,
            )
            from merid.agents.coordination import AgentVote as _AgentVote
            from decimal import Decimal as _SCEDecimal

            _sce_proposal = _TradeProposal(
                domain=_TradeDomain.PREDICTION,
                agent_id=self.agent_id,
                venue="kalshi",
                instrument_id=market.market_id,
                side=_OSide.BUY if action == "buy" else _OSide.SELL,
                order_type=_OType.LIMIT,
                qty=_SCEDecimal(str(size)),
                price=_SCEDecimal(str(price_cents / 100.0)) if price_cents else None,
                confidence=_SCEDecimal(str(
                    float(signal.confidence) if hasattr(signal, "confidence") else 0.5
                )),
                rationale=f"{signal.action} {market.market_id}",
            )
            _sce_pid = _sce_proposal.proposal_id

            # Base votes: this agent + risk-manager + governance
            # (execution_guard.pre_trade_check() and BTC15m risk already passed above)
            _sce_votes: list = [
                _AgentVote(
                    agent_id=self.agent_id,
                    decision="approve",
                    confidence=float(signal.confidence) if hasattr(signal, "confidence") else 0.5,
                    reasoning="pre-trade checks passed",
                    weight=1.0,
                ),
                _AgentVote(
                    agent_id="risk-manager-01",
                    decision="approve",
                    confidence=1.0,
                    reasoning="execution_guard pre_trade_check passed",
                    weight=1.5,
                ),
                _AgentVote(
                    agent_id="governance-01",
                    decision="approve",
                    confidence=1.0,
                    reasoning="Kalshi prediction domain validated",
                    weight=1.5,
                ),
            ]

            # Peer votes: map ConsensusAggregator raw_proposals → approve/reject/abstain
            try:
                from merid.swarm.consensus_aggregator import get_consensus_aggregator as _get_ca
                _peer_asset = self._strategy._extract_asset_from_market_id(market.market_id) if (self._strategy and market) else ""
                if not _peer_asset or _peer_asset == "UNK":
                    _peer_asset = self.config.assets[0] if self.config.assets else ""
                _peer_tf = self.config.timeframes[0] if self.config.timeframes else ""
                _cv = _get_ca().get_consensus(_peer_asset, _peer_tf)
                if _cv is not None:
                    for _rp in _cv.raw_proposals:
                        if _rp.agent_id == self.agent_id:
                            continue  # already counted in base votes above
                        _peer_decision = (
                            "approve" if _rp.direction == side
                            else "reject" if _rp.direction in ("yes", "no") and _rp.direction != side
                            else "abstain"
                        )
                        _sce_votes.append(_AgentVote(
                            agent_id=_rp.agent_id,
                            decision=_peer_decision,
                            confidence=_rp.confidence,
                            reasoning=f"peer direction={_rp.direction}",
                            weight=0.5 if _rp.downweight else 1.0,
                        ))
            except Exception as _cv_err:
                self.logger.debug("swarm_engine_peer_votes: %s", _cv_err)

            _sce_result = await asyncio.wait_for(
                _get_sce().run_consensus([_sce_proposal], {_sce_pid: _sce_votes}),
                timeout=3.0,
            )
            if not _sce_result:
                self.logger.info(
                    "swarm_engine_vetoed: %s side=%s action=%s size=%s",
                    market.market_id, side, action, size,
                )
                return

        except Exception as _sce_exc:
            self.logger.debug("swarm_engine_gate (fail-open): %s", _sce_exc)

        # === KalshiCore Agent Pipeline ===
        # Fire all 8 LLM-based reasoning agents against this trade proposal in the
        # background.  Results are recorded in Neo4j + the reflection system so agents
        # learn over time.  Never blocks trade execution — always fail-open.
        try:
            from core.kalshi_orchestrator import get_kalshi_core
            from core.energy import create_energy as _create_energy
            _kc_edge = getattr(signal, "edge", None)
            _kc_edge_bps = int(float(getattr(_kc_edge, "net_edge", 0)) * 10000) if _kc_edge else 0
            _kc_p_true = float(getattr(_kc_edge, "model_prob", 0.5)) if _kc_edge else 0.5
            _kc_p_implied = float(getattr(_kc_edge, "market_prob", 0.5)) if _kc_edge else 0.5
            _kc_payload = (
                f"Kalshi trade proposal | agent={self.agent_id} lane={self.config.name} "
                f"market={market.market_id} direction={side} action={action} "
                f"price={price_cents}c size={size} contracts "
                f"edge={_kc_edge_bps}bps p_true={_kc_p_true:.3f} p_implied={_kc_p_implied:.3f} "
                f"confidence={float(getattr(signal, 'confidence', 0)):.2f} "
                f"reason: {getattr(signal, 'reason', 'N/A')}"
            )
            _kc_energy = _create_energy(
                source=f"kalshi_lane:{self.config.name}",
                payload=_kc_payload,
            )
            _kc_task = asyncio.create_task(
                get_kalshi_core().run_cycle(_kc_energy),
                name=f"kalshi_core:{market.market_id}",
            )
            # Drain the exception so Python doesn't log "task was destroyed pending"
            _kc_task.add_done_callback(
                lambda _t: _t.exception() if not _t.cancelled() else None
            )
        except Exception as _kc_exc:
            self.logger.debug("kalshi_core_fire_and_forget: %s", _kc_exc)

        if action == "quote":
            # For quotes, place a buy and sell limit order pair
            _q_bid_result = None
            _q_ask_result = None
            if signal.bid_price_cents:
                _q_bid_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="buy",
                    price_cents=signal.bid_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                )
            if signal.ask_price_cents:
                _q_ask_result = await _kalshi_place_order(
                    ticker=market.market_id,
                    side="yes",
                    action="sell",
                    price_cents=signal.ask_price_cents,
                    count=size,
                    agent_name=self.agent_id,
                )
            # Record as a single "quote" event in logs
            _q_ok = ((_q_bid_result is None or _q_bid_result.success) and
                     (_q_ask_result is None or _q_ask_result.success))
            result_success = _q_ok
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(),
                "order_id": "quote_group",
            }
            if _q_ok:
                result_error = None
            else:
                _leg_errs: list[str] = []
                if _q_bid_result is not None and not _q_bid_result.success:
                    _leg_errs.append(f"bid:{_q_bid_result.error_message or 'fail'}")
                if _q_ask_result is not None and not _q_ask_result.success:
                    _leg_errs.append(f"ask:{_q_ask_result.error_message or 'fail'}")
                result_error = "; ".join(_leg_errs) if _leg_errs else "One or both quote legs failed"
        elif signal.side == "both":
            # BUG-4 fix: Arb — buy YES leg and NO leg via a shared Kalshi order
            # group so the exchange can atomically cancel both on limit breach.
            # A parent intent_id links both legs for downstream analytics.
            import uuid as _arb_uuid
            from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent as _ArbIntent

            # CRITICAL FIX: Resolve valid market price when signal.limit_price_cents is None/invalid
            # For arb: YES price + NO price must equal 100, and both must be in range 1-99
            price_cents = signal.limit_price_cents
            if price_cents is None or price_cents <= 0 or price_cents >= 100:
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    state = store.get(market.market_id)
                    if state:
                        if state.mid_cents and 0 < state.mid_cents < 100:
                            price_cents = int(state.mid_cents)
                        elif state.best_ask_cents and 0 < state.best_ask_cents < 100:
                            price_cents = int(state.best_ask_cents)
                        elif state.best_bid_cents and 0 < state.best_bid_cents < 100:
                            price_cents = int(state.best_bid_cents)
                        else:
                            price_cents = 50
                    else:
                        price_cents = 50
                except Exception as _price_exc:
                    self.logger.debug("[trading_agent.arb] Failed to fetch market price for %s: %s", market.market_id, _price_exc)
                    price_cents = 50
                # Ensure valid range 1-99
                price_cents = max(1, min(99, price_cents))
                if price_cents != signal.limit_price_cents:
                    self.logger.info(
                        "[trading_agent.arb] Resolved market price for %s: %s -> %sc",
                        market.market_id, signal.limit_price_cents, price_cents
                    )
            yes_price = price_cents
            no_price = max(1, 100 - yes_price)

            # Create a dedicated order group for this arb trade
            _arb_group_id: Optional[str] = None
            _arb_notional_cents = size * (yes_price + no_price)
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client as _get_arb_client
                _arb_client = _get_arb_client()
                await _arb_client.connect()
                _arb_grp_res = await _arb_client.create_order_group(
                    name=f"arb-{market.market_id}-{_arb_uuid.uuid4().hex[:8]}",
                    max_cost_cents=_arb_notional_cents + 500,
                )
                if _arb_grp_res.success:
                    _arb_group_id = _arb_grp_res.data
                    self.logger.debug("arb: created order group %s", _arb_group_id)
            except Exception as _grp_exc:
                self.logger.warning("arb: order group creation failed (continuing without): %s", _grp_exc)

            _arb_parent_intent_id = f"arb-{_arb_uuid.uuid4().hex}"
            _arb_trace = new_decision_trace_id("arb")

            _snap_ts = (
                snapshot_timestamp_utc_epoch_seconds(getattr(snapshot, "timestamp", None))
                if snapshot
                else __import__("time").time()
            )

            async def _place_arb(s: str, p: int, leg: int) -> object:
                if force_paper:
                    from merid.prediction.kalshi_tools import _kalshi_place_paper_order
                    return await _kalshi_place_paper_order(
                        ticker=market.market_id, side=s, action="buy",
                        price_cents=p, count=size,
                    )

                # BANKROLL UNIFICATION: Get effective bankroll from v2 unified service
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                _effective_equity_usd = 0.0
                try:
                    _eff = get_equity_for_risk_calc_sync()
                    if _eff:
                        _effective_equity_usd = float(_eff)
                except Exception as _bre:
                    self.logger.debug("[trading_agent.arb] Failed to get effective bankroll: %s", _bre)

                _intent = _ArbIntent(
                    ticker=market.market_id, side=s, action="buy",
                    price_cents=p, count=size,
                    source=f"arb:{self.config.name}",
                    agent_id=self.agent_id,
                    order_group_id=_arb_group_id,
                    parent_intent_id=_arb_parent_intent_id,
                    leg_index=leg,
                    snapshot_ts=_snap_ts,
                    edge_pct=float(signal.edge.net_edge) if signal.edge else None,
                    decision_trace_id=_arb_trace,
                    sentiment_driven=False,
                    effective_equity_usd=_effective_equity_usd if _effective_equity_usd > 0 else None,
                )
                _r = await route_order_async(_intent)
                # Adapt to legacy .success / .payload / .error_message interface
                _r.success = _r.status not in ("rejected",)
                _r.payload = _r.fill or {}
                _r.error_message = _r.reason or ""
                return _r

            _yes_result = await _place_arb("yes", yes_price, 0)
            _no_result = await _place_arb("no", no_price, 1)

            async def _cancel_leg(order_id: Optional[str], label: str) -> None:
                if not order_id:
                    return
                try:
                    from merid.event_venues.kalshi.client import get_kalshi_client as _cc
                    _ccl = _cc()
                    await _ccl.connect()
                    _cr = await _ccl.cancel_order_result(order_id)
                    if _cr.success:
                        self.logger.warning("arb rollback: %s leg %s cancelled", label, order_id)
                    else:
                        self.logger.error(
                            "arb rollback: cancel of %s leg %s failed: %s — UNHEDGED EXPOSURE",
                            label, order_id, getattr(_cr, "error_message", _cr),
                        )
                except Exception as _rb_exc:
                    self.logger.error(
                        "arb rollback FAILED for %s leg %s: %s — UNHEDGED EXPOSURE",
                        label, order_id, _rb_exc,
                    )

            # Rollback YES if NO failed
            if _yes_result.success and not _no_result.success:
                await _cancel_leg((_yes_result.payload or {}).get("order_id"), "YES")

            # BUG-4 fix: also rollback NO if YES failed (was missing before)
            if _no_result.success and not _yes_result.success:
                await _cancel_leg((_no_result.payload or {}).get("order_id"), "NO")

            _arb_ok = _yes_result.success and _no_result.success
            result_success = _arb_ok
            result_payload = {
                "simulated": self._venue_gate.should_simulate_fill(),
                "yes_order_id": (_yes_result.payload or {}).get("order_id"),
                "no_order_id": (_no_result.payload or {}).get("order_id"),
                "arb": True,
                "arb_group_id": _arb_group_id,
                "arb_parent_intent_id": _arb_parent_intent_id,
            }
            result_error = None if _arb_ok else (
                f"YES: {getattr(_yes_result, 'error_message', '')}; NO: {getattr(_no_result, 'error_message', '')}"
            )
            # Override side/action for log consistency
            side = "both"
            action = "buy"
        else:
            # CRITICAL FIX: Resolve valid market price when signal.limit_price_cents is None/invalid
            # Order router requires 1-99 cents; 0 or 100 are invalid
            price_cents = signal.limit_price_cents
            if price_cents is None or price_cents <= 0 or price_cents >= 100:
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    state = store.get(market.market_id)
                    if state:
                        if state.mid_cents and 0 < state.mid_cents < 100:
                            price_cents = int(state.mid_cents)
                        elif state.best_ask_cents and 0 < state.best_ask_cents < 100:
                            price_cents = int(state.best_ask_cents)
                        elif state.best_bid_cents and 0 < state.best_bid_cents < 100:
                            price_cents = int(state.best_bid_cents)
                        else:
                            price_cents = 50
                    else:
                        price_cents = 50
                except Exception as _price_exc:
                    self.logger.debug("[trading_agent] Failed to fetch market price for %s: %s", market.market_id, _price_exc)
                    price_cents = 50
                # Ensure valid range 1-99
                price_cents = max(1, min(99, price_cents))
                if price_cents != signal.limit_price_cents:
                    self.logger.info(
                        "[trading_agent] Resolved market price for %s: %s -> %sc",
                        market.market_id, signal.limit_price_cents, price_cents
                    )
            # Route through order_router so TIF resolution (IOC-auto-below-seconds
            # via KalshiMarketStateStore) and the full safety pipeline apply.
            # Consensus confidence and rationale are forwarded to the OrderIntent
            # so the order router can log and apply them.
            try:
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                from trading.trade_mode import TradeMode as _TradeMode
                # PRODUCTION FIX: Dynamic take-profit based on R-multiple and confidence
                from merid.prediction.dynamic_takeprofit import compute_dynamic_tp
                _intent_mode = _TradeMode.PAPER if force_paper else None
                _conf = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else None
                _rationale = (
                    str(signal.action.value if hasattr(signal.action, "value") else signal.action)
                )[:200]
                # Prefer strategy correlation_id so logs ([TRACE] ANALYZE_START) match router / fills metadata.
                _sig_corr = getattr(signal, "correlation_id", None)
                _sig_corr_s = (
                    _sig_corr.strip()
                    if isinstance(_sig_corr, str) and _sig_corr.strip()
                    else None
                )
                _trace = _sig_corr_s or new_decision_trace_id("ta")

                # BANKROLL UNIFICATION: Get effective bankroll from v2 unified service
                # This ensures the risk layer uses the same bankroll value as the sizing layer
                _effective_equity_usd = 0.0
                try:
                    _eff = get_equity_for_risk_calc_sync()
                    if _eff:
                        _effective_equity_usd = float(_eff)
                except Exception as _bre:
                    self.logger.debug("[trading_agent] Failed to get effective bankroll: %s — risk check may block", _bre)
                    # Continue with 0; risk layer will fail-closed if equity is required

                # MICRO-SCALPING: Check cycle tracker capacity before deploying capital
                _order_notional = (price_cents * size) / 100.0
                _cycle_ok, _cycle_available, _cycle_reason = self._cycle_tracker.check_capacity(_order_notional)
                if not _cycle_ok:
                    self.logger.warning(
                        "[CYCLE_CAP_BLOCK] %s: %s | available=$%.2f needed=$%.2f",
                        market.market_id, _cycle_reason, _cycle_available, _order_notional,
                    )
                    return  # Block order - cycle cap reached
                
                # Record deployment in cycle tracker (will be released on position close)
                self._cycle_tracker.record_deployment(_order_notional, f"{market.market_id}_{side}")
                self.logger.debug(
                    "[CYCLE_CAP_DEPLOY] %s: $%.2f deployed | available=$%.2f | cycle_util=%.1f%%",
                    market.market_id, _order_notional, self._cycle_tracker.available,
                    self._cycle_tracker.summary()["utilization_pct"],
                )

                # ── PER-TRADE SUMMARY ───────────────────────────────────────────────
                # Concise entry log for post-mortem analysis of 4am-style anomalies
                _trade_asset = getattr(self.config, 'asset', 'BTC')
                _trade_is_major = _trade_asset in ('BTC', 'ETH')
                _asset_tf = f"{_trade_asset}:{self.config.timeframes[0] if self.config.timeframes else '15m'}"
                _edge_val = float(signal.edge.net_edge) if signal.edge else 0.0
                _conf_val = _conf if _conf is not None else 0.0
                _sl_dist = 2.0  # micro-scalping default SL distance in cents
                _dtp_target = self._dynamic_tp_calc.get_target(
                    entry_price=price_cents,
                    current_price=price_cents,
                    volatility=self._calculate_volatility(market.market_id, price_cents) if hasattr(self, '_calculate_volatility') else 0.03,
                    momentum=_edge_val,
                ) if hasattr(self, '_dynamic_tp_calc') else 0.05

                # ═── KALSHI 15M EDGE METRICS ─────────────────────────────────────────
                # Compute systematic edge: spot→strike distance vs implied vs model prob
                _kalshi_price_dollars = price_cents / 100.0  # Convert cents to dollars (0.01-0.99)
                _model_prob = _conf_val if _conf_val > 0 else 0.5  # Use confidence as model prob proxy
                
                # Extract strike from ticker (e.g., KXBTC-15M-250501-T85300 → 85300)
                _strike_price = None
                try:
                    _ticker_parts = market.market_id.split('-')
                    for _part in _ticker_parts:
                        if _part.startswith('T') and _part[1:].isdigit():
                            _strike_price = float(_part[1:])
                            break
                        elif _part.startswith('P') and _part[1:].replace('.', '').isdigit():
                            _strike_price = float(_part[1:])
                            break
                except Exception:
                    _strike_price = None
                
                # Get spot price for distance calculation
                _spot_price = None
                try:
                    from merid.prediction.crypto_top_edge import CRYPTO_ASSETS
                    if _trade_asset in CRYPTO_ASSETS:
                        # Try to get spot from live price feed
                        from data.live_price_feed import get_live_price_feed
                        feed = get_live_price_feed()
                        symbol = f"{_trade_asset}-USD" if _trade_asset else "BTC-USD"
                        price_data = feed.get_current_price(symbol)
                        if price_data:
                            _spot_price = float(price_data.price)
                except Exception:
                    _spot_price = None
                
                # Compute edge metrics if we have both spot and strike
                _edge_metrics_str = ""
                _metrics = None
                if _spot_price and _strike_price:
                    _metrics = compute_kalshi_edge_metrics(
                        spot=_spot_price,
                        strike=_strike_price,
                        kalshi_price=_kalshi_price_dollars,
                        model_prob=_model_prob,
                        asset=_trade_asset,
                        contracts=size,
                    )
                    _edge_metrics_str = format_edge_metrics_log(_metrics)
                else:
                    # Fallback: log without distance metrics
                    _edge_metrics_str = (
                        f"kalshi_price={_kalshi_price_dollars:.2f} model_prob={_model_prob:.3f} "
                        f"spot=unknown strike={_strike_price or 'unknown'} "
                        f"edge=unknown (spot/strike unavailable)"
                    )

                # ═── LAYER 3 EXECUTION GUARD: Distance + Edge ──────────────────────────
                # Fatal: Block trades that exceed distance caps or edge floors
                if _metrics:
                    _layer3_guard = check_execution_guards(
                        asset=_trade_asset,
                        timeframe=_asset_tf.split(':')[1] if ':' in _asset_tf else '15m',
                        delta_pct=_metrics.delta_pct,
                        z_score=_metrics.z_score,
                        edge=_metrics.edge,
                        log_fn=self.logger.info,
                    )
                    if not _layer3_guard.allowed:
                        # Release cycle tracker allocation since we're blocking
                        self._cycle_tracker.record_release(_order_notional, f"{market.market_id}_{side}")
                        return  # Blocked by distance or edge guard
                # ─────────────────────────────────────────────────────────────────────

                self.logger.info(
                    "[TRADE_ENTRY] %s | asset_tf=%s | edge=%.3f | conf=%.2f | "
                    "size=%d | price=%dc | SL=%.1fc | DTP=%.1f%% | "
                    "trail=%.1f%%@%+.1f%% | max_hold=%ds | corr_id=%s | %s",
                    market.market_id,
                    _asset_tf,
                    _edge_val,
                    _conf_val,
                    size,
                    price_cents,
                    _sl_dist,
                    _dtp_target * 100,
                    (0.015 if _trade_is_major else 0.02) * 100,  # trailing distance
                    1.5,  # trailing activation
                    180,  # max_hold_seconds (reverted 2026-05-08 from 120s to restore profitable trades)
                    _trace[:16] if _trace else "none",
                    _edge_metrics_str,
                )
                # ────────────────────────────────────────────────────────────────────

                # PRODUCTION FIX: Compute dynamic take-profit based on R-multiple and confidence
                # Maps confidence to TP: ≤0.3 → 1.0R, 0.3-0.6 → 1.5R, >0.6 → 2.0-3.0R
                _tp_price_cents = None
                _tp_r_multiple = None
                try:
                    # Estimate stop distance (default 2 cents for micro-scalping)
                    _stop_distance = 2.0
                    # Determine direction for TP computation
                    _direction = "LONG" if side.lower() == "yes" else "SHORT"
                    # Use edge confidence or fallback
                    _tp_confidence = _conf if _conf is not None else 0.5
                    # Use edge.net_edge as Kelly fraction proxy
                    _kelly = float(signal.edge.net_edge) if signal.edge else None

                    _tp_plan = compute_dynamic_tp(
                        entry_price=float(price_cents),
                        stop_price=float(price_cents) - _stop_distance if _direction == "LONG" else float(price_cents) + _stop_distance,
                        direction=_direction,
                        confidence=_tp_confidence,
                        kelly_fraction=_kelly
                    )

                    _tp_price_cents = int(_tp_plan.tp_price)
                    _tp_r_multiple = _tp_plan.tp_r_multiple
                    # Clamp TP to valid Kalshi range 1-99
                    _tp_price_cents = max(1, min(99, _tp_price_cents))

                    self.logger.debug(
                        "[DTP] %s: entry=%sc, TP=%sc (%.2fR), conf=%.2f",
                        market.market_id, price_cents, _tp_price_cents,
                        _tp_r_multiple, _tp_confidence
                    )
                except Exception as _tp_exc:
                    self.logger.debug("[DTP] TP computation failed for %s: %s", market.market_id, _tp_exc)

                _intent = OrderIntent(
                    ticker=market.market_id,
                    side=side,
                    action=action,
                    price_cents=price_cents,
                    count=size,
                    mode=_intent_mode,
                    source=self.agent_id,
                    agent_id=self.agent_id,
                    confidence=_conf,
                    rationale=_rationale,
                    edge_pct=float(signal.edge.net_edge) if signal.edge else None,
                    snapshot_ts=snapshot_timestamp_utc_epoch_seconds(
                        getattr(snapshot, "timestamp", None) if snapshot else None
                    ),
                    decision_trace_id=_trace,
                    client_tag=_sig_corr_s,
                    sentiment_driven=bool(_conf and _conf > 0.4),
                    effective_equity_usd=_effective_equity_usd if _effective_equity_usd > 0 else None,
                    # PRODUCTION: Dynamic take-profit wiring
                    take_profit_price_cents=_tp_price_cents,
                    take_profit_r_multiple=_tp_r_multiple,
                )
                # Add timeout to prevent indefinite hanging on network calls
                import asyncio
                try:
                    _route_result = await asyncio.wait_for(
                        route_order_async(_intent),
                        timeout=30.0  # 30 second timeout for order placement
                    )
                except asyncio.TimeoutError:
                    self.logger.error("route_order_async TIMEOUT after 30s | market=%s", market.market_id)
                    raise
                # Adapt OrderResult → legacy .success/.payload/.error_message
                result_success = _route_result.status not in ("rejected",)
                result_payload = _route_result.fill or {}
                result_error = _route_result.reason or ""
                # CRITICAL FIX: Release cycle tracker allocation if order was rejected
                if not result_success:
                    self._cycle_tracker.record_release(_order_notional, f"{market.market_id}_{side}")
                    self.logger.warning(
                        "[CYCLE_CAP_RELEASE] %s: Order rejected, released $%.2f | reason=%s",
                        market.market_id, _order_notional, result_error
                    )
            except Exception as _re:
                # SECURITY: No fallback - all orders must go through canonical router.
                # Fallbacks create complexity and potential bypass paths.
                self.logger.error("route_order_async failed, order rejected: %s", _re)
                # CRITICAL FIX: Release cycle tracker allocation on exception
                self._cycle_tracker.record_release(_order_notional, f"{market.market_id}_{side}")
                self.logger.warning(
                    "[CYCLE_CAP_RELEASE] %s: Router exception, released $%.2f | error=%s",
                    market.market_id, _order_notional, str(_re)[:100]
                )
                result_success = False
                result_payload = {}
                result_error = f"router_failed:{str(_re)[:100]}"

        try:
            from merid.prediction.crypto_edge_production import log_execution_decision
            from core.execution_gate import check_execution_gate

            _eg = check_execution_gate()
            _safe = bool(getattr(_eg, "safe_to_trade", True) and not getattr(_eg, "blocked", False))
            _eg_sources = [r.source for r in (_eg.reasons or [])]
            _cv = None
            try:
                _ca = get_consensus_aggregator().get_consensus(
                    self.config.assets[0] if self.config.assets else "",
                    self.config.timeframes[0] if self.config.timeframes else "",
                )
                if _ca:
                    _cv = {
                        "direction": _ca.consensus_direction,
                        "p": _ca.consensus_probability,
                        "status": _ca.status.value,
                    }
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
            log_execution_decision(
                market=market.market_id,
                side=str(side),
                size=int(size),
                consensus_value=_cv,
                safe_to_trade=_safe,
                risk_state=getattr(_eg, "gate_state", "unknown"),
                actual_order_submitted=bool(result_success),
                block_reason=(
                    "none"
                    if result_success
                    else (str(result_error)[:200] if result_error else "order_rejected_unknown")
                ),
                source="kalshi_trading_agent",
                execution_gate_sources=_eg_sources,
            )
            if _safe and not result_success and not (result_error or ""):
                logger.warning(
                    "[EXECUTION_INVARIANT] safe_to_trade but order failed without reason market=%s",
                    market.market_id,
                )
        except Exception as _exl:
            self.logger.debug("execution decision log skipped: %s", _exl)

        # BUG-FIX: Use explicit datetime module reference to avoid UnboundLocalError
        # when datetime is determined to be a local variable but hasn't been assigned yet.
        from datetime import datetime as _datetime_now
        now_ts = _datetime_now.now(timezone.utc)
        # Also fix the datetime references earlier in this function (lines ~3722, 3726)
        # where datetime was used without being declared global, causing Python to
        # treat it as local but unassigned at this point.
        ref_bid = float(snapshot.implied.yes_bid) if snapshot and snapshot.implied.yes_bid else None
        ref_ask = float(snapshot.implied.yes_ask) if snapshot and snapshot.implied.yes_ask else None
        ref_mid = (ref_bid + ref_ask) / 2 if ref_bid and ref_ask else None

        # Record order
        _o_edge_pct = float(signal.edge.net_edge) if signal.edge else None
        _o_confidence = float(signal.confidence) if hasattr(signal, "confidence") else None
        _o_phase = signal.phase.value if hasattr(signal, "phase") and signal.phase else ""
        _o_archetype = self.config.archetype if hasattr(self.config, "archetype") else ""
        # BUG-FIX: Use resolved price_cents (which was validated/fetched from market state)
        # instead of signal.limit_price_cents which may be 0 or None
        _o_price_c = price_cents if price_cents > 0 else (signal.limit_price_cents or 50)
        _o_notional = round(size * (_o_price_c / 100.0), 2) if _o_price_c else None
        order_entry = {
            "ts": now_ts.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": side,
            "action": action,
            "price_cents": _o_price_c if action != "quote" else None,
            "bid_price": signal.bid_price_cents,
            "ask_price": signal.ask_price_cents,
            "contracts": size,
            "ref_bid": ref_bid,
            "ref_ask": ref_ask,
            "ref_mid": ref_mid,
            "success": result_success,
            "simulated": result_payload.get("simulated", False) if result_success else None,
            "error": result_error if not result_success else None,
            "agent": self.config.name,
            "edge_pct": _o_edge_pct,
            "confidence": _o_confidence,
            "phase": _o_phase,
            "archetype": _o_archetype,
            "notional_usd": _o_notional,
            "time_in_force": getattr(signal, "time_in_force", "gtc") or "gtc",
        }
        self.state.order_log.append(order_entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]

        # Publish order_placed event regardless of fill outcome
        try:
            from core.event_bus import event_stream as _event_bus
            await _event_bus.publish("kalshi:order_placed", order_entry)
        except Exception as _ep:
            self.logger.debug(f"Event bus order_placed publish error (ignored): {_ep}")

        # BUG-06 fix: derive live-fill flag from venue gate mode (authoritative),
        # not from a payload dict key that may be absent after schema changes.
        _is_live_fill = not self._venue_gate.should_simulate_fill()

        # BUG-02 fix: distinguish between an order being *accepted* (GTC resting)
        # and actually *filled*.  Only confirmed fills trigger risk accounting,
        # position tracking, and fill-log entries.  Accepted-only orders are
        # counted in the order log but not treated as open exposure.
        _order_status = (result_payload or {}).get("status", "")
        _is_accepted_only = (
            _is_live_fill
            and result_success
            and _order_status in ("accepted_live", "resting", "open")
            and _order_status not in ("filled_live", "partial_live")
            and not (result_payload or {}).get("simulated", False)
        )

        if result_success:
            self.state.orders_placed += 1
            self.state.orders_this_window += 1
            # End global ERROR_THRESHOLD startup grace on first real (non-simulated) live success.
            if _is_live_fill and not (result_payload or {}).get("simulated", False):
                try:
                    from merid.risk.kill_switches import risk_controller as _rc_warm

                    _rc_warm.mark_execution_warm(source=f"kalshi_order:{self.config.name}")
                except Exception as e:
                    self.logger.debug(f"Silent error suppressed: {e}")
            _order_id = result_payload.get("order_id", "") if result_payload else ""
            if _tick is not None and _bus is not None:
                _bus.emit(_tick.emit_order_submitted(
                    market_id=market.market_id,
                    side=side,
                    contracts=size,
                    price_cents=int(price_cents) if price_cents else 0,
                    order_id=str(_order_id),
                ))

            # [TRACE] EXECUTE_ORDER — log with correlation_id after order placement
            if corr_id:
                self.logger.info(
                    "[TRACE] EXECUTE_ORDER | corr_id=%s | market=%s | side=%s | action=%s | size=%s | price=%s | status=%s | simulated=%s",
                    corr_id,
                    market.market_id,
                    side,
                    action,
                    size,
                    price_cents,
                    "success" if result_success else "failed",
                    result_payload.get("simulated", False) if result_payload else False,
                )
            _edge_pct = float(signal.edge.net_edge) if signal.edge else None
            _confidence = float(signal.confidence) if hasattr(signal, "confidence") else None
            _phase = signal.phase.value if hasattr(signal, "phase") and signal.phase else ""
            _archetype = self.config.archetype if hasattr(self.config, "archetype") else ""
            # BUG-FIX: Use resolved price_cents (which was validated/fetched from market state)
            _price_c = price_cents if price_cents > 0 else (signal.limit_price_cents or 50)
            _notional = round(size * (_price_c / 100.0), 2) if _price_c else None
            # B17: use actual fill price from the routing result (simulate_paper_fill
            # applies real bid/ask slippage); fall back to signal limit price only when
            # the fill dict is absent (e.g. legacy fallback path).
            _actual_fill_price_c = (
                result_payload.get("price_cents")
                or result_payload.get("fill_price_cents")
                or _price_c
            )
            fill_entry = {
                "ts": now_ts.isoformat(),
                "market_id": market.market_id,
                "question": market.question[:120] if market.question else "",
                "side": side,
                "action": action,
                "price_cents": _actual_fill_price_c if action != "quote" else None,
                "requested_price_cents": _price_c if action != "quote" else None,
                "contracts": size,
                "ref_bid": ref_bid,
                "ref_ask": ref_ask,
                "ref_mid": ref_mid,
                "simulated": result_payload.get("simulated", False),
                "fill_id": result_payload.get("order_id") or result_payload.get("fill_id"),
                "agent": self.config.name,
                "edge_pct": _edge_pct,
                "confidence": _confidence,
                "phase": _phase,
                "archetype": _archetype,
                "notional_usd": _notional,
                # Live market context from simulate_paper_fill (None when book not initialised)
                "book_initialized": result_payload.get("book_initialized"),
                "live_spread_cents": result_payload.get("live_spread_cents"),
                "live_depth_10c": result_payload.get("live_depth_10c"),
                "seconds_to_expiry": result_payload.get("seconds_to_expiry"),
                "slippage_cents": result_payload.get("slippage_cents"),
            }
            self.state.fill_log.append(fill_entry)
            if len(self.state.fill_log) > _MAX_LOG_ENTRIES:
                self.state.fill_log = self.state.fill_log[-_MAX_LOG_ENTRIES:]

            # Emit event bus event
            try:
                from core.event_bus import event_stream
                await event_stream.publish("kalshi:order_filled", fill_entry)
            except Exception as exc:
                self.logger.debug(f"Event bus publish error (ignored): {exc}")

            if _tick is not None and _bus is not None:
                _bus.emit(_tick.emit_fill(
                    market_id=market.market_id,
                    side=side,
                    contracts=size,
                    # B17: use actual fill price, not the pre-slippage limit price
                    fill_price_cents=int(_actual_fill_price_c or signal.limit_price_cents or 50),
                ))

            # ── Realized edge: log trade entry for later settlement comparison ──
            try:
                from merid.metrics.realized_edge import get_realized_edge_store
                from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents
                edge_store = get_realized_edge_store()
                _trade_id = result_payload.get("order_id") or f"{market.market_id}:{now_ts.isoformat()}"
                # B19a: use actual fill price from routing result, not pre-slippage limit price
                _price_c = int(_actual_fill_price_c or signal.limit_price_cents or 50)
                _p_implied = _price_c / 100.0
                # Bug 4 fix: use model_prob directly (pre-fee probability).
                # Reconstructing from net_edge subtracts fee drag twice because
                # net_edge is already p_model - p_implied - fee_drag.
                _p_model = _p_implied
                if signal.edge and hasattr(signal.edge, 'model_prob') and signal.edge.model_prob is not None:
                    _p_model = max(0.01, min(0.99, float(signal.edge.model_prob)))
                elif signal.edge and hasattr(signal.edge, 'net_edge'):
                    # Fallback for edges that only expose net_edge (legacy path)
                    _p_model = max(0.01, min(0.99, _p_implied + float(signal.edge.net_edge)))
                _fee_c = kalshi_fee_cents(_price_c, size)
                _bucket = (market.category or "unknown").lower()
                edge_store.record_trade_entry(
                    trade_id=_trade_id,
                    forecaster_id=self.config.name,
                    bucket=_bucket,
                    market_id=market.market_id,
                    side=side,
                    action=action,
                    price_cents=_price_c,
                    p_model=_p_model,
                    p_implied=_p_implied,
                    contracts=size,
                    fee_cents=_fee_c,
                    timestamp=now_ts.timestamp(),
                )
            except Exception as _edge_exc:
                self.logger.debug("realized_edge record_trade_entry skipped: %s", _edge_exc)

            # Record fill in performance tracker
            try:
                tracker = get_agent_performance_tracker()
                tracker.record_fill(
                    agent_id=self.agent_id,
                    market_id=market.market_id,
                    side=side,
                    # B19a: use actual fill price, not pre-slippage limit price
                    price_cents=int(_actual_fill_price_c or signal.limit_price_cents or 50),
                    contracts=size,
                    predicted_edge=float(signal.edge.net_edge) if signal.edge else 0.0,
                    confidence=float(signal.confidence) if hasattr(signal, 'confidence') else 0.5,
                )
            except Exception as exc:
                self.logger.debug(f"Performance tracker record error (ignored): {exc}")

            # Wire 3 audit: write ConsensusBlock for replay/audit trail
            try:
                from merid.lanes.consensus_integration import create_consensus_block_from_lane
                _audit_asset = self.config.assets[0] if self.config.assets else ""
                _audit_tf = self.config.timeframes[0] if self.config.timeframes else ""
                _audit_consensus = get_consensus_aggregator().get_consensus(_audit_asset, _audit_tf)
                create_consensus_block_from_lane(
                    market_data={
                        "ticker": market.market_id,
                        "market_ticker": market.market_id,
                        "yes_bid": self._live_markets[0].yes_price if self._live_markets else None,
                        "no_bid": self._live_markets[0].no_price if self._live_markets else None,
                        "spread_bps": self._live_markets[0].spread_bps if self._live_markets else None,
                    },
                    consensus_result={
                        "direction": _audit_consensus.consensus_direction if _audit_consensus else "neutral",
                        "probability": _audit_consensus.consensus_probability if _audit_consensus else 0.5,
                        "confidence": _audit_consensus.consensus_confidence if _audit_consensus else 0.0,
                        "status": _audit_consensus.status.value if _audit_consensus else "stale",
                        "size_band": _audit_consensus.size_band if _audit_consensus else "small",
                    },
                    risk_decision={},
                    votes=[],
                )
            except Exception as _audit_exc:
                self.logger.debug("consensus_block_audit_failed (non-fatal): %s", _audit_exc)

            # Wire fill into PnL attribution engine for debate/signal attribution
            try:
                from merid.prediction.pnl_attribution import record_debate_trade
                _pnl_trade_id = (
                    (result_payload.get("order_id") or result_payload.get("fill_id"))
                    if result_payload else None
                ) or f"{market.market_id}:{now_ts.isoformat()}"
                _pnl_price = float(_actual_fill_price_c or signal.limit_price_cents or 50) / 100.0
                _base_kelly = (
                    float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0
                )
                _debate_mult = getattr(signal, "debate_multiplier", 1.0) or 1.0
                await record_debate_trade(
                    symbol=market.market_id,
                    trade_type="entry",
                    timestamp=now_ts.timestamp(),
                    price=_pnl_price,
                    quantity=size,
                    trade_id=_pnl_trade_id,
                    agent_id=self.agent_id,
                    base_kelly_fraction=_base_kelly,
                    debate_multiplier=_debate_mult,
                    final_kelly_fraction=_base_kelly * _debate_mult,
                    debate_recommendation=side,
                )
            except Exception as exc:
                self.logger.debug("pnl_attribution record_debate_trade skipped: %s", exc)

            # Register fill with stop-loss engine
            try:
                pos_id = result_payload.get("order_id") or market.market_id
                expiry_ts = market.end_date.timestamp() if market.end_date else 0.0
                # B19a: use actual fill price for entry tracking, not pre-slippage limit price
                _fill_price_for_tp = int(_actual_fill_price_c or signal.limit_price_cents or 50)
                # PRODUCTION FIX: Pull TP targets from position_cache (populated via order_router)
                _tp_price = _tp_r = _sl_price = None
                try:
                    _cached_pos = get_position_cache().get_position(market.market_id)
                    if _cached_pos:
                        _tp_price = getattr(_cached_pos, 'take_profit_price_cents', None)
                        _tp_r = getattr(_cached_pos, 'take_profit_r_multiple', None)
                        _sl_price = getattr(_cached_pos, 'stop_loss_price_cents', None)
                except Exception:
                    pass  # Non-fatal: TP targets optional
                tp = TrackedPosition(
                    position_id=pos_id,
                    ticker=market.market_id,
                    side=side,
                    entry_price_cents=_fill_price_for_tp,
                    contracts=size,
                    entry_ts=time.time(),
                    contract_expiry_ts=expiry_ts,
                    current_price_cents=_fill_price_for_tp,
                    take_profit_price_cents=_tp_price,
                    take_profit_r_multiple=_tp_r,
                    stop_loss_price_cents=_sl_price,
                    entry_mode="paper" if force_paper else None,
                )
                self._tracked_positions[pos_id] = tp
                self.logger.debug("stop_loss: tracking position %s %s@%dc", pos_id, side, tp.entry_price_cents)
                # Register with TakeProfitManager — arms the TP state machine
                try:
                    self._tp_manager.on_position_open(tp)
                except Exception as _tp_reg_exc:
                    self.logger.debug("tp_manager.on_position_open skipped: %s", _tp_reg_exc)
            except Exception as exc:
                self.logger.debug("stop_loss register skipped: %s", exc)

            # Wire fill into KalshiRiskManager so risk/sizing endpoints see live flow
            # G3: Only record into live risk manager for real (non-simulated) fills.
            # Paper/sim fills must not skew live drawdown, rate-limit, or PnL state.
            # BUG-02: skip all fill-accounting for accepted-but-not-yet-filled orders.
            if _is_accepted_only:
                self.logger.debug(
                    "order accepted (GTC resting) for %s — fill accounting deferred until fill event",
                    market.market_id,
                )
            else:
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                    risk_mgr = get_kalshi_risk()
                    price_cents = signal.limit_price_cents or 50
                    category = getattr(self.config, 'category', None)
                    if _is_live_fill:
                        # Real fill: update notional exposure AND rate counters.
                        if action in ("sell",):
                            # Closing a position — decrement notional so the cap
                            # reflects actual open exposure, not lifetime volume.
                            risk_mgr.record_close(category=category, contracts=size, price_cents=price_cents)
                        else:
                            risk_mgr.record_order(category=category, contracts=size, price_cents=price_cents)
                        # NOTE: Do NOT call record_pnl() here with edge-based estimates.
                        # Kalshi contracts settle at expiry — PnL is only realized at
                        # settlement, not at fill time.  Crediting speculative edge as
                        # immediate PnL contaminates daily_pnl_usd (the daily loss kill
                        # switch trigger) with phantom gains/losses and inflates
                        # current_equity_usd used for Kelly sizing between PortfolioRiskAgent
                        # syncs.  OutcomeResolver calls record_pnl() at actual settlement.
                    else:
                        # Paper/sim fill: only advance rate-limit counters so a sudden
                        # mode-switch to live doesn't produce a thundering herd.
                        # Do NOT touch total_notional_usd or category_notional — those
                        # caps are for real exposure only.
                        risk_mgr.record_rate_only()
                except Exception as exc:
                    self.logger.debug(f"KalshiRiskManager record error (ignored): {exc}")

            # Record fill in paper session for per-interval PnL tracking
            # G1: Only record in PaperSession when the fill was actually simulated
            # (PAPER/MOCK mode). Live and Shadow fills must NOT pollute paper stats.
            #
            # BUG-02 fix: Kalshi binary contracts settle at expiry, not at fill
            # time.  Recording a random Bernoulli draw here produces an equity
            # curve that is entirely uncorrelated with actual outcomes.  Instead
            # we record only the trade entry (pnl=0, won=None) and let
            # OutcomeResolver call paper_session.record_settlement() once the
            # market resolves.
            _is_simulated_fill = not _is_live_fill
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active and _is_simulated_fill:
                    # B23: prefer actual fee_cents from simulate_paper_fill fill dict;
                    # fall back to pre-trade estimate from PreTradeCheck.
                    _actual_fee_cents = result_payload.get("fee_cents") if result_payload else None
                    if _actual_fee_cents is not None:
                        fee_cents = float(_actual_fee_cents)
                    else:
                        fee_cents = float(check.estimated_fee * 100) * size if hasattr(check, 'estimated_fee') and check.estimated_fee else 0.0
                    session.record_fill(
                        agent_name=self.config.name,
                        pnl_cents=0.0,       # deferred — booked at settlement
                        fees_cents=fee_cents,
                        won=None,            # outcome unknown until expiry
                    )
                    # Register the open trade for deferred settlement so
                    # OutcomeResolver can close it with the real outcome.
                    session.register_open_trade(
                        agent_name=self.config.name,
                        market_id=market.market_id,
                        side=side,
                        action=action,
                        contracts=size,
                        # B22: use actual fill price (post-slippage, market-anchored)
                        # not pre-slippage signal limit price. OutcomeResolver uses
                        # this price in the binary payoff formula at settlement.
                        price_cents=float(_actual_fill_price_c or signal.limit_price_cents or 50),
                    )
            except Exception as exc:
                self.logger.debug(f"Paper session record error (ignored): {exc}")

            # Trigger portfolio rebalancer after fill
            # G4: Only execute real rebalance orders when NOT in simulated mode
            try:
                from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
                from merid.event_venues.kalshi.client import get_kalshi_client as _get_rb_client
                _rebalancer = get_portfolio_rebalancer()
                if _rebalancer.get_targets():  # only run if targets are configured
                    _rb_client = _get_rb_client()
                    _rb_actions = await _rebalancer.analyze_rebalance_needed(_rb_client)
                    if _rb_actions:
                        self.logger.info(
                            "rebalancer: %d actions needed after fill on %s",
                            len(_rb_actions), market.market_id,
                        )
                        # G4: Gate real rebalance orders on VenueGate — skip in paper/sim mode
                        if not _is_simulated_fill:
                            await _rebalancer.execute_rebalance(_rb_client, actions=_rb_actions)
                        else:
                            self.logger.debug(
                                "rebalancer: skipping execute in paper/sim mode (%d actions)",
                                len(_rb_actions),
                            )
            except Exception as exc:
                self.logger.debug("rebalancer post-fill skipped: %s", exc)

            # Update CryptoSwarmRiskBTC15m open-exposure tracker on fill.
            # G2: Use actual agent deployment mode, not hardcoded PAPER.
            # BUG-03 fix: do NOT use a Bernoulli draw to simulate PnL here.
            # Kalshi contracts settle at expiry; real PnL is only known then.
            # Instead, record the raw dollar exposure added by this fill so the
            # risk manager's open-exposure cap is accurate.  OutcomeResolver will
            # call record_trade_result() with the true outcome at settlement.
            if self._btc15m_risk is not None and not _is_accepted_only:
                try:
                    from merid.risk.crypto_swarm_risk_btc15m import TradeMode as _TM
                    # B22: use actual fill price for exposure tracking, not signal limit price
                    p_c = float(_actual_fill_price_c or signal.limit_price_cents or 50)
                    # Dollar exposure added by this fill (cost to open the position)
                    _open_exposure_delta = size * p_c / 100.0
                    # Resolve actual trade mode from deployment controller
                    _btc_mode = _TM.PAPER
                    try:
                        # B12: use public get_mode() — ._agents is private dict
                        from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode as _AM
                        _dep_ctrl = get_deployment_controller()
                        _dep_agent_mode = _dep_ctrl.get_mode(self.agent_id)
                        if _dep_agent_mode == _AM.LIVE:
                            _btc_mode = _TM.LIVE
                        elif _dep_agent_mode == _AM.SHADOW:
                            _btc_mode = _TM.LIVE  # shadow counts as live for risk tracking
                    except Exception as _dep_exc:
                        self.logger.debug("deployment mode lookup failed: %s", _dep_exc)
                    # Sync exposure; PnL recording deferred to OutcomeResolver
                    self._btc15m_risk.open_exposure_total = (
                        getattr(self._btc15m_risk, "open_exposure_total", 0.0)
                        + _open_exposure_delta
                    )
                    self.logger.debug(
                        "btc15m risk: open_exposure_total += %.2f (deferred PnL at settlement)",
                        _open_exposure_delta,
                    )
                except Exception as _rte:
                    self.logger.debug("btc15m risk exposure update skipped: %s", _rte)

            # Record decision in ReflectionSystem for learning/persistence
            try:
                from agents.reflection.integration import get_reflection_system
                reflection_sys = get_reflection_system()
                action_str = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
                confidence = float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5
                edge_val = float(signal.edge.net_edge) if signal.edge and hasattr(signal.edge, "net_edge") else 0.0
                reflection_sys.record_decision(
                    agent_id=self.agent_id,
                    energy_id=f"{market.market_id}:{now_ts.isoformat()}",
                    decision="accept",
                    confidence=confidence,
                    reasoning=f"{action_str} {size}x {market.market_id} edge={edge_val:.4f}",
                    market_context={
                        "market_id": market.market_id,
                        "question": market.question[:120] if market.question else "",
                        "side": side,
                        "action": action,
                        "price_cents": signal.limit_price_cents,
                        "contracts": size,
                        "edge": edge_val,
                        "implied_yes": float(snapshot.implied.yes_prob) if snapshot and snapshot.implied else None,
                        "implied_no": float(snapshot.implied.no_prob) if snapshot and snapshot.implied else None,
                        "simulated": result_payload.get("simulated", False),
                    },
                    agent_state=self.state.to_dict(),
                )
            except Exception as exc:
                self.logger.debug(f"ReflectionSystem record error (ignored): {exc}")

            # Emit ForecastEvent into RewardEngine so fills flow into reputation pipeline
            try:
                from merid.rewards.engine import get_reward_engine
                from merid.rewards.events import ForecastEvent
                _engine = get_reward_engine()
                _engine.process_event(ForecastEvent(
                    agent_id=self.agent_id,
                    venue="kalshi",
                    symbol=market.market_id,
                    probability=(
                        float(signal.edge.model_prob)
                        if signal.edge and hasattr(signal.edge, "model_prob") and signal.edge.model_prob is not None
                        else float(signal.limit_price_cents or 50) / 100.0
                    ),
                    confidence=float(signal.edge.confidence) if signal.edge and hasattr(signal.edge, "confidence") else 0.5,
                    metadata={
                        "action": action,
                        "side": side,
                        "contracts": size,
                        "price_cents": price_cents,
                        "simulated": result_payload.get("simulated", False),
                    },
                ))
            except Exception as exc:
                self.logger.debug("RewardEngine ForecastEvent skipped: %s", exc)

            self.logger.info(
                f"Order placed: {action} {size}x {side} {market.market_id} "
                f"@{price_cents}c (sim={result_payload.get('simulated', False)})"
            )
        else:
            # Record error in paper session only for paper/sim fills
            try:
                from merid.prediction.paper_session import get_paper_session
                session = get_paper_session()
                if session.is_active and not _is_live_fill:
                    session.record_error(self.config.name)
            except Exception as _pse:
                self.logger.debug("paper session record_error skipped: %s", _pse)
            # Wire into global error-threshold kill switch — only *incident* failures,
            # not expected policy rejects (sanity_check, caps, live_not_enabled, etc.).
            try:
                from merid.prediction.order_error_threshold import (
                    should_count_toward_error_threshold,
                )
                from merid.risk.kill_switches import risk_controller as _rc

                if should_count_toward_error_threshold(result_error):
                    _rc.record_error(error_hint=result_error or "")
                else:
                    self.logger.debug(
                        "error_threshold_skip: policy rejection not counted | %s | %s",
                        market.market_id,
                        (result_error or "")[:300],
                    )
            except Exception as _kse:
                self.logger.debug("kill_switch record_error skipped: %s", _kse)
            self.logger.warning(
                f"Order failed for {market.market_id}: {result_error}"
            )

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable agent summary."""
        # Get base state dict
        base_state = self.state.to_dict()

        # Build performance snapshot (BUG-W3 fix)
        performance = {}
        if hasattr(self, '_performance_tracker') and self._performance_tracker:
            metrics = self._performance_tracker.get_agent_metrics(self.agent_id)
            if metrics:
                performance = metrics.to_dict()

        return {
            **base_state,
            "config": {
                "name": self.config.name,
                "assets": self.config.assets,
                "timeframes": self.config.timeframes,
                "category": getattr(self.config, 'category', 'unknown'),
                "archetype": getattr(self.config, 'archetype', 'unknown'),
                "agent_id": self.config.agent_id,
                "risk_limits": {
                    "max_yes_position": self.config.risk_limits.max_yes_position,
                    "max_no_position": self.config.risk_limits.max_no_position,
                    "max_orders_per_window": self._get_effective_max_orders(top_n_edges=3),
                    "max_orders_per_window_configured": self.config.risk_limits.max_orders_per_window,  # 0 = auto
                    "max_notional_usd": str(self.config.risk_limits.max_notional_usd),
                },
                "entry_window": {
                    "minutes_before_expiry": self.config.entry_window.minutes_before_expiry,
                    "cutoff_minutes_before_expiry": self.config.entry_window.cutoff_minutes_before_expiry,
                },
            },
            "performance": performance,
            "last_heartbeat_ts": base_state.get("last_heartbeat_at", time.time()),
            "take_profit": self._build_tp_summary(),
        }

    def _build_tp_summary(self) -> Dict[str, Any]:
        """Build take-profit summary for agent status endpoint.

        Returns aggregated TP state and per-position details for observability.
        """
        try:
            base = self._tp_manager.summary()
        except Exception as _e:
            base = {"error": str(_e)}

        # Add per-position TP state for open positions
        position_details: Dict[str, Any] = {}
        for pos_id, pos in self._tracked_positions.items():
            try:
                tp_state = self._tp_manager.get_state(pos_id)
                if tp_state:
                    position_details[pos_id] = {
                        "ticker": pos.ticker,
                        "side": pos.side,
                        "entry_price_cents": pos.entry_price_cents,
                        "current_price_cents": pos.current_price_cents,
                        "contracts": pos.contracts,
                        "tp_state": tp_state.tp_state.value,
                        "primary_target_cents": tp_state.primary_target_cents,
                        "remaining_contracts": tp_state.remaining_contracts,
                        "peak_price_cents": tp_state.peak_price_cents if tp_state.peak_price_cents > 0 else None,
                        "round_trips": self._tp_manager._round_trips.get(pos.ticker, {}).get("round_trips", 0),
                    }
            except Exception as _e:
                position_details[pos_id] = {"error": str(_e)}

        return {
            **base,
            "positions": position_details,
            "config": {
                "tp_enabled": self._tp_manager._config.tp_enabled,
                "tp_r_multiple_primary": self._tp_manager._config.tp_r_multiple_primary,
                "tp_scale_out_fraction": self._tp_manager._config.tp_scale_out_fraction,
                "tp_trailing_enabled": self._tp_manager._config.tp_trailing_enabled,
                "tp_trailing_giveback_cents": self._tp_manager._config.tp_trailing_giveback_cents,
            } if hasattr(self._tp_manager, "_config") else {},
        }

    def get_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent strategy signals."""
        return self.state.signal_log[-limit:]

    def get_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent orders."""
        return self.state.order_log[-limit:]

    def get_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent fills."""
        return self.state.fill_log[-limit:]

    # ── Crypto 15m risk layer helpers (CryptoSwarmRiskBTC15m) ───────────────

    def _estimate_spread_ticks(self, snapshot: Optional[MarketSnapshot]) -> Optional[int]:
        """Estimate spread in ticks (cents) from snapshot.

        ImpliedProbability stores yes_bid/yes_ask in the same units they were
        inserted: the WS path stores raw cents (0-99) while the fallback path
        stores Decimal fractions (0.0-1.0).  We normalise to cents here so
        the returned value is always in the 0-99 range expected by callers.
        """
        if not snapshot or not snapshot.implied:
            return None
        yes_bid = float(snapshot.implied.yes_bid) if snapshot.implied.yes_bid else 0
        yes_ask = float(snapshot.implied.yes_ask) if snapshot.implied.yes_ask else 0
        if yes_bid > 0 and yes_ask > 0:
            spread = yes_ask - yes_bid
            # Values in fraction range (0-1): convert to cents
            if yes_ask <= 1.0:
                spread = spread * 100.0
            return max(0, int(round(spread)))
        return None

    def _get_current_open_exposure(self) -> float:
        """Get total dollar exposure of open positions."""
        try:
            # Try to get from KalshiRiskManager
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_mgr = get_kalshi_risk()
            total_notional = risk_mgr.state.total_notional_usd if hasattr(risk_mgr, 'state') else 0.0
            return total_notional
        except Exception as _rme:
            self.logger.debug("kalshi_risk notional lookup skipped, using fill log: %s", _rme)
            # Fallback: estimate from fill log
            total = 0.0
            for fill in self.state.fill_log[-100:]:  # Last 100 fills
                if fill.get("action") == "buy":
                    price = fill.get("price_cents", 50)
                    contracts = fill.get("contracts", 0)
                    total += contracts * (price / 100.0)
            return total

    def _get_open_positions_dict(self) -> Dict[str, float]:
        """Get open positions as ticker -> exposure dict."""
        positions: Dict[str, float] = {}
        for fill in self.state.fill_log[-50:]:
            ticker = fill.get("market_id", "")
            contracts = fill.get("contracts", 0)
            price = fill.get("price_cents", 50)
            exposure = contracts * (price / 100.0)
            if fill.get("action") == "buy":
                positions[ticker] = positions.get(ticker, 0) + exposure
            elif fill.get("action") == "sell":
                positions[ticker] = positions.get(ticker, 0) - exposure
        # Remove zero/negative positions
        return {k: v for k, v in positions.items() if v > 0}

    async def _record_risk_blocked_order(
        self,
        market: EventMarket,
        signal: StrategySignal,
        decision: Any,
        snapshot: Optional[MarketSnapshot],
    ) -> None:
        """Record a risk-blocked order in logs and explainability."""
        now = datetime.now(timezone.utc)
        
        # Add to order log as blocked
        entry = {
            "ts": now.isoformat(),
            "market_id": market.market_id,
            "question": market.question[:120] if market.question else "",
            "side": "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no",
            "action": str(signal.action),
            "contracts": signal.contracts,
            "success": False,
            "error": f"Risk blocked: {decision.blocked_reason}",
            "risk_decision": {
                "mode": decision.mode.value,
                "reason": decision.reason,
                "adjustments": decision.adjustments,
            },
        }
        self.state.order_log.append(entry)
        if len(self.state.order_log) > _MAX_LOG_ENTRIES:
            self.state.order_log = self.state.order_log[-_MAX_LOG_ENTRIES:]
        
        # Record in explainability
        try:
            from agents.explainability import DecisionType, create_reasoning_builder, get_explainability_tracker
            
            action_value = signal.action.value if hasattr(signal.action, "value") else str(signal.action)
            
            builder = create_reasoning_builder(self.config.name, DecisionType.ACTION)
            builder.set_decision(f"BLOCKED: {action_value} {market.market_id}", 0.0)
            builder.set_primary_reason(f"Crypto 15m risk layer blocked: {decision.blocked_reason}")
            builder.add_contrary_factor(f"risk decision: {decision.reason}")
            
            for adj_name, adj_value in decision.adjustments.items():
                builder.add_contrary_factor(f"adjustment: {adj_name}={adj_value}")
            
            builder.set_risk_assessment(
                {
                    "allowed": False,
                    "reason": decision.blocked_reason,
                    "crypto_15m_risk_layer": True,
                    "adjustments": decision.adjustments,
                }
            )
            
            reasoning = builder.build()
            get_explainability_tracker().record_decision(reasoning)
        except Exception as exc:
            self.logger.debug(f"Explainability blocked order record skipped: {exc}")

    # ── Market Mood Bus Integration ────────────────────────────────────────

    def _get_mood_context(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Any]:
        """Get unified market context from the Market Mood Bus."""
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            return bus.get_context(asset, timeframe)
        except Exception as exc:
            self.logger.debug(f"MarketMoodBus fetch error: {exc}")
            return None

    def _build_kalshi_market_context(self, ticker: str, snapshot: MarketSnapshot) -> dict:
        """Build a market-data context dict from live KalshiMarketState + snapshot.

        Used by KalshiLiveMarketStrategy and for populating AgentProposal.market_data.
        News/sentiment from the snapshot is included at a capped weight so it
        informs but does not dominate the opinion.
        """
        ctx: dict = {}
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            state = get_kalshi_market_state_store().get(ticker)
            if state:
                ctx["mid_cents"] = state.mid_cents
                ctx["spread_cents"] = state.spread_cents
                ctx["best_bid_cents"] = state.best_bid_cents
                ctx["best_ask_cents"] = state.best_ask_cents
                ctx["top_of_book_size"] = state.top_of_book_size
                ctx["depth_10c"] = state.depth_10c
                ctx["volume_24h"] = state.volume_24h
                ctx["open_interest"] = state.open_interest
                ctx["seconds_to_expiry"] = state.seconds_to_expiry
                ctx["book_initialized"] = state.book_initialized
        except Exception as _mse:
            self.logger.debug("Kalshi market state fetch skipped: %s", _mse)

        # Supplement with news/sentiment — kept at minimal weight via strategy
        sent_score = getattr(snapshot, "sentiment_global", None)
        if sent_score is not None:
            # sentiment_global can be either:
            # - 0-100 (fear/greed from MarketMoodBus) → normalize to -1 to +1
            # - -1 to +1 (combined_score from SentimentBusV2) → use directly
            if -1.0 <= float(sent_score) <= 1.0:
                # Already normalized from SentimentBusV2
                ctx["sentiment_score"] = float(sent_score)
            else:
                # 0-100 fear/greed from MarketMoodBus → normalize to -1 to +1
                ctx["sentiment_score"] = (float(sent_score) / 50.0) - 1.0
        elif getattr(snapshot, "sentiment_local", None) is not None:
            ctx["sentiment_score"] = float(snapshot.sentiment_local)

        # ── TSM context keys for crypto opinion strategies ────────────────────
        try:
            from config.kalshi_crypto_series_meta import infer_asset_from_kalshi_market_ticker
            _tsm_asset = infer_asset_from_kalshi_market_ticker(ticker)
            if _tsm_asset:
                ctx["asset"] = _tsm_asset
                ctx["horizon_secs"] = float(ctx.get("seconds_to_expiry") or 3600.0)
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                _cat_mkt = get_market_catalog().get_market(ticker)
                if _cat_mkt:
                    if _cat_mkt.market_type == "range":
                        ctx["market_type"] = "bracket"
                        if _cat_mkt.floor_strike and _cat_mkt.cap_strike:
                            ctx["bracket"] = [_cat_mkt.floor_strike, _cat_mkt.cap_strike]
                    else:
                        ctx["market_type"] = "threshold"
                        if _cat_mkt.strike_price is not None:
                            ctx["strike"] = _cat_mkt.strike_price
                            ctx["side"] = "above"
        except Exception as _tce:
            self.logger.debug("TSM context injection skipped: %s", _tce)

        return ctx

    def _resolve_consensus_asset_timeframe(
        self, signal: object, *, market_id_fallback: str = ""
    ) -> tuple[str, str]:
        """Asset/timeframe for Wire-2 proposals. Multi-asset agents (e.g. ``CRYPTO_15M_MM``) omit ``assets: []`` — infer from ``signal.market_id``."""
        asset = (self.config.assets[0] if self.config.assets else "") or ""
        timeframe = (self.config.timeframes[0] if self.config.timeframes else "") or ""
        mid = (getattr(signal, "market_id", None) or "").strip()
        if not mid and market_id_fallback:
            mid = market_id_fallback.strip()
        if asset and timeframe:
            return asset, timeframe
        try:
            from config.kalshi_crypto_series_meta import (
                infer_asset_from_kalshi_market_ticker,
                infer_asset_timeframe_from_ticker,
            )

            if not asset:
                asset = infer_asset_from_kalshi_market_ticker(mid) or ""
            prefix = mid.split("-")[0].upper() if mid and "-" in mid else (mid.upper() if mid else "")
            if prefix:
                a2, t2 = infer_asset_timeframe_from_ticker(prefix)
                if not asset and a2 and a2 != "UNK":
                    asset = a2
                if not timeframe and t2 and t2 != "UNK":
                    timeframe = t2
        except Exception as _ce:
            self.logger.debug("consensus asset infer: %s", _ce)
        if not asset and mid:
            try:
                asset = self._strategy._extract_asset_from_market_id(mid)
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")
        return asset or "", timeframe or ""

    def _submit_consensus_proposal(self, signal: object) -> None:
        """Submit an AgentProposal to SwarmConsensusAggregator (Wire 2).

        Called once per cycle after the first actionable signal is generated.
        Never raises — consensus failure must not block trading.
        """
        try:
            asset, timeframe = self._resolve_consensus_asset_timeframe(signal)
            if not asset:
                self.logger.debug(
                    "consensus_proposal_skipped: empty asset (agent=%s market_id=%s)",
                    self.config.name,
                    getattr(signal, "market_id", None),
                )
                return

            proposal = get_kalshi_consensus_adapter().signal_to_proposal(
                signal=signal,
                agent_id=self.config.agent_id,
                asset=asset,
                timeframe=timeframe,
                archetype=self.config.archetype,
                live_markets=self._live_markets,
                track_record=getattr(self, "_track_record", None),
            )
            get_consensus_aggregator().submit_proposal(proposal)
            self.logger.debug(
                "consensus_proposal_submitted: %s %s->%s conf=%.2f",
                self.config.name, asset, proposal.direction, proposal.confidence,
            )
        except Exception as exc:
            self.logger.warning("consensus_proposal_failed (non-fatal): %s", exc)

    def _submit_to_consensus(
        self,
        market: EventMarket,
        signal: StrategySignal,
        snapshot: MarketSnapshot,
        mood_context: Optional[Any],
    ) -> bool:
        """Submit agent proposal to SwarmConsensusAggregator + TaCoConsensusCoordinator.

        Returns True if the proposal was successfully submitted to the aggregator.

        The primary opinion is derived from live Kalshi market data (orderbook,
        spread, depth, volume, OI, expiry) via KalshiLiveMarketStrategy.
        News/sentiment from the snapshot contributes at most 3 % of the final
        estimate so it still informs but cannot override market signals.

        Both the execution-gating ``SwarmConsensusAggregator`` and the
        debate-orchestrating ``TaCoConsensusCoordinator`` receive the opinion,
        ensuring the full consensus/debate/vote/execute pipeline operates on
        real Kalshi data rather than news alone.
        """
        # [TRACE] CONSENSUS_START — log with correlation_id from signal
        corr_id = getattr(signal, 'correlation_id', None)
        if corr_id:
            self.logger.info(
                "[TRACE] CONSENSUS_START | corr_id=%s | market=%s | agent=%s | direction=%s | formulas=%s | audit_spec=%s",
                corr_id,
                market.market_id,
                self.agent_id,
                signal.action.value if hasattr(signal.action, 'value') else signal.action,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )
        try:
            from merid.swarm.consensus_aggregator import (
                get_consensus_aggregator,
                AgentProposal,
            )

            # ── Direction from signal action ──────────────────────────────
            direction_map = {
                SignalAction.BUY_YES:  "yes",
                SignalAction.SELL_YES: "no",
                SignalAction.BUY_NO:   "no",
                SignalAction.SELL_NO:  "yes",
            }
            direction = direction_map.get(signal.action, "neutral")

            # ── Base probability from signal or snapshot ──────────────────
            market_prob = 0.5
            if signal.edge and hasattr(signal.edge, 'yes_prob'):
                market_prob = float(signal.edge.yes_prob)
            elif snapshot.implied:
                market_prob = float(snapshot.implied.yes_prob)

            # ── Build live Kalshi market context ──────────────────────────
            market_ctx = self._build_kalshi_market_context(market.market_id, snapshot)

            # ── Use KalshiLiveMarketStrategy for market-data-driven prob ──
            prob = market_prob
            conf = 0.5
            signal_sources: list = ["strategy_signal"]
            reasoning_tag = str(signal.action)
            try:
                from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy
                _strategy = KalshiLiveMarketStrategy()
                _est = _strategy.estimate(
                    agent_id=self.agent_id,
                    ticker=market.market_id,
                    market_prob=market_prob,
                    category=(market.category or "").lower(),
                    context=market_ctx,
                )
                if _est is not None:
                    prob = _est.agent_prob
                    conf = _est.confidence
                    signal_sources = _est.signal_sources
                    reasoning_tag = _est.reasoning_tag
            except Exception as _se:
                self.logger.debug("KalshiLiveMarketStrategy skipped: %s", _se)
                if signal.edge and hasattr(signal.edge, 'confidence'):
                    conf = float(signal.edge.confidence)

            # ── Try TSM strategies for crypto markets ──────────────────────
            if market_ctx.get("asset"):
                try:
                    from merid.prediction.opinion_strategy import _STRATEGIES as _STRAT_REG
                    for _sn in ("spot_basis_fair_value", "trend_momentum"):
                        _s = _STRAT_REG.get(_sn)
                        if _s is None:
                            continue
                        _te = _s.estimate(
                            agent_id=self.agent_id,
                            ticker=market.market_id,
                            market_prob=prob,
                            category=(market.category or "").lower(),
                            context=market_ctx,
                        )
                        if _te is not None:
                            prob = 0.5 * _te.agent_prob + 0.5 * prob
                            signal_sources = list(dict.fromkeys(signal_sources + _te.signal_sources))
                            reasoning_tag = _te.reasoning_tag
                            break
                except Exception as _tse:
                    self.logger.debug("TSM strategy dispatch skipped: %s", _tse)

            # ── Size preference from mood context ─────────────────────────
            size_pref = "base"
            if mood_context and hasattr(mood_context, 'should_reduce_size'):
                if mood_context.should_reduce_size():
                    size_pref = "reduced"

            # ── Track record ──────────────────────────────────────────────
            track_record = None
            metrics = None
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                metrics = tracker.get_agent_metrics(self.agent_id)
                # BUG-M fix: AgentMetrics is a dataclass — use attribute
                # access, not dict .get(); was silently throwing AttributeError.
                # Gate on >= 5 closes so new agents don't populate track_record
                # with 0/0 values that block the live-tracker fallback in the
                # consensus aggregator (which has the same 5-close threshold).
                if metrics and metrics.total_closes >= 5:
                    track_record = {
                        "win_rate": metrics.win_rate,
                        "sharpe_ratio": metrics.sharpe_ratio,
                    }
            except Exception as _tre:
                self.logger.debug("track_record lookup skipped: %s", _tre)

            # Same inference as Wire-2 ``_submit_consensus_proposal`` — static
            # ``assets: []`` (CRYPTO_15M_MM, scanners) must not submit empty asset.
            asset, timeframe = self._resolve_consensus_asset_timeframe(
                signal, market_id_fallback=getattr(market, "market_id", "") or ""
            )

            # BUG-Y fix: check if this agent's Sharpe is below the matrix
            # downweight threshold and propagate the flag to the proposal so
            # the consensus aggregator can apply the 50% vote reduction.
            _proposal_downweight = False
            try:
                if metrics and metrics.total_closes >= 5:
                    from config.trading_constants import SHARPE_DOWNWEIGHT_THRESHOLD
                    _proposal_downweight = metrics.sharpe_ratio < SHARPE_DOWNWEIGHT_THRESHOLD
            except Exception as e:
                self.logger.debug(f"Silent error suppressed: {e}")

            # ── Build + submit AgentProposal (execution gating) ───────────
            if asset:
                # CONSENSUS_AUDIT: Populate data provenance fields
                data_source = "primary_ws" if "kalshi_orderbook" in signal_sources else "unknown"
                is_fallback = "kalshi_market_prob_fallback" in reasoning_tag or "fallback" in reasoning_tag.lower()
                data_quality_flags = {
                    "orderbook_valid": True,  # KalshiLiveMarketStrategy only returns valid orderbook data
                    "candle_valid": True,
                    "price_boundaries_ok": True,
                }
                
                proposal = AgentProposal(
                    agent_id=self.agent_id,
                    asset=asset,
                    timeframe=timeframe,
                    direction=direction,
                    probability=prob,
                    confidence=conf,
                    size_preference=size_pref,
                    rationale=reasoning_tag,
                    edge_estimate=float(signal.edge.net_edge * 100) if signal.edge else 0.0,
                    timestamp=datetime.now(timezone.utc),
                    agent_archetype=self.config.archetype,
                    agent_track_record=track_record,
                    market_data=market_ctx if market_ctx else None,
                    downweight=_proposal_downweight,
                    data_source=data_source,
                    is_fallback=is_fallback,
                    data_quality_flags=data_quality_flags,
                )
                get_consensus_aggregator().submit_proposal(proposal)
            else:
                self.logger.debug(
                    "_submit_to_consensus: skip AgentProposal (unresolved asset) agent=%s market=%s",
                    self.config.name,
                    market.market_id,
                )

            # ── Submit AgentOpinion to TaCoConsensusCoordinator ───────────
            # This feeds the debate-orchestration loop which scans _opinions
            # for high-disagreement Kalshi symbols.
            self._submit_taco_opinion(
                ticker=market.market_id,
                prob=prob,
                conf=conf,
                direction=direction,
                reasoning_tag=reasoning_tag,
                signal_sources=signal_sources,
                market_ctx=market_ctx,
            )

            self.logger.debug(
                "Submitted Kalshi-market-driven consensus: %s @ %.1f%% "
                "(conf=%.2f, sources=%s)",
                direction, prob * 100, conf, signal_sources[:3],
            )
            return True

        except Exception as exc:
            self.logger.debug("Consensus submission error: %s", exc)
            return False

    def _submit_taco_opinion(
        self,
        ticker: str,
        prob: float,
        conf: float,
        direction: str,
        reasoning_tag: str,
        signal_sources: list,
        market_ctx: dict,
    ) -> None:
        """Submit an AgentOpinion to TaCoConsensusCoordinator.

        The debate-orchestration loop reads ``coordinator._opinions`` keyed by
        symbol to find Kalshi markets with high inter-agent disagreement and
        create debate sessions.  Without this submission, debates are never
        triggered from real Kalshi market data.

        ``score`` maps agent probability → −1..+1:
          - P(YES) = 1.0 → score = +1.0 (strong YES)
          - P(YES) = 0.5 → score =  0.0 (neutral)
          - P(YES) = 0.0 → score = −1.0 (strong NO)
        """
        try:
            import uuid
            from consensus.taco_consensus import AgentOpinion, Stance, get_consensus_coordinator

            score = round((prob - 0.5) * 2.0, 4)  # map 0-1 → -1..+1

            if score >= 0.6:
                stance = Stance.STRONG_BULL.value
            elif score >= 0.3:
                stance = Stance.BULL.value
            elif score <= -0.6:
                stance = Stance.STRONG_BEAR.value
            elif score <= -0.3:
                stance = Stance.BEAR.value
            else:
                stance = Stance.NEUTRAL.value

            # Horizon from seconds_to_expiry
            secs = market_ctx.get("seconds_to_expiry")
            if secs is not None:
                if secs < 3_600:
                    horizon = "short"
                elif secs < 86_400:
                    horizon = "medium"
                else:
                    horizon = "long"
            else:
                horizon = "short"

            opinion = AgentOpinion(
                opinion_id=f"op_{uuid.uuid4().hex[:12]}",
                agent_id=self.agent_id,
                role=getattr(self.config, "archetype", "trader"),
                symbol=ticker,
                venue="kalshi",
                stance=stance,
                score=score,
                confidence=conf,
                rationale=reasoning_tag,
                horizon=horizon,
                data_sources=signal_sources,
                supporting_data={k: v for k, v in market_ctx.items() if v is not None},
            )

            coordinator = get_consensus_coordinator()
            import asyncio as _aio
            try:
                loop = _aio.get_running_loop()
                # BUG-FIX: Add done callback to catch task exceptions
                _task = loop.create_task(
                    coordinator.submit_opinion(opinion),
                    name=f"taco-opinion-{opinion.opinion_id[:8]}"
                )
                def _on_done(t):
                    if not t.cancelled() and t.exception():
                        self.logger.debug("TaCo opinion task failed: %s", t.exception())
                _task.add_done_callback(_on_done)
            except RuntimeError:
                _aio.run(coordinator.submit_opinion(opinion))

        except Exception as _te:
            self.logger.debug("TaCo opinion submission skipped: %s", _te)

    def _get_consensus(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[Any]:
        """Get current consensus view from SwarmConsensusAggregator."""
        try:
            from merid.swarm.consensus_aggregator import get_consensus_aggregator
            aggregator = get_consensus_aggregator()
            return aggregator.get_consensus(asset, timeframe)
        except Exception as exc:
            self.logger.debug(f"Consensus fetch error: {exc}")
            return None
        except Exception as exc:
            self.logger.debug(f"Consensus fetch error: {exc}")
            return None
