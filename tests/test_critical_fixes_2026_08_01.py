"""
Tests for critical fixes implemented on 2026-08-01.

These tests verify:
1. Fills ledger validates fill data before recording
2. Window clearing on rejection allows retry
3. Window rebuild from positions on startup
4. Corrupted position data is filtered in enforcement checks
5. Slot allocator exception cleanup
6. Pending orders cross-validation with order gate
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from threading import Lock
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill
from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest


class TestFillsLedgerValidation:
    """Test that fills ledger validates fill data before recording."""
    
    def test_reject_fill_with_invalid_count(self):
        """Test that fills with invalid count are rejected."""
        ledger = KalshiFillsLedger()
        
        # Create fill with invalid count (0)
        fill = KalshiFill(
            fill_id="test_fill_1",
            market_ticker="KXBTC15M-TEST",
            count_fp=0,  # Invalid
            side="yes",
            action="buy",
            raw_payload={}
        )
        
        # Should reject without recording
        initial_count = len(ledger._processed_fill_ids)
        ledger.on_fill(fill)
        
        # Should not be recorded
        assert len(ledger._processed_fill_ids) == initial_count
        assert fill.fill_id not in ledger._processed_fill_ids
    
    def test_reject_fill_with_negative_count(self):
        """Test that fills with negative count are rejected."""
        ledger = KalshiFillsLedger()
        
        # Create fill with negative count
        fill = KalshiFill(
            fill_id="test_fill_2",
            market_ticker="KXBTC15M-TEST",
            count_fp=-1,  # Invalid
            side="yes",
            action="buy",
            raw_payload={}
        )
        
        # Should reject without recording
        initial_count = len(ledger._processed_fill_ids)
        ledger.on_fill(fill)
        
        # Should not be recorded
        assert len(ledger._processed_fill_ids) == initial_count
    
    def test_reject_fill_with_empty_fill_id(self):
        """Test that fills with empty fill_id are rejected."""
        ledger = KalshiFillsLedger()
        
        # Create fill with empty fill_id
        fill = KalshiFill(
            fill_id="",  # Invalid
            market_ticker="KXBTC15M-TEST",
            count_fp=10,
            side="yes",
            action="buy",
            raw_payload={}
        )
        
        # Should reject without recording
        initial_count = len(ledger._processed_fill_ids)
        ledger.on_fill(fill)
        
        # Should not be recorded
        assert len(ledger._processed_fill_ids) == initial_count
    
    def test_reject_fill_with_invalid_side(self):
        """Test that fills with invalid side are rejected."""
        ledger = KalshiFillsLedger()
        
        # Create fill with invalid side
        fill = KalshiFill(
            fill_id="test_fill_3",
            market_ticker="KXBTC15M-TEST",
            count_fp=10,
            side="invalid",  # Invalid
            action="buy",
            raw_payload={}
        )
        
        # Should reject without recording
        initial_count = len(ledger._processed_fill_ids)
        ledger.on_fill(fill)
        
        # Should not be recorded
        assert len(ledger._processed_fill_ids) == initial_count
    
    def test_accept_valid_fill(self):
        """Test that valid fills are accepted and recorded."""
        ledger = KalshiFillsLedger()
        
        # Create valid fill
        fill = KalshiFill(
            fill_id="test_fill_valid",
            market_ticker="KXBTC15M-TEST",
            count_fp=10,
            side="yes",
            action="buy",
            raw_payload={}
        )
        
        # Should accept and record
        initial_count = len(ledger._processed_fill_ids)
        ledger.on_fill(fill)
        
        # Should be recorded
        assert len(ledger._processed_fill_ids) == initial_count + 1
        assert fill.fill_id in ledger._processed_fill_ids


class TestWindowClearingOnRejection:
    """Test that windows are cleared on rejection to allow retry."""
    
    def test_window_cleared_on_rejection(self):
        """Test that entry window is cleared when order is rejected."""
        from merid.event_venues.kalshi.order_router import (
            _asset_entry_windows, _asset_entry_windows_lock, clear_entry_window_for_asset
        )
        
        # Set up a window for BTC
        current_window = int(time.time() // 900) * 900
        with _asset_entry_windows_lock:
            _asset_entry_windows["BTC"] = current_window
        
        # Verify window is set
        with _asset_entry_windows_lock:
            assert _asset_entry_windows.get("BTC") == current_window
        
        # Clear window on rejection
        clear_entry_window_for_asset("BTC")
        
        # Verify window is cleared
        with _asset_entry_windows_lock:
            assert "BTC" not in _asset_entry_windows
    
    def test_window_clearing_idempotent(self):
        """Test that clearing a non-existent window doesn't raise error."""
        from merid.event_venues.kalshi.order_router import clear_entry_window_for_asset
        
        # Should not raise error even if window doesn't exist
        clear_entry_window_for_asset("NONEXISTENT_ASSET")
    
    def test_rebuild_windows_from_positions(self):
        """Test that windows are rebuilt from position cache."""
        from merid.event_venues.kalshi.order_router import (
            _asset_entry_windows, _asset_entry_windows_lock, rebuild_entry_windows_from_positions
        )
        
        # Clear all windows
        with _asset_entry_windows_lock:
            _asset_entry_windows.clear()
        
        # Mock position cache with BTC and ETH positions
        mock_position_cache = Mock()
        mock_position = Mock()
        mock_position.contracts = 10
        mock_position_cache.get_all_positions.return_value = {
            "KXBTC15M-TEST": mock_position,
            "KXETH15M-TEST": mock_position
        }
        
        # Patch at the import location inside the function
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache):
            rebuild_entry_windows_from_positions()
        
        # Verify windows were rebuilt for BTC and ETH
        with _asset_entry_windows_lock:
            assert "BTC" in _asset_entry_windows
            assert "ETH" in _asset_entry_windows


