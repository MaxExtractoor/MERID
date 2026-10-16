"""Regression tests for the measured claim-vs-realized edge-bias correction.

2026-10-16: the artifact's ``edge_bias.by_source`` block carries decayed,
market-normalized ``expected_net_ev - cf_pnl`` per ``ASSET|side|entry_source``
— measured on fills AND vetoed evals so the gate's own selection bias is
visible.  ``edge_bias_correction_cents`` turns it into a signed reserve:
positive = extra cost on over-claiming cohorts, negative = bounded rebate
on confidently under-claiming cohorts.
"""
from __future__ import annotations

import os

import pytest

from merid.prediction import evidence_policy as ep
from merid.prediction.trade_decision import (
    EntryCostStack,
    compute_edge,
    entry_cost_stack_from_breakdown,
)


def _rec(n_eff, gap_wsum, gap_sq=0.0, n_post=None, wsum_post=None, sq_post=None):
    return {
        "n_eff": float(n_eff),
        "gap_wsum": float(gap_wsum),
        "gap_sq_wsum": float(gap_sq),
        "n_eff_post": float(n_eff if n_post is None else n_post),
        "gap_wsum_post": float(gap_wsum if wsum_post is None else wsum_post),
        "gap_sq_wsum_post": float(gap_sq if sq_post is None else sq_post),
    }


