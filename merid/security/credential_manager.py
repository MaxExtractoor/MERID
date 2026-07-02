"""
Credential Manager - AES-256-GCM Encryption for Trading Credentials

This module provides secure credential storage and retrieval using AES-256-GCM encryption
with HKDF-derived keys. Follows 2026 industry best practices for credential security.

Reference: ADR-009 Credential Management (Arbiter-Bot)
https://arbiter-bot.dev/adrs/009-credential-management/
"""

import os
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import json
import logging

logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manages encrypted credential storage with AES-256-GCM.
    
    Key hierarchy:
    - Master key (from env var or KMS)
      ├── User/system-specific keys (HKDF-derived)
          ├── Kalshi API credentials
          └── Other platform credentials
    """
    
    def __init__(self, master_key: Optional[str] = None, salt: Optional[str] = None):
        """
        Initialize credential manager.
        
        Args:
            master_key: 32-byte (256-bit) master key. If None, reads from KALSHI_MASTER_KEY env var.
            salt: Salt for HKDF key derivation. If None, uses default salt.
        """
        if master_key is None:
            master_key = os.environ.get("KALSHI_MASTER_KEY")
            if not master_key:
                raise ValueError(
                    "KALSHI_MASTER_KEY environment variable not set. "
                    "Generate a secure 32-byte key: python -c 'import secrets; print(secrets.token_hex(32))'"
                )
        
        # Ensure master key is 32 bytes
        if len(master_key) == 64:  # hex encoded
            master_key = bytes.fromhex(master_key)
        elif len(master_key) == 32:  # raw bytes
            master_key = master_key
        else:
            raise ValueError("Master key must be 32 bytes (raw) or 64 hex characters")
        
        self.master_key = master_key
        self.salt = salt or "kalshi_credential_salt_v1"
        self.backend = default_backend()
        
    def _derive_key(self, context: str) -> bytes:
        """
        Derive a context-specific key using HKDF.
        
        Args:
            context: Context string (e.g., "kalshi_api", "kalshi_private_key")
            
        Returns:
            32-byte derived key
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt.encode(),
            info=context.encode(),
            backend=self.backend
        )
        return hkdf.derive(self.master_key)
    
    def encrypt(self, plaintext: str, context: str) -> Dict[str, str]:
        """
        Encrypt plaintext using AES-256-GCM.
        
        Args:
            plaintext: Data to encrypt
            context: Context for key derivation
            
        Returns:
            Dict with 'ciphertext' (base64) and 'nonce' (base64)
        """
        key = self._derive_key(context)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        
        return {
            'ciphertext': base64.b64encode(ciphertext).decode(),
            'nonce': base64.b64encode(nonce).decode()
        }
    
    def decrypt(self, ciphertext: str, nonce: str, context: str) -> str:
        """
        Decrypt ciphertext using AES-256-GCM.
        
        Args:
            ciphertext: Base64-encoded ciphertext
            nonce: Base64-encoded nonce
            context: Context for key derivation (must match encryption context)
            
        Returns:
            Decrypted plaintext
        """
        key = self._derive_key(context)
        aesgcm = AESGCM(key)
        
        ciphertext_bytes = base64.b64decode(ciphertext)
        nonce_bytes = base64.b64decode(nonce)
        
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, None)
        return plaintext.decode()
    
    def store_credential(self, credential_type: str, credential_data: Dict[str, str], 
                        storage_path: Path) -> None:
        """
        Encrypt and store credentials to file.
        
        Args:
            credential_type: Type of credential (e.g., "kalshi_api")
            credential_data: Dict of credential fields to encrypt
            storage_path: Path to store encrypted credentials
        """
        encrypted_data = {}
        for field, value in credential_data.items():
            context = f"{credential_type}_{field}"
            encrypted = self.encrypt(value, context)
            encrypted_data[field] = encrypted
        
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(storage_path, 'w') as f:
            json.dump(encrypted_data, f, indent=2)
        
        logger.info(f"Stored encrypted credentials for {credential_type} to {storage_path}")
    
    def load_credential(self, credential_type: str, storage_path: Path) -> Dict[str, str]:
        """
        Load and decrypt credentials from file.
        
        Args:
            credential_type: Type of credential (e.g., "kalshi_api")
            storage_path: Path to encrypted credentials file
            
        Returns:
            Dict of decrypted credential fields
        """
        if not storage_path.exists():
            raise FileNotFoundError(f"Credential file not found: {storage_path}")
        
        with open(storage_path, 'r') as f:
            encrypted_data = json.load(f)
        
        decrypted_data = {}
        for field, encrypted in encrypted_data.items():
            context = f"{credential_type}_{field}"
            decrypted = self.decrypt(
                encrypted['ciphertext'],
                encrypted['nonce'],
                context
            )
            decrypted_data[field] = decrypted
        
        logger.info(f"Loaded decrypted credentials for {credential_type} from {storage_path}")
        return decrypted_data


def generate_master_key() -> str:
    """
    Generate a secure 32-byte master key for credential encryption.
    
    Returns:
        Hex-encoded 32-byte key
    """
    import secrets
    return secrets.token_hex(32)


# Convenience function for Kalshi credentials
def get_kalshi_credential_manager() -> CredentialManager:
    """
    Get a credential manager instance configured for Kalshi.
    
    Returns:
        CredentialManager instance
    """
    return CredentialManager()


def store_kalshi_credentials(api_key_id: str, private_key_path: str, 
                             storage_path: Optional[Path] = None) -> None:
    """
    Convenience function to store Kalshi credentials securely.
    
    Args:
        api_key_id: Kalshi API key ID
        private_key_path: Path to Kalshi private key file
        storage_path: Path to store encrypted credentials (default: data/credentials/kalshi.json)
    """
    if storage_path is None:
        storage_path = Path("data/credentials/kalshi.json")
    
    # Read private key
    with open(private_key_path, 'r') as f:
        private_key = f.read()
    
    manager = get_kalshi_credential_manager()
    credential_data = {
        'api_key_id': api_key_id,
        'private_key': private_key
    }
    
    manager.store_credential("kalshi", credential_data, storage_path)


def load_kalshi_credentials(storage_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Convenience function to load Kalshi credentials securely.
    
    Args:
        storage_path: Path to encrypted credentials (default: data/credentials/kalshi.json)
        
    Returns:
        Dict with 'api_key_id' and 'private_key'
    """
    if storage_path is None:
        storage_path = Path("data/credentials/kalshi.json")
    
    manager = get_kalshi_credential_manager()
    return manager.load_credential("kalshi", storage_path)
