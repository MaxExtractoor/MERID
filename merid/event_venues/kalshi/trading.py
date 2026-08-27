"""Kalshi trading utilities - High-level trading operations."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import Any, List, Optional

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trading")


class KalshiTrader:
    """
    High-level trading interface for Kalshi.
    
    Provides convenient methods for common trading operations
    like buying/selling yes/no contracts, position management, etc.
    """
    
    def __init__(self, client: Optional[KalshiVenueClient] = None, config: Optional[Any] = None):
        # Use unified config by default
        config = config or get_kalshi_config()
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

    def _pre_order_check(self, ticker: str, count: int, price_cents: int, category: str | None = None) -> tuple[bool, str]:
        """Run kill-switch + KalshiRiskManager checks before placing any order.

        Returns (allowed, reason).  Fail-closed: any import/runtime error blocks the order.
        """
        # Direct KalshiTrader client bypass is not allowed in production.
        # All production orders must flow through order_router so the
        # ExecutionRiskFirewall and other invariants are enforced.
        try:
            from merid.settings import settings
            if settings.is_production:
                logger.critical(
                    "[KalshiTrader] Direct client order bypass blocked in production. "
                    "Use order_router instead."
                )
                return False, "direct_client_bypass_blocked_in_production"
        except Exception as exc:
            logger.warning("[KalshiTrader] Failed to read settings: %s", exc)
        # CRITICAL FIX: 2026-07-09 - Enforce max 2 contracts per order
        # This prevents multi-contract orders from bypassing the global $2 exposure cap
        from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER
        if count > MAX_CONTRACTS_PER_ORDER:
            logger.error(
                "[KalshiTrader] Order rejected: count=%d exceeds max %d contracts per order | ticker=%s",
                count, MAX_CONTRACTS_PER_ORDER, ticker
            )
            return False, f"max_contracts_exceeded:count={count}>1"

        # 2026-07-05 FIX: REMOVED price range validation [50, 70]
        # This check was preventing orders from filling at actual market prices
        # Orders now use actual market mid-spread prices for proper execution

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
            from merid.event_venues.kalshi.market_filter import (
                group_id_from_ticker,
                extract_asset_from_ticker,
                get_series_timeframe_bucket,
            )
            risk = get_kalshi_risk()
            # Look up existing position so per-contract limit check is accurate
            _existing_pos = 0
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                _cached = get_position_cache().get_position(ticker)
                if _cached is not None:
                    _existing_pos = _cached.contracts
            except Exception as e:
                logger.debug(f"Position cache lookup failed: {e}")

            # Derive asset/timeframe for group-level risk aggregation using canonical helper
            _group_id = group_id_from_ticker(ticker)
            _asset = extract_asset_from_ticker(ticker)
            _timeframe = get_series_timeframe_bucket(ticker)
            
            allowed, reason = risk.check_order(
                ticker=ticker,
                category=category,
                contracts=count,
                price_cents=price_cents,
                existing_position=_existing_pos,
                asset=_asset,
                timeframe=_timeframe,
                group_id=_group_id,
            )
            if not allowed:
                logger.warning("Order blocked by KalshiRiskManager: %s", reason)
                return False, reason
        except Exception as exc:
            logger.error("KalshiRiskManager check unavailable — blocking order: %s", exc)
            return False, f"risk_manager_unavailable:{exc}"

        return True, "OK"

    def _record_order(
        self,
        category: str | None,
        count: int,
        price_cents: int,
        ticker: str | None = None,
        group_id: str | None = None,
        asset: str | None = None,
        timeframe: str | None = None,
    ) -> None:
        """Record a successful order in KalshiRiskManager for exposure tracking.

        Args:
            category: Risk category (e.g., "crypto")
            count: Number of contracts
            price_cents: Price per contract in cents
            ticker: Market ticker (used to derive group context if group_id not provided)
            group_id: Pre-computed group ID (if available)
            asset: Asset symbol (if pre-computed)
            timeframe: Timeframe bucket (if pre-computed)
        """
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            from merid.event_venues.kalshi.market_filter import (
                group_id_from_ticker,
                extract_asset_from_ticker,
                get_series_timeframe_bucket,
            )

            risk = get_kalshi_risk()

            # Use provided group_id, or derive from ticker using canonical helper
            if group_id:
                _group_id = group_id
                _asset = asset
                _timeframe = timeframe
            elif ticker:
                _group_id = group_id_from_ticker(ticker)
                _asset = asset or extract_asset_from_ticker(ticker)
                _timeframe = timeframe or get_series_timeframe_bucket(ticker)
            else:
                # No ticker, no group_id - fallback to basic rate-only recording
                risk.record_rate_only()
                return

            risk.record_order(
                category=category,
                contracts=count,
                price_cents=price_cents,
                group_id=_group_id,
                asset=_asset,
                timeframe=_timeframe,
            )
        except Exception as exc:
            logger.debug("record_order failed (non-fatal): %s", exc)

    async def connect(self) -> None:
        """Initialize connections."""
        await asyncio.wait_for(self.client.connect(), timeout=10.0)
    
    async def close(self) -> None:
        """Close connections."""
        await self.client.close()
    
    async def buy_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy YES contracts in a market."""
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
        
        if not self._is_live_trading_allowed():
            logger.debug("buy_yes: skipped (paper/sim mode) ticker=%s", ticker)
            return None
        allowed, reason = self._pre_order_check(ticker, count, price or DEFAULT_KALSHI_PRICE_CENTS)
        if not allowed:
            logger.warning("buy_yes blocked: %s ticker=%s", reason, ticker)
            return None
        # BUG-FIX: Pass price for ALL orders (including market) to avoid fallback in Kalshi client
        # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        logger.debug(f"buy_yes: {ticker} count={count} price={price}")
        result = await self.client.place_order(order)
        if result:
            self._record_order("crypto", count, price or DEFAULT_KALSHI_PRICE_CENTS, ticker=ticker)
        return result
    
    async def buy_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy NO contracts in a market."""
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
        
        if not self._is_live_trading_allowed():
            logger.debug("buy_no: skipped (paper/sim mode) ticker=%s", ticker)
            return None
        allowed, reason = self._pre_order_check(ticker, count, price or DEFAULT_KALSHI_PRICE_CENTS)
        if not allowed:
            logger.warning("buy_no blocked: %s ticker=%s", reason, ticker)
            return None
        # BUG-FIX: Pass price for ALL orders (including market) to avoid fallback in Kalshi client
        # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order("crypto", count, price or DEFAULT_KALSHI_PRICE_CENTS, ticker=ticker)
        return result
    
    async def sell_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell YES contracts (or close YES position)."""
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
        
        if not self._is_live_trading_allowed():
            logger.debug("sell_yes: skipped (paper/sim mode) ticker=%s", ticker)
            return None
        allowed, reason = self._pre_order_check(ticker, count, price or DEFAULT_KALSHI_PRICE_CENTS)
        if not allowed:
            logger.warning("sell_yes blocked: %s ticker=%s", reason, ticker)
            return None
        # BUG-FIX: Pass price for ALL orders (including market) to avoid fallback in Kalshi client
        # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order("crypto", count, price or DEFAULT_KALSHI_PRICE_CENTS, ticker=ticker)
        return result
    
    async def sell_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell NO contracts (or close NO position)."""
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
        
        if not self._is_live_trading_allowed():
            logger.debug("sell_no: skipped (paper/sim mode) ticker=%s", ticker)
            return None
        allowed, reason = self._pre_order_check(ticker, count, price or DEFAULT_KALSHI_PRICE_CENTS)
        if not allowed:
            logger.warning("sell_no blocked: %s ticker=%s", reason, ticker)
            return None
        # BUG-FIX: Pass price for ALL orders (including market) to avoid fallback in Kalshi client
        # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        result = await self.client.place_order(order)
        if result:
            self._record_order("crypto", count, price or DEFAULT_KALSHI_PRICE_CENTS, ticker=ticker)
        return result
    
    async def close_position(self, ticker: str) -> List[PlacedOrder]:
        """
        Close all positions in a market by placing offsetting orders.
        
        Args:
            ticker: Market ticker to close position in
            
        Returns:
            List of placed orders
        """
        if not self._is_live_trading_allowed():
            logger.debug("close_position: skipped (paper/sim mode) ticker=%s", ticker)
            return []
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
            
            # PRODUCTION-FIX: Use actual market price from KalshiMarketStateStore instead of hardcoded 50c
            price_est = 50  # Fallback if market state unavailable
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                state = get_kalshi_market_state_store().get_unified(ticker)
                if state and state.mid_cents > 0:
                    price_est = state.mid_cents
            except Exception as _exc:
                logger.debug("close_position: failed to fetch market state for %s, using 50c fallback: %s", ticker, _exc)
            
            allowed, reason = self._pre_order_check(ticker, int(size), price_est)
            if not allowed:
                logger.warning("close_position order blocked: %s ticker=%s", reason, ticker)
                continue

            # BUG-FIX: Pass price for ALL orders (including market) to avoid 50c fallback in Kalshi client
            # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
            order = VenueOrder(
                market_id=ticker,
                side=side,
                size=size,
                price=Decimal(price_est) / 100,
                order_type="market",
                outcome_id=outcome
            )

            placed = await self.client.place_order(order)
            if placed:
                self._record_order("crypto", int(size), price_est, ticker=ticker)
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
