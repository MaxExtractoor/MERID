"""
Regression tests for bootstrap sighted mode.

Tests that bootstrap assertions register correctly and move the system
from blind_hard to blind_soft mode.
"""

import pytest
import time
import requests
from web.api.reality import router as reality_router
from web.main import create_app


@pytest.mark.localvenue
@pytest.mark.reality
class TestBootstrapSightedMode:
    """Test bootstrap sighted mode functionality."""
    
    @pytest.fixture
    async def app(self):
        """Create test app."""
        return create_app()
    
    @pytest.fixture
    async def client(self, app):
        """Create test client."""
        from httpx import AsyncClient
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client
    
    async def test_bootstrap_registers_assertions(self, client):
        """Test that bootstrap endpoint registers assertions."""
        # Clear any existing assertions first
        try:
            # Get current registry and clear it
            from core.reality_registry import get_reality_registry
            registry = get_reality_registry()
            registry._assertions.clear()
        except:
            pass
        
        # Call bootstrap
        response = await client.post("/api/v1/reality/bootstrap")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "bootstrapped"
        assert data["assertions_registered"] == 3
        assert len(data["assertion_ids"]) == 3
    
    async def bootstrap_system(self):
        """Bootstrap the system for testing."""
        # Clear any existing assertions first
        try:
            from core.reality_registry import get_reality_registry
            registry = get_reality_registry()
            registry._assertions.clear()
        except:
            pass
        
        # Call bootstrap
        response = requests.post("http://127.0.0.1:8001/api/v1/reality/bootstrap", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "bootstrapped"
        assert data["assertions_registered"] == 3
        return data
    
    def test_bootstrap_sighted_mode(self):
        """Test that bootstrap moves system to blind_soft mode."""
        # Bootstrap the system
        bootstrap_data = self.bootstrap_system()
        
        # Check reality status
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        
        # Should be in degraded but not blind_hard mode
        assert data["status"] == "degraded"
        assert data["bootstrap_required"] == False  # Bootstrap completed
        
        # Check system state
        system_state = data["system_state"]
        assert system_state["mode"] in ["blind_soft", "normal"]  # Should not be blind_hard
        assert system_state["assertions_count"] > 0  # Should have assertions
        assert system_state["valid_assertions"] > 0  # Should have valid assertions
        
        # Check that it's not the critical blindness state
        assert "No assertions registered" not in system_state["reason"]
        assert "No valid assertions" not in system_state["reason"]
    
    def test_local_venue_respects_bootstrap(self):
        """Test that local venue respects bootstrap state."""
        # Bootstrap the system
        self.bootstrap_system()
        
        # Check local venue validation status
        response = requests.get("http://127.0.0.1:8001/api/v1/localvenue/validation-status", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        
        # Local venue should still be failing (because it has its own validation logic)
        # but it should have access to reality system status
        assert data["overall_status"] in ["FAILING", "DEGRADED"]
        assert data["current_phase"] == "Phase 0"
        
        # The key is that it should not crash due to reality system errors
        assert isinstance(data["phases"], list)
        assert len(data["phases"]) == 4  # All phases should be present
    
    def test_bootstrap_persistence(self):
        """Test that bootstrap assertions persist across calls."""
        # Bootstrap once
        bootstrap_data1 = self.bootstrap_system()
        initial_assertions = bootstrap_data["assertions_registered"]
        
        # Check status immediately
        response1 = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Bootstrap again (should not create duplicates)
        response2 = requests.post("http://127.0.0.1:8001/api/v1/reality/bootstrap", timeout=5)
        assert response2.status_code == 200
        
        data2 = response2.json()
        # Should register the same number (no duplicates)
        assert data2["assertions_registered"] == initial_assertions
        
        # Status should be consistent
        response3 = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response3.status_code == 200
        data3 = response3.json()
        
        # Should be in the same mode
        assert data1["system_state"]["mode"] == data3["system_state"]["mode"]
        assert data1["system_state"]["assertions_count"] == data3["system_state"]["assertions_count"]
    
    def test_governance_apis_degraded_but_accessible(self):
        """Test that governance APIs return degraded but accessible responses."""
        # Bootstrap the system
        self.bootstrap_system()
        
        # Test governance charter registry
        response = requests.get("http://127.0.0.1:8001/api/v1/governance/charter-registry", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        assert data["service"] == "governance_charter_registry"
        assert data["status"] == "degraded"
        assert "Reality system requires bootstrap" in data["message"]
        assert len(data["available_alternatives"]) > 0
        
        # Test intelligence summary
        response = requests.get("http://127.0.0.1:8001/api/v1/intelligence/summary", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        assert data["service"] == "intelligence_summary"
        assert data["status"] == "degraded"
        assert "Reality system requires bootstrap" in data["message"]
    
    def test_dashboard_routing_works(self):
        """Test that dashboard routing works correctly."""
        # Test main dashboard endpoint
        response = requests.get("http://127.0.0.1:8001/dashboard", timeout=5, allow_redirects=False)
        assert response.status_code == 307  # Redirect
        
        # Test dashboard fixed endpoint
        response = requests.get("http://127.0.0.1:8001/dashboard/fixed", timeout=5)
        assert response.status_code == 200
        assert len(response.text) > 1000  # Should have HTML content


if __name__ == "__main__":
    # Run tests manually
    test_instance = TestBootstrapSightedMode()
    
    print("🧪 Running Bootstrap Sighted Mode Tests")
    print("=" * 50)
    
    try:
        test_instance.test_bootstrap_registers_assertions(None)
        print("✅ Bootstrap registers assertions")
        
        test_instance.test_bootstrap_sighted_mode()
        print("✅ Bootstrap moves to sighted mode")
        
        test_instance.test_local_venue_respects_bootstrap()
        print("✅ Local venue respects bootstrap state")
        
        test_instance.test_bootstrap_persistence()
        print("✅ Bootstrap assertions persist")
        
        test_instance.test_governance_apis_degraded_but_accessible()
        print("✅ Governance APIs degraded but accessible")
        
        test_instance.test_dashboard_routing_works()
        print("✅ Dashboard routing works")
        
        print("\n🎉 All bootstrap sighted mode tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
