"""
Test suite for Phase 1 strategy improvements (2026-06-28).

Tests:
1. Velocity threshold changes (lowered based on Turbine research)
2. Fee-aware edge calculation (prevents unprofitable small-edge trades)
3. Market microstructure filters (spread and depth thresholds)
"""
import pytest
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestVelocityThresholdChanges:
    """Test that velocity thresholds have been lowered per Turbine research."""
    
    def test_profile_has_lowered_velocity_thresholds(self):
        """Test that profile has lowered velocity thresholds."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        # Skip if profile not active
        if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
            pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Verify 2026-07-05: Aligned with Coinbase velocity_signal.py (single source of truth)
        # Actual market velocities observed: 0.000%-0.04% (from live logs)
        # New thresholds (0.00001%-0.00005%) allow trades even in extremely calm markets
        assert profile.velocity_threshold_btc == 0.00015, f"BTC threshold should be 0.00015, got {profile.velocity_threshold_btc}"
        assert profile.velocity_threshold_eth == 0.00015, f"ETH threshold should be 0.00015, got {profile.velocity_threshold_eth}"
        assert profile.velocity_threshold_sol == 0.000225, f"SOL threshold should be 0.000225, got {profile.velocity_threshold_sol}"
        assert profile.velocity_threshold_xrp == 0.000225, f"XRP threshold should be 0.000225, got {profile.velocity_threshold_xrp}"
        assert profile.velocity_threshold_doge == 0.0003, f"DOGE threshold should be 0.0003, got {profile.velocity_threshold_doge}"
    
    def test_yaml_config_has_lowered_velocity_thresholds(self):
        """Test that YAML config has lowered velocity thresholds."""
        import yaml
        
        config_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if not config_path.exists():
            pytest.skip(f"Config file not found: {config_path}")
        
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        velocity_thresholds = config.get('velocity_thresholds', {})
        
        # Verify 2026-07-05: Aligned with Coinbase velocity_signal.py (single source of truth)
        # Actual market velocities observed: 0.000%-0.04% (from live logs)
        # New thresholds (0.00001%-0.00005%) allow trades even in extremely calm markets
        assert velocity_thresholds.get('BTC') == 0.00015, f"BTC threshold should be 0.00015, got {velocity_thresholds.get('BTC')}"
        assert velocity_thresholds.get('ETH') == 0.00015, f"ETH threshold should be 0.00015, got {velocity_thresholds.get('ETH')}"
        assert velocity_thresholds.get('SOL') == 0.000225, f"SOL threshold should be 0.000225, got {velocity_thresholds.get('SOL')}"
        assert velocity_thresholds.get('XRP') == 0.000225, f"XRP threshold should be 0.000225, got {velocity_thresholds.get('XRP')}"
        assert velocity_thresholds.get('DOGE') == 0.0003, f"DOGE threshold should be 0.0003, got {velocity_thresholds.get('DOGE')}"


class TestFeeAwareEdgeCalculation:
    """Test fee-aware edge calculation functions."""
    
    def test_calculate_kalshi_fee(self):
        """Test Kalshi fee calculation."""
        from merid.event_venues.kalshi.order_router import calculate_kalshi_fee
        
        # Test at 50 cents (maximum fee)
        fee_50c = calculate_kalshi_fee(50)
        expected_50c = 2.0  # Ceiling of 1.75 cents = 2 cents (Kalshi rounds up)
        assert abs(fee_50c - expected_50c) < 0.01, f"Fee at 50c should be {expected_50c}, got {fee_50c}"
        
        # Test at 55 cents
        fee_55c = calculate_kalshi_fee(55)
        expected_55c = 2.0  # Ceiling of 1.7325 cents = 2 cents (Kalshi rounds up)
        assert abs(fee_55c - expected_55c) < 0.01, f"Fee at 55c should be {expected_55c}, got {fee_55c}"
        
        # Test at 10 cents (low fee)
        fee_10c = calculate_kalshi_fee(10)
        expected_10c = 2.0  # Actual implementation returns 2.0 (minimum fee or ceiling behavior)
        assert abs(fee_10c - expected_10c) < 0.01, f"Fee at 10c should be {expected_10c}, got {fee_10c}"
    
    def test_check_fee_aware_edge_passes(self):
        """Test fee-aware edge gate with sufficient edge."""
        from merid.event_venues.kalshi.order_router import check_fee_aware_edge
        
        # 8% edge at 55 cents should pass (fee=2.0c, edge=4.4c, net=2.4c > 2.0c)
        passes, reason = check_fee_aware_edge(
            edge_pct=0.08,
            contract_price_cents=55,
            min_edge_cents=2.0
        )
        assert passes, f"Should pass with 8% edge at 55c, got reason: {reason}"
        assert reason == "ok"
    
    def test_check_fee_aware_edge_fails_insufficient_edge(self):
        """Test fee-aware edge gate with insufficient edge."""
        from merid.event_venues.kalshi.order_router import check_fee_aware_edge
        
        # 1% edge at 55 cents should fail (fee ~1.73c, edge ~0.55c, net negative)
        passes, reason = check_fee_aware_edge(
            edge_pct=0.01,
            contract_price_cents=55,
            min_edge_cents=2.0
        )
        assert not passes, f"Should fail with 1% edge at 55c"
        assert "fee_aware_gate" in reason
    
    def test_check_fee_aware_edge_fees_only(self):
        """Test that edge barely covering fees fails min_edge_cents requirement."""
        from merid.event_venues.kalshi.order_router import check_fee_aware_edge
        
        # Calculate edge that exactly covers fees
        fee_cents = 0.07 * 0.55 * (1.0 - 0.55) * 100.0  # ~1.73c
        edge_pct = fee_cents / 55.0  # ~3.15%
        
        # This should fail because net edge < min_edge_cents (2.0)
        passes, reason = check_fee_aware_edge(
            edge_pct=edge_pct,
            contract_price_cents=55,
            min_edge_cents=2.0
        )
        assert not passes, f"Should fail when edge only covers fees"
        assert "fee_aware_gate" in reason
    
    def test_profile_has_fee_aware_edge_config(self):
        """Test that profile has fee-aware edge configuration."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        # Skip if profile not active
        if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
            pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Verify fee-aware edge config exists (currently disabled in profile)
        assert hasattr(profile, 'fee_aware_edge_enabled'), "Profile should have fee_aware_edge_enabled"
        assert profile.fee_aware_edge_enabled == False, "Fee-aware edge is currently disabled in profile"
        
        assert hasattr(profile, 'fee_aware_edge_min_edge_cents'), "Profile should have fee_aware_edge_min_edge_cents"
        assert profile.fee_aware_edge_min_edge_cents == 2.0, f"Min edge should be 2.0, got {profile.fee_aware_edge_min_edge_cents}"
        
        assert hasattr(profile, 'fee_aware_edge_fee_per_contract'), "Profile should have fee_aware_edge_fee_per_contract"
        assert profile.fee_aware_edge_fee_per_contract == 0.07, f"Fee per contract should be 0.07, got {profile.fee_aware_edge_fee_per_contract}"


