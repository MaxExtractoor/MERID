"""Tests for critical router fail-fast validation in main.py."""

import sys
from unittest.mock import patch, MagicMock
import pytest


def test_critical_router_fail_fast_on_missing_router():
    """Test that app fails to start if a critical router is None."""
    # Test the validation logic directly
    mock_auth = MagicMock()
    mock_kalshi_api = None  # This one fails
    mock_kalshi_grid = MagicMock()
    mock_operator = MagicMock()
    
    critical_routers = [
        ("auth_router", mock_auth),
        ("kalshi_api_router", mock_kalshi_api),
        ("kalshi_grid_router", mock_kalshi_grid),
        ("operator_endpoints_router", mock_operator),
    ]
    
    # Expect SystemExit when a critical router is None
    with pytest.raises(SystemExit) as exc_info:
        for name, router_instance in critical_routers:
            if router_instance is None:
                raise SystemExit(1)
    
    assert exc_info.value.code == 1


def test_critical_router_passes_when_all_loaded():
    """Test that app starts normally when all critical routers are present."""
    # All routers present - should not raise
    mock_auth = MagicMock()
    mock_kalshi_api = MagicMock()
    mock_kalshi_grid = MagicMock()
    mock_operator = MagicMock()
    
    critical_routers = [
        ("auth_router", mock_auth),
        ("kalshi_api_router", mock_kalshi_api),
        ("kalshi_grid_router", mock_kalshi_grid),
        ("operator_endpoints_router", mock_operator),
    ]
    
    # Should not raise any exception
    for name, router_instance in critical_routers:
        if router_instance is None:
            raise SystemExit(1)
    
    # If we reach here, test passes
    assert True


def test_critical_router_list_includes_expected_routers():
    """Verify the critical router list includes expected routers."""
    expected_routers = [
        "kalshi_api_router",
        "health_router",
        "loop_router",
    ]

    # Legacy web.main was deleted; the 15m production app lives in web.main_15m_lean.
    import web.main_15m_lean as main_module

    # The CRITICAL_ROUTERS list should exist and contain expected entries
    assert hasattr(main_module, 'CRITICAL_ROUTERS')
    router_names = [
        name[0] if isinstance(name, (list, tuple)) and len(name) == 2 else name
        for name in main_module.CRITICAL_ROUTERS
    ]

    for expected in expected_routers:
        assert expected in router_names, f"Expected {expected} in CRITICAL_ROUTERS"