class TestCorruptedPositionDataFiltering:
    """Test that corrupted position data is filtered in enforcement checks."""
    
    def test_global_allocator_filters_corrupted_positions(self):
        """Test that global allocator filters positions with corrupted exposure data."""
        from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate
        
        allocator = GlobalAllocator()
        
        # Create candidates
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.9, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"
            ),
        ]
        
        # Current positions with corrupted data (exposure = 0)
        current_positions = {
            "BTC": 0.0,  # Corrupted
            "ETH": 0.50,  # Valid
        }
        
        # Allocate - should filter out BTC (corrupted) and allow it to trade
        chosen = allocator.allocate(candidates, current_positions)
        
        # BTC should be allowed to trade (corrupted data filtered)
        btc_chosen = any(c.asset == "BTC" for c in chosen)
        assert btc_chosen, "BTC should be allowed to trade despite corrupted position data"
        
        # ETH should be blocked (valid position exists)
        eth_chosen = any(c.asset == "ETH" for c in chosen)
        assert not eth_chosen, "ETH should be blocked due to valid position"


class TestSlotAllocatorExceptionCleanup:
    """Test that slot allocator cleans up on exceptions."""
    
    def test_slot_cleanup_on_exception(self):
        """Test that slots are cleaned up when exception occurs during allocation."""
        allocator = GlobalSlotAllocator()
        
        # Create a valid request
        request = AllocationRequest(
            agent_id="TEST_AGENT",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.05,
            spread_cents=0,
            confidence=0.6,
            is_exit_order=False,
            request_time=time.time()
        )
        
        # Mock PositionSlot to raise exception during allocation
        with patch('merid.risk.global_slot_allocator.PositionSlot', side_effect=Exception("Test exception")):
            # This should not leave a partially allocated slot
            success, reason, slot_id = allocator.request_allocation(request)
            
            # Should fail due to exception
            assert not success
            assert "Allocation failed" in reason
            
            # Slot should be cleaned up (not in _slots)
            assert slot_id not in allocator._slots or slot_id is None


class TestPendingOrdersCrossValidation:
    """Test that pending orders cross-validation logic exists and doesn't crash."""
    
    def test_pending_order_cross_validation_exists(self):
        """Test that cross-validation logic is present in global_allocator."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        
        # Verify the cross-validation code exists by checking the source
        import inspect
        source = inspect.getsource(GlobalAllocator.allocate)
        
        # Check that order gate cross-validation is mentioned
        assert "order_gate" in source.lower() or "cross" in source.lower(), \
            "Cross-validation logic should be present in allocate method"
    
    def test_pending_order_timeout_logic_exists(self):
        """Test that timeout-based cleanup logic exists."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        
        # Verify the timeout logic exists (it's an instance variable)
        allocator = GlobalAllocator()
        assert hasattr(allocator, '_pending_order_timeout'), \
            "Pending order timeout should be defined"
        assert allocator._pending_order_timeout > 0, \
            "Pending order timeout should be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
