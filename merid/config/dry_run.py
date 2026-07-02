"""Dry-run mode utility for Kalshi 15m crypto.

Provides dry-run mode checking for sandbox/dry-run operations.
When dry-run is enabled, orders are logged but NOT submitted to Kalshi API.
"""

import os
from typing import Optional
import yaml
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("merid.config.dry_run")


def get_kalshi_15m_dry_run() -> bool:
    """Check if Kalshi 15m dry-run mode is enabled.
    
    Reads the dry_run flag from the active profile config (e.g., kalshi_crypto_15m_v2.yaml).
    
    Returns:
        True if dry-run mode is enabled, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    # Only check dry_run for kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        return False
    
    try:
        # 2026 FIX: Read from the ACTIVE profile file, not the legacy v1 file.
        # Previous implementation read kalshi_crypto_15m.yaml (v1) even when the
        # active profile was kalshi_crypto_15m_v2, causing legacy contamination.
        config_path = Path(f"config/profiles/{os.getenv('MERID_PROFILE', 'kalshi_crypto_15m_v2')}.yaml")
        
        if not config_path.exists():
            logger.warning(f"Kalshi 15m config file not found at {config_path}, defaulting dry_run=False")
            return False
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        dry_run = config.get("dry_run", False)
        
        if dry_run:
            logger.info("🧪 DRY-RUN MODE ENABLED - Orders will be logged but NOT submitted to Kalshi API")
        else:
            logger.info("🚀 LIVE MODE - Orders will be submitted to Kalshi API")
        
        return dry_run
    except Exception as e:
        logger.error(f"Failed to read dry_run flag from config: {e}, defaulting to False")
        return False


def is_dry_run_enabled() -> bool:
    """Convenience alias for get_kalshi_15m_dry_run().
    
    Returns:
        True if dry-run mode is enabled, False otherwise
    """
    return get_kalshi_15m_dry_run()


def log_dry_run_order(order_intent: dict) -> None:
    """Log an order that would be submitted in dry-run mode.
    
    Args:
        order_intent: Dictionary containing order details (ticker, side, action, price, count)
    """
    logger.info(
        f"[DRY-RUN] Order NOT submitted (dry-run mode enabled): "
        f"ticker={order_intent.get('ticker')}, "
        f"side={order_intent.get('side')}, "
        f"action={order_intent.get('action')}, "
        f"price_cents={order_intent.get('price_cents')}, "
        f"count={order_intent.get('count')}"
    )
