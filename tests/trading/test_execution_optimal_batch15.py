"""Tests for execution optimal module - Batch 15 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time
import numpy as np

from trading.execution.optimal import (
    ExecutionStrategy, OrderSide, OrderStatus,
    MarketState, ExecutionSlice, ExecutionPlan,
    AlmgrenChriss, VWAP, TWAP, QueuePositionEstimator,
    OptimalExecutionEngine, get_optimal_executor
)


class TestExecutionEnums:
    """Tests for execution enums."""

    def test_execution_strategy_values(self):
        assert ExecutionStrategy.ALMGREN_CHRISS.value == "almgren_chriss"
        assert ExecutionStrategy.VWAP.value == "vwap"
        assert ExecutionStrategy.TWAP.value == "twap"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestMarketState:
    """Tests for MarketState dataclass."""

    def test_market_state_creation(self):
        state = MarketState(
            symbol="BTCUSDT",
            mid_price=45000.0,
            bid_price=44999.0,
            ask_price=45001.0,
            spread=2.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.5,
            intraday_volatility=0.02,
            bid_depth=100.0,
            ask_depth=100.0
        )
        assert state.symbol == "BTCUSDT"
        assert state.mid_price == 45000.0

    def test_market_state_to_dict(self):
        state = MarketState(symbol="BTCUSDT", mid_price=45000.0, bid_price=44999.0,
                          ask_price=45001.0, spread=2.0, daily_volume=1000000.0,
                          hourly_volume=50000.0, current_volume_rate=1000.0,
                          volatility=0.5, intraday_volatility=0.02,
                          bid_depth=100.0, ask_depth=100.0)
        d = state.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert "spread_bps" in d


class TestExecutionSlice:
    """Tests for ExecutionSlice dataclass."""

    def test_slice_creation(self):
        slice_obj = ExecutionSlice(slice_id=0, target_quantity=100.0, target_time=time.time())
        assert slice_obj.slice_id == 0
        assert slice_obj.target_quantity == 100.0
        assert slice_obj.executed_quantity == 0.0

    def test_slice_is_complete(self):
        slice_obj = ExecutionSlice(slice_id=0, target_quantity=100.0, target_time=time.time())
        assert not slice_obj.is_complete()
        slice_obj.executed_quantity = 100.0
        assert slice_obj.is_complete()


class TestExecutionPlan:
    """Tests for ExecutionPlan dataclass."""

    def test_plan_creation(self):
        plan = ExecutionPlan(
            plan_id="plan_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=time.time(),
            end_time=time.time() + 3600,
            duration_seconds=3600
        )
        assert plan.plan_id == "plan_123"
        assert plan.progress_pct() == 0.0

    def test_plan_progress(self):
        plan = ExecutionPlan(plan_id="plan_123", symbol="BTCUSDT", side=OrderSide.BUY,
                           total_quantity=1000.0, strategy=ExecutionStrategy.TWAP,
                           start_time=time.time(), end_time=time.time() + 3600,
                           duration_seconds=3600)
        plan.executed_quantity = 500.0
        assert plan.progress_pct() == 0.5


class TestAlmgrenChriss:
    """Tests for Almgren-Chriss model."""

    @pytest.fixture
    def model(self):
        return AlmgrenChriss(eta=0.01, gamma=0.001, risk_aversion=1e-6)

    def test_initialization(self, model):
        assert model.eta == 0.01
        assert model.gamma == 0.001

    def test_compute_optimal_trajectory(self, model):
        trajectory = model.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600,
            volatility=0.5,
            n_slices=10
        )
        assert len(trajectory) == 10
        assert sum(trajectory) == pytest.approx(1000.0, rel=0.01)

    def test_estimate_execution_cost(self, model):
        costs = model.estimate_execution_cost(
            total_quantity=1000.0,
            duration_seconds=3600,
            volatility=0.5,
            mid_price=45000.0
        )
        assert "temporary_impact" in costs
        assert "permanent_impact" in costs

    def test_optimal_duration(self, model):
        duration = model.optimal_duration(
            total_quantity=1000.0,
            volatility=0.5,
            daily_volume=1000000.0
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

    def test_compute_schedule(self, vwap):
        now = time.time()
        schedule = vwap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10
        )
        assert len(schedule) == 10

    def test_estimate_tracking_error(self, vwap):
        execution = [(45000.0, 100.0), (45100.0, 200.0)]
        error = vwap.estimate_tracking_error(execution, market_vwap=45050.0)
        assert isinstance(error, float)


class TestTWAP:
    """Tests for TWAP execution."""

    @pytest.fixture
    def twap(self):
        return TWAP()

    def test_compute_schedule(self, twap):
        now = time.time()
        schedule = twap.compute_schedule(1000.0, now, now + 3600, n_slices=10)
        assert len(schedule) == 10
        total = sum(q for _, q in schedule)
        assert total == pytest.approx(1000.0, rel=0.01)

    def test_with_randomization(self, twap):
        now = time.time()
        schedule = twap.with_randomization(1000.0, now, now + 3600, n_slices=10)
        assert len(schedule) == 10


class TestQueuePositionEstimator:
    """Tests for QueuePositionEstimator."""

    @pytest.fixture
    def estimator(self):
        return QueuePositionEstimator()

    def test_estimate_queue_position_buy(self, estimator):
        order_book = [(44990.0, 10.0), (44995.0, 20.0)]
        position, fill_time = estimator.estimate_queue_position(
            price=45000.0,
            size=5.0,
            order_book_depth=order_book,
            side=OrderSide.BUY
        )
        assert position >= 0
        assert fill_time >= 0

    def test_update_fill_rate(self, estimator):
        estimator.update_fill_rate("BTCUSDT", 0.05)
        assert "BTCUSDT" in estimator._queue_history


class TestOptimalExecutionEngine:
    """Tests for OptimalExecutionEngine."""

    @pytest.fixture
    def engine(self):
        return OptimalExecutionEngine()

    @pytest.fixture
    def market_state(self):
        return MarketState(
            symbol="BTCUSDT", mid_price=45000.0, bid_price=44999.0,
            ask_price=45001.0, spread=2.0, daily_volume=1000000.0,
            hourly_volume=50000.0, current_volume_rate=1000.0,
            volatility=0.5, intraday_volatility=0.02,
            bid_depth=100.0, ask_depth=100.0
        )

    def test_initialization(self, engine):
        assert engine.almgren_chriss is not None
        assert engine.vwap is not None
        assert engine.twap is not None

    def test_create_plan_twap(self, engine, market_state):
        plan = engine.create_plan(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            duration_seconds=3600,
            n_slices=10
        )
        assert plan.plan_id is not None
        assert len(plan.slices) == 10
        assert plan.status == OrderStatus.PENDING

    def test_record_execution(self, engine, market_state):
        plan = engine.create_plan("BTCUSDT", OrderSide.BUY, 1000.0,
                                 ExecutionStrategy.TWAP, market_state, n_slices=10)
        success = engine.record_execution(plan.plan_id, 0, 100.0, 45000.0)
        assert success is True
        assert plan.slices[0].executed_quantity == 100.0

    def test_cancel_plan(self, engine, market_state):
        plan = engine.create_plan("BTCUSDT", OrderSide.BUY, 1000.0,
                                 ExecutionStrategy.TWAP, market_state, n_slices=10)
        success = engine.cancel_plan(plan.plan_id, "Test cancellation")
        assert success is True
        assert plan.status == OrderStatus.CANCELLED

    def test_get_active_plans(self, engine, market_state):
        engine.create_plan("BTCUSDT", OrderSide.BUY, 1000.0,
                          ExecutionStrategy.TWAP, market_state, n_slices=10)
        active = engine.get_active_plans()
        assert len(active) >= 1

    def test_estimate_market_impact(self, engine, market_state):
        impact = engine.estimate_market_impact(1000.0, market_state)
        assert "participation_rate" in impact
        assert "total_impact_bps" in impact

    def test_get_status(self, engine):
        status = engine.get_status()
        assert "total_plans" in status
        assert "active_plans" in status


class TestGetOptimalExecutor:
    """Tests for singleton."""

    def test_singleton(self):
        engine1 = get_optimal_executor()
        engine2 = get_optimal_executor()
        assert engine1 is engine2
