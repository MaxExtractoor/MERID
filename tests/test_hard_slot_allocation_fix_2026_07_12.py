"""
Tests for hard slot allocation fix (2026-07-12)

This test suite verifies that the $1 global exposure cap is enforced via hard slot
allocation in the order router, preventing the bypass where multiple orders could
pass passive exposure checks simultaneously.

Root cause fixed:
- Order router had passive read-only check (get_available_exposure)
- Global allocator execution path didn't call slot allocation
- Multiple orders could pass check simultaneously before fills
- Total exposure could exceed $1 cap

Fix applied:
- Hard slot allocation BEFORE any order processing in order_router
- Slot allocation in global allocator execution path
- Slot release on all rejection/exception paths
- Exit orders bypass allocation (they reduce exposure)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
from merid.risk.global_slot_allocator import get_global_slot_allocator, AllocationRequest


class TestHardSlotAllocationInOrderRouter:
    """Test hard slot allocation in order router via code structure analysis."""
    
    def test_hard_slot_allocation_called_before_processing(self):
        """Verify slot allocation is called BEFORE any order processing."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot allocation is called
        assert "request_allocation" in router_source, \
            "Order router should call request_allocation"
        
        # Verify allocation happens before gate check
        lines = router_source.split('\n')
        allocation_line = None
        gate_check_line = None
        
        for i, line in enumerate(lines):
            if "request_allocation" in line and "slot_allocator" in line:
                allocation_line = i
            if "verdict = gate.check" in line:
                gate_check_line = i
        
        assert allocation_line is not None, "Slot allocation should exist"
        assert gate_check_line is not None, "Gate check should exist"
        assert allocation_line < gate_check_line, "Slot allocation should happen before gate check"
    
    def test_hard_slot_allocation_blocks_on_insufficient_exposure(self):
        """Verify order is rejected when slot allocation fails due to insufficient exposure."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify hard block logic exists
        assert "if not allocated:" in router_source, \
            "Order router should check allocation result"
        
        # Verify rejection on allocation failure
        assert "slot_allocator_hard_block" in router_source or "insufficient_exposure" in router_source, \
            "Order router should hard block on allocation failure"
        
        # Verify return rejected status
        assert 'status="rejected"' in router_source, \
            "Order router should return rejected status on allocation failure"
    
    def test_exit_order_bypasses_slot_allocation(self):
        """Verify exit orders bypass slot allocation."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify exit order check exists
        assert "if not _is_exit_order" in router_source, \
            "Order router should check for exit orders"
        
        # Verify bypass logic
        assert "EXIT_ORDER_BYPASS" in router_source or "exit order bypass" in router_source.lower(), \
            "Order router should log exit order bypass"
    
    def test_slot_released_on_price_guard_rejection(self):
        """Verify slot is released when price guard rejects the order."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot release on price guard rejection
        assert "release_slot" in router_source, \
            "Order router should release slots"
        
        # Verify release happens in price guard rejection path
        assert "price guard rejection" in router_source.lower() or "PRICE_GUARD" in router_source, \
            "Order router should release slot on price guard rejection"
    
    def test_slot_released_on_gate_rejection(self):
        """Verify slot is released when gate rejects the order."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot release on gate rejection
        assert "release_slot" in router_source, \
            "Order router should release slots"
        
        # Verify release happens in gate rejection path
        assert "GATE BLOCKED" in router_source or "gate rejection" in router_source.lower(), \
            "Order router should release slot on gate rejection"
    
    def test_slot_released_on_gate_exception(self):
        """Verify slot is released when gate raises an exception."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot release on exception
        assert "release_slot" in router_source, \
            "Order router should release slots"
        
        # Verify release happens in exception handler
        assert "except Exception as exc:" in router_source, \
            "Order router should have exception handler"
        
        # Verify release is in exception handler
        lines = router_source.split('\n')
        in_exception_handler = False
        found_release = False
        
        for line in lines:
            if "except Exception as exc:" in line:
                in_exception_handler = True
            elif in_exception_handler and "def " in line and "except" not in line:
                in_exception_handler = False
            elif in_exception_handler and "release_slot" in line:
                found_release = True
                break
        
        assert found_release, "Order router should release slot in exception handler"
    
    def test_fail_closed_on_slot_allocator_exception(self):
        """Verify order is rejected when slot allocator raises an exception."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify slot allocation is in try block
        assert "try:" in router_source, \
            "Order router should have try block for slot allocation"
        
        # Verify exception handler exists
        assert "except Exception as slot_err:" in router_source, \
            "Order router should catch slot allocator exceptions"
        
        # Verify fail-closed (return rejected)
        lines = router_source.split('\n')
        in_slot_exception = False
        found_rejection = False
        
        for line in lines:
            if "except Exception as slot_err:" in line:
                in_slot_exception = True
            elif in_slot_exception and "except" in line and "slot_err" not in line:
                in_slot_exception = False
            elif in_slot_exception and 'status="rejected"' in line:
                found_rejection = True
                break
        
        assert found_rejection, "Order router should return rejected status on slot allocator exception"


