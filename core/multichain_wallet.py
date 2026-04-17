"""
Multi-Chain Wallet Abstraction for MERID
Unified interface for EVM and non-EVM chains.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from core.environment import get_environment_flags
from core.network_client import RoutingProfile, get_network_client

logger = get_logger("core.multichain_wallet")


class ChainType(Enum):
    """Blockchain types."""
    EVM = "evm"
    SOLANA = "solana"
    TON = "ton"
    COSMOS = "cosmos"


class ChainNetwork(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    ARBITRUM = "arbitrum"
    BASE = "base"
    BNB = "bnb"
    POLYGON = "polygon"
    OPTIMISM = "optimism"
    SOLANA = "solana"
    TON = "ton"


@dataclass
class ChainConfig:
    """Configuration for a blockchain."""
    chain_id: int
    name: str
    chain_type: ChainType
    rpc_url: str
    explorer_url: str
    native_token: str
    gas_token: str
    supports_eip1559: bool


@dataclass
class WalletAddress:
    """Wallet address on a chain."""
    chain: ChainNetwork
    address: str
    derivation_path: Optional[str]
    public_key: Optional[str]


@dataclass
class Transaction:
    """Transaction data."""
    chain: ChainNetwork
    from_address: str
    to_address: str
    value: float
    gas_limit: int
    gas_price: float
    nonce: int
    data: Optional[str]
    tx_hash: Optional[str]
    status: str


class ChainAdapter(ABC):
    """Base class for chain adapters."""
    
    def __init__(self, config: ChainConfig):
        self.config = config
    
    @abstractmethod
    def get_address(self, account_index: int = 0) -> str:
        """Get wallet address."""
        pass
    
    @abstractmethod
    def get_balance(self, address: str) -> float:
        """Get native token balance."""
        pass
    
    @abstractmethod
    def get_nonce(self, address: str) -> int:
        """Get transaction nonce."""
        pass
    
    @abstractmethod
    def estimate_gas(self, transaction: Dict[str, Any]) -> int:
        """Estimate gas for transaction."""
        pass
    
    @abstractmethod
    def send_transaction(self, transaction: Transaction) -> str:
        """Send transaction and return tx hash."""
        pass
    
    @abstractmethod
    def get_transaction_status(self, tx_hash: str) -> str:
        """Get transaction status."""
        pass


class EVMAdapter(ChainAdapter):
    """Adapter for EVM-compatible chains."""
    
    def __init__(self, config: ChainConfig):
        super().__init__(config)
        self._nonce_cache: Dict[str, int] = {}
    
    def get_address(self, account_index: int = 0) -> str:
        """Get EVM address."""
        # In production, derive from mnemonic/private key
        return f"0x{'0' * 40}"
    
    def get_balance(self, address: str) -> float:
        """Get ETH/native token balance."""
        # In production, call RPC
        return 0.0
    
    def get_nonce(self, address: str) -> int:
        """Get transaction nonce."""
        # Check cache first
        if address in self._nonce_cache:
            nonce = self._nonce_cache[address]
            self._nonce_cache[address] += 1
            return nonce
        
        # In production, call RPC eth_getTransactionCount
        nonce = 0
        self._nonce_cache[address] = nonce + 1
        return nonce
    
    def estimate_gas(self, transaction: Dict[str, Any]) -> int:
        """Estimate gas."""
        # In production, call RPC eth_estimateGas
        return 21000
    
    def send_transaction(self, transaction: Transaction) -> str:
        """Send EVM transaction."""
        # In production:
        # 1. Build transaction object
        # 2. Sign with private key
        # 3. Send via eth_sendRawTransaction
        
        tx_hash = f"0x{'0' * 64}"
        transaction.tx_hash = tx_hash
        transaction.status = "pending"
        
        logger.info(
            f"Sent transaction on {self.config.name}: {transaction.value} "
            f"{self.config.native_token} to {transaction.to_address}"
        )
        
        return tx_hash
    
    def get_transaction_status(self, tx_hash: str) -> str:
        """Get transaction status."""
        # In production, call eth_getTransactionReceipt
        return "confirmed"
    
    def get_gas_price(self) -> Dict[str, float]:
        """Get current gas prices."""
        if self.config.supports_eip1559:
            # EIP-1559 gas pricing
            return {
                "base_fee": 30.0,
                "max_priority_fee": 2.0,
                "max_fee": 50.0
            }
        else:
            # Legacy gas pricing
            return {
                "gas_price": 30.0
            }


class SolanaAdapter(ChainAdapter):
    """Adapter for Solana."""
    
    def get_address(self, account_index: int = 0) -> str:
        """Get Solana address."""
        # In production, derive from keypair
        return "11111111111111111111111111111111"
    
    def get_balance(self, address: str) -> float:
        """Get SOL balance."""
        # In production, call getBalance RPC
        return 0.0
    
    def get_nonce(self, address: str) -> int:
        """Solana uses recent blockhash, not nonce."""
        return 0
    
    def estimate_gas(self, transaction: Dict[str, Any]) -> int:
        """Estimate compute units."""
        # In production, simulate transaction
        return 200000
    
    def send_transaction(self, transaction: Transaction) -> str:
        """Send Solana transaction."""
        # In production:
        # 1. Get recent blockhash
        # 2. Build transaction
        # 3. Sign with keypair
        # 4. Send via sendTransaction RPC
        
        tx_hash = "1" * 88
        transaction.tx_hash = tx_hash
        transaction.status = "pending"
        
        logger.info(
            f"Sent Solana transaction: {transaction.value} SOL to {transaction.to_address}"
        )
        
        return tx_hash
    
    def get_transaction_status(self, tx_hash: str) -> str:
        """Get transaction status."""
        # In production, call getTransaction RPC
        return "confirmed"


class MultiChainWallet:
    """Unified multi-chain wallet."""
    
    def __init__(self):
        self._adapters: Dict[ChainNetwork, ChainAdapter] = {}
        self._addresses: Dict[ChainNetwork, str] = {}
        self._network_client = get_network_client()
        self._module_name = "core.multichain_wallet"
        self._network_client.register_module_profile(self._module_name, RoutingProfile.VPN_A)
        self._initialize_chains()
    
    def _initialize_chains(self) -> None:
        """Initialize chain adapters."""
        # EVM chains
        evm_chains = {
            ChainNetwork.ETHEREUM: ChainConfig(
                chain_id=1,
                name="Ethereum",
                chain_type=ChainType.EVM,
                rpc_url="https://eth.llamarpc.com",
                explorer_url="https://etherscan.io",
                native_token="ETH",
                gas_token="ETH",
                supports_eip1559=True
            ),
            ChainNetwork.ARBITRUM: ChainConfig(
                chain_id=42161,
                name="Arbitrum",
                chain_type=ChainType.EVM,
                rpc_url="https://arb1.arbitrum.io/rpc",
                explorer_url="https://arbiscan.io",
                native_token="ETH",
                gas_token="ETH",
                supports_eip1559=True
            ),
            ChainNetwork.BASE: ChainConfig(
                chain_id=8453,
                name="Base",
                chain_type=ChainType.EVM,
                rpc_url="https://mainnet.base.org",
                explorer_url="https://basescan.org",
                native_token="ETH",
                gas_token="ETH",
                supports_eip1559=True
            ),
            ChainNetwork.BNB: ChainConfig(
                chain_id=56,
                name="BNB Chain",
                chain_type=ChainType.EVM,
                rpc_url="https://bsc-dataseed.binance.org",
                explorer_url="https://bscscan.com",
                native_token="BNB",
                gas_token="BNB",
                supports_eip1559=False
            )
        }
        
        for chain, config in evm_chains.items():
            adapter = EVMAdapter(config)
            self._adapters[chain] = adapter
            self._addresses[chain] = adapter.get_address()
        
        # Solana
        solana_config = ChainConfig(
            chain_id=0,
            name="Solana",
            chain_type=ChainType.SOLANA,
            rpc_url="https://api.mainnet-beta.solana.com",
            explorer_url="https://explorer.solana.com",
            native_token="SOL",
            gas_token="SOL",
            supports_eip1559=False
        )
        solana_adapter = SolanaAdapter(solana_config)
        self._adapters[ChainNetwork.SOLANA] = solana_adapter
        self._addresses[ChainNetwork.SOLANA] = solana_adapter.get_address()
        
        logger.info(f"Initialized {len(self._adapters)} chain adapters")
    
    def get_address(self, chain: ChainNetwork) -> Optional[str]:
        """Get wallet address for a chain."""
        return self._addresses.get(chain)
    
    def get_all_addresses(self) -> Dict[ChainNetwork, str]:
        """Get all wallet addresses."""
        return self._addresses.copy()
    
    def get_balance(self, chain: ChainNetwork, address: Optional[str] = None) -> float:
        """Get balance on a chain."""
        if not self._can_use_network():
            logger.warning("Network disabled; returning cached/zero balances")
            return 0.0
        adapter = self._adapters.get(chain)
        if not adapter:
            return 0.0
        
        addr = address or self._addresses.get(chain)
        if not addr:
            return 0.0
        self._guard_network_call("balance", chain.value)
        return adapter.get_balance(addr)
    
    def get_all_balances(self) -> Dict[ChainNetwork, float]:
        """Get balances across all chains."""
        balances = {}
        
        for chain, address in self._addresses.items():
            balance = self.get_balance(chain, address)
            balances[chain] = balance
        
        return balances
    
    def send_transaction(
        self,
        chain: ChainNetwork,
        to_address: str,
        value: float,
        data: Optional[str] = None
    ) -> Optional[str]:
        """Send transaction on a chain."""
        if not self._can_use_network():
            logger.error("Cannot send transaction while offline or VPN-restricted")
            return None
        adapter = self._adapters.get(chain)
        if not adapter:
            logger.error(f"No adapter for chain {chain.value}")
            return None
        
        from_address = self._addresses.get(chain)
        if not from_address:
            logger.error(f"No address for chain {chain.value}")
            return None
        
        # Get nonce
        nonce = adapter.get_nonce(from_address)
        
        # Estimate gas
        gas_limit = adapter.estimate_gas({
            "from": from_address,
            "to": to_address,
            "value": value,
            "data": data
        })
        
        # Get gas price
        if isinstance(adapter, EVMAdapter):
            gas_prices = adapter.get_gas_price()
            gas_price = gas_prices.get("max_fee", gas_prices.get("gas_price", 0))
        else:
            gas_price = 0.0
        
        # Build transaction
        transaction = Transaction(
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            value=value,
            gas_limit=gas_limit,
            gas_price=gas_price,
            nonce=nonce,
            data=data,
            tx_hash=None,
            status="pending"
        )
        
        # Send transaction
        self._guard_network_call("send_tx", f"{chain.value}:{to_address}")
        tx_hash = adapter.send_transaction(transaction)
        
        return tx_hash
    
    def get_transaction_status(
        self,
        chain: ChainNetwork,
        tx_hash: str
    ) -> Optional[str]:
        """Get transaction status."""
        if not self._can_use_network():
            logger.warning("Network disabled; transaction status unavailable")
            return None
        adapter = self._adapters.get(chain)
        if not adapter:
            logger.error(f"No adapter for chain {chain.value}")
            return None
        
        self._guard_network_call("tx_status", f"{chain.value}:{tx_hash}")
        return adapter.get_transaction_status(tx_hash)
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary across all chains."""
        balances = self.get_all_balances()
        
        total_value_usd = 0.0  # Would need price feeds
        
        return {
            "chains": len(self._adapters),
            "addresses": len(self._addresses),
            "balances": {
                chain.value: balance
                for chain, balance in balances.items()
            },
            "total_value_usd": total_value_usd
        }


# Global wallet
_multichain_wallet: Optional[MultiChainWallet] = None
_multichain_wallet_lock = threading.Lock()


def get_multichain_wallet() -> MultiChainWallet:
    """Get the global multi-chain wallet."""
    global _multichain_wallet
    if _multichain_wallet is None:
        with _multichain_wallet_lock:
            if _multichain_wallet is None:
                _multichain_wallet = MultiChainWallet()
    return _multichain_wallet