def _evidence(by_source):
    return {"edge_bias": {"by_source": by_source}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Deterministic knobs; production .env epoch must not leak in.
    monkeypatch.delenv("MERID_EVIDENCE_EPOCH_TS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_CORRECTION", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_MIN_NEFF", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_PRIOR_K", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_CAP_CENTS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_REBATE_CAP_CENTS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_REBATE_Z", raising=False)


class TestLookupAndMapping:
    def test_ask_basis_uses_side_ask_source(self):
        ev = _evidence({
            "SOL|yes|yes_ask": _rec(30, 600.0),       # +20c over-claim
            "SOL|yes|no_bid_complement": _rec(30, -600.0),
        })
        c = ep.edge_bias_correction_cents(ev, "SOL", "yes", "ask")
        assert c > 0.0
        c_bid = ep.edge_bias_correction_cents(ev, "SOL", "yes", "bid")
        assert c_bid < 0.0 or c_bid == 0.0  # under-claim needs confidence too

    def test_bid_basis_maps_to_opposite_complement(self):
        ev = _evidence({"DOGE|no|yes_bid_complement": _rec(30, -1500.0, 3000.0)})
        assert ep.edge_bias_correction_cents(ev, "DOGE", "no", "bid") < 0.0

    def test_side_star_fallback(self):
        ev = _evidence({"XRP|no|*": _rec(25, 500.0)})
        assert ep.edge_bias_correction_cents(ev, "XRP", "no", "ask") > 0.0

    def test_missing_cohort_returns_zero(self):
        assert ep.edge_bias_correction_cents(None, "BTC", "yes", "ask") == 0.0
        ev = _evidence({"ETH|yes|yes_ask": _rec(30, 300.0)})
        assert ep.edge_bias_correction_cents(ev, "BTC", "yes", "ask") == 0.0


class TestStandingAndCaps:
    def test_min_neff_required(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_MIN_NEFF", "12")
        ev = _evidence({"SOL|yes|yes_ask": _rec(11.9, 300.0)})
        assert ep.edge_bias_correction_cents(ev, "SOL", "yes", "ask") == 0.0

    def test_overclaim_charge_capped(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_CAP_CENTS", "8")
        ev = _evidence({"SOL|yes|yes_ask": _rec(100, 3000.0)})  # +30c mean
        assert ep.edge_bias_correction_cents(ev, "SOL", "yes", "ask") == 8.0

    def test_shrinkage_pulls_small_n_toward_zero(self):
        # Same +5c mean on n=12 vs n=100: shrunk = wsum/(n+K), both under cap.
        ev12 = _evidence({"SOL|yes|yes_ask": _rec(12, 60.0)})
        ev100 = _evidence({"SOL|yes|yes_ask": _rec(100, 500.0)})
        c12 = ep.edge_bias_correction_cents(ev12, "SOL", "yes", "ask")
        c100 = ep.edge_bias_correction_cents(ev100, "SOL", "yes", "ask")
        assert 0 < c12 < c100
        assert abs(c12 - 60.0 / 20.0) < 1e-9    # 3.0c: shrunk toward 0
        assert abs(c100 - 500.0 / 108.0) < 1e-9 # ~4.63c: near full strength

    def test_epoch_requires_post_mass(self, monkeypatch):
        monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", "1700000000")
        # Pre-epoch mass only -> no standing.
        ev = _evidence({"SOL|yes|yes_ask": _rec(50, 1000.0, n_post=0.0, wsum_post=0.0)})
        assert ep.edge_bias_correction_cents(ev, "SOL", "yes", "ask") == 0.0
        # Post-epoch mass -> applies.
        ev2 = _evidence({"SOL|yes|yes_ask": _rec(50, 1000.0, n_post=20.0, wsum_post=400.0)})
        assert ep.edge_bias_correction_cents(ev2, "SOL", "yes", "ask") > 0.0


class TestRebateConfidence:
    def test_confident_underclaim_rebates(self, monkeypatch):
        # mean=-30c, se small -> mean + z*se < 0 -> rebate -4c cap.
        ev = _evidence({"ETH|yes|yes_ask": _rec(50, -1500.0, 2000.0)})
        c = ep.edge_bias_correction_cents(ev, "ETH", "yes", "ask")
        assert c == -4.0

    def test_noisy_underclaim_no_rebate(self, monkeypatch):
        # mean=-5c but huge variance -> upper bound still positive.
        ev = _evidence({"ETH|yes|yes_ask": _rec(15, -75.0, 8000.0)})
        c = ep.edge_bias_correction_cents(ev, "ETH", "yes", "ask")
        assert c == 0.0

    def test_rebate_shrinks_before_cap(self, monkeypatch):
        # mean=-10c on n=15, zero var: shrunk = -150/23 = -6.5 -> cap 4.
        ev = _evidence({"XRP|yes|yes_ask": _rec(15, -150.0, 0.0)})
        c = ep.edge_bias_correction_cents(ev, "XRP", "yes", "ask")
        # var=0 -> se=0 -> mean<0 confident; rebate = min(4, 6.52) = 4
        assert c == -4.0


class TestIntegration:
    def test_compute_edge_subtracts_signed_correction(self):
        base = compute_edge(
            p_yes=0.60, selected_side="yes", entry_price=0.50,
            entry_fee=0.01, exit_cost_reserve=0.0, model_risk_reserve=0.0,
        )
        charged = compute_edge(
            p_yes=0.60, selected_side="yes", entry_price=0.50,
            entry_fee=0.01, exit_cost_reserve=0.0, model_risk_reserve=0.0,
            edge_bias_correction=0.05,
        )
        rebated = compute_edge(
            p_yes=0.60, selected_side="yes", entry_price=0.50,
            entry_fee=0.01, exit_cost_reserve=0.0, model_risk_reserve=0.0,
            edge_bias_correction=-0.03,
        )
        assert charged.net_edge == pytest.approx(base.net_edge - 0.05)
        assert rebated.net_edge == pytest.approx(base.net_edge + 0.03)
        assert charged.edge_bias_correction == 0.05

    def test_pi_star_identity_with_signed_term(self):
        stack = EntryCostStack(
            executable_price_prob=0.50, venue_fee_prob=0.01,
            spread_slippage_prob=0.0, model_uncertainty_prob=0.0,
            required_net_edge_prob=0.02, edge_bias_prob=-0.03,
        )
        # p_selected - pi_star == net_edge - required
        assert 0.60 - stack.pi_star == pytest.approx(
            stack.net_edge_after_required(0.60)
        )
        # Rebate lowers the hurdle by 3c.
        plain = EntryCostStack(
            executable_price_prob=0.50, venue_fee_prob=0.01,
            spread_slippage_prob=0.0, model_uncertainty_prob=0.0,
            required_net_edge_prob=0.02,
        )
        assert stack.pi_star == pytest.approx(plain.pi_star - 0.03)

    def test_stack_from_breakdown_carries_correction(self):
        bd = compute_edge(
            p_yes=0.60, selected_side="yes", entry_price=0.50,
            entry_fee=0.01, exit_cost_reserve=0.0, model_risk_reserve=0.0,
            edge_bias_correction=0.04,
        )
        stack = entry_cost_stack_from_breakdown(bd, 0.02)
        assert stack.edge_bias_prob == pytest.approx(0.04)

    def test_disabled_flag(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_CORRECTION", "0")
        ev = _evidence({"SOL|yes|yes_ask": _rec(100, 3000.0)})
        assert ep.edge_bias_correction_cents(ev, "SOL", "yes", "ask") == 0.0
