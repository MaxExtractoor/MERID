"""
Unit tests for Top3BatchManager — batch lifecycle management.
"""

import pytest
import time
from datetime import datetime, timezone

from merid.trading.top3_edge_allocator import (
    EdgeCandidate,
    Top3Allocation,
    Top3Batch,
    BatchStatus,
)
from merid.trading.top3_batch_manager import (
    Top3BatchManager,
    get_top3_batch_manager,
    reset_top3_batch_manager,
    REJECT_NO_ACTIVE_BATCH,
    REJECT_ASSET_NOT_IN_TOP3,
    REJECT_NOTIONAL_LIMIT_REACHED,
)


@pytest.fixture
def fresh_batch_manager():
    """Provide a fresh batch manager singleton for each test."""
    import os
    os.environ["MERID_TEST_MODE"] = "1"
    reset_top3_batch_manager()
    return get_top3_batch_manager()


@pytest.fixture
def sample_candidates():
    """Provide sample edge candidates."""
    return [
        EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
        EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
        EdgeCandidate("DOGE", edge=0.02, max_notional_cap=1000),
    ]


class TestBatchCreation:
    """Tests for batch creation logic."""
    
    def test_batch_not_created_with_no_allocations(self, fresh_batch_manager):
        """No batch should be created when no valid allocations."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[],  # No candidates
        )
        
        assert batch is None
        assert mgr.get_current_batch() is None
    
    def test_batch_not_created_with_zero_bankroll(self, fresh_batch_manager, sample_candidates):
        """No batch should be created with zero/negative bankroll."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=0,
            candidates=sample_candidates,
        )
        
        assert batch is None
    
    def test_batch_created_when_none_exists(self, fresh_batch_manager, sample_candidates):
        """New batch should be created when no active batch."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        assert batch is not None
        assert batch.status == BatchStatus.ACTIVE
        assert len(batch.allocations) == 3  # Top 3
        assert mgr.get_current_batch() is batch
    
    def test_batch_not_created_when_already_active(self, fresh_batch_manager, sample_candidates):
        """New batch should NOT be created when one is already active."""
        mgr = fresh_batch_manager
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        assert batch1 is not None
        
        # Try to create second batch
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        assert batch2 is None
        assert mgr.get_current_batch() is batch1
    
    def test_new_batch_created_when_previous_closed(self, fresh_batch_manager, sample_candidates):
        """New batch should be created after previous is closed and reconciled."""
        mgr = fresh_batch_manager
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        batch1_id = batch1.batch_id
        
        # Close all positions
        for alloc in batch1.allocations:
            mgr.mark_asset_closed(batch1_id, alloc.asset)
        
        # CRITICAL: Must reconcile bankroll before new cycle can start
        # Cycle lock prevents new batches until FULLY_RECONCILED
        mgr.mark_batch_reconciled(batch1_id, realized_pnl_cents=500)
        
        # Verify batch is now FULLY_RECONCILED
        assert mgr.get_current_batch().status == BatchStatus.FULLY_RECONCILED
        
        # Now can create new batch (cycle lock is released)
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        assert batch2 is not None
        assert batch2.batch_id != batch1_id


class TestBatchLifecycle:
    """Tests for batch state transitions."""
    
    def test_mark_asset_filled(self, fresh_batch_manager, sample_candidates):
        """Should track filled assets correctly."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        result = mgr.mark_asset_filled(batch.batch_id, "BTC", 1000)
        
        assert result is True
        assert "BTC" in batch.filled_assets
    
    def test_mark_asset_filled_wrong_batch(self, fresh_batch_manager, sample_candidates):
        """Should fail when marking filled for wrong batch."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        result = mgr.mark_asset_filled("wrong-batch-id", "BTC", 1000)
        
        assert result is False
    
    def test_mark_asset_closed(self, fresh_batch_manager, sample_candidates):
        """Should track closed assets correctly."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        result = mgr.mark_asset_closed(batch.batch_id, "BTC")
        
        assert result is True
        assert "BTC" in batch.closed_assets
    
    def test_batch_auto_closes_when_all_closed(self, fresh_batch_manager, sample_candidates):
        """Batch should auto-close when all assets are marked closed."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        # Close all allocations
        for alloc in batch.allocations:
            mgr.mark_asset_closed(batch.batch_id, alloc.asset)
        
        assert batch.status == BatchStatus.CLOSED
        assert batch.all_positions_closed()
    
    def test_close_batch_manual(self, fresh_batch_manager, sample_candidates):
        """Should allow manual batch closure."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        # Close it (force=True required since positions are still technically "open" in test state)
        mgr.close_batch(batch.batch_id, reason="manual_test", force=True)
        
        assert batch.status == BatchStatus.CLOSED
    
    def test_close_batch_manual_bypass_attempt(self, fresh_batch_manager, sample_candidates):
        """Should reject manual batch closure when positions are open."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        # Attempt to close without force=True
        result = mgr.close_batch(batch.batch_id, reason="manual_test")
        
        assert result is False
        assert batch.status == BatchStatus.ACTIVE
    
    def test_close_batch_manual_bypass_attempt_force(self, fresh_batch_manager, sample_candidates):
        """Should allow manual batch closure with force=True."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        # Attempt to close with force=True
        result = mgr.close_batch(batch.batch_id, reason="manual_test", force=True)
        
        assert result is True
        assert batch.status == BatchStatus.CLOSED


