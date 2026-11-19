"""Tests for merid.backtesting.deflated_sharpe (Bailey & Lopez de Prado DSR)."""

import math

import numpy as np
import pytest

from merid.backtesting.deflated_sharpe import (
    deflated_sharpe_ratio,
    expected_max_sharpe_under_null,
    min_track_record_length,
)


def test_dsr_high_for_strong_consistent_series():
    # Steady positive drift with small nonzero noise -> SR well above the
    # null benchmark. (A literally constant series has zero variance and is
    # degenerate by design.)
    returns = [0.02 + 0.0004 * ((i % 3) - 1) for i in range(40)]
    res = deflated_sharpe_ratio(returns, n_trials=1)
    assert res is not None
    assert res.dsr == pytest.approx(1.0, abs=1e-6)
    assert res.sr_per_period > 0


def test_dsr_deflates_with_more_trials():
    rng_returns = [0.01, -0.005, 0.02, 0.0, -0.01, 0.015, 0.005, -0.002,
                   0.012, -0.004, 0.008, 0.003, -0.006, 0.011, 0.001, -0.003]
    one = deflated_sharpe_ratio(rng_returns, n_trials=1)
    many = deflated_sharpe_ratio(rng_returns, n_trials=500)
    assert one is not None and many is not None
    assert many.sr_benchmark > one.sr_benchmark
    assert many.dsr < one.dsr


def test_dsr_low_for_noise_around_zero():
    # Alternating +/- returns: near-zero mean, high variance -> DSR ~ 0.
    returns = [0.05 if i % 2 == 0 else -0.05 for i in range(60)]
    res = deflated_sharpe_ratio(returns, n_trials=20)
    assert res is not None
    assert res.dsr < 0.5


def test_dsr_degenerate_inputs_return_none():
    assert deflated_sharpe_ratio([0.01] * 5, n_trials=1) is None  # too short
    assert deflated_sharpe_ratio([0.0] * 30, n_trials=1) is None  # zero variance
    assert deflated_sharpe_ratio([0.01] * 30, n_trials=0) is None  # bad trials


def test_expected_max_sharpe_under_null_bounds():
    assert expected_max_sharpe_under_null(0.1, 1) == 0.0
    s2 = expected_max_sharpe_under_null(0.1, 2)
    s100 = expected_max_sharpe_under_null(0.1, 100)
    assert 0.0 < s2 < s100


def test_dsr_annualization_is_report_only():
    returns = [0.01, -0.002, 0.015, 0.003, -0.001, 0.012, 0.004, -0.003,
               0.009, 0.001, -0.004, 0.013, 0.002, -0.002, 0.01, 0.005]
    res = deflated_sharpe_ratio(returns, n_trials=4, periods_per_year=252)
    assert res is not None
    assert res.sr_annualized == pytest.approx(
        res.sr_per_period * math.sqrt(252), rel=1e-6
    )
    # DSR invariant to annualization rescaling.
    res2 = deflated_sharpe_ratio([2 * x for x in returns], n_trials=4)
    assert res2 is not None
    assert res2.dsr == pytest.approx(res.dsr, abs=1e-9)


def test_trial_sharpes_empirical_variance_raises_benchmark():
    # Canonical path: dispersed trial Sharpes produce a higher SR0 than the
    # n_trials-only null fallback for the same count.
    returns = [0.01, -0.002, 0.015, 0.003, -0.001, 0.012, 0.004, -0.003,
               0.009, 0.001, -0.004, 0.013, 0.002, -0.002, 0.01, 0.005]
    dispersed = [0.4, -0.3, 0.2, -0.1, 0.05, -0.02, 0.5, -0.4]
    res = deflated_sharpe_ratio(returns, trial_sharpes=dispersed)
    assert res is not None
    assert res.n_trials == len(dispersed)
    assert res.trial_sr_variance == pytest.approx(
        float(np.var(np.asarray(dispersed), ddof=1)), rel=1e-9
    )
    fallback = deflated_sharpe_ratio(returns, n_trials=len(dispersed))
    assert fallback is not None
    # Empirical dispersion >= null estimate here -> benchmark at least as high.
    assert res.sr_benchmark >= fallback.sr_benchmark - 1e-12


def test_min_track_record_length():
    # SR comfortably above benchmark -> finite MinTRL; below -> None.
    assert min_track_record_length(0.10, 0.02, 0.0, 3.0) is not None
    assert min_track_record_length(0.01, 0.05, 0.0, 3.0) is None
    res = deflated_sharpe_ratio(
        [0.01, -0.002, 0.015, 0.003, -0.001, 0.012, 0.004, -0.003,
         0.009, 0.001, -0.004, 0.013, 0.002, -0.002, 0.01, 0.005] * 4,
        n_trials=3,
    )
    assert res is not None
    assert res.min_track_record_length is None or res.min_track_record_length > 0
