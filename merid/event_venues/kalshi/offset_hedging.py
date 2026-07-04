"""Offset Hedging Manager for Kalshi 15m Crypto Trading.

Implements offset hedging strategy: when holding YES, buy NO in same market
to cap downside while preserving upside.

Configuration:
- hedge_ratio: 30% hedge, 70% conviction
- min_edge_for_hedge: Only hedge when edge >= 3%
- max_hedge_notional_pct: Max 2% of equity for hedge
- rebalance_threshold: Rebalance when probability drifts > 5%
"""

from __future__ import annotations

import asyncio
import time as _time
from decimal import Decimal
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.offset_hedging")

# Profile integration
try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    _PROFILE_AVAILABLE = True
except ImportError:
    _PROFILE_AVAILABLE = False
    logger.warning("[OFFSET-HEDGING] Profile adapter not available, hedging disabled")


def _is_offset_hedging_enabled() -> bool:
    """Check if offset hedging is enabled from profile config."""
    if not _PROFILE_AVAILABLE:
        return False
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_enabled
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read offset_hedging_enabled: %s", e)
    
    return False


def _get_hedge_ratio() -> float:
    """Get hedge ratio from profile config."""
    if not _PROFILE_AVAILABLE:
        return 0.30  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_hedge_ratio
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read hedge_ratio: %s", e)
    
    return 0.30  # Default


def _get_min_edge_for_hedge() -> float:
    """Get minimum edge for hedge from profile config."""
    if not _PROFILE_AVAILABLE:
        return 0.03  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_min_edge_for_hedge
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read min_edge_for_hedge: %s", e)
    
    return 0.03  # Default


def _get_max_hedge_notional_pct() -> float:
    """Get max hedge notional percentage from profile config."""
    if not _PROFILE_AVAILABLE:
        return 0.02  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_max_hedge_notional_pct
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read max_hedge_notional_pct: %s", e)
    
    return 0.02  # Default


def _get_min_hedge_contracts() -> int:
    """Get minimum hedge contracts from profile config."""
    if not _PROFILE_AVAILABLE:
        return 1  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_min_hedge_contracts
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read min_hedge_contracts: %s", e)
    
    return 1  # Default


def _get_max_hedge_contracts() -> int:
    """Get maximum hedge contracts from profile config."""
    if not _PROFILE_AVAILABLE:
        return 3  # Default
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return profile.offset_hedging_max_hedge_contracts
    except Exception as e:
        logger.warning("[OFFSET-HEDGING] Failed to read max_hedge_contracts: %s", e)
    
    return 3  # Default


async def should_hedge_position(
    ticker: str,
    side: str,
    edge_pct: float,
    fill_price_cents: int,
    fill_count: int,
    bankroll_usd: float,
) -> Tuple[bool, Optional[int], Optional[str]]:
    """Determine if a position should be hedged and calculate hedge size.
    
    Args:
        ticker: Market ticker (e.g., KXBTC15M-26JUL020700-00)
        side: Side of the filled order ("yes" or "no")
        edge_pct: Edge percentage of the original trade
        fill_price_cents: Fill price in cents
        fill_count: Number of contracts filled
        bankroll_usd: Current bankroll in USD
        
    Returns:
        Tuple of (should_hedge, hedge_contracts, reason)
    """
    # Check if offset hedging is enabled
    if not _is_offset_hedging_enabled():
        return False, None, "offset_hedging_disabled"
    
    # Check if edge meets minimum threshold
    min_edge = _get_min_edge_for_hedge()
    if edge_pct < min_edge:
        return False, None, f"edge_below_threshold:{edge_pct:.4f}<{min_edge:.4f}"
    
    # Calculate hedge notional cap
    max_hedge_notional_pct = _get_max_hedge_notional_pct()
    max_hedge_notional_usd = bankroll_usd * max_hedge_notional_pct
    
    # Calculate hedge ratio
    hedge_ratio = _get_hedge_ratio()
    
    # Calculate hedge contracts based on hedge ratio
    hedge_contracts = int(fill_count * hedge_ratio)
    
    # Clamp to min/max contracts
    min_contracts = _get_min_hedge_contracts()
    max_contracts = _get_max_hedge_contracts()
    hedge_contracts = max(min_contracts, min(max_contracts, hedge_contracts))
    
    # Calculate hedge notional
    hedge_notional_usd = (hedge_contracts * fill_price_cents) / 100.0
    
    # Check if hedge notional exceeds cap
    if hedge_notional_usd > max_hedge_notional_usd:
        # Reduce contracts to fit within cap
        hedge_contracts = int((max_hedge_notional_usd * 100.0) / fill_price_cents)
        hedge_contracts = max(min_contracts, min(max_contracts, hedge_contracts))
        logger.info(
            "[OFFSET-HEDGING] Hedge notional capped: original=%.2f capped=%.2f contracts=%d",
            hedge_notional_usd, max_hedge_notional_usd, hedge_contracts
        )
    
    logger.info(
        "[OFFSET-HEDGING] Hedge check: ticker=%s side=%s edge=%.4f fill_count=%d "
        "hedge_contracts=%d hedge_notional=%.2f bankroll=%.2f",
        ticker, side, edge_pct, fill_count, hedge_contracts, hedge_notional_usd, bankroll_usd
    )
    
    return True, hedge_contracts, "hedge_approved"


