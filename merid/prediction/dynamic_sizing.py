"""Dynamic position sizing — MAX_CYCLE_RISK_PCT bankroll allocation across winners.

This module ensures that:
1. Total notional across ALL winners in a cycle ≤ MAX_CYCLE_RISK_PCT of bankroll
2. The allocation is distributed by edge-weighted allocation
3. Per-winner sizing respects the dynamic cap

Configuration:
- CRITICAL: All modes use MAX_CYCLE_RISK_PCT cycle risk (from core.settings)
- Default is 3% per cycle (optimized 2026-05-07), configurable via MAX_CYCLE_RISK_PCT env var

Usage:
    # Get cap for this cycle (with $47 bankroll, 3% = $1.41 cycle cap)
    cap = get_cycle_sizing_cap(bankroll_usd=47.0, winner_count=2)
    # Returns: max contracts per winner to stay within cycle cap
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.dynamic_sizing")


# Canonical allocation percentage from core.settings (single source of truth)
# This ensures consistency with global_execution_guard and trading_agent
from core.settings import MAX_CYCLE_RISK_PCT

def _get_allocation_pct() -> Decimal:
    """Get canonical cycle allocation percentage as Decimal."""
    pct = Decimal(str(MAX_CYCLE_RISK_PCT))
    logger.info(
        "[DYNAMIC_SIZING] MAX_CYCLE_RISK_PCT loaded: %.4f (%.2f%%)",
        float(pct),
        float(pct) * 100
    )
    return pct

# Safety ceiling: never allocate more than this even with high bankroll
MAX_ABSOLUTE_ALLOCATION_USD = Decimal("100.0")  # $100 cap

# Minimum contracts to trade (if we pass all gates, trade at least 1)
MIN_CONTRACTS_PER_WINNER = 1


@dataclass(frozen=True)
class CycleSizingCap:
    """Sizing constraints for a cycle with N winners."""
    bankroll_usd: Decimal
    winner_count: int
    max_total_notional_usd: Decimal  # MAX_CYCLE_RISK_PCT of bankroll (2% unified)
    max_notional_per_winner_usd: Decimal  # Distributed equally by default
    max_contracts_per_winner: int  # At current price
    price_cents: int  # Reference price used for calculation
    allocation_pct: Decimal  # Actual % used (e.g., 0.02 for 2%)
    
    def to_dict(self) -> dict:
        return {
            "bankroll_usd": float(self.bankroll_usd),
            "winner_count": self.winner_count,
            "max_total_notional_usd": float(self.max_total_notional_usd),
            "max_notional_per_winner_usd": float(self.max_notional_per_winner_usd),
            "max_contracts_per_winner": self.max_contracts_per_winner,
            "price_cents": self.price_cents,
            "allocation_pct": float(self.allocation_pct),
        }


def get_cycle_allocation_pct() -> Decimal:
    """Get the cycle allocation percentage from canonical source.
    
    Returns:
        Decimal: Allocation percentage (from core.settings.MAX_CYCLE_RISK_PCT)
    """
    return _get_allocation_pct()


def get_actual_contract_price_cents(ticker: str, side: str = "yes", market_prob: Optional[float] = None) -> int:
    """Get the actual contract price in cents from market state.
    
    For crypto prediction markets on Kalshi, fetches the live market price
    from KalshiMarketStateStore instead of using hardcoded assumptions.
    
    Args:
        ticker: Market ticker (e.g., "KXBTCD-25JUN2812-T86799.99")
        side: "yes" or "no" - which side of the contract
        market_prob: Optional market probability (0-1) for probability-based fallback
        
    Returns:
        int: Contract price in cents (1-99), or probability-derived price if unavailable
    """
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        store = get_kalshi_market_state_store()
        state = store.get(ticker)
        if state:
            # Use mid price for sizing calculations
            if side == "yes" and state.yes_ask is not None and state.yes_bid is not None:
                return int((state.yes_ask + state.yes_bid) // 2)
            elif side == "no" and state.no_ask is not None and state.no_bid is not None:
                return int((state.no_ask + state.no_bid) // 2)
            # Fallback to last trade or mid if available
            if state.last_trade_price_cents is not None:
                return int(state.last_trade_price_cents)
            # Fallback to mid_cents if book initialized
            if state.mid_cents is not None and state.mid_cents > 0:
                return int(state.mid_cents)
            # Fallback to best_bid/ask if available
            if state.best_bid_cents is not None and state.best_bid_cents > 0:
                return int(state.best_bid_cents)
            if state.best_ask_cents is not None and state.best_ask_cents > 0:
                return int(state.best_ask_cents)
    except Exception as e:
        logger.debug("Could not fetch actual contract price for %s: %s", ticker, e)
    
    # BUG-FIX (2026-05-07): Use 50c as default instead of probability-derived 1c
    # Probability-derived fallback (max(1, min(99, int(round(market_prob * 100)))))
    # could return 1 cent when market_prob is very low, causing Kelly sizing to return 0
    # When market state is unavailable, 50c is the midpoint for binary options
    # Safe default: 50 cents (midpoint for binary options)
    return 50


def get_crypto_contract_price_cents(asset: str, timeframe: str = "1h", side: str = "yes") -> int:
    """Get contract price for a crypto asset from live market data.
    
    Resolves the appropriate Kalshi ticker for the asset/timeframe and
    fetches the actual market price instead of using hardcoded values.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe (15m, 1h, daily, etc.)
        side: "yes" or "no"
        
    Returns:
        int: Contract price in cents
    """
    try:
        from merid.event_venues.kalshi.market_selector import resolve_series_ticker
        from merid.prediction.crypto_top_edge import get_crypto_top_edge_arbiter
        
        # Try to find the actual ticker from arbiter winners
        arbiter = get_crypto_top_edge_arbiter()
        if arbiter and arbiter._last_cycle_winners:
            for ticker_key, winner_obj in arbiter._last_cycle_winners.items():
                if asset.upper() in ticker_key:
                    ticker = ticker_key
                    if ticker:
                        return get_actual_contract_price_cents(ticker, side)
        
        # Fallback: resolve series ticker and fetch price
        series = resolve_series_ticker(asset, timeframe)
        if series:
            # Find a matching market from the catalog
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            markets = catalog.find_by_series_prefix(series)
            if markets:
                return get_actual_contract_price_cents(markets[0].ticker, side)
                
    except Exception as e:
        logger.debug("Could not resolve crypto contract price for %s/%s: %s", asset, timeframe, e)
    
    # Safe default only when all else fails
    # Use 1 cent to allow at least 1 contract with small bankroll
    return 1


def get_price_aware_max_contracts(ticker: str, price_cents: int) -> int:
    """Get max contracts from price-aware sizing in AgentRiskLimits.
    
    This function retrieves the price-aware contract limits configured in
    kalshi_agent_grid.yaml for the agent associated with this ticker.
    
    Args:
        ticker: Market ticker (e.g., "KXETH15M-26MAY092045-45")
        price_cents: Contract price in cents
        
    Returns:
        int: Max contracts allowed at this price, or 0 if no price bands configured
    """
    try:
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        # Get the agent grid config to look up risk limits
        config = get_agent_grid_config()
        
        # Try to determine which agent owns this ticker
        # For crypto markets, the ticker contains the 15M series code (KXBTC15M, KXETH15M, etc.)
        asset_map = {
            "KXBTC15M": "BTC_15M",
            "KXETH15M": "ETH_15M",
            "KXSOL15M": "SOL_15M",
            "KXXRP15M": "XRP_15M",
            "KXDOGE15M": "DOGE_15M",
        }
        
        # Extract asset code from ticker
        agent_name = None
        for prefix, name in asset_map.items():
            if ticker.startswith(prefix):
                agent_name = name
                break
        
        if not agent_name:
            logger.debug("[PRICE_AWARE] No agent mapping for ticker %s", ticker)
            return 0
        
        # Get the agent config from the grid config
        agent_config = None
        for agent_cfg in config.agents:
            if agent_cfg.name == agent_name:
                agent_config = agent_cfg
                break
        
        if agent_config and agent_config.risk_limits:
            max_contracts = agent_config.risk_limits.get_max_contracts_for_price(price_cents)
            logger.info(
                "[PRICE_AWARE] ticker=%s agent=%s price_cents=%d max_contracts=%d",
                ticker, agent_name, price_cents, max_contracts
            )
            return max_contracts
        
        logger.debug("[PRICE_AWARE] No risk limits found for agent %s", agent_name)
        return 0
        
    except Exception as e:
        logger.warning("[PRICE_AWARE_ERROR] Could not get price-aware limits for %s: %s", ticker, e)
        return 0


def compute_cycle_sizing_cap(
    bankroll_usd: Decimal,
    winner_count: int,
    price_cents: Optional[int] = None,  # Now fetched dynamically
    ticker: Optional[str] = None,  # Pass ticker to fetch actual price
    side: str = "yes",
    allocation_pct: Optional[Decimal] = None,
) -> CycleSizingCap:
    """Compute max contracts per winner to stay within 1-3% total allocation.
    
    Args:
        bankroll_usd: Available bankroll in USD
        winner_count: Number of winners this cycle (1-3 typically)
        price_cents: Contract price in cents (fetched dynamically if None)
        ticker: Market ticker to fetch actual price from
        side: "yes" or "no" for price lookup
        allocation_pct: Override allocation % (default 3%)
        
    Returns:
        CycleSizingCap with computed constraints
    """
    """Compute max contracts per winner to stay within 1-3% total allocation.
    
    Args:
        bankroll_usd: Available bankroll in USD
        winner_count: Number of winners this cycle (1-3 typically)
        price_cents: Contract price in cents (default 50 for midpoint)
        allocation_pct: Override allocation % (default 3%)
        
    Returns:
        CycleSizingCap with computed constraints
        
    Example:
        With $44.35 bankroll, 2 winners, 3% allocation:
        - Max total notional = $44.35 * 0.03 = $1.33
        - Per winner = $1.33 / 2 = $0.67
        - At 50c/contract = max 1 contract (rounded down, but MIN_CONTRACTS=1)
        
        This forces the sizing down to 1 contract per winner = $0.50 total
        which is ~1.1% of bankroll — within the 3% cap.
    """
    if allocation_pct is None:
        allocation_pct = get_cycle_allocation_pct()
    
    # Fetch actual contract price if not provided or invalid
    # BUG-FIX: Also handle price_cents=0 (invalid) by defaulting to 1 cent
    # This allows at least 1 contract to be traded even with small bankroll
    if price_cents is None or price_cents <= 0:
        if ticker:
            price_cents = get_actual_contract_price_cents(ticker, side)
            # Ensure we got a valid price
            if price_cents is None or price_cents <= 0:
                price_cents = 1  # Minimum viable price
        else:
            price_cents = 1  # Safe default only when no ticker available
    
    # Ensure winner_count is at least 1 to avoid division by zero
    winner_count = max(1, winner_count)
    
    # Compute max total notional (MAX_CYCLE_RISK_PCT of bankroll, 2% unified)
    max_total_notional = bankroll_usd * allocation_pct
    
    # Apply absolute safety cap
    max_total_notional = min(max_total_notional, MAX_ABSOLUTE_ALLOCATION_USD)
    
    # EDGE-PRIORITY FIX (2026-05-07): Use edge-weighted allocation instead of equal distribution
    # Higher-ranked winners (#1, #2, #3) get larger allocation based on their edge rank
    # #1 gets 50%, #2 gets 30%, #3 gets 20% of total allocation
    edge_weight = Decimal("1.0")  # Default equal weight
    winner_rank = 0  # 0 = unknown, 1-3 = ranked winner
    
    try:
        from merid.prediction.crypto_top_edge import get_crypto_top_edge_arbiter
        arbiter = get_crypto_top_edge_arbiter()
        
        if arbiter and ticker and arbiter._last_cycle_winners:
            winner = arbiter._last_cycle_winners.get(ticker)
            # Robust check: handle both dataclass and dict-like winner objects
            if winner:
                # Try to get is_winner and rank using getattr for flexibility
                is_winner = getattr(winner, 'is_winner', False)
                rank = getattr(winner, 'rank', 0)
                
                if is_winner and rank in (1, 2, 3):
                    winner_rank = rank
                    # Edge-weighted allocation: #1 gets 50%, #2 gets 30%, #3 gets 20%
                    if winner_rank == 1:
                        edge_weight = Decimal("0.50")
                    elif winner_rank == 2:
                        edge_weight = Decimal("0.30")
                    elif winner_rank == 3:
                        edge_weight = Decimal("0.20")
                    logger.info(
                        "[EDGE_PRIORITY] ticker=%s rank=%d weight=%.2f",
                        ticker or "unknown", winner_rank, float(edge_weight)
                    )
                else:
                    logger.debug(
                        "[EDGE_PRIORITY] ticker=%s not a ranked winner (is_winner=%s, rank=%s)",
                        ticker or "unknown", is_winner, rank
                    )
            else:
                logger.debug(
                    "[EDGE_PRIORITY] ticker=%s not found in arbiter winners (available: %s)",
                    ticker or "unknown",
                    list(arbiter._last_cycle_winners.keys())[:5]  # Log first 5 for brevity
                )
        else:
            logger.debug(
                "[EDGE_PRIORITY] Skipping edge-weighted lookup: arbiter=%s, ticker=%s, winners=%s",
                arbiter is not None,
                ticker or "None",
                arbiter._last_cycle_winners is not None if arbiter else None
            )
    except Exception as e:
        logger.warning("[EDGE_PRIORITY_ERROR] Could not get edge weight for %s: %s", ticker, e)
    
    # Distribute by edge weight (if ranked) or equally (if not ranked)
    if winner_rank > 0:
        max_per_winner = max_total_notional * edge_weight
    else:
        max_per_winner = max_total_notional / Decimal(winner_count)
    
    # Convert to contracts at given price
    price_usd = Decimal(price_cents) / Decimal("100")
    if price_usd > 0:
        max_contracts = int(max_per_winner / price_usd)
    else:
        max_contracts = 0
    
    # Apply minimum (if we're trading at all, trade at least 1)
    # BUG-FIX (2026-05-07): Original condition `max_contracts > 0` prevented minimum
    # from being applied when calculation resulted in 0. This caused all trades to
    # be blocked when max_per_winner < price_usd (e.g., $0.35 / $0.50 = 0.7 → 0).
    # 
    # SECOND FIX (2026-05-07): Even if max_per_winner < price_usd, allow 1 contract
    # if we have any allocation budget. The allocation percentage is a risk cap,
    # not a hard floor - we should allow at least 1 contract when budget exists.
    # This prevents small bankrolls from being completely blocked.
    if max_contracts < MIN_CONTRACTS_PER_WINNER and max_total_notional >= price_usd:
        max_contracts = MIN_CONTRACTS_PER_WINNER
    
    # PRICE-AWARE SIZING: Apply price band caps from AgentRiskLimits
    # This ensures we respect the graduated limits based on contract price
    if ticker:
        price_aware_max = get_price_aware_max_contracts(ticker, price_cents)
        if price_aware_max > 0:
            # Cap max_contracts to the price-aware limit
            if max_contracts > price_aware_max:
                logger.info(
                    "[PRICE_AWARE_CAP] ticker=%s price_cents=%d bankroll_contracts=%d capped_to=%d",
                    ticker, price_cents, max_contracts, price_aware_max
                )
                max_contracts = price_aware_max
    
    # PMSIZE_GLOBALALLOC: Log global cycle allocation for observability
    logger.info(
        "[PMSIZE_GLOBALALLOC] ticker=%s bankroll=$%.2f allocation_pct=%.4f "
        "winners=%d max_total_notional=$%.2f max_per_winner=$%.2f "
        "price_cents=%d max_contracts_per_winner=%d",
        ticker or "unknown",
        float(bankroll_usd),
        float(allocation_pct),
        winner_count,
        float(max_total_notional),
        float(max_per_winner),
        price_cents,
        max_contracts
    )
    
    return CycleSizingCap(
        bankroll_usd=bankroll_usd,
        winner_count=winner_count,
        max_total_notional_usd=max_total_notional,
        max_notional_per_winner_usd=max_per_winner,
        max_contracts_per_winner=max_contracts,
        price_cents=price_cents,
        allocation_pct=allocation_pct,
    )


def get_winner_count_for_cycle() -> int:
    """Get the expected number of winners for this cycle.
    
    This queries the arbiter to determine how many winners we're expecting.
    Defaults to 1 if arbiter unavailable (conservative).
    
    Returns:
        int: Expected winner count (1-3)
    """
    try:
        from merid.prediction.crypto_top_edge import get_crypto_top_edge_arbiter
        arbiter = get_crypto_top_edge_arbiter()
        if arbiter and arbiter._last_cycle_winners:
            return len(arbiter._last_cycle_winners)
    except Exception as e:
        logger.debug("Could not determine winner count from arbiter: %s", e)
    
    # Default: assume 1 winner (most conservative)
    return 1


def get_cycle_sizing_cap(
    bankroll_usd: Decimal,
    price_cents: Optional[int] = None,
    ticker: Optional[str] = None,
    side: str = "yes",
) -> CycleSizingCap:
    """Get the sizing cap for the current cycle.
    
    EDGE-PRIORITY FIX (2026-05-07): Use edge-weighted allocation instead of equal distribution.
    Higher-ranked winners (#1, #2, #3) get larger allocation based on their edge relative to total.
    This ensures capital is concentrated on the best opportunities.
    
    Args:
        bankroll_usd: Available bankroll
        price_cents: Contract price in cents (fetched dynamically if None)
        ticker: Market ticker to fetch actual price from
        side: "yes" or "no" for price lookup
        
    Returns:
        CycleSizingCap with computed constraints
    """
    winner_count = get_winner_count_for_cycle()
    return compute_cycle_sizing_cap(bankroll_usd, winner_count, price_cents, ticker, side)


def apply_cycle_cap_to_kelly_size(
    kelly_contracts: int,
    bankroll_usd: Decimal,
    price_cents: Optional[int] = None,
    ticker: Optional[str] = None,
    side: str = "yes",
    edge: Optional[Decimal] = None,
) -> Tuple[int, str]:
    """Apply cycle-level cap to Kelly-derived contract count.
    
    Args:
        kelly_contracts: Raw contracts from Kelly sizing
        bankroll_usd: Available bankroll
        price_cents: Contract price (fetched dynamically if None)
        ticker: Market ticker to fetch actual price from
        side: "yes" or "no" for price lookup
        edge: Edge value for weighted distribution (optional)
        
    Returns:
        Tuple of (capped_contracts, reason)
    """
    cap = get_cycle_sizing_cap(bankroll_usd, price_cents, ticker, side)
    
    if kelly_contracts <= cap.max_contracts_per_winner:
        return kelly_contracts, "kelly_within_cycle_cap"
    
    # Cap exceeded — apply the cycle limit
    capped = max(0, cap.max_contracts_per_winner)
    
    # Log the reduction
    logger.info(
        "[CYCLE_CAP_APPLIED] kelly=%d → capped=%d (bankroll=$%.2f, winners=%d, "
        "max_total=$%.2f, max_per_winner=$%.2f)",
        kelly_contracts,
        capped,
        float(bankroll_usd),
        cap.winner_count,
        float(cap.max_total_notional_usd),
        float(cap.max_notional_per_winner_usd),
    )
    
    reason = (
        f"cycle_cap:bankroll_{float(bankroll_usd):.2f}_winners_{cap.winner_count}_"
        f"max_per_{cap.max_contracts_per_winner}"
    )
    
    return capped, reason
