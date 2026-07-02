"""
Profile resolver - Central authority for determining the current MERID profile.

This module provides a single source of truth for profile detection and
profile-specific behavior gating.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("profile_resolver")


# Known profiles
PROFILE_KALSHI_CRYPTO_15M_V2 = "kalshi_crypto_15m_v2"
PROFILE_KALSHI_CRYPTO_15M = "kalshi_crypto_15m"
PROFILE_KALSHI_PM_LIVE = "kalshi-pm-live"
PROFILE_BASELINE = "baseline"

PRODUCTION_PROFILES = {
    PROFILE_KALSHI_CRYPTO_15M_V2,
    PROFILE_KALSHI_CRYPTO_15M,
    PROFILE_KALSHI_PM_LIVE,
}


def get_profile() -> str:
    """
    Get the current MERID profile from environment.
    
    Returns:
        The profile name (e.g., "kalshi_crypto_15m_v2")
    
    Raises:
        RuntimeError: If MERID_PROFILE is not set
    """
    profile = os.environ.get("MERID_PROFILE")
    
    if not profile:
        raise RuntimeError(
            "MERID_PROFILE environment variable is not set. "
            "This is required for all MERID operations."
        )
    
    return profile


def is_profile(profile_name: str) -> bool:
    """
    Check if the current profile matches the given name.
    
    Args:
        profile_name: The profile name to check against
    
    Returns:
        True if current profile matches, False otherwise
    """
    try:
        current = get_profile()
        return current == profile_name
    except RuntimeError:
        return False


def is_production_profile() -> bool:
    """
    Check if the current profile is a production profile.
    
    Returns:
        True if current profile is in PRODUCTION_PROFILES set
    """
    try:
        current = get_profile()
        return current in PRODUCTION_PROFILES
    except RuntimeError:
        return False


def is_kalshi_crypto_15m_v2() -> bool:
    """
    Check if the current profile is kalshi_crypto_15m_v2.
    
    Returns:
        True if profile is kalshi_crypto_15m_v2
    """
    return is_profile(PROFILE_KALSHI_CRYPTO_15M_V2)


def require_profile(expected_profile: str, context: str = "") -> None:
    """
    Require that the current profile matches the expected profile.
    
    Args:
        expected_profile: The profile that is required
        context: Additional context for error message
    
    Raises:
        RuntimeError: If current profile does not match expected
    """
    current = get_profile()
    
    if current != expected_profile:
        error_msg = (
            f"Profile mismatch: expected '{expected_profile}' but got '{current}'"
        )
        if context:
            error_msg += f" (context: {context})"
        
        logger.error(f"[PROFILE-GUARD] {error_msg}")
        raise RuntimeError(error_msg)


def forbid_profile(forbidden_profile: str, context: str = "") -> None:
    """
    Forbid execution under a specific profile.
    
    Args:
        forbidden_profile: The profile that is not allowed
        context: Additional context for error message
    
    Raises:
        RuntimeError: If current profile matches forbidden profile
    """
    current = get_profile()
    
    if current == forbidden_profile:
        error_msg = (
            f"Operation not allowed under profile '{forbidden_profile}'"
        )
        if context:
            error_msg += f" (context: {context})"
        
        logger.error(f"[PROFILE-GUARD] {error_msg}")
        raise RuntimeError(error_msg)


def allow_only_profiles(allowed_profiles: set, context: str = "") -> None:
    """
    Allow execution only under specific profiles.
    
    Args:
        allowed_profiles: Set of profile names that are allowed
        context: Additional context for error message
    
    Raises:
        RuntimeError: If current profile is not in allowed set
    """
    current = get_profile()
    
    if current not in allowed_profiles:
        error_msg = (
            f"Operation not allowed under profile '{current}'. "
            f"Allowed profiles: {sorted(allowed_profiles)}"
        )
        if context:
            error_msg += f" (context: {context})"
        
        logger.error(f"[PROFILE-GUARD] {error_msg}")
        raise RuntimeError(error_msg)


def log_profile_context(context: str) -> None:
    """
    Log the current profile with context for debugging.
    
    Args:
        context: The context from which this is called
    """
    try:
        current = get_profile()
        logger.info(f"[PROFILE-CONTEXT] {context} | profile={current}")
    except RuntimeError as e:
        logger.warning(f"[PROFILE-CONTEXT] {context} | ERROR: {e}")
