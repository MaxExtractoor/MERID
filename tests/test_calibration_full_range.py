"""Full-range calibration cap + evidence floor tests (2026-09-25).

The observed win-rate curve (``data/probability_tail_calibration.json``)
covers 5-99c on both sides.  Entries may never claim more model probability
than ``observed_win_rate + buffer`` at ANY held price — not just the cheap
tail — and a held-side price cell is only tradeable when the observed rate
clears ``price + fee + evidence_margin``.

Realized motivation (324 settled entries, 2026-08-25..2026-09-25):
NO 30-39c won 30.9% (-343c) and YES 50-59c won 42.9% (-253c) — the model's
unverified claimed edge was the loss source at every price, not just tails.
"""
from __future__ import annotations

import itertools
import math
from typing import Optional

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import compute_trade_decision
from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator


# A synthetic per-side curve faithful to the shipped artifact's shape:
# observed WR near (slightly above) price for favorites, materially below
# price for cheap YES, above price for mid-favorite NO.
def _calibrator(buffer: float = 0.05) -> TailProbabilityCalibrator:
    return TailProbabilityCalibrator(
        yes_held_prices=[0.10, 0.30, 0.40, 0.50, 0.55, 0.60, 0.75, 0.90],
        yes_actual_probs=[0.10, 0.28, 0.40, 0.53, 0.59, 0.63, 0.77, 0.90],
        no_held_prices=[0.10, 0.30, 0.40, 0.50, 0.55, 0.60, 0.75, 0.90],
        no_actual_probs=[0.12, 0.32, 0.43, 0.52, 0.61, 0.67, 0.83, 0.92],
        buffer=buffer,
    )


@pytest.fixture(autouse=True)
def _calibrated(monkeypatch):
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "load_tail_calibrator", lambda *a, **k: _calibrator())
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", True)
    # Deterministic vol path: no market-implied anchoring, no realized tracker
    # — the caller-supplied annualized_vol is what the model uses.
    monkeypatch.setattr(_td, "MERID_ANCHOR_VOL_TO_MARKET", False)
    monkeypatch.setattr(_td, "MERID_USE_REALIZED_VOL", False)


_ids = itertools.count()


def _decision(
    *,
    spot: float = 100.0,
    strike: float = 100.0,
    seconds_to_expiry: float = 900.0,
    yes_bid: float = 58.0,
    yes_ask: float = 60.0,
    no_bid: float = 38.0,
    no_ask: float = 40.0,
    fee_cents: float = 1.0,
    vol: float = 0.60,
    model_uncertainty: float = 0.0,
    p_yes_model: Optional[float] = None,
) -> object:
    n = next(_ids)
    return compute_trade_decision(
        run_id=f"cal_test_{n}",
        decision_id=f"cal_test_{n}",
        ticker="KXBTC15M-26SEP251200-00",
        asset="BTC",
        spot_price=spot,
        strike_price=strike,
        seconds_to_expiry=seconds_to_expiry,
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        no_bid_cents=no_bid,
        no_ask_cents=no_ask,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=fee_cents,
        annualized_vol=vol,
        model_uncertainty=model_uncertainty,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        p_yes_model=p_yes_model,
    )


class TestFullRangeCap:
    def test_cap_applies_above_tail_floor(self, monkeypatch):
        """Model claims beyond observed+buffer are capped at 60c, not just <35c."""
        monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
        d = _decision(
            yes_ask=60.0, no_ask=40.0,
            p_yes_model=0.95,  # hybrid claims far above curve(0.60)=0.63+0.05=0.68
        )
        p_yes_for_yes = d.indicators["p_yes_for_yes"]
        assert p_yes_for_yes <= 0.68 + 1e-9, (
            f"p_yes_for_yes {p_yes_for_yes} exceeded observed+buffer cap"
        )
        assert d.indicators["tail_calibration_yes_applied"] is True

    def test_model_below_cap_untouched(self, monkeypatch):
        """A model claim under the observed+buffer cap passes through unchanged."""
        monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
        d = _decision(yes_ask=60.0, no_ask=40.0, p_yes_model=0.60)
        assert math.isclose(d.indicators["p_yes_for_yes"], 0.60, abs_tol=1e-6)

    def test_flag_off_restores_tail_only(self, monkeypatch):
        """MERID_CALIBRATION_CAP_FULL_RANGE=0 reverts to <35c-only caps."""
        monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
        monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
        d = _decision(yes_ask=60.0, no_ask=40.0, p_yes_model=0.95)
        assert d.indicators["p_yes_for_yes"] > 0.68


