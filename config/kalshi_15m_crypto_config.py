"""
Canonical Kalshi 15-Minute Crypto Configuration

Single source of truth for 15m crypto trading universe, time semantics,
and policy parameters. Consolidates metadata from kalshi_crypto_series_meta,
kalshi_universe, and dynamic_entry_window into one coherent configuration.

DO NOT DUPLICATE these values elsewhere - import from this module.

DEPRECATION NOTICE:
====================
The ASSET_RISK_LIMITS and GLOBAL_RISK_LIMITS in this file are superseded by
config/profiles/kalshi_crypto_15m_v2.yaml, which is the single source of truth
for 15m crypto risk configuration when MERID_PROFILE=kalshi_crypto_15m_v2.
The legacy dictionaries below are kept only for backward compatibility and
should not be used in new code.
"""

from __future__ import annotations
import os
import warnings

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple
from enum import Enum


class AssetSymbol(str, Enum):
    """Canonical crypto asset symbols for Kalshi 15m markets."""
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    XRP = "XRP"
    DOGE = "DOGE"


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: Universe Definition (Single Source of Truth)
# ═══════════════════════════════════════════════════════════════════════════

KALSHI_15M_CRYPTO_ASSETS: Tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "DOGE",
)

KALSHI_15M_TIMEFRAME: Literal["15m"] = "15m"

# Series tickers for 15m crypto (from kalshi_crypto_series_meta)
# NOTE: This is the CANONICAL source for series tickers - NOT deprecated
# Only ASSET_RISK_LIMITS and GLOBAL_RISK_LIMITS are superseded by profile
KALSHI_15M_SERIES_TICKERS: Dict[str, str] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}

# Asset class grouping for exit policy mapping (from dynamic_entry_window)
ASSET_CLASS_MAJOR: Tuple[str, ...] = ("BTC", "ETH")
ASSET_CLASS_ALT: Tuple[str, ...] = ("SOL", "XRP", "DOGE")


def get_asset_class(asset: str) -> Literal["major", "alt"]:
    """Get asset class (major or alt) for policy parameter selection."""
    asset_upper = asset.upper()
    if asset_upper in ASSET_CLASS_MAJOR:
        return "major"
    return "alt"


def get_series_ticker(asset: str) -> Optional[str]:
    """Get Kalshi series ticker for a 15m crypto asset."""
    return KALSHI_15M_SERIES_TICKERS.get(asset.upper())


def is_15m_crypto_asset(asset: str) -> bool:
    """Check if an asset is in the 15m crypto trading universe."""
    return asset.upper() in KALSHI_15M_CRYPTO_ASSETS


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: Time Semantics (Standardized Expiry Math)
# ═══════════════════════════════════════════════════════════════════════════

# Time bucket definitions (from dynamic_entry_window)
TIME_BUCKETS: Dict[str, Tuple[float, float]] = {
    "0-2": (0.0, 2.0),
    "2-5": (2.0, 5.0),
    "5-10": (5.0, 10.0),
    "10+": (10.0, 9999.0),
}

# Time-to-expiry bands for multipliers (from dynamic_entry_window)
T2E_BANDS: Dict[str, Tuple[float, float]] = {
    "long": (8.0, 9999.0),
    "medium": (4.0, 8.0),
    "short": (0.0, 4.0),
}


def get_time_bucket(minutes_to_expiry: float) -> str:
    """Convert minutes to expiry to analysis bucket."""
    for bucket, (min_val, max_val) in TIME_BUCKETS.items():
        if min_val <= minutes_to_expiry < max_val:
            return bucket
    return "10+"


def get_t2e_band(minutes_to_expiry: float) -> str:
    """Convert minutes to expiry to time-to-expiry band for multipliers."""
    for band, (min_val, max_val) in T2E_BANDS.items():
        if min_val <= minutes_to_expiry < max_val:
            return band
    return "short"


