"""
MERID API Contract Tests
Tests for UI/backend API compatibility validation
"""

import pytest
import asyncio
from typing import Dict, Any, List
from fastapi.testclient import TestClient
from web.main import create_app
import json

class TestApiContracts:
    """Test suite for API contract validation"""
    
    def __init__(self):
        self.app = create_app()
        self.client = TestClient(self.app)
    
    def test_openapi_spec_available(self):
        """Test that OpenAPI spec is available"""
        response = self.client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        
        # Validate OpenAPI structure
        assert "openapi" in data
        assert "info" in data["openapi"]
        assert "paths" in data["openapi"]
        assert data["openapi"]["info"]["title"] == "MERID API"
        
    def test_health_api_contract(self):
        """Test health API contract compliance"""
        response = self.client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        
        # Validate required fields
        assert "status" in data
        assert isinstance(data["status"], str)
        assert "chain" in data
        assert isinstance(data["chain"], (dict, list))
        
        # Validate data types
        if "components" in data:
            assert isinstance(data["components"], (int, float))
        
    def test_dashboard_api_contract(self):
        """Test dashboard API contract compliance"""
        response = self.client.get("/api/v1/test/simple")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "data" in data
        
        # Validate data structure
        data = data["data"]
        assert "prices" in data
        assert "news" in data
        assert "reality" in data
        assert "intelligence" in data
        
        # Validate prices
        prices = data["prices"]
        assert isinstance(prices, dict)
        for symbol, price_data in prices.items():
            assert isinstance(price_data, dict)
            assert "price" in price_data
            assert isinstance(price_data["price"], (int, float))
            assert "change_24h" in price_data
            assert isinstance(price_data["change_24h"], (int, float))
        
        # Validate news
        news = data["news"]
        assert isinstance(news, list)
        for item in news:
            assert isinstance(item, dict)
            assert "title" in item
            assert "source" in item
            assert "url" in item
            
        # Validate reality
        reality = data["reality"]
        assert isinstance(reality, dict)
        assert "mode" in reality
        assert "valid_assertions_pct" in reality
        assert isinstance(reality["valid_assertions_pct"], (int, float))
        
        # Validate intelligence
        intelligence = data["intelligence"]
        assert isinstance(intelligence, dict)
        assert "sources" in intelligence
        assert "total_sources" in intelligence
        
    def test_intelligence_news_contract(self):
        """Test intelligence news API contract compliance"""
        response = self.client.get("/api/v1/intelligence/news?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "news" in data
        
        # Validate news items
        news = data["news"]
        assert isinstance(news, list)
        assert len(news) <= 5  # Respect limit parameter
        
        for item in news:
            assert isinstance(item, dict)
            assert "title" in item
            assert "source" in item
            assert "url" in item
            assert "timestamp" in item
            
    def test_intelligence_sources_contract(self):
        """Test intelligence sources API contract compliance"""
        response = self.client.get("/api/v1/intelligence/sources")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "sources" in data
        assert "total_sources" in data
        
        # Validate sources data
        sources = data["sources"]
        assert isinstance(sources, dict)
        
        for source, data in sources.items():
            assert isinstance(data, dict)
            assert "count" in data
            assert isinstance(data["count"], (int, float))
            assert "categories" in data
            assert "sentiments" in data
            
    def test_intelligence_sentiment_contract(self):
        """Test intelligence sentiment API contract compliance"""
        response = self.client.get("/api/v1/intelligence/sentiment")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "sentiments" in data
        assert "analysis" in data
        
        # Validate sentiments
        sentiments = data["sentiments"]
        assert isinstance(sentiments, dict)
        assert "positive" in sentiments
        assert "negative" in sentiments
        assert "neutral" in sentiments
        assert "total" in sentiments
        assert "positive_pct" in sentiments
        assert "negative_pct" in sentiments
        assert "neutral_pct" in sentiments
        
        # Validate analysis
        analysis = data["analysis"]
        assert "dominant_sentiment" in analysis
        assert "sentiment_ratio" in analysis
        
    def test_institutional_markets_contract(self):
        """Test institutional markets API contract compliance"""
        response = self.client.get("/api/v1/institutional/predictions/markets?limit=3")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "markets" in data
        assert "aggregator_id" in data
        assert "total_markets" in data
        
        # Validate markets
        markets = data["markets"]
        assert isinstance(markets, list)
        assert len(markets) <= 3  # Respect limit parameter
        
        for market in markets:
            assert isinstance(market, dict)
            assert "market_id" in market
            assert "question" in market
            assert "category" in market
            assert "yes_price" in market
            assert "no_price" in market
            assert "volume_24h" in market
            assert "liquidity" in market
            assert "expires" in market
            assert "platform" in market
            assert "status" in market
            
            # Validate enums
            valid_categories = ["politics", "sports", "finance", "crypto", "technology", "entertainment", "weather", "other"]
            assert market["category"] in valid_categories
            
            valid_platforms = ["polymarket", "predictit", "kalshi", "augur", "foretell"]
            assert market["platform"] in valid_platforms
            
            valid_statuses = ["open", "pending", "resolved", "cancelled"]
            assert market["status"] in valid_statuses
            
    def test_institutional_drift_contract(self):
        """Test institutional drift signals API contract compliance"""
        response = self.client.get("/api/v1/institutional/predictions/drift?limit=3")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "signals" in data
        assert "aggregator_id" in data
        assert "total_signals" in data
        
        # Validate signals
        signals = data["signals"]
        assert isinstance(signals, list)
        assert len(signals) <= 3  # Respect limit parameter
        
        for signal in signals:
            assert isinstance(signal, dict)
            assert "market_id" in signal
            assert "question" in signal
            assert "drift_pct" in signal
            assert "confidence" in signal
            assert "timestamp" in signal
            
            # Validate data types
            assert isinstance(signal["drift_pct"], (int, float))
            assert isinstance(signal["confidence"], (int, float))
            assert isinstance(signal["timestamp"], (int, float))
            
    def test_institutional_arbitrage_contract(self):
        """Test institutional arbitrage API contract compliance"""
        response = self.client.get("/api/v1/institutional/predictions/arbitrage?limit=3")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "status" in data
        assert "opportunities" in data
        assert "aggregator_id" in data
        assert "total_opportunities" in data
        
        # Validate opportunities
        opportunities = data["opportunities"]
        assert isinstance(opportunities, list)
        assert len(opportunities) <= 3  # Respect limit parameter
        
        for opportunity in opportunities:
            assert isinstance(opportunity, dict)
            assert "market_id" in opportunity
            assert "question" in opportunity
            assert "platform_a" in opportunity
            assert "platform_b" in opportunity
            assert "spread_pct" in opportunity
            assert "potential_profit" in opportunity
            assert "confidence" in opportunity
            
            # Validate data types
            assert isinstance(opportunity["spread_pct"], (int, float))
            assert isinstance(opportunity["potential_profit"], (int, float))
            assert isinstance(opportunity["confidence"], (int, float))
            
    def test_reality_status_contract(self):
        """Test reality status API contract compliance"""
        response = self.client.get("/api/v1/reality/status")
        assert response.status_code == 200
        data = response.json()
        
        # Validate structure
        assert "mode" in data
        assert "valid_assertions_pct" in data
        assert "regime_entropy" in data
        assert "active_conflicts" in data
        assert "blind_spots" in data
        
        # Validate data types
        assert isinstance(data["mode"], str)
        assert isinstance(data["valid_assertions_pct"], (int, float))
        assert isinstance(data["regime_entropy"], (int, float))
        assert isinstance(data["active_conflicts"], (int, float))
        assert isinstance(data["blind_spots"], list)
        
        # Validate mode values
        valid_modes = ["operational", "blind", "offline"]
        assert data["mode"] in valid_modes
        
        # Validate percentage ranges
        assert 0 <= data["valid_assertions_pct"] <= 100
        assert data["regime_entropy"] >= 0
        assert data["active_conflicts"] >= 0

    def test_error_handling(self):
        """Test error handling in API contracts"""
        # Test 404 error
        response = self.client.get("/api/v1/nonexistent")
        assert response.status_code == 404
        
        # Test error response structure
        data = response.json()
        assert "detail" in data
        
        # Test invalid request
        response = self.client.post("/api/v1/test/simple", json={"invalid": "data"})
        # Should still work with validation errors handled by FastAPI

    def test_cors_headers(self):
        """Test CORS headers are properly set"""
        response = self.client.options("/api/v1/test/simple")
        assert response.status_code == 200
        
        # Check for CORS headers
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers
        assert "access-control-allow-headers" in response.headers

if __name__ == "__main__":
    pytest.main([TestApiContracts])
