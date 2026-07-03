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
    For Kalshi, the minimum notional is typically $1.00 for sanity check compliance,
    but this should be derived from venue rules or contract metadata when available.
    
    Args:
        venue: Venue name (e.g., "kalshi")
        contract_ticker: Optional contract ticker for contract-specific rules
        price_cents: Optional price in cents for dynamic calculation
        
    Returns:
        Minimum notional in USD as Decimal. Returns 0.0 if no constraint.
    """
    # Kalshi-specific rules
    if venue.lower() == "kalshi":
        # Kalshi contracts pay $1 per contract
        # Minimum order notional is $1.00 for sanity check compliance
        # This is a venue-level requirement, not a risk limit
        return Decimal("1.00")
    
    # For other venues or if venue metadata is unavailable, return 0.0 (no constraint)
    # This allows the sizing function to proceed without a min_notional floor
    return Decimal("0.0")


# =============================================================================
# Configuration Sources
# =============================================================================

def _get_bankroll_cap_pct() -> Decimal:
    """Get global bankroll cap percentage from environment.
    
    SAFETY CEILING: This is a GLOBAL SAFETY CEILING, not a primary policy mechanism.
    Production profiles must set risk percentages (per_trade_risk_pct, max_single_order_pct)
    that are ≤ this ceiling. Changing this env var in production is a risk-governance action,
    not a tuning knob.
    
    Reads MERID_BANKROLL_CAP_PCT env var, clamped to safe range [1%, 2%].
    Default is 2% (max) if not configured.
    
    Returns:
        Cap percentage as Decimal (e.g., Decimal("0.02") for 2%)
    """
    try:
        raw_pct = float(os.getenv("MERID_BANKROLL_CAP_PCT", "2.0"))
        # CRITICAL FIX: Validate bankroll cap percentage is reasonable
        if raw_pct < 0 or raw_pct > 100:
            logger.warning(
                "[UNIFIED-SIZING] Invalid MERID_BANKROLL_CAP_PCT=%s - using default 2.0",
                raw_pct
            )
            raw_pct = 2.0
    except (ValueError, TypeError):
        raw_pct = 2.0
    
    # Clamp to safe range: 1% minimum, 2% maximum
    clamped_pct = max(1.0, min(2.0, raw_pct))
    return Decimal(str(clamped_pct / 100.0))  # Convert to fraction


def _get_per_asset_risk_pct(asset: str) -> Optional[Decimal]:
    """Get per-asset risk percentage from profile config.
    
    This reads from kalshi_crypto_15m.yaml per-asset max_notional_pct.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
    
    Returns:
        Risk percentage as Decimal, or None to use global cap
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error("[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production")
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            asset_config = profile.asset_configs.get(asset)
            if asset_config:
                return Decimal(str(asset_config.max_notional_pct))
        else:
            logger.error("[UNIFIED-SIZING] Profile not active - cannot size orders in production")
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error("[UNIFIED-SIZING] Failed to read per-asset risk pct from profile: %s", e)
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
        logger.error("[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production")
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.venue_max_single_order_pct))
        else:
            logger.error("[UNIFIED-SIZING] Profile not active - cannot size orders in production")
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error("[UNIFIED-SIZING] Failed to read max_single_order_pct from profile: %s", e)
        raise RuntimeError(f"Profile read failed: {e}") from e


def _get_max_contracts_per_asset(asset: str) -> int:
    """Get max contracts per asset from profile config.
    
    This reads from kalshi_crypto_15m.yaml per-asset max_contracts.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
    
    Returns:
        Max contracts for this asset
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error("[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production")
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            asset_config = profile.asset_configs.get(asset)
            if asset_config:
                return asset_config.max_contracts
            # If asset not in profile, use a conservative default
            logger.warning("[UNIFIED-SIZING] Asset %s not in profile config, using default max_contracts=10", asset)
            return 10
        else:
            logger.error("[UNIFIED-SIZING] Profile not active - cannot size orders in production")
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error("[UNIFIED-SIZING] Failed to read max_contracts from profile: %s", e)
        raise RuntimeError(f"Profile read failed: {e}") from e


def _get_min_edge_risk_pct() -> Decimal:
    """Get min-edge-based risk percentage from profile config.
    
    NOTE: This reads from kalshi_crypto_15m.yaml guardrails.min_post_fee_edge.
    The field is conceptually a minimum edge threshold, but we repurpose it as a
    per-trade risk cap for sizing. This is a temporary measure; a dedicated
    per_trade_risk_pct field should be added to the profile for clarity.
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error("[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production")
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.guardrails_min_post_fee_edge))
        else:
            logger.error("[UNIFIED-SIZING] Profile not active - cannot size orders in production")
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error("[UNIFIED-SIZING] Failed to read min_edge from profile: %s", e)
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
        return 0.5  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_edge_multiplier
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_edge_multiplier: %s", e)
    
    return 0.5  # Default


def _get_dynamic_sizing_confidence_multiplier() -> float:
    """Get confidence multiplier for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.confidence_multiplier.
    
    Returns:
        Confidence multiplier as float.
    """
    if not _PROFILE_AVAILABLE:
        return 0.3  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_confidence_multiplier
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_confidence_multiplier: %s", e)
    
    return 0.3  # Default


