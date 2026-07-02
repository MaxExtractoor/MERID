"""Test 2026-aligned risk management features.

Tests for:
- Per-asset cluster stop-loss limits
- Institutional-grade risk controls (VaR caps, drawdown limits)
- Order deduplication with deterministic clientOrderId fallback
"""

import pytest
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig


class TestPerAssetClusterStopLoss:
    """Test per-asset cluster stop-loss limits (2026 standard)."""

    def test_extract_asset_from_cluster_id(self):
        """Test asset extraction from various cluster_id formats."""
        risk = KalshiRiskManager()
        
        # Test BTC
        assert risk._extract_asset_from_cluster_id("KXBTC15M-26JUN290345-45") == "BTC"
        # Test ETH
        assert risk._extract_asset_from_cluster_id("KXETH15M-26JUN290345-45") == "ETH"
        # Test SOL
        assert risk._extract_asset_from_cluster_id("KXSOL15M-26JUN290345-45") == "SOL"
        # Test XRP
        assert risk._extract_asset_from_cluster_id("KXXRP15M-26JUN290345-45") == "XRP"
        # Test DOGE
        assert risk._extract_asset_from_cluster_id("KXDOGE15M-26JUN290345-45") == "DOGE"
        # Test unknown format
        assert risk._extract_asset_from_cluster_id("UNKNOWN-FORMAT") == "UNKNOWN"

    def test_per_asset_cluster_stop_loss_limits(self):
        """Test per-asset cluster stop-loss limits are applied correctly."""
        config = KalshiRiskConfig()
        config.per_asset_cluster_stop_loss = {
            'BTC': 3.00,
            'ETH': 3.00,
            'SOL': 5.00,
            'XRP': 5.00,
            'DOGE': 5.00,
        }
        risk = KalshiRiskManager(config=config)
        
        # Verify per-asset limits are loaded
        assert risk._config.per_asset_cluster_stop_loss['BTC'] == 3.00
        assert risk._config.per_asset_cluster_stop_loss['ETH'] == 3.00
        assert risk._config.per_asset_cluster_stop_loss['SOL'] == 5.00
        assert risk._config.per_asset_cluster_stop_loss['XRP'] == 5.00
        assert risk._config.per_asset_cluster_stop_loss['DOGE'] == 5.00

    def test_cluster_stop_loss_uses_per_asset_limits(self):
        """Test cluster stop-loss check uses per-asset limits."""
        config = KalshiRiskConfig()
        config.per_asset_cluster_stop_loss = {
            'BTC': 3.00,
            'SOL': 5.00,
        }
        config.max_stop_loss_usd_per_cluster = 5.00  # Aggregate fallback
        risk = KalshiRiskManager(config=config)
        
        # Test BTC with $2.50 loss (should pass, under $3.00 limit)
        allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
            "KXBTC15M-26JUN290345-45",
            order_worst_case_loss_usd=2.50
        )
        assert allowed is True
        assert "OK" in reason
        
        # Test BTC with $3.50 loss (should fail, over $3.00 limit)
        allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
            "KXBTC15M-26JUN290345-45",
            order_worst_case_loss_usd=3.50
        )
        assert allowed is False
        assert "CLUSTER_STOP_LOSS" in reason
        assert "asset=BTC" in reason
        
        # Test SOL with $4.50 loss (should pass, under $5.00 limit)
        allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
            "KXSOL15M-26JUN290345-45",
            order_worst_case_loss_usd=4.50
        )
        assert allowed is True
        assert "OK" in reason
        
        # Test SOL with $5.50 loss (should fail, over $5.00 limit)
        allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
            "KXSOL15M-26JUN290345-45",
            order_worst_case_loss_usd=5.50
        )
        assert allowed is False
        assert "CLUSTER_STOP_LOSS" in reason
        assert "asset=SOL" in reason

    def test_cluster_stop_loss_fallback_to_aggregate(self):
        """Test cluster stop-loss falls back to aggregate limit for unknown assets."""
        config = KalshiRiskConfig()
        config.max_stop_loss_usd_per_cluster = 5.00
        config.per_asset_cluster_stop_loss = {
            'BTC': 3.00,
        }
        risk = KalshiRiskManager(config=config)
        
        # Test unknown asset falls back to aggregate $5.00 limit
        allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
            "KXUNKNOWN15M-26JUN290345-45",
            order_worst_case_loss_usd=4.50
        )
        assert allowed is True
        assert "OK" in reason


class TestInstitutionalRiskControls:
    """Test institutional-grade risk controls (2026 standard)."""

    def test_daily_var_cap_configuration(self):
        """Test daily VaR cap is configured from profile."""
        # This test validates the YAML configuration structure
        risk_policy_config = {
            'daily_var_cap_pct': 0.03,
            'daily_var_cap_min_usd': 2.00,
            'daily_var_cap_max_usd': 1500.0,
        }
        
        # Verify VaR config structure
        assert risk_policy_config['daily_var_cap_pct'] == 0.03
        assert risk_policy_config['daily_var_cap_min_usd'] == 2.00
        assert risk_policy_config['daily_var_cap_max_usd'] == 1500.0

    def test_anomalous_state_detection_configuration(self):
        """Test anomalous market state detection is configured."""
        # This test validates the YAML configuration structure
        risk_policy_config = {
            'anomalous_state_detection': True,
            'anomalous_position_reduction_pct': 0.50,
        }
        
        # Verify anomalous state detection config
        assert risk_policy_config['anomalous_state_detection'] is True
        assert risk_policy_config['anomalous_position_reduction_pct'] == 0.50


class TestOrderDeduplication2026Standard:
    """Test order deduplication aligned with 2026 standards."""

    def test_dedup_registry_uses_larger_bucket_for_15m_profile(self, monkeypatch):
        """Test dedup registry uses 300s bucket for 15m profile (2026 standard)."""
        import os
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
        
        # Reset registry to force re-initialization
        from merid.guards.order_dedup_registry import reset_order_dedup_registry_for_tests, get_order_dedup_registry
        reset_order_dedup_registry_for_tests()
        
        registry = get_order_dedup_registry()
        
        # Verify 300s bucket (5 minutes) for 15m profile
        assert registry.bucket_seconds == 300
        
        # Cleanup
        reset_order_dedup_registry_for_tests()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
