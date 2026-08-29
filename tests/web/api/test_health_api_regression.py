"""
Regression tests for health/readiness endpoint behavior.

Tests for:
1. kalshi-readiness endpoint behavior
2. Spot service integration

Run with: pytest tests/web/api/test_health_api_regression.py -v
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient


class TestKalshiReadiness:
    """Tests for kalshi-readiness endpoint behavior"""
    
    @pytest.fixture
    def mock_app(self):
        """Mock FastAPI app with health router"""
        from web.main_15m_lean import app
        return app
    
    @pytest.fixture
    def client(self, mock_app):
        """Test client for FastAPI app"""
        return TestClient(mock_app)
    
    def test_readiness_endpoint_exists(self, client):
        """Test that readiness endpoint is accessible"""
        response = client.get('/api/health/kalshi-readiness')
        # Endpoint should exist (may return unhealthy if not fully configured)
        assert response.status_code in [200, 500]
    
    def test_readiness_returns_json(self, client):
        """Test that readiness returns JSON response"""
        response = client.get('/api/health/kalshi-readiness')
        if response.status_code == 200:
            data = response.json()
            assert 'status' in data or 'error' in data


class TestHealthSnapshot:
    """Tests for /api/v1/health-snapshot/ shape."""

    @pytest.fixture
    def client(self):
        from web.main_15m_lean import app
        return TestClient(app)

    def test_health_snapshot_includes_quarantine_path(self, client, monkeypatch):
        """The live 15m end-to-end probe checks quarantine_path in this response."""
        from types import SimpleNamespace

        placeholder = {
            "timestamp": "2026-08-29T03:00:00Z",
            "ws": {
                "connection_state": "CONNECTED",
                "latency_ms": 0.0,
                "heartbeat_age_s": 0.0,
                "is_connected": True,
            },
            "spot": {
                "last_update_age_s": 0.0,
                "service_running": True,
                "is_stale": False,
                "stale_reason": None,
            },
            "book": {
                "book_consistency": "OK",
                "suspect_reason": None,
                "last_update_age_s": 0.0,
                "is_dual_sided": True,
                "best_bid_cents": 50,
                "best_ask_cents": 55,
                "spread_cents": 5,
                "spread_pct": 0.1,
                "is_stale": False,
            },
            "risk": {
                "utilization_pct": 0.0,
                "has_capacity": True,
                "is_exhausted": False,
            },
            "gates": {
                "spot_age": "PASS",
                "book_freshness": "PASS",
                "liquidity": "PASS",
                "data_quality": "PASS",
                "edge": "PASS",
                "risk": "PASS",
                "overall": "PASS",
                "reason": None,
            },
            "quarantine_path": "active",
        }

        mock_snapshot = SimpleNamespace(
            to_dict=lambda: placeholder,
            map_to_scenario=lambda: "test_one_sided_book_no_bids_scenario",
        )

        with patch("merid.monitoring.health_snapshot.get_health_snapshot", return_value=mock_snapshot):
            response = client.get("/api/v1/health-snapshot/")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["quarantine_path"] == "active"


class TestSpotServiceIntegration:
    """Tests for spot service integration in health endpoints"""
    
    def test_get_unified_spot_service_singleton(self):
        """Test that get_unified_spot_service returns singleton"""
        from data.unified_spot_service import get_unified_spot_service
        
        instance1 = get_unified_spot_service()
        instance2 = get_unified_spot_service()
        
        assert id(instance1) == id(instance2)
    
    def test_spot_service_has_cache(self):
        """Test that spot service has cache attribute"""
        from data.unified_spot_service import get_unified_spot_service
        
        service = get_unified_spot_service()
        assert hasattr(service, '_cache')
        assert hasattr(service, '_asset_success_ts')
        assert hasattr(service, '_running')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
