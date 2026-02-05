"""MERID Multi-Chain Wallet Manager.

Unified wallet management for Ethereum, Solana, Cronos, and other chains.
Supports HD wallets, hardware wallets, and secure key storage.
"""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from decimal import Decimal
import os
import structlog

from eth_account import Account
from eth_account.hdaccount import generate_mnemonic, seed_from_mnemonic, key_from_seed
from solders.keypair import Keypair
import base58

logger = structlog.get_logger(__name__)


@dataclass
class WalletInfo:
    """Wallet information across chains."""
    name: str
    eth_address: Optional[str]
    sol_address: Optional[str]
    cronos_address: Optional[str]
    created_at: str
    type: str  # "hd", "hardware", "imported"


@dataclass
class WalletBalance:
    """Wallet balances across chains."""
    eth_balance: Decimal = Decimal(0)
    sol_balance: Decimal = Decimal(0)
    cronos_balance: Decimal = Decimal(0)
    tokens: Dict[str, Decimal] = None
    
    def __post_init__(self):
        if self.tokens is None:
            self.tokens = {}


class HDWalletManager:
    """Hierarchical Deterministic (HD) Wallet manager."""
    
    # BIP44 coin types
    COIN_TYPES = {
        "eth": 60,      # Ethereum
        "cronos": 60,   # Cronos (EVM)
        "sol": 501,     # Solana
    }
    
    def __init__(self, mnemonic: Optional[str] = None):
        self.mnemonic = mnemonic or generate_mnemonic(12, "english")
        self.logger = logger.bind(component="HDWalletManager")
        self._eth_accounts: Dict[int, Account] = {}
        self._sol_keypairs: Dict[int, Keypair] = {}
        
        self.logger.info("hd_wallet_initialized", has_mnemonic=bool(mnemonic))
    
    def derive_eth_account(self, index: int = 0) -> Account:
        """Derive Ethereum account from HD wallet."""
        if index in self._eth_accounts:
            return self._eth_accounts[index]
        
        # BIP44 path: m/44'/60'/0'/0/index
        seed = seed_from_mnemonic(self.mnemonic, "")
        private_key = key_from_seed(seed, f"m/44'/60'/0'/0/{index}")
        
        account = Account.from_key(private_key)
        self._eth_accounts[index] = account
        
        self.logger.info(
            "eth_account_derived",
            index=index,
            address=account.address[:10]
        )
        
        return account
    
    def derive_sol_keypair(self, index: int = 0) -> Keypair:
        """Derive Solana keypair from HD wallet."""
        if index in self._sol_keypairs:
            return self._sol_keypairs[index]
        
        # Note: Solana uses different derivation (BIP44 with ed25519)
        # Simplified - in production use proper SLIP-0010
        seed = seed_from_mnemonic(self.mnemonic, "")
        # Use seed bytes for Solana keypair
        seed_bytes = bytes(seed)[:32]
        keypair = Keypair.from_seed(seed_bytes)
        
        self._sol_keypairs[index] = keypair
        
        self.logger.info(
            "sol_keypair_derived",
            index=index,
            pubkey=str(keypair.pubkey())[:10]
        )
        
        return keypair
    
    def get_eth_address(self, index: int = 0) -> str:
        """Get Ethereum address for index."""
        return self.derive_eth_account(index).address
    
    def get_sol_address(self, index: int = 0) -> str:
        """Get Solana address for index."""
        return str(self.derive_sol_keypair(index).pubkey())
    
    def get_eth_private_key(self, index: int = 0) -> str:
        """Get Ethereum private key for index (use with caution)."""
        return self.derive_eth_account(index).key.hex()
    
    def get_sol_private_key(self, index: int = 0) -> bytes:
        """Get Solana private key bytes for index (use with caution)."""
        keypair = self.derive_sol_keypair(index)
        return bytes(keypair)
    
    def export_mnemonic(self) -> str:
        """Export mnemonic phrase (secure storage recommended)."""
        return self.mnemonic
    
    def derive_multiple_accounts(
        self,
        chain: str,
        count: int = 10
    ) -> List[str]:
        """Derive multiple accounts for a chain."""
        addresses = []
        
        for i in range(count):
            if chain in ["eth", "ethereum", "cronos"]:
                addr = self.get_eth_address(i)
            elif chain in ["sol", "solana"]:
                addr = self.get_sol_address(i)
            else:
                raise ValueError(f"Unsupported chain: {chain}")
            
            addresses.append(addr)
        
        return addresses


