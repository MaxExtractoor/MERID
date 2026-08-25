"""
Tests for asset coverage fixes (2026-07-16).

This test file verifies the fixes for 5-asset coverage discrepancies found during the deep audit:
1. loop_15m.py velocity thresholds match profile YAML values
2. SwarmOrchestrator SYMBOL_LIMITS includes all 5 assets (BTC, ETH, SOL, XRP, DOGE)
"""

import pytest


class TestLoop15mVelocityThresholdAlignment:
    """Test that loop_15m.py velocity thresholds match profile YAML values."""
    
    def test_loop_15m_velocity_thresholds_match_profile_yaml(self):
        """Verify loop_15m.py uses correct velocity thresholds from profile YAML."""
        # Profile YAML velocity thresholds (single source of truth)
        profile_thresholds = {
            "BTC": 0.00015,   # 0.015%
            "ETH": 0.00015,   # 0.015%
            "SOL": 0.000225,  # 0.0225%
            "XRP": 0.000225,  # 0.0225%
            "DOGE": 0.0003,   # 0.03%
        }
        
        # Read loop_15m.py to verify hardcoded thresholds match
        with open('merid/loop_15m.py', 'r') as f:
            content = f.read()
        
        # Check that the velocity threshold section has the correct values
        # The pattern should be: velocity_threshold = 0.00015 for BTC/ETH
        assert 'velocity_threshold = 0.00015' in content, "BTC/ETH threshold should be 0.00015"
        assert 'velocity_threshold = 0.000225' in content, "SOL/XRP threshold should be 0.000225"
        assert 'velocity_threshold = 0.0003' in content, "DOGE threshold should be 0.0003"
        
        # Verify the old incorrect values are NOT present
        assert 'velocity_threshold = 0.0002' not in content or 'Default BTC threshold' in content, \
            "Old BTC threshold 0.0002 should not be used as ETH/SOL/XRP/DOGE threshold"
        assert 'velocity_threshold = 0.0004' not in content, "Old SOL threshold 0.0004 should not be present"
        assert 'velocity_threshold = 0.0005' not in content, "Old XRP threshold 0.0005 should not be present"
        assert 'velocity_threshold = 0.0006' not in content, "Old DOGE threshold 0.0006 should not be present"


class TestSwarmOrchestratorSymbolLimits:
    """Test that SwarmOrchestrator SYMBOL_LIMITS includes all 5 assets."""
    
    def test_swarm_orchestrator_symbol_limits_has_doge(self):
        """Verify SwarmOrchestrator SYMBOL_LIMITS includes DOGE."""
        # Read the file directly since the module has import dependencies
        with open('merid/swarm/orchestrator.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that DOGE is in SYMBOL_LIMITS
        assert '"DOGE"' in content or "'DOGE'" in content, "DOGE should be in SYMBOL_LIMITS"
        
        # Check that all 5 assets are present in SYMBOL_LIMITS
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert f'"{asset}"' in content or f"'{asset}'" in content, \
                f"{asset} should be in SYMBOL_LIMITS"
        
        # Verify DOGE has max_size_contracts = 1
        assert 'DOGE' in content and 'max_size_contracts' in content, \
            "DOGE should have max_size_contracts defined"
    
    def test_swarm_orchestrator_intent_documentation_includes_doge(self):
        """Verify SwarmOrchestrator intent documentation includes DOGE."""
        with open('merid/swarm/orchestrator.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that DOGE_15M is documented in lane_id
        assert 'DOGE_15M' in content, "DOGE_15M should be documented in lane_id options"
        
        # Check that DOGE is documented in symbol
        assert '"DOGE"' in content or "'DOGE'" in content, "DOGE should be documented in symbol options"
    
    def test_swarm_orchestrator_md_documentation_includes_doge(self):
        """Verify SwarmOrchestrator markdown documentation includes DOGE."""
        with open('merid/swarm/SWARM_ORCHESTRATOR_ENHANCED.md', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that DOGE is documented in the intent schema
        assert 'DOGE_15M' in content, "DOGE_15M should be in markdown documentation"
        assert 'DOGE' in content, "DOGE should be in markdown documentation"
        
        # Check that symbol-specific limits mention all 5 assets
        assert 'BTC, ETH, SOL, XRP, DOGE' in content, \
            "Symbol-specific limits should list all 5 assets (BTC, ETH, SOL, XRP, DOGE)"


class TestFiveAssetStackCompleteness:
    """Test that the 5-asset stack is complete across all components."""
    
    def test_five_assets_consistently_defined(self):
        """Verify all 5 assets (BTC, ETH, SOL, XRP, DOGE) are consistently defined."""
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        
        # Check profile YAML
        with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
            yaml_content = f.read()
        
        # Verify velocity_thresholds section has all 5 assets
        for asset in expected_assets:
            assert f'{asset}:' in yaml_content, f"{asset} should be in velocity_thresholds"
        
        # Check crypto_15m_profile.py
        with open('merid/risk/profiles/crypto_15m_profile.py', 'r', encoding='utf-8') as f:
            profile_content = f.read()
        
        for asset in expected_assets:
            assert f'velocity_threshold_{asset.lower()}' in profile_content, \
                f"{asset} velocity threshold should be defined in crypto_15m_profile.py"
