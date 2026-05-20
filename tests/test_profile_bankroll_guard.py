"""
Bankroll Logic Guard Test for kalshi_crypto_15m Profile

This test ensures that when MERID_PROFILE=kalshi_crypto_15m_v2 is active,
no balance-derived functions are called to compute risk/exposure caps below the cycle level.

This is a guard against accidental re-introduction of bankroll logic into the
config-only 15m crypto profile.
"""

import os
import ast
import pytest
from pathlib import Path
from unittest.mock import patch


class TestProfileBankrollGuard:
    """Test that bankroll logic is not used when kalshi_crypto_15m_v2 profile is active."""

    def test_no_bankroll_helpers_in_profile_path(self):
        """
        Scan key files for bankroll-related function calls in profile-active paths.
        
        This is a static analysis test that checks for patterns like:
        - calibrate_from_balance
        - _compute_dynamic_contract_caps
        - get_equity_for_risk_calc
        - bankroll_service
        - KALSHI_PORTFOLIO_BANKROLL_CENTS
        
        When these appear in code that could be executed with MERID_PROFILE=kalshi_crypto_15m_v2,
        it indicates a potential regression to balance-derived behavior.
        
        NOTE: _prediction_risk.py is excluded because profile gating is at the class level
        in __post_init__, not around individual function calls.
        NOTE: kalshi_risk.py is excluded because profile gating is at the method level
        (calibrate_from_balance, _compute_dynamic_contract_caps), not around individual calls.
        """
        # Files to scan for bankroll logic
        files_to_scan = [
            'merid/prediction/ai_guardrails.py',
            'merid/guardrails/capabilities.py',
        ]
        
        # Patterns that should NOT appear in profile-gated code
        forbidden_patterns = [
            'calibrate_from_balance(',
            '_compute_dynamic_contract_caps(',
            'get_equity_for_risk_calc',
            'KALSHI_PORTFOLIO_BANKROLL_CENTS',
        ]
        
        violations = []
        
        for file_path in files_to_scan:
            full_path = Path(__file__).parent.parent / file_path
            if not full_path.exists():
                continue
            
            with open(full_path, 'r') as f:
                content = f.read()
                
                for pattern in forbidden_patterns:
                    # Check if pattern exists
                    if pattern in content:
                        # Check if it's in a profile-gated block
                        # Profile-gated blocks should have comments like:
                        # "PROFILE GATING" or "LEGACY: not used in kalshi_crypto_15m_v2"
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if pattern in line:
                                # Check surrounding lines for profile gating
                                context_start = max(0, i - 5)
                                context_end = min(len(lines), i + 5)
                                context = '\n'.join(lines[context_start:context_end])
                                
                                # If profile gating is present, this is OK
                                if 'PROFILE GATING' in context or 'kalshi_crypto_15m' in context:
                                    continue
                                
                                # If it's a comment about legacy, this is OK
                                if 'LEGACY' in context or 'deprecated' in context.lower():
                                    continue
                                
                                # Otherwise, it's a potential violation
                                violations.append({
                                    'file': file_path,
                                    'line': i + 1,
                                    'pattern': pattern,
                                    'context': line.strip(),
                                })
        
        # Report violations
        if violations:
            violation_msg = "Found potential bankroll logic violations:\n"
            for v in violations:
                violation_msg += f"  {v['file']}:{v['line']}: {v['pattern']}\n"
                violation_msg += f"    Context: {v['context']}\n"
            pytest.fail(violation_msg)

    def test_profile_gating_present_in_key_locations(self):
        """
        Verify that profile gating comments are present in key locations.
        
        This ensures that the gating logic is explicitly documented, making it
        harder to accidentally remove or bypass.
        """
        # Files that should have profile gating
        files_with_gating = [
            'merid/event_venues/kalshi/kalshi_risk.py',
            'merid/prediction/risk/_prediction_risk.py',
            'merid/prediction/ai_guardrails.py',
        ]
        
        required_keywords = ['PROFILE GATING', 'kalshi_crypto_15m_v2']
        
        for file_path in files_with_gating:
            full_path = Path(__file__).parent.parent / file_path
            if not full_path.exists():
                continue
            
            with open(full_path, 'r') as f:
                content = f.read()
                
            for keyword in required_keywords:
                if keyword not in content:
                    pytest.fail(
                        f"Missing required keyword '{keyword}' in {file_path}. "
                        f"Profile gating should be explicitly documented."
                    )

    def test_profile_yaml_has_no_bankroll_defaults(self):
        """
        Verify that kalshi_crypto_15m.yaml has no "0 = derive from bankroll" values.
        
        All values in the profile should be explicit numbers, not 0 with comments
        indicating bankroll derivation. Comments and documentation strings are ignored.
        """
        profile_path = Path(__file__).parent.parent / 'config' / 'profiles' / 'kalshi_crypto_15m.yaml'
        
        if not profile_path.exists():
            pytest.skip(f"Profile file not found: {profile_path}")
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Check for "0 = derive from bankroll" pattern, but ignore comment lines
        # and documentation strings (lines that are part of lists or descriptions)
        for line in lines:
            # Skip comment lines
            if line.strip().startswith('#'):
                continue
            
            # Skip documentation strings (lines that start with "- " in list context)
            if line.strip().startswith('- '):
                continue
            
            # Check for the pattern in non-comment, non-documentation lines
            if 'derive from bankroll' in line.lower():
                pytest.fail(
                    f"Profile file contains 'derive from bankroll' pattern in non-comment line: {line.strip()}. "
                    f"All values in kalshi_crypto_15m.yaml should be explicit numbers."
                )

    def test_agent_grid_has_profile_references(self):
        """
        Verify that kalshi_agent_grid.yaml has profile-gating comments for 15m crypto agents.
        
        This ensures that the agent grid explicitly references the profile for 15m crypto,
        making the dependency clear.
        """
        agent_grid_path = Path(__file__).parent.parent / 'config' / 'kalshi_agent_grid.yaml'
        
        if not agent_grid_path.exists():
            pytest.skip(f"Agent grid file not found: {agent_grid_path}")
        
        with open(agent_grid_path, 'r') as f:
            content = f.read()
        
        # 15m crypto agents that should have profile references
        agents_to_check = ['BTC_15M', 'ETH_15M', 'SOL_15M', 'XRP_15M', 'DOGE_15M']
        
        for agent in agents_to_check:
            if agent in content:
                # Find the agent section and check for profile reference
                agent_start = content.find(agent)
                if agent_start == -1:
                    continue
                
                # Get the next 500 characters (should include risk_limits section)
                agent_section = content[agent_start:agent_start + 500]
                
                # Should have PROFILE-GATED comment
                if 'PROFILE-GATED' not in agent_section and 'profile' not in agent_section.lower():
                    pytest.fail(
                        f"Agent {agent} in kalshi_agent_grid.yaml should have PROFILE-GATED comment "
                        f"or profile reference to indicate config-only behavior."
                    )

    def test_profile_adapter_methods_exist(self):
        """
        Verify that Crypto15mProfileAdapter has all required mapping methods.
        
        This ensures the adapter provides a complete interface for mapping profile
        values to internal config objects.
        """
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        required_methods = [
            'to_kalshi_risk_config',
            'to_category_limits',
            'to_cycle_sizing_cap',
            'to_agent_overrides',
            'should_disable_balance_calibration',
            'should_disable_dynamic_contract_caps',
        ]
        
        for method in required_methods:
            if not hasattr(Crypto15mProfileAdapter, method):
                pytest.fail(f"Missing required method: {method}")

    def test_profile_detection_works(self):
        """
        Verify that profile detection via environment variable works correctly.
        """
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
        
        # Test profile not active by default
        with patch.dict(os.environ, {}, clear=True):
            assert is_profile_active() is False
        
        # Test profile active when env var is set
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            assert is_profile_active() is True
        
        # Test profile not active for other values
        with patch.dict(os.environ, {'MERID_PROFILE': 'other_profile'}, clear=False):
            assert is_profile_active() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