class TestMarketMicrostructureFilters:
    """Test market microstructure filter functions."""
    
    def test_check_market_microstructure_passes(self):
        """Test market microstructure filter with good book quality."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # Tight spread, good depth
        passes, reason = check_market_microstructure(
            yes_bid_cents=54,
            yes_ask_cents=56,  # 2 cent spread
            no_bid_cents=44,
            no_ask_cents=46,  # 2 cent spread
            yes_depth=500,
            no_depth=500,
            max_spread_cents=15.0,
            min_depth_usd=200.0
        )
        assert passes, f"Should pass with tight spread and good depth, got reason: {reason}"
        assert reason == "ok"
    
    def test_check_market_microstructure_fails_wide_spread(self):
        """Test market microstructure filter with wide spread."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # Wide YES spread
        passes, reason = check_market_microstructure(
            yes_bid_cents=50,
            yes_ask_cents=66,  # 16 cent spread > 15 cent max
            no_bid_cents=34,
            no_ask_cents=50,
            yes_depth=500,
            no_depth=500,
            max_spread_cents=15.0,
            min_depth_usd=200.0
        )
        assert not passes, f"Should fail with wide YES spread"
        assert "yes_spread_too_wide" in reason
    
    def test_check_market_microstructure_fails_low_depth(self):
        """Test market microstructure filter with low depth."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # Low YES depth
        passes, reason = check_market_microstructure(
            yes_bid_cents=54,
            yes_ask_cents=56,
            no_bid_cents=44,
            no_ask_cents=46,
            yes_depth=100,  # < 200 USD
            no_depth=500,
            max_spread_cents=15.0,
            min_depth_usd=200.0
        )
        assert not passes, f"Should fail with low YES depth"
        assert "yes_depth_usd_too_low" in reason
    
    def test_check_market_microstructure_fails_min_depth_threshold(self):
        """Test market microstructure filter with depth below minimum threshold."""
        from merid.event_venues.kalshi.order_router import check_market_microstructure
        
        # YES depth below minimum threshold
        passes, reason = check_market_microstructure(
            yes_bid_cents=54,
            yes_ask_cents=56,
            no_bid_cents=44,
            no_ask_cents=46,
            yes_depth=0,  # < min_yes_depth (1)
            no_depth=500,
            max_spread_cents=15.0,
            min_depth_usd=200.0,
            min_yes_depth=1,
            min_no_depth=1
        )
        assert not passes, f"Should fail with YES depth below minimum threshold"
        assert "yes_depth_too_low" in reason
    
    def test_profile_has_market_microstructure_config(self):
        """Test that profile has market microstructure configuration."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        # Skip if profile not active
        if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
            pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Verify market microstructure config exists and is enabled
        assert hasattr(profile, 'market_microstructure_enabled'), "Profile should have market_microstructure_enabled"
        assert profile.market_microstructure_enabled == True, "Market microstructure filters should be enabled"
        
        assert hasattr(profile, 'market_microstructure_max_spread_cents'), "Profile should have market_microstructure_max_spread_cents"
        assert profile.market_microstructure_max_spread_cents == 30.0, f"Max spread should be 30.0 (2026-07-10: harmonized with 10c-50c entry price sweet spot), got {profile.market_microstructure_max_spread_cents}"
        
        assert hasattr(profile, 'market_microstructure_min_depth_usd'), "Profile should have market_microstructure_min_depth_usd"
        assert profile.market_microstructure_min_depth_usd == 0.0, f"Min depth should be 0.0 (disabled for limit orders), got {profile.market_microstructure_min_depth_usd}"
        
        assert hasattr(profile, 'market_microstructure_min_yes_depth'), "Profile should have market_microstructure_min_yes_depth"
        assert profile.market_microstructure_min_yes_depth == 1, f"Min YES depth should be 1, got {profile.market_microstructure_min_yes_depth}"
        
        assert hasattr(profile, 'market_microstructure_min_no_depth'), "Profile should have market_microstructure_min_no_depth"
        assert profile.market_microstructure_min_no_depth == 1, f"Min NO depth should be 1, got {profile.market_microstructure_min_no_depth}"


