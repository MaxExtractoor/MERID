"""Comprehensive tests for trading/execution/optimal.py - Optimal Execution module.

Coverage targets: enums, dataclasses, AlmgrenChriss, VWAP, TWAP,
QueuePositionEstimator, OptimalExecutionEngine.
"""

import pytest
import time
import numpy as np
from unittest.mock import patch, MagicMock

from trading.execution.optimal import (
    ExecutionStrategy, OrderSide, OrderStatus,
    MarketState, ExecutionSlice, ExecutionPlan,
    AlmgrenChriss, VWAP, TWAP, QueuePositionEstimator,
    OptimalExecutionEngine, get_optimal_executor,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestExecutionStrategy:
    """Test ExecutionStrategy enum."""

    def test_all_values(self):
        assert ExecutionStrategy.ALMGREN_CHRISS.value == "almgren_chriss"
        assert ExecutionStrategy.VWAP.value == "vwap"
        assert ExecutionStrategy.TWAP.value == "twap"
        assert ExecutionStrategy.ICEBERG.value == "iceberg"
        assert ExecutionStrategy.ADAPTIVE.value == "adaptive"

    def test_enum_count(self):
        assert len(ExecutionStrategy) == 5


class TestOrderSide:
    """Test OrderSide enum."""

    def test_all_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderStatus:
    """Test OrderStatus enum."""

    def test_all_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.FAILED.value == "failed"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestMarketState:
    """Test MarketState dataclass."""

    @pytest.fixture
    def sample_state(self):
        return MarketState(
            symbol="ETH/USDT",
            mid_price=3000.0,
            bid_price=2999.0,
            ask_price=3001.0,
            spread=2.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.05,
            intraday_volatility=0.02,
            bid_depth=100000.0,
            ask_depth=120000.0
        )

    def test_creation(self, sample_state):
        assert sample_state.symbol == "ETH/USDT"
        assert sample_state.mid_price == 3000.0
        assert sample_state.spread == 2.0

    def test_to_dict(self, sample_state):
        d = sample_state.to_dict()
        assert d["symbol"] == "ETH/USDT"
        assert d["mid_price"] == 3000.0
        assert "spread_bps" in d
        assert d["spread_bps"] == pytest.approx(6.67, rel=0.01)

    def test_timestamp_default(self):
        state = MarketState(
            symbol="BTC/USDT",
            mid_price=50000.0,
            bid_price=49999.0,
            ask_price=50001.0,
            spread=2.0,
            daily_volume=5000000.0,
            hourly_volume=200000.0,
            current_volume_rate=5000.0,
            volatility=0.04,
            intraday_volatility=0.015,
            bid_depth=500000.0,
            ask_depth=600000.0
        )
        assert state.timestamp > 0


class TestExecutionSlice:
    """Test ExecutionSlice dataclass."""

    def test_creation(self):
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time()
        )
        assert slice_obj.slice_id == 0
        assert slice_obj.target_quantity == 100.0
        assert slice_obj.executed_quantity == 0.0

    def test_is_complete_false(self):
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time(),
            executed_quantity=50.0
        )
        assert slice_obj.is_complete() is False

    def test_is_complete_true(self):
        slice_obj = ExecutionSlice(
            slice_id=0,
            target_quantity=100.0,
            target_time=time.time(),
            executed_quantity=99.5
        )
        assert slice_obj.is_complete() is True

    def test_to_dict(self):
        slice_obj = ExecutionSlice(
            slice_id=1,
            target_quantity=50.0,
            target_time=1234567890.0,
            executed_quantity=25.0,
            executed_price=3000.0,
            slippage=0.5
        )
        d = slice_obj.to_dict()
        assert d["slice_id"] == 1
        assert d["is_complete"] is False


class TestExecutionPlan:
    """Test ExecutionPlan dataclass."""

    @pytest.fixture
    def sample_plan(self):
        return ExecutionPlan(
            plan_id="test_001",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.VWAP,
            start_time=time.time(),
            end_time=time.time() + 3600,
            duration_seconds=3600.0
        )

    def test_creation(self, sample_plan):
        assert sample_plan.plan_id == "test_001"
        assert sample_plan.strategy == ExecutionStrategy.VWAP
        assert sample_plan.status == OrderStatus.PENDING

    def test_progress_pct_zero(self, sample_plan):
        assert sample_plan.progress_pct() == 0.0

    def test_progress_pct_partial(self, sample_plan):
        sample_plan.executed_quantity = 500.0
        assert sample_plan.progress_pct() == 0.5

    def test_progress_pct_zero_total(self):
        plan = ExecutionPlan(
            plan_id="test",
            symbol="X",
            side=OrderSide.BUY,
            total_quantity=0.0,
            strategy=ExecutionStrategy.TWAP,
            start_time=0,
            end_time=0,
            duration_seconds=0
        )
        assert plan.progress_pct() == 0.0

    def test_to_dict(self, sample_plan):
        d = sample_plan.to_dict()
        assert d["plan_id"] == "test_001"
        assert d["side"] == "buy"
        assert d["strategy"] == "vwap"
        assert d["progress_pct"] == 0.0


