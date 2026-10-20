"""Regression tests for the 2026-10-19 momentum-capture fixes.

Three defects were found by replaying live quota/scalp losses against the
published 15-minute binary literature:

1. quota_candidate_order / quota_dir_absent_min_p — with no directional read
   (dir_pref None) the quota lane emitted pure-argmax coin flips and even
   tried the alternate side; observed live as dir_pref=None taker emissions
   at 75-80c asks with -3..-10c claimed EV.  With no direction the emitted
   side must clear a conviction floor and never fall back to the unevidenced
   alternate.

2. _scalp_arm_override_cents — the static +10c trailing arm missed the
   +4-9c peak cluster where losing scalps lived (XRP YES@70 peak 77c -> 1c,
   DOGE YES@69 peak 73c -> 1c, trailing_activated=False throughout).  Probe
   entries (entry_edge <= 0) arm at +5c and all positions arm at +6c inside
   the final 240s.

3. Settlement-lane tail reserve — the generic model_uncertainty +
   calibration-gap reserve stack (~4-5c) was charged on banked-sample
   claims whose true residual risk is (1 - p_side) * entry (~0.1c at
   p=0.999), so every settlement-convergence admission died on economics
   (observed: KXXRP15M-1745 tte=34s NO@99c p=0.999 -> -4.34c net vs the
   lane's 0.75c bound).  The favored side's reserve is now the
   distribution's own tail loss.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import dataclass
from typing import List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import window_quota as wq
import merid.prediction.trade_decision as td
from merid.prediction.trade_decision import compute_trade_decision
from merid.prediction.settlement_distribution import (
    SettlementDistribution,
    build_settlement_state,
    compute_settlement_distribution,
)
from merid.position_management.position_monitor import _scalp_arm_override_cents


# ---------------------------------------------------------------------------
# 1. Quota evidence gate
# ---------------------------------------------------------------------------


class TestQuotaEvidenceGate:
    def test_candidate_order_dir_pref_first(self):
        assert wq.quota_candidate_order("no", "yes") == ["no", "yes"]

    def test_candidate_order_aligned_single(self):
        assert wq.quota_candidate_order("yes", "yes") == ["yes"]

    def test_candidate_order_no_direction_argmax_only(self):
        """The unevidenced alternate-side fallback is gone: with dir_pref
        None the lane may only try the argmax side."""
        assert wq.quota_candidate_order(None, "no") == ["no"]
        assert wq.quota_candidate_order(None, "yes") == ["yes"]

    def test_candidate_order_nothing(self):
        assert wq.quota_candidate_order(None, None) == []

    def test_dir_absent_min_p_default(self, monkeypatch):
        monkeypatch.delenv("MERID_WINDOW_QUOTA_DIR_ABSENT_MIN_P", raising=False)
        assert wq.quota_dir_absent_min_p() == pytest.approx(0.60)

    def test_dir_absent_min_p_env(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_DIR_ABSENT_MIN_P", "0.70")
        assert wq.quota_dir_absent_min_p() == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# 2. Scalp arm override
# ---------------------------------------------------------------------------


class _FakePos:
    def __init__(self, entry_edge=None, market_id="MKT"):
        self.entry_edge = entry_edge
        self.market_id = market_id


class _FakeMS:
    def __init__(self, seconds_to_expiry):
        self.seconds_to_expiry = seconds_to_expiry


class _FakeStore:
    def __init__(self, state):
        self._state = state

    def get(self, _market_id):
        return self._state


@pytest.fixture()
def _ms_store(monkeypatch):
    """Patch the market-state store the helper reads TTE from."""
    import merid.event_venues.kalshi.market_state as ms

    holder = {"state": None}

    monkeypatch.setattr(
        ms, "get_kalshi_market_state_store",
        lambda: _FakeStore(holder["state"]),
    )
    return holder


class TestScalpArmOverride:
    def test_probe_arm_lowers_for_negative_edge(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=600.0)
        pos = _FakePos(entry_edge=-0.05)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(5.0)

    def test_probe_arm_untouched_for_positive_edge(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=600.0)
        pos = _FakePos(entry_edge=0.03)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(10.0)

    def test_probe_arm_untouched_when_edge_missing(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=600.0)
        pos = _FakePos(entry_edge=None)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(10.0)

    def test_probe_arm_never_raises(self, _ms_store):
        """An 8c profile arm on a no-edge entry stays 5c; a 3c arm is not
        raised to 5c."""
        _ms_store["state"] = _FakeMS(seconds_to_expiry=600.0)
        pos = _FakePos(entry_edge=0.0)
        assert _scalp_arm_override_cents(pos, 3.0) == pytest.approx(3.0)

    def test_late_window_arm(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=200.0)
        pos = _FakePos(entry_edge=0.05)  # positive edge, late window
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(6.0)

    def test_late_window_boundary(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=241.0)
        pos = _FakePos(entry_edge=0.05)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(10.0)

    def test_late_and_probe_take_min(self, _ms_store):
        _ms_store["state"] = _FakeMS(seconds_to_expiry=200.0)
        pos = _FakePos(entry_edge=-0.10)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(5.0)

    def test_env_overrides(self, _ms_store, monkeypatch):
        monkeypatch.setenv("MERID_TRAIL_PROBE_ARM_CENTS", "4")
        monkeypatch.setenv("MERID_TRAIL_LATE_ARM_TTE_S", "120")
        monkeypatch.setenv("MERID_TRAIL_LATE_ARM_CENTS", "3")
        _ms_store["state"] = _FakeMS(seconds_to_expiry=100.0)
        pos = _FakePos(entry_edge=-0.02)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(3.0)

    def test_disabled_flags(self, _ms_store, monkeypatch):
        monkeypatch.setenv("MERID_TRAIL_PROBE_ARM_CENTS", "0")
        monkeypatch.setenv("MERID_TRAIL_LATE_ARM_CENTS", "0")
        _ms_store["state"] = _FakeMS(seconds_to_expiry=60.0)
        pos = _FakePos(entry_edge=-0.5)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(10.0)

    def test_missing_market_state_fails_open_no_override(self, _ms_store):
        _ms_store["state"] = None  # store present but no row
        pos = _FakePos(entry_edge=0.05)
        assert _scalp_arm_override_cents(pos, 10.0) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 3. Settlement-lane tail reserve
# ---------------------------------------------------------------------------


@dataclass
class _FakeObs:
    source_ts_ms: int
    value_decimal: Decimal


def _make_state(
    *,
    tte_s: float,
    observed_value: float = 101.5,
    latest: float = 101.5,
    strike: float = 100.0,
):
    now = datetime(2026, 9, 23, 17, 30, 0, tzinfo=timezone.utc)
    expiry = now + timedelta(seconds=tte_s)
    window_start = expiry - timedelta(seconds=60)
    history: List[_FakeObs] = []
    for i in range(59, -1, -1):
        slot = expiry - timedelta(seconds=i)
        if slot > now:
            break
        history.append(
            _FakeObs(
                source_ts_ms=int(slot.timestamp() * 1000),
                value_decimal=Decimal(str(observed_value)),
            )
        )
    return build_settlement_state(
        ticker="KXBTC15M-TEST",
        asset="BTC",
        strike_price=strike,
        expiry_ts=expiry,
        now_ts=now,
        latest_rti=latest,
        latest_rti_decimal=Decimal(str(latest)),
        latest_rti_ts=now,
        rti_history=history,
        source="cf_rti",
        settlement_reference="cfb_rti_live",
    )


def _make_dist(**kwargs) -> SettlementDistribution:
    return compute_settlement_distribution(
        _make_state(**kwargs), annualized_vol=0.60
    )


def _lane_decision(
    *,
    dist,
    tte_s,
    yes_bid=48.0,
    yes_ask=52.0,
    no_bid=48.0,
    no_ask=52.0,
    min_edge=0.01,
):
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-TEST",
        asset="BTC",
        spot_price=101.5,
        strike_price=100.0,
        seconds_to_expiry=tte_s,
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        no_bid_cents=no_bid,
        no_ask_cents=no_ask,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=min_edge,
        settlement_reference="cfb_rti_live",
        settlement_distribution=dist,
    )


@pytest.fixture(autouse=True)
def _lane_on(monkeypatch):
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_ENABLED", True)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_P", 0.84)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_OBSERVED", 10)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_TTE_S", 10.0)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS", 99.0)
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 180.0)
    monkeypatch.setenv("MERID_EXIT_ONLY_CUTOFF_S", "30")
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)


class TestSettlementLaneTailReserve:
    def test_favored_side_reserve_is_tail_loss(self):
        """At p_side ~0.999 and a 96c ask the reserve is ~0.1c, not the
        generic ~4-5c model_uncertainty stack."""
        dist = _make_dist(tte_s=15.0)  # 45 banked samples, p_yes ~ 1.0
        assert dist.p_yes_raw > 0.99
        d = _lane_decision(
            dist=dist, tte_s=45.0,
            yes_ask=96.0, yes_bid=94.0, no_ask=6.0, no_bid=4.0,
        )
        assert d.indicators.get("entry_lane") == "settlement_convergence"
        tail = d.indicators.get("settlement_lane_tail_reserve_cents")
        assert tail is not None
        expected = (1.0 - float(dist.p_yes_raw)) * 0.96 * 100.0
        assert tail == pytest.approx(expected, abs=0.05)
        bd = d.yes_edge_breakdown
        assert bd is not None
        assert bd.model_risk_reserve == pytest.approx(expected / 100.0, abs=1e-3)

    def test_unfavored_side_keeps_generic_reserve(self):
        dist = _make_dist(tte_s=15.0)
        d = _lane_decision(
            dist=dist, tte_s=45.0,
            yes_ask=96.0, yes_bid=94.0, no_ask=6.0, no_bid=4.0,
        )
        bd = d.no_edge_breakdown
        assert bd is not None
        # Generic stack (model_uncertainty=0.05 plus any measured add-ons)
        # remains on the unfavored side — it can never emit anyway.
        assert bd.model_risk_reserve >= 0.05

    def test_high_price_ask_now_economically_viable(self):
        """The exact live failure: NO@99-equivalent at p~1.0 — previously
        -4.34c net vs the 0.75c lane bound; now the tail reserve is ~0.1c
        so EV is decided by fee+spread, not phantom model risk."""
        dist = _make_dist(tte_s=15.0, observed_value=99.0, latest=99.0,
                          strike=100.0)  # banked BELOW strike -> NO favored
        assert (1.0 - dist.p_yes_raw) > 0.99
        d = _lane_decision(
            dist=dist, tte_s=45.0,
            yes_ask=5.0, yes_bid=3.0, no_ask=96.0, no_bid=94.0,
        )
        assert d.indicators.get("entry_lane") == "settlement_convergence"
        bd = d.no_edge_breakdown
        # Tail reserve ~ (1 - p_no) * 0.96 -> ~0.1c, not 4c+.
        assert bd.model_risk_reserve < 0.02
        # Net edge is now positive at 96c when p ~ 0.999.
        assert bd.net_edge > 0
