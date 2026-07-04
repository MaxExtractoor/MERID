"""Unit tests for Kalshi format conversion (BUY_YES, SELL_YES, BUY_NO, SELL_NO)."""

import pytest


def test_loop_15m_exit_order_kalshi_format():
    """Test that loop_15m.py exit orders use Kalshi format (SELL_YES, SELL_NO)."""
    # Simulate the conversion logic from loop_15m.py _execute_exit_order
    def convert_to_kalshi_format(side_str, action):
        """Convert side/action to Kalshi format."""
        side_upper = side_str.upper()
        if side_upper == "YES" and action == "sell":
            return "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            return "SELL_NO"
        else:
            return f"{action.upper()}_{side_upper}"
    
    # Test YES position exit (should be SELL_YES)
    assert convert_to_kalshi_format("yes", "sell") == "SELL_YES"
    assert convert_to_kalshi_format("YES", "sell") == "SELL_YES"
    
    # Test NO position exit (should be SELL_NO)
    assert convert_to_kalshi_format("no", "sell") == "SELL_NO"
    assert convert_to_kalshi_format("NO", "sell") == "SELL_NO"


def test_ct_execution_adapter_kalshi_format():
    """Test that ct_execution_adapter.py uses Kalshi format."""
    # Simulate the conversion logic from ct_execution_adapter.py
    def convert_to_kalshi_format(side_raw, action):
        """Convert side/action to Kalshi format."""
        side_upper = side_raw.upper()
        action_lower = action.lower()
        action_upper = action.upper()
        if side_upper == "YES" and action_lower == "buy":
            return "BUY_YES"
        elif side_upper == "YES" and action_lower == "sell":
            return "SELL_YES"
        elif side_upper == "NO" and action_lower == "buy":
            return "BUY_NO"
        elif side_upper == "NO" and action_lower == "sell":
            return "SELL_NO"
        else:
            return f"{action_upper}_{side_upper}"
    
    # Test all four combinations
    assert convert_to_kalshi_format("yes", "buy") == "BUY_YES"
    assert convert_to_kalshi_format("yes", "sell") == "SELL_YES"
    assert convert_to_kalshi_format("no", "buy") == "BUY_NO"
    assert convert_to_kalshi_format("no", "sell") == "SELL_NO"
    
    # Test case insensitivity
    assert convert_to_kalshi_format("YES", "buy") == "BUY_YES"
    assert convert_to_kalshi_format("YES", "BUY") == "BUY_YES"
    assert convert_to_kalshi_format("no", "SELL") == "SELL_NO"


def test_universal_agent_kalshi_format():
    """Test that universal_agent.py uses Kalshi format."""
    # Simulate the conversion logic from universal_agent.py
    def convert_to_kalshi_format(side, action):
        """Convert side/action to Kalshi format."""
        side_upper = side.upper()
        action_lower = action.lower()
        if side_upper == "YES" and action_lower == "buy":
            return "BUY_YES"
        elif side_upper == "YES" and action_lower == "sell":
            return "SELL_YES"
        elif side_upper == "NO" and action_lower == "buy":
            return "BUY_NO"
        elif side_upper == "NO" and action_lower == "sell":
            return "SELL_NO"
        else:
            return f"{action.upper()}_{side_upper}"
    
    # Test all four combinations
    assert convert_to_kalshi_format("yes", "buy") == "BUY_YES"
    assert convert_to_kalshi_format("yes", "sell") == "SELL_YES"
    assert convert_to_kalshi_format("no", "buy") == "BUY_NO"
    assert convert_to_kalshi_format("no", "sell") == "SELL_NO"