def _get_dynamic_sizing_max_contracts() -> int:
    """Get max contracts for dynamic sizing from profile config.
    
    This reads from kalshi_crypto_15m.yaml dynamic_sizing.max_contracts.
    
    Returns:
        Max contracts as int.
    """
    if not _PROFILE_AVAILABLE:
        return 3  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.dynamic_sizing_max_contracts
    except Exception as e:
        logger.warning("[UNIFIED-SIZING] Failed to read dynamic_sizing_max_contracts: %s", e)
    
    return 3  # Default


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
            "[UNIFIED-SIZING] INVALID_PRICE: price_cents=%d for asset=%s - cannot size order with zero/negative price",
            price_cents, asset
        )
        raise ValueError(f"Invalid price_cents={price_cents} for asset={asset} - must be > 0")
    
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
        # Interlock rule: risk_pct_for_sizing = min(min_edge_risk_pct, max_single_order_pct, MERID_BANKROLL_CAP_PCT)
        min_edge_risk_pct = _get_min_edge_risk_pct()  # from profile guardrails.min_post_fee_edge (repurposed)
        max_single_order_pct = _get_max_single_order_pct()  # from profile venue.max_single_order_pct
        bankroll_cap_pct = _get_bankroll_cap_pct()  # global safety ceiling from MERID_BANKROLL_CAP_PCT env
        per_asset_risk_pct = _get_per_asset_risk_pct(asset)  # per-asset from profile (optional)
        
        risk_pct_candidates = [min_edge_risk_pct, max_single_order_pct, bankroll_cap_pct]
        if per_asset_risk_pct is not None:
            risk_pct_candidates.append(per_asset_risk_pct)
        
        risk_pct_effective = min(risk_pct_candidates)
        
        # Step 2: Compute max_notional from bankroll and effective risk_pct
        max_notional_usd = bankroll_usd * risk_pct_effective
        
        logger.info(
            "[SIZE-COMPUTE] Computed max_notional from risk_pct: bankroll=%.2f risk_pct=%.4f max_notional=%.2f asset=%s "
            "(candidates: min_edge=%.4f, max_single=%.4f, bankroll_cap=%.4f, per_asset=%s)",
            float(bankroll_usd), float(risk_pct_effective), float(max_notional_usd), asset,
            float(min_edge_risk_pct), float(max_single_order_pct), float(bankroll_cap_pct),
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
    
    # Step 5: Check existing positions for position-aware sizing
    # Reduce max_notional if we already have exposure to this asset
    existing_position_notional = Decimal("0")
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        positions = cache.get_all_positions()
        
        # Sum existing positions for this asset (across all timeframes)
        for ticker, pos in positions.items():
            # Extract asset from ticker (e.g., KXBTC15M-... -> BTC)
            ticker_asset = None
            if "BTC" in ticker.upper():
                ticker_asset = "BTC"
            elif "ETH" in ticker.upper():
                ticker_asset = "ETH"
            elif "SOL" in ticker.upper():
                ticker_asset = "SOL"
            elif "XRP" in ticker.upper():
                ticker_asset = "XRP"
            elif "DOGE" in ticker.upper():
                ticker_asset = "DOGE"
            
            if ticker_asset == asset and hasattr(pos, 'contracts'):
                # Calculate notional from position using actual entry price
                # Use avg_price_cents from position if available, otherwise fallback to current price
                entry_price_cents = getattr(pos, 'avg_price_cents', None)
                if entry_price_cents and entry_price_cents > 0:
                    position_notional_usd = (Decimal(entry_price_cents) / Decimal("100")) * pos.contracts
                else:
                    # Fallback to current price if entry price unavailable
                    position_notional_usd = contract_notional_usd * pos.contracts
                existing_position_notional += position_notional_usd
        
        if existing_position_notional > 0:
            # Reduce max_notional by existing exposure
            available_notional = max_notional_usd - existing_position_notional
            if available_notional <= 0:
                logger.info(
                    "[SIZE-COMPUTE] Position-aware sizing: already at max exposure for %s (existing=%.2f, max=%.2f). Rejecting.",
                    asset, float(existing_position_notional), float(max_notional_usd)
                )
                return 0, Decimal("0"), {
                    "bankroll_usd": float(bankroll_usd),
                    "risk_pct_effective": float(risk_pct_effective),
                    "max_notional_usd": float(max_notional_usd),
                    "price_cents": price_cents,
                    "asset": asset,
                    "contracts_from_notional": 0,
                    "max_contracts_cap": max_contracts_cap,
                    "per_asset_risk_pct": per_asset_risk_pct,
                    "final_count": 0,
                    "final_notional_usd": 0.0,
                    "rejection_reason": "position_limit_exceeded"
                }
            max_notional_usd = available_notional
            logger.info(
                "[SIZE-COMPUTE] Position-aware sizing: reduced max_notional for %s from %.2f to %.2f (existing exposure: %.2f)",
                asset, float(max_notional_usd + existing_position_notional), float(max_notional_usd), float(existing_position_notional)
            )
    except Exception as e:
        logger.warning("[SIZE-COMPUTE] Failed to check existing positions for position-aware sizing: %s", e)
    
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