class TestEvidenceFloor:
    def test_sub_breakeven_cell_blocked(self, monkeypatch):
        """YES@30c: observed 28% < price+fee+margin -> deterministic block."""
        monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
        d = _decision(
            yes_bid=28.0, yes_ask=30.0, no_bid=68.0, no_ask=70.0,
            p_yes_model=0.80,
        )
        assert d.selected_outcome != "yes"
        # The block may be reported by the edge-threshold leg first (the
        # capped p cannot clear the ask) or by the evidence floor — both are
        # valid rejections of a sub-breakeven cell.
        assert d.no_trade_reason in (
            "calibration_evidence_yes",
            "yes_edge_below_threshold",
            "cost_basis_override_yes",
        )

    def test_profitable_cell_allowed(self, monkeypatch):
        """NO@60c: observed 67% > 60+fee+margin -> cell eligible; high model p wins."""
        del monkeypatch
        # spot < strike -> Bachelier raw bearish (p_no ~0.68): the model's own
        # probability clears the net-edge bar in an evidence-positive cell.
        # TTE 400 keeps the scenario inside the bounded live-entry domain
        # (selections past 600s are now downgraded by the domain gate).
        d = _decision(
            spot=99.85, strike=100.0, seconds_to_expiry=400.0,
            yes_bid=38.0, yes_ask=40.0, no_bid=58.0, no_ask=60.0,
        )
        assert d.selected_outcome == "no"

    def test_margin_zero_uses_pure_breakeven(self, monkeypatch):
        """With margin=0 the floor is exactly price+fee."""
        monkeypatch.setattr(_td, "MERID_CALIBRATION_EVIDENCE_MARGIN", 0.0)
        # NO@40: curve 0.43 >= 0.40+0.01 -> cell eligible.  The trade itself
        # still needs edge; the assertion is that evidence does not block it.
        d = _decision(
            yes_bid=58.0, yes_ask=60.0, no_bid=38.0, no_ask=40.0,
        )
        assert d.no_trade_reason != "calibration_evidence_no"
        assert d.indicators["calibration_evidence_no"] is True

    def test_dual_no_curve_carries_no_evidence(self, monkeypatch):
        """A dual NO curve must not gate NO cells (it is not independent evidence)."""
        dual = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30],
            yes_actual_probs=[0.05, 0.20],
            no_held_prices=[0.90, 0.70],
            no_actual_probs=[0.95, 0.80],
        )
        assert dual.no_curve_is_dual
        monkeypatch.setattr(_td, "load_tail_calibrator", lambda *a, **k: dual)
        # spot < strike -> Bachelier bearish; NO@60 qualifies on economics and
        # the dual artifact must not veto it.  TTE 400 keeps the scenario
        # inside the bounded live-entry domain.
        d = _decision(
            spot=99.85, strike=100.0, seconds_to_expiry=400.0,
            yes_bid=38.0, yes_ask=40.0, no_bid=58.0, no_ask=60.0,
        )
        assert d.selected_outcome == "no"


