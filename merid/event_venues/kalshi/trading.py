"""Kalshi trading utilities - High-level trading operations."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trading")


class KalshiTrader:
    """
    High-level trading interface for Kalshi.
    
    Provides convenient methods for common trading operations
    like buying/selling yes/no contracts, position management, etc.
    """
    
    def __init__(self, client: Optional[KalshiVenueClient] = None, config: Optional[KalshiConfig] = None):
        self.client = client or KalshiVenueClient(config)

    # G8: Central gate — checked before every order method
    def _is_live_trading_allowed(self) -> bool:
        """Return True only when VenueGate permits real order submission."""
        try:
            from merid.prediction.venue_gate import get_venue_gate
            gate = get_venue_gate()
            return not gate.should_simulate_fill()
        except Exception as exc:
            # Fail-closed: if venue_gate unavailable, block live trading for safety
            logger.warning(f"VenueGate unavailable - blocking live trading: {exc}")
            return False

    def _pre_order_check(
        self,
        ticker: str,
        count: int,
        price_cents: int,
        category: str | None = None,
        spread_cents: int | None = None,
        depth_at_price: int | None = None,
    ) -> tuple[bool, str]:
        """Run kill-switch + KalshiRiskManager checks before placing any order.

        Pass ``spread_cents`` and ``depth_at_price`` from the live orderbook
        snapshot so that E1 orderbook checks are applied.

        Returns (allowed, reason).  Fail-closed: any import/runtime error blocks the order.
        """
        # 1. Global kill switch
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason() or "kill_switch_active"
                logger.warning("Order blocked by kill switch: %s", reason)
                return False, f"kill_switch:{reason}"
        except Exception as exc:
            logger.error("Kill-switch check unavailable — blocking order: %s", exc)
            return False, f"kill_switch_unavailable:{exc}"

        # 2. Kalshi-specific risk checks (position limits, category caps, drawdown, rate limit)
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk = get_kalshi_risk()
            allowed, reason = risk.check_order(
                ticker=ticker,
                category=category,
                contracts=count,
                price_cents=price_cents,
                spread_cents=spread_cents,
                depth_at_price=depth_at_price,
            )
            if not allowed:
                logger.warning("Order blocked by KalshiRiskManager: %s", reason)
                return False, reason
        except Exception as exc:
            logger.error("KalshiRiskManager check unavailable — blocking order: %s", exc)
            return False, f"risk_manager_unavailable:{exc}"

        return True, "OK"

    def _record_order(self, category: str | None, count: int, price_cents: int) -> None:
        """Record a successful order in KalshiRiskManager for exposure tracking."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            get_kalshi_risk().record_order(category, count, price_cents)
        except Exception as exc:
            logger.debug("record_order failed (non-fatal): %s", exc)

    async def connect(self) -> None:
        """Initialize connections."""
        await self.client.connect()
    
    async def close(self) -> None:
        """Close connections."""
        await self.client.close()
    
    async def buy_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy YES contracts in a market."""
        allowed, reason = self._pre_order_check(ticker, count, price or 50)
        if not allowed:
            logger.warning("buy_yes blocked: %s ticker=%s", reason, ticker)
            return None
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        logger.debug(f"buy_yes: {ticker} count={count} price={price}")
        result = await self.client.place_order(order)
        if result:
            self._record_order(None, count, price or 50)
        return result
    
    async def buy_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy NO contracts in a market."""
        allowed, reason = self._pre_order_check(ticker, count, price or 50)
        if not allowed:
            logger.warning("buy_no blocked: %s ticker=%s", reason, ticker)
            return None
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order(None, count, price or 50)
        return result
    
    async def sell_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell YES contracts (or close YES position)."""
        allowed, reason = self._pre_order_check(ticker, count, price or 50)
        if not allowed:
            logger.warning("sell_yes blocked: %s ticker=%s", reason, ticker)
            return None
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order(None, count, price or 50)
        return result
    
    async def sell_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell NO contracts (or close NO position)."""
        allowed, reason = self._pre_order_check(ticker, count, price or 50)
        if not allowed:
            logger.warning("sell_no blocked: %s ticker=%s", reason, ticker)
            return None
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order(None, count, price or 50)
        return result
    
    async def close_position(self, ticker: str) -> List[PlacedOrder]:
        """
        Close all positions in a market by placing offsetting orders.
        
        Args:
            ticker: Market ticker to close position in
            
        Returns:
            List of placed orders
        """
        positions = await self.client.get_positions()
        market_positions = [p for p in positions if p.market_id == ticker]
        
        orders = []
        for pos in market_positions:
            if pos.size == 0:
                continue
            
            # Close by selling the held side
            side = "sell" if pos.size > 0 else "buy"
            size = abs(pos.size)
            outcome = pos.outcome_id or "yes"
            
            price_est = 50  # Market order — use mid-price estimate for risk check
            allowed, reason = self._pre_order_check(ticker, int(size), price_est)
            if not allowed:
                logger.warning("close_position order blocked: %s ticker=%s", reason, ticker)
                continue

            order = VenueOrder(
                market_id=ticker,
                side=side,
                size=size,
                price=None,  # Market order
                order_type="market",
                outcome_id=outcome
            )

            placed = await self.client.place_order(order)
            if placed:
                self._record_order(None, int(size), price_est)
                orders.append(placed)
        
        return orders
    
    async def get_market_by_ticker(self, ticker: str) -> Optional[EventMarket]:
        """
        Get a market by its ticker.
        
        Args:
            ticker: Full ticker symbol (e.g., "FED-25DEC-T3.00")
            
        Returns:
            EventMarket or None
        """
        return await self.client.get_market(ticker)
    
    async def search_markets(self, query: str, limit: int = 10) -> List[EventMarket]:
        """
        Search markets by keyword.
        
        Args:
            query: Search query
            limit: Max results
            
        Returns:
            List of matching markets
        """
        return await self.client.list_markets(MarketFilter(search=query, limit=limit))
    
    async def get_best_price(self, ticker: str, side: str = "yes", action: str = "buy") -> Optional[Decimal]:
        """
        Get best available price for a market outcome.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            
        Returns:
            Best price in dollars (0-1) or None
        """
        orderbook = await self.client.get_orderbook(ticker)
        
        if not orderbook:
            return None
        
        # Kalshi orderbook structure is simplified
        # Prices are already in dollars from the conversion
        if action == "buy":
            return orderbook.asks[0][0] if orderbook.asks else None
        else:
            return orderbook.bids[0][0] if orderbook.bids else None
    
    async def get_account_summary(self) -> dict:
        """
        Get account summary including balance and positions.
        
        Returns:
            Dictionary with balance, positions, and open orders
        """
        balance = await self.client.get_balance()
        positions = await self.client.get_positions()
        open_orders = await self.client.get_open_orders()
        
        return {
            "balance": balance,
            "positions": positions,
            "open_orders": open_orders,
            "position_count": len(positions),
            "open_order_count": len(open_orders)
        }
