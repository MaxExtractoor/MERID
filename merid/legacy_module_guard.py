"""Legacy Module Guard — Runtime detection of legacy modules in 15m process.

This module provides helpers to detect and prevent legacy modules from being
loaded in the kalshi_crypto_15m_v2 profile process.

Legacy modules are those that belong to:
- PM runtime (DeploymentController, persisted agents, lane managers)
- Paper trading engine (PaperSession, paper_config)
- Reflection system (core/learning/persistence)
- Social broadcasters and PM "analytics"
- Cross-venue or non-15m Kalshi logic

Usage:
    from merid.legacy_module_guard import get_loaded_legacy_modules, assert_no_legacy_modules
    
    # Get list of loaded legacy modules
    legacy = get_loaded_legacy_modules()
    
    # Assert no legacy modules loaded (raises RuntimeError if any found)
    assert_no_legacy_modules()
"""

from __future__ import annotations

import sys
from typing import List, Set


# Known legacy module patterns that should NOT be loaded in 15m process
LEGACY_MODULE_PATTERNS: Set[str] = {
    # PM runtime
    "core.paper_session",
    "swarm.agent_registry",
    "merid.event_venues.kalshi.deployment",
    "merid.event_venues.kalshi.auto_promoter",
    
    # Paper trading
    "merid.paper_config",
    
    # Reflection system
    "core.learning",
    "core.persistence",
    "agents.reflection.integration",
    
    # Social broadcasters
    "merid.social",
    
    # Cross-venue (non-Kalshi)
    "merid.event_venues.binance",
    "merid.event_venues.bybit",
    "merid.event_venues.okx",
    
    # PM analytics
    "merid.pm_analytics",
}


def get_loaded_legacy_modules() -> List[str]:
    """Return list of legacy modules currently loaded in sys.modules.
    
    Returns:
        List of module names that match legacy patterns.
    """
    loaded = []
    for module_name in sys.modules:
        # Check if any legacy pattern is a prefix of the module name
        for pattern in LEGACY_MODULE_PATTERNS:
            if module_name == pattern or module_name.startswith(pattern + "."):
                loaded.append(module_name)
                break
    return loaded


def assert_no_legacy_modules(context: str = "runtime") -> None:
    """Assert that no legacy modules are loaded.
    
    Args:
        context: Context string for error message (e.g., "startup", "self-check")
    
    Raises:
        RuntimeError: If any legacy modules are loaded.
    """
    legacy = get_loaded_legacy_modules()
    if legacy:
        raise RuntimeError(
            f"Legacy modules detected in {context}: {legacy}. "
            f"These modules should not be loaded in kalshi_crypto_15m_v2 profile."
        )


def get_legacy_module_report() -> dict:
    """Return detailed report of legacy module status.
    
    Returns:
        Dict with:
        - legacy_modules_loaded: List of loaded legacy module names
        - legacy_count: Number of legacy modules loaded
        - is_clean: True if no legacy modules loaded
        - all_patterns: All legacy patterns being checked
    """
    legacy = get_loaded_legacy_modules()
    return {
        "legacy_modules_loaded": legacy,
        "legacy_count": len(legacy),
        "is_clean": len(legacy) == 0,
        "all_patterns": sorted(LEGACY_MODULE_PATTERNS),
    }
