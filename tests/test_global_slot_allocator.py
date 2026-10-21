"""
Test suite for Global Slot Allocator

Tests the $3 hard limit enforcement across all 5 assets with slot-based position management.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGlobalSlotAllocator:
    """Test suite for GlobalSlotAllocator."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_basic_import(self):
        """Test that the module can be imported."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        assert GlobalSlotAllocator is not None
        print("✓ Basic import test passed")
    
    def test_singleton_initialization(self):
        """Test that singleton pattern works correctly."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator1 = get_global_slot_allocator()
        allocator2 = get_global_slot_allocator()
        assert allocator1 is allocator2, "Singleton should return same instance"
        print("✓ Singleton initialization test passed")
    
    def test_max_exposure_limit(self):
        """Test that $1 exposure limit is enforced."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Should allow 50c entry
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        assert allocated, f"50c entry should be allowed: {reason}"
        assert slot_id is not None
        
        # Check exposure
        total_exposure = allocator.get_total_exposure()
        assert total_exposure == 0.50, f"Expected 0.50 exposure, got {total_exposure}"
        
        print("✓ Max exposure limit test passed")
    
    def test_entry_price_range_validation(self):
        """Test that entry price must stay inside the resolved profile band."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        min_cents = allocator.min_entry_cents
        max_cents = allocator.max_entry_cents

        # Test that AllocationRequest validates entry price for entry orders
        # Should reject below the band floor
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=min_cents - 1,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            )

        # Should reject above the band ceiling
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=max_cents + 1,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            )

        # Should accept the band floor
        request_min = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=min_cents,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        assert request_min.entry_price_cents == min_cents

        # Should accept the band ceiling
        request_max = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=max_cents,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        assert request_max.entry_price_cents == max_cents
        
        print("✓ Entry price range validation test passed")
    
    def test_exit_order_bypasses_price_validation(self):
        """Test that exit orders bypass entry price validation."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit orders should accept any price (no validation)
        request_exit_low = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=5,  # Below minimum
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        assert request_exit_low.entry_price_cents == 5
        
        request_exit_high = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=99,  # Above maximum
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        assert request_exit_high.entry_price_cents == 99
        
        print("✓ Exit order bypasses price validation test passed")
    
    def test_exit_order_bypasses_slot_allocation(self):
        """Test that exit orders bypass slot allocation even at full capacity."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill $2.00 of the $3.00 capacity (BTC 75c + ETH 75c + SOL 50c = 200c)
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=75,  # $0.75 (max valid entry price)
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated1, _, _ = allocator.request_allocation(request1)
        assert allocated1
        assert allocator.get_total_exposure() == 0.75
        assert allocator.get_available_exposure() == 2.25

        request2 = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=75,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated2, _, _ = allocator.request_allocation(request2)
        assert allocated2
        assert allocator.get_total_exposure() == 1.50
        assert allocator.get_available_exposure() == 1.50

        request3 = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated3, _, _ = allocator.request_allocation(request3)
        assert allocated3
        assert allocator.get_total_exposure() == 2.00
        assert allocator.get_available_exposure() == 1.00

        # Entry order should be rejected when it exceeds the remaining $1.00.
        # 3 contracts at 50c = $1.50 > $1.00 available.
        request_reject = AllocationRequest(
            agent_id="DOGE_15M",
            asset="DOGE",
            ticker="KXDOGE15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False,
            count=3,
        )
        allocated_reject, reason_reject, _ = allocator.request_allocation(request_reject)
        assert not allocated_reject
        # Should be rejected due to insufficient exposure
        
        # Exit order should bypass allocation even at full capacity
        request_exit = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        allocated_exit, reason_exit, slot_id_exit = allocator.request_allocation(request_exit)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        assert slot_id_exit is None  # Exit orders don't get slot IDs
        
        # Exposure should still be $2.00 (exit orders don't consume slots)
        assert allocator.get_total_exposure() == 2.00
        
        print("✓ Exit order bypasses slot allocation test passed")
    
    def test_slot_release_on_closure(self):
        """Test that slots are released when positions close."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_total_exposure() == 0.35
        
        # Release the slot
        released = allocator.release_slot(slot_id, exit_price_cents=99)
        assert released
        assert allocator.get_total_exposure() == 0.0
        assert allocator.get_available_exposure() == 3.0
        
        print("✓ Slot release on closure test passed")
    
    def test_sequential_trading_with_exits(self):
        """Test the sequential trading scenario with early exits."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()

        # Scenario: BTC 75c + ETH 75c + SOL 50c x3 = 300c used, 0c available
        request_btc = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=75,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request_eth = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=75,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request_sol = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False,
            count=3,
        )

        allocated_btc, _, slot_btc = allocator.request_allocation(request_btc)
        allocated_eth, _, slot_eth = allocator.request_allocation(request_eth)
        allocated_sol, _, slot_sol = allocator.request_allocation(request_sol)

        assert allocated_btc and allocated_eth and allocated_sol
        assert abs(allocator.get_total_exposure() - 3.00) < 0.01  # Floating point tolerance
        assert abs(allocator.get_available_exposure() - 0.00) < 0.01

        # Should reject a DOGE entry (capacity is exhausted)
        doge_price = allocator.min_entry_cents
        request_doge = AllocationRequest(
            agent_id="DOGE_15M",
            asset="DOGE",
            ticker="KXDOGE15M-TEST",
            entry_price_cents=doge_price,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated_doge, reason_doge, _ = allocator.request_allocation(request_doge)
        assert not allocated_doge
        assert "Insufficient exposure" in reason_doge

        # Exit order for BTC should be allowed even at full capacity
        request_exit_btc = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        allocated_exit_btc, reason_exit_btc, _ = allocator.request_allocation(request_exit_btc)
        assert allocated_exit_btc
        assert reason_exit_btc == "EXIT_ORDER_BYPASS"

        # BTC closes - release slot
        allocator.release_slot(slot_btc, exit_price_cents=50)
        assert allocator.get_total_exposure() == 2.25
        assert allocator.get_available_exposure() == 0.75

        # Now the DOGE entry should be allowed
        allocated_doge2, _, slot_doge = allocator.request_allocation(request_doge)
        assert allocated_doge2
        assert allocator.get_total_exposure() == pytest.approx(2.25 + doge_price / 100.0)

        print("✓ Sequential trading with exits test passed")
    
    def test_release_by_asset(self):
        """Test releasing all slots for a specific asset."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # 2026-07-13: With MAX_POSITIONS_PER_ASSET=1, we can only have 1 slot per asset
        # Test releasing a single slot for an asset
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST1",
            entry_price_cents=allocator.min_entry_cents,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        allocated1, _, slot1 = allocator.request_allocation(request1)
        assert allocated1
        
        # Second BTC order should be rejected due to per-asset limit
        request2 = AllocationRequest(
            agent_id="BTC_15M",  # Same asset
            asset="BTC",
            ticker="KXBTC15M-TEST2",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        allocated2, reason2, _ = allocator.request_allocation(request2)
        assert not allocated2
        assert "already has" in reason2.lower() or "position" in reason2.lower()
        
        # Release the BTC slot
        released_count = allocator.release_by_asset("BTC")
        assert released_count == 1
        assert allocator.get_total_exposure() == 0.0
        
        print("✓ Release by asset test passed")
    
    def test_clear_stale_slots(self):
        """Test clearing stale slots that have been occupied too long."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        import time
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        
        # Manually set entry time to be old (2 hours ago)
        with allocator._lock:
            slot = allocator._slots[slot_id]
            slot.entry_time = time.time() - 7200  # 2 hours ago
        
        # Clear stale slots with 1 hour max age
        cleared = allocator.clear_stale_slots(max_age_seconds=3600)
        assert cleared == 1
        assert allocator.get_total_exposure() == 0.0
        assert allocator.get_slot_count() == 0
        
        print("✓ Clear stale slots test passed")
    
    def test_sync_with_position_cache(self):
        """Test synchronizing slot allocator with position cache.
        
        CRITICAL FIX (2026-07-31): Tests state drift fix where slots remain allocated
        even though positions no longer exist in the position cache.
        """
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST-ORPHAN",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_total_exposure() == 0.35
        
        # Mock position cache to return empty (position no longer exists)
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get_all_positions.return_value = []  # No positions
            mock_get_cache.return_value = mock_cache
            
            # Sync should remove the orphaned slot
            removed = allocator.sync_with_position_cache()
            assert removed == 1
            assert allocator.get_total_exposure() == 0.0
            assert allocator.get_slot_count() == 0
        
        print("✓ Sync with position cache test passed")
    
    def test_sync_with_position_cache_no_orphans(self):
        """Test sync when all slots have corresponding positions."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST-VALID",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        
        # Mock position cache to return the position
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_position = MagicMock()
            mock_position.market_id = "KXBTC15M-TEST-VALID"
            mock_cache.get_all_positions.return_value = [mock_position]
            mock_get_cache.return_value = mock_cache
            
            # Sync should not remove any slots
            removed = allocator.sync_with_position_cache()
            assert removed == 0
            assert allocator.get_total_exposure() == 0.35
            assert allocator.get_slot_count() == 1
        
        print("✓ Sync with position cache (no orphans) test passed")

    def test_sync_with_position_cache_removes_expired_market(self):
        """Test sync removes slots for markets whose parsed expiry is long past.

        CRITICAL FIX (2026-08-22): Settled/phantom positions can hold a slot open
        and block new $1-cap entries.  sync_with_position_cache must drop slots
        whose market has expired well beyond the close time.
        """
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker
        import time

        allocator = get_global_slot_allocator()

        # Use a 15m ticker whose expiry is well in the past.
        # Ticker: KXBTC15M-26AUG100000-00 -> 2026-08-10 00:00 UTC (expired)
        expired_ticker = "KXBTC15M-26AUG100000-00"
        expiry_ts = parse_expiry_from_ticker(expired_ticker)
        assert expiry_ts > 0.0 and time.time() > expiry_ts + 600

        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker=expired_ticker,
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_slot_count() == 1

        # Mock an empty position cache (the slot should still be cleared due to expiry)
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.get_all_positions.return_value = []
            mock_get_cache.return_value = mock_cache

            removed = allocator.sync_with_position_cache()
            assert removed == 1
            assert allocator.get_slot_count() == 0
            assert allocator.get_total_exposure() == 0.0

        print("✓ Sync with position cache (expired market) test passed")


class TestLaneAwareEntryBand:
    """Bounded admission lanes carry their own verified price band.

    2026-10-20: the pinned_fav lane's 92-98c band exceeded the profile
    25-80c range — once submit-time EV revalidation was fixed, every
    canonical-valid pinned intent died here as ``slot_allocation_error``.
    The lane stamp swaps in the band the lane's own gate verified; the
    exposure math (count * price vs the $3 cap) is unchanged.
    """

    def setup_method(self):
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
        # The repo .env arms maker mode for live (lane band 82-91c); this
        # class pins the taker-mode 92-98c band it was written against.
        os.environ["MERID_PINNED_FAV_MAKER_MODE"] = "0"

    def teardown_method(self):
        os.environ.pop("MERID_PINNED_FAV_MAKER_MODE", None)

    def _req(self, price_cents, lane, ticker="KXXRP15M-TEST", asset="XRP"):
        from merid.risk.global_slot_allocator import AllocationRequest
        return AllocationRequest(
            agent_id="pf_test",
            asset=asset,
            ticker=ticker,
            entry_price_cents=price_cents,
            edge_pct=-10.0,
            spread_cents=1,
            decision_lane=lane,
        )

    def test_pinned_fav_band_admits_92_98(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        allocated, reason, slot_id = allocator.request_allocation(
            self._req(95, "pinned_fav")
        )
        assert allocated, f"95c pinned_fav must fit the lane band: {reason}"
        assert slot_id is not None
        # Exposure still counts at cash notional against the cap.
        assert allocator.get_total_exposure() == pytest.approx(0.95)

    def test_pinned_fav_band_is_bounded(self):
        # The lane band replaces the profile range — it does not widen
        # to 1-99.  Out-of-band lane requests still fail closed.
        with pytest.raises(ValueError, match="outside allowed range"):
            self._req(99, "pinned_fav")   # above lane hi (98)
        with pytest.raises(ValueError, match="outside allowed range"):
            self._req(85, "pinned_fav")   # below lane lo (92)

    def test_generic_request_keeps_profile_ceiling(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        # No lane stamp: a 92c ordinary request still dies at the profile
        # ceiling (80c) — the lane exception is stamp-scoped.
        with pytest.raises(ValueError, match="outside allowed range"):
            self._req(92, None)
        allocated, reason, _ = allocator.request_allocation(self._req(50, None))
        assert allocated, f"50c ordinary request should pass: {reason}"

    def test_can_allocate_lane_band(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        ok, reason = allocator.can_allocate(
            95, asset="XRP", decision_lane="pinned_fav"
        )
        assert ok, reason
        ok, reason = allocator.can_allocate(95, asset="BTC")
        assert not ok and "above maximum" in reason

    def test_can_allocate_maker_band(self):
        """2026-10-21 live blocker: maker-mode pf bids (82-91c band) emitted
        by the lane died at the router as
        ``slot_allocation_failed:Entry price 86c above maximum 80c`` — the
        call site dropped ``decision_lane`` so the profile ceiling applied.
        With the stamp passed, an 86c bid fits the maker band."""
        os.environ["MERID_PINNED_FAV_MAKER_MODE"] = "1"
        try:
            from merid.risk.global_slot_allocator import (
                get_global_slot_allocator,
            )
            allocator = get_global_slot_allocator()
            ok, reason = allocator.can_allocate(
                86, asset="XRP", decision_lane="pinned_fav"
            )
            assert ok, reason
            # Still bounded: above maker hi (91) fails closed, and an
            # unstamped 86c request still dies at the profile ceiling.
            ok, reason = allocator.can_allocate(
                95, asset="XRP", decision_lane="pinned_fav"
            )
            assert not ok and "above maximum" in reason
            ok, reason = allocator.can_allocate(86, asset="XRP")
            assert not ok and "above maximum" in reason
        finally:
            os.environ["MERID_PINNED_FAV_MAKER_MODE"] = "0"

    def test_settlement_lane_extends_ceiling(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        allocated, reason, _ = allocator.request_allocation(
            self._req(96, "settlement_convergence")
        )
        assert allocated, f"96c settlement intent must pass: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
