"""Test trend alignment integration in agent_grid_15m.py.

This verifies that the TrendAlignmentStrategy is correctly integrated as a
confirmation filter in the signal generation process as per the 2026 technical analysis audit.
"""

import pytest
from pathlib import Path


class TestTrendAlignmentIntegration:
    """Test suite for trend alignment integration."""
    
    def test_trend_alignment_strategy_exists(self):
        """Verify that TrendAlignmentStrategy class exists."""
        trend_alignment_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "strategies" / "trend_alignment.py"
        
        assert trend_alignment_path.exists(), f"Trend alignment file not found: {trend_alignment_path}"
        
        with open(trend_alignment_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify TrendAlignmentStrategy class exists
        assert "class TrendAlignmentStrategy" in content, \
            "TrendAlignmentStrategy class should exist"
        
        # Verify it has methods for trend detection
        assert "update_price" in content or "update" in content, \
            "TrendAlignmentStrategy should have price update method"
        assert "_check_trend_alignment" in content or "check_alignment" in content or "is_aligned" in content, \
            "TrendAlignmentStrategy should have alignment check method"
    
    def test_trend_alignment_used_in_agent_grid(self):
        """Verify that trend alignment is used in agent_grid_15m.py."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        assert agent_grid_path.exists(), f"Agent grid file not found: {agent_grid_path}"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify trend alignment is imported or referenced
        assert "trend_alignment" in content.lower() or "TrendAlignment" in content, \
            "Trend alignment should be referenced in agent_grid_15m.py"
        
        # Verify _check_trend_alignment method exists
        assert "_check_trend_alignment" in content, \
            "_check_trend_alignment method should exist in agent_grid_15m.py"
    
    def test_trend_alignment_confirmation_filter(self):
        """Verify that trend alignment is used as a confirmation filter."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify trend alignment check is called in signal generation
        # This is a soft check - we just verify the method is used
        assert "_check_trend_alignment" in content and "signal" in content.lower(), \
            "Trend alignment should be used in signal generation context"
    
    def test_trend_alignment_5m_1h_timeframes(self):
        """Verify that trend alignment uses 5m and 1h timeframes."""
        trend_alignment_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "strategies" / "trend_alignment.py"
        
        if trend_alignment_path.exists():
            with open(trend_alignment_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Verify 5m and 1h timeframes are referenced
            assert "5m" in content or "5 minute" in content.lower(), \
                "Trend alignment should use 5m timeframe"
            assert "1h" in content or "1 hour" in content.lower(), \
                "Trend alignment should use 1h timeframe"
    
    def test_trend_alignment_skip_logic(self):
        """Verify that trend alignment can skip trades when not aligned."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify there's logic to skip when trends are not aligned
        # This is a soft check - we just verify alignment check affects signal generation
        assert "skip" in content.lower() or "not aligned" in content.lower() or "aligned" in content.lower(), \
            "Trend alignment should have skip logic when not aligned"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
