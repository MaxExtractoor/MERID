"""
Unit tests for alignment degraded mode module.
"""

import pytest
from datetime import datetime, timezone

from merid.prediction.alignment_degraded_mode import (
    AlignmentDegradedMode,
    get_alignment_degraded_mode,
)


class TestAlignmentDegradedMode:
    """Test AlignmentDegradedMode."""
    
    def test_initialization(self):
        """Test initializing AlignmentDegradedMode."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        assert mode.gap_threshold_cents == 50
        assert mode.consecutive_failures_threshold == 3
        assert len(mode.degraded_assets) == 0
        assert len(mode.consecutive_failures) == 0
    
    def test_check_alignment_aligned(self):
        """Test checking alignment when aligned."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        is_aligned = mode.check_alignment("BTC", 30.0)
        
        assert is_aligned is True
        assert mode.consecutive_failures["BTC"] == 0
        assert "BTC" not in mode.degraded_assets
    
    def test_check_alignment_misaligned(self):
        """Test checking alignment when misaligned."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # First failure
        is_aligned = mode.check_alignment("BTC", 60.0)
        assert is_aligned is False
        assert mode.consecutive_failures["BTC"] == 1
        assert "BTC" not in mode.degraded_assets  # Not yet degraded
        
        # Second failure
        is_aligned = mode.check_alignment("BTC", 60.0)
        assert is_aligned is False
        assert mode.consecutive_failures["BTC"] == 2
        assert "BTC" not in mode.degraded_assets  # Not yet degraded
        
        # Third failure - should enter degraded mode
        is_aligned = mode.check_alignment("BTC", 60.0)
        assert is_aligned is False
        assert mode.consecutive_failures["BTC"] == 3
        assert "BTC" in mode.degraded_assets  # Now degraded
    
    def test_check_alignment_restored(self):
        """Test checking alignment when restored after degradation."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # Enter degraded mode
        for _ in range(3):
            mode.check_alignment("BTC", 60.0)
        assert "BTC" in mode.degraded_assets
        
        # Restore alignment
        is_aligned = mode.check_alignment("BTC", 30.0)
        assert is_aligned is True
        assert mode.consecutive_failures["BTC"] == 0
        assert "BTC" not in mode.degraded_assets  # Restored
    
    def test_is_degraded(self):
        """Test checking if asset is degraded."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        assert mode.is_degraded("BTC") is False
        
        # Enter degraded mode
        for _ in range(3):
            mode.check_alignment("BTC", 60.0)
        
        assert mode.is_degraded("BTC") is True
    
    def test_can_enter_new_position(self):
        """Test checking if new entries are allowed."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # Not degraded - should allow
        assert mode.can_enter_new_position("BTC") is True
        
        # Enter degraded mode
        for _ in range(3):
            mode.check_alignment("BTC", 60.0)
        
        # Degraded - should block
        assert mode.can_enter_new_position("BTC") is False
    
    def test_get_status(self):
        """Test getting status of all assets."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # Add some failures
        mode.check_alignment("BTC", 60.0)
        mode.check_alignment("ETH", 30.0)
        
        status = mode.get_status()
        
        assert "BTC" in status
        assert "ETH" in status
        assert status["BTC"]["consecutive_failures"] == 1
        assert status["BTC"]["is_degraded"] is False
        assert status["ETH"]["consecutive_failures"] == 0
        assert status["ETH"]["is_degraded"] is False
    
    def test_log_status(self):
        """Test logging status."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # Add some failures
        mode.check_alignment("BTC", 60.0)
        mode.check_alignment("ETH", 30.0)
        
        # Should not raise exception
        mode.log_status()
    
    def test_multiple_assets(self):
        """Test tracking multiple assets independently."""
        mode = AlignmentDegradedMode(
            gap_threshold_cents=50,
            consecutive_failures_threshold=3
        )
        
        # BTC enters degraded mode
        for _ in range(3):
            mode.check_alignment("BTC", 60.0)
        
        # ETH stays aligned
        mode.check_alignment("ETH", 30.0)
        
        assert mode.is_degraded("BTC") is True
        assert mode.is_degraded("ETH") is False
        assert mode.can_enter_new_position("BTC") is False
        assert mode.can_enter_new_position("ETH") is True


class TestSingleton:
    """Test singleton instance."""
    
    def test_get_alignment_degraded_mode(self):
        """Test getting singleton instance."""
        mode1 = get_alignment_degraded_mode()
        mode2 = get_alignment_degraded_mode()
        
        # Should return same instance
        assert mode1 is mode2
    
    def test_singleton_persistence(self):
        """Test that singleton persists state."""
        mode = get_alignment_degraded_mode()
        
        # Modify state
        mode.check_alignment("BTC", 60.0)
        
        # Get instance again
        mode2 = get_alignment_degraded_mode()
        
        # State should persist
        assert mode2.consecutive_failures["BTC"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
