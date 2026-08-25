"""Tests for Kalshi API bypass fixes (2026-07-16).

These tests verify that all REST client bypasses in web/api/kalshi_api.py
are properly blocked and fail closed to prevent circumventing risk guards.

Bypasses fixed:
1. PASS8_SIM_FALLBACK in place_order - REST fallback removed
2. cancel_order REST fallback - executor now required
3. amend_order REST bypass - blocked entirely
4. batch_cancel_orders REST bypass - blocked entirely
"""

import pytest
import json
from fastapi import HTTPException


class TestPlaceOrderNoRestFallback:
    """Test that place_order does not fall back to REST client in any mode."""
    
    def test_place_order_rest_fallback_removed(self):
        """Verify PASS8_SIM_FALLBACK code path is removed from place_order."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.place_order)
        
        # Should NOT contain the old fallback code
        assert "[PASS8_SIM_FALLBACK]" not in source, \
            "PASS8_SIM_FALLBACK tag should be removed"
        assert "SIM/MOCK mode: Using REST fallback" not in source, \
            "REST fallback message should be removed"
        assert "rest.create_order" not in source, \
            "Direct rest.create_order call should be removed"
        
        # Should contain fail-closed error
        assert "FAIL CLOSED" in source or "fail closed" in source.lower(), \
            "Should have fail-closed comment"
        assert "SYSTEM_DEGRADED_EXECUTOR_UNAVAILABLE" in source, \
            "Should raise executor unavailable error"
    
    def test_place_order_blocks_when_router_unavailable(self):
        """Test that place_order blocks when route_order_async is unavailable."""
        # This is tested in test_execution_gate_fail_closed_order_paths.py
        # We just verify the structure here
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.place_order)
        
        # Should raise HTTPException 503 when router unavailable
        assert "HTTPException" in source, \
            "Should raise HTTPException"
        assert "503" in source, \
            "Should use 503 status code for degraded state"


class TestCancelOrderExecutorRequired:
    """Test that cancel_order requires executor and blocks REST fallback."""
    
    def test_cancel_order_rest_fallback_removed(self):
        """Verify cancel_order does not fall back to REST client."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.cancel_order)
        
        # Should NOT contain REST fallback
        assert "rest.cancel_order" not in source, \
            "Direct rest.cancel_order call should be removed"
        assert "_get_rest_client" not in source, \
            "Should not call _get_rest_client"
        
        # Should require executor
        assert "executor = _get_executor()" in source, \
            "Should get executor"
        assert "if not executor:" in source, \
            "Should check if executor is available"
    
    def test_cancel_order_blocks_when_executor_unavailable(self):
        """Test that cancel_order blocks when executor is unavailable."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.cancel_order)
        
        # Should raise HTTPException 503 when executor unavailable
        assert "HTTPException" in source, \
            "Should raise HTTPException"
        assert "503" in source, \
            "Should use 503 status code"
        assert "CANCEL_EXECUTOR_GUARD" in source, \
            "Should have cancel guard identifier"


class TestAmendOrderBlocked:
    """Test that amend_order is blocked entirely (must use cancel-replace)."""
    
    def test_amend_order_rest_bypass_removed(self):
        """Verify amend_order does not call REST client directly."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.amend_order)
        
        # Should NOT contain REST client call
        assert "rest.amend_order" not in source, \
            "Direct rest.amend_order call should be removed"
        assert "_get_rest_client" not in source, \
            "Should not call _get_rest_client"
        
        # Should be blocked
        assert "FAIL CLOSED" in source or "fail closed" in source.lower(), \
            "Should have fail-closed comment"
        assert "AMEND_EXECUTOR_GUARD" in source, \
            "Should have amend guard identifier"
    
    def test_amend_order_requires_cancel_replace(self):
        """Test that amend_order directs to cancel-replace through order_router."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.amend_order)
        
        # Should mention cancel-replace
        assert "cancel-replace" in source.lower(), \
            "Should mention cancel-replace as alternative"
        assert "order_router" in source.lower(), \
            "Should direct to order_router path"


class TestBatchCancelOrdersBlocked:
    """Test that batch_cancel_orders is blocked entirely."""
    
    def test_batch_cancel_rest_bypass_removed(self):
        """Verify batch_cancel_orders does not call REST client directly."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.batch_cancel_orders)
        
        # Should NOT contain REST client call
        assert "rest.batch_cancel_orders" not in source, \
            "Direct rest.batch_cancel_orders call should be removed"
        assert "_get_rest_client" not in source, \
            "Should not call _get_rest_client"
        
        # Should be blocked
        assert "FAIL CLOSED" in source or "fail closed" in source.lower(), \
            "Should have fail-closed comment"
        assert "BATCH_CANCEL_EXECUTOR_GUARD" in source, \
            "Should have batch cancel guard identifier"
    
    def test_batch_cancel_requires_individual_executor_cancels(self):
        """Test that batch_cancel directs to individual executor cancels."""
        from web.api import kalshi_api
        import inspect
        
        source = inspect.getsource(kalshi_api.batch_cancel_orders)
        
        # Should mention individual cancel
        assert "individual cancel" in source.lower(), \
            "Should mention individual cancel as alternative"
        assert "executor" in source.lower(), \
            "Should direct to executor path"


