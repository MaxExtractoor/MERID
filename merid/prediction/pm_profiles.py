"""PM strategy profiles (MERID_PM_PROFILE) — DEPRECATED for kalshi_crypto_15m_v2.

For kalshi_crypto_15m_v2 profile, edge thresholds come from config/profiles/kalshi_crypto_15m.yaml.
This module is a minimal stub to support legacy tests and non-15m profiles.

Full PM profile logic has been moved to archive/legacy/pm_profiles.py.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.pm_profiles")


def get_pm_profile_strategy_overrides(profile_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get strategy overrides from PM profile YAML.
    
    NOTE: For kalshi_crypto_15m_v2, edge thresholds come from kalshi_crypto_15m.yaml.
    PM profile is used for other profiles (baseline, production, crypto_low_edge_dev).
    
    Returns empty dict for kalshi_crypto_15m_v2 (profile YAML is single source of truth).
    """
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        logger.debug("PM profile not used for kalshi_crypto_15m_v2 (uses profile YAML edge thresholds)")
        return {}
    
    # For non-15m profiles, this stub returns empty dict.
    # Full implementation is in archive/legacy/pm_profiles.py if needed.
    name = (profile_name or os.getenv("MERID_PM_PROFILE") or "").strip()
    if not name:
        return {}
    
    logger.warning("PM profile %r requested but full implementation is archived. Returns empty dict.", name)
    result = {}
    
    # DEFENSIVE ASSERTION: If somehow non-empty data is returned for kalshi_crypto_15m_v2, log ERROR
    if merid_profile == "kalshi_crypto_15m_v2" and result:
        logger.error(
            "CRITICAL: Non-empty PM profile data returned for kalshi_crypto_15m_v2. "
            "This violates single-source-of-truth. Profile YAML should be the only source. "
            "PM profile name: %r, Data: %r. Ignoring PM profile data.",
            name, result
        )
        return {}
    
    return result
