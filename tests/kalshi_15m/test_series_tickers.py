import pytest
from merid.prediction.agent_grid_config import load_agent_grid_config
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_agent_grid_catalog_series_tickers, kalshi_ct_default_series_tickers
from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS


@pytest.mark.kalshi_15m
class TestSeriesTickers:
    """Test that 15m agents use correct 15M series tickers."""

    def test_agent_grid_15m_series_tickers(self):
        """Verify that 15m agents exist in agent grid."""
        config = load_agent_grid_config()
        btc_agent = next((a for a in config.agents if a.name == "BTC_15M"), None)
        assert btc_agent is not None, "BTC_15M agent not found in agent grid"
        
        eth_agent = next((a for a in config.agents if a.name == "ETH_15M"), None)
        assert eth_agent is not None, "ETH_15M agent not found in agent grid"
        
        sol_agent = next((a for a in config.agents if a.name == "SOL_15M"), None)
        assert sol_agent is not None, "SOL_15M agent not found in agent grid"
        
        xrp_agent = next((a for a in config.agents if a.name == "XRP_15M"), None)
        assert xrp_agent is not None, "XRP_15M agent not found in agent grid"
        
        doge_agent = next((a for a in config.agents if a.name == "DOGE_15M"), None)
        assert doge_agent is not None, "DOGE_15M agent not found in agent grid"

    def test_kalshi_universe_15m_products(self):
        """Verify that KALSHI_CRYPTO_PRODUCTS uses 15M tickers for 15m timeframe."""
        # Check that BTC_15M uses KXBTC15M
        btc_15m = KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", {})
        if btc_15m:
            assert "KXBTC15M" in btc_15m, "BTC_15M should use KXBTC15M ticker"
        
        # Check that ETH_15M uses KXETH15M
        eth_15m = KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", {})
        if eth_15m:
            assert "KXETH15M" in eth_15m, "ETH_15M should use KXETH15M ticker"

    def test_catalog_series_tickers(self):
        """Verify that kalshi_agent_grid_catalog_series_tickers returns 15M tickers."""
        series_tickers = kalshi_agent_grid_catalog_series_tickers()
        assert "KXBTC15M" in series_tickers, "KXBTC15M should be in catalog series tickers"
        assert "KXETH15M" in series_tickers, "KXETH15M should be in catalog series tickers"

    def test_kalshi_ct_default_series_tickers(self):
        """Verify that kalshi_ct_default_series_tickers returns 15M tickers."""
        series_tickers = kalshi_ct_default_series_tickers()
        # Should include 15M tickers
        assert any("15M" in ticker for ticker in series_tickers), "Should include 15M series tickers"

    def test_kalshi_15m_series_tickers_config(self):
        """Verify that KALSHI_15M_SERIES_TICKERS is defined."""
        assert KALSHI_15M_SERIES_TICKERS is not None, "KALSHI_15M_SERIES_TICKERS should be defined"
        assert len(KALSHI_15M_SERIES_TICKERS) > 0, "KALSHI_15M_SERIES_TICKERS should not be empty"

    def test_kalshi_agent_grid_catalog_series_tickers(self):
        """Verify that kalshi_agent_grid_catalog_series_tickers() returns 15M tickers."""
        catalog_tickers = kalshi_agent_grid_catalog_series_tickers()
        assert "KXBTC15M" in catalog_tickers
        assert "KXETH15M" in catalog_tickers
        assert "KXSOL15M" in catalog_tickers
        assert "KXXRP15M" in catalog_tickers
        assert "KXDOGE15M" in catalog_tickers

    def test_kalshi_ct_default_series_tickers_detailed(self):
        """Verify that KalshiContinuousTrader default series tickers are 15M."""
        ct_tickers = kalshi_ct_default_series_tickers()
        assert "KXBTC15M" in ct_tickers
        assert "KXETH15M" in ct_tickers
        assert "KXSOL15M" in ct_tickers
        assert "KXXRP15M" in ct_tickers
        assert "KXDOGE15M" in ct_tickers

    def test_series_ticker_consistency(self):
        """Verify that all series ticker sources are consistent."""
        # All sources should agree on the 15M series tickers
        from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
        from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
        
        catalog_tickers = kalshi_agent_grid_catalog_series_tickers()
        config_tickers = list(KALSHI_15M_SERIES_TICKERS.values())
        
        for ticker in config_tickers:
            assert ticker in catalog_tickers, f"{ticker} from config not in catalog tickers"
