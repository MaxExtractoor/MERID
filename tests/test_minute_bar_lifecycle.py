"""
Contract tests for the agent's 1-minute candle builder.

These tests verify that the in-progress candle is only finalized on a
minute boundary, that exactly one completed bar reaches ATR/ADX/FVG
histories, and that OHLC invariants hold for every finalized bar.
"""

import time
from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m


# Reference time chosen so that 1000.0s falls inside a minute that starts at
# 960.0s and ends at 1020.0s.  1020.0s is the first minute boundary after 1000.
BASE_TIME = 1000.0
NEXT_MINUTE = 1020.0
TWO_MINUTES = 1080.0


@dataclass
class FakeSpotData:
    """Simple spot data object with OHLC fields."""

    open: float
    high: float
    low: float
    volume: float


def _make_agent():
    """Return a minimal LeanAgent15m with mocked dependencies."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        signal_mode="momentum_fvg",
    )

    agent = LeanAgent15m(
        config=config,
        catalog=Mock(),
        market_state_store=Mock(),
        spot_provider=Mock(),
        order_router=Mock(),
        risk_config=Mock(),
    )
    return agent


def _make_time_stepper(monkeypatch, start=BASE_TIME):
    """Patch time.time so tests can advance the clock by mutating a list."""
    current = [start]
    monkeypatch.setattr(
        "merid.prediction.agent_grid_15m.time.time", lambda: current[0]
    )
    return current


def _candle_start_for(t):
    """Return the millisecond candle start for a given Unix timestamp."""
    return (int(t * 1000) // 60000) * 60000


def test_one_in_progress_bar_per_asset(monkeypatch):
    """Many ticks inside one minute update a single mutable candle."""
    agent = _make_agent()
    clock = _make_time_stepper(monkeypatch, start=BASE_TIME)

    data = FakeSpotData(open=100.0, high=100.2, low=99.9, volume=10.0)

    agent._update_price_history("BTC", 100.0, data)
    clock[0] = BASE_TIME + 5.0
    agent._update_price_history("BTC", 100.1, data)
    clock[0] = BASE_TIME + 10.0
    agent._update_price_history("BTC", 100.2, data)

    candle = agent._current_candle["BTC"]
    assert candle is not None
    assert candle["start"] == _candle_start_for(BASE_TIME)
    assert candle["open"] == 100.0
    assert candle["high"] == 100.2
    assert candle["low"] == 99.9
    assert candle["close"] == 100.2
    assert candle["tick_count"] == 3

    # No completed bars should have been emitted yet.
    assert len(agent._spot_price_history["BTC"]) == 0
    assert len(agent._volume_history["BTC"]) == 0
    assert len(agent._sma_history["BTC"]) == 3  # per-tick updates
    assert len(agent._price_1m_history["BTC"]) == 3


def test_minute_boundary_closes_exactly_one_bar(monkeypatch):
    """Crossing a minute boundary finalizes exactly one completed bar."""
    agent = _make_agent()
    clock = _make_time_stepper(monkeypatch, start=BASE_TIME)

    data = FakeSpotData(open=100.0, high=101.0, low=99.5, volume=20.0)

    agent._update_price_history("BTC", 100.0, data)
    clock[0] = BASE_TIME + 10.0
    agent._update_price_history("BTC", 100.5, data)

    # Advance to the next minute.
    clock[0] = NEXT_MINUTE
    agent._update_price_history("BTC", 100.8, data)

    # The first minute should be finalized.
    assert len(agent._spot_price_history["BTC"]) == 1
    assert len(agent._volume_history["BTC"]) == 1

    candle = agent._spot_price_history["BTC"][0]
    ts, close, open_, high, low = candle
    assert open_ == 100.0
    assert high == 101.0
    assert low == 99.5
    assert close == 100.5
    assert low <= open_ <= high
    assert low <= close <= high

    # A new in-progress candle should have started.
    current = agent._current_candle["BTC"]
    assert current["start"] == _candle_start_for(NEXT_MINUTE)
    assert current["open"] == 100.5
    assert current["tick_count"] == 1


def test_large_feed_gap_does_not_invent_bars(monkeypatch):
    """A multi-minute gap only finalizes one real bar."""
    agent = _make_agent()
    clock = _make_time_stepper(monkeypatch, start=BASE_TIME)

    data = FakeSpotData(open=100.0, high=100.5, low=99.5, volume=5.0)

    agent._update_price_history("BTC", 100.0, data)

    # Jump two minutes ahead; the implementation must not create a synthetic
    # zero-range bar for the skipped minute.
    clock[0] = TWO_MINUTES
    agent._update_price_history("BTC", 101.0, data)

    assert len(agent._spot_price_history["BTC"]) == 1
    assert agent._spot_price_history["BTC"][0][2] == 100.0  # open


def test_ohlc_invariants_on_finalized_bar(monkeypatch):
    """Every finalized bar must satisfy low <= open <= high and low <= close <= high."""
    agent = _make_agent()
    clock = _make_time_stepper(monkeypatch, start=BASE_TIME)

    data = FakeSpotData(open=100.0, high=100.5, low=99.0, volume=1.0)

    agent._update_price_history("BTC", 100.0, data)
    clock[0] = BASE_TIME + 5.0
    agent._update_price_history("BTC", 101.0, data)  # exceed public high
    clock[0] = BASE_TIME + 10.0
    agent._update_price_history("BTC", 98.5, data)  # below public low

    clock[0] = NEXT_MINUTE
    agent._update_price_history("BTC", 99.5, data)

    candle = agent._spot_price_history["BTC"][0]
    _, close, open_, high, low = candle

    assert low <= open_ <= high
    assert low <= close <= high
    assert high == 101.0
    assert low == 98.5


def test_adx_and_volume_histories_advance_on_finalized_bar_only(monkeypatch):
    """ADX and volume histories should not grow while a bar is in progress."""
    agent = _make_agent()
    clock = _make_time_stepper(monkeypatch, start=BASE_TIME)

    data = FakeSpotData(open=100.0, high=100.0, low=100.0, volume=1.0)

    # Two ticks in the first minute.
    agent._update_price_history("BTC", 100.0, data)
    clock[0] = BASE_TIME + 10.0
    agent._update_price_history("BTC", 100.0, data)

    pre_close_volume = len(agent._volume_history["BTC"])
    pre_close_tr = len(agent._tr_history.get("BTC", []))

    # First minute close: volume history grows; ADX needs a prior bar,
    # so TR history does not grow on the very first close.
    clock[0] = NEXT_MINUTE
    agent._update_price_history("BTC", 100.0, data)

    assert len(agent._volume_history["BTC"]) == pre_close_volume + 1
    assert len(agent._tr_history["BTC"]) == pre_close_tr

    # Second minute close: now there is a prior bar, so TR history grows.
    clock[0] = BASE_TIME + 70.0  # inside the second minute
    agent._update_price_history("BTC", 100.0, data)
    clock[0] = TWO_MINUTES
    agent._update_price_history("BTC", 100.0, data)

    assert len(agent._volume_history["BTC"]) == pre_close_volume + 2
    assert len(agent._tr_history["BTC"]) == pre_close_tr + 1
