"""Unified order sizing for Kalshi 15m crypto trading.

This module provides a single source of truth for order size computation
under the fixed $1 total exposure model (global slot allocator).

The sizing function:
- Applies Kelly-criterion edge filtering (rejects no-edge trades)
- Reads existing exposure from the global slot allocator ($1 cap authority)
- Allows up to the configured per-asset max (2 in production) while staying inside the $1 cap
- Returns integer contract count and computed notional

2026-07-16: All percentage-based sizing (bankroll_cap_pct, per-asset
max_notional_pct, max_single_order_pct, per_trade_risk_pct) has been PRUNED.
The $1 global slot allocator (merid/risk/global_slot_allocator.py) is the
single source of truth for exposure allocation.

This is the ONLY place where order size is computed for 15m agents.
All other code should use this function or validate against its output.
"""

from __future__ import annotations

import math
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

# Fee integration (all-in cost / EV)
try:
    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_per_contract_cents
    _FEES_AVAILABLE = True
except ImportError:
    _FEES_AVAILABLE = False
    calculate_kalshi_fee_per_contract_cents = None  # type: ignore
    logger.warning("[UNIFIED-SIZING] Fee module not available, fee-aware Kelly disabled")

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
    Regime sizing is DISABLED to prevent interference with the $1 fixed exposure model.
    If re-enabled in the future, this guard ensures:
    1. Multiplier is never <= 0.0 (would block all trades)
    2. Multiplier is clamped to safe range [0.1, 1.0]
    3. Exception handling prevents regime detection failures from blocking trading
    
    Returns:
        Multiplier between 0.0 and 1.0. Returns 1.0 if regime detection unavailable.
    """
    # CRITICAL: Regime sizing is DISABLED to prevent interference with risk limits
    # DISABLED REASON: Regime-based multipliers could cause oversizing beyond the $1 global slot allocator cap
    # RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
    # RE-ENABLE REQUIREMENTS:
    #   1. Update kalshi_crypto_15m_risk_envelope.py to apply regime_multiplier to risk limits
    #   2. Ensure the $1 fixed exposure cap (global slot allocator) is still respected after multiplier
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
    
    DISABLED: TTE sizing interferes with the $1 fixed exposure model (global slot allocator).
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
    # DISABLED REASON: Time-to-expiry multipliers could cause oversizing beyond the $1 global slot allocator cap
    # RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
    # RE-ENABLE REQUIREMENTS:
    #   1. Update kalshi_crypto_15m_risk_envelope.py to apply tte_multiplier to risk limits
    #   2. Ensure the $1 fixed exposure cap (global slot allocator) is still respected after multiplier
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
      2. Ensure the $1 fixed exposure cap (global slot allocator) is still respected after multiplier
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
    
    This prevents rejection of low-priced contracts (1c-4c) when they are valid
    entries in the 5c-85c sweet spot range.
    
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

# 2026-07-16: _get_bankroll_cap_pct and _get_per_asset_risk_pct REMOVED.
# Percentage-based sizing is PRUNED - the $1 global slot allocator
# (merid/risk/global_slot_allocator.py) is the single source of truth.


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


# 2026-07-16: _get_max_single_order_pct REMOVED (percentage-based sizing PRUNED).


def _get_max_contracts_per_asset(asset: str) -> int:
    """Get max contracts per asset from profile config.
    
    This reads from kalshi_crypto_15m.yaml per-asset max_contracts.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE", or "BTC15M", "ETH15M", etc.)
    
    Returns:
        Max contracts for this asset
    
    Fallback: returns 2 if profile is unavailable; production must activate the profile.
    """
    if not _PROFILE_AVAILABLE:
        logger.warning(
            "[UNIFIED-SIZING] Profile adapter not available - using default max_contracts=2"
        )
        return 2
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            
            # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset normalization
            # Profile config uses keys like "BTC", "ETH", "SOL", "XRP", "DOGE"
            # But callers may pass "BTC15M", "ETH15M", etc. or full tickers
            from merid.utils.kalshi_identity import extract_asset
            asset_normalized = extract_asset(asset)
            
            asset_config = profile.asset_configs.get(asset_normalized)
            if asset_config:
                return asset_config.max_contracts
            # If asset not in profile, use a conservative default
            logger.warning("[UNIFIED-SIZING] Asset %s (normalized to %s) not in profile config, using default max_contracts=2", asset, asset_normalized)
            return 2  # Slot model: 2 contracts per order ($2 global slot allocator)
        else:
            logger.warning(
                "[UNIFIED-SIZING] Profile not active - using default max_contracts=2"
            )
            return 2  # Slot model default; production must activate profile for real values
    except Exception as e:
        logger.error(
            "[UNIFIED-SIZING] Failed to read max_contracts from profile: %s - "
            "profile read failed, max contracts unavailable",
            e
        )
        raise RuntimeError(f"Profile read failed: {e}")


def _get_kelly_multiplier(edge_pct: Optional[Decimal] = None, asset: Optional[str] = None) -> float:
    """Get Kelly multiplier from profile config based on edge band.
    
    This reads from kalshi_crypto_15m_v2.yaml edge_bands configuration.
    Kelly multipliers are applied to reduce position size based on edge quality:
    - watch band (3% edge): 0.0x Kelly (no trading)
    - small band (3-5% edge): 0.25x Kelly (conservative)
    - standard band (>5% edge): 0.5x Kelly (standard)
    
    2026-07-17: Updated to 3% minimum based on industry research (SimpleFunctions, Market Math, Claw Arbs)
    2026-07-17: Added per-asset edge thresholds based on MQL5 research (asset-specific tuning required)
    
    Args:
        edge_pct: Edge percentage (e.g., 0.02 for 2%). If None, returns 0.5x (standard).
        asset: Asset symbol (e.g., "BTC", "ETH"). If provided, uses per-asset thresholds.
    
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
            
            # Get per-asset minimum edge if asset is provided
            min_edge_pct = 0.030  # Default 3% minimum
            if asset and hasattr(profile, 'edge_bands_per_asset'):
                per_asset = profile.edge_bands_per_asset
                if asset in per_asset and hasattr(per_asset[asset], 'min_edge_pct'):
                    min_edge_pct = float(per_asset[asset].min_edge_pct)
            
            # Determine edge band based on edge_pct
            # 2026-07-17: Updated to industry standard (3% minimum from SimpleFunctions, Market Math, Claw Arbs)
            # Watch band: 3% edge (0.030) - log only
            if edge_pct_float <= min_edge_pct:
                return 0.0  # No trading in watch band
            # Small band: 3-5% edge (0.030-0.05) - trade with reduced size
            elif edge_pct_float <= 0.05:
                return 0.25  # 0.25x Kelly for small band
            # Standard band: >5% edge (>0.05) - trade with standard size
            else:
                return 0.5  # 0.5x Kelly for standard band
        else:
            logger.warning("[UNIFIED-SIZING] Profile not active, using default Kelly multiplier 0.5x")
            return 0.5
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read Kelly multiplier from profile: %s, using default 0.5x", e)
        return 0.5  # Default to 0.5x Kelly on error from e


