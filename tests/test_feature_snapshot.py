"""Tests for the centralized FeatureSnapshot builder."""

import math
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

import merid.data.cf_rti_adapter as _rti
import merid.prediction.feature_snapshot as _fs
from merid.data.cf_rti_adapter import (
    CfbRtiObservation,
    reset_state,
)
from merid.prediction.feature_snapshot import FeatureSnapshotBuilder


def _make_rti_obs(asset, value, source_ts_ms, observed_ts_ms=None, mono_ns=None):
    if observed_ts_ms is None:
        observed_ts_ms = source_ts_ms
    if mono_ns is None:
        mono_ns = int(time.monotonic_ns())
    return CfbRtiObservation(
        asset=asset,
        cfb_symbol=f"{asset}_RTI",
        value=value,
        source_ts_ms=source_ts_ms,
        observed_ts_ms=observed_ts_ms,
        observed_ts_mono_ns=mono_ns,
        value_decimal=Decimal(str(value)),
        execution_eligible=True,
    )


@pytest.fixture(autouse=True)
def _clean_state():
    reset_state()
    _orig_get_live = _fs.get_live_rti
    _orig_get_return = _fs.get_rti_return
    yield
    _fs.get_live_rti = _orig_get_live
    _fs.get_rti_return = _orig_get_return
    reset_state()


def _make_market_state(asset, bid_cents, ask_cents, bid_size, ask_size, spot):
    ms = MagicMock()
    ms.underlying = asset
    ms.series_ticker = f"KX{asset}15M"
    ms.ticker = f"KX{asset}15M-TEST"
    ms.best_bid_cents = bid_cents
    ms.best_ask_cents = ask_cents
    ms.best_no_bid_cents = 100 - ask_cents
    ms.best_no_ask_cents = 100 - bid_cents
    ms.bid_cents = bid_cents
    ms.ask_cents = ask_cents
    ms.yes_bid = bid_cents
    ms.yes_ask = ask_cents
    ms.no_bid = 100 - ask_cents
    ms.no_ask = 100 - bid_cents
    ms.yes_bid_size = bid_size
    ms.yes_ask_size = ask_size
    ms.no_bid_size = bid_size
    ms.no_ask_size = ask_size
    # Level list format: list of (price_cents, size)
    ms.yes_bids = [(bid_cents, bid_size)]
    ms.no_bids = [(100 - ask_cents, ask_size)]
    ms.top_of_book_size = 0
    ms.external_spot = spot
    ms.spot_price = spot
    ms.last_book_update_ts = time.time()
    ms.expected_expiration_time = time.time() + 600
    return ms


def _record_history(asset, *obs):
    for o in obs:
        _rti._record_rti_history(asset, o)


def test_feature_snapshot_builder_computes_rti_returns_and_microstructure():
    now_ms = 1_000_000_000_000
    btc = _make_rti_obs("BTC", 60200.0, now_ms - 100, mono_ns=now_ms * 1_000_000)
    eth = _make_rti_obs("ETH", 3010.0, now_ms - 100, mono_ns=now_ms * 1_000_000)

    _record_history(
        "BTC",
        _make_rti_obs("BTC", 60000.0, now_ms - 60_000, mono_ns=now_ms * 1_000_000),
        _make_rti_obs("BTC", 60100.0, now_ms - 30_000, mono_ns=now_ms * 1_000_000),
        _make_rti_obs("BTC", 60150.0, now_ms - 10_000, mono_ns=now_ms * 1_000_000),
        btc,
    )
    _record_history(
        "ETH",
        _make_rti_obs("ETH", 3000.0, now_ms - 60_000, mono_ns=now_ms * 1_000_000),
        eth,
    )

    # Patch the RTI functions in the feature_snapshot module so the builder uses
    # the seeded history without trying to open a real WebSocket or REST call.
    _fs.get_live_rti = lambda asset: {"BTC": btc, "ETH": eth}.get(asset)
    _fs.get_rti_return = lambda asset, lookback: {
        ("BTC", 1.0): None,
        ("BTC", 3.0): None,
        ("BTC", 10.0): math.log(60200.0 / 60150.0),
        ("BTC", 30.0): math.log(60200.0 / 60100.0),
        ("BTC", 60.0): math.log(60200.0 / 60000.0),
        ("ETH", 1.0): None,
        ("ETH", 3.0): None,
        ("ETH", 10.0): None,
        ("ETH", 30.0): None,
        ("ETH", 60.0): math.log(3010.0 / 3000.0),
    }.get((asset, lookback))

    store = MagicMock()
    btc_ms = _make_market_state("BTC", 45, 48, 100, 50, 60200.0)
    eth_ms = _make_market_state("ETH", 50, 53, 80, 70, 3010.0)
    store.get_all.return_value = {
        "KXBTC15M-TEST": btc_ms,
        "KXETH15M-TEST": eth_ms,
    }

    builder = FeatureSnapshotBuilder(
        assets=["BTC", "ETH"],
        market_state_store=store,
    )
    snap = builder.build(now=time.time())

    assert snap is not None
    assert "BTC" in snap.by_asset
    assert "ETH" in snap.by_asset

    btc_slice = snap.by_asset["BTC"]
    assert btc_slice.rti_value == 60200.0
    assert btc_slice.rti_execution_eligible is True
    assert "rti_return_10s" in btc_slice.rti_returns
    assert btc_slice.rti_returns["rti_return_10s"] == math.log(60200.0 / 60150.0)
    assert btc_slice.rti_returns["rti_return_60s"] == math.log(60200.0 / 60000.0)

    eth_slice = snap.by_asset["ETH"]
    assert eth_slice.rti_returns["rti_return_60s"] == math.log(3010.0 / 3000.0)

    # Microstructure should be populated for BTC.
    assert btc_slice.microstructure_yes_features is not None
    assert btc_slice.microstructure_no_features is not None
    assert btc_slice.microstructure_total_delta_pp is not None
    # btc_log_return uses the spot history; with one BTC update it is not yet
    # available because the builder needs a second BTC observation.
    assert btc_slice.btc_log_return is None

    # ETH should have a cross-asset delta derived from BTC.
    assert eth_slice.microstructure_cross_delta_pp is not None


def test_feature_snapshot_builder_marks_missing_data():
    _fs.get_live_rti = lambda asset: None
    _fs.get_rti_return = lambda asset, lookback: None

    store = MagicMock()
    store.get_all.return_value = {}
    builder = FeatureSnapshotBuilder(assets=["SOL"], market_state_store=store)
    snap = builder.build(now=time.time())
    sol_slice = snap.by_asset["SOL"]
    assert sol_slice.feature_valid is False
    assert "rti_unavailable" in sol_slice.missing_reasons
    assert "market_state_unavailable" in sol_slice.missing_reasons
