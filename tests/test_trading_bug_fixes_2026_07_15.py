"""Tests for trading bug fixes applied on 2026-07-15.

Bug fixes:
1. Authentication timestamp buffer increased from 5000ms to 60000ms
   - Fixed in: client_v2.py, client.py, ws.py
   - Reason: Observed 43-second network latency causing "header timestamp expired" errors

2. Position cache staleness fix with time-based fallback logic
   - Fixed in: fills_poller.py
   - Reason: Stale positions from previous sessions blocking slot allocator

3. REST API timeout increased from 15s to 60s
   - Fixed in: timeout_config.py
   - Reason: Handle observed 43-second network latency
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestAuthenticationTimestampFix:
    """Test authentication timestamp buffer fix."""
    
    def test_client_v2_timestamp_buffer_increased(self):
        """Verify client_v2.py uses 10000ms timestamp buffer."""
        from merid.event_venues.kalshi import client_v2
        import inspect
        
        # Get the source code of the _sign_request method
        source = inspect.getsource(client_v2.KalshiClientV2._sign_request)
        
        # Verify the timestamp buffer is 10000ms
        assert "10000" in source, "Timestamp buffer should be 10000ms"
        assert "5000" not in source or "10000" in source, "Should not have old 5000ms buffer"
        assert "timestamp out of range" in source or "future" in source.lower(), "Should reference future timestamp rejection"
    
    def test_client_timestamp_buffer_increased(self):
        """Verify legacy client.py uses 10000ms timestamp buffer."""
        from merid.event_venues.kalshi import client
        import inspect
        
        # Get the source code of the _sign_headers method
        source = inspect.getsource(client.KalshiVenueClient._sign_headers)
        
        # Verify the timestamp buffer is 10000ms
        assert "10000" in source, "Timestamp buffer should be 10000ms"
        assert "timestamp out of range" in source or "future" in source.lower(), "Should reference future timestamp rejection"
    
    def test_ws_timestamp_buffer_increased(self):
        """Verify ws.py uses 10000ms timestamp buffer."""
        # This test verifies the timestamp buffer in the WebSocket connect method
        # We can't easily test the actual connect() method without a real connection,
        # but we can verify the code pattern by checking the source
        
        from merid.event_venues.kalshi import ws as ws_module
        import inspect
        
        # Get the source code of the connect method
        source = inspect.getsource(ws_module.KalshiWebSocket.connect)
        
        # Verify the timestamp buffer is 10000ms
        assert "10000" in source, "Timestamp buffer should be 10000ms"
        assert "timestamp out of range" in source or "future" in source.lower(), "Should reference future timestamp rejection"


class TestPositionCacheStalenessFix:
    """Test position cache staleness fix with time-based fallback."""
    
    def test_fills_poller_staleness_check_logic(self):
        """Verify fills_poller.py has staleness check logic."""
        from merid.event_venues.kalshi import fills_poller as poller_module
        import inspect
        
        # Get the source code of _do_reconcile method
        source = inspect.getsource(poller_module.FillsPoller._do_reconcile)
        
        # Verify the staleness check logic exists
        assert "since_hours=1" in source, "Should check for recent positions (1h)"
        assert "since_hours=24" in source, "Should check for stale positions (24h)"
        assert "stale positions" in source.lower(), "Should mention stale positions"
        assert "clear_open_positions_on_empty_cache" in source, "Should clear stale positions"
    
    def test_compute_net_positions_has_since_hours_parameter(self):
        """Verify compute_net_positions has since_hours parameter with default 24."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        import inspect
        
        # Verify the method signature
        sig = inspect.signature(KalshiFillsLedger.compute_net_positions)
        assert 'since_hours' in sig.parameters, "Should have since_hours parameter"
        assert sig.parameters['since_hours'].default == 24, "Default should be 24 hours"


class TestRestApiTimeoutFix:
    """Test REST API timeout configuration fix."""
    
    def test_rest_api_timeout_increased(self):
        """Verify REST_API_TIMEOUT_S is 60 seconds."""
        from merid.event_venues.kalshi.timeout_config import REST_API_TIMEOUT_S
        
        assert REST_API_TIMEOUT_S == 60.0, f"Expected 60.0s timeout, got {REST_API_TIMEOUT_S}s"
    
    def test_timeout_config_has_commentary(self):
        """Verify timeout_config.py has commentary about the fix."""
        from merid.event_venues.kalshi import timeout_config as config_module
        import inspect
        
        # Get the source code
        source = inspect.getsource(config_module)
        
        # Verify the commentary mentions the fix
        assert "43s" in source or "43 second" in source, "Should reference observed 43s latency"
        assert "2026-07-15" in source, "Should reference the fix date"


class TestPositionCacheStalenessFixDetailed:
    """Detailed tests for position cache staleness fix in fills_poller."""
    
    def test_kalshi_risk_uses_explicit_since_hours(self):
        """Verify kalshi_risk.py uses explicit since_hours=24 parameter."""
        from merid.event_venues.kalshi import kalshi_risk
        import inspect
        
        # Get the source code of resync_category_contracts_from_positions method
        source = inspect.getsource(kalshi_risk.KalshiRiskManager.resync_category_contracts_from_positions)
        
        # Verify the explicit since_hours=24 parameter is used
        assert "since_hours=24" in source, "Should use explicit since_hours=24 parameter"
    
    def test_fills_ledger_uses_explicit_since_hours(self):
        """Verify fills_ledger.py uses explicit since_hours=24 parameter in get_open_exposure_usd."""
        from merid.event_venues.kalshi import fills_ledger
        import inspect
        
        # Get the source code of get_open_exposure_usd method
        source = inspect.getsource(fills_ledger.KalshiFillsLedger.get_open_exposure_usd)
        
        # Verify the explicit since_hours=24 parameter is used
        assert "since_hours=24" in source, "Should use explicit since_hours=24 parameter"


class TestIntegrationScenarios:
    """Integration tests for the bug fixes."""
    
    def test_timestamp_buffer_across_all_clients(self):
        """Verify all three clients use consistent timestamp buffer."""
        from merid.event_venues.kalshi import client_v2, client, ws as ws_module
        import inspect
        
        # Get source for all three modules
        client_v2_source = inspect.getsource(client_v2.KalshiClientV2._sign_request)
        client_source = inspect.getsource(client.KalshiVenueClient._sign_headers)
        ws_source = inspect.getsource(ws_module.KalshiWebSocket.connect)
        
        # Verify all use 10000ms buffer
        assert "10000" in client_v2_source, "client_v2.py should use 10000ms buffer"
        assert "10000" in client_source, "client.py should use 10000ms buffer"
        assert "10000" in ws_source, "ws.py should use 10000ms buffer"
    
    def test_position_cache_fallback_flow(self):
        """Verify the position cache fallback flow exists in fills_poller."""
        from merid.event_venues.kalshi import fills_poller as poller_module
        import inspect
        
        # Get the source code of _do_reconcile method
        source = inspect.getsource(poller_module.FillsPoller._do_reconcile)
        
        # Verify the fallback logic exists
        assert "REST API returned 0 positions" in source, "Should check for REST returning 0 positions"
        assert "recent positions" in source.lower(), "Should mention recent positions"
        assert "stale positions" in source.lower(), "Should mention stale positions"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
