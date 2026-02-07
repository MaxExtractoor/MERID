"""
MERID-FIN Optimal Execution

Phase 4.1 of Master Build Directive

Implements:
- Almgren-Chriss optimal execution
- VWAP (Volume Weighted Average Price)
- TWAP (Time Weighted Average Price)
- Queue position estimation

This module answers: "How do we execute with minimal footprint?"

MERID-FIN may never bypass GOV or OPS.
"""

from __future__ import annotations

import time
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("trading.execution.optimal")


class ExecutionStrategy(Enum):
    """Execution strategy types."""
    ALMGREN_CHRISS = "almgren_chriss"
    VWAP = "vwap"
    TWAP = "twap"
    ICEBERG = "iceberg"
    ADAPTIVE = "adaptive"


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class MarketState:
    """Current market state for execution."""
    symbol: str
    mid_price: float
    bid_price: float
    ask_price: float
    spread: float
    
    # Volume metrics
    daily_volume: float
    hourly_volume: float
    current_volume_rate: float  # Per minute
    
    # Volatility
    volatility: float  # Annualized
    intraday_volatility: float
    
    # Liquidity
    bid_depth: float
    ask_depth: float
    
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mid_price": round(self.mid_price, 6),
            "spread": round(self.spread, 6),
            "spread_bps": round(self.spread / self.mid_price * 10000, 2),
            "daily_volume": round(self.daily_volume, 2),
            "volatility": round(self.volatility, 4),
            "bid_depth": round(self.bid_depth, 2),
            "ask_depth": round(self.ask_depth, 2),
        }


@dataclass
class ExecutionSlice:
    """A single slice of an execution schedule."""
    slice_id: int
    target_quantity: float
    target_time: float
    
    # Execution
    executed_quantity: float = 0.0
    executed_price: float = 0.0
    execution_time: Optional[float] = None
    
    # Slippage
    expected_price: float = 0.0
    slippage: float = 0.0
    
    def is_complete(self) -> bool:
        return self.executed_quantity >= self.target_quantity * 0.99
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "target_quantity": round(self.target_quantity, 6),
            "target_time": self.target_time,
            "executed_quantity": round(self.executed_quantity, 6),
            "executed_price": round(self.executed_price, 6),
            "slippage": round(self.slippage, 6),
            "is_complete": self.is_complete(),
        }


@dataclass
class ExecutionPlan:
    """Complete execution plan."""
    plan_id: str
    symbol: str
    side: OrderSide
    total_quantity: float
    strategy: ExecutionStrategy
    
    # Timing
    start_time: float
    end_time: float
    duration_seconds: float
    
    # Slices
    slices: List[ExecutionSlice] = field(default_factory=list)
    
    # Progress
    executed_quantity: float = 0.0
    average_price: float = 0.0
    total_slippage: float = 0.0
    
    # Status
    status: OrderStatus = OrderStatus.PENDING
    
    # Risk metrics
    expected_cost: float = 0.0
    actual_cost: float = 0.0
    market_impact: float = 0.0
    
    def progress_pct(self) -> float:
        if self.total_quantity == 0:
            return 0.0
        return self.executed_quantity / self.total_quantity
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "total_quantity": round(self.total_quantity, 6),
            "strategy": self.strategy.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "slice_count": len(self.slices),
            "executed_quantity": round(self.executed_quantity, 6),
            "progress_pct": round(self.progress_pct() * 100, 2),
            "average_price": round(self.average_price, 6),
            "total_slippage": round(self.total_slippage, 6),
            "status": self.status.value,
            "expected_cost": round(self.expected_cost, 6),
            "actual_cost": round(self.actual_cost, 6),
            "market_impact": round(self.market_impact, 6),
        }


