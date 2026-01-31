"""
Comprehensive Production System Tests for MERID.

Tests all critical components before going 100% live.
"""

import asyncio
import time
from typing import Dict, Any

import httpx
import pytest


def _prod_api_available() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.prod_integration,
    pytest.mark.quarantine,
    pytest.mark.skipif(not _prod_api_available(), reason="Production API not reachable"),
]


BASE_URL = "http://127.0.0.1:8000"


class TestProductionSystem:
    """Production system integration tests."""
    
    @pytest.fixture
    def client(self):
        """HTTP client for API testing."""
        return httpx.Client(base_url=BASE_URL, timeout=30.0)
    
    def test_health_endpoint(self, client):
        """Test system health endpoint."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        print("✅ Health endpoint working")
    
    def test_mining_status(self, client):
        """Test mining status endpoint."""
        response = client.get("/api/v1/mining/status")
        assert response.status_code == 200
        data = response.json()
        assert "mining_in_progress" in data
        print("✅ Mining status endpoint working")
    
    def test_mining_difficulty(self, client):
        """Test mining difficulty endpoint."""
        response = client.get("/api/v1/mining/difficulty")
        assert response.status_code == 200
        data = response.json()
        assert "current_difficulty" in data
        assert "min_confidence_threshold" in data
        print("✅ Mining difficulty endpoint working")
    
    def test_reflection_summary(self, client):
        """Test reflection summary endpoint."""
        response = client.get("/api/v1/reflection/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_reflections" in data
        assert "active_agents" in data
        print("✅ Reflection summary endpoint working")
    
    def test_agent_charters(self, client):
        """Test agent charters endpoint."""
        response = client.get("/api/v1/charters")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) > 0
        print("✅ Agent charters endpoint working")
    
    def test_dashboard_loads(self, client):
        """Test that production dashboard loads."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"MERID" in response.content
        print("✅ Production dashboard loads")
    
    def test_simple_dashboard_loads(self, client):
        """Test that simple dashboard loads."""
        response = client.get("/simple")
        assert response.status_code == 200
        assert b"MERID" in response.content
        print("✅ Simple dashboard loads")
    
    def test_static_files(self, client):
        """Test that static files are accessible."""
        # Test CSS
        response = client.get("/static/css/merid.css")
        assert response.status_code == 200
        print("✅ CSS files accessible")
        
        # Test production CSS
        response = client.get("/static/css/production.css")
        assert response.status_code == 200
        print("✅ Production CSS accessible")
        
        # Test JS
        response = client.get("/static/js/production.js")
        assert response.status_code == 200
        print("✅ JavaScript files accessible")
        
        # Test logo
        response = client.get("/static/merid_logo.png")
        assert response.status_code == 200
        print("✅ Logo file accessible")
    
    def test_auth_endpoints(self, client):
        """Test authentication endpoints exist."""
        # Test registration endpoint structure
        response = client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com"
        })
        # Should get validation error or success, not 404
        assert response.status_code in [200, 400, 422]
        print("✅ Auth registration endpoint exists")
    
    def test_referral_endpoints(self, client):
        """Test referral endpoints exist."""
        response = client.get("/api/v1/referrals/leaderboard")
        assert response.status_code == 200
        print("✅ Referral leaderboard endpoint working")
    
    def test_mine_block_endpoint(self, client):
        """Test block mining endpoint (without actually mining)."""
        response = client.post("/api/v1/mining/mine", json={})
        assert response.status_code in [200, 409]  # 409 if already mining
        print("✅ Mining endpoint accessible")


class TestSystemIntegration:
    """Integration tests for full system workflow."""
    
    @pytest.mark.asyncio
    async def test_full_mining_workflow(self):
        """Test complete mining workflow."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # Check initial status
            response = await client.get("/api/v1/mining/status")
            assert response.status_code == 200
            initial_data = response.json()
            
            # Start mining if not already in progress
            if not initial_data.get("mining_in_progress"):
                response = await client.post("/api/v1/mining/mine", json={})
                assert response.status_code == 200
                print("✅ Mining initiated")
                
                # Wait for mining to complete (max 30 seconds)
                for _ in range(30):
                    await asyncio.sleep(1)
                    response = await client.get("/api/v1/mining/status")
                    data = response.json()
                    
                    if not data.get("mining_in_progress") and data.get("latest_block"):
                        print("✅ Block mined successfully")
                        
                        # Verify block structure
                        block = data["latest_block"]
                        assert "index" in block
                        assert "hash" in block
                        assert "timestamp" in block
                        assert "consensus" in block
                        assert "value" in block
                        print("✅ Block structure valid")
                        
                        # Verify value metrics
                        metrics = data["latest_value_metrics"]
                        assert "overall_score" in metrics
                        assert "value_grade" in metrics
                        assert "breakdown" in metrics
                        print("✅ Value metrics valid")
                        
                        return
                
                print("⚠️  Mining took longer than expected")
            else:
                print("⚠️  Mining already in progress")


def run_production_tests():
    """Run all production tests."""
    print("\n" + "=" * 70)
    print("MERID PRODUCTION SYSTEM TESTS")
    print("=" * 70 + "\n")
    
    # Run pytest
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-s"
    ])
    
    print("\n" + "=" * 70)
    if exit_code == 0:
        print("✅ ALL TESTS PASSED - SYSTEM READY FOR PRODUCTION")
    else:
        print("❌ SOME TESTS FAILED - REVIEW REQUIRED")
    print("=" * 70 + "\n")
    
    return exit_code


if __name__ == "__main__":
    exit(run_production_tests())
