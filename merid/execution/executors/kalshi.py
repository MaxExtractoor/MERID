"""Kalshi prediction market executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class KalshiExecutor(TradeExecutor):
    venue = "kalshi"

    def __init__(self) -> None:
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
        self.base_url = os.getenv("KALSHI_API_URL", "https://api.elections.kalshi.com")
        self._client = httpx.Client(timeout=10.0)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        # Kalshi uses ticker IDs; map symbol to ticker (simplified)
        ticker = self._symbol_to_ticker(symbol)
        params = {"ticker": ticker, "side": side, "count": str(int(amount))}
        resp = self._client.get(f"{self.base_url}/trade/v1/price", params=params)
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
            metadata={"ticker": ticker},
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
        ticker = self._symbol_to_ticker(symbol)
        payload = {
            "ticker": ticker,
            "side": side,
            "count": int(amount),
            "client_order_id": f"merid_{ticker}_{int(amount)}",
        }
        if order_type == "limit" and price is not None:
            payload["price"] = price

        resp = self._client.post(f"{self.base_url}/trade/v1/order", json=payload)
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Kalshi API error {resp.status_code}: {resp.text}",
            )
        data = resp.json()
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=float(data.get("executed_price", price or 0)),
            tx_id=data.get("order_id"),
            metadata={"order_id": data.get("order_id")},
        )

    async def get_positions(self) -> List[Position]:
        resp = self._client.get(f"{self.base_url}/portfolio/v1/positions")
        resp.raise_for_status()
        data = resp.json()
        positions = []
        for pos in data.get("positions", []):
            positions.append(
                Position(
                    symbol=self._ticker_to_symbol(pos["ticker"]),
                    size=float(pos["count"]),
                    entry_price=float(pos.get("avg_price", 0)),
                    pnl=float(pos.get("pnl", 0)),
                    venue=self.venue,
                    metadata={"ticker": pos["ticker"]},
                )
            )
        return positions

    def _symbol_to_ticker(self, symbol: str) -> str:
        # Very naive mapping – in production use a registry
        mapping = {
            "PRES-2024-DEM": "PRES-2024-DEM",
            "PRES-2024-REP": "PRES-2024-REP",
        }
        return mapping.get(symbol, symbol)

    def _ticker_to_symbol(self, ticker: str) -> str:
        # Reverse mapping
        mapping = {
            "PRES-2024-DEM": "PRES-2024-DEM",
            "PRES-2024-REP": "PRES-2024-REP",
        }
        return mapping.get(ticker, ticker)