class AlmgrenChriss:
    """
    Almgren-Chriss optimal execution model.
    
    Minimizes expected cost + risk penalty:
    E[Cost] + λ * Var[Cost]
    
    where:
    - Temporary impact: g(v) = η * v
    - Permanent impact: h(v) = γ * v
    - λ = risk aversion parameter
    """
    
    def __init__(
        self,
        eta: float = 0.01,      # Temporary impact coefficient
        gamma: float = 0.001,   # Permanent impact coefficient
        risk_aversion: float = 1e-6,
    ):
        self.eta = eta
        self.gamma = gamma
        self.risk_aversion = risk_aversion
        
        logger.info(
            "Almgren-Chriss initialized (eta=%.4f, gamma=%.4f, lambda=%.2e)",
            eta, gamma, risk_aversion
        )
    
    def compute_optimal_trajectory(
        self,
        total_quantity: float,
        duration_seconds: float,
        volatility: float,
        n_slices: int = 10,
    ) -> List[float]:
        """
        Compute optimal execution trajectory.
        
        Returns list of quantities per slice.
        """
        if n_slices <= 0:
            return []
        
        # Time step
        tau = duration_seconds / n_slices
        
        # Kappa parameter (urgency)
        # kappa = sqrt(lambda * sigma^2 / eta)
        if self.eta > 0:
            kappa = math.sqrt(self.risk_aversion * volatility ** 2 / self.eta)
        else:
            kappa = 0.01
        
        # Optimal trajectory using hyperbolic functions
        # x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T)
        
        T = duration_seconds
        trajectory = []
        
        for j in range(n_slices):
            t_j = j * tau
            t_next = (j + 1) * tau
            
            if kappa * T < 0.01:
                # Linear approximation for small kappa*T
                x_j = total_quantity * (1 - t_j / T)
                x_next = total_quantity * (1 - t_next / T)
            else:
                x_j = total_quantity * math.sinh(kappa * (T - t_j)) / math.sinh(kappa * T)
                x_next = total_quantity * math.sinh(kappa * (T - t_next)) / math.sinh(kappa * T)
            
            # Quantity to execute in this slice
            slice_qty = x_j - x_next
            trajectory.append(max(0, slice_qty))
        
        # Normalize to ensure total matches
        total_traj = sum(trajectory)
        if total_traj > 0:
            trajectory = [q * total_quantity / total_traj for q in trajectory]
        
        return trajectory
    
    def estimate_execution_cost(
        self,
        total_quantity: float,
        duration_seconds: float,
        volatility: float,
        mid_price: float,
    ) -> Dict[str, float]:
        """
        Estimate total execution cost.
        
        Returns breakdown of costs.
        """
        # Average trading rate
        v_avg = total_quantity / duration_seconds if duration_seconds > 0 else total_quantity
        
        # Temporary impact cost
        temp_cost = self.eta * v_avg * total_quantity * mid_price
        
        # Permanent impact cost
        perm_cost = 0.5 * self.gamma * total_quantity ** 2 * mid_price
        
        # Timing risk (variance)
        timing_risk = self.risk_aversion * volatility ** 2 * total_quantity ** 2 * duration_seconds
        
        return {
            "temporary_impact": temp_cost,
            "permanent_impact": perm_cost,
            "timing_risk": timing_risk,
            "total_expected_cost": temp_cost + perm_cost,
            "total_with_risk": temp_cost + perm_cost + timing_risk,
        }
    
    def optimal_duration(
        self,
        total_quantity: float,
        volatility: float,
        daily_volume: float,
    ) -> float:
        """
        Compute optimal execution duration.
        
        Balances market impact vs timing risk.
        """
        # Participation rate constraint (max 10% of daily volume)
        max_participation = 0.10
        min_duration = total_quantity / (daily_volume * max_participation / 86400)
        
        # Optimal duration from Almgren-Chriss
        if self.eta > 0 and self.risk_aversion > 0:
            opt_duration = math.sqrt(self.eta / (self.risk_aversion * volatility ** 2))
        else:
            opt_duration = min_duration
        
        return max(min_duration, opt_duration)


