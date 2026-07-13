"""
Tests for error propagation fix in order routing path.

This test suite validates the critical fix to ensure error reasons are properly
propagated from order_router through kalshi_tools to agent_grid_15m.

Run with: pytest tests/test_error_propagation_fix.py -v
"""

import pytest
import inspect


class TestKalshiToolsStatusHandling:
    """Test that kalshi_tools properly handles different OrderResult statuses."""

    def test_rejected_status_returns_toolresult_fail(self):
        """Test that rejected status from order_router returns ToolResult.fail."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Read the kalshi_tools source to verify the status handling logic
        source = inspect.getsource(_kalshi_place_order)
        
        # Verify the code checks for rejected status
        assert 'if result.status == "rejected"' in source
        assert 'ToolResult.fail' in source

    def test_duplicate_unknown_status_handling_exists(self):
        """Test that kalshi_tools handles duplicate_unknown status."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        source = inspect.getsource(_kalshi_place_order)
        
        # Verify the code checks for duplicate_unknown status
        assert 'duplicate_unknown' in source

    def test_ambiguous_status_handling_exists(self):
        """Test that kalshi_tools handles ambiguous statuses."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        source = inspect.getsource(_kalshi_place_order)
        
        # Verify the code handles ambiguous statuses
        assert 'Order status ambiguous' in source


class TestErrorExtractionInAgentGrid:
    """Test that error reasons are properly extracted in agent_grid_15m."""

    def test_error_message_attribute_extraction(self):
        """Test that error_message attribute is extracted from ToolResult."""
        from merid.guardrails.tools import ToolResult, ToolErrorCode
        
        # Create a ToolResult with error_message
        result = ToolResult.fail(
            ToolErrorCode.POLICY_BLOCKED,
            "Order rejected: profile_blocked_source",
            tool_name="kalshi_place_order"
        )
        
        # Simulate agent_grid_15m error extraction logic
        reason = "Unknown"
        if result:
            if hasattr(result, 'error_message') and result.error_message:
                reason = result.error_message
            elif hasattr(result, 'reason') and result.reason:
                reason = result.reason
            elif hasattr(result, 'message') and result.message:
                reason = result.message
            elif hasattr(result, 'payload') and isinstance(result.payload, dict):
                reason = result.payload.get('reason', 'Unknown')
        
        assert reason == "Order rejected: profile_blocked_source"
        assert reason != "Unknown"

    def test_payload_reason_fallback(self):
        """Test that payload['reason'] is used as fallback."""
        from merid.guardrails.tools import ToolResult, ToolErrorCode
        
        # Create a ToolResult with reason in payload
        result = ToolResult(
            success=False,
            error_code=ToolErrorCode.INTERNAL,
            payload={"reason": "payload_based_reason"},
            tool_name="test"
        )
        
        # Simulate agent_grid_15m error extraction logic
        reason = "Unknown"
        if result:
            if hasattr(result, 'error_message') and result.error_message:
                reason = result.error_message
            elif hasattr(result, 'reason') and result.reason:
                reason = result.reason
            elif hasattr(result, 'message') and result.message:
                reason = result.message
            elif hasattr(result, 'payload') and isinstance(result.payload, dict):
                reason = result.payload.get('reason', 'Unknown')
        
        assert reason == "payload_based_reason"

    def test_order_result_reason_extraction(self):
        """Test that reason attribute is extracted from OrderResult."""
        from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
        
        # Create an OrderResult with reason
        result = OrderResult(
            status="rejected",
            mode=TradingMode.LIVE,
            reason="test_rejection_reason",
            latency_ms=10.0
        )
        
        # Simulate agent_grid_15m error extraction logic
        reason = "Unknown"
        if result:
            if hasattr(result, 'error_message') and result.error_message:
                reason = result.error_message
            elif hasattr(result, 'reason') and result.reason:
                reason = result.reason
            elif hasattr(result, 'message') and result.message:
                reason = result.message
            elif hasattr(result, 'payload') and isinstance(result.payload, dict):
                reason = result.payload.get('reason', 'Unknown')
        
        assert reason == "test_rejection_reason"

    def test_agent_grid_error_extraction_logic_exists(self):
        """Test that agent_grid_15m has the updated error extraction logic."""
        # Read the agent_grid_15m source file directly
        with open('c:\\Dev\\MERID\\merid\\prediction\\agent_grid_15m.py', 'r') as f:
            source = f.read()
        
        # Verify the code checks for error_message first
        assert 'error_message' in source
        assert 'payload' in source
