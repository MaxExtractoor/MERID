"""MERID Coinbase Advanced Trade Adapter - US Crypto Trading.

US-compliant crypto trading via Coinbase Advanced Trade REST API.
Uses CDP API key HMAC-SHA256 signing (Cloud API Trading keys).

Env vars:
    MERID_COINBASE_API_KEY    / COINBASE_CLIENT_API_KEY / COINBASE_API_KEY
    MERID_COINBASE_API_SECRET / COINBASE_CLIENT_API_SECRET / COINBASE_API_SECRET
"""

from merid.coinbase_env import coinbase_api_key as _cb_key
from merid.coinbase_env import coinbase_api_secret as _cb_secret

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import hmac
import time
import uuid
import structlog

import httpx

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.coinbase.com"


def _sign_request(
    api_secret: str,
    timestamp: str,
    method: str,
    path: str,
    body: str = "",
) -> str:
    """Generate CB-ACCESS-SIGN HMAC-SHA256 signature."""
    message = f"{timestamp}{method.upper()}{path}{body}"
    return hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class CoinbaseAdvancedAdapter(VenueAdapter):
    """Coinbase Advanced Trade adapter for US crypto trading.

    Stage 0: real API for get_balance (accounts), get_positions (via accounts),
    place_order (market), get_market_data (product ticker).
    _is_stub remains True until integration test passes.
    """
    _is_stub = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        super().__init__("coinbase_advanced", paper=False)
        self.api_key = api_key or _cb_key()
        self.api_secret = api_secret or _cb_secret()
        self._http: Optional[httpx.AsyncClient] = None
        self.logger = logger.bind(adapter="CoinbaseAdvanced")

    @property
    def _has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _auth_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Build Coinbase Advanced Trade auth headers."""
        ts = str(int(time.time()))
        sig = _sign_request(self.api_secret, ts, method, path, body)
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    async def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade API."""
        if not self._has_credentials:
            self.logger.warning("coinbase_no_credentials — running in stub mode")
            return False
        try:
            from utils.http_client import get_shared_ssl_context
            self._http = httpx.AsyncClient(base_url=_BASE_URL, timeout=15.0, verify=get_shared_ssl_context())
            path = "/api/v3/brokerage/accounts"
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
            )
            resp.raise_for_status()
            accounts = resp.json().get("accounts", [])
            self.connected = True
            self.logger.info(
                "coinbase_connected",
                accounts=len(accounts),
            )
            return True
        except Exception as e:
            self.logger.error("coinbase_connect_error", error=str(e))
            self.connected = False
            return False

    async def disconnect(self) -> bool:
        """Disconnect from Coinbase."""
        if self._http:
            await self._http.aclose()
            self._http = None
        self.connected = False
        self.logger.info("coinbase_disconnected")
        return True

    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get crypto market data from Coinbase product ticker."""
        if not self._http:
            return None
        try:
            path = f"/api/v3/brokerage/products/{symbol}"
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
            )
            resp.raise_for_status()
            p = resp.json()
            return MarketData(
                symbol=symbol,
                bid=Decimal(str(p.get("quote_min_size", "0"))),
                ask=Decimal(str(p.get("quote_max_size", "0"))),
                last=Decimal(str(p.get("price", "0"))),
                volume_24h=Decimal(str(p.get("volume_24h", "0"))),
                high_24h=Decimal(str(p.get("price", "0"))),
                low_24h=Decimal(str(p.get("price", "0"))),
                timestamp=datetime.now(timezone.utc),
                venue="coinbase_advanced",
            )
        except Exception as e:
            self.logger.error("market_data_error", error=str(e))
            return None

    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Place crypto order on Coinbase Advanced Trade.

        Args:
            symbol: Product ID (e.g. "BTC-USD").
            side: BUY or SELL.
            amount: Base currency amount for market buy, or quote size.
            price: Limit price (only for limit orders).
        """
        if not self._http:
            return {"status": "error", "message": "Not connected"}

        try:
            client_order_id = str(uuid.uuid4())
            cb_side = "BUY" if side == OrderSide.BUY else "SELL"

            order_config: Dict[str, Any] = {}
            if order_type == OrderType.MARKET:
                if side == OrderSide.BUY:
                    order_config["market_market_ioc"] = {"quote_size": str(amount)}
                else:
                    order_config["market_market_ioc"] = {"base_size": str(amount)}
            elif order_type == OrderType.LIMIT and price is not None:
                order_config["limit_limit_gtc"] = {
                    "base_size": str(amount),
                    "limit_price": str(price),
                }
            else:
                return {"status": "error", "message": f"Unsupported order type: {order_type.value}"}

            body_dict = {
                "client_order_id": client_order_id,
                "product_id": symbol,
                "side": cb_side,
                "order_configuration": order_config,
            }

            import json
            body_str = json.dumps(body_dict)
            path = "/api/v3/brokerage/orders"

            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount),
            )

            resp = await self._http.post(
                path,
                headers=self._auth_headers("POST", path, body_str),
                content=body_str,
            )
            resp.raise_for_status()
            data = resp.json()

            success_resp = data.get("success_response", {})
            error_resp = data.get("error_response", {})

            if data.get("success"):
                return {
                    "status": "accepted",
                    "order_id": success_resp.get("order_id", ""),
                    "symbol": symbol,
                    "side": side.value,
                    "venue": "coinbase_advanced",
                }
            else:
                return {
                    "status": "error",
                    "message": error_resp.get("message", "Unknown error"),
                    "error": error_resp.get("error", ""),
                }
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order via Coinbase Advanced Trade API."""
        if not self._http:
            return {"status": "error", "message": "Not connected"}
        try:
            import json
            path = "/api/v3/brokerage/orders/batch_cancel"
            body_dict = {"order_ids": [order_id]}
            body_str = json.dumps(body_dict)
            resp = await self._http.post(
                path,
                headers=self._auth_headers("POST", path, body_str),
                content=body_str,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results and results[0].get("success"):
                return {"status": "cancelled", "order_id": order_id}
            return {"status": "error", "message": "Cancel failed", "detail": results}
        except Exception as e:
            self.logger.error("cancel_error", error=str(e))
            return {"status": "error", "message": str(e)}

    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status via Coinbase Advanced Trade API."""
        if not self._http:
            return None
        try:
            path = f"/api/v3/brokerage/orders/historical/{order_id}"
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
            )
            resp.raise_for_status()
            o = resp.json().get("order", {})
            total = Decimal(str(o.get("order_configuration", {}).get("limit_limit_gtc", {}).get("base_size", "0") or "0"))
            filled = Decimal(str(o.get("filled_size", "0")))
            return Order(
                id=o.get("order_id", order_id),
                symbol=o.get("product_id", symbol),
                side=OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL,
                order_type=OrderType.MARKET if "market" in str(o.get("order_type", "")) else OrderType.LIMIT,
                amount=total,
                price=None,
                filled=filled,
                remaining=max(total - filled, Decimal("0")),
                status=o.get("status", "unknown"),
                venue="coinbase_advanced",
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            self.logger.error("order_status_error", error=str(e))
            return None

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders via Coinbase Advanced Trade API."""
        if not self._http:
            return []
        try:
            path = "/api/v3/brokerage/orders/historical/batch"
            params: Dict[str, str] = {"order_status": "OPEN"}
            if symbol:
                params["product_id"] = symbol
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
                params=params,
            )
            resp.raise_for_status()
            orders = resp.json().get("orders", [])
            return [
                Order(
                    id=o.get("order_id", ""),
                    symbol=o.get("product_id", ""),
                    side=OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL,
                    order_type=OrderType.MARKET if "market" in str(o.get("order_type", "")) else OrderType.LIMIT,
                    amount=Decimal(str(o.get("filled_size", "0"))),
                    price=None,
                    filled=Decimal(str(o.get("filled_size", "0"))),
                    remaining=Decimal("0"),
                    status=o.get("status", "OPEN"),
                    venue="coinbase_advanced",
                    timestamp=datetime.now(timezone.utc),
                )
                for o in orders
            ]
        except Exception as e:
            self.logger.error("open_orders_error", error=str(e))
            return []

    async def get_positions(self) -> List[Position]:
        """Get crypto positions derived from non-zero account balances."""
        if not self._http:
            return []
        try:
            path = "/api/v3/brokerage/accounts"
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
            )
            resp.raise_for_status()
            accounts = resp.json().get("accounts", [])
            result = []
            for acct in accounts:
                bal = Decimal(str(acct.get("available_balance", {}).get("value", "0")))
                currency = acct.get("available_balance", {}).get("currency", "")
                if bal > 0 and currency not in ("USD", "USDC", "USDT"):
                    result.append(Position(
                        symbol=currency,
                        side="long",
                        size=bal,
                        entry_price=Decimal("0"),
                        current_price=Decimal("0"),
                        unrealized_pnl=Decimal("0"),
                        venue="coinbase_advanced",
                        timestamp=datetime.now(timezone.utc),
                    ))
            return result
        except Exception as e:
            self.logger.error("positions_error", error=str(e))
            return []

    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balances from Coinbase accounts endpoint."""
        if not self._http:
            return {}
        try:
            path = "/api/v3/brokerage/accounts"
            resp = await self._http.get(
                path,
                headers=self._auth_headers("GET", path),
            )
            resp.raise_for_status()
            accounts = resp.json().get("accounts", [])
            result: Dict[str, Decimal] = {}
            for acct in accounts:
                currency = acct.get("available_balance", {}).get("currency", "")
                value = Decimal(str(acct.get("available_balance", {}).get("value", "0")))
                if value > 0:
                    result[currency] = value
            return result
        except Exception as e:
            self.logger.error("balance_error", error=str(e))
            return {}


# Singleton
coinbase_advanced_adapter = CoinbaseAdvancedAdapter()
