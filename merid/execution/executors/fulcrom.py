"""Fulcrom (Cronos DEX) executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class FulcromExecutor(HTTPExecutor):
    """Fulcrom DEX executor with async HTTP support."""
    
    venue = "fulcrom"
    base_url = os.getenv("FULCROM_API_URL", "https://api.fulcrom.finance")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.rpc_url = os.getenv("CRONOS_RPC_URL", "https://evm-cronos.crypto.org")
        self.private_key = os.getenv("CRONOS_PRIVATE_KEY")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Fulcrom API authentication headers."""
        return {}

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get quote for token swap."""
        base, quote_token = symbol.split("-")
        response = await self._request(
            "GET",
            "/v1/quote",
            params={
                "base": base,
                "quote": quote_token,
                "amount": str(amount),
                "type": side,
            }
        )
        data = response.json()
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
        """Execute trade via Fulcrom DEX."""
        base, quote_token = symbol.split("-")
        payload = {
            "base": base,
            "quote": quote_token,
            "amount": str(amount),
            "type": side,
            "order_type": order_type,
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)

        try:
            response = await self._request(
                "POST",
                "/v1/order",
                json_data=payload,
                idempotent=True,
            )
            data = response.json()
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
        except (ConnectionError, RuntimeError, ValueError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Fulcrom API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Fulcrom."""
        response = await self._request(
            "GET",
            "/v1/positions",
        )
        data = response.json()
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
