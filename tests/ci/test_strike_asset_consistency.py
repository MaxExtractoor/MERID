"""CI Test: Strike Asset Consistency

P0-002 Audit CI Test — Validates that asset-in-ticker validation works correctly
and prevents cross-asset mispairing (e.g., BTC spot used for ETH market).

Run: pytest tests/ci/test_strike_asset_consistency.py -v
"""
from __future__ import annotations

import pytest

from merid.prediction.kalshi_strike_selector import asset_in_ticker, RejectionReason
from config.kalshi_crypto_series_meta import SERIES_META_BY_TICKER


class TestAssetInTicker:
    """Validate asset_in_ticker() function."""

    def test_valid_btc_ticker(self) -> None:
        """BTC spot with BTC ticker should pass."""
        assert asset_in_ticker("KXBTC15M-27APR-T101500", "BTC") is True
        assert asset_in_ticker("KXBTCD1-T85000", "BTC") is True

    def test_valid_eth_ticker(self) -> None:
        """ETH spot with ETH ticker should pass."""
        assert asset_in_ticker("KXETH15M-27APR-T3500", "ETH") is True
        assert asset_in_ticker("KXETHD1-T4000", "ETH") is True

    def test_valid_sol_ticker(self) -> None:
        """SOL spot with SOL ticker should pass."""
        assert asset_in_ticker("KXSOL15M-27APR-T150", "SOL") is True

    def test_valid_xrp_ticker(self) -> None:
        """XRP spot with XRP ticker should pass."""
        assert asset_in_ticker("KXXRP15M-27APR-T2", "XRP") is True

    def test_valid_doge_ticker(self) -> None:
        """DOGE spot with DOGE ticker should pass."""
        assert asset_in_ticker("KXDOGE15M-27APR-T0.20", "DOGE") is True

    def test_cross_asset_mismatch_btc_eth(self) -> None:
        """BTC spot with ETH ticker should fail (cross-asset mispairing)."""
        assert asset_in_ticker("KXETH15M-27APR-T3500", "BTC") is False

    def test_cross_asset_mismatch_eth_btc(self) -> None:
        """ETH spot with BTC ticker should fail (cross-asset mispairing)."""
        assert asset_in_ticker("KXBTC15M-27APR-T101500", "ETH") is False

    def test_cross_asset_mismatch_sol_xrp(self) -> None:
        """SOL spot with XRP ticker should fail."""
        assert asset_in_ticker("KXXRP15M-27APR-T2", "SOL") is False

    def test_empty_ticker(self) -> None:
        """Empty ticker should fail."""
        assert asset_in_ticker("", "BTC") is False

    def test_empty_asset(self) -> None:
        """Empty asset should fail."""
        assert asset_in_ticker("KXBTC15M-27APR-T101500", "") is False

    def test_none_ticker(self) -> None:
        """None ticker should fail."""
        assert asset_in_ticker(None, "BTC") is False  # type: ignore[arg-type]

    def test_none_asset(self) -> None:
        """None asset should fail."""
        assert asset_in_ticker("KXBTC15M-27APR-T101500", None) is False  # type: ignore[arg-type]

    def test_case_insensitive(self) -> None:
        """Asset matching should be case-insensitive."""
        assert asset_in_ticker("KXBTC15M-27APR-T101500", "btc") is True
        assert asset_in_ticker("KXBTC15M-27APR-T101500", "BtC") is True


class TestStrikeSelectorIntegration:
    """Validate strike selector integration with asset validation."""

    def test_selector_rejects_cross_asset(self) -> None:
        """Strike selector must reject cross-asset pairing."""
        from merid.prediction.kalshi_strike_selector import KalshiStrikeSelector

        selector = KalshiStrikeSelector()

        # Try to evaluate BTC market with ETH asset (cross-asset mispairing)
        result = selector.evaluate(
            ticker="KXBTC15M-27APR-T101500",
            asset="ETH",  # Wrong asset!
            timeframe="15m",
            spot=70000.0,
            strike=101500.0,
        )

        assert not result.accepted, "Should reject cross-asset pairing"
        assert result.rejection_reason == RejectionReason.ASSET_TICKER_MISMATCH, \
            f"Expected ASSET_TICKER_MISMATCH, got {result.rejection_reason}"

    def test_selector_accepts_matching_asset(self) -> None:
        """Strike selector must accept matching asset."""
        from merid.prediction.kalshi_strike_selector import KalshiStrikeSelector

        selector = KalshiStrikeSelector()

        # Correct asset for BTC market (BTC 15m max distance is 5%)
        # spot=70000, strike=72000 = ~2.9% distance (within 5% threshold)
        result = selector.evaluate(
            ticker="KXBTC15M-27APR-T72000",
            asset="BTC",
            timeframe="15m",
            spot=70000.0,
            strike=72000.0,  # ~2.9% distance, within 5% for BTC 15m
        )

        # Should be accepted (within max distance for BTC 15m)
        assert result.accepted, f"Should accept valid BTC market, got: {result.rejection_reason}"


class TestStrikeAssetMismatchMetric:
    """Validate STRIKE_ASSET_MISMATCH metric registration."""

    def test_metric_exists(self) -> None:
        """merid_pm_strike_asset_mismatch_total counter must be registered."""
        from monitoring.metrics import get_metrics_registry

        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_pm_strike_asset_mismatch_total")
        assert counter is not None, "merid_pm_strike_asset_mismatch_total counter not found"

        # Verify labels
        assert "asset" in counter.label_names, "Missing 'asset' label"
        assert "ticker" in counter.label_names, "Missing 'ticker' label"
        assert "inferred_asset" in counter.label_names, "Missing 'inferred_asset' label"

    def test_metric_incremented_on_mismatch(self) -> None:
        """Metric must increment when cross-asset mispairing detected."""
        from monitoring.metrics import get_metrics_registry

        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_pm_strike_asset_mismatch_total")
        assert counter is not None

        # Get initial value
        initial = counter.get(labels={"asset": "BTC", "ticker": "KXETH15M-27APR-T3500", "inferred_asset": "ETH"})

        # Trigger a mismatch
        asset_in_ticker("KXETH15M-27APR-T3500", "BTC")

        # Get new value
        new = counter.get(labels={"asset": "BTC", "ticker": "KXETH15M-27APR-T3500", "inferred_asset": "ETH"})

        assert new == initial + 1, f"Counter should increment, {new} != {initial + 1}"


class TestAllSeriesTickersHaveAssets:
    """Validate all series tickers in meta have resolvable assets."""

    def test_all_series_meta_have_assets(self) -> None:
        """All SERIES_META_LIST entries must have valid assets."""
        for meta in SERIES_META_BY_TICKER.values():
            assert meta.asset is not None, f"Missing asset for {meta.series_ticker}"
            assert len(meta.asset) > 0, f"Empty asset for {meta.series_ticker}"
            assert meta.asset.isupper(), f"Asset not uppercase: {meta.asset}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
