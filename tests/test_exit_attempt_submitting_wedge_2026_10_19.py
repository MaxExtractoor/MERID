"""Regression: SUBMITTING-exit-attempt wedge (2026-10-19 stack audit).

Before this fix an arbiter attempt could be left in SUBMITTING forever:

  - ``post_route_update`` had no branch for ``not_submitted`` / ``duplicate``
    / unhandled statuses, so the attempt was never advanced.
  - ``positions_requiring_reconcile`` enumerated only
    ``_MUST_RECONCILE_STATES``, which excludes SUBMITTING, so the reconcile
    worker never picked the wedged attempt up.
  - Route timeout/exception paths in loop_15m and stop_candidate could
    return before any lifecycle call landed.

A wedged SUBMITTING attempt makes ``arbitrate`` return ``in_flight`` for
every later proposal — silently suppressing all protective exits for the
generation until restart.

These tests pin the fixed contract:

  1. ``not_submitted`` (router authoritative-empty) resolves the attempt
     confirmed-dead -> RETRY_ELIGIBLE.
  2. ``duplicate`` -> ACK_UNKNOWN (another route owns the coid).
  3. Any unhandled status -> ACK_UNKNOWN safe default (unknown != dead).
  4. Fresh SUBMITTING is excluded from reconcile enumeration; aged
     SUBMITTING (> MERID_EXIT_SUBMITTING_STALE_S, default 30s) is included
     and ``arbitrate`` reports ``reconcile_required`` for it.
"""
from __future__ import annotations

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
)
from merid.position_management.position_exit_state import (
    PositionExitStateStore,
)
from merid.position_management.exit_pipeline import post_route_update

TICKER = "KXBTC15M-WEDGE-30"
GEN = "fill_entry_wedge_1"
PKEY = f"{TICKER}|{GEN}"


def _arbiter(tmp_path) -> ExitArbiter:
    return ExitArbiter(
        state_store=PositionExitStateStore(
            str(tmp_path / "exit_state.json")),
        attempt_store=ExitAttemptStore(
            str(tmp_path / "exit_attempts.json")),
    )


def _mint(tmp_path) -> ExitArbiter:
    """Mint a real SUBMITTING attempt via the arbiter's own selection."""
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
            kind=ProposalKind.PROFIT_LOCK.value, proposal_id="pl1",
            limit_cents=55, qty_cc=300, reason="test")],
    )
    assert result.status == "submitted"
    attempt = arb.attempt_store.get_active(PKEY)
    assert attempt is not None
    assert attempt.state == AttemptState.SUBMITTING
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
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestPostRouteUpdateUnhandledStatuses:
    def test_not_submitted_resolves_retry_eligible(self, tmp_path):
        """Router authoritative-empty (order provably never landed) is
        confirmed-dead evidence -> RETRY_ELIGIBLE, not a SUBMITTING wedge."""
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("not_submitted"), arbiter=arb)
        attempt = arb.attempt_store.get_active(PKEY)
        assert attempt.state == AttemptState.RETRY_ELIGIBLE

    def test_duplicate_marks_ack_unknown(self, tmp_path):
        """A router-level duplicate leaves ownership with another in-flight
        route — the outcome is unknown, so reconcile must observe it."""
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("duplicate"), arbiter=arb)
        attempt = arb.attempt_store.get_active(PKEY)
        assert attempt.state == AttemptState.ACK_UNKNOWN

    def test_unhandled_status_marks_ack_unknown(self, tmp_path):
        """Any status post_route_update does not recognise must leave the
        attempt in a reconcile-required state, never wedged SUBMITTING."""
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("held_unmarketable"), arbiter=arb)
        attempt = arb.attempt_store.get_active(PKEY)
        assert attempt.state == AttemptState.ACK_UNKNOWN

    def test_acked_status_still_works(self, tmp_path):
        """Sanity: the pre-existing ack path is unchanged."""
        arb = _mint(tmp_path)
        post_route_update(
            PKEY, _result("submitted", has_execution=False), arbiter=arb)
        # 'submitted' isn't an explicit branch — safe default ACK_UNKNOWN
        # still applies; the important property is it is NOT stuck in
        # SUBMITTING with no reconcile path.
        assert arb.attempt_store.get_active(PKEY).state in (
            AttemptState.ACK_UNKNOWN,
            AttemptState.WORKING_OR_PARTIALLY_FILLED,
        )


class TestStaleSubmittingReconcile:
    def test_fresh_submitting_not_enumerated(self, tmp_path):
        """An in-flight route call must never be disturbed."""
        arb = _mint(tmp_path)
        assert PKEY not in arb.positions_requiring_reconcile()

    def test_aged_submitting_enumerated(self, tmp_path):
        """SUBMITTING older than the route-timeout bound is a wedge —
        enumerate it so the worker reconciles by client_order_id."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.updated_ts = time.time() - 120.0
        attempt.created_ts = time.time() - 120.0
        arb.attempt_store.save_active(attempt)
        assert PKEY in arb.positions_requiring_reconcile()

    def test_aged_submitting_reports_reconcile_required(self, tmp_path):
        """The arbitrate gate must tell callers a stale submission needs
        reconciliation, not merely 'in_flight'."""
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.updated_ts = time.time() - 120.0
        attempt.created_ts = time.time() - 120.0
        arb.attempt_store.save_active(attempt)
        result = arb.arbitrate(
            market_id=TICKER,
            generation_id=GEN,
            held_side="yes",
            remaining_cc=300,
            breakeven_floor_cents=36,
            book=ExitBook(
                held_side="yes", liquidation_cents=60, qty_cc=500,
                age_ms=50),
            proposals=[ExitProposal(
                kind=ProposalKind.PROFIT_LOCK.value, proposal_id="pl2",
                limit_cents=58, qty_cc=300, reason="test")],
        )
        assert result.status == "reconcile_required"

    def test_fresh_submitting_reports_in_flight(self, tmp_path):
        """A fresh in-flight attempt still blocks replacement as in_flight."""
        arb = _mint(tmp_path)
        result = arb.arbitrate(
            market_id=TICKER,
            generation_id=GEN,
            held_side="yes",
            remaining_cc=300,
            breakeven_floor_cents=36,
            book=ExitBook(
                held_side="yes", liquidation_cents=60, qty_cc=500,
                age_ms=50),
            proposals=[ExitProposal(
                kind=ProposalKind.PROFIT_LOCK.value, proposal_id="pl2",
                limit_cents=58, qty_cc=300, reason="test")],
        )
        assert result.status == "in_flight"

    def test_stale_submitting_reconciles_to_retry(self, tmp_path):
        """End-to-end: aged SUBMITTING -> reconcile evidence -> resolved."""
        from merid.position_management.exit_arbiter import ReconcileEvidence
        arb = _mint(tmp_path)
        attempt = arb.attempt_store.get_active(PKEY)
        attempt.updated_ts = time.time() - 120.0
        arb.attempt_store.save_active(attempt)
        # Never transmitted (no coid bound -> local_no_transmit path).
        assert PKEY in arb.positions_requiring_reconcile()
        arb.begin_reconcile(PKEY)
        arb.resolve_reconcile(PKEY, ReconcileEvidence(
            order_found=False, terminal=True, filled_cc=0,
            source="local_no_transmit"))
        assert arb.attempt_store.get_active(PKEY).state == (
            AttemptState.RETRY_ELIGIBLE)