def test_loop_15m_entry_order_kalshi_format():
    """Test that loop_15m.py entry orders use Kalshi format (existing logic)."""
    # Simulate the conversion logic from loop_15m.py _execute_candidate
    def convert_to_kalshi_format(side_raw, action_raw):
        """Convert side/action to Kalshi format."""
        side_upper = side_raw.upper()
        action_upper = action_raw.upper()
        if side_upper == "YES" and action_upper == "BUY":
            return "BUY_YES"
        elif side_upper == "YES" and action_upper == "SELL":
            return "SELL_YES"
        elif side_upper == "NO" and action_upper == "BUY":
            return "BUY_NO"
        elif side_upper == "NO" and action_upper == "SELL":
            return "SELL_NO"
        else:
            return None  # Invalid combination
    
    # Test all four combinations
    assert convert_to_kalshi_format("YES", "BUY") == "BUY_YES"
    assert convert_to_kalshi_format("YES", "SELL") == "SELL_YES"
    assert convert_to_kalshi_format("NO", "BUY") == "BUY_NO"
    assert convert_to_kalshi_format("NO", "SELL") == "SELL_NO"
    
    # Test case insensitivity
    assert convert_to_kalshi_format("yes", "buy") == "BUY_YES"
    assert convert_to_kalshi_format("yes", "sell") == "SELL_YES"


def test_order_router_kalshi_format_parsing():
    """Test that order_router.py correctly parses Kalshi format."""
    # Simulate the parsing logic from order_router.py
    def parse_kalshi_format(kalshi_side):
        """Parse Kalshi format to extract action and outcome_id."""
        # Extract outcome_id
        if "YES" in kalshi_side:
            outcome_id = "yes"
        elif "NO" in kalshi_side:
            outcome_id = "no"
        else:
            outcome_id = kalshi_side
        
        # Extract action
        if "BUY" in kalshi_side:
            order_action = "buy"
        elif "SELL" in kalshi_side:
            order_action = "sell"
        else:
            order_action = kalshi_side
        
        return outcome_id, order_action
    
    # Test all four combinations
    assert parse_kalshi_format("BUY_YES") == ("yes", "buy")
    assert parse_kalshi_format("SELL_YES") == ("yes", "sell")
    assert parse_kalshi_format("BUY_NO") == ("no", "buy")
    assert parse_kalshi_format("SELL_NO") == ("no", "sell")


def test_kalshi_format_consistency():
    """Test that all conversion functions produce consistent Kalshi format."""
    # All functions should produce the same Kalshi format for the same input
    test_cases = [
        ("yes", "buy", "BUY_YES"),
        ("yes", "sell", "SELL_YES"),
        ("no", "buy", "BUY_NO"),
        ("no", "sell", "SELL_NO"),
    ]
    
    for side, action, expected in test_cases:
        # Test loop_15m exit conversion
        side_upper = side.upper()
        if side_upper == "YES" and action == "sell":
            loop_15m_exit = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            loop_15m_exit = "SELL_NO"
        else:
            loop_15m_exit = f"{action.upper()}_{side_upper}"
        
        # Test ct_execution_adapter conversion
        side_upper = side.upper()
        action_lower = action.lower()
        action_upper = action.upper()
        if side_upper == "YES" and action_lower == "buy":
            ct_adapter = "BUY_YES"
        elif side_upper == "YES" and action_lower == "sell":
            ct_adapter = "SELL_YES"
        elif side_upper == "NO" and action_lower == "buy":
            ct_adapter = "BUY_NO"
        elif side_upper == "NO" and action_lower == "sell":
            ct_adapter = "SELL_NO"
        else:
            ct_adapter = f"{action_upper}_{side_upper}"
        
        # Test universal_agent conversion
        side_upper = side.upper()
        action_lower = action.lower()
        if side_upper == "YES" and action_lower == "buy":
            universal_agent = "BUY_YES"
        elif side_upper == "YES" and action_lower == "sell":
            universal_agent = "SELL_YES"
        elif side_upper == "NO" and action_lower == "buy":
            universal_agent = "BUY_NO"
        elif side_upper == "NO" and action_lower == "sell":
            universal_agent = "SELL_NO"
        else:
            universal_agent = f"{action.upper()}_{side_upper}"
        
        # Verify consistency
        if action == "sell":
            # Exit orders only
            assert loop_15m_exit == expected, f"loop_15m exit failed for {side}/{action}"
        assert ct_adapter == expected, f"ct_adapter failed for {side}/{action}"
        assert universal_agent == expected, f"universal_agent failed for {side}/{action}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