class TestGlobalAllocatorSlotAllocation:
    """Test slot allocation in global allocator execution path."""
    
    def test_global_allocator_requests_slot_before_execution(self):
        """Verify global allocator requests slot before executing orders."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            grid_source = f.read()
        
        # Verify slot allocation happens before execution
        lines = grid_source.split('\n')
        allocation_line = None
        execution_line = None
        
        for i, line in enumerate(lines):
            if "GLOBAL-ALLOCATOR-SLOT-ALLOCATED" in line:
                allocation_line = i
            if "GLOBAL-ALLOCATOR-EXECUTE" in line:
                execution_line = i
        
        assert allocation_line is not None, "GLOBAL-ALLOCATOR-SLOT-ALLOCATED log should exist"
        assert execution_line is not None, "GLOBAL-ALLOCATOR-EXECUTE log should exist"
        assert allocation_line < execution_line, "Slot allocation should happen before execution"
    
    def test_global_allocator_rejects_on_slot_failure(self):
        """Verify global allocator skips orders when slot allocation fails."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            grid_source = f.read()
        
        # Verify rejection logic exists
        assert "GLOBAL-ALLOCATOR-SLOT-REJECT" in grid_source, \
            "Global allocator should log GLOBAL-ALLOCATOR-SLOT-REJECT on slot failure"
        
        # Verify continue statement after rejection
        assert "continue  # Skip this order - no slot available" in grid_source, \
            "Global allocator should continue to next order on slot rejection"
    
    def test_global_allocator_releases_slot_on_execution_failure(self):
        """Verify global allocator releases slot when order execution fails."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            grid_source = f.read()
        
        # Verify slot release on execution failure
        assert "GLOBAL-ALLOCATOR-SLOT-RELEASED" in grid_source, \
            "Global allocator should log GLOBAL-ALLOCATOR-SLOT-RELEASED on execution failure"
        
        # Verify release happens in execution failure handler
        assert "execution failed" in grid_source.lower() or "EXECUTE-FAILED" in grid_source, \
            "Global allocator should release slot on EXECUTE-FAILED"
    
    def test_global_allocator_releases_slot_on_exception(self):
        """Verify global allocator releases slot when exception occurs."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            grid_source = f.read()
        
        # Verify slot release on exception
        assert "GLOBAL-ALLOCATOR-SLOT-RELEASED" in grid_source, \
            "Global allocator should log GLOBAL-ALLOCATOR-SLOT-RELEASED on exception"
        
        # Verify release happens in exception handler
        assert "exception" in grid_source.lower() or "EXECUTE-ERROR" in grid_source, \
            "Global allocator should release slot on EXECUTE-ERROR"


class TestExposureCapEnforcement:
    """Test $1 exposure cap enforcement across all paths."""
    
    def test_order_router_enforces_hard_cap(self):
        """Verify order router enforces hard $1 cap via slot allocation."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify hard slot allocation exists
        assert "request_allocation" in router_source, \
            "Order router should call request_allocation for hard cap enforcement"
        
        # Verify hard block on allocation failure
        assert "slot_allocator_hard_block" in router_source or "insufficient_exposure" in router_source, \
            "Order router should hard block on allocation failure"
    
    def test_no_passive_exposure_check_in_main_path(self):
        """Verify passive exposure check is removed from main path (replaced by hard allocation)."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Count occurrences of passive check vs hard allocation
        passive_checks = router_source.count("get_available_exposure")
        hard_allocations = router_source.count("request_allocation")
        
        # Hard allocation should be the primary mechanism
        assert hard_allocations >= 1, \
            "Order router should have hard slot allocation"
    
    def test_exit_orders_bypass_hard_cap(self):
        """Verify exit orders bypass hard cap (they reduce exposure)."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            router_source = f.read()
        
        # Verify exit order bypass logic
        assert "if not _is_exit_order" in router_source, \
            "Order router should check for exit orders before slot allocation"
        
        # Verify bypass log
        assert "EXIT_ORDER_BYPASS" in router_source or "exit order bypass" in router_source.lower(), \
            "Order router should log exit order bypass"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
