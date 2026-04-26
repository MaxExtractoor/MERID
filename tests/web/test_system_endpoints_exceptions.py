"""Tests for improved exception handling in system_endpoints.py."""

import pytest
from unittest.mock import patch, MagicMock
import sys


def test_real_system_metrics_handles_import_error():
    """Test that _real_system_metrics handles ImportError gracefully."""
    from web.api.system_endpoints import _real_system_metrics
    
    # Simulate psutil not being installed
    with patch.dict('sys.modules', {'psutil': None}):
        result = _real_system_metrics()
        
        assert result["cpu_usage"] == 0.0
        assert result["memory_usage"] == 0.0
        assert result["active_connections"] == 0


def test_get_paper_engine_handles_import_error():
    """Test that _get_paper_engine handles ImportError gracefully."""
    from web.api.system_endpoints import _get_paper_engine
    
    # Simulate module not available
    with patch.dict('sys.modules', {'trading.paper_trading': None}):
        result = _get_paper_engine()
        assert result is None


def test_get_kalshi_risk_handles_import_error():
    """Test that _get_kalshi_risk handles ImportError gracefully."""
    from web.api.system_endpoints import _get_kalshi_risk
    
    # Simulate module not available
    with patch.dict('sys.modules', {'merid.event_venues.kalshi.kalshi_risk': None}):
        result = _get_kalshi_risk()
        assert result is None


def test_get_kalshi_grid_handles_import_error():
    """Test that _get_kalshi_grid handles ImportError gracefully."""
    from web.api.system_endpoints import _get_kalshi_grid
    
    # Simulate module not available
    with patch.dict('sys.modules', {'merid.prediction.agent_grid': None}):
        result = _get_kalshi_grid()
        assert result is None


def test_kalshi_pnl_returns_zero_pnl_on_failure():
    """Test that _kalshi_pnl returns zero PnL when risk manager unavailable."""
    from web.api.system_endpoints import _kalshi_pnl, _zero_pnl
    
    # When _get_kalshi_risk returns None, should return zero PnL
    with patch('web.api.system_endpoints._get_kalshi_risk', return_value=None):
        result = _kalshi_pnl()
        expected = _zero_pnl()
        assert result == expected
