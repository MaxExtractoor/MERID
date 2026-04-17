"""Coinbase price feed for MERID (spot BTC,ETH,SOL,XRP,DOGE vs USD only)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor, ExecutionError, NonRetryableError


class CoinbasePriceFeed(HTTPExecutor):
    """Coinbase price feed for MERID (spot BTC,ETH,SOL,XRP,DOGE vs USD only).

    This is a READ-ONLY price adapter. It does NOT support trading or positions.
    Use venue-specific executors (e.g., Kalshi) for trading operations.
    Intended for Kalshi crypto vs Coinbase spot pricing integration.
    """
    
    venue = "coinbase_price"
    base_url = os.getenv("COINBASE_API_URL", "https://api.coinbase.com")
    default_timeout = 5.0

    SUPPORTED_PRODUCTS = {
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "XRP-USD",
        "DOGE-USD",
    }

    def __init__(self, **kwargs) -> None:
        # no trading credentials required for price feed
        super().__init__(**kwargs)

    def _get_auth_headers(self) -> Dict[str, str]:
        """Public price endpoints; no auth required."""
        return {}

    def _to_product_id(self, symbol: str) -> str:
        """Convert symbol to Coinbase product ID."""
        symbol = symbol.upper()
        if symbol not in self.SUPPORTED_PRODUCTS:
            raise NonRetryableError(f"Unsupported Coinbase price symbol: {symbol}", self.venue)
        return symbol

    async def get_price(self, symbol: str) -> float:
        """Get current price for symbol from Coinbase public v2 spot endpoint.

        Uses ``/v2/prices/{pair}/spot`` (no auth required).
        Falls back to Exchange ticker if v2 fails.

        Args:
            symbol: Trading pair (e.g., "BTC-USD")

        Returns:
            Current price as float

        Raises:
            ExecutionError: If price fetch fails
            NonRetryableError: If symbol is not supported
        """
        product_id = self._to_product_id(symbol)

        # Attempt 1: Coinbase v2 public spot price (no auth)
        try:
            path = f"/v2/prices/{product_id}/spot"
            resp = await self._request("GET", path, headers=self._get_auth_headers())
            data = resp.json()
            amount = data.get("data", {}).get("amount")
            if amount is not None:
                return float(amount)
        except NonRetryableError:
            raise
        except Exception:
            pass  # fall through to Exchange ticker

        # Attempt 2: Coinbase Exchange public ticker
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.default_timeout) as client:
                resp = await client.get(
                    f"https://api.exchange.coinbase.com/products/{product_id}/ticker",
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                price_str = data.get("price")
                if price_str is not None:
                    return float(price_str)
        except NonRetryableError:
            raise
        except Exception as e:
            raise ExecutionError(f"Failed to fetch price for {symbol}: {e}", self.venue, cause=e)

        raise ExecutionError(f"No price returned for {product_id}", self.venue)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get latest quote for symbol.
        
        This is a convenience wrapper around get_price() to fit the Quote interface.
        Note: side and amount are accepted for interface compatibility but do not
        affect the price (this is a spot price feed, not an order book).
        """
        price = await self.get_price(symbol)
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"source": "coinbase_product_price"},
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
        """TRADING IS DISABLED - This is a read-only price feed.
        
        Raises:
            NonRetryableError: Always, to prevent accidental trading attempts
        """
        raise NonRetryableError(
            "CoinbasePriceFeed is read-only (prices only); trading is disabled. "
            "Use Kalshi or other venue-specific executors for trading.",
            self.venue,
        )

    async def get_positions(self) -> List[Position]:
        """POSITIONS ARE DISABLED - This is a read-only price feed.
        
        Raises:
            NonRetryableError: Always, to prevent position queries
        """
        raise NonRetryableError(
            "CoinbasePriceFeed does not expose positions; use Kalshi or venue-specific executors.",
            self.venue,
        )


# Backward compatibility alias
CoinbaseExecutor = CoinbasePriceFeed
