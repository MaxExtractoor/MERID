"""Regression: RECONCILING wedge on resting-limit exits whose market expired
(2026-10-27 audit).

Observed live: three ``model_exit`` attempts (KXSOL15M-26OCT181930-30,
KXETH15M-26OCT240000-00, KXDOGE15M-26OCT251545-45) stayed
``inconclusive_lookup_still_unresolved`` for 2-9 days.  Each had a bound
client_order_id but no order_id, so ``local_no_transmit`` could not apply,
and as resting-limit attempts ``ioc_terminal_inferred`` could not either.
The coid lookup covers only the current order views (resting/executed/
canceled); Kalshi ages terminal orders off them, so for an expired market
the lookup can *never* succeed — a guaranteed permanent wedge that paged
CRITICAL every worker tick and grew the ledger to 3.7MB / 15k history rows.

Fixed contract pinned here:

  1. An attempt whose market is provably past its ticker-embedded window
     end (plus MERID_EXIT_MARKET_DEAD_AFTER_S margin) and whose exchange
     lookups all miss resolves ``market_terminal_inferred`` ->
     RETRY_ELIGIBLE.  Market close cancels every resting order, so an
     unfindable order on a closed market is dead by construction — the
     same inference class as ``ioc_terminal_inferred``.
  2. A resolved attempt on a terminal market is then closed out
     (``market_settled`` -> FLAT): a settled market can never mint a
     replacement, so RETRY_ELIGIBLE is a dead active row.  The same
     cleanup applies at store load for pre-existing stragglers.
  3. Live (unexpired) markets keep the strict contract: inconclusive
     stays RECONCILING; a resolved attempt stays RETRY_ELIGIBLE.
  4. An unparseable market id stays RECONCILING (fail-closed).
  5. A real exchange observation still beats inference (lookup first).
  6. positions_requiring_reconcile orders youngest-first so bounded
     sweeps spend their lookup budget on live exposure, not zombies.
  7. Active-attempt history is bounded (_MAX_ACTIVE_HISTORY) with a
     truncation tombstone — a wedge can no longer grow the ledger forever.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
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
from merid.position_management.exit_pipeline import (
    _market_is_terminal,
    reconcile_attempt,
)

GEN = "fill_entry_market_term"


def _ticker_for_window_end_utc(end_utc: datetime) -> str:
    """Build a canonical-shaped KX*15M ticker from a UTC instant.

    The parser reads the body as America/New_York, so formatting a UTC
    instant yields a parsed expiry ~4-5h later than ``end_utc`` — tests
    pick margins far enough out that the direction is unambiguous.
    """
    return "KXBTC15M-" + end_utc.strftime("%y%b%d%H%M").upper() + "-50"


def _arbiter(tmp_path) -> ExitArbiter:
    return ExitArbiter(
        state_store=PositionExitStateStore(
            tmp_path / "exit_state.json"),
        attempt_store=ExitAttemptStore(
            tmp_path / "exit_attempts.json"),
    )


def _mint(tmp_path, ticker: str, *, gen: str = GEN,
          coid: str = "exit_mktterm1") -> ExitArbiter:
    arb = _arbiter(tmp_path)
    result = arb.arbitrate(
        market_id=ticker,
        generation_id=gen,
        held_side="yes",
        remaining_cc=300,
        breakeven_floor_cents=36,
        book=ExitBook(
            held_side="yes", liquidation_cents=60, qty_cc=500, age_ms=50),
        proposals=[ExitProposal(
            kind=ProposalKind.MODEL_EXIT.value, proposal_id="p1",
            limit_cents=55, qty_cc=300, reason="test")],
    )
    assert result.status == "submitted"
    attempt = arb.attempt_store.get_active(f"{ticker}|{gen}")
    assert attempt is not None and attempt.state == AttemptState.SUBMITTING
    if coid is not None:
        attempt.client_order_id = coid
        attempt.order_id = None  # coid-only, like the live wedges
        arb.attempt_store.save_active(attempt)
    return arb


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

    async def get_order_result(self, order_id):
        return _Ok(self._order)

    async def get_order_by_client_id_result(
            self, client_order_id, market_id=None, min_ts=None):
        return _Ok(self._order)


EXPIRED_TICKER = "KXSOL15M-26OCT181930-30"   # settled ~9 days ago
PKEY_EXPIRED = f"{EXPIRED_TICKER}|{GEN}"


def _closed_records(store: ExitAttemptStore, pkey: str):
    rec = store._positions.get(pkey) or {}
    return rec.get("closed") or []


class TestMarketTerminalInference:
    def test_expired_market_attempt_closes_out(self, tmp_path):
        """coid-bound resting-limit attempt on a settled market resolves
        market_terminal_inferred then closes out — a settled market can
        never mint a replacement."""
        arb = _mint(tmp_path, EXPIRED_TICKER)
        arb.begin_reconcile(PKEY_EXPIRED)

        out = asyncio.run(reconcile_attempt(
            PKEY_EXPIRED, _FakeClient(order=None), arbiter=arb))
        assert out == "FLAT"

        assert arb.attempt_store.get_active(PKEY_EXPIRED) is None
        assert PKEY_EXPIRED not in arb.positions_requiring_reconcile()
        closed = _closed_records(arb.attempt_store, PKEY_EXPIRED)
        notes = [h["note"] for h in closed[-1]["history"]]
        assert "reconciled:order_dead_unfilled:market_terminal_inferred" in notes
        assert "market_settled" in notes
        assert closed[-1]["state"] == "FLAT"

    def test_live_market_attempt_stays_reconciling(self, tmp_path):
        """A market still inside its window keeps the strict contract —
        absence is not proof of death for a resting order."""
        live_ticker = _ticker_for_window_end_utc(
            datetime.now(timezone.utc) + timedelta(hours=24))
        pkey = f"{live_ticker}|{GEN}"
        arb = _mint(tmp_path, live_ticker)
        arb.begin_reconcile(pkey)

        out = asyncio.run(reconcile_attempt(
            pkey, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RECONCILING.value

    def test_unparseable_ticker_stays_reconciling(self, tmp_path):
        """No derivable expiry => no inference => fail-closed."""
        ticker = "KXBTC15M-RECON-IOC"
        pkey = f"{ticker}|{GEN}"
        arb = _mint(tmp_path, ticker)
        attempt = arb.attempt_store.get_active(pkey)
        attempt.created_ts = time.time() - 3600.0
        arb.attempt_store.save_active(attempt)
        arb.begin_reconcile(pkey)

        out = asyncio.run(reconcile_attempt(
            pkey, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RECONCILING.value

    def test_real_evidence_beats_inference(self, tmp_path):
        """A coid lookup that surfaces the order resolves via real
        evidence — terminal inference is only the fallback.  The settled
        market then closes the record out the same way."""
        arb = _mint(tmp_path, EXPIRED_TICKER)
        arb.begin_reconcile(PKEY_EXPIRED)

        order = SimpleNamespace(status="canceled", filled_size=0)
        out = asyncio.run(reconcile_attempt(
            PKEY_EXPIRED, _FakeClient(order=order), arbiter=arb))
        assert out == "FLAT"
        closed = _closed_records(arb.attempt_store, PKEY_EXPIRED)
        notes = [h["note"] for h in closed[-1]["history"]]
        assert "reconciled:order_dead_unfilled:client_order_id_lookup" in notes
        assert "market_settled" in notes

    def test_dead_after_margin_blocks_inference(self, tmp_path, monkeypatch):
        """Inside the dead-after margin the inference must not fire —
        Kalshi may lag the nominal close."""
        monkeypatch.setenv("MERID_EXIT_MARKET_DEAD_AFTER_S", "999999999")
        arb = _mint(tmp_path, EXPIRED_TICKER)
        arb.begin_reconcile(PKEY_EXPIRED)

        out = asyncio.run(reconcile_attempt(
            PKEY_EXPIRED, _FakeClient(order=None), arbiter=arb))
        assert out == AttemptState.RECONCILING.value

    def test_market_is_terminal_helper(self):
        assert _market_is_terminal(EXPIRED_TICKER)
        assert not _market_is_terminal(_ticker_for_window_end_utc(
            datetime.now(timezone.utc) + timedelta(hours=24)))
        assert not _market_is_terminal("KXBTC15M-RECON-IOC")
        assert not _market_is_terminal(None)
        assert not _market_is_terminal("")


class TestLoadTimeSettledMarketSweep:
    def test_retry_eligible_on_settled_market_retires(self, tmp_path):
        """RETRY_ELIGIBLE actives on terminal markets move to bounded
        closed history at load; live/unparseable markets stay active."""
        live_ticker = _ticker_for_window_end_utc(
            datetime.now(timezone.utc) + timedelta(hours=24))
        expired_pkey = f"{EXPIRED_TICKER}|g_old"
        live_pkey = f"{live_ticker}|g_live"
        weird_pkey = "KXBTC15M-FOO|g_weird"

        def _active(pkey):
            return {
                "attempt_id": "a#1", "position_key": pkey,
                "generation_id": pkey.split("|", 1)[1],
                "state": "RETRY_ELIGIBLE",
                "proposal_kind": "model_exit", "proposal_id": "p1",
                "limit_cents": 55, "qty_cc": 100, "filled_cc": 0,
                "client_order_id": "exit_x", "order_id": None,
                "created_ts": time.time() - 1000,
                "updated_ts": time.time(),
                "history": [{"ts": time.time(), "from": "RECONCILING",
                             "to": "RETRY_ELIGIBLE", "note": "test"}],
                "fill_ids": [],
            }

        store_path = tmp_path / "exit_attempts.json"
        store_path.write_text(json.dumps({
            "schema_version": 1, "updated_at": time.time(),
            "positions": {
                expired_pkey: {"attempt_seq": 1,
                               "active": _active(expired_pkey),
                               "closed": []},
                live_pkey: {"attempt_seq": 1,
                            "active": _active(live_pkey),
                            "closed": []},
                weird_pkey: {"attempt_seq": 1,
                             "active": _active(weird_pkey),
                             "closed": []},
            }}))
        store = ExitAttemptStore(store_path)

        assert store.get_active(expired_pkey) is None
        closed = store._positions[expired_pkey]["closed"]
        assert closed and closed[-1]["state"] == "RETRY_ELIGIBLE"
        assert store.get_active(live_pkey) is not None
        assert store.get_active(weird_pkey) is not None


class TestReconcileOrdering:
    def test_youngest_attempt_reconciles_first(self, tmp_path):
        """Bounded sweeps should spend lookups on fresh live-position
        wedges ahead of long-lived zombies."""
        arb = _mint(tmp_path, "KXBTC15M-AAA", gen="g_old", coid="exit_old")
        old_key = "KXBTC15M-AAA|g_old"
        new_key = "KXBTC15M-BBB|g_new"
        result = arb.arbitrate(
            market_id="KXBTC15M-BBB", generation_id="g_new",
            held_side="yes", remaining_cc=300, breakeven_floor_cents=36,
            book=ExitBook(
                held_side="yes", liquidation_cents=60, qty_cc=500,
                age_ms=50),
            proposals=[ExitProposal(
                kind=ProposalKind.MODEL_EXIT.value, proposal_id="p1",
                limit_cents=55, qty_cc=300, reason="test")])
        assert result.status == "submitted"

        for key, age in ((old_key, 1000.0), (new_key, 10.0)):
            att = arb.attempt_store.get_active(key)
            att.client_order_id = "exit_x"
            att.created_ts = time.time() - age
            arb.attempt_store.save_active(att)
            arb.mark_ack_unknown(key)

        keys = arb.positions_requiring_reconcile()
        assert keys[:2] == [new_key, old_key]


class TestActiveHistoryCap:
    def test_history_bounded_with_tombstone(self, tmp_path):
        store = ExitAttemptStore(tmp_path / "exit_attempts.json")
        arb = ExitArbiter(
            state_store=PositionExitStateStore(
                tmp_path / "exit_state.json"),
            attempt_store=store)
        result = arb.arbitrate(
            market_id=EXPIRED_TICKER, generation_id=GEN, held_side="yes",
            remaining_cc=300, breakeven_floor_cents=36,
            book=ExitBook(
                held_side="yes", liquidation_cents=60, qty_cc=500,
                age_ms=50),
            proposals=[ExitProposal(
                kind=ProposalKind.MODEL_EXIT.value, proposal_id="p1",
                limit_cents=55, qty_cc=300, reason="test")])
        assert result.status == "submitted"

        attempt = store.get_active(PKEY_EXPIRED)
        for i in range(store._MAX_ACTIVE_HISTORY + 200):
            attempt.history.append({
                "ts": time.time(), "from": "RECONCILING",
                "to": "RECONCILING", "note": f"churn:{i}"})
        store.save_active(attempt)

        reloaded = store.get_active(PKEY_EXPIRED)
        assert len(reloaded.history) == store._MAX_ACTIVE_HISTORY
        assert reloaded.history[0]["note"].startswith("history_truncated:")
        assert reloaded.history[-1]["note"] == "churn:%d" % (
            store._MAX_ACTIVE_HISTORY + 199)
