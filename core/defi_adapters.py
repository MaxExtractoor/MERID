"""
DeFi Protocol Adapters for MERID
Swap, LP, lending/borrowing, staking, and routing protocols.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.multichain_wallet import ChainNetwork, get_multichain_wallet
from core.network_client import NetworkClient, get_network_client
from core.environment_flags import EnvironmentFlags, get_environment_flags
from utils.logger import get_logger

logger = get_logger("core.defi_adapters")


class ProtocolType(Enum):
    """DeFi protocol types."""
    SWAP = "swap"
    LP = "liquidity_provision"
    LENDING = "lending"
    BORROWING = "borrowing"
    STAKING = "staking"
    YIELD_FARMING = "yield_farming"


class SwapProtocol(Enum):
    """Supported swap protocols."""
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    CURVE = "curve"
    BALANCER = "balancer"
    SUSHISWAP = "sushiswap"
    PANCAKESWAP = "pancakeswap"


@dataclass
class SwapQuote:
    """Quote for a token swap."""
    protocol: SwapProtocol
    chain: ChainNetwork
    token_in: str
    token_out: str
    amount_in: float
    amount_out: float
    price_impact: float
    gas_estimate: int
    route: List[str]
    timestamp: float


@dataclass
class LiquidityPosition:
    """Liquidity provision position."""
    protocol: SwapProtocol
    chain: ChainNetwork
    pool_address: str
    token_a: str
    token_b: str
    amount_a: float
    amount_b: float
    share: float
    fees_earned: float
    timestamp: float


@dataclass
class LendingPosition:
    """Lending/borrowing position."""
    protocol: str
    chain: ChainNetwork
    asset: str
    supplied: float
    borrowed: float
    collateral_factor: float
    apy_supply: float
    apy_borrow: float
    health_factor: float
    timestamp: float


class DeFiAdapter(ABC):
    """Base class for DeFi protocol adapters."""
    
    def __init__(self, chain: ChainNetwork):
        self.chain = chain
        self.wallet = get_multichain_wallet()
        self._network_client = get_network_client()
        self._env_flags = get_environment_flags()
        
        # Register module profile with network client
        self._network_client.register_module_profile(
            module_name=f"defi_adapter_{chain.value}",
            required_endpoints=["rpc", "api"],
            fallback_behavior="block",
        )
    
    def _check_network_access(self, operation: str) -> bool:
        """Check if network access is allowed for operation."""
        if self._env_flags.offline_mode:
            logger.warning(
                "DeFi %s blocked: offline mode enabled for %s",
                operation,
                self.chain.value,
            )
            return False
        
        if not self._network_client.can_call_outbound(f"defi_adapter_{self.chain.value}"):
            logger.warning(
                "DeFi %s blocked: network client denied for %s",
                operation,
                self.chain.value,
            )
            return False
        
        return True
    
    @abstractmethod
    def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Optional[SwapQuote]:
        """Get swap quote."""
        pass
    
    @abstractmethod
    def execute_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        min_amount_out: float,
        slippage_tolerance: float
    ) -> Optional[str]:
        """Execute swap and return tx hash."""
        pass


class UniswapV3Adapter(DeFiAdapter):
    """Adapter for Uniswap V3."""
    
    def __init__(self, chain: ChainNetwork):
        super().__init__(chain)
        self.router_address = self._get_router_address()
    
    def _get_router_address(self) -> str:
        """Get router address for chain."""
        routers = {
            ChainNetwork.ETHEREUM: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
            ChainNetwork.ARBITRUM: "0xE592427A0AEce92De3Edee1F18E0157C05861564",
            ChainNetwork.BASE: "0x2626664c2603336E57B271c5C0b26F421741e481",
            ChainNetwork.POLYGON: "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        }
        return routers.get(self.chain, "")
    
    def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Optional[SwapQuote]:
        """Get Uniswap V3 quote."""
        if not self._check_network_access("get_quote"):
            return None
        
        # In production, call quoter contract
        amount_out = amount_in * 0.998  # Simulate 0.2% slippage
        price_impact = 0.002
        
        return SwapQuote(
            protocol=SwapProtocol.UNISWAP_V3,
            chain=self.chain,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=amount_out,
            price_impact=price_impact,
            gas_estimate=150000,
            route=[token_in, token_out],
            timestamp=time.time()
        )
    
    def execute_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        min_amount_out: float,
        slippage_tolerance: float
    ) -> Optional[str]:
        """Execute Uniswap V3 swap."""
        if not self._check_network_access("execute_swap"):
            return None
        
        # In production:
        # 1. Approve token_in for router
        # 2. Build swap transaction
        # 3. Send transaction
        
        logger.info(
            f"Executing Uniswap V3 swap on {self.chain.value}: "
            f"{amount_in} {token_in} -> {token_out} (min: {min_amount_out})"
        )
        
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=self.router_address,
            value=0.0,
            data="0x"  # Encoded swap data
        )
        
        return tx_hash
    
    def add_liquidity(
        self,
        token_a: str,
        token_b: str,
        amount_a: float,
        amount_b: float,
        fee_tier: int = 3000
    ) -> Optional[str]:
        """Add liquidity to Uniswap V3 pool."""
        if not self._check_network_access("add_liquidity"):
            return None
        
        logger.info(
            f"Adding liquidity to Uniswap V3 on {self.chain.value}: "
            f"{amount_a} {token_a} + {amount_b} {token_b} (fee: {fee_tier})"
        )
        
        # In production, call position manager contract
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=self.router_address,
            value=0.0,
            data="0x"
        )
        
        return tx_hash


class CurveAdapter(DeFiAdapter):
    """Adapter for Curve Finance."""
    
    def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Optional[SwapQuote]:
        """Get Curve quote."""
        if not self._check_network_access("get_quote"):
            return None
        
        # Curve specializes in stablecoin swaps with low slippage
        amount_out = amount_in * 0.9995  # 0.05% slippage
        price_impact = 0.0005
        
        return SwapQuote(
            protocol=SwapProtocol.CURVE,
            chain=self.chain,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=amount_out,
            price_impact=price_impact,
            gas_estimate=200000,
            route=[token_in, token_out],
            timestamp=time.time()
        )
    
    def execute_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        min_amount_out: float,
        slippage_tolerance: float
    ) -> Optional[str]:
        """Execute Curve swap."""
        if not self._check_network_access("execute_swap"):
            return None
        
        logger.info(
            f"Executing Curve swap on {self.chain.value}: "
            f"{amount_in} {token_in} -> {token_out}"
        )
        
        return "0x" + "0" * 64


class AaveAdapter:
    """Adapter for Aave lending protocol."""
    
    def __init__(self, chain: ChainNetwork):
        self.chain = chain
        self.wallet = get_multichain_wallet()
        self._network_client = get_network_client()
        self._env_flags = get_environment_flags()
        self.pool_address = self._get_pool_address()
        
        # Register module profile with network client
        self._network_client.register_module_profile(
            module_name=f"aave_adapter_{chain.value}",
            required_endpoints=["rpc", "api"],
            fallback_behavior="block",
        )
    
    def _check_network_access(self, operation: str) -> bool:
        """Check if network access is allowed for operation."""
        if self._env_flags.offline_mode:
            logger.warning(
                "Aave %s blocked: offline mode enabled for %s",
                operation,
                self.chain.value,
            )
            return False
        
        if not self._network_client.can_call_outbound(f"aave_adapter_{self.chain.value}"):
            logger.warning(
                "Aave %s blocked: network client denied for %s",
                operation,
                self.chain.value,
            )
            return False
        
        return True
    
    def _get_pool_address(self) -> str:
        """Get Aave pool address for chain."""
        pools = {
            ChainNetwork.ETHEREUM: "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
            ChainNetwork.ARBITRUM: "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
            ChainNetwork.POLYGON: "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
        }
        return pools.get(self.chain, "")
    
    def supply(self, asset: str, amount: float) -> Optional[str]:
        """Supply asset to Aave."""
        if not self._check_network_access("supply"):
            return None
        
        logger.info(f"Supplying {amount} {asset} to Aave on {self.chain.value}")
        
        # In production:
        # 1. Approve asset for pool
        # 2. Call supply function
        
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=self.pool_address,
            value=0.0,
            data="0x"
        )
        
        return tx_hash
    
    def borrow(self, asset: str, amount: float) -> Optional[str]:
        """Borrow asset from Aave."""
        if not self._check_network_access("borrow"):
            return None
        
        logger.info(f"Borrowing {amount} {asset} from Aave on {self.chain.value}")
        
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=self.pool_address,
            value=0.0,
            data="0x"
        )
        
        return tx_hash
    
    def get_position(self, address: str) -> Optional[LendingPosition]:
        """Get lending position."""
        if not self._check_network_access("get_position"):
            return None
        
        # In production, query Aave contracts
        return LendingPosition(
            protocol="aave",
            chain=self.chain,
            asset="USDC",
            supplied=1000.0,
            borrowed=500.0,
            collateral_factor=0.8,
            apy_supply=0.03,
            apy_borrow=0.05,
            health_factor=1.5,
            timestamp=time.time()
        )


class DeFiRouter:
    """Routes DeFi operations to best protocol."""
    
    def __init__(self):
        self._swap_adapters: Dict[ChainNetwork, List[DeFiAdapter]] = {}
        self._initialize_adapters()
    
    def _initialize_adapters(self) -> None:
        """Initialize protocol adapters."""
        chains = [
            ChainNetwork.ETHEREUM,
            ChainNetwork.ARBITRUM,
            ChainNetwork.BASE,
            ChainNetwork.POLYGON
        ]
        
        for chain in chains:
            self._swap_adapters[chain] = [
                UniswapV3Adapter(chain),
                CurveAdapter(chain)
            ]
    
    def get_best_quote(
        self,
        chain: ChainNetwork,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Optional[SwapQuote]:
        """Get best quote across all protocols."""
        adapters = self._swap_adapters.get(chain, [])
        
        quotes = []
        for adapter in adapters:
            try:
                quote = adapter.get_quote(token_in, token_out, amount_in)
                if quote:
                    quotes.append(quote)
            except Exception as exc:
                logger.error(f"Failed to get quote from {adapter.__class__.__name__}: {exc}")
        
        if not quotes:
            return None
        
        # Return quote with best output amount
        return max(quotes, key=lambda q: q.amount_out)
    
    def execute_best_swap(
        self,
        chain: ChainNetwork,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_tolerance: float = 0.005
    ) -> Optional[str]:
        """Execute swap on best protocol."""
        quote = self.get_best_quote(chain, token_in, token_out, amount_in)
        
        if not quote:
            logger.error("No quote available for swap")
            return None
        
        min_amount_out = quote.amount_out * (1 - slippage_tolerance)
        
        # Find adapter for best protocol
        adapters = self._swap_adapters.get(chain, [])
        for adapter in adapters:
            if isinstance(adapter, UniswapV3Adapter) and quote.protocol == SwapProtocol.UNISWAP_V3:
                return adapter.execute_swap(token_in, token_out, amount_in, min_amount_out, slippage_tolerance)
            elif isinstance(adapter, CurveAdapter) and quote.protocol == SwapProtocol.CURVE:
                return adapter.execute_swap(token_in, token_out, amount_in, min_amount_out, slippage_tolerance)
        
        return None
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "chains_supported": len(self._swap_adapters),
            "protocols_per_chain": {
                chain.value: len(adapters)
                for chain, adapters in self._swap_adapters.items()
            }
        }


# Global router
_defi_router: Optional[DeFiRouter] = None


def get_defi_router() -> DeFiRouter:
    """Get the global DeFi router."""
    global _defi_router
    if _defi_router is None:
        _defi_router = DeFiRouter()
    return _defi_router
