"""Extended tests for trading/execution/optimal.py - Optimal Execution Coverage."""
import pytest
import time
import math
from unittest.mock import patch, MagicMock
import numpy as np

from trading.execution.optimal import (
    ExecutionStrategy,
    OrderSide,
    OrderStatus,
    MarketState,
    ExecutionSlice,
    ExecutionPlan,
    AlmgrenChriss,
    VWAP,
    TWAP,
    QueuePositionEstimator,
    OptimalExecutionEngine,
    get_optimal_executor,
)


class TestEnums:
    """Test enum definitions."""

    def test_execution_strategy_values(self):
        """Test ExecutionStrategy enum values."""
        assert ExecutionStrategy.ALMGREN_CHRISS.value == "almgren_chriss"
        assert ExecutionStrategy.VWAP.value == "vwap"
        assert ExecutionStrategy.TWAP.value == "twap"
        assert ExecutionStrategy.ICEBERG.value == "iceberg"
        assert ExecutionStrategy.ADAPTIVE.value == "adaptive"

    def test_order_side_values(self):
        """Test OrderSide enum values."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        """Test OrderStatus enum values."""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.FAILED.value == "failed"


class TestMarketState:
    """Test MarketState dataclass."""

    def test_market_state_creation(self):
        """Test creating a market state."""
        state = MarketState(
            symbol="BTC/USD",
            mid_price=50000.0,
            bid_price=49990.0,
            ask_price=50010.0,
            spread=20.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.02,
            intraday_volatility=0.01,
            bid_depth=100000.0,
            ask_depth=100000.0
        )
        assert state.symbol == "BTC/USD"
        assert state.mid_price == 50000.0
        assert state.spread == 20.0

    def test_market_state_to_dict(self):
        """Test market state to_dict."""
        state = MarketState(
            symbol="ETH/USD",
            mid_price=3000.0,
            bid_price=2998.0,
            ask_price=3002.0,
            spread=4.0,
            daily_volume=500000.0,
            hourly_volume=25000.0,
            current_volume_rate=500.0,
            volatility=0.03,
            intraday_volatility=0.015,
            bid_depth=50000.0,
            ask_depth=50000.0
        )
        result = state.to_dict()
        
        assert result["symbol"] == "ETH/USD"
        assert result["mid_price"] == 3000.0
        assert "spread_bps" in result


class TestExecutionSlice:
    """Test ExecutionSlice dataclass."""

    def test_slice_creation(self):
        """Test creating an execution slice."""
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time() + 60
        )
        assert slice_obj.slice_id == 0
        assert slice_obj.target_quantity == 100.0
        assert slice_obj.executed_quantity == 0.0

    def test_slice_is_complete_false(self):
        """Test is_complete when not complete."""
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time(),
            executed_quantity=50.0
        )
        assert slice_obj.is_complete() is False

    def test_slice_is_complete_true(self):
        """Test is_complete when complete."""
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time(),
            executed_quantity=99.5  # 99% threshold
        )
        assert slice_obj.is_complete() is True

    def test_slice_to_dict(self):
        """Test slice to_dict."""
        slice_obj = ExecutionSlice(
            slice_id=1,
            target_quantity=50.0,
            target_time=1234567890.0,
            executed_quantity=50.0,
            executed_price=50000.0,
            slippage=5.0
        )
        result = slice_obj.to_dict()
        
        assert result["slice_id"] == 1
        assert result["target_quantity"] == 50.0
        assert result["executed_quantity"] == 50.0
        assert result["is_complete"] is True


class TestExecutionPlan:
    """Test ExecutionPlan dataclass."""

    def test_plan_creation(self):
        """Test creating an execution plan."""
        plan = ExecutionPlan(
            plan_id="exec_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=time.time(),
            end_time=time.time() + 3600,
            duration_seconds=3600.0
        )
        assert plan.plan_id == "exec_001"
        assert plan.symbol == "BTC/USD"
        assert plan.side == OrderSide.BUY
        assert plan.status == OrderStatus.PENDING

    def test_plan_progress_pct(self):
        """Test progress percentage calculation."""
        plan = ExecutionPlan(
            plan_id="exec_002",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            total_quantity=100.0,
            strategy=ExecutionStrategy.VWAP,
            start_time=time.time(),
            end_time=time.time() + 1800,
            duration_seconds=1800.0,
            executed_quantity=50.0
        )
        assert plan.progress_pct() == 0.5

    def test_plan_progress_pct_zero(self):
        """Test progress when total is zero."""
        plan = ExecutionPlan(
            plan_id="exec_003",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=0.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=time.time(),
            end_time=time.time() + 60,
            duration_seconds=60.0
        )
        assert plan.progress_pct() == 0.0

    def test_plan_to_dict(self):
        """Test plan to_dict."""
        plan = ExecutionPlan(
            plan_id="exec_004",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=500.0,
            strategy=ExecutionStrategy.ALMGREN_CHRISS,
            start_time=1234567890.0,
            end_time=1234571490.0,
            duration_seconds=3600.0,
            executed_quantity=250.0,
            average_price=50000.0,
            status=OrderStatus.PARTIAL
        )
        result = plan.to_dict()
        
        assert result["plan_id"] == "exec_004"
        assert result["side"] == "buy"
        assert result["strategy"] == "almgren_chriss"
        assert result["progress_pct"] == 50.0
        assert result["status"] == "partial"


class TestAlmgrenChriss:
    """Test AlmgrenChriss class."""

    @pytest.fixture
    def model(self):
        return AlmgrenChriss(eta=0.01, gamma=0.001, risk_aversion=1e-6)

    def test_initialization(self, model):
        """Test model initialization."""
        assert model.eta == 0.01
        assert model.gamma == 0.001
        assert model.risk_aversion == 1e-6

    def test_compute_optimal_trajectory(self, model):
        """Test computing optimal trajectory."""
        trajectory = model.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.02,
            n_slices=10
        )
        
        assert len(trajectory) == 10
        assert sum(trajectory) == pytest.approx(1000.0, rel=0.01)
        assert all(q >= 0 for q in trajectory)

    def test_compute_optimal_trajectory_zero_slices(self, model):
        """Test trajectory with zero slices."""
        trajectory = model.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.02,
            n_slices=0
        )
        assert trajectory == []

    def test_compute_optimal_trajectory_single_slice(self, model):
        """Test trajectory with single slice."""
        trajectory = model.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.02,
            n_slices=1
        )
        assert len(trajectory) == 1
        assert trajectory[0] == pytest.approx(1000.0, rel=0.01)

    def test_compute_optimal_trajectory_zero_eta(self):
        """Test trajectory with zero eta."""
        model = AlmgrenChriss(eta=0.0, gamma=0.001, risk_aversion=1e-6)
        trajectory = model.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.02,
            n_slices=5
        )
        assert len(trajectory) == 5
        assert sum(trajectory) == pytest.approx(1000.0, rel=0.01)

    def test_estimate_execution_cost(self, model):
        """Test execution cost estimation."""
        cost = model.estimate_execution_cost(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.02,
            mid_price=50000.0
        )
        
        assert "temporary_impact" in cost
        assert "permanent_impact" in cost
        assert "timing_risk" in cost
        assert "total_expected_cost" in cost
        assert cost["total_expected_cost"] >= 0

    def test_estimate_execution_cost_zero_duration(self, model):
        """Test cost with zero duration."""
        cost = model.estimate_execution_cost(
            total_quantity=1000.0,
            duration_seconds=0.0,
            volatility=0.02,
            mid_price=50000.0
        )
        assert cost["total_expected_cost"] >= 0

    def test_optimal_duration(self, model):
        """Test optimal duration calculation."""
        duration = model.optimal_duration(
            total_quantity=1000.0,
            volatility=0.02,
            daily_volume=100000.0
        )
        
        assert duration > 0
        # Should be at least the minimum based on participation rate
        min_participation_duration = 1000.0 / (100000.0 * 0.10 / 86400)
        assert duration >= min_participation_duration

    def test_optimal_duration_zero_params(self):
        """Test optimal duration with zero parameters."""
        model = AlmgrenChriss(eta=0.0, gamma=0.0, risk_aversion=0.0)
        duration = model.optimal_duration(
            total_quantity=1000.0,
            volatility=0.02,
            daily_volume=100000.0
        )
        assert duration > 0


class TestVWAP:
    """Test VWAP class."""

    @pytest.fixture
    def vwap(self):
        return VWAP()

    def test_initialization(self, vwap):
        """Test VWAP initialization."""
        assert vwap._default_profile is not None
        assert len(vwap._default_profile) == 24
        assert vwap._default_profile.sum() == pytest.approx(1.0)

    def test_set_volume_profile(self, vwap):
        """Test setting custom volume profile."""
        profile = np.ones(24)
        vwap.set_volume_profile("BTC/USD", profile)
        
        assert "BTC/USD" in vwap._custom_profiles
        assert vwap._custom_profiles["BTC/USD"].sum() == pytest.approx(1.0)

    def test_set_volume_profile_invalid_length(self, vwap):
        """Test setting invalid profile length."""
        with pytest.raises(ValueError):
            vwap.set_volume_profile("BTC/USD", np.ones(10))

    def test_compute_schedule(self, vwap):
        """Test computing VWAP schedule."""
        now = time.time()
        schedule = vwap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            symbol="default",
            n_slices=10
        )
        
        assert len(schedule) == 10
        total_qty = sum(q for _, q in schedule)
        assert total_qty == pytest.approx(1000.0, rel=0.01)

    def test_compute_schedule_custom_profile(self, vwap):
        """Test schedule with custom profile."""
        # Set uniform profile
        vwap.set_volume_profile("TEST/USD", np.ones(24))
        
        now = time.time()
        schedule = vwap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            symbol="TEST/USD",
            n_slices=10
        )
        
        assert len(schedule) == 10
        total_qty = sum(q for _, q in schedule)
        assert total_qty == pytest.approx(1000.0, rel=0.01)

    def test_estimate_tracking_error(self, vwap):
        """Test tracking error estimation."""
        actual_execution = [
            (50000.0, 100.0),  # price, quantity
            (50100.0, 100.0),
            (50050.0, 100.0),
        ]
        market_vwap = 50000.0
        
        error = vwap.estimate_tracking_error(actual_execution, market_vwap)
        
        # Execution VWAP = (50000*100 + 50100*100 + 50050*100) / 300 = 50050
        # Error = (50050 - 50000) / 50000 * 10000 = 10 bps
        assert error == pytest.approx(10.0, rel=0.1)

    def test_estimate_tracking_error_empty(self, vwap):
        """Test tracking error with empty execution."""
        error = vwap.estimate_tracking_error([], 50000.0)
        assert error == 0.0

    def test_estimate_tracking_error_zero_quantity(self, vwap):
        """Test tracking error with zero total quantity."""
        actual_execution = [(50000.0, 0.0)]
        error = vwap.estimate_tracking_error(actual_execution, 50000.0)
        assert error == 0.0


class TestTWAP:
    """Test TWAP class."""

    @pytest.fixture
    def twap(self):
        return TWAP()

    def test_initialization(self, twap):
        """Test TWAP initialization."""
        assert twap is not None

    def test_compute_schedule(self, twap):
        """Test computing TWAP schedule."""
        now = time.time()
        schedule = twap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10
        )
        
        assert len(schedule) == 10
        # All quantities should be equal
        quantities = [q for _, q in schedule]
        assert all(q == pytest.approx(100.0) for q in quantities)

    def test_compute_schedule_zero_slices(self, twap):
        """Test schedule with zero slices."""
        schedule = twap.compute_schedule(
            total_quantity=1000.0,
            start_time=time.time(),
            end_time=time.time() + 3600,
            n_slices=0
        )
        assert schedule == []

    def test_with_randomization(self, twap):
        """Test TWAP with randomization."""
        now = time.time()
        schedule = twap.with_randomization(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10,
            time_jitter_pct=0.1,
            size_jitter_pct=0.1
        )
        
        assert len(schedule) == 10
        total_qty = sum(q for _, q in schedule)
        assert total_qty == pytest.approx(1000.0, rel=0.01)
        
        # Times should be within bounds
        for t, _ in schedule:
            assert now <= t <= now + 3600

    def test_with_randomization_single_slice(self, twap):
        """Test randomization with single slice."""
        now = time.time()
        schedule = twap.with_randomization(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=1
        )
        
        assert len(schedule) == 1
        assert schedule[0][1] == 1000.0


class TestQueuePositionEstimator:
    """Test QueuePositionEstimator class."""

    @pytest.fixture
    def estimator(self):
        return QueuePositionEstimator()

    def test_initialization(self, estimator):
        """Test estimator initialization."""
        assert estimator._queue_history == {}

    def test_estimate_queue_position_buy(self, estimator):
        """Test queue position for buy order."""
        order_book = [
            (50000.0, 100.0),  # Higher price, will be ahead
            (49999.0, 50.0),   # Lower price, not ahead
        ]
        
        position, fill_time = estimator.estimate_queue_position(
            price=50000.0,
            size=10.0,
            order_book_depth=order_book,
            side=OrderSide.BUY
        )
        
        assert position == 100  # Only the order at 50000 is ahead
        assert fill_time > 0

    def test_estimate_queue_position_sell(self, estimator):
        """Test queue position for sell order."""
        order_book = [
            (50000.0, 50.0),   # Higher price, not ahead
            (49999.0, 100.0),  # Lower price, will be ahead
        ]
        
        position, fill_time = estimator.estimate_queue_position(
            price=49999.0,
            size=10.0,
            order_book_depth=order_book,
            side=OrderSide.SELL
        )
        
        assert position == 100

    def test_estimate_queue_position_zero_size(self, estimator):
        """Test queue position with zero size."""
        position, fill_time = estimator.estimate_queue_position(
            price=50000.0,
            size=0.0,
            order_book_depth=[(50000.0, 100.0)],
            side=OrderSide.BUY
        )
        
        assert fill_time == float('inf')

    def test_update_fill_rate(self, estimator):
        """Test updating fill rate."""
        estimator.update_fill_rate("BTC/USD", 0.05)
        
        assert "BTC/USD" in estimator._queue_history
        assert len(estimator._queue_history["BTC/USD"]) == 1


class TestOptimalExecutionEngine:
    """Test OptimalExecutionEngine class."""

    @pytest.fixture
    def engine(self):
        return OptimalExecutionEngine()

    @pytest.fixture
    def market_state(self):
        return MarketState(
            symbol="BTC/USD",
            mid_price=50000.0,
            bid_price=49990.0,
            ask_price=50010.0,
            spread=20.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.02,
            intraday_volatility=0.01,
            bid_depth=100000.0,
            ask_depth=100000.0
        )

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine.almgren_chriss is not None
        assert engine.vwap is not None
        assert engine.twap is not None
        assert engine.queue_estimator is not None

    def test_create_plan_twap(self, engine, market_state):
        """Test creating TWAP plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=3600.0,
            n_slices=10
        )
        
        assert plan.symbol == "BTC/USD"
        assert plan.side == OrderSide.BUY
        assert plan.strategy == ExecutionStrategy.TWAP
        assert len(plan.slices) == 10
        assert plan.status == OrderStatus.PENDING

    def test_create_plan_vwap(self, engine, market_state):
        """Test creating VWAP plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.SELL,
            total_quantity=500.0,
            strategy=ExecutionStrategy.VWAP,
            market_state=market_state,
            duration_seconds=1800.0,
            n_slices=5
        )
        
        assert plan.strategy == ExecutionStrategy.VWAP
        assert len(plan.slices) == 5

    def test_create_plan_almgren_chriss(self, engine, market_state):
        """Test creating Almgren-Chriss plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=2000.0,
            strategy=ExecutionStrategy.ALMGREN_CHRISS,
            market_state=market_state,
            duration_seconds=7200.0,
            n_slices=20
        )
        
        assert plan.strategy == ExecutionStrategy.ALMGREN_CHRISS
        assert len(plan.slices) == 20

    def test_create_plan_auto_duration(self, engine, market_state):
        """Test creating plan with auto-computed duration."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=10
        )
        
        assert plan.duration_seconds > 0

    def test_record_execution(self, engine, market_state):
        """Test recording execution."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=60.0,
            n_slices=2
        )
        
        result = engine.record_execution(
            plan_id=plan.plan_id,
            slice_id=0,
            executed_quantity=50.0,
            executed_price=50005.0
        )
        
        assert result is True
        assert plan.executed_quantity == 50.0
        assert plan.status == OrderStatus.PARTIAL

    def test_record_execution_complete(self, engine, market_state):
        """Test recording execution that completes plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=60.0,
            n_slices=2
        )
        
        engine.record_execution(plan.plan_id, 0, 50.0, 50000.0)
        engine.record_execution(plan.plan_id, 1, 50.0, 50010.0)
        
        assert plan.status == OrderStatus.FILLED

    def test_record_execution_invalid_plan(self, engine):
        """Test recording execution for invalid plan."""
        result = engine.record_execution(
            plan_id="nonexistent",
            slice_id=0,
            executed_quantity=50.0,
            executed_price=50000.0
        )
        assert result is False

    def test_record_execution_invalid_slice(self, engine, market_state):
        """Test recording execution for invalid slice."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=60.0,
            n_slices=2
        )
        
        result = engine.record_execution(
            plan_id=plan.plan_id,
            slice_id=99,  # Invalid slice
            executed_quantity=50.0,
            executed_price=50000.0
        )
        assert result is False

    def test_get_next_slice(self, engine, market_state):
        """Test getting next slice to execute."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=0.1,  # Very short duration
            n_slices=2
        )
        
        time.sleep(0.15)  # Wait for slices to become executable
        
        next_slice = engine.get_next_slice(plan.plan_id)
        assert next_slice is not None

    def test_get_next_slice_invalid_plan(self, engine):
        """Test getting next slice for invalid plan."""
        result = engine.get_next_slice("nonexistent")
        assert result is None

    def test_cancel_plan(self, engine, market_state):
        """Test cancelling a plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5
        )
        
        result = engine.cancel_plan(plan.plan_id, "Test cancellation")
        
        assert result is True
        assert plan.status == OrderStatus.CANCELLED

    def test_cancel_plan_invalid(self, engine):
        """Test cancelling invalid plan."""
        result = engine.cancel_plan("nonexistent", "reason")
        assert result is False

    def test_get_plan(self, engine, market_state):
        """Test getting a plan."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5
        )
        
        retrieved = engine.get_plan(plan.plan_id)
        assert retrieved is plan

    def test_get_plan_invalid(self, engine):
        """Test getting invalid plan."""
        result = engine.get_plan("nonexistent")
        assert result is None

    def test_get_active_plans(self, engine, market_state):
        """Test getting active plans."""
        plan1 = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2
        )
        plan2 = engine.create_plan(
            symbol="ETH/USD",
            side=OrderSide.SELL,
            total_quantity=50.0,
            strategy=ExecutionStrategy.VWAP,
            market_state=market_state,
            n_slices=2
        )
        
        active = engine.get_active_plans()
        assert len(active) == 2

    def test_estimate_market_impact(self, engine, market_state):
        """Test market impact estimation."""
        impact = engine.estimate_market_impact(1000.0, market_state)
        
        assert "participation_rate" in impact
        assert "temporary_impact_bps" in impact
        assert "permanent_impact_bps" in impact
        assert "spread_cost_bps" in impact
        assert "total_impact_bps" in impact

    def test_get_status(self, engine, market_state):
        """Test getting engine status."""
        engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2
        )
        
        status = engine.get_status()
        
        assert "total_plans" in status
        assert "active_plans" in status
        assert status["total_plans"] >= 1
        assert status["active_plans"] >= 1

    def test_get_execution_summary(self, engine, market_state):
        """Test getting execution summary."""
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2
        )
        
        summary = engine.get_execution_summary(plan.plan_id)
        
        assert summary is not None
        assert "plan" in summary
        assert "slices" in summary
        assert "cost_analysis" in summary

    def test_get_execution_summary_invalid(self, engine):
        """Test getting summary for invalid plan."""
        result = engine.get_execution_summary("nonexistent")
        assert result is None


class TestSingleton:
    """Test singleton pattern."""

    def test_get_optimal_executor_singleton(self):
        """Test get_optimal_executor returns singleton."""
        import trading.execution.optimal as optimal_module
        optimal_module._optimal_executor = None
        
        engine1 = get_optimal_executor()
        engine2 = get_optimal_executor()
        
        assert engine1 is engine2
        
        # Cleanup
        optimal_module._optimal_executor = None
