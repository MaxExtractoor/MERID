"""Tests for the settlement-convergence lane and bounded sample forward-fill.

Covers:
  - SettlementDistribution V2 in-window construction with bounded forward-fill
    of dropped RTI frames (fail-closed beyond the bound).
  - The settlement-convergence lane bypassing min-TTE / final-minute cutoffs
    only when the in-window distribution has enough banked samples and a
    high-confidence side.
  - Market-anchor release proportional to unrealized settlement fraction.
  - Lane-conditioned cost stack (zero exit reserve, no near-expiry penalties).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import pytest

import merid.prediction.trade_decision as td
from merid.prediction.settlement_distribution import (
    SettlementDistribution,
    build_settlement_state,
    compute_settlement_distribution,
)
from merid.prediction.trade_decision import compute_trade_decision


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
    missing_slots: Optional[List[int]] = None,
):
    """Build an in-window SettlementState.

    ``tte_s`` is seconds to expiry (<=60 for in_window).  The elapsed slots of
    the 60-second settlement window are populated at ``observed_value`` except
    for the slot offsets listed in ``missing_slots`` (offset = seconds before
    expiry, e.g. 59 == oldest slot).
    """
    now = datetime(2026, 9, 23, 17, 30, 0, tzinfo=timezone.utc)
    expiry = now + timedelta(seconds=tte_s)
    assert expiry.microsecond == 0
    window_start = expiry - timedelta(seconds=60)
    missing = set(missing_slots or [])

    history: List[_FakeObs] = []
    for i in range(59, -1, -1):
        slot = expiry - timedelta(seconds=i)
        if slot > now:
            break
        if i in missing:
            continue
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
    state = _make_state(**kwargs)
    return compute_settlement_distribution(state, annualized_vol=0.60)


def _make_lane_decision(
    *,
    dist: SettlementDistribution,
    tte_s: float,
    yes_bid: float = 48.0,
    yes_ask: float = 52.0,
    no_bid: float = 48.0,
    no_ask: float = 52.0,
    min_edge: float = 0.01,
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
def _lane_enabled(monkeypatch):
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_ENABLED", True)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_P", 0.84)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_OBSERVED", 10)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_TTE_S", 10.0)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS", 97.0)
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 180.0)
    monkeypatch.setenv("MERID_EXIT_ONLY_CUTOFF_S", "30")
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)


# ---------------------------------------------------------------------------
# Distribution construction + bounded forward-fill
# ---------------------------------------------------------------------------


def test_in_window_distribution_banks_samples():
    dist = _make_dist(tte_s=30.0, observed_value=101.5, latest=101.5)
    assert dist.phase == "in_window"
    assert dist.observed_count == 30
    assert dist.remaining_count == 30
    assert dist.p_yes_raw > 0.99  # mean ~1.5% above strike, residual var small


def test_forward_fill_tolerates_bounded_gaps():
    # Slot offsets >= tte are elapsed; >=31 at tte=30 picks realized slots.
    state = _make_state(tte_s=30.0, missing_slots=[55, 40, 31])
    dist = compute_settlement_distribution(
        state, annualized_vol=0.60, max_missing_samples=5
    )
    assert dist.filled_count == 3
    # Real observed count excludes fills (lane gate uses the real count).
    assert dist.observed_count == 27
    assert dist.p_yes_raw > 0.99


def test_forward_fill_beyond_bound_fails_closed():
    state = _make_state(tte_s=30.0, missing_slots=[59, 55, 50, 45, 40, 35])
    with pytest.raises(ValueError):
        compute_settlement_distribution(
            state, annualized_vol=0.60, max_missing_samples=5
        )


def test_strict_mode_rejects_any_gap():
    state = _make_state(tte_s=30.0, missing_slots=[45])
    with pytest.raises(ValueError):
        compute_settlement_distribution(state, annualized_vol=0.60)


# ---------------------------------------------------------------------------
# Lane eligibility
# ---------------------------------------------------------------------------


def test_lane_bypasses_min_tte_with_high_confidence_settlement():
    dist = _make_dist(tte_s=45.0)  # in_window, 15 banked, p_yes ~ 1
    d = _make_lane_decision(dist=dist, tte_s=45.0)
    assert d.no_trade_reason not in (
        "min_tte_entry_disabled",
        "final_minute_entry_disabled",
    )
    assert d.indicators.get("entry_lane") == "settlement_convergence"
    assert d.selected_outcome == "yes", d.no_trade_reason


def test_lane_rejects_without_confident_side():
    # Observed AT the strike -> p_yes ~ 0.5, no favored side.
    dist = _make_dist(tte_s=45.0, observed_value=100.0, latest=100.0)
    d = _make_lane_decision(dist=dist, tte_s=45.0)
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled"


def test_lane_requires_minimum_banked_samples(monkeypatch):
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_OBSERVED", 50)
    dist = _make_dist(tte_s=45.0)  # only 15 banked
    d = _make_lane_decision(dist=dist, tte_s=45.0)
    assert d.no_trade_reason == "min_tte_entry_disabled"


def test_lane_respects_own_tte_floor(monkeypatch):
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MIN_TTE_S", 20.0)
    dist = _make_dist(tte_s=15.0)  # deep in-window but below lane floor
    d = _make_lane_decision(dist=dist, tte_s=15.0)
    assert d.no_trade_reason == "final_minute_entry_disabled"


def test_lane_disabled_keeps_generic_gates(monkeypatch):
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_ENABLED", False)
    dist = _make_dist(tte_s=45.0)
    d = _make_lane_decision(dist=dist, tte_s=45.0)
    assert d.no_trade_reason == "min_tte_entry_disabled"


def test_lane_price_cap_blocks_extreme_asks(monkeypatch):
    # The cap is checked after selection, so it must sit below an ask that
    # still clears the edge gate (p_sel is capped at 0.95).
    monkeypatch.setattr(td, "MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS", 50.0)
    dist = _make_dist(tte_s=45.0)
    d = _make_lane_decision(dist=dist, tte_s=45.0, yes_ask=52.0, yes_bid=48.0)
    assert d.no_trade_reason == "settlement_lane_price_cap"


# ---------------------------------------------------------------------------
# Lane cost stack + confidence treatment
# ---------------------------------------------------------------------------


def test_lane_zeroes_exit_cost_reserve():
    dist = _make_dist(tte_s=45.0)
    d = _make_lane_decision(dist=dist, tte_s=45.0)
    assert float(d.expected_exit_cost_yes) == 0.0
    assert float(d.expected_exit_cost_no) == 0.0


def test_confidence_skips_near_expiry_in_lane():
    conf = td._compute_confidence(
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
        seconds_to_expiry=30.0,
        yes_bid_cents=83.0,
        yes_ask_cents=85.0,
        no_bid_cents=15.0,
        no_ask_cents=17.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        model_uncertainty=0.05,
        settlement_lane=True,
    )
    assert "near_expiry" not in conf.reasons
    conf2 = td._compute_confidence(
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
        seconds_to_expiry=30.0,
        yes_bid_cents=83.0,
        yes_ask_cents=85.0,
        no_bid_cents=15.0,
        no_ask_cents=17.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        model_uncertainty=0.05,
        settlement_lane=False,
    )
    assert "near_expiry" in conf2.reasons


def test_model_risk_reserve_skips_near_expiry_bump_in_lane():
    lane = td._compute_model_risk_reserve(0.05, "live", "normal", 30.0, settlement_lane=True)
    plain = td._compute_model_risk_reserve(0.05, "live", "normal", 30.0, settlement_lane=False)
    assert lane == pytest.approx(0.05)
    assert plain == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Anchor release inside the settlement window
# ---------------------------------------------------------------------------


def test_anchor_released_proportional_to_unrealized_fraction(monkeypatch):
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.5)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.9)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_WINDOW_S", 900.0)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_ANCHOR_RELEASE", True)

    # tte=45 -> in_window with 15 observed / 45 remaining -> release factor 0.75
    dist = _make_dist(tte_s=45.0, observed_value=100.2, latest=100.2)
    d = _make_lane_decision(dist=dist, tte_s=45.0, min_edge=99.0)  # force no-trade
    base_w = 0.5 + (0.9 - 0.5) * (1.0 - 45.0 / 900.0)  # 0.88
    expected = base_w * (45.0 / 60.0)
    assert float(d.indicators["market_anchor_weight"]) == pytest.approx(expected)


def test_anchor_not_released_pre_window(monkeypatch):
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.5)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.9)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_WINDOW_S", 900.0)
    monkeypatch.setattr(td, "MERID_SETTLEMENT_ANCHOR_RELEASE", True)

    dist = _make_dist(tte_s=45.0, observed_value=100.2, latest=100.2)
    # Fake a pre_window phase — anchor release must not engage.
    dist = SettlementDistribution(
        mean=dist.mean, std=dist.std, z_score=dist.z_score,
        p_yes_raw=dist.p_yes_raw, observed_count=0, remaining_count=60,
        seconds_to_expiry=200.0, phase="pre_window",
        forecast_method="zero_drift_forward_average",
    )
    d = _make_lane_decision(dist=dist, tte_s=200.0, min_edge=99.0)
    base_w = 0.5 + (0.9 - 0.5) * (1.0 - 200.0 / 900.0)
    assert float(d.indicators["market_anchor_weight"]) == pytest.approx(base_w)
