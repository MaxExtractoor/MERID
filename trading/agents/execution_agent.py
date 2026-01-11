"""
Execution Agent - Lightning-fast trade execution with one-click capability.

Handles:
- One-click market orders
- Smart order routing
- Execution speed optimization
- Fill tracking and reporting
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("trading.agents.execution")


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Trading order."""
    order_id: str
    venue: str
    asset: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: float = field(default_factory=time.time)
    submitted_at: Optional[float] = None
    filled_at: Optional[float] = None
    fill_price: Optional[float] = None
    filled_size: float = 0.0
    fees: float = 0.0
    
    def execution_time_ms(self) -> Optional[float]:
        """Calculate execution time in milliseconds."""
        if self.submitted_at and self.filled_at:
            return (self.filled_at - self.submitted_at) * 1000
        return None


@dataclass
class TradeExecution:
    """Completed trade execution record."""
    trade_id: str
    order: Order
    execution_time_ms: float
    slippage_bps: float
    expected_price: float
    actual_price: float
    pnl: Optional[float] = None


class ExecutionAgent:
    """
    Lightning-fast trade execution agent.
    
    Features:
    - One-click execution
    - Smart order routing
    - Execution speed optimization
    - Real-time fill tracking
    """
    
    def __init__(
        self,
        default_venue: str = "hyperliquid",
        max_execution_time_ms: float = 500.0
    ):
        self.default_venue = default_venue
        self.max_execution_time_ms = max_execution_time_ms
        
        self.pending_orders: Dict[str, Order] = {}
        self.execution_history: List[TradeExecution] = []
        self.recent_trades: List[Dict] = []
        
        self.total_orders = 0
        self.total_filled = 0
        self.avg_execution_time_ms = 0.0
        self.avg_slippage_bps = 0.0
        
        self.performance_stats = {
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "total_volume_usd": 0.0,
            "avg_execution_time_ms": 0.0
        }
        
        logger.info(
            "ExecutionAgent initialized: venue=%s, max_execution_time=%.1fms",
            default_venue, max_execution_time_ms
        )
    
    async def execute_one_click_trade(
        self,
        asset: str,
        side: OrderSide,
        size_usd: float,
        venue: Optional[str] = None
    ) -> Order:
        """
        Execute one-click market order with lightning speed.
        
        Optimized for minimal latency.
        """
        venue = venue or self.default_venue
        order_id = f"order_{int(time.time() * 1000000)}"
        
        order = Order(
            order_id=order_id,
            venue=venue,
            asset=asset,
            side=side,
            order_type=OrderType.MARKET,
            size=size_usd
        )
        
        self.pending_orders[order_id] = order
        self.total_orders += 1
        
        logger.info(
            "One-click trade initiated: %s %s %.2f USD on %s",
            side.value, asset, size_usd, venue
        )
        
        # Execute with minimal latency
        start_time = time.time()
        
        try:
            # Submit order
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = time.time()
            
            # Simulate exchange execution (in production, call actual exchange API)
            await self._execute_on_exchange(order)
            
            # Track execution
            execution_time = (time.time() - start_time) * 1000
            
            if order.status == OrderStatus.FILLED:
                self.total_filled += 1
                
                # Update metrics
                self._update_execution_metrics(order, execution_time)
                
                logger.info(
                    "Order filled: %s, price=%.4f, time=%.1fms",
                    order_id, order.fill_price, execution_time
                )
            
            return order
            
        except Exception as exc:
            order.status = OrderStatus.REJECTED
            logger.error("Order execution failed: %s - %s", order_id, exc)
            raise
        finally:
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
    
    async def execute_limit_order(
        self,
        asset: str,
        side: OrderSide,
        size_usd: float,
        limit_price: float,
        venue: Optional[str] = None
    ) -> Order:
        """Execute limit order."""
        venue = venue or self.default_venue
        order_id = f"order_{int(time.time() * 1000000)}"
        
        order = Order(
            order_id=order_id,
            venue=venue,
            asset=asset,
            side=side,
            order_type=OrderType.LIMIT,
            size=size_usd,
            price=limit_price
        )
        
        self.pending_orders[order_id] = order
        self.total_orders += 1
        
        logger.info(
            "Limit order placed: %s %s %.2f USD @ %.4f on %s",
            side.value, asset, size_usd, limit_price, venue
        )
        
        # Submit to exchange
        order.status = OrderStatus.SUBMITTED
        order.submitted_at = time.time()
        
        # In production, this would monitor for fills
        # For now, simulate
        await self._execute_on_exchange(order)
        
        return order
    
    async def execute_stop_loss(
        self,
        asset: str,
        side: OrderSide,
        size_usd: float,
        stop_price: float,
        venue: Optional[str] = None
    ) -> Order:
        """Execute stop loss order."""
        venue = venue or self.default_venue
        order_id = f"order_{int(time.time() * 1000000)}"
        
        order = Order(
            order_id=order_id,
            venue=venue,
            asset=asset,
            side=side,
            order_type=OrderType.STOP_LOSS,
            size=size_usd,
            stop_price=stop_price
        )
        
        self.pending_orders[order_id] = order
        self.total_orders += 1
        
        logger.info(
            "Stop loss placed: %s %s %.2f USD @ stop=%.4f on %s",
            side.value, asset, size_usd, stop_price, venue
        )
        
        order.status = OrderStatus.SUBMITTED
        order.submitted_at = time.time()
        
        return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        if order_id not in self.pending_orders:
            logger.warning("Order %s not found in pending orders", order_id)
            return False
        
        order = self.pending_orders[order_id]
        
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
            logger.warning("Order %s already %s", order_id, order.status.value)
            return False
        
        # Cancel on exchange
        order.status = OrderStatus.CANCELLED
        del self.pending_orders[order_id]
        
        logger.info("Order cancelled: %s", order_id)
        return True
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get current order status."""
        return self.pending_orders.get(order_id)
    
    def get_performance_stats(self) -> Dict:
        """Get execution performance statistics."""
        return self.performance_stats.copy()
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get recent executed trades."""
        return self.recent_trades[-limit:]
    
    def _record_trade(self, order_data: Dict):
        """Record a completed trade."""
        self.recent_trades.append({
            "order_id": order_data.get('order_id'),
            "asset": order_data.get('asset'),
            "side": order_data.get('side'),
            "size_usd": order_data.get('size_usd'),
            "fill_price": order_data.get('fill_price'),
            "status": order_data.get('status'),
            "timestamp": time.time()
        })
        
        # Keep only last 100 trades
        if len(self.recent_trades) > 100:
            self.recent_trades = self.recent_trades[-100:]
    
    def _update_execution_metrics(self, order: Order, execution_time_ms: float):
        """Update execution performance metrics."""
        # Update average execution time
        total_time = self.avg_execution_time_ms * (self.total_filled - 1) + execution_time_ms
        self.avg_execution_time_ms = total_time / self.total_filled
        
        # Calculate slippage (for market orders)
        if order.order_type == OrderType.MARKET and order.fill_price:
            expected_price = 100.0  # Mock
            slippage_bps = abs((order.fill_price - expected_price) / expected_price) * 10000
            
            total_slippage = self.avg_slippage_bps * (self.total_filled - 1) + slippage_bps
            self.avg_slippage_bps = total_slippage / self.total_filled
            
            # Record execution
            execution = TradeExecution(
                trade_id=order.order_id,
                order=order,
                execution_time_ms=execution_time_ms,
                slippage_bps=slippage_bps,
                expected_price=expected_price,
                actual_price=order.fill_price
            )
            
            self.execution_history.append(execution)
    
    # Internal methods
    
    async def _execute_on_exchange(self, order: Order):
        """
        Execute order on exchange.
        
        In production, this would call actual exchange APIs.
        For now, simulate execution.
        """
        # Simulate network latency
        await asyncio.sleep(0.05)  # 50ms
        
        # Simulate fill
        if order.order_type == OrderType.MARKET:
            # Market orders fill immediately
            order.status = OrderStatus.FILLED
            order.filled_at = time.time()
            order.filled_size = order.size
            
            # Simulate fill price with small slippage
            base_price = 100.0  # Mock price
            slippage = 0.001 if order.side == OrderSide.BUY else -0.001
            order.fill_price = base_price * (1 + slippage)
            order.fees = order.size * 0.0005  # 0.05% fee
            
        elif order.order_type == OrderType.LIMIT:
            # Limit orders may or may not fill
            # For simulation, 70% fill rate
            import random
            if random.random() < 0.7:
                order.status = OrderStatus.FILLED
                order.filled_at = time.time()
                order.filled_size = order.size
                order.fill_price = order.price
                order.fees = order.size * 0.0002  # Lower fee for maker


# Global singleton
_execution_agent: Optional[ExecutionAgent] = None


def get_execution_agent() -> ExecutionAgent:
    """Get or create execution agent singleton."""
    global _execution_agent
    if _execution_agent is None:
        _execution_agent = ExecutionAgent()
    return _execution_agent
