"""
Tests for exit_order_utils module.

Tests the shared exit order detection logic to ensure consistency
across order_router.py, position_cache.py, and other components.
"""

import pytest
from merid.event_venues.kalshi.exit_order_utils import (
    is_exit_order_from_source,
    is_exit_order_from_action,
    EXIT_ORDER_MARKERS,
)


class TestExitOrderFromSource:
    """Test is_exit_order_from_source function."""
    
    def test_take_profit_marker_detected(self):
        """Test that 'take_profit' marker is detected."""
        assert is_exit_order_from_source("take_profit") is True
        assert is_exit_order_from_source("position_monitor_take_profit") is True
        assert is_exit_order_from_source("TAKE_PROFIT") is True  # case insensitive
    
    def test_stop_loss_marker_detected(self):
        """Test that 'stop_loss' marker is detected."""
        assert is_exit_order_from_source("stop_loss") is True
        assert is_exit_order_from_source("trailing_stop_loss") is True
        assert is_exit_order_from_source("STOP_LOSS") is True  # case insensitive
    
    def test_exit_marker_detected(self):
        """Test that 'exit' marker is detected."""
        assert is_exit_order_from_source("exit") is True
        assert is_exit_order_from_source("position_monitor_exit") is True
        assert is_exit_order_from_source("EXIT") is True  # case insensitive
    
    def test_close_marker_detected(self):
        """Test that 'close' marker is detected."""
        assert is_exit_order_from_source("close") is True
        assert is_exit_order_from_source("position_close") is True
        assert is_exit_order_from_source("CLOSE") is True  # case insensitive
    
    def test_ratchet_marker_detected(self):
        """Test that 'ratchet' marker is detected."""
        assert is_exit_order_from_source("ratchet") is True
        assert is_exit_order_from_source("ratchet_floor") is True
        assert is_exit_order_from_source("RATCHET") is True  # case insensitive
    
    def test_trim_marker_detected(self):
        """Test that 'trim' marker is detected."""
        assert is_exit_order_from_source("trim") is True
        assert is_exit_order_from_source("ratchet_trim") is True
        assert is_exit_order_from_source("TRIM") is True  # case insensitive
    
    def test_scale_out_marker_detected(self):
        """Test that 'scale_out' marker is detected."""
        assert is_exit_order_from_source("scale_out") is True
        assert is_exit_order_from_source("SCALE_OUT") is True  # case insensitive
    
    def test_micro_scalp_marker_detected(self):
        """Test that 'micro_scalp' marker is detected."""
        assert is_exit_order_from_source("micro_scalp") is True
        assert is_exit_order_from_source("MICRO_SCALP") is True  # case insensitive
    
    def test_entry_order_not_detected(self):
        """Test that entry orders are not detected as exits."""
        assert is_exit_order_from_source("entry") is False
        assert is_exit_order_from_source("signal") is False
        assert is_exit_order_from_source("agent_grid") is False
        assert is_exit_order_from_source("strategy") is False
    
    def test_sell_action_not_detected_without_marker(self):
        """Test that sell action without exit marker is not detected as exit.
        
        CRITICAL: This prevents NO entry orders from bypassing slot allocation.
        """
        assert is_exit_order_from_source("sell") is False
        assert is_exit_order_from_source("sell_no") is False
        assert is_exit_order_from_source("short") is False
    
    def test_no_entry_order_not_detected(self):
        """Test that NO entry orders are not detected as exits.
        
        CRITICAL: NO entry orders (selling NO contracts to open short position)
        must allocate slots to enforce $1 exposure cap.
        """
        assert is_exit_order_from_source("no_entry") is False
        assert is_exit_order_from_source("short_entry") is False
    
    def test_empty_source_not_detected(self):
        """Test that empty source is not detected as exit."""
        assert is_exit_order_from_source("") is False
        assert is_exit_order_from_source(None) is False
    
    def test_all_exit_markers_list(self):
        """Test that EXIT_ORDER_MARKERS contains all expected markers."""
        expected_markers = [
            "take_profit",
            "stop_loss",
            "micro_scalp",
            "exit",
            "close",
            "ratchet",
            "trim",
            "scale_out",
            "hedge",  # SEV-0 FIX: Hedge orders reduce net exposure
            "hedge_engine",  # SEV-0 FIX: HEDGE_ENGINE source marker
            "offset_hedging",  # SEV-0 FIX: offset_hedging source marker
            "position_monitor_exit",  # CRITICAL FIX (2026-07-20): PositionMonitor exit orders
            "resting_bracket",  # CRITICAL FIX (2026-08-01): Bracket orders are exit orders
        ]
        assert set(EXIT_ORDER_MARKERS) == set(expected_markers)

    def test_hedge_marker_detected(self):
        """Test that 'hedge' marker is detected (SEV-0 FIX)."""
        assert is_exit_order_from_source("hedge") is True
        assert is_exit_order_from_source("offset_hedging") is True
        assert is_exit_order_from_source("HEDGE") is True  # case insensitive

    def test_hedge_engine_marker_detected(self):
        """Test that 'hedge_engine' marker is detected (SEV-0 FIX)."""
        assert is_exit_order_from_source("hedge_engine") is True
        assert is_exit_order_from_source("HEDGE_ENGINE") is True  # case insensitive


