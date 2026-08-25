"""Tests for warmup bypass fixes (2026-07-16).

These tests verify that all warmup bypasses are properly removed to prevent
orders from executing within minutes of startup with insufficient indicator data.

Warmup bypasses fixed:
1. min_bars_cold_start in crypto_15m_indicators.py - removed
2. Cold start logic in agent_grid_15m.py - removed
3. Warmup override in loop_15m.py - removed
"""

import pytest
from pathlib import Path


class TestCrypto15mIndicatorsNoColdStart:
    """Test that crypto_15m_indicators.py no longer has cold start bypass."""
    
    def test_min_bars_cold_start_removed(self):
        """Verify min_bars_cold_start is removed from IndicatorConfig."""
        source = Path("c:/Dev/MERID/merid/signals/crypto_15m_indicators.py").read_text(encoding='utf-8')
        
        # Should NOT have active min_bars_cold_start field definition
        # (comments about removal are OK)
        lines = source.split('\n')
        active_field_def = False
        for line in lines:
            if 'min_bars_cold_start:' in line and not line.strip().startswith('#'):
                active_field_def = True
                break
        
        assert not active_field_def, \
            "min_bars_cold_start field should be removed from IndicatorConfig"
        
        # Should have comment about removal
        assert "REMOVED min_bars_cold_start" in source or "removed min_bars_cold_start" in source.lower(), \
            "Should have comment explaining removal"
    
    def test_min_bars_required_is_26(self):
        """Verify min_bars_required is 26 for MACD warmup."""
        source = Path("c:/Dev/MERID/merid/signals/crypto_15m_indicators.py").read_text(encoding='utf-8')
        
        # CRITICAL FIX: 2026-08-01 - min_bars_required changed from 30 to 26 for MACD(8,21,5) warmup
        # MACD(8,21,5) needs 21 (slow) + 5 (signal) = 26 bars minimum
        # Should have min_bars_required = 26
        assert "min_bars_required: int = 26" in source, \
            "min_bars_required should be 26 for MACD(8,21,5) warmup"
    
    def test_composite_gate_no_cold_start_logic(self):
        """Verify composite gate no longer has cold start bypass logic."""
        source = Path("c:/Dev/MERID/merid/signals/crypto_15m_indicators.py").read_text(encoding='utf-8')
        
        # Should NOT have cold start conditional in composite gate section
        # Look for the pattern that was removed
        assert "min_bars_threshold = self.cfg.min_bars_cold_start" not in source, \
            "Composite gate should not use min_bars_cold_start"
        
        # Should NOT have conditional logic based on bars_available < min_bars_required
        assert "if snap.bars_available < self.cfg.min_bars_required:" not in source, \
            "Should not have separate cold start path"
        
        # Should have single gate check
        assert "snap.trade_allowed = (" in source, \
            "Should have single trade_allowed check"
        assert "snap.vol_gate_ok" in source, \
            "Should check vol_gate_ok"
        assert "snap.atr_move_ok" in source, \
            "Should check atr_move_ok"
        assert "snap.chop_gate_ok" in source, \
            "Should check chop_gate_ok"
        assert "snap.bars_available >= min_bars_threshold" in source, \
            "Should check bars_available >= min_bars_threshold"


class TestAgentGridNoColdStartBypass:
    """Test that agent_grid_15m.py no longer has cold start bypass logic."""
    
    def test_agent_grid_no_cold_start_comments(self):
        """Verify agent_grid_15m.py no longer has cold start bypass comments."""
        source = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py").read_text(encoding='utf-8')
        
        # Should NOT have old cold start comments
        assert "Use indicator stack's min_bars_cold_start for faster warmup" not in source, \
            "Should not have cold start bypass comment"
        assert "allows trading with fewer bars during initialization" not in source, \
            "Should not comment about allowing fewer bars"
        assert "indicator stack now has cold start logic" not in source, \
            "Should not claim indicator stack has cold start logic"
        
        # Should have removal comment
        assert "REMOVED cold start bypass logic" in source or "removed cold start bypass" in source.lower(), \
            "Should have comment explaining removal"
    
    def test_agent_grid_requires_26_bars(self):
        """Verify agent_grid_15m.py requires 26 bars before signal generation."""
        source = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py").read_text()
        
        # CRITICAL FIX: 2026-08-01 - Changed from 30 to 26 for MACD(8,21,5) warmup
        # Should have 26-bar requirement
        assert "min_bars_required = 26" in source, \
            "Should require 26 bars for signal generation"
        
        # Should block trading with insufficient bars
        assert "if indicator_snap.bars_available < min_bars_required:" in source, \
            "Should check bars_available before signal generation"
        assert "return None" in source, \
            "Should return None to block trading during warmup"
        assert "NOT READY, skipping signal generation" in source, \
            "Should log warmup status"


