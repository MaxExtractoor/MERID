"""Regression tests for the 2026-10-21 bid-pass vehicle decoupling.

The bid-priced eval pass (route="maker_bid") is the sole emission vehicle
for every bid-basis lane: generic maker_bid, pinned_fav maker mode,
drift_fav, cheap_no_settle.  Previously the generic lane's daily
submission cap short-circuited the *eval* — once the counter reached the
cap, every lane sharing the pass died silently (no audit rows, no
candidates).  Observed live 2026-10-21 ~17:56Z: count reached
MERID_MAKER_BID_DAILY_CAP=480 -> zero :maker_bid evals -> every
pinned_fav maker-mode ENTER died as pinned_fav_maker_only -> zero
order attempts for the rest of the session.
"""
from __future__ import annotations

import inspect

import merid.prediction.agent_grid_15m as ag


def test_bid_pass_runs_when_generic_lane_enabled():
    import merid.prediction.agent_grid_15m as ag_mod
    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ag_mod, "MERID_MAKER_BID_LANE_ENABLED", True)
        assert ag_mod._bid_pass_enabled()


def test_bid_pass_runs_for_pf_maker_mode_without_generic_lane(monkeypatch):
    monkeypatch.setattr(ag, "MERID_MAKER_BID_LANE_ENABLED", False)
    monkeypatch.setattr(
        "merid.prediction.directional_regime.pinned_fav_maker_mode",
        lambda: True,
    )
    assert ag._bid_pass_enabled()


def test_bid_pass_runs_for_drift_lane_without_generic_lane(monkeypatch):
    monkeypatch.setattr(ag, "MERID_MAKER_BID_LANE_ENABLED", False)
    monkeypatch.setattr(
        "merid.prediction.directional_regime.pinned_fav_maker_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "merid.prediction.drift_lane.drift_enabled", lambda: True
    )
    assert ag._bid_pass_enabled()


def test_bid_pass_runs_for_cheap_no_without_generic_lane(monkeypatch):
    monkeypatch.setattr(ag, "MERID_MAKER_BID_LANE_ENABLED", False)
    monkeypatch.setattr(
        "merid.prediction.directional_regime.pinned_fav_maker_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "merid.prediction.drift_lane.drift_enabled", lambda: False
    )
    monkeypatch.setattr(
        "merid.prediction.drift_lane.cheap_no_enabled", lambda: True
    )
    assert ag._bid_pass_enabled()


def test_bid_pass_off_only_when_no_consumer_lane_enabled(monkeypatch):
    monkeypatch.setattr(ag, "MERID_MAKER_BID_LANE_ENABLED", False)
    monkeypatch.setattr(
        "merid.prediction.directional_regime.pinned_fav_maker_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "merid.prediction.drift_lane.drift_enabled", lambda: False
    )
    monkeypatch.setattr(
        "merid.prediction.drift_lane.cheap_no_enabled", lambda: False
    )
    assert not ag._bid_pass_enabled()


def test_generic_lane_classification():
    # Unstamped or maker_bid-stamped selections consume the generic counter.
    assert ag._is_generic_maker_bid_lane(None)
    assert ag._is_generic_maker_bid_lane("")
    assert ag._is_generic_maker_bid_lane("maker_bid")
    # Lane-owned selections consume their own durable counters downstream
    # (pinned_fav -> pinned_fav_fills.json, drift/cheap -> drift_lane_state).
    for lane in (
        "pinned_fav",
        "drift_fav",
        "cheap_no_settle",
        "threshold_cell",
        "window_quota",
        "evidence_cell_escape",
    ):
        assert not ag._is_generic_maker_bid_lane(lane), lane


def test_eval_not_gated_by_submission_counter():
    """The eval call site must not short-circuit on the daily counter —
    the cap is enforced at emission via consume-then-suppress."""
    src = inspect.getsource(ag)
    eval_idx = src.find('decision_maker_bid = _call_trade_decision(')
    assert eval_idx > 0, "maker_bid eval call site not found"
    guard = src[eval_idx - 400:eval_idx]
    assert "_bid_pass_enabled()" in guard
    assert "_maker_bid_under_daily_cap()" not in guard


def test_generic_cap_suppresses_at_emission():
    """Generic selections over the daily cap rewrite to NO_TRADE with a
    named reason — the LANE_SUPPRESSED pattern used by every bounded lane."""
    src = inspect.getsource(ag)
    assert "maker_bid_cap_exceeded_at_emission" in src
    # The emission gate must consult the generic-lane classifier so lane-
    # owned candidates never burn the generic budget.
    assert "_is_generic_maker_bid_lane(_mb_lane)" in src
