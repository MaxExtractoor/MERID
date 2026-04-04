"""Tests for timeframe classification and per-timeframe min-edge bucketing.

Covers:
  - KalshiSignalGenerator._extract_timeframe() — canonical Kalshi ticker patterns
  - KalshiContinuousTrader._get_min_edge() — normalization of non-canonical TF strings
  - EDGE_THRESHOLDS lookup correctness after normalization
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── _extract_timeframe tests ──────────────────────────────────────────────────

class TestKalshiSignalGeneratorExtractTimeframe:
    """_extract_timeframe must map real Kalshi ticker patterns to canonical strings."""

    @pytest.fixture
    def generator(self):
        from merid.signals.kalshi_signals import KalshiSignalGenerator
        return KalshiSignalGenerator.__new__(KalshiSignalGenerator)

    # ── 15-minute patterns ────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "KXBTC-26APR0316-T15M-T95000",
        "KXETH-26APR-15m-T1211",
        "BTC-15MIN-HIGH",
        "KXSOL-15m",
    ])
    def test_15m_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "15m", ticker

    # ── 1-hour patterns ───────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "KXETH-26APR0316-T1H-T1211",
        "KXBTC-D1H-T95000",
        "BTC-1H-HIGH",
        "KXETH-HOURLY-HIGH",
        "BTC-60MIN",
        "ETH-60M-BRACKET",
    ])
    def test_1h_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "1h", ticker

    # ── Daily patterns ────────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "KXBTC-DAILY-T95000",
        "KXETH-24H-T1211",
        "BTC-D24H-CLOSE",
        "ETH-EOD-HIGH",
        "KXBTC-26APR-DAILY",
    ])
    def test_daily_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "daily", ticker

    # ── Weekly patterns ───────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "KXBTC-WEEKLY-HIGH",
        "ETH-WEEK-BRACKET",
        "BTC-EOW-CLOSE",
    ])
    def test_weekly_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "weekly", ticker

    # ── Monthly patterns ──────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "KXBTC-MONTHLY-HIGH",
        "ETH-MONTH-T5000",
        "BTC-EOM-BRACKET",
    ])
    def test_monthly_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "monthly", ticker

    # ── Unknown patterns ──────────────────────────────────────────────────────
    @pytest.mark.parametrize("ticker", [
        "BTC-UNKNOWN",
        "KXBTC-26FEB-T95000",   # no timeframe segment
        "FED-25DEC-T3.00",
    ])
    def test_unknown_patterns(self, generator, ticker):
        assert generator._extract_timeframe(ticker) == "unknown", ticker

    # ── Case-insensitivity ────────────────────────────────────────────────────
    def test_case_insensitive(self, generator):
        assert generator._extract_timeframe("KXBTC-T1H-HIGH") == "1h"
        assert generator._extract_timeframe("kxbtc-t1h-high") == "1h"
        assert generator._extract_timeframe("KXBTC-DAILY") == "daily"

    # ── 15m takes priority over 1h when both present ─────────────────────────
    def test_15m_takes_priority_over_1h(self, generator):
        """T15M should beat T1H if both appear in ticker."""
        assert generator._extract_timeframe("BTC-T15M-T1H") == "15m"


# ── _get_min_edge normalization tests ─────────────────────────────────────────

def _make_ct():
    mock_catalog = MagicMock()
    mock_catalog.get_markets_by_asset.return_value = []
    with patch(
        "merid.trading.kalshi_continuous_trader.get_market_catalog",
        return_value=mock_catalog,
    ):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        return KalshiContinuousTrader(catalog=mock_catalog, dry_run=True)


def _candidate(underlying: str, timeframe: str):
    from merid.trading.kalshi_continuous_trader import TradingCandidate
    return TradingCandidate(
        ticker=f"KXTEST-{underlying}-{timeframe}",
        underlying=underlying,
        timeframe=timeframe,
        mid_price_cents=50,
    )


class TestGetMinEdgeNormalization:
    """_get_min_edge must normalise non-canonical timeframe strings."""

    def test_canonical_1h_uses_grid(self):
        ct = _make_ct()
        # "1h" is canonical — should find a grid entry for ETH
        result = ct._get_min_edge(_candidate("ETH", "1h"))
        from merid.trading.kalshi_continuous_trader import EDGE_THRESHOLDS
        expected = EDGE_THRESHOLDS.get(("ETH", "1h"), ct._min_edge)
        assert result == expected

    def test_hourly_normalizes_to_1h(self):
        ct = _make_ct()
        result_hourly = ct._get_min_edge(_candidate("ETH", "hourly"))
        result_1h = ct._get_min_edge(_candidate("ETH", "1h"))
        assert result_hourly == result_1h

    def test_24h_normalizes_to_daily(self):
        ct = _make_ct()
        result_24h = ct._get_min_edge(_candidate("BTC", "24h"))
        result_daily = ct._get_min_edge(_candidate("BTC", "daily"))
        assert result_24h == result_daily

    def test_eod_normalizes_to_daily(self):
        ct = _make_ct()
        result_eod = ct._get_min_edge(_candidate("BTC", "eod"))
        result_daily = ct._get_min_edge(_candidate("BTC", "daily"))
        assert result_eod == result_daily

    def test_weekly_aliases(self):
        ct = _make_ct()
        result_week = ct._get_min_edge(_candidate("SOL", "week"))
        result_weekly = ct._get_min_edge(_candidate("SOL", "weekly"))
        assert result_week == result_weekly

    def test_monthly_aliases(self):
        ct = _make_ct()
        result_month = ct._get_min_edge(_candidate("DOGE", "month"))
        result_monthly = ct._get_min_edge(_candidate("DOGE", "monthly"))
        assert result_month == result_monthly

    def test_legacy_alias_intraday_to_1h(self):
        ct = _make_ct()
        result_intraday = ct._get_min_edge(_candidate("BTC", "intraday"))
        result_1h = ct._get_min_edge(_candidate("BTC", "1h"))
        assert result_intraday == result_1h

    def test_legacy_alias_scalp_to_15m(self):
        ct = _make_ct()
        result_scalp = ct._get_min_edge(_candidate("BTC", "scalp"))
        result_15m = ct._get_min_edge(_candidate("BTC", "15m"))
        assert result_scalp == result_15m

    def test_legacy_alias_swing_to_daily(self):
        ct = _make_ct()
        result_swing = ct._get_min_edge(_candidate("ETH", "swing"))
        result_daily = ct._get_min_edge(_candidate("ETH", "daily"))
        assert result_swing == result_daily

    def test_unknown_timeframe_returns_global_fallback(self):
        ct = _make_ct()
        result = ct._get_min_edge(_candidate("BTC", "unknown"))
        assert result == ct._min_edge

    def test_empty_timeframe_returns_global_fallback(self):
        ct = _make_ct()
        result = ct._get_min_edge(_candidate("ETH", ""))
        assert result == ct._min_edge

    def test_all_canonical_timeframes_have_grid_entries(self):
        """Every canonical timeframe should resolve to a grid entry for BTC."""
        ct = _make_ct()
        from merid.trading.kalshi_continuous_trader import EDGE_THRESHOLDS
        for tf in ("15m", "1h", "daily", "weekly", "monthly"):
            result = ct._get_min_edge(_candidate("BTC", tf))
            expected = EDGE_THRESHOLDS.get(("BTC", tf), ct._min_edge)
            assert result == expected, f"BTC {tf}: expected {expected}, got {result}"

    def test_all_assets_all_timeframes_non_zero(self):
        """No (asset, timeframe) combination should return edge threshold of 0."""
        ct = _make_ct()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            for tf in ("15m", "1h", "daily", "weekly", "monthly"):
                result = ct._get_min_edge(_candidate(asset, tf))
                assert result > 0, f"{asset} {tf} returned zero min_edge"
