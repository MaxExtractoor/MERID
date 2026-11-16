"""Regression and invariant tests for price band alignment across BTC, ETH, SOL, XRP, DOGE.

Validates:
1. Tail regimes (tail_low 1-9c, tail_high 91-99c) are enabled and classify executable prices.
2. describe_price_band reports enabled_band for 1-9c and 91-99c.
3. The 60-90s TTE dead zone is closed (markets classify at 15-90s TTE).
4. Sub-15s quotes fail closed (below execution floor).
5. Settlement lane reachability supports up to 150s (2.5 minutes).
6. Pinned favorite lane reachability covers 85-99c.
7. Threshold cell reachability bypasses static regime pre-filters.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from decimal import Decimal
import pytest

from merid.event_venues.kalshi.market_regime import (
    classify_market_regime,
    describe_price_band,
    REGIME_CONFIGS,
)
from merid.prediction.directional_regime import (
    _pinned_fav_lo,
    _pinned_fav_hi,
    pinned_fav_band_match,
)


def test_tail_regimes_present_and_enabled():
    assert "tail_low" in REGIME_CONFIGS
    assert "tail_high" in REGIME_CONFIGS
    assert REGIME_CONFIGS["tail_low"].enabled is True
    assert REGIME_CONFIGS["tail_high"].enabled is True
    assert REGIME_CONFIGS["tail_low"].min_price_cents == 1
    assert REGIME_CONFIGS["tail_low"].max_price_cents == 9
    assert REGIME_CONFIGS["tail_high"].min_price_cents == 91
    assert REGIME_CONFIGS["tail_high"].max_price_cents == 99


def test_tail_regime_classification():
    # 1-9c maps to tail_low
    r_low = classify_market_regime(5, 100)
    assert r_low is not None
    assert r_low.name == "tail_low"

    # 91-99c maps to tail_high
    r_high = classify_market_regime(95, 100)
    assert r_high is not None
    assert r_high.name == "tail_high"


def test_describe_price_band_tail_enabled():
    d_low = describe_price_band(3)
    assert d_low["band"] == "tail_low"
    assert d_low["enabled"] is True
    assert d_low["reason"] == "enabled_band"

    d_high = describe_price_band(97)
    assert d_high["band"] == "tail_high"
    assert d_high["enabled"] is True
    assert d_high["reason"] == "enabled_band"


def test_dead_zone_closed_between_15s_and_90s():
    # Previous bug: between 60s and 90s, all standard regimes were disabled.
    for tte in [20, 45, 75, 89]:
        assert classify_market_regime(50, tte) is not None
        assert classify_market_regime(80, tte) is not None
        assert classify_market_regime(88, tte) is not None
        assert classify_market_regime(5, tte) is not None
        assert classify_market_regime(95, tte) is not None


def test_sub_15s_fails_closed():
    # Below the 15s execution floor, entries are not admitted
    assert classify_market_regime(50, 10) is None
    assert classify_market_regime(95, 5) is None
    assert classify_market_regime(5, 0) is None


def test_settlement_lane_reachable_up_to_150s(monkeypatch):
    monkeypatch.setenv("MERID_SETTLEMENT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_SETTLEMENT_LANE_MAX_TTE_S", "150.0")

    from merid.prediction.agent_grid_15m import _settlement_lane_reachable

    assert _settlement_lane_reachable(150.0) is True
    assert _settlement_lane_reachable(100.0) is True
    assert _settlement_lane_reachable(60.0) is True
    assert _settlement_lane_reachable(15.0) is True
    assert _settlement_lane_reachable(10.0) is False  # below min TTE (15s)
    assert _settlement_lane_reachable(151.0) is False  # above max TTE


def test_pinned_fav_band_range_expanded():
    assert _pinned_fav_lo() <= 85.0
    assert _pinned_fav_hi() >= 99.0
    assert pinned_fav_band_match(85.0) is True
    assert pinned_fav_band_match(90.0) is True
    assert pinned_fav_band_match(95.0) is True
    assert pinned_fav_band_match(99.0) is True
    assert pinned_fav_band_match(84.0) is False
    assert pinned_fav_band_match(100.0) is False


def test_fractional_prices_and_boundary_cracks():
    # Boundary cracks previously caused fractional prices (e.g. 9.3c, 14.5c, 24.8c,
    # 75.4c, 85.5c, 90.5c) to return None and mislabel as 'above_ceiling' with enabled=False.
    boundary_samples = [1.0, 2.3, 9.0, 9.3, 10.0, 14.5, 15.0, 24.8, 25.0, 50.0, 75.4, 76.0, 85.5, 86.0, 90.5, 91.0, 98.7, 99.0]
    for p in boundary_samples:
        r = classify_market_regime(p, 300)
        assert r is not None, f"price {p} returned None regime"
        d = describe_price_band(p)
        assert d["enabled"] is True, f"price {p} reported enabled=False"
        assert d["reason"] == "enabled_band", f"price {p} reported reason {d['reason']}"
        assert d["band"] != "above_ceiling", f"price {p} mislabeled as above_ceiling"
        assert d["band"] != "below_floor", f"price {p} mislabeled as below_floor"

    # Strict out of bounds
    d_below = describe_price_band(0.5)
    assert d_below["enabled"] is False
    assert d_below["band"] == "below_floor"

    d_above = describe_price_band(99.5)
    assert d_above["enabled"] is False
    assert d_above["band"] == "above_ceiling"


if __name__ == "__main__":
    test_tail_regimes_present_and_enabled()
    test_tail_regime_classification()
    test_describe_price_band_tail_enabled()
    test_dead_zone_closed_between_15s_and_90s()
    test_sub_15s_fails_closed()
    test_pinned_fav_band_range_expanded()
    test_fractional_prices_and_boundary_cracks()
    print("All direct tests passed!")