class TestBypassFixesIntegration:
    """Integration tests to verify all bypasses are fixed together."""
    
    def test_all_guards_use_503_status_code(self):
        """Verify all bypass guards use consistent 503 status code."""
        from web.api import kalshi_api
        import inspect
        
        functions_to_check = [
            kalshi_api.place_order,
            kalshi_api.cancel_order,
            kalshi_api.amend_order,
            kalshi_api.batch_cancel_orders,
        ]
        
        for func in functions_to_check:
            source = inspect.getsource(func)
            # All should have HTTPException with 503
            assert "HTTPException" in source, \
                f"{func.__name__} should raise HTTPException"
            assert "503" in source, \
                f"{func.__name__} should use 503 status code"
    
    def test_all_guards_have_unique_identifiers(self):
        """Verify all bypass guards have unique guard identifiers."""
        from web.api import kalshi_api
        import inspect
        
        guard_identifiers = {
            "place_order": "PASS8_REST_FALLBACK_GUARD",
            "cancel_order": "CANCEL_EXECUTOR_GUARD",
            "amend_order": "AMEND_EXECUTOR_GUARD",
            "batch_cancel_orders": "BATCH_CANCEL_EXECUTOR_GUARD",
        }
        
        for func_name, expected_guard in guard_identifiers.items():
            func = getattr(kalshi_api, func_name)
            source = inspect.getsource(func)
            assert expected_guard in source, \
                f"{func_name} should have guard identifier {expected_guard}"
    
    def test_all_guards_have_critical_severity(self):
        """Verify all bypass guards are marked as critical severity."""
        from web.api import kalshi_api
        import inspect
        
        functions_to_check = [
            kalshi_api.place_order,
            kalshi_api.cancel_order,
            kalshi_api.amend_order,
            kalshi_api.batch_cancel_orders,
        ]
        
        for func in functions_to_check:
            source = inspect.getsource(func)
            assert '"severity": "critical"' in source, \
                f"{func.__name__} should have critical severity"
    
    def test_all_guards_have_oncall_contact(self):
        """Verify all bypass guards direct to on-call."""
        from web.api import kalshi_api
        import inspect
        
        functions_to_check = [
            kalshi_api.place_order,
            kalshi_api.cancel_order,
            kalshi_api.amend_order,
            kalshi_api.batch_cancel_orders,
        ]
        
        for func in functions_to_check:
            source = inspect.getsource(func)
            assert '"contact": "#on-call"' in source, \
                f"{func.__name__} should direct to on-call"
    
    def test_all_guards_prevent_bypass(self):
        """Verify all guards explicitly prevent bypass in remediation."""
        from web.api import kalshi_api
        import inspect
        
        functions_to_check = [
            kalshi_api.place_order,
            kalshi_api.cancel_order,
            kalshi_api.amend_order,
            kalshi_api.batch_cancel_orders,
        ]
        
        for func in functions_to_check:
            source = inspect.getsource(func)
            assert "Do not attempt to bypass" in source or "bypass" in source.lower(), \
                f"{func.__name__} should explicitly prevent bypass in remediation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
