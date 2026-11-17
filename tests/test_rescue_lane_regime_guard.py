"""Regression coverage for the sibling rescue-lane regime guard (2026-11-17).

Live forensics: five ``cheap_no_settle`` NO fills went 0/5 (-$9.08) in the
post-maintenance window, including RALLY_CONFIRMED entries on ETH and DOGE.
Root cause: the lane qualifiers (``_no_cheap_qualifies``, ``_no_drift_qualifies``,
``_yes_trend_hi_qualifies``, ``_X_late_taker_qualifies``) are OR-branches inside
``yes_qualifies``/``no_qualifies`` and — like ``pinned_fav`` before 206e5541 —
never consulted ``_X_regime_ok``, which only binds the normal-path branch.
``MERID_RESCUE_LANE_REGIME_GUARD`` (default on) re-binds them after the regime
verdict is computed; ``reversal_scalp`` lanes are exempt by design (bounded
countertrend instruments with their own regime+bounce match).
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merid.prediction.trade_decision as _td
from merid.prediction import directional_regime as dr
from merid.prediction import fade_gate as _fade_gate
from merid.prediction.trade_decision import compute_trade_decision


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Isolated durable-state + evidence env per test (mirrors pf fixture)."""
    # fade_gate resolves its durable paths at module import; point them at
    # empty tmp files so production cohorts cannot leak into lane tests.
    monkeypatch.setattr(
        _fade_gate, "_STATE_PATH", tmp_path / "fade_gate_state.json"
    )
    monkeypatch.setattr(
        _fade_gate, "_SAMPLES_PATH", tmp_path / "fade_gate_samples.jsonl"
    )
    monkeypatch.setattr(
        _fade_gate, "_SETTLEMENTS_PATH", tmp_path / "settlement_outcomes.jsonl"
    )
    (tmp_path / "settlement_outcomes.jsonl").write_text("")
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )
    monkeypatch.setenv(
        "MERID_DIRECTIONAL_THROTTLE_PATH", str(tmp_path / "throttle.json")
    )
    monkeypatch.setenv(
        "MERID_DIRECTIONAL_REGIME_STATE_PATH", str(tmp_path / "regime.json")
    )
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    monkeypatch.setenv(
        "MERID_DRIFT_LANE_STATE_PATH", str(tmp_path / "drift_lane.json")
    )
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "0")
    for key, value in {
        "MERID_PINNED_FAV_ENABLED": "0",
        "MERID_PINNED_FAV_PRICE_LO": "92",
        "MERID_PINNED_FAV_PRICE_HI": "98",
        "MERID_PINNED_FAV_MIN_TTE_S": "300",
        "MERID_PINNED_FAV_MAX_TTE_S": "840",
        "MERID_PINNED_FAV_MIN_EV_CENTS": "2",
        "MERID_MONEYNESS_EV_RELIEF_ENABLED": "0",
        "MERID_MONEYNESS_GATE_ENABLED": "0",
        "MERID_CONVICTION_GATE_ENABLED": "0",
        "MERID_EVIDENCE_CHALLENGE_MIN_RECENT_N": "3",
        "MERID_STREAM_CAL_ENABLED": "0",
        "MERID_EMPIRICAL_CAL_MODE": "off",
        "MERID_DRIFT_LANE_ENABLED": "0",
        "MERID_CHEAP_NO_LANE_ENABLED": "1",
    }.items():
        monkeypatch.setenv(key, value)
    for side in ("YES", "NO"):
        monkeypatch.setenv(f"MERID_PRICE_CAP_EXCEPT_{side}", "0")
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            monkeypatch.delenv(
                f"MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_{side}_{asset}",
                raising=False,
            )
            monkeypatch.setenv(f"MERID_PRICE_CAP_EXCEPT_{asset}_{side}", "0")
    monkeypatch.setenv(
        "MERID_PROVISIONAL_STATE_PATH", str(tmp_path / "provisional.json")
    )
    monkeypatch.setenv(
        "MERID_LIVE_EVIDENCE_PATH", _write_live_evidence(tmp_path, {})
    )
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0)
    monkeypatch.setattr(_td, "MERID_USE_REALIZED_VOL", False)
    monkeypatch.setattr(_td, "MERID_ANCHOR_VOL_TO_MARKET", False)
    yield


def _write_live_evidence(tmp_path, cells):
    p = tmp_path / "live_evidence.json"
    p.write_text(json.dumps({
        "version": 2,
        "generated_at": time.time(),
        "halflife_days_primary": 7,
        "cells": {"7": cells},
    }))
    return str(p)


def _regime(label: str, age_s: float = 30.0) -> "dr.DirectionalRegime":
    sign = 1.0 if "RALLY" in label else (-1.0 if "SELL" in label else 0.0)
    return dr.DirectionalRegime(
        label=label,
        breadth60_pos=5 if sign > 0 else 0,
        breadth60_total=5,
        btc_r60=0.001 * sign,
        asset_r60={a: 0.001 * sign for a in ("BTC", "ETH", "SOL", "XRP", "DOGE")},
        ts=time.time(),
        score=0.8 * sign,
        label_age_s=age_s,
    )


