"""
MERID Shared Constants Module

Central repository for commonly used constants across the codebase.
Most values now derive from merid.settings for bankroll-driven configuration.
"""

from __future__ import annotations

from merid.settings import settings

# =============================================================================
# TIMEOUTS AND RETRIES (from settings, with fallbacks)
# =============================================================================
DEFAULT_TIMEOUT = getattr(settings, 'KALSHI_DEFAULT_TIMEOUT', 30.0)  # seconds
MAX_RETRIES = getattr(settings, 'KALSHI_MAX_RETRIES', 3)
RETRY_DELAY = getattr(settings, 'KALSHI_RETRY_DELAY', 1.0)  # seconds
BATCH_SIZE = getattr(settings, 'KALSHI_BATCH_SIZE', 100)
SLEEP_INTERVAL = getattr(settings, 'KALSHI_SLEEP_INTERVAL', 5.0)

# =============================================================================
# TRADING CONSTANTS (bankroll-derived from settings)
# =============================================================================
DEFAULT_ORDER_SIZE = getattr(settings, 'KALSHI_DEFAULT_ORDER_SIZE', 10.0)
MAX_ORDER_SIZE = getattr(settings, 'MERID_MAX_ORDER_SIZE_USD', 10000.0)
MIN_ORDER_SIZE = getattr(settings, 'KALSHI_MIN_ORDER_SIZE', 1.0)

# =============================================================================
# KALSHI SPECIFIC (from settings)
# =============================================================================
KALSHI_FEE_BPS = getattr(settings, 'KALSHI_FEE_BPS', 5)  # 5 basis points
KALSHI_MAX_POSITION_SIZE = getattr(settings, 'MERID_MAX_POSITION_SIZE_USD', 1000.0)

# =============================================================================
# MONITORING CONSTANTS (from settings)
# =============================================================================
HEALTH_CHECK_INTERVAL = getattr(settings, 'KALSHI_HEALTH_CHECK_INTERVAL', 60.0)  # seconds
METRICS_COLLECTION_INTERVAL = getattr(settings, 'KALSHI_METRICS_INTERVAL', 30.0)  # seconds

# =============================================================================
# LEGACY SCRIPT CONSTANTS (for backward compatibility)
# =============================================================================
# These are kept for legacy scripts but should be phased out
VOLUME_TARGET = 1000.0
EPS = 0.01
MIN_EFFECTIVE = 0.05
LATENCY_GATE = 100.0  # ms
RELIABILITY_GATE = 0.99
ROI_GATE = 0.10
SLO_GATE = 0.95
PLAYBOOK_PATH = "playbooks/"

__all__ = [
    # Timeouts and retries
    "DEFAULT_TIMEOUT",
    "MAX_RETRIES", 
    "RETRY_DELAY",
    "BATCH_SIZE",
    "SLEEP_INTERVAL",
    
    # Trading
    "DEFAULT_ORDER_SIZE",
    "MAX_ORDER_SIZE",
    "MIN_ORDER_SIZE",
    
    # Kalshi
    "KALSHI_FEE_BPS",
    "KALSHI_MAX_POSITION_SIZE",
    
    # Monitoring
    "HEALTH_CHECK_INTERVAL",
    "METRICS_COLLECTION_INTERVAL",
    
    # Legacy (to be deprecated)
    "VOLUME_TARGET",
    "EPS",
    "MIN_EFFECTIVE",
    "LATENCY_GATE",
    "RELIABILITY_GATE",
    "ROI_GATE",
    "SLO_GATE",
    "PLAYBOOK_PATH",
]
