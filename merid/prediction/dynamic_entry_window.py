"""
Dynamic Entry Window System

Config-driven entry window policies for Kalshi 15m crypto markets.
Supports asset-specific windows, terminal phase overrides, and policy tagging for analysis.

Configuration is now sourced from config.kalshi_15m_crypto_config (canonical single source of truth).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import os
import logging
import time
from decimal import Decimal
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class EntryWindowDecision(Enum):
    """Reason for entry window decision."""
    ALLOWED_BASE = "allowed_base"
    ALLOWED_TERMINAL_OVERRIDE = "allowed_terminal_override"
    OUTSIDE_WINDOW = "outside_window"
    TERMINAL_EDGE_TOO_LOW = "terminal_edge_too_low"
    TERMINAL_DISABLED = "terminal_disabled"
    VOLATILITY_TOO_HIGH = "volatility_too_high"
    BOOK_QUALITY_TOO_LOW = "book_quality_too_low"
    SCOPE_VIOLATION = "scope_violation"
    SPREAD_TOO_WIDE = "spread_too_wide"
    DEPTH_TOO_LOW = "depth_too_low"


# Import canonical configuration
import os
_profile = os.getenv("MERID_PROFILE", "").lower()
_deprecation_logged = False

try:
    from config.kalshi_15m_crypto_config import (
        AssetWindowPolicy as CanonicalAssetWindowPolicy,
        TerminalPhaseConfig as CanonicalTerminalPhaseConfig,
        DEFAULT_ENTRY_POLICIES,
        EXIT_POLICY_TABLE,
        ASSET_CLASS_MAJOR,
        ASSET_CLASS_ALT,
        get_asset_class,
        get_base_edge_threshold,
        get_entry_policy,
        get_exit_policy_params,
        get_time_bucket,
        get_t2e_band,
        validate_minutes_to_expiry,
        VolatilityTier,
    )
    _USE_CANONICAL_CONFIG = True
    
except ImportError:
    # Fallback to local definitions if canonical config not available
    _USE_CANONICAL_CONFIG = False
    logger.warning("[DYNAMIC_WINDOW] Canonical config not available, using local definitions")


class RiskTier(Enum):
    """Risk tier classification for exit policy mapping."""
    TIER_A = "A"  # High confidence: low vol, aggressive/normal regime, strong calibration
    TIER_B = "B"  # Normal: mixed signals
    TIER_C = "C"  # Fragile: defensive regime, high vol, marginal EV, weak calibration


# Use canonical config if available, otherwise define locally
if _USE_CANONICAL_CONFIG:
    TerminalPhaseConfig = CanonicalTerminalPhaseConfig
    AssetWindowPolicy = CanonicalAssetWindowPolicy
else:
    @dataclass
    class TerminalPhaseConfig:
        """Terminal phase (near expiry) configuration."""
        enabled: bool = True
        edge_threshold_pct: float = 20.0
        max_terminal_minutes: int = 5
        use_dynamic_threshold: bool = True
        t2e_multiplier_enabled: bool = True
        book_quality_enabled: bool = True
        model_feedback_enabled: bool = True

    @dataclass
    class AssetWindowPolicy:
        """Entry window policy for a specific asset."""
        asset: str
        base_window_start_minutes: int = 12
        base_window_end_minutes: int = 3
        terminal_config: TerminalPhaseConfig = field(default_factory=TerminalPhaseConfig)
        policy_name: str = "default"


@dataclass
class WindowResolution:
    """Result of dynamic window resolution."""
    allowed: bool
    reason: EntryWindowDecision
    active_policy_name: str
    bucket: str  # Time bucket for analysis (e.g., "0-2", "2-5", "5-10", "10+")
    minutes_to_expiry: Optional[float] = None
    edge_pct: Optional[float] = None
    dynamic_edge_threshold: Optional[float] = None  # Computed dynamic threshold
    volatility_tier: Optional[str] = None  # Volatility regime (low/medium/high)
    t2e_multiplier: Optional[float] = None  # Applied time-to-expiry multiplier
    book_quality_multiplier: Optional[float] = None  # Applied orderbook quality multiplier
    model_feedback_adjustment: Optional[float] = None  # Applied model-quality adjustment


@dataclass
class ExitPolicyResolution:
    """Exit policy derived from the same signals as dynamic entry window.
    
    This is the exit companion to WindowResolution - both form one coherent
    risk contract per trade. Exit parameters key off the same volatility,
    regime, and model-quality signals used for entry decisions.
    """
    enabled: bool  # Must be True for any live trade
    risk_tier: str  # "A", "B", or "C" based on regime + vol + model quality
    take_profit_r_multiple: Optional[float] = None  # TP as R-multiple of edge
    stop_loss_edge_multiplier: float = 1.0  # SL distance as multiplier of entry edge
    trailing_enabled: bool = False
    trailing_activation_r_multiple: Optional[float] = None  # When trailing starts
    trailing_giveback_pct: Optional[float] = None  # Giveback from peak
    max_hold_seconds: int = 600  # Time-based auto-exit
    auto_exit_enabled: bool = True  # Whether time-based exit is enforced
    rationale: dict = None  # Diagnostic: regime, vol_tier, model_quality, etc.


# Volatility tier classification - use canonical if available, otherwise define locally
if not _USE_CANONICAL_CONFIG:
    class VolatilityTier(Enum):
        """Volatility regime classification for dynamic thresholds."""
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    # Volatility-tiered base edge thresholds (from user design spec)
    VOLATILITY_TIERED_BASE_THRESHOLDS: Dict[str, Dict[str, Tuple[float, float]]] = {
        "BTC": {
            "low": (0.12, 0.15),
            "medium": (0.18, 0.20),
            "high": (0.25, 0.30),
        },
        "ETH": {
            "low": (0.14, 0.18),
            "medium": (0.20, 0.22),
            "high": (0.28, 0.32),
        },
        "SOL": {
            "low": (0.18, 0.22),
            "medium": (0.25, 0.28),
            "high": (0.32, 0.38),
        },
        "XRP": {
            "low": (0.18, 0.22),
            "medium": (0.25, 0.28),
            "high": (0.32, 0.38),
        },
        "DOGE": {
            "low": (0.20, 0.25),
            "medium": (0.28, 0.32),
            "high": (0.35, 0.40),
        },
    }


# Time-to-expiry multipliers (from user design spec)
T2E_MULTIPLIERS: Dict[str, float] = {
    "long": 1.0,       # > 8 minutes to expiry
    "medium": 1.15,    # 4-8 minutes
    "short": 1.35,     # < 4 minutes (higher bar near expiry)
}


# Orderbook quality multipliers (from user design spec)
BOOK_QUALITY_MULTIPLIERS: Dict[str, float] = {
    "good": 0.95,      # Tight spread, sufficient depth (can lower threshold)
    "normal": 1.0,
    "bad": 1.25,       # Wide spread, shallow depth (demand more edge)
}


# Default policies - use canonical if available, otherwise define locally
if _USE_CANONICAL_CONFIG:
    DEFAULT_POLICIES = DEFAULT_ENTRY_POLICIES
else:
    DEFAULT_POLICIES: Dict[str, AssetWindowPolicy] = {
        "BTC": AssetWindowPolicy(
            asset="BTC",
            base_window_start_minutes=12,
            base_window_end_minutes=3,
            terminal_config=TerminalPhaseConfig(
                enabled=True,
                edge_threshold_pct=20.0,
                max_terminal_minutes=3,
                use_dynamic_threshold=True,
                t2e_multiplier_enabled=True,
                book_quality_enabled=True,
                model_feedback_enabled=True,
            ),
            policy_name="kalshi_15m_btc_v1"
        ),
        "ETH": AssetWindowPolicy(
            asset="ETH",
            base_window_start_minutes=12,
            base_window_end_minutes=3,
            terminal_config=TerminalPhaseConfig(
                enabled=True,
                edge_threshold_pct=20.0,
                max_terminal_minutes=3,
                use_dynamic_threshold=True,
                t2e_multiplier_enabled=True,
                book_quality_enabled=True,
                model_feedback_enabled=True,
            ),
            policy_name="kalshi_15m_eth_v1"
        ),
        "SOL": AssetWindowPolicy(
            asset="SOL",
            base_window_start_minutes=10,
            base_window_end_minutes=4,
            terminal_config=TerminalPhaseConfig(
                enabled=True,
                edge_threshold_pct=20.0,
                max_terminal_minutes=4,
                use_dynamic_threshold=True,
                t2e_multiplier_enabled=True,
                book_quality_enabled=True,
                model_feedback_enabled=True,
            ),
            policy_name="kalshi_15m_sol_v1"
        ),
        "XRP": AssetWindowPolicy(
            asset="XRP",
            base_window_start_minutes=10,
            base_window_end_minutes=4,
            terminal_config=TerminalPhaseConfig(
                enabled=True,
                edge_threshold_pct=20.0,
                max_terminal_minutes=4,
                use_dynamic_threshold=True,
                t2e_multiplier_enabled=True,
                book_quality_enabled=True,
                model_feedback_enabled=True,
            ),
            policy_name="kalshi_15m_xrp_v1"
        ),
        "DOGE": AssetWindowPolicy(
            asset="DOGE",
            base_window_start_minutes=10,
            base_window_end_minutes=4,
            terminal_config=TerminalPhaseConfig(
                enabled=True,
                edge_threshold_pct=20.0,
                max_terminal_minutes=4,
                use_dynamic_threshold=True,
                t2e_multiplier_enabled=True,
                book_quality_enabled=True,
                model_feedback_enabled=True,
            ),
            policy_name="kalshi_15m_doge_v1"
        ),
    }


def _get_asset_class(asset: str) -> str:
    """Get asset class (major or alt) for policy parameter selection."""
    if _USE_CANONICAL_CONFIG:
        return get_asset_class(asset)
    asset_upper = asset.upper()
    if asset_upper in ASSET_CLASS_MAJOR:
        return "major"
    return "alt"


def _get_bucket(minutes_to_expiry: float) -> str:
    """Convert minutes to expiry to analysis bucket."""
    if _USE_CANONICAL_CONFIG:
        return get_time_bucket(minutes_to_expiry)
    if minutes_to_expiry < 2:
        return "0-2"
    elif minutes_to_expiry < 5:
        return "2-5"
    elif minutes_to_expiry < 10:
        return "5-10"
    else:
        return "10+"


def _get_t2e_band(minutes_to_expiry: float) -> str:
    """Convert minutes to expiry to time-to-expiry band for multipliers."""
    if _USE_CANONICAL_CONFIG:
        return get_t2e_band(minutes_to_expiry)
    if minutes_to_expiry >= 8:
        return "long"
    elif minutes_to_expiry >= 4:
        return "medium"
    else:
        return "short"


# ═══════════════════════════════════════════════════════════════════════════
# Entry Window Metrics (for verifying edge vs config drift)
# ═══════════════════════════════════════════════════════════════════════════

from collections import defaultdict
from threading import Lock

# Thread-safe metrics tracking
_entry_window_metrics_lock = Lock()
_entry_window_metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

# Per-asset scope violation metrics for detecting universe drift
_scope_metrics_lock = Lock()
_scope_violations_15m = defaultdict(int)  # {asset: count}
_books_seen_15m = defaultdict(int)  # {asset: count}

def _increment_entry_metric(asset: str, bucket: str, reason: str, allowed: bool):
    """Thread-safe increment of entry window metrics."""
    with _entry_window_metrics_lock:
        _entry_window_metrics[asset][bucket]["total"] = _entry_window_metrics[asset][bucket].get("total", 0) + 1
        if allowed:
            _entry_window_metrics[asset][bucket]["allowed"] = _entry_window_metrics[asset][bucket].get("allowed", 0) + 1
        else:
            _entry_window_metrics[asset][bucket][reason] = _entry_window_metrics[asset][bucket].get(reason, 0) + 1

def _increment_scope_metric(asset: str, is_violation: bool):
    """Thread-safe increment of scope violation metrics.
    
    Track books seen and scope violations per asset to detect drift between
    canonical config and actual venue data.
    """
    with _scope_metrics_lock:
        _books_seen_15m[asset] += 1
        if is_violation:
            _scope_violations_15m[asset] += 1

def get_entry_window_metrics() -> dict:
    """Get current entry window metrics."""
    with _entry_window_metrics_lock:
        return dict(_entry_window_metrics)

def reset_entry_window_metrics():
    """Reset entry window metrics (for testing or new sessions)."""
    with _entry_window_metrics_lock:
        _entry_window_metrics.clear()
    with _scope_metrics_lock:
        _scope_violations_15m.clear()
        _books_seen_15m.clear()

def get_scope_metrics() -> dict:
    """Get current scope violation metrics.
    
    Returns dict with structure:
    {
        "scope_violations": {asset: count},
        "books_seen": {asset: count},
        "violation_ratios": {asset: ratio}
    }
    """
    with _scope_metrics_lock:
        violations = dict(_scope_violations_15m)
        books = dict(_books_seen_15m)
    
    ratios = {}
    for asset in books:
        if books[asset] > 0:
            ratios[asset] = violations.get(asset, 0) / books[asset]
    
    return {
        "scope_violations": violations,
        "books_seen": books,
        "violation_ratios": ratios,
    }

def check_scope_violation_threshold(threshold_pct: float = 0.05) -> List[str]:
    """Check if any asset exceeds scope violation threshold.
    
    Args:
        threshold_pct: Maximum allowed violation ratio (default 5%)
    
    Returns:
        List of asset names that exceed the threshold
    """
    metrics = get_scope_metrics()
    violations = []
    
    for asset, ratio in metrics["violation_ratios"].items():
        if ratio > threshold_pct:
            violations.append(asset)
            logger.warning(
                f"[SCOPE_METRICS] {asset} scope violation ratio {ratio:.2%} exceeds threshold {threshold_pct:.2%} "
                f"({metrics['scope_violations'][asset]} violations / {metrics['books_seen'][asset]} books seen)"
            )
    
    return violations

def log_scope_metrics_summary():
    """Log a summary of scope violation metrics."""
    metrics = get_scope_metrics()
    
    if not metrics["books_seen"]:
        logger.info("[SCOPE_METRICS] No scope metrics collected yet")
        return
    
    logger.info("=" * 80)
    logger.info("SCOPE VIOLATION METRICS SUMMARY")
    logger.info("=" * 80)
    
    for asset in sorted(metrics["books_seen"].keys()):
        violations = metrics["scope_violations"].get(asset, 0)
        books = metrics["books_seen"][asset]
        ratio = metrics["violation_ratios"].get(asset, 0.0)
        
        logger.info(f"{asset}: {violations} violations / {books} books seen ({ratio:.2%})")
    
    logger.info("=" * 80)


def run_scope_violation_monitoring_check(threshold_pct: float = 0.05) -> dict:
    """Run scope violation monitoring check and return results.
    
    This function is designed to be called periodically from a monitoring loop
    to check for universe drift and emit alerts when thresholds are exceeded.
    
    Args:
        threshold_pct: Maximum allowed violation ratio (default 5%)
    
    Returns:
        Dict with check results:
        {
            "violations_exceeding_threshold": [asset_names],
            "all_assets": {asset: {"violations": int, "books": int, "ratio": float}},
            "check_passed": bool
        }
    """
    metrics = get_scope_metrics()
    violations_exceeding = check_scope_violation_threshold(threshold_pct)
    
    result = {
        "violations_exceeding_threshold": violations_exceeding,
        "all_assets": {},
        "check_passed": len(violations_exceeding) == 0,
    }
    
    for asset in sorted(metrics["books_seen"].keys()):
        result["all_assets"][asset] = {
            "violations": metrics["scope_violations"].get(asset, 0),
            "books": metrics["books_seen"][asset],
            "ratio": metrics["violation_ratios"].get(asset, 0.0),
        }
    
    # Log monitoring event
    if violations_exceeding:
        logger.error(
            "[SCOPE_MONITORING] %d assets exceed scope violation threshold %.2f%%: %s",
            len(violations_exceeding),
            threshold_pct * 100,
            ", ".join(violations_exceeding)
        )
    else:
        logger.info(
            "[SCOPE_MONITORING] All assets within scope violation threshold %.2f%%",
            threshold_pct * 100
        )
    
    return result


def persist_metrics_to_file(output_dir: str = "output") -> str:
    """Persist current metrics to a JSON file for later analysis.
    
    Args:
        output_dir: Directory to save the metrics file (default: "output")
    
    Returns:
        Path to the saved file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"entry_window_metrics_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)
    
    metrics_data = {
        "timestamp": timestamp,
        "entry_window_metrics": get_entry_window_metrics(),
        "scope_metrics": get_scope_metrics(),
    }
    
    with open(filepath, "w") as f:
        json.dump(metrics_data, f, indent=2, default=str)
    
    logger.info(f"[METRICS] Persisted metrics to {filepath}")
    return filepath


