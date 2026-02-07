"""Tests for trading execution optimal module - Batch 31 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time
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
    """Tests for execution enums."""

    def test_execution_strategy_values(self):
        assert ExecutionStrategy.ALMGREN_CHRISS.value == "almgren_chriss"
        assert ExecutionStrategy.VWAP.value == "vwap"
        assert ExecutionStrategy.TWAP.value == "twap"
        assert ExecutionStrategy.ICEBERG.value == "iceberg"
        assert ExecutionStrategy.ADAPTIVE.value == "adaptive"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.FAILED.value == "failed"


class TestMarketState:
    """Tests for MarketState dataclass."""

    @pytest.fixture
    def market_state(self):
        return MarketState(
            symbol="BTC/USD",
            mid_price=50000.0,
            bid_price=49999.0,
            ask_price=50001.0,
            spread=2.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.5,
            intraday_volatility=0.02,
            bid_depth=100.0,
            ask_depth=100.0,
        )

    def test_market_state_creation(self, market_state):
        assert market_state.symbol == "BTC/USD"
        assert market_state.mid_price == 50000.0
        assert market_state.spread == 2.0
        assert market_state.volatility == 0.5

    def test_market_state_to_dict(self, market_state):
        d = market_state.to_dict()
        assert d["symbol"] == "BTC/USD"
        assert d["mid_price"] == 50000.0
        assert d["spread"] == 2.0
        assert "spread_bps" in d
        assert "daily_volume" in d
        assert "volatility" in d


class TestExecutionSlice:
    """Tests for ExecutionSlice dataclass."""

    @pytest.fixture
    def execution_slice(self):
        return ExecutionSlice(
            slice_id=0,
            target_quantity=1.0,
            target_time=time.time() + 60,
            expected_price=50000.0,
        )

    def test_slice_creation(self, execution_slice):
        assert execution_slice.slice_id == 0
        assert execution_slice.target_quantity == 1.0
        assert execution_slice.executed_quantity == 0.0
        assert execution_slice.expected_price == 50000.0

    def test_slice_is_complete_not_executed(self, execution_slice):
        assert execution_slice.is_complete() is False

    def test_slice_is_complete_executed(self, execution_slice):
        execution_slice.executed_quantity = 1.0
        assert execution_slice.is_complete() is True

    def test_slice_is_complete_partial(self, execution_slice):
        execution_slice.executed_quantity = 0.995
        assert execution_slice.is_complete() is True

    def test_slice_to_dict(self, execution_slice):
        d = execution_slice.to_dict()
        assert d["slice_id"] == 0
        assert d["target_quantity"] == 1.0
        assert d["is_complete"] is False


class TestExecutionPlan:
    """Tests for ExecutionPlan dataclass."""

    @pytest.fixture
    def execution_plan(self):
        now = time.time()
        return ExecutionPlan(
            plan_id="plan_123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=now,
            end_time=now + 3600,
            duration_seconds=3600,
        )

    def test_plan_creation(self, execution_plan):
        assert execution_plan.plan_id == "plan_123"
        assert execution_plan.symbol == "BTC/USD"
        assert execution_plan.total_quantity == 10.0
        assert execution_plan.status == OrderStatus.PENDING

    def test_plan_progress_pct_zero(self, execution_plan):
        assert execution_plan.progress_pct() == 0.0

    def test_plan_progress_pct_half(self, execution_plan):
        execution_plan.executed_quantity = 5.0
        assert execution_plan.progress_pct() == 0.5

    def test_plan_progress_pct_total_zero(self):
        plan = ExecutionPlan(
            plan_id="plan_empty",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=0.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=time.time(),
            end_time=time.time() + 3600,
            duration_seconds=3600,
        )
        assert plan.progress_pct() == 0.0

    def test_plan_to_dict(self, execution_plan):
        d = execution_plan.to_dict()
        assert d["plan_id"] == "plan_123"
        assert d["symbol"] == "BTC/USD"
        assert d["side"] == "buy"
        assert d["total_quantity"] == 10.0
        assert "progress_pct" in d


class TestAlmgrenChriss:
    """Tests for AlmgrenChriss model."""

    @pytest.fixture
    def model(self):
        return AlmgrenChriss(eta=0.01, gamma=0.001, risk_aversion=1e-6)

    def test_initialization(self, model):
        assert model.eta == 0.01
        assert model.gamma == 0.001
        assert model.risk_aversion == 1e-6

    def test_compute_optimal_trajectory_basic(self, model):
        trajectory = model.compute_optimal_trajectory(
            total_quantity=100.0,
            duration_seconds=3600,
            volatility=0.5,
            n_slices=10,
        )
        assert len(trajectory) == 10
        assert sum(trajectory) > 99.0  # Should be close to 100
        assert sum(trajectory) < 101.0

    def test_compute_optimal_trajectory_zero_slices(self, model):
        trajectory = model.compute_optimal_trajectory(
            total_quantity=100.0,
            duration_seconds=3600,
            volatility=0.5,
            n_slices=0,
        )
        assert trajectory == []

    def test_compute_optimal_trajectory_negative_slices(self, model):
        trajectory = model.compute_optimal_trajectory(
            total_quantity=100.0,
            duration_seconds=3600,
            volatility=0.5,
            n_slices=-1,
        )
        assert trajectory == []

    def test_estimate_execution_cost(self, model):
        cost = model.estimate_execution_cost(
            total_quantity=100.0,
            duration_seconds=3600,
            volatility=0.5,
            mid_price=50000.0,
        )
        assert "temporary_impact" in cost
        assert "permanent_impact" in cost
        assert "timing_risk" in cost
        assert "total_expected_cost" in cost
        assert "total_with_risk" in cost
        assert cost["total_expected_cost"] > 0

    def test_optimal_duration(self, model):
        duration = model.optimal_duration(
            total_quantity=1000.0,
            volatility=0.5,
            daily_volume=100000.0,
        )
        assert duration > 0


class TestVWAP:
    """Tests for VWAP execution."""

    @pytest.fixture
    def vwap(self):
        return VWAP()

    def test_initialization(self, vwap):
        assert vwap._default_profile is not None
        assert len(vwap._default_profile) == 24
        assert abs(vwap._default_profile.sum() - 1.0) < 0.01  # Normalized

    def test_set_volume_profile_valid(self, vwap):
        profile = np.ones(24)
        vwap.set_volume_profile("BTC", profile)
        assert "BTC" in vwap._custom_profiles

    def test_set_volume_profile_invalid_length(self, vwap):
        profile = np.ones(25)
        with pytest.raises(ValueError):
            vwap.set_volume_profile("BTC", profile)

    def test_compute_schedule_basic(self, vwap):
        now = time.time()
        schedule = vwap.compute_schedule(
            total_quantity=100.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10,
        )
        assert len(schedule) == 10
        # Total should be close to 100
        total = sum(q for _, q in schedule)
        assert total > 99.0 and total < 101.0

    def test_estimate_tracking_error(self, vwap):
        actual = [(50000.0, 1.0), (50100.0, 1.0)]
        error = vwap.estimate_tracking_error(actual, 50050.0)
        assert isinstance(error, float)

    def test_estimate_tracking_error_empty(self, vwap):
        error = vwap.estimate_tracking_error([], 50000.0)
        assert error == 0.0


class TestTWAP:
    """Tests for TWAP execution."""

    @pytest.fixture
    def twap(self):
        return TWAP()

    def test_compute_schedule_basic(self, twap):
        now = time.time()
        schedule = twap.compute_schedule(
            total_quantity=100.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10,
        )
        assert len(schedule) == 10
        assert all(q == 10.0 for _, q in schedule)

    def test_compute_schedule_zero_slices(self, twap):
        now = time.time()
        schedule = twap.compute_schedule(
            total_quantity=100.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=0,
        )
        assert schedule == []

    def test_with_randomization(self, twap):
        now = time.time()
        schedule = twap.with_randomization(
            total_quantity=100.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10,
        )
        assert len(schedule) == 10
        # Total should still be 100
        total = sum(q for _, q in schedule)
        assert total > 99.0 and total < 101.0


class TestQueuePositionEstimator:
    """Tests for QueuePositionEstimator."""

    @pytest.fixture
    def estimator(self):
        return QueuePositionEstimator()

    def test_estimate_queue_position_buy(self, estimator):
        depth = [(49999.0, 10.0), (49998.0, 20.0), (49997.0, 30.0)]
        position, fill_time = estimator.estimate_queue_position(
            price=49998.0,
            size=1.0,
            order_book_depth=depth,
            side=OrderSide.BUY,
        )
        assert position > 0
        assert fill_time > 0

    def test_estimate_queue_position_sell(self, estimator):
        depth = [(50001.0, 10.0), (50002.0, 20.0), (50003.0, 30.0)]
        position, fill_time = estimator.estimate_queue_position(
            price=50002.0,
            size=1.0,
            order_book_depth=depth,
            side=OrderSide.SELL,
        )
        assert position > 0
        assert fill_time > 0

    def test_update_fill_rate(self, estimator):
        estimator.update_fill_rate("BTC", 0.05)
        assert "BTC" in estimator._queue_history
        assert len(estimator._queue_history["BTC"]) == 1


class TestOptimalExecutionEngine:
    """Tests for OptimalExecutionEngine."""

    @pytest.fixture
    def engine(self):
        return OptimalExecutionEngine()

    @pytest.fixture
    def market_state(self):
        return MarketState(
            symbol="BTC/USD",
            mid_price=50000.0,
            bid_price=49999.0,
            ask_price=50001.0,
            spread=2.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.5,
            intraday_volatility=0.02,
            bid_depth=100.0,
            ask_depth=100.0,
        )

    def test_initialization(self, engine):
        assert engine.almgren_chriss is not None
        assert engine.vwap is not None
        assert engine.twap is not None
        assert engine.queue_estimator is not None

    def test_create_plan_twap(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=3600,
            n_slices=10,
        )
        assert plan is not None
        assert plan.symbol == "BTC/USD"
        assert plan.total_quantity == 10.0
        assert plan.strategy == ExecutionStrategy.TWAP
        assert len(plan.slices) == 10

    def test_create_plan_vwap(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.VWAP,
            market_state=market_state,
            n_slices=10,
        )
        assert plan is not None
        assert plan.strategy == ExecutionStrategy.VWAP
        assert len(plan.slices) == 10

    def test_create_plan_almgren_chriss(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.ALMGREN_CHRISS,
            market_state=market_state,
            n_slices=10,
        )
        assert plan is not None
        assert plan.strategy == ExecutionStrategy.ALMGREN_CHRISS

    def test_record_execution(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        result = engine.record_execution(plan.plan_id, 0, 2.0, 50000.0)
        assert result is True
        assert plan.slices[0].executed_quantity == 2.0

    def test_record_execution_invalid_plan(self, engine):
        result = engine.record_execution("invalid_plan", 0, 2.0, 50000.0)
        assert result is False

    def test_get_next_slice(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        # Set slice target time to past
        for s in plan.slices:
            s.target_time = time.time() - 1
        slice_obj = engine.get_next_slice(plan.plan_id)
        assert slice_obj is not None

    def test_cancel_plan(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        result = engine.cancel_plan(plan.plan_id, "test cancellation")
        assert result is True
        assert plan.status == OrderStatus.CANCELLED

    def test_cancel_plan_invalid(self, engine):
        result = engine.cancel_plan("invalid_plan", "test")
        assert result is False

    def test_get_plan(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        retrieved = engine.get_plan(plan.plan_id)
        assert retrieved is plan

    def test_get_active_plans(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        active = engine.get_active_plans()
        assert plan in active

    def test_estimate_market_impact(self, engine, market_state):
        impact = engine.estimate_market_impact(1000.0, market_state)
        assert "participation_rate" in impact
        assert "temporary_impact_bps" in impact
        assert "permanent_impact_bps" in impact
        assert "spread_cost_bps" in impact
        assert "total_impact_bps" in impact

    def test_get_status(self, engine, market_state):
        engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        status = engine.get_status()
        assert "total_plans" in status
        assert "active_plans" in status
        assert status["total_plans"] == 1

    def test_get_execution_summary(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            total_quantity=10.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=5,
        )
        engine.record_execution(plan.plan_id, 0, 2.0, 50000.0)
        summary = engine.get_execution_summary(plan.plan_id)
        assert summary is not None
        assert "plan" in summary
        assert "slices" in summary
        assert "cost_analysis" in summary


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_optimal_executor(self):
        # Reset singleton
        import trading.execution.optimal as optimal_module
        optimal_module._optimal_executor = None

        executor1 = get_optimal_executor()
        executor2 = get_optimal_executor()
        assert executor1 is executor2
