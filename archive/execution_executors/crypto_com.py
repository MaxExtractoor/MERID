"""Crypto.com Exchange executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class CryptoComExecutor(HTTPExecutor):
    """Crypto.com API executor with async HTTP support."""
    
    venue = "crypto_com"
    base_url = os.getenv("CRYPTO_COM_API_URL", "https://api.crypto.com")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = os.getenv("CRYPTO_COM_API_KEY")
        self.api_secret = os.getenv("CRYPTO_COM_API_SECRET")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Crypto.com authentication headers."""
        return {
            "API-Key": self.api_key or "",
            "API-Secret": self.api_secret or "",
        }

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get latest quote for symbol."""
        instrument = self._symbol_to_instrument(symbol)
        response = await self._request(
            "GET",
            "/v2/public/get-ticker",
            params={"instrument_name": instrument},
        )
        data = response.json()
        ticker = data["result"]
        price = float(ticker["b"]) if side == "buy" else float(ticker["k"])
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"instrument": instrument},
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
        """Execute trade via Crypto.com API."""
        instrument = self._symbol_to_instrument(symbol)
        payload = {
            "instrument_name": instrument,
            "side": side,
            "type": order_type,
            "quantity": str(amount),
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)

        try:
            response = await self._request(
                "POST",
                "/v2/private/create-order",
                json_data=payload,
                headers=self._get_auth_headers(),
                idempotent=True,
            )
            data = response.json()
            result = data["result"]
            return TradeResult(
                success=True,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=float(result.get("price", price or 0)),
                tx_id=result.get("order_id"),
                metadata={"order_id": result.get("order_id")},
            )
        except (ConnectionError, RuntimeError, ValueError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Crypto.com API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Crypto.com."""
        response = await self._request(
            "GET",
            "/v2/private/get-positions",
            headers=self._get_auth_headers(),
        )
        data = response.json()
        positions = []
        for pos in data.get("result", {}).get("list", []):
            positions.append(
                Position(
                    symbol=self._instrument_to_symbol(pos["instrument_name"]),
                    size=float(pos["size"]),
                    entry_price=float(pos.get("entry_price", 0)),
                    pnl=float(pos.get("unrealized_pnl", 0)),
                    venue=self.venue,
                    metadata={"instrument_name": pos["instrument_name"]},
                )
            )
        return positions

    def _symbol_to_instrument(self, symbol: str) -> str:
        """Convert symbol to Crypto.com instrument format."""
        return symbol.replace("-", "")

    def _instrument_to_symbol(self, instrument: str) -> str:
        """Convert instrument to symbol format."""
        if len(instrument) <= 4:
            return instrument
        base = instrument[:-4]
        quote = instrument[-4:]
        return f"{base}-{quote}"
