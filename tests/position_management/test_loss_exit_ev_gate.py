"""Tests for the mid-trade loss-exit EV gate (2026-09-25).

The gate vetoes edge_decay / current_edge_reversal / time_stop /
model_invalidation_loss_exit candidates unless the settlement-aligned
evaluator independently concludes that liquidating beats the calibrated,
risk-reserved hold value (net_sell > conservative_hold + margin, persistent).
This prevents the measured premature-loss pattern of selling recoverable dips
at or below model fair on 0/100 binaries.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import merid.position_management.position_monitor as pm
from merid.event_venues.kalshi.settlement_aligned_exit import EvDecision
from merid.position_management.exit_decision import (
    ExitDecision,
    ExitPriority,
    ExitSourceLayer,
)
from merid.position_management.exit_policy import ExitReason


def _position():
    # fill provenance mirrors production positions (always created from
    # trusted fills); positions without it bypass the gate like the other
    # hardening guards so legacy unit tests still exercise trigger logic.
    return SimpleNamespace(
        position_id="pos-test-12345678",
        market_id="KXBTC15M-26SEP251200-00",
        outcome_side="yes",
        thesis_side="yes",
        side=SimpleNamespace(value="yes"),
        size=1,
        avg_entry_price_cents=55,
        unrealized_pnl_cents=-10,
        fill_source="exchange_fill",
        entry_fill_id="fill-test-1",
    )


def _decision(reason, priority=None):
    return ExitDecision(
        reason=reason,
        priority=priority or ExitPriority.TIME_STOP,
        source_layer=ExitSourceLayer.POLICY_LAYER,
        exit_price_cents=45,
    )


@pytest.fixture
def ev_env(monkeypatch):
    """Patch the settlement evaluator + market-state store with stubs.

    Returns a holder dict; ``set_eval(decision_or_exc)`` installs the stub
    evaluator the module-level ``get_exit_evaluator`` will return.
    """
    holder = {}

    def _make_evaluator(decision=None, exc=None):
        evaluator = MagicMock()
        if exc is not None:
            evaluator.evaluate = MagicMock(side_effect=exc)
        else:
            ev = SimpleNamespace(
                decision=decision,
                detail="test",
                bid_cents=45,
                net_sell_value_cents="42",
                conservative_hold_cents="40",
                switch_margin_cents=2,
                consecutive_breach=3,
            )
            evaluator.evaluate = MagicMock(return_value=ev)
        return evaluator

    def _set(decision=None, exc=None):
        holder["evaluator"] = _make_evaluator(decision=decision, exc=exc)

    store_stub = SimpleNamespace(
        get=lambda *a, **k: None, get_unified=lambda *a, **k: None
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: store_stub,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.settlement_aligned_exit.get_exit_evaluator",
        lambda: holder.get("evaluator") or _make_evaluator(
            decision=EvDecision.HOLD_DATA_INSUFFICIENT
        ),
    )
    holder["set"] = _set
    return holder


class TestGatedReasonSet:
    def test_loss_reasons_gated(self):
        gated = pm._LOSS_EXIT_EV_GATED_REASONS
        assert ExitReason.EDGE_DECAY in gated
        assert ExitReason.CURRENT_EDGE_REVERSAL in gated
        assert ExitReason.TIME_STOP in gated
        assert ExitReason.MODEL_INVALIDATION_LOSS_EXIT in gated

    def test_profit_and_hard_reasons_not_gated(self):
        gated = pm._LOSS_EXIT_EV_GATED_REASONS
        for reason in (
            ExitReason.TAKE_PROFIT,
            ExitReason.DYNAMIC_TAKE_PROFIT,
            ExitReason.TRAIL,
            ExitReason.AUTO_EXIT_99C,
            ExitReason.SETTLEMENT_GUARD,
            ExitReason.LOSS_CAP,
            ExitReason.STOP_LOSS,
            ExitReason.RISK,
            ExitReason.CONTINUATION_STOP,
        ):
            assert reason not in gated

    def test_gate_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MERID_LOSS_EXIT_EV_GATE", raising=False)
        assert pm._loss_exit_ev_gate_enabled() is True
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "0")
        assert pm._loss_exit_ev_gate_enabled() is False


class TestFilterEvGatedCandidates:
    def test_gate_disabled_passes_all(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "0")
        cands = [_decision(ExitReason.TIME_STOP), _decision(ExitReason.EDGE_DECAY)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands

    def test_no_gated_reasons_no_eval(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_SELL_VALUE_INFERIOR)
        cands = [_decision(ExitReason.TAKE_PROFIT, ExitPriority.TAKE_PROFIT)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands
        # No gated reasons → the evaluator must not even be consulted.
        assert ev_env["evaluator"].evaluate.call_count == 0

    def test_veto_drops_gated_keeps_ungated(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_SELL_VALUE_INFERIOR)
        cands = [
            _decision(ExitReason.TIME_STOP),
            _decision(ExitReason.EDGE_DECAY, ExitPriority.EDGE_DECAY),
            _decision(ExitReason.TAKE_PROFIT, ExitPriority.TAKE_PROFIT),
        ]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert [c.reason for c in out] == [ExitReason.TAKE_PROFIT]

    def test_pass_keeps_gated(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.SELL_SIGNALLED)
        cands = [
            _decision(ExitReason.TIME_STOP),
            _decision(ExitReason.TAKE_PROFIT, ExitPriority.TAKE_PROFIT),
        ]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands

    def test_pending_persistence_vetoes(self, monkeypatch, ev_env):
        """A breach without the required consecutive confirmations holds."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_PERSISTENCE_NOT_MET)
        cands = [_decision(ExitReason.MODEL_INVALIDATION_LOSS_EXIT)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == []

    def test_eval_exception_fails_closed(self, monkeypatch, ev_env):
        """An eval error must not let a loss exit slip through."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](exc=RuntimeError("no state store"))
        cands = [_decision(ExitReason.TIME_STOP)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == []

    def test_current_edge_reversal_gated(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_DATA_INSUFFICIENT)
        cands = [_decision(ExitReason.CURRENT_EDGE_REVERSAL)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == []

    def test_no_fill_provenance_bypasses_gate(self, monkeypatch, ev_env):
        """Synthetic/test positions keep trigger behavior (hardening convention)."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_SELL_VALUE_INFERIOR)
        pos = _position()
        pos.fill_source = None
        pos.entry_fill_id = None
        cands = [_decision(ExitReason.TIME_STOP)]
        out = pm._filter_ev_gated_exit_candidates(pos, cands, None, 400.0)
        assert out == cands
        assert ev_env["evaluator"].evaluate.call_count == 0


class TestLossExitEvJustified:
    def test_sell_signalled_allowed(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.SELL_SIGNALLED)
        ok, ev = pm._loss_exit_ev_justified(_position(), None, 400.0)
        assert ok is True
        assert ev.decision == EvDecision.SELL_SIGNALLED
        kwargs = ev_env["evaluator"].evaluate.call_args.kwargs
        assert kwargs["canonical_reason"] == "value_switch_exit"
        assert kwargs["held_side"] == "yes"
        assert kwargs["market_key"] == "KXBTC15M-26SEP251200-00"

    def test_hold_decisions_veto(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        for decision in (
            EvDecision.HOLD_SELL_VALUE_INFERIOR,
            EvDecision.HOLD_DATA_INSUFFICIENT,
            EvDecision.HOLD_PERSISTENCE_NOT_MET,
            EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED,
        ):
            ev_env["set"](decision=decision)
            ok, _ = pm._loss_exit_ev_justified(_position(), None, 400.0)
            assert ok is False

    def test_exception_fails_closed(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](exc=RuntimeError("boom"))
        ok, ev = pm._loss_exit_ev_justified(_position(), None, 400.0)
        assert ok is False
        assert ev is None
