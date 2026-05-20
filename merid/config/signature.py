"""Config signature utility for Kalshi 15m crypto.

Computes a stable hash of the canonical Kalshi 15m config (YAML + series universe)
to detect config changes and ensure configuration integrity.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("merid.config.signature")


def load_kalshi_15m_config() -> Dict[str, Any]:
    """Load the canonical Kalshi 15m config from YAML.
    
    Returns:
        Dict containing the parsed YAML config
    """
    try:
        import yaml
        
        config_path = Path("config/profiles/kalshi_crypto_15m.yaml")
        if not config_path.exists():
            config_path = Path("config/kalshi_crypto_15m.yaml")
        
        if not config_path.exists():
            logger.warning(f"Kalshi 15m config file not found at {config_path}")
            return {}
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        logger.info(f"Loaded Kalshi 15m config from {config_path}")
        return config or {}
    except Exception as e:
        logger.error(f"Failed to load Kalshi 15m config: {e}")
        return {}


def load_kalshi_15m_series_universe() -> Dict[str, Any]:
    """Load the Kalshi 15m series universe configuration.
    
    Returns:
        Dict containing the series universe config
    """
    try:
        from config.kalshi_15m_crypto_config import (
            KALSHI_15M_SERIES_TICKERS,
            KALSHI_15M_CRYPTO_ASSETS,
        )
        
        universe = {
            "series_tickers": KALSHI_15M_SERIES_TICKERS,
            "crypto_assets": KALSHI_15M_CRYPTO_ASSETS,
        }
        
        logger.info("Loaded Kalshi 15m series universe from kalshi_15m_crypto_config")
        return universe
    except Exception as e:
        logger.error(f"Failed to load Kalshi 15m series universe: {e}")
        return {}


def compute_config_signature(config: Dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash of a config dictionary.
    
    Args:
        config: Dictionary containing configuration data
        
    Returns:
        SHA-256 hash as a hexadecimal string
    """
    if not config:
        return hashlib.sha256(b"{}").hexdigest()
    
    # Sort keys and convert to JSON for stable hashing
    config_json = json.dumps(config, sort_keys=True, default=str)
    signature = hashlib.sha256(config_json.encode()).hexdigest()
    
    return signature


def get_kalshi_15m_config_signature() -> str:
    """Compute the signature of the canonical Kalshi 15m config.
    
    This combines the YAML config and series universe into a single signature
    that can be used to detect config changes.
    
    Returns:
        SHA-256 signature of the combined Kalshi 15m config
    """
    config = load_kalshi_15m_config()
    universe = load_kalshi_15m_series_universe()
    
    combined_config = {
        "yaml_config": config,
        "series_universe": universe,
    }
    
    signature = compute_config_signature(combined_config)
    logger.info(f"Kalshi 15m config signature: {signature[:16]}...")
    
    return signature


def emit_config_signature_metric() -> None:
    """Emit the Kalshi 15m config signature as a metric.
    
    This can be called during startup to log the config signature
    for monitoring and change detection.
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    if profile != "kalshi_crypto_15m_v2":
        return  # Only emit for kalshi_crypto_15m_v2 profile
    
    signature = get_kalshi_15m_config_signature()
    
    # Log the signature
    logger.info("=" * 80)
    logger.info("🔐 KALSHI 15M CONFIG SIGNATURE")
    logger.info("=" * 80)
    logger.info(f"Profile: kalshi_crypto_15m_v2")
    logger.info(f"Config Signature: {signature}")
    logger.info("=" * 80)
    
    # TODO: Emit as Prometheus metric when metrics system is available
    # Example: kalshi_config_signature{profile="kalshi_crypto_15m_v2"} signature


def verify_config_signature() -> bool:
    """Verify that the config signature matches expected value (if set).
    
    This can be used in CI/CD to ensure config hasn't drifted.
    
    Returns:
        True if signature verification passed (or no expected signature set)
        False if signature doesn't match expected value
    """
    current_signature = get_kalshi_15m_config_signature()
    expected_signature = os.getenv("KALSHI_15M_CONFIG_SIGNATURE", "")
    
    if not expected_signature:
        logger.info("No expected config signature set, skipping verification")
        return True
    
    if current_signature == expected_signature:
        logger.info("Config signature matches expected value")
        return True
    else:
        logger.error(
            f"Config signature mismatch! "
            f"Expected: {expected_signature}, "
            f"Current: {current_signature}"
        )
        return False