def _get_slippage_cents() -> int:
    """Return the configured slippage estimate in cents for all-in cost."""
    if _PROFILE_AVAILABLE and is_profile_active():
        try:
            adapter = get_active_profile()
            profile = adapter.profile
            return int(getattr(profile, "guardrails_max_slippage_cents", 5))
        except Exception as e:
            logger.debug("[UNIFIED-SIZING] Failed to read slippage from profile: %s", e)
    raw = os.getenv("MERID_SIGNAL_SLIPPAGE_CENTS", "5")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 5


def compute_fee_cents(price_cents: int) -> float:
    """Average Kalshi fee per contract in cents for a single-contract fill."""
    if _FEES_AVAILABLE and calculate_kalshi_fee_per_contract_cents is not None:
        return float(calculate_kalshi_fee_per_contract_cents(1, price_cents))
    # Fallback parabolic estimate (matches the official formula at extremes).
    price = price_cents / 100.0
    fee = 0.07 * 1.0 * price * (1.0 - price) * 100.0
    return float(math.ceil(fee))


def compute_all_in_cost_cents(
    price_cents: int,
    fee_cents: Optional[float] = None,
    slippage_cents: Optional[int] = None,
) -> float:
    """Realized all-in cost in cents: price + fee (+ optional slippage).

    The canonical cost basis for signal EV and Kelly is the executable quote
    price plus the Kalshi taker fee.  Settlement is free, so hold-to-settle
    trades pay only the entry fee.  ``slippage_cents`` is intentionally opt-in:
    it should only be passed when modeling a worst-case fill, not as the
    default realized cost of a marketable limit order.
    """
    if fee_cents is None:
        fee_cents = compute_fee_cents(price_cents)
    if slippage_cents is None:
        # Default to zero: the 5c limit-price guard is a fill guarantee bound,
        # not a cost you pay every trade.  Callers can still pass it explicitly
        # for stress/robustness calculations.
        slippage_cents = 0
    return float(price_cents) + float(fee_cents) + float(slippage_cents)


