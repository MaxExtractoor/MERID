"""Tests for order scaling engine (TWAP, VWAP, iceberg, adaptive)."""

import pytest
from merid.event_venues.kalshi.order_scaler import (
    OrderScaler,
    ScalingConfig,
    ScalingStrategy,
    ChildOrder,
    ScalingPlan,
    get_order_scaler,
)


class TestScalingConfig:
    """Test scaling configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = ScalingConfig()
        assert config.strategy == ScalingStrategy.NONE
        assert config.min_child_orders == 1
        assert config.max_child_orders == 5
        assert config.time_window_seconds == 300.0
        assert config.participation_rate == 0.10
        assert config.visible_pct == 0.10
        assert config.edge_threshold == 0.02
        assert config.size_threshold_contracts == 3
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = ScalingConfig(
            strategy=ScalingStrategy.TWAP,
            min_child_orders=2,
            max_child_orders=10,
            time_window_seconds=600.0,
        )
        assert config.strategy == ScalingStrategy.TWAP
        assert config.min_child_orders == 2
        assert config.max_child_orders == 10
        assert config.time_window_seconds == 600.0


class TestOrderScaler:
    """Test order scaling logic."""
    
    def test_scaler_initialization(self):
        """Test scaler initialization."""
        config = ScalingConfig(strategy=ScalingStrategy.TWAP)
        scaler = OrderScaler(config)
        assert scaler.config.strategy == ScalingStrategy.TWAP
    
    def test_should_scale_small_order(self):
        """Test that small orders are not scaled."""
        config = ScalingConfig()
        scaler = OrderScaler(config)
        
        # Small order (< threshold)
        assert not scaler.should_scale(
            contracts=2,
            edge_pct=0.05,
            market_depth=100,
        )
    
    def test_should_scale_low_edge(self):
        """Test that low-edge orders are not scaled."""
        config = ScalingConfig()
        scaler = OrderScaler(config)
        
        # Low edge (< threshold)
        assert not scaler.should_scale(
            contracts=5,
            edge_pct=0.01,
            market_depth=100,
        )
    
    def test_should_scale_thin_market(self):
        """Test that thin market orders are not scaled."""
        config = ScalingConfig()
        scaler = OrderScaler(config)
        
        # Thin market
        assert not scaler.should_scale(
            contracts=5,
            edge_pct=0.05,
            market_depth=10,
        )
    
    def test_should_scale_valid(self):
        """Test that valid orders are scaled."""
        config = ScalingConfig()
        scaler = OrderScaler(config)
        
        # Valid order
        assert scaler.should_scale(
            contracts=5,
            edge_pct=0.05,
            market_depth=100,
        )
    
    def test_create_twap_plan(self):
        """Test TWAP plan creation."""
        config = ScalingConfig(strategy=ScalingStrategy.TWAP)
        scaler = OrderScaler(config)
        
        plan = scaler._create_twap_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=10,
            parent_intent_id="test_intent",
        )
        
        assert plan.strategy == ScalingStrategy.TWAP
        assert plan.total_contracts == 10
        assert len(plan.child_orders) >= 2
        assert len(plan.child_orders) <= 5
        
        # Verify child orders
        total_child_contracts = sum(child.count for child in plan.child_orders)
        assert total_child_contracts == 10
        
        # Verify delays are non-negative
        for child in plan.child_orders:
            assert child.delay_seconds >= 0
    
    def test_create_iceberg_plan(self):
        """Test iceberg plan creation."""
        config = ScalingConfig(strategy=ScalingStrategy.ICEBERG)
        scaler = OrderScaler(config)
        
        plan = scaler._create_iceberg_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=20,
            parent_intent_id="test_intent",
        )
        
        assert plan.strategy == ScalingStrategy.ICEBERG
        assert plan.total_contracts == 20
        
        # Verify visible count is 10% of total
        visible_count = plan.child_orders[0].visible_count
        assert visible_count == 2  # 10% of 20
        
        # Verify all child orders have visible_count set
        for child in plan.child_orders:
            assert child.visible_count is not None
    
    def test_create_adaptive_plan_high_edge(self):
        """Test adaptive plan with high edge (aggressive)."""
        config = ScalingConfig(strategy=ScalingStrategy.ADAPTIVE)
        scaler = OrderScaler(config)
        
        plan = scaler._create_adaptive_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=10,
            edge_pct=0.06,  # 6% edge - aggressive
            parent_intent_id="test_intent",
        )
        
        assert plan.strategy == ScalingStrategy.ADAPTIVE
        assert len(plan.child_orders) == 2  # High edge = fewer orders
        
        # First order should be larger (front-loaded)
        first_order = plan.child_orders[0]
        assert first_order.count > plan.child_orders[1].count
    
    def test_create_adaptive_plan_low_edge(self):
        """Test adaptive plan with low edge (conservative)."""
        config = ScalingConfig(strategy=ScalingStrategy.ADAPTIVE)
        scaler = OrderScaler(config)
        
        plan = scaler._create_adaptive_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=10,
            edge_pct=0.015,  # 1.5% edge - conservative
            parent_intent_id="test_intent",
        )
        
        assert plan.strategy == ScalingStrategy.ADAPTIVE
        assert len(plan.child_orders) == 5  # Low edge = more orders
    
    def test_create_scaling_plan_none_when_not_applicable(self):
        """Test that scaling plan returns None when not applicable."""
        config = ScalingConfig()
        scaler = OrderScaler(config)
        
        plan = scaler.create_scaling_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=2,  # Below threshold
            edge_pct=0.05,
            market_depth=100,
            parent_intent_id="test_intent",
        )
        
        assert plan is None
    
    def test_create_scaling_plan_valid(self):
        """Test that scaling plan is created for valid orders."""
        config = ScalingConfig(strategy=ScalingStrategy.TWAP)
        scaler = OrderScaler(config)
        
        plan = scaler.create_scaling_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=5,
            edge_pct=0.05,
            market_depth=100,
            parent_intent_id="test_intent",
        )
        
        assert plan is not None
        assert plan.parent_intent_id == "test_intent"
        assert plan.total_contracts == 5


class TestScalingSingleton:
    """Test order scaler singleton."""
    
    def test_get_order_scaler_singleton(self):
        """Test that get_order_scaler returns singleton."""
        # Reset singleton for clean test
        import merid.event_venues.kalshi.order_scaler as scaler_module
        scaler_module._scaler = None
        
        scaler1 = get_order_scaler()
        scaler2 = get_order_scaler()
        assert scaler1 is scaler2
    
    def test_get_order_scaler_custom_config(self):
        """Test that custom config is used on first call."""
        # Reset singleton for clean test
        import merid.event_venues.kalshi.order_scaler as scaler_module
        scaler_module._scaler = None
        
        config = ScalingConfig(strategy=ScalingStrategy.ICEBERG)
        scaler = get_order_scaler(config)
        assert scaler.config.strategy == ScalingStrategy.ICEBERG


class TestChildOrder:
    """Test child order dataclass."""
    
    def test_child_order_fields(self):
        """Test child order field values."""
        child = ChildOrder(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            count=5,
            delay_seconds=10.0,
        )
        
        assert child.ticker == "KXBTC15M-26JUL040215-15"
        assert child.side == "yes"
        assert child.action == "buy"
        assert child.price_cents == 60
        assert child.count == 5
        assert child.delay_seconds == 10.0
        assert child.order_type == "limit"
        assert child.time_in_force == "gtc"


class TestScalingPlan:
    """Test scaling plan dataclass."""
    
    def test_scaling_plan_fields(self):
        """Test scaling plan field values."""
        plan = ScalingPlan(
            parent_intent_id="test_parent",
            strategy=ScalingStrategy.TWAP,
            total_contracts=10,
            child_orders=[],
            expected_duration_seconds=300.0,
            rationale="Test plan",
        )
        
        assert plan.parent_intent_id == "test_parent"
        assert plan.strategy == ScalingStrategy.TWAP
        assert plan.total_contracts == 10
        assert plan.expected_duration_seconds == 300.0
        assert plan.rationale == "Test plan"


class TestScalingIntegration:
    """Integration tests for scaling with order router."""
    
    def test_order_intent_scaling_fields(self):
        """Test that OrderIntent has scaling fields."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            count=10,
            scaling_enabled=True,
            scaling_strategy="adaptive",
        )
        
        assert intent.scaling_enabled is True
        assert intent.scaling_strategy == "adaptive"
    
    @pytest.mark.asyncio
    async def test_scaled_order_execution_integration(self):
        """Test that scaled orders can be executed through router."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.prediction.trading_mode import TradingMode
        
        # Create intent with scaling enabled
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL040215-15",
            side="BUY_YES",
            action="buy",
            price_cents=60,
            count=5,
            scaling_enabled=True,
            scaling_strategy="twap",
            mode=TradingMode.PAPER,
            edge_pct=0.05,
            yes_depth=100,
            no_depth=100,
        )
        
        # This should not fail (scaling may or may not be applied)
        # The important thing is that the router handles the scaling fields
        result = await route_order_async(intent)
        
        # Result should be valid (may be rejected for other reasons)
        assert result is not None
        assert result.status in ("filled_paper", "rejected", "partial_fill")
    
    def test_profile_config_loading(self):
        """Test that profile config can be loaded for scaling."""
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
            
            if is_profile_active():
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter, 'profile'):
                    profile = profile_adapter.profile
                    if hasattr(profile, 'order_scaling'):
                        scaling_config = profile.order_scaling
                        # Verify config has expected fields
                        assert hasattr(scaling_config, 'enabled')
                        assert hasattr(scaling_config, 'strategy')
                        assert hasattr(scaling_config, 'min_child_orders')
                        assert hasattr(scaling_config, 'max_child_orders')
                        # Verify defaults are safe
                        assert scaling_config.enabled is False  # Disabled by default for production safety
                        assert scaling_config.max_child_orders <= 10  # Production safety cap
        except ImportError:
            # Profile module not available, skip test
            pytest.skip("Profile module not available")
    
    def test_production_safety_checks(self):
        """Test that production safety checks are in place."""
        from merid.event_venues.kalshi.order_scaler import OrderScaler, ScalingConfig, ScalingStrategy
        
        # Test max_child_orders cap (applied in should_scale())
        config = ScalingConfig(
            strategy=ScalingStrategy.TWAP,
            max_child_orders=20,  # Exceeds safety cap
        )
        scaler = OrderScaler(config)
        
        # Cap is applied when should_scale is called
        scaler.should_scale(contracts=10, edge_pct=0.05, market_depth=100)
        
        # Should cap to 10 after should_scale is called
        assert scaler.config.max_child_orders == 10
    
    def test_total_contract_verification(self):
        """Test that total contracts are verified in scaling plans."""
        from merid.event_venues.kalshi.order_scaler import OrderScaler, ScalingConfig, ScalingStrategy
        
        config = ScalingConfig(strategy=ScalingStrategy.TWAP)
        scaler = OrderScaler(config)
        
        plan = scaler._create_twap_plan(
            ticker="KXBTC15M-26JUL040215-15",
            side="yes",
            action="buy",
            price_cents=60,
            total_contracts=10,
            parent_intent_id="test",
        )
        
        # Verify total matches
        actual_total = sum(child.count for child in plan.child_orders)
        assert actual_total == 10
