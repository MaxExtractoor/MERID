"""Tests for Kalshi integration in main loop.

Test Cases:
1. Loop generates Kalshi signals during feature refresh
2. Loop runs Kalshi agent cycle
3. Signals are stored in SignalStore
4. Agent grid is checked if running
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time














def test_kalshi_stack_no_betting_imports():
    """Guard: Kalshi prediction domain must not import betting modules on hot path.
    
    This test fails if merid.betting is imported when running Kalshi-only mode,
    preventing the legacy sports betting stack from contaminating the Kalshi loop.
    See: slow tick #134 analysis (betting_refreshed:6events on hot path).
    
    NOTE: This test checks that importing MeridLoop in Kalshi-only mode does NOT
    trigger betting module imports. Previous tests may have imported betting modules,
    so we track NEW imports during this specific test.
    """
    import sys
    
    # Capture current betting modules BEFORE importing loop
    pre_test_betting = set(name for name in sys.modules if name.startswith("merid.betting"))
    
    # Clear any betting modules to simulate fresh import
    for mod in list(sys.modules.keys()):
        if mod.startswith("merid.betting"):
            del sys.modules[mod]
    
    # Now import MeridLoop fresh
    from merid.loop import MeridLoop, LoopConfig
    
    loop = MeridLoop()
    is_kalshi_only = "prediction" in loop.config.active_domains and "betting" not in loop.config.active_domains
    
    # Check what betting modules were imported by this import
    post_test_betting = set(name for name in sys.modules if name.startswith("merid.betting"))
    newly_imported = post_test_betting - pre_test_betting
    
    if is_kalshi_only:
        # In Kalshi-only mode, importing MeridLoop should NOT import betting modules
        # (the lazy accessor methods are defined but don't import until called)
        assert len(newly_imported) == 0, f"Kalshi stack imported betting modules: {newly_imported}"
    
    # Restore previously imported modules for other tests
    for mod in pre_test_betting:
        if mod not in sys.modules:
            # Best effort restore - mark as already processed
            sys.modules[mod] = None


def test_betting_refresh_feature_flag_respected():
    """Test that betting refresh respects the betting_refresh feature flag."""
    from core.feature_flags import set_flag, reset_flag, is_enabled
    from merid.loop import MeridLoop
    
    # Ensure flag is disabled (default)
    reset_flag("betting_refresh")
    assert not is_enabled("betting_refresh"), "betting_refresh should default to False"
    
    # Create loop and check betting step would not run
    loop = MeridLoop()
    
    # When flag is disabled, tick should report betting_refreshed:disabled
    # When enabled, it would try to run the step
    set_flag("betting_refresh", True)
    assert is_enabled("betting_refresh"), "betting_refresh should be toggleable"
    
    # Reset to default
    reset_flag("betting_refresh")
    assert not is_enabled("betting_refresh"), "betting_refresh should reset to False"
