"""Tests for the unit-corrected MACD edge calculation in agent_grid_15m."""

import math

import pytest

from merid.prediction.agent_grid_15m import _fvg_edge_components


def test_btc_example_macd_pct_and_edge_component():
    """BTC: $1.49 MACD histogram on $95,000 spot = 0.00157% before weighting."""
    comp = _fvg_edge_components(
        score=3,
        side_velocity_sign=1.0,
        velocity=5.8799716632798e-06,
        velocity_threshold=0.00015,
        macd_hist=1.49,
        spot_price=95000.0,
        rsi=56.0,
        rsi_zone="neutral",
        fvg_dir=None,
        fvg_conf=0.3,
        macd_edge_weight=10.0,
        max_edge_pct=15.0,
    )
    assert comp["macd_pct"] == pytest.approx(0.0015684210526, abs=1e-9)
    assert comp["macd_edge"] == pytest.approx(0.015684210526, abs=1e-9)
    assert comp["edge_pct"] == pytest.approx(1.0 + comp["macd_edge"], abs=1e-9)


def test_directionality_positive_macd_favors_yes_penalizes_no():
    """A positive MACD histogram should increase the YES edge and decrease the NO edge."""
    base = {
        "score": 4,
        "velocity": 0.0,
        "velocity_threshold": 0.00015,
        "macd_hist": 1.0,
        "spot_price": 100.0,
        "rsi": 50.0,
        "rsi_zone": "neutral",
        "fvg_dir": None,
        "fvg_conf": 0.0,
        "macd_edge_weight": 10.0,
        "max_edge_pct": 15.0,
    }
    yes = _fvg_edge_components(side_velocity_sign=1.0, **base)
    no = _fvg_edge_components(side_velocity_sign=-1.0, **base)
    # macd_pct = 1.0 / 100.0 * 100 = 1.0%; weight 10 -> 10 percentage points
    assert yes["macd_pct"] == pytest.approx(1.0)
    assert yes["macd_edge"] == pytest.approx(10.0)
    assert no["macd_edge"] == pytest.approx(-10.0)
    assert yes["edge_pct"] > no["edge_pct"]


def test_scale_invariance_price_and_macd():
    """Multiplying price and macd_hist by the same factor leaves macd_pct unchanged."""
    kwargs = {
        "score": 4,
        "velocity": 0.0,
        "velocity_threshold": 0.00015,
        "rsi": 50.0,
        "rsi_zone": "neutral",
        "fvg_dir": None,
        "fvg_conf": 0.0,
        "macd_edge_weight": 10.0,
        "max_edge_pct": 15.0,
    }
    low = _fvg_edge_components(
        side_velocity_sign=1.0,
        macd_hist=1.5,
        spot_price=100.0,
        **kwargs,
    )
    high = _fvg_edge_components(
        side_velocity_sign=1.0,
        macd_hist=150.0,
        spot_price=10000.0,
        **kwargs,
    )
    assert low["macd_pct"] == pytest.approx(high["macd_pct"])
    assert low["macd_edge"] == pytest.approx(high["macd_edge"])


def test_zero_or_none_price_guards_against_division_by_zero():
    for price in [0.0, None, -1.0, float("nan")]:
        comp = _fvg_edge_components(
            score=4,
            side_velocity_sign=1.0,
            velocity=0.0,
            velocity_threshold=0.00015,
            macd_hist=1.0,
            spot_price=price,
            rsi=50.0,
            rsi_zone="neutral",
            fvg_dir=None,
            fvg_conf=0.0,
            macd_edge_weight=10.0,
            max_edge_pct=15.0,
        )
        assert comp["macd_pct"] == 0.0
        assert math.isfinite(comp["edge_pct"])


def test_max_edge_pct_cap():
    """Even an enormous normalized MACD must not exceed the configured cap."""
    comp = _fvg_edge_components(
        score=10,
        side_velocity_sign=1.0,
        velocity=0.0,
        velocity_threshold=0.00015,
        macd_hist=10000.0,
        spot_price=1.0,
        rsi=30.0,
        rsi_zone="oversold",
        fvg_dir="bullish",
        fvg_conf=1.0,
        macd_edge_weight=1000.0,
        max_edge_pct=15.0,
    )
    assert comp["edge_pct"] == pytest.approx(15.0)


def test_score_below_three_gets_discounted_edge_not_constant():
    """A score below 3 should discount the edge, not replace it with 0.5."""
    comp = _fvg_edge_components(
        score=2,
        side_velocity_sign=1.0,
        velocity=0.0,
        velocity_threshold=0.00015,
        macd_hist=0.5,
        spot_price=100.0,
        rsi=50.0,
        rsi_zone="neutral",
        fvg_dir=None,
        fvg_conf=0.0,
        macd_edge_weight=10.0,
        max_edge_pct=15.0,
    )
    # macd_pct = 0.5 / 100 * 100 = 0.5%; weight 10 -> 5.0 pp
    # base_edge floor = 1.0, score=2 multiplier = 0.9
    assert comp["macd_pct"] == pytest.approx(0.5)
    assert comp["edge_pct"] == pytest.approx((1.0 + 5.0) * 0.9)


def test_velocity_alignment_bonus_sign():
    """Aligned velocity adds to edge; counter-trend velocity subtracts."""
    aligned = _fvg_edge_components(
        score=4,
        side_velocity_sign=1.0,
        velocity=0.0002,
        velocity_threshold=0.00015,
        macd_hist=0.0,
        spot_price=100.0,
        rsi=50.0,
        rsi_zone="neutral",
        fvg_dir=None,
        fvg_conf=0.0,
        macd_edge_weight=10.0,
        max_edge_pct=15.0,
    )
    counter = _fvg_edge_components(
        score=4,
        side_velocity_sign=1.0,
        velocity=-0.0002,
        velocity_threshold=0.00015,
        macd_hist=0.0,
        spot_price=100.0,
        rsi=50.0,
        rsi_zone="neutral",
        fvg_dir=None,
        fvg_conf=0.0,
        macd_edge_weight=10.0,
        max_edge_pct=15.0,
    )
    assert aligned["velocity_bonus"] > 0
    assert counter["velocity_bonus"] < 0
    assert aligned["edge_pct"] > counter["edge_pct"]
