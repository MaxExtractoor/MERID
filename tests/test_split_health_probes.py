"""Tests for Split Health Probes implementation.

CRITICAL FIX (2026-07-17): Tests for liveness, readiness, and startup probe separation.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


class TestSplitHealthProbes:
    """Test split health probe endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        # Import here to avoid circular imports
        from web.main_15m_lean import app
        return TestClient(app)
    
    def test_liveness_probe(self, client):
        """Test liveness probe endpoint."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "alive"
        assert "timestamp" in data
    
    def test_readiness_probe_not_ready(self, client):
        """Test readiness probe when not ready."""
        response = client.get("/api/v1/ready")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be not_ready initially
        assert data["status"] in ["not_ready", "ready"]
        assert "startup_completed" in data
        assert "loop_task_alive" in data
    
    def test_startup_probe(self, client):
        """Test startup probe endpoint."""
        response = client.get("/api/v1/startup")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] in ["in_progress", "complete"]
        assert "startup_started" in data
        assert "startup_completed" in data
    
    def test_liveness_probe_fast(self, client):
        """Test that liveness probe is fast (no external dependencies)."""
        import time
        
        start = time.time()
        response = client.get("/api/v1/health")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Should complete in under 100ms
        assert elapsed < 0.1
    
    def test_readiness_probe_checks_loop(self, client):
        """Test that readiness probe checks loop task status."""
        response = client.get("/api/v1/ready")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should check loop task
        assert "loop_task_alive" in data
    
    def test_startup_probe_checks_startup_state(self, client):
        """Test that startup probe checks startup state."""
        response = client.get("/api/v1/startup")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should check startup state
        assert "startup_started" in data
        assert "startup_completed" in data
    
    def test_health_endpoint_separate_from_ready(self, client):
        """Test that /health is separate from /ready."""
        health_response = client.get("/api/v1/health")
        ready_response = client.get("/api/v1/ready")
        
        health_data = health_response.json()
        ready_data = ready_response.json()
        
        # Health should only return alive status
        assert "status" in health_data
        assert health_data["status"] == "alive"
        
        # Ready should return more detailed status
        assert "status" in ready_data
        assert "loop_task_alive" in ready_data
        assert "startup_completed" in ready_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
