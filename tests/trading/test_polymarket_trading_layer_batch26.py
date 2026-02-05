"""Tests for Polymarket trading layer - Batch 26 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import os
import time

from trading.polymarket_trading_layer import (
    ChainlinkFeed,
    DEFAULT_CHAINLINK_FEEDS,
    ChainlinkOracle,
    PolymarketClient,
    feed_probability
)


class TestChainlinkFeed:
    """Tests for ChainlinkFeed dataclass."""

    def test_feed_creation(self):
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

    def test_default_feeds(self):
        assert len(DEFAULT_CHAINLINK_FEEDS) > 0
        feed = DEFAULT_CHAINLINK_FEEDS[0]
        assert isinstance(feed, ChainlinkFeed)


class TestChainlinkOracle:
    """Tests for ChainlinkOracle."""

    @pytest.fixture
    def oracle(self):
        return ChainlinkOracle(network="polygon")

    def test_initialization(self, oracle):
        assert oracle.network == "polygon"
        assert oracle._client is not None

    def test_extract_price_direct(self, oracle):
        payload = {"price": "45000.50"}
        price = oracle._extract_price(payload)
        assert price == 45000.50

    def test_extract_price_nested(self, oracle):
        payload = {"data": {"price": "3800.25"}}
        price = oracle._extract_price(payload)
        assert price == 3800.25

    def test_extract_price_result_key(self, oracle):
        payload = {"data": {"result": "100.75"}}
        price = oracle._extract_price(payload)
        assert price == 100.75

    def test_extract_price_invalid(self, oracle):
        with pytest.raises(ValueError):
            oracle._extract_price({"invalid": "data"})

    def test_extract_timestamp_direct(self, oracle):
        payload = {"updatedAt": "1234567890"}
        ts = oracle._extract_timestamp(payload)
        assert ts == 1234567890.0

    def test_extract_timestamp_nested(self, oracle):
        payload = {"data": {"timestamp": "1234567890"}}
        ts = oracle._extract_timestamp(payload)
        assert ts == 1234567890.0

    def test_extract_timestamp_fallback(self, oracle):
        payload = {"no_timestamp": "here"}
        ts = oracle._extract_timestamp(payload)
        # Should return current time
        assert ts > 0


class TestFeedProbability:
    """Tests for feed_probability function."""

    def test_probability_basic(self):
        snapshot = {"price": 500.0, "scale_hint": 1000.0}
        prob = feed_probability(snapshot)
        assert prob == 0.5

    def test_probability_clamped_high(self):
        snapshot = {"price": 2000.0, "scale_hint": 1000.0}
        prob = feed_probability(snapshot)
        assert prob == 1.0  # Clamped at 1.0

    def test_probability_clamped_low(self):
        snapshot = {"price": -100.0, "scale_hint": 1000.0}
        prob = feed_probability(snapshot)
        assert prob == 0.0  # Clamped at 0.0

    def test_probability_defaults(self):
        snapshot = {"price": 0.5}
        prob = feed_probability(snapshot)
        assert prob == 0.5  # scale_hint defaults to 1.0


class TestPolymarketClient:
    """Tests for PolymarketClient."""

    @pytest.fixture
    def client(self):
        return PolymarketClient(use_mock=True)

    def test_initialization(self, client):
        assert client.use_mock is True
        assert client.timeout == 10.0
        assert client._client is not None

    def test_initialization_with_env(self):
        with patch.dict(os.environ, {"MERID_POLYMARKET_MOCK": "1"}):
            client = PolymarketClient()
            assert client.use_mock is True

    def test_find_negative_risk_opportunities(self, client):
        markets = [
            {"slug": "market1", "volume": "1000", "yesPrice": "0.4", "noPrice": "0.7"},
            {"slug": "market2", "volume": "100", "yesPrice": "0.5", "noPrice": "0.5"},
            {"slug": "market3", "volume": "2000", "yesPrice": "0.3", "noPrice": "0.8"},
        ]
        
        opportunities = client.find_negative_risk_opportunities(markets, min_volume=500)
        
        # Markets with edge >= 0.05 and volume >= 500
        assert len(opportunities) == 2
        # Sorted by edge descending
        assert opportunities[0]["slug"] in ["market1", "market3"]

    def test_find_negative_risk_with_alternative_keys(self, client):
        markets = [
            {"question": "Market 1", "volume": 1000, "yes_price": 0.4, "no_price": 0.7},
        ]
        
        opportunities = client.find_negative_risk_opportunities(markets)
        
        assert len(opportunities) == 1
        assert opportunities[0]["slug"] == "Market 1"

    def test_find_negative_risk_empty(self, client):
        opportunities = client.find_negative_risk_opportunities([])
        assert opportunities == []

    def test_find_negative_risk_none_market(self, client):
        markets = [None, {"slug": "market1", "volume": 1000, "yesPrice": 0.4, "noPrice": 0.7}]
        opportunities = client.find_negative_risk_opportunities(markets)
        assert len(opportunities) == 1

    def test_find_negative_risk_calculated_no_price(self, client):
        # Test edge calculation when prices create arbitrage opportunity
        markets = [
            {"slug": "market1", "volume": "600", "yesPrice": "0.3", "noPrice": "0.8"},
        ]
        # edge = max(0, 0.8 - 0.7) = 0.1, which is >= 0.05 threshold
        opportunities = client.find_negative_risk_opportunities(markets)
        assert len(opportunities) == 1
        assert opportunities[0]["slug"] == "market1"

    def test_find_negative_risk_below_threshold(self, client):
        markets = [
            {"slug": "market1", "volume": "1000", "yesPrice": "0.5", "noPrice": "0.5"},
        ]
        # edge = max(0, 0.5 - 0.5) = 0
        opportunities = client.find_negative_risk_opportunities(markets, yes_prob_threshold=0.05)
        # edge of 0 is less than threshold of 0.05
        assert len(opportunities) == 0