async def place_hedge_order(
    ticker: str,
    hedge_side: str,
    hedge_contracts: int,
    fill_price_cents: int,
) -> bool:
    """Place a hedge order in the opposite side.
    
    Args:
        ticker: Market ticker
        hedge_side: Opposite side to hedge ("no" if original was "yes", vice versa)
        hedge_contracts: Number of contracts to hedge
        fill_price_cents: Reference price for limit order
        
    Returns:
        True if hedge order placed successfully, False otherwise
    """
    try:
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.prediction.trading_mode import TradingMode
        
        # Determine hedge action (always buy for hedge)
        hedge_action = "buy"
        
        # Set limit price slightly better than fill price to increase fill probability
        # For NO hedge when YES was bought: buy NO at current NO bid
        # For YES hedge when NO was bought: buy YES at current YES bid
        hedge_price_cents = fill_price_cents  # Simplified: use same price
        
        # Create hedge intent
        hedge_intent = OrderIntent(
            ticker=ticker,
            side=hedge_side,
            action=hedge_action,
            price_cents=hedge_price_cents,
            count=hedge_contracts,
            mode=TradingMode.LIVE,
            edge_pct=0.0,  # Hedge orders have no edge requirement
            source="offset_hedging",
            decision_trace_id="hedge",
            sentiment_driven=False,
        )
        
        logger.info(
            "[OFFSET-HEDGING] Placing hedge order: ticker=%s side=%s count=%d price=%dc",
            ticker, hedge_side, hedge_contracts, hedge_price_cents
        )
        
        # Route hedge order
        result = await route_order_async(hedge_intent)
        
        if result.status in ("filled_live", "accepted_live"):
            logger.info(
                "[OFFSET-HEDGING] Hedge order placed successfully: ticker=%s side=%s count=%d status=%s",
                ticker, hedge_side, hedge_contracts, result.status
            )
            return True
        else:
            logger.warning(
                "[OFFSET-HEDGING] Hedge order failed: ticker=%s side=%s count=%d status=%s reason=%s",
                ticker, hedge_side, hedge_contracts, result.status, result.reason
            )
            return False
            
    except Exception as e:
        logger.error("[OFFSET-HEDGING] Failed to place hedge order: %s", e, exc_info=True)
        return False


async def handle_fill_for_hedging(
    ticker: str,
    side: str,
    edge_pct: float,
    fill_price_cents: int,
    fill_count: int,
    bankroll_usd: float,
) -> bool:
    """Handle a fill and potentially place a hedge order.
    
    This is called after a successful fill to determine if hedging is needed
    and place the hedge order if appropriate.
    
    Args:
        ticker: Market ticker
        side: Side of the filled order
        edge_pct: Edge percentage of the original trade
        fill_price_cents: Fill price in cents
        fill_count: Number of contracts filled
        bankroll_usd: Current bankroll in USD
        
    Returns:
        True if hedge was placed or not needed, False if hedge failed
    """
    # Determine if hedging is needed
    should_hedge, hedge_contracts, reason = await should_hedge_position(
        ticker, side, edge_pct, fill_price_cents, fill_count, bankroll_usd
    )
    
    if not should_hedge:
        logger.info("[OFFSET-HEDGING] No hedge needed: ticker=%s reason=%s", ticker, reason)
        return True
    
    # Determine hedge side (opposite of fill side)
    hedge_side = "no" if side == "yes" else "yes"
    
    # Place hedge order
    hedge_success = await place_hedge_order(
        ticker, hedge_side, hedge_contracts, fill_price_cents
    )
    
    if hedge_success:
        logger.info(
            "[OFFSET-HEDGING] Hedge placed successfully: ticker=%s original_side=%s hedge_side=%s contracts=%d",
            ticker, side, hedge_side, hedge_contracts
        )
    else:
        logger.warning(
            "[OFFSET-HEDGING] Hedge placement failed: ticker=%s original_side=%s hedge_side=%s contracts=%d",
            ticker, side, hedge_side, hedge_contracts
        )
    
    return hedge_success