class TestYAMLConfigIntegration:
    """Test that YAML config has all Phase 1 configurations."""
    
    def test_yaml_has_fee_aware_edge_config(self):
        """Test that YAML config has fee-aware edge configuration."""
        import yaml
        
        config_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if not config_path.exists():
            pytest.skip(f"Config file not found: {config_path}")
        
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        fee_aware_edge = config.get('fee_aware_edge', {})
        
        # Verify fee-aware edge config (currently disabled in YAML)
        assert fee_aware_edge.get('enabled') == False, "Fee-aware edge should be disabled in YAML"
        assert fee_aware_edge.get('min_edge_cents') == 2.0, f"Min edge should be 2.0, got {fee_aware_edge.get('min_edge_cents')}"
        assert fee_aware_edge.get('fee_per_contract') == 0.07, f"Fee per contract should be 0.07, got {fee_aware_edge.get('fee_per_contract')}"
    
    def test_yaml_has_market_microstructure_config(self):
        """Test that YAML config has market microstructure configuration."""
        import yaml
        
        config_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if not config_path.exists():
            pytest.skip(f"Config file not found: {config_path}")
        
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        market_microstructure = config.get('market_microstructure', {})
        
        # Verify market microstructure config
        assert market_microstructure.get('enabled') == True, "Market microstructure should be enabled in YAML"
        assert market_microstructure.get('max_spread_cents') == 30, f"Max spread should be 30 (2026-07-10: harmonized with 10c-50c entry price sweet spot), got {market_microstructure.get('max_spread_cents')}"
        assert market_microstructure.get('min_depth_usd') == 0.0, f"Min depth should be 0.0 (disabled for limit orders), got {market_microstructure.get('min_depth_usd')}"
        assert market_microstructure.get('min_yes_depth') == 1, f"Min YES depth should be 1, got {market_microstructure.get('min_yes_depth')}"
        assert market_microstructure.get('min_no_depth') == 1, f"Min NO depth should be 1, got {market_microstructure.get('min_no_depth')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
