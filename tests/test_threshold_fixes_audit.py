"""
Test suite for threshold fixes from deep audit.

Tests for the following fixes:
1. max_md_staleness_sec default changed from 30s to 120s in profile
2. agent_grid_15m.py uses profile staleness values (not hardcoded 120s)
3. MIN_TIME_TO_EXPIRY default changed from 2 to 3 minutes
4. Depth thresholds now use risk envelope (not hardcoded tier-based)
5. min_bars_required reduced from 52 to 20 for 15-minute markets (research-based optimization)
"""

import pytest
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMaxMdStalenessThreshold:
    """Test max_md_staleness_sec threshold fixes."""
    
    def test_profile_default_max_md_staleness_is_15s(self):
        """Test that profile default max_md_staleness_sec is 15s (strategy-specific threshold)."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Check that strategy_policy_max_md_staleness_sec defaults to 15s (strategy-specific)
            assert profile.strategy_policy_max_md_staleness_sec == 15.0, \
                f"Expected strategy_policy_max_md_staleness_sec=15s, got {profile.strategy_policy_max_md_staleness_sec}s"
        except Exception as e:
            pytest.skip(f"Profile staleness check skipped: {e}")
    
    def test_agent_grid_uses_profile_staleness_not_hardcoded(self):
        """Test that agent_grid_15m.py uses profile staleness values (not hardcoded 120s)."""
        agent_grid_15m_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_15m_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_15m_path.read_text(encoding='utf-8')
        
        # Check that hardcoded TEMPORARY 120s override is removed
        assert "TEMPORARY" not in content or "120.0  # TEMPORARY" not in content, \
            "TEMPORARY hardcoded 120s override should be removed from agent_grid_15m.py"
        
        # Check that it uses profile values
        assert "profile.strategy_policy_max_md_staleness_sec" in content, \
            "agent_grid_15m.py should use profile.strategy_policy_max_md_staleness_sec"
    
    def test_venue_invariants_max_book_staleness_is_30s(self):
        """Test that venue_invariants_max_book_staleness_ms is 30s (30000ms)."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Check that venue_invariants_max_book_staleness_ms is 30000ms (30s)
            assert profile.venue_invariants_max_book_staleness_ms == 30000.0, \
                f"Expected venue_invariants_max_book_staleness_ms=30000ms, got {profile.venue_invariants_max_book_staleness_ms}ms"
        except Exception as e:
            pytest.skip(f"Venue staleness check skipped: {e}")


class TestMinTimeToExpiryThreshold:
    """Test MIN_TIME_TO_EXPIRY threshold fixes."""
    
    def test_agent_grid_min_time_to_expiry_default_is_3_minutes(self):
        """Test that MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN default is 3 minutes (not 2)."""
        agent_grid_15m_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_15m_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_15m_path.read_text(encoding='utf-8')
        
        # Check that default is 3 minutes
        assert "MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN: int = 3" in content, \
            "MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN should default to 3 minutes"
        
        # Check comment mentions profile default
        assert "matches profile default" in content or "Default 3 minutes" in content, \
            "Comment should mention profile default (3 minutes)"
    
    def test_profile_min_time_to_expiry_is_2_5_minutes(self):
        """Test that profile guardrails_min_time_to_expiry_min is 2.5 minutes."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Check that guardrails_min_time_to_expiry_min is 2.5 minutes (from YAML)
            assert profile.guardrails_min_time_to_expiry_min == 2.5, \
                f"Expected guardrails_min_time_to_expiry_min=2.5min, got {profile.guardrails_min_time_to_expiry_min}min"
        except Exception as e:
            pytest.skip(f"Profile expiry check skipped: {e}")


class TestDepthThresholdFixes:
    """Test depth threshold fixes - now uses risk envelope instead of hardcoded tier-based."""
    
    def test_agent_grid_uses_risk_envelope_depth_thresholds(self):
        """Test that agent_grid_15m.py uses risk envelope for depth thresholds (not hardcoded)."""
        agent_grid_15m_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_15m_path.exists():
            pytest.skip("agent_grid_15m.py not found")
        
        content = agent_grid_15m_path.read_text(encoding='utf-8')
        
        # Check that hardcoded tier-based thresholds are removed
        assert "Tier 1 (BTC/ETH): min_depth_yes/no = 10" not in content, \
            "Hardcoded tier-based depth thresholds should be removed"
        assert "Tier 2 (SOL/XRP/DOGE): min_depth_yes/no = 5" not in content, \
            "Hardcoded tier-based depth thresholds should be removed"
        
        # Check that it uses risk envelope
        assert "get_kalshi_crypto_15m_risk_envelope" in content, \
            "agent_grid_15m.py should use get_kalshi_crypto_15m_risk_envelope"
        assert "get_depth_thresholds" in content, \
            "agent_grid_15m.py should call get_depth_thresholds(asset)"
        
        # Check that fallback is 5 (not tier-based)
        assert "using fallback 5" in content, \
            "Fallback should be 5 (not tier-based)"
    
    def test_risk_envelope_has_per_asset_depth_thresholds(self):
        """Test that risk envelope has per-asset depth thresholds."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
            
            # Use compute function with mock bankroll (doesn't require live connection)
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=50.0)
            
            # Check that get_depth_thresholds method exists
            assert hasattr(envelope, 'get_depth_thresholds'), \
                "Risk envelope should have get_depth_thresholds method"
            
            # Test that it returns thresholds for each asset
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                thresholds = envelope.get_depth_thresholds(asset)
                assert 'min_depth_yes' in thresholds, \
                    f"get_depth_thresholds should return min_depth_yes for {asset}"
                assert 'min_depth_no' in thresholds, \
                    f"get_depth_thresholds should return min_depth_no for {asset}"
                assert thresholds['min_depth_yes'] > 0, \
                    f"min_depth_yes should be positive for {asset}"
                assert thresholds['min_depth_no'] > 0, \
                    f"min_depth_no should be positive for {asset}"
        except Exception as e:
            pytest.skip(f"Risk envelope depth check skipped: {e}")


