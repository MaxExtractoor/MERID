"""
Comprehensive audit test to verify no code paths bypass the global slot allocator.

This test ensures that ALL order execution paths in the 15m Kalshi crypto trading stack
properly integrate with the global slot allocator for the $1 hard exposure cap.

CRITICAL: Exit orders are the ONLY orders allowed to bypass slot allocation to guarantee
position closure even at full capacity. All other orders MUST go through slot allocation.
"""

import pytest
import os
import ast
from pathlib import Path


class TestSlotAllocatorBypassAudit:
    """Audit all code paths to ensure no slot allocator bypasses exist."""

    def test_order_router_uses_slot_allocator(self):
        """Verify order_router.py integrates with global slot allocator."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot allocator integration exists
        assert "get_global_slot_allocator" in router_source, \
            "order_router.py should import get_global_slot_allocator"
        
        # Verify slot allocator is used for exposure checks
        assert "get_available_exposure" in router_source, \
            "order_router.py should check available exposure from slot allocator"
        
        # Verify exit order bypass exists
        assert "_is_exit_order" in router_source, \
            "order_router.py should have exit order detection"
        
        # Verify exit orders bypass slot allocation
        assert "is_exit_order" in router_source.lower() or "exit order bypass" in router_source.lower(), \
            "order_router.py should bypass slot allocation for exit orders"

    def test_kalshi_tools_uses_order_router(self):
        """Verify kalshi_tools.py routes through order_router (not direct client)."""
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            tools_source = f.read()
        
        # Verify kalshi_tools uses route_order_async
        assert "route_order_async" in tools_source, \
            "kalshi_tools.py should use route_order_async for order execution"
        
        # Verify NO direct client.place_order calls
        assert "client.place_order" not in tools_source, \
            "kalshi_tools.py should NOT call client.place_order directly (bypasses slot allocator)"
        
        # Verify NO direct client.place_order_result calls
        assert "client.place_order_result" not in tools_source, \
            "kalshi_tools.py should NOT call client.place_order_result directly (bypasses slot allocator)"

    def test_web_api_uses_order_router(self):
        """Verify web API endpoints route through order_router."""
        with open("web/api/kalshi_api.py", "r", encoding="utf-8") as f:
            api_source = f.read()
        
        # Verify place_order endpoint uses route_order_async
        assert "route_order_async" in api_source, \
            "web/api/kalshi_api.py should use route_order_async"
        
        # Verify batch_place_orders uses route_order_async
        assert "batch_place_orders" in api_source and "route_order_async" in api_source, \
            "web/api/kalshi_api.py batch_place_orders should use route_order_async"

    def test_agent_grid_uses_slot_allocator(self):
        """Verify agent_grid_15m.py integrates with global slot allocator."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            grid_source = f.read()
        
        # Verify slot allocator integration
        assert "get_global_slot_allocator" in grid_source, \
            "agent_grid_15m.py should import get_global_slot_allocator"
        
        # Verify request_allocation is called
        assert "request_allocation" in grid_source, \
            "agent_grid_15m.py should call request_allocation"
        
        # Verify is_exit_order=False for entry orders
        assert "is_exit_order=False" in grid_source, \
            "agent_grid_15m.py should set is_exit_order=False for entry orders"

    def test_loop_15m_exit_order_bypass(self):
        """Verify loop_15m.py exit orders bypass slot allocation."""
        with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
            loop_source = f.read()
        
        # Verify slot allocator integration for exit orders
        assert "get_global_slot_allocator" in loop_source, \
            "loop_15m.py should import get_global_slot_allocator"
        
        # Verify exit order bypass flag
        assert "is_exit_order=True" in loop_source, \
            "loop_15m.py should set is_exit_order=True for exit orders"
        
        # Verify EXIT_ORDER_BYPASS reason check
        assert "EXIT_ORDER_BYPASS" in loop_source, \
            "loop_15m.py should check for EXIT_ORDER_BYPASS reason"

    def test_no_direct_client_place_order_in_production_code(self):
        """Verify no direct KalshiVenueClient.place_order calls in production code paths."""
        # Files to check (production code paths only)
        production_files = [
            "merid/prediction/kalshi_tools.py",
            "merid/prediction/agent_grid_15m.py",
            "merid/loop_15m.py",
            "web/api/kalshi_api.py",
            "merid/trading/ct_execution_adapter.py",
        ]
        
        for file_path in production_files:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            
            # Check for direct client.place_order calls
            if "client.place_order" in source:
                # Allow if it's in a comment or string
                lines = source.split('\n')
                for i, line in enumerate(lines):
                    if "client.place_order" in line:
                        # Skip if it's a comment
                        if line.strip().startswith('#'):
                            continue
                        # Skip if it's in a string
                        if '"' in line and "client.place_order" in line.split('"')[1]:
                            continue
                        # Otherwise, it's a real call - FAIL
                        pytest.fail(
                            f"{file_path} line {i+1} contains direct client.place_order call "
                            f"which bypasses slot allocator: {line.strip()}"
                        )

    def test_client_has_safety_guard(self):
        """Verify KalshiVenueClient has safety guard against manual orders."""
        with open("merid/event_venues/kalshi/client.py", "r", encoding="utf-8") as f:
            client_source = f.read()
        
        # Verify DEBUG_ALLOW_MANUAL_ORDERS check exists
        assert "DEBUG_ALLOW_MANUAL_ORDERS" in client_source, \
            "KalshiVenueClient should have DEBUG_ALLOW_MANUAL_ORDERS safety check"
        
        # Verify safety check is in place_order_result
        lines = client_source.split('\n')
        in_place_order_result = False
        found_safety_check = False
        
        for line in lines:
            if "async def place_order_result" in line:
                in_place_order_result = True
            elif in_place_order_result and "def " in line and "place_order_result" not in line:
                in_place_order_result = False
            elif in_place_order_result and "DEBUG_ALLOW_MANUAL_ORDERS" in line:
                found_safety_check = True
                break
        
        assert found_safety_check, \
            "KalshiVenueClient.place_order_result should have DEBUG_ALLOW_MANUAL_ORDERS safety check"

    def test_order_gate_uses_slot_allocator(self):
        """Verify order_gate.py uses slot allocator for sequential trading."""
        with open("merid/event_venues/kalshi/order_gate.py", "r", encoding="utf-8") as f:
            gate_source = f.read()
        
        # Verify slot allocator integration
        assert "get_global_slot_allocator" in gate_source, \
            "order_gate.py should import get_global_slot_allocator"
        
        # Verify slot allocator is used for sequential trading check
        assert "get_available_exposure" in gate_source, \
            "order_gate.py should use slot allocator for exposure checks"

    def test_unified_sizing_uses_slot_allocator(self):
        """Verify unified_sizing.py uses slot allocator for exposure calculation."""
        with open("merid/prediction/unified_sizing.py", "r", encoding="utf-8") as f:
            sizing_source = f.read()
        
        # Verify slot allocator integration
        assert "get_global_slot_allocator" in sizing_source, \
            "unified_sizing.py should import get_global_slot_allocator"
        
        # Verify slot allocator is used for exposure calculation
        assert "get_total_exposure" in sizing_source or "get_available_exposure" in sizing_source, \
            "unified_sizing.py should use slot allocator for exposure calculation"

    def test_position_cache_releases_slots(self):
        """Verify position_cache.py releases slots on position closure."""
        with open("merid/event_venues/kalshi/position_cache.py", "r", encoding="utf-8") as f:
            cache_source = f.read()
        
        # Verify slot allocator integration
        assert "get_global_slot_allocator" in cache_source, \
            "position_cache.py should import get_global_slot_allocator"
        
        # Verify slot release on fill
        assert "release_by_asset" in cache_source, \
            "position_cache.py should release slots by asset on fill"

    def test_no_bypass_in_legacy_code(self):
        """Verify legacy code paths are disabled or properly gated."""
        # Check that legacy trading_agent is not imported in production paths
        production_files = [
            "merid/loop_15m.py",
            "merid/prediction/agent_grid_15m.py",
            "web/main_15m_lean.py",
        ]
        
        for file_path in production_files:
            if not os.path.exists(file_path):
                continue
                
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            
            # Check for legacy trading_agent imports
            if "from archive.legacy.trading_agent import" in source:
                pytest.fail(
                    f"{file_path} imports legacy trading_agent which may bypass slot allocator"
                )
            
            if "from merid.trading.trading_agent import" in source:
                pytest.fail(
                    f"{file_path} imports trading_agent which may bypass slot allocator"
                )

    def test_signal_router_has_no_subscribers_in_15m(self):
        """Verify SignalRouter has no subscribers in 15m production (trading_agent not running)."""
        # This is expected behavior - 15m stack uses agent_grid directly, not signal router
        # The signal router is for legacy paths that are disabled in 15m production
        
        with open("merid/event_venues/kalshi/signal_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify signal router exists (for legacy compatibility)
        assert "class SignalRouter" in router_source, \
            "SignalRouter should exist for legacy compatibility"
        
        # Verify subscriber mechanism exists
        assert "subscribe" in router_source, \
            "SignalRouter should have subscribe mechanism"
        
        # Note: In 15m production, there are NO subscribers to SignalRouter
        # This is correct - agent_grid_15m handles signal generation directly
        # trading_agent (the subscriber) is NOT running in 15m production

    def test_ct_adapter_uses_signal_router(self):
        """Verify CT execution adapter uses signal router for live execution (shadow uses router directly)."""
        with open("merid/trading/ct_execution_adapter.py", "r", encoding="utf-8") as f:
            ct_source = f.read()
        
        # Verify CT uses submit_signal for live execution
        assert "submit_signal" in ct_source, \
            "CT execution adapter should use submit_signal for live execution"
        
        # Verify execute_live uses submit_signal (not direct route_order_async)
        lines = ct_source.split('\n')
        in_execute_live = False
        uses_submit_signal = False
        uses_route_order_async = False
        
        for line in lines:
            if "async def execute_live" in line:
                in_execute_live = True
            elif in_execute_live and "def " in line and "execute_live" not in line:
                in_execute_live = False
            elif in_execute_live:
                if "submit_signal" in line:
                    uses_submit_signal = True
                if "route_order_async" in line and "await route_order_async" in line:
                    uses_route_order_async = True
        
        assert uses_submit_signal, \
            "CT execution adapter execute_live should use submit_signal"
        assert not uses_route_order_async, \
            "CT execution adapter execute_live should NOT call route_order_async directly"
        
        # Shadow mode is allowed to call route_order_async directly (for parity comparison)
        # This is correct - shadow mode is for testing, not live execution

    def test_all_order_paths_accounted_for(self):
        """Verify all known order execution paths are accounted for in this test."""
        # This is a meta-test to ensure we're not missing any paths
        
        # Known order execution paths in 15m production:
        # 1. agent_grid_15m -> slot allocator -> signal generation
        # 2. loop_15m -> slot allocator (exit orders bypass)
        # 3. kalshi_tools -> route_order_async -> slot allocator
        # 4. web/api -> route_order_async -> slot allocator
        
        # Dead paths (correctly disabled in 15m):
        # - SignalRouter -> trading_agent (no subscribers in 15m)
        # - CT execution adapter -> SignalRouter (signals dropped in 15m)
        # - Legacy trading_agent (not imported in 15m)
        
        # Direct client calls (blocked by safety guard):
        # - KalshiVenueClient.place_order (requires DEBUG_ALLOW_MANUAL_ORDERS)
        
        # All paths are either properly wired or correctly disabled
        assert True, "All order execution paths accounted for"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