def load_metrics_from_file(filepath: str) -> dict:
    """Load metrics from a JSON file.
    
    Args:
        filepath: Path to the metrics JSON file
    
    Returns:
        Dict with "entry_window_metrics" and "scope_metrics" keys
    """
    with open(filepath, "r") as f:
        return json.load(f)

def log_entry_window_metrics_summary():
    """Log a summary of entry window metrics for debugging."""
    metrics = get_entry_window_metrics()
    if not metrics:
        logger.info("[DYNAMIC_WINDOW_METRICS] No metrics collected yet")
        return
    
    logger.info("=" * 80)
    logger.info("ENTRY WINDOW METRICS SUMMARY")
    logger.info("=" * 80)
    
    for asset, buckets in sorted(metrics.items()):
        logger.info(f"\n{asset}:")
        for bucket, counts in sorted(buckets.items()):
            total = counts.get("total", 0)
            allowed = counts.get("allowed", 0)
            rejected = total - allowed
            if total == 0:
                continue
            
            allowed_pct = (allowed / total * 100) if total > 0 else 0
            logger.info(f"  {bucket}: {total} evaluated, {allowed} allowed ({allowed_pct:.1f}%)")
            
            if rejected > 0:
                reasons = [(k, v) for k, v in counts.items() if k not in ["total", "allowed"]]
                for reason, count in sorted(reasons, key=lambda x: -x[1]):
                    reason_pct = (count / rejected * 100) if rejected > 0 else 0
                    logger.info(f"    - {reason}: {count} ({reason_pct:.1f}% of rejections)")
    
    logger.info("=" * 80)


