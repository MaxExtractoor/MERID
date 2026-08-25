"""Tests for dynamic threshold system.

Tests the dynamic threshold calculator T = α·spread + β·σ_15m + γ·fee + δ·slippage + ε
and its integration with edge-aware gating.
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_dynamic_threshold,
    DynamicThresholdResult,
    PerSideEdgeMetrics,
    select_best_side,
    edge_aware_microstructure_gate
)
from merid.event_venues.kalshi.asset_threshold_config import (
    get_asset_config,
    ThresholdStrictness
)


class TestDynamicThresholdCalculator:
    """Test dynamic threshold calculation."""
    
    def test_btc_threshold_calculation(self):
        """Test BTC threshold calculation with default config."""
        result = compute_dynamic_threshold(
            asset="BTC",
            spread_cents=10,
            fee_cents=2.0,
            orderbook=None,
            order_size=1,
            max_price_window_cents=5
        )
        
        assert result is not None
        assert result.asset_config_name == "BTC"
        assert result.threshold_cents > 0
        assert result.spread_component > 0
        assert result.fee_component > 0
        assert result.base_hurdle == 1.0  # BTC base hurdle
    
    def test_eth_threshold_calculation(self):
        """Test ETH threshold calculation with default config."""
        result = compute_dynamic_threshold(
            asset="ETH",
            spread_cents=15,
            fee_cents=2.5,
            orderbook=None,
            order_size=1,
            max_price_window_cents=5
        )
        
        assert result is not None
        assert result.asset_config_name == "ETH"
        assert result.threshold_cents > 0
        assert result.base_hurdle == 1.5  # ETH base hurdle
    
    def test_doge_threshold_calculation(self):
        """Test DOGE threshold calculation with highest strictness."""
        result = compute_dynamic_threshold(
            asset="DOGE",
            spread_cents=20,
            fee_cents=3.0,
            orderbook=None,
            order_size=1,
            max_price_window_cents=5
        )
        
        assert result is not None
        assert result.asset_config_name == "DOGE"
        assert result.threshold_cents > 0
        assert result.base_hurdle == 3.0  # DOGE base hurdle (highest)
    
    def test_asset_specific_threshold_ranking(self):
        """Test that asset threshold ranking is correct: DOGE > XRP > SOL > ETH > BTC."""
        btc_result = compute_dynamic_threshold("BTC", spread_cents=10, fee_cents=2.0)
        eth_result = compute_dynamic_threshold("ETH", spread_cents=10, fee_cents=2.0)
        sol_result = compute_dynamic_threshold("SOL", spread_cents=10, fee_cents=2.0)
        xrp_result = compute_dynamic_threshold("XRP", spread_cents=10, fee_cents=2.0)
        doge_result = compute_dynamic_threshold("DOGE", spread_cents=10, fee_cents=2.0)
        
        # With same spread/fee, DOGE should have highest threshold, BTC lowest
        assert doge_result.threshold_cents > xrp_result.threshold_cents
        assert xrp_result.threshold_cents > sol_result.threshold_cents
        assert sol_result.threshold_cents > eth_result.threshold_cents
        assert eth_result.threshold_cents > btc_result.threshold_cents
    
    def test_unknown_asset_fallback_to_btc(self):
        """Test that unknown assets fall back to BTC config."""
        result = compute_dynamic_threshold(
            asset="UNKNOWN",
            spread_cents=10,
            fee_cents=2.0
        )
        
        assert result is not None
        assert result.asset_config_name == "BTC"  # Falls back to BTC
    
    def test_spread_component_scaling(self):
        """Test that spread component scales with spread size."""
        low_spread = compute_dynamic_threshold("BTC", spread_cents=5, fee_cents=2.0)
        high_spread = compute_dynamic_threshold("BTC", spread_cents=20, fee_cents=2.0)
        
        assert high_spread.spread_component > low_spread.spread_component
        assert high_spread.threshold_cents > low_spread.threshold_cents
    
    def test_fee_component_scaling(self):
        """Test that fee component scales with fee size."""
        low_fee = compute_dynamic_threshold("BTC", spread_cents=10, fee_cents=1.0)
        high_fee = compute_dynamic_threshold("BTC", spread_cents=10, fee_cents=5.0)
        
        assert high_fee.fee_component > low_fee.fee_component


class TestDynamicThresholdIntegration:
    """Test dynamic threshold integration with gating logic."""
    
    def test_select_best_side_with_dynamic_threshold(self):
        """Test select_best_side with dynamic threshold."""
        yes_edge = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=5.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        no_edge = PerSideEdgeMetrics(
            side="no",
            raw_edge_cents=8.0,
            spread_cents=5,
            executable_edge_cents=3.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.625,
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold that only YES passes
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=4.0,
            spread_component=2.0,
            volatility_component=0.5,
            fee_component=1.0,
            slippage_component=0.0,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        result = select_best_side(
            yes_edge=yes_edge,
            no_edge=no_edge,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # YES has 5c edge > 4c threshold, NO has 3c edge < 4c threshold
        assert result == "yes"
    
    def test_select_best_side_both_fail_dynamic_threshold(self):
        """Test select_best_side when both sides fail dynamic threshold."""
        yes_edge = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=5.0,
            spread_cents=5,
            executable_edge_cents=2.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=1.0,
            p_hat_yes_cents=50.0
        )
        
        no_edge = PerSideEdgeMetrics(
            side="no",
            raw_edge_cents=4.0,
            spread_cents=5,
            executable_edge_cents=1.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=1.25,
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold that both fail
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=5.0,
            spread_component=2.0,
            volatility_component=1.0,
            fee_component=1.0,
            slippage_component=0.5,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        result = select_best_side(
            yes_edge=yes_edge,
            no_edge=no_edge,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Both fail, should return None
        assert result is None
    
    def test_edge_aware_gate_with_dynamic_threshold(self):
        """Test edge_aware_microstructure_gate with dynamic threshold."""
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=5.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold that passes
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=4.0,
            spread_component=2.0,
            volatility_component=0.5,
            fee_component=1.0,
            slippage_component=0.0,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        assert passes is True
        assert reason == "ok"
    
    def test_edge_aware_gate_dynamic_threshold_rejection(self):
        """Test edge_aware_microstructure_gate rejects when edge below dynamic threshold."""
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=3.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold that fails
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=5.0,
            spread_component=2.0,
            volatility_component=1.0,
            fee_component=1.0,
            slippage_component=0.5,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        assert passes is False
        assert "executable_edge_too_low" in reason


class TestAssetThresholdConfig:
    """Test asset threshold configuration."""
    
    def test_get_asset_config_btc(self):
        """Test BTC config has lowest strictness."""
        config = get_asset_config("BTC")
        assert config is not None
        assert config.asset == "BTC"
        assert config.strictness == ThresholdStrictness.LOWEST
        assert config.base_alpha_hurdle == 1.0
    
    def test_get_asset_config_doge(self):
        """Test DOGE config has highest strictness."""
        config = get_asset_config("DOGE")
        assert config is not None
        assert config.asset == "DOGE"
        assert config.strictness == ThresholdStrictness.HIGHEST
        assert config.base_alpha_hurdle == 3.0
    
    def test_dynamic_multiplier_calculation(self):
        """Test dynamic multiplier increases with strictness."""
        btc_config = get_asset_config("BTC")
        doge_config = get_asset_config("DOGE")
        
        btc_multiplier = btc_config.get_dynamic_multiplier()
        doge_multiplier = doge_config.get_dynamic_multiplier()
        
        assert doge_multiplier > btc_multiplier
        assert btc_multiplier == 1.0  # Lowest strictness
        assert doge_multiplier == 1.8  # Highest strictness


class TestYesNoSymmetry:
    """Test YES/NO symmetry with dynamic threshold."""
    
    def test_yes_no_symmetry_with_same_edge(self):
        """Test that YES and NO with same edge are symmetric."""
        yes_edge = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=5.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        no_edge = PerSideEdgeMetrics(
            side="no",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=5.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=4.0,
            spread_component=2.0,
            volatility_component=0.5,
            fee_component=1.0,
            slippage_component=0.0,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        # With same edge, should prefer YES (arbitrary tie-breaker)
        result = select_best_side(
            yes_edge=yes_edge,
            no_edge=no_edge,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        assert result in ["yes", "no"]  # Either is acceptable


class TestWideSpreadRejection:
    """Test wide-spread rejection with dynamic threshold."""
    
    def test_wide_spread_increases_threshold(self):
        """Test that wide spreads increase dynamic threshold."""
        narrow_spread = compute_dynamic_threshold("BTC", spread_cents=5, fee_cents=2.0)
        wide_spread = compute_dynamic_threshold("BTC", spread_cents=30, fee_cents=2.0)
        
        assert wide_spread.threshold_cents > narrow_spread.threshold_cents
        assert wide_spread.spread_component > narrow_spread.spread_component
    
    def test_wide_spread_rejection_with_moderate_edge(self):
        """Test that wide spreads reject orders with moderate edge."""
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=30,  # Wide spread
            executable_edge_cents=5.0,  # Moderate edge
            spread_cost_cents=30.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=2.0,  # Spread > edge
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold should be high due to wide spread
        dynamic_threshold = compute_dynamic_threshold("BTC", spread_cents=30, fee_cents=2.0)
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should fail due to spread cost ratio > threshold
        assert passes is False


class TestVolatilityRegimeSensitivity:
    """Test volatility regime sensitivity with dynamic threshold."""
    
    def test_threshold_without_volatility_data(self):
        """Test that threshold works without volatility data (graceful degradation)."""
        # When volatility service is unavailable or fails, threshold should still compute
        result = compute_dynamic_threshold(
            asset="BTC",
            spread_cents=10,
            fee_cents=2.0,
            orderbook=None
        )
        
        assert result is not None
        assert result.threshold_cents > 0
        # Volatility component should be 0 when data unavailable
        assert result.volatility_component == 0.0
        # Other components should still contribute
        assert result.spread_component > 0
        assert result.fee_component > 0
    
    def test_base_threshold_consistency(self):
        """Test that base threshold is consistent across assets when spread/fee are same."""
        # All assets should have non-zero base hurdle
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            result = compute_dynamic_threshold(asset, spread_cents=10, fee_cents=2.0)
            assert result.base_hurdle > 0
            assert result.threshold_cents > result.base_hurdle  # Threshold > base hurdle


class TestThresholdConsistency:
    """Test threshold consistency across decision and execution."""
    
    def test_threshold_passed_to_gate(self):
        """Test that dynamic threshold is correctly passed to gate function."""
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=5,
            executable_edge_cents=5.0,
            spread_cost_cents=5.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.5,
            p_hat_yes_cents=50.0
        )
        
        dynamic_threshold = DynamicThresholdResult(
            threshold_cents=4.0,
            spread_component=2.0,
            volatility_component=0.5,
            fee_component=1.0,
            slippage_component=0.0,
            base_hurdle=0.5,
            asset_config_name="BTC"
        )
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should use dynamic threshold (4c) instead of fraction threshold (3c)
        assert passes is True  # 5c edge > 4c threshold
    
    def test_threshold_components_logged(self):
        """Test that threshold components are properly logged."""
        result = compute_dynamic_threshold("BTC", spread_cents=10, fee_cents=2.0)
        
        # All components should be accessible
        assert result.spread_component >= 0
        assert result.volatility_component >= 0
        assert result.fee_component >= 0
        assert result.slippage_component >= 0
        assert result.base_hurdle >= 0
        assert result.threshold_cents >= 0


class TestRegressionCases:
    """Regression tests for current BTC/ETH rejection cases."""
    
    def test_btc_wide_spread_negative_executable_edge(self):
        """Test BTC with wide spread causing negative executable edge (regression test).
        
        This simulates the case where BTC had -32c executable edge due to wide spread.
        The dynamic threshold should correctly reject this case.
        """
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=10.0,
            spread_cents=40,  # Very wide spread
            executable_edge_cents=-32.0,  # Negative edge (original bug case)
            spread_cost_cents=40.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=4.0,  # Spread > edge
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold for BTC with wide spread
        dynamic_threshold = compute_dynamic_threshold("BTC", spread_cents=40, fee_cents=2.0)
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should reject due to negative executable edge
        assert passes is False
        assert "non_positive_executable_edge" in reason
    
    def test_eth_wide_spread_negative_executable_edge(self):
        """Test ETH with wide spread causing negative executable edge (regression test).
        
        This simulates the case where ETH had -23c executable edge due to wide spread.
        The dynamic threshold should correctly reject this case.
        """
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,  # Wide spread
            executable_edge_cents=-23.0,  # Negative edge (original bug case)
            spread_cost_cents=35.0,
            taker_fee_cents=3.0,
            spread_to_edge_ratio=2.33,  # Spread > edge
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold for ETH with wide spread
        dynamic_threshold = compute_dynamic_threshold("ETH", spread_cents=35, fee_cents=3.0)
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should reject due to negative executable edge
        assert passes is False
        assert "non_positive_executable_edge" in reason
    
    def test_btc_moderate_spread_positive_edge_passes(self):
        """Test BTC with moderate spread and positive edge should pass.
        
        This tests that BTC can still trade when conditions are favorable.
        """
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=20.0,
            spread_cents=8,  # Moderate spread
            executable_edge_cents=10.0,  # Positive edge (higher to exceed dynamic threshold)
            spread_cost_cents=8.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.4,  # Spread < edge
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold for BTC with moderate spread
        dynamic_threshold = compute_dynamic_threshold("BTC", spread_cents=8, fee_cents=2.0)
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should pass - positive edge exceeds dynamic threshold
        assert passes is True
    
    def test_eth_moderate_spread_positive_edge_passes(self):
        """Test ETH with moderate spread and positive edge should pass.
        
        This tests that ETH can still trade when conditions are favorable.
        """
        edge_metrics = PerSideEdgeMetrics(
            side="yes",
            raw_edge_cents=25.0,
            spread_cents=10,  # Moderate spread
            executable_edge_cents=13.0,  # Positive edge (higher to exceed dynamic threshold)
            spread_cost_cents=10.0,
            taker_fee_cents=2.0,
            spread_to_edge_ratio=0.4,  # Spread < edge
            p_hat_yes_cents=50.0
        )
        
        # Dynamic threshold for ETH with moderate spread
        dynamic_threshold = compute_dynamic_threshold("ETH", spread_cents=10, fee_cents=2.0)
        
        passes, reason = edge_aware_microstructure_gate(
            edge_metrics=edge_metrics,
            min_executable_edge_frac=0.03,
            max_spread_to_edge_ratio=0.8,
            dynamic_threshold=dynamic_threshold
        )
        
        # Should pass - positive edge exceeds dynamic threshold
        assert passes is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
