"""
MERID Wallet & Custody System.

Secure wallet management with vault separation, hardware wallet support,
and emergency key management.

Version: 1.0.0
"""

from wallet.wallet_manager import WalletManager, get_wallet_manager
from wallet.vault import Vault, VaultType, get_vault_manager
from wallet.key_manager import KeyManager, KeyType, get_key_manager
from wallet.wallet_connect import WalletConnectSession, get_wallet_connect_manager
from wallet.hardware_wallet import HardwareWalletInterface, get_hardware_wallet_manager

__all__ = [
    "WalletManager",
    "get_wallet_manager",
    "Vault",
    "VaultType",
    "get_vault_manager",
    "KeyManager",
    "KeyType",
    "get_key_manager",
    "WalletConnectSession",
    "get_wallet_connect_manager",
    "HardwareWalletInterface",
    "get_hardware_wallet_manager",
]

# Security settings
REQUIRE_ENCRYPTION = True
REQUIRE_2FA_FOR_WITHDRAWAL = True
MAX_SINGLE_WITHDRAWAL_USD = 10000.0
