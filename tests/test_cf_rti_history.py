"""Tests for CF-RTI history and return helpers."""

import math
import time
from decimal import Decimal

import pytest

from merid.data import cf_rti_adapter
from merid.data.cf_rti_adapter import (
    CfbRtiObservation,
    get_rti_history,
    get_rti_return,
    reset_state,
)


def make_obs(asset, value, source_ts_ms, **kwargs):
    return CfbRtiObservation(
        asset=asset,
        cfb_symbol=f"{asset}_RTI",
        value=value,
        source_ts_ms=source_ts_ms,
        observed_ts_ms=source_ts_ms,
        observed_ts_mono_ns=int(time.monotonic() * 1e9),
        value_decimal=Decimal(str(value)),
        **kwargs,
    )


def _record_observations(*obs):
    for o in obs:
        cf_rti_adapter._record_rti_history(o.asset, o)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_state()
    yield
    reset_state()


def test_get_rti_history_returns_chronological_order():
    obs = [
        make_obs("BTC", 60000.0, 1_000_000),
        make_obs("BTC", 60100.0, 1_001_000),
        make_obs("BTC", 60200.0, 1_002_000),
    ]
    _record_observations(*obs)
    history = get_rti_history("BTC")
    assert len(history) == 3
    assert [o.source_ts_ms for o in history] == [1_000_000, 1_001_000, 1_002_000]


def test_get_rti_history_filters_by_max_age():
    obs = [
        make_obs("BTC", 60000.0, 0),
        make_obs("BTC", 60100.0, 30_000),
        make_obs("BTC", 60200.0, 60_000),
    ]
    _record_observations(*obs)
    # 35 seconds of age from the 60,000 ms timestamp keeps the 30,000 and 60,000 ms obs.
    history = get_rti_history("BTC", max_age_s=35.0)
    assert len(history) == 2
    assert history[0].source_ts_ms == 30_000


def test_get_rti_return_computes_log_return():
    obs = [
        make_obs("BTC", 60000.0, 0),
        make_obs("BTC", 60100.0, 10_000),
    ]
    _record_observations(*obs)
    ret = get_rti_return("BTC", 10.0)
    assert ret is not None
    assert math.isclose(ret, math.log(60100.0 / 60000.0), rel_tol=1e-9)


def test_get_rti_return_returns_none_when_lookback_unavailable():
    obs = [
        make_obs("BTC", 60000.0, 0),
        make_obs("BTC", 60100.0, 5_000),
    ]
    _record_observations(*obs)
    # 20-second lookback requested but only 5 seconds of data -> None
    assert get_rti_return("BTC", 20.0) is None


def test_get_rti_return_returns_none_for_insufficient_history():
    _record_observations(make_obs("BTC", 60000.0, 0))
    assert get_rti_return("BTC", 1.0) is None


def test_get_rti_return_returns_none_for_nonpositive_values():
    obs = [
        make_obs("BTC", 0.0, 0),
        make_obs("BTC", 60100.0, 10_000),
    ]
    _record_observations(*obs)
    assert get_rti_return("BTC", 10.0) is None


def test_get_rti_return_uses_exact_lookback_match():
    obs = [
        make_obs("BTC", 60000.0, 0),
        make_obs("BTC", 60050.0, 5_000),
        make_obs("BTC", 60100.0, 10_000),
        make_obs("BTC", 60200.0, 25_000),
    ]
    _record_observations(*obs)
    # A 20s lookback from 25_000 should use the 5_000 ms observation,
    # which is the most recent at/before the 5_000 ms cutoff.
    ret = get_rti_return("BTC", 20.0)
    assert ret is not None
    assert math.isclose(ret, math.log(60200.0 / 60050.0), rel_tol=1e-9)


def test_duplicate_source_timestamps_deduped():
    obs = [
        make_obs("BTC", 60000.0, 1_000),
        make_obs("BTC", 60001.0, 1_000),
    ]
    _record_observations(*obs)
    history = get_rti_history("BTC")
    assert len(history) == 1
    assert history[0].value == 60000.0