class VWAP:
    """
    Volume Weighted Average Price execution.
    
    Executes proportionally to expected volume profile.
    """
    
    def __init__(self):
        # Default hourly volume profile (normalized)
        # Assumes higher volume at open/close
        self._default_profile = self._generate_default_profile()
        self._custom_profiles: Dict[str, np.ndarray] = {}
        
        logger.info("VWAP executor initialized")
    
    def _generate_default_profile(self) -> np.ndarray:
        """Generate default U-shaped volume profile."""
        hours = np.arange(24)
        
        # U-shape: high at 9-10, 15-16 (market hours), low overnight
        profile = np.ones(24) * 0.5
        
        # Market hours (assuming 9:30-16:00)
        profile[9:17] = 1.0
        profile[9] = 1.5   # Open
        profile[10] = 1.3
        profile[15] = 1.4  # Close approach
        profile[16] = 1.2
        
        # Normalize
        profile = profile / profile.sum()
        
        return profile
    
    def set_volume_profile(self, symbol: str, profile: np.ndarray) -> None:
        """Set custom volume profile for a symbol."""
        if len(profile) != 24:
            raise ValueError("Profile must have 24 hourly values")
        
        self._custom_profiles[symbol] = profile / profile.sum()
    
    def compute_schedule(
        self,
        total_quantity: float,
        start_time: float,
        end_time: float,
        symbol: str = "default",
        n_slices: int = 10,
    ) -> List[Tuple[float, float]]:
        """
        Compute VWAP execution schedule.
        
        Returns list of (time, quantity) tuples.
        """
        profile = self._custom_profiles.get(symbol, self._default_profile)
        
        duration = end_time - start_time
        slice_duration = duration / n_slices
        
        schedule = []
        
        for i in range(n_slices):
            slice_start = start_time + i * slice_duration
            slice_end = slice_start + slice_duration
            
            # Get expected volume fraction for this period
            start_hour = int((slice_start % 86400) / 3600)
            end_hour = int((slice_end % 86400) / 3600)
            
            # Sum profile values for hours in this slice
            if start_hour == end_hour:
                vol_fraction = profile[start_hour] * (slice_duration / 3600)
            else:
                vol_fraction = sum(profile[h % 24] for h in range(start_hour, end_hour + 1))
            
            schedule.append((slice_start, total_quantity * vol_fraction))
        
        # Normalize
        total_scheduled = sum(q for _, q in schedule)
        if total_scheduled > 0:
            schedule = [(t, q * total_quantity / total_scheduled) for t, q in schedule]
        
        return schedule
    
    def estimate_tracking_error(
        self,
        actual_execution: List[Tuple[float, float]],
        market_vwap: float,
    ) -> float:
        """Estimate VWAP tracking error."""
        if not actual_execution:
            return 0.0
        
        total_qty = sum(q for _, q in actual_execution)
        if total_qty == 0:
            return 0.0
        
        # Weighted average execution price
        exec_vwap = sum(p * q for p, q in actual_execution) / total_qty
        
        # Tracking error in bps
        tracking_error = (exec_vwap - market_vwap) / market_vwap * 10000
        
        return tracking_error


class TWAP:
    """
    Time Weighted Average Price execution.
    
    Executes equal quantities at regular intervals.
    """
    
    def __init__(self):
        logger.info("TWAP executor initialized")
    
    def compute_schedule(
        self,
        total_quantity: float,
        start_time: float,
        end_time: float,
        n_slices: int = 10,
    ) -> List[Tuple[float, float]]:
        """
        Compute TWAP execution schedule.
        
        Returns list of (time, quantity) tuples.
        """
        if n_slices <= 0:
            return []
        
        duration = end_time - start_time
        slice_duration = duration / n_slices
        quantity_per_slice = total_quantity / n_slices
        
        schedule = []
        for i in range(n_slices):
            slice_time = start_time + i * slice_duration
            schedule.append((slice_time, quantity_per_slice))
        
        return schedule
    
    def with_randomization(
        self,
        total_quantity: float,
        start_time: float,
        end_time: float,
        n_slices: int = 10,
        time_jitter_pct: float = 0.1,
        size_jitter_pct: float = 0.1,
    ) -> List[Tuple[float, float]]:
        """
        Compute TWAP with randomization to avoid detection.
        """
        base_schedule = self.compute_schedule(
            total_quantity, start_time, end_time, n_slices
        )
        
        randomized = []
        duration = end_time - start_time
        slice_duration = duration / n_slices
        
        remaining_qty = total_quantity
        
        for i, (t, q) in enumerate(base_schedule):
            # Time jitter
            time_jitter = np.random.uniform(-time_jitter_pct, time_jitter_pct)
            new_time = t + slice_duration * time_jitter
            new_time = max(start_time, min(end_time, new_time))
            
            # Size jitter (except last slice)
            if i < len(base_schedule) - 1:
                size_jitter = np.random.uniform(-size_jitter_pct, size_jitter_pct)
                new_qty = q * (1 + size_jitter)
                new_qty = min(new_qty, remaining_qty)
            else:
                new_qty = remaining_qty
            
            remaining_qty -= new_qty
            randomized.append((new_time, new_qty))
        
        return randomized


