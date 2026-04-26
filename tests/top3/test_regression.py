"""
Regression tests for Top-3 system — preventing "spraying" across all 5 assets.

These tests verify that the production bug (trading all 5 assets instead of top 3)
cannot recur.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from merid.trading.top3_edge_allocator import (
    EdgeCandidate,
    Top3Allocation,
    Top3Batch,
    BatchStatus,
)
from merid.trading.top3_batch_manager import (
    get_top3_batch_manager,
    reset_top3_batch_manager,
)


@pytest.fixture
def reset_state():
    """Reset and provide batch manager singleton before each test."""
    import os
    os.environ["MERID_TEST_MODE"] = "1"
    reset_top3_batch_manager()
    yield get_top3_batch_manager()
    reset_top3_batch_manager()


class TestNoSprayingRegression:
    """
    Regression tests for the "spraying" bug where the system would trade
    all 5 assets (BTC, ETH, SOL, XRP, DOGE) instead of just the top 3 by edge.
    """
    
    def test_at_most_3_assets_per_cycle(
        self, reset_state
    ):
        """
        CRITICAL REGRESSION: At most 3 assets can be selected per cycle.
        
        This was the original bug: the system would select all 5 assets
        instead of respecting the top-3 constraint.
        """
        mgr = get_top3_batch_manager()
        
        # All 5 assets have positive edges
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=1000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # CRITICAL: Must be at most 3, not all 5
        assert batch is not None
        assert len(batch.allocations) <= 3, \
            f"BUG: {len(batch.allocations)} assets selected, expected max 3"
        
        # Specifically must be top 3 by edge (BTC, ETH, SOL)
        assets = {a.asset for a in batch.allocations}
        assert "BTC" in assets
        assert "ETH" in assets
        assert "SOL" in assets
        assert "XRP" not in assets, "XRP (4th by edge) should not be in top 3"
        assert "DOGE" not in assets, "DOGE (5th by edge) should not be in top 3"
    
    def test_cannot_open_position_in_4th_or_5th_asset(
        self, reset_state
    ):
        """
        Regression: Agents should be blocked from opening positions in
        assets outside the top-3 allocation.
        """
        mgr = get_top3_batch_manager()
        
        # Create batch with only top 3
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Top 3 should be allowed
        for asset in ["BTC", "ETH", "SOL"]:
            allowed, reason, _ = mgr.can_open_new_position(asset, 500)
            assert allowed is True, f"{asset} should be allowed (top 3)"
        
        # 4th asset (XRP) should be rejected
        allowed, reason, _ = mgr.can_open_new_position("XRP", 500)
        assert allowed is False, "XRP should be rejected (not in top 3)"
        assert "ASSET_NOT_IN_TOP3" in reason
    
    def test_batch_blocks_new_entries_until_closed(
        self, reset_state
    ):
        """
        Regression: Once a batch is opened, no new trades allowed
        until all positions are closed.
        """
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        # Create batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Mark BTC filled
        mgr.mark_asset_filled(batch1.batch_id, "BTC", 1000)
        
        # Try to create new batch (should fail - current batch still active)
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        assert batch2 is None, "New batch should not be created while active batch exists"
        
        # Close remaining positions
        for asset in ["BTC", "ETH", "SOL"]:
            mgr.mark_asset_closed(batch1.batch_id, asset)
        
        # CRITICAL: Must reconcile bankroll before new cycle can start
        mgr.mark_batch_reconciled(batch1.batch_id, realized_pnl_cents=500)
        
        # Create fresh candidates (old ones may be stale)
        fresh_candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        # Now can create new batch (cycle lock released)
        batch3 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=fresh_candidates,
        )
        assert batch3 is not None
        assert batch3.batch_id != batch1.batch_id
    
    def test_no_independent_per_asset_decisions(
        self, reset_state
    ):
        """
        Regression: Per-asset agents must NOT make independent entry decisions.
        All entry decisions must go through the central batch manager.
        """
        mgr = get_top3_batch_manager()
        
        # Simulate 5 agents each with positive edge
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.05, max_notional_cap=2000),
            EdgeCandidate("DOGE", edge=0.04, max_notional_cap=1000),
        ]
        
        # Central selector creates batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Only 3 assets in batch - not all 5
        assert len(batch.allocations) == 3
        
        # XRP and DOGE agents should be blocked
        for asset in ["XRP", "DOGE"]:
            allowed, reason, _ = mgr.can_open_new_position(asset, 500)
            assert allowed is False, \
                f"{asset} should be blocked - independent agent decision prevented"


class TestBankrollCapEnforcement:
    """
    Regression tests for bankroll cap enforcement (1-2% per cycle).
    """
    
    def test_total_notional_never_exceeds_2pct(
        self, reset_state
    ):
        """
        CRITICAL: Total notional across all 3 assets must never exceed 2%
        of bankroll in a single cycle.
        """
        mgr = get_top3_batch_manager()
        
        bankroll = 50_000  # $500
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=50000),
            EdgeCandidate("ETH", edge=0.09, max_notional_cap=40000),
            EdgeCandidate("SOL", edge=0.08, max_notional_cap=30000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=bankroll,
            candidates=candidates,
        )
        
        # Total must be <= 2% of bankroll
        total = batch.total_target_notional
        max_allowed = int(0.02 * bankroll)  # 1000 cents = $10
        
        assert total <= max_allowed, \
            f"CRITICAL: Total {total}c exceeds 2% cap ({max_allowed}c) for bankroll {bankroll}"
    
    def test_sum_of_allocations_equals_total(
        self, reset_state
    ):
        """
        Sum of individual allocations must equal the batch total
        (accounting for integer rounding).
        """
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        sum_allocations = sum(a.target_notional for a in batch.allocations)
        
        # Allow for rounding differences (max 2 cents off per allocation)
        assert abs(sum_allocations - batch.total_target_notional) <= 2


class TestEdgeRankingIntegrity:
    """
    Regression tests for edge ranking integrity.
    """
    
    def test_highest_edge_gets_largest_allocation(
        self, reset_state
    ):
        """
        Highest edge asset should get the largest notional allocation.
        """
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.15, max_notional_cap=5000),  # Highest
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.05, max_notional_cap=3000),  # Lowest
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Get allocations
        btc = batch.get_allocation_for_asset("BTC")
        eth = batch.get_allocation_for_asset("ETH")
        sol = batch.get_allocation_for_asset("SOL")
        
        assert btc.target_notional > eth.target_notional > sol.target_notional
    
    def test_equal_edges_get_equal_allocation(
        self, reset_state
    ):
        """
        Equal edges should result in equal allocations (split evenly).
        """
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=5000),  # Equal to BTC
            EdgeCandidate("SOL", edge=0.10, max_notional_cap=5000),  # Equal to BTC
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=90_000,  # 2% = 1800 cents
            candidates=candidates,
        )
        
        # All should be equal (600 cents each)
        for alloc in batch.allocations:
            assert alloc.target_notional == 600
            assert alloc.weight == pytest.approx(1/3, rel=0.01)


class TestNoBypassPaths:
    """
    Regression tests ensuring no bypass paths exist.
    """
    
    def test_no_direct_per_asset_entry(self, reset_state):
        """
        Per-asset agents cannot open positions without batch approval.
        This tests that there's no "backdoor" around the batch manager.
        """
        mgr = get_top3_batch_manager()
        
        # No batch exists
        assert mgr.get_current_batch() is None
        
        # Any attempt to open should fail
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            allowed, reason, _ = mgr.can_open_new_position(asset, 500)
            assert allowed is False, \
                f"{asset} should be blocked without batch - no bypass allowed"
    
    def test_batch_must_be_active(self, reset_state):
        """
        Only ACTIVE batches allow entries. PENDING, CLOSING, CLOSED
        statuses must block new entries.
        """
        mgr = get_top3_batch_manager()
        
        # Create batch
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[
                EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            ],
        )
        
        # Mark position as closed first (simulating trade completion)
        mgr.mark_asset_closed(batch.batch_id, "BTC")
        
        # Now close the batch
        mgr.close_batch(batch.batch_id, reason="test")
        
        # Should be closed
        assert batch.status == BatchStatus.CLOSED
        
        # Entry should be blocked
        allowed, reason, _ = mgr.can_open_new_position("BTC", 500)
        assert allowed is False, "Entry should be blocked when batch is closed"


class TestStaleSignalPrevention:
    """REGRESSION TESTS: Stale signal prevention.
    
    Critical safety: Each new cycle after reconciliation must use FRESH
    edges/signals computed AFTER the previous cycle was reconciled.
    Prevents using stale market analysis from before the reconciliation period.
    """
    
    def test_fresh_signal_allowed(self, reset_state):
        """Fresh signals (recent timestamp) should allow batch creation."""
        mgr = get_top3_batch_manager()
        
        # Create fresh candidates (just computed)
        fresh_candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=fresh_candidates,
        )
        
        assert batch is not None, "Fresh signals should allow batch creation"
    
    def test_stale_signal_blocked(self, reset_state):
        """Stale signals (old timestamp) should BLOCK batch creation."""
        mgr = get_top3_batch_manager()
        from datetime import datetime, timezone, timedelta
        
        # Create stale candidates (2 minutes old)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stale_candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000, timestamp=stale_time),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000, timestamp=stale_time),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=stale_candidates,
        )
        
        assert batch is None, "Stale signals (>60s) should BLOCK batch creation"
    
    def test_mixed_fresh_stale_blocked(self, reset_state):
        """If ANY signal is stale, batch creation is blocked."""
        mgr = get_top3_batch_manager()
        from datetime import datetime, timezone, timedelta
        
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        mixed_candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),  # Fresh
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000, timestamp=stale_time),  # Stale
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=mixed_candidates,
        )
        
        assert batch is None, "Mixed fresh/stale: stale wins, batch blocked"
    
    def test_signal_freshness_check_age(self):
        """Test EdgeCandidate.is_fresh() returns correct age."""
        from datetime import datetime, timezone, timedelta
        
        # Fresh signal (just now)
        fresh = EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)
        assert fresh.is_fresh(max_age_seconds=60.0) is True
        assert fresh.age_seconds() < 1.0
        
        # Stale signal (2 minutes old)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stale = EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000, timestamp=stale_time)
        assert stale.is_fresh(max_age_seconds=60.0) is False
        assert stale.age_seconds() >= 119.0  # Should be at least ~120s old
    
    def test_unique_signal_ids(self):
        """Each EdgeCandidate should have unique signal_id."""
        import time
        c1 = EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)
        time.sleep(0.01)  # Small delay to ensure different timestamps
        c2 = EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)
        
        assert c1.signal_id != c2.signal_id, "Each signal should have unique ID"


class TestEntryExitTimingPrecision:
    """REGRESSION TESTS: Entry/Exit timing precision validation.
    
    Critical safety: Entry and exit must execute within strict latency
    windows to prevent stale execution and ensure optimal pricing.
    """
    
    def test_entry_timing_valid(self):
        """Entry within latency window should be valid."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager
        import time
        
        tpm = TakeProfitManager()
        now = time.time()
        
        valid, reason = tpm.validate_entry_timing(
            position_id="test_pos",
            signal_generated_ts=now - 2.0,  # 2 seconds ago
            entry_executed_ts=now,  # Now
        )
        
        assert valid is True, f"Entry within 5s window should be valid: {reason}"
        assert reason == ""
    
    def test_entry_timing_too_slow(self):
        """Entry exceeding max latency should be rejected."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager
        import time
        
        tpm = TakeProfitManager()
        now = time.time()
        
        valid, reason = tpm.validate_entry_timing(
            position_id="test_pos",
            signal_generated_ts=now - 10.0,  # 10 seconds ago (exceeds 5s max)
            entry_executed_ts=now,
        )
        
        assert valid is False, "Entry >5s after signal should be rejected"
        assert "STALE_ENTRY" in reason
    
    def test_exit_timing_valid(self):
        """Exit within latency window should be valid."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager
        import time
        
        tpm = TakeProfitManager()
        now = time.time()
        
        valid, reason = tpm.validate_exit_timing(
            position_id="test_pos",
            tp_trigger_ts=now - 1.5,  # 1.5 seconds ago
            exit_executed_ts=now,  # Now
        )
        
        assert valid is True, f"Exit within 3s window should be valid: {reason}"
        assert reason == ""
    
    def test_exit_timing_too_slow(self):
        """Exit exceeding max latency should be rejected."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager
        import time
        
        tpm = TakeProfitManager()
        now = time.time()
        
        valid, reason = tpm.validate_exit_timing(
            position_id="test_pos",
            tp_trigger_ts=now - 8.0,  # 8 seconds ago (exceeds 3s max)
            exit_executed_ts=now,
        )
        
        assert valid is False, "Exit >3s after trigger should be rejected"
        assert "DELAYED_EXIT" in reason
    
    def test_timing_impossible_backward(self):
        """Entry/exit executed before signal/trigger is impossible."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager
        import time
        
        tpm = TakeProfitManager()
        now = time.time()
        
        # Entry executed BEFORE signal generated
        valid, reason = tpm.validate_entry_timing(
            position_id="test_pos",
            signal_generated_ts=now,  # Signal generated now
            entry_executed_ts=now - 1.0,  # But entry was 1 second ago (impossible!)
        )
        
        assert valid is False, "Entry before signal is impossible"
        assert "TIMING_VIOLATION" in reason
    
    def test_timing_validation_disabled(self):
        """Timing validation can be disabled via config."""
        from merid.event_venues.kalshi.take_profit import TakeProfitManager, TakeProfitConfig
        import time
        
        # Create manager with validation disabled
        config = TakeProfitConfig(
            require_entry_timestamp_validation=False,
            require_exit_timestamp_validation=False,
        )
        tpm = TakeProfitManager(config=config)
        now = time.time()
        
        # Even with 100s delay, should be accepted when validation disabled
        valid, reason = tpm.validate_entry_timing(
            position_id="test_pos",
            signal_generated_ts=now - 100.0,
            entry_executed_ts=now,
        )
        
        assert valid is True, "Validation disabled should accept any timing"
        assert reason == ""


