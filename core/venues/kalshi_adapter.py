"""MERID Kalshi Adapter - CFTC-Regulated US Prediction Markets.

US-compliant prediction market trading via Kalshi Trade API v2.
Uses RSA key-based authentication with JWT bearer tokens.

Env vars:
    KALSHI_API_KEY_ID       — API key ID from Kalshi dashboard
    KALSHI_PRIVATE_KEY_PATH — path to RSA private key PEM file
    KALSHI_PRIVATE_KEY_PEM  — raw PEM string (alternative to path)
    KALSHI_API_HOST         — base URL (default: elections trade-api v2)
    KALSHI_USE_DEMO         — set to "true" for demo environment
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime, timezone
import asyncio
import time
import uuid
import structlog
import os

import httpx

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig, KalshiOrder
from merid.event_venues.base import VenueOrder
from merid.resilience import OperationResult

logger = structlog.get_logger(__name__)

class KalshiAdapter(VenueAdapter):
    """Kalshi adapter for US-regulated prediction markets.
    
    Wraps the resilient KalshiVenueClient to provide the VenueAdapter interface.
    Supports MOCK, PAPER, and LIVE modes.
    """
    _is_stub = False  # Now a real adapter

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        use_demo: bool = True,
        paper: bool = True,
    ):
        super().__init__("kalshi", paper=paper)
        config = KalshiConfig(
            api_key=api_key_id or os.getenv("KALSHI_API_KEY_ID"),
            private_key_path=private_key_path or os.getenv("KALSHI_PRIVATE_KEY_PATH"),
            use_demo=use_demo or os.getenv("KALSHI_USE_DEMO", "true").lower() == "true",
        )
        # Use prime tier for higher rate limits if possible, default to basic
        self._client = KalshiVenueClient(config, rate_tier=os.getenv("KALSHI_RATE_TIER", "basic"))
        self.logger = logger.bind(venue="kalshi", paper=paper, demo=config.use_demo)

    async def connect(self) -> bool:
        """Connect via the resilient client."""
        try:
            await self._client.connect()
            # Verify connectivity with a balance check
            balance_res = await self._client.get_balance_result()
            if balance_res.success:
                self.connected = True
                self.logger.info("kalshi_adapter_connected", balance=balance_res.data)
                return True
            else:
                self.logger.error("kalshi_adapter_connect_failed", error=str(balance_res.error))
                return False
        except Exception as e:
            self.logger.error("kalshi_adapter_connect_exception", error=str(e))
            return False

    async def disconnect(self) -> bool:
        """Disconnect the client."""
        await self._client.close()
        self.connected = False
        return True

    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data via resilient client."""
        res = await self._client.get_market_result(symbol)
        if not res.success or not res.data:
            return None
        
        m = res.data
        # Best bid/ask from outcomes (Yes is typically what we trade)
        yes_outcome = next((o for o in m.outcomes if o.outcome_id == "yes"), None)
        if not yes_outcome:
            return None

        return MarketData(
            symbol=symbol,
            bid=yes_outcome.best_bid,
            ask=yes_outcome.best_ask,
            last=yes_outcome.price,
            volume_24h=m.volume,
            high_24h=yes_outcome.best_ask,
            low_24h=yes_outcome.best_bid,
            timestamp=datetime.now(timezone.utc),
            venue="kalshi",
        )

    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order via resilient client with Kalshi constraint validation."""
        # Get market data to validate constraints
        market_data = await self.get_market_data(symbol)
        
        # Validate order against Kalshi constraints before API call
        try:
            from merid.event_venues.kalshi.order_constraints import validate_kalshi_order
            from datetime import datetime, timezone
            
            # Convert price to cents (Kalshi uses cents for binary markets)
            price_cents = int(price * 100) if price is not None else 50  # Default to 50 cents
            
            # Get market status from market data if available
            market_status = "active"  # Default to active if we can't determine
            market_close_time = None
            current_position = 0
            
            if market_data:
                # Try to get market details from the catalog
                try:
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    catalog = get_market_catalog()
                    if catalog:
                        market = catalog.get_market(symbol)
                        if market:
                            market_status = market.status
                            market_close_time = market.close_time
                except Exception as catalog_err:
                    self.logger.warning("kalshi_adapter_catalog_fetch_failed", error=str(catalog_err))
            
            # Validate order
            allowed, reason = validate_kalshi_order(
                market_id=symbol,
                market_status=market_status,
                market_close_time=market_close_time,
                side="yes" if side == OrderSide.BUY else "no",
                price_cents=price_cents,
                quantity=int(amount),
                current_position=current_position,
                market_halted=False,
            )
            
            if not allowed:
                self.logger.warning(
                    "kalshi_adapter_order_rejected",
                    ticker=symbol,
                    reason=reason,
                    price_cents=price_cents,
                    quantity=int(amount),
                )
                return {
                    "status": "rejected",
                    "message": f"Order rejected by Kalshi constraints: {reason}",
                    "venue": "kalshi",
                }
                
        except ImportError:
            self.logger.warning("kalshi_adapter_constraints_not_available")
        except Exception as constraint_err:
            self.logger.error("kalshi_adapter_constraint_check_failed", error=str(constraint_err))
            # Fail-closed: reject order if constraint check fails
            return {
                "status": "error",
                "message": f"Order constraint validation failed: {constraint_err}",
                "venue": "kalshi",
            }
        
        # Convert merid.core side to Kalshi side (YES is usually the long side in our logic)
        # In prediction markets, side is often about the outcome.
        # Here we assume OrderSide.BUY targets 'yes' and OrderSide.SELL targets 'no' 
        # or we might need more granular control. For now, following existing logic.
        
        v_order = VenueOrder(
            market_id=symbol,
            side="buy", # Kalshi 'action' is always 'buy' or 'sell'
            size=amount,
            price=price,
            order_type=order_type.value.lower(),
            outcome_id="yes" if side == OrderSide.BUY else "no"
        )
        
        res = await self._client.place_order_result(v_order)
        if not res.success or not res.data:
            return {"status": "error", "message": str(res.error)}
        
        o = res.data
        return {
            "status": o.status,
            "order_id": o.order_id,
            "ticker": o.market_id,
            "side": o.side,
            "contracts": str(o.remaining_size),
            "venue": "kalshi",
        }

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order via resilient client."""
        res = await self._client.cancel_order_result(order_id, symbol)
        if res.success:
            return {"status": "cancelled", "order_id": order_id}
        return {"status": "error", "message": str(res.error)}

    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status via resilient client."""
        res = await self._client.get_order_result(order_id, symbol)
        if not res.success or not res.data:
            return None
        
        o = res.data
        return Order(
            id=o.order_id,
            symbol=o.market_id,
            side=OrderSide.BUY if o.side == "yes" else OrderSide.SELL,
            order_type=OrderType.LIMIT if o.price else OrderType.MARKET,
            amount=o.size,
            price=o.price,
            filled=o.filled_size,
            remaining=o.remaining_size,
            status=o.status,
            venue="kalshi",
            timestamp=o.created_at or datetime.now(timezone.utc),
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders via resilient client."""
        res = await self._client.get_open_orders_result(symbol)
        if not res.success:
            return []
        
        return [
            Order(
                id=o.order_id,
                symbol=o.market_id,
                side=OrderSide.BUY if o.side == "yes" else OrderSide.SELL,
                order_type=OrderType.LIMIT if o.price else OrderType.MARKET,
                amount=o.size,
                price=o.price,
                filled=o.filled_size,
                remaining=o.remaining_size,
                status=o.status,
                venue="kalshi",
                timestamp=o.created_at or datetime.now(timezone.utc),
            )
            for o in res.data
        ]

    async def get_positions(self) -> List[Position]:
        """Get positions via resilient client."""
        res = await self._client.get_positions_result()
        if not res.success:
            return []
        
        return [
            Position(
                symbol=p.market_id,
                side=p.outcome_id, # 'yes' or 'no'
                size=p.size,
                entry_price=p.average_entry_price,
                current_price=p.average_entry_price, # Placeholder
                unrealized_pnl=p.unrealized_pnl or Decimal("0"),
                venue="kalshi",
                timestamp=datetime.now(timezone.utc),
            )
            for p in res.data
        ]

    async def get_balance(self) -> Dict[str, Decimal]:
        """Get balance via resilient client."""
        res = await self._client.get_balance_result()
        if not res.success:
            return {}
        return res.data

    # Extra methods requested for "One unified adapter"
    async def list_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List markets for discovery."""
        from merid.event_venues.base import MarketFilter
        res = await self._client.list_markets_result(MarketFilter(limit=limit, active_only=True))
        if not res.success:
            return []
        return [m.__dict__ for m in res.data]

    async def get_orderbook(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get orderbook."""
        res = await self._client.get_orderbook_result(symbol)
        if not res.success or not res.data:
            return None
        return {
            "bids": [(float(p), float(q)) for p, q in res.data.bids],
            "asks": [(float(p), float(q)) for p, q in res.data.asks],
        }

    async def list_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List recent trades."""
        res = await self._client.get_trades_result(limit=limit)
        if not res.success:
            return []
        return [t.__dict__ for t in res.data]


# Singleton
kalshi_adapter = KalshiAdapter()
