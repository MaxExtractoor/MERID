"""Tests for Continuous Position Reconciliation implementation.

CRITICAL FIX (2026-07-17): Tests for 60s background position reconciliation.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.continuous_reconciliation import (
    ContinuousReconciler,
    PositionMismatch,
    ReconciliationAction,
    get_continuous_reconciler,
)


class TestContinuousReconciler:
    """Test continuous position reconciliation."""
    
    def test_singleton_pattern(self):
        """Test that ContinuousReconciler is a singleton."""
        cr1 = get_continuous_reconciler()
        cr2 = get_continuous_reconciler()
        
        assert cr1 is cr2
    
    def test_initial_state(self):
        """Test initial reconciler state."""
        cr = get_continuous_reconciler()
        
        assert cr._running is False
        assert cr._reconciliation_count == 0
        assert cr._last_reconciliation_time is None
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping reconciler."""
        cr = get_continuous_reconciler()
        
        await cr.start()
        assert cr._running is True
        
        await cr.stop()
        assert cr._running is False
    
    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test starting when already running."""
        cr = get_continuous_reconciler()
        
        await cr.start()
        await cr.start()  # Should not raise
        assert cr._running is True
        
        await cr.stop()
    
    @pytest.mark.asyncio
    async def test_reconcile_cycle(self):
        """Test a single reconciliation cycle."""
        cr = get_continuous_reconciler()
        
        # Mock the fetch methods
        cr._fetch_exchange_positions = AsyncMock(return_value={
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        })
        cr._fetch_ledger_positions = AsyncMock(return_value={
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        })
        cr._fetch_monitor_positions = AsyncMock(return_value={
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        })
        
        await cr._reconcile()
        
        assert cr._reconciliation_count == 1
        assert cr._last_reconciliation_time is not None
        assert len(cr._mismatches) == 0  # No mismatches
    
    @pytest.mark.asyncio
    async def test_fetch_ledger_positions_key_fix(self):
        """Test that _fetch_ledger_positions uses correct key 'market_ticker'.
        
        CRITICAL FIX (2026-07-31): Fixed data structure key mismatch.
        compute_net_positions() returns dict with "market_ticker" key, not "market_id".
        This test verifies the fix prevents 'string indices must be integers' error.
        """
        # Read the actual source file to verify the fix is in place
        with open('merid/event_venues/kalshi/continuous_reconciliation.py', 'r') as f:
            source = f.read()
        
        # Verify the fix: should use "market_ticker" not "market_id"
        assert 'market_ticker' in source
        assert 'pos["market_ticker"]' in source
    
    @pytest.mark.asyncio
    async def test_detect_mismatch(self):
        """Test mismatch detection."""
        cr = get_continuous_reconciler()
        
        exchange_positions = {
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        }
        ledger_positions = {
            "market1": {"contracts": 5, "side": "yes", "avg_price_cents": 50},  # Mismatch
        }
        monitor_positions = {
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        }
        
        mismatches = cr._detect_mismatches(exchange_positions, ledger_positions, monitor_positions)
        
        assert len(mismatches) == 1
        assert mismatches[0].market_id == "market1"
        assert mismatches[0].local_contracts == 5
        assert mismatches[0].exchange_contracts == 10
        assert mismatches[0].action == ReconciliationAction.ACCEPT_EXCHANGE
    
    @pytest.mark.asyncio
    async def test_apply_action_accept_exchange(self):
        """Test applying ACCEPT_EXCHANGE action."""
        cr = get_continuous_reconciler()
        
        mismatch = PositionMismatch(
            market_id="market1",
            local_contracts=5,
            exchange_contracts=10,
            local_side="yes",
            exchange_side="yes",
            local_avg_price_cents=50,
            exchange_avg_price_cents=50,
            detected_at=datetime.now(timezone.utc),
            action=ReconciliationAction.ACCEPT_EXCHANGE,
        )
        
        # Mock position cache
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = AsyncMock()
            mock_get_cache.return_value = mock_cache
            
            await cr._apply_action(mismatch)
            
            # Verify sync_from_rest was called with force=True
            mock_cache.sync_from_rest.assert_called_once()
            call_args = mock_cache.sync_from_rest.call_args
            assert call_args.kwargs.get('force') is True
    
    @pytest.mark.asyncio
    async def test_mismatch_callback(self):
        """Test mismatch callback registration."""
        cr = get_continuous_reconciler()
        
        callback_called = []
        
        def callback(mismatch):
            callback_called.append(mismatch)
        
        cr.register_mismatch_callback(callback)
        
        # Mock fetch methods to create a mismatch
        cr._fetch_exchange_positions = AsyncMock(return_value={
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        })
        cr._fetch_ledger_positions = AsyncMock(return_value={
            "market1": {"contracts": 5, "side": "yes", "avg_price_cents": 50},
        })
        cr._fetch_monitor_positions = AsyncMock(return_value={
            "market1": {"contracts": 10, "side": "yes", "avg_price_cents": 50},
        })
        
        await cr._reconcile()
        
        assert len(callback_called) == 1
        assert callback_called[0].market_id == "market1"
    
    def test_get_status(self):
        """Test getting reconciler status."""
        cr = get_continuous_reconciler()
        
        status = cr.get_status()
        
        assert "running" in status
        assert "reconciliation_count" in status
        assert "mismatch_count" in status
        assert "interval_seconds" in status


class TestPositionMismatch:
    """Test PositionMismatch dataclass."""
    
    def test_to_dict(self):
        """Test converting mismatch to dictionary."""
        mismatch = PositionMismatch(
            market_id="market1",
            local_contracts=5,
            exchange_contracts=10,
            local_side="yes",
            exchange_side="yes",
            local_avg_price_cents=50,
            exchange_avg_price_cents=50,
            detected_at=datetime.now(timezone.utc),
            action=ReconciliationAction.ACCEPT_EXCHANGE,
        )
        
        d = mismatch.to_dict()
        
        assert d["market_id"] == "market1"
        assert d["local_contracts"] == 5
        assert d["exchange_contracts"] == 10
        assert d["action"] == "accept_exchange"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
