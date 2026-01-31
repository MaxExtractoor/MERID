"""Crypto.com Exchange executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class CryptoComExecutor(TradeExecutor):
    venue = "crypto_com"

    def __init__(self) -> None:
        self.api_key = os.getenv("CRYPTO_COM_API_KEY")
        self.api_secret = os.getenv("CRYPTO_COM_API_SECRET")
        self.base_url = os.getenv("CRYPTO_COM_API_URL", "https://api.crypto.com")
        self._client = httpx.Client(timeout=10.0)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        instrument = self._symbol_to_instrument(symbol)
        resp = self._client.get(f"{self.base_url}/v2/public/get-ticker", params={"instrument_name": instrument})
        resp.raise_for_status()
        data = resp.json()
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
        instrument = self._symbol_to_instrument(symbol)
        payload = {
            "instrument_name": instrument,
            "side": side,
            "type": order_type,
            "quantity": str(amount),
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)

        resp = self._client.post(
            f"{self.base_url}/v2/private/create-order",
            json=payload,
            headers=self._auth_headers(),
        )
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Crypto.com API error {resp.status_code}: {resp.text}",
            )
        data = resp.json()
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

    async def get_positions(self) -> List[Position]:
        resp = self._client.get(f"{self.base_url}/v2/private/get-positions", headers=self._auth_headers())
        resp.raise_for_status()
        data = resp.json()
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

    def _auth_headers(self) -> Dict[str, str]:
        # Simplified auth; real implementation requires signature
        return {
            "API-Key": self.api_key,
            "API-Secret": self.api_secret,
        }

    def _symbol_to_instrument(self, symbol: str) -> str:
        # Simple mapping: BTC-USDT -> BTC-USDT
        return symbol.replace("-", "")

    def _instrument_to_symbol(self, instrument: str) -> str:
        # Reverse mapping: BTCUSDT -> BTC-USDT
        # Naive: insert hyphen before last 4 chars (USDT)
        if len(instrument) <= 4:
            return instrument
        base = instrument[:-4]
        quote = instrument[-4:]
        return f"{base}-{quote}"