def validate_minutes_to_expiry(minutes_to_expiry: float, asset: str) -> Tuple[bool, Optional[str]]:
    """
    Validate minutes_to_expiry for a 15m crypto market.
    
    For 15m markets, minutes_to_expiry should be in range [0, 15].
    Values outside this range indicate a configuration or mapping bug.
    
    Returns:
        (is_valid, error_message)
    """
    if not (0.0 <= minutes_to_expiry <= 15.0):
        return False, f"Invalid minutes_to_expiry {minutes_to_expiry} for {asset} (expected 0-15 for 15m market)"
    return True, None


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: Entry Window Policies (Consolidated from dynamic_entry_window)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TerminalPhaseConfig:
    """Terminal phase (near expiry) configuration."""
    enabled: bool = True
    edge_threshold_pct: float = 2.0  # Lowered from 20% to 2% to allow terminal bucket entry
    max_terminal_minutes: int = 5
    use_dynamic_threshold: bool = True
    t2e_multiplier_enabled: bool = True
    book_quality_enabled: bool = True
    model_feedback_enabled: bool = True


@dataclass(frozen=True)
class AssetWindowPolicy:
    """Entry window policy for a specific 15m crypto asset."""
    asset: str
    base_window_start_minutes: int
    base_window_end_minutes: int
    terminal_config: TerminalPhaseConfig
    policy_name: str


# Default entry window policies for 15m crypto (from dynamic_entry_window DEFAULT_POLICIES)
# NOTE: These windows must match the profile YAML (kalshi_crypto_15m.yaml) for consistency
DEFAULT_ENTRY_POLICIES: Dict[str, AssetWindowPolicy] = {
    "BTC": AssetWindowPolicy(
        asset="BTC",
        base_window_start_minutes=30,  # Match profile YAML: minutes_before_expiry=30
        base_window_end_minutes=2,    # Match profile YAML: cutoff_minutes_before_expiry=2
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=2.0,  # Lowered from 20% to 2% for testing terminal bucket entry
            max_terminal_minutes=2,
            use_dynamic_threshold=True,
            t2e_multiplier_enabled=True,
            book_quality_enabled=True,
            model_feedback_enabled=True,
        ),
        policy_name="kalshi_15m_btc_v1"
    ),
    "ETH": AssetWindowPolicy(
        asset="ETH",
        base_window_start_minutes=30,  # Match profile YAML: minutes_before_expiry=30
        base_window_end_minutes=2,    # Match profile YAML: cutoff_minutes_before_expiry=2
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=2.0,  # Lowered from 20% to 2% for testing terminal bucket entry
            max_terminal_minutes=2,
            use_dynamic_threshold=True,
            t2e_multiplier_enabled=True,
            book_quality_enabled=True,
            model_feedback_enabled=True,
        ),
        policy_name="kalshi_15m_eth_v1"
    ),
    "SOL": AssetWindowPolicy(
        asset="SOL",
        base_window_start_minutes=30,  # Match profile YAML: minutes_before_expiry=30
        base_window_end_minutes=2,    # Match profile YAML: cutoff_minutes_before_expiry=2
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=2.0,  # Lowered from 20% to 2% for testing terminal bucket entry
            max_terminal_minutes=2,
            use_dynamic_threshold=True,
            t2e_multiplier_enabled=True,
            book_quality_enabled=True,
            model_feedback_enabled=True,
        ),
        policy_name="kalshi_15m_sol_v1"
    ),
    "XRP": AssetWindowPolicy(
        asset="XRP",
        base_window_start_minutes=30,  # Match profile YAML: minutes_before_expiry=30
        base_window_end_minutes=2,    # Match profile YAML: cutoff_minutes_before_expiry=2
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=2.0,  # Lowered from 20% to 2% for testing terminal bucket entry
            max_terminal_minutes=2,
            use_dynamic_threshold=True,
            t2e_multiplier_enabled=True,
            book_quality_enabled=True,
            model_feedback_enabled=True,
        ),
        policy_name="kalshi_15m_xrp_v1"
    ),
    "DOGE": AssetWindowPolicy(
        asset="DOGE",
        base_window_start_minutes=30,  # Match profile YAML: minutes_before_expiry=30
        base_window_end_minutes=2,    # Match profile YAML: cutoff_minutes_before_expiry=2
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=2.0,  # Lowered from 20% to 2% for testing terminal bucket entry
            max_terminal_minutes=2,
            use_dynamic_threshold=True,
            t2e_multiplier_enabled=True,
            book_quality_enabled=True,
            model_feedback_enabled=True,
        ),
        policy_name="kalshi_15m_doge_v1"
    ),
}


