"""
Comprehensive test for $1 allocation rule with up to 2 contracts per asset enforcement.

This test validates the critical fixes applied on 2026-07-31 and 2026-08-22 to ensure:
1. Each asset can trade up to 2 contracts within the $1 cap
2. Total contracts across all assets are bounded by the $1 exposure cap
3. Entry orders are rejected if count is outside [1, 2]
4. Exit orders can have count > 2 for multi-contract closes
5. Position cache validates contract count limits
6. Slot allocator validates contract count limits
7. Global allocator validates contract count limits
"""

import pytest
from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate


class Test1ContractAllocationRule:
    """Test suite for $1 allocation rule with 1 contract per asset enforcement."""
    
    def test_allocation_request_count_validation_entry(self):
        """Test that AllocationRequest validates count in [1, 2] for entry orders."""
        # Valid entry order with count=1 should pass
        valid_request = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=False,
            count=1
        )
        assert valid_request.count == 1

        # Valid entry order with count=2 should pass (2026-08-22: max 2 contracts per order)
        valid_request_2 = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=False,
            count=2
        )
        assert valid_request_2.count == 2

        # Invalid entry order with count=3 should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            invalid_request = AllocationRequest(
                agent_id="test_agent",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=50,
                edge_pct=5.0,
                spread_cents=2,
                confidence=0.8,
                is_exit_order=False,
                count=3
            )
        assert "between 1 and 2" in str(exc_info.value)
    
    def test_allocation_request_count_validation_exit(self):
        """Test that AllocationRequest allows count>1 for exit orders."""
        # Valid exit order with count=1 should pass
        valid_exit = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=True,
            count=1
        )
        assert valid_exit.count == 1
        
        # Valid exit order with count=3 should pass (multi-contract close)
        valid_multi_exit = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=True,
            count=3
        )
        assert valid_multi_exit.count == 3
        
        # Invalid exit order with count=0 should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            invalid_exit = AllocationRequest(
                agent_id="test_agent",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=50,
                edge_pct=5.0,
                spread_cents=2,
                confidence=0.8,
                is_exit_order=True,
                count=0
            )
        assert "count>0" in str(exc_info.value)
    
    def test_global_slot_allocator_count_validation(self):
        """Test that GlobalSlotAllocator enforces count in [1, 2] for entry orders."""
        allocator = GlobalSlotAllocator()

        # Valid entry order with count=1 should be allocated
        valid_request = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=False,
            count=1
        )
        allocated, reason, slot_id = allocator.request_allocation(valid_request)
        assert allocated is True
        assert slot_id is not None

        # Release the slot
        allocator.release_slot(slot_id)

        # Valid entry order with count=2 should also be allocated (2026-08-22)
        valid_request_2 = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=False,
            count=2
        )
        allocated_2, reason_2, slot_id_2 = allocator.request_allocation(valid_request_2)
        assert allocated_2 is True
        assert slot_id_2 is not None
        assert allocator.get_total_exposure() == 1.0  # 2 contracts @ 50c

        allocator.release_slot(slot_id_2)

        # Invalid entry order with count=3 should raise ValueError at creation time
        # (validation happens in AllocationRequest.__post_init__)
        with pytest.raises(ValueError) as exc_info:
            invalid_request = AllocationRequest(
                agent_id="test_agent",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=50,
                edge_pct=5.0,
                spread_cents=2,
                confidence=0.8,
                is_exit_order=False,
                count=3
            )
        assert "between 1 and 2" in str(exc_info.value)
    
    def test_global_slot_allocator_exit_order_bypass(self):
        """Test that exit orders bypass count validation in slot allocator."""
        allocator = GlobalSlotAllocator()
        
        # Exit order with count=3 should bypass allocation (no slot needed)
        exit_request = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=True,
            count=3
        )
        allocated, reason, slot_id = allocator.request_allocation(exit_request)
        assert allocated is True
        assert reason == "EXIT_ORDER_BYPASS"
        assert slot_id is None
    
    def test_global_allocator_count_filtering(self):
        """Test that GlobalAllocator filters candidates with count outside [1, 2]."""
        allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=0.01)

        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,  # Valid
                edge_pct=5.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=10,
                count=3,  # Invalid - exceeds max 2, should be filtered
                edge_pct=4.0,
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL",
                ticker="KXSOL15M-TEST",
                side="yes",
                action="buy",
                price_cents=20,
                count=1,  # Valid
                edge_pct=3.0,
                confidence=0.6,
                model_prob=0.5,
                agent_name="SOL_15M"
            ),
        ]

        chosen = allocator.allocate(candidates, current_positions={})

        # Only BTC and SOL should be chosen (ETH filtered due to count=3)
        assert len(chosen) == 2
        assets = [c.asset for c in chosen]
        assert "BTC" in assets
        assert "SOL" in assets
        assert "ETH" not in assets

        # Verify all chosen have count in [1, 2]
        for candidate in chosen:
            assert 1 <= candidate.count <= 2
    
    def test_position_slot_contracts_tracking(self):
        """Test that PositionSlot tracks contract count correctly."""
        from merid.risk.global_slot_allocator import PositionSlot

        # Create slot with 1 contract (default)
        slot1 = PositionSlot(
            slot_id="test_slot_1",
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            entry_time=1234567890.0,
            count=1
        )
        assert slot1.count == 1
        assert slot1.exposure_usd == 0.50  # 50c * 1 contract

        # Create slot with multiple contracts (allowed for position tracking)
        slot2 = PositionSlot(
            slot_id="test_slot_2",
            agent_id="test_agent",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=30,
            entry_time=1234567890.0,
            count=3
        )
        assert slot2.count == 3
        assert slot2.exposure_usd == 0.90  # 30c * 3 contracts
    
    def test_1_contract_per_asset_enforcement(self):
        """Test that only 1 contract per asset is allowed."""
        allocator = GlobalSlotAllocator()
        
        # First BTC order with count=1 should succeed
        request1 = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8,
            is_exit_order=False,
            count=1
        )
        allocated1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert allocated1 is True
        
        # Second BTC order should be rejected (per-asset limit)
        request2 = AllocationRequest(
            agent_id="test_agent",
            asset="BTC",
            ticker="KXBTC15M-TEST2",
            entry_price_cents=30,
            edge_pct=4.0,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False,
            count=1
        )
        allocated2, reason2, slot_id2 = allocator.request_allocation(request2)
        assert allocated2 is False
        assert "already has" in reason2
        
        # ETH order should succeed (different asset)
        request3 = AllocationRequest(
            agent_id="test_agent",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=30,
            edge_pct=4.0,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False,
            count=1
        )
        allocated3, reason3, slot_id3 = allocator.request_allocation(request3)
        assert allocated3 is True
        
        # Total exposure should be $0.80 (50c + 30c)
        assert allocator.get_total_exposure() == 0.80
    
    def test_1_cap_with_multiple_assets(self):
        """Test that GlobalAllocator enforces the $1 cap across multiple assets."""
        allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=0.01)

        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=5.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M",
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=4.0,
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M",
            ),
            OrderCandidate(
                asset="SOL",
                ticker="KXSOL15M-TEST",
                side="yes",
                action="buy",
                price_cents=25,
                count=1,
                edge_pct=3.0,
                confidence=0.6,
                model_prob=0.5,
                agent_name="SOL_15M",
            ),
        ]

        chosen = allocator.allocate(candidates, current_positions={})
        chosen_assets = [c.asset for c in chosen]

        # BTC+ETH+SOL = $1.05, so one must be rejected by the $1 knapsack cap.
        # SOL has the lowest edge, so the optimal combination is BTC + ETH = $0.80.
        assert len(chosen) == 2
        assert "BTC" in chosen_assets
        assert "ETH" in chosen_assets
        assert "SOL" not in chosen_assets
        assert sum(c.notional_usd for c in chosen) == 0.80


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
