"""Kalshi prediction market executor for MERID."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class KalshiExecutor(HTTPExecutor):
    """Kalshi prediction market executor with async HTTP support."""
    
    venue = "kalshi"
    base_url = os.getenv("KALSHI_API_URL", "https://api.elections.kalshi.com")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Kalshi authentication headers."""
        return {
            "KALSHI-API-KEY-ID": self.api_key_id or "",
        }

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get quote for prediction market contract."""
        ticker = self._symbol_to_ticker(symbol)
        response = await self._request(
            "GET",
            "/trade/v1/price",
            params={"ticker": ticker, "side": side, "count": str(int(amount))}
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
        """Execute trade on Kalshi prediction market."""
        ticker = self._symbol_to_ticker(symbol)
        payload = {
            "ticker": ticker,
            "side": side,
            "count": int(amount),
            "client_order_id": f"merid_{ticker}_{int(amount)}",
        }
        if order_type == "limit" and price is not None:
            payload["price"] = price

        try:
            response = await self._request(
                "POST",
                "/trade/v1/order",
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
                price=float(data.get("executed_price", price or 0)),
                tx_id=data.get("order_id"),
                metadata={"order_id": data.get("order_id")},
            )
        except (ConnectionError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Kalshi API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Kalshi."""
        response = await self._request(
            "GET",
            "/portfolio/v1/positions",
            headers=self._get_auth_headers(),
        )
        data = response.json()
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
        """Convert symbol to Kalshi ticker."""
        mapping = {
            "PRES-2024-DEM": "PRES-2024-DEM",
            "PRES-2024-REP": "PRES-2024-REP",
        }
        return mapping.get(symbol, symbol)

    def _ticker_to_symbol(self, ticker: str) -> str:
        """Convert Kalshi ticker to symbol."""
        mapping = {
            "PRES-2024-DEM": "PRES-2024-DEM",
            "PRES-2024-REP": "PRES-2024-REP",
        }
        return mapping.get(ticker, ticker)
