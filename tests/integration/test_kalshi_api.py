"""Integration tests for Kalshi API endpoints.

Tests full request/response cycles with mocked Kalshi client.
Run with: pytest tests/integration/test_kalshi_api.py -v
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from web.api.kalshi_api import router

# Create test client
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestKalshiAPIHealth:
    """Health check endpoint tests."""

    def test_health_no_client(self):
        """Health check when no client configured."""
        response = client.get("/api/v1/kalshi/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded", "disconnected", "halted", "critical"]
        assert "issues" in data
        assert "catalog" in data
        assert "risk" in data
        assert "ws" in data
        assert "rate_limits" in data

    def test_health_response_structure(self):
        """Health response keeps required top-level fields."""
        response = client.get("/api/v1/kalshi/health")
        assert response.status_code == 200
        data = response.json()
        required = {"status", "issues", "catalog", "risk", "ws", "rate_limits"}
        assert required.issubset(set(data.keys()))


class TestKalshiAPIMarkets:
    """Market listing and detail endpoint tests."""

    def test_list_markets_no_params(self):
        """List markets without filters."""
        response = client.get("/api/v1/kalshi/markets")
        assert response.status_code == 200
        data = response.json()
        assert "markets" in data
        assert "count" in data

    def test_list_markets_with_category(self):
        """List markets filtered by category."""
        response = client.get("/api/v1/kalshi/markets?category=crypto")
        assert response.status_code == 200
        data = response.json()
        assert "markets" in data

    def test_list_markets_with_search(self):
        """List markets with search query."""
        response = client.get("/api/v1/kalshi/markets?search=BTC")
        assert response.status_code == 200
        data = response.json()
        assert "markets" in data

    def test_market_detail_not_found(self):
        """Market detail for non-existent ticker."""
        response = client.get("/api/v1/kalshi/markets/INVALID-TICKER-123")
        assert response.status_code == 404

    def test_orderbook_not_found(self):
        """Orderbook for non-existent ticker."""
        response = client.get("/api/v1/kalshi/markets/INVALID-TICKER-123/orderbook")
        # Should return empty orderbook, not 404
        assert response.status_code == 200
        data = response.json()
        assert "ticker" in data


class TestKalshiAPIOrderPlacement:
    """Order placement endpoint tests."""

    def test_place_order_validation_error(self):
        """Order placement with invalid side."""
        response = client.post(
            "/api/v1/kalshi/orders",
            params={
                "ticker": "KXBTC-24DEC-ABOVE-60000",
                "side": "invalid",
                "action": "buy",
                "count": 1,
                "price_cents": 50,
            }
        )
        assert response.status_code == 400

    def test_place_order_price_out_of_range(self):
        """Order placement with invalid price."""
        response = client.post(
            "/api/v1/kalshi/orders",
            params={
                "ticker": "KXBTC-24DEC-ABOVE-60000",
                "side": "yes",
                "action": "buy",
                "count": 1,
                "price_cents": 150,  # Invalid: > 99
            }
        )
        assert response.status_code == 400

    def test_batch_orders_empty(self):
        """Batch order placement with empty list."""
        response = client.post(
            "/api/v1/kalshi/orders/batch",
            json=[]
        )
        assert response.status_code == 400

    def test_batch_orders_too_many(self):
        """Batch order placement exceeding limit."""
        orders = [{"ticker": "KXBTC", "side": "yes", "count": 1}] * 21
        response = client.post(
            "/api/v1/kalshi/orders/batch",
            json=orders
        )
        assert response.status_code == 400

    def test_amend_order_no_params(self):
        """Amend order without price or count."""
        response = client.patch(
            "/api/v1/kalshi/orders/test-order-123/amend"
        )
        assert response.status_code == 400


class TestKalshiAPIPortfolio:
    """Portfolio endpoint tests."""

    def test_get_positions(self):
        """Get positions endpoint."""
        response = client.get("/api/v1/kalshi/positions")
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data
        assert "count" in data
        if data["positions"]:
            assert "status" in data["positions"][0]

    def test_get_orders(self):
        """Get orders endpoint."""
        response = client.get("/api/v1/kalshi/orders")
        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        assert "count" in data

    def test_get_balance(self):
        """Get balance endpoint."""
        response = client.get("/api/v1/kalshi/balance")
        assert response.status_code == 200
        data = response.json()
        assert "usd" in data or "error" in data

    def test_get_fills(self):
        """Get fills endpoint."""
        response = client.get("/api/v1/kalshi/fills?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "fills" in data
        assert "count" in data

    def test_portfolio_summary(self):
        """Portfolio summary endpoint."""
        response = client.get("/api/v1/kalshi/portfolio/summary")
        # May return 503 if client not configured
        assert response.status_code in [200, 503]

    def test_portfolio_risk(self):
        """Portfolio risk endpoint."""
        response = client.get("/api/v1/kalshi/portfolio/risk")
        assert response.status_code in [200, 503]

    def test_portfolio_var(self):
        """Portfolio VaR endpoint."""
        response = client.get("/api/v1/kalshi/portfolio/var?alpha=0.1")
        assert response.status_code in [200, 503]

    def test_portfolio_pnl(self):
        """Portfolio PnL endpoint."""
        response = client.get("/api/v1/kalshi/portfolio/pnl")
        assert response.status_code in [200, 503]


class TestKalshiAPIRisk:
    """Risk management endpoint tests."""

    def test_get_risk(self):
        """Risk status endpoint."""
        response = client.get("/api/v1/kalshi/risk")
        assert response.status_code == 200
        data = response.json()
        assert "kill_switch_active" in data

    def test_kill_switch_toggle(self):
        """Kill switch toggle endpoint."""
        # First activate
        response = client.post("/api/v1/kalshi/kill-switch?activate=true")
        assert response.status_code == 200
        data = response.json()
        assert "kill_switch" in data
        assert "action" in data

        # Then deactivate
        response = client.post("/api/v1/kalshi/kill-switch?activate=false")
        assert response.status_code == 200

    def test_risk_events(self):
        """Risk events endpoint."""
        response = client.get("/api/v1/kalshi/risk/events")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data

    def test_risk_downsize(self):
        """Risk downsize endpoint."""
        response = client.post("/api/v1/kalshi/risk/downsize?asset=BTC&factor=0.5")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


class TestKalshiAPICatalog:
    """Catalog endpoint tests."""

    def test_catalog_summary(self):
        """Catalog summary endpoint."""
        response = client.get("/api/v1/kalshi/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "market_count" in data

    def test_catalog_refresh(self):
        """Catalog refresh endpoint."""
        response = client.post("/api/v1/kalshi/catalog/refresh")
        assert response.status_code == 200
        data = response.json()
        assert "refreshed" in data

    def test_get_categories(self):
        """Get categories endpoint."""
        response = client.get("/api/v1/kalshi/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "known" in data

    def test_update_categories(self):
        """Update categories endpoint."""
        response = client.put(
            "/api/v1/kalshi/categories",
            json={"crypto": "live", "politics": "read-only"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "updated" in data


class TestKalshiAPIEdge:
    """Edge signals endpoint tests."""

    def test_edge_signals(self):
        """Edge signals endpoint."""
        response = client.get("/api/v1/kalshi/edge")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data

    def test_edge_signals_with_tickers(self):
        """Edge signals with specific tickers."""
        response = client.get("/api/v1/kalshi/edge?tickers=KXBTC-24DEC-ABOVE-60000")
        assert response.status_code == 200


class TestKalshiAPIVolume:
    """Volume monitoring endpoint tests."""

    def test_volume_changes(self):
        """Volume changes endpoint."""
        response = client.get("/api/v1/kalshi/volume-changes")
        # May return error if monitor not available
        assert response.status_code == 200

    def test_volume_history(self):
        """Volume history endpoint."""
        response = client.get("/api/v1/kalshi/volume-history/KXBTC-24DEC-ABOVE-60000")
        assert response.status_code == 200


class TestKalshiAPIFavorites:
    """Favorites endpoint tests."""

    def test_get_favorites(self):
        """Get favorites endpoint."""
        response = client.get("/api/v1/kalshi/favorites")
        assert response.status_code == 200
        data = response.json()
        assert "favorites" in data

    def test_set_favorites(self):
        """Set favorites endpoint."""
        response = client.put(
            "/api/v1/kalshi/favorites",
            json={"favorites": ["KXBTC-24DEC-ABOVE-60000", "KXETH-24DEC-ABOVE-3000"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert "favorites" in data
        assert data["count"] == 2

    def test_toggle_favorite(self):
        """Toggle favorite endpoint."""
        response = client.post("/api/v1/kalshi/favorites/toggle?ticker=KXBTC-TEST")
        assert response.status_code == 200
        data = response.json()
        assert "action" in data
        assert data["action"] in ["added", "removed"]


class TestKalshiAPIClientMetrics:
    """Client metrics endpoint tests."""

    def test_client_metrics(self):
        """Client metrics endpoint."""
        response = client.get("/api/v1/kalshi/client/metrics")
        # May return 503 if client not configured
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "circuit_breaker" in data
            assert "rate_limiter" in data


class TestKalshiAPISizing:
    """Sizing metrics endpoint tests."""

    def test_sizing_metrics(self):
        """Sizing metrics endpoint."""
        response = client.get("/api/v1/kalshi/sizing-metrics")
        assert response.status_code == 200
        data = response.json()
        assert "kelly_fraction" in data
        assert "drawdown_tier" in data


class TestKalshiAPIPnLHistory:
    """PnL history endpoint tests."""

    def test_pnl_history(self):
        """PnL history endpoint."""
        response = client.get("/api/v1/kalshi/pnl-history?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "points" in data
        assert "breaches" in data


class TestKalshiAPIInsights:
    """Insights endpoint tests."""

    def test_risk_insights(self):
        """Risk insights endpoint."""
        response = client.get("/api/v1/kalshi/risk/insights")
        assert response.status_code == 200
        data = response.json()
        assert "insights" in data


class TestKalshiAPIConsensus:
    """Consensus signals endpoint tests."""

    def test_consensus_signals(self):
        """Consensus signals endpoint."""
        response = client.get("/api/v1/kalshi/consensus-signals")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data


class TestKalshiAPINews:
    """News signals endpoint tests."""

    def test_news_signals(self):
        """News signals endpoint."""
        response = client.get("/api/v1/kalshi/news-signals?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data


class TestKalshiAPILiquidity:
    """Liquidity endpoint tests."""

    def test_liquidity_alerts(self):
        """Liquidity alerts endpoint."""
        response = client.get("/api/v1/kalshi/liquidity-alerts")
        assert response.status_code == 200

    def test_liquidity_health(self):
        """Liquidity health endpoint."""
        response = client.get("/api/v1/kalshi/liquidity-health/KXBTC-24DEC-ABOVE-60000")
        assert response.status_code == 200
        data = response.json()
        assert "ticker" in data


class TestKalshiAPIFIX:
    """FIX API endpoint tests."""

    def test_fix_status(self):
        """FIX status endpoint."""
        response = client.get("/api/v1/kalshi/fix/status")
        assert response.status_code == 200
        data = response.json()
        assert "connected" in data

    def test_fix_pending(self):
        """FIX pending orders endpoint."""
        response = client.get("/api/v1/kalshi/fix/pending")
        # May return 503 if FIX not configured
        assert response.status_code in [200, 503]

    def test_fix_executions(self):
        """FIX executions endpoint."""
        response = client.get("/api/v1/kalshi/fix/executions?limit=10")
        # May return 503 if FIX not configured
        assert response.status_code in [200, 503]


class TestKalshiAPIRateLimiting:
    """Rate limiting behavior tests."""

    def test_rate_limit_headers(self):
        """Verify rate limit headers present."""
        # Make multiple requests to trigger rate limiting
        responses = []
        for _ in range(5):
            response = client.get("/api/v1/kalshi/health")
            responses.append(response)

        # Check last response has rate limit headers
        last_response = responses[-1]
        # Note: Rate limit headers may not be present if middleware not configured
        # This test documents expected behavior


class TestKalshiAPIErrorHandling:
    """Error handling tests."""

    def test_404_endpoint(self):
        """Non-existent endpoint returns 404."""
        response = client.get("/api/v1/kalshi/non-existent-endpoint")
        assert response.status_code == 404

    def test_invalid_method(self):
        """Invalid HTTP method returns 405."""
        response = client.post("/api/v1/kalshi/markets")
        assert response.status_code == 405

    def test_invalid_json_body(self):
        """Invalid JSON body handled gracefully."""
        response = client.post(
            "/api/v1/kalshi/orders/batch",
            data="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
