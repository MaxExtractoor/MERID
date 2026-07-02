"""
Tests for credential manager module.
"""

import pytest
import os
import tempfile
from pathlib import Path
from merid.security.credential_manager import (
    CredentialManager,
    generate_master_key,
    get_kalshi_credential_manager,
    store_kalshi_credentials,
    load_kalshi_credentials
)


class TestCredentialManager:
    """Test suite for CredentialManager class."""
    
    def test_generate_master_key(self):
        """Test master key generation."""
        key = generate_master_key()
        assert len(key) == 64  # 32 bytes in hex
        assert all(c in '0123456789abcdef' for c in key)
    
    def test_credential_manager_initialization_with_key(self):
        """Test initialization with explicit master key."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        assert manager.master_key == bytes.fromhex(master_key)
    
    def test_credential_manager_initialization_with_env(self):
        """Test initialization from environment variable."""
        master_key = generate_master_key()
        os.environ['KALSHI_MASTER_KEY'] = master_key
        manager = CredentialManager()
        assert manager.master_key == bytes.fromhex(master_key)
        del os.environ['KALSHI_MASTER_KEY']
    
    def test_credential_manager_missing_env(self):
        """Test error when master key not provided."""
        if 'KALSHI_MASTER_KEY' in os.environ:
            del os.environ['KALSHI_MASTER_KEY']
        with pytest.raises(ValueError, match="KALSHI_MASTER_KEY environment variable not set"):
            CredentialManager()
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        plaintext = "test_api_key_12345"
        context = "test_context"
        
        encrypted = manager.encrypt(plaintext, context)
        assert 'ciphertext' in encrypted
        assert 'nonce' in encrypted
        
        decrypted = manager.decrypt(encrypted['ciphertext'], encrypted['nonce'], context)
        assert decrypted == plaintext
    
    def test_decrypt_wrong_context_fails(self):
        """Test that decryption fails with wrong context."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        plaintext = "test_api_key_12345"
        encrypted = manager.encrypt(plaintext, "context1")
        
        # Should fail with different context
        with pytest.raises(Exception):  # cryptography raises various exceptions
            manager.decrypt(encrypted['ciphertext'], encrypted['nonce'], "context2")
    
    def test_store_load_credential(self):
        """Test storing and loading credentials."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_credentials.json"
            
            credential_data = {
                'api_key_id': 'test_key_id',
                'private_key': '-----BEGIN RSA PRIVATE KEY-----\ntest_key\n-----END RSA PRIVATE KEY-----'
            }
            
            manager.store_credential("test_type", credential_data, storage_path)
            assert storage_path.exists()
            
            loaded_data = manager.load_credential("test_type", storage_path)
            assert loaded_data == credential_data
    
    def test_load_nonexistent_credential(self):
        """Test error when loading nonexistent credential file."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        with pytest.raises(FileNotFoundError):
            manager.load_credential("test_type", Path("/nonexistent/path.json"))
    
    def test_key_derivation_different_contexts(self):
        """Test that different contexts produce different keys."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        key1 = manager._derive_key("context1")
        key2 = manager._derive_key("context2")
        
        assert key1 != key2
    
    def test_key_derivation_same_context(self):
        """Test that same context produces same key."""
        master_key = generate_master_key()
        manager = CredentialManager(master_key=master_key)
        
        key1 = manager._derive_key("context1")
        key2 = manager._derive_key("context1")
        
        assert key1 == key2


class TestKalshiCredentialConvenience:
    """Test suite for Kalshi credential convenience functions."""
    
    def test_get_kalshi_credential_manager(self):
        """Test getting Kalshi credential manager."""
        master_key = generate_master_key()
        os.environ['KALSHI_MASTER_KEY'] = master_key
        
        manager = get_kalshi_credential_manager()
        assert isinstance(manager, CredentialManager)
        
        del os.environ['KALSHI_MASTER_KEY']
    
    def test_store_load_kalshi_credentials(self):
        """Test storing and loading Kalshi credentials."""
        master_key = generate_master_key()
        os.environ['KALSHI_MASTER_KEY'] = master_key
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create temporary private key file
            private_key_path = Path(tmpdir) / "private_key.pem"
            private_key_content = "-----BEGIN RSA PRIVATE KEY-----\ntest_key\n-----END RSA PRIVATE KEY-----"
            private_key_path.write_text(private_key_content)
            
            storage_path = Path(tmpdir) / "kalshi_credentials.json"
            
            store_kalshi_credentials(
                api_key_id="test_key_id",
                private_key_path=str(private_key_path),
                storage_path=storage_path
            )
            
            assert storage_path.exists()
            
            loaded = load_kalshi_credentials(storage_path)
            assert loaded['api_key_id'] == "test_key_id"
            assert loaded['private_key'] == private_key_content
        
        del os.environ['KALSHI_MASTER_KEY']
