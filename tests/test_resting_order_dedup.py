"""Test for resting order deduplication fix.

Verifies that duplicate resting orders are blocked even when they have
different client_order_ids due to different 5-second time buckets.
"""
from __future__ import annotations

import pytest
from merid.event_venues.kalshi.order_gate import (
    IdempotentOrderStore,
    OrderRecord,
    OrderStatus,
    PreTradeGate,
)


class TestRestingOrderDeduplication:
    """Test resting order deduplication across time buckets."""

    def test_find_resting_duplicate_finds_identical_order(self):
        """Verify find_resting_duplicate finds identical resting orders."""
        store = IdempotentOrderStore()
        
        # Insert a resting order
        record = OrderRecord(
            client_order_id="merid-abc123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.LIVE,
        )
        store.insert_if_absent(record)
        
        # Find duplicate with same parameters but different coid
        duplicate = store.find_resting_duplicate(
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            price_cents=97,
            exclude_coid="merid-different456",
        )
        
        assert duplicate is not None
        assert duplicate.client_order_id == "merid-abc123"
        assert duplicate.price_cents == 97

    def test_find_resting_duplicate_excludes_current_order(self):
        """Verify find_resting_duplicate excludes the current order."""
        store = IdempotentOrderStore()
        
        # Insert a resting order
        record = OrderRecord(
            client_order_id="merid-abc123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.LIVE,
        )
        store.insert_if_absent(record)
        
        # Try to find duplicate with same coid (should return None)
        duplicate = store.find_resting_duplicate(
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            price_cents=97,
            exclude_coid="merid-abc123",  # Same coid
        )
        
        assert duplicate is None

    def test_find_resting_duplicate_different_price(self):
        """Verify find_resting_duplicate does not match different prices."""
        store = IdempotentOrderStore()
        
        # Insert a resting order at 97c
        record = OrderRecord(
            client_order_id="merid-abc123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.LIVE,
        )
        store.insert_if_absent(record)
        
        # Try to find duplicate at 98c (should return None)
        duplicate = store.find_resting_duplicate(
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            price_cents=98,  # Different price
            exclude_coid="merid-different456",
        )
        
        assert duplicate is None

    def test_find_resting_duplicate_different_side(self):
        """Verify find_resting_duplicate does not match different sides."""
        store = IdempotentOrderStore()
        
        # Insert a YES order
        record = OrderRecord(
            client_order_id="merid-abc123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.LIVE,
        )
        store.insert_if_absent(record)
        
        # Try to find duplicate for NO side (should return None)
        duplicate = store.find_resting_duplicate(
            contract_id="KXETH15M-26JUL022100-00",
            side="no",  # Different side
            action="buy",
            price_cents=97,
            exclude_coid="merid-different456",
        )
        
        assert duplicate is None

    def test_find_resting_duplicate_terminal_state_ignored(self):
        """Verify find_resting_duplicate ignores terminal states."""
        store = IdempotentOrderStore()
        
        # Insert a FILLED order (terminal state)
        record = OrderRecord(
            client_order_id="merid-abc123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.FILLED,  # Terminal state
        )
        store.insert_if_absent(record)
        
        # Try to find duplicate (should return None since FILLED is terminal)
        duplicate = store.find_resting_duplicate(
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            price_cents=97,
            exclude_coid="merid-different456",
        )
        
        assert duplicate is None

    def test_pretrade_gate_blocks_resting_duplicate(self):
        """Verify PreTradeGate.check() blocks resting duplicates."""
        gate = PreTradeGate()
        
        # Insert a resting order directly into the store
        record = OrderRecord(
            client_order_id="merid-existing123",
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            status=OrderStatus.LIVE,
        )
        gate.store.insert_if_absent(record)
        
        # Try to submit identical order (different time bucket = different coid)
        verdict = gate.check(
            agent_id="ETH_15M",
            strategy_group="eth_15m",
            contract_id="KXETH15M-26JUL022100-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=97,
            decision_ts=9999999999.0,  # Different time bucket
        )
        
        assert verdict.allowed is False
        assert "resting_duplicate" in verdict.reason
        assert verdict.is_duplicate is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