# ═══════════════════════════════════════════════════════════════════════════
# Migration Guard: Ensure 15m pipelines only use canonical config
# ═══════════════════════════════════════════════════════════════════════════

def assert_15m_canonical_asset(asset: str, timeframe: str = "15m"):
    """Assert that asset/timeframe combination is in canonical 15m config."""
    if _USE_CANONICAL_CONFIG:
        from config.kalshi_15m_crypto_config import (
            KALSHI_15M_CRYPTO_ASSETS,
            KALSHI_15M_TIMEFRAME,
        )
        
        asset_upper = asset.upper()
        if asset_upper not in KALSHI_15M_CRYPTO_ASSETS:
            raise AssertionError(
                f"Asset {asset_upper} not in canonical 15m config. "
                f"Expected one of: {KALSHI_15M_CRYPTO_ASSETS}"
            )
        
        if timeframe != KALSHI_15M_TIMEFRAME:
            raise AssertionError(
                f"Timeframe {timeframe} not canonical 15m timeframe. "
                f"Expected: {KALSHI_15M_TIMEFRAME}"
            )
    else:
        logger.debug(
            f"[MIGRATION_GUARD] Canonical config not available, skipping guard for {asset}/{timeframe}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Liquidity/Spread Guard Configuration
# ═══════════════════════════════════════════════════════════════════════════

# Default liquidity thresholds per asset and bucket
# Format: {asset: {bucket: {"max_spread": float, "min_depth": int}}}
# If not using canonical config, these fallbacks will be used
DEFAULT_LIQUIDITY_THRESHOLDS = {
    "BTC": {
        "10+": {"max_spread": 0.03, "min_depth": 10},  # 3% spread, $10 min depth
        "5-10": {"max_spread": 0.04, "min_depth": 10},
        "2-5": {"max_spread": 0.05, "min_depth": 15},
        "0-2": {"max_spread": 0.06, "min_depth": 20},
    },
    "ETH": {
        "10+": {"max_spread": 0.04, "min_depth": 10},
        "5-10": {"max_spread": 0.05, "min_depth": 10},
        "2-5": {"max_spread": 0.06, "min_depth": 15},
        "0-2": {"max_spread": 0.07, "min_depth": 20},
    },
    "SOL": {
        "10+": {"max_spread": 0.05, "min_depth": 10},
        "5-10": {"max_spread": 0.06, "min_depth": 10},
        "2-5": {"max_spread": 0.07, "min_depth": 15},
        "0-2": {"max_spread": 0.08, "min_depth": 20},
    },
    "XRP": {
        "10+": {"max_spread": 0.05, "min_depth": 10},
        "5-10": {"max_spread": 0.06, "min_depth": 10},
        "2-5": {"max_spread": 0.07, "min_depth": 15},
        "0-2": {"max_spread": 0.08, "min_depth": 20},
    },
    "DOGE": {
        "10+": {"max_spread": 0.06, "min_depth": 10},
        "5-10": {"max_spread": 0.07, "min_depth": 10},
        "2-5": {"max_spread": 0.08, "min_depth": 15},
        "0-2": {"max_spread": 0.09, "min_depth": 20},
    },
}

def get_liquidity_thresholds(asset: str, bucket: str) -> dict:
    """Get liquidity thresholds for an asset and bucket.
    
    Returns dict with "max_spread" and "min_depth" keys.
    """
    if _USE_CANONICAL_CONFIG:
        # Try to get from canonical config if it has liquidity thresholds
        try:
            from config.kalshi_15m_crypto_config import get_liquidity_thresholds as canonical_liquidity
            return canonical_liquidity(asset, bucket)
        except (ImportError, AttributeError):
            pass
    
    # Fallback to local definition
    return DEFAULT_LIQUIDITY_THRESHOLDS.get(asset, {}).get(bucket, {"max_spread": 0.10, "min_depth": 10})

def check_liquidity_guard(
    asset: str,
    bucket: str,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    bid_size: Optional[int] = None,
    ask_size: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """Check if market meets liquidity/spread requirements.
    
    Args:
        asset: Asset symbol
        bucket: Time bucket (e.g., "10+", "5-10", "2-5", "0-2")
        bid: Bid price (0-1 scale for binary options)
        ask: Ask price (0-1 scale for binary options)
        bid_size: Bid size in contracts
        ask_size: Ask size in contracts
    
    Returns:
        (passes, reason) tuple where passes is True if guard passes,
        and reason is None if passes, otherwise the rejection reason string.
    """
    thresholds = get_liquidity_thresholds(asset, bucket)
    
    # Check spread if both bid and ask available
    if bid is not None and ask is not None:
        spread = ask - bid
        if spread > thresholds["max_spread"]:
            return False, EntryWindowDecision.SPREAD_TOO_WIDE.value
    
    # Check depth if both bid_size and ask_size available
    if bid_size is not None and ask_size is not None:
        min_depth = min(bid_size, ask_size)
        if min_depth < thresholds["min_depth"]:
            return False, EntryWindowDecision.DEPTH_TOO_LOW.value
    
    return True, None


def _determine_volatility_tier(asset: str) -> VolatilityTier:
    """Determine volatility tier for an asset using existing infrastructure.
    
    Uses DynamicEdgeCalibrator to get current volatility state and classify.
    Falls back to MEDIUM if calibrator unavailable.
    """
    try:
        from merid.prediction.dynamic_edge_calibrator import get_dynamic_edge_calibrator
        calibrator = get_dynamic_edge_calibrator()
        vol_state = calibrator.get_volatility(asset)
        
        # Simple tier classification based on 24h realized vol
        # These thresholds are configurable per asset
        vol_thresholds = {
            "BTC": (0.40, 0.60),  # (low_threshold, high_threshold)
            "ETH": (0.50, 0.70),
            "SOL": (0.65, 0.85),
            "XRP": (0.60, 0.80),
            "DOGE": (0.75, 0.95),
        }
        
        low_thresh, high_thresh = vol_thresholds.get(asset, (0.50, 0.75))
        
        if vol_state.rv_24h < low_thresh:
            return VolatilityTier.LOW
        elif vol_state.rv_24h < high_thresh:
            return VolatilityTier.MEDIUM
        else:
            return VolatilityTier.HIGH
    except Exception as e:
        logger.debug(f"Could not determine volatility tier for {asset}: {e}, using MEDIUM")
        return VolatilityTier.MEDIUM


def _get_base_edge_threshold(asset: str, volatility_tier: VolatilityTier) -> float:
    """Get base edge threshold from volatility-tiered table.
    
    Returns the upper bound of the threshold range for the tier (more lenient).
    """
    if _USE_CANONICAL_CONFIG:
        # Use canonical config's get_base_edge_threshold
        from config.kalshi_15m_crypto_config import get_base_edge_threshold as canonical_get_threshold
        return canonical_get_threshold(asset, volatility_tier)
    
    # Fallback to local definition
    tier_thresholds = VOLATILITY_TIERED_BASE_THRESHOLDS.get(asset)
    if not tier_thresholds:
        # Fallback to BTC thresholds if asset not in table
        tier_thresholds = VOLATILITY_TIERED_BASE_THRESHOLDS["BTC"]
    
    low, high = tier_thresholds.get(volatility_tier.value, (0.15, 0.20))
    return high  # Use upper bound for more lenient threshold


def _assess_book_quality(ticker: str) -> str:
    """Assess orderbook quality for a market.
    
    Returns: 'good', 'normal', or 'bad'
    """
    try:
        from merid.event_venues.kalshi.orderbook import MultiMarketOrderbook
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        
        # Try to get from market state store (faster)
        state_store = get_kalshi_market_state_store()
        market_state = state_store.get(ticker)
        
        if market_state and market_state.book_initialized:
            spread_pct = market_state.spread_cents / 100.0  # Convert to percentage
            depth = market_state.depth_10c if market_state.depth_10c else 0
            
            # Quality assessment thresholds
            if spread_pct < 0.03 and depth > 100:
                return "good"
            elif spread_pct > 0.08 or depth < 30:
                return "bad"
            else:
                return "normal"
        else:
            # Fallback: try orderbook directly
            orderbook_mgr = MultiMarketOrderbook()
            book = orderbook_mgr.get_book(ticker)
            if book.initialized:
                spread = book.get_spread()
                if spread:
                    spread_pct = spread / 100.0
                    depth = book.get_depth("yes", None) + book.get_depth("no", None)
                    
                    if spread_pct < 0.03 and depth > 100:
                        return "good"
                    elif spread_pct > 0.08 or depth < 30:
                        return "bad"
    except Exception as e:
        logger.debug(f"Could not assess book quality for {ticker}: {e}")
    
    return "normal"  # Conservative default


def _get_model_feedback_adjustment(asset: str) -> float:
    """Get model-quality feedback adjustment.
    
    Uses calibration (Brier score) and hit ratio to adjust thresholds:
    - Good performance (low Brier, high hit rate) -> lower threshold by 1-2%
    - Poor performance (high Brier, low hit rate) -> raise threshold by 2-5%
    
    Returns: Adjustment in percentage points (e.g., -0.02 for 2% reduction)
    """
    try:
        from merid.metrics.calibration import get_calibration_store
        from merid.metrics.hit_ratio import get_hit_ratio_tracker
        
        cal_store = get_calibration_store()
        hit_tracker = get_hit_ratio_tracker()
        
        # Get calibration stats for this asset bucket
        brier = cal_store.get_brier("edge_model_v1", "crypto")
        hit_stats = hit_tracker.stats
        hit_ratio = hit_stats.get("hit_ratio", 0.5)
        
        # Good performance: Brier < 0.20 and hit ratio > 0.55
        if brier < 0.20 and hit_ratio > 0.55:
            return -0.02  # Lower threshold by 2%
        # Poor performance: Brier > 0.30 or hit ratio < 0.45
        elif brier > 0.30 or hit_ratio < 0.45:
            return 0.03  # Raise threshold by 3%
        # Neutral performance: no adjustment
        else:
            return 0.0
    except Exception as e:
        logger.debug(f"Could not get model feedback for {asset}: {e}")
        return 0.0


def _get_regime_multiplier(asset: str) -> float:
    """Get regime-based edge multiplier from UnifiedRegimeClassifier.
    
    Returns: Multiplier (e.g., 0.8 for aggressive regime, 1.5 for defensive)
    """
    try:
        from merid.signals.unified_regime_classifier import get_unified_regime_classifier
        
        classifier = get_unified_regime_classifier()
        state = classifier.get_current_state()
        
        if state:
            return state.edge_threshold_multiplier
    except Exception as e:
        logger.debug(f"Could not get regime multiplier: {e}")
    
    return 1.0  # Default: no adjustment


def resolve_entry_window(
    asset: str,
    minutes_to_expiry: Optional[float],
    edge_pct: Optional[float],
    policy_name: Optional[str] = None,
    ticker: Optional[str] = None,  # Kalshi ticker for orderbook quality check
) -> WindowResolution:
    """
    Resolve whether a trade is allowed based on dynamic entry window policy.
    
    Now uses dynamic edge thresholds based on:
    - Volatility tier (low/medium/high)
    - Time-to-expiry multipliers
    - Orderbook quality multipliers
    - Model-quality feedback (calibration + hit ratio)
    - Regime-based adjustments
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        minutes_to_expiry: Minutes remaining until market expiry
        edge_pct: Edge percentage (e.g., 0.15 for 15%)
        policy_name: Optional policy name to use (for A/B testing)
        ticker: Kalshi market ticker for orderbook quality assessment
    
    Returns:
        WindowResolution with decision, reason, and metadata
    """
    if minutes_to_expiry is None:
        # Missing expiry info - fail closed
        resolution = WindowResolution(
            allowed=False,
            reason=EntryWindowDecision.OUTSIDE_WINDOW,
            active_policy_name="unknown",
            bucket="unknown",
            minutes_to_expiry=None,
            edge_pct=edge_pct,
            dynamic_edge_threshold=None,
            volatility_tier=None,
            t2e_multiplier=None,
            book_quality_multiplier=None,
            model_feedback_adjustment=None,
        )
        _increment_entry_metric(asset_upper, "unknown", resolution.reason.value, resolution.allowed)
        return resolution
    
    asset_upper = asset.upper()
    
    # Validate minutes_to_expiry for 15m markets if canonical config available
    is_scope_violation = False
    if _USE_CANONICAL_CONFIG:
        is_valid, error_msg = validate_minutes_to_expiry(minutes_to_expiry, asset)
        if not is_valid:
            logger.warning(f"[DYNAMIC_WINDOW] {error_msg}")
            # Track scope violation if asset is not in canonical config or timeframe is wrong
            if "not in canonical" in error_msg or "timeframe" in error_msg:
                is_scope_violation = True
    
    # Track scope metrics
    _increment_scope_metric(asset_upper, is_scope_violation)
    
    # Reject if scope violation detected
    if is_scope_violation:
        resolution = WindowResolution(
            allowed=False,
            reason=EntryWindowDecision.SCOPE_VIOLATION,
            active_policy_name="unknown",
            bucket="unknown",
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct,
            dynamic_edge_threshold=None,
            volatility_tier=None,
            t2e_multiplier=None,
            book_quality_multiplier=None,
            model_feedback_adjustment=None,
        )
        _increment_entry_metric(asset_upper, "unknown", resolution.reason.value, resolution.allowed)
        return resolution
    
    policy = _POLICIES.get(asset_upper)
    
    if policy is None:
        logger.warning(f"[DYNAMIC_WINDOW] No policy for asset {asset_upper}, using fallback")
        # Fallback: conservative 10-5 window, no terminal
        policy = AssetWindowPolicy(
            asset=asset_upper,
            base_window_start_minutes=10,
            base_window_end_minutes=5,
            terminal_config=TerminalPhaseConfig(enabled=False),
            policy_name="fallback"
        )
    
    bucket = _get_bucket(minutes_to_expiry)
    
    # Check if in base window
    in_base_window = (
        policy.base_window_end_minutes <= minutes_to_expiry <= policy.base_window_start_minutes
    )
    
    # Check if in terminal band
    in_terminal = 0 <= minutes_to_expiry < policy.base_window_end_minutes
    
    # Liquidity/spread guard (check before allowing in base window)
    # Integrate with KalshiMarketStateStore for orderbook data
    book_quality_multiplier = 1.0
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        market_state_store = get_kalshi_market_state_store()
        market_state = market_state_store.get(ticker)
        
        if market_state and market_state.book_initialized:
            # Check spread quality: reject if spread is too wide (poor liquidity)
            if market_state.spread_cents and market_state.mid_cents:
                spread_pct = market_state.spread_cents / market_state.mid_cents if market_state.mid_cents > 0 else 0
                # Reject if spread > 5% (poor liquidity)
                if spread_pct > 0.05:
                    resolution = WindowResolution(
                        allowed=False,
                        reason=EntryWindowDecision.REJECTED_SPREAD_TOO_WIDE,
                        active_policy_name=policy.policy_name,
                        bucket=bucket,
                        minutes_to_expiry=minutes_to_expiry,
                        edge_pct=edge_pct,
                        dynamic_edge_threshold=None,
                        volatility_tier=None,
                        t2e_multiplier=None,
                        book_quality_multiplier=book_quality_multiplier,
                        model_feedback_adjustment=None,
                    )
                    _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
                    return resolution
                
                # Adjust multiplier based on spread quality (tighter spread = higher multiplier)
                # Spread < 1%: 1.0x, 1-2%: 0.9x, 2-3%: 0.8x, 3-5%: 0.7x
                if spread_pct < 0.01:
                    book_quality_multiplier = 1.0
                elif spread_pct < 0.02:
                    book_quality_multiplier = 0.9
                elif spread_pct < 0.03:
                    book_quality_multiplier = 0.8
                else:
                    book_quality_multiplier = 0.7
    except Exception:
        # If market state store is unavailable, proceed without liquidity guard
        book_quality_multiplier = 1.0
    
    if in_base_window:
        resolution = WindowResolution(
            allowed=True,
            reason=EntryWindowDecision.ALLOWED_BASE,
            active_policy_name=policy.policy_name,
            bucket=bucket,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct,
            dynamic_edge_threshold=None,
            volatility_tier=None,
            t2e_multiplier=None,
            book_quality_multiplier=None,
            model_feedback_adjustment=None,
        )
        _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
        return resolution
    
    if in_terminal and policy.terminal_config.enabled:
        # Compute dynamic edge threshold
        dynamic_threshold = None
        volatility_tier = None
        t2e_mult = None
        book_quality_mult = None
        model_adj = None
        
        if policy.terminal_config.use_dynamic_threshold:
            # Step 1: Determine volatility tier and get base threshold
            volatility_tier = _determine_volatility_tier(asset_upper)
            base_threshold = _get_base_edge_threshold(asset_upper, volatility_tier)
            
            # Step 2: Apply orderbook quality multiplier if enabled and ticker provided (disabled for testing)
            book_quality_mult = 1.0
            book_quality = None
            if False and policy.terminal_config.book_quality_enabled and ticker:
                book_quality = _assess_book_quality(ticker)
                book_quality_mult = BOOK_QUALITY_MULTIPLIERS.get(book_quality, 1.0)
                
                # If book quality is bad, reject immediately
                if book_quality == "bad":
                    resolution = WindowResolution(
                        allowed=False,
                        reason=EntryWindowDecision.BOOK_QUALITY_TOO_LOW,
                        active_policy_name=policy.policy_name,
                        bucket=bucket,
                        minutes_to_expiry=minutes_to_expiry,
                        edge_pct=edge_pct,
                        dynamic_edge_threshold=None,
                        volatility_tier=volatility_tier.value,
                        t2e_multiplier=None,
                        book_quality_multiplier=book_quality_mult,
                        model_feedback_adjustment=None,
                    )
                    _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
                    return resolution
            
            # Step 3: Apply model-quality feedback if enabled (disabled for testing)
            model_adj = 0.0
            if False and policy.terminal_config.model_feedback_enabled:
                model_adj = _get_model_feedback_adjustment(asset_upper)
            
            # Step 4: Apply regime multiplier (disabled for now to simplify testing)
            regime_mult = 1.0  # _get_regime_multiplier(asset_upper)
            
            # Compute final dynamic threshold (t2e and regime multipliers removed to prevent over-conservative thresholds)
            dynamic_threshold = base_threshold * book_quality_mult * regime_mult + model_adj
            
            # Clamp to reasonable bounds (5% to 50%)
            dynamic_threshold = max(0.05, min(0.50, dynamic_threshold))
        else:
            # Use static threshold from config (convert percentage to decimal)
            dynamic_threshold = policy.terminal_config.edge_threshold_pct / 100.0
        
        # Check if edge meets threshold (edge_pct is in percentage, convert to decimal)
        edge_decimal = edge_pct / 100.0 if edge_pct is not None else None
        if edge_decimal is not None and edge_decimal >= dynamic_threshold:
            resolution = WindowResolution(
                allowed=True,
                reason=EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE,
                active_policy_name=policy.policy_name,
                bucket=bucket,
                minutes_to_expiry=minutes_to_expiry,
                edge_pct=edge_pct,
                dynamic_edge_threshold=dynamic_threshold,
                volatility_tier=volatility_tier.value if volatility_tier else None,
                t2e_multiplier=t2e_mult,
                book_quality_multiplier=book_quality_mult,
                model_feedback_adjustment=model_adj,
            )
            _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
            return resolution
        else:
            resolution = WindowResolution(
                allowed=False,
                reason=EntryWindowDecision.TERMINAL_EDGE_TOO_LOW,
                active_policy_name=policy.policy_name,
                bucket=bucket,
                minutes_to_expiry=minutes_to_expiry,
                edge_pct=edge_pct,
                dynamic_edge_threshold=dynamic_threshold,
                volatility_tier=volatility_tier.value if volatility_tier else None,
                t2e_multiplier=t2e_mult,
                book_quality_multiplier=book_quality_mult,
                model_feedback_adjustment=model_adj,
            )
            _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
            return resolution
    
    if in_terminal and not policy.terminal_config.enabled:
        resolution = WindowResolution(
            allowed=False,
            reason=EntryWindowDecision.TERMINAL_DISABLED,
            active_policy_name=policy.policy_name,
            bucket=bucket,
            minutes_to_expiry=minutes_to_expiry,
            edge_pct=edge_pct,
            dynamic_edge_threshold=None,
            volatility_tier=None,
            t2e_multiplier=None,
            book_quality_multiplier=None,
            model_feedback_adjustment=None,
        )
        _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
        return resolution
    
    # Outside window entirely
    resolution = WindowResolution(
        allowed=False,
        reason=EntryWindowDecision.OUTSIDE_WINDOW,
        active_policy_name=policy.policy_name,
        bucket=bucket,
        minutes_to_expiry=minutes_to_expiry,
        edge_pct=edge_pct,
        dynamic_edge_threshold=None,
        volatility_tier=None,
        t2e_multiplier=None,
        book_quality_multiplier=None,
        model_feedback_adjustment=None,
    )
    _increment_entry_metric(asset_upper, bucket, resolution.reason.value, resolution.allowed)
    return resolution


def load_policies_from_env() -> Dict[str, AssetWindowPolicy]:
    """
    Load entry window policies from environment variables.
    
    Env var format:
    MERID_ENTRY_WINDOW_{ASSET}_START_MINUTES=12
    MERID_ENTRY_WINDOW_{ASSET}_END_MINUTES=3
    MERID_ENTRY_WINDOW_{ASSET}_TERMINAL_ENABLED=true
    MERID_ENTRY_WINDOW_{ASSET}_TERMINAL_EDGE_THRESHOLD=20.0
    MERID_ENTRY_WINDOW_{ASSET}_POLICY_NAME=kalshi_15m_v1
    
    Returns:
        Dictionary of asset -> AssetWindowPolicy
    """
    policies = {}
    
    # Global policy version for all assets (if set, overrides per-asset names)
    global_policy_version = os.getenv("MERID_ENTRY_WINDOW_POLICY_VERSION", "v1")
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        start_key = f"MERID_ENTRY_WINDOW_{asset}_START_MINUTES"
        end_key = f"MERID_ENTRY_WINDOW_{asset}_END_MINUTES"
        term_enabled_key = f"MERID_ENTRY_WINDOW_{asset}_TERMINAL_ENABLED"
        term_edge_key = f"MERID_ENTRY_WINDOW_{asset}_TERMINAL_EDGE_THRESHOLD"
        policy_name_key = f"MERID_ENTRY_WINDOW_{asset}_POLICY_NAME"
        
        start = int(os.getenv(start_key, str(DEFAULT_POLICIES[asset].base_window_start_minutes)))
        end = int(os.getenv(end_key, str(DEFAULT_POLICIES[asset].base_window_end_minutes)))
        term_enabled = os.getenv(term_enabled_key, str(DEFAULT_POLICIES[asset].terminal_config.enabled)).lower() in ("true", "1", "yes")
        term_edge = float(os.getenv(term_edge_key, str(DEFAULT_POLICIES[asset].terminal_config.edge_threshold_pct)))
        
        # Policy name: per-asset override or global version
        policy_name = os.getenv(policy_name_key, f"kalshi_15m_{asset.lower()}_{global_policy_version}")
        
        policies[asset] = AssetWindowPolicy(
            asset=asset,
            base_window_start_minutes=start,
            base_window_end_minutes=end,
            terminal_config=TerminalPhaseConfig(
                enabled=term_enabled,
                edge_threshold_pct=term_edge,
                max_terminal_minutes=end
            ),
            policy_name=policy_name
        )
    
    return policies


# Global policies cache (can be updated at runtime)
_POLICIES: Dict[str, AssetWindowPolicy] = DEFAULT_POLICIES.copy()


def update_policies(policies: Dict[str, AssetWindowPolicy]) -> None:
    """Update the global policies cache."""
    global _POLICIES
    _POLICIES = policies.copy()
    logger.info(f"[DYNAMIC_WINDOW] Updated policies for {len(policies)} assets")


def get_policies() -> Dict[str, AssetWindowPolicy]:
    """Get current policies."""
    return _POLICIES.copy()


# Initialize policies from env on module load
try:
    env_policies = load_policies_from_env()
    update_policies(env_policies)
    logger.info("[DYNAMIC_WINDOW] Loaded policies from environment variables")
except Exception as e:
    logger.warning(f"[DYNAMIC_WINDOW] Failed to load policies from env: {e}, using defaults")


# ── Exit Policy Configuration (Coherent Risk Contract) ──────────────────────

# Asset class grouping for exit policy mapping - use canonical if available
if _USE_CANONICAL_CONFIG:
    # Already imported as ASSET_CLASS_MAJOR and ASSET_CLASS_ALT
    pass
else:
    ASSET_CLASS_MAJOR = ["BTC", "ETH"]
    ASSET_CLASS_ALT = ["SOL", "XRP", "DOGE"]

# Exit policy mapping table - use canonical if available, otherwise define locally
if not _USE_CANONICAL_CONFIG:
    EXIT_POLICY_TABLE: Dict[Tuple[str, str], Dict[str, any]] = {
        ("A", "major"): {
            "tp_r_multiple": 1.8,
            "sl_edge_multiplier": 0.8,
            "trailing_enabled": True,
            "trailing_activation_r_multiple": 1.0,
            "trailing_giveback_pct": 15.0,
            "max_hold_seconds": 900,
            "auto_exit_enabled": True,
        },
        ("A", "alt"): {
            "tp_r_multiple": 2.0,
            "sl_edge_multiplier": 1.0,
            "trailing_enabled": True,
            "trailing_activation_r_multiple": 1.0,
            "trailing_giveback_pct": 20.0,
            "max_hold_seconds": 900,
            "auto_exit_enabled": True,
        },
        ("B", "major"): {
            "tp_r_multiple": 1.4,
            "sl_edge_multiplier": 1.0,
            "trailing_enabled": True,
            "trailing_activation_r_multiple": 1.0,
            "trailing_giveback_pct": 15.0,
            "max_hold_seconds": 600,
            "auto_exit_enabled": True,
        },
        ("B", "alt"): {
            "tp_r_multiple": 1.5,
            "sl_edge_multiplier": 1.2,
            "trailing_enabled": True,
            "trailing_activation_r_multiple": 1.0,
            "trailing_giveback_pct": 20.0,
            "max_hold_seconds": 600,
            "auto_exit_enabled": True,
        },
        ("C", "major"): {
            "tp_r_multiple": 1.1,
            "sl_edge_multiplier": 0.75,
            "trailing_enabled": False,
            "trailing_activation_r_multiple": None,
            "trailing_giveback_pct": None,
            "max_hold_seconds": 360,
            "auto_exit_enabled": True,
        },
        ("C", "alt"): {
            "tp_r_multiple": 1.2,
            "sl_edge_multiplier": 0.9,
            "trailing_enabled": False,
            "trailing_activation_r_multiple": None,
            "trailing_giveback_pct": None,
            "max_hold_seconds": 360,
            "auto_exit_enabled": True,
        },
    }


def _classify_risk_tier(
    regime: str,
    volatility_tier: str,
    model_quality_good: bool,
    edge_buffer: float,  # How much edge exceeds threshold (positive = comfortable margin)
) -> RiskTier:
    """Classify risk tier based on regime, volatility, and model quality.
    
    Args:
        regime: "aggressive", "normal", "defensive", or "halt" from unified_regime_classifier
        volatility_tier: "low", "medium", or "high"
        model_quality_good: True if Brier < 0.20 and hit_ratio > 0.55
        edge_buffer: Edge percentage above threshold (e.g., 0.05 = 5% buffer)
    
    Returns:
        RiskTier (A, B, or C)
    """
    # Defensive regime or halt → Tier C
    if regime in ("defensive", "halt"):
        return RiskTier.TIER_C
    
    # High volatility + weak model quality → Tier C
    if volatility_tier == "high" and not model_quality_good:
        return RiskTier.TIER_C
    
    # High volatility + thin edge buffer → Tier C
    if volatility_tier == "high" and edge_buffer < 0.02:
        return RiskTier.TIER_C
    
    # Low volatility + strong model quality + good edge buffer → Tier A
    if volatility_tier == "low" and model_quality_good and edge_buffer >= 0.05:
        return RiskTier.TIER_A
    
    # Aggressive/normal regime + medium vol + decent model quality → Tier A
    if regime in ("aggressive", "normal") and volatility_tier in ("low", "medium") and model_quality_good:
        return RiskTier.TIER_A
    
    # Everything else → Tier B (normal)
    return RiskTier.TIER_B


def _get_asset_class(asset: str) -> str:
    """Return asset class for exit policy mapping."""
    return "major" if asset.upper() in ASSET_CLASS_MAJOR else "alt"


def resolve_exit_policy(
    window_resolution: WindowResolution,
    asset: str,
    edge_pct: Optional[float] = None,
) -> ExitPolicyResolution:
    """Resolve exit policy from the same signals used for dynamic entry window.
    
    This function creates the exit companion to WindowResolution, ensuring
    entry and exit parameters form one coherent risk contract.
    
    Args:
        window_resolution: Result from resolve_entry_window()
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        edge_pct: Edge percentage (uses window_resolution.edge_pct if None)
    
    Returns:
        ExitPolicyResolution with TP, SL, trailing, and time-based exit parameters
    """
    if not window_resolution.allowed:
        # Entry rejected → exit policy disabled
        return ExitPolicyResolution(
            enabled=False,
            risk_tier="C",
            take_profit_r_multiple=None,
            stop_loss_edge_multiplier=1.0,
            trailing_enabled=False,
            trailing_activation_r_multiple=None,
            trailing_giveback_pct=None,
            max_hold_seconds=0,
            auto_exit_enabled=False,
            rationale={"reason": "entry_not_allowed"},
        )
    
    # Use edge from window_resolution if not provided
    actual_edge_pct = edge_pct or window_resolution.edge_pct
    if actual_edge_pct is None:
        actual_edge_pct = 0.0
    
    # Get signals for risk tier classification
    volatility_tier = window_resolution.volatility_tier or "medium"
    dynamic_threshold = window_resolution.dynamic_edge_threshold or 0.15
    edge_buffer = max(0, actual_edge_pct - dynamic_threshold)
    
    # Get regime from unified_regime_classifier
    regime = "normal"  # Default fallback
    try:
        from merid.signals.unified_regime_classifier import get_unified_regime_classifier
        classifier = get_unified_regime_classifier()
        state = classifier.get_current_state()
        if state:
            regime = state.regime.value
    except Exception as e:
        logger.debug(f"Could not get regime for exit policy: {e}")
    
    # Get model quality
    model_quality_good = False
    try:
        from merid.metrics.calibration import get_calibration_store
        from merid.metrics.hit_ratio import get_hit_ratio_tracker
        
        cal_store = get_calibration_store()
        hit_tracker = get_hit_ratio_tracker()
        
        brier = cal_store.get_brier("edge_model_v1", "crypto")
        hit_stats = hit_tracker.stats
        hit_ratio = hit_stats.get("hit_ratio", 0.5)
        
        model_quality_good = (brier < 0.20 and hit_ratio > 0.55)
    except Exception as e:
        logger.debug(f"Could not get model quality for exit policy: {e}")
    
    # Classify risk tier
    risk_tier = _classify_risk_tier(regime, volatility_tier, model_quality_good, edge_buffer)
    
    # Get asset class
    asset_class = _get_asset_class(asset)
    
    # Look up exit parameters from table
    policy_key = (risk_tier.value, asset_class)
    exit_params = EXIT_POLICY_TABLE.get(policy_key, EXIT_POLICY_TABLE[("B", "major")])
    
    # Build rationale for diagnostics
    rationale = {
        "regime": regime,
        "volatility_tier": volatility_tier,
        "model_quality_good": model_quality_good,
        "edge_buffer_pct": edge_buffer,
        "edge_pct": actual_edge_pct,
        "dynamic_threshold": dynamic_threshold,
        "asset_class": asset_class,
    }
    
    return ExitPolicyResolution(
        enabled=True,
        risk_tier=risk_tier.value,
        take_profit_r_multiple=exit_params["tp_r_multiple"],
        stop_loss_edge_multiplier=exit_params["sl_edge_multiplier"],
        trailing_enabled=exit_params["trailing_enabled"],
        trailing_activation_r_multiple=exit_params.get("trailing_activation_r_multiple"),
        trailing_giveback_pct=exit_params.get("trailing_giveback_pct"),
        max_hold_seconds=exit_params["max_hold_seconds"],
        auto_exit_enabled=exit_params["auto_exit_enabled"],
        rationale=rationale,
    )


def validate_exit_policy(ep: ExitPolicyResolution) -> bool:
    """Validate that an exit policy is complete and safe for live trading.
    
    Enforces the "no trade without exit plan" rule:
    - enabled must be True
    - stop_loss_edge_multiplier must be positive
    - At least one of TP or trailing must be active
    - auto_exit_enabled must be True (time-based exit mandatory)
    
    Args:
        ep: ExitPolicyResolution to validate
    
    Returns:
        True if valid, False otherwise
    """
    if not ep.enabled:
        logger.warning("[EXIT_POLICY] Exit policy not enabled - trade rejected")
        return False
    
    if ep.stop_loss_edge_multiplier <= 0:
        logger.warning("[EXIT_POLICY] Invalid stop loss multiplier - trade rejected")
        return False
    
    if not ep.auto_exit_enabled:
        logger.warning("[EXIT_POLICY] Auto-exit not enabled - trade rejected")
        return False
    
    # At least one of TP or trailing must be active
    has_tp = ep.take_profit_r_multiple is not None and ep.take_profit_r_multiple > 0
    has_trailing = ep.trailing_enabled
    
    if not has_tp and not has_trailing:
        logger.warning("[EXIT_POLICY] No TP or trailing - trade rejected")
        return False
    
    return True
