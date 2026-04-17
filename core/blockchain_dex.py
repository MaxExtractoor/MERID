"""MERID Blockchain DEX Trading Module.

Multi-chain DEX integration for Ethereum, Cronos, and other EVM chains.
Supports Uniswap, PancakeSwap, and custom DEX contracts.
"""

from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from decimal import Decimal
import asyncio
import structlog
from web3 import Web3
from web3.contract import Contract
from web3.types import TxParams, Wei
from eth_account import Account
from eth_account.datastructures import SignedTransaction
import os

logger = structlog.get_logger(__name__)


@dataclass
class TokenPair:
    """Token pair for DEX trading."""
    base_token: str  # Contract address
    quote_token: str  # Contract address
    base_symbol: str
    quote_symbol: str
    decimals: int = 18
    
    def __post_init__(self):
        self.base_token = Web3.to_checksum_address(self.base_token)
        self.quote_token = Web3.to_checksum_address(self.quote_token)


@dataclass
class SwapQuote:
    """DEX swap quote."""
    input_amount: Decimal
    output_amount: Decimal
    price: Decimal
    price_impact: Decimal
    gas_estimate: int
    slippage: Decimal
    route: List[str]
    timestamp: float


@dataclass
class SwapResult:
    """DEX swap execution result."""
    tx_hash: str
    status: str  # pending, confirmed, failed
    gas_used: Optional[int]
    gas_price: Optional[Decimal]
    actual_output: Optional[Decimal]
    block_number: Optional[int]
    error: Optional[str] = None


