"""Jupiter (Solana DEX) executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from merid.execution.base import Quote, Position, TradeExecutor, TradeResult, TradeSideLiteral


class JupiterExecutor(TradeExecutor):
    venue = "jupiter"

    def __init__(self) -> None:
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.jupiter_api = os.getenv("JUPITER_API_URL", "https://quote-api.jup.ag")
        self.private_key = os.getenv("SOLANA_PRIVATE_KEY")
        self.public_key = os.getenv("SOLANA_PUBLIC_KEY")
        self._client = httpx.Client(timeout=10.0)

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        input_mint, output_mint = self._symbol_to_mints(symbol)
        if side == "sell":
            input_mint, output_mint = output_mint, input_mint
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount * 1e6)),  # assume 6 decimals for USDC
            "slippageBps": "100",
        }
        resp = self._client.get(f"{self.jupiter_api}/v6/quote", params=params)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["outAmount"]) / float(data["inAmount"])
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=None,
            metadata={
                "input_mint": input_mint,
                "output_mint": output_mint,
                "quote_id": data.get("id"),
            },
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
        input_mint, output_mint = self._symbol_to_mints(symbol)
        if side == "sell":
            input_mint, output_mint = output_mint, input_mint
        quote_params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount * 1e6)),
            "slippageBps": "100",
        }
        quote_resp = self._client.get(f"{self.jupiter_api}/v6/quote", params=quote_params)
        quote_resp.raise_for_status()
        quote_data = quote_resp.json()

        # Build swap transaction
        swap_resp = self._client.post(
            f"{self.jupiter_api}/v6/swap",
            json={
                "quoteResponse": quote_data,
                "userPublicKey": self.public_key,
                "wrapAndUnwrapSol": True,
            },
        )
        swap_resp.raise_for_status()
        swap_data = swap_resp.json()
        # In a real implementation, you would sign and send the transaction via Solana SDK
        # Here we simulate success by returning the transaction ID
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=float(quote_data["outAmount"]) / float(quote_data["inAmount"]),
            tx_id=swap_data.get("txid"),
            metadata={
                "input_mint": input_mint,
                "output_mint": output_mint,
                "quote_id": quote_data.get("id"),
                "swap_transaction": swap_data.get("swapTransaction"),
            },
        )

    async def get_positions(self) -> List[Position]:
        # Jupiter doesn’t hold positions; query token accounts via Solana RPC
        # Simplified: return empty list for now
        return []

    def _symbol_to_mints(self, symbol: str) -> tuple[str, str]:
        # Very naive mapping – in production use a registry or on-chain lookup
        mapping = {
            "SOL-USDC": ("So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            "BTC-USDC": ("9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            "ETH-USDC": ("7vfCXTUXx5WKF2Ad9cGBh34qLhXeZpj5ELCdMhJHw8wB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
        }
        return mapping.get(symbol, ("", ""))