# =============================================================================
# AlmgrenChriss Tests
# =============================================================================

class TestAlmgrenChriss:
    """Test AlmgrenChriss class."""

    def test_init(self):
        ac = AlmgrenChriss(eta=0.02, gamma=0.002, risk_aversion=1e-5)
        assert ac.eta == 0.02
        assert ac.gamma == 0.002
        assert ac.risk_aversion == 1e-5

    def test_init_defaults(self):
        ac = AlmgrenChriss()
        assert ac.eta == 0.01
        assert ac.gamma == 0.001

    def test_compute_optimal_trajectory(self):
        ac = AlmgrenChriss()
        traj = ac.compute_optimal_trajectory(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.05,
            n_slices=10
        )
        assert len(traj) == 10
        assert sum(traj) == pytest.approx(1000.0)
        assert all(q >= 0 for q in traj)

    def test_compute_optimal_trajectory_zero_slices(self):
        ac = AlmgrenChriss()
        traj = ac.compute_optimal_trajectory(1000, 3600, 0.05, 0)
        assert traj == []

    def test_compute_optimal_trajectory_zero_eta(self):
        ac = AlmgrenChriss(eta=0)
        traj = ac.compute_optimal_trajectory(1000, 3600, 0.05, 5)
        assert len(traj) == 5

    def test_compute_optimal_trajectory_small_kappa(self):
        ac = AlmgrenChriss(eta=1000, risk_aversion=1e-12)
        traj = ac.compute_optimal_trajectory(1000, 100, 0.001, 5)
        assert len(traj) == 5

    def test_estimate_execution_cost(self):
        ac = AlmgrenChriss()
        cost = ac.estimate_execution_cost(
            total_quantity=1000.0,
            duration_seconds=3600.0,
            volatility=0.05,
            mid_price=100.0
        )
        assert "temporary_impact" in cost
        assert "permanent_impact" in cost
        assert "timing_risk" in cost
        assert "total_expected_cost" in cost
        assert cost["total_expected_cost"] > 0

    def test_estimate_execution_cost_zero_duration(self):
        ac = AlmgrenChriss()
        cost = ac.estimate_execution_cost(1000, 0, 0.05, 100)
        assert cost["temporary_impact"] > 0

    def test_optimal_duration(self):
        ac = AlmgrenChriss()
        duration = ac.optimal_duration(
            total_quantity=10000.0,
            volatility=0.05,
            daily_volume=1000000.0
        )
        assert duration > 0

    def test_optimal_duration_zero_params(self):
        ac = AlmgrenChriss(eta=0, risk_aversion=0)
        duration = ac.optimal_duration(1000, 0.05, 100000)
        assert duration > 0


# =============================================================================
# VWAP Tests
# =============================================================================

class TestVWAP:
    """Test VWAP class."""

    def test_init(self):
        vwap = VWAP()
        assert vwap._default_profile is not None
        assert len(vwap._default_profile) == 24

    def test_default_profile_normalized(self):
        vwap = VWAP()
        assert vwap._default_profile.sum() == pytest.approx(1.0)

    def test_set_volume_profile(self):
        vwap = VWAP()
        profile = np.ones(24)
        vwap.set_volume_profile("ETH/USDT", profile)
        assert "ETH/USDT" in vwap._custom_profiles

    def test_set_volume_profile_invalid(self):
        vwap = VWAP()
        with pytest.raises(ValueError):
            vwap.set_volume_profile("ETH/USDT", np.ones(12))

    def test_compute_schedule(self):
        vwap = VWAP()
        now = time.time()
        schedule = vwap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10
        )
        assert len(schedule) == 10
        total = sum(q for _, q in schedule)
        assert total == pytest.approx(1000.0)

    def test_compute_schedule_custom_profile(self):
        vwap = VWAP()
        profile = np.ones(24) * 2
        vwap.set_volume_profile("TEST", profile)
        
        now = time.time()
        schedule = vwap.compute_schedule(1000, now, now + 3600, "TEST", 5)
        assert len(schedule) == 5

    def test_estimate_tracking_error_empty(self):
        vwap = VWAP()
        error = vwap.estimate_tracking_error([], 100.0)
        assert error == 0.0

    def test_estimate_tracking_error_zero_qty(self):
        vwap = VWAP()
        error = vwap.estimate_tracking_error([(100, 0)], 100.0)
        assert error == 0.0

    def test_estimate_tracking_error(self):
        vwap = VWAP()
        actual = [(101.0, 50.0), (102.0, 50.0)]
        market_vwap = 100.0
        error = vwap.estimate_tracking_error(actual, market_vwap)
        assert error > 0  # Executed above VWAP


