"""
Security module for credential management and encryption.
"""

from .credential_manager import (
    CredentialManager,
    generate_master_key,
    get_kalshi_credential_manager,
    store_kalshi_credentials,
    load_kalshi_credentials
)

__all__ = [
    'CredentialManager',
    'generate_master_key',
    'get_kalshi_credential_manager',
    'store_kalshi_credentials',
    'load_kalshi_credentials'
]
