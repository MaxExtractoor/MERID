"""Tests for the mid-trade loss-exit EV gate.

2026-10-08 repair: the shared exit taxonomy is the sole classification
authority.  Only DISCRETIONARY reasons (``stop_loss``, ``loss_cut``,
``value_switch_exit``) consult the EV comparison; OPERATIONAL and EMERGENCY
exits are never vetoed here, and UNKNOWN reasons fail closed.  The monitor
passes the candidate's real canonical reason to the evaluator instead of the
hardcoded ``value_switch_exit`` that used to convert every gated call into a
discretionary one.
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
    def test_discretionary_reasons_gated(self):
        assert pm._exit_reason_is_ev_gated(ExitReason.STOP_LOSS) is True
        assert pm._exit_reason_is_ev_gated(ExitReason.LOSS_CUT_40PCT) is True
        assert pm._exit_reason_is_ev_gated("value_switch_exit") is True

    def test_operational_and_emergency_reasons_not_gated(self):
        for reason in (
            ExitReason.EDGE_DECAY,
            ExitReason.CURRENT_EDGE_REVERSAL,
            ExitReason.TIME_STOP,
            ExitReason.MODEL_INVALIDATION_LOSS_EXIT,
            ExitReason.TAKE_PROFIT,
            ExitReason.DYNAMIC_TAKE_PROFIT,
            ExitReason.TRAIL,
            ExitReason.AUTO_EXIT_99C,
            ExitReason.SETTLEMENT_GUARD,
            ExitReason.LOSS_CAP,
            ExitReason.RISK,
            ExitReason.CONTINUATION_STOP,
            ExitReason.EXTREME_PROFIT,
            ExitReason.HARD_PROFIT_LOCK,
        ):
            assert pm._exit_reason_is_ev_gated(reason) is False, reason

    def test_unknown_reason_gated_fail_closed(self):
        assert pm._exit_reason_is_ev_gated("totally_made_up_reason") is True

    def test_no_monitor_reason_classifies_unknown(self):
        """Every monitor ExitReason must resolve to a known class — the
        fail-closed UNKNOWN path would silently veto a previously-mechanical
        exit (2026-10-08 regression guard)."""
        for reason in ExitReason:
            assert pm._exit_policy_class(reason).value != "unknown", reason.value

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

    def test_veto_drops_discretionary_keeps_operational(self, monkeypatch, ev_env):
        """A vetoed discretionary exit must not suppress operational exits
        raised in the same tick."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_SELL_VALUE_INFERIOR)
        cands = [
            _decision(ExitReason.STOP_LOSS),
            _decision(ExitReason.TIME_STOP),
            _decision(ExitReason.TAKE_PROFIT, ExitPriority.TAKE_PROFIT),
        ]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert [c.reason for c in out] == [ExitReason.TIME_STOP, ExitReason.TAKE_PROFIT]

    def test_operational_exits_never_consult_evaluator(self, monkeypatch, ev_env):
        """edge_decay / time_stop / model_invalidation submit mechanically —
        the 2026-09-25 bug EV-vetoed exactly these reasons."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](exc=RuntimeError("evaluator must not be called"))
        cands = [
            _decision(ExitReason.EDGE_DECAY),
            _decision(ExitReason.TIME_STOP),
            _decision(ExitReason.MODEL_INVALIDATION_LOSS_EXIT),
        ]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands

    def test_pass_keeps_gated(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.SELL_SIGNALLED)
        cands = [
            _decision(ExitReason.STOP_LOSS),
            _decision(ExitReason.TAKE_PROFIT, ExitPriority.TAKE_PROFIT),
        ]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands

    def test_pending_persistence_vetoes(self, monkeypatch, ev_env):
        """A breach without the required consecutive confirmations holds."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_PERSISTENCE_NOT_MET)
        cands = [_decision(ExitReason.STOP_LOSS)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == []

    def test_eval_exception_fails_closed(self, monkeypatch, ev_env):
        """An eval error must not let a discretionary loss exit slip through."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](exc=RuntimeError("no state store"))
        cands = [_decision(ExitReason.STOP_LOSS)]
        out = pm._filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == []

    def test_no_fill_provenance_bypasses_gate(self, monkeypatch, ev_env):
        """Synthetic/test positions keep trigger behavior (hardening convention)."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.HOLD_SELL_VALUE_INFERIOR)
        pos = _position()
        pos.fill_source = None
        pos.entry_fill_id = None
        cands = [_decision(ExitReason.STOP_LOSS)]
        out = pm._filter_ev_gated_exit_candidates(pos, cands, None, 400.0)
        assert out == cands
        assert ev_env["evaluator"].evaluate.call_count == 0


class TestLossExitEvJustified:
    def test_sell_signalled_allowed(self, monkeypatch, ev_env):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        ev_env["set"](decision=EvDecision.SELL_SIGNALLED)
        ok, ev = pm._loss_exit_ev_justified(
            _position(), None, 400.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is True
        assert ev.decision == EvDecision.SELL_SIGNALLED
        kwargs = ev_env["evaluator"].evaluate.call_args.kwargs
        # The evaluator is consulted under the candidate's REAL canonical
        # reason — the old code hardcoded "value_switch_exit" and silently
        # converted operational exits into discretionary ones.
        assert kwargs["canonical_reason"] == "stop_loss"
        assert kwargs["held_side"] == "yes"
        assert kwargs["market_key"] == "KXBTC15M-26SEP251200-00"

    def test_bypass_decisions_allow_operational_exits(self, monkeypatch, ev_env):
        """OPERATIONAL/EMERGENCY reasons pass through BYPASS_* decisions —
        the evaluator records telemetry but cannot veto a mandatory close."""
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "1")
        for decision in (EvDecision.BYPASS_OPERATIONAL, EvDecision.BYPASS_EMERGENCY):
            ev_env["set"](decision=decision)
            ok, _ = pm._loss_exit_ev_justified(
                _position(), None, 400.0, exit_reason=ExitReason.EDGE_DECAY
            )
            assert ok is True, decision

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
