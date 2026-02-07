"""Coinbase executor for MERID."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor, ExecutionError


class CoinbaseExecutor(HTTPExecutor):
    """Coinbase API executor with async HTTP support."""
    
    venue = "coinbase"
    base_url = os.getenv("COINBASE_API_URL", "https://api.coinbase.com")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Coinbase requires signature-based auth - not used in base headers."""
        return {}
    
    def _sign(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Generate Coinbase authentication headers."""
        timestamp = str(time.time())
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key or "",
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase or "",
        }

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get latest quote for symbol."""
        product_id = self._to_product_id(symbol)
        path = f"/v2/products/{product_id}/ticker"
        auth_headers = self._sign("GET", path)
        
        response = await self._request(
            "GET",
            path,
            headers=auth_headers,
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
            metadata={"product_id": product_id},
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
        """Execute trade via Coinbase API."""
        import json

        product_id = self._to_product_id(symbol)
        payload = {
            "product_id": product_id,
            "side": side,
            "size": str(amount),
            "type": order_type,
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)

        body = json.dumps(payload)
        path = "/v2/orders"
        auth_headers = self._sign("POST", path, body)

        try:
            response = await self._request(
                "POST",
                path,
                json_data=payload,
                headers=auth_headers,
                idempotent=True,
            )
            data = response.json()

            return TradeResult(
                success=True,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=float(data.get("executed_value", 0)) / amount,
                tx_id=data.get("id"),
                metadata={"order_id": data.get("id")},
            )
        except (ConnectionError, RuntimeError, ValueError, asyncio.TimeoutError, ExecutionError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Coinbase API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Coinbase."""
        path = "/v2/accounts"
        auth_headers = self._sign("GET", path)
        
        response = await self._request("GET", path, headers=auth_headers)
        accounts = response.json().get("data", [])
        
        positions = []
        for acct in accounts:
            if acct.get("type") != "wallet":
                continue
            bal = float(acct.get("available", {}).get("value", 0))
            if bal == 0:
                continue
            positions.append(
                Position(
                    symbol=acct["currency"] + "-USD",
                    size=bal,
                    entry_price=0.0,
                    pnl=0.0,
                    venue=self.venue,
                    metadata={"account_id": acct["id"]},
                )
            )
        return positions
    
    def _to_product_id(self, symbol: str) -> str:
        """Convert symbol to Coinbase product ID."""
        base, quote = symbol.split("-")
        if quote.upper() in {"USDT", "USD"}:
            return f"{base}-USD"
        return symbol
