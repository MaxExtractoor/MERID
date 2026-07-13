"""Tests for Kalshi UI Summary API — unified data endpoint for frontend.

Test Cases:
1. UI summary endpoint returns expected structure
2. UI summary includes all required fields
3. UI summary handles errors gracefully
4. Response times are acceptable
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies for UI summary endpoint."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter") as mock_adapter, \
         patch("merid.reconciliation.kalshi_reconciler.get_kalshi_reconciler") as mock_reconciler, \
         patch("merid.signals.store.get_signal_store") as mock_store, \
         patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid:
        
        # Mock venue adapter
        adapter = MagicMock()
        # Default mock position for tests that need positions
        position_mock = MagicMock()
        position_mock.symbol = "BTC-TEST"
        position_mock.quantity = 10
        position_mock.average_entry_price = 55.0
        position_mock.unrealized_pnl = 50.0
        position_mock.side = "yes"
        position_mock.realized_pnl = 0.0
        adapter.get_positions = AsyncMock(return_value=[position_mock])
        adapter.get_orders = AsyncMock(return_value=[])
        mock_adapter.return_value = adapter
        
        # Mock reconciler
        reconciler = MagicMock()
        report = MagicMock()
        report.severity.value = "OK"
        report.summary = "All good"
        report.issues = []
        report.timestamp = 1234567890.0
        reconciler.return_value.reconcile.return_value = report
        mock_reconciler.return_value = reconciler.return_value
        
        # Mock signal store
        store = MagicMock()
        store.list_signals = MagicMock(return_value=[])
        mock_store.return_value = store
        
        # Mock agent grid
        grid = MagicMock()
        grid._running = True
        grid.agents = []
        mock_grid.return_value = grid
        
        yield {
            "adapter": adapter,
            "reconciler": reconciler.return_value,
            "store": store,
            "grid": grid,
        }


def test_ui_summary_endpoint_structure(mock_dependencies):
    """Test that /api/v1/kalshi/ui-summary returns expected structure."""
    from web.main_15m_lean import app
    
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify all required top-level fields
    assert "positions" in data
    assert "orders" in data
    assert "fills" in data
    assert "balance" in data
    assert "risk" in data
    assert "reconciliation" in data
    assert "signals" in data
    assert "grid" in data
    assert "mode" in data
    assert "timestamp" in data


def test_ui_summary_positions_structure(mock_dependencies):
    """Test that positions have correct structure."""
    from web.main_15m_lean import app
    
    # Position is already mocked in fixture with default values
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    positions = data["positions"]
    assert len(positions) == 1
    
    pos = positions[0]
    assert "ticker" in pos
    assert "outcome" in pos
    assert "size" in pos
    assert "avg_price" in pos
    assert "unrealized_pnl" in pos


def test_ui_summary_signals_structure(mock_dependencies):
    """Test that signals section has correct structure."""
    from web.main_15m_lean import app
    
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    signals = data["signals"]
    assert "edge_top" in signals
    assert "liquidity" in signals
    assert "volume_anomalies" in signals
    assert "risk_events" in signals
    
    # All should be lists
    assert isinstance(signals["edge_top"], list)
    assert isinstance(signals["liquidity"], list)
    assert isinstance(signals["volume_anomalies"], list)
    assert isinstance(signals["risk_events"], list)


def test_ui_summary_reconciliation_structure(mock_dependencies):
    """Test that reconciliation section has correct structure."""
    from web.main_15m_lean import app
    
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    recon = data["reconciliation"]
    assert "severity" in recon
    assert "summary" in recon
    assert "issue_count" in recon
    assert "issues" in recon
    assert "timestamp" in recon
    
    assert recon["severity"] == "OK"


def test_ui_summary_grid_structure(mock_dependencies):
    """Test that grid section has correct structure."""
    from web.main_15m_lean import app
    
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    grid = data["grid"]
    assert "status" in grid
    assert "agents" in grid
    assert "pnl" in grid
    
    assert grid["status"] == "running"
    assert isinstance(grid["agents"], list)


def test_ui_summary_mode_field(mock_dependencies):
    """Test that mode field is present and valid."""
    from web.main_15m_lean import app
    
    client = TestClient(app)
    response = client.get("/api/v1/kalshi/ui-summary")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["mode"] in ("paper", "live")


def test_ui_summary_graceful_adapter_failure(mock_dependencies):
    """Test that endpoint handles adapter failures gracefully."""
    from web.main_15m_lean import app
    from unittest.mock import patch, AsyncMock
    
    # Make adapter fail by patching where kalshi_ui imports it
    failing_adapter = AsyncMock(side_effect=Exception("Adapter unavailable"))
    with patch("web.api.kalshi_ui.get_kalshi_venue_adapter", return_value=failing_adapter):
        client = TestClient(app)
        response = client.get("/api/v1/kalshi/ui-summary")
        
        # Should still return 200 with empty positions
        assert response.status_code == 200
        data = response.json()
        
        assert data["positions"] == []
        assert data["orders"] == []


def test_ui_summary_graceful_reconciliation_failure(mock_dependencies):
    """Test that endpoint handles reconciliation failures gracefully."""
    from web.main_15m_lean import app
    from unittest.mock import patch, MagicMock
    
    # Make reconciler fail by patching where kalshi_ui imports it
    with patch("web.api.kalshi_ui.get_kalshi_reconciler", side_effect=Exception("Reconciliation failed")):
        client = TestClient(app)
        response = client.get("/api/v1/kalshi/ui-summary")
        
        # Should still return 200 with unknown reconciliation
        assert response.status_code == 200
        data = response.json()
        
        assert data["reconciliation"]["severity"] == "UNKNOWN"


def test_ui_summary_response_time():
    """Test that UI summary responds within reasonable time."""
    from web.main_15m_lean import app
    import time
    
    with patch("merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter"), \
         patch("merid.reconciliation.kalshi_reconciler.get_kalshi_reconciler"), \
         patch("merid.signals.store.get_signal_store"), \
         patch("merid.prediction.agent_grid.get_agent_grid"):
        
        client = TestClient(app)
        
        start = time.time()
        response = client.get("/api/v1/kalshi/ui-summary")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 2.0  # Should respond in under 2 seconds
