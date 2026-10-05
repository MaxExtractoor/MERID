"""Tests for the 2026-09-23 adverse-selection / entry-execution hardening.

Covers:
  - Entries execute taker/IOC only (maker lane disabled by default)
  - Router-level coercion of any entry intent that still resolves to maker
  - Bachelier digital uses the d2 drift-corrected z-score
  - EWMA realized-vol tracker fed by the RTI tick stream
  - Market-anchor logit shrinkage of the model probability
  - Favorite-longshot-bias reserve in the dynamic min-edge
  - Minimum time-to-expiry gate for new entries
  - Entry-fill markout telemetry sign conventions
"""
from __future__ import annotations

import math
import os
from decimal import Decimal
from typing import Optional

import pytest

import merid.prediction.trade_decision as td
from merid.prediction.trade_decision import (
    _compute_bachelier_components,
    _compute_dynamic_min_required_edge,
    compute_trade_decision,
)


def _make_decision(
    *,
    spot: float = 100.0,
    strike: float = 100.0,
    seconds_to_expiry: float = 900.0,
    yes_bid: float = 40.0,
    yes_ask: float = 42.0,
    no_bid: float = 58.0,
    no_ask: float = 60.0,
    fee_cents: float = 1.0,
    vol: float = 0.60,
    model_uncertainty: float = 0.05,
    data_quality: str = "live",
    regime: str = "normal",
    min_edge: float = 0.03,
    settlement_reference: str = "cfb_rti_live",
    p_yes_model: Optional[float] = None,
):
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP231430-30",
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
        data_quality=data_quality,
        regime=regime,
        min_required_edge=min_edge,
        settlement_reference=settlement_reference,
        p_yes_model=p_yes_model,
    )


@pytest.fixture(autouse=True)
def _disable_anchor(monkeypatch):
    """Default tests run unanchored; anchor tests re-enable explicitly."""
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)


# --------------------------------------------------------------------------
# Bachelier d2 drift term
# --------------------------------------------------------------------------


def test_bachelier_uses_d2_drift_term():
    """z must equal (ln(S/K) - sigma^2 T/2) / (sigma sqrt(T))."""
    spot, strike, t_s, vol = 101.0, 100.0, 900.0, 0.60
    comp = _compute_bachelier_components(spot, strike, t_s, vol)
    assert comp is not None
    t_years = t_s / (365.0 * 24.0 * 60.0 * 60.0)
    expected_z = (math.log(spot / strike) - 0.5 * vol * vol * t_years) / (
        vol * math.sqrt(t_years)
    )
    assert math.isclose(comp["z_score"], expected_z, rel_tol=1e-9)
    assert math.isclose(comp["p_yes_raw"], 0.5 * (1.0 + math.erf(expected_z / math.sqrt(2.0))), rel_tol=1e-9)


# --------------------------------------------------------------------------
# EWMA realized vol tracker
# --------------------------------------------------------------------------


def test_realized_vol_tracker_estimates_vol():
    from merid.prediction.realized_vol import RealizedVolTracker

    tracker = RealizedVolTracker(
        half_life_s=30.0, min_samples=20, min_span_s=30.0, max_sample_age_s=10.0
    )
    # 200 ticks, 1s apart, alternating +/-0.015% returns on BTC.
    px = 100_000.0
    t0 = 1_000_000.0
    for i in range(200):
        px *= 1.0 + (0.00015 if i % 2 == 0 else -0.00015)
        tracker.record("BTC", px, t0 + i * 1.0)
    est = tracker.annualized_vol("BTC", now=t0 + 199.0 + 1.0)
    assert est is not None
    # r^2/dt ~ (1.5e-4)^2 = 2.25e-8 per second -> sigma_ann ~ sqrt(2.25e-8 * 3.156e7) ~ 0.84
    assert 0.5 < est.value < 1.5


def test_realized_vol_tracker_insufficient_samples():
    from merid.prediction.realized_vol import RealizedVolTracker

    tracker = RealizedVolTracker(min_samples=60, min_span_s=120.0)
    t0 = 1_000_000.0
    for i in range(10):
        tracker.record("ETH", 3000.0 * (1 + 0.0001 * i), t0 + i)
    assert tracker.annualized_vol("ETH", now=t0 + 10.0) is None


