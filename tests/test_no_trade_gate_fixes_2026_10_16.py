"""Regression coverage for the 2026-10-16 no-trade audit.

Three decision-layer defects were suppressing otherwise eligible
candidates:

1. ``insufficient_depth_*`` applied taker-consumption semantics to
   post-only routes (``maker``/``maker_bid``/``empirical_marginal_maker``).
   A resting limit order adds liquidity at its price; requiring own-side
   ask depth for it rejected candidates whose real constraint (adverse
   selection) is already charged separately.

2. The FIX-15 drift reserve double-charged cells whose own
   streaming-calibration bound had already priced the same CUSUM
   evidence (an alarmed exact cell contributes its shrunk mean with no
   honesty buffer inside ``streaming_bound``).  The flat reserve now
   applies only where the bound is alarm-blind (pooled/unmeasured).

3. The terminal ``no_trade_reason`` cascade dropped ``*_trendside_block``
   and ``tail_guard_violation_*``, so whipsaw-guard and tail-calibration
   vetoes surfaced as the ``no_qualifying_side`` catch-all and hid the
   guards' true suppression rate.
"""
import time

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction import streaming_calibration as sc
from merid.prediction.directional_regime import DirectionalRegime
from merid.prediction.trade_decision import compute_trade_decision


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Neutral overlays + isolated streaming-calibration state."""
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )
    monkeypatch.setenv("MERID_STREAM_CAL_PATH", str(tmp_path / "sc.json"))
    monkeypatch.setenv("MERID_STREAM_CAL_ENABLED", "1")
    monkeypatch.delenv("MERID_STREAM_CAL_HALFLIFE_DAYS", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_PRIOR_K", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_MIN_NEFF", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_BUFFER", raising=False)
    monkeypatch.setenv("MERID_DRIFT_ALARM_RESERVE_CENTS", "2.0")
    sc.reset_cache()
    yield
    sc.reset_cache()


def _decision(asset: str = "ETH", **over):
    args = dict(
        run_id="nt_audit",
        decision_id=f"nt_{asset}",
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        spot_price=100.5,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=58.0,
        no_ask_cents=60.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.03,
        settlement_reference="cfb_rti_live",
    )
    args.update(over)
    return compute_trade_decision(**args)


def _sc_row(asset="ETH", side="yes", price=42.0, p=0.55, won=False,
            tte=600.0, sat=None, ts=None, ticker="KXETH-T1"):
    now = time.time()
    sat = now if sat is None else sat
    return {
        "asset": asset, "side": side, "ticker": ticker,
        "entry_cents": price, "seconds_to_close": tte,
        "calibrated_probability": p,
        "settled_yes": won if side == "yes" else not won,
        "settled_at": sat, "decision_ts": sat - 100.0 if ts is None else ts,
        "src": "veto", "mkey": f"{ticker}|{side}",
    }


# ---------------------------------------------------------------------------
# FIX C: post-only routes must not require own-side ask (consumable) depth
# ---------------------------------------------------------------------------

def test_taker_route_still_requires_consumable_depth():
    """IOC taker entries cross the ask — thin own-side depth is a real veto."""
    d = _decision(yes_depth_cc=0.0, no_depth_cc=200.0, route="taker")
    assert d.selected_outcome is None
    assert d.no_trade_reason == "insufficient_depth_yes"


@pytest.mark.parametrize("route", ["maker", "maker_bid"])
def test_post_only_route_ignores_ask_side_depth(route):
    """A resting limit order adds liquidity; ask-side depth is not its
    constraint (fill pick-off risk is priced via the ASR term instead)."""
    over = {"route": route, "yes_depth_cc": 0.0, "no_depth_cc": 200.0}
    if route == "maker_bid":
        over["entry_price_basis"] = "bid"
        over["adverse_selection_reserve"] = 0.04
    d = _decision(**over)
    assert d.no_trade_reason != "insufficient_depth_yes", (
        route, d.no_trade_reason,
    )
    assert d.selected_outcome == "yes", (route, d.no_trade_reason)


def test_post_only_depth_bypass_is_audited():
    """The relaxed gate stamps the raw book depths it bypassed."""
    d = _decision(
        route="maker_bid", entry_price_basis="bid",
        adverse_selection_reserve=0.04,
        yes_depth_cc=0.0, no_depth_cc=50.0,
    )
    bypass = d.indicators.get("depth_gate_post_only_bypass")
    assert bypass is not None and bypass["route"] == "maker_bid"
    assert bypass["yes_depth_cc"] == 0.0


# ---------------------------------------------------------------------------
# FIX B: drift reserve must not double-charge an exact-slice-alarmed cell
# ---------------------------------------------------------------------------

def test_drift_reserve_skipped_when_exact_bound_already_priced_alarm():
    """Exact-slice bound: the alarmed cell already tightened its own cap
    (0 buffer), so the flat +2c reserve would triple-count the evidence."""
    now = time.time()
    rows = [
        _sc_row(ticker=f"KXD-{i}", p=0.55, won=False, sat=now - i)
        for i in range(10)
    ]
    assert sc.update_from_rows(rows) == 10
    alarm = sc.drift_alarm("ETH", "yes", 42.0, 600.0)
    assert alarm is not None and alarm["direction"] == "over"
    detail = sc.streaming_bound_detail("ETH", "yes", 42.0, 600.0)
    assert detail["source"] == "exact" and detail["bound"] is not None

    d = _decision()
    assert d.indicators["streaming_cal_bound_source_yes"] == "exact"
    # The alarm is still reported, but its reserve is not re-charged.
    assert (d.indicators["yes_drift_alarm"] or {}).get("direction") == "over"
    assert d.indicators["yes_drift_reserve_cents"] == 0.0


def test_drift_reserve_applies_when_bound_is_alarm_blind():
    """Sparse exact cell -> pooled bound path carries no cusum_hi, so the
    alarm is the only correction channel and the reserve must still charge."""
    now = time.time()
    rows = [
        _sc_row(ticker=f"KXS-{i}", p=0.55, won=False, sat=now - i)
        for i in range(3)
    ]
    assert sc.update_from_rows(rows) == 3
    alarm = sc.drift_alarm("ETH", "yes", 42.0, 600.0)
    assert alarm is not None and alarm["direction"] == "over"
    detail = sc.streaming_bound_detail("ETH", "yes", 42.0, 600.0)
    assert detail["source"] == "pooled" and detail["bound"] is not None

    d = _decision()
    assert (d.indicators["yes_drift_alarm"] or {}).get("direction") == "over"
    assert d.indicators["yes_drift_reserve_cents"] == pytest.approx(2.0)


def test_drift_reserve_unchanged_when_no_alarm():
    """No tripped alarm -> no reserve on either bound path."""
    d = _decision()
    assert d.indicators["yes_drift_reserve_cents"] == 0.0
    assert d.indicators["no_drift_reserve_cents"] == 0.0


# ---------------------------------------------------------------------------
# FIX D: terminal reason must name trendside vetoes, not the catch-all
# ---------------------------------------------------------------------------

def _fresh_rally_regime() -> DirectionalRegime:
    return DirectionalRegime(
        label="RALLY_CONFIRMED",
        breadth60_pos=5,
        breadth60_total=5,
        btc_r60=0.001,
        asset_r60={"ETH": 0.001},
        ts=time.time(),
        score=0.9,
        up_ticks=10,
        label_age_s=5.0,  # < MERID_REGIME_TREND_MIN_AGE_S (60s default)
    )


def test_trendside_veto_is_named_not_catchall():
    """Buying the trend side on a just-confirmed label is the whipsaw veto;
    the terminal reason must say so instead of 'no_qualifying_side'."""
    d = _decision(directional_regime=_fresh_rally_regime())
    assert d.selected_outcome is None
    assert d.no_trade_reason is not None
    assert d.no_trade_reason.startswith("trend_regime_fresh"), (
        d.no_trade_reason,
    )
    assert d.no_trade_reason != "no_qualifying_side"
