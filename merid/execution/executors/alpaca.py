"""Alpaca equities executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class AlpacaExecutor(TradeExecutor):
    venue = "alpaca"

    def __init__(self) -> None:
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.api_secret = os.getenv("ALPACA_API_SECRET")
        self.base_url = os.getenv("ALPACA_API_URL", "https://paper-api.alpaca.markets")
        self._client = httpx.Client(timeout=10.0)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        resp = self._client.get(
            f"{self.base_url}/v2/stocks/{symbol}/quotes/latest",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        quote = data["quote"]
        price = float(quote["ap"]) if side == "buy" else float(quote["bp"])
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"ask": quote["ap"], "bid": quote["bp"]},
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
        payload = {
            "symbol": symbol,
            "qty": str(amount),
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }
        if order_type == "limit" and price is not None:
            payload["limit_price"] = str(price)

        resp = self._client.post(f"{self.base_url}/v2/orders", json=payload, headers=self._headers())
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Alpaca API error {resp.status_code}: {resp.text}",
            )
        data = resp.json()
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=float(data.get("filled_avg_price", price or 0)),
            tx_id=data.get("id"),
            metadata={"order_id": data.get("id")},
        )

    async def get_positions(self) -> List[Position]:
        resp = self._client.get(f"{self.base_url}/v2/positions", headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        positions = []
        for pos in data:
            positions.append(
                Position(
                    symbol=pos["symbol"],
                    size=float(pos["qty"]),
                    entry_price=float(pos["avg_entry_price"]),
                    pnl=float(pos["unrealized_plpc"]) / 10000.0,  # convert basis points
                    venue=self.venue,
                    metadata={"asset_id": pos["asset_id"]},
                )
            )
        return positions

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
