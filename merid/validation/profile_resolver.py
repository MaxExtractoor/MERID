"""
15m Profile Resolver - Validates and resolves profile configuration for 15m_live mode.

This module enforces the configuration hierarchy for the kalshi_crypto_15m_v2 profile
and prevents accidental use of incompatible or deprecated profiles.
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Allowed profiles for 15m_live mode
ALLOWED_15M_PROFILES = {
    "kalshi_crypto_15m_v2",
}

# Forbidden profiles (test-only, deprecated, or incompatible)
FORBIDDEN_PROFILES = set()  # No forbidden profiles currently

# Required config files for 15m_live mode
REQUIRED_CONFIG_FILES = {
    "config/profiles/kalshi_crypto_15m_v2.yaml",
    "config/kalshi_agent_grid.yaml",
    "config/kalshi_universe.py",
}

# Deprecated config modules (should not be imported in 15m_live mode)
# Note: config.kalshi_15m_crypto_config contains both deprecated risk limits
# and valid universe constants. The universe constants (KALSHI_15M_SERIES_TICKERS,
# KALSHI_15M_CRYPTO_ASSETS) are still valid and used by kalshi_universe.py.
# Only the risk-related parts (ASSET_RISK_LIMITS, GLOBAL_RISK_LIMITS) are deprecated.
# Therefore, we do NOT flag config.kalshi_15m_crypto_config as deprecated.
DEPRECATED_CONFIG_MODULES = {
    "merid.prediction.risk.kalshi_risk_engine",  # Use venue config instead
}


def validate_15m_profile(profile: str, runtime_mode: str) -> None:
    """
    Validate that the profile is allowed for the given runtime mode.
    
    Args:
        profile: The MERID_PROFILE value
        runtime_mode: The MERID_RUNTIME_MODE value
        
    Raises:
        ValueError: If profile is invalid for the runtime mode
    """
    if runtime_mode != "15m_live":
        # No validation for other modes
        return
    
    if not profile:
        raise ValueError(
            "[PROFILE-VALIDATION] MERID_PROFILE must be set in 15m_live mode. "
            f"Expected one of: {ALLOWED_15M_PROFILES}"
        )
    
    if profile in FORBIDDEN_PROFILES:
        raise ValueError(
            f"[PROFILE-VALIDATION] Profile '{profile}' is forbidden in 15m_live mode. "
            f"This is a test-only or deprecated profile. "
            f"Use 'kalshi_crypto_15m_v2' instead."
        )
    
    if profile not in ALLOWED_15M_PROFILES:
        raise ValueError(
            f"[PROFILE-VALIDATION] Profile '{profile}' is not allowed in 15m_live mode. "
            f"Allowed profiles: {ALLOWED_15M_PROFILES}. "
            f"For 15m crypto trading, use 'kalshi_crypto_15m_v2'."
        )
    
    logger.info(f"[PROFILE-VALIDATION] Profile '{profile}' validated for 15m_live mode")


def validate_required_config_files(base_path: str) -> None:
    """
    Validate that all required config files exist.
    
    Args:
        base_path: Base path to the MERID repository
        
    Raises:
        FileNotFoundError: If any required config file is missing
    """
    missing_files = []
    
    for config_file in REQUIRED_CONFIG_FILES:
        full_path = Path(base_path) / config_file
        if not full_path.exists():
            missing_files.append(str(full_path))
    
    if missing_files:
        raise FileNotFoundError(
            f"[CONFIG-VALIDATION] Required config files missing: {missing_files}. "
            f"15m_live mode requires all config files to be present."
        )
    
    logger.info(f"[CONFIG-VALIDATION] All required config files present ({len(REQUIRED_CONFIG_FILES)} files)")


def check_deprecated_modules_imported() -> None:
    """
    Check if any deprecated config modules have been imported.
    
    This is a runtime guard to prevent accidental use of deprecated config sources.
    
    Raises:
        RuntimeError: If deprecated modules are imported
    """
    import sys
    
    imported_deprecated = []
    
    for module_name in DEPRECATED_CONFIG_MODULES:
        if module_name in sys.modules:
            imported_deprecated.append(module_name)
    
    if imported_deprecated:
        raise RuntimeError(
            f"[IMPORT-VALIDATION] Deprecated modules imported in 15m_live mode: {imported_deprecated}. "
            f"These modules are superseded by kalshi_crypto_15m.yaml profile. "
            f"Remove imports from 15m code paths."
        )
    
    logger.info("[IMPORT-VALIDATION] No deprecated config modules imported")


def resolve_15m_profile_config(profile: str, base_path: str) -> dict:
    """
    Resolve and load the 15m profile configuration.
    
    Args:
        profile: The MERID_PROFILE value
        base_path: Base path to the MERID repository
        
    Returns:
        dict: The loaded profile configuration
        
    Raises:
        ValueError: If profile validation fails
        FileNotFoundError: If config files are missing
    """
    runtime_mode = os.getenv("MERID_RUNTIME_MODE", "")
    
    # Validate profile
    validate_15m_profile(profile, runtime_mode)
    
    # Validate config files exist
    validate_required_config_files(base_path)
    
    # Check for deprecated imports
    check_deprecated_modules_imported()
    
    # Load profile config (implementation would use actual YAML loader)
    # This is a placeholder - actual implementation would load kalshi_crypto_15m.yaml
    profile_config = {
        "profile": profile,
        "runtime_mode": runtime_mode,
        "config_loaded": True,
    }
    
    logger.info(f"[PROFILE-RESOLVER] Resolved profile '{profile}' for 15m_live mode")
    
    return profile_config


def get_15m_allowed_series_tickers() -> set:
    """
    Get the allowed series tickers for 15m crypto trading.
    
    Returns:
        set: Set of allowed series tickers (5 crypto 15M series)
    """
    return {
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M",
    }


def validate_series_ticker(series_ticker: str) -> bool:
    """
    Validate that a series ticker is allowed for 15m crypto trading.
    
    Args:
        series_ticker: The series ticker to validate
        
    Returns:
        bool: True if allowed, False otherwise
    """
    allowed = get_15m_allowed_series_tickers()
    is_allowed = series_ticker in allowed
    
    if not is_allowed:
        logger.warning(
            f"[SERIES-VALIDATION] Series ticker '{series_ticker}' is not allowed for 15m crypto trading. "
            f"Allowed tickers: {allowed}"
        )
    
    return is_allowed
