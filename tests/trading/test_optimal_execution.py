"""Tests for OptimalExecutionEngine - Batch 1 Coverage."""
import pytest
import time
from trading.execution.optimal import (
    OptimalExecutionEngine, ExecutionStrategy, OrderSide,
    MarketState, ExecutionSlice
)


@pytest.fixture
def market_state():
    """Create a sample market state."""
    return MarketState(
        symbol="BTC-USD",
        mid_price=45000.0,
        bid_price=44999.0,
        ask_price=45001.0,
        spread=2.0,
        daily_volume=1000000000.0,
        hourly_volume=50000000.0,
        current_volume_rate=1000000.0,
        volatility=0.5,
        intraday_volatility=0.02,
        bid_depth=100.0,
        ask_depth=100.0,
    )


@pytest.fixture
def optimal_engine():
    """Create an OptimalExecutionEngine instance."""
    return OptimalExecutionEngine()


class TestOptimalExecutionEngine:
    """Tests for optimal execution functionality."""

    def test_create_plan_almgren_chriss(self, optimal_engine, market_state):
        """Test creating execution plan with Almgren-Chriss strategy."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.ALMGREN_CHRISS,
            market_state=market_state,
            n_slices=5,
        )

        assert plan is not None
        assert plan.symbol == "BTC-USD"
        assert plan.side == OrderSide.BUY
        assert plan.total_quantity == 1.0
        assert plan.strategy == ExecutionStrategy.ALMGREN_CHRISS
        assert len(plan.slices) == 5
        assert plan.plan_id.startswith("exec_")

    def test_create_plan_twap(self, optimal_engine, market_state):
        """Test creating execution plan with TWAP strategy."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.SELL,
            total_quantity=2.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=3600,
            n_slices=10,
        )

        assert plan is not None
        assert plan.strategy == ExecutionStrategy.TWAP
        assert len(plan.slices) == 10
        assert plan.duration_seconds == 3600

    def test_create_plan_vwap(self, optimal_engine, market_state):
        """Test creating execution plan with VWAP strategy."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=0.5,
            strategy=ExecutionStrategy.VWAP,
            market_state=market_state,
            n_slices=4,
        )

        assert plan is not None
        assert plan.strategy == ExecutionStrategy.VWAP
        assert len(plan.slices) == 4

    def test_record_execution_and_update_plan(self, optimal_engine, market_state):
        """Test recording execution against a plan."""
        # Create a plan first
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )

        # Record execution for first slice
        result = optimal_engine.record_execution(
            plan_id=plan.plan_id,
            slice_id=0,
            executed_quantity=0.2,
            executed_price=45000.0,
        )

        assert result is True
        assert plan.slices[0].executed_quantity == 0.2
        assert plan.executed_quantity == 0.2
        assert plan.status.value == "partial"  # PARTIAL

    def test_record_execution_plan_not_found(self, optimal_engine):
        """Test recording execution for non-existent plan."""
        result = optimal_engine.record_execution(
            plan_id="non-existent-plan",
            slice_id=0,
            executed_quantity=0.1,
            executed_price=45000.0,
        )

        assert result is False

    def test_cancel_plan(self, optimal_engine, market_state):
        """Test canceling an active execution plan."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )

        result = optimal_engine.cancel_plan(plan.plan_id, "Test cancellation")

        assert result is True
        assert plan.status.value == "cancelled"

    def test_cancel_plan_not_found(self, optimal_engine):
        """Test canceling non-existent plan."""
        result = optimal_engine.cancel_plan("non-existent", "Test")

        assert result is False

    def test_get_plan(self, optimal_engine, market_state):
        """Test retrieving a plan by ID."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )

        retrieved = optimal_engine.get_plan(plan.plan_id)

        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id

    def test_get_active_plans(self, optimal_engine, market_state):
        """Test getting all active plans."""
        # Create two plans
        plan1 = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        plan2 = optimal_engine.create_plan(
            symbol="ETH-USD",
            side=OrderSide.SELL,
            total_quantity=2.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )

        # Cancel one
        optimal_engine.cancel_plan(plan2.plan_id, "Test")

        active = optimal_engine.get_active_plans()

        assert len(active) == 1
        assert active[0].plan_id == plan1.plan_id

    def test_estimate_market_impact(self, optimal_engine, market_state):
        """Test market impact estimation."""
        impact = optimal_engine.estimate_market_impact(
            quantity=10.0,
            market_state=market_state,
        )

        assert "participation_rate" in impact
        assert "temporary_impact_bps" in impact
        assert "permanent_impact_bps" in impact
        assert "spread_cost_bps" in impact
        assert "total_impact_bps" in impact

    def test_plan_completion(self, optimal_engine, market_state):
        """Test plan marked as filled when all slices complete."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2,
        )

        # Execute both slices
        optimal_engine.record_execution(plan.plan_id, 0, 0.5, 45000.0)
        optimal_engine.record_execution(plan.plan_id, 1, 0.5, 45001.0)

        assert plan.executed_quantity >= plan.total_quantity * 0.99
        assert plan.status.value == "filled"

    def test_average_price_calculation(self, optimal_engine, market_state):
        """Test average price calculation across slices."""
        plan = optimal_engine.create_plan(
            symbol="BTC-USD",
            side=OrderSide.BUY,
            total_quantity=1.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2,
        )

        # Execute at different prices
        optimal_engine.record_execution(plan.plan_id, 0, 0.5, 44000.0)
        optimal_engine.record_execution(plan.plan_id, 1, 0.5, 46000.0)

        # Average should be around 45000
        assert plan.average_price is not None
        assert 44000.0 < plan.average_price < 46000.0
