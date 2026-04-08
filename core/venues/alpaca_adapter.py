"""LEGACY (Alpaca/IBKR) — not used in production Kalshi.

MERID Alpaca Adapter - US Stocks, ETFs, and Crypto.

US-compliant trading via Alpaca Markets API (paper and live).
Uses the official alpaca-py SDK for all API calls.

This adapter is NOT imported by the Kalshi production pipeline.
It is retained for legacy equity trading support only.

Env vars:
    MERID_ALPACA_API_KEY  / ALPACA_API_KEY
    MERID_ALPACA_API_SECRET / ALPACA_API_SECRET
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import asyncio
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)

# Alpaca SDK imports (deferred to method bodies if unavailable)
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide as AlpacaSide, TimeInForce
    _HAS_ALPACA_SDK = True
except ImportError:
    _HAS_ALPACA_SDK = False


class AlpacaAdapter(VenueAdapter):
    """Alpaca adapter for US equities and crypto trading.

    Stage 0: real API for get_balance, get_positions, place_order (market).
    _is_stub remains True until integration test passes and manual smoke run.
    """
    _is_stub = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: bool = True
    ):
        super().__init__("alpaca", paper)
        self.api_key = (
            api_key
            or os.getenv("MERID_ALPACA_API_KEY")
            or os.getenv("ALPACA_API_KEY")
        )
        self.api_secret = (
            api_secret
            or os.getenv("MERID_ALPACA_API_SECRET")
            or os.getenv("ALPACA_API_SECRET")
        )
        self._trading_client: Optional["TradingClient"] = None
        self.logger = logger.bind(adapter="Alpaca", paper=paper)

    @property
    def _has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def connect(self) -> bool:
        """Connect to Alpaca API via the official SDK."""
        if not _HAS_ALPACA_SDK:
            self.logger.error("alpaca_sdk_not_installed")
            return False
        if not self._has_credentials:
            self.logger.warning("alpaca_no_credentials — running in stub mode")
            self.connected = False
            return False
        try:
            self._trading_client = TradingClient(
                api_key=self.api_key,
                secret_key=self.api_secret,
                paper=self.paper,
            )
            # Validate credentials with a lightweight account call
            acct = await asyncio.to_thread(self._trading_client.get_account)
            self.connected = True
            self.logger.info(
                "alpaca_connected",
                paper=self.paper,
                account_id=str(acct.id)[:8],
                equity=str(acct.equity),
            )
            return True
        except Exception as e:
            self.logger.error("alpaca_connect_error", error=str(e))
            self.connected = False
            return False

    async def disconnect(self) -> bool:
        """Disconnect from Alpaca."""
        self._trading_client = None
        self.connected = False
        self.logger.info("alpaca_disconnected")
        return True

    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data for symbol.

        Stage 0: not yet wired to Alpaca data API — returns None when
        no stub data is appropriate. Full implementation in a later stage.
        """
        return None

    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order on Alpaca via SDK."""
        if not self._trading_client:
            return {"status": "error", "message": "Not connected"}

        try:
            alpaca_side = AlpacaSide.BUY if side == OrderSide.BUY else AlpacaSide.SELL

            if order_type == OrderType.MARKET:
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=float(amount),
                    side=alpaca_side,
                    time_in_force=TimeInForce.GTC,
                )
            elif order_type == OrderType.LIMIT and price is not None:
                req = LimitOrderRequest(
                    symbol=symbol,
                    qty=float(amount),
                    side=alpaca_side,
                    time_in_force=TimeInForce.GTC,
                    limit_price=float(price),
                )
            else:
                return {"status": "error", "message": f"Unsupported order type: {order_type.value}"}

            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount),
            )

            result = await asyncio.to_thread(self._trading_client.submit_order, req)

            return {
                "status": str(result.status),
                "order_id": str(result.id),
                "symbol": result.symbol,
                "side": str(result.side),
                "filled_amount": str(result.filled_qty or 0),
                "filled_price": str(result.filled_avg_price or ""),
                "venue": "alpaca",
                "paper": self.paper,
            }
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order via SDK."""
        if not self._trading_client:
            return {"status": "error", "message": "Not connected"}
        try:
            await asyncio.to_thread(self._trading_client.cancel_order_by_id, order_id)
            return {"status": "cancelled", "order_id": order_id}
        except Exception as e:
            self.logger.error("cancel_error", error=str(e))
            return {"status": "error", "message": str(e)}

    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status via SDK."""
        if not self._trading_client:
            return None
        try:
            o = await asyncio.to_thread(self._trading_client.get_order_by_id, order_id)
            return Order(
                id=str(o.id),
                symbol=o.symbol,
                side=OrderSide.BUY if str(o.side) == "buy" else OrderSide.SELL,
                order_type=OrderType.MARKET if str(o.type) == "market" else OrderType.LIMIT,
                amount=Decimal(str(o.qty or 0)),
                price=Decimal(str(o.limit_price)) if o.limit_price else None,
                filled=Decimal(str(o.filled_qty or 0)),
                remaining=Decimal(str(o.qty or 0)) - Decimal(str(o.filled_qty or 0)),
                status=str(o.status),
                venue="alpaca",
                timestamp=o.created_at or datetime.now(),
            )
        except Exception as e:
            self.logger.error("order_status_error", error=str(e))
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders via SDK."""
        if not self._trading_client:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = await asyncio.to_thread(self._trading_client.get_orders, req)
            result = []
            for o in orders:
                if symbol and o.symbol != symbol:
                    continue
                result.append(Order(
                    id=str(o.id),
                    symbol=o.symbol,
                    side=OrderSide.BUY if str(o.side) == "buy" else OrderSide.SELL,
                    order_type=OrderType.MARKET if str(o.type) == "market" else OrderType.LIMIT,
                    amount=Decimal(str(o.qty or 0)),
                    price=Decimal(str(o.limit_price)) if o.limit_price else None,
                    filled=Decimal(str(o.filled_qty or 0)),
                    remaining=Decimal(str(o.qty or 0)) - Decimal(str(o.filled_qty or 0)),
                    status=str(o.status),
                    venue="alpaca",
                    timestamp=o.created_at or datetime.now(),
                ))
            return result
        except Exception as e:
            self.logger.error("open_orders_error", error=str(e))
            return []

    async def get_positions(self) -> List[Position]:
        """Get positions via SDK."""
        if not self._trading_client:
            return []
        try:
            positions = await asyncio.to_thread(self._trading_client.get_all_positions)
            result = []
            for p in positions:
                result.append(Position(
                    symbol=p.symbol,
                    side="long" if str(p.side) == "long" else "short",
                    size=Decimal(str(p.qty or 0)),
                    entry_price=Decimal(str(p.avg_entry_price or 0)),
                    current_price=Decimal(str(p.current_price or 0)),
                    unrealized_pnl=Decimal(str(p.unrealized_pl or 0)),
                    venue="alpaca",
                    timestamp=datetime.now(),
                ))
            return result
        except Exception as e:
            self.logger.error("positions_error", error=str(e))
            return []

    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance via SDK."""
        if not self._trading_client:
            return {}
        try:
            acct = await asyncio.to_thread(self._trading_client.get_account)
            return {
                "USD": Decimal(str(acct.cash or 0)),
                "EQUITY": Decimal(str(acct.equity or 0)),
                "BUYING_POWER": Decimal(str(acct.buying_power or 0)),
                "PORTFOLIO_VALUE": Decimal(str(acct.portfolio_value or 0)),
            }
        except Exception as e:
            self.logger.error("balance_error", error=str(e))
            return {}


# Singleton
alpaca_adapter = AlpacaAdapter()