class QueuePositionEstimator:
    """
    Estimates queue position for limit orders.
    """
    
    def __init__(self):
        self._queue_history: Dict[str, deque] = {}
        
        logger.info("Queue position estimator initialized")
    
    def estimate_queue_position(
        self,
        price: float,
        size: float,
        order_book_depth: List[Tuple[float, float]],
        side: OrderSide,
    ) -> Tuple[int, float]:
        """
        Estimate queue position and expected fill time.
        
        Returns (position, expected_fill_time_seconds).
        """
        # Find queue at price level
        queue_ahead = 0.0
        
        for level_price, level_size in order_book_depth:
            if side == OrderSide.BUY:
                if level_price >= price:
                    queue_ahead += level_size
            else:
                if level_price <= price:
                    queue_ahead += level_size
        
        # Estimate fill time based on historical fill rate
        # Simplified: assume 1% of queue fills per second
        fill_rate = 0.01
        expected_time = queue_ahead / (fill_rate * size) if size > 0 else float('inf')
        
        return int(queue_ahead), expected_time
    
    def update_fill_rate(
        self,
        symbol: str,
        observed_fill_rate: float,
    ) -> None:
        """Update observed fill rate for a symbol."""
        if symbol not in self._queue_history:
            self._queue_history[symbol] = deque(maxlen=100)
        
        self._queue_history[symbol].append({
            "fill_rate": observed_fill_rate,
            "timestamp": time.time(),
        })


