"""
Trading Execution Engine

Handles trade execution with safety checks, position management, and dry-run capabilities.
Provides a unified interface for trading operations across multiple venues.
"""

import asyncio
import random
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("trading.execution")

class OrderType(Enum):
    """Order types supported by the execution engine."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"

class OrderSide(Enum):
    """Order sides."""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """Order status tracking."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"

@dataclass
class TradeOrder:
    """Trade order specification."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None  # None for market orders
    stop_price: Optional[float] = None  # For stop orders
    time_in_force: str = "GTC"  # Good Till Cancelled
    reduce_only: bool = False  # Reduce position only
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ExecutionResult:
    """Result of order execution."""
    order_id: str
    status: OrderStatus
    executed_quantity: float
    executed_price: Optional[float]
    execution_fee: float
    timestamp: float
    venue: str
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Position:
    """Trading position tracking."""
    symbol: str
    side: OrderSide
    size: float  # Positive for long, negative for short
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: float
    venue: str

class TradingExecutionEngine:
    """
    Unified trading execution engine with safety checks and dry-run capabilities.
    
    Features:
    - Multi-venue support
    - Dry-run execution for testing
    - Position management
    - Risk checks and safety limits
    - Comprehensive order tracking
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.dry_run = config.get("dry_run", True)
        self.max_position_size = config.get("max_position_size", 100000.0)  # $100K max
        self.max_daily_loss = config.get("max_daily_loss", 10000.0)  # $10K max daily loss
        self.venue_configs = config.get("venues", {})
        
        # State tracking
        self._orders: Dict[str, TradeOrder] = {}
        self._executions: Dict[str, ExecutionResult] = {}
        self._positions: Dict[str, Position] = {}
        self._daily_pnl = 0.0
        self._last_reset_time = time.time()
        
        # Safety tracking
        self._order_count = 0
        self._error_count = 0
        self._last_execution_time = 0.0
        
        logger.info(f"TradingExecutionEngine initialized (dry_run: {self.dry_run})")
    
    async def execute_order(self, order: TradeOrder) -> ExecutionResult:
        """
        Execute a trading order with safety checks.
        
        Args:
            order: TradeOrder to execute
            
        Returns:
            ExecutionResult with execution details
        """
        try:
            # Pre-execution safety checks
            if not await self._safety_check(order):
                return self._create_rejected_result(order, "Safety check failed")
            
            # Store order
            self._orders[order.order_id] = order
            self._order_count += 1
            
            # Execute order
            if self.dry_run:
                result = await self._execute_dry_run(order)
            else:
                result = await self._execute_live(order)
            
            # Store execution result
            self._executions[order.order_id] = result
            
            # Update position if filled
            if result.status == OrderStatus.FILLED:
                await self._update_position(order, result)
            
            # Update daily PnL
            await self._update_daily_pnl(result)
            
            self._last_execution_time = time.time()
            
            logger.info(f"Order {order.order_id} executed: {result.status}")
            return result
            
        except Exception as e:
            logger.error(f"Order execution failed for {order.order_id}: {e}")
            self._error_count += 1
            return self._create_failed_result(order, str(e))
    
    async def _safety_check(self, order: TradeOrder) -> bool:
        """Perform pre-execution safety checks."""
        try:
            # Execution gate — unified safety check (kill switch, recon, feeds, PnL)
            try:
                from core.execution_gate import check_execution_gate
                gate = check_execution_gate()
                if gate.blocked:
                    reasons_str = "; ".join(r.message for r in gate.reasons)
                    logger.warning(
                        "execution_blocked | order=%s symbol=%s reasons=[%s]",
                        order.order_id, order.symbol, reasons_str,
                    )
                    return False
                if gate.is_limited:
                    is_reduce = getattr(order, 'reduce_only', False) or getattr(order, 'side', '') in ('sell', 'close')
                    if not is_reduce:
                        logger.warning(
                            "execution_limited | order=%s symbol=%s — new risk blocked (reduce-only mode)",
                            order.order_id, order.symbol,
                        )
                        return False
            except ImportError:
                pass

            # Check daily loss limit
            if self._daily_pnl < -self.max_daily_loss:
                logger.warning(f"Daily loss limit exceeded: ${self._daily_pnl:.2f}")
                return False
            
            # Check position size
            notional_value = order.quantity * (order.price or 45000.0)  # Default BTC price
            if notional_value > self.max_position_size:
                logger.warning(f"Position size too large: ${notional_value:.2f}")
                return False
            
            # Check order frequency (rate limiting)
            time_since_last = time.time() - self._last_execution_time
            if time_since_last < 0.1:  # Max 10 orders per second
                logger.warning("Order frequency too high")
                return False
            
            # Check symbol support
            if not self._is_symbol_supported(order.symbol):
                logger.warning(f"Symbol not supported: {order.symbol}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Safety check failed: {e}")
            return False
    
    async def _execute_dry_run(self, order: TradeOrder) -> ExecutionResult:
        """Execute order in dry-run mode."""
        try:
            # Simulate execution delay
            await asyncio.sleep(0.05)  # 50ms execution time
            
            # Generate realistic execution result
            if order.order_type == OrderType.MARKET:
                # Market orders always fill
                executed_price = self._get_mock_price(order.symbol)
                executed_quantity = order.quantity
                status = OrderStatus.FILLED
            else:
                # Limit orders may or may not fill (80% fill rate for testing)
                if random.random() < 0.8:
                    executed_price = order.price
                    executed_quantity = order.quantity
                    status = OrderStatus.FILLED
                else:
                    executed_price = None
                    executed_quantity = 0.0
                    status = OrderStatus.SUBMITTED
            
            # Calculate fee (0.1% typical)
            fee = executed_quantity * executed_price * 0.001 if executed_price else 0.0
            
            result = ExecutionResult(
                order_id=order.order_id,
                status=status,
                executed_quantity=executed_quantity,
                executed_price=executed_price,
                execution_fee=fee,
                timestamp=time.time(),
                venue="dry_run",
                metadata={
                    "dry_run": True,
                    "simulation": True,
                    "fill_rate": 0.8 if order.order_type != OrderType.MARKET else 1.0
                }
            )
            
            logger.debug(f"Dry-run execution: {order.order_id} -> {status}")
            return result
            
        except Exception as e:
            logger.error(f"Dry-run execution failed: {e}")
            return self._create_failed_result(order, str(e))
    
    async def _execute_live(self, order: TradeOrder) -> ExecutionResult:
        """Execute order in live mode (placeholder for actual implementation)."""
        # This would contain actual exchange API calls
        logger.warning("Live execution not implemented - using dry-run fallback")
        return await self._execute_dry_run(order)
    
    def _get_mock_price(self, symbol: str) -> float:
        """Get mock price for symbol."""
        # Base prices for major cryptocurrencies
        base_prices = {
            "BTCUSDT": 45000.0,
            "ETHUSDT": 3000.0,
            "SOLUSDT": 100.0,
            "BNBUSDT": 300.0,
            "ADAUSDT": 0.5,
            "XRPUSDT": 0.6,
            "DOTUSDT": 7.0,
            "DOGEUSDT": 0.08,
            "AVAXUSDT": 35.0,
            "MATICUSDT": 0.9
        }
        
        base_price = base_prices.get(symbol, 1.0)
        
        # Add small variation (-0.1% to +0.1%)
        import random
        variation = random.uniform(-0.001, 0.001)
        
        return base_price * (1 + variation)
    
    def _is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        supported_symbols = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT",
            "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT"
        ]
        return symbol in supported_symbols
    
    async def _update_position(self, order: TradeOrder, result: ExecutionResult):
        """Update position after order execution."""
        try:
            if result.status != OrderStatus.FILLED:
                return
            
            symbol = order.symbol
            current_pos = self._positions.get(symbol)
            
            executed_value = result.executed_quantity * result.executed_price
            
            if current_pos is None:
                # New position
                side = order.side
                size = executed_value if order.side == OrderSide.BUY else -executed_value
                entry_price = result.executed_price
                
                self._positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    current_price=entry_price,
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                    timestamp=time.time(),
                    venue=result.venue
                )
            else:
                # Update existing position
                if order.side == OrderSide.BUY:
                    current_pos.size += executed_value
                else:
                    current_pos.size -= executed_value
                
                # Update current price
                current_pos.current_price = result.executed_price
                
                # Calculate unrealized PnL
                if current_pos.size != 0:
                    price_change = (current_pos.current_price - current_pos.entry_price) / current_pos.entry_price
                    current_pos.unrealized_pnl = current_pos.size * price_change
                
                # Remove position if closed
                if abs(current_pos.size) < 1.0:  # Less than $1 remaining
                    del self._positions[symbol]
            
            logger.debug(f"Position updated for {symbol}: {executed_value:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to update position: {e}")
    
    async def _update_daily_pnl(self, result: ExecutionResult):
        """Update daily PnL tracking."""
        try:
            # Reset daily PnL if it's a new day
            current_time = time.time()
            if current_time - self._last_reset_time > 86400:  # 24 hours
                self._daily_pnl = 0.0
                self._last_reset_time = current_time
                logger.info("Daily PnL reset")
            
            # Update PnL (simplified - would need more complex calculation in production)
            # For now, just subtract fees from PnL
            self._daily_pnl -= result.execution_fee
            
        except Exception as e:
            logger.error(f"Failed to update daily PnL: {e}")
    
    def _create_rejected_result(self, order: TradeOrder, reason: str) -> ExecutionResult:
        """Create a rejected execution result."""
        return ExecutionResult(
            order_id=order.order_id,
            status=OrderStatus.REJECTED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="safety_check",
            error_message=reason,
            metadata={"rejected": True, "reason": reason}
        )
    
    def _create_failed_result(self, order: TradeOrder, error: str) -> ExecutionResult:
        """Create a failed execution result."""
        return ExecutionResult(
            order_id=order.order_id,
            status=OrderStatus.FAILED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="execution_engine",
            error_message=error,
            metadata={"failed": True, "error": error}
        )
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for symbol."""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all current positions."""
        return self._positions.copy()
    
    def get_order_status(self, order_id: str) -> Optional[ExecutionResult]:
        """Get execution status for order."""
        return self._executions.get(order_id)
    
    def get_execution_metrics(self) -> Dict[str, Any]:
        """Get execution engine metrics."""
        total_orders = len(self._executions)
        filled_orders = sum(1 for r in self._executions.values() if r.status == OrderStatus.FILLED)
        fill_rate = filled_orders / total_orders if total_orders > 0 else 0.0
        
        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "fill_rate": fill_rate,
            "error_count": self._error_count,
            "daily_pnl": self._daily_pnl,
            "active_positions": len(self._positions),
            "dry_run": self.dry_run,
            "last_execution": self._last_execution_time
        }
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order (placeholder for actual implementation)."""
        try:
            if order_id in self._executions:
                result = self._executions[order_id]
                if result.status in [OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED]:
                    # In production, this would call the exchange API
                    result.status = OrderStatus.CANCELLED
                    result.timestamp = time.time()
                    logger.info(f"Order {order_id} cancelled")
                    return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def reset_daily_metrics(self):
        """Reset daily metrics."""
        self._daily_pnl = 0.0
        self._last_reset_time = time.time()
        logger.info("Daily metrics reset")