def compute_ev_net(
    model_prob: float,
    price_cents: int,
    fee_cents: Optional[float] = None,
    slippage_cents: Optional[int] = None,
) -> float:
    """Expected value in cents net of realized all-in cost.

    EV = p_model*100 - (price + fee) by default.  The ``slippage_cents``
    parameter is opt-in and is only included when a caller explicitly wants to
    stress a worst-case fill; it is not part of the default economic EV gate.
    """
    all_in_cost_cents = compute_all_in_cost_cents(price_cents, fee_cents, slippage_cents)
    return (model_prob * 100.0) - all_in_cost_cents


# 2026-07-16: _get_per_trade_risk_pct REMOVED (percentage-based sizing PRUNED).
# The $1 global slot allocator enforces per-trade exposure (1 contract, 5c-85c).


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
        return 2  # Slot model: 2 contracts per order ($2 global slot allocator)
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_max_contracts
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_max_contracts: %s", e)
    
    return 2  # Slot model: 2 contracts per order ($2 global slot allocator)


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
# Kelly Criterion Functions
# =============================================================================

def calculate_kelly_fraction(
    model_prob: float,
    price_cents: int,
    confidence: float = 0.5,
    fractional_kelly: float = 0.25,
    side: str = "yes",
    consider_fee_impact: bool = False,
    fee_cents: Optional[float] = None,
    slippage_cents: Optional[int] = None,
) -> float:
    """Calculate Kelly fraction for a binary option using a single all-in cost.

    The all-in cost includes the contract price, the Kalshi fee, and an
    explicit slippage estimate.  Both the signal-generation EV gate and the
    sizing Kelly calculator now share this cost so they cannot disagree.

    Args:
        model_prob: True probability of winning (0.0-1.0)
        price_cents: Contract price in cents (1-99)
        confidence: Model confidence (0.0-1.0) for weighting
        fractional_kelly: Kelly fraction multiplier (default 0.25 for quarter-Kelly)
        side: "yes" or "no" - informational only, model_prob is side-specific
        consider_fee_impact: If True, include fee and slippage in the cost basis
        fee_cents: Optional per-contract fee in cents (default: compute from Kalshi schedule)
        slippage_cents: Optional slippage in cents (default: profile or env)

    Returns:
        Kelly fraction (0.0 to 1.0). Returns 0.0 if edge is negative.
    """
    # Validate inputs
    if model_prob is None:
        logger.warning("[KELLY] model_prob is None, rejecting")
        return 0.0

    if not (0.0 <= model_prob <= 1.0):
        logger.warning("[KELLY] Invalid model_prob=%.4f, clamping to [0,1]", model_prob)
        model_prob = max(0.0, min(1.0, model_prob))

    if not (0.0 <= confidence <= 1.0):
        logger.warning("[KELLY] Invalid confidence=%.2f, clamping to [0,1]", confidence)
        confidence = max(0.0, min(1.0, confidence))

    price = price_cents / 100.0
    if price <= 0 or price >= 1.0:
        logger.warning("[KELLY] Invalid price=%.2f, cannot calculate Kelly", price)
        return 0.0

    # Single all-in cost basis: price + fee + slippage
    if consider_fee_impact:
        cost = compute_all_in_cost_cents(price_cents, fee_cents, slippage_cents) / 100.0
    else:
        cost = price

    if cost <= 0 or cost >= 1.0:
        logger.warning("[KELLY] Invalid all-in cost=%.4f, cannot calculate Kelly", cost)
        return 0.0

    p = model_prob
    # Kelly for a binary with cost c and payoff 1: f* = (p - c) / (1 - c)
    kelly = (p - cost) / (1.0 - cost)

    # If Kelly is negative, no edge
    if kelly <= 0:
        logger.debug(
            "[KELLY] Negative edge: model_prob=%.4f side=%s price=%.2f cost=%.4f kelly=%.4f",
            model_prob, side, price, cost, kelly
        )
        return 0.0

    # Apply fractional Kelly (quarter-Kelly by default for production)
    fractional = kelly * fractional_kelly

    # Apply confidence weighting (0.5 to 2.0 multiplier)
    confidence_multiplier = 0.5 + (confidence * 1.5)
    weighted_kelly = fractional * confidence_multiplier

    # Cap at 1.0 (cannot bet more than 100% of available capital)
    final_kelly = min(1.0, weighted_kelly)

    logger.debug(
        "[KELLY] model_prob=%.4f side=%s price=%.2f cost=%.4f kelly=%.4f "
        "fractional=%.4f confidence=%.2f final=%.4f",
        model_prob, side, price, cost, kelly, fractional, confidence, final_kelly
    )

    return final_kelly


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
    model_prob: Optional[float] = None,  # 2026-07-12: Model probability for Kelly calculation
    side: str = "yes",  # 2026-07-13: Side for Kelly calculation (yes/no)
    metadata: Optional[dict] = None,  # 2026-07-31: Metadata for sweet spot price adjustment tracking
    flb_position_multiplier: float = 1.0,  # 2026-08-01: FLB-aware position sizing multiplier
) -> Tuple[int, Decimal, dict]:
    """Compute order size using fixed $2 total exposure model with Kelly filtering (2026-07-12).
    
    This is the SINGLE SOURCE OF TRUTH for order sizing in 15m agents.
    All percentage-based sizing has been removed in favor of fixed $2 total exposure.
    
    NEW (2026-07-12): Kelly Criterion integration
    - Uses Kelly fraction to filter trades with no edge
    - Confidence-weighted Kelly for intelligent position sizing
    - Still respects $1 global cap via slot allocation
    
    Formula:
        1. Calculate Kelly fraction from model_prob, price, confidence
        2. If Kelly fraction is 0, reject (no edge)
        3. Use fixed $2 exposure cap from profile (fixed_exposure_cap_usd)
        4. Check existing total exposure from slot allocator
        5. Available exposure = $2 - existing_exposure
        6. If available_exposure >= contract_cost, allow up to 2 contracts
        7. Otherwise, reject (no slots available)
    
    Example with existing_exposure=$0.65, price_cents=35:
        available_exposure = $1.00 - $0.65 = $0.35
        contract_cost = $0.35
        available_exposure >= contract_cost → allow 1 contract
        new_total_exposure = $0.65 + $0.35 = $1.00 ✅ (at cap)
    
    Args:
        bankroll_usd: Current bankroll in USD (from Kalshi API) - kept for compatibility
        price_cents: Price per contract in cents (0-99)
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
        model_prob: Model probability (0.0-1.0) for Kelly calculation
    
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
    
    # 2026-07-12: Kelly Criterion filtering
    # CRITICAL FIX 2026-08-08: Always re-run Kelly/sizing against the final repriced
    # price. Previously SWEET-SPOT-EXECUTION set a flag that bypassed Kelly, letting
    # mispriced orders through. Now that repricing is explicit and side-aware, the
    # edge/sizing must be recalculated at the submitted price.
    if model_prob is not None:
        confidence_float = float(confidence) if confidence is not None else 0.5

        # All-in cost is always computed for telemetry, but only used for Kelly
        # gating when consider_fee_impact is True (default False preserves legacy
        # test expectations; production callers pass consider_fee_impact=True).
        _fee_cents: Optional[float] = None
        _slippage_cents: Optional[int] = None
        _ev_net: Optional[float] = None
        _all_in_cost_cents: Optional[float] = None

        if consider_fee_impact or estimated_fee_cents is not None:
            if estimated_fee_cents is not None:
                _fee_cents = float(estimated_fee_cents)
            _all_in_cost_cents = compute_all_in_cost_cents(price_cents, _fee_cents, _slippage_cents)
            _ev_net = (model_prob * 100.0) - _all_in_cost_cents

        kelly_fraction = calculate_kelly_fraction(
            model_prob=model_prob,
            price_cents=price_cents,
            confidence=confidence_float,
            fractional_kelly=0.25,  # Quarter-Kelly for production
            side=side,
            consider_fee_impact=consider_fee_impact or estimated_fee_cents is not None,
            fee_cents=_fee_cents,
            slippage_cents=_slippage_cents,
        )

        # If Kelly fraction is 0, reject (no edge)
        if kelly_fraction <= 0:
            logger.info(
                "[UNIFIED-SIZING] Kelly filter: asset=%s model_prob=%.2f price=%dc kelly=%.4f - NO EDGE, rejecting",
                asset, model_prob, price_cents, kelly_fraction
            )
            return 0, Decimal("0"), {
                "bankroll_usd": float(bankroll_usd),
                "price_cents": price_cents,
                "asset": asset,
                "reason": "kelly_no_edge",
                "model_prob": model_prob,
                "kelly_fraction": kelly_fraction,
                "all_in_cost_cents": _all_in_cost_cents,
                "ev_net_cents": _ev_net,
            }

        logger.info(
            "[UNIFIED-SIZING] Kelly filter passed: asset=%s model_prob=%.2f price=%dc kelly=%.4f",
            asset, model_prob, price_cents, kelly_fraction
        )
    
    # 2026-07-08 UPDATE: Fixed $2 total exposure model - slot-based position management
    # All percentage-based sizing has been removed
    # New model: sum of all contract prices must be ≤ $2
    
    # Step 1: Get fixed $2 exposure cap from profile
    fixed_exposure_cap_usd = Decimal("2.00")  # Default
    if _PROFILE_AVAILABLE and is_profile_active():
        adapter = get_active_profile()
        profile = adapter.profile
        fixed_exposure_cap_usd = Decimal(str(profile.risk_policy_fixed_exposure_cap_usd))
    
    # Step 2: Get existing total exposure from slot allocator
    # CRITICAL FIX: 2026-07-13 - Use slot_allocator for exposure check
    # Slot allocator is the authoritative source for exposure tracking including allocated slots
    # Position cache only tracks filled positions, not allocated slots
    existing_exposure_usd = Decimal("0")
    try:
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        slot_allocator = get_global_slot_allocator()
        
        # CRITICAL FIX (2026-07-31): Sync slot allocator with position cache before checking exposure
        # This prevents state drift where slots remain allocated even though positions no longer exist
        # This is the root cause of "total_exposure=1.00 when no positions exist" issue
        sync_count = slot_allocator.sync_with_position_cache()
        if sync_count > 0:
            logger.info("[UNIFIED-SIZING] Synced slot allocator with position cache: removed %d orphaned slots", sync_count)
        
        existing_exposure_usd = Decimal(str(slot_allocator.get_total_exposure()))
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to get existing exposure from slot allocator: %s", e)
    
    # Step 3: Calculate available exposure
    available_exposure_usd = fixed_exposure_cap_usd - existing_exposure_usd
    
    # Step 4: Calculate contract cost
    contract_cost_usd = Decimal(price_cents) / Decimal("100")

    # Step 4a: Compute the maximum number of whole contracts that fit under any
    # explicit per-order notional cap (legacy percentage-based fallback).
    max_by_notional: Optional[int] = None
    if max_notional_usd is not None:
        max_by_notional = int(Decimal(str(max_notional_usd)) // contract_cost_usd)
        if max_by_notional < 1:
            logger.warning(
                "[UNIFIED-SIZING] CAPITAL_INSUFFICIENT: asset=%s price=%dc contract_cost=%.2f "
                "exceeds max_notional_usd=%.2f - rejecting order",
                asset, price_cents, float(contract_cost_usd), float(max_notional_usd)
            )
            return 0, Decimal("0"), {
                "bankroll_usd": float(bankroll_usd),
                "price_cents": price_cents,
                "asset": asset,
                "reason": "capital_insufficient_max_notional",
                "contract_cost_usd": float(contract_cost_usd),
                "max_notional_usd": float(max_notional_usd),
            }

    # Step 5: Check if we have enough exposure slot
    if available_exposure_usd < contract_cost_usd:
        logger.warning(
            "[UNIFIED-SIZING] Insufficient exposure slot: available=%.2f, needed=%.2f, existing=%.2f, cap=%.2f asset=%s",
            float(available_exposure_usd), float(contract_cost_usd), float(existing_exposure_usd),
            float(fixed_exposure_cap_usd), asset
        )
        # Debug: log slot allocator state for troubleshooting
        try:
            from merid.risk.global_slot_allocator import get_global_slot_allocator
            slot_allocator = get_global_slot_allocator()
            slots = slot_allocator.get_slots_by_asset(asset) if asset else []
            logger.warning(
                "[UNIFIED-SIZING] Slot allocator state: total_slots=%d, asset_slots=%d, total_exposure=%.2f",
                slot_allocator.get_slot_count(), len(slots), slot_allocator.get_total_exposure()
            )
            for slot in slots:
                logger.warning(
                    "[UNIFIED-SIZING] Active slot: slot_id=%s ticker=%s entry_price=%dc exposure=%.2f status=%s",
                    slot.slot_id, slot.ticker, slot.entry_price_cents, slot.exposure_usd, slot.status
                )
        except Exception as e:
            logger.warning("[UNIFIED-SIZING] Failed to log slot allocator state: %s", e)

        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "price_cents": price_cents,
            "asset": asset,
            "reason": "insufficient_exposure_slot",
            "available_exposure_usd": float(available_exposure_usd),
            "contract_cost_usd": float(contract_cost_usd),
            "existing_exposure_usd": float(existing_exposure_usd),
        }

    # Step 6: Compute target contract count
    # 2026-08-22: Size up to the configured per-asset max while staying inside the
    # fixed $1 global exposure cap. The $1 allocation itself is not changed.
    if _is_dynamic_sizing_enabled():
        target_contracts = _get_dynamic_sizing_base_contracts()
        if target_contracts < 1:
            target_contracts = 1
    else:
        target_contracts = _get_max_contracts_per_asset(asset)

    # Step 7: Get effective max contracts cap (per-asset and dynamic)
    max_contracts_cap = _get_max_contracts_per_asset(asset)
    if _is_dynamic_sizing_enabled():
        dynamic_max = _get_dynamic_sizing_max_contracts()
        if dynamic_max < 1:
            dynamic_max = 1
        max_contracts_cap = min(max_contracts_cap, dynamic_max)

    # Step 8: Cap by the number of whole contracts that fit in the available $2 exposure
    max_by_exposure = int(available_exposure_usd // contract_cost_usd)

    contract_count = min(target_contracts, max_contracts_cap, max_by_exposure)
    if max_by_notional is not None:
        contract_count = min(contract_count, max_by_notional)

    if contract_count < 1:
        # Defensive: should not reach here because of the exposure check above,
        # but handle the case where a cap reduced the count to 0.
        logger.warning(
            "[UNIFIED-SIZING] Insufficient exposure for requested count: "
            "available=$%.2f, price=%dc, target=%d, max_cap=%d, by_exposure=%d, asset=%s",
            float(available_exposure_usd), price_cents, target_contracts, max_contracts_cap, max_by_exposure, asset
        )
        return 0, Decimal("0"), {
            "bankroll_usd": float(bankroll_usd),
            "price_cents": price_cents,
            "asset": asset,
            "reason": "insufficient_exposure_for_requested_count",
            "available_exposure_usd": float(available_exposure_usd),
            "contract_cost_usd": float(contract_cost_usd),
            "existing_exposure_usd": float(existing_exposure_usd),
            "max_contracts_cap": max_contracts_cap,
            "target_contracts": target_contracts,
            "max_by_exposure": max_by_exposure,
        }

    order_notional_usd = Decimal(contract_count) * contract_cost_usd

    # 2026-08-01: Apply FLB position sizing multiplier
    # FLB multiplier reduces effective position size based on FLB risk zones
    # Since slot-based model enforces the configured max, we pass this in metadata for downstream use
    # The order router can use this to adjust position sizing or reject high-risk trades
    if flb_position_multiplier != 1.0:
        logger.info(
            "[UNIFIED-SIZING] FLB position multiplier applied: asset=%s price=%dc flb_multiplier=%.2f "
            "(FLB-aware position sizing based on research-backed risk zones)",
            asset, price_cents, flb_position_multiplier
        )

    logger.info(
        "[UNIFIED-SIZING] Slot-based sizing: asset=%s price=%dc cost=$%.2f "
        "existing_exposure=$%.2f available=$%.2f cap=$%.2f contracts=%d flb_multiplier=%.2f",
        asset, price_cents, float(contract_cost_usd), float(existing_exposure_usd),
        float(available_exposure_usd), float(fixed_exposure_cap_usd), contract_count, flb_position_multiplier
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
    fee_adjusted = bool(
        consider_fee_impact and estimated_fee_cents is not None and float(estimated_fee_cents) > 0
    )

    metadata = {
        "bankroll_usd": float(bankroll_usd),
        "price_cents": price_cents,
        "asset": asset,
        "contract_count": contract_count,
        "order_notional_usd": float(order_notional_usd),
        "existing_exposure_usd": float(existing_exposure_usd),
        "available_exposure_usd": float(available_exposure_usd),
        "fixed_exposure_cap_usd": float(fixed_exposure_cap_usd),
        "flb_position_multiplier": flb_position_multiplier,  # 2026-08-01: FLB multiplier for downstream use
        "consider_fee_impact": bool(consider_fee_impact),
        "fee_adjusted": fee_adjusted,
        "estimated_fee_cents": float(estimated_fee_cents) if estimated_fee_cents is not None else None,
    }
    
    # Add Kelly information if model_prob was provided
    if model_prob is not None:
        confidence_float = float(confidence) if confidence is not None else 0.5
        _fee_cents: Optional[float] = None
        _slippage_cents: Optional[int] = None
        if consider_fee_impact or estimated_fee_cents is not None:
            if estimated_fee_cents is not None:
                _fee_cents = float(estimated_fee_cents)
            _all_in_cost_cents = compute_all_in_cost_cents(price_cents, _fee_cents, _slippage_cents)
            _ev_net = (model_prob * 100.0) - _all_in_cost_cents
            metadata["all_in_cost_cents"] = _all_in_cost_cents
            metadata["ev_net_cents"] = _ev_net
            metadata["fee_cents"] = compute_fee_cents(price_cents) if _fee_cents is None else _fee_cents
            metadata["slippage_cents"] = _slippage_cents if _slippage_cents is not None else _get_slippage_cents()

        kelly_fraction = calculate_kelly_fraction(
            model_prob=model_prob,
            price_cents=price_cents,
            confidence=confidence_float,
            fractional_kelly=0.25,
            side=side,
            consider_fee_impact=consider_fee_impact or estimated_fee_cents is not None,
            fee_cents=_fee_cents,
            slippage_cents=_slippage_cents,
        )
        metadata["model_prob"] = model_prob
        metadata["confidence"] = confidence_float
        metadata["kelly_fraction"] = kelly_fraction

    logger.info(
        "[UNIFIED-SIZING] Final sizing: asset=%s contracts=%d notional=$%.2f price=%dc "
        "total_exposure_after=$%.2f",
        asset, contract_count, float(order_notional_usd), price_cents,
        float(existing_exposure_usd + order_notional_usd)
    )
    
    return contract_count, order_notional_usd, metadata