class OptimalExecutionEngine:
    """
    Main optimal execution engine.
    
    Coordinates execution strategies and monitors progress.
    """
    
    def __init__(self):
        self.almgren_chriss = AlmgrenChriss()
        self.vwap = VWAP()
        self.twap = TWAP()
        self.queue_estimator = QueuePositionEstimator()
        
        # Active plans
        self._plans: Dict[str, ExecutionPlan] = {}
        self._plan_count = 0
        
        # Execution history
        self._execution_history: deque = deque(maxlen=1000)
        
        logger.info("Optimal execution engine initialized")
    
    def create_plan(
        self,
        symbol: str,
        side: OrderSide,
        total_quantity: float,
        strategy: ExecutionStrategy,
        market_state: MarketState,
        duration_seconds: Optional[float] = None,
        n_slices: int = 10,
    ) -> ExecutionPlan:
        """Create an execution plan."""
        self._plan_count += 1
        plan_id = f"exec_{self._plan_count}_{int(time.time())}"
        
        now = time.time()
        
        # Determine duration
        if duration_seconds is None:
            duration_seconds = self.almgren_chriss.optimal_duration(
                total_quantity,
                market_state.volatility,
                market_state.daily_volume,
            )
        
        end_time = now + duration_seconds
        
        # Generate schedule based on strategy
        if strategy == ExecutionStrategy.ALMGREN_CHRISS:
            quantities = self.almgren_chriss.compute_optimal_trajectory(
                total_quantity, duration_seconds, market_state.volatility, n_slices
            )
            times = [now + i * duration_seconds / n_slices for i in range(n_slices)]
        
        elif strategy == ExecutionStrategy.VWAP:
            schedule = self.vwap.compute_schedule(
                total_quantity, now, end_time, symbol, n_slices
            )
            times = [t for t, _ in schedule]
            quantities = [q for _, q in schedule]
        
        elif strategy == ExecutionStrategy.TWAP:
            schedule = self.twap.with_randomization(
                total_quantity, now, end_time, n_slices
            )
            times = [t for t, _ in schedule]
            quantities = [q for _, q in schedule]
        
        else:
            # Default to TWAP
            schedule = self.twap.compute_schedule(
                total_quantity, now, end_time, n_slices
            )
            times = [t for t, _ in schedule]
            quantities = [q for _, q in schedule]
        
        # Create slices
        slices = []
        for i, (t, q) in enumerate(zip(times, quantities)):
            slices.append(ExecutionSlice(
                slice_id=i,
                target_quantity=q,
                target_time=t,
                expected_price=market_state.mid_price,
            ))
        
        # Estimate cost
        cost_estimate = self.almgren_chriss.estimate_execution_cost(
            total_quantity,
            duration_seconds,
            market_state.volatility,
            market_state.mid_price,
        )
        
        plan = ExecutionPlan(
            plan_id=plan_id,
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            strategy=strategy,
            start_time=now,
            end_time=end_time,
            duration_seconds=duration_seconds,
            slices=slices,
            expected_cost=cost_estimate["total_expected_cost"],
        )
        
        self._plans[plan_id] = plan
        
        logger.info(
            "Execution plan created: %s - %s %s %.4f over %.0fs (%d slices)",
            plan_id, side.value, symbol, total_quantity, duration_seconds, n_slices
        )
        
        return plan
    
    def record_execution(
        self,
        plan_id: str,
        slice_id: int,
        executed_quantity: float,
        executed_price: float,
    ) -> bool:
        """Record an execution against a plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        
        if slice_id >= len(plan.slices):
            return False
        
        slice_obj = plan.slices[slice_id]
        
        # Update slice
        slice_obj.executed_quantity += executed_quantity
        slice_obj.executed_price = executed_price
        slice_obj.execution_time = time.time()
        slice_obj.slippage = executed_price - slice_obj.expected_price
        
        # Update plan totals
        plan.executed_quantity += executed_quantity
        
        # Recalculate average price
        total_value = sum(
            s.executed_quantity * s.executed_price
            for s in plan.slices
            if s.executed_quantity > 0
        )
        if plan.executed_quantity > 0:
            plan.average_price = total_value / plan.executed_quantity
        
        # Update slippage
        plan.total_slippage = sum(
            s.slippage * s.executed_quantity
            for s in plan.slices
        )
        
        # Update status
        if plan.executed_quantity >= plan.total_quantity * 0.99:
            plan.status = OrderStatus.FILLED
        elif plan.executed_quantity > 0:
            plan.status = OrderStatus.PARTIAL
        
        # Calculate actual cost
        plan.actual_cost = abs(plan.total_slippage)
        
        # Record in history
        self._execution_history.append({
            "plan_id": plan_id,
            "slice_id": slice_id,
            "quantity": executed_quantity,
            "price": executed_price,
            "timestamp": time.time(),
        })
        
        return True
    
    def get_next_slice(self, plan_id: str) -> Optional[ExecutionSlice]:
        """Get the next slice to execute."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        
        now = time.time()
        
        for slice_obj in plan.slices:
            if not slice_obj.is_complete() and slice_obj.target_time <= now:
                return slice_obj
        
        return None
    
    def cancel_plan(self, plan_id: str, reason: str) -> bool:
        """Cancel an execution plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        
        plan.status = OrderStatus.CANCELLED
        
        logger.warning("Execution plan cancelled: %s - Reason: %s", plan_id, reason)
        return True
    
    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """Get an execution plan."""
        return self._plans.get(plan_id)
    
    def get_active_plans(self) -> List[ExecutionPlan]:
        """Get all active plans."""
        return [
            p for p in self._plans.values()
            if p.status in (OrderStatus.PENDING, OrderStatus.PARTIAL)
        ]
    
    def estimate_market_impact(
        self,
        quantity: float,
        market_state: MarketState,
    ) -> Dict[str, float]:
        """Estimate market impact of an order."""
        # Participation rate
        participation = quantity / market_state.hourly_volume if market_state.hourly_volume > 0 else 1.0
        
        # Temporary impact (linear)
        temp_impact = self.almgren_chriss.eta * quantity / market_state.daily_volume
        
        # Permanent impact
        perm_impact = self.almgren_chriss.gamma * quantity / market_state.daily_volume
        
        # Spread cost
        spread_cost = market_state.spread / market_state.mid_price / 2
        
        return {
            "participation_rate": round(participation, 4),
            "temporary_impact_bps": round(temp_impact * 10000, 2),
            "permanent_impact_bps": round(perm_impact * 10000, 2),
            "spread_cost_bps": round(spread_cost * 10000, 2),
            "total_impact_bps": round((temp_impact + perm_impact + spread_cost) * 10000, 2),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        active = self.get_active_plans()
        
        return {
            "total_plans": len(self._plans),
            "active_plans": len(active),
            "completed_plans": len([p for p in self._plans.values() if p.status == OrderStatus.FILLED]),
            "cancelled_plans": len([p for p in self._plans.values() if p.status == OrderStatus.CANCELLED]),
            "execution_history_size": len(self._execution_history),
        }
    
    def get_execution_summary(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get execution summary for a plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        
        return {
            "plan": plan.to_dict(),
            "slices": [s.to_dict() for s in plan.slices],
            "cost_analysis": {
                "expected_cost": round(plan.expected_cost, 6),
                "actual_cost": round(plan.actual_cost, 6),
                "cost_savings": round(plan.expected_cost - plan.actual_cost, 6),
            },
        }


# Singleton instance
_optimal_executor: Optional[OptimalExecutionEngine] = None


def get_optimal_executor() -> OptimalExecutionEngine:
    """Get the singleton optimal execution engine."""
    global _optimal_executor
    if _optimal_executor is None:
        _optimal_executor = OptimalExecutionEngine()
    return _optimal_executor