class TestLoop15mNoWarmupOverride:
    """Test that loop_15m.py no longer has warmup override."""
    
    def test_loop_15m_no_warmup_override(self):
        """Verify loop_15m.py no longer forces health checks to True during warmup."""
        source = Path("c:/Dev/MERID/merid/loop_15m.py").read_text(encoding='utf-8')
        
        # All warmup override logic should be commented out
        lines = source.split('\n')
        active_warmup_overrides = []
        
        for i, line in enumerate(lines):
            if 'if in_warmup:' in line and not line.strip().startswith('#'):
                # This is an active warmup block - check if it has override logic
                for j in range(i+1, min(i+10, len(lines))):
                    if '= True' in lines[j] and not lines[j].strip().startswith('#'):
                        active_warmup_overrides.append(f"Line {i+1}: {line.strip()}")
                        break
                    if 'if' in lines[j] and 'in_warmup' not in lines[j]:
                        break
        
        assert len(active_warmup_overrides) == 0, \
            f"Found active warmup override logic: {active_warmup_overrides}"
        
        # Should have removal comments
        assert "REMOVED warmup" in source or "removed warmup" in source.lower(), \
            "Should have comment explaining removal"
    
    def test_loop_15m_no_allow_trading_during_warmup_comment(self):
        """Verify loop_15m.py no longer has comment about allowing trading during warmup."""
        source = Path("c:/Dev/MERID/merid/loop_15m.py").read_text(encoding='utf-8')
        
        # Should NOT have old design decision comment (unless commented out)
        lines = source.split('\n')
        active_design_decision = False
        
        for line in lines:
            if "DESIGN DECISION: Allow trading during warmup" in line and not line.strip().startswith('#'):
                active_design_decision = True
                break
        
        assert not active_design_decision, \
            "Should not have active comment about allowing trading during warmup"


class TestWarmupEnforcementIntegration:
    """Integration tests to verify warmup is enforced across the stack."""
    
    def test_all_components_require_26_bars(self):
        """Verify all components require 26 bars for trading."""
        indicators_source = Path("c:/Dev/MERID/merid/signals/crypto_15m_indicators.py").read_text(encoding='utf-8')
        agent_source = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py").read_text(encoding='utf-8')
        
        # CRITICAL FIX: 2026-08-01 - Changed from 30 to 26 for MACD(8,21,5) warmup
        # Indicator config
        assert "min_bars_required: int = 26" in indicators_source, \
            "Indicator config should require 26 bars"
        
        # Agent grid
        assert "min_bars_required = 26" in agent_source, \
            "Agent grid should require 26 bars"
    
    def test_no_cold_start_paths_exist(self):
        """Verify no cold start paths exist in the trading stack."""
        indicators_source = Path("c:/Dev/MERID/merid/signals/crypto_15m_indicators.py").read_text(encoding='utf-8')
        agent_source = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py").read_text(encoding='utf-8')
        loop_source = Path("c:/Dev/MERID/merid/loop_15m.py").read_text(encoding='utf-8')
        
        # Check all components for active cold start references (not comments)
        for source, name in [(indicators_source, "crypto_15m_indicators"), 
                              (agent_source, "agent_grid_15m"), 
                              (loop_source, "loop_15m")]:
            lines = source.split('\n')
            active_references = []
            for line in lines:
                if 'min_bars_cold_start' in line and not line.strip().startswith('#'):
                    active_references.append(line.strip())
            
            assert len(active_references) == 0, \
                f"{name} should not have active min_bars_cold_start references: {active_references}"
    
    def test_warmup_blocks_trading(self):
        """Verify warmup blocks trading by returning None."""
        agent_source = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py").read_text(encoding='utf-8')
        
        # Should return None during warmup
        assert "return None" in agent_source, \
            "Should return None to block trading during warmup"
        
        # Should have warmup logging
        assert "WARMUP" in agent_source or "warmup" in agent_source.lower(), \
            "Should log warmup status"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