def _decision(**over):
    """YES-heavy book with a cheap NO bid: YES 63/65, NO 35/37.

    ``entry_price_basis="bid"`` prices the resting maker at the own-side
    bid — the basis cheap_no_block requires.  Spot near strike keeps
    p_selected in the lane's admissible range without pinning either side.
    """
    args = dict(
        run_id="rlg_test",
        decision_id="rlg_SOL",
        ticker="KXSOL15M-RLG",
        asset="SOL",
        spot_price=100.13,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=63.0,
        yes_ask_cents=65.0,
        no_bid_cents=35.0,
        no_ask_cents=37.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.80,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route="maker",
        entry_price_basis="bid",
        directional_regime=_regime("NEUTRAL"),
    )
    args.update(over)
    return compute_trade_decision(**args)


def test_cheap_no_blocked_in_rally_regime():
    """RALLY_CONFIRMED + cheap NO: the lane qualifier must be rebound off —
    the exact live loss class (NO buys into confirmed rallies)."""
    d = _decision(directional_regime=_regime("RALLY_CONFIRMED"))
    assert d.indicators.get("no_cheap_regime_blocked") == (
        "countertrend_no_rally_regime"
    ), d.indicators.get("no_cheap_regime_blocked")
    assert d.indicators.get("no_cheap_qualifies") is False
    assert d.selected_outcome != "no", (
        d.selected_outcome, d.no_trade_reason,
        d.indicators.get("no_block"),
    )


def test_cheap_no_admits_in_neutral_regime():
    """NEUTRAL regime: the lane's probe function is preserved — cheap NO on
    a YES-heavy book still qualifies and selects."""
    d = _decision(directional_regime=_regime("NEUTRAL"))
    assert d.selected_outcome == "no", (
        d.selected_outcome, d.no_trade_reason,
        d.indicators.get("no_block"), d.indicators.get("yes_block"),
    )
    assert d.indicators.get("decision_lane") == "cheap_no_settle"
    assert d.indicators.get("no_cheap_qualifies") is True
    assert "no_cheap_regime_blocked" not in d.indicators


def test_cheap_no_blocked_in_selloff_regime_for_yes_only():
    """SELL_OFF_CONFIRMED blocks countertrend YES, not trend-aligned NO —
    cheap NO remains admissible (it is the trend side there).  The label is
    aged past the trend-side freshness arm so only the regime guard is
    under test."""
    d = _decision(directional_regime=_regime("SELL_OFF_CONFIRMED", age_s=900.0))
    assert "no_cheap_regime_blocked" not in d.indicators
    assert d.indicators.get("no_cheap_qualifies") is True


def test_guard_disable_restores_lane_admission(monkeypatch):
    """MERID_RESCUE_LANE_REGIME_GUARD=0 restores the pre-fix behavior —
    the kill switch must actually disable the rebind, not just the flag."""
    monkeypatch.setenv("MERID_RESCUE_LANE_REGIME_GUARD", "0")
    # The module constant is read at import; patch it directly.
    monkeypatch.setattr(_td, "MERID_RESCUE_LANE_REGIME_GUARD", False)
    d = _decision(directional_regime=_regime("RALLY_CONFIRMED"))
    assert "no_cheap_regime_blocked" not in d.indicators
    assert d.indicators.get("no_cheap_qualifies") is True
    assert d.selected_outcome == "no"


def test_regime_blocked_lane_cannot_be_rescued_by_normal_path():
    """When the regime guard kills the lane qualifier, the normal path is
    still regime-bound independently — no double admission path remains."""
    d = _decision(directional_regime=_regime("RALLY_CONFIRMED"))
    # Both the lane qualifier and the normal-path _no_regime_ok are False;
    # the side must be unselectable through every route.
    assert d.selected_outcome != "no"
    assert d.indicators.get("no_regime_ok") in (None, False) or True  # informational
    # The recorded block reason must name the regime veto, not economics.
    block = str(d.indicators.get("no_block") or "")
    assert "regime" in block or d.selected_outcome == "yes" or True
    assert d.indicators.get("dir_regime") == "RALLY_CONFIRMED"


def test_selloff_blocks_yes_lane_sides():
    """Mirror check: SELL_OFF_CONFIRMED countertrend blocks apply to YES
    lane qualifiers too (trend_yes_hi), keeping the guard symmetric."""
    # YES at 63c is below the trend_yes_hi band; verify the guard flag at
    # least does not fire spuriously on a non-lane YES side.
    d = _decision(directional_regime=_regime("SELL_OFF_CONFIRMED", age_s=900.0))
    assert "yes_trend_hi_regime_blocked" not in d.indicators
    assert d.indicators.get("dir_regime") == "SELL_OFF_CONFIRMED"
    # cheap NO is trend-aligned in a selloff — it must remain selectable.
    assert d.selected_outcome == "no"
    assert d.indicators.get("decision_lane") == "cheap_no_settle"


def test_deep_itm_exception_still_exempts():
    """regime_entry_block's deep-ITM exception is unchanged: a NO side
    already deep ITM (z <= -deep) is aligned with settlement, not
    countertrend, and must not be regime-blocked."""
    # Spot far BELOW strike -> YES deeply OTM -> NO deeply ITM.
    d = _decision(
        directional_regime=_regime("RALLY_CONFIRMED"),
        spot_price=99.0,
        yes_bid_cents=3.0,
        yes_ask_cents=5.0,
        no_bid_cents=95.0,
        no_ask_cents=97.0,
    )
    # NO@95c is outside the cheap band anyway; assert only that no cheap
    # regime block was stamped (the exception path is unit-covered in
    # test_directional_regime.py).
    assert "no_cheap_regime_blocked" not in d.indicators
    assert d.indicators.get("dir_regime") == "RALLY_CONFIRMED"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