class DEXManager:
    """Manager for DEX interactions across multiple chains."""
    
    # Uniswap V2/V3 Router ABIs (simplified)
    UNISWAP_V2_ROUTER_ABI = [
        {
            "name": "getAmountsOut",
            "type": "function",
            "inputs": [
                {"name": "amountIn", "type": "uint256"},
                {"name": "path", "type": "address[]"}
            ],
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view"
        },
        {
            "name": "swapExactTokensForTokens",
            "type": "function",
            "inputs": [
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}
            ],
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable"
        }
    ]
    
    ERC20_ABI = [
        {
            "name": "balanceOf",
            "type": "function",
            "inputs": [{"name": "account", "type": "address"}],
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view"
        },
        {
            "name": "approve",
            "type": "function",
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}
            ],
            "outputs": [{"name": "", "type": "bool"}],
            "stateMutability": "nonpayable"
        },
        {
            "name": "decimals",
            "type": "function",
            "inputs": [],
            "outputs": [{"name": "", "type": "uint8"}],
            "stateMutability": "view"
        }
    ]
    
    # Chain configurations
    CHAINS = {
        "ethereum": {
            "rpc_url": os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com"),
            "router": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",  # Uniswap V2
            "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "weth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        },
        "cronos": {
            "rpc_url": os.getenv("CRONOS_RPC_URL", "https://evm.cronos.org"),
            "router": "0xcd7d16fb918511bf7269ec4f48d61d79fb26f918",  # VVS Finance
            "factory": "0x3b44b2a1875437e979d5f93a5b5cc5c5d5273792",
            "weth": "0x5C7F8A570d578ED84E63fdFA7b1eE71dEae2A0A6"
        },
        "polygon": {
            "rpc_url": os.getenv("POLYGON_RPC_URL", "https://polygon.llamarpc.com"),
            "router": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",  # QuickSwap
            "factory": "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32",
            "weth": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
        }
    }
    
    def __init__(self, chain: str = "ethereum", private_key: Optional[str] = None):
        self.chain = chain
        self.config = self.CHAINS.get(chain, self.CHAINS["ethereum"])
        self.w3 = Web3(Web3.HTTPProvider(self.config["rpc_url"]))
        self.logger = logger.bind(chain=chain, component="DEXManager")
        
        self.account: Optional[Account] = None
        if private_key:
            self.account = Account.from_key(private_key)
            self.logger = self.logger.bind(account=self.account.address[:8])
        
        # Initialize router contract
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.config["router"]),
            abi=self.UNISWAP_V2_ROUTER_ABI
        )
        
        self.logger.info("dex_manager_initialized", router=self.config["router"][:20])
    
    def get_token_contract(self, token_address: str) -> Contract:
        """Get ERC20 token contract."""
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.ERC20_ABI
        )
    
    def get_token_balance(self, token_address: str, wallet_address: Optional[str] = None) -> Decimal:
        """Get token balance for wallet."""
        address = wallet_address or (self.account.address if self.account else None)
        if not address:
            raise ValueError("Wallet address required")
        
        token = self.get_token_contract(token_address)
        balance = token.functions.balanceOf(address).call()
        decimals = token.functions.decimals().call()
        
        return Decimal(balance) / (10 ** decimals)
    
    def get_eth_balance(self, wallet_address: Optional[str] = None) -> Decimal:
        """Get native token (ETH/CRO/MATIC) balance."""
        address = wallet_address or (self.account.address if self.account else None)
        if not address:
            raise ValueError("Wallet address required")
        
        balance_wei = self.w3.eth.get_balance(address)
        return Decimal(balance_wei) / Decimal(10**18)
    
    async def get_swap_quote(
        self,
        pair: TokenPair,
        amount_in: Decimal,
        slippage_tolerance: Decimal = Decimal("0.005")  # 0.5%
    ) -> SwapQuote:
        """Get swap quote from DEX."""
        
        self.logger.info(
            "getting_swap_quote",
            base=pair.base_symbol,
            quote=pair.quote_symbol,
            amount=str(amount_in)
        )
        
        # Calculate amounts
        amount_in_wei = int(amount_in * (10 ** pair.decimals))
        
        path = [pair.base_token, pair.quote_token]
        
        try:
            # Get amounts out
            amounts = self.router.functions.getAmountsOut(
                amount_in_wei,
                path
            ).call()
            
            output_amount = Decimal(amounts[-1]) / (10 ** pair.decimals)
            price = output_amount / amount_in
            
            # Calculate price impact (simplified)
            # In production, use pool reserves for accurate calculation
            price_impact = Decimal("0.001")  # Placeholder
            
            # Gas estimate
            gas_estimate = 150000  # Simplified estimate
            
            # Apply slippage to get minimum output
            min_output = int(amounts[-1] * (1 - float(slippage_tolerance)))
            
            quote = SwapQuote(
                input_amount=amount_in,
                output_amount=output_amount,
                price=price,
                price_impact=price_impact,
                gas_estimate=gas_estimate,
                slippage=slippage_tolerance,
                route=[pair.base_symbol, pair.quote_symbol],
                timestamp=asyncio.get_event_loop().time()
            )
            
            self.logger.info(
                "swap_quote_received",
                output=str(output_amount),
                price=str(price),
                gas_estimate=gas_estimate
            )
            
            return quote
            
        except Exception as e:
            self.logger.error("swap_quote_error", error=str(e))
            raise
    
    async def execute_swap(
        self,
        pair: TokenPair,
        amount_in: Decimal,
        min_amount_out: Optional[Decimal] = None,
        slippage: Decimal = Decimal("0.005"),
        deadline_minutes: int = 20
    ) -> SwapResult:
        """Execute token swap on DEX."""
        
        if not self.account:
            raise ValueError("Private key required for swap execution")
        
        self.logger.info(
            "executing_swap",
            base=pair.base_symbol,
            quote=pair.quote_symbol,
            amount=str(amount_in)
        )
        
        try:
            # Get quote first
            quote = await self.get_swap_quote(pair, amount_in, slippage)
            
            if min_amount_out is None:
                min_amount_out = quote.output_amount * (1 - slippage)
            
            # Approve token spending
            token_in = self.get_token_contract(pair.base_token)
            approve_tx = token_in.functions.approve(
                self.config["router"],
                int(amount_in * (10 ** pair.decimals))
            ).build_transaction({
                'from': self.account.address,
                'gas': 100000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address)
            })
            
            # Sign and send approve
            signed_approve = self.account.sign_transaction(approve_tx)
            approve_hash = self.w3.eth.send_raw_transaction(signed_approve.rawTransaction)
            
            # Wait for approval
            self.w3.eth.wait_for_transaction_receipt(approve_hash, timeout=60)
            
            # Build swap transaction
            amount_in_wei = int(amount_in * (10 ** pair.decimals))
            amount_out_min_wei = int(min_amount_out * (10 ** pair.decimals))
            deadline = int(asyncio.get_event_loop().time()) + (deadline_minutes * 60)
            
            swap_tx = self.router.functions.swapExactTokensForTokens(
                amount_in_wei,
                amount_out_min_wei,
                [pair.base_token, pair.quote_token],
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'gas': quote.gas_estimate,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address)
            })
            
            # Sign and send swap
            signed_swap = self.account.sign_transaction(swap_tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed_swap.rawTransaction)
            
            self.logger.info("swap_submitted", tx_hash=tx_hash.hex())
            
            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            result = SwapResult(
                tx_hash=tx_hash.hex(),
                status="confirmed" if receipt['status'] == 1 else "failed",
                gas_used=receipt['gasUsed'],
                gas_price=Decimal(self.w3.from_wei(receipt['effectiveGasPrice'], 'ether')),
                actual_output=None,  # Would parse from event logs
                block_number=receipt['blockNumber'],
                error=None if receipt['status'] == 1 else "Transaction failed"
            )
            
            self.logger.info(
                "swap_completed",
                status=result.status,
                gas_used=result.gas_used,
                block=result.block_number
            )
            
            return result
            
        except Exception as e:
            self.logger.error("swap_execution_error", error=str(e))
            return SwapResult(
                tx_hash="",
                status="failed",
                gas_used=None,
                gas_price=None,
                actual_output=None,
                block_number=None,
                error=str(e)
            )
    
    async def get_token_price_usd(self, token_address: str) -> Decimal:
        """Get token price in USD via DEX quote against USDC/USDT."""
        # Placeholder - would query against stablecoin pair
        # In production, use price oracle or CoinGecko API
        return Decimal("1.0")


class MultiChainDEXManager:
    """Manager for DEX operations across multiple chains."""
    
    def __init__(self, private_key: Optional[str] = None):
        self.managers: Dict[str, DEXManager] = {}
        self.private_key = private_key
        self.logger = logger.bind(component="MultiChainDEXManager")
    
    def get_manager(self, chain: str) -> DEXManager:
        """Get or create DEX manager for chain."""
        if chain not in self.managers:
            self.managers[chain] = DEXManager(chain, self.private_key)
        return self.managers[chain]
    
    async def compare_prices_across_chains(
        self,
        base_token: str,
        quote_token: str,
        chains: List[str] = None
    ) -> Dict[str, Decimal]:
        """Compare token prices across multiple chains."""
        chains = chains or ["ethereum", "cronos", "polygon"]
        prices = {}
        
        for chain in chains:
            try:
                manager = self.get_manager(chain)
                # Get price via quote
                # Simplified - would need proper token addresses per chain
                prices[chain] = await manager.get_token_price_usd(base_token)
            except Exception as e:
                self.logger.error("price_comparison_error", chain=chain, error=str(e))
                prices[chain] = None
        
        return prices
