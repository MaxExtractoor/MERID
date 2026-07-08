"""Unified order sizing for Kalshi 15m crypto trading.

This module provides a single source of truth for order size computation,
replacing hardcoded sizing (e.g., $1.00) with bankroll-aware, profile-based sizing.

The sizing function:
- Reads bankroll from live Kalshi balance
- Applies risk percentage from profile config
- Respects per-asset caps from profile
- Enforces global caps (max_single_order_pct, max_total_notional_pct)
- Returns integer contract count and computed notional

This is the ONLY place where order size is computed for 15m agents.
All other code should use this function or validate against its output.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.unified_sizing")

# Profile integration
try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    _PROFILE_AVAILABLE = True
except ImportError:
    _PROFILE_AVAILABLE = False
    logger.warning("[UNIFIED-SIZING] Profile adapter not available, using hardcoded values")

# Regime detection integration
try:
    from ops.regime_detection import get_regime_detector
    _REGIME_DETECTION_AVAILABLE = True
except ImportError:
    _REGIME_DETECTION_AVAILABLE = False
    logger.warning("[UNIFIED-SIZING] Regime detection not available, multipliers not applied")

# TTE regime integration
try:
    from merid.risk.tte_regime import get_tte_classifier
    _TTE_REGIME_AVAILABLE = True
except ImportError:
    _TTE_REGIME_AVAILABLE = False
    logger.warning("[UNIFIED-SIZING] TTE regime not available, multipliers not applied")


def _get_regime_position_size_multiplier() -> float:
    """Get position size multiplier from current regime constraints.
    
    This reads from ops.regime_detection.RegimeConstraints.position_size_multiplier.
    The multiplier reduces position sizes based on market regime risk:
    - TRENDING_BULL: 1.0 (normal)
    - TRENDING_BEAR: 0.7 (reduce in bear markets)
    - MEAN_REVERTING: 0.8 (moderate reduction)
    - HIGH_VOLATILITY: 0.4 (significant reduction)
    - CRISIS: 0.1 (minimal trading)
    - UNKNOWN: 1.0 (FIX: 2026-07-04 - Changed from 0.0 to 1.0 to prevent silent blocking)
    
    CRITICAL FIX: 2026-07-04 - Prevent silent blocking by regime detection
    Previous behavior: UNKNOWN regime returned 0.0 multiplier, blocking ALL trades
    New behavior: UNKNOWN regime returns 1.0 (allow trading with normal sizing)
    This prevents regime detection failures from silently blocking all trading
    
    CRITICAL FIX: 2026-07-06 - Added guard to prevent regime sizing from interfering with risk limits
    Regime sizing is DISABLED to prevent interference with 3% per asset / 5% per 15m window limits.
    If re-enabled in the future, this guard ensures:
    1. Multiplier is never <= 0.0 (would block all trades)
    2. Multiplier is clamped to safe range [0.1, 1.0]
    3. Exception handling prevents regime detection failures from blocking trading
    
    Returns:
        Multiplier between 0.0 and 1.0. Returns 1.0 if regime detection unavailable.
    """
    # CRITICAL: Regime sizing is DISABLED to prevent interference with risk limits
    # DISABLED REASON: Regime-based multipliers could cause oversizing beyond 3% per asset / 5% per 15m window limits
    # RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
    # RE-ENABLE REQUIREMENTS:
    #   1. Update kalshi_crypto_15m_risk_envelope.py to apply regime_multiplier to risk limits
    #   2. Ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
    #   3. Add validation to prevent regime_multiplier > 1.0 from causing oversizing
    #   4. Test with various regime multipliers to verify limits are respected
    return 1.0
    
    # The code below is preserved for future reference if regime sizing is re-enabled
    # It includes comprehensive guards to prevent silent blocking
    """
    if not _REGIME_DETECTION_AVAILABLE:
        return 1.0
    
    try:
        detector = get_regime_detector()
        constraints = detector.get_constraints()
        if constraints:
            multiplier = constraints.position_size_multiplier
            # CRITICAL FIX: Prevent 0.0 multiplier from blocking all trades
            if multiplier <= 0.0:
                logger.warning(
                    "[REGIME-SIZING] CRITICAL: Regime multiplier=%.2f would block all trades, forcing to 1.0",
                    multiplier
                )
                multiplier = 1.0
            # CRITICAL FIX: Clamp multiplier to safe range [0.1, 1.0]
            # This prevents extreme reductions that could interfere with risk limits
            if multiplier < 0.1:
                logger.warning(
                    "[REGIME-SIZING] CRITICAL: Regime multiplier=%.2f below safe minimum 0.1, clamping to 0.1",
                    multiplier
                )
                multiplier = 0.1
            if multiplier > 1.0:
                logger.warning(
                    "[REGIME-SIZING] CRITICAL: Regime multiplier=%.2f above safe maximum 1.0, clamping to 1.0",
                    multiplier
                )
                multiplier = 1.0
            return multiplier
    except Exception as e:
        logger.warning("[REGIME-SIZING] Failed to get regime multiplier: %s", e)
    
    return 1.0
    """


def _get_tte_position_size_multiplier(tte_seconds: Optional[float] = None) -> float:
    """Get position size multiplier from TTE regime.
    
    DISABLED: TTE sizing interferes with 3% per asset / 5% per 15m window limits.
    Always returns 1.0 to prevent TTE-based scaling from interfering with risk limits.
    
    This reads from merid.risk.tte_regime.TTERegimeConfig size multipliers:
    - NORMAL: 1.0 (normal)
    - APPROACHING: 0.75 (reduce as expiry approaches)
    - CRITICAL: 0.5 (significant reduction near expiry)
    - TERMINAL: 0.25 (minimal trading very close to expiry)
    
    Args:
        tte_seconds: Time to expiry in seconds. If None, returns 1.0.
    
    Returns:
        Multiplier between 0.0 and 1.0. Returns 1.0 if TTE regime unavailable or tte_seconds is None.
    """
    # CRITICAL: TTE sizing is DISABLED to prevent interference with risk limits
    # DISABLED REASON: Time-to-expiry multipliers could cause oversizing beyond 3% per asset / 5% per 15m window limits
    # RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
    # RE-ENABLE REQUIREMENTS:
    #   1. Update kalshi_crypto_15m_risk_envelope.py to apply tte_multiplier to risk limits
    #   2. Ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
    #   3. Add validation to prevent tte_multiplier > 1.0 from causing oversizing
    #   4. Test with various TTE values to verify limits are respected
    return 1.0


def _get_time_of_day_multiplier(asset: str) -> float:
    """
    Get time-of-day risk scaling multiplier.
    
    CURRENT STATUS: DISABLED via profile YAML (time_of_day_risk_scaling.enabled: false)
    This function returns 1.0 (no scaling) when disabled.
    
    FUTURE RE-ENABLEMENT: When re-enabling, must:
      1. Update kalshi_crypto_15m_risk_envelope.py to apply time_of_day_multiplier to risk limits
      2. Ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
      3. Add validation to prevent time_of_day_multiplier > 1.0 from causing oversizing
      4. Test with various time-of-day multipliers to verify limits are respected
    
    Industry Research (LiquidView 2026):
    - Asian session (00:00-08:00 UTC): 15-30% wider spreads, 20-40% lower depth
    - European session (08:00-14:00 UTC): Competitive liquidity, near-daily tight spreads
    - US session (14:00-22:00 UTC): Peak liquidity, deepest books, lowest execution cost
    - Late Asian/early Pacific (22:00-00:00 UTC): Liquidity trough, highest execution costs
    
    Profile YAML multipliers (when enabled):
    - US market: 1.0 (100% risk during peak liquidity)
    - European: 0.9 (90% risk during good liquidity)
    - Asian: 0.8 (80% risk during lower liquidity)
    - Weekend: 0.8 (80% risk during reduced liquidity)
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
    
    Returns:
        Multiplier between 0.5 and 1.0. Returns 1.0 if disabled or on error.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        profile_adapter = get_active_profile()
        if not profile_adapter or not profile_adapter._profile:
            return 1.0
        
        profile = profile_adapter._profile
        if not profile.time_of_day_risk_scaling_enabled:
            # DISABLED: Return 1.0 (no scaling) when feature is disabled in YAML
            return 1.0
        
        # If enabled, read from profile and apply session-based logic
        from datetime import datetime, timezone
        current_utc_hour = datetime.now(timezone.utc).hour
        current_utc_minute = datetime.now(timezone.utc).minute
        current_time_utc = current_utc_hour + current_utc_minute / 60.0
        
        # Parse session windows from profile (format: "HH:MM-HH:MM ET")
        # Convert ET to UTC (ET = UTC-4 or UTC-5 depending on DST)
        # For simplicity, assume ET = UTC-4 (daylight time)
        et_offset = 4
        
        def parse_time_range(time_str: str) -> tuple[float, float]:
            """Parse 'HH:MM-HH:MM ET' to UTC hours."""
            # Strip ' ET' suffix if present
            time_str = time_str.replace(' ET', '')
            start_str, end_str = time_str.split('-')
            start_h, start_m = map(int, start_str.split(':'))
            end_h, end_m = map(int, end_str.split(':'))
            start_utc = (start_h + et_offset) % 24
            end_utc = (end_h + et_offset) % 24
            return start_utc + start_m / 60.0, end_utc + end_m / 60.0
        
        us_market_start, us_market_end = parse_time_range(profile.time_of_day_risk_scaling_us_market_hours)
        asian_start, asian_end = parse_time_range(profile.time_of_day_risk_scaling_asian_session)
        european_start, european_end = parse_time_range(profile.time_of_day_risk_scaling_european_session)
        
        # Determine current session
        in_us_market = us_market_start <= current_time_utc < us_market_end
        in_asian = asian_start <= current_time_utc < asian_end
        in_european = european_start <= current_time_utc < european_end
        
        # Check if weekend (Saturday/Sunday in UTC)
        is_weekend = datetime.now(timezone.utc).weekday() >= 5
        
        # Apply multiplier based on session
        if is_weekend:
            multiplier = profile.time_of_day_risk_scaling_weekend_multiplier
        elif in_us_market:
            multiplier = profile.time_of_day_risk_scaling_us_market_multiplier
        elif in_asian:
            multiplier = profile.time_of_day_risk_scaling_asian_multiplier
        elif in_european:
            multiplier = profile.time_of_day_risk_scaling_european_multiplier
        else:
            multiplier = 1.0
        
        # Validate multiplier is within safe bounds (0.5 to 1.0)
        multiplier = max(0.5, min(1.0, multiplier))
        
        logger.info(
            "[TIME-OF-DAY-SCALING] asset=%s time_utc=%.2f multiplier=%.2f",
            asset, current_time_utc, multiplier
        )
        return multiplier
    except Exception as e:
        logger.warning("[TIME-OF-DAY-SCALING] asset=%s failed to get multiplier: %s", asset, e)
        return 1.0


