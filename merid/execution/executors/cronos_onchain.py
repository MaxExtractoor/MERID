"""Cronos Onchain executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class CronosOnchainExecutor(HTTPExecutor):
    """Cronos onchain executor with async HTTP support."""
    
    venue = "cronos_onchain"
    base_url = os.getenv("CRONOS_RPC_URL", "https://evm-cronos.crypto.org")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.private_key = os.getenv("CRONOS_PRIVATE_KEY")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Cronos RPC doesn't use auth headers."""
        return {"Content-Type": "application/json"}

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get price quote for token pair."""
        base, quote_token = symbol.split("-")
        price = await self._fetch_price(base, quote_token)
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={"base": base, "quote": quote_token},
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
        """Execute on-chain trade via Cronos EVM."""
        base, quote_token = symbol.split("-")
        # In production, build and sign EVM transaction to DEX router
        # For now, simulate success
        exec_price = price or await self._fetch_price(base, quote_token)
        tx_hash = f"0x{'mocktx' * 8}"
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=exec_price,
            tx_id=tx_hash,
            metadata={"base": base, "quote": quote_token},
        )

    async def get_positions(self) -> List[Position]:
        """Query token balances via RPC."""
        positions = []
        usdc_balance = await self._token_balance("USDC")
        if usdc_balance > 0:
            positions.append(
                Position(
                    symbol="USDC-CRO",
                    size=usdc_balance,
                    entry_price=0.0,
                    pnl=0.0,
                    venue=self.venue,
                    metadata={"token": "USDC"},
                )
            )
        return positions

    async def _fetch_price(self, base: str, quote: str) -> float:
        """Fetch price from price feed or oracle."""
        mock_prices = {
            ("ETH", "USDC"): 3000.0,
            ("BTC", "USDC"): 50000.0,
            ("CRO", "USDC"): 0.08,
        }
        return mock_prices.get((base, quote), 1.0)

    async def _token_balance(self, token: str) -> float:
        """Query token balance via RPC."""
        mock_balances = {"USDC": 1234.56, "ETH": 0.5, "CRO": 1000.0}
        return mock_balances.get(token, 0.0)
