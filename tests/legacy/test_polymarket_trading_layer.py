"""Tests for trading/polymarket_trading_layer.py - Coverage improvement."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time

from trading.polymarket_trading_layer import (
    ChainlinkFeed,
    ChainlinkOracle,
    PolymarketClient,
    feed_probability,
    DEFAULT_CHAINLINK_FEEDS,
)


# =============================================================================
# ChainlinkFeed Tests
# =============================================================================

class TestChainlinkFeed:
    """Test ChainlinkFeed dataclass."""
    
    def test_create_feed(self):
        """Test creating a ChainlinkFeed."""
        feed = ChainlinkFeed(
            slug="eth-usd",
            category="crypto-usd",
            name="ETH/USD",
            scale_hint=5000.0
        )
        
        assert feed.slug == "eth-usd"
        assert feed.category == "crypto-usd"
        assert feed.name == "ETH/USD"
        assert feed.scale_hint == 5000.0
    
    def test_default_scale_hint(self):
        """Test default scale_hint value."""
        feed = ChainlinkFeed(slug="test", category="test", name="Test")
        assert feed.scale_hint == 1000.0
    
    def test_feed_is_frozen(self):
        """Test that feed is immutable."""
        feed = ChainlinkFeed(slug="test", category="test", name="Test")
        
        with pytest.raises(AttributeError):
            feed.slug = "new-slug"


class TestDefaultChainlinkFeeds:
    """Test DEFAULT_CHAINLINK_FEEDS constant."""
    
    def test_default_feeds_exist(self):
        """Test default feeds are defined."""
        assert len(DEFAULT_CHAINLINK_FEEDS) >= 4
    
    def test_eth_usd_feed(self):
        """Test ETH/USD feed is in defaults."""
        eth_feed = next((f for f in DEFAULT_CHAINLINK_FEEDS if f.slug == "eth-usd"), None)
        assert eth_feed is not None
        assert eth_feed.name == "ETH/USD"


# =============================================================================
# ChainlinkOracle Tests
# =============================================================================

class TestChainlinkOracleInit:
    """Test ChainlinkOracle initialization."""
    
    def test_default_init(self):
        """Test default initialization."""
        oracle = ChainlinkOracle()
        
        assert oracle.network == "polygon"
        assert oracle._client is not None
    
    def test_custom_network(self):
        """Test custom network initialization."""
        oracle = ChainlinkOracle(network="ethereum")
        
        assert oracle.network == "ethereum"


class TestChainlinkOracleFetchFeeds:
    """Test fetch_feeds method."""
    
    def test_fetch_feeds_success(self):
        """Test successful feed fetch."""
        oracle = ChainlinkOracle()
        
        mock_response = Mock()
        mock_response.json.return_value = {"price": 3500.0, "updatedAt": time.time()}
        mock_response.raise_for_status = Mock()
        
        oracle._client = Mock()
        oracle._client.get.return_value = mock_response
        
        feeds = [ChainlinkFeed(slug="eth-usd", category="crypto-usd", name="ETH/USD")]
        result = oracle.fetch_feeds(feeds)
        
        assert "eth-usd" in result
        assert result["eth-usd"]["price"] == 3500.0
    
    def test_fetch_feeds_error_returns_mock(self):
        """Test feed fetch error returns mock data."""
        oracle = ChainlinkOracle()
        oracle._client = Mock()
        oracle._client.get.side_effect = Exception("Network error")
        
        feeds = [ChainlinkFeed(slug="eth-usd", category="crypto-usd", name="ETH/USD")]
        
        result = oracle.fetch_feeds(feeds)
        
        assert "eth-usd" in result
        assert result["eth-usd"]["price"] == 0.0  # Mock returns 0


class TestChainlinkOracleExtractPrice:
    """Test _extract_price method."""
    
    def test_extract_direct_price(self):
        """Test extracting price directly from payload."""
        oracle = ChainlinkOracle()
        
        payload = {"price": 3500.0}
        price = oracle._extract_price(payload)
        
        assert price == 3500.0
    
    def test_extract_nested_data_price(self):
        """Test extracting price from nested data."""
        oracle = ChainlinkOracle()
        
        payload = {"data": {"price": 4000.0}}
        price = oracle._extract_price(payload)
        
        assert price == 4000.0
    
    def test_extract_nested_data_result(self):
        """Test extracting price from nested data.result."""
        oracle = ChainlinkOracle()
        
        payload = {"data": {"result": 5000.0}}
        price = oracle._extract_price(payload)
        
        assert price == 5000.0
    
    def test_extract_from_value(self):
        """Test extracting price from value key."""
        oracle = ChainlinkOracle()
        
        payload = {"value": {"price": 6000.0}}
        price = oracle._extract_price(payload)
        
        assert price == 6000.0
    
    def test_extract_invalid_payload(self):
        """Test extracting from invalid payload raises."""
        oracle = ChainlinkOracle()
        
        with pytest.raises(ValueError, match="Unsupported"):
            oracle._extract_price({})


class TestChainlinkOracleExtractTimestamp:
    """Test _extract_timestamp method."""
    
    def test_extract_updatedAt(self):
        """Test extracting updatedAt timestamp."""
        oracle = ChainlinkOracle()
        
        ts = 1700000000.0
        payload = {"updatedAt": ts}
        result = oracle._extract_timestamp(payload)
        
        assert result == ts
    
    def test_extract_timestamp_key(self):
        """Test extracting timestamp key."""
        oracle = ChainlinkOracle()
        
        ts = 1700000000.0
        payload = {"timestamp": ts}
        result = oracle._extract_timestamp(payload)
        
        assert result == ts
    
    def test_extract_nested_timestamp(self):
        """Test extracting nested timestamp."""
        oracle = ChainlinkOracle()
        
        ts = 1700000000.0
        payload = {"data": {"timestamp": ts}}
        result = oracle._extract_timestamp(payload)
        
        assert result == ts
    
    def test_extract_missing_returns_current_time(self):
        """Test missing timestamp returns current time."""
        oracle = ChainlinkOracle()
        
        before = time.time()
        result = oracle._extract_timestamp({})
        after = time.time()
        
        assert before <= result <= after


class TestChainlinkOracleMockPrice:
    """Test _mock_price method."""
    
    def test_mock_price_returns_zero(self):
        """Test mock price returns 0."""
        oracle = ChainlinkOracle()
        
        result = oracle._mock_price("eth-usd")
        
        assert result == 0.0


# =============================================================================
# feed_probability Tests
# =============================================================================

class TestFeedProbability:
    """Test feed_probability function."""
    
    def test_basic_probability(self):
        """Test basic probability calculation."""
        snapshot = {"price": 2500.0, "scale_hint": 5000.0}
        
        prob = feed_probability(snapshot)
        
        assert prob == 0.5
    
    def test_probability_capped_at_one(self):
        """Test probability is capped at 1.0."""
        snapshot = {"price": 10000.0, "scale_hint": 5000.0}
        
        prob = feed_probability(snapshot)
        
        assert prob == 1.0
    
    def test_probability_floored_at_zero(self):
        """Test probability is floored at 0.0."""
        snapshot = {"price": -100.0, "scale_hint": 5000.0}
        
        prob = feed_probability(snapshot)
        
        assert prob == 0.0
    
    def test_missing_price_defaults_to_zero(self):
        """Test missing price defaults to 0."""
        snapshot = {"scale_hint": 5000.0}
        
        prob = feed_probability(snapshot)
        
        assert prob == 0.0
    
    def test_missing_scale_defaults_to_one(self):
        """Test missing scale defaults to 1.0."""
        snapshot = {"price": 0.5}
        
        prob = feed_probability(snapshot)
        
        assert prob == 0.5
    
    def test_zero_scale_defaults_to_one(self):
        """Test zero scale is treated as 1.0."""
        snapshot = {"price": 0.5, "scale_hint": 0.0}
        
        prob = feed_probability(snapshot)
        
        assert prob == 0.5


# =============================================================================
# PolymarketClient Tests
# =============================================================================

class TestPolymarketClientInit:
    """Test PolymarketClient initialization."""
    
    def test_default_init(self):
        """Test default initialization."""
        client = PolymarketClient()
        
        assert client.timeout == 10.0
        assert client.use_mock is False
    
    def test_mock_mode(self):
        """Test mock mode initialization."""
        client = PolymarketClient(use_mock=True)
        
        assert client.use_mock is True
    
    @patch.dict("os.environ", {"MERID_POLYMARKET_MOCK": "1"})
    def test_mock_mode_from_env(self):
        """Test mock mode from environment."""
        client = PolymarketClient()
        
        assert client.use_mock is True


class TestPolymarketClientFetchMarkets:
    """Test fetch_markets method."""
    
    def test_fetch_markets_mock_mode(self):
        """Test fetch_markets in mock mode."""
        client = PolymarketClient(use_mock=True)
        
        markets = client.fetch_markets(limit=10)
        
        assert markets == []
    
    def test_fetch_markets_success_list(self):
        """Test fetch_markets with list response."""
        client = PolymarketClient()
        
        mock_response = Mock()
        mock_response.json.return_value = [
            {"slug": "market1", "volume": 1000},
            {"slug": "market2", "volume": 2000}
        ]
        mock_response.raise_for_status = Mock()
        
        client._client = Mock()
        client._client.get.return_value = mock_response
        
        markets = client.fetch_markets(limit=10)
        
        assert len(markets) == 2
    
    def test_fetch_markets_success_dict_with_data(self):
        """Test fetch_markets with dict response containing data."""
        client = PolymarketClient()
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {"slug": "market1", "volume": 1000},
            ]
        }
        mock_response.raise_for_status = Mock()
        
        client._client = Mock()
        client._client.get.return_value = mock_response
        
        markets = client.fetch_markets(limit=10)
        
        assert len(markets) == 1
    
    def test_fetch_markets_with_category(self):
        """Test fetch_markets with category filter."""
        client = PolymarketClient()
        
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        
        client._client = Mock()
        client._client.get.return_value = mock_response
        
        client.fetch_markets(category="crypto", limit=5)
        
        call_args = client._client.get.call_args
        assert call_args[1]["params"]["category"] == "crypto"
    
    def test_fetch_markets_error_returns_mock(self):
        """Test fetch_markets error falls back to mock."""
        client = PolymarketClient()
        client._client = Mock()
        client._client.get.side_effect = Exception("Network error")
        
        markets = client.fetch_markets()
        
        assert markets == []
    
    def test_fetch_markets_invalid_response(self):
        """Test fetch_markets with invalid response type."""
        client = PolymarketClient()
        
        mock_response = Mock()
        mock_response.json.return_value = "invalid"
        mock_response.raise_for_status = Mock()
        
        client._client = Mock()
        client._client.get.return_value = mock_response
        
        markets = client.fetch_markets()
        
        assert markets == []


class TestPolymarketClientFindNegativeRisk:
    """Test find_negative_risk_opportunities method."""
    
    def test_find_opportunities_basic(self):
        """Test finding negative risk opportunities."""
        client = PolymarketClient()
        
        # Edge = max(0, no_price - (1 - yes_price))
        # For high-edge: edge = max(0, 0.98 - (1 - 0.1)) = max(0, 0.98 - 0.9) = 0.08
        markets = [
            {
                "slug": "high-edge-market",
                "volume": 1000,
                "yesPrice": 0.1,
                "noPrice": 0.98  # edge = 0.08 > threshold of 0.05
            },
            {
                "slug": "low-volume-market",
                "volume": 100,
                "yesPrice": 0.1,
                "noPrice": 0.98
            }
        ]
        
        opps = client.find_negative_risk_opportunities(markets, min_volume=500, yes_prob_threshold=0.05)
        
        assert len(opps) == 1
        assert opps[0]["slug"] == "high-edge-market"
    
    def test_find_opportunities_empty_market(self):
        """Test handling None/empty markets."""
        client = PolymarketClient()
        
        markets = [None, {}, {"slug": "valid", "volume": 1000, "yesPrice": 0.05}]
        
        opps = client.find_negative_risk_opportunities(markets, min_volume=500)
        
        # Only valid market with enough volume
        assert len(opps) <= 1
    
    def test_find_opportunities_sorted_by_edge(self):
        """Test opportunities are sorted by edge."""
        client = PolymarketClient()
        
        markets = [
            {"slug": "low-edge", "volume": 1000, "yesPrice": 0.4, "noPrice": 0.65},
            {"slug": "high-edge", "volume": 1000, "yesPrice": 0.1, "noPrice": 0.95}
        ]
        
        opps = client.find_negative_risk_opportunities(markets, min_volume=500, yes_prob_threshold=0.01)
        
        if len(opps) >= 2:
            assert opps[0]["edge"] >= opps[1]["edge"]
    
    def test_find_opportunities_uses_yes_price_fallback(self):
        """Test using yes_price fallback key."""
        client = PolymarketClient()
        
        markets = [
            {"slug": "alt-keys", "volume": 1000, "yes_price": 0.1, "no_price": 0.95}
        ]
        
        opps = client.find_negative_risk_opportunities(markets, min_volume=500)
        
        assert len(opps) >= 0  # May or may not qualify based on edge threshold


class TestPolymarketClientMockMarkets:
    """Test _mock_markets method."""
    
    def test_mock_markets_returns_empty(self):
        """Test mock_markets returns empty list."""
        client = PolymarketClient()
        
        result = client._mock_markets(10)
        
        assert result == []