# =============================================================================
# Venue-Aware Minimum Notional
# =============================================================================

def compute_min_notional_for_venue(
    venue: str = "kalshi",
    contract_ticker: Optional[str] = None,
    price_cents: Optional[int] = None,
) -> Decimal:
    """Compute minimum notional requirement from venue/contract metadata.
    
    This function centralizes min_notional calculation to avoid hardcoded constants.
    For Kalshi, the minimum notional is DYNAMIC based on contract price - aligned with
    the 1-contract-per-order rule and the 10c minimum contract price floor.
    
    HARD RULE (2026-07-06): Agents place 1 contract per order. The min_notional
    must be equal to the contract notional itself (price_cents / 100) to ensure
    a single contract always satisfies the minimum notional requirement.
    
    This prevents rejection of low-priced contracts (1c-9c) when they are valid
    entries in the 10-75c sweet spot range.
    
    Args:
        venue: Venue name (e.g., "kalshi")
        contract_ticker: Optional contract ticker for contract-specific rules
        price_cents: Optional price in cents for dynamic calculation
        
    Returns:
        Minimum notional in USD as Decimal. Returns 0.0 if no constraint.
    """
    # Kalshi-specific rules
    if venue.lower() == "kalshi":
        # CRITICAL FIX: Dynamic min_notional based on actual contract price
        # With 1-contract-per-order rule, min_notional = contract_notional
        # This ensures single contract orders always pass min_notional validation
        if price_cents is not None and price_cents > 0:
            # Min notional = cost of 1 contract at this price
            return Decimal(str(price_cents)) / Decimal("100")
        else:
            # Fallback: use 10c minimum price floor = $0.10
            return Decimal("0.10")
    
    # For other venues or if venue metadata is unavailable, return 0.0 (no constraint)
    # This allows the sizing function to proceed without a min_notional floor
    return Decimal("0.0")