def test_realized_vol_tracker_stale_tick_rejected():
    from merid.prediction.realized_vol import RealizedVolTracker

    tracker = RealizedVolTracker(min_samples=5, min_span_s=5.0, max_sample_age_s=30.0)
    t0 = 1_000_000.0
    for i in range(30):
        tracker.record("SOL", 100.0 * (1 + 0.0002 * (i % 2)), t0 + i)
    assert tracker.annualized_vol("SOL", now=t0 + 5000.0) is None


def test_fetch_realized_vol_uses_tracker(monkeypatch):
    import merid.prediction.realized_vol as rv

    tracker = rv.get_realized_vol_tracker()
    t0 = 1_000_000.0
    px = 50_000.0
    for i in range(200):
        px *= 1.0 + (0.00015 if i % 2 == 0 else -0.00015)
        tracker.record("BTC", px, t0 + i)
    monkeypatch.setattr(rv.time, "time", lambda: t0 + 200.0)
    monkeypatch.setenv("MERID_USE_REALIZED_VOL", "1")
    # module constant is read at call time
    monkeypatch.setattr(td, "MERID_USE_REALIZED_VOL", True)
    val = td._fetch_realized_vol("BTC")
    assert val is not None and 0.3 < val < 1.5


# --------------------------------------------------------------------------
# Market-anchor shrinkage
# --------------------------------------------------------------------------


def test_market_anchor_shrinks_model_toward_market(monkeypatch):
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.25)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.85)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_WINDOW_S", 900.0)

    # Window open (tte=900 -> frac_elapsed=0 -> w=0.25): model p_raw high,
    # market mid 41c -> anchored p must sit strictly between raw and market.
    d = _make_decision(spot=101.5, strike=100.0, seconds_to_expiry=900.0)
    pre = float(d.indicators["p_yes_pre_anchor"])
    post = float(d.indicators["p_yes_post_anchor"])
    w = float(d.indicators["market_anchor_weight"])
    mkt = float(d.indicators["market_anchor_prob"])
    assert math.isclose(w, 0.25, abs_tol=1e-9)
    assert math.isclose(mkt, 0.41, abs_tol=1e-9)
    assert mkt < post < pre


def test_market_anchor_weight_ramps_to_max_near_expiry(monkeypatch):
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.25)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.85)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_WINDOW_S", 900.0)

    d = _make_decision(spot=101.5, strike=100.0, seconds_to_expiry=250.0)
    w = float(d.indicators["market_anchor_weight"])
    expected = 0.25 + (0.85 - 0.25) * (1.0 - 250.0 / 900.0)
    assert math.isclose(w, expected, abs_tol=1e-9)


def test_market_anchor_requires_two_sided_book(monkeypatch):
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0.5)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0.9)
    # One-sided book (no bid): anchor must not engage.
    d = _make_decision(spot=101.5, strike=100.0, yes_bid=0.0, seconds_to_expiry=900.0)
    assert float(d.indicators["market_anchor_weight"]) == 0.0
    assert math.isclose(
        float(d.indicators["p_yes_post_anchor"]), float(d.indicators["p_yes_pre_anchor"]), abs_tol=1e-12
    )


# --------------------------------------------------------------------------
# FLB longshot reserve
# --------------------------------------------------------------------------


def test_flb_longshot_reserve_raises_edge_floor_for_cheap_contracts(monkeypatch):
    monkeypatch.setattr(td, "MERID_FLB_LONGSHOT_SLOPE", 0.15)
    cheap = _compute_dynamic_min_required_edge(
        asset="BTC", price_cents=30, side="yes",
        yes_bid_cents=29.0, yes_ask_cents=31.0,
        no_bid_cents=69.0, no_ask_cents=71.0,
        floor_min_required_edge=0.03,
    )
    fav = _compute_dynamic_min_required_edge(
        asset="BTC", price_cents=55, side="yes",
        yes_bid_cents=54.0, yes_ask_cents=56.0,
        no_bid_cents=44.0, no_ask_cents=46.0,
        floor_min_required_edge=0.03,
    )
    # 30c contract: +0.15 * (0.5 - 0.30) = +3c of extra required net edge.
    assert cheap > fav
    assert math.isclose(cheap - fav, 0.15 * (0.5 - 0.30), abs_tol=0.02)


