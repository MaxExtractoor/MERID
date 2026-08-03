"""
Test single execution point architecture.

This test verifies that all order execution flows through a single point:
order_router.route_order_async, which is the only place where slot allocation
should occur. This prevents double allocation and ensures consistent slot state.

Critical fix (2026-07-12): Removed slot allocation from agent_grid_15m and
execution_subscriber to prevent double allocation bugs.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestSingleExecutionPoint:
    """Test that all execution paths go through order_router with single slot allocation."""
    
    def test_agent_grid_15m_no_direct_slot_allocation(self):
        """Verify agent_grid_15m execution path does not call slot_allocator.request_allocation directly.
        
        Note: agent_grid_15m DOES call slot_allocator in signal generation (line 10628) to reserve
        capacity before orders are created. This is intentional and not a bug. The execution path
        (global allocator execution around line 12637) should NOT call slot_allocator - that's the double allocation bug.
        """
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check the execution path (global allocator execution) - should NOT have slot allocation
        # Find the global allocator execution loop (where _kalshi_place_order is called)
        # NOTE: Anchor on the actual execution loop statement, not log markers, because
        # comments elsewhere in the file may mention GLOBAL-ALLOCATOR-EXECUTE.
        lines = source.split('\n')
        execution_path_lines = []
        
        for i, line in enumerate(lines):
            # Look for the global allocator execution loop
            if 'for order in chosen_orders' in line:
                # Capture a section around this line
                start = max(0, i - 5)
                end = min(len(lines), i + 200)
                execution_path_lines.extend(lines[start:end])
                break
        
        execution_path_source = '\n'.join(execution_path_lines)
        
        # Execution path should NOT have slot allocation calls
        assert "slot_allocator.request_allocation(" not in execution_path_source, \
            "agent_grid_15m execution path should not call slot_allocator.request_allocation directly"
        
        # Verify execution path calls _kalshi_place_order
        assert "_kalshi_place_order" in execution_path_source, \
            "agent_grid_15m execution path should call _kalshi_place_order"
        
        # Verify execution path does NOT call release_slot
        assert "slot_allocator.release_slot(" not in execution_path_source, \
            "agent_grid_15m execution path should not call slot_allocator.release_slot directly"
        
        print("✓ agent_grid_15m execution path has no direct slot allocation")
    
    def test_execution_subscriber_no_direct_slot_allocation(self):
        """Verify execution_subscriber does not call slot_allocator.request_allocation directly."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # execution_subscriber should NOT have slot allocation calls (check for actual function calls)
        assert "slot_allocator.request_allocation(" not in source, \
            "execution_subscriber should not call slot_allocator.request_allocation directly"
        
        # Verify it calls _kalshi_place_order
        assert "_kalshi_place_order" in source, \
            "execution_subscriber should call _kalshi_place_order"
        
        # Verify it does NOT call release_slot
        assert "slot_allocator.release_slot(" not in source, \
            "execution_subscriber should not call slot_allocator.release_slot directly"
        
        print("✓ execution_subscriber has no direct slot allocation")
    
    def test_kalshi_tools_routes_to_order_router(self):
        """Verify kalshi_tools._kalshi_place_order calls route_order_async."""
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # kalshi_tools should import and call route_order_async
        assert "from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async" in source, \
            "kalshi_tools should import route_order_async"
        
        assert "await route_order_async(intent)" in source, \
            "kalshi_tools should call route_order_async"
        
        # Verify kalshi_tools does NOT call slot_allocator directly
        assert "slot_allocator.request_allocation" not in source, \
            "kalshi_tools should not call slot_allocator.request_allocation directly"
        
        print("✓ kalshi_tools routes to order_router")
    
    def test_order_router_has_slot_allocation(self):
        """Verify order_router.route_order_async has slot allocation."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # order_router should have slot allocation
        assert "slot_allocator.request_allocation" in source, \
            "order_router should call slot_allocator.request_allocation"
        
        # order_router should have slot release on rejection paths
        assert "slot_allocator.release_slot" in source, \
            "order_router should call slot_allocator.release_slot"
        
        # Verify it uses _is_exit_order for unified detection
        assert "_is_exit_order(intent)" in source, \
            "order_router should use _is_exit_order for unified exit order detection"
        
        print("✓ order_router has slot allocation and release")
    
    def test_source_whitelist_compliance(self):
        """Verify kalshi_tools uses proper source attribution."""
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify source attribution logic
        assert 'source="merid.prediction.agent_grid_15m" if _agent_name and "15M" in _agent_name.upper() else "kalshi_tools"' in source, \
            "kalshi_tools should use proper source attribution for whitelist compliance"
        
        print("✓ kalshi_tools uses proper source attribution")
    
    def test_no_double_allocation_flow(self):
        """Verify the execution flow prevents double allocation.
        
        Note: agent_grid_15m calls slot_allocator in signal generation (line 10628) to reserve
        capacity. This is intentional. The execution path (collect_order_candidate) should NOT
        call slot_allocator - that's the double allocation bug we fixed.
        """
        # Expected flow:
        # agent_grid_15m signal generation → slot_allocator.request_allocation (RESERVATION)
        # agent_grid_15m execution → kalshi_tools._kalshi_place_order → order_router.route_order_async
        #                                                                  → slot_allocator.request_allocation (ALLOCATION)
        
        # Verify agent_grid_15m execution path does not allocate (check for actual function calls)
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            agent_grid_source = f.read()
        
        # Find the collect_order_candidate method
        lines = agent_grid_source.split('\n')
        in_execution_path = False
        execution_path_lines = []
        
        for i, line in enumerate(lines):
            if 'def collect_order_candidate' in line:
                in_execution_path = True
            elif in_execution_path and line.strip().startswith('def '):
                # End of method
                break
            elif in_execution_path:
                execution_path_lines.append(line)
        
        execution_path_source = '\n'.join(execution_path_lines)
        
        assert "slot_allocator.request_allocation(" not in execution_path_source
        
        # Verify kalshi_tools does not allocate (check for actual function calls)
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            kalshi_tools_source = f.read()
        assert "slot_allocator.request_allocation(" not in kalshi_tools_source
        
        # Verify order_router DOES allocate
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            order_router_source = f.read()
        assert "slot_allocator.request_allocation(" in order_router_source
        
        print("✓ No double allocation in execution flow")
    
    def test_slot_release_centralized_in_order_router(self):
        """Verify slot release is centralized in order_router."""
        # agent_grid_15m should not release slots (check for actual function calls)
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            agent_grid_source = f.read()
        assert "slot_allocator.release_slot(" not in agent_grid_source
        
        # execution_subscriber should not release slots (check for actual function calls)
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            execution_subscriber_source = f.read()
        assert "slot_allocator.release_slot(" not in execution_subscriber_source
        
        # kalshi_tools should not release slots (check for actual function calls)
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            kalshi_tools_source = f.read()
        assert "slot_allocator.release_slot(" not in kalshi_tools_source
        
        # order_router should release slots
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            order_router_source = f.read()
        assert "slot_allocator.release_slot(" in order_router_source
        
        print("✓ Slot release centralized in order_router")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
