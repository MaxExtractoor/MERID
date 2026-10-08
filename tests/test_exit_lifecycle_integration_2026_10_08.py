"""Deterministic exit-lifecycle integration scenarios (2026-10-08 release).

Covers the release-proof scenarios that exercise the repaired obligation /
taxonomy / accounting seams end-to-end at the layer they live in:

- Partial IOC fill, then a late additional fill on the same attempt.
- Late fill arriving AFTER an exchange-terminal observation (fill is truth).
- New-window rollover: obligations are scoped by position_key so a fresh
  window's position is never blocked by the prior window's locks.
- Operational exits on 0.75-contract positions across all five assets and
  both sides pass the monitor without EV consultation.
- Restart with a persisted-but-unsubmitted exit: rehydrate + sweep
  terminalizes the stale obligation instead of wedging it.
"""

import json
import time

import pytest

import merid.event_venues.kalshi.order_attempt_store as attempt_store_module
from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptState,
    OrderAttemptStore,
)
from merid.position_management.exit_decision import (
    ExitDecision,
    ExitPriority,
    ExitSourceLayer,
)
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import (
    PositionMonitor,
    _filter_ev_gated_exit_candidates,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        attempt_store_module, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db")
    )
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


@pytest.fixture()
def monitor(tmp_path, monkeypatch, store):
    monkeypatch.setenv(
        "MERID_EXIT_INTENT_PERSISTENCE_PATH", str(tmp_path / "exit_intents.json")
    )
    return PositionMonitor()


def _attempt(store, position_key, ticker="KXBTC15M-W1"):
    return store.create_exit_attempt(
        exit_intent_id=f"intent_{position_key}_{time.time_ns()}",
        position_key=position_key,
        ticker=ticker,
        reason="take_profit",
        client_order_id=f"coid_{position_key}_{time.time_ns()}",
        requested_quantity=75,
        requested_limit_cents=55,
    )


class TestPartialAndLateFill:
    def test_partial_ioc_then_late_fill_completes(self, store):
        """IOC partial → PARTIALLY_FILLED → the late residual fill arrives
        through the fills feed and terminalizes the attempt FILLED."""
        rec = _attempt(store, "pos-pf")
        store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.SUBMITTING.value,
            actor="t", reason="dispatch")
        store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.PARTIALLY_FILLED.value,
            actor="t", reason="ioc_partial", exchange_order_id="xo-1")
        late = store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.FILLED.value,
            actor="fills_poller", reason="late_fill_applied",
            exchange_order_id="xo-1")
        assert late.state == ExitOrderAttemptState.FILLED.value

    def test_late_fill_after_reject_is_ground_truth(self, store):
        """Kalshi can fill moments before our reject observation lands; the
        REJECTED_EXCHANGE -> FILLED edge keeps the ledger authoritative."""
        rec = _attempt(store, "pos-lf")
        store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.SUBMITTING.value,
            actor="t", reason="dispatch")
        store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.REJECTED_EXCHANGE.value,
            actor="t", reason="route_reject")
        late = store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.FILLED.value,
            actor="fills_poller", reason="late_fill_after_terminal_obs")
        assert late.state == ExitOrderAttemptState.FILLED.value


class TestWindowRollover:
    def test_new_window_not_blocked_by_old_obligation(self, monitor, store):
        """Old window's settled obligation is terminal; a same-asset new
        window position mints its own attempt and is not held by stale locks."""
        old = _attempt(store, "pos-old-window", ticker="KXBTC15M-W0")
        store.transition_exit_attempt(
            old.attempt_id, ExitOrderAttemptState.TERMINAL_UNFILLED.value,
            actor="t", reason="unsubmitted_age_limit:obligation_orphaned_position_gone")
        # Stale in-memory artifacts from the old window are scoped to its key.
        monitor._exit_intent_in_flight["pos-old-window"] = {
            "state": "RECONCILED", "timestamp": time.time() - 3600,
            "client_order_id": old.client_order_id,
        }
        new = _attempt(store, "pos-new-window", ticker="KXBTC15M-W1")
        assert new.state == ExitOrderAttemptState.INTENT_PERSISTED.value
        assert monitor._is_exit_intent_in_flight("pos-new-window") is False

    def test_expired_market_terminalizes_obligation(self, monitor, store):
        rec = _attempt(store, "pos-exp", ticker="KXETH15M-EXP")
        store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.SUBMITTING.value,
            actor="t", reason="dispatch")
        swept = store.transition_exit_attempt(
            rec.attempt_id, ExitOrderAttemptState.CANCELED.value,
            actor="t", reason="expired_market_sweep")
        assert swept.state == ExitOrderAttemptState.CANCELED.value