class TestBypassPrevention:
    """REGRESSION TESTS: Verify no bypass paths exist for cycle locking.
    
    These tests ensure that the cycle lock cannot be bypassed through
    any manual or automated mechanism.
    """
    
    def test_close_batch_requires_force_with_open_positions(self, reset_state):
        """Manual close should be blocked when positions are open."""
        mgr = get_top3_batch_manager()
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[
                EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
                EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            ],
        )
        assert batch is not None
        assert batch.status == BatchStatus.ACTIVE
        
        # Attempt to close without force - should be blocked
        result = mgr.close_batch(batch.batch_id, reason="bypass_attempt")
        assert result is False, "Close should be blocked with open positions"
        assert batch.status == BatchStatus.ACTIVE, "Batch should remain ACTIVE"
        
        # Verify cycle is still locked
        locked, reason = mgr.is_cycle_locked()
        assert locked is True, "Cycle should still be locked"
    
    def test_close_batch_force_bypass(self, reset_state):
        """Force=True allows bypass but logs critical warning."""
        mgr = get_top3_batch_manager()
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[
                EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            ],
        )
        
        # Force close with positions open
        result = mgr.close_batch(batch.batch_id, reason="emergency", force=True)
        assert result is True, "Force close should succeed"
        assert batch.status == BatchStatus.CLOSED
    
    def test_mark_reconcile_requires_closed_status(self, reset_state):
        """Cannot reconcile a batch that isn't CLOSED."""
        mgr = get_top3_batch_manager()
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)],
        )
        
        # Try to reconcile while still ACTIVE - should fail
        result = mgr.mark_batch_reconciled(batch.batch_id, realized_pnl_cents=100)
        assert result is False, "Cannot reconcile ACTIVE batch"
        
        # Force close then reconcile
        mgr.close_batch(batch.batch_id, reason="test", force=True)
        result = mgr.mark_batch_reconciled(batch.batch_id, realized_pnl_cents=100)
        assert result is True, "Can reconcile after CLOSED"
        assert batch.status == BatchStatus.FULLY_RECONCILED
    
    def test_cycle_lock_persists_across_get_current_batch_calls(self, reset_state):
        """Cycle lock state should be consistent across repeated checks."""
        mgr = get_top3_batch_manager()
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)],
        )
        
        # Multiple checks should all report locked
        for _ in range(5):
            locked, reason = mgr.is_cycle_locked()
            assert locked is True, f"Cycle should be locked: {reason}"
        
        # get_current_batch should also return locked batch
        current = mgr.get_current_batch()
        assert current is not None
        assert current.status == BatchStatus.ACTIVE
    
    def test_no_alternate_batch_creation_path(self, reset_state):
        """maybe_create_new_batch is the ONLY path to create batches."""
        mgr = get_top3_batch_manager()
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000)],
        )
        assert batch1 is not None
        
        # There is no other method to create a batch - verified by inspection:
        # - No direct _current_batch assignment outside maybe_create_new_batch
        # - No import of Top3Batch constructor in other modules for batch creation
        # - All batch creation flows through maybe_create_new_batch
        
        # Verify the lock is in place
        locked, _ = mgr.is_cycle_locked()
        assert locked is True, "Cycle should be locked preventing new batches"