# =============================================================================
# Configuration Sources
# =============================================================================

def _get_bankroll_cap_pct() -> Decimal:
    """Get bankroll cap percentage from profile config.
    
    This reads from kalshi_crypto_15m.yaml venue.bankroll_cap_pct.
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error(
            "[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production - "
            "profile initialization failed, order sizing unavailable"
        )
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.venue_bankroll_cap_pct))
        else:
            logger.error(
                "[UNIFIED-SIZING] Profile not active - cannot size orders in production - "
                "profile not activated, order sizing unavailable"
            )
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read bankroll_cap_pct from profile: %s - "
            "profile read failed, order sizing unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}") from e


def _get_per_asset_risk_pct(asset: str) -> Optional[Decimal]:
    """Get per-asset risk percentage from profile config.
    
    This reads from kalshi_crypto_15m.yaml per-asset max_notional_pct.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE", or "BTC15M", "ETH15M", etc.)
    
    Returns:
        Risk percentage as Decimal, or None to use global cap
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error(
            "[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production - "
            "profile initialization failed, per-asset risk pct unavailable"
        )
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            
            # CRITICAL FIX: Normalize asset name by stripping "15M" suffix
            # Profile config uses keys like "BTC", "ETH", "SOL", "XRP", "DOGE"
            # But callers may pass "BTC15M", "ETH15M", etc.
            asset_normalized = asset.replace("15M", "") if asset.endswith("15M") else asset
            
            asset_config = profile.asset_configs.get(asset_normalized)
            if asset_config:
                return Decimal(str(asset_config.max_notional_pct))
            else:
                logger.warning(
                    "[UNIFIED-SIZING] Asset %s (normalized to %s) not in profile config, using global cap",
                    asset, asset_normalized
                )
                return None
        else:
            logger.error(
                "[UNIFIED-SIZING] Profile not active - cannot size orders in production - "
                "profile not activated, per-asset risk pct unavailable"
            )
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read per-asset risk pct from profile: %s - "
            "profile read failed, per-asset risk pct unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}") from e
    
    return None


def _get_fractional_contract_override_threshold() -> float:
    """Get fractional contract override threshold from profile config.
    
    This reads from kalshi_crypto_15m.yaml fractional_contract_override_threshold.
    Controls whether to allow 1 contract when max_notional is close to contract cost.
    
    Returns:
        Threshold as float (e.g., 0.5 for 50%). Returns 0.0 to disable override.
    
    PRODUCTION: If profile is unavailable, returns 0.0 (override disabled).
    """
    if not _PROFILE_AVAILABLE:
        return 0.0  # Disable override if profile unavailable
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            # Read from profile object (fractional_contract_override_threshold)
            if hasattr(profile, 'fractional_contract_override_threshold'):
                return float(profile.fractional_contract_override_threshold)
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read fractional_contract_override_threshold: %s", e)
    
    return 0.0  # Default to disabled