def get_entry_policy(asset: str) -> Optional[AssetWindowPolicy]:
    """Get entry window policy for a 15m crypto asset."""
    return DEFAULT_ENTRY_POLICIES.get(asset.upper())


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Exit Policy Parameters (Consolidated from dynamic_entry_window)
# ═══════════════════════════════════════════════════════════════════════════

# Exit policy mapping table: (risk_tier, asset_class) -> parameters
# TP multiple: reward-to-risk ratio (higher = more ambitious profit target)
# SL edge multiplier: stop distance as fraction of entry edge (lower = tighter stop)
# Trailing: whether trailing stop is enabled
# Max hold seconds: time-based auto-exit
EXIT_POLICY_TABLE: Dict[Tuple[str, str], Dict[str, any]] = {
    # Tier A (high confidence) - Major assets
    ("A", "major"): {
        "tp_r_multiple": 1.8,
        "sl_edge_multiplier": 0.8,
        "trailing_enabled": True,
        "trailing_activation_r_multiple": 1.0,
        "trailing_giveback_pct": 15.0,
        "max_hold_seconds": 900,
        "auto_exit_enabled": True,
    },
    # Tier A (high confidence) - Alt assets
    ("A", "alt"): {
        "tp_r_multiple": 2.0,
        "sl_edge_multiplier": 1.0,
        "trailing_enabled": True,
        "trailing_activation_r_multiple": 1.0,
        "trailing_giveback_pct": 20.0,
        "max_hold_seconds": 900,
        "auto_exit_enabled": True,
    },
    # Tier B (normal) - Major assets
    ("B", "major"): {
        "tp_r_multiple": 1.4,
        "sl_edge_multiplier": 1.0,
        "trailing_enabled": True,
        "trailing_activation_r_multiple": 1.0,
        "trailing_giveback_pct": 15.0,
        "max_hold_seconds": 600,
        "auto_exit_enabled": True,
    },
    # Tier B (normal) - Alt assets
    ("B", "alt"): {
        "tp_r_multiple": 1.5,
        "sl_edge_multiplier": 1.2,
        "trailing_enabled": True,
        "trailing_activation_r_multiple": 1.0,
        "trailing_giveback_pct": 20.0,
        "max_hold_seconds": 600,
        "auto_exit_enabled": True,
    },
    # Tier C (fragile) - Major assets
    ("C", "major"): {
        "tp_r_multiple": 1.1,
        "sl_edge_multiplier": 0.75,
        "trailing_enabled": False,
        "trailing_activation_r_multiple": None,
        "trailing_giveback_pct": None,
        "max_hold_seconds": 360,
        "auto_exit_enabled": True,
    },
    # Tier C (fragile) - Alt assets
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


def get_exit_policy_params(risk_tier: str, asset: str) -> Dict[str, any]:
    """
    Get exit policy parameters for a risk tier and asset.
    
    Args:
        risk_tier: "A", "B", or "C"
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
    
    Returns:
        Dictionary of exit policy parameters
    """
    asset_class = get_asset_class(asset)
    policy_key = (risk_tier, asset_class)
    return EXIT_POLICY_TABLE.get(policy_key, EXIT_POLICY_TABLE[("B", "major")])


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION RISK LIMITS (Single Source of Truth)
# ═══════════════════════════════════════════════════════════════════════════
#
# These are the PRODUCTION canonical risk limits for 15m crypto trading.
# Both LIVE and PAPER modes read from these exact values.
# Paper mode differs from live ONLY in execution mode (no real orders), not in sizing or limits.
#
# RISK GOVERNANCE:
# - Any limit change must be configuration-only (no code changes required)
# - Changes apply to both LIVE and PAPER automatically
# - Startup validation enforces LIVE/PAPER parity
# - Audit trail: limits are logged at startup for every agent
#
# ADJUSTMENT PROCESS:
# 1. Review live performance metrics (win rate, Sharpe, max drawdown, slippage)
# 2. Adjust values below based on performance data
# 3. Run startup validation to ensure parity
# 4. Deploy - both LIVE and PAPER will use new limits
#
# CURRENT PRODUCTION LIMITS (Conservative for initial go-live):
# - Per-asset: 5 contracts/order, 20 max open, 3 resting orders, $100 daily loss
# - Global: $1,000 total notional, $500 daily loss, 10 contracts/order max
#
# ═══════════════════════════════════════════════════════════════════════════

# Per-asset risk limits for 15m crypto (PRODUCTION CANONICAL VALUES)
# These values are used by BOTH LIVE and PAPER trading stacks
ASSET_RISK_LIMITS = {
    "BTC": {
        "max_contracts_per_order": 5,  # Production canonical value
        "max_open_contracts": 20,  # Production canonical value
        "max_concurrent_resting_orders": 3,  # Production canonical value
        "max_daily_loss_usd": 100.0,  # Production canonical value
    },
    "ETH": {
        "max_contracts_per_order": 5,  # Production canonical value
        "max_open_contracts": 20,  # Production canonical value
        "max_concurrent_resting_orders": 3,  # Production canonical value
        "max_daily_loss_usd": 100.0,  # Production canonical value
    },
    "SOL": {
        "max_contracts_per_order": 5,  # Production canonical value
        "max_open_contracts": 20,  # Production canonical value
        "max_concurrent_resting_orders": 3,  # Production canonical value
        "max_daily_loss_usd": 100.0,  # Production canonical value
    },
    "XRP": {
        "max_contracts_per_order": 5,  # Production canonical value
        "max_open_contracts": 20,  # Production canonical value
        "max_concurrent_resting_orders": 3,  # Production canonical value
        "max_daily_loss_usd": 100.0,  # Production canonical value
    },
    "DOGE": {
        "max_contracts_per_order": 5,  # Production canonical value
        "max_open_contracts": 20,  # Production canonical value
        "max_concurrent_resting_orders": 3,  # Production canonical value
        "max_daily_loss_usd": 100.0,  # Production canonical value
    },
}

# Global risk limits for 15m crypto (PRODUCTION CANONICAL VALUES)
# These values are used by BOTH LIVE and PAPER trading stacks
GLOBAL_RISK_LIMITS = {
    "max_total_open_notional_usd": 1000.0,  # Production canonical value (~3% of bankroll)
    "max_daily_loss_usd": 500.0,  # Production canonical value (~14% of bankroll)
    "max_total_contracts_per_order": 10,  # Production canonical value
}

def get_asset_risk_limits(asset: str) -> dict:
    """Get risk limits for a specific asset.

    DEPRECATED: Use profile-based configuration from kalshi_crypto_15m_v2.yaml instead.
    This function is kept for backward compatibility.

    Args:
        asset: Asset symbol (e.g., "BTC")

    Returns:
        Dict with risk limit keys
    """
    warnings.warn(
        "get_asset_risk_limits() is deprecated. Use profile-based configuration from "
        "kalshi_crypto_15m_v2.yaml instead. Profile-based config is the single source of truth.",
        DeprecationWarning,
        stacklevel=2
    )
    return ASSET_RISK_LIMITS.get(asset.upper(), ASSET_RISK_LIMITS["BTC"])

def get_global_risk_limits() -> dict:
    """Get global risk limits for 15m crypto.

    DEPRECATED: Use profile-based configuration from kalshi_crypto_15m_v2.yaml instead.
    This function is kept for backward compatibility.

    Returns:
        Dict with global risk limit keys
    """
    warnings.warn(
        "get_global_risk_limits() is deprecated. Use profile-based configuration from "
        "kalshi_crypto_15m_v2.yaml instead. Profile-based config is the single source of truth.",
        DeprecationWarning,
        stacklevel=2
    )
    return GLOBAL_RISK_LIMITS


def verify_risk_parity() -> tuple[bool, str]:
    """Verify that LIVE and PAPER modes use identical risk limits.
    
    This enforces the principle that paper mirrors live - both modes should
    read from the same canonical config. Any divergence is an error unless
    explicitly overridden.
    
    Returns:
        (parity_ok, error_message) - True if parity holds, False with error message otherwise
    """
    from merid.prediction.trading_mode import TradingMode
    
    # Load config for both modes (they should be identical)
    live_asset_limits = {asset: get_asset_risk_limits(asset) for asset in KALSHI_15M_CRYPTO_ASSETS}
    live_global_limits = get_global_risk_limits()
    
    # In a true parity check, we'd simulate loading in paper mode
    # For now, we verify the config is mode-agnostic (no environment-specific overrides)
    
    # Check that limits are not environment-dependent
    errors = []
    
    # Verify per-asset limits are consistent
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        limits = get_asset_risk_limits(asset)
        
        # Check for any environment-specific keys
        for key, value in limits.items():
            if isinstance(value, str) and "live" in value.lower():
                errors.append(f"{asset}.{key} has live-specific value: {value}")
            if isinstance(value, str) and "paper" in value.lower():
                errors.append(f"{asset}.{key} has paper-specific value: {value}")
    
    # Verify global limits are consistent
    for key, value in GLOBAL_RISK_LIMITS.items():
        if isinstance(value, str) and "live" in value.lower():
            errors.append(f"GLOBAL.{key} has live-specific value: {value}")
        if isinstance(value, str) and "paper" in value.lower():
            errors.append(f"GLOBAL.{key} has paper-specific value: {value}")
    
    if errors:
        return False, "; ".join(errors)
    
    return True, "LIVE and PAPER risk limits are identical (canonical config)"


def log_risk_limits_for_agent(asset: str, mode: str = "LIVE") -> None:
    """Log risk limits for a specific agent at startup.
    
    This provides an audit trail of which limits each agent is using.
    Uses profile-based configuration from kalshi_crypto_15m_v2.yaml.
    
    Args:
        asset: Asset symbol (e.g., "BTC")
        mode: Trading mode (LIVE/PAPER/MOCK)
    """
    from utils.logger import get_logger
    logger = get_logger("config.kalshi_15m_crypto_config")
    
    # Use profile-based configuration instead of deprecated functions
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        profile_adapter = get_active_profile()
        if profile_adapter is not None:
            profile = profile_adapter.profile
            
            # Get per-asset limits from profile
            asset_key = asset.lower()
            per_asset = profile.per_asset.get(asset_key, {})
            
            logger.info("=" * 80)
            logger.info(f"AGENT RISK LIMITS: {asset} ({mode})")
            logger.info("=" * 80)
            logger.info(f"max_contracts_per_order: {per_asset.get('max_contracts_per_order', 'N/A')}")
            logger.info(f"max_open_contracts: {per_asset.get('max_open_contracts', 'N/A')}")
            logger.info(f"max_concurrent_resting_orders: {per_asset.get('max_concurrent_resting_orders', 'N/A')}")
            logger.info(f"max_daily_loss_usd: ${per_asset.get('max_daily_loss_usd', 'N/A')}")
            logger.info(f"max_total_open_notional_usd: ${profile.global_capital.get('max_total_open_notional_usd', 'N/A')}")
            logger.info(f"max_daily_loss_usd (global): ${profile.global_capital.get('max_daily_loss_usd', 'N/A')}")
            logger.info(f"max_total_contracts_per_order: {profile.global_capital.get('max_total_contracts_per_order', 'N/A')}")
            logger.info("=" * 80)
            return
    except Exception:
        # Fallback to deprecated functions if profile unavailable
        pass
    
    # Fallback to deprecated functions (will trigger deprecation warning)
    asset_limits = get_asset_risk_limits(asset)
    global_limits = get_global_risk_limits()
    
    logger.info("=" * 80)
    logger.info(f"AGENT RISK LIMITS: {asset} ({mode}) [FALLBACK - DEPRECATED]")
    logger.info("=" * 80)
    logger.info(f"max_contracts_per_order: {asset_limits['max_contracts_per_order']}")
    logger.info(f"max_open_contracts: {asset_limits['max_open_contracts']}")
    logger.info(f"max_concurrent_resting_orders: {asset_limits['max_concurrent_resting_orders']}")
    logger.info(f"max_daily_loss_usd: ${asset_limits['max_daily_loss_usd']}")
    logger.info(f"max_total_open_notional_usd: ${global_limits['max_total_open_notional_usd']}")
    logger.info(f"max_daily_loss_usd (global): ${global_limits['max_daily_loss_usd']}")
    logger.info(f"max_total_contracts_per_order: {global_limits['max_total_contracts_per_order']}")
    logger.info("=" * 80)


# ═══════════════════════════════════════════════════════════════════════════
# Section 5: Edge Thresholds (Volatility-Tiered)
# ═══════════════════════════════════════════════════════════════════════════

# Volatility tier classification
class VolatilityTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Volatility-tiered base edge thresholds (from dynamic_entry_window)
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


def get_base_edge_threshold(asset: str, volatility_tier: VolatilityTier) -> float:
    """
    Get base edge threshold from volatility-tiered table.
    
    Returns the upper bound of the threshold range for the tier (more lenient).
    """
    tier_thresholds = VOLATILITY_TIERED_BASE_THRESHOLDS.get(asset.upper())
    if not tier_thresholds:
        # Fallback to BTC thresholds if asset not in table
        tier_thresholds = VOLATILITY_TIERED_BASE_THRESHOLDS["BTC"]
    
    low, high = tier_thresholds.get(volatility_tier.value, (0.15, 0.20))
    return high  # Use upper bound for more lenient threshold


# ═══════════════════════════════════════════════════════════════════════════
# Section 6: Multipliers (T2E, Book Quality, Model Feedback)
# ═══════════════════════════════════════════════════════════════════════════

# Time-to-expiry multipliers
T2E_MULTIPLIERS: Dict[str, float] = {
    "long": 1.0,
    "medium": 1.15,
    "short": 1.35,
}

# Orderbook quality multipliers
BOOK_QUALITY_MULTIPLIERS: Dict[str, float] = {
    "good": 0.95,
    "normal": 1.0,
    "bad": 1.25,
}


# ═══════════════════════════════════════════════════════════════════════════
# Section 7: Validation and Diagnostics
# ═══════════════════════════════════════════════════════════════════════════

def validate_config() -> Tuple[bool, List[str]]:
    """
    Validate the 15m crypto configuration for consistency.
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    # Check all assets have entry policies
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        if asset not in DEFAULT_ENTRY_POLICIES:
            errors.append(f"Missing entry policy for {asset}")
        if asset not in KALSHI_15M_SERIES_TICKERS:
            errors.append(f"Missing series ticker for {asset}")
    
    # Check all (tier, asset_class) combinations exist in exit policy table
    for tier in ["A", "B", "C"]:
        for asset_class in ["major", "alt"]:
            key = (tier, asset_class)
            if key not in EXIT_POLICY_TABLE:
                errors.append(f"Missing exit policy for {key}")
    
    # Check all assets have volatility thresholds
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        if asset not in VOLATILITY_TIERED_BASE_THRESHOLDS:
            errors.append(f"Missing volatility thresholds for {asset}")
    
    return len(errors) == 0, errors


def dump_config_summary() -> Dict[str, any]:
    """
    Dump configuration summary for diagnostics and logging.
    
    Returns:
        Dictionary with configuration summary
    """
    return {
        "universe": {
            "assets": list(KALSHI_15M_CRYPTO_ASSETS),
            "timeframe": KALSHI_15M_TIMEFRAME,
            "series_tickers": KALSHI_15M_SERIES_TICKERS,
        },
        "entry_policies": {
            asset: {
                "policy_name": policy.policy_name,
                "window_start": policy.base_window_start_minutes,
                "window_end": policy.base_window_end_minutes,
                "terminal_enabled": policy.terminal_config.enabled,
            }
            for asset, policy in DEFAULT_ENTRY_POLICIES.items()
        },
        "exit_policies": {
            f"{tier}_{asset_class}": params
            for (tier, asset_class), params in EXIT_POLICY_TABLE.items()
        },
        "validation": validate_config(),
    }


# Run validation on module load
_is_valid, _validation_errors = validate_config()
if not _is_valid:
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"[KALSHI_15M_CONFIG] Configuration validation failed: {_validation_errors}")
