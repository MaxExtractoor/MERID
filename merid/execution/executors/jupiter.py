"""Jupiter (Solana DEX) executor for MERID."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.execution.http_base import HTTPExecutor


class JupiterExecutor(HTTPExecutor):
    """Jupiter DEX executor with async HTTP support."""
    
    venue = "jupiter"
    base_url = os.getenv("JUPITER_API_URL", "https://quote-api.jup.ag")
    default_timeout = 10.0
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.private_key = os.getenv("SOLANA_PRIVATE_KEY")
        self.public_key = os.getenv("SOLANA_PUBLIC_KEY")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Jupiter API doesn't require auth headers for quotes/swaps."""
        return {}

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get swap quote from Jupiter."""
        input_mint, output_mint = self._symbol_to_mints(symbol)
        if side == "sell":
            input_mint, output_mint = output_mint, input_mint
        
        response = await self._request(
            "GET",
            "/v6/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(int(amount * 1e6)),
                "slippageBps": "100",
            }
        )
        data = response.json()
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
        """Execute swap via Jupiter API."""
        input_mint, output_mint = self._symbol_to_mints(symbol)
        if side == "sell":
            input_mint, output_mint = output_mint, input_mint
        
        # Get quote first
        quote_resp = await self._request(
            "GET",
            "/v6/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(int(amount * 1e6)),
                "slippageBps": "100",
            }
        )
        quote_data = quote_resp.json()

        # Build swap transaction
        try:
            swap_resp = await self._request(
                "POST",
                "/v6/swap",
                json_data={
                    "quoteResponse": quote_data,
                    "userPublicKey": self.public_key,
                    "wrapAndUnwrapSol": True,
                },
                idempotent=True,
            )
            swap_data = swap_resp.json()
            
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
        except (ConnectionError, RuntimeError, ValueError) as e:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Jupiter API error: {e}",
            )

    async def get_positions(self) -> List[Position]:
        """Jupiter doesn't hold positions; query token accounts via Solana RPC."""
        # Simplified: return empty list for now
        return []

    def _symbol_to_mints(self, symbol: str) -> tuple[str, str]:
        """Convert symbol to Jupiter mint addresses."""
        mapping = {
            "SOL-USDC": ("So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            "BTC-USDC": ("9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            "ETH-USDC": ("7vfCXTUXx5WKF2Ad9cGBh34qLhXeZpj5ELCdMhJHw8wB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
        }
        return mapping.get(symbol, ("", ""))