def test_spread_not_double_charged_in_edge_threshold(monkeypatch):
    """The taker ask already embeds the full spread in gross_edge and pi*
    charges spread_slippage again; the threshold must not add it a third time.
    2026-09-25 counterfactual: marginal-band favorites were net profitable."""
    wide = _compute_dynamic_min_required_edge(
        asset="BTC", price_cents=60, side="yes",
        yes_bid_cents=56.0, yes_ask_cents=64.0,   # 8c spread
        no_bid_cents=36.0, no_ask_cents=44.0,
        floor_min_required_edge=0.03,
    )
    tight = _compute_dynamic_min_required_edge(
        asset="BTC", price_cents=60, side="yes",
        yes_bid_cents=59.0, yes_ask_cents=61.0,   # 2c spread
        no_bid_cents=39.0, no_ask_cents=41.0,
        floor_min_required_edge=0.03,
    )
    assert math.isclose(wide, tight, abs_tol=1e-9)


def test_convexity_halved_on_favorites(monkeypatch):
    """Held >=50c uses half the p*(1-p) adverse-selection reserve."""
    # Isolate the convexity term: the 50-89c mid-band relief (default 1.5c)
    # would otherwise subtract past the hard floor and mask the halving.
    monkeypatch.setattr(td, "MERID_EDGE_MID_BAND_RELIEF_CENTS", 0.0)
    fav = _compute_dynamic_min_required_edge(
        asset="BTC", price_cents=60, side="yes",
        yes_bid_cents=59.0, yes_ask_cents=61.0,
        no_bid_cents=39.0, no_ask_cents=41.0,
        floor_min_required_edge=0.03,
    )
    # base 3% + 0.02 * 0.6 * 0.4 = 0.0048 -> 0.0348
    assert math.isclose(fav, 0.03 + 0.02 * 0.6 * 0.4, abs_tol=1e-9)


# --------------------------------------------------------------------------
# Minimum time-to-expiry entry gate
# --------------------------------------------------------------------------


def test_min_tte_gate_blocks_late_entries(monkeypatch):
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 180.0)
    d = _make_decision(spot=101.5, strike=100.0, seconds_to_expiry=150.0)
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled"


def test_min_tte_gate_allows_early_entries(monkeypatch):
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 180.0)
    d = _make_decision(spot=101.5, strike=100.0, seconds_to_expiry=600.0)
    # Gate itself must not be the blocker (selection may still no-trade on edge).
    assert d.no_trade_reason != "min_tte_entry_disabled"


# --------------------------------------------------------------------------
# Router-level maker-entry coercion
# --------------------------------------------------------------------------


def test_router_coerces_maker_entry_to_taker(monkeypatch):
    from merid.event_venues.kalshi.order_router import OrderIntent, _apply_execution_mode

    monkeypatch.delenv("MERID_ENTRY_MAKER_ENABLED", raising=False)
    intent = OrderIntent(
        ticker="KXBTC15M-26SEP231430-30",
        price_cents=42,
        count=1,
        side="BUY_YES",
        action="buy",
        execution_mode="maker",
        post_only=True,
        time_in_force="gtc",
    )
    intent.aggressiveness = 0.0
    post_only, aggr, _otype, tif = _apply_execution_mode(intent)
    assert execution_mode_is_taker(intent)
    assert post_only is False
    assert aggr == 1.0
    assert tif.upper() == "IOC"


def test_router_respects_maker_entry_when_enabled(monkeypatch):
    from merid.event_venues.kalshi.order_router import OrderIntent, _apply_execution_mode

    monkeypatch.setenv("MERID_ENTRY_MAKER_ENABLED", "1")
    intent = OrderIntent(
        ticker="KXBTC15M-26SEP231430-30",
        price_cents=42,
        count=1,
        side="BUY_YES",
        action="buy",
        execution_mode="maker",
        post_only=True,
        time_in_force="gtc",
    )
    intent.aggressiveness = 0.0
    post_only, aggr, _otype, tif = _apply_execution_mode(intent)
    assert intent.execution_mode == "maker"
    assert post_only is True
    assert aggr == 0.0
    assert tif.upper() == "GTC"


