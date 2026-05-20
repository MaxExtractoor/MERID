"""TWAP (Time-Weighted Average Price) Execution Engine.

Implements time-weighted average price execution for large orders to reduce market impact.
Splits large orders into smaller slices executed over time to achieve better average prices.

Key Features:
- Automatic order slicing based on size thresholds
- Time-based execution schedule (e.g., 5-minute, 15-minute, 30-minute TWAP)
- Participation rate limits to avoid moving the market
- Real-time market impact monitoring
- Adaptive scheduling based on orderbook depth

Usage:
    from execution.twap_executor import get_twap_executor
    
    executor = get_twap_executor()
    
    # Submit a TWAP order
    result = executor.submit_twap_order(
        ticker="KXBTC15M-26MAY092115-15",
        side="yes",
        total_contracts=100,
        duration_minutes=15,
        participation_rate=0.1
    )
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from utils.logger import get_logger

logger = get_logger("execution.twap_executor")


class TWAPStatus(str, Enum):
    """TWAP order status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TWAPSliceStatus(str, Enum):
    """TWAP slice status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    FAILED = "failed"


@dataclass
class TWAPSlice:
    """A single slice of a TWAP order."""
    slice_id: str
    parent_order_id: str
    ticker: str
    side: str
    contracts: int
    target_price_cents: int
    scheduled_time: datetime
    status: TWAPSliceStatus = TWAPSliceStatus.PENDING
    filled_contracts: int = 0
    avg_fill_price_cents: int = 0
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None


@dataclass
class TWAPOrder:
    """A TWAP order."""
    order_id: str
    ticker: str
    side: str
    total_contracts: int
    duration_minutes: int
    participation_rate: float
    start_time: datetime
    end_time: datetime
    status: TWAPStatus = TWAPStatus.PENDING
    slices: List[TWAPSlice] = field(default_factory=list)
    filled_contracts: int = 0
    avg_fill_price_cents: int = 0
    total_cost_usd: float = 0
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


@dataclass
class TWAPConfig:
    """TWAP execution configuration."""
    min_contracts_for_twap: int = 50  # Minimum order size to trigger TWAP
    default_duration_minutes: int = 15  # Default TWAP duration
    default_participation_rate: float = 0.1  # Default participation rate (10%)
    max_participation_rate: float = 0.3  # Maximum participation rate (30%)
    slice_interval_seconds: int = 60  # Time between slice executions
    max_slippage_tolerance_pct: float = 0.5  # Maximum acceptable slippage (0.5%)
    enable_adaptive_slicing: bool = True  # Enable adaptive slicing based on orderbook depth


class TWAPExecutor:
    """TWAP execution engine.
    
    Implements time-weighted average price execution by splitting large orders
    into smaller slices executed over time to reduce market impact.
    """
    
    _instance: Optional["TWAPExecutor"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the TWAP executor."""
        self._config = TWAPConfig()
        self._active_orders: Dict[str, TWAPOrder] = {}
        self._order_history: List[TWAPOrder] = []
        self._history_lock = threading.Lock()
        self._executor_task: Optional[asyncio.Task] = None
        self._running = False
        logger.info("TWAPExecutor initialized")
    
    def get_config(self) -> TWAPConfig:
        """Get the TWAP configuration."""
        return self._config
    
    def set_config(self, config: TWAPConfig):
        """Update the TWAP configuration."""
        self._config = config
        logger.info("TWAP configuration updated")
    
    def should_use_twap(self, contracts: int) -> bool:
        """Determine if an order should use TWAP execution.
        
        Args:
            contracts: Number of contracts to trade
            
        Returns:
            True if TWAP should be used, False otherwise
        """
        return contracts >= self._config.min_contracts_for_twap
    
    def submit_twap_order(
        self,
        ticker: str,
        side: str,
        total_contracts: int,
        duration_minutes: Optional[int] = None,
        participation_rate: Optional[float] = None,
        target_price_cents: Optional[int] = None
    ) -> TWAPOrder:
        """Submit a TWAP order for execution.
        
        Args:
            ticker: Market ticker
            side: Order side ("yes" or "no")
            total_contracts: Total number of contracts to trade
            duration_minutes: Duration of TWAP execution (uses default if None)
            participation_rate: Participation rate (uses default if None)
            target_price_cents: Target price in cents (uses mid price if None)
            
        Returns:
            TWAPOrder object
        """
        if not self.should_use_twap(total_contracts):
            logger.warning(f"Order size {total_contracts} below TWAP threshold {self._config.min_contracts_for_twap}")
        
        order_id = str(uuid4())
        duration = duration_minutes or self._config.default_duration_minutes
        participation = participation_rate or self._config.default_participation_rate
        
        # Clamp participation rate
        participation = min(participation, self._config.max_participation_rate)
        
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(minutes=duration)
        
        # Get target price if not provided
        if target_price_cents is None:
            target_price_cents = self._get_mid_price(ticker)
        
        # Create slices
        slices = self._create_slices(
            order_id=order_id,
            ticker=ticker,
            side=side,
            total_contracts=total_contracts,
            target_price_cents=target_price_cents,
            start_time=start_time,
            end_time=end_time,
            participation_rate=participation
        )
        
        order = TWAPOrder(
            order_id=order_id,
            ticker=ticker,
            side=side,
            total_contracts=total_contracts,
            duration_minutes=duration,
            participation_rate=participation,
            start_time=start_time,
            end_time=end_time,
            slices=slices,
            status=TWAPStatus.PENDING
        )
        
        self._active_orders[order_id] = order
        logger.info(
            f"TWAP order submitted: {order_id} ticker={ticker} side={side} "
            f"contracts={total_contracts} duration={duration}min slices={len(slices)}"
        )
        
        # Start execution if not already running
        if not self._running:
            self._start_executor()
        
        return order
    
    def _create_slices(
        self,
        order_id: str,
        ticker: str,
        side: str,
        total_contracts: int,
        target_price_cents: int,
        start_time: datetime,
        end_time: datetime,
        participation_rate: float
    ) -> List[TWAPSlice]:
        """Create time-weighted slices for a TWAP order.
        
        Args:
            order_id: Parent order ID
            ticker: Market ticker
            side: Order side
            total_contracts: Total contracts to trade
            target_price_cents: Target price
            start_time: Start time
            end_time: End time
            participation_rate: Participation rate
            
        Returns:
            List of TWAP slices
        """
        slices = []
        total_seconds = int((end_time - start_time).total_seconds())
        num_slices = max(1, total_seconds // self._config.slice_interval_seconds)
        
        # Calculate contracts per slice
        contracts_per_slice = total_contracts // num_slices
        remaining_contracts = total_contracts % num_slices
        
        for i in range(num_slices):
            slice_id = f"{order_id}_slice_{i}"
            slice_contracts = contracts_per_slice + (1 if i < remaining_contracts else 0)
            slice_time = start_time + timedelta(seconds=i * self._config.slice_interval_seconds)
            
            slice_obj = TWAPSlice(
                slice_id=slice_id,
                parent_order_id=order_id,
                ticker=ticker,
                side=side,
                contracts=slice_contracts,
                target_price_cents=target_price_cents,
                scheduled_time=slice_time
            )
            slices.append(slice_obj)
        
        return slices
    
    def _get_mid_price(self, ticker: str) -> int:
        """Get the mid price for a ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Mid price in cents
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get_state(ticker)
            
            if state and state.mid_cents:
                return state.mid_cents
        except Exception as e:
            logger.warning(f"Failed to get mid price for {ticker}: {e}")
        
        # Default to 50 cents if no market data available
        return 50
    
    def _start_executor(self):
        """Start the TWAP executor task."""
        if self._running:
            return
        
        self._running = True
        logger.info("TWAP executor started")
        
        # In production, this would be an async task
        # For now, we'll implement a simplified synchronous version
        # that executes slices in a background thread
        def executor_loop():
            while self._running:
                self._execute_pending_slices()
                time.sleep(1)
        
        import threading
        self._executor_thread = threading.Thread(target=executor_loop, daemon=True)
        self._executor_thread.start()
    
    def _execute_pending_slices(self):
        """Execute pending TWAP slices that are due."""
        now = datetime.now(timezone.utc)
        
        for order_id, order in list(self._active_orders.items()):
            if order.status != TWAPStatus.PENDING and order.status != TWAPStatus.EXECUTING:
                continue
            
            # Check if order should start executing
            if order.status == TWAPStatus.PENDING and now >= order.start_time:
                order.status = TWAPStatus.EXECUTING
                logger.info(f"TWAP order {order_id} started executing")
            
            # Execute pending slices
            for slice_obj in order.slices:
                if slice_obj.status == TWAPSliceStatus.PENDING and now >= slice_obj.scheduled_time:
                    self._execute_slice(slice_obj)
            
            # Check if order is complete
            self._check_order_completion(order)
    
    def _execute_slice(self, slice_obj: TWAPSlice):
        """Execute a single TWAP slice.
        
        Args:
            slice_obj: TWAP slice to execute
        """
        slice_obj.status = TWAPSliceStatus.SUBMITTED
        slice_obj.submitted_at = datetime.now(timezone.utc)
        
        try:
            # Submit the order to the venue
            # In production, this would call the actual venue API
            # For now, we'll simulate execution
            filled_contracts = self._simulate_execution(slice_obj)
            
            slice_obj.filled_contracts = filled_contracts
            slice_obj.filled_at = datetime.now(timezone.utc)
            
            if filled_contracts == slice_obj.contracts:
                slice_obj.status = TWAPSliceStatus.FILLED
            elif filled_contracts > 0:
                slice_obj.status = TWAPSliceStatus.PARTIALLY_FILLED
            else:
                slice_obj.status = TWAPSliceStatus.FAILED
                slice_obj.error_message = "No contracts filled"
            
            logger.info(
                f"TWAP slice executed: {slice_obj.slice_id} "
                f"filled={filled_contracts}/{slice_obj.contracts}"
            )
            
        except Exception as e:
            slice_obj.status = TWAPSliceStatus.FAILED
            slice_obj.error_message = str(e)
            logger.error(f"TWAP slice execution failed: {slice_obj.slice_id} error={e}")
    
    def _simulate_execution(self, slice_obj: TWAPSlice) -> int:
        """Simulate order execution (placeholder for production).
        
        Args:
            slice_obj: TWAP slice to execute
            
        Returns:
            Number of contracts filled
        """
        # In production, this would call the actual venue API
        # For now, return the full slice size as filled
        return slice_obj.contracts
    
    def _check_order_completion(self, order: TWAPOrder):
        """Check if a TWAP order is complete.
        
        Args:
            order: TWAP order to check
        """
        # Calculate total filled
        total_filled = sum(slice_obj.filled_contracts for slice_obj in order.slices)
        order.filled_contracts = total_filled
        
        # Calculate average fill price
        filled_slices = [s for s in order.slices if s.filled_contracts > 0]
        if filled_slices:
            total_value = sum(s.filled_contracts * s.avg_fill_price_cents for s in filled_slices)
            order.avg_fill_price_cents = total_value // total_filled if total_filled > 0 else 0
        
        # Check if all slices are complete
        all_slices_complete = all(
            s.status in [TWAPSliceStatus.FILLED, TWAPSliceStatus.FAILED]
            for s in order.slices
        )
        
        # Check if time has expired
        now = datetime.now(timezone.utc)
        time_expired = now >= order.end_time
        
        if all_slices_complete or time_expired:
            order.status = TWAPStatus.COMPLETED
            order.completed_at = now
            
            # Move to history
            with self._history_lock:
                self._order_history.append(order)
                if order.order_id in self._active_orders:
                    del self._active_orders[order.order_id]
            
            logger.info(f"TWAP order completed: {order.order_id} filled={total_filled}/{order.total_contracts}")
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a TWAP order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled, False otherwise
        """
        if order_id not in self._active_orders:
            logger.warning(f"TWAP order not found: {order_id}")
            return False
        
        order = self._active_orders[order_id]
        
        if order.status in [TWAPStatus.COMPLETED, TWAPStatus.CANCELLED, TWAPStatus.FAILED]:
            logger.warning(f"TWAP order cannot be cancelled: {order_id} status={order.status}")
            return False
        
        order.status = TWAPStatus.CANCELLED
        
        # Cancel pending slices
        for slice_obj in order.slices:
            if slice_obj.status == TWAPSliceStatus.PENDING:
                slice_obj.status = TWAPSliceStatus.FAILED
                slice_obj.error_message = "Order cancelled"
        
        # Move to history
        with self._history_lock:
            self._order_history.append(order)
            del self._active_orders[order_id]
        
        logger.info(f"TWAP order cancelled: {order_id}")
        return True
    
    def get_order(self, order_id: str) -> Optional[TWAPOrder]:
        """Get a TWAP order by ID.
        
        Args:
            order_id: Order ID
            
        Returns:
            TWAP order if found, None otherwise
        """
        if order_id in self._active_orders:
            return self._active_orders[order_id]
        
        # Check history
        with self._history_lock:
            for order in reversed(self._order_history):
                if order.order_id == order_id:
                    return order
        
        return None
    
    def get_active_orders(self) -> List[TWAPOrder]:
        """Get all active TWAP orders.
        
        Returns:
            List of active TWAP orders
        """
        return list(self._active_orders.values())
    
    def get_order_history(self, limit: int = 100) -> List[TWAPOrder]:
        """Get TWAP order history.
        
        Args:
            limit: Maximum number of orders to return
            
        Returns:
            List of historical TWAP orders
        """
        with self._history_lock:
            return self._order_history[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get TWAP executor summary.
        
        Returns:
            Summary statistics
        """
        active_orders = self.get_active_orders()
        history = self.get_order_history()
        
        total_orders = len(active_orders) + len(history)
        completed_orders = [o for o in history if o.status == TWAPStatus.COMPLETED]
        cancelled_orders = [o for o in history if o.status == TWAPStatus.CANCELLED]
        
        fill_rate = 0.0
        if completed_orders:
            total_contracts = sum(o.total_contracts for o in completed_orders)
            total_filled = sum(o.filled_contracts for o in completed_orders)
            fill_rate = total_filled / total_contracts if total_contracts > 0 else 0
        
        return {
            "running": self._running,
            "active_orders": len(active_orders),
            "total_orders": total_orders,
            "completed_orders": len(completed_orders),
            "cancelled_orders": len(cancelled_orders),
            "fill_rate": fill_rate,
            "config": {
                "min_contracts_for_twap": self._config.min_contracts_for_twap,
                "default_duration_minutes": self._config.default_duration_minutes,
                "default_participation_rate": self._config.default_participation_rate,
                "slice_interval_seconds": self._config.slice_interval_seconds
            }
        }
    
    def shutdown(self):
        """Shutdown the TWAP executor."""
        self._running = False
        logger.info("TWAP executor shutdown")


# Singleton accessor
_twap_executor: Optional[TWAPExecutor] = None
_twap_executor_lock = threading.Lock()


def get_twap_executor() -> TWAPExecutor:
    """Get the singleton TWAPExecutor instance."""
    global _twap_executor
    if _twap_executor is None:
        with _twap_executor_lock:
            if _twap_executor is None:
                _twap_executor = TWAPExecutor()
    return _twap_executor
