#!/usr/bin/env python3
"""
Test suite for price range fix (2026-07-12).

Tests verify that all price clamping uses the expanded price_range (10-75c)
to align with current market conditions (YES prices 60-97c observed).

Files fixed:
- merid/loop_15m.py: price clamping aligned with 10-75c expanded range
- merid/event_venues/kalshi/dynamic_risk.py: limit_price_cents clamping aligned with 10-75c
- merid/event_venues/kalshi/order_router.py: price clamping aligned with 10-75c
- merid/prediction/kalshi_tools.py: price clamping aligned with 10-75c
- merid_core/schemas/intent.py: price clamping aligned with 10-75c
- merid_core/kalshi/execution_pipeline.py: price clamping aligned with 10-75c
- merid/prediction/agent_grid_15m.py: entry band aligned with 10-75c expanded range
- config/profiles/kalshi_crypto_15m_v2.yaml: price_range set to 10-75c
"""

import pytest
from pathlib import Path


class TestLoop15mPriceRangeFix:
    """Test that loop_15m.py price clamping uses 10-75c expanded range."""
    
    def test_loop_15m_price_clamping_10_75(self):
        """Verify loop_15m.py clamps prices to 10-75c (expanded range)."""
        loop_path = Path('merid/loop_15m.py')
        if not loop_path.exists():
            pytest.skip("loop_15m.py not found")
        
        content = loop_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75," in content, \
            "loop_15m.py should clamp prices to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "loop_15m.py should have fix comment for 10-75c expanded range"


class TestDynamicRiskPriceRangeFix:
    """Test that dynamic_risk.py limit_price_cents clamping uses 10-75c expanded range."""
    
    def test_dynamic_risk_limit_price_clamping_10_75(self):
        """Verify dynamic_risk.py clamps limit_price_cents to 10-75c (expanded range)."""
        dynamic_risk_path = Path('merid/event_venues/kalshi/dynamic_risk.py')
        if not dynamic_risk_path.exists():
            pytest.skip("dynamic_risk.py not found")
        
        content = dynamic_risk_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75, limit_price_cents))" in content, \
            "dynamic_risk.py should clamp limit_price_cents to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "dynamic_risk.py should have fix comment for 10-75c expanded range"


class TestOrderRouterPriceRangeFix:
    """Test that order_router.py price clamping uses 10-75c expanded range."""
    
    def test_order_router_price_clamping_10_75(self):
        """Verify order_router.py clamps prices to 10-75c (expanded range)."""
        order_router_path = Path('merid/event_venues/kalshi/order_router.py')
        if not order_router_path.exists():
            pytest.skip("order_router.py not found")
        
        content = order_router_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75," in content, \
            "order_router.py should clamp prices to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "order_router.py should have fix comment for 10-75c expanded range"


class TestKalshiToolsPriceRangeFix:
    """Test that kalshi_tools.py price clamping uses 10-75c expanded range."""
    
    def test_kalshi_tools_price_clamping_10_75(self):
        """Verify kalshi_tools.py clamps prices to 10-75c (expanded range)."""
        kalshi_tools_path = Path('merid/prediction/kalshi_tools.py')
        if not kalshi_tools_path.exists():
            pytest.skip("kalshi_tools.py not found")
        
        content = kalshi_tools_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75," in content, \
            "kalshi_tools.py should clamp prices to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "kalshi_tools.py should have fix comment for 10-75c expanded range"


class TestIntentSchemaPriceRangeFix:
    """Test that intent.py price clamping uses 10-75c expanded range."""
    
    def test_intent_schema_price_clamping_10_75(self):
        """Verify intent.py clamps prices to 10-75c (expanded range)."""
        intent_path = Path('merid_core/schemas/intent.py')
        if not intent_path.exists():
            pytest.skip("intent.py not found")
        
        content = intent_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75," in content, \
            "intent.py should clamp prices to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "intent.py should have fix comment for 10-75c expanded range"


class TestExecutionPipelinePriceRangeFix:
    """Test that execution_pipeline.py price clamping uses 10-75c expanded range."""
    
    def test_execution_pipeline_price_clamping_10_75(self):
        """Verify execution_pipeline.py clamps prices to 10-75c (expanded range)."""
        pipeline_path = Path('merid_core/kalshi/execution_pipeline.py')
        if not pipeline_path.exists():
            pytest.skip("execution_pipeline.py not found")
        
        content = pipeline_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the clamping uses 10-75c range
        assert "max(10, min(75," in content, \
            "execution_pipeline.py should clamp prices to 10-75c expanded range"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "execution_pipeline.py should have fix comment for 10-75c expanded range"


class TestAgentGridPriceRangeFix:
    """Test that agent_grid_15m.py entry band uses 10-75c expanded range."""
    
    def test_agent_grid_entry_band_10_75(self):
        """Verify agent_grid_15m.py uses 10-75c entry band (expanded range)."""
        agent_grid_path = Path('merid/prediction/agent_grid_15m.py')
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check that the entry band uses 10-75c range
        assert "10 <= clamped_price_cents <= 75" in content, \
            "agent_grid_15m.py should use 10-75c expanded range for price validation"
        
        # Check for fix comment
        assert "2026-07-12" in content or "10-75c" in content, \
            "agent_grid_15m.py should have fix comment for 10-75c expanded range"


class TestComprehensivePriceRangeFix:
    """Comprehensive test that all price clamping uses 10-75c expanded range."""
    
    def test_no_5_95_clamping_in_critical_files(self):
        """Verify no 5-95c clamping remains in critical trading files."""
        critical_files = [
            'merid/loop_15m.py',
            'merid/event_venues/kalshi/dynamic_risk.py',
            'merid/event_venues/kalshi/order_router.py',
            'merid/prediction/kalshi_tools.py',
            'merid_core/schemas/intent.py',
            'merid_core/kalshi/execution_pipeline.py',
            'merid/prediction/agent_grid_15m.py',
        ]
        
        for file_path in critical_files:
            path = Path(file_path)
            if not path.exists():
                continue
            
            content = path.read_text(encoding='utf-8', errors='ignore')
            
            # Check for legacy 5-95c clamping pattern
            assert "max(5, min(95," not in content, \
                f"{file_path} should not have 5-95c clamping (legacy pattern)"
            
            # Check for legacy 5-95c range checks
            assert "5 <= " not in content or " <= 95" not in content, \
                f"{file_path} should not have 5-95c range checks (legacy pattern)"
    
    def test_all_10_75_clamping_present(self):
        """Verify all critical files have 10-75c clamping where appropriate."""
        files_with_10_75_clamping = [
            'merid/loop_15m.py',
            'merid/event_venues/kalshi/dynamic_risk.py',
            'merid/event_venues/kalshi/order_router.py',
            'merid/prediction/kalshi_tools.py',
            'merid_core/schemas/intent.py',
            'merid_core/kalshi/execution_pipeline.py',
        ]
        
        for file_path in files_with_10_75_clamping:
            path = Path(file_path)
            if not path.exists():
                continue
            
            content = path.read_text(encoding='utf-8', errors='ignore')
            
            # Check for 10-75c clamping pattern
            has_10_75_clamping = "max(10, min(75," in content
            
            if not has_10_75_clamping:
                pytest.fail(
                    f"{file_path} should have 10-75c clamping pattern but none found"
                )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
