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
        raise RuntimeError(f"Profile read failed: {e}")


def _get_kelly_multiplier(edge_pct: Optional[Decimal] = None) -> float:
    """Get Kelly multiplier from profile config based on edge band.
    
    This reads from kalshi_crypto_15m.yaml edge_bands configuration.
    Kelly multipliers are applied to reduce position size based on edge quality:
    - watch band (0.5% edge): 0.0x Kelly (no trading)
    - small band (0.5-1% edge): 0.25x Kelly (conservative)
    - standard band (>1% edge): 0.5x Kelly (standard)
    
    Args:
        edge_pct: Edge percentage (e.g., 0.02 for 2%). If None, returns 0.5x (standard).
    
    Returns:
        Kelly multiplier as float (e.g., 0.25 for quarter-Kelly).
    
    PRODUCTION: If profile is unavailable, returns 0.5x (standard fractional Kelly).
    """
    if not _PROFILE_AVAILABLE:
        logger.warning("[UNIFIED-SIZING] Profile adapter not available, using default Kelly multiplier 0.5x")
        return 0.5  # Default to 0.5x Kelly if profile unavailable
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Check if edge_bands are enabled
            if not hasattr(profile, 'edge_bands_enabled') or not profile.edge_bands_enabled:
                return 0.5  # Default to 0.5x Kelly if edge bands disabled
            
            # If edge_pct is not provided, use standard band multiplier
            if edge_pct is None:
                return 0.5
            
            edge_pct_float = float(edge_pct)
            
            # Determine edge band based on edge_pct
            # Watch band: 0.5% edge (0.005)
            if edge_pct_float <= 0.005:
                return 0.0  # No trading in watch band
            # Small band: 0.5-1% edge (0.005-0.01)
            elif edge_pct_float <= 0.01:
                return 0.25  # 0.25x Kelly for small band
            # Standard band: >1% edge (>0.01)
            else:
                return 0.5  # 0.5x Kelly for standard band
        else:
            logger.warning("[UNIFIED-SIZING] Profile not active, using default Kelly multiplier 0.5x")
            return 0.5
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read Kelly multiplier from profile: %s, using default 0.5x", e)
        return 0.5  # Default to 0.5x Kelly on error from e


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
    """Compute order size using fixed $1 total exposure model (2026-07-08).
    
    This is the SINGLE SOURCE OF TRUTH for order sizing in 15m agents.
    All percentage-based sizing has been removed in favor of fixed $1 total exposure.
    
    Formula:
        1. Use fixed $1 exposure cap from profile (fixed_exposure_cap_usd)
        2. Check existing total exposure from position_cache
        3. Available exposure = $1 - existing_exposure
        4. If available_exposure >= contract_cost, allow 1 contract
        5. Otherwise, reject (no slots available)
    
    Example with existing_exposure=$0.65, price_cents=35:
        available_exposure = $1.00 - $0.65 = $0.35
        contract_cost = $0.35
        available_exposure >= contract_cost → allow 1 contract
        new_total_exposure = $0.65 + $0.35 = $1.00 ✅ (at cap)
    
    Args:
        bankroll_usd: Current bankroll in USD (from Kalshi API) - kept for compatibility
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
    
    # 2026-07-08 UPDATE: Fixed $1 total exposure model - slot-based position management
    # All percentage-based sizing has been removed
    # New model: sum of all contract prices must be ≤ $1
    
    # Step 1: Get fixed $1 exposure cap from profile
    fixed_exposure_cap_usd = Decimal("1.00")  # Default
    if _PROFILE_AVAILABLE and is_profile_active():
        adapter = get_active_profile()
        profile = adapter.profile
        fixed_exposure_cap_usd = Decimal(str(profile.risk_policy_fixed_exposure_cap_usd))
    
    # Step 2: Get existing total exposure from position_cache
    existing_exposure_usd = Decimal("0")
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        position_cache = get_position_cache()
        existing_exposure_usd = Decimal(str(position_cache.get_total_exposure_usd()))
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to get existing exposure: %s", e)
    
    # Step 3: Calculate available exposure
    available_exposure_usd = fixed_exposure_cap_usd - existing_exposure_usd
    
    # Step 4: Calculate contract cost
    contract_cost_usd = Decimal(price_cents) / Decimal("100")
    
    # Step 5: Check if we have enough exposure slot
    if available_exposure_usd < contract_cost_usd:
        logger.info(
            "[UNIFIED-SIZING] Insufficient exposure slot: available=%.2f, needed=%.2f, existing=%.2f, cap=%.2f asset=%s",
            float(available_exposure_usd), float(contract_cost_usd), float(existing_exposure_usd),
            float(fixed_exposure_cap_usd), asset
        )
        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "price_cents": price_cents,
            "asset": asset,
            "reason": "insufficient_exposure_slot",
            "available_exposure_usd": float(available_exposure_usd),
            "contract_cost_usd": float(contract_cost_usd),
            "existing_exposure_usd": float(existing_exposure_usd),
        }
    
    # Step 6: Allow 1 contract (slot-based)
    contract_count = 1
    order_notional_usd = contract_cost_usd
    
    # Step 7: Get per-asset max contracts cap (should be 1)
    max_contracts_cap = _get_max_contracts_per_asset(asset)
    contract_count = min(contract_count, max_contracts_cap)
    
    logger.info(
        "[UNIFIED-SIZING] Slot-based sizing: asset=%s price=%dc cost=$%.2f "
        "existing_exposure=$%.2f available=$%.2f cap=$%.2f contracts=%d",
        asset, price_cents, float(contract_cost_usd), float(existing_exposure_usd),
        float(available_exposure_usd), float(fixed_exposure_cap_usd), contract_count
    )
    
    # Step 8: Validate min_notional and min_contracts if provided
    if min_notional_usd is not None and order_notional_usd < min_notional_usd:
        logger.info(
            "[UNIFIED-SIZING] Undersized trade: notional=%.2f < min_notional=%.2f. Rejecting.",
            float(order_notional_usd), float(min_notional_usd)
        )
        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "price_cents": price_cents,
            "asset": asset,
            "reason": "below_min_notional",
            "order_notional_usd": float(order_notional_usd),
            "min_notional_usd": float(min_notional_usd),
        }
    
    if min_contracts is not None and contract_count < min_contracts:
        logger.info(
            "[UNIFIED-SIZING] Undersized trade: count=%d < min_contracts=%d. Rejecting.",
            contract_count, min_contracts
        )
        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "price_cents": price_cents,
            "asset": asset,
            "reason": "below_min_contracts",
            "contract_count": contract_count,
            "min_contracts": min_contracts,
        }
    
    # Return result
    metadata = {
        "bankroll_usd": float(bankroll_usd),
        "price_cents": price_cents,
        "asset": asset,
        "contract_count": contract_count,
        "order_notional_usd": float(order_notional_usd),
        "existing_exposure_usd": float(existing_exposure_usd),
        "available_exposure_usd": float(available_exposure_usd),
        "fixed_exposure_cap_usd": float(fixed_exposure_cap_usd),
    }
    
    logger.info(
        "[UNIFIED-SIZING] Final sizing: asset=%s contracts=%d notional=$%.2f price=%dc "
        "total_exposure_after=$%.2f",
        asset, contract_count, float(order_notional_usd), price_cents,
        float(existing_exposure_usd + order_notional_usd)
    )
    
    return contract_count, order_notional_usd, metadata
