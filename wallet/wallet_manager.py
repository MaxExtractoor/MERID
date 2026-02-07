"""
Wallet Manager - Central wallet management system.

Coordinates all wallet functionality including keys, vaults,
WalletConnect, and hardware wallets.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any

from wallet.key_manager import KeyManager, get_key_manager, KeyType
from wallet.vault import VaultManager, get_vault_manager, VaultType
from wallet.wallet_connect import WalletConnectManager, get_wallet_connect_manager
from wallet.hardware_wallet import HardwareWalletManager, get_hardware_wallet_manager, HardwareWalletType
from utils.logger import get_logger

logger = get_logger("wallet.manager")


class WalletManager:
    """
    Central wallet management system.
    
    Coordinates:
    - Key management (encrypted storage)
    - Vault system (trading/treasury separation)
    - WalletConnect (external wallet connections)
    - Hardware wallets (Ledger/Trezor)
    """
    
    def __init__(self):
        self.logger = get_logger("wallet.manager")
        
        # Sub-managers
        self._key_manager = get_key_manager()
        self._vault_manager = get_vault_manager()
        self._wallet_connect = get_wallet_connect_manager()
        self._hardware_wallet = get_hardware_wallet_manager()
        
        # Connected wallets (all types)
        self._active_wallets: Dict[str, Dict[str, Any]] = {}
        
        # Default settings
        self._require_2fa: bool = True
        self._max_single_tx_usd: float = 10000.0
        self._daily_limit_usd: float = 100000.0
        self._daily_spent_usd: float = 0.0
    
    # ==========================================
    # KEY MANAGEMENT
    # ==========================================
    
    def unlock(self, password: str) -> bool:
        """Unlock the wallet system."""
        success = self._key_manager.unlock(password)
        if success:
            self.logger.info("Wallet system unlocked")
        return success
    
    def lock(self) -> None:
        """Lock the wallet system."""
        self._key_manager.lock()
        self.logger.info("Wallet system locked")
    
    def is_unlocked(self) -> bool:
        """Check if wallet is unlocked."""
        return self._key_manager._unlocked
    
    def import_seed_phrase(
        self,
        seed_phrase: str,
        label: str = "",
        chain: str = "ethereum",
    ) -> Optional[str]:
        """Import a seed phrase."""
        return self._key_manager.import_seed_phrase(seed_phrase, label, chain)
    
    def import_private_key(
        self,
        private_key: str,
        label: str = "",
        chain: str = "ethereum",
    ) -> Optional[str]:
        """Import a private key."""
        return self._key_manager.import_private_key(private_key, label, chain)
    
    def list_keys(self) -> List[Dict[str, Any]]:
        """List all stored keys."""
        return self._key_manager.list_keys()
    
    def revoke_key(self, key_id: str, reason: str = "") -> bool:
        """Revoke a key."""
        return self._key_manager.revoke_key(key_id, reason)
    
    def rotate_key(self, key_id: str, new_key: str) -> Optional[str]:
        """Rotate a key."""
        return self._key_manager.rotate_key(key_id, new_key)
    
    # ==========================================
    # VAULT MANAGEMENT
    # ==========================================
    
    def get_vault(self, vault_type: VaultType) -> Optional[Dict[str, Any]]:
        """Get vault by type."""
        vault = self._vault_manager.get_vault_by_type(vault_type)
        return vault.to_dict() if vault else None
    
    def deposit_to_vault(
        self,
        vault_type: VaultType,
        asset: str,
        amount: float,
        value_usd: float,
    ) -> bool:
        """Deposit to a vault."""
        vault = self._vault_manager.get_vault_by_type(vault_type)
        if not vault:
            return False
        return self._vault_manager.deposit(vault.vault_id, asset, amount, value_usd)
    
    def withdraw_from_vault(
        self,
        vault_type: VaultType,
        asset: str,
        amount: float,
        value_usd: float,
        reason: str = "",
    ) -> bool:
        """Withdraw from a vault."""
        vault = self._vault_manager.get_vault_by_type(vault_type)
        if not vault:
            return False
        return self._vault_manager.withdraw(vault.vault_id, asset, amount, value_usd, reason)
    
    def transfer_between_vaults(
        self,
        from_type: VaultType,
        to_type: VaultType,
        asset: str,
        amount: float,
        value_usd: float,
        reason: str = "",
    ) -> Optional[str]:
        """Transfer between vaults."""
        from_vault = self._vault_manager.get_vault_by_type(from_type)
        to_vault = self._vault_manager.get_vault_by_type(to_type)
        
        if not from_vault or not to_vault:
            return None
        
        return self._vault_manager.transfer(
            from_vault.vault_id,
            to_vault.vault_id,
            asset,
            amount,
            value_usd,
            reason,
        )
    
    def get_total_balance(self) -> float:
        """Get total balance across all vaults."""
        return self._vault_manager.get_total_value()
    
    # ==========================================
    # WALLETCONNECT
    # ==========================================
    
    def create_wallet_connect_session(self, chain_id: int = 1) -> Dict[str, Any]:
        """Create a WalletConnect session with QR code."""
        session = self._wallet_connect.create_session(chain_id)
        return session.to_dict()
    
    def get_wallet_connect_sessions(self) -> List[Dict[str, Any]]:
        """Get active WalletConnect sessions."""
        sessions = self._wallet_connect.get_active_sessions()
        return [s.to_dict() for s in sessions]
    
    def disconnect_wallet_connect(self, session_id: str) -> bool:
        """Disconnect a WalletConnect session."""
        return self._wallet_connect.disconnect_session(session_id)
    
    def request_wallet_connect_sign(
        self,
        session_id: str,
        method: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        """Request signature via WalletConnect."""
        return self._wallet_connect.request_sign(session_id, method, params)
    
    # ==========================================
    # HARDWARE WALLET
    # ==========================================
    
    async def connect_hardware_wallet(
        self,
        wallet_type: HardwareWalletType,
    ) -> Optional[Dict[str, Any]]:
        """Connect a hardware wallet."""
        device = await self._hardware_wallet.connect_device(wallet_type)
        if device:
            self._active_wallets[device.device_id] = {
                "type": "hardware",
                "wallet_type": wallet_type.value,
                "device": device.to_dict(),
            }
            return device.to_dict()
        return None
    
    async def disconnect_hardware_wallet(self, device_id: str) -> bool:
        """Disconnect a hardware wallet."""
        success = await self._hardware_wallet.disconnect_device(device_id)
        if success and device_id in self._active_wallets:
            del self._active_wallets[device_id]
        return success
    
    def get_hardware_wallets(self) -> List[Dict[str, Any]]:
        """Get connected hardware wallets."""
        devices = self._hardware_wallet.get_connected_devices()
        return [d.to_dict() for d in devices]
    
    async def sign_with_hardware(
        self,
        device_id: str,
        tx_type: str,
        tx_data: Dict[str, Any],
    ) -> Optional[str]:
        """Sign with hardware wallet."""
        return await self._hardware_wallet.request_signature(device_id, tx_type, tx_data)
    
    # ==========================================
    # TRANSACTION MANAGEMENT
    # ==========================================
    
    def can_execute_transaction(self, value_usd: float) -> tuple[bool, str]:
        """Check if a transaction can be executed."""
        # Check single transaction limit
        if value_usd > self._max_single_tx_usd:
            return False, f"Exceeds single transaction limit: ${self._max_single_tx_usd}"
        
        # Check daily limit
        if self._daily_spent_usd + value_usd > self._daily_limit_usd:
            return False, f"Would exceed daily limit: ${self._daily_limit_usd}"
        
        # Check if unlocked
        if not self.is_unlocked():
            return False, "Wallet is locked"
        
        return True, "OK"
    
    def record_transaction(self, value_usd: float) -> None:
        """Record a transaction for limit tracking."""
        self._daily_spent_usd += value_usd
    
    def reset_daily_limits(self) -> None:
        """Reset daily limits (call at midnight)."""
        self._daily_spent_usd = 0.0
        self._vault_manager.reset_daily_limits()
        self.logger.info("Daily limits reset")
    
    # ==========================================
    # EMERGENCY FUNCTIONS
    # ==========================================
    
    def emergency_lock(self) -> None:
        """Emergency lock all wallets."""
        self._key_manager.lock()
        
        # Disconnect all WalletConnect sessions
        for session in self._wallet_connect.get_active_sessions():
            self._wallet_connect.disconnect_session(session.session_id)
        
        # Freeze all vaults
        for vault_id in list(self._vault_manager._vaults.keys()):
            self._vault_manager.freeze_vault(vault_id, "Emergency lock")
        
        self.logger.critical("EMERGENCY LOCK: All wallets locked and vaults frozen")
    
    def emergency_wipe(self, confirmation: str) -> bool:
        """Emergency wipe all keys."""
        return self._key_manager.emergency_wipe(confirmation)
    
    # ==========================================
    # STATUS
    # ==========================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive wallet status."""
        return {
            "unlocked": self.is_unlocked(),
            "total_balance_usd": self.get_total_balance(),
            "daily_spent_usd": self._daily_spent_usd,
            "daily_limit_usd": self._daily_limit_usd,
            "key_manager": self._key_manager.get_status(),
            "vault_manager": self._vault_manager.get_status(),
            "wallet_connect": self._wallet_connect.get_status(),
            "hardware_wallet": self._hardware_wallet.get_status(),
            "active_wallets": len(self._active_wallets),
        }


# Singleton
_wallet_manager: Optional[WalletManager] = None


def get_wallet_manager() -> WalletManager:
    """Get or create the Wallet Manager singleton."""
    global _wallet_manager
    if _wallet_manager is None:
        _wallet_manager = WalletManager()
    return _wallet_manager
