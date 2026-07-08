"""
Test for signal metadata fix (2026-07-08).

CRITICAL FIX: _kalshi_place_order now accepts and passes model_prob, edge_pct, confidence
to OrderIntent. These fields are required by order_router's _validate_signal_metadata function.

Before fix: OrderIntent was created without model_prob, edge_pct, confidence, causing
all orders to be rejected with "invalid_model_prob:None".

After fix: Signal metadata is propagated from agent_grid_15m through _kalshi_place_order
to OrderIntent, allowing orders to pass validation.
"""

import sys
import os
import inspect

# Add project root to path (go up 4 levels from tests/event_venues/kalshi to project root)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)


def test_kalshi_place_order_signature_has_signal_metadata_params():
    """Test that _kalshi_place_order signature includes model_prob, edge_pct, confidence."""
    
    # Read the kalshi_tools.py file to verify the signature
    kalshi_tools_path = os.path.join(project_root, "merid", "prediction", "kalshi_tools.py")
    
    with open(kalshi_tools_path, 'r') as f:
        content = f.read()
    
    # Verify that the function signature includes the new parameters
    # Look for the async def _kalshi_place_order line and check for the parameters
    assert "async def _kalshi_place_order(" in content, "_kalshi_place_order function not found"
    
    # Find the function definition block
    func_start = content.find("async def _kalshi_place_order(")
    func_block = content[func_start:func_start+500]  # Get the first 500 chars of the function
    
    # Verify new parameters are in the signature
    assert "model_prob: Optional[float] = None" in func_block, "model_prob parameter missing from _kalshi_place_order"
    assert "edge_pct: Optional[float] = None" in func_block, "edge_pct parameter missing from _kalshi_place_order"
    assert "confidence: Optional[float] = None" in func_block, "confidence parameter missing from _kalshi_place_order"
    
    print("✓ _kalshi_place_order has model_prob, edge_pct, confidence parameters")


def test_resolve_exit_policy_signature_fix():
    """Test that resolve_exit_policy signature is correct (no side, price_cents, minutes_to_expiry)."""
    
    # Read the order_router.py file to verify the signature
    order_router_path = os.path.join(project_root, "merid", "event_venues", "kalshi", "order_router.py")
    
    with open(order_router_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify that the function signature is correct
    assert "def resolve_exit_policy(" in content, "resolve_exit_policy function not found"
    
    # Find the function definition block
    func_start = content.find("def resolve_exit_policy(")
    func_block = content[func_start:func_start+300]  # Get the first 300 chars of the function
    
    # Verify correct parameters are in the signature
    assert "edge_result" in func_block, "edge_result parameter missing from resolve_exit_policy"
    assert "asset" in func_block, "asset parameter missing from resolve_exit_policy"
    assert "regime" in func_block, "regime parameter missing from resolve_exit_policy"
    assert "strip_context" in func_block, "strip_context parameter missing from resolve_exit_policy"
    
    # Verify old parameters are NOT present (this was the bug)
    assert "side=" not in func_block, "side parameter should NOT be in resolve_exit_policy signature"
    assert "price_cents=" not in func_block, "price_cents parameter should NOT be in resolve_exit_policy signature"
    assert "minutes_to_expiry=" not in func_block, "minutes_to_expiry parameter should NOT be in resolve_exit_policy signature"
    
    print("✓ resolve_exit_policy signature is correct (no side, price_cents, minutes_to_expiry)")


def test_agent_grid_15m_passes_signal_metadata():
    """Test that agent_grid_15m extracts and passes signal metadata."""
    
    # Read the agent_grid_15m.py file to verify the fix
    agent_grid_path = os.path.join(project_root, "merid", "prediction", "agent_grid_15m.py")
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify that signal metadata is extracted
    assert 'model_prob = signal.get("model_prob")' in content, "model_prob extraction missing from agent_grid_15m"
    assert 'edge_pct = signal.get("edge_pct")' in content, "edge_pct extraction missing from agent_grid_15m"
    assert 'confidence = signal.get("confidence")' in content, "confidence extraction missing from agent_grid_15m"
    
    # Verify that signal metadata is passed to _kalshi_place_order
    assert 'model_prob=model_prob' in content, "model_prob not passed to _kalshi_place_order"
    assert 'edge_pct=edge_pct' in content, "edge_pct not passed to _kalshi_place_order"
    assert 'confidence=confidence' in content, "confidence not passed to _kalshi_place_order"
    
    print("✓ agent_grid_15m extracts and passes signal metadata")


def test_kalshi_tools_passes_signal_metadata_to_orderintent():
    """Test that kalshi_tools passes signal metadata to OrderIntent."""
    
    # Read the kalshi_tools.py file to verify the fix
    kalshi_tools_path = os.path.join(project_root, "merid", "prediction", "kalshi_tools.py")
    
    with open(kalshi_tools_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify that OrderIntent is created with signal metadata
    assert 'model_prob=model_prob' in content, "model_prob not passed to OrderIntent in kalshi_tools"
    assert 'edge_pct=edge_pct' in content, "edge_pct not passed to OrderIntent in kalshi_tools"
    assert 'confidence=confidence' in content, "confidence not passed to OrderIntent in kalshi_tools"
    
    # Verify the comment explaining the fix is present
    assert "CRITICAL FIX: Pass model_prob, edge_pct, confidence from signal metadata" in content, \
        "Fix comment missing from kalshi_tools"
    
    print("✓ kalshi_tools passes signal metadata to OrderIntent")


if __name__ == "__main__":
    print("Running signal metadata fix tests...\n")
    
    test_kalshi_place_order_signature_has_signal_metadata_params()
    test_resolve_exit_policy_signature_fix()
    test_agent_grid_15m_passes_signal_metadata()
    test_kalshi_tools_passes_signal_metadata_to_orderintent()
    
    print("\n=== ALL TESTS PASSED ===")
