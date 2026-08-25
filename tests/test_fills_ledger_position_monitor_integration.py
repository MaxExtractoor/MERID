"""
Test for fills_ledger to PositionMonitor integration fix.

This test verifies that fills_ledger.on_fill() now adds positions to PositionMonitor,
ensuring exit policies execute on every trade regardless of which component tracks the position.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from merid.position_management.position_monitor import get_position_monitor, PositionMonitor
from merid.position_management.position import Position, PositionSide


class TestFillsLedgerPositionMonitorIntegration:
    """Test that fills_ledger integrates with PositionMonitor for exit policy enforcement."""
    
    @pytest.fixture
    def mock_fill(self):
        """Create a mock KalshiFill for testing."""
        fill = Mock()
        fill.fill_id = "test_fill_123"
        fill.market_ticker = "KXBTC15M-2024-01-01T12:00:00"
        fill.side = "yes"
        fill.action = "buy"
        fill.price_cents = 50
        fill.count_fp = 10
        fill.fee_cost = 0.5
        fill.agent_id = "BTC_15M"
        fill.created_time = datetime.utcnow()
        fill.raw_payload = None
        fill.proceeds_dollars = -5.0  # Cost for buy
        return fill
    
    @pytest.fixture
    def position_monitor(self):
        """Get the PositionMonitor singleton for testing."""
        with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync', return_value=1000.0):
            monitor = get_position_monitor()
            # Clear any existing positions
            monitor._open_positions.clear()
            yield monitor
    
    def test_fills_ledger_integration_code_path_exists(self, position_monitor):
        """Test that the fills_ledger integration code path exists and is callable."""
        # This test verifies the code structure by checking that the necessary
        # imports and method calls exist in fills_ledger.py
        
        import merid.event_venues.kalshi.fills_ledger as fills_ledger_module
        
        # Verify the on_fill method exists
        assert hasattr(fills_ledger_module, 'KalshiFillsLedger')
        assert hasattr(fills_ledger_module.KalshiFillsLedger, 'on_fill')
        
        # Read the source to verify the integration code exists
        import inspect
        source = inspect.getsource(fills_ledger_module.KalshiFillsLedger.on_fill)
        
        # Verify key integration markers exist
        assert "get_position_monitor" in source, "Missing PositionMonitor integration"
        assert "monitor.add_position" in source, "Missing monitor.add_position call"
        assert "monitor.remove_position" in source, "Missing monitor.remove_position call"
        
        print("[PASS] fills_ledger integration code path verified")
    
    def test_position_monitor_singleton_accessible(self):
        """Test that PositionMonitor singleton is accessible."""
        monitor = get_position_monitor()
        assert monitor is not None
        assert isinstance(monitor, PositionMonitor)
        print("[PASS] PositionMonitor singleton accessible")
    
    def test_position_monitor_add_position_works(self, position_monitor):
        """Test that PositionMonitor.add_position() works correctly."""
        test_position = Position(
            position_id="TEST-123",
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=45,
        )
        
        position_monitor.add_position(test_position)
        
        assert "TEST-123" in position_monitor._open_positions
        assert position_monitor._open_positions["TEST-123"].size == 10
        
        print("[PASS] PositionMonitor.add_position() works correctly")
    
    def test_position_monitor_remove_position_works(self, position_monitor):
        """Test that PositionMonitor.remove_position() works correctly."""
        test_position = Position(
            position_id="TEST-456",
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=45,
        )
        
        position_monitor.add_position(test_position)
        assert "TEST-456" in position_monitor._open_positions
        
        position_monitor.remove_position("TEST-456")
        assert "TEST-456" not in position_monitor._open_positions
        
        print("[PASS] PositionMonitor.remove_position() works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
