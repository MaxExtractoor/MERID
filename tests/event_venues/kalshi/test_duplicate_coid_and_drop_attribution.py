"""Regression tests for the 2026-10-31 post-restart stack fixes.

1. ws.py stale-delta drop attribution: frames shed under queue backlog now
   carry their (seq -> ticker) identity downstream so a dropped update
   invalidates only the affected book instead of every book multiplexed on
   the shared orderbook subscription.
2. Dead client_order_id 409 loop: a reconciled exit flight record must not
   lend its idempotency key to the next obligation, the identity layer must
   never rebind a terminal attempt's coid, and a ``duplicate_order_terminal``
   route result must terminalize the generic order-attempt record.
"""

import time
import types
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptStore,
    OrderAttemptRecord,
)


@pytest.fixture
def store():
    return KalshiMarketStateStore()


@pytest.fixture
def attempt_store(tmp_path):
    return OrderAttemptStore(db_path=str(tmp_path / "attempts.db"))


class TestDroppedFrameAttribution:
    def test_attributed_drop_invalidates_only_affected(self, store):
        """Dropped (seq,ticker) pairs cover the skipped range -> per-ticker."""
        store._check_sid_delta_sequence(4, 100, "KXBTC15M-A")
        store._check_sid_delta_sequence(4, 101, "KXETH15M-A")
        called = []
        store._mark_book_untrusted_and_resync = (
            lambda t, reason, **kw: called.append((t, reason))
        )
        # seqs 102 (ETH) and 103 (BTC) shed by ws.py; 104 arrives with the
        # attribution attached.
        store._handle_sid_sequence_gap(
            4, 104, 2, "KXBTC15M-A",
            dropped=[(102, "KXETH15M-A"), (103, "KXBTC15M-A")],
        )
        assert {t for t, _ in called} == {"KXETH15M-A", "KXBTC15M-A"}
        assert all(r == "ws_delta_dropped_stale" for _, r in called)
        # A third ticker on the sid is NOT invalidated.
        assert "KXSOL15M-A" not in {t for t, _ in called}

    def test_no_attribution_invalidates_all_siblings(self, store):
        store._check_sid_delta_sequence(4, 100, "KXBTC15M-A")
        store._check_sid_delta_sequence(4, 101, "KXETH15M-A")
        called = []
        store._mark_book_untrusted_and_resync = (
            lambda t, reason, **kw: called.append((t, reason))
        )
        store._handle_sid_sequence_gap(4, 104, 2, "KXBTC15M-A", dropped=None)
        assert {t for t, _ in called} == {"KXBTC15M-A", "KXETH15M-A"}
        assert all(r == "ws_sid_sequence_gap" for _, r in called)

    def test_partial_coverage_falls_back_to_full_invalidation(self, store):
        """Coverage cannot be proven -> fail closed on the whole sid."""
        store._check_sid_delta_sequence(4, 100, "KXBTC15M-A")
        store._check_sid_delta_sequence(4, 101, "KXETH15M-A")
        called = []
        store._mark_book_untrusted_and_resync = (
            lambda t, reason, **kw: called.append((t, reason))
        )
        store._handle_sid_sequence_gap(
            4, 104, 2, "KXBTC15M-A",
            dropped=[(102, "KXETH15M-A")],  # 103 unaccounted for
        )
        assert {t for t, _ in called} == {"KXBTC15M-A", "KXETH15M-A"}

    def test_overflow_sentinel_invalidates_all(self, store):
        store._check_sid_delta_sequence(4, 100, "KXBTC15M-A")
        store._check_sid_delta_sequence(4, 101, "KXETH15M-A")
        called = []
        store._mark_book_untrusted_and_resync = (
            lambda t, reason, **kw: called.append((t, reason))
        )
        store._handle_sid_sequence_gap(4, 104, 2, "KXBTC15M-A", dropped="overflow")
        assert len(called) == 2


class TestRecoverySourceMapping:
    def test_ws_resync_snapshot_is_authoritative(self, store):
        """The WS-triggered REST resync path fetches a full REST orderbook —
        it must map to REST_FULL_ORDERBOOK so an INVALID book can recover
        (previously resolved UNKNOWN and was rejected by the attest gate)."""
        assert (
            store._resolve_book_source("ws_resync", "orderbook_snapshot")
            == "REST_FULL_ORDERBOOK"
        )

    def test_unknown_via_still_rejected(self, store):
        assert store._resolve_book_source("quote_fallback", "x") == "WS_QUOTE"
        assert store._resolve_book_source("mystery_via", "x") == "UNKNOWN"


def _make_monitor():
    """Bare PositionMonitor carrying only the attributes the flight paths use."""
    import threading
    from merid.position_management.position_monitor import PositionMonitor

    mon = object.__new__(PositionMonitor)
    mon._lock = threading.RLock()
    mon._exit_intent_in_flight = {}
    mon._position_to_client_order = {}
    mon._recent_exit_submissions = {}
    mon._open_positions = {}
    mon._transition_exit_attempt = lambda *a, **k: None
    mon._save_exit_intent_in_flight = lambda *a, **k: None
    return mon


