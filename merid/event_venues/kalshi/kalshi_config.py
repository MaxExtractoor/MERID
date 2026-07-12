"""
Unified Kalshi Configuration

Single source of truth for environment, URLs, and authentication credentials.
Used by both REST client (client_v2.py) and WebSocket bridge (ws_bridge.py).

This eliminates config drift between components and ensures both use identical
credentials for the same environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.kalshi_config")

# Global flag for Kalshi readiness - set by verify_kalshi_config()
KALSHI_READY = False


@dataclass
class KalshiConfig:
    """Unified Kalshi configuration for a specific environment."""
    
    env: str  # "prod" or "demo"
    rest_base_url: str
    ws_base_url: str
    api_key_id: str
    private_key_path: str
    public_rest_api_url: Optional[str] = None  # Public API URL for market discovery
    private_key_pem: Optional[str] = None  # Alternative to file path
    
    def __repr__(self) -> str:
        masked_key = self.api_key_id[:4] + "****" + self.api_key_id[-4:] if len(self.api_key_id) > 8 else "****"
        return f"KalshiConfig(env={self.env}, key={masked_key}, rest={self.rest_base_url}, ws={self.ws_base_url})"


# Environment-specific URLs per Kalshi docs
# CRITICAL FIX: 2026-07-07 - Use elections API endpoints for crypto markets
# The external-api endpoints do not support elections markets (crypto 15m)
# Elections API is the correct endpoint for KXBTC15M, KXETH15M, etc.
_ENV_CONFIGS = {
    "prod": {
        "rest_base_url": "https://api.elections.kalshi.com/trade-api/v2",
        "ws_base_url": "wss://api.elections.kalshi.com/trade-api/ws/v2",
        "public_rest_api_url": "https://api.elections.kalshi.com/trade-api/v2",
    },
    "demo": {
        "rest_base_url": "https://demo-api.kalshi.co/trade-api/v2",
        "ws_base_url": "wss://demo-api.kalshi.co/trade-api/ws/v2",
        "public_rest_api_url": "https://demo-api.kalshi.co/trade-api/v2",
    },
}


def get_kalshi_env() -> str:
    """
    Get Kalshi environment from environment variables.
    
    Priority:
    1. MERID_KALSHI_ENV
    2. KALSHI_ENV
    3. Default to "prod"
    
    Returns:
        "prod" or "demo"
    """
    env = os.getenv("MERID_KALSHI_ENV", "").lower()
    if not env:
        env = os.getenv("KALSHI_ENV", "").lower()
    if not env:
        env = "prod"
    
    # Normalize to valid values
    # Accept both "live" (legacy MERID convention) and "prod" (Kalshi docs standard)
    if env == "live":
        env = "prod"
    
    if env not in ["prod", "demo"]:
        logger.warning(f"[KALSHI-CONFIG] Invalid env '{env}', defaulting to 'prod'")
        env = "prod"
    
    return env


def get_kalshi_config(env: Optional[str] = None) -> KalshiConfig:
    """
    Get unified Kalshi configuration for the specified environment.
    
    Args:
        env: Optional environment override ("prod" or "demo"). If None, uses
             environment variables.
    
    Returns:
        KalshiConfig with URLs and credentials for the environment.
    
    Raises:
        ValueError: If required credentials are missing.
    """
    if env is None:
        env = get_kalshi_env()
    
    if env not in _ENV_CONFIGS:
        raise ValueError(f"Invalid environment: {env}. Must be 'prod' or 'demo'.")
    
    urls = _ENV_CONFIGS[env]
    
    # CRITICAL FIX: Respect MERID_KALSHI_HTTP_BASE and MERID_KALSHI_WS_BASE environment variables
    # if they are set (override hardcoded _ENV_CONFIGS)
    rest_base_url = os.getenv("MERID_KALSHI_HTTP_BASE") or urls["rest_base_url"]
    ws_base_url = os.getenv("MERID_KALSHI_WS_BASE") or urls["ws_base_url"]
    
    # Log if using overridden endpoints
    if os.getenv("MERID_KALSHI_HTTP_BASE"):
        logger.info(f"[KALSHI-CONFIG] Using overridden REST endpoint: {rest_base_url}")
    if os.getenv("MERID_KALSHI_WS_BASE"):
        logger.info(f"[KALSHI-CONFIG] Using overridden WS endpoint: {ws_base_url}")
    
    # Get credentials with environment-specific fallbacks
    # Priority: env-specific vars -> generic vars
    if env == "prod":
        api_key_id = (
            os.getenv("KALSHI_LIVE_API_KEY_ID") or
            os.getenv("KALSHI_API_KEY_ID") or
            ""
        )
        private_key_path = (
            os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH") or
            os.getenv("KALSHI_PRIVATE_KEY_PATH") or
            ""
        )
        private_key_pem = (
            os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM") or
            os.getenv("KALSHI_PRIVATE_KEY_PEM") or
            None
        )
    else:  # demo
        api_key_id = (
            os.getenv("KALSHI_DEMO_API_KEY_ID") or
            os.getenv("KALSHI_API_KEY_ID") or
            ""
        )
        private_key_path = (
            os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH") or
            os.getenv("KALSHI_PRIVATE_KEY_PATH") or
            ""
        )
        private_key_pem = (
            os.getenv("KALSHI_DEMO_PRIVATE_KEY_PEM") or
            os.getenv("KALSHI_PRIVATE_KEY_PEM") or
            None
        )
    
    # Validate required fields
    if not api_key_id:
        raise ValueError(
            f"KALSHI_API_KEY_ID not set for environment '{env}'. "
            f"Set KALSHI_{'LIVE' if env == 'prod' else 'DEMO'}_API_KEY_ID or KALSHI_API_KEY_ID."
        )
    
    if not private_key_path and not private_key_pem:
        raise ValueError(
            f"KALSHI_PRIVATE_KEY_PATH not set for environment '{env}'. "
            f"Set KALSHI_{'LIVE' if env == 'prod' else 'DEMO'}_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PATH."
        )
    
    config = KalshiConfig(
        env=env,
        rest_base_url=rest_base_url,
        ws_base_url=ws_base_url,
        api_key_id=api_key_id,
        private_key_path=private_key_path,
        private_key_pem=private_key_pem,
        public_rest_api_url=urls.get("public_rest_api_url"),
    )
    
    logger.info(f"[KALSHI-CONFIG] Loaded config: {config}")
    return config


def build_auth_message(timestamp_ms: str, method: str, path: str) -> str:
    """
    Build the authentication message string for signing.
    
    Both REST and WS use the same message format per Kalshi docs:
    timestamp + method.upper() + path
    
    Args:
        timestamp_ms: Timestamp in milliseconds (as string)
        method: HTTP method (e.g., "GET", "POST")
        path: API path (e.g., "/trade-api/v2/portfolio/balance" or "/trade-api/ws/v2")
    
    Returns:
        Message string to be signed
    """
    return timestamp_ms + method.upper() + path


def log_auth_debug(
    component: str,
    config: KalshiConfig,
    method: str,
    path: str,
    timestamp_ms: str,
    message: str,
    signature_length: int,
) -> None:
    """
    Log authentication debug information for side-by-side comparison.
    
    Args:
        component: "REST" or "WS"
        config: KalshiConfig instance
        method: HTTP method
        path: API path
        timestamp_ms: Timestamp used
        message: Message that was signed
        signature_length: Length of signature in bytes
    """
    masked_key = config.api_key_id[:4] + "****" + config.api_key_id[-4:] if len(config.api_key_id) > 8 else "****"
    
    logger.info(
        f"[AUTH-{component}] env={config.env} "
        f"key={masked_key} "
        f"method={method} "
        f"path={path} "
        f"timestamp={timestamp_ms} "
        f"message='{message}' "
        f"signature_length={signature_length}"
    )


def verify_kalshi_config() -> tuple[bool, str, KalshiConfig]:
    """
    Verify Kalshi configuration is properly set up.
    
    This function checks:
    1. Environment variables are set
    2. Config can be loaded
    3. Key file exists (if using file path)
    
    Sets global KALSHI_READY flag based on validation result.
    
    Returns:
        Tuple of (is_valid, error_message, config)
        - is_valid: True if config is valid
        - error_message: Error message if invalid, empty string if valid
        - config: KalshiConfig instance if valid, None otherwise
    """
    global KALSHI_READY
    logger.info("[KALSHI-CONFIG-VERIFY] Starting configuration verification")
    
    # Check environment variables
    env = get_kalshi_env()
    logger.info(f"[KALSHI-CONFIG-VERIFY] Environment: {env}")
    
    # Log which env vars are set
    env_vars_to_check = [
        "MERID_KALSHI_ENV",
        "KALSHI_ENV",
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PATH",
        "KALSHI_PRIVATE_KEY_PEM",
    ]
    
    if env == "prod":
        env_vars_to_check.extend([
            "KALSHI_LIVE_API_KEY_ID",
            "KALSHI_LIVE_PRIVATE_KEY_PATH",
            "KALSHI_LIVE_PRIVATE_KEY_PEM",
        ])
    else:
        env_vars_to_check.extend([
            "KALSHI_DEMO_API_KEY_ID",
            "KALSHI_DEMO_PRIVATE_KEY_PATH",
            "KALSHI_DEMO_PRIVATE_KEY_PEM",
        ])
    
    for var in env_vars_to_check:
        value = os.getenv(var)
        if value:
            masked_value = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
            logger.info(f"[KALSHI-CONFIG-VERIFY] {var}={masked_value}")
        else:
            logger.debug(f"[KALSHI-CONFIG-VERIFY] {var}=NOT_SET")
    
    # Try to load config
    try:
        config = get_kalshi_config()
        logger.info(f"[KALSHI-CONFIG-VERIFY] Config loaded successfully: {config}")
        
        # Check if key file exists
        if config.private_key_path and not config.private_key_pem:
            if os.path.exists(config.private_key_path):
                logger.info(f"[KALSHI-CONFIG-VERIFY] Key file exists: {config.private_key_path}")
            else:
                error_msg = f"Key file not found: {config.private_key_path}"
                logger.error(f"[KALSHI-CONFIG-VERIFY] {error_msg}")
                KALSHI_READY = False
                return False, error_msg, config
        
        # Config is valid - set global flag
        KALSHI_READY = True
        logger.info("[KALSHI-CONFIG-VERIFY] Configuration valid - KALSHI_READY=True")
        return True, "", config
        
    except ValueError as e:
        error_msg = f"Config validation failed: {e}"
        logger.error(f"[KALSHI-CONFIG-VERIFY] {error_msg}")
        KALSHI_READY = False
        return False, error_msg, None
    except Exception as e:
        error_msg = f"Unexpected error loading config: {e}"
        logger.error(f"[KALSHI-CONFIG-VERIFY] {error_msg}")
        KALSHI_READY = False
        return False, error_msg, None


# DISABLED: Auto-verify config at module import time
# This was causing config to be loaded before environment variables were set by the startup script
# The config should be loaded explicitly after environment variables are set
# Call verify_kalshi_config() explicitly after loading .env in the web server startup.
