"""Regression tests for the orphan-PENDING sweep added to ``IdempotentOrderStore``.

Before this sweep, ``prune_old`` only removed records in TERMINAL states
(FILLED / REJECTED / CANCELED).  A PENDING record produced by the gate but
never advanced to SUBMITTED — for example because the upstream caller
crashed between ``PreTradeGate.check`` and ``route_order_async``, or an
unhandled exception inside the router dropped the call *before*
``mark_submitted`` — would therefore leak into the idempotent store
forever.  Because PENDING records also block later duplicate checks, the
leak would silently prevent legitimate retries of the same logical order.

The complementary sweep (``prune_stale_pending``) mark-rejects any
non-terminal record older than its TTL so the terminal prune can
eventually sweep it.  The tests below freeze that contract.
"""

from __future__ import annotations

import time

import pytest

from merid.event_venues.kalshi.order_gate import (
    IdempotentOrderStore,
    OrderRecord,
    OrderStatus,
    PreTradeGate,
)


def _make_record(coid: str, status: OrderStatus, updated_at: float) -> OrderRecord:
    rec = OrderRecord(
        client_order_id=coid,
        agent_id="test-agent",
        strategy_group="test",
        contract_id="TEST-CONTRACT",
        side="yes",
        action="buy",
        target_count=1,
        price_cents=50,
        status=status,
    )
    # created_at/updated_at are set via default_factory; override for determinism.
    rec.updated_at = updated_at
    return rec


class TestPruneStalePendingBasics:

    def test_pending_older_than_ttl_is_marked_rejected(self):
        store = IdempotentOrderStore()
        stale_pending = _make_record("coid-stale", OrderStatus.PENDING, time.time() - 600)
        store._orders["coid-stale"] = stale_pending

        result = store.prune_stale_pending(pending_ttl_s=300)

        assert result == {"orphaned_pending": 1, "orphaned_submitted": 0}
        assert stale_pending.status == OrderStatus.REJECTED
        # updated_at bumped so prune_old's 24h TTL restarts from now.
        assert stale_pending.updated_at > time.time() - 5

    def test_fresh_pending_is_left_alone(self):
        """A PENDING record younger than the TTL is an in-flight order."""
        store = IdempotentOrderStore()
        fresh = _make_record("coid-fresh", OrderStatus.PENDING, time.time() - 5)
        store._orders["coid-fresh"] = fresh

        result = store.prune_stale_pending(pending_ttl_s=300)

        assert result == {"orphaned_pending": 0, "orphaned_submitted": 0}
        assert fresh.status == OrderStatus.PENDING

    def test_submitted_older_than_long_ttl_is_marked_rejected(self):
        store = IdempotentOrderStore()
        zombie = _make_record("coid-zombie", OrderStatus.SUBMITTED, time.time() - 7200)
        store._orders["coid-zombie"] = zombie

        result = store.prune_stale_pending(submitted_ttl_s=3600)

        assert result == {"orphaned_pending": 0, "orphaned_submitted": 1}
        assert zombie.status == OrderStatus.REJECTED

    def test_live_records_are_never_touched(self):
        """LIVE records are not orphans — only the reconciler resolves them."""
        store = IdempotentOrderStore()
        live = _make_record("coid-live", OrderStatus.LIVE, time.time() - 86400)
        store._orders["coid-live"] = live

        result = store.prune_stale_pending(pending_ttl_s=1, submitted_ttl_s=1)

        assert result == {"orphaned_pending": 0, "orphaned_submitted": 0}
        assert live.status == OrderStatus.LIVE

    def test_terminal_records_are_never_touched(self):
        """Terminal records are owned by prune_old, not the orphan sweep."""
        store = IdempotentOrderStore()
        for status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED):
            rec = _make_record(f"coid-{status.value}", status, time.time() - 86400)
            store._orders[rec.client_order_id] = rec

        result = store.prune_stale_pending(pending_ttl_s=1, submitted_ttl_s=1)

        assert result == {"orphaned_pending": 0, "orphaned_submitted": 0}
        # All three preserved at their original terminal status.
        for status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED):
            assert store._orders[f"coid-{status.value}"].status == status


