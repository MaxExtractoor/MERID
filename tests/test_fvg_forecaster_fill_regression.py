"""Regression tests for the FVG forecaster fill/distance fix.

Before the fix, a bullish FVG was marked filled on the same candle it was
detected because ``close >= c3.low`` and the check used ``current_price >= top``.
These tests lock in the corrected sign convention:

- Bullish FVG (gap below current price): fills when price drops to ``<= top``.
- Bearish FVG (gap above current price): fills when price rises to ``>= bottom``.
- ``distance_to_fill`` is positive before the gap is reached and zero/negative
  once price is at or inside the gap.
"""

import pytest

from merid.prediction.forecasters.fvg import FVGForecaster, FVGStore


def _fresh_forecaster() -> FVGForecaster:
    """Return a forecaster with an isolated in-memory store."""
    return FVGForecaster(store=FVGStore())


def _rising_candles(forecaster: FVGForecaster, asset: str = "BTC") -> None:
    """Three rising 15m candles that create a bullish FVG [10100, 10200]."""
    forecaster.update_price(
        asset, "15m",
        open_p=10000, high=10100, low=10050, close=10080, timestamp=1.0,
        min_gap_cents=2.0,
    )
    forecaster.update_price(
        asset, "15m",
        open_p=10080, high=10200, low=10080, close=10150, timestamp=2.0,
        min_gap_cents=2.0,
    )
    forecaster.update_price(
        asset, "15m",
        open_p=10150, high=10300, low=10200, close=10280, timestamp=3.0,
        min_gap_cents=2.0,
    )


def _falling_candles(forecaster: FVGForecaster, asset: str = "BTC") -> None:
    """Three falling 15m candles that create a bearish FVG [10300, 10400]."""
    forecaster.update_price(
        asset, "15m",
        open_p=10500, high=10500, low=10400, close=10450, timestamp=1.0,
        min_gap_cents=2.0,
    )
    forecaster.update_price(
        asset, "15m",
        open_p=10450, high=10450, low=10350, close=10380, timestamp=2.0,
        min_gap_cents=2.0,
    )
    forecaster.update_price(
        asset, "15m",
        open_p=10300, high=10300, low=10200, close=10280, timestamp=3.0,
        min_gap_cents=2.0,
    )


def test_bullish_fvg_persists_after_formation():
    """A bullish FVG must not be filled on the candle that creates it."""
    f = _fresh_forecaster()
    _rising_candles(f)

    active = f._store.get_active_fvgs("BTC", "15m")
    assert len(active) == 1, "bullish FVG should be active after formation"
    fvg = active[0]
    assert fvg.direction == "bullish"
    assert fvg.top == 10200
    assert fvg.bottom == 10100
    assert fvg.filled is False

    # Price is above the gap: distance to fill should be positive.
    assert fvg.distance_to_fill(10280) == pytest.approx(80.0)
    assert fvg.is_within_fill_distance(10280, threshold=100.0)
    assert fvg.is_within_fill_distance(10350, threshold=100.0) is False


def test_bullish_fvg_fills_only_on_retrace():
    """A bullish FVG fills only when price returns to the gap from above."""
    f = _fresh_forecaster()
    _rising_candles(f)

    # First retrace that reaches the top of the gap.
    f.update_price(
        "BTC", "15m",
        open_p=10280, high=10300, low=10190, close=10200, timestamp=4.0,
    )

    active = f._store.get_active_fvgs("BTC", "15m")
    filled = [fvg for fvg in f._store._fvgs["BTC:15m"] if fvg.filled]
    assert len(active) == 0, "FVG should no longer be active after fill"
    assert len(filled) >= 1, "at least one FVG instance should be marked filled"


def test_bullish_distance_to_fill_sign_convention():
    """distance_to_fill is positive above the gap, zero/negative inside/below."""
    f = _fresh_forecaster()
    _rising_candles(f)
    fvg = f._store.get_active_fvgs("BTC", "15m")[0]

    # Above the gap: must drop to reach it.
    assert fvg.distance_to_fill(10300) > 0
    # At the top of the gap.
    assert fvg.distance_to_fill(10200) == pytest.approx(0.0)
    # Inside the gap.
    assert fvg.distance_to_fill(10150) < 0
    # Below the gap (a break-through).
    assert fvg.distance_to_fill(10050) < 0


def test_bearish_fvg_persists_and_fills():
    """A bearish FVG must persist after formation and fill on a retrace up."""
    f = _fresh_forecaster()
    _falling_candles(f)

    active = f._store.get_active_fvgs("BTC", "15m")
    assert len(active) == 1, "bearish FVG should be active after formation"
    fvg = active[0]
    assert fvg.direction == "bearish"
    assert fvg.top == 10400
    assert fvg.bottom == 10300
    assert fvg.filled is False

    # Price is below the gap: distance to fill should be positive.
    assert fvg.distance_to_fill(10280) == pytest.approx(20.0)

    # Retrace that reaches the bottom of the gap.
    f.update_price(
        "BTC", "15m",
        open_p=10280, high=10300, low=10200, close=10300, timestamp=4.0,
        min_gap_cents=2.0,
    )

    active = f._store.get_active_fvgs("BTC", "15m")
    filled = [fvg for fvg in f._store._fvgs["BTC:15m"] if fvg.filled]
    assert len(active) == 0, "FVG should be filled/empty after retrace"
    assert len(filled) >= 1, "at least one FVG instance should be marked filled"


def test_bearish_distance_to_fill_sign_convention():
    """distance_to_fill is positive below the gap, zero/negative inside/above."""
    f = _fresh_forecaster()
    _falling_candles(f)
    fvg = f._store.get_active_fvgs("BTC", "15m")[0]

    assert fvg.distance_to_fill(10250) > 0
    assert fvg.distance_to_fill(10300) == pytest.approx(0.0)
    assert fvg.distance_to_fill(10350) < 0
    assert fvg.distance_to_fill(10500) < 0


def test_predict_converts_spot_price_dollars_to_cents():
    """predict(spot_price=...) must convert dollars to the FVG store's cent units."""
    f = _fresh_forecaster()
    _rising_candles(f)

    # FVG store is in cents (spot*100). Call predict with spot in dollars.
    result = f.predict(
        market_id="KXBTC15M",
        implied_yes=0.5,
        implied_no=0.5,
        volume=1.0,
        open_interest=1.0,
        minutes_to_expiry=10.0,
        asset="BTC",
        timeframe="15m",
        spot_price=102.80,  # dollars -> 10280 cents, just above the bullish FVG top
    )

    assert result is not None
    assert result.components.get("fvg_active") == 1
    # 102.80 dollars is 10280 cents, above the 10200 top -> still positive distance.
    assert result.components.get("fvg_distance_to_fill") == pytest.approx(80.0)


def test_predict_falls_back_when_no_spot_provided():
    """predict without spot_price uses implied_yes as a fallback and warns."""
    f = _fresh_forecaster()
    _rising_candles(f)

    result = f.predict(
        market_id="KXBTC15M",
        implied_yes=0.5,
        implied_no=0.5,
        volume=1.0,
        open_interest=1.0,
        minutes_to_expiry=10.0,
        asset="BTC",
        timeframe="15m",
    )

    assert result is not None
    # Fallback current_price = 0.5 * 100 = 50 cents, which is below the gap.
    # The nearest FVG should be found and distance is negative (inside/below).
    assert result.components.get("fvg_active") == 1
    assert result.components.get("fvg_distance_to_fill") < 0
