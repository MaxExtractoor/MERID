"""Tests for market/assertion_source.py."""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from market.assertion_source import (
    MarketAssertion, MarketAssertionSource, get_market_assertion_source, _market_source
)


class TestMarketAssertion:
    """Test MarketAssertion dataclass."""

    def test_creation(self):
        """Test MarketAssertion creation."""
        assertion = MarketAssertion(
            symbol="BTC/USD",
            price=50000.0,
            volume=1000000.0,
            timestamp=1234567890.0,
            source="coinbase",
            confidence=0.9
        )
        assert assertion.symbol == "BTC/USD"
        assert assertion.price == 50000.0
        assert assertion.volume == 1000000.0
        assert assertion.confidence == 0.9

    def test_default_confidence(self):
        """Test MarketAssertion with default confidence."""
        assertion = MarketAssertion(
            symbol="ETH/USD",
            price=3000.0,
            volume=500000.0,
            timestamp=1234567890.0,
            source="kraken"
        )
        assert assertion.confidence == 0.8


class TestMarketAssertionSourceInitialization:
    """Test MarketAssertionSource initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source = MarketAssertionSource()
            
            assert source.last_assertion_time == 0.0
            assert source.assertion_interval == 60.0
            assert source.market_data_cache == {}


class TestMarketAssertionSourceUpdateMarketData:
    """Test update_market_data method."""

    def test_update_caches_data(self):
        """Test that update_market_data caches the data."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source = MarketAssertionSource()
            
            source.update_market_data("BTC/USD", 50000.0, 1000000.0, "coinbase")
            
            assert "BTC/USD" in source.market_data_cache
            assert source.market_data_cache["BTC/USD"].price == 50000.0
            assert source.market_data_cache["BTC/USD"].volume == 1000000.0

    def test_update_triggers_assertion_after_interval(self):
        """Test that assertion is registered after interval."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source = MarketAssertionSource()
            source.last_assertion_time = 0  # Force immediate trigger
            
            with patch.object(source, '_register_market_assertion') as mock_register:
                source.update_market_data("BTC/USD", 50000.0, 1000000.0, "coinbase")
                
                # Since time.time() - 0 >= 60, it should trigger
                mock_register.assert_called_once_with("BTC/USD")


class TestMarketAssertionSourceRegisterBatch:
    """Test register_batch_market_data method."""

    def test_register_batch(self):
        """Test batch registration."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source = MarketAssertionSource()
            
            market_data_list = [
                {"symbol": "BTC/USD", "price": 50000.0, "volume": 1000000.0, "source": "demo"},
                {"symbol": "ETH/USD", "price": 3000.0, "volume": 500000.0, "source": "demo"}
            ]
            
            with patch.object(source, '_register_market_assertion') as mock_register:
                source.register_batch_market_data(market_data_list)
                
                assert "BTC/USD" in source.market_data_cache
                assert "ETH/USD" in source.market_data_cache
                # Demo source should trigger immediate registration
                assert mock_register.call_count == 2

    def test_register_batch_non_demo(self):
        """Test batch registration with non-demo source."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source = MarketAssertionSource()
            
            market_data_list = [
                {"symbol": "BTC/USD", "price": 50000.0, "volume": 1000000.0, "source": "live"}
            ]
            
            with patch.object(source, 'update_market_data') as mock_update:
                source.register_batch_market_data(market_data_list)
                
                mock_update.assert_called_once_with("BTC/USD", 50000.0, 1000000.0, "live")


class TestMarketAssertionSourceGetMarketAssertions:
    """Test get_market_assertions method."""

    def test_get_assertions_empty(self):
        """Test getting assertions when none exist."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            mock_registry.return_value.get_assertions_by_domain.return_value = []
            
            source = MarketAssertionSource()
            assertions = source.get_market_assertions()
            
            assert assertions == []

    def test_get_assertions_with_data(self):
        """Test getting assertions with data."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
                # Create mock assertion
                mock_assertion = Mock()
                mock_assertion.assertion_id = "test_id"
                mock_assertion.description = "Market data for BTC/USD: price=$50000, volume=1000000"
                mock_assertion.confidence_score = 0.8
                mock_assertion.provenance_score = 0.7
                mock_assertion.status.value = "active"
                mock_assertion.created_at = 1234567890.0
                mock_assertion.effective_confidence.return_value = 0.75
                mock_assertion.is_usable.return_value = True
                
                mock_registry.return_value.get_assertions_by_domain.return_value = [mock_assertion]
                mock_auditor.return_value.regime_entropy = 0.5
                
                source = MarketAssertionSource()
                assertions = source.get_market_assertions()
                
                assert len(assertions) == 1
                assert assertions[0]["assertion_id"] == "test_id"
                assert assertions[0]["symbol"] == "Market data for BTC/USD"


class TestGetMarketAssertionSource:
    """Test get_market_assertion_source function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _market_source
        import market.assertion_source as mas
        mas._market_source = None

    def test_singleton(self):
        """Test get_market_assertion_source returns singleton."""
        with patch('market.assertion_source.get_reality_registry') as mock_registry:
            mock_registry.return_value = Mock()
            source1 = get_market_assertion_source()
            source2 = get_market_assertion_source()
            
            assert source1 is source2
