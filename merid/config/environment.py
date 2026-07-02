"""
Environment Configuration

Explicit environment separation for MERID trading system.
This module provides the single source of truth for environment detection
and enforces strict separation between dev, staging, and prod behavior.

Usage:
    from merid.config.environment import current_env, Env, require_prod_ready_config

    env = current_env()
    if env is Env.PROD:
        require_prod_ready_config()
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Literal
from utils.logger import get_logger

logger = get_logger("merid.config.environment")


class Env(Enum):
    """Environment enumeration for explicit mode separation."""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

    def __str__(self) -> str:
        return self.value


def current_env() -> Env:
    """
    Get the current environment from environment variables.

    Priority:
    1. MERID_ENV
    2. Default to "dev"

    Returns:
        Current environment as Env enum.

    Raises:
        ValueError: If MERID_ENV is set to an invalid value.
    """
    value = os.getenv("MERID_ENV", "dev").lower()
    
    # Map common aliases
    if value in ("production", "live"):
        value = "prod"
    elif value in ("development",):
        value = "dev"
    
    try:
        return Env(value)
    except ValueError:
        valid_values = [e.value for e in Env]
        raise ValueError(
            f"Invalid MERID_ENV '{value}'. Must be one of: {valid_values}"
        )


def require_prod_ready_config() -> None:
    """
    Enforce production-ready configuration.

    This function checks that all required configuration is present
    for production trading. If any required config is missing,
    it raises a RuntimeError to prevent the process from starting.

    Must be called early in the main entrypoint before spinning up
    the event loop or schedulers.

    Raises:
        RuntimeError: If running in PROD mode with missing required config.
    """
    env = current_env()
    
    if env is not Env.PROD:
        logger.info(f"[ENV-CHECK] Skipping prod config checks in {env} mode")
        return
    
    logger.info("[ENV-CHECK] Enforcing production-ready configuration")
    
    # Check Kalshi API credentials
    kalshi_key_id = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_LIVE_API_KEY_ID")
    if not kalshi_key_id:
        raise RuntimeError(
            "Missing KALSHI_API_KEY_ID or KALSHI_LIVE_API_KEY_ID in PROD mode. "
            "Production trading requires valid Kalshi API credentials."
        )
    
    kalshi_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH") or os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
    kalshi_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM") or os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM")
    
    if not kalshi_key_path and not kalshi_key_pem:
        raise RuntimeError(
            "Missing KALSHI_PRIVATE_KEY_PATH or KALSHI_LIVE_PRIVATE_KEY_PATH "
            "(or PEM equivalent) in PROD mode. "
            "Production trading requires valid Kalshi private key."
        )
    
    # Check environment is explicitly set to prod
    kalshi_env = os.getenv("KALSHI_ENV", "").lower()
    if kalshi_env not in ("prod", "live"):
        raise RuntimeError(
            f"KALSHI_ENV must be 'prod' or 'live' in PROD mode, got '{kalshi_env}'. "
            "Production trading must use production Kalshi environment."
        )
    
    logger.info("[ENV-CHECK] Production configuration validated successfully")


def log_environment_startup() -> None:
    """
    Log environment and key configuration at startup.

    This should be called early in the main entrypoint to make the
    runtime environment obvious in logs.
    """
    env = current_env()
    
    logger.info("=" * 60)
    logger.info(f"[STARTUP] MERID Environment: {env.value.upper()}")
    logger.info(f"[STARTUP] MERID_ENV={os.getenv('MERID_ENV', 'not set')}")
    logger.info(f"[STARTUP] KALSHI_ENV={os.getenv('KALSHI_ENV', 'not set')}")
    logger.info(f"[STARTUP] MERID_RUNTIME_MODE={os.getenv('MERID_RUNTIME_MODE', 'not set')}")
    logger.info("=" * 60)


# Feature flags controlled by environment
def enable_composite_spot_fallback() -> bool:
    """
    Whether composite spot fallback is enabled.
    
    In PROD, this must be False to ensure only unified spot is used.
    In DEV/STAGING, this can be True for testing.
    """
    return current_env() is not Env.PROD


def enable_legacy_fallbacks() -> bool:
    """
    Whether legacy fallback paths are enabled.
    
    In PROD, this must be False to prevent silent degradation.
    In DEV/STAGING, this can be True for testing.
    """
    return current_env() is not Env.PROD


def enable_synthetic_data() -> bool:
    """
    Whether synthetic data generation is allowed.
    
    In PROD, this must be False to prevent trading on fake data.
    In DEV/STAGING, this can be True for testing.
    """
    return current_env() is not Env.PROD
