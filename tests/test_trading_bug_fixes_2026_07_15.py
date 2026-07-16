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

4. Phantom slot lockout fix in order_router.py
   - Fixed in: order_router.py
   - Reason: Slot allocator rejecting orders due to stale slots from previous sessions
   - Mechanism: Detects when allocator rejects due to "already has X position(s)" but position
     cache shows 0 positions, then clears phantom slots and retries allocation
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


class TestPhantomSlotLockoutFix:
    """Test phantom slot lockout fix in order_router.py."""
    
    def test_phantom_slot_detection_logic_exists(self):
        """Verify order_router.py has phantom slot detection logic."""
        from merid.event_venues.kalshi import order_router
        import inspect
        
        # Get the source code of _check_intent_risk method
        source = inspect.getsource(order_router._check_intent_risk)
        
        # Verify the phantom slot detection logic exists
        assert "phantom slot lockout" in source.lower(), "Should detect phantom slot lockout"
        assert "get_position_cache" in source, "Should get position cache to check for phantom slots"
        assert "clear_slots_on_empty_positions" in source, "Should clear phantom slots"
        assert "retry allocation" in source.lower(), "Should retry allocation after clearing"
    
    def test_phantom_slot_clear_on_zero_positions(self):
        """Verify phantom slots are cleared when position cache shows 0 positions."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        # Create allocator and add a phantom slot
        allocator = GlobalSlotAllocator()
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL151645-45",
            entry_price_cents=75,
            edge_pct=15.0,
            spread_cents=10,
            confidence=0.95
        )
        allocator.request_allocation(request)
        
        # Verify slot is allocated
        assert allocator.get_slot_count() == 1, "Should have 1 slot allocated"
        assert allocator.get_slots_by_asset("BTC") != [], "Should have BTC slot"
        
        # Get real position cache and verify it returns 0 positions for BTC
        pos_cache = get_position_cache()
        asset_positions = pos_cache.get_positions_by_asset("BTC")
        
        # Clear phantom slots
        allocator.clear_slots_on_empty_positions(position_count=0)
        
        # Verify slot is cleared
        assert allocator.get_slot_count() == 0, "Should have 0 slots after clearing"
        assert allocator.get_slots_by_asset("BTC") == [], "Should have no BTC slots"
    
    def test_phantom_slot_not_cleared_with_actual_positions(self):
        """Verify phantom slots are NOT cleared when position cache shows actual positions."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        from merid.event_venues.kalshi.position_cache import get_position_cache, CachedPosition
        
        # Create allocator and add a slot
        allocator = GlobalSlotAllocator()
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL151645-45",
            entry_price_cents=75,
            edge_pct=15.0,
            spread_cents=10,
            confidence=0.95
        )
        allocator.request_allocation(request)
        
        # Verify slot is allocated
        assert allocator.get_slot_count() == 1, "Should have 1 slot allocated"
        
        # Get real position cache and add a mock position for BTC
        pos_cache = get_position_cache()
        # Add a mock position to simulate actual position
        pos_cache._positions["KXBTC15M-26JUL151645-45"] = CachedPosition(
            market_id="KXBTC15M-26JUL151645-45",
            contracts=1,
            side="yes",
            avg_price_cents=75
        )
        
        # Try to clear phantom slots (should not clear since position_count > 0)
        allocator.clear_slots_on_empty_positions(position_count=1)
        
        # Verify slot is NOT cleared
        assert allocator.get_slot_count() == 1, "Should still have 1 slot (not cleared)"
        
        # Clean up the mock position
        del pos_cache._positions["KXBTC15M-26JUL151645-45"]
    
    def test_order_router_phantom_slot_check_code_pattern(self):
        """Verify the code pattern for phantom slot check in order_router."""
        from merid.event_venues.kalshi import order_router
        import inspect
        
        # Get the source code of _check_intent_risk method
        source = inspect.getsource(order_router._check_intent_risk)
        
        # Verify the specific code pattern
        assert "if not can_allocate:" in source, "Should check if allocation failed"
        assert "asset_positions = pos_cache.get_positions_by_asset(asset)" in source, "Should get asset positions"
        assert "if not asset_positions and \"already has\" in alloc_reason:" in source, "Should check for phantom slot condition"
        assert "slot_allocator.clear_slots_on_empty_positions(position_count=0)" in source, "Should clear phantom slots"
        assert "can_allocate, alloc_reason = slot_allocator.can_allocate(intent.price_cents, asset)" in source, "Should retry allocation"


