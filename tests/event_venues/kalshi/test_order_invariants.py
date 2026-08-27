"""CI contract tests for order-flow invariants.

Tests validate the four non-negotiable invariants:

1. **Single ownership** — Only one agent can hold a lease for a given
   (venue, contract, side, strategy) at a time.

2. **Idempotent order submission** — The same logical decision always
   produces the same ``client_order_id``, and duplicate submissions are
   blocked while an order is pending/live/filled.

3. **Fill awareness** — If target quantity is already satisfied, new
   orders for the same (contract, side, strategy) are rejected.

4. **Centralized gate** — All order paths (agent grid + CT) run through
   the same ``PreTradeGate.check()`` before any external API call.

Run with::

    pytest tests/event_venues/kalshi/test_order_invariants.py -v

NOTE: Implementation has changed - order state machine, fill awareness logic, and exit order handling have evolved.
Order invariants are tested through integration tests in the production stack.
"""

from __future__ import annotations

import threading
import time
import pytest

from merid.event_venues.kalshi.contract_lease import (
    ContractLeaseRegistry,
    LeaseKey,
    Lease,
    LeaseMetrics,
    reset_contract_lease_registry_for_testing,
    get_contract_lease_registry,
)
from merid.event_venues.kalshi.order_gate import (
    PreTradeGate,
    IdempotentOrderStore,
    OrderStatus,
    GateVerdict,
    deterministic_client_order_id,
    DECISION_BUCKET_WIDTH_S,
    reset_pre_trade_gate_for_testing,
    get_pre_trade_gate,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset global singletons before and after each test."""
    reset_contract_lease_registry_for_testing()
    reset_pre_trade_gate_for_testing()
    yield
    reset_contract_lease_registry_for_testing()
    reset_pre_trade_gate_for_testing()


@pytest.fixture
def registry():
    return ContractLeaseRegistry(default_ttl_s=10.0)


@pytest.fixture
def gate():
    return PreTradeGate()


KEY_BTC = LeaseKey(
    venue="kalshi",
    contract_id="KXBTC-25DEC-T100000",
    side="yes",
    strategy_group="btc_15m",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Single Ownership / Contract Lease Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContractLeaseInvariant:
    """Only one agent may own a (venue, contract, side, strategy) at a time."""

    def test_acquire_returns_lease(self, registry):
        lease = registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        assert lease is not None
        assert lease.owner_agent_id == "agent_A"

    def test_second_agent_blocked(self, registry):
        """Core invariant: second agent gets None (conflict)."""
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        conflict = registry.acquire(KEY_BTC, owner_agent_id="agent_B")
        assert conflict is None

    def test_same_agent_reacquire_is_renewal(self, registry):
        """Same owner re-acquiring extends TTL, not a conflict."""
        lease1 = registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        lease2 = registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        assert lease2 is not None
        assert lease2.renewals == 1

    def test_release_allows_new_owner(self, registry):
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        released = registry.release(KEY_BTC, owner_agent_id="agent_A")
        assert released is True
        lease = registry.acquire(KEY_BTC, owner_agent_id="agent_B")
        assert lease is not None
        assert lease.owner_agent_id == "agent_B"

    def test_release_denied_wrong_owner(self, registry):
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        released = registry.release(KEY_BTC, owner_agent_id="agent_B")
        assert released is False

    def test_expired_lease_allows_new_owner(self):
        """After TTL expires, another agent can claim the contract."""
        reg = ContractLeaseRegistry(default_ttl_s=1.0)  # 1.0s is the enforced minimum
        reg.acquire(KEY_BTC, owner_agent_id="agent_A")
        time.sleep(1.5)
        lease = reg.acquire(KEY_BTC, owner_agent_id="agent_B")
        assert lease is not None
        assert lease.owner_agent_id == "agent_B"

    def test_transfer_changes_ownership(self, registry):
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        ok = registry.transfer(KEY_BTC, from_agent_id="agent_A", to_agent_id="agent_B")
        assert ok is True
        assert registry.owner_of(KEY_BTC) == "agent_B"

    def test_transfer_denied_wrong_from(self, registry):
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        ok = registry.transfer(KEY_BTC, from_agent_id="agent_B", to_agent_id="agent_C")
        assert ok is False
        assert registry.owner_of(KEY_BTC) == "agent_A"

    def test_metrics_track_conflicts(self, registry):
        registry.acquire(KEY_BTC, owner_agent_id="agent_A")
        registry.acquire(KEY_BTC, owner_agent_id="agent_B")
        registry.acquire(KEY_BTC, owner_agent_id="agent_C")
        m = registry.get_metrics()
        assert m["conflicts"] == 2
        assert m["acquired"] == 1

    def test_concurrent_agents_only_one_wins(self, registry):
        """Simulate two threads racing to acquire the same lease."""
        results = {}

        def try_acquire(agent_id):
            lease = registry.acquire(KEY_BTC, owner_agent_id=agent_id)
            results[agent_id] = lease is not None

        t1 = threading.Thread(target=try_acquire, args=("agent_A",))
        t2 = threading.Thread(target=try_acquire, args=("agent_B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        winners = [a for a, won in results.items() if won]
        assert len(winners) == 1, f"Expected exactly 1 winner, got {winners}"

    def test_different_strategies_independent(self, registry):
        """Different strategy groups can own the same contract independently."""
        key_a = LeaseKey("kalshi", "KXBTC-25DEC-T100000", "yes", "btc_15m")
        key_b = LeaseKey("kalshi", "KXBTC-25DEC-T100000", "yes", "btc_hourly")
        la = registry.acquire(key_a, owner_agent_id="agent_A")
        lb = registry.acquire(key_b, owner_agent_id="agent_B")
        assert la is not None
        assert lb is not None

    def test_different_sides_independent(self, registry):
        key_yes = LeaseKey("kalshi", "KXBTC-25DEC-T100000", "yes", "btc_15m")
        key_no = LeaseKey("kalshi", "KXBTC-25DEC-T100000", "no", "btc_15m")
        la = registry.acquire(key_yes, owner_agent_id="agent_A")
        lb = registry.acquire(key_no, owner_agent_id="agent_B")
        assert la is not None
        assert lb is not None

    def test_prune_expired(self):
        reg = ContractLeaseRegistry(default_ttl_s=1.0)  # 1.0s is the enforced minimum
        reg.acquire(KEY_BTC, owner_agent_id="agent_A")
        time.sleep(1.5)
        pruned = reg.prune_expired()
        assert pruned == 1
        assert reg.active_count() == 0

    def test_force_release_all(self, registry):
        for i in range(5):
            key = LeaseKey("kalshi", f"TICKER-{i}", "yes", "strat")
            registry.acquire(key, owner_agent_id=f"agent_{i}")
        count = registry.force_release_all("test")
        assert count == 5
        assert registry.active_count() == 0

    def test_leases_for_agent(self, registry):
        for i in range(3):
            key = LeaseKey("kalshi", f"TICKER-{i}", "yes", "strat")
            registry.acquire(key, owner_agent_id="agent_A")
        key_other = LeaseKey("kalshi", "TICKER-99", "yes", "strat")
        registry.acquire(key_other, owner_agent_id="agent_B")
        assert len(registry.leases_for_agent("agent_A")) == 3
        assert len(registry.leases_for_agent("agent_B")) == 1

    def test_singleton_returns_same_instance(self):
        r1 = get_contract_lease_registry()
        r2 = get_contract_lease_registry()
        assert r1 is r2


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Deterministic client_order_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeterministicClientOrderId:
    """Same decision → same client_order_id.  Different decision → different."""

    def test_same_inputs_same_id(self):
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts)
        assert a == b

    def test_within_same_bucket_same_id(self):
        """Decisions within the same time bucket are considered the same."""
        base_ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, base_ts)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, base_ts + 30)
        assert a == b  # Both in same 60s bucket

    def test_different_bucket_different_id(self):
        """Decisions in different time buckets produce different IDs."""
        base_ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, base_ts)
        b = deterministic_client_order_id(
            "ag1", "btc_15m", "KXBTC", "yes", 10,
            base_ts + DECISION_BUCKET_WIDTH_S + 1,
        )
        assert a != b

    def test_different_agent_different_id(self):
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts)
        b = deterministic_client_order_id("ag2", "btc_15m", "KXBTC", "yes", 10, ts)
        assert a != b

    def test_different_side_different_id(self):
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "no", 10, ts)
        assert a != b

    def test_different_qty_different_id(self):
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 20, ts)
        assert a != b

    def test_different_price_different_id(self):
        """BUG-0312: Different prices in same bucket must produce different IDs.

        This prevents the duplicate gate from blocking legitimate multi-leg
        orders (e.g., buy YES at 45¢ and sell YES at 55¢) as duplicates.
        """
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts, 45)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts, 55)
        assert a != b, "Different prices should produce different client_order_ids"

    def test_same_price_same_id(self):
        """Same price produces same ID (retry idempotency)."""
        ts = 1700000000.0
        a = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts, 50)
        b = deterministic_client_order_id("ag1", "btc_15m", "KXBTC", "yes", 10, ts, 50)
        assert a == b, "Same price should produce same client_order_id for retries"

    def test_id_has_merid_prefix(self):
        coid = deterministic_client_order_id("ag1", "s", "T", "yes", 1, 1.0)
        assert coid.startswith("merid-")

    def test_id_length_consistent(self):
        coid = deterministic_client_order_id("ag1", "s", "T", "yes", 1, 1.0)
        # "merid-" (6) + 32 hex chars = 38
        assert len(coid) == 38


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Idempotent Order Store / Duplicate Blocking
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdempotentOrderStore:
    """Duplicate orders (same client_order_id) are blocked."""

    def test_insert_and_lookup(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        rec = OrderRecord(
            client_order_id="coid-1",
            agent_id="ag1",
            strategy_group="btc_15m",
            contract_id="KXBTC",
            side="yes",
            action="buy",
            target_count=10,
            price_cents=55,
        )
        inserted, existing = store.insert_if_absent(rec)
        assert inserted is True
        assert existing is None
        assert store.lookup("coid-1") is not None

    def test_duplicate_insert_blocked(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        rec = OrderRecord(
            client_order_id="coid-1",
            agent_id="ag1",
            strategy_group="btc_15m",
            contract_id="KXBTC",
            side="yes",
            action="buy",
            target_count=10,
            price_cents=55,
        )
        store.insert_if_absent(rec)
        inserted2, existing2 = store.insert_if_absent(rec)
        assert inserted2 is False
        assert existing2 is not None

    def test_status_transitions(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        rec = OrderRecord(
            client_order_id="coid-1",
            agent_id="ag1",
            strategy_group="btc_15m",
            contract_id="KXBTC",
            side="yes",
            action="buy",
            target_count=10,
            price_cents=55,
        )
        store.insert_if_absent(rec)
        store.mark_submitted("coid-1", "venue-123")
        assert store.lookup("coid-1").status == OrderStatus.SUBMITTED
        store.mark_filled("coid-1", 10)
        assert store.lookup("coid-1").status == OrderStatus.FILLED

    def test_filled_count_for_contract(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        for i in range(3):
            rec = OrderRecord(
                client_order_id=f"coid-{i}",
                agent_id="ag1",
                strategy_group="btc_15m",
                contract_id="KXBTC",
                side="yes",
                action="buy",
                target_count=5,
                price_cents=55,
            )
            store.insert_if_absent(rec)
            store.mark_submitted(f"coid-{i}", f"venue-{i}")
            store.mark_filled(f"coid-{i}", 5)
        total = store.filled_count_for_contract("KXBTC", "yes", "btc_15m")
        # filled_count_for_contract returns canonical centi-contracts
        assert total == 1500

    def test_has_live_order(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        rec = OrderRecord(
            client_order_id="coid-live",
            agent_id="ag1",
            strategy_group="btc_15m",
            contract_id="KXBTC",
            side="yes",
            action="buy",
            target_count=10,
            price_cents=55,
        )
        store.insert_if_absent(rec)
        store.mark_submitted("coid-live")
        assert store.has_live_order("KXBTC", "yes", "btc_15m") is True
        store.mark_canceled("coid-live")
        assert store.has_live_order("KXBTC", "yes", "btc_15m") is False

    def test_prune_old_removes_terminal(self):
        store = IdempotentOrderStore()
        from merid.event_venues.kalshi.order_gate import OrderRecord
        rec = OrderRecord(
            client_order_id="coid-old",
            agent_id="ag1",
            strategy_group="btc_15m",
            contract_id="KXBTC",
            side="yes",
            action="buy",
            target_count=10,
            price_cents=55,
        )
        store.insert_if_absent(rec)
        store.mark_submitted("coid-old", "venue-old")
        store.mark_filled("coid-old", 10)
        # Force the record to look old
        store._orders["coid-old"].updated_at = time.time() - 100000
        pruned = store.prune_old(ttl_s=1.0)
        assert pruned == 1
        assert store.lookup("coid-old") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PreTradeGate Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreTradeGate:
    """Gate enforces dedup + fill-awareness as single entry point."""

    def test_first_order_allowed(self, gate):
        v = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=1700000000.0,
        )
        assert v.allowed is True
        assert v.client_order_id.startswith("merid-")
        assert v.is_duplicate is False

    def test_duplicate_blocked(self, gate):
        """Same decision within the same time bucket → duplicate."""
        ts = 1700000000.0
        v1 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        assert v1.allowed is True

        v2 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts + 5,
        )
        assert v2.allowed is False
        assert v2.is_duplicate is True
        assert "duplicate" in v2.reason

    def test_different_bucket_allowed(self, gate):
        """Same decision in a new time bucket → new order."""
        ts = 1700000000.0
        v1 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        assert v1.allowed is True
        # Mark the first one as canceled so it doesn't block
        gate.mark_canceled(v1.client_order_id)

        v2 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55,
            decision_ts=ts + DECISION_BUCKET_WIDTH_S + 1,
        )
        assert v2.allowed is True
        assert v2.client_order_id != v1.client_order_id

    def test_already_satisfied_blocked(self, gate):
        """If target qty is already filled, new order is rejected."""
        ts = 1700000000.0
        v1 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        gate.mark_submitted(v1.client_order_id, "venue-abc")
        gate.mark_filled(v1.client_order_id, 10)

        # New decision, same contract — but existing_filled >= target
        v2 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55,
            decision_ts=ts + DECISION_BUCKET_WIDTH_S + 1,
            existing_filled=10,
        )
        assert v2.allowed is False
        assert "already_satisfied" in v2.reason

    def test_sell_orders_skip_fill_check(self, gate):
        """Sell/close orders should not be blocked by fill awareness."""
        ts = 1700000000.0
        v = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="sell",
            target_count=10, price_cents=55, decision_ts=ts,
            existing_filled=10,
        )
        assert v.allowed is True

    def test_mark_submitted_and_filled(self, gate):
        ts = 1700000000.0
        v = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        gate.mark_submitted(v.client_order_id, "venue-abc")
        rec = gate.store.lookup(v.client_order_id)
        assert rec.status == OrderStatus.SUBMITTED
        assert rec.venue_order_id == "venue-abc"

        gate.mark_filled(v.client_order_id, 10)
        rec = gate.store.lookup(v.client_order_id)
        assert rec.status == OrderStatus.FILLED

    def test_mark_rejected_frees_slot(self, gate):
        """After rejection, the same coid can be re-checked (status=REJECTED
        is terminal, so a new decision bucket is needed)."""
        ts = 1700000000.0
        v1 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        gate.mark_rejected(v1.client_order_id, "venue_error")
        rec = gate.store.lookup(v1.client_order_id)
        assert rec.status == OrderStatus.REJECTED

    def test_metrics_counters(self, gate):
        ts = 1700000000.0
        gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        # Duplicate
        gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts + 5,
        )
        m = gate.get_metrics()
        assert m["checks"] == 2
        assert m["allowed"] == 1
        assert m["blocked_duplicate"] == 1

    def test_singleton_returns_same_instance(self):
        g1 = get_pre_trade_gate()
        g2 = get_pre_trade_gate()
        assert g1 is g2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Concurrent Ownership Invariant (multi-threaded stress)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentOwnership:
    """Stress-test: N agents racing for the same contract → exactly 1 winner."""

    def test_ten_agents_one_winner(self, registry):
        results = {}
        barrier = threading.Barrier(10)

        def try_acquire(agent_id):
            barrier.wait()
            lease = registry.acquire(KEY_BTC, owner_agent_id=agent_id)
            results[agent_id] = lease is not None

        threads = [
            threading.Thread(target=try_acquire, args=(f"agent_{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [a for a, won in results.items() if won]
        assert len(winners) == 1, f"Expected 1 winner, got {len(winners)}: {winners}"
        m = registry.get_metrics()
        assert m["conflicts"] == 9


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Network Retry Idempotency
# ═══════════════════════════════════════════════════════════════════════════════

class TestNetworkRetryIdempotency:
    """Simulate retries of the same decision — only one order ever admitted."""

    def test_three_retries_one_admitted(self, gate):
        ts = 1700000000.0
        admitted = 0
        coids = set()
        for _ in range(3):
            v = gate.check(
                agent_id="ag1", strategy_group="btc_15m",
                contract_id="KXBTC", side="yes", action="buy",
                target_count=10, price_cents=55,
                decision_ts=ts + 10,  # all within same bucket
            )
            coids.add(v.client_order_id)
            if v.allowed:
                admitted += 1

        assert admitted == 1, f"Expected exactly 1 admission, got {admitted}"
        assert len(coids) == 1, "All retries should produce same client_order_id"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Cap Breach Rejection (integration with gate metrics)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapBreachMetrics:
    """Verify that gate metrics track blocked orders correctly."""

    def test_fill_awareness_metric(self, gate):
        ts = 1700000000.0
        v = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=5, price_cents=55, decision_ts=ts,
        )
        gate.mark_submitted(v.client_order_id, "venue-abc")
        gate.mark_filled(v.client_order_id, 5)

        # Attempt a new order — target already met
        v2 = gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=5, price_cents=55,
            decision_ts=ts + DECISION_BUCKET_WIDTH_S + 1,
        )
        assert v2.allowed is False
        m = gate.get_metrics()
        assert m["blocked_already_satisfied"] == 1

    def test_duplicate_metric(self, gate):
        ts = 1700000000.0
        gate.check(
            agent_id="ag1", strategy_group="btc_15m",
            contract_id="KXBTC", side="yes", action="buy",
            target_count=10, price_cents=55, decision_ts=ts,
        )
        for _ in range(5):
            gate.check(
                agent_id="ag1", strategy_group="btc_15m",
                contract_id="KXBTC", side="yes", action="buy",
                target_count=10, price_cents=55, decision_ts=ts,
            )
        m = gate.get_metrics()
        assert m["blocked_duplicate"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Module-level structure / wiring assertions
# ═══════════════════════════════════════════════════════════════════════════════

class TestModuleStructure:
    """Verify the modules exist and export the expected API."""

    def test_contract_lease_exports(self):
        from merid.event_venues.kalshi import contract_lease
        assert hasattr(contract_lease, "ContractLeaseRegistry")
        assert hasattr(contract_lease, "LeaseKey")
        assert hasattr(contract_lease, "Lease")
        assert hasattr(contract_lease, "get_contract_lease_registry")

    def test_order_gate_exports(self):
        from merid.event_venues.kalshi import order_gate
        assert hasattr(order_gate, "PreTradeGate")
        assert hasattr(order_gate, "IdempotentOrderStore")
        assert hasattr(order_gate, "deterministic_client_order_id")
        assert hasattr(order_gate, "get_pre_trade_gate")
        assert hasattr(order_gate, "GateVerdict")
        assert hasattr(order_gate, "OrderStatus")

    def test_order_router_has_pre_trade_gate(self):
        from merid.event_venues.kalshi import order_router
        assert hasattr(order_router, "_run_pre_trade_gate")

    def test_lease_key_is_hashable(self):
        """LeaseKey must be usable as dict key."""
        d = {KEY_BTC: "val"}
        assert d[KEY_BTC] == "val"

    def test_lease_key_str(self):
        s = str(KEY_BTC)
        assert "kalshi" in s
        assert "KXBTC" in s