class TestDeviationGuardInflationOnly:
    def test_large_downward_cap_no_violation(self, monkeypatch):
        """A >0.15 downward calibration move OUTSIDE the tail must not violate.

        Under the legacy guard this would have been a violation (abs deviation
        >0.15, not in tail); the guard now only polices inflation.
        """
        # spot > strike -> Bachelier raw ~0.94 -> capped to curve(0.60)+buf=0.68:
        # a -0.26 downward move at 60c (outside tail) must not violate.
        d = _decision(
            spot=100.5, strike=100.0,
            yes_bid=58.0, yes_ask=60.0, no_bid=38.0, no_ask=40.0,
        )
        assert d.indicators.get("tail_guard_violation_yes") is False

    def test_inflation_still_violates(self, monkeypatch):
        """An upward move >0.15 still trips the guard."""
        monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.9)
        monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.9)
        d = _decision(
            spot=100.0, strike=100.0,  # raw p_yes ~0.5
            yes_bid=78.0, yes_ask=80.0, no_bid=18.0, no_ask=20.0,
        )
        # Market anchor pulls p_yes toward ~0.79 -> +0.26 inflation vs raw.
        assert d.indicators.get("tail_guard_violation_yes") is True


class TestMarketLeanFadeGate:
    """2026-09-27: entries against a meaningful market lean are blocked for
    assets whose historical fade cohort is toxic (BTC/XRP/DOGE), allowed for
    ETH/SOL whose fade cohort is net-positive, and untouched for thin leans."""

    def _fade_decision(self, monkeypatch, asset: str, lean_yes_cents: float = 26.0):
        """Market: YES mid = 50c + lean; the calibrated model sees a weaker
        same-direction lean (p_no caps at 0.37) so the EV diff picks the
        OPPOSITE, cheap side — the toxic fade anatomy from live fills."""
        mid = 50.0 + lean_yes_cents
        ya = mid + 1.0
        yb = mid - 1.0
        na = 100.0 - yb
        nb = 100.0 - ya
        return _decision(
            spot=100.081, strike=100.0, seconds_to_expiry=400.0,
            yes_bid=yb, yes_ask=ya, no_bid=nb, no_ask=na,
            fee_cents=1.0, vol=0.60,
        )

    def test_btc_fade_into_strong_lean_blocked(self, monkeypatch):
        monkeypatch.setattr(_td, "MERID_FADE_ALLOWED_ASSETS", {"ETH", "SOL"})
        d = self._fade_decision(monkeypatch, "BTC", lean_yes_cents=26.0)
        assert d.selected_outcome is None, (
            f"fade into +21c market lean must be blocked, got {d.selected_outcome}"
        )
        assert d.no_trade_reason == "market_fade_blocked_no", d.no_trade_reason

    def test_eth_fade_allowed_by_cohort(self, monkeypatch):
        monkeypatch.setattr(_td, "MERID_FADE_ALLOWED_ASSETS", {"ETH", "SOL"})
        import merid.prediction.trade_decision as td2
        d = td2.compute_trade_decision(
            run_id="fade_test_eth", decision_id="fade_test_eth",
            ticker="KXETH15M-26SEP271200-00", asset="ETH",
            spot_price=100.081, strike_price=100.0, seconds_to_expiry=400.0,
            yes_bid_cents=75.0, yes_ask_cents=77.0,
            no_bid_cents=23.0, no_ask_cents=25.0,
            yes_depth_cc=200.0, no_depth_cc=200.0,
            fee_per_contract_cents=1.0, annualized_vol=0.60,
            model_uncertainty=0.0, data_quality="live", regime="normal",
            min_required_edge=0.02, settlement_reference="cfb_rti_live",
        )
        assert d.selected_outcome == "no", (
            f"ETH fade cohort is profitable; entry should survive, got {d.no_trade_reason}"
        )

    def test_thin_lean_not_gated(self, monkeypatch):
        """Below the lean threshold the gate must not fire."""
        monkeypatch.setattr(_td, "MERID_FADE_ALLOWED_ASSETS", {"ETH", "SOL"})
        d = self._fade_decision(monkeypatch, "BTC", lean_yes_cents=8.0)
        assert d.no_trade_reason != "market_fade_blocked_no", d.no_trade_reason
