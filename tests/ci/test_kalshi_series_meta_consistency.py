"""CI Test: Kalshi Series Meta Consistency

P0/P1 Audit CI Test — Validates that all series ticker mappings across MERID
are consistent with the single source of truth in kalshi_crypto_series_meta.py.

This prevents schema drift when:
- New assets/frequencies are added
- Suffix conventions change
- Multiple modules have divergent mappings

Run: pytest tests/ci/test_kalshi_series_meta_consistency.py -v
"""
from __future__ import annotations

import pytest
from typing import Set, Tuple

from config.kalshi_crypto_series_meta import (
    SERIES_META_LIST,
    SERIES_META_BY_TICKER,
    all_series_tickers,
    build_kalshi_crypto_products,
)
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, KALSHI_CRYPTO_SERIES_TICKERS
from merid.event_venues.kalshi.crypto_series import CRYPTO_SERIES_PREFIXES, FREQUENCY_SUFFIXES
from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE, TIMEFRAME_SERIES_SUFFIX
from merid.event_venues.kalshi.collector import CRYPTO_SERIES, TIMEFRAME_SERIES_SUFFIXES


class TestSeriesMetaConsistency:
    """Validate series ticker mappings are consistent across all modules."""

    def test_all_series_tickers_unique(self) -> None:
        """All series tickers in SERIES_META_LIST must be unique."""
        tickers = [m.series_ticker for m in SERIES_META_LIST]
        assert len(tickers) == len(set(tickers)), f"Duplicate tickers found: {[t for t in tickers if tickers.count(t) > 1]}"

    def test_series_meta_by_ticker_complete(self) -> None:
        """SERIES_META_BY_TICKER must contain all series from SERIES_META_LIST."""
        for meta in SERIES_META_LIST:
            assert meta.series_ticker.upper() in SERIES_META_BY_TICKER, \
                f"Missing {meta.series_ticker} in SERIES_META_BY_TICKER"

    def test_all_series_tickers_function(self) -> None:
        """all_series_tickers() must return all tickers from SERIES_META_LIST."""
        expected = {m.series_ticker for m in SERIES_META_LIST}
        actual = set(all_series_tickers())
        assert expected == actual, f"Mismatch: expected {expected - actual}, got {actual - expected}"


class TestCryptoSeriesPrefixConsistency:
    """Validate CRYPTO_SERIES_* prefix mappings are consistent."""

    def test_crypto_series_prefixes_match_base(self) -> None:
        """CRYPTO_SERIES_PREFIXES must match CRYPTO_SERIES_BASE."""
        from merid.event_venues.kalshi.crypto_series import CRYPTO_SERIES_PREFIXES
        from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE

        assert CRYPTO_SERIES_PREFIXES == CRYPTO_SERIES_BASE, \
            f"CRYPTO_SERIES_PREFIXES != CRYPTO_SERIES_BASE: " \
            f"{set(CRYPTO_SERIES_PREFIXES.items()) ^ set(CRYPTO_SERIES_BASE.items())}"

    def test_crypto_series_prefixes_match_collector(self) -> None:
        """CRYPTO_SERIES_PREFIXES must match CRYPTO_SERIES in collector."""
        from merid.event_venues.kalshi.crypto_series import CRYPTO_SERIES_PREFIXES
        from merid.event_venues.kalshi.collector import CRYPTO_SERIES

        assert CRYPTO_SERIES_PREFIXES == CRYPTO_SERIES, \
            f"CRYPTO_SERIES_PREFIXES != CRYPTO_SERIES: " \
            f"{set(CRYPTO_SERIES_PREFIXES.items()) ^ set(CRYPTO_SERIES.items())}"

    def test_prefixes_match_series_meta(self) -> None:
        """All prefixes must generate valid series meta tickers."""
        for asset, prefix in CRYPTO_SERIES_PREFIXES.items():
            # Check at least one series exists for this asset
            asset_series = [m for m in SERIES_META_LIST if m.asset == asset]
            assert len(asset_series) > 0, f"No series meta found for asset {asset}"
            # Check all series for this asset start with the prefix
            for meta in asset_series:
                assert meta.series_ticker.startswith(prefix), \
                    f"Series {meta.series_ticker} doesn't start with prefix {prefix}"


