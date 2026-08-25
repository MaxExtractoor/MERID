"""
Secrets Management Module

Provides secure handling of sensitive credentials and secrets.
Features:
- Credential masking for logging
- Environment variable validation
- Secure string handling
- Detection of sensitive data patterns
"""

import os
import re
from typing import Optional, Set, Dict, Any
from functools import lru_cache

# Patterns that indicate sensitive data
SENSITIVE_PATTERNS = [
    r'password',
    r'secret',
    r'key',
    r'token',
    r'credential',
    r'auth',
    r'api[_-]?key',
    r'access[_-]?key',
    r'secret[_-]?key',
    r'private[_-]?key',
    r'session[_-]?id',
    r'csrf',
    r'bearer',
]

SENSITIVE_FIELDS: Set[str] = {
    'password', 'secret', 'token', 'credential', 'api_key', 'access_key',
    'secret_key', 'private_key', 'session_id', 'csrf_token', 'bearer_token',
    'auth_token', 'refresh_token', 'app_password', 'service_role_key',
    'anon_key', 'superuser_password', 'telegram_token', 'telegram_chat_id',
    'polygon_access_key_id', 'polygon_secret_access_key', 'polygon_s3_endpoint',
    'polygon_bucket', 'huggingface_api_key', 'claude_sonnet_4', 'deepseek_api_key',
    'ollama_api_key', 'openai_api_key', 'open_router_api_key', 'anthropic_api_key',
    'finnhub_api_key', 'finnhub_secret_key', 'the_graph_api_key', 'nansen_api_key',
    'helius_rpc_url', 'coinbase_api_key', 'coinbase_api_secret', 'messari_api_key',
    'alpha_vantage_api_key', 'polygon_api_key', 'news_api_key', 'serper_api_key',
    'fred_api_key', 'supabase_url', 'supabase_anon_key', 'supabase_service_role_key',
    'my_email', 'app_password', 'receiver_email',
}

# Compile regex patterns for efficient matching
_SENSITIVE_REGEX = re.compile(
    '|'.join(SENSITIVE_PATTERNS),
    re.IGNORECASE
)


def is_sensitive_field(field_name: str) -> bool:
    """Check if a field name indicates sensitive data.
    
    Args:
        field_name: The field name to check
        
    Returns:
        True if the field name suggests sensitive data
    """
    field_lower = field_name.lower()
    
    # Direct match against known sensitive fields
    if field_lower in SENSITIVE_FIELDS:
        return True
    
    # Pattern match
    if _SENSITIVE_REGEX.search(field_lower):
        return True
    
    return False


def mask_value(value: Any, field_name: str = "") -> str:
    """Mask a sensitive value for logging/display.
    
    Args:
        value: The value to mask
        field_name: Optional field name for context
        
    Returns:
        Masked string representation
    """
    if value is None:
        return "[None]"
    
    # Convert to string
    str_value = str(value)
    
    # If empty or very short, return as-is
    if len(str_value) <= 4:
        return str_value
    
    # If field name indicates sensitivity, mask it
    if field_name and is_sensitive_field(field_name):
        return mask_sensitive_string(str_value)
    
    # Check if value looks like a sensitive pattern (e.g., long hex strings)
    if _looks_like_secret(str_value):
        return mask_sensitive_string(str_value)
    
    return str_value


def mask_sensitive_string(value: str, visible_chars: int = 4) -> str:
    """Mask a sensitive string, showing only first and last few characters.
    
    Args:
        value: The string to mask
        visible_chars: Number of characters to show at start and end
        
    Returns:
        Masked string like "abcd****xyz"
    """
    if not value:
        return "[empty]"
    
    if len(value) <= visible_chars * 2:
        # Too short to mask meaningfully
        return "*" * len(value)
    
    return f"{value[:visible_chars]}{'*' * (len(value) - visible_chars * 2)}{value[-visible_chars:]}"


def _looks_like_secret(value: str) -> bool:
    """Check if a string looks like a secret/key/token.
    
    Args:
        value: The string to check
        
    Returns:
        True if the string resembles a secret
    """
    # Long hex strings (likely API keys, tokens)
    if len(value) >= 32 and re.match(r'^[a-fA-F0-9]+$', value):
        return True
    
    # Base64-like strings
    if len(value) >= 20 and re.match(r'^[A-Za-z0-9+/=]+$', value):
        return True
    
    # Strings with common secret patterns
    if re.search(r'[_-](key|token|secret|auth)[_-]?', value, re.IGNORECASE):
        return True
    
    return False


def sanitize_dict_for_logging(data: Dict[str, Any]) -> Dict[str, str]:
    """Sanitize a dictionary by masking sensitive values.
    
    Args:
        data: Dictionary to sanitize
        
    Returns:
        Dictionary with sensitive values masked
    """
    sanitized = {}
    for key, value in data.items():
        if is_sensitive_field(key):
            sanitized[key] = mask_sensitive_string(str(value) if value else "")
        else:
            sanitized[key] = str(value)
    return sanitized


def get_secret(env_var: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Get a secret from environment variables with validation.
    
    Args:
        env_var: Environment variable name
        default: Default value if not set
        required: If True, raise ValueError when not set
        
    Returns:
        The secret value or default
        
    Raises:
        ValueError: If required=True and value not set
    """
    value = os.getenv(env_var, default)
    
    if required and not value:
        raise ValueError(f"Required environment variable {env_var} is not set")
    
    return value


class SecretString:
    """A string that masks itself when converted to string representation.
    
    Use this for storing sensitive values that should not be logged.
    """
    
    def __init__(self, value: str):
        self._value = value
    
    def get_value(self) -> str:
        """Get the actual secret value."""
        return self._value
    
    def __str__(self) -> str:
        return mask_sensitive_string(self._value)
    
    def __repr__(self) -> str:
        return f"<SecretString: {mask_sensitive_string(self._value)}>"
    
    def __eq__(self, other) -> bool:
        if isinstance(other, SecretString):
            return self._value == other._value
        return self._value == other
    
    def __hash__(self) -> int:
        return hash(self._value)


@lru_cache(maxsize=128)
def get_cached_secret(env_var: str, default: Optional[str] = None) -> Optional[str]:
    """Get a secret from environment with caching (for performance).
    
    Args:
        env_var: Environment variable name
        default: Default value if not set
        
    Returns:
        The secret value or default
    """
    return os.getenv(env_var, default)


def validate_environment_secrets(required_vars: Set[str]) -> Dict[str, bool]:
    """Validate that required environment variables are set.
    
    Args:
        required_vars: Set of required environment variable names
        
    Returns:
        Dictionary mapping var names to whether they are set
    """
    results = {}
    for var in required_vars:
        results[var] = bool(os.getenv(var))
    return results
