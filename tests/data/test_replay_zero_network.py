"""Verify that a replay run makes no direct network calls."""

import os
from pathlib import Path
from unittest import mock

import pytest

import requests

from merid.data.ingress_replay import get_replay_dispatcher, reset_replay_dispatcher_for_tests
from merid.settings import settings


@pytest.fixture(autouse=True)
def _replay_env(tmp_path: Path):
    """Set up a minimal replay tape and clear state before/after each test."""
    old_tape = os.environ.get("MERID_REPLAY_TAPE")
    old_replay = os.environ.get("MERID_REPLAY")
    old_record = os.environ.get("MERID_INGRESS_RECORDING")

    reset_replay_dispatcher_for_tests(None)
    tape_dir = Path(__file__).parent / "golden" / "replay_tape"
    os.environ["MERID_REPLAY_TAPE"] = str(tape_dir)
    os.environ["MERID_INGRESS_RECORDING"] = "false"
    os.environ["MERID_REPLAY"] = "true"

    # Reset settings latches to keep the test replay-safe.
    settings.MERID_ALLOW_LIVE_TRADES = False
    settings.TRADING_ENABLED = False

    yield

    if old_tape is None:
        os.environ.pop("MERID_REPLAY_TAPE", None)
    else:
        os.environ["MERID_REPLAY_TAPE"] = old_tape
    if old_replay is None:
        os.environ.pop("MERID_REPLAY", None)
    else:
        os.environ["MERID_REPLAY"] = old_replay
    if old_record is None:
        os.environ.pop("MERID_INGRESS_RECORDING", None)
    else:
        os.environ["MERID_INGRESS_RECORDING"] = old_record
    reset_replay_dispatcher_for_tests(None)


def test_settings_balance_fetch_skips_network_in_replay() -> None:
    """settings._fetch_kalshi_balance must not call requests in replay."""
    with mock.patch("requests.get") as mock_get:
        result = settings._fetch_kalshi_balance()
    assert mock_get.call_count == 0
    assert result == 0.0


def test_market_state_sync_rest_fallback_skips_network_in_replay() -> None:
    """KalshiMarketStateStore.get_trusted_quote_sync must not hit REST in replay."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    with mock.patch("httpx.Client.get") as mock_get:
        quote = store.get_trusted_quote_sync("KXBTC15M-NONEXISTENT")
    assert mock_get.call_count == 0
    assert quote is None


def test_unified_spot_service_skips_network_in_replay() -> None:
    """UnifiedSpotService must not call public spot APIs in replay."""
    from data.unified_spot_service import get_unified_spot_service

    svc = get_unified_spot_service()
    with mock.patch("requests.get") as mock_get:
        result = svc.get("BTC")
    assert mock_get.call_count == 0
