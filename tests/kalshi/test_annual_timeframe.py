"""Tests for annual timeframe config coverage in market_filter.

Ensures that all 5 assets × 6 timeframes (including annual) are fully
represented in MIN_EDGE_GRID, MAX_PRICE_GRID, and PRICE_BANDS so that
annual Kalshi contracts are never silently filtered or mispriced.
"""
import pytest
from decimal import Decimal

from merid.event_venues.kalshi.market_filter import (
    CANONICAL_TIMEFRAMES_SET,
    MIN_EDGE_GRID,
    MAX_PRICE_GRID,
    PRICE_BANDS,
    PRICE_BANDS_DEFAULT,
    get_series_timeframe_bucket,
    get_tiered_min_edge,
    get_tiered_max_price,
    get_price_band,
)

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly", "annual")


# ── Canonical set ──────────────────────────────────────────────────────────

def test_canonical_timeframes_set_has_annual():
    assert "annual" in CANONICAL_TIMEFRAMES_SET


def test_canonical_timeframes_set_has_all_six():
    assert CANONICAL_TIMEFRAMES_SET == {"15m", "1h", "daily", "weekly", "monthly", "annual"}


# ── MIN_EDGE_GRID ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("asset", ASSETS)
def test_min_edge_grid_has_annual(asset):
    assert "annual" in MIN_EDGE_GRID[asset], f"MIN_EDGE_GRID[{asset}] missing annual"


@pytest.mark.parametrize("asset", ASSETS)
def test_min_edge_grid_all_six_timeframes(asset):
    missing = CANONICAL_TIMEFRAMES_SET - set(MIN_EDGE_GRID[asset].keys())
    assert not missing, f"MIN_EDGE_GRID[{asset}] missing: {missing}"


@pytest.mark.parametrize("asset", ASSETS)
def test_min_edge_annual_below_monthly(asset):
    """Annual markets are lower-noise → annual floor ≤ monthly floor."""
    assert MIN_EDGE_GRID[asset]["annual"] <= MIN_EDGE_GRID[asset]["monthly"]


@pytest.mark.parametrize("asset", ASSETS)
def test_min_edge_annual_above_zero(asset):
    assert MIN_EDGE_GRID[asset]["annual"] > Decimal("0")


# ── MAX_PRICE_GRID ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("asset", ASSETS)
def test_max_price_grid_has_annual(asset):
    assert "annual" in MAX_PRICE_GRID[asset], f"MAX_PRICE_GRID[{asset}] missing annual"


@pytest.mark.parametrize("asset", ASSETS)
def test_max_price_annual_above_monthly(asset):
    """Annual max price must exceed monthly — longer tenor = higher prob cap."""
    assert MAX_PRICE_GRID[asset]["annual"] > MAX_PRICE_GRID[asset]["monthly"], (
        f"{asset}: annual max_price={MAX_PRICE_GRID[asset]['annual']} "
        f"<= monthly={MAX_PRICE_GRID[asset]['monthly']}"
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_max_price_annual_above_fallback(asset):
    """Annual max price must exceed the legacy global fallback (35 cents)."""
    from merid.event_venues.kalshi.market_filter import MAX_PRICE_GLOBAL_FALLBACK
    assert MAX_PRICE_GRID[asset]["annual"] > MAX_PRICE_GLOBAL_FALLBACK, (
        f"{asset}: annual max_price={MAX_PRICE_GRID[asset]['annual']} "
        f"<= fallback={MAX_PRICE_GLOBAL_FALLBACK} — annual markets would be over-filtered"
    )


# ── PRICE_BANDS ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("asset", ASSETS)
def test_price_band_has_annual(asset):
    assert (asset, "annual") in PRICE_BANDS, f"PRICE_BANDS missing ({asset}, annual)"


@pytest.mark.parametrize("asset", ASSETS)
def test_price_band_annual_explicitly_defined(asset):
    """Annual band must be explicitly defined as a key in PRICE_BANDS (not just a dict miss)."""
    assert (asset, "annual") in PRICE_BANDS, (
        f"({asset}, annual) key is absent from PRICE_BANDS — only PRICE_BANDS_DEFAULT fallback applies"
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_price_band_annual_valid_range(asset):
    lo, hi = PRICE_BANDS[(asset, "annual")]
    assert 0.0 < lo < hi < 1.0, f"({asset}, annual) band {(lo, hi)} is invalid"


# ── Ticker detection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker,expected", [
    ("KXBTCY",              "annual"),
    ("KXETHY",              "annual"),
    ("KXSOLY",              "annual"),
    ("KXBTCY-26DEC2025",    "annual"),
    ("KXBTC15M",            "15m"),
    ("KXBTC15M-26MAR250115-15", "15m"),
    ("KXBTC",               "1h"),
    ("KXETH-26MAR2025-1500", "1h"),
    ("KXBTCD1",             "daily"),
    ("KXBTCW1",             "weekly"),
    ("KXBTC1M",             "monthly"),
])
def test_get_series_timeframe_bucket(ticker, expected):
    assert get_series_timeframe_bucket(ticker) == expected, (
        f"ticker={ticker!r}: got {get_series_timeframe_bucket(ticker)!r}, expected {expected!r}"
    )


# ── Helper functions with annual tickers ──────────────────────────────────

@pytest.mark.parametrize("asset", ASSETS)
def test_get_tiered_min_edge_annual(asset):
    edge = get_tiered_min_edge(asset, "KXBTCY")
    assert edge >= Decimal("0.02"), f"{asset}/annual: edge {edge} suspiciously low"
    assert edge <= Decimal("0.20"), f"{asset}/annual: edge {edge} suspiciously high"


@pytest.mark.parametrize("asset", ASSETS)
def test_get_tiered_max_price_annual(asset):
    price = get_tiered_max_price(asset, "KXBTCY")
    assert price > 35, f"{asset}/annual: max_price={price} <= 35 (legacy fallback — grids not wired)"
    assert price <= 99, f"{asset}/annual: max_price={price} >= 99 (too high)"


@pytest.mark.parametrize("asset", ASSETS)
def test_get_price_band_annual(asset):
    lo, hi = get_price_band(asset, "KXBTCY")
    assert lo > 0.0
    assert hi < 1.0
    assert lo < hi
    # Must have an explicit entry (key must exist in PRICE_BANDS dict, not just fallback)
    assert (asset, "annual") in PRICE_BANDS, (
        f"{asset}/annual: no explicit key in PRICE_BANDS — only fallback applies"
    )
