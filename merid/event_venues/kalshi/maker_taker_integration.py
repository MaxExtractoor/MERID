"""Maker/Taker policy integration for order routing.

This module provides the integration layer between the order router and the
maker/taker policy engine. It enriches OrderIntent with fee-aware metadata
and adjusts prices for maker-friendly placement.

Strategy Policy Default:
    - Default policy mode is AGGRESSIVE_CONVICTION for 15m crypto trading
    - This is a deliberate choice to prefer maker placement when edge supports it
    - Can be overridden per-intent via intent.policy_mode

Usage:
    from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy
    
    intent = OrderIntent(...)
    apply_maker_taker_policy(intent)
    # intent now has expected_role, fee_type, estimated_fee_cents, etc.
"""

from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.maker_taker_integration")


def apply_maker_taker_policy(intent) -> None:
    """Apply maker/taker policy to an OrderIntent.
    
    This function:
    1. Fetches market state for bid/ask data
    2. Calls the policy engine to determine optimal role
    3. Enriches intent with policy decision metadata
    4. Adjusts price for maker-friendly placement if recommended
    
    CRITICAL FIX (2026-07-20): Exit orders bypass maker/taker policy since they use
    marketable IOC behavior to secure immediate fills. Maker/taker recommendations
    are not applicable for exits and would be confusing.
    
    Args:
        intent: OrderIntent to enrich with policy metadata
    """
    # CRITICAL FIX (2026-07-20): Skip maker/taker policy for exit orders
    # Exit orders use marketable IOC behavior and should not receive maker/taker recommendations
    from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_intent
    if is_exit_order_from_intent(intent):
        logger.info(
            f"[MAKER-TAKER] Skipping policy for exit order: ticker={intent.ticker} | "
            f"entry_or_exit={intent.entry_or_exit} | source={intent.source} | "
            f"Exit orders use marketable IOC behavior - maker/taker not applicable"
        )
        # Set explicit "taker" role for exits since they cross the spread
        intent.expected_role = "taker"
        intent.fee_type = "taker"
        intent.estimated_fee_cents = None  # Will be computed from fill
        intent.edge_net_of_fees_pct = None
        intent.policy_mode = "EXIT_ORDER_BYPASS"
        intent.post_only = False  # Exits are never post_only
        return
    
    try:
        from merid.event_venues.kalshi.maker_taker_policy import (
            PolicyMode,
            decide_order_role,
        )
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        
        # Get market state for bid/ask data
        market_state_store = get_kalshi_market_state_store()
        
        # Try to get from KalshiMarketState first (has direct best_bid_cents/best_ask_cents)
        base_state = market_state_store.get(intent.ticker) if market_state_store else None
        best_bid_cents = getattr(base_state, 'best_bid_cents', None) if base_state else None
        best_ask_cents = getattr(base_state, 'best_ask_cents', None) if base_state else None
        
        # If base state doesn't have bid/ask, try UnifiedMarketState.book
        if best_bid_cents is None or best_ask_cents is None:
            unified_state = market_state_store.get_unified(intent.ticker) if market_state_store else None
            if unified_state and unified_state.book:
                best_bid_cents = unified_state.book.best_yes_bid
                best_ask_cents = unified_state.book.best_yes_ask
        
        # Log if market state is missing (maker/taker decision will use synthetic book data)
        if best_bid_cents is None or best_ask_cents is None:
            logger.warning(
                f"[MAKER-TAKER] Market state unavailable for ticker={intent.ticker} | "
                f"best_bid={best_bid_cents} best_ask={best_ask_cents} | "
                f"Using synthetic book data (price ± 1 tick) for policy decision"
            )
        
        # Determine policy mode (default to AGGRESSIVE_CONVICTION for 15m crypto)
        policy_mode = PolicyMode.AGGRESSIVE_CONVICTION
        if intent.policy_mode:
            # Use explicit policy mode from intent if provided
            try:
                policy_mode = PolicyMode[intent.policy_mode.upper()]
            except (ValueError, KeyError):
                logger.warning(f"[MAKER-TAKER] Invalid policy_mode={intent.policy_mode}, using AGGRESSIVE_CONVICTION")
                policy_mode = PolicyMode.AGGRESSIVE_CONVICTION
        
        # Get edge from intent (default to 0 if not provided)
        edge_pct = intent.edge_pct or 0.0
        
        # Call policy engine to determine optimal role
        role_decision = decide_order_role(
            policy_mode=policy_mode,
            edge_pct=edge_pct,
            price_cents=intent.price_cents,
            market_best_bid_cents=best_bid_cents or intent.price_cents - 1,
            market_best_ask_cents=best_ask_cents or intent.price_cents + 1,
            contracts=intent.count,
            side=intent.side,
            action=intent.action,
        )
        
        # Enrich intent with policy decision metadata
        intent.expected_role = role_decision.recommended_role.value
        intent.fee_type = role_decision.recommended_role.value  # "maker" or "taker"
        intent.estimated_fee_cents = role_decision.fee_cents_estimate
        intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct
        intent.should_execute = role_decision.should_execute  # CRITICAL FIX (2026-08-01): Copy execution decision from policy engine
        intent.policy_mode = policy_mode.name
        
        # Apply post_only flag from policy decision
        # CRITICAL FIX (2026-07-12): Marketable intents (aggressiveness > 0) must NEVER be
        # forced to post_only=True. The router's marketable-limit logic prices these orders
        # to cross the spread; post_only would cause Kalshi "post-only cross" rejections or
        # leave the order resting unfilled. Policy post_only applies to resting intents only.
        intent_aggressiveness = getattr(intent, "aggressiveness", 0.0) or 0.0
        if intent_aggressiveness > 0.0:
            if role_decision.post_only:
                logger.info(
                    f"[MAKER-TAKER] Policy recommended maker/post_only but intent is marketable "
                    f"(aggressiveness={intent_aggressiveness:.2f}) - keeping post_only=False | "
                    f"ticker={intent.ticker}"
                )
            intent.post_only = False
        else:
            intent.post_only = role_decision.post_only
        
        # Skip maker price adjustment to ensure integer cents
        # if role_decision.recommended_role.value == "maker" and best_bid_cents and best_ask_cents:
        #     from merid.event_venues.kalshi.order_router import _price_for_side
        #     adjusted_price = _price_for_side(
        #         price_cents=intent.price_cents,
        #         side=intent.side,
        #         action=intent.action,
        #         best_bid_cents=best_bid_cents,
        #         best_ask_cents=best_ask_cents,
        #         maker_bias_cents=1,
        #     )
        #     if adjusted_price != intent.price_cents:
        #         logger.info(
        #             f"[MAKER-TAKER] Adjusted price for maker placement: {intent.price_cents}c -> {adjusted_price}c | "
        #             f"ticker={intent.ticker} | action={intent.action} | reason={role_decision.reason}"
        #         )
        #         intent.price_cents = int(adjusted_price)  # Ensure integer cents
        
        logger.info(
            f"[MAKER-TAKER] Policy decision: role={role_decision.recommended_role.value} | "
            f"post_only={intent.post_only} (applied) | policy_post_only={role_decision.post_only} (recommended) | "
            f"fee_cents={role_decision.fee_cents_estimate} | "
            f"edge_net_fees={role_decision.edge_net_of_fees_pct:.3f}% | reason={role_decision.reason}"
        )
        
    except Exception as e:
        logger.warning(f"[MAKER-TAKER] Policy engine failed, using defaults: {e}")
        # Fallback: set default values
        # NOTE: "unknown" fee_type/expected_role is a safe fallback that indicates
        # the policy engine failed. Downstream code should handle "unknown" gracefully
        # and not assume it means "maker" or "taker". The order will proceed with
        # the original price and no maker/taker optimization.
        intent.expected_role = "unknown"
        intent.fee_type = "unknown"
        intent.estimated_fee_cents = None
        intent.edge_net_of_fees_pct = None
        intent.policy_mode = None