class TestOrphanSweepEnablesTerminalPrune:
    """The whole point of the two-stage design: orphans eventually leave."""

    def test_orphan_then_prune_removes_leaked_pending_records(self):
        """Full lifecycle: orphan a PENDING, let TTL elapse, then prune."""
        store = IdempotentOrderStore()
        stale = _make_record("coid-stale", OrderStatus.PENDING, time.time() - 600)
        store._orders["coid-stale"] = stale

        # First pass: mark the orphan.
        store.prune_stale_pending(pending_ttl_s=300)
        assert stale.status == OrderStatus.REJECTED

        # Immediately after the mark, prune_old with a short TTL still
        # shouldn't sweep — updated_at was just bumped.
        pruned = store.prune_old(ttl_s=60)
        assert pruned == 0
        assert "coid-stale" in store._orders

        # Simulate the record aging past the terminal TTL.
        stale.updated_at = time.time() - 120
        pruned = store.prune_old(ttl_s=60)
        assert pruned == 1
        assert "coid-stale" not in store._orders


class TestPreTradeGateCleanupStaleIntegration:
    """``PreTradeGate.cleanup_stale`` wires both passes together."""

    def test_cleanup_stale_reports_both_passes(self):
        gate = PreTradeGate()
        now = time.time()

        # A stale PENDING (> 5 min), a fresh PENDING, an old FILLED, and an
        # old CANCELED — orphan sweep should hit the stale PENDING, terminal
        # prune should remove the two old terminal records.
        gate.store._orders["stale-pending"] = _make_record(
            "stale-pending", OrderStatus.PENDING, now - 600
        )
        gate.store._orders["fresh-pending"] = _make_record(
            "fresh-pending", OrderStatus.PENDING, now - 5
        )
        gate.store._orders["old-filled"] = _make_record(
            "old-filled", OrderStatus.FILLED, now - 90000  # 25h
        )
        gate.store._orders["old-canceled"] = _make_record(
            "old-canceled", OrderStatus.CANCELED, now - 90000
        )

        result = gate.cleanup_stale(ttl_s=86400)

        assert result["pruned_terminal"] == 2
        assert result["orphaned_pending"] == 1
        assert result["orphaned_submitted"] == 0

        # Stale pending was *marked* (not deleted this pass).
        assert "stale-pending" in gate.store._orders
        assert gate.store._orders["stale-pending"].status == OrderStatus.REJECTED

        # Fresh pending untouched.
        assert gate.store._orders["fresh-pending"].status == OrderStatus.PENDING

        # Old terminals removed.
        assert "old-filled" not in gate.store._orders
        assert "old-canceled" not in gate.store._orders

    def test_cleanup_stale_with_custom_orphan_ttls(self):
        gate = PreTradeGate()
        now = time.time()
        gate.store._orders["almost-stale"] = _make_record(
            "almost-stale", OrderStatus.PENDING, now - 30
        )

        # Aggressive 10s TTL catches the 30s-old record.
        result = gate.cleanup_stale(ttl_s=86400, pending_ttl_s=10)
        assert result["orphaned_pending"] == 1

    def test_cleanup_stale_is_idempotent_across_ticks(self):
        """Running cleanup twice in a row shouldn't re-mark the same record."""
        gate = PreTradeGate()
        gate.store._orders["stale-pending"] = _make_record(
            "stale-pending", OrderStatus.PENDING, time.time() - 600
        )

        first = gate.cleanup_stale(ttl_s=86400)
        second = gate.cleanup_stale(ttl_s=86400)

        assert first["orphaned_pending"] == 1
        # Second pass sees a REJECTED record (not PENDING), so no re-mark.
        assert second["orphaned_pending"] == 0
