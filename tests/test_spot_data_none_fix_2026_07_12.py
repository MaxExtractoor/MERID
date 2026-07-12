"""
Test for spot_data=None fix (2026-07-12).

Root cause: agent_grid_15m.py calls spot_provider.get(asset) synchronously,
but UnifiedSpotProvider only had async get_spot() method.

Fix: Added synchronous get() method to UnifiedSpotProvider that wraps
UnifiedSpotService.get() and returns SpotSnapshot with OHLC data.
"""
import pytest
from unittest.mock import Mock, patch
import time


class TestSpotDataNoneFix:
    """Test that UnifiedSpotProvider.get() returns spot data with OHLC."""

    def test_unified_spot_provider_has_get_method(self):
        """Test that UnifiedSpotProvider has a synchronous get() method."""
        from merid.prediction.spot_provider import UnifiedSpotProvider

        provider = UnifiedSpotProvider()
        assert hasattr(provider, 'get'), "UnifiedSpotProvider must have get() method"
        assert callable(provider.get), "get() must be callable"

    def test_unified_spot_provider_get_returns_spot_snapshot(self):
        """Test that get() returns SpotSnapshot with OHLC data."""
        from merid.prediction.spot_provider import UnifiedSpotProvider
        from data.unified_spot_service import SpotPrice

        # Mock the unified spot service
        mock_spot = SpotPrice(
            price=85000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase",
            open=84800.0,
            high=85200.0,
            low=84700.0,
            volume=1000.0
        )

        with patch('data.unified_spot_service.get_unified_spot_service') as mock_get_service:
            mock_service = Mock()
            mock_service.get.return_value = mock_spot
            mock_get_service.return_value = mock_service

            provider = UnifiedSpotProvider()
            result = provider.get("BTC")

            assert result is not None, "get() should return SpotSnapshot"
            assert result.asset == "BTC"
            assert result.price_usd == 85000.0
            assert result.price == 85000.0, "price property should alias price_usd"
            assert result.open == 84800.0, "OHLC open should be preserved"
            assert result.high == 85200.0, "OHLC high should be preserved"
            assert result.low == 84700.0, "OHLC low should be preserved"
            assert result.source == "unified_spot"

    def test_unified_spot_provider_get_handles_spot_error(self):
        """Test that get() returns None on SpotError."""
        from merid.prediction.spot_provider import UnifiedSpotProvider
        from data.unified_spot_service import SpotError

        mock_error = SpotError(
            reason="stale",
            asset="BTC",
            age_s=120,
            message="Spot data age 120s exceeds threshold"
        )

        with patch('data.unified_spot_service.get_unified_spot_service') as mock_get_service:
            mock_service = Mock()
            mock_service.get.return_value = mock_error
            mock_get_service.return_value = mock_service

            provider = UnifiedSpotProvider()
            result = provider.get("BTC")

            assert result is None, "get() should return None on SpotError"

    def test_unified_spot_provider_get_handles_none(self):
        """Test that get() returns None when service returns None."""
        from merid.prediction.spot_provider import UnifiedSpotProvider

        with patch('data.unified_spot_service.get_unified_spot_service') as mock_get_service:
            mock_service = Mock()
            mock_service.get.return_value = None
            mock_get_service.return_value = mock_service

            provider = UnifiedSpotProvider()
            result = provider.get("BTC")

            assert result is None, "get() should return None when service returns None"

    def test_spot_snapshot_price_property(self):
        """Test that SpotSnapshot.price property aliases price_usd."""
        from merid.prediction.spot_provider import SpotSnapshot

        snapshot = SpotSnapshot(
            asset="BTC",
            price_usd=85000.0,
            timestamp_ms=1234567890,
            source="unified_spot",
            open=84800.0,
            high=85200.0,
            low=84700.0
        )

        assert snapshot.price == 85000.0, "price property should equal price_usd"
        assert snapshot.price == snapshot.price_usd

    def test_all_5_assets_supported(self):
        """Test that get() works for all 5 crypto assets."""
        from merid.prediction.spot_provider import UnifiedSpotProvider
        from data.unified_spot_service import SpotPrice

        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        with patch('data.unified_spot_service.get_unified_spot_service') as mock_get_service:
            mock_service = Mock()
            mock_get_service.return_value = mock_service

            provider = UnifiedSpotProvider()

            for asset in assets:
                mock_spot = SpotPrice(
                    price=100.0,
                    timestamp=int(time.time() * 1000),
                    source="coinbase",
                    open=99.0,
                    high=101.0,
                    low=98.0
                )
                mock_service.get.return_value = mock_spot

                result = provider.get(asset)
                assert result is not None, f"get() should return data for {asset}"
                assert result.asset == asset, f"Asset should be {asset}"
                assert result.price == 100.0, f"Price should be set for {asset}"

    @pytest.mark.asyncio
    async def test_get_spot_async_wrapper(self):
        """Test that async get_spot() wraps synchronous get()."""
        from merid.prediction.spot_provider import UnifiedSpotProvider
        from data.unified_spot_service import SpotPrice

        mock_spot = SpotPrice(
            price=85000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase",
            open=84800.0,
            high=85200.0,
            low=84700.0
        )

        with patch('data.unified_spot_service.get_unified_spot_service') as mock_get_service:
            mock_service = Mock()
            mock_service.get.return_value = mock_spot
            mock_get_service.return_value = mock_service

            provider = UnifiedSpotProvider()
            result = await provider.get_spot("BTC")

            assert result is not None, "get_spot() should return SpotSnapshot"
            assert result.price == 85000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
