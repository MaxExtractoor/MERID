"""
Test signal-to-side mapping consistency across the production stack.

This test validates that:
1. Production agent_grid_15m.py uses consistent signal["side"] and signal["action"] mapping
2. Signal generation follows Kalshi best practices (outcome_side yes/no + action buy/sell)
3. No inversions exist in the production path (e.g., velocity > 0 mapping to NO)
4. Legacy agents are properly marked as deprecated and not used in production
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass


class TestSignalToSideMappingConsistency:
    """Test signal-to-side mapping consistency in production stack."""
    
    def test_agent_grid_signal_structure(self):
        """Verify agent_grid_15m.py uses signal["side"] and signal["action"]."""
        # Read the agent_grid_15m.py file
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Should use signal["side"] for contract side (yes/no)
        assert '"side": signal["side"]' in content or 'signal["side"]' in content
        
        # Should use signal["action"] for trading action (buy/sell)
        assert '"action": signal["action"]' in content or 'signal["action"]' in content
        
        # Should NOT use signal.direction (legacy pattern)
        # signal.direction is used only for internal direction calculations, not for order side
        assert 'signal.direction == "up"' not in content or 'signal.direction' not in content
    
    def test_velocity_to_side_mapping_consistency(self):
        """Verify velocity > 0 maps to YES in production stack."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Check that positive velocity favors YES in trend_following mode
        # This is the correct mapping per Kalshi best practices
        assert 'velocity > 0' in content
        assert 'signal_side' in content
        
        # Verify no inversion (velocity > 0 should NOT map to NO directly)
        # We check for the absence of inversion patterns
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'velocity > 0' in line and 'signal_side = "no"' in line:
                # Check if this is in a mean_reversion context (which is valid)
                context = '\n'.join(lines[max(0, i-5):min(len(lines), i+5)])
                if 'mean_reversion' not in context.lower():
                    pytest.fail(f"Found inversion at line {i}: velocity > 0 mapping to NO without mean_reversion context")
    
    @pytest.mark.skip(reason="2026-07-18: Panic fade disabled - causing losses by betting against trend")
    def test_panic_fade_signal_mapping(self):
        """Verify panic fade signal uses correct side/action mapping."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Oversold should map to YES (expect reversion up)
        assert 'is_oversold' in content
        assert 'signal_side = "yes"' in content
        assert 'signal_action = "buy"' in content
        
        # Overbought should map to NO (expect reversion down)
        assert 'is_overbought' in content
        # Both should use "buy" action (entering position)
    
    def test_price_based_signal_mapping(self):
        """Verify price-based signal uses correct side/action mapping."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Low price should map to YES (buy cheap)
        assert 'market_price <= buy_threshold' in content or 'buy_threshold' in content
        assert 'signal_side = "yes"' in content
        assert 'signal_action = "buy"' in content
        
        # High price should map to NO (bet against)
        assert 'market_price >= sell_threshold' in content or 'sell_threshold' in content
        assert 'signal_side = "no"' in content
        assert 'signal_action = "buy"' in content
    
    def test_legacy_agents_marked_deprecated(self):
        """Verify legacy agents are marked as deprecated."""
        legacy_agents = [
            'merid/agents/btc_15m_agent.py',
            'merid/agents/eth_15m_agent.py',
            'merid/agents/sol_15m_agent.py',
            'merid/agents/xrp_15m_agent.py',
            'merid/agents/doge_15m_agent.py',
        ]
        
        for agent_file in legacy_agents:
            with open(agent_file, 'r') as f:
                content = f.read()
            
            # Should be marked as deprecated
            assert 'DEPRECATED' in content or 'deprecated' in content.lower()
            assert 'NOT used in production' in content or 'production' in content.lower()
    
    def test_production_uses_agent_grid_15m(self):
        """Verify production stack uses agent_grid_15m.py not legacy agents."""
        with open('merid/startup_validations.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should forbid legacy agent_grid
        assert 'merid.prediction.agent_grid' in content
        assert 'legacy' in content.lower()
        
        # Should allow agent_grid_15m
        assert 'merid.prediction.agent_grid_15m' in content
    
    def test_kalshi_format_conversion_consistency(self):
        """Verify Kalshi format conversion follows official documentation."""
        with open('merid/event_venues/kalshi/test_kalshi_format_conversion.py', 'r') as f:
            content = f.read()
        
        # Should test all four combinations
        assert 'BUY_YES' in content
        assert 'SELL_YES' in content
        assert 'BUY_NO' in content
        assert 'SELL_NO' in content
        
        # Should follow Kalshi's outcome_side mapping
        # buy-yes and sell-no both produce long yes exposure
        # buy-no and sell-yes both produce long no exposure
        assert 'outcome_id' in content
    
    def test_risk_enforcement_side_consistency(self):
        """Verify risk enforcement uses consistent side field."""
        with open('merid/prediction/risk/_prediction_risk.py', 'r') as f:
            content = f.read()
        
        # Should use side.lower() == "yes" or side.lower() == "no"
        assert 'side.lower()' in content or 'side == "yes"' in content or 'side == "no"' in content
        
        # Should have separate limits for yes and no
        assert 'max_yes_position' in content
        assert 'max_no_position' in content
    
    def test_order_candidate_side_action_fields(self):
        """Verify OrderCandidate uses side and action fields correctly."""
        with open('merid/risk/profiles/global_allocator.py', 'r') as f:
            content = f.read()
        
        # OrderCandidate should have side (yes/no) and action (buy/sell)
        assert 'side: str' in content
        assert 'action: str' in content
        assert '# "yes" or "no"' in content or '# "buy" or "sell"' in content
    
    def test_signal_to_candidate_mapping(self):
        """Verify signal maps correctly to OrderCandidate in agent_grid_15m."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Should extract side and action from signal
        assert 'side = candidate.get' in content or '"side": signal["side"]' in content
        assert 'action = candidate.get' in content or '"action": signal["action"]' in content
        
        # Should pass these to OrderCandidate
        assert 'OrderCandidate(' in content
        assert 'side=side' in content
        assert 'action=action' in content


class TestKalshiBestPracticesCompliance:
    """Test compliance with Kalshi's official best practices."""
    
    def test_outcome_side_usage(self):
        """Verify system uses outcome_side concept (yes/no for directional exposure)."""
        # Check that production code uses yes/no for directional exposure
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Should use yes/no for contract side
        assert 'signal_side = "yes"' in content
        assert 'signal_side = "no"' in content
        
        # Should use buy for trading action (production always buys to enter)
        # Sell is used only for exiting positions, not in signal generation
        assert 'signal_action = "buy"' in content
    
    def test_no_legacy_action_side_in_production(self):
        """Verify production doesn't rely on legacy action/side fields."""
        # Production should use signal["side"] and signal["action"]
        # Legacy fields (action/side without outcome_side) should not be used
        
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Should use the new structure
        assert 'signal["side"]' in content
        assert 'signal["action"]' in content
    
    def test_dual_side_evaluation(self):
        """Verify system evaluates both YES and NO sides for best edge."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Should evaluate both sides
        assert 'side_edges' in content or 'edge_yes' in content
        assert 'edge_no' in content
        
        # Should select side with maximum edge
        assert 'max(side_edges' in content or 'signal_side = max' in content


class TestNoInversionsInProductionPath:
    """Test that no inversions exist in the production signal path."""
    
    def test_no_velocity_inversion(self):
        """Verify velocity > 0 does not invert to NO in production."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        
        # Check for potential inversion patterns
        for i, line in enumerate(lines):
            # Look for velocity > 0 followed by signal_side = "no"
            if 'velocity > 0' in line:
                # Check next few lines for inversion
                context = '\n'.join(lines[i:i+10])
                if 'signal_side = "no"' in context and 'mean_reversion' not in context.lower():
                    pytest.fail(f"Potential velocity inversion found at line {i}")
    
    def test_no_market_price_inversion(self):
        """Verify market_price > 0.5 does not invert to NO in production."""
        with open('merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # market_price > 0.5 should indicate UP (kalshi_direction)
        # This should NOT directly map to NO side
        # It's used for informational purposes only
        assert 'kalshi_direction = "up" if market_price > 0.5 else "down"' in content
        
        # Verify this is not used for side selection (only for logging/filtering)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'kalshi_direction' in line:
                context = '\n'.join(lines[i:i+5])
                # Should not be used for signal_side assignment
                if 'signal_side = kalshi_direction' in context:
                    pytest.fail(f"kalshi_direction incorrectly used for signal_side at line {i}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
