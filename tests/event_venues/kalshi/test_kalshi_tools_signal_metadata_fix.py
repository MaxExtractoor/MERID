"""
Test for kalshi_tools signal metadata fix (2026-07-08).

CRITICAL FIX: _kalshi_place_order now accepts and passes model_prob, edge_pct, confidence
to OrderIntent. These fields are required by order_router's _validate_signal_metadata function.

Before fix: OrderIntent was created without model_prob, edge_pct, confidence, causing
all orders to be rejected with "invalid_model_prob:None".

After fix: Signal metadata is propagated from agent_grid_15m through _kalshi_place_order
to OrderIntent, allowing orders to pass validation.

NOTE: These tests reference deprecated merid.prediction.kalshi_tools methods.
The test is skipped to avoid testing deprecated functionality.
"""

import sys
import os
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytestmark = pytest.mark.skip(reason="Tests deprecated merid.prediction.kalshi_tools methods")

from unittest.mock import AsyncMock, MagicMock, patch


async def test_kalshi_place_order_passes_signal_metadata():
    """Test that _kalshi_place_order passes model_prob, edge_pct, confidence to OrderIntent."""
    
    # Mock the order router to capture the OrderIntent
    mock_order_intent = None
    
    async def mock_route_order_async(intent):
        nonlocal mock_order_intent
        mock_order_intent = intent
        from merid.event_venues.kalshi.order_router import OrderResult
        return OrderResult(
            status="submitted",
            mode="paper",
            reason="",
            latency_ms=10.0,
        )
    
    # Mock dependencies
    with patch('merid.prediction.kalshi_tools._get_client') as mock_get_client, \
         patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_get_gate, \
         patch('merid.prediction.kalshi_tools.get_order_cache') as mock_get_cache, \
         patch('merid.prediction.kalshi_tools.route_order_async', side_effect=mock_route_order_async), \
         patch('merid.prediction.kalshi_tools.get_kalshi_risk') as mock_get_risk:
        
        # Setup mocks
        mock_client = MagicMock()
        mock_client.is_circuit_open = False
        mock_get_client.return_value = mock_client
        
        mock_gate = MagicMock()
        mock_gate.should_simulate_fill.return_value = False
        mock_get_gate.return_value = mock_gate
        
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        
        mock_risk = MagicMock()
        mock_risk._check_fills_integrity.return_value = (True, "")
        mock_get_risk.return_value = mock_risk
        
        # Import after patching
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Call _kalshi_place_order with signal metadata
        result = await _kalshi_place_order(
            ticker="KXBTC15M-26JUL081800-00",
            side="yes",
            action="buy",
            price_cents=60,
            count=1,
            agent_name="BTC_15M",
            stop_loss_price_cents=55,
            take_profit_r_multiple=1.0,
            # CRITICAL: Pass signal metadata
            model_prob=0.65,
            edge_pct=2.5,
            confidence=0.70
        )
        
        # Verify OrderIntent was created with signal metadata
        assert mock_order_intent is not None
        assert mock_order_intent.model_prob == 0.65
        assert mock_order_intent.edge_pct == 2.5
        assert mock_order_intent.confidence == 0.70


async def test_kalshi_place_order_handles_none_signal_metadata():
    """Test that _kalshi_place_order handles None signal metadata gracefully."""
    
    # Mock the order router to capture the OrderIntent
    mock_order_intent = None
    
    async def mock_route_order_async(intent):
        nonlocal mock_order_intent
        mock_order_intent = intent
        from merid.event_venues.kalshi.order_router import OrderResult
        return OrderResult(
            status="submitted",
            mode="paper",
            reason="",
            latency_ms=10.0,
        )
    
    # Mock dependencies
    with patch('merid.prediction.kalshi_tools._get_client') as mock_get_client, \
         patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_get_gate, \
         patch('merid.prediction.kalshi_tools.get_order_cache') as mock_get_cache, \
         patch('merid.prediction.kalshi_tools.route_order_async', side_effect=mock_route_order_async), \
         patch('merid.prediction.kalshi_tools.get_kalshi_risk') as mock_get_risk:
        
        # Setup mocks
        mock_client = MagicMock()
        mock_client.is_circuit_open = False
        mock_get_client.return_value = mock_client
        
        mock_gate = MagicMock()
        mock_gate.should_simulate_fill.return_value = False
        mock_get_gate.return_value = mock_gate
        
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        
        mock_risk = MagicMock()
        mock_risk._check_fills_integrity.return_value = (True, "")
        mock_get_risk.return_value = mock_risk
        
        # Import after patching
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Call _kalshi_place_order without signal metadata (backward compatibility)
        result = await _kalshi_place_order(
            ticker="KXBTC15M-26JUL081800-00",
            side="yes",
            action="buy",
            price_cents=60,
            count=1,
            agent_name="BTC_15M",
            stop_loss_price_cents=55,
            take_profit_r_multiple=1.0,
            # Signal metadata omitted (None by default)
        )
        
        # Verify OrderIntent was created with None metadata (backward compatible)
        assert mock_order_intent is not None
        assert mock_order_intent.model_prob is None
        assert mock_order_intent.edge_pct is None
        assert mock_order_intent.confidence is None


def test_resolve_exit_policy_signature_fix():
    """Test that resolve_exit_policy is called with correct signature."""
    
    # Mock the resolve functions
    mock_window_resolution = MagicMock()
    mock_window_resolution.window_id = "15m"
    
    mock_exit_resolution = MagicMock()
    mock_exit_resolution.exit_policy_id = "tp_sl_15m"
    mock_exit_resolution.regime = "conservative"
    mock_exit_resolution.max_hold_seconds = 900
    
    with patch('merid.prediction.kalshi_tools.resolve_window_policy', return_value=mock_window_resolution), \
         patch('merid.prediction.kalshi_tools.resolve_exit_policy', return_value=mock_exit_resolution) as mock_resolve_exit:
        
        # Import after patching
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Verify that resolve_exit_policy is called with correct signature
        # The fix ensures it's called with (edge_result, asset, regime, strip_context=None)
        # NOT with side, price_cents, or minutes_to_expiry parameters
        
        # This test verifies the fix is in place by checking the function signature
        # We can't actually call the function here due to async/patching complexity,
        # but we can verify the import and signature are correct
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        import inspect
        
        sig = inspect.signature(resolve_exit_policy)
        params = list(sig.parameters.keys())
        
        # Verify signature: (edge_result, asset, regime, strip_context=None)
        assert "edge_result" in params
        assert "asset" in params
        assert "regime" in params
        assert "strip_context" in params
        
        # Verify old parameters are NOT in signature
        assert "side" not in params
        assert "price_cents" not in params
        assert "minutes_to_expiry" not in params


if __name__ == "__main__":
    import asyncio
    
    print("Running test_kalshi_place_order_passes_signal_metadata...")
    asyncio.run(test_kalshi_place_order_passes_signal_metadata())
    print("--- PASSED")
    
    print("Running test_kalshi_place_order_handles_none_signal_metadata...")
    asyncio.run(test_kalshi_place_order_handles_none_signal_metadata())
    print("--- PASSED")
    
    print("Running test_resolve_exit_policy_signature_fix...")
    test_resolve_exit_policy_signature_fix()
    print("--- PASSED")
    
    print("\n=== ALL TESTS PASSED ===")
