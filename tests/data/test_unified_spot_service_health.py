"""
Unified Spot Service Health Log Tests

Tests that SPOT-HEALTH log is present in UnifiedSpotService.
"""
import pytest
import inspect


class TestUnifiedSpotServiceHealthLog:
    """Test SPOT-HEALTH log presence in UnifiedSpotService."""

    def test_spot_health_log_present(self):
        """Test that SPOT-HEALTH log is present in UnifiedSpotService."""
        try:
            from data.unified_spot_service import UnifiedSpotService
        except ImportError:
            # If import fails, skip this test
            pytest.skip("UnifiedSpotService import failed")
            return
        
        # Verify SPOT-HEALTH log is present in source code
        source = inspect.getsource(UnifiedSpotService._stream_loop)
        
        # Verify SPOT-HEALTH log is present
        assert "SPOT-HEALTH" in source or "[SPOT-HEALTH]" in source
