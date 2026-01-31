"""Fulcrom (Cronos DEX) executor for MERID."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class FulcromExecutor(TradeExecutor):
    venue = "fulcrom"

    def __init__(self) -> None:
        self.rpc_url = os.getenv("CRONOS_RPC_URL", "https://evm-cronos.crypto.org")
        self.fulcrom_api = os.getenv("FULCROM_API_URL", "https://api.fulcrom.finance")
        self.private_key = os.getenv("CRONOS_PRIVATE_KEY")
        self._client = httpx.Client(timeout=10.0)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        base, quote = symbol.split("-")
        params = {
            "base": base,
            "quote": quote,
            "amount": str(amount),
            "type": side,
        }
        resp = self._client.get(f"{self.fulcrom_api}/v1/quote", params=params)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price"])
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"quote_id": data.get("id")},
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
        base, quote = symbol.split("-")
        payload = {
            "base": base,
            "quote": quote,
            "amount": str(amount),
            "type": side,
            "order_type": order_type,
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)

        resp = self._client.post(f"{self.fulcrom_api}/v1/order", json=payload)
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Fulcrom API error {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        # In a real implementation, you would sign and send the transaction via Cronos EVM SDK
        # Here we simulate success by returning the transaction hash
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=float(data.get("executed_price", price or 0)),
            tx_id=data.get("tx_hash"),
            metadata={"order_id": data.get("id")},
        )

    async def get_positions(self) -> List[Position]:
        # Query Fulcrom positions via API (simplified)
        resp = self._client.get(f"{self.fulcrom_api}/v1/positions")
        resp.raise_for_status()
        data = resp.json()
        positions = []
        for pos in data.get("positions", []):
            positions.append(
                Position(
                    symbol=f"{pos['base']}-{pos['quote']}",
                    size=float(pos["size"]),
                    entry_price=float(pos["entry_price"]),
                    pnl=float(pos["pnl"]),
                    venue=self.venue,
                    metadata={"position_id": pos["id"]},
                )
            )
        return positions
