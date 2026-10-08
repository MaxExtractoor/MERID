"""Shared exit-taxonomy authority tests (2026-10-08 repair).

The position monitor previously maintained a private EV-gate set
(``_LOSS_EXIT_EV_GATED_REASONS``) that vetoed EDGE_DECAY / TIME_STOP /
MODEL_INVALIDATION exits whose shared-taxonomy class is OPERATIONAL, and
hardcoded ``canonical_reason="value_switch_exit"`` so the evaluator treated
mandatory closes as discretionary.  These tests pin the repaired contract:

- The shared taxonomy is the sole classification authority.
- OPERATIONAL / EMERGENCY exits are never EV-vetoed (evaluator BYPASS).
- DISCRETIONARY exits remain EV-gated.
- UNKNOWN reasons fail closed.
- A configured exposure deadline rescues a discretionary hold caused *only*
  by missing model inputs; it does not rescue mechanical book failures or
  override the evaluator's explicit near-settlement terminal.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from merid.position_management.exit_decision import (
    ExitDecision,
    ExitPriority,
    ExitSourceLayer,
)
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position_monitor import (
    _exit_reason_is_ev_gated,
    _filter_ev_gated_exit_candidates,
    _loss_exit_ev_justified,
)
from merid.position_management.position import Position, PositionSide
from merid.event_venues.kalshi.settlement_aligned_exit import (
    EvDecision,
    EvExitEvaluation,
)


def _position(**kwargs) -> Position:
    defaults = {
        "market_id": "KXBTC15M-POLICY",
        "series_ticker": "KXBTC15M",
        "side": PositionSide.YES,
        "size": 1,
        "avg_entry_price_cents": 50,
        "all_in_entry_basis_cents": 50,
        "fill_source": "test",
        "entry_fill_id": "test-fill",
    }
    defaults.update(kwargs)
    return Position(**defaults)


def _cand(reason: ExitReason) -> ExitDecision:
    return ExitDecision(
        reason=reason,
        priority=ExitPriority.TAKE_PROFIT,
        source_layer=ExitSourceLayer.POSITION_LEVEL,
        exit_price_cents=50,
    )


def _ev(decision: "EvDecision", detail: str = "") -> EvExitEvaluation:
    return EvExitEvaluation(
        evaluation_id="ev-test",
        market_key="KXBTC15M-POLICY",
        position_id="pos-test",
        held_side="yes",
        canonical_reason="stop_loss",
        exit_class="discretionary",
        decision=decision,
        detail=detail,
        quantity_contracts="1",
        ts=0.0,
    )


class _FakeEvaluator:
    """Returns canned evaluations while capturing the canonical reason."""

    def __init__(self, ev: EvExitEvaluation):
        self._ev = ev
        self.seen_reasons = []

    def evaluate(self, position, **kwargs):
        self.seen_reasons.append(kwargs.get("canonical_reason"))
        return self._ev


@pytest.fixture
def stub_evaluator(monkeypatch):
    """Patch get_exit_evaluator + market state store; return installer."""
    stub_state = SimpleNamespace()
    stub_store = SimpleNamespace(
        get=lambda market_id: stub_state,
        get_unified=lambda market_id: stub_state,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: stub_store,
    )

    def _install(ev: EvExitEvaluation) -> _FakeEvaluator:
        fake = _FakeEvaluator(ev)
        monkeypatch.setattr(
            "merid.event_venues.kalshi.settlement_aligned_exit.get_exit_evaluator",
            lambda: fake,
        )
        return fake

    return _install


class TestSharedTaxonomyClassification:
    """The shared taxonomy is the only classification authority."""

    @pytest.mark.parametrize(
        "reason",
        [
            ExitReason.EDGE_DECAY,
            ExitReason.CURRENT_EDGE_REVERSAL,
            ExitReason.TIME_STOP,
            ExitReason.MODEL_INVALIDATION_LOSS_EXIT,
            ExitReason.TAKE_PROFIT,
            ExitReason.TRAIL,
            ExitReason.AUTO_EXIT_99C,
            ExitReason.HARD_PROFIT_LOCK,
            ExitReason.LOSS_CAP,
        ],
    )
    def test_operational_and_emergency_reasons_not_ev_gated(self, reason):
        assert _exit_reason_is_ev_gated(reason) is False

    @pytest.mark.parametrize(
        "reason",
        [ExitReason.STOP_LOSS, ExitReason.LOSS_CUT_40PCT, "value_switch_exit"],
    )
    def test_discretionary_reasons_ev_gated(self, reason):
        assert _exit_reason_is_ev_gated(reason) is True

    def test_unknown_reason_gated_fail_closed(self):
        assert _exit_reason_is_ev_gated("totally_made_up_reason") is True


class TestLossExitEvJustified:
    """The evaluator is consulted under the real canonical reason and its
    BYPASS_* decisions authorize mandatory closes."""

    def test_operational_reason_bypasses_and_passes_true_reason(
        self, monkeypatch, stub_evaluator
    ):
        fake = stub_evaluator(_ev(EvDecision.BYPASS_OPERATIONAL))
        ok, ev = _loss_exit_ev_justified(
            _position(), None, 120.0, exit_reason=ExitReason.EDGE_DECAY
        )
        assert ok is True
        # edge_decay canonicalizes to signal_reversal — not value_switch_exit.
        assert fake.seen_reasons == ["signal_reversal"]

    def test_emergency_reason_bypasses(self, stub_evaluator):
        stub_evaluator(_ev(EvDecision.BYPASS_EMERGENCY))
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 120.0, exit_reason=ExitReason.SETTLEMENT_GUARD
        )
        assert ok is True

    def test_unknown_reason_fails_closed(self, stub_evaluator):
        stub_evaluator(_ev(EvDecision.BLOCK_UNKNOWN_REASON))
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 400.0, exit_reason="totally_made_up_reason"
        )
        assert ok is False

    def test_discretionary_sell_signalled_allows(self, stub_evaluator):
        stub_evaluator(_ev(EvDecision.SELL_SIGNALLED))
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 400.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is True

    def test_discretionary_hold_outside_deadline_vetoes(self, stub_evaluator):
        stub_evaluator(
            _ev(
                EvDecision.HOLD_DATA_INSUFFICIENT,
                "uncalibrated_model_inputs:vol_source=none/calibration=none",
            )
        )
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 400.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is False

    def test_degraded_deadline_rescues_missing_input_hold(self, stub_evaluator):
        """Inside the configured exposure deadline, a discretionary hold whose
        blockers are ALL missing-model-input classes proceeds mechanically —
        unavailable vol/RTI cannot silently cancel a risk deadline."""
        stub_evaluator(
            _ev(
                EvDecision.HOLD_DATA_INSUFFICIENT,
                "uncalibrated_model_inputs:vol_source=none;"
                "rti_unavailable_or_ineligible;no_model_valuation",
            )
        )
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 200.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is True

    def test_degraded_deadline_refuses_mechanical_blockers(self, stub_evaluator):
        """The degraded rescue must not apply when a mechanical book/provenance
        blocker is mixed in — unverifiable market data still fails closed."""
        stub_evaluator(
            _ev(
                EvDecision.HOLD_DATA_INSUFFICIENT,
                "uncalibrated_model_inputs:vol_source=none;stale_book",
            )
        )
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 200.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is False

    def test_near_settlement_terminal_not_overridden(self, stub_evaluator):
        """HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED is the evaluator's explicit
        terminal inside the final averaging minute — settlement exposure is
        recorded, not silently sold into an unpriceable book."""
        stub_evaluator(_ev(EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED))
        ok, _ = _loss_exit_ev_justified(
            _position(), None, 30.0, exit_reason=ExitReason.STOP_LOSS
        )
        assert ok is False


class TestFilterEvGatedCandidates:
    """Mixed candidate lists keep mandatory exits even when a discretionary
    exit in the same tick is vetoed."""

    def test_vetoed_discretionary_does_not_suppress_operational(
        self, monkeypatch, stub_evaluator
    ):
        stub_evaluator(
            _ev(
                EvDecision.HOLD_DATA_INSUFFICIENT,
                "uncalibrated_model_inputs:vol_source=none;stale_book",
            )
        )
        cands = [_cand(ExitReason.EDGE_DECAY), _cand(ExitReason.STOP_LOSS)]
        out = _filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert [c.reason for c in out] == [ExitReason.EDGE_DECAY]

    def test_all_operational_passthrough_without_eval(
        self, monkeypatch, stub_evaluator
    ):
        fake = stub_evaluator(_ev(EvDecision.HOLD_DATA_INSUFFICIENT))
        cands = [_cand(ExitReason.EDGE_DECAY), _cand(ExitReason.TAKE_PROFIT)]
        out = _filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert len(out) == 2
        assert fake.seen_reasons == []  # evaluator never consulted

    def test_gate_disabled_passthrough(self, monkeypatch):
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "0")
        cands = [_cand(ExitReason.STOP_LOSS)]
        out = _filter_ev_gated_exit_candidates(_position(), cands, None, 400.0)
        assert out == cands

    def test_no_provenance_passthrough(self, monkeypatch, stub_evaluator):
        stub_evaluator(_ev(EvDecision.HOLD_DATA_INSUFFICIENT))
        pos = _position(fill_source=None, entry_fill_id=None)
        cands = [_cand(ExitReason.STOP_LOSS)]
        out = _filter_ev_gated_exit_candidates(pos, cands, None, 400.0)
        assert out == cands
