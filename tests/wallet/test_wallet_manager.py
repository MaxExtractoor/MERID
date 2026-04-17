"""Tests for wallet/wallet_manager.py."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from wallet.wallet_manager import (
    WalletManager, get_wallet_manager, _wallet_manager
)
from wallet.key_manager import KeyType
from wallet.vault import VaultType
from wallet.hardware_wallet import HardwareWalletType


class TestWalletManager:
    """Test WalletManager class."""

    def test_initialization(self):
        """Test wallet manager initialization."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key.return_value = Mock()
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            
            assert manager._require_2fa is True
            assert manager._max_single_tx_usd == 10000.0
            assert manager._daily_limit_usd == 100000.0
            assert manager._daily_spent_usd == 0.0

    def test_unlock(self):
        """Test unlock method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager.unlock.return_value = True
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.unlock("password123")
            
            assert result is True
            mock_key_manager.unlock.assert_called_once_with("password123")

    def test_lock(self):
        """Test lock method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            manager.lock()
            
            mock_key_manager.lock.assert_called_once()

    def test_is_unlocked(self):
        """Test is_unlocked method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager._unlocked = True
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.is_unlocked()
            
            assert result is True

    def test_import_seed_phrase(self):
        """Test import_seed_phrase method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager.import_seed_phrase.return_value = "key_123"
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.import_seed_phrase("word1 word2 ...", "my_key", "ethereum")
            
            assert result == "key_123"
            mock_key_manager.import_seed_phrase.assert_called_once_with("word1 word2 ...", "my_key", "ethereum")

    def test_list_keys(self):
        """Test list_keys method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager.list_keys.return_value = [{"id": "key1"}, {"id": "key2"}]
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.list_keys()
            
            assert len(result) == 2
            assert result[0]["id"] == "key1"

    def test_revoke_key(self):
        """Test revoke_key method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager.revoke_key.return_value = True
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.revoke_key("key_123", "compromised")
            
            assert result is True
            mock_key_manager.revoke_key.assert_called_once_with("key_123", "compromised")

    def test_get_total_balance(self):
        """Test get_total_balance method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_vault_manager = Mock()
            mock_vault_manager.get_total_value.return_value = 50000.0
            mock_key.return_value = Mock()
            mock_vault.return_value = mock_vault_manager
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            result = manager.get_total_balance()
            
            assert result == 50000.0

    def test_can_execute_transaction(self):
        """Test can_execute_transaction method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager._unlocked = True
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            manager._daily_spent_usd = 0.0
            
            # Within limits
            can_execute, reason = manager.can_execute_transaction(5000.0)
            assert can_execute is True
            assert reason == "OK"
            
            # Exceeds single tx limit
            can_execute, reason = manager.can_execute_transaction(15000.0)
            assert can_execute is False
            assert "single transaction limit" in reason

    def test_can_execute_transaction_locked(self):
        """Test can_execute_transaction when locked."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager._unlocked = False
            mock_key.return_value = mock_key_manager
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            can_execute, reason = manager.can_execute_transaction(1000.0)
            
            assert can_execute is False
            assert "locked" in reason

    def test_record_transaction(self):
        """Test record_transaction method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key.return_value = Mock()
            mock_vault.return_value = Mock()
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            manager.record_transaction(5000.0)
            
            assert manager._daily_spent_usd == 5000.0

    def test_reset_daily_limits(self):
        """Test reset_daily_limits method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_vault_manager = Mock()
            mock_key.return_value = Mock()
            mock_vault.return_value = mock_vault_manager
            mock_wc.return_value = Mock()
            mock_hw.return_value = Mock()
            
            manager = WalletManager()
            manager._daily_spent_usd = 50000.0
            manager.reset_daily_limits()
            
            assert manager._daily_spent_usd == 0.0
            mock_vault_manager.reset_daily_limits.assert_called_once()

    def test_get_status(self):
        """Test get_status method."""
        with patch('wallet.wallet_manager.get_key_manager') as mock_key, \
             patch('wallet.wallet_manager.get_vault_manager') as mock_vault, \
             patch('wallet.wallet_manager.get_wallet_connect_manager') as mock_wc, \
             patch('wallet.wallet_manager.get_hardware_wallet_manager') as mock_hw:
            
            mock_key_manager = Mock()
            mock_key_manager.get_status.return_value = {"keys": 5}
            mock_key_manager._unlocked = True
            mock_key.return_value = mock_key_manager
            
            mock_vault_manager = Mock()
            mock_vault_manager.get_status.return_value = {"vaults": 3}
            mock_vault_manager.get_total_value.return_value = 100000.0
            mock_vault.return_value = mock_vault_manager
            
            mock_wc_manager = Mock()
            mock_wc_manager.get_status.return_value = {"sessions": 2}
            mock_wc.return_value = mock_wc_manager
            
            mock_hw_manager = Mock()
            mock_hw_manager.get_status.return_value = {"devices": 1}
            mock_hw.return_value = mock_hw_manager
            
            manager = WalletManager()
            status = manager.get_status()
            
            assert status["unlocked"] is True
            assert status["total_balance_usd"] == 100000.0
            assert status["key_manager"]["keys"] == 5
            assert status["vault_manager"]["vaults"] == 3
            assert status["wallet_connect"]["sessions"] == 2
            assert status["hardware_wallet"]["devices"] == 1


class TestGetWalletManager:
    """Test get_wallet_manager function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _wallet_manager
        import wallet.wallet_manager as wm
        wm._wallet_manager = None

    def test_singleton(self):
        """Test get_wallet_manager returns singleton."""
        with patch('wallet.wallet_manager.get_key_manager'), \
             patch('wallet.wallet_manager.get_vault_manager'), \
             patch('wallet.wallet_manager.get_wallet_connect_manager'), \
             patch('wallet.wallet_manager.get_hardware_wallet_manager'):
            
            manager1 = get_wallet_manager()
            manager2 = get_wallet_manager()
            assert manager1 is manager2