class TestExitOrderFromAction:
    """Test is_exit_order_from_action function."""
    
    def test_source_marker_overrides_action(self):
        """Test that source marker is checked first, regardless of action."""
        # Even with 'sell' action, if source has exit marker, it's an exit
        assert is_exit_order_from_action("sell", "take_profit") is True
        assert is_exit_order_from_action("buy", "stop_loss") is True
    
    def test_sell_action_without_source_not_exit(self):
        """Test that sell action without source marker is not exit.
        
        CRITICAL: This prevents NO entry orders from bypassing slot allocation.
        """
        assert is_exit_order_from_action("sell", None) is False
        assert is_exit_order_from_action("sell", "") is False
        assert is_exit_order_from_action("sell", "entry") is False
    
    def test_buy_action_without_source_not_exit(self):
        """Test that buy action without source marker is not exit."""
        assert is_exit_order_from_action("buy", None) is False
        assert is_exit_order_from_action("buy", "") is False
        assert is_exit_order_from_action("buy", "entry") is False
    
    def test_no_entry_order_not_detected(self):
        """Test that NO entry orders are not detected as exits.
        
        CRITICAL: NO entry orders (selling NO contracts to open short position)
        must allocate slots to enforce $1 exposure cap.
        """
        assert is_exit_order_from_action("sell", "no_entry") is False
        assert is_exit_order_from_action("sell", "short_entry") is False
    
    def test_position_monitor_exit_detected(self):
        """Test that position_monitor_exit source is detected."""
        assert is_exit_order_from_action("sell", "position_monitor_exit") is True
        assert is_exit_order_from_action("buy", "position_monitor_exit") is True


class TestExitOrderDetectionConsistency:
    """Test that exit order detection is consistent across methods."""
    
    def test_source_and_action_consistency(self):
        """Test that is_exit_order_from_source and is_exit_order_from_action are consistent."""
        # For sources with markers, both should return True
        for marker in EXIT_ORDER_MARKERS:
            assert is_exit_order_from_source(marker) is True
            assert is_exit_order_from_action("sell", marker) is True
            assert is_exit_order_from_action("buy", marker) is True
        
        # For sources without markers, both should return False
        non_exit_sources = ["entry", "signal", "agent_grid", "sell", "buy"]
        for source in non_exit_sources:
            assert is_exit_order_from_source(source) is False
            assert is_exit_order_from_action("sell", source) is False
            assert is_exit_order_from_action("buy", source) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