def _get_max_single_order_pct() -> Decimal:
    """Get max single order percentage from profile config.
    
    This reads from kalshi_crypto_15m.yaml venue.max_single_order_pct.
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error(
            "[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production - "
            "profile initialization failed, max single order pct unavailable"
        )
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.venue_max_single_order_pct))
        else:
            logger.error(
                "[UNIFIED-SIZING] Profile not active - cannot size orders in production - "
                "profile not activated, max single order pct unavailable"
            )
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read max_single_order_pct from profile: %s - "
            "profile read failed, max single order pct unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}") from e


def _get_max_contracts_per_asset(asset: str) -> int:
    """Get max contracts per asset from profile config.
    
    This reads from kalshi_crypto_15m.yaml per-asset max_contracts.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE", or "BTC15M", "ETH15M", etc.)
    
    Returns:
        Max contracts for this asset
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error(
            "[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production - "
            "profile initialization failed, max contracts unavailable"
        )
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            
            # CRITICAL FIX: Normalize asset name by stripping "15M" suffix
            # Profile config uses keys like "BTC", "ETH", "SOL", "XRP", "DOGE"
            # But callers may pass "BTC15M", "ETH15M", etc.
            asset_normalized = asset.replace("15M", "") if asset.endswith("15M") else asset
            
            asset_config = profile.asset_configs.get(asset_normalized)
            if asset_config:
                return asset_config.max_contracts
            # If asset not in profile, use a conservative default
            logger.warning("[UNIFIED-SIZING] Asset %s (normalized to %s) not in profile config, using default max_contracts=1", asset, asset_normalized)
            return 1  # CRITICAL FIX (2026-07-08): Reduced from 10 to 1 to enforce 3% risk limit
        else:
            logger.error(
                "[UNIFIED-SIZING] Profile not active - cannot size orders in production - "
                "profile not activated, max contracts unavailable"
            )
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read max_contracts from profile: %s - "
            "profile read failed, max contracts unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}") from e


