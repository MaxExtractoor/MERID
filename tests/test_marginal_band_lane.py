"""Marginal-band lane accounting tests (2026-10-12).

The release lane (NO-side SOL/DOGE/XRP <=1c EDGE_BELOW_DYNAMIC_THRESHOLD
near-miss) must bound exposure — one admission per asset per 15m window,
per-asset and lane-wide daily caps — and self-suspend on realized losses or
repeated pre-wire coherence rejects.  State persists to a day-scoped JSON
file that rolls on the UTC day boundary.
"""
import json

import pytest

import merid.prediction.marginal_band_lane as mbl


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    state_file = tmp_path / "marginal_band_lane.json"
    monkeypatch.setattr(mbl, "MERID_MBAND_DAILY_FILE", str(state_file))
    monkeypatch.setattr(mbl, "MERID_MBAND_LANE_ENABLED", True)
    monkeypatch.setattr(mbl, "MERID_MBAND_DAILY_CAP", 3)
    monkeypatch.setattr(mbl, "MERID_MBAND_PER_ASSET_DAILY_CAP", 2)
    monkeypatch.setattr(mbl, "MERID_MBAND_SUSPEND_CONSEC_LOSSES", 2)
    monkeypatch.setattr(mbl, "MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS", 75.0)
    monkeypatch.setattr(mbl, "MERID_MBAND_SUSPEND_COHERENCE_FAILURES", 3)
    mbl.reset_lane_state_cache()
    yield str(state_file)
    mbl.reset_lane_state_cache()


def test_suppression_reason_none_when_open():
    assert mbl.suppression_reason("SOL", "KXSOL15M-T1") is None


def test_window_slot_consumed_once_per_asset():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    assert mbl.suppression_reason("SOL", "KXSOL15M-T1") == "window_consumed"
    # A different asset in the same window stays open.
    assert mbl.suppression_reason("DOGE", "KXDOGE15M-T1") is None
    # A new window re-opens the asset's slot.
    assert mbl.suppression_reason("SOL", "KXSOL15M-T2") is None


def test_per_asset_daily_cap():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T2", decision_id="d2", side="no"
    )
    assert mbl.suppression_reason("SOL", "KXSOL15M-T3") == (
        "per_asset_daily_cap"
    )
    # The lane-wide cap is not yet hit — other assets remain open.
    assert mbl.suppression_reason("DOGE", "KXDOGE15M-T1") is None


def test_lane_daily_cap():
    for i, asset in enumerate(("SOL", "DOGE", "XRP")):
        mbl.record_submission(
            asset=asset,
            ticker=f"KX{asset}15M-T{i}",
            decision_id=f"d{i}",
            side="no",
        )
    assert mbl.suppression_reason("XRP", "KXXRP15M-T9") == "daily_cap"


def test_lane_disabled_blocks():
    import merid.prediction.marginal_band_lane as m
    m.MERID_MBAND_LANE_ENABLED = False
    try:
        assert m.suppression_reason("SOL", "KXSOL15M-T1") == "lane_disabled"
    finally:
        m.MERID_MBAND_LANE_ENABLED = True


def test_consecutive_loss_suspension():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.record_submission(
        asset="DOGE", ticker="KXDOGE15M-T1", decision_id="d2", side="no"
    )
    mbl.record_settlement(decision_id="d1", net_pnl_cents=-20.0)
    assert mbl.suppression_reason("XRP", "KXXRP15M-T9") is None
    mbl.record_settlement(decision_id="d2", net_pnl_cents=-20.0)
    assert mbl.suppression_reason("XRP", "KXXRP15M-T9").startswith(
        "suspended:consecutive_losses"
    )


def test_win_resets_consecutive_losses():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.record_submission(
        asset="DOGE", ticker="KXDOGE15M-T1", decision_id="d2", side="no"
    )
    mbl.record_submission(
        asset="XRP", ticker="KXXRP15M-T1", decision_id="d3", side="no"
    )
    mbl.record_settlement(decision_id="d1", net_pnl_cents=-20.0)
    mbl.record_settlement(decision_id="d2", net_pnl_cents=+15.0)
    mbl.record_settlement(decision_id="d3", net_pnl_cents=-20.0)
    # one consecutive loss only -> not suspended (the daily cap is a
    # separate budget check and may legitimately read as consumed here).
    assert mbl.lane_status()["suspended"] is False
    assert mbl.lane_status()["consecutive_losses"] == 1


def test_daily_loss_suspension():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.record_settlement(decision_id="d1", net_pnl_cents=-80.0)
    assert mbl.suppression_reason("DOGE", "KXDOGE15M-T9").startswith(
        "suspended:daily_loss"
    )


def test_coherence_failure_suspension():
    for i in range(3):
        mbl.record_coherence_failure(
            decision_id=f"d{i}", reason="stale_decision_price_edge_decayed"
        )
    assert mbl.suppression_reason("SOL", "KXSOL15M-T9").startswith(
        "suspended:coherence_failures"
    )


def test_coherence_failure_releases_decision_binding():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.record_coherence_failure(decision_id="d1", reason="not_marketable")
    assert mbl.marginal_band_for_decision("d1") is None


def test_decision_binding_and_unbound_settlement_ignored():
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    meta = mbl.marginal_band_for_decision("d1")
    assert meta == {
        "asset": "SOL",
        "ticker": "KXSOL15M-T1",
        "side": "no",
        "ts": meta["ts"],
    }
    # A settlement for a decision the lane never admitted is a no-op —
    # primary-lane fills must not touch lane accounting.
    mbl.record_settlement(decision_id="not_a_lane_decision", net_pnl_cents=-999.0)
    status = mbl.lane_status()
    assert status["realized_pnl_cents"] == 0.0
    assert status["consecutive_losses"] == 0


def test_state_persists_across_cache_reset(_isolate):
    mbl.record_submission(
        asset="SOL", ticker="KXSOL15M-T1", decision_id="d1", side="no"
    )
    mbl.reset_lane_state_cache()
    st = json.loads(open(_isolate, encoding="utf-8").read())
    assert st["count"] == 1
    assert st["assets"]["SOL"] == 1
    assert st["windows"]["SOL"] == "KXSOL15M-T1"
    assert "d1" in st["open"]
    # Cache reset reloads the persisted day state.
    assert mbl.suppression_reason("SOL", "KXSOL15M-T1") == "window_consumed"


def test_utc_day_rollover_clears_caps_and_suspension(_isolate):
    mbl.record_coherence_failure(decision_id=None, reason="x")
    mbl.record_coherence_failure(decision_id=None, reason="x")
    mbl.record_coherence_failure(decision_id=None, reason="x")
    assert mbl.lane_status()["suspended"] is True
    # Roll the persisted date back one day; next load must reset day-scoped
    # fields (incl. suspension) while keeping the open binding map.
    st = json.loads(open(_isolate, encoding="utf-8").read())
    st["date"] = "1999-01-01"
    open(_isolate, "w", encoding="utf-8").write(json.dumps(st))
    mbl.reset_lane_state_cache()
    status = mbl.lane_status()
    assert status["suspended"] is False
    assert status["coherence_failures"] == 0
    assert status["count"] == 0