@pytest.mark.parametrize("role", ["maker", "taker"])
@pytest.mark.parametrize("side", ["BUY_YES", "BUY_NO"])
def test_both_enabled_roles_reach_correct_wire_request(role, side, monkeypatch):
    from types import SimpleNamespace
    import time
    from merid.event_venues.kalshi.order_router import (
        OrderIntent, _apply_execution_mode, _resolve_tif, _build_create_order_request,
    )

    monkeypatch.setenv("MERID_ENTRY_MAKER_ENABLED", "1")
    state = SimpleNamespace(seconds_to_expiry=600)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: SimpleNamespace(get=lambda ticker: state),
    )
    maker = role == "maker"
    intent = OrderIntent(
        ticker="KXBTC15M-TEST", side=side, action="buy", count=1, price_cents=50,
        execution_mode=role, liquidity_role=role, post_only=maker,
        aggressiveness=0.0 if maker else 1.0, time_in_force="gtc" if maker else "ioc",
        max_rest_seconds=10, p_selected=0.65, client_order_id=f"test-{role}-{side}",
        entry_or_exit="entry",
    )
    post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
    resolved = _resolve_tif(intent)
    request = _build_create_order_request(
        intent, ticker=intent.ticker, exchange_index=2, final_price_cents=50,
        effective_order_type=order_type, effective_tif=tif,
        expiration_ts=resolved.expiration_time, post_only=post_only,
    )
    assert intent.execution_mode == role
    assert request.post_only is maker
    assert request.side == "buy"
    assert request.outcome == ("yes" if side == "BUY_YES" else "no")
    assert request.time_in_force == ("GTC" if maker else "IOC")
    assert aggressiveness == (0.0 if maker else 1.0)
    if maker:
        assert int(time.time()) < request.expiration_ts <= int(time.time()) + 10
    else:
        assert request.expiration_ts is None


def execution_mode_is_taker(intent) -> bool:
    return getattr(intent, "execution_mode", None) == "taker"


# --------------------------------------------------------------------------
# Entry markout telemetry
# --------------------------------------------------------------------------


def test_markout_tracker_yes_and_no_sign(tmp_path, monkeypatch):
    from merid.observability.entry_markout import EntryMarkoutTracker
    import merid.observability.entry_markout as em

    monkeypatch.setenv("MERID_ENTRY_MARKOUT_LOG", str(tmp_path / "markouts.jsonl"))
    tracker = EntryMarkoutTracker(horizons_s=(10.0,))

    mids = {"T1": 45.0, "T2": 55.0}
    monkeypatch.setattr(
        EntryMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: mids.get(t))
    )

    t0 = 1_000_000.0
    tracker.record_entry_fill(
        ticker="T1", position_id="p1", asset="BTC", side="yes",
        fill_price_cents=40.0, count=1.0, fill_ts=t0,
    )
    tracker.record_entry_fill(
        ticker="T2", position_id="p2", asset="BTC", side="no",
        fill_price_cents=40.0, count=1.0, fill_ts=t0,
    )
    n = tracker.poll(now=t0 + 11.0)
    assert n == 2

    rows = [
        __import__("json").loads(line)
        for line in (tmp_path / "markouts.jsonl").read_text().splitlines()
        if '"event": "markout"' in line or '"event":"markout"' in line
    ]
    by_ticker = {r["ticker"]: r for r in rows}
    # YES @40, yes_mid 45 -> +5c (market moved in favor).
    assert by_ticker["T1"]["markout_cents"] == 5.0
    # NO @40, yes_mid 55 -> held(NO) mid = 45 -> +5c (YES fell = NO rose).
    assert by_ticker["T2"]["markout_cents"] == 5.0


def test_markout_tracker_negative_adverse(tmp_path, monkeypatch):
    from merid.observability.entry_markout import EntryMarkoutTracker

    monkeypatch.setenv("MERID_ENTRY_MARKOUT_LOG", str(tmp_path / "markouts.jsonl"))
    tracker = EntryMarkoutTracker(horizons_s=(10.0,))
    monkeypatch.setattr(
        EntryMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: 33.0)
    )
    t0 = 1_000_000.0
    tracker.record_entry_fill(
        ticker="T1", position_id="p1", asset="SOL", side="yes",
        fill_price_cents=40.0, count=1.0, fill_ts=t0,
    )
    tracker.poll(now=t0 + 11.0)
    rows = [
        __import__("json").loads(line)
        for line in (tmp_path / "markouts.jsonl").read_text().splitlines()
        if "markout" in line
    ]
    assert rows[-1]["markout_cents"] == -7.0
