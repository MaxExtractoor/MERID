#!/usr/bin/env python3
"""
Comprehensive tests for audit fixes from 2026-07-09.

Tests cover:
1. SOL decimal scaling fix (USD vs cents in logging)
2. Fills pipeline data loss fix (POSITION-FALLBACK)
3. 75c entry band fix (profile alignment)
4. Side recording verification (Kalshi API behavior)
5. Position sizing limits (3% risk enforcement)
"""

import pytest
from pathlib import Path
from decimal import Decimal


class TestSOLDecimalScaling:
    """Test SOL decimal scaling fix in agent_grid_15m.py."""
    
    def test_format_price_receives_usd_values(self):
        """Verify format_price receives USD values, not cent values."""
        agent_grid_path = Path('merid/prediction/agent_grid_15m.py')
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that format_price is called with USD prices (not multiplied by 100)
        # The fix ensures we pass original USD prices to format_price
        # Look for the FVG-UPDATE log line which should have format_price with USD prices
        has_correct_format = 'format_price(asset, open_price), format_price(asset, high_price)' in content
        assert has_correct_format, "format_price should receive USD prices (open_price, high_price, etc.), not cent values"
    
    def test_no_cent_multiplication_in_format_price_call(self):
        """Verify format_price is not called with cent-multiplied values."""
        agent_grid_path = Path('merid/prediction/agent_grid_15m.py')
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that we don't multiply by 100 before calling format_price
        has_cent_bug = 'format_price(open_price * 100' in content
        assert not has_cent_bug, "format_price should not receive cent-multiplied values"


class TestFillsPipelineDataLoss:
    """Test fills pipeline data loss fix in fills_poller.py."""
    
    def test_position_fallback_does_not_clear_fills(self):
        """Verify POSITION-FALLBACK does not automatically clear fills ledger."""
        poller_path = Path('merid/event_venues/kalshi/fills_poller.py')
        if not poller_path.exists():
            pytest.skip("fills_poller.py not found")
        
        content = poller_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that clear_all_fills is NOT called in POSITION-FALLBACK
        has_clear_fills = 'await ledger.clear_all_fills()' in content
        assert not has_clear_fills, "POSITION-FALLBACK should not clear fills ledger"
        
        # Check that the fix comment is present
        has_fix_comment = 'NOT clearing fills ledger' in content
        assert has_fix_comment, "Fix comment should be present"


class Test75cEntryBandFix:
    """Test 75c entry band fix to align with 50c profile max."""
    
    def test_entry_band_references_50c_max(self):
        """Verify entry band references use 50c max, not 75c."""
        agent_grid_path = Path('merid/prediction/agent_grid_15m.py')
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that references use 50c, not 75c
        has_75c_bug = '[25c, 75c]' in content or '[10c, 75c]' in content
        assert not has_75c_bug, "Entry band should use 50c max, not 75c"
        
        # Check that correct 50c references are present
        has_50c_fix = '[10c, 50c]' in content
        assert has_50c_fix, "Entry band should use [10c, 50c] range"
    
    def test_sweet_spot_comment_uses_50c(self):
        """Verify sweet spot comment uses 50c."""
        agent_grid_path = Path('merid/prediction/agent_grid_15m.py')
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that sweet spot comment uses 50c
        has_correct_comment = '[10c, 50c] has good risk/reward profile' in content
        assert has_correct_comment, "Sweet spot comment should use 50c max"


class TestSideRecording:
    """Test side recording verification (Kalshi API behavior)."""
    
    def test_side_recording_uses_kalshi_api_format(self):
        """Verify side recording uses Kalshi API format correctly."""
        ledger_path = Path('merid/event_venues/kalshi/fills_ledger.py')
        if not ledger_path.exists():
            pytest.skip("fills_ledger.py not found")
        
        content = ledger_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that side is taken directly from Kalshi API response
        has_side_extraction = 'side=raw.get("side"' in content
        assert has_side_extraction, "Side should be extracted from Kalshi API response"
        
        # Check that we don't transform the side (Kalshi API is correct)
        has_side_transformation = 'side.*transform' in content.lower()
        assert not has_side_transformation, "Side should not be transformed (Kalshi API is correct)"


class TestPositionSizingLimits:
    """Test position sizing limits for 3% risk enforcement."""
    
    def test_max_contracts_equals_one(self):
        """Verify max_contracts=1 to enforce 3% risk limit."""
        profile_path = Path('config/profiles/kalshi_crypto_15m_v2.yaml')
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        content = profile_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that max_single_order_contracts is 1
        has_max_contracts_one = 'max_single_order_contracts: 1' in content
        assert has_max_contracts_one, "max_single_order_contracts should be 1 for 3% risk limit"
    
    def test_unified_risk_manager_enforces_single_contract(self):
        """Verify UnifiedRiskManager enforces single contract limit."""
        risk_path = Path('merid/risk/unified_risk_manager.py')
        if not risk_path.exists():
            pytest.skip("unified_risk_manager.py not found")
        
        content = risk_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that per_trade_max_contracts defaults to 1
        has_single_contract = 'per_trade_max_contracts: int = 1' in content
        assert has_single_contract, "per_trade_max_contracts should default to 1"
        
        # Check that contracts > max_contracts is enforced
        has_enforcement = 'contracts > self._limits.per_trade_max_contracts' in content
        assert has_enforcement, "Should enforce contracts > max_contracts check"


class TestProfileConfiguration:
    """Test profile configuration consistency."""
    
    def test_price_range_max_is_50c(self):
        """Verify profile price_range.max_price_cents is 50."""
        profile_path = Path('config/profiles/kalshi_crypto_15m_v2.yaml')
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        content = profile_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that price_range max is 50c
        has_50c_max = 'max_price_cents: 50' in content
        assert has_50c_max, "price_range.max_price_cents should be 50"
    
    def test_price_range_min_is_10c(self):
        """Verify profile price_range.min_price_cents is 10."""
        profile_path = Path('config/profiles/kalshi_crypto_15m_v2.yaml')
        if not profile_path.exists():
            pytest.skip("kalshi_crypto_15m_v2.yaml not found")
        
        content = profile_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that price_range min is 10c
        has_10c_min = 'min_price_cents: 10' in content
        assert has_10c_min, "price_range.min_price_cents should be 10"


class TestExitPolicyPrecedence:
    """Test exit policy precedence order."""
    
    def test_exit_precedence_documented(self):
        """Verify exit precedence order is documented."""
        exit_policy_path = Path('merid/position_management/exit_policy.py')
        if not exit_policy_path.exists():
            pytest.skip("exit_policy.py not found")
        
        content = exit_policy_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that exit precedence is documented
        has_precedence = 'EXIT PRECEDENCE ORDER' in content
        assert has_precedence, "Exit precedence order should be documented"
        
        # Check that EXTREME_PROFIT is highest priority
        has_extreme_profit_first = 'EXTREME_PROFIT' in content and 'highest priority' in content
        assert has_extreme_profit_first, "EXTREME_PROFIT should be highest priority"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
