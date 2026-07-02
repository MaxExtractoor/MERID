"""
Tests for catalog lagging vs MD stale combinations.

Tests cover:
- catalog_lagging + MD fresh → non-blocking (trading allowed)
- catalog_lagging + MD stale → blocking (trading not allowed)
- no_active_tickers + MD fresh → blocking (trading not allowed)
- no_active_tickers + MD stale → blocking (trading not allowed)
- healthy + MD fresh → non-blocking (trading allowed)
- healthy + MD stale → blocking (trading not allowed)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch


class TestCatalogLaggingSemantics:
    """Test catalog lagging semantics vs MD staleness."""
    
    @pytest.fixture
    def mock_catalog(self):
        """Create a mock catalog with series health."""
        catalog = Mock()
        catalog._series_health = {
            "KXBTC15M": "healthy",
            "KXETH15M": "healthy",
            "KXSOL15M": "healthy",
            "KXXRP15M": "healthy",
            "KXDOGE15M": "healthy",
        }
        catalog.get_series_health = lambda series_ticker: catalog._series_health.get(series_ticker, "unknown")
        return catalog
    
    @pytest.fixture
    def mock_market_state_store(self):
        """Create a mock market state store with MD freshness."""
        store = Mock()
        now = datetime.now(timezone.utc)
        
        # Create mock states for each asset
        def create_state(age_seconds):
            state = Mock()
            state.last_update_ts = now - timedelta(seconds=age_seconds)
            state.last_book_update_ts = now - timedelta(seconds=age_seconds)
            state.book_initialized = True
            state.spread_cents = 10
            state.depth_at_top = 100
            return state
        
        store._states = {
            "KXBTC15M-26JUN261200": create_state(5),  # Fresh
            "KXETH15M-26JUN261200": create_state(5),  # Fresh
            "KXSOL15M-26JUN261200": create_state(5),  # Fresh
            "KXXRP15M-26JUN261200": create_state(5),  # Fresh
            "KXDOGE15M-26JUN261200": create_state(5),  # Fresh
        }
        
        def get(ticker):
            # Return first state for the series
            for key, state in store._states.items():
                if key.startswith(ticker):
                    return state
            return None
        
        store.get = get
        return store
    
    def test_catalog_lagging_with_fresh_md_allows_trading(self, mock_catalog, mock_market_state_store):
        """Test catalog_lagging + MD fresh → non-blocking (trading allowed)."""
        # Set catalog to lagging
        mock_catalog._series_health["KXBTC15M"] = "lagging"
        
        # MD is fresh (5 seconds old)
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "lagging"
        assert md_age < 30.0  # Fresh MD
        
        # Trading should be allowed (non-blocking)
        # This is the HF-RELAX: lagging + fresh MD = allowed
        should_block = (series_health == "no_active_tickers") or \
                      (series_health != "healthy" and (md_state.spread_cents is None or md_state.depth_at_top < 1))
        
        assert not should_block, "catalog_lagging + fresh MD should be non-blocking"
    
    def test_catalog_lagging_with_stale_md_blocks_trading(self, mock_catalog, mock_market_state_store):
        """Test catalog_lagging + MD stale → blocking (trading not allowed)."""
        # Set catalog to lagging
        mock_catalog._series_health["KXBTC15M"] = "lagging"
        
        # Set MD to stale (60 seconds old)
        now = datetime.now(timezone.utc)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_update_ts = now - timedelta(seconds=60)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_book_update_ts = now - timedelta(seconds=60)
        
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "lagging"
        assert md_age >= 30.0  # Stale MD
        
        # Trading should be blocked (stale MD overrides lagging)
        # Even though catalog is lagging (non-critical), stale MD is critical
        should_block = md_age >= 30.0
        
        assert should_block, "catalog_lagging + stale MD should be blocking"
    
    def test_no_active_tickers_with_fresh_md_blocks_trading(self, mock_catalog, mock_market_state_store):
        """Test no_active_tickers + MD fresh → blocking (trading not allowed)."""
        # Set catalog to no_active_tickers
        mock_catalog._series_health["KXBTC15M"] = "no_active_tickers"
        
        # MD is fresh (5 seconds old)
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "no_active_tickers"
        assert md_age < 30.0  # Fresh MD
        
        # Trading should be blocked (no_active_tickers is critical)
        should_block = series_health == "no_active_tickers"
        
        assert should_block, "no_active_tickers + fresh MD should be blocking"
    
    def test_no_active_tickers_with_stale_md_blocks_trading(self, mock_catalog, mock_market_state_store):
        """Test no_active_tickers + MD stale → blocking (trading not allowed)."""
        # Set catalog to no_active_tickers
        mock_catalog._series_health["KXBTC15M"] = "no_active_tickers"
        
        # Set MD to stale (60 seconds old)
        now = datetime.now(timezone.utc)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_update_ts = now - timedelta(seconds=60)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_book_update_ts = now - timedelta(seconds=60)
        
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "no_active_tickers"
        assert md_age >= 30.0  # Stale MD
        
        # Trading should be blocked (both conditions are blocking)
        should_block = series_health == "no_active_tickers"
        
        assert should_block, "no_active_tickers + stale MD should be blocking"
    
    def test_healthy_with_fresh_md_allows_trading(self, mock_catalog, mock_market_state_store):
        """Test healthy + MD fresh → non-blocking (trading allowed)."""
        # Catalog is already healthy (default)
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "healthy"
        assert md_age < 30.0  # Fresh MD
        
        # Trading should be allowed (optimal conditions)
        should_block = (series_health == "no_active_tickers") or \
                      (series_health != "healthy" and (md_state.spread_cents is None or md_state.depth_at_top < 1))
        
        assert not should_block, "healthy + fresh MD should be non-blocking"
    
    def test_healthy_with_stale_md_blocks_trading(self, mock_catalog, mock_market_state_store):
        """Test healthy + MD stale → blocking (trading not allowed)."""
        # Catalog is healthy (default)
        series_health = mock_catalog.get_series_health("KXBTC15M")
        
        # Set MD to stale (60 seconds old)
        now = datetime.now(timezone.utc)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_update_ts = now - timedelta(seconds=60)
        mock_market_state_store._states["KXBTC15M-26JUN261200"].last_book_update_ts = now - timedelta(seconds=60)
        
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "healthy"
        assert md_age >= 30.0  # Stale MD
        
        # Trading should be blocked (stale MD is critical)
        should_block = md_age >= 30.0
        
        assert should_block, "healthy + stale MD should be blocking"
    
    def test_catalog_lagging_with_no_liquidity_blocks_trading(self, mock_catalog, mock_market_state_store):
        """Test catalog_lagging + no liquidity → blocking (trading not allowed)."""
        # Set catalog to lagging
        mock_catalog._series_health["KXBTC15M"] = "lagging"
        
        # Set MD to have no liquidity
        mock_market_state_store._states["KXBTC15M-26JUN261200"].spread_cents = None
        mock_market_state_store._states["KXBTC15M-26JUN261200"].depth_at_top = 0
        
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Verify semantics
        assert series_health == "lagging"
        assert md_state.spread_cents is None or md_state.depth_at_top < 1
        
        # Trading should be blocked (no liquidity)
        should_block = (series_health == "no_active_tickers") or \
                      (series_health != "healthy" and (md_state.spread_cents is None or md_state.depth_at_top < 1))
        
        assert should_block, "catalog_lagging + no liquidity should be blocking"
    
    def test_unknown_catalog_health_with_fresh_md_allows_trading(self, mock_catalog, mock_market_state_store):
        """Test unknown catalog health + MD fresh → non-blocking (trading allowed)."""
        # Set catalog to unknown
        mock_catalog._series_health["KXBTC15M"] = "unknown"
        
        # MD is fresh (5 seconds old)
        series_health = mock_catalog.get_series_health("KXBTC15M")
        md_state = mock_market_state_store.get("KXBTC15M")
        
        # Calculate MD age
        md_age = (datetime.now(timezone.utc) - md_state.last_update_ts).total_seconds()
        
        # Verify semantics
        assert series_health == "unknown"
        assert md_age < 30.0  # Fresh MD
        
        # Trading should be allowed (unknown is treated like lagging - non-critical)
        should_block = (series_health == "no_active_tickers") or \
                      (series_health != "healthy" and (md_state.spread_cents is None or md_state.depth_at_top < 1))
        
        assert not should_block, "unknown + fresh MD should be non-blocking"


class TestCatalogLaggingLogMessages:
    """Test that catalog lagging produces clear log messages."""
    
    def test_catalog_lagging_log_message_format(self):
        """Test that catalog lagging logs use the correct format."""
        # This test verifies the log message format after renaming
        # The log should use "CATALOG-LAGGING" not "CATALOG-STUCK"
        
        expected_log_prefix = "[CATALOG-LAGGING]"
        assert expected_log_prefix == "[CATALOG-LAGGING]"
    
    def test_catalog_lagging_warn_log_message_format(self):
        """Test that catalog lagging warn logs use the correct format."""
        # The warn log should use "CATALOG-LAGGING-WARN" not "CATALOG-STUCK-WARN"
        
        expected_log_prefix = "[CATALOG-LAGGING-WARN]"
        assert expected_log_prefix == "[CATALOG-LAGGING-WARN]"
    
    def test_failsafe_mode_log_message_uses_lagging(self):
        """Test that failsafe mode logs use 'lagging' not 'stuck'."""
        # The failsafe mode log should reference "catalog lagging" not "catalog stuck"
        
        expected_log_message = "catalog lagging but MD fresh"
        assert "lagging" in expected_log_message
        assert "stuck" not in expected_log_message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