class TestOperationalExitAcrossAssetsAndSides:
    @pytest.mark.parametrize(
        "ticker,asset",
        [
            ("KXBTC15M-W1", "BTC"),
            ("KXETH15M-W1", "ETH"),
            ("KXSOL15M-W1", "SOL"),
            ("KXXRP15M-W1", "XRP"),
            ("KXDOGE15M-W1", "DOGE"),
        ],
    )
    @pytest.mark.parametrize("side", [PositionSide.YES, PositionSide.NO])
    def test_operational_exits_pass_without_eval_on_fractional(
        self, monkeypatch, ticker, asset, side
    ):
        """A 0.75-contract position (75cc) with an operational exit reason
        passes the monitor filter with zero evaluator consultations — the
        evaluator must never be the bottleneck for mandatory closes."""
        eval_calls = []

        def _boom(*a, **k):
            eval_calls.append(1)
            raise AssertionError("evaluator consulted for operational exit")

        monkeypatch.setattr(
            "merid.event_venues.kalshi.settlement_aligned_exit.get_exit_evaluator",
            _boom,
        )
        pos = Position(
            position_id=f"pos-{asset}-{side.value}",
            market_id=ticker,
            side=side,
            size=__import__("decimal").Decimal("0.75"),
            avg_entry_price_cents=50,
            fill_source="test",
            entry_fill_id="fill-1",
        )
        cands = [
            ExitDecision(
                reason=ExitReason.EDGE_DECAY,
                priority=ExitPriority.TRAIL,
                source_layer=ExitSourceLayer.POSITION_LEVEL,
                exit_price_cents=55,
            ),
            ExitDecision(
                reason=ExitReason.HARD_PROFIT_LOCK,
                priority=ExitPriority.TAKE_PROFIT,
                source_layer=ExitSourceLayer.POSITION_LEVEL,
                exit_price_cents=90,
            ),
        ]
        out = _filter_ev_gated_exit_candidates(pos, cands, None, 400.0)
        assert len(out) == 2
        assert eval_calls == []


class TestRestartRecovery:
    def test_restart_sweeps_unsubmitted_persisted_exit(
        self, tmp_path, monkeypatch, store
    ):
        """Persisted INTENT_PERSISTED from a killed run is rehydrated then
        terminalized by the stale-obligation sweep — never silently wedged."""
        stale = store.create_exit_attempt(
            exit_intent_id="intent_killed_run",
            position_key="pos-killed",
            ticker="KXBTC15M-W1",
            reason="take_profit",
            client_order_id="coid_killed_run",
            requested_quantity=75,
            requested_limit_cents=55,
        )
        conn = store._get_conn()
        with conn:
            conn.execute(
                "UPDATE exit_order_attempts SET created_at=? WHERE attempt_id=?",
                (time.time() - 600.0, stale.attempt_id),
            )
        monkeypatch.setenv(
            "MERID_EXIT_INTENT_PERSISTENCE_PATH", str(tmp_path / "e2.json")
        )
        monitor = PositionMonitor()  # rehydrates from the store on init
        assert "pos-killed" in monitor._exit_intent_in_flight
        assert monitor._sweep_stale_exit_obligations() >= 1
        assert (
            store.get_exit_attempt(stale.attempt_id).state
            == ExitOrderAttemptState.TERMINAL_UNFILLED.value
        )
