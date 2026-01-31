"""Webull executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class WebullExecutor(TradeExecutor):
    venue = "webull"

    def __init__(self) -> None:
        self.username = os.getenv("WEBULL_USERNAME")
        self.password = os.getenv("WEBULL_PASSWORD")
        self.did = os.getenv("WEBULL_DID")
        self.base_url = os.getenv("WEBULL_API_URL", "https://api.webull.com")
        self._client = httpx.Client(timeout=10.0)
        self._access_token: Optional[str] = None

    async def _ensure_auth(self) -> None:
        if self._access_token:
            return
        # Simplified: assume token already available via env in demo
        self._access_token = os.getenv("WEBULL_ACCESS_TOKEN")

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        await self._ensure_auth()
        resp = self._client.get(
            f"{self.base_url}/quote/realTime/{symbol}",
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
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

        resp = self._client.post(
            f"{self.base_url}/trade/v2/order/place",
            json=payload,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Webull API error {resp.status_code}: {resp.text}",
            )
        data = resp.json()
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

    async def get_positions(self) -> List[Position]:
        await self._ensure_auth()
        resp = self._client.get(
            f"{self.base_url}/account/v5/positions",
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
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
