"""Tests for canonical Kalshi 15m crypto configuration."""

import pytest

# DEPRECATED: kalshi_15m_crypto_config.py removed - use profile YAML instead.
# Only the asset-universe contract survives, sourced from kalshi_universe.py;
# the entry/exit policy, volatility-tier, and risk-limit surfaces moved to the
# crypto_15m profile (see merid.risk.profiles tests).
from config.kalshi_universe import (
    KALSHI_15M_CRYPTO_ASSETS,
    KALSHI_15M_SERIES_TICKERS,
)
KALSHI_15M_TIMEFRAME = "15m"
ASSET_CLASS_MAJOR = ["BTC", "ETH"]
ASSET_CLASS_ALT = ["SOL", "XRP", "DOGE"]


class TestUniverseDefinition:
    """Tests for universe definition (Section 1)."""
    
    def test_15m_assets_complete(self):
        """All five expected assets are present."""
        assert set(KALSHI_15M_CRYPTO_ASSETS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    
    def test_15m_timeframe(self):
        """Timeframe is exactly 15m."""
        assert KALSHI_15M_TIMEFRAME == "15m"
    
    def test_series_tickers_complete(self):
        """All assets have series tickers."""
        for asset in KALSHI_15M_CRYPTO_ASSETS:
            assert asset in KALSHI_15M_SERIES_TICKERS
            assert KALSHI_15M_SERIES_TICKERS[asset].startswith("KX")
            assert "15M" in KALSHI_15M_SERIES_TICKERS[asset]
    
    def test_asset_class_grouping(self):
        """Asset classes are correctly grouped."""
        assert set(ASSET_CLASS_MAJOR) == {"BTC", "ETH"}
        assert set(ASSET_CLASS_ALT) == {"SOL", "XRP", "DOGE"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
