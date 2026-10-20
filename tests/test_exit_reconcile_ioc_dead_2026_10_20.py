"""Regression: RECONCILING wedge on terminal IOC exits (2026-10-20 audit).

Observed live (KXBTC15M-26OCT200015): a stop-candidate IOC exit was
``accepted_live`` by the venue but the response carried no order_id, so
reconcile had only the client_order_id path.  The coid lookup hit
``GET /portfolio/orders`` *without* a status filter, which returns resting
orders only — a terminal IOC is unobservable — so the attempt stayed
``inconclusive_lookup_still_unresolved`` for ~7 minutes while every later
protective exit was suppressed as ``attempt_in_flight:RECONCILING`` and the
position rode to ~19c settlement (−53c).

Fixed contract pinned here:

  1. ``get_order_by_client_id_result`` retries a miss with
     ``status=executed`` and ``status=canceled`` so terminal orders are
     observable.
  2. An immediate-only attempt (``stopcand_`` coid / ``stop_candidate:``
     proposal / ``time_in_force`` marker) whose exchange views all miss
     after ``MERID_EXIT_IOC_DEAD_AFTER_S`` resolves ``ioc_terminal_inferred``
     -> RETRY_ELIGIBLE.  IOCs cannot rest — unfindable is dead — and a fresh
     reduce-only retry cannot stack exposure.
  3. Non-IOC attempts keep the strict contract: inconclusive lookups stay
     RECONCILING (absence is never proof of death for resting orders).
  4. ``accepted_live``/``submitted_live``/``resting`` route outcomes are
     genuinely acked → mark_acked (WORKING), not the misleading
     "route_unhandled" ACK_UNKNOWN.
  5. A persistently inconclusive attempt escalates to a CRITICAL log once.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from merid.position_management.exit_arbiter import (
    AttemptState,
    ExitArbiter,
    ExitAttemptStore,
    ExitBook,
    ExitProposal,
    ProposalKind,
    ReconcileEvidence,
)
from merid.position_management.position_exit_state import (
    PositionExitStateStore,
)
from merid.position_management.exit_pipeline import (
    _attempt_is_ioc,
    _ioc_attempt_is_dead,
    post_route_update,
    reconcile_attempt,
)

TICKER = "KXBTC15M-RECON-IOC"
GEN = "fill_entry_recon_ioc"
PKEY = f"{TICKER}|{GEN}"


def _arbiter(tmp_path) -> ExitArbiter:
    return ExitArbiter(
        state_store=PositionExitStateStore(
            str(tmp_path / "exit_state.json")),
        attempt_store=ExitAttemptStore(
            str(tmp_path / "exit_attempts.json")),
    )


def _mint(tmp_path, *, coid: str = "stopcand_sc-dead1") -> ExitArbiter:
    arb = _arbiter(tmp_path)
    result = arb.arbitrate(
        market_id=TICKER,
        generation_id=GEN,
        held_side="yes",
        remaining_cc=300,
        breakeven_floor_cents=36,
        book=ExitBook(
            held_side="yes", liquidation_cents=60, qty_cc=500, age_ms=50),
        proposals=[ExitProposal(
            kind=ProposalKind.PROFIT_LOCK.value, proposal_id="p1",
            limit_cents=55, qty_cc=300, reason="test")],
    )
    assert result.status == "submitted"
    attempt = arb.attempt_store.get_active(PKEY)
    assert attempt is not None and attempt.state == AttemptState.SUBMITTING
    if coid is not None:
        attempt.client_order_id = coid
        arb.attempt_store.save_active(attempt)
    return arb


def _result(status, **kw):
    base = dict(
        status=status,
        submission_attempted=True,
        submission_certainty="",
        executed_quantity_cc=0,
        has_execution=False,
        is_terminal=False,
        is_resting=False,
        requires_recovery=False,
        fill={},
        order_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _Ok:
    def __init__(self, data):
        self.success = True
        self.data = data
        self.latency_ms = 0.0
        self.retries = 0

    def unwrap_or(self, default):
        return self.data


class _FakeClient:
    """Reconcile client: order-id and coid lookups both miss by default."""

    def __init__(self, order=None):
        self._order = order
        self.coid_calls = []

    async def get_order_result(self, order_id):
        return _Ok(self._order)

    async def get_order_by_client_id_result(
            self, client_order_id, market_id=None, min_ts=None):
        self.coid_calls.append(
            {"coid": client_order_id, "market_id": market_id,
             "min_ts": min_ts})
        return _Ok(self._order)


class TestIocTerminalInference:
    def test_old_ioc_attempt_releases_to_retry(self, tmp_path):
        """stopcand_ IOC unfindable past the dead-after bound = dead."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.created_ts = time.time() - 120.0
        attempt.order_id = None
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        out = asyncio.run(reconcile_attempt(
            PKEY, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RETRY_ELIGIBLE.value

    def test_fresh_ioc_attempt_stays_reconciling(self, tmp_path):
        """Inside the bound, absence is still treated as inconclusive —
        the wire/endpoint may lag the accepted IOC."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.order_id = None  # coid path only, like the live wedge
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        out = asyncio.run(reconcile_attempt(
            PKEY, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RECONCILING.value

    def test_non_ioc_attempt_never_infers(self, tmp_path):
        """A resting-capable order stays RECONCILING forever on inconclusive
        lookups — inference would allow a duplicate resting exit."""
        arb = _mint(tmp_path, coid="exit_abc123")
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.created_ts = time.time() - 3600.0
        attempt.order_id = None
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        out = asyncio.run(reconcile_attempt(
            PKEY, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RECONCILING.value

    def test_ioc_inference_uses_client_order_id_lookup_min_ts(self, tmp_path):
        """The coid lookup passes a min_ts bound derived from the attempt."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.created_ts = time.time() - 500.0
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        client = _FakeClient(order=None)
        asyncio.run(reconcile_attempt(PKEY, client, arbiter=arb))
        assert client.coid_calls
        assert client.coid_calls[0]["min_ts"] == int(attempt.created_ts) - 120

    def test_found_terminal_order_resolves_normally(self, tmp_path):
        """A coid lookup that surfaces the canceled IOC resolves via real
        evidence — inference is only the fallback."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.order_id = None
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        order = SimpleNamespace(status="canceled", filled_size=0)
        out = asyncio.run(reconcile_attempt(
            PKEY, _FakeClient(order=order), arbiter=arb))
        assert out == AttemptState.RETRY_ELIGIBLE.value


class TestIocDetection:
    def test_stopcand_coid_prefix(self):
        assert _attempt_is_ioc(SimpleNamespace(
            time_in_force=None, client_order_id="stopcand_sc-x",
            proposal_id=None, decision_id=None))

    def test_stop_candidate_proposal_id(self):
        assert _attempt_is_ioc(SimpleNamespace(
            time_in_force=None, client_order_id="weird_prefix_x",
            proposal_id="stop_candidate:sc-y", decision_id=None))

    def test_explicit_tif(self):
        assert _attempt_is_ioc(SimpleNamespace(
            time_in_force="ioc", client_order_id="exit_z",
            proposal_id=None, decision_id=None))

    def test_gtc_not_ioc(self):
        assert not _attempt_is_ioc(SimpleNamespace(
            time_in_force="gtc", client_order_id="exit_z",
            proposal_id=None, decision_id=None))

    def test_dead_age_bound(self, monkeypatch):
        monkeypatch.setenv("MERID_EXIT_IOC_DEAD_AFTER_S", "90")
        old = SimpleNamespace(
            time_in_force=None, client_order_id="stopcand_sc-1",
            proposal_id=None, decision_id=None,
            created_ts=time.time() - 100.0)
        fresh = SimpleNamespace(
            time_in_force=None, client_order_id="stopcand_sc-1",
            proposal_id=None, decision_id=None,
            created_ts=time.time() - 10.0)
        assert _ioc_attempt_is_dead(old)
        assert not _ioc_attempt_is_dead(fresh)


class TestAcceptedLiveRouteOutcome:
    def test_accepted_live_marks_working(self, tmp_path):
        """accepted_live is a genuine ack — WORKING (must-reconcile set),
        not a fake 'unhandled' ACK_UNKNOWN."""
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("accepted_live"), arbiter=arb)
        attempt = arb.attempt_store.get_active(PKEY)
        assert attempt.state == AttemptState.WORKING_OR_PARTIALLY_FILLED

    def test_submitted_live_marks_working(self, tmp_path):
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("submitted_live"), arbiter=arb)
        assert arb.attempt_store.get_active(PKEY).state == (
            AttemptState.WORKING_OR_PARTIALLY_FILLED)

    def test_accepted_live_binds_order_id(self, tmp_path):
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("accepted_live", order_id="oid-777"), arbiter=arb)
        assert arb.attempt_store.get_active(PKEY).order_id == "oid-777"


class TestStuckReconcileAlert:
    def test_stuck_alert_fires_once(self, tmp_path, caplog):
        import logging
        arb = _mint(tmp_path, coid="exit_stuck1")  # non-IOC -> stays wedged
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.created_ts = time.time() - 400.0
        attempt.order_id = None
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(PKEY)

        client = _FakeClient(order=None)
        with caplog.at_level(logging.CRITICAL):
            asyncio.run(reconcile_attempt(PKEY, client, arbiter=arb))
            asyncio.run(reconcile_attempt(PKEY, client, arbiter=arb))
        crits = [r for r in caplog.records
                 if "EXIT-RECONCILE-STUCK" in r.getMessage()]
        assert len(crits) == 1
