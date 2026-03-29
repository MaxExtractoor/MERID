"""Tests for config/kalshi_crypto_config.py.

Ensures the canonical crypto universe definition is correct and consistent
with what catalogs and the sentiment bus expect.
"""

from __future__ import annotations

import pytest

from config.kalshi_crypto_config import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_FREQS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    ALL_CRYPTO_ASSETS,
    FREQ_TO_WS_TIMEFRAME,
    MOOD_LABEL_TO_WS_TIMEFRAME,
    WS_TIMEFRAME_TO_FREQ,
    WS_TIMEFRAME_TO_MOOD_LABEL,
    active_crypto_asset_mood_timeframe_grid,
)


class TestActiveAssets:
    """ACTIVE_CRYPTO_ASSETS must contain exactly BTC/ETH/SOL/XRP/DOGE."""

    def test_btc_present(self) -> None:
        assert "BTC" in ACTIVE_CRYPTO_ASSETS

    def test_eth_present(self) -> None:
        assert "ETH" in ACTIVE_CRYPTO_ASSETS

    def test_sol_present(self) -> None:
        assert "SOL" in ACTIVE_CRYPTO_ASSETS

    def test_xrp_present(self) -> None:
        assert "XRP" in ACTIVE_CRYPTO_ASSETS

    def test_doge_present(self) -> None:
        assert "DOGE" in ACTIVE_CRYPTO_ASSETS

    def test_exactly_five_assets(self) -> None:
        assert len(ACTIVE_CRYPTO_ASSETS) == 5

    def test_all_crypto_assets_is_frozenset(self) -> None:
        assert isinstance(ALL_CRYPTO_ASSETS, frozenset)

    def test_all_crypto_assets_matches_active(self) -> None:
        assert ALL_CRYPTO_ASSETS == frozenset(ACTIVE_CRYPTO_ASSETS)


class TestActiveTimeframes:
    """ACTIVE_CRYPTO_WS_TIMEFRAMES must cover 15m/1h/daily/weekly."""

    def test_15m_present(self) -> None:
        assert "15m" in ACTIVE_CRYPTO_WS_TIMEFRAMES

    def test_1h_present(self) -> None:
        assert "1h" in ACTIVE_CRYPTO_WS_TIMEFRAMES

    def test_daily_present(self) -> None:
        assert "daily" in ACTIVE_CRYPTO_WS_TIMEFRAMES

    def test_weekly_present(self) -> None:
        assert "weekly" in ACTIVE_CRYPTO_WS_TIMEFRAMES

    def test_exactly_four_ws_timeframes(self) -> None:
        assert len(ACTIVE_CRYPTO_WS_TIMEFRAMES) == 4

    def test_active_freqs_has_four_entries(self) -> None:
        assert len(ACTIVE_CRYPTO_FREQS) == 4

    def test_freq_to_ws_timeframe_covers_all_freqs(self) -> None:
        for freq in ACTIVE_CRYPTO_FREQS:
            assert freq in FREQ_TO_WS_TIMEFRAME, f"{freq} missing from FREQ_TO_WS_TIMEFRAME"

    def test_ws_timeframe_to_freq_round_trips(self) -> None:
        for freq, tf in FREQ_TO_WS_TIMEFRAME.items():
            assert WS_TIMEFRAME_TO_FREQ[tf] == freq


class TestMoodLabels:
    """WS_TIMEFRAME_TO_MOOD_LABEL must cover all four WS timeframes."""

    def test_all_ws_timeframes_have_mood_label(self) -> None:
        for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            assert tf in WS_TIMEFRAME_TO_MOOD_LABEL, f"{tf} missing from WS_TIMEFRAME_TO_MOOD_LABEL"

    def test_mood_labels_round_trip(self) -> None:
        for tf, mood in WS_TIMEFRAME_TO_MOOD_LABEL.items():
            assert MOOD_LABEL_TO_WS_TIMEFRAME[mood] == tf

    def test_scalp_maps_to_15m(self) -> None:
        assert WS_TIMEFRAME_TO_MOOD_LABEL["15m"] == "scalp"

    def test_intraday_maps_to_1h(self) -> None:
        assert WS_TIMEFRAME_TO_MOOD_LABEL["1h"] == "intraday"

    def test_swing_maps_to_daily(self) -> None:
        assert WS_TIMEFRAME_TO_MOOD_LABEL["daily"] == "swing"

    def test_position_maps_to_weekly(self) -> None:
        assert WS_TIMEFRAME_TO_MOOD_LABEL["weekly"] == "position"


class TestGrid:
    """active_crypto_asset_mood_timeframe_grid must produce exactly 20 entries."""

    def test_grid_has_twenty_entries(self) -> None:
        grid = active_crypto_asset_mood_timeframe_grid()
        assert len(grid) == 20  # 5 assets × 4 timeframes

    def test_grid_covers_all_assets(self) -> None:
        grid = active_crypto_asset_mood_timeframe_grid()
        grid_assets = {entry[0] for entry in grid}
        assert grid_assets == set(ACTIVE_CRYPTO_ASSETS)

    def test_grid_covers_all_timeframes(self) -> None:
        grid = active_crypto_asset_mood_timeframe_grid()
        grid_tfs = {entry[1] for entry in grid}
        assert grid_tfs == set(ACTIVE_CRYPTO_WS_TIMEFRAMES)

    def test_grid_covers_all_mood_labels(self) -> None:
        grid = active_crypto_asset_mood_timeframe_grid()
        grid_moods = {entry[2] for entry in grid}
        assert grid_moods == set(WS_TIMEFRAME_TO_MOOD_LABEL.values())

    def test_grid_entries_are_tuples_of_three(self) -> None:
        for entry in active_crypto_asset_mood_timeframe_grid():
            assert len(entry) == 3
