"""Tests for the Deflated-Sharpe leg of validate_before_lift()."""

import random

import pytest

from merid.risk.btc_promotion_config import BacktestReport, validate_before_lift


def _report(returns, *, sharpe=1.5, max_dd=0.10, trades=300, years=2.0,
            n_trials=1, trial_sharpes=None):
    eq = [100.0]
    for r in returns:
        eq.append(eq[-1] * (1 + r))
    return BacktestReport(
        equity_curve=eq,
        returns=list(returns),
        max_drawdown=max_dd,
        sharpe=sharpe,
        trades=trades,
        years=years,
        n_trials=n_trials,
        trial_sharpes=trial_sharpes,
    )


def _strong_returns(n=2000, seed=7):
    rng = random.Random(seed)
    return [0.001 + rng.gauss(0, 0.01) for _ in range(n)]


def test_strong_report_passes_with_dsr_detail():
    res = validate_before_lift(_report(_strong_returns(), n_trials=25))
    assert res["ok"] is True
    assert res["reason"] == "ok"
    assert res["dsr"]["evaluated"] is True
    assert res["dsr"]["dsr"] == pytest.approx(1.0, abs=0.01)
    assert res["dsr"]["n_trials"] == 25


def test_selection_inflation_fails_dsr_leg():
    # Sharpe clears the legacy 0.7 floor but 500 tried variants deflate it
    # below the 0.95 DSR threshold — the exact failure mode the gate exists for.
    rng = random.Random(3)
    rets = [0.0004 + rng.gauss(0, 0.01) for _ in range(8760)]
    res = validate_before_lift(
        _report(rets, sharpe=0.8, max_dd=0.20, trades=150, years=1.0, n_trials=500)
    )
    assert res["ok"] is False
    assert res["reason"].startswith("dsr_below_")
    assert res["dsr"]["dsr"] < 0.95


def test_legacy_failures_short_circuit_before_dsr():
    res = validate_before_lift(_report(_strong_returns(), sharpe=0.5))
    assert res["ok"] is False
    assert res["reason"] == "sharpe_lt_0p7"
    assert res["dsr"] == {"evaluated": False}


def test_degenerate_returns_fail_closed_on_dsr():
    res = validate_before_lift(
        _report([0.001] * 2000, sharpe=99.0, max_dd=0.0, trades=500, years=2.0)
    )
    # Constant returns: sharpe field is caller-supplied so legacy checks pass,
    # but the DSR leg cannot evaluate a zero-variance series -> fail closed.
    assert res["ok"] is False
    assert res["reason"] == "dsr_not_evaluable"


def test_dsr_min_env_zero_disables_leg(monkeypatch):
    monkeypatch.setenv("MERID_PROMOTION_DSR_MIN", "0")
    rng = random.Random(11)
    rets = [rng.gauss(0, 0.01) for _ in range(8760)]
    res = validate_before_lift(
        _report(rets, sharpe=0.8, max_dd=0.20, trades=150, years=1.0, n_trials=500)
    )
    assert res["ok"] is True
    assert res["dsr"]["evaluated"] is True  # still computed for the audit trail


def test_trial_sharpes_path_uses_empirical_variance():
    # Realistic per-bar trial Sharpes (~0.01-0.05 scale), not enormous ones —
    # the empirical variance sets the benchmark the selected SR must beat.
    dispersed = [0.05, -0.03, 0.04, -0.01, 0.02, 0.0, -0.04, 0.03]
    res = validate_before_lift(
        _report(_strong_returns(), n_trials=1, trial_sharpes=dispersed)
    )
    assert res["ok"] is True
    assert res["dsr"]["n_trials"] == len(dispersed)
    assert res["dsr"]["trial_sr_variance"] > 0
