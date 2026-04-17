"""Alpaca equities executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class AlpacaExecutor(HTTPExecutor):
    """Alpaca API executor with async HTTP support."""
    
    venue = "alpaca"
    base_url = os.getenv("ALPACA_API_URL", "https://paper-api.alpaca.markets")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.api_secret = os.getenv("ALPACA_API_SECRET")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Alpaca API authentication headers."""
        return {
            "APCA-API-KEY-ID": self.api_key or "",
            "APCA-API-SECRET-KEY": self.api_secret or "",
        }

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get latest quote for symbol."""
        response = await self._request(
            "GET",
            f"/v2/stocks/{symbol}/quotes/latest"
        )
        data = response.json()
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
        """Execute trade via Alpaca API."""
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "qty": str(amount),
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }
        if order_type == "limit" and price is not None:
            payload["limit_price"] = str(price)

        try:
            response = await self._request(
                "POST",
                "/v2/orders",
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
                price=float(data.get("filled_avg_price", price or 0)),
                tx_id=data.get("id"),
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
                error=f"Alpaca API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Alpaca."""
        response = await self._request("GET", "/v2/positions")
        data = response.json()
        
        positions = []
        for pos in data:
            positions.append(
                Position(
                    symbol=pos["symbol"],
                    size=float(pos["qty"]),
                    entry_price=float(pos["avg_entry_price"]),
                    pnl=float(pos.get("unrealized_pl", 0)),
                    venue=self.venue,
                    metadata={"asset_id": pos["asset_id"]},
                )
            )
        return positions