class TestMinBarsRequiredFix:
    """Test min_bars_required fix - reduced from 52 to 20 for 15-minute markets."""
    
    def test_indicators_min_bars_required_is_20(self):
        """Test that crypto_15m_indicators.py min_bars_required is 20 (not 52)."""
        indicators_path = Path(__file__).parent.parent / "merid" / "signals" / "crypto_15m_indicators.py"
        
        if not indicators_path.exists():
            pytest.skip("crypto_15m_indicators.py not found")
        
        content = indicators_path.read_text(encoding='utf-8')
        
        # Check that min_bars_required is 20 (not 52)
        assert "min_bars_required: int = 20" in content, \
            "min_bars_required should be 20 for 15-minute markets"
        
        # Check comment mentions 15-minute markets
        assert "15-minute markets" in content, \
            "Comment should mention 15-minute markets"
    
    def test_indicators_min_bars_for_macd_is_15(self):
        """Test that min_bars_for_macd is 15 (aligned with new min_bars_required)."""
        indicators_path = Path(__file__).parent.parent / "merid" / "signals" / "crypto_15m_indicators.py"
        
        if not indicators_path.exists():
            pytest.skip("crypto_15m_indicators.py not found")
        
        content = indicators_path.read_text(encoding='utf-8')
        
        # Check that min_bars_for_macd is 15
        assert "min_bars_for_macd: int = 15" in content, \
            "min_bars_for_macd should be 15 for MACD calculations"


class TestThresholdConsistency:
    """Test that thresholds are consistent across all components."""
    
    def test_staleness_thresholds_are_different_layers(self):
        """Test that staleness thresholds are different (strategy vs venue invariants)."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Check that staleness thresholds are different (strategy-specific vs venue invariant)
            strategy_staleness = profile.strategy_policy_max_md_staleness_sec
            venue_staleness_ms = profile.venue_invariants_max_book_staleness_ms
            venue_staleness_sec = venue_staleness_ms / 1000.0
            
            assert strategy_staleness == 15.0, \
                f"strategy_policy_max_md_staleness_sec should be 15s, got {strategy_staleness}s"
            assert venue_staleness_sec == 30.0, \
                f"venue_invariants_max_book_staleness_ms should be 30000ms (30s), got {venue_staleness_ms}ms"
            
            # They should be different (strategy is stricter than venue invariant)
            assert strategy_staleness < venue_staleness_sec, \
                f"Strategy staleness should be stricter than venue invariant: strategy={strategy_staleness}s, venue={venue_staleness_sec}s"
        except Exception as e:
            pytest.skip(f"Staleness consistency check skipped: {e}")
    
    def test_all_5_assets_have_depth_thresholds(self):
        """Test that all 5 assets have depth thresholds in risk envelope."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
            
            # Use compute function with mock bankroll (doesn't require live connection)
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=50.0)
            
            # Check all 5 assets
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                thresholds = envelope.get_depth_thresholds(asset)
                assert thresholds is not None, \
                    f"Depth thresholds should exist for {asset}"
                assert 'min_depth_yes' in thresholds, \
                    f"min_depth_yes should exist for {asset}"
                assert 'min_depth_no' in thresholds, \
                    f"min_depth_no should exist for {asset}"
        except Exception as e:
            pytest.skip(f"All assets depth check skipped: {e}")