# =============================================================================
# TWAP Tests
# =============================================================================

class TestTWAP:
    """Test TWAP class."""

    def test_init(self):
        twap = TWAP()
        assert twap is not None

    def test_compute_schedule(self):
        twap = TWAP()
        now = time.time()
        schedule = twap.compute_schedule(
            total_quantity=1000.0,
            start_time=now,
            end_time=now + 3600,
            n_slices=10
        )
        assert len(schedule) == 10
        # Equal quantities
        for _, q in schedule:
            assert q == pytest.approx(100.0)

    def test_compute_schedule_zero_slices(self):
        twap = TWAP()
        schedule = twap.compute_schedule(1000, 0, 3600, 0)
        assert schedule == []

    def test_with_randomization(self):
        twap = TWAP()
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
        total = sum(q for _, q in schedule)
        assert total == pytest.approx(1000.0, rel=0.01)


# =============================================================================
# QueuePositionEstimator Tests
# =============================================================================

class TestQueuePositionEstimator:
    """Test QueuePositionEstimator class."""

    def test_init(self):
        estimator = QueuePositionEstimator()
        assert estimator._queue_history == {}

    def test_estimate_queue_position_buy(self):
        estimator = QueuePositionEstimator()
        order_book = [
            (100.0, 50.0),
            (99.0, 100.0),
            (98.0, 200.0),
        ]
        position, fill_time = estimator.estimate_queue_position(
            price=100.0,
            size=10.0,
            order_book_depth=order_book,
            side=OrderSide.BUY
        )
        assert position >= 0
        assert fill_time >= 0

    def test_estimate_queue_position_sell(self):
        estimator = QueuePositionEstimator()
        order_book = [
            (100.0, 50.0),
            (101.0, 100.0),
            (102.0, 200.0),
        ]
        position, fill_time = estimator.estimate_queue_position(
            price=100.0,
            size=10.0,
            order_book_depth=order_book,
            side=OrderSide.SELL
        )
        assert position >= 0

    def test_estimate_queue_position_zero_size(self):
        estimator = QueuePositionEstimator()
        position, fill_time = estimator.estimate_queue_position(
            100, 0, [], OrderSide.BUY
        )
        assert fill_time == float('inf')

    def test_update_fill_rate(self):
        estimator = QueuePositionEstimator()
        estimator.update_fill_rate("ETH/USDT", 0.02)
        assert "ETH/USDT" in estimator._queue_history
        assert len(estimator._queue_history["ETH/USDT"]) == 1


# =============================================================================
# OptimalExecutionEngine Tests
# =============================================================================

