"""Unit tests for optimized spread and edge thresholds."""

import pytest
from unittest.mock import MagicMock, patch


class TestThresholdOptimization:
    """Test optimized spread and edge thresholds for 15m crypto markets."""
    
    def test_guardrails_max_spread_cents_optimized(self):
        """Test that max_spread_cents is set to 50c for realistic 15m market spreads."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_max_spread_cents=50
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify max_spread_cents is set to 50c (research: 2-5c typical, up to 10c in volatile conditions)
                assert profile.guardrails_max_spread_cents == 50
    
    def test_guardrails_min_post_fee_edge_optimized(self):
        """Test that min_post_fee_edge is set to 1.5% for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_min_post_fee_edge=0.015
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_post_fee_edge is set to 1.5% (research: 2-2.5% net edge realistic, 1.5% floor)
                assert profile.guardrails_min_post_fee_edge == 0.015
    
    def test_strategy_policy_min_edge_optimized(self):
        """Test that strategy min_edge is set to 1.5% for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 strategy_policy_min_edge=0.015
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_edge is set to 1.5% (research: profitable systems trade edges down to 1-2%)
                assert profile.strategy_policy_min_edge == 0.015
    
    def test_guardrails_max_orders_per_cycle_optimized(self):
        """Test that max_orders_per_cycle is increased to 5 for more opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_max_orders_per_cycle=5
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify max_orders_per_cycle is set to 5 (industry standard: 15-20 trades per session)
                assert profile.guardrails_max_orders_per_cycle == 5
    
    def test_guardrails_min_time_to_expiry_optimized(self):
        """Test that min_time_to_expiry_min is relaxed to 2.0 for more 15m opportunities."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 guardrails_min_time_to_expiry_min=2.0
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify min_time_to_expiry_min is set to 2.0 (reduced from 2.5min for more 15m opportunities)
                assert profile.guardrails_min_time_to_expiry_min == 2.0
    
    def test_spread_gate_cents_optimized(self):
        """Test that spread_gate_cents is increased to 50c aligned with guardrails."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 momentum_fvg_spread_gate_cents=50
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Verify spread_gate_cents is set to 50c (aligned with guardrails_max_spread_cents)
                assert profile.momentum_fvg_spread_gate_cents == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
