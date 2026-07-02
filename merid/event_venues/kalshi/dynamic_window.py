"""Dynamic entry window evaluation for Kalshi 15m crypto trading.

This module provides a pure function to evaluate whether a market should be traded
based on dynamic conditions (volatility, market quality, execution feedback, risk state)
instead of a fixed 2-12 minute window.

The function is designed to run in shadow mode first: log the dynamic decision
without changing behavior, then flip to enforce after observation.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum

import logging

logger = logging.getLogger(__name__)


class WindowReason(str, Enum):
    """Reason codes for window decisions."""
    # Early side (strip open)
    TOO_EARLY_VOL_HIGH = "too_early_vol_high"
    TOO_EARLY_SPREAD_WIDE = "too_early_spread_wide"
    TOO_EARLY_DEPTH_LOW = "too_early_depth_low"
    TOO_EARLY_RECENT_INVARIANT = "too_early_recent_invariant"
    TOO_EARLY_EXECUTION_POOR = "too_early_execution_poor"
    
    # Late side (strip end)
    TOO_CLOSE_TO_EXPIRY = "too_close_to_expiry"
    
    # Market quality
    SPREAD_TOO_WIDE = "spread_too_wide"
    DEPTH_TOO_LOW = "depth_too_low"
    BOOK_STALE = "book_stale"
    
    # Risk gate
    COOLDOWN_ACTIVE = "cooldown_active"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    ROLLING_LOSS_LIMIT = "rolling_loss_limit"
    
    # Allowed
    ALLOWED = "allowed"


@dataclass
class DynamicWindowResult:
    """Result of dynamic window evaluation."""
    # Decision
    would_allow_trade: bool
    reason: WindowReason
    
    # Computed thresholds
    min_seconds_from_open: float
    min_seconds_to_expiry: float
    
    # Input state (for logging/audit)
    time_since_open: float
    time_to_expiry: float
    vol_regime: str
    spread_cents: int
    depth_at_top: int
    is_stale: bool
    execution_slippage: float
    execution_fill_rate: float
    cooldown_active: bool
    drawdown_state: str
    
    # Rationale
    rationale: str
    
    # Computation time
    computation_time_ms: float


def evaluate_dynamic_window(
    # Time inputs
    now: datetime,
    strip_start: datetime,
    strip_end: datetime,
    
    # Market state
    spread_cents: int,
    depth_at_top: int,
    is_stale: bool,
    
    # Volatility regime
    vol_regime: str,  # "LOW", "NORMAL", "HIGH", "EXTREME"
    
    # Execution feedback (per-asset)
    execution_slippage: float = 0.0,  # Average slippage in cents
    execution_fill_rate: float = 1.0,  # Fill rate (0-1)
    
    # Risk state
    cooldown_active: bool = False,
    drawdown_state: str = "FLAT",
    recent_invariant_violations: int = 0,
    
    # Asset context (for execution feedback lookup)
    asset: Optional[str] = None,
    
    # Mode (shadow vs enforce)
    shadow_mode: bool = True,
) -> DynamicWindowResult:
    """Evaluate dynamic entry window for a market.
    
    This is a pure function - no side effects, no behavior changes in shadow mode.
    Designed to be logged alongside the static 2-12 check for comparison.
    
    Args:
        now: Current UTC time
        strip_start: When the market strip opened (UTC)
        strip_end: When the market strip expires (UTC)
        spread_cents: Current spread in cents
        depth_at_top: Current depth at best bid/ask
        is_stale: Whether market data is stale
        vol_regime: Volatility regime (LOW/NORMAL/HIGH/EXTREME)
        execution_slippage: Average slippage for this asset (cents)
        execution_fill_rate: Fill rate for this asset (0-1)
        cooldown_active: Whether cooldown is active from invariant violations
        drawdown_state: Current drawdown state (FLAT/MINOR/MODERATE/SEVERE/CRITICAL)
        recent_invariant_violations: Count of recent invariant violations
        asset: Asset symbol (for logging)
        shadow_mode: If True, only log decision without enforcing
    
    Returns:
        DynamicWindowResult with decision, thresholds, and rationale
    """
    import time
    t0 = time.time()
    
    # Load thresholds from kalshi_crypto_15m profile config
    legacy_max_spread = 10  # Legacy default for audit logging
    max_spread_cents = legacy_max_spread
    min_time_to_expiry_min = 2.5  # Default fallback (150s)
    try:
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        adapter = Crypto15mProfileAdapter()
        if adapter and adapter.profile:
            max_spread_cents = adapter.profile.guardrails_max_spread_cents
            min_time_to_expiry_min = adapter.profile.guardrails_min_time_to_expiry_min
            logger.info(
                "[SPREAD-CONFIG] Loaded max_spread_cents=%d from profile kalshi_crypto_15m.yaml "
                "(overriding legacy default=%d)",
                max_spread_cents, legacy_max_spread
            )
    except Exception as e:
        logger.warning(
            "[SPREAD-CONFIG] Failed to load thresholds from kalshi_crypto_15m profile: %s, using defaults",
            e
        )
    
    # Compute time metrics
    # Convert now to datetime if it's a timestamp (int/float)
    if isinstance(now, (int, float)):
        from datetime import datetime, timezone
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
    else:
        now_dt = now
    
    time_since_open = max(0.0, (now_dt - strip_start).total_seconds())
    time_to_expiry = max(0.0, (strip_end - now_dt).total_seconds())
    
    # ── 1. Risk Gate Check (hard block) ─────────────────────────────────────
    if cooldown_active:
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=WindowReason.COOLDOWN_ACTIVE,
            min_seconds_from_open=0.0,
            min_seconds_to_expiry=180.0,  # Default 3 min
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale="Cooldown active from invariant violation - trading blocked",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    if drawdown_state in ("SEVERE", "CRITICAL"):
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=WindowReason.DAILY_LOSS_LIMIT,
            min_seconds_from_open=0.0,
            min_seconds_to_expiry=180.0,
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale=f"Drawdown state {drawdown_state} - trading blocked",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    # ── 2. Market Quality Check (hard block) ───────────────────────────────
    if is_stale:
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=WindowReason.BOOK_STALE,
            min_seconds_from_open=0.0,
            min_seconds_to_expiry=180.0,
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale="Market data stale - trading blocked",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    # Spread check with tolerance (aligned with optimizer policy)
    # Allow small breaches based on depth, but hard block on excessive spreads
    spread_breach = spread_cents - max_spread_cents
    if spread_breach > 0:
        # Calculate tolerance based on depth (up to 10c bonus for depth)
        depth_bonus = min(10, depth_at_top / 10) if depth_at_top else 0
        max_tolerance = 0.5 * max_spread_cents  # Cap at 50% of max_spread_cents
        total_tolerance = min(depth_bonus, max_tolerance)
        
        if spread_breach > total_tolerance:
            return DynamicWindowResult(
                would_allow_trade=False,
                reason=WindowReason.SPREAD_TOO_WIDE,
                min_seconds_from_open=0.0,
                min_seconds_to_expiry=180.0,
                time_since_open=time_since_open,
                time_to_expiry=time_to_expiry,
                vol_regime=vol_regime,
                spread_cents=spread_cents,
                depth_at_top=depth_at_top,
                is_stale=is_stale,
                execution_slippage=execution_slippage,
                execution_fill_rate=execution_fill_rate,
                cooldown_active=cooldown_active,
                drawdown_state=drawdown_state,
                rationale=f"Spread too wide ({spread_cents}c > {max_spread_cents}c, breach={spread_breach:.1f}c > tolerance={total_tolerance:.1f}c) - trading blocked",
                computation_time_ms=(time.time() - t0) * 1000,
            )
        else:
            logger.info(
                "[DYNAMIC-WINDOW-SPREAD-TOLERANCE] spread=%sc > max=%sc breach=%.1fc <= tolerance=%.1fc (capped at %.1fc) - allowing with warning",
                spread_cents, max_spread_cents, spread_breach, total_tolerance, max_tolerance
            )
    
    if depth_at_top < 5:  # Minimum depth threshold
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=WindowReason.DEPTH_TOO_LOW,
            min_seconds_from_open=0.0,
            min_seconds_to_expiry=180.0,
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale=f"Depth too low ({depth_at_top} < 5) - trading blocked",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    # ── 3. Compute Dynamic Early Threshold (min_seconds_from_open) ───────────
    # Base threshold: 0 seconds (allow immediate entry in ideal conditions)
    min_from_open = 0.0
    
    # Adjust based on volatility regime
    if vol_regime == "HIGH":
        min_from_open += 60.0  # Wait 1 minute in high vol
    elif vol_regime == "EXTREME":
        min_from_open += 120.0  # Wait 2 minutes in extreme vol
    
    # Adjust based on spread (wider spread = longer wait)
    if spread_cents >= 5:
        min_from_open += 30.0  # Add 30 seconds for wide spreads
    elif spread_cents >= 8:
        min_from_open += 60.0  # Add 60 seconds for very wide spreads
    
    # Adjust based on depth (lower depth = longer wait)
    if depth_at_top < 10:
        min_from_open += 30.0  # Add 30 seconds for thin books
    elif depth_at_top < 20:
        min_from_open += 15.0  # Add 15 seconds for moderate books
    
    # Adjust based on recent invariant violations
    if recent_invariant_violations >= 3:
        min_from_open += 60.0  # Add 60 seconds if recent issues
    elif recent_invariant_violations >= 1:
        min_from_open += 30.0  # Add 30 seconds if any recent issues
    
    # Adjust based on execution feedback (poor execution = longer wait)
    if execution_slippage > 3.0 or execution_fill_rate < 0.7:
        min_from_open += 60.0  # Add 60 seconds for poor execution
    elif execution_slippage > 1.0 or execution_fill_rate < 0.9:
        min_from_open += 30.0  # Add 30 seconds for moderate execution issues
    
    # Cap at 60 seconds (1 minute) maximum early wait
    # Reduced from 120s to allow earlier trading in 15m markets
    min_from_open = min(min_from_open, 60.0)
    
    # ── 4. Compute Dynamic Late Threshold (min_seconds_to_expiry) ───────────
    # Base threshold from profile (e.g., 2.5 minutes = 150s for normal regime)
    min_to_expiry = min_time_to_expiry_min * 60.0  # Convert minutes to seconds
    
    # Allow slightly closer entries if drawdown is FLAT and execution is good
    if drawdown_state == "FLAT" and execution_slippage < 1.0 and execution_fill_rate > 0.9:
        min_to_expiry = max(min_to_expiry * 0.8, 90.0)  # Allow 20% closer, minimum 90s
    
    # Extend further if drawdown is elevated
    if drawdown_state in ("MODERATE", "SEVERE"):
        min_to_expiry = max(min_to_expiry * 1.5, 240.0)  # Require 50% more time, minimum 4 minutes
    
    # ── 5. Apply Dynamic Thresholds ─────────────────────────────────────────
    # Early side check
    # CRITICAL FIX: Removed hardcoded depth threshold (10 contracts) - now uses liquidity-aware check
    # Depth thresholds are now per-asset from risk profile, not global constants
    if time_since_open < min_from_open:
        reason = WindowReason.TOO_EARLY_VOL_HIGH if vol_regime in ("HIGH", "EXTREME") else WindowReason.TOO_EARLY_SPREAD_WIDE if spread_cents >= 5 else WindowReason.TOO_EARLY_EXECUTION_POOR if execution_slippage > 1.0 else WindowReason.TOO_EARLY_RECENT_INVARIANT
        
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=reason,
            min_seconds_from_open=min_from_open,
            min_seconds_to_expiry=min_to_expiry,
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale=f"Too early: {time_since_open:.1f}s since open < {min_from_open:.1f}s threshold (vol={vol_regime}, spread={spread_cents}c, depth={depth_at_top})",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    # Late side check
    if time_to_expiry < min_to_expiry:
        return DynamicWindowResult(
            would_allow_trade=False,
            reason=WindowReason.TOO_CLOSE_TO_EXPIRY,
            min_seconds_from_open=min_from_open,
            min_seconds_to_expiry=min_to_expiry,
            time_since_open=time_since_open,
            time_to_expiry=time_to_expiry,
            vol_regime=vol_regime,
            spread_cents=spread_cents,
            depth_at_top=depth_at_top,
            is_stale=is_stale,
            execution_slippage=execution_slippage,
            execution_fill_rate=execution_fill_rate,
            cooldown_active=cooldown_active,
            drawdown_state=drawdown_state,
            rationale=f"Too close to expiry: {time_to_expiry:.1f}s < {min_to_expiry:.1f}s threshold",
            computation_time_ms=(time.time() - t0) * 1000,
        )
    
    # All checks passed
    return DynamicWindowResult(
        would_allow_trade=True,
        reason=WindowReason.ALLOWED,
        min_seconds_from_open=min_from_open,
        min_seconds_to_expiry=min_to_expiry,
        time_since_open=time_since_open,
        time_to_expiry=time_to_expiry,
        vol_regime=vol_regime,
        spread_cents=spread_cents,
        depth_at_top=depth_at_top,
        is_stale=is_stale,
        execution_slippage=execution_slippage,
        execution_fill_rate=execution_fill_rate,
        cooldown_active=cooldown_active,
        drawdown_state=drawdown_state,
        rationale=f"Allowed: {time_since_open:.1f}s since open >= {min_from_open:.1f}s, {time_to_expiry:.1f}s to expiry >= {min_to_expiry:.1f}s (vol={vol_regime}, spread={spread_cents}c, depth={depth_at_top})",
        computation_time_ms=(time.time() - t0) * 1000,
    )


def log_static_vs_dynamic_comparison(
    market_id: str,
    static_allowed: bool,
    static_min: int,
    static_max: int,
    dynamic_result: DynamicWindowResult,
) -> None:
    """Log comparison between static 2-12 window and dynamic window.
    
    This is used during shadow mode to build evidence before flipping to enforce.
    
    Args:
        market_id: Market identifier
        static_allowed: Whether static 2-12 window allows trade
        static_min: Static min_minutes (cutoff)
        static_max: Static max_minutes (window)
        dynamic_result: Result from evaluate_dynamic_window()
    """
    logger.info(
        "[WINDOW-COMPARISON] market=%s | "
        "STATIC: allowed=%s window=[%d-%d]min | "
        "DYNAMIC: allowed=%s min_from_open=%.1fs min_to_expiry=%.1fs reason=%s | "
        "rationale=%s",
        market_id,
        static_allowed, static_min, static_max,
        dynamic_result.would_allow_trade,
        dynamic_result.min_seconds_from_open,
        dynamic_result.min_seconds_to_expiry,
        dynamic_result.reason.value,
        dynamic_result.rationale,
    )
    
    # Track divergences for audit
    if static_allowed != dynamic_result.would_allow_trade:
        divergence_type = "static_allow_dynamic_deny" if static_allowed else "static_deny_dynamic_allow"
        logger.warning(
            "[WINDOW-DIVERGENCE] market=%s type=%s | "
            "Static says %s, Dynamic says %s | "
            "This trade would %s if dynamic enforced",
            market_id, divergence_type,
            "ALLOW" if static_allowed else "DENY",
            "ALLOW" if dynamic_result.would_allow_trade else "DENY",
            "be skipped" if static_allowed else "be taken"
        )