class TestOptimalExecutionEngine:
    """Test OptimalExecutionEngine class."""

    @pytest.fixture
    def engine(self):
        return OptimalExecutionEngine()

    @pytest.fixture
    def market_state(self):
        return MarketState(
            symbol="ETH/USDT",
            mid_price=3000.0,
            bid_price=2999.0,
            ask_price=3001.0,
            spread=2.0,
            daily_volume=1000000.0,
            hourly_volume=50000.0,
            current_volume_rate=1000.0,
            volatility=0.05,
            intraday_volatility=0.02,
            bid_depth=100000.0,
            ask_depth=120000.0
        )

    def test_init(self, engine):
        assert engine.almgren_chriss is not None
        assert engine.vwap is not None
        assert engine.twap is not None
        assert engine._plans == {}

    def test_create_plan_almgren_chriss(self, engine, market_state):
        plan = engine.create_plan(
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            total_quantity=1000.0,
            strategy=ExecutionStrategy.ALMGREN_CHRISS,
            market_state=market_state,
            duration_seconds=3600.0,
            n_slices=10
        )
        assert plan.strategy == ExecutionStrategy.ALMGREN_CHRISS
        assert len(plan.slices) == 10

    def test_create_plan_vwap(self, engine, market_state):
        plan = engine.create_plan(
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            total_quantity=500.0,
            strategy=ExecutionStrategy.VWAP,
            market_state=market_state,
            n_slices=5
        )
        assert plan.strategy == ExecutionStrategy.VWAP

    def test_create_plan_twap(self, engine, market_state):
        plan = engine.create_plan(
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            total_quantity=200.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=4
        )
        assert plan.strategy == ExecutionStrategy.TWAP

    def test_create_plan_default_strategy(self, engine, market_state):
        plan = engine.create_plan(
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.ICEBERG,
            market_state=market_state
        )
        # Falls back to TWAP schedule
        assert len(plan.slices) > 0

    def test_record_execution(self, engine, market_state):
        plan = engine.create_plan(
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            total_quantity=100.0,
            strategy=ExecutionStrategy.TWAP,
            market_state=market_state,
            n_slices=2
        )
        
        result = engine.record_execution(plan.plan_id, 0, 50.0, 3001.0)
        assert result is True
        assert plan.executed_quantity == 50.0

    def test_record_execution_invalid_plan(self, engine):
        result = engine.record_execution("nonexistent", 0, 50, 100)
        assert result is False

    def test_record_execution_invalid_slice(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state, n_slices=2
        )
        result = engine.record_execution(plan.plan_id, 99, 50, 100)
        assert result is False

    def test_record_execution_fills_plan(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state, n_slices=2
        )
        engine.record_execution(plan.plan_id, 0, 50, 100)
        engine.record_execution(plan.plan_id, 1, 50, 100)
        assert plan.status == OrderStatus.FILLED

    def test_get_next_slice(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state, duration_seconds=1, n_slices=2
        )
        # Slices are in the past
        time.sleep(0.1)
        next_slice = engine.get_next_slice(plan.plan_id)
        assert next_slice is not None

    def test_get_next_slice_invalid_plan(self, engine):
        result = engine.get_next_slice("nonexistent")
        assert result is None

    def test_cancel_plan(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state
        )
        result = engine.cancel_plan(plan.plan_id, "Test cancellation")
        assert result is True
        assert plan.status == OrderStatus.CANCELLED

    def test_cancel_plan_invalid(self, engine):
        result = engine.cancel_plan("nonexistent", "reason")
        assert result is False

    def test_get_plan(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state
        )
        retrieved = engine.get_plan(plan.plan_id)
        assert retrieved is plan

    def test_get_plan_invalid(self, engine):
        result = engine.get_plan("nonexistent")
        assert result is None

    def test_get_active_plans(self, engine, market_state):
        engine.create_plan("ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP, market_state)
        engine.create_plan("BTC", OrderSide.SELL, 200, ExecutionStrategy.VWAP, market_state)
        
        active = engine.get_active_plans()
        assert len(active) == 2

    def test_estimate_market_impact(self, engine, market_state):
        impact = engine.estimate_market_impact(10000.0, market_state)
        assert "participation_rate" in impact
        assert "temporary_impact_bps" in impact
        assert "permanent_impact_bps" in impact
        assert "total_impact_bps" in impact

    def test_get_status(self, engine, market_state):
        engine.create_plan("ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP, market_state)
        status = engine.get_status()
        assert status["total_plans"] == 1
        assert status["active_plans"] == 1

    def test_get_execution_summary(self, engine, market_state):
        plan = engine.create_plan(
            "ETH", OrderSide.BUY, 100, ExecutionStrategy.TWAP,
            market_state, n_slices=2
        )
        summary = engine.get_execution_summary(plan.plan_id)
        assert "plan" in summary
        assert "slices" in summary
        assert "cost_analysis" in summary

    def test_get_execution_summary_invalid(self, engine):
        result = engine.get_execution_summary("nonexistent")
        assert result is None


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetOptimalExecutor:
    """Test get_optimal_executor singleton."""

    def test_returns_instance(self):
        import trading.execution.optimal as module
        module._optimal_executor = None
        
        engine = get_optimal_executor()
        assert isinstance(engine, OptimalExecutionEngine)

    def test_returns_same_instance(self):
        engine1 = get_optimal_executor()
        engine2 = get_optimal_executor()
        assert engine1 is engine2