def _get_per_trade_risk_pct() -> Decimal:
    """Get per-trade risk percentage from profile config.
    
    This reads from kalshi_crypto_15m.yaml guardrails.per_trade_risk_pct.
    This is the dedicated per-trade risk control for sizing (not to be confused with edge thresholds).
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error(
            "[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production - "
            "profile initialization failed, per-trade risk pct unavailable"
        )
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.guardrails_per_trade_risk_pct))
        else:
            logger.error(
                "[UNIFIED-SIZING] Profile not active - cannot size orders in production - "
                "profile not activated, per-trade risk pct unavailable"
            )
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read per_trade_risk_pct from profile: %s - "
            "profile read failed, per-trade risk pct unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}") from e


def _is_dynamic_sizing_enabled() -> bool:
    """Check if dynamic position sizing is enabled from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.enabled.
    
    Returns:
        True if dynamic sizing is enabled, False otherwise.
    """
    if not _PROFILE_AVAILABLE:
        return False  # Disable if profile unavailable
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_enabled
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_enabled: %s", e)
    
    return False


def _get_dynamic_sizing_base_contracts() -> int:
    """Get base contracts for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.base_contracts.
    
    Returns:
        Base contracts as int.
    """
    if not _PROFILE_AVAILABLE:
        return 1  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_base_contracts
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_base_contracts: %s", e)
    
    return 1  # Default


def _get_dynamic_sizing_edge_multiplier() -> float:
    """Get edge multiplier for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.edge_multiplier.
    
    Returns:
        Edge multiplier as float.
    """
    if not _PROFILE_AVAILABLE:
        return 2.0  # 2026-07-05: Updated default from 0.5 to 2.0 based on Turbine research
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_edge_multiplier
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_edge_multiplier: %s", e)
    
    return 2.0  # 2026-07-05: Updated default from 0.5 to 2.0 based on Turbine research


def _get_dynamic_sizing_confidence_multiplier() -> float:
    """Get confidence multiplier for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.confidence_multiplier.
    
    Returns:
        Confidence multiplier as float.
    """
    if not _PROFILE_AVAILABLE:
        return 1.0  # 2026-07-05: Updated default from 0.3 to 1.0 based on Turbine research
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_confidence_multiplier
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_confidence_multiplier: %s", e)
    
    return 1.0  # 2026-07-05: Updated default from 0.3 to 1.0 based on Turbine research


def _get_dynamic_sizing_max_contracts() -> int:
    """Get max contracts for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.max_contracts.
    
    Returns:
        Max contracts as int.
    """
    if not _PROFILE_AVAILABLE:
        return 1  # CRITICAL FIX (2026-07-08): Reduced from 3 to 1 to enforce 3% risk limit
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_max_contracts
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_max_contracts: %s", e)
    
    return 1  # CRITICAL FIX (2026-07-08): Reduced from 3 to 1 to enforce 3% risk limit


def _get_dynamic_sizing_min_contracts() -> int:
    """Get min contracts for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.min_contracts.
    
    Returns:
        Min contracts as int.
    """
    if not _PROFILE_AVAILABLE:
        return 1  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_min_contracts
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_min_contracts: %s", e)
    
    return 1  # Default


# =============================================================================
# Unified Sizing Function
# =============================================================================

def compute_order_size(
    bankroll_usd: Decimal,
    price_cents: int,
    asset: str,
    edge_pct: Optional[Decimal] = None,
    confidence: Optional[Decimal] = None,
    consider_fee_impact: bool = False,
    estimated_fee_cents: Optional[int] = None,
    min_notional_usd: Optional[Decimal] = None,
    min_contracts: Optional[int] = None,
    max_notional_usd: Optional[Decimal] = None,  # NEW: explicit max_notional from profile
    time_of_day_multiplier: float = 1.0,  # 2026 Research-Based Risk Management: Time-of-day risk scaling
    tte_seconds: Optional[float] = None,  # Time to expiry in seconds for TTE regime multiplier
) -> Tuple[int, Decimal, dict]:
    """Compute order size from bankroll, risk percentage, and market constraints.
    
    This is the SINGLE SOURCE OF TRUTH for order sizing in 15m agents.
    All other sizing logic should be removed or deprecated.
    
    Formula:
        1. If max_notional_usd is provided, use it directly (from profile per-asset cap)
           Otherwise, compute effective risk_pct as min of:
           - min_edge_risk_pct from profile (repurposed from guardrails.min_post_fee_edge)
           - max_single_order_pct from profile (5%)
           - MERID_BANKROLL_CAP_PCT from env (global safety ceiling, default 2%)
           - per-asset risk_pct from profile (if available)
           Then compute max_notional = bankroll_usd × risk_pct
        
        2. If consider_fee_impact=True, subtract estimated fee from max_notional
        
        3. Apply per-asset max contracts cap from profile
        
        4. Convert max_notional to integer contract count:
           contract_notional = price_cents / 100.0
           contracts_from_notional = floor(max_notional / contract_notional)
        
        5. Validate against min_notional_usd and min_contracts (from KalshiRiskConfig)
           If computed count would result in notional below min_notional, reject the trade
        
        6. Return count and computed notional
    
    Example with bankroll=$36.58, risk_pct=0.02, price_cents=50:
        max_notional = $36.58 × 0.02 = $0.73
        contract_notional = $0.50
        contracts_from_notional = floor(0.73 / 0.50) = floor(1.46) = 1
        count = 1
        notional = 1 × $0.50 = $0.50 ✅ (within cap)
    
    Args:
        bankroll_usd: Current bankroll in USD (from Kalshi API)
        price_cents: Price per contract in cents (0-99)
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
    
    Returns:
        Tuple of (count, notional_usd, metadata_dict)
    
    Raises:
        ValueError: If price_cents <= 0 (invalid price)
    """
    # CRITICAL: Guard against invalid price (price=0 causes notional=0)
    if price_cents <= 0:
        logger.error(
            "[UNIFIED-SIZING] INVALID_PRICE: price_cents=%d for asset=%s - "
            "cannot size order with zero/negative price, order sizing failed",
            price_cents, asset
        )
        raise ValueError(f"Invalid price_cents={price_cents} for asset={asset} - must be > 0")
    
    # CRITICAL FIX (2026-07-07): Removed redundant window limit check from unified_sizing.py
    # Window limits are now enforced ONLY in order_gate.py with ACTUAL order notional
    # Previous check here used a conservative 3% estimate that could block valid orders
    # The proper enforcement point is order_gate.py which uses real contract count and price
    # This eliminates the estimate vs actual notional conflict and prevents false rejections
    
    # INTENTIONAL WRAPPER: This function is NOT a pure delegation to invariants.py.
    # It owns specific policy concerns while delegating pure sizing math:
    #
    # OWNED BY THIS WRAPPER:
    # - Risk pct interlock logic (min_edge_risk_pct, max_single_order_pct, bankroll_cap_pct)
    # - Fee adjustment on max_notional (consider_fee_impact)
    # - Position-aware sizing (queries position_cache, reduces max_notional based on existing exposure)
    # - Per-asset max contracts cap enforcement
    #
    # DELEGATED TO invariants.py (pure math):
    # - compute_max_notional: bankroll × risk_pct with floor
    # - compute_contracts: notional → contract count with override threshold
    # - is_trade_valid: notional vs max_risk_pct validation
    #
    # This separation is intentional: invariants.py owns pure Kalshi contract math,
    # while unified_sizing.py owns MERID-specific risk policy and position management.
    from merid.event_venues.kalshi.invariants import compute_max_notional, compute_contracts, is_trade_valid
    
    # Step 1: Use provided max_notional_usd if available, otherwise compute from risk_pct
    if max_notional_usd is not None:
        # Use explicit max_notional from profile (per-asset cap with floor applied)
        max_notional_usd = Decimal(str(max_notional_usd))
        risk_pct_effective = max_notional_usd / bankroll_usd if bankroll_usd > 0 else Decimal("0")
        per_asset_risk_pct = None  # Not used when max_notional is explicit
        logger.info(
            "[SIZE-COMPUTE] Using explicit max_notional from profile: bankroll=%.2f max_notional=%.2f risk_pct=%.4f asset=%s",
            float(bankroll_usd), float(max_notional_usd), float(risk_pct_effective), asset
        )
    else:
        # Compute effective risk_pct
        # Interlock rule: risk_pct_for_sizing = min(per_trade_risk_pct, max_single_order_pct, bankroll_cap_pct)
        per_trade_risk_pct = _get_per_trade_risk_pct()  # from profile guardrails.per_trade_risk_pct (dedicated sizing control)
        max_single_order_pct = _get_max_single_order_pct()  # from profile venue.max_single_order_pct
        bankroll_cap_pct = _get_bankroll_cap_pct()  # from profile venue.bankroll_cap_pct
        per_asset_risk_pct = _get_per_asset_risk_pct(asset)  # per-asset from profile (optional)
        
        risk_pct_candidates = [per_trade_risk_pct, max_single_order_pct, bankroll_cap_pct]
        if per_asset_risk_pct is not None:
            risk_pct_candidates.append(per_asset_risk_pct)
        
        risk_pct_effective = min(risk_pct_candidates)
        
        # Step 2: Compute max_notional from bankroll and effective risk_pct
        max_notional_usd = bankroll_usd * risk_pct_effective
        
        logger.info(
            "[SIZE-COMPUTE] Computed max_notional from risk_pct: bankroll=%.2f risk_pct=%.4f max_notional=%.2f asset=%s "
            "(candidates: per_trade=%.4f, max_single=%.4f, bankroll_cap=%.4f, per_asset=%s)",
            float(bankroll_usd), float(risk_pct_effective), float(max_notional_usd), asset,
            float(per_trade_risk_pct), float(max_single_order_pct), float(bankroll_cap_pct),
            f"{float(per_asset_risk_pct):.4f}" if per_asset_risk_pct else "None"
        )
    
    # Step 2.5: Apply fee impact if requested
    fee_adjusted = False
    if consider_fee_impact and estimated_fee_cents is not None:
        fee_usd = Decimal(estimated_fee_cents) / Decimal("100")
        if fee_usd > 0 and max_notional_usd > fee_usd:
            max_notional_usd = max_notional_usd - fee_usd
            fee_adjusted = True
            logger.info(
                f"[UNIFIED-SIZING] Fee-aware sizing: subtracted ${fee_usd:.2f} fee from max_notional, "
                f"new max_notional=${max_notional_usd:.2f}"
            )
    
    # Step 3: Get per-asset max contracts cap
    max_contracts_cap = _get_max_contracts_per_asset(asset)
    
    # Step 4: Apply dynamic position sizing if enabled
    # Scale position size based on edge and confidence
    dynamic_sizing_multiplier = 1.0  # Default: no scaling
    if _is_dynamic_sizing_enabled():
        edge_pct = edge_pct if edge_pct is not None else 0.0
        confidence = confidence if confidence is not None else 0.5
        
        # Get dynamic sizing parameters from profile
        base_contracts = _get_dynamic_sizing_base_contracts()
        edge_multiplier = _get_dynamic_sizing_edge_multiplier()
        confidence_multiplier = _get_dynamic_sizing_confidence_multiplier()
        max_contracts = _get_dynamic_sizing_max_contracts()
        min_contracts = _get_dynamic_sizing_min_contracts()
        
        # Calculate dynamic size: base + (edge × edge_multiplier) + (confidence × confidence_multiplier)
        # Convert Decimal to float for multiplication with float multipliers
        edge_pct_float = float(edge_pct) if edge_pct is not None else 0.0
        confidence_float = float(confidence) if confidence is not None else 0.5
        dynamic_size = base_contracts + (edge_pct_float * 100 * edge_multiplier) + (confidence_float * 100 * confidence_multiplier)
        dynamic_size = max(min_contracts, min(max_contracts, int(dynamic_size)))
        
        # Calculate multiplier to apply to notional
        # If dynamic_size > 1, we want to increase notional proportionally
        dynamic_sizing_multiplier = float(dynamic_size) / float(base_contracts)
        
        logger.info(
            "[DYNAMIC-SIZING] edge=%.4f confidence=%.4f base=%d edge_mult=%.2f conf_mult=%.2f "
            "dynamic_size=%d multiplier=%.2f asset=%s",
            edge_pct, confidence, base_contracts, edge_multiplier, confidence_multiplier,
            dynamic_size, dynamic_sizing_multiplier, asset
        )
        
        # Apply multiplier to max_notional
        max_notional_usd = max_notional_usd * Decimal(str(dynamic_sizing_multiplier))
    
    # Step 4.5: Apply time-of-day risk scaling multiplier
    # CRITICAL: Use _get_time_of_day_multiplier to ensure consistency with profile YAML
    # This replaces the direct time_of_day_multiplier parameter with profile-driven logic
    actual_time_of_day_multiplier = _get_time_of_day_multiplier(asset)
    if actual_time_of_day_multiplier != 1.0:
        max_notional_usd = max_notional_usd * Decimal(str(actual_time_of_day_multiplier))
        logger.info(
            "[TIME-OF-DAY-SCALING] Applied multiplier=%.2f to max_notional for asset=%s (new max_notional=%.2f)",
            actual_time_of_day_multiplier, asset, float(max_notional_usd)
        )
    
    # Step 4.6: Apply regime-based position size multiplier
    # CRITICAL FIX: Apply ops.regime_detection.RegimeConstraints.position_size_multiplier
    # This reduces position sizes based on market regime risk (BEAR, HIGH_VOLATILITY, CRISIS)
    regime_multiplier = _get_regime_position_size_multiplier()
    if regime_multiplier != 1.0:
        max_notional_usd = max_notional_usd * Decimal(str(regime_multiplier))
        logger.info(
            "[REGIME-SIZING] Applied regime multiplier=%.2f to max_notional for asset=%s (new max_notional=%.2f)",
            regime_multiplier, asset, float(max_notional_usd)
        )
    
    # Step 4.7: Apply TTE-based position size multiplier
    # CRITICAL FIX: Apply merid.risk.tte_regime.TTERegimeConfig size multipliers
    # This reduces position sizes as contracts approach expiry
    tte_multiplier = _get_tte_position_size_multiplier(tte_seconds)
    if tte_multiplier != 1.0:
        max_notional_usd = max_notional_usd * Decimal(str(tte_multiplier))
        logger.info(
            "[TTE-SIZING] Applied TTE multiplier=%.2f to max_notional for asset=%s (new max_notional=%.2f)",
            tte_multiplier, asset, float(max_notional_usd)
        )
    
    # Step 5: Check existing positions for position-aware sizing
    # CRITICAL FIX: DISABLED to prevent interference with window-based risk limits
    # Position-aware sizing reduces max_notional based on existing positions, which conflicts
    # with the 3% per-agent / 5% total venue per 15-minute window limits. The window-based
    # limits are the single source of truth for risk enforcement, and position-aware sizing
    # could allow agents to bypass window limits by reducing max_notional after positions are closed.
    # RE-ENABLE REQUIREMENTS:
    #   1. Update kalshi_crypto_15m_risk_envelope.py to account for position-aware sizing
    #   2. Ensure 3% per agent / 5% per 15m window limits are still respected after reduction
    #   3. Add validation to prevent position-aware sizing from allowing window limit bypass
    #   4. Test with various position states to verify limits are respected
    #
    # DISABLED CODE (preserved for future reference):
    # existing_position_notional = Decimal("0")
    # try:
    #     from merid.event_venues.kalshi.position_cache import get_position_cache
    #     cache = get_position_cache()
    #     positions = cache.get_all_positions()
    #     
    #     # Sum existing positions for this asset (across all timeframes)
    #     for ticker, pos in positions.items():
    #         # Extract asset from ticker (e.g., KXBTC15M-... -> BTC)
    #         ticker_asset = None
    #         if "BTC" in ticker.upper():
    #             ticker_asset = "BTC"
    #         elif "ETH" in ticker.upper():
    #             ticker_asset = "ETH"
    #         elif "SOL" in ticker.upper():
    #             ticker_asset = "SOL"
    #         elif "XRP" in ticker.upper():
    #             ticker_asset = "XRP"
    #         elif "DOGE" in ticker.upper():
    #             ticker_asset = "DOGE"
    #         
    #         if ticker_asset == asset and hasattr(pos, 'contracts'):
    #             # Calculate notional from position using actual entry price
    #             # Use avg_price_cents from position if available, otherwise fallback to current price
    #             entry_price_cents = getattr(pos, 'avg_price_cents', None)
    #             if entry_price_cents and entry_price_cents > 0:
    #                 position_notional_usd = (Decimal(entry_price_cents) / Decimal("100")) * pos.contracts
    #             else:
    #                 # Fallback to current price if entry price unavailable
    #                 position_notional_usd = contract_notional_usd * pos.contracts
    #             existing_position_notional += position_notional_usd
    #     
    #     if existing_position_notional > 0:
    #         # Reduce max_notional by existing exposure
    #         available_notional = max_notional_usd - existing_position_notional
    #         if available_notional <= 0:
    #             logger.info(
    #                 "[SIZE-COMPUTE] Position-aware sizing: already at max exposure for %s (existing=%.2f, max=%.2f). Rejecting.",
    #                 asset, float(existing_position_notional), float(max_notional_usd)
    #             )
    #             return 0, Decimal("0"), {
    #                 "bankroll_usd": float(bankroll_usd),
    #                 "risk_pct_effective": float(risk_pct_effective),
    #                 "max_notional_usd": float(max_notional_usd),
    #                 "price_cents": price_cents,
    #                 "asset": asset,
    #                 "contracts_from_notional": 0,
    #                 "max_contracts_cap": max_contracts_cap,
    #                 "per_asset_risk_pct": per_asset_risk_pct,
    #                 "final_count": 0,
    #                 "final_notional_usd": 0.0,
    #                 "rejection_reason": "position_limit_exceeded"
    #             }
    #         max_notional_usd = available_notional
    #         logger.info(
    #             "[SIZE-COMPUTE] Position-aware sizing: reduced max_notional for %s from %.2f to %.2f (existing exposure: %.2f)",
    #             asset, float(max_notional_usd + existing_position_notional), float(max_notional_usd), float(existing_position_notional)
    #         )
    # except Exception as e:
    #     logger.warning("[SIZE-COMPUTE] Failed to check existing positions for position-aware sizing: %s", e)
    
    # Step 5: Convert max_notional to contract count
    contract_notional_usd = Decimal(price_cents) / Decimal("100")
    if contract_notional_usd == 0:
        # Avoid division by zero
        contracts_from_notional = 0
    else:
        contracts_from_notional = int(max_notional_usd / contract_notional_usd)
    
    # Step 5.5: Small bankroll override - allow 1 contract if max_notional is close to contract cost
    # This enables trading with small bankrolls where percentage-based caps are too restrictive
    # Only apply if:
    # - contracts_from_notional is 0 (can't afford 1 contract at percentage cap)
    # - max_notional is at least threshold % of contract cost (from config)
    # - max_contracts_cap allows at least 1 contract
    # - CRITICAL: contract_notional_usd must be >= minimum notional (prevent 1¢ orders)
    # Config: fractional_contract_override_threshold in kalshi_crypto_15m.yaml (default 0.5 = 50%)
    if contracts_from_notional == 0 and max_contracts_cap >= 1:
        # CRITICAL FIX: Reject override if contract cost is too low (prevents 1¢ orders)
        # Minimum contract notional should be at least $0.05 to avoid extreme leverage
        min_contract_notional_usd = Decimal("0.05")
        if contract_notional_usd < min_contract_notional_usd:
            logger.warning(
                "[SIZE-COMPUTE] Small bankroll override rejected: contract_notional=%.2f < min=%.2f (prevents extreme leverage/1¢ orders)",
                float(contract_notional_usd), float(min_contract_notional_usd)
            )
            # Don't override - keep contracts_from_notional = 0
        else:
            override_threshold = _get_fractional_contract_override_threshold()
            if override_threshold > 0 and max_notional_usd >= contract_notional_usd * Decimal(str(override_threshold)):
                contracts_from_notional = 1
                logger.info(
                    "[SIZE-COMPUTE] Small bankroll override: allowing 1 contract (max_notional=%.2f >= %.0f%% of contract_cost=%.2f)",
                    float(max_notional_usd), override_threshold * 100, float(contract_notional_usd)
                )
    
    # Step 6: Apply per-asset max contracts cap
    count = min(contracts_from_notional, max_contracts_cap)
    
    # Step 6: Validate against min_contracts and min_notional
    # For Kalshi, minimum notional is venue-specific (typically $1.00 for sanity check compliance)
    # We enforce this separately from caps to avoid the "mkt=0" issue
    if min_contracts is None:
        min_contracts = 1  # Default to 1 contract minimum
    
    # Compute notional for current count
    proposed_notional = count * contract_notional_usd
    
    # If count is 0, reject (return 0)
    if count == 0:
        logger.info(
            "[SIZE-COMPUTE] Undersized trade: count=0 (max_notional too small for 1 contract). Rejecting."
        )
        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "risk_pct_effective": float(risk_pct_effective),
            "max_notional_usd": float(max_notional_usd),
            "price_cents": price_cents,
            "asset": asset,
            "contracts_from_notional": contracts_from_notional,
            "max_contracts_cap": max_contracts_cap,
            "per_asset_risk_pct": float(per_asset_risk_pct) if per_asset_risk_pct else None,
            "final_count": 0,
            "final_notional_usd": 0.0,
            "rejection_reason": "undersized",
        }
    
    # Apply min_notional check - use venue-aware function if not provided
    # This is separate from caps - it's a venue requirement, not a risk limit
    if min_notional_usd is None:
        # Use venue-aware min_notional for Kalshi
        min_notional_usd = compute_min_notional_for_venue(venue="kalshi", contract_ticker=asset, price_cents=price_cents)
    else:
        min_notional_usd = Decimal(str(min_notional_usd))
    
    if min_notional_usd > 0 and proposed_notional > 0:
        if proposed_notional < min_notional_usd:
            # Try to bump up to minimum if within caps
            min_count_for_notional = int((min_notional_usd / contract_notional_usd).to_integral_value(rounding="ROUND_CEILING"))
            if min_count_for_notional <= max_contracts_cap and min_count_for_notional * contract_notional_usd <= max_notional_usd:
                count = min_count_for_notional
                proposed_notional = count * contract_notional_usd
                logger.info(
                    "[SIZE-COMPUTE] Bumped count to meet min_notional: %d -> %d (notional: %.2f -> %.2f)",
                    contracts_from_notional, count, float(count * contract_notional_usd), float(proposed_notional)
                )
            else:
                logger.info(
                    "[SIZE-COMPUTE] Cannot meet min_notional=%.2f with caps (max_notional=%.2f, max_contracts=%d). Rejecting.",
                    float(min_notional_usd), float(max_notional_usd), max_contracts_cap
                )
                return 0, Decimal("0"), {
                    "bankroll_usd": float(bankroll_usd),
                    "risk_pct_effective": float(risk_pct_effective),
                    "max_notional_usd": float(max_notional_usd),
                    "price_cents": price_cents,
                    "asset": asset,
                    "contracts_from_notional": contracts_from_notional,
                    "max_contracts_cap": max_contracts_cap,
                    "per_asset_risk_pct": float(per_asset_risk_pct) if per_asset_risk_pct else None,
                    "final_count": 0,
                    "final_notional_usd": 0.0,
                    "rejection_reason": "min_notional_not_met",
                }
    
    # Step 7: Ensure minimum order notional for sanity check compliance
    # Kalshi sanity check requires minimum notional of $1.00 per order
    # DISABLED: Minimum notional enforcement disabled to respect per-trade risk limits
    # The minimum notional check was causing count to increase beyond per-trade risk cap
    # For production, minimum notional should be enforced at the order router level
    # if needed, not in the sizing function which should respect risk limits
    # min_order_notional_usd = Decimal("1.00")
    # notional_usd = count * contract_notional_usd
    # if notional_usd > 0 and notional_usd < min_order_notional_usd:
    #     # Calculate minimum contracts needed to meet $1.00 notional
    #     min_count_for_notional = int((min_order_notional_usd / contract_notional_usd).to_integral_value(rounding="ROUND_CEILING"))
    #     # Only increase if within per-trade risk cap (max_notional_usd) and max contracts cap
    #     if min_count_for_notional * contract_notional_usd <= max_notional_usd and min_count_for_notional <= max_contracts_cap:
    #         count = min_count_for_notional
    
    # Compute final notional
    notional_usd = count * contract_notional_usd
    
    # Build metadata for logging
    metadata = {
        "bankroll_usd": float(bankroll_usd),
        "risk_pct_effective": float(risk_pct_effective),
        "max_notional_usd": float(max_notional_usd),
        "price_cents": price_cents,
        "fee_adjusted": fee_adjusted,
        "consider_fee_impact": consider_fee_impact,
        "asset": asset,
        "contracts_from_notional": contracts_from_notional,
        "max_contracts_cap": max_contracts_cap,
        "per_asset_risk_pct": float(per_asset_risk_pct) if per_asset_risk_pct else None,
        "final_count": count,
        "final_notional_usd": float(notional_usd),
    }
    
    # Log SIZE-COMPUTE
    logger.info(
        "[SIZE-COMPUTE] bankroll=%.2f risk_pct=%.4f max_notional=%.2f price=%dc asset=%s "
        "contracts_from_notional=%d max_contracts_cap=%d final_count=%d final_notional=%.2f",
        metadata["bankroll_usd"],
        metadata["risk_pct_effective"],
        metadata["max_notional_usd"],
        metadata["price_cents"],
        metadata["asset"],
        metadata["contracts_from_notional"],
        metadata["max_contracts_cap"],
        count,
        float(notional_usd),
    )
    
    return count, notional_usd, metadata
