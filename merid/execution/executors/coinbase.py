"""Coinbase executor for MERID."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class CoinbaseExecutor(TradeExecutor):
    venue = "coinbase"

    def __init__(self) -> None:
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_URL", "https://api.coinbase.com")
        self._client = httpx.Client(timeout=10.0)

    def _sign(self, method: str, path: str, body: str = "") -> tuple[str, str, str]:
        """Generate CB-ACCESS-SIGN, CB-ACCESS-TIMESTAMP, CB-ACCESS-PASSPHRASE headers."""
        timestamp = str(time.time())
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature, timestamp, self.passphrase

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        product_id = self._to_product_id(symbol)
        path = f"/v2/products/{product_id}/ticker"
        signature, timestamp, passphrase = self._sign("GET", path)
        resp = self._client.get(
            f"{self.base_url}{path}",
            headers={
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": passphrase,
            },
        )
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
        product_id = self._to_product_id(symbol)
        payload = {
            "product_id": product_id,
            "side": side,
            "size": str(amount),
            "type": order_type,
        }
        if order_type == "limit" and price is not None:
            payload["price"] = str(price)
        body = httpx._content_type_to_json(payload)
        path = "/v2/orders"
        signature, timestamp, passphrase = self._sign("POST", path, body)
        resp = self._client.post(
            f"{self.base_url}{path}",
            headers={
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            },
            content=body,
        )
        if resp.status_code not in {200, 201}:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Coinbase API error {resp.status_code}: {resp.text}",
            )
        data = resp.json()
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

    async def get_positions(self) -> List[Position]:
        path = "/v2/accounts"
        signature, timestamp, passphrase = self._sign("GET", path)
        resp = self._client.get(
            f"{self.base_url}{path}",
            headers={
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": passphrase,
            },
        )
        resp.raise_for_status()
        accounts = resp.json().get("data", [])
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
        base, quote = symbol.split("-")
        if quote.upper() in {"USDT", "USD"}:
            return f"{base}-USD"
        return symbol