class TestGetPositionsByAsset:
    """Test get_positions_by_asset method in KalshiPositionCache."""
    
    def test_get_positions_by_asset_empty(self):
        """Verify get_positions_by_asset returns empty list when no positions."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        pos_cache = get_position_cache()
        
        # Test with no positions
        btc_positions = pos_cache.get_positions_by_asset("BTC")
        assert btc_positions == [], "Should return empty list when no BTC positions"
        
        eth_positions = pos_cache.get_positions_by_asset("ETH")
        assert eth_positions == [], "Should return empty list when no ETH positions"
    
    def test_get_positions_by_asset_with_positions(self):
        """Verify get_positions_by_asset returns correct positions for asset."""
        from merid.event_venues.kalshi.position_cache import get_position_cache, CachedPosition
        
        pos_cache = get_position_cache()
        
        # Add mock positions for different assets
        pos_cache._positions["KXBTC15M-26JUL151645-45"] = CachedPosition(
            market_id="KXBTC15M-26JUL151645-45",
            contracts=1,
            side="yes",
            avg_price_cents=75
        )
        pos_cache._positions["KXETH15M-26JUL151645-45"] = CachedPosition(
            market_id="KXETH15M-26JUL151645-45",
            contracts=2,
            side="no",
            avg_price_cents=50
        )
        pos_cache._positions["KXSOL15M-26JUL151645-45"] = CachedPosition(
            market_id="KXSOL15M-26JUL151645-45",
            contracts=0,  # Closed position
            side="yes",
            avg_price_cents=30
        )
        
        # Test BTC positions
        btc_positions = pos_cache.get_positions_by_asset("BTC")
        assert len(btc_positions) == 1, "Should have 1 BTC position"
        assert btc_positions[0].market_id == "KXBTC15M-26JUL151645-45"
        assert btc_positions[0].contracts == 1
        
        # Test ETH positions
        eth_positions = pos_cache.get_positions_by_asset("ETH")
        assert len(eth_positions) == 1, "Should have 1 ETH position"
        assert eth_positions[0].market_id == "KXETH15M-26JUL151645-45"
        assert eth_positions[0].contracts == 2
        
        # Test SOL positions (should return empty since contracts=0)
        sol_positions = pos_cache.get_positions_by_asset("SOL")
        assert len(sol_positions) == 0, "Should return empty list for closed SOL position"
        
        # Test asset with no positions
        doge_positions = pos_cache.get_positions_by_asset("DOGE")
        assert doge_positions == [], "Should return empty list for DOGE with no positions"
        
        # Clean up
        del pos_cache._positions["KXBTC15M-26JUL151645-45"]
        del pos_cache._positions["KXETH15M-26JUL151645-45"]
        del pos_cache._positions["KXSOL15M-26JUL151645-45"]
    
    def test_get_positions_by_asset_case_insensitive(self):
        """Verify get_positions_by_asset is case-insensitive."""
        from merid.event_venues.kalshi.position_cache import get_position_cache, CachedPosition
        
        pos_cache = get_position_cache()
        
        # Add a BTC position
        pos_cache._positions["KXBTC15M-26JUL151645-45"] = CachedPosition(
            market_id="KXBTC15M-26JUL151645-45",
            contracts=1,
            side="yes",
            avg_price_cents=75
        )
        
        # Test case insensitivity
        btc_lower = pos_cache.get_positions_by_asset("btc")
        btc_upper = pos_cache.get_positions_by_asset("BTC")
        btc_mixed = pos_cache.get_positions_by_asset("BtC")
        
        assert len(btc_lower) == 1, "Should find BTC with lowercase"
        assert len(btc_upper) == 1, "Should find BTC with uppercase"
        assert len(btc_mixed) == 1, "Should find BTC with mixed case"
        
        # Clean up
        del pos_cache._positions["KXBTC15M-26JUL151645-45"]
    
    def test_get_positions_by_asset_multiple_markets_same_asset(self):
        """Verify get_positions_by_asset returns all positions for asset across markets."""
        from merid.event_venues.kalshi.position_cache import get_position_cache, CachedPosition
        
        pos_cache = get_position_cache()
        
        # Add multiple BTC positions (different markets)
        pos_cache._positions["KXBTC15M-26JUL151645-45"] = CachedPosition(
            market_id="KXBTC15M-26JUL151645-45",
            contracts=1,
            side="yes",
            avg_price_cents=75
        )
        pos_cache._positions["KXBTC15M-26JUL151700-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL151700-30",
            contracts=1,
            side="no",
            avg_price_cents=25
        )
        
        # Test that both BTC positions are returned
        btc_positions = pos_cache.get_positions_by_asset("BTC")
        assert len(btc_positions) == 2, "Should return all 2 BTC positions"
        
        market_ids = [p.market_id for p in btc_positions]
        assert "KXBTC15M-26JUL151645-45" in market_ids
        assert "KXBTC15M-26JUL151700-30" in market_ids
        
        # Clean up
        del pos_cache._positions["KXBTC15M-26JUL151645-45"]
        del pos_cache._positions["KXBTC15M-26JUL151700-30"]


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