class TestExitFlightCoidLifecycle:
    def test_terminal_record_does_not_lend_dead_coid(self):
        """A reconciled flight record must not seed the next obligation's coid."""
        mon = _make_monitor()
        pid = "pos_abc12345"
        mon._exit_intent_in_flight[pid] = {
            "state": "RECONCILED",
            "client_order_id": "exit_deadbeef00",
            "reason": "hard_profit_lock",
            "timestamp": time.time() - 30,
        }
        mon._mark_exit_intent_in_flight(pid, reason="hard_profit_lock")
        flight = mon._exit_intent_in_flight[pid]
        assert flight["state"] == "EXECUTION_PENDING"
        assert flight["client_order_id"] is None
        # The unresolved-coid lookup must not resurrect the dead key either.
        assert mon._get_unresolved_exit_client_order_id(pid) is None

    def test_inflight_record_keeps_coid_for_resubmit(self):
        """A genuinely in-flight obligation keeps its idempotency key."""
        mon = _make_monitor()
        pid = "pos_abc12345"
        mon._exit_intent_in_flight[pid] = {
            "state": "EXECUTION_PENDING",
            "client_order_id": "exit_live00000",
            "reason": "trail",
            "timestamp": time.time() - 5,
        }
        mon._mark_exit_intent_in_flight(pid, reason="trail")
        assert mon._exit_intent_in_flight[pid]["client_order_id"] == "exit_live00000"
        assert mon._get_unresolved_exit_client_order_id(pid) == "exit_live00000"


def _fake_intent(**kw):
    base = dict(
        intent_id="intent_exit_x",
        client_order_id=None,
        order_attempt_id=None,
        client_tag=None,
        decision_id=None,
        run_id=None,
        process_id=None,
        ticker="KXETH15M-TEST",
        action="sell",
        side="no",
        price_cents=99,
        count=2.0,
        count_fp=None,
        reduce_only=True,
        tif=None,
        time_in_force=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _record(store, coid, intent_id, status, fingerprint="fp"):
    rec = OrderAttemptRecord(
        order_attempt_id=f"oa_{coid}",
        client_order_id=coid,
        decision_id=None,
        replaces_order_attempt_id=None,
        intent_id=intent_id,
        client_tag=None,
        run_id=None,
        process_id=None,
        fingerprint=fingerprint,
        status=status,
        created_at=time.time(),
        updated_at=time.time(),
        payload_json="{}",
    )
    store.persist_attempt(rec)
    return rec


class TestOrderIdentityTerminalReuse:
    def test_terminal_record_mints_fresh_coid(self, attempt_store):
        from merid.event_venues.kalshi import order_identity

        _record(attempt_store, "exit_dead0000", "intent_exit_x", "REJECTED")
        intent = _fake_intent(client_order_id="exit_dead0000")
        out = order_identity.finalize_order_identity(intent, store=attempt_store)
        assert out.client_order_id != "exit_dead0000"
        assert out.order_attempt_id is not None

    def test_live_record_still_reuses_coid(self, attempt_store):
        """Same-intent retry on a live attempt keeps idempotent resubmit."""
        from merid.event_venues.kalshi import order_identity

        _record(attempt_store, "exit_live000", "intent_exit_x", "ACKNOWLEDGED")
        intent = _fake_intent(client_order_id="exit_live000")
        out = order_identity.finalize_order_identity(intent, store=attempt_store)
        assert out.client_order_id == "exit_live000"
        assert out.order_attempt_id == "oa_exit_live000"


class TestAttemptStoreFinalization:
    @pytest.fixture(autouse=True)
    def _patch_store(self, attempt_store, monkeypatch):
        import merid.event_venues.kalshi.order_attempt_store as oas_mod
        monkeypatch.setattr(
            oas_mod, "OrderAttemptStore", lambda *a, **k: attempt_store
        )

    @staticmethod
    def _rejected_result():
        return types.SimpleNamespace(
            status="rejected",
            submission_certainty="rejected",
            has_execution=False,
            reason="duplicate_order_terminal:canceled",
            error=None,
            submission_attempted=True,
        )

    def test_rejected_certainty_terminalizes_acknowledged(self, attempt_store):
        from merid.event_venues.kalshi import order_router

        rec = _record(attempt_store, "exit_dup000", "intent_exit_x", "ACKNOWLEDGED")
        intent = _fake_intent(order_attempt_id=rec.order_attempt_id)
        order_router._finalize_attempt_store_for_result(
            intent, self._rejected_result()
        )
        updated = attempt_store.get_by_client_order_id("exit_dup000")
        assert updated.status == "REJECTED"

    def test_rejected_result_does_not_downgrade_terminal(self, attempt_store):
        from merid.event_venues.kalshi import order_router

        rec = _record(attempt_store, "exit_fill00", "intent_exit_x", "FILLED")
        intent = _fake_intent(order_attempt_id=rec.order_attempt_id)
        order_router._finalize_attempt_store_for_result(
            intent, self._rejected_result()
        )
        updated = attempt_store.get_by_client_order_id("exit_fill00")
        assert updated.status == "FILLED"
