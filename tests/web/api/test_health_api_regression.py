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