class TestEntryValidation:
    """Tests for entry validation (the main gate)."""
    
    def test_can_open_new_position_with_active_batch(self, fresh_batch_manager, sample_candidates):
        """Should allow entry for assets in active batch."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        allowed, reason, allocation = mgr.can_open_new_position("BTC", 500)
        
        assert allowed is True
        assert reason == ""
        assert allocation is not None
        assert allocation.asset == "BTC"
    
    def test_cannot_open_without_batch(self, fresh_batch_manager):
        """Should reject entry when no active batch."""
        mgr = fresh_batch_manager
        
        allowed, reason, allocation = mgr.can_open_new_position("BTC", 500)
        
        assert allowed is False
        assert reason == REJECT_NO_ACTIVE_BATCH
        assert allocation is None
    
    def test_cannot_open_asset_not_in_batch(self, fresh_batch_manager, sample_candidates):
        """Should reject entry for assets not in batch."""
        mgr = fresh_batch_manager
        
        # Create batch with only top 3 (BTC, ETH, SOL)
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        # XRP and DOGE are not in top 3
        allowed, reason, allocation = mgr.can_open_new_position("XRP", 500)
        
        assert allowed is False
        assert reason == REJECT_ASSET_NOT_IN_TOP3
        assert allocation is None
    
    def test_rejection_counters_increment(self, fresh_batch_manager, sample_candidates):
        """Rejection counters should track rejections."""
        mgr = fresh_batch_manager
        
        # Try to open without batch
        mgr.can_open_new_position("BTC", 500)
        
        # Create batch and try non-top3 asset
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        mgr.can_open_new_position("DOGE", 500)
        
        summary = mgr.get_rejection_summary()
        
        assert summary[REJECT_NO_ACTIVE_BATCH] == 1
        assert summary[REJECT_ASSET_NOT_IN_TOP3] == 1


class TestBatchMetrics:
    """Tests for metrics and observability."""
    
    def test_get_metrics_with_active_batch(self, fresh_batch_manager, sample_candidates):
        """Should return metrics dict with active batch info."""
        mgr = fresh_batch_manager
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        metrics = mgr.get_metrics()
        
        assert metrics["active_batch"] == 1
        assert "current_batch" in metrics
        assert metrics["current_batch"]["batch_id"] == batch.batch_id
        assert "assets" in metrics["current_batch"]
    
    def test_get_metrics_without_batch(self, fresh_batch_manager):
        """Should return metrics dict without current_batch."""
        mgr = fresh_batch_manager
        
        metrics = mgr.get_metrics()
        
        assert metrics["active_batch"] == 0
        assert "current_batch" not in metrics
    
    def test_reset_rejection_counters(self, fresh_batch_manager):
        """Should reset rejection counters."""
        mgr = fresh_batch_manager
        
        # Cause some rejections
        mgr.can_open_new_position("BTC", 500)
        
        assert mgr.get_rejection_summary()[REJECT_NO_ACTIVE_BATCH] == 1
        
        mgr.reset_rejection_counters()
        
        assert mgr.get_rejection_summary()[REJECT_NO_ACTIVE_BATCH] == 0


class TestValidateOrder:
    """Tests for order validation convenience method."""
    
    def test_validate_order_accepts_valid(self, fresh_batch_manager, sample_candidates):
        """Should accept valid orders."""
        mgr = fresh_batch_manager
        
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        allowed, reason = mgr.validate_order("BTC", "KXBTC-TEST", "yes", 10, 50)
        
        assert allowed is True
        assert reason == ""
    
    def test_validate_order_rejects_without_batch(self, fresh_batch_manager):
        """Should reject when no batch."""
        mgr = fresh_batch_manager
        
        allowed, reason = mgr.validate_order("BTC", "KXBTC-TEST", "yes", 10, 50)
        
        assert allowed is False
        assert reason == REJECT_NO_ACTIVE_BATCH
    
    def test_validate_order_rejects_wrong_asset(self, fresh_batch_manager, sample_candidates):
        """Should reject wrong asset."""
        mgr = fresh_batch_manager
        
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        
        allowed, reason = mgr.validate_order("XRP", "KXXRP-TEST", "yes", 10, 50)
        
        assert allowed is False
        assert reason == REJECT_ASSET_NOT_IN_TOP3


class TestBatchPersistence:
    """Tests for state persistence (in-memory when cache unavailable)."""
    
    def test_state_persists_in_memory(self, fresh_batch_manager, sample_candidates):
        """Batch state should persist in memory when cache unavailable."""
        mgr = fresh_batch_manager
        
        # Create batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates,
        )
        batch_id = batch.batch_id
        
        # Simulate "reload" by creating new manager (uses same memory state)
        # Note: In real scenario with cache, this would load from cache
        # Without cache, _memory_batch is used
        mgr2 = Top3BatchManager()
        
        # Since we're using in-memory fallback, state should be preserved
        loaded_batch = mgr2.get_current_batch()
        assert loaded_batch is not None
        assert loaded_batch.batch_id == batch_id


class TestCycleLocking:
    """REGRESSION TESTS: Cycle locking prevents cycle piling.
    
    Critical safety feature: No new cycle can start until previous
    cycle is FULLY_RECONCILED (bankroll updated with realized P&L).
    """
    
    def test_cycle_unlocked_when_no_batch(self, fresh_batch_manager):
        """Fresh start - cycle should be unlocked."""
        mgr = fresh_batch_manager
        
        locked, reason = mgr.is_cycle_locked()
        
        assert locked is False
        assert reason == ""
    
    def test_cycle_locked_when_batch_active(self, fresh_batch_manager, sample_candidates):
        """Cycle locked when batch is ACTIVE."""
        mgr = fresh_batch_manager
        
        # Create an active batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[:3],
        )
        assert batch is not None
        assert batch.status == BatchStatus.ACTIVE
        
        # Cycle should be locked
        locked, reason = mgr.is_cycle_locked()
        assert locked is True
        assert "ACTIVE" in reason
    
    def test_cycle_locked_when_batch_closed(self, fresh_batch_manager, sample_candidates):
        """Cycle locked when batch is CLOSED but not reconciled."""
        mgr = fresh_batch_manager
        
        # Create batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[:3],
        )
        assert batch is not None
        
        # Close the batch (simulate all positions closed)
        mgr.close_batch(batch.batch_id, reason="test_close", force=True)
        
        # Verify CLOSED status
        current = mgr.get_current_batch()
        assert current.status == BatchStatus.CLOSED
        
        # Cycle should STILL be locked (not yet reconciled)
        locked, reason = mgr.is_cycle_locked()
        assert locked is True
        assert "CLOSED" in reason
    
    def test_cycle_unlocked_when_fully_reconciled(self, fresh_batch_manager, sample_candidates):
        """Cycle unlocked when batch is FULLY_RECONCILED."""
        mgr = fresh_batch_manager
        
        # Create batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[:3],
        )
        assert batch is not None
        
        # Close the batch
        mgr.close_batch(batch.batch_id, reason="test_close", force=True)
        
        # Mark as reconciled
        result = mgr.mark_batch_reconciled(batch.batch_id, realized_pnl_cents=500)
        assert result is True
        
        # Verify FULLY_RECONCILED status
        current = mgr.get_current_batch()
        assert current.status == BatchStatus.FULLY_RECONCILED
        
        # Cycle should now be unlocked
        locked, reason = mgr.is_cycle_locked()
        assert locked is False
        assert reason == ""
    
    def test_new_batch_blocked_when_cycle_locked(self, fresh_batch_manager, sample_candidates):
        """Cannot create new batch when cycle is locked (regression test)."""
        mgr = fresh_batch_manager
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[:3],
        )
        assert batch1 is not None
        
        # Attempt to create second batch while first is still ACTIVE
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[2:5],  # Different edges
        )
        
        # Second batch should be blocked
        assert batch2 is None
    
    def test_new_batch_allowed_after_reconciliation(self, fresh_batch_manager, sample_candidates):
        """New batch allowed only after FULLY_RECONCILED."""
        mgr = fresh_batch_manager
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[:3],
        )
        assert batch1 is not None
        batch1_id = batch1.batch_id
        
        # Close and reconcile (force=True required)
        mgr.close_batch(batch1_id, reason="test_close", force=True)
        mgr.mark_batch_reconciled(batch1_id, realized_pnl_cents=500)
        
        # Now new batch should be allowed
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=sample_candidates[2:5],
        )
        assert batch2 is not None
        assert batch2.batch_id != batch1_id