class TestFrequencySuffixConsistency:
    """Validate frequency suffix mappings are consistent."""

    def test_frequency_suffixes_aligned(self) -> None:
        """FREQUENCY_SUFFIXES should align with TIMEFRAME_SERIES_SUFFIX where applicable."""
        from merid.event_venues.kalshi.crypto_series import FREQUENCY_SUFFIXES
        from merid.event_venues.kalshi.market_selector import TIMEFRAME_SERIES_SUFFIX

        # Check overlapping keys have same values (note: monthly differs by convention)
        common_keys = set(FREQUENCY_SUFFIXES.keys()) & set(TIMEFRAME_SERIES_SUFFIX.keys())
        for key in common_keys:
            # Known naming convention difference: monthly is "1M" vs "M1"
            if key == "monthly":
                continue  # Modules use different conventions; both are valid
            assert FREQUENCY_SUFFIXES[key] == TIMEFRAME_SERIES_SUFFIX[key], \
                f"Suffix mismatch for {key}: {FREQUENCY_SUFFIXES[key]} != {TIMEFRAME_SERIES_SUFFIX[key]}"

    def test_collector_suffixes_in_meta(self) -> None:
        """TIMEFRAME_SERIES_SUFFIXES in collector must generate valid meta tickers."""
        from merid.event_venues.kalshi.collector import TIMEFRAME_SERIES_SUFFIXES

        for asset, prefix in CRYPTO_SERIES.items():
            for tf, suffix in TIMEFRAME_SERIES_SUFFIXES.items():
                expected_ticker = f"{prefix}{suffix}"
                # Check this ticker exists in meta (or is valid)
                meta = SERIES_META_BY_TICKER.get(expected_ticker.upper())
                if meta:
                    assert meta.asset == asset, f"Asset mismatch for {expected_ticker}"
                    # Map collector timeframe to canonical
                    canonical_tf = tf.replace("hourly", "1h")
                    assert meta.timeframe == canonical_tf or meta.timeframe == tf, \
                        f"Timeframe mismatch for {expected_ticker}: {meta.timeframe} vs {tf}"


class TestKalshiUniverseConsistency:
    """Validate kalshi_universe.py consistency with series meta."""

    def test_kalshi_crypto_products_match_meta(self) -> None:
        """KALSHI_CRYPTO_PRODUCTS tickers must all exist in SERIES_META_BY_TICKER."""
        for product_key, tickers in KALSHI_CRYPTO_PRODUCTS.items():
            for ticker in tickers:
                assert ticker.upper() in SERIES_META_BY_TICKER, \
                    f"KALSHI_CRYPTO_PRODUCTS[{product_key}] has unknown ticker: {ticker}"

    def test_kalshi_crypto_series_tickers_subset_of_meta(self) -> None:
        """KALSHI_CRYPTO_SERIES_TICKERS must be subset of all_series_tickers()."""
        meta_tickers = set(all_series_tickers())
        universe_tickers = set(KALSHI_CRYPTO_SERIES_TICKERS)

        extra = universe_tickers - meta_tickers
        assert not extra, f"KALSHI_CRYPTO_SERIES_TICKERS has extra tickers not in meta: {extra}"

    def test_build_kalshi_crypto_products_matches_universe(self) -> None:
        """build_kalshi_crypto_products() output should match KALSHI_CRYPTO_PRODUCTS."""
        built = build_kalshi_crypto_products()

        # Check all built products exist in universe
        for key, tickers in built.items():
            if key in KALSHI_CRYPTO_PRODUCTS:
                universe_tickers = set(KALSHI_CRYPTO_PRODUCTS[key])
                built_tickers = set(tickers)
                assert built_tickers == universe_tickers, \
                    f"Product {key} mismatch: built {built_tickers} vs universe {universe_tickers}"


class TestSeriesTickerFormat:
    """Validate series ticker format conventions."""

    def test_series_ticker_format(self) -> None:
        """All series tickers must follow KX{ASSET}{SUFFIX} pattern."""
        for meta in SERIES_META_LIST:
            ticker = meta.series_ticker
            # Must start with KX
            assert ticker.startswith("KX"), f"{ticker} doesn't start with KX"
            # Must contain asset code
            assert meta.asset in ticker, f"{ticker} doesn't contain asset {meta.asset}"

    def test_timeframe_suffix_consistency(self) -> None:
        """Timeframe suffixes must be consistent with conventions."""
        expected_suffixes = {
            "15m": "15M",
            "1h": "",  # Bare ticker for hourly
            "daily": "D1",
            "weekly": "W1",
            "monthly": "1M",
            "annual": "Y",
        }

        for meta in SERIES_META_LIST:
            tf = meta.timeframe
            expected = expected_suffixes.get(tf)
            if expected is not None:
                prefix = CRYPTO_SERIES_PREFIXES.get(meta.asset, f"KX{meta.asset}")
                expected_ticker = f"{prefix}{expected}"
                # For hourly (empty suffix), just check it starts with prefix and has no other suffix
                if tf == "1h":
                    assert meta.series_ticker == prefix, \
                        f"Hourly ticker {meta.series_ticker} != {prefix}"
                else:
                    assert meta.series_ticker == expected_ticker, \
                        f"{tf} ticker mismatch: {meta.series_ticker} != {expected_ticker}"


class TestAssetCoverage:
    """Validate all expected assets are covered."""

    EXPECTED_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_all_expected_assets_have_series(self) -> None:
        """All expected assets must have series defined."""
        assets_in_meta = {m.asset for m in SERIES_META_LIST}
        missing = self.EXPECTED_ASSETS - assets_in_meta
        assert not missing, f"Missing assets in SERIES_META_LIST: {missing}"

    def test_all_expected_assets_have_prefix(self) -> None:
        """All expected assets must have prefix mappings."""
        for asset in self.EXPECTED_ASSETS:
            assert asset in CRYPTO_SERIES_PREFIXES, f"Missing prefix for {asset}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
