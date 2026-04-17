"""MERID Solana Blockchain Integration.

Supports Jupiter, Orca, and other Solana DEXs for high-speed trading.
Includes wallet management, transaction parsing, and price monitoring.
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from decimal import Decimal
import asyncio
import base64
import structlog

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.system_program import TransferParams, transfer
from solders.instruction import Instruction
import httpx

logger = structlog.get_logger(__name__)


@dataclass
class SolanaToken:
    """Solana token/SPL token info."""
    mint: str
    symbol: str
    name: str
    decimals: int
    logo_uri: Optional[str] = None
    
    def __post_init__(self):
        self.pubkey = Pubkey.from_string(self.mint)


@dataclass
class JupiterQuote:
    """Jupiter swap quote."""
    input_mint: str
    output_mint: str
    in_amount: Decimal
    out_amount: Decimal
    price_impact: Decimal
    slippage: Decimal
    route: List[Dict[str, Any]]
    fees: Decimal
    timestamp: float


@dataclass
class SolanaSwapResult:
    """Solana swap execution result."""
    signature: str
    status: str
    slot: Optional[int]
    fee_lamports: Optional[int]
    error: Optional[str] = None


class SolanaManager:
    """Manager for Solana blockchain operations."""
    
    # Solana token list
    KNOWN_TOKENS = {
        "SOL": SolanaToken(
            mint="So11111111111111111111111111111111111111112",
            symbol="SOL",
            name="Wrapped SOL",
            decimals=9
        ),
        "USDC": SolanaToken(
            mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            symbol="USDC",
            name="USD Coin",
            decimals=6
        ),
        "USDT": SolanaToken(
            mint="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            symbol="USDT",
            name="Tether USD",
            decimals=6
        ),
        "BONK": SolanaToken(
            mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            symbol="BONK",
            name="Bonk",
            decimals=5
        )
    }
    
    def __init__(
        self,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
        private_key: Optional[bytes] = None
    ):
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
        self.logger = logger.bind(chain="solana", component="SolanaManager")
        
        self.keypair: Optional[Keypair] = None
        if private_key:
            self.keypair = Keypair.from_bytes(private_key)
            self.logger = self.logger.bind(
                account=str(self.keypair.pubkey())[:8]
            )
        
        # Jupiter API endpoints
        self.jupiter_api = "https://quote-api.jup.ag/v6"
        
        self.logger.info("solana_manager_initialized", rpc=rpc_url[:30])
    
    async def get_balance(self, address: Optional[str] = None) -> Decimal:
        """Get SOL balance for address."""
        pubkey = Pubkey.from_string(address) if address else (
            self.keypair.pubkey() if self.keypair else None
        )
        
        if not pubkey:
            raise ValueError("Address or keypair required")
        
        try:
            response = await self.client.get_balance(pubkey)
            lamports = response.value
            sol = Decimal(lamports) / Decimal(10**9)
            
            return sol
            
        except Exception as e:
            self.logger.error("balance_fetch_error", error=str(e))
            raise
    
    async def get_token_balance(
        self,
        mint: str,
        address: Optional[str] = None
    ) -> Decimal:
        """Get SPL token balance."""
        owner = Pubkey.from_string(address) if address else (
            self.keypair.pubkey() if self.keypair else None
        )
        
        if not owner:
            raise ValueError("Address or keypair required")
        
        try:
            # Get token accounts by owner
            response = await self.client.get_token_accounts_by_owner(
                owner,
                {"mint": Pubkey.from_string(mint)}
            )
            
            if not response.value:
                return Decimal(0)
            
            # Parse balance from account data
            token_account = response.value[0]
            # Account data layout: mint(32) + owner(32) + amount(8) + ...
            data = base64.b64decode(token_account.account.data[0])
            amount = int.from_bytes(data[64:72], byteorder='little')
            
            # Get decimals for token
            token_info = self.KNOWN_TOKENS.get(mint)
            decimals = token_info.decimals if token_info else 6
            
            return Decimal(amount) / Decimal(10**decimals)
            
        except Exception as e:
            self.logger.error("token_balance_error", mint=mint, error=str(e))
            return Decimal(0)
    
    async def get_jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: Decimal,
        slippage: Decimal = Decimal("0.005")
    ) -> JupiterQuote:
        """Get swap quote from Jupiter."""
        
        self.logger.info(
            "getting_jupiter_quote",
            input_mint=input_mint[:8],
            output_mint=output_mint[:8],
            amount=str(amount)
        )
        
        # Get input token decimals
        input_token = self.KNOWN_TOKENS.get(input_mint)
        decimals = input_token.decimals if input_token else 6
        
        amount_lamports = int(amount * Decimal(10**decimals))
        
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_lamports),
            "slippageBps": int(slippage * 10000),
            "onlyDirectRoutes": "false",
            "asLegacyTransaction": "false"
        }
        
        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    f"{self.jupiter_api}/quote",
                    params=params
                )
                response.raise_for_status()
                data = response.json()
            
            # Get output token decimals
            output_token = self.KNOWN_TOKENS.get(output_mint)
            out_decimals = output_token.decimals if output_token else 6
            
            quote = JupiterQuote(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=Decimal(data["outAmount"]) / Decimal(10**out_decimals),
                price_impact=Decimal(data["priceImpactPct"]) / 100,
                slippage=slippage,
                route=data.get("routePlan", []),
                fees=Decimal(data.get("platformFee", {}).get("amount", "0")),
                timestamp=asyncio.get_event_loop().time()
            )
            
            self.logger.info(
                "jupiter_quote_received",
                out_amount=str(quote.out_amount),
                impact=str(quote.price_impact)
            )
            
            return quote
            
        except Exception as e:
            self.logger.error("jupiter_quote_error", error=str(e))
            raise
    
    async def execute_jupiter_swap(
        self,
        quote: JupiterQuote,
        destination_address: Optional[str] = None
    ) -> SolanaSwapResult:
        """Execute swap via Jupiter."""
        
        if not self.keypair:
            raise ValueError("Keypair required for swap execution")
        
        self.logger.info(
            "executing_jupiter_swap",
            input=quote.input_mint[:8],
            output=quote.output_mint[:8]
        )
        
        try:
            # Get swap transaction from Jupiter
            swap_request = {
                "quoteResponse": {
                    "inputMint": quote.input_mint,
                    "outputMint": quote.output_mint,
                    "inAmount": str(int(quote.in_amount * Decimal(10**9))),
                    "outAmount": str(int(quote.out_amount * Decimal(10**6))),
                    "slippageBps": int(quote.slippage * 10000)
                },
                "userPublicKey": str(self.keypair.pubkey()),
                "wrapAndUnwrapSol": True,
                "asLegacyTransaction": False
            }
            
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(
                    f"{self.jupiter_api}/swap",
                    json=swap_request
                )
                response.raise_for_status()
                swap_data = response.json()
            
            # Deserialize transaction
            tx_bytes = base64.b64decode(swap_data["swapTransaction"])
            transaction = Transaction.deserialize(tx_bytes)
            
            # Sign transaction
            transaction.sign(self.keypair)
            
            # Send transaction
            opts = TxOpts(skip_preflight=False, preflight_commitment="confirmed")
            result = await self.client.send_transaction(
                transaction,
                self.keypair,
                opts=opts
            )
            
            signature = result.value
            
            self.logger.info("jupiter_swap_sent", signature=signature[:20])
            
            # Wait for confirmation
            await self.client.confirm_transaction(signature)
            
            # Get transaction details
            tx_info = await self.client.get_transaction(signature)
            
            return SolanaSwapResult(
                signature=signature,
                status="confirmed",
                slot=tx_info.value.slot if tx_info.value else None,
                fee_lamports=tx_info.value.transaction.meta.fee if tx_info.value else None
            )
            
        except Exception as e:
            self.logger.error("jupiter_swap_error", error=str(e))
            return SolanaSwapResult(
                signature="",
                status="failed",
                slot=None,
                fee_lamports=None,
                error=str(e)
            )
    
    async def get_orca_pool_price(self, pool_address: str) -> Decimal:
        """Get price from Orca CLMM pool."""
        # Placeholder for Orca integration
        # Would fetch pool state and calculate current price
        return Decimal("1.0")
    
    async def transfer_sol(
        self,
        to_address: str,
        amount: Decimal
    ) -> str:
        """Transfer SOL to address."""
        
        if not self.keypair:
            raise ValueError("Keypair required for transfers")
        
        try:
            to_pubkey = Pubkey.from_string(to_address)
            lamports = int(amount * Decimal(10**9))
            
            # Create transfer instruction
            ix = transfer(
                TransferParams(
                    from_pubkey=self.keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            
            # Create and sign transaction
            transaction = Transaction()
            transaction.add(ix)
            
            # Get recent blockhash
            blockhash_response = await self.client.get_latest_blockhash()
            transaction.recent_blockhash = blockhash_response.value.blockhash
            
            transaction.sign(self.keypair)
            
            # Send
            result = await self.client.send_transaction(
                transaction,
                self.keypair
            )
            
            signature = result.value
            self.logger.info("sol_transfer_sent", signature=signature[:20])
            
            return signature
            
        except Exception as e:
            self.logger.error("sol_transfer_error", error=str(e))
            raise
    
    async def get_transaction_history(
        self,
        address: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent transaction history."""
        pubkey = Pubkey.from_string(address) if address else (
            self.keypair.pubkey() if self.keypair else None
        )
        
        if not pubkey:
            raise ValueError("Address or keypair required")
        
        try:
            response = await self.client.get_signatures_for_address(
                pubkey,
                limit=limit
            )
            
            transactions = []
            for sig_info in response.value:
                transactions.append({
                    "signature": sig_info.signature,
                    "slot": sig_info.slot,
                    "timestamp": sig_info.block_time,
                    "status": "success" if not sig_info.err else "failed"
                })
            
            return transactions
            
        except Exception as e:
            self.logger.error("tx_history_error", error=str(e))
            return []
    
    async def close(self):
        """Close client connection."""
        await self.client.close()


class SolanaMoralisIntegration:
    """Integration with Moralis for enhanced Solana data."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://solana-gateway.moralis.io"
        self.logger = logger.bind(component="SolanaMoralis")
    
    async def get_wallet_portfolio(self, address: str) -> Dict[str, Any]:
        """Get wallet portfolio via Moralis."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/account/mainnet/{address}/portfolio",
                    headers={"x-api-key": self.api_key}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.logger.error("moralis_portfolio_error", error=str(e))
            return {}
    
    async def get_token_price(self, token_address: str) -> Decimal:
        """Get token price via Moralis."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/token/mainnet/{token_address}/price",
                    headers={"x-api-key": self.api_key}
                )
                response.raise_for_status()
                data = response.json()
                return Decimal(str(data.get("usdPrice", 0)))
        except Exception as e:
            self.logger.error("moralis_price_error", error=str(e))
            return Decimal(0)
