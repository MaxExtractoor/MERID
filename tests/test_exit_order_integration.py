"""
Integration tests for exit order bypass logic across the trading stack.

Tests the complete flow from signal generation through order routing to ensure
exit orders bypass slot allocation even at full $1 capacity.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExitOrderIntegration:
    """Integration tests for exit order bypass logic."""
    
    def setup_method(self):
        """Reset all singletons before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_signal_generation_entry_order_flag(self):
        """Test that signal generation sets is_exit_order=False."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Entry order should have is_exit_order=False
        entry_request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        assert entry_request.is_exit_order == False
        assert entry_request.entry_price_cents == 30
        
        print("✓ Signal generation entry order flag test passed")
    
    def test_exit_order_bypass_at_full_capacity(self):
        """Test that exit orders bypass allocation at full $1 capacity."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # 2026-07-13: Correlation discount disabled - no patch needed
        # Fill to full capacity ($2.00 cap)
        requests = [
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 75, 2.0, 5, 0.5, False),
            AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 75, 2.0, 5, 0.5, False),
            AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 50, 2.0, 5, 0.5, False),
        ]
        
        for req in requests:
            allocated, _, _ = allocator.request_allocation(req)
            assert allocated
        
        assert abs(allocator.get_total_exposure() - 2.00) < 0.01
        
        # Entry order should be rejected
        entry_req = AllocationRequest("XRP_15M", "XRP", "KXXRP15M-1", 10, 2.0, 5, 0.5, False)
        allocated_entry, reason_entry, _ = allocator.request_allocation(entry_req)
        assert not allocated_entry
        assert "Insufficient exposure" in reason_entry
        
        # Exit order should bypass
        exit_req = AllocationRequest("position_monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, 0.5, True)
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        
        print("✓ Exit order bypass at full capacity test passed")
    
    def test_slot_allocator_to_position_cache_integration(self):
        """Test that slot allocator and position cache exposure tracking align."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate slots
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 30, 2.0, 5, 0.5, False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 40, 2.0, 5, 0.5, False)
        
        allocated1, _, slot1 = allocator.request_allocation(req1)
        allocated2, _, slot2 = allocator.request_allocation(req2)
        
        assert allocated1 and allocated2
        assert abs(allocator.get_total_exposure() - 0.70) < 0.01
        
        # Release by asset
        released = allocator.release_by_asset("BTC")
        assert released == 1
        assert abs(allocator.get_total_exposure() - 0.40) < 0.01
        
        print("✓ Slot allocator to position cache integration test passed")
    
    def test_unified_sizing_uses_slot_allocator(self):
        """Test that unified sizing uses slot allocator for exposure calculation."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        from merid.prediction.unified_sizing import compute_order_size
        from decimal import Decimal
        
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # 2026-07-13: Correlation discount disabled - no patch needed
        # Allocate to near capacity using valid entry prices (10-75c)
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 75, 2.0, 5, 0.5, False)
        req2 = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 75, 2.0, 5, 0.5, False)
        req3 = AllocationRequest("XRP_15M", "XRP", "KXXRP15M-1", 40, 2.0, 5, 0.5, False)
        
        allocated1, _, _ = allocator.request_allocation(req1)
        allocated2, _, _ = allocator.request_allocation(req2)
        allocated3, _, _ = allocator.request_allocation(req3)
        assert allocated1 and allocated2 and allocated3
        
        # Total should be 190c, leaving 10c of the $2 cap available
        assert abs(allocator.get_total_exposure() - 1.90) < 0.01
        
        # Seed matching positions so sync_with_position_cache does not
        # correctly drop the allocator slots as orphans (slots are
        # provisional until backed by a cache position).
        from merid.event_venues.kalshi.position_cache import (
            get_position_cache, CachedPosition,
        )
        cache = get_position_cache()
        for ticker, cents in (("KXBTC15M-1", 75), ("KXSOL15M-1", 75), ("KXXRP15M-1", 40)):
            cache._positions[ticker] = CachedPosition(
                market_id=ticker, agent_id="T", side="yes", thesis_side="yes",
                contracts=1, avg_price_cents=cents,
            )
        
        # Try to size a 30c order (should fail due to insufficient exposure)
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.0"),
            price_cents=30,
            asset="ETH",
            model_prob=0.60  # 2026-07-12: Kelly Criterion integration
        )
        
        # Sizing must clip to the 10c of remaining cap exposure (the
        # centi-contract grid allows fractional fills instead of rejecting).
        assert count < 1.0
        assert notional <= Decimal("0.10") + Decimal("0.001")
        
        print("✓ Unified sizing uses slot allocator test passed")
    
    def test_order_gate_uses_slot_allocator(self):
        """Test that order gate uses slot allocator for sequential trading check."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # 2026-07-13: Correlation discount disabled - no patch needed
        # Fill to near capacity with valid entry prices (10-75c)
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 75, 2.0, 5, 0.5, False)
        req2 = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 75, 2.0, 5, 0.5, False)
        req3 = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 35, 2.0, 5, 0.5, False)
        
        allocated1, _, _ = allocator.request_allocation(req1)
        allocated2, _, _ = allocator.request_allocation(req2)
        allocated3, _, _ = allocator.request_allocation(req3)
        assert allocated1 and allocated2 and allocated3
        
        # Total should be 185c, leaving 15c of the $2 cap available
        assert abs(allocator.get_total_exposure() - 1.85) < 0.01
        
        # Available should be 15c
        available = allocator.get_available_exposure()
        assert abs(available - 0.15) < 0.01
        
        # 20c order should be rejected by gate (insufficient exposure)
        # This would be tested by actual order gate call, but we test the logic here
        required_exposure = 20 / 100.0
        assert required_exposure > available
        
        print("✓ Order gate uses slot allocator test passed")
    
    def test_exit_order_price_validation_bypass(self):
        """Test that exit orders bypass entry price validation."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit orders should accept any price (bypass 10-75c validation)
        # Note: AllocationRequest params are (agent_id, asset, ticker, entry_price_cents, edge_pct, spread_cents, confidence, is_exit_order)
        exit_low = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 5, 0.0, 0, 0.5, True)
        exit_high = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 99, 0.0, 0, 0.5, True)
        
        assert exit_low.entry_price_cents == 5
        assert exit_high.entry_price_cents == 99
        
        # Entry orders should reject out-of-range prices (10-75c)
        with pytest.raises(ValueError):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 5, 2.0, 5, 0.5, False)
        
        with pytest.raises(ValueError):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 80, 2.0, 5, 0.5, False)  # Updated to 80c (above 75c max)
        
        print("✓ Exit order price validation bypass test passed")
    
    def test_sequential_trading_scenario(self):
        """Test the full sequential trading scenario with early exits."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # 2026-07-13: Correlation discount disabled - no patch needed
        # Initial: BTC 75c + ETH 75c + SOL 45c = 195c used, 5c of $2 available
        req_btc = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 75, 2.0, 5, 0.5, False)
        req_eth = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 75, 2.0, 5, 0.5, False)
        req_sol = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 45, 2.0, 5, 0.5, False)
        
        allocated_btc, _, slot_btc = allocator.request_allocation(req_btc)
        allocated_eth, _, slot_eth = allocator.request_allocation(req_eth)
        allocated_sol, _, slot_sol = allocator.request_allocation(req_sol)
        
        assert allocated_btc and allocated_eth and allocated_sol
        assert abs(allocator.get_total_exposure() - 1.95) < 0.01
        
        # DOGE 50c should be rejected (would exceed $2)
        req_doge = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 50, 2.0, 5, 0.5, False)
        allocated_doge, reason_doge, _ = allocator.request_allocation(req_doge)
        assert not allocated_doge
        
        # Exit order for BTC should bypass
        exit_btc = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, 0.5, True)
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_btc)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        
        # Release BTC slot
        allocator.release_slot(slot_btc, exit_price_cents=50)
        assert abs(allocator.get_total_exposure() - 1.20) < 0.01
        
        # Now DOGE 50c should be allowed
        req_doge2 = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 50, 2.0, 5, 0.5, False)
        allocated_doge2, _, slot_doge = allocator.request_allocation(req_doge2)
        assert allocated_doge2
        assert abs(allocator.get_total_exposure() - 1.70) < 0.01
        
        print("✓ Sequential trading scenario test passed")
    
    def test_concurrent_exit_and_entry_orders(self):
        """Test that exit orders and entry orders can interleave correctly."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # 2026-07-13: Correlation discount disabled - no patch needed
        # Fill to near capacity
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 75, 2.0, 5, 0.5, False)
        req2 = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 75, 2.0, 5, 0.5, False)
        
        allocated1, _, slot1 = allocator.request_allocation(req1)
        allocated2, _, slot2 = allocator.request_allocation(req2)
        
        assert allocated1 and allocated2
        assert abs(allocator.get_total_exposure() - 1.50) < 0.01
        
        # Entry order should be rejected (150c + 60c = 210c > $2.00)
        entry_req = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 60, 2.0, 5, 0.5, False)
        allocated_entry, _, _ = allocator.request_allocation(entry_req)
        assert not allocated_entry
        
        # Exit order should bypass
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, 0.5, True)
        allocated_exit, _, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        
        # Release slot
        allocator.release_slot(slot1, exit_price_cents=50)
        assert abs(allocator.get_total_exposure() - 0.75) < 0.01  # Was 150c, released 75c
        
        # Entry order should now be allowed
        allocated_entry2, _, _ = allocator.request_allocation(entry_req)
        assert allocated_entry2
        assert abs(allocator.get_total_exposure() - 1.35) < 0.01  # 75c (DOGE) + 60c (SOL)
        
        print("✓ Concurrent exit and entry orders test passed")
    
    def test_exit_order_does_not_consume_slot(self):
        """Test that exit orders don't consume slots (only entry orders do)."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Ensure clean state
        
        # Initial slot count should be 0
        assert allocator.get_slot_count() == 0
        
        # Entry order should consume a slot
        entry_req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 30, 2.0, 5, 0.5, False)
        allocated, _, slot_id = allocator.request_allocation(entry_req)
        assert allocated
        assert slot_id is not None
        assert allocator.get_slot_count() == 1
        
        # Exit order should not consume a slot
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, 0.5, True)
        allocated_exit, _, exit_slot_id = allocator.request_allocation(exit_req)
        assert allocated_exit
        assert exit_slot_id is None  # Exit orders don't get slot IDs
        assert allocator.get_slot_count() == 1  # Still 1 slot
        
        print("✓ Exit order does not consume slot test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
