"""Single-source crypto lane config must stay aligned across WS, catalog, and risk."""

from __future__ import annotations

import pytest

from config.kalshi_crypto_config import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_FREQS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    check_ws_ticker_asset_coverage,
    kalshi_ticker_to_asset,
)
from config.kalshi_universe import ACTIVE_CRYPTO_WS_TIMEFRAMES as UNIVERSE_WS_TF
from merid.event_venues.kalshi.market_selector import ALL_TIMEFRAMES


def test_active_crypto_assets_five_coin_grid() -> None:
    assert set(ACTIVE_CRYPTO_ASSETS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}


def test_active_crypto_freqs_match_catalog_timeframe_derivation() -> None:
    assert ACTIVE_CRYPTO_FREQS == ["15M"]
    assert ACTIVE_CRYPTO_WS_TIMEFRAMES == ["15m"]
    # Note: UNIVERSE_WS_TF and ALL_TIMEFRAMES may have more timeframes for broader crypto lane
    # For 15m stack, we only use 15m timeframe


@pytest.mark.skip(reason="active_crypto_asset_mood_timeframe_grid removed - mood surfaces not used in 15m stack")
def test_active_crypto_mood_grid_matches_assets_times_ws_tfs() -> None:
    from config.kalshi_crypto_config import active_crypto_asset_mood_timeframe_grid
    g = active_crypto_asset_mood_timeframe_grid()
    assert len(g) == len(ACTIVE_CRYPTO_ASSETS) * len(ACTIVE_CRYPTO_WS_TIMEFRAMES)


def test_check_ws_ticker_asset_coverage_detects_gap() -> None:
    ok, counts, missing = check_ws_ticker_asset_coverage(
        ["KXBTC15M-A", "KXETH15M-B"],
        strict=False,
    )
    assert not ok
    assert set(missing) >= {"SOL", "XRP", "DOGE"}
    assert counts["BTC"] >= 1 and counts["ETH"] >= 1


def test_check_ws_ticker_asset_coverage_strict_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        check_ws_ticker_asset_coverage(["KXBTC-A"], strict=True)


def test_kalshi_ticker_to_asset_longest_prefix() -> None:
    assert kalshi_ticker_to_asset("KXETH-26MAR2914-T3000") == "ETH"
    assert kalshi_ticker_to_asset("KXBTC15M-26MAR291315-15") == "BTC"
    assert kalshi_ticker_to_asset("KXBTCD1-26MAR-T50000") == "BTC"
    assert kalshi_ticker_to_asset("KXDOGEW1-26MAR-T001") == "DOGE"
