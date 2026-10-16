"""FIX 11 (2026-10-15): measured policy give-back reserve.

The armed exit policy pays {0, TP, 100}, not {0, 100} — a triggered profit
exit sells below the settlement payoff when the market recovers.  The reserve
is measured from logs/exit_markouts.jsonl: E[max(0, -markout_60s)] on
profit-path exits, charged per entry as p_trigger * giveback.
"""
from __future__ import annotations

import json
import math

import pytest

from merid.prediction import exit_giveback as xg
from merid.prediction.trade_decision import compute_edge


def _write_marks(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _mark(asset, markout, reason="take_profit", horizon=60.0):
    return {
        "event": "exit_markout",
        "asset": asset,
        "side": "yes",
        "reason": reason,
        "horizon_s": horizon,
        "markout_cents": markout,
        "exit_price_cents": 70.0,
    }


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_EXIT_MARKOUT_LOG", str(tmp_path / "em.jsonl"))
    monkeypatch.delenv("MERID_POLICY_GIVEBACK_ENABLED", raising=False)
    monkeypatch.delenv("MERID_POLICY_GIVEBACK_MIN_SAMPLES", raising=False)
    monkeypatch.delenv("MERID_POLICY_GIVEBACK_FLOOR_CENTS", raising=False)
    monkeypatch.delenv("MERID_POLICY_GIVEBACK_CAP_CENTS", raising=False)
    xg.reset_cache()
    yield
    xg.reset_cache()


def test_giveback_floor_when_no_log(tmp_path):
    """Missing log -> bounded floor, not zero."""
    assert xg.giveback_per_trigger_cents("BTC") == pytest.approx(1.0)


def test_giveback_measured_mean_of_recoveries(tmp_path):
    """E[max(0,-markout)] over profit exits; losses/side exits excluded."""
    _write_marks(
        tmp_path / "em.jsonl",
        [
            _mark("BTC", -6.0),   # recovered 6c after we sold -> giveback 6
            _mark("BTC", -10.0),  # giveback 10
            _mark("BTC", 4.0),    # market fell -> no giveback
            _mark("BTC", -30.0, reason="hard_stop"),  # loss exit: excluded
            _mark("BTC", -20.0, horizon=5.0),          # wrong horizon: excluded
        ],
    )
    # givebacks [6,10,0] -> mean 5.33
    assert xg.giveback_per_trigger_cents("BTC") == pytest.approx(16.0 / 3.0)


def test_giveback_falls_back_to_global_and_caps(tmp_path):
    _write_marks(
        tmp_path / "em.jsonl",
        [_mark("ETH", -25.0) for _ in range(4)],  # ETH: 25c giveback
    )
    # ETH mean 25 > cap 15 -> capped
    assert xg.giveback_per_trigger_cents("ETH") == pytest.approx(15.0)
    # SOL has no rows -> falls back to the pooled estimate (25 -> cap 15)
    assert xg.giveback_per_trigger_cents("SOL") == pytest.approx(15.0)


def test_giveback_disabled_returns_zero(tmp_path, monkeypatch):
    _write_marks(tmp_path / "em.jsonl", [_mark("BTC", -9.0) for _ in range(4)])
    monkeypatch.setenv("MERID_POLICY_GIVEBACK_ENABLED", "0")
    xg.reset_cache()
    assert xg.giveback_per_trigger_cents("BTC") == 0.0


def test_giveback_sparse_samples_still_measured(tmp_path):
    _write_marks(
        tmp_path / "em.jsonl",
        [_mark("DOGE", -8.0) for _ in range(3)],  # exactly min_samples
    )
    assert xg.giveback_per_trigger_cents("DOGE") == pytest.approx(8.0)


def test_edge_charges_policy_giveback():
    """net_edge subtracts the give-back reserve; decomposition stays explicit."""
    bd = compute_edge(
        p_yes=0.70,
        selected_side="yes",
        entry_price=0.64,
        entry_fee=0.0175,
        exit_cost_reserve=0.005,
        model_risk_reserve=0.05,
        policy_giveback_reserve=0.03,
    )
    assert math.isclose(
        bd.net_edge,
        0.70 - 0.64 - 0.0175 - 0.005 - 0.05 - 0.03,
        abs_tol=1e-9,
    )
    assert bd.policy_giveback_reserve == pytest.approx(0.03)
