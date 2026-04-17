"""Tests for catalog subset filter (Bug S2-1 regression guard)."""
import pytest
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
from config.kalshi_universe_loader import fetch_kalshi_active_markets


def _make_client_stub(tickers, series_prefix="KXBTC"):
    """Minimal stub that returns a fixed list of open market tickers.

    series_prefix must start with a value in KALSHI_INCLUDED_SERIES_PREFIXES so
    the series-prefix guard inside fetch_kalshi_active_markets() passes through.
    """

    class _Market:
        def __init__(self, t):
            self.ticker = t
            self.status = "open"

    class _Event:
        def __init__(self, markets, series):
            self.category = "crypto"
            self.series_ticker = series
            self.markets = markets

    class _Resp:
        def __init__(self, tickers, series_prefix):
            self.events = [_Event([_Market(t) for t in tickers], series_prefix)]
            self.cursor = None

        def get(self, key, default=None):
            return getattr(self, key, default)

    class _Client:
        def __init__(self, tickers, series_prefix):
            self._tickers = tickers
            self._series_prefix = series_prefix

        def get_events(self, **kwargs):
            return _Resp(self._tickers, self._series_prefix)

    return _Client(tickers, series_prefix)


def test_btc_15m_subset_nonempty_for_updown_ticker():
    """A ticker starting with the BTC_15M series prefix must land in BTC_15M subset."""
    live_ticker = "KXBTUPDOWN-15M-0316-1415"
    # series_prefix "KXBTC" is in KALSHI_INCLUDED_SERIES_PREFIXES — passes the series guard
    client = _make_client_stub([live_ticker], series_prefix="KXBTC")
    result = fetch_kalshi_active_markets(client)
    assert live_ticker in result["BTC_15M"], (
        f"Expected {live_ticker!r} in BTC_15M subset but got {result['BTC_15M']}"
    )


def test_eth_15m_subset_nonempty_for_updown_ticker():
    live_ticker = "KXETHUPDOWN-15M-0316-1415"
    # series_prefix "KXETH" is in KALSHI_INCLUDED_SERIES_PREFIXES
    client = _make_client_stub([live_ticker], series_prefix="KXETH")
    result = fetch_kalshi_active_markets(client)
    assert live_ticker in result["ETH_15M"]


def test_sol_15m_ticker_not_in_eth_or_btc_subset():
    """SOL ticker must land only in SOL_15M, not in ETH_15M or BTC_15M."""
    live_ticker = "KXSOLUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker], series_prefix="KXSOL")
    result = fetch_kalshi_active_markets(client)
    assert live_ticker in result["SOL_15M"]
    assert live_ticker not in result.get("ETH_15M", [])
    assert live_ticker not in result.get("BTC_15M", [])


def test_unrelated_ticker_not_in_btc_subset():
    """An ETH ticker must not appear in the BTC_15M subset."""
    live_ticker = "KXETHUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker], series_prefix="KXETH")
    result = fetch_kalshi_active_markets(client)
    assert live_ticker not in result["BTC_15M"]


# ── Bug S2-2: series-ticker canonicalization ──────────────────────────────

from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP


def test_btc_15m_series_map_matches_canonical():
    """AGENT_SERIES_MAP["BTC_15M"] must contain the exact canonical prefix from KALSHI_CRYPTO_PRODUCTS."""
    canonical_prefix = KALSHI_CRYPTO_PRODUCTS["BTC_15M"][0]   # e.g. "KXBTUPDOWN-15M"
    assert canonical_prefix in AGENT_SERIES_MAP["BTC_15M"], (
        f"Expected {canonical_prefix!r} in AGENT_SERIES_MAP['BTC_15M'] but got {AGENT_SERIES_MAP['BTC_15M']}"
    )


def test_doge_15m_series_map_matches_canonical():
    canonical_prefix = KALSHI_CRYPTO_PRODUCTS["DOGE_15M"][0]
    assert canonical_prefix in AGENT_SERIES_MAP["DOGE_15M"], (
        f"Expected {canonical_prefix!r} in AGENT_SERIES_MAP['DOGE_15M'] but got {AGENT_SERIES_MAP['DOGE_15M']}"
    )
