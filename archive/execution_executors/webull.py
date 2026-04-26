"""Webull executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class WebullExecutor(HTTPExecutor):
    """Webull API executor with async HTTP support."""
    
    venue = "webull"
    base_url = os.getenv("WEBULL_API_URL", "https://api.webull.com")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.username = os.getenv("WEBULL_USERNAME")
        self.password = os.getenv("WEBULL_PASSWORD")
        self.did = os.getenv("WEBULL_DID")
        self._access_token: Optional[str] = None

    async def _ensure_auth(self) -> None:
        """Ensure authentication token is available."""
        if self._access_token:
            return
        # Simplified: assume token already available via env in demo
        self._access_token = os.getenv("WEBULL_ACCESS_TOKEN")

    def _get_auth_headers(self) -> Dict[str, str]:
        """Webull authentication headers."""
        return {"Authorization": f"Bearer {self._access_token or ''}"}

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get latest quote for symbol."""
        await self._ensure_auth()
        response = await self._request(
            "GET",
            f"/quote/realTime/{symbol}",
            headers=self._get_auth_headers(),
        )
        data = response.json()
        price = float(data["latestPrice"])
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"timestamp": data.get("timestamp")},
        )

    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:
        """Execute trade via Webull API."""
        await self._ensure_auth()
        payload = {
            "securityId": symbol,
            "orderType": order_type.upper(),
            "orderAction": side.upper(),
            "totalQuantity": str(amount),
            "timeInForce": "DAY",
        }
        if order_type == "limit" and price is not None:
            payload["limitPrice"] = str(price)

        try:
            response = await self._request(
                "POST",
                "/trade/v2/order/place",
                json_data=payload,
                headers=self._get_auth_headers(),
                idempotent=True,
            )
            data = response.json()
            return TradeResult(
                success=True,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=float(data.get("avgPrice", price or 0)),
                tx_id=data.get("orderId"),
                metadata={"order_id": data.get("orderId")},
            )
        except (ConnectionError, RuntimeError, ValueError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Webull API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Webull."""
        await self._ensure_auth()
        response = await self._request(
            "GET",
            "/account/v5/positions",
            headers=self._get_auth_headers(),
        )
        data = response.json()
        positions = []
        for pos in data.get("positions", []):
            positions.append(
                Position(
                    symbol=pos["tickerSymbol"],
                    size=float(pos["position"]),
                    entry_price=float(pos.get("avgPrice", 0)),
                    pnl=float(pos.get("unrealizedPnl", 0)),
                    venue=self.venue,
                    metadata={"security_id": pos["securityId"]},
                )
            )
        return positions