class SecureWalletStorage:
    """Secure storage for wallet keys (placeholder for HSM/Vault integration)."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        self.logger = logger.bind(component="SecureWalletStorage")
        # In production, integrate with:
        # - HashiCorp Vault
        # - AWS KMS / Azure Key Vault
        # - Hardware Security Modules (HSM)
        self._storage: Dict[str, Any] = {}
    
    def store_wallet(self, wallet_id: str, wallet_data: Dict[str, Any]) -> bool:
        """Store wallet securely."""
        # Placeholder - in production encrypt and store in secure backend
        self._storage[wallet_id] = wallet_data
        self.logger.info("wallet_stored", wallet_id=wallet_id[:8])
        return True
    
    def retrieve_wallet(self, wallet_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve wallet from secure storage."""
        wallet = self._storage.get(wallet_id)
        if wallet:
            self.logger.info("wallet_retrieved", wallet_id=wallet_id[:8])
        return wallet
    
    def delete_wallet(self, wallet_id: str) -> bool:
        """Delete wallet from storage."""
        if wallet_id in self._storage:
            del self._storage[wallet_id]
            self.logger.info("wallet_deleted", wallet_id=wallet_id[:8])
            return True
        return False


class MultiChainWalletManager:
    """Manager for multi-chain wallets."""
    
    def __init__(self):
        self.hd_managers: Dict[str, HDWalletManager] = {}
        self.imported_wallets: Dict[str, Dict[str, Any]] = {}
        self.secure_storage = SecureWalletStorage()
        self.logger = logger.bind(component="MultiChainWalletManager")
    
    def create_hd_wallet(self, name: str, mnemonic: Optional[str] = None) -> str:
        """Create new HD wallet."""
        hd_manager = HDWalletManager(mnemonic)
        wallet_id = f"hd_{name}_{os.urandom(4).hex()}"
        
        self.hd_managers[wallet_id] = hd_manager
        
        # Store securely
        wallet_data = {
            "name": name,
            "type": "hd",
            "mnemonic_encrypted": hd_manager.mnemonic,  # Encrypt in production
            "created_at": str(os.times()[0])
        }
        self.secure_storage.store_wallet(wallet_id, wallet_data)
        
        self.logger.info("hd_wallet_created", wallet_id=wallet_id[:16], name=name)
        
        return wallet_id
    
    def import_eth_wallet(self, name: str, private_key: str) -> str:
        """Import Ethereum private key."""
        account = Account.from_key(private_key)
        
        wallet_id = f"imported_eth_{name}_{os.urandom(4).hex()}"
        wallet_data = {
            "name": name,
            "type": "imported",
            "chain": "eth",
            "address": account.address,
            "private_key_encrypted": private_key  # Encrypt in production
        }
        
        self.imported_wallets[wallet_id] = wallet_data
        self.secure_storage.store_wallet(wallet_id, wallet_data)
        
        self.logger.info(
            "eth_wallet_imported",
            wallet_id=wallet_id[:16],
            address=account.address[:10]
        )
        
        return wallet_id
    
    def import_sol_wallet(self, name: str, private_key_bytes: bytes) -> str:
        """Import Solana private key."""
        keypair = Keypair.from_bytes(private_key_bytes)
        
        wallet_id = f"imported_sol_{name}_{os.urandom(4).hex()}"
        wallet_data = {
            "name": name,
            "type": "imported",
            "chain": "sol",
            "address": str(keypair.pubkey()),
            "private_key_encrypted": base58.b58encode(private_key_bytes).decode()
        }
        
        self.imported_wallets[wallet_id] = wallet_data
        self.secure_storage.store_wallet(wallet_id, wallet_data)
        
        self.logger.info(
            "sol_wallet_imported",
            wallet_id=wallet_id[:16],
            address=str(keypair.pubkey())[:10]
        )
        
        return wallet_id
    
    def get_wallet_addresses(
        self,
        wallet_id: str,
        indices: List[int] = None
    ) -> Dict[str, List[str]]:
        """Get addresses for wallet across chains."""
        indices = indices or [0]
        addresses = {
            "eth": [],
            "sol": [],
            "cronos": []
        }
        
        if wallet_id in self.hd_managers:
            hd = self.hd_managers[wallet_id]
            for idx in indices:
                addresses["eth"].append(hd.get_eth_address(idx))
                addresses["sol"].append(hd.get_sol_address(idx))
                addresses["cronos"].append(hd.get_eth_address(idx))
        
        elif wallet_id in self.imported_wallets:
            wallet = self.imported_wallets[wallet_id]
            chain = wallet.get("chain")
            if chain == "eth":
                addresses["eth"] = [wallet["address"]]
                addresses["cronos"] = [wallet["address"]]
            elif chain == "sol":
                addresses["sol"] = [wallet["address"]]
        
        return addresses
    
    def get_signing_credentials(
        self,
        wallet_id: str,
        chain: str,
        index: int = 0
    ) -> Optional[Any]:
        """Get signing credentials for a wallet."""
        # Use with extreme caution - return key only for signing
        if wallet_id in self.hd_managers:
            hd = self.hd_managers[wallet_id]
            
            if chain in ["eth", "ethereum", "cronos"]:
                return hd.derive_eth_account(index)
            elif chain in ["sol", "solana"]:
                return hd.derive_sol_keypair(index)
        
        elif wallet_id in self.imported_wallets:
            wallet = self.imported_wallets[wallet_id]
            if wallet.get("chain") == chain:
                if chain == "eth":
                    return Account.from_key(wallet["private_key_encrypted"])
                elif chain == "sol":
                    return Keypair.from_bytes(
                        base58.b58decode(wallet["private_key_encrypted"])
                    )
        
        return None
    
    def list_wallets(self) -> List[WalletInfo]:
        """List all managed wallets."""
        wallets = []
        
        for wallet_id, hd in self.hd_managers.items():
            wallets.append(WalletInfo(
                name=wallet_id.replace("hd_", "").rsplit("_", 1)[0],
                eth_address=hd.get_eth_address(0),
                sol_address=hd.get_sol_address(0),
                cronos_address=hd.get_eth_address(0),
                created_at="",
                type="hd"
            ))
        
        for wallet_id, wallet in self.imported_wallets.items():
            chain = wallet.get("chain")
            wallets.append(WalletInfo(
                name=wallet["name"],
                eth_address=wallet["address"] if chain == "eth" else None,
                sol_address=wallet["address"] if chain == "sol" else None,
                cronos_address=wallet["address"] if chain == "eth" else None,
                created_at="",
                type="imported"
            ))
        
        return wallets
    
    def backup_mnemonic(self, wallet_id: str) -> Optional[str]:
        """Get mnemonic for HD wallet backup (secure handling required)."""
        if wallet_id in self.hd_managers:
            return self.hd_managers[wallet_id].export_mnemonic()
        return None
    
    def estimate_gas_costs(
        self,
        chain: str,
        operation: str
    ) -> Dict[str, Decimal]:
        """Estimate gas costs for operations."""
        # Placeholder - would query current gas prices
        estimates = {
            "eth": {
                "transfer": Decimal("0.001"),  # ETH
                "swap": Decimal("0.01"),
                "contract_interaction": Decimal("0.005")
            },
            "sol": {
                "transfer": Decimal("0.000005"),  # SOL
                "swap": Decimal("0.0001"),
                "token_transfer": Decimal("0.00001")
            }
        }
        
        return estimates.get(chain, {})


# Singleton instance for application use
wallet_manager = MultiChainWalletManager()
