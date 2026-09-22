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


















