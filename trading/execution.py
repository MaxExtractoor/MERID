"""
Execution Layer - Trade execution per MASTER_SPEC v1.0

This module implements the execution layer for MERID:
- Paper trading (default mode for safe testing)
- Live execution (requires explicit toggle + API keys)
- Position management with real-time P&L tracking
- Risk controls (max position size, stop-loss automation)

Reference: MASTER_SPEC.md Section 3 (Layer 4: Execution Layer)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.events import EventEnvelope, EventType, EventPriority, create_audit_event
from core.error_handling import (
    get_error_handler, with_error_handling, ErrorSeverity,
    RetryStrategy, get_health_monitor
)
from core.state_recovery import get_state_manager, get_self_healing
from core.reality_auditor import RealityAuditorProtocol
from utils.deps import get_ccxt_async
from utils.logger import get_logger
from core.social_strategy_router import evaluate_social_trade, release_social_position
from latency_optimizer.orchestrator_hooks import record_trading_tick
from trading.execution.defense import DefenseAction, ThreatLevel

logger = get_logger("trading.execution")


class ExecutionMode(Enum):
    """Execution mode for the trading system."""
    PAPER = "paper"
    LIVE = "live"
    DISABLED = "disabled"


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(Enum):
    """Position side."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


def _is_abort_action(action: DefenseAction) -> bool:
    """Return True when MEV defense recommends aborting execution."""
    return action == DefenseAction.ABORT


def _is_high_threat(level: ThreatLevel) -> bool:
    """Return True when threat level is high enough to force abort."""
    return level in {ThreatLevel.HIGH, ThreatLevel.CRITICAL}


@dataclass
class Order:
    """Represents a trading order."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None
    
    consensus_round_id: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)
    
    def is_complete(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


@dataclass
class Position:
    """Represents an open position."""
    position_id: str
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    current_price: float
    
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    opened_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    leverage: float = 1.0
    margin_used: float = 0.0
    
    metadata: Dict[str, object] = field(default_factory=dict)
    
    def update_pnl(self, current_price: float) -> None:
        """Update unrealized P&L based on current price."""
        self.current_price = current_price
        self.updated_at = time.time()
        
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
        else:
            self.unrealized_pnl = 0.0
    
    def check_stop_loss(self, current_price: float) -> bool:
        """Check if stop loss is triggered."""
        if self.stop_loss is None:
            return False
        
        if self.side == PositionSide.LONG:
            return current_price <= self.stop_loss
        elif self.side == PositionSide.SHORT:
            return current_price >= self.stop_loss
        
        return False
    
    def check_take_profit(self, current_price: float) -> bool:
        """Check if take profit is triggered."""
        if self.take_profit is None:
            return False
        
        if self.side == PositionSide.LONG:
            return current_price >= self.take_profit
        elif self.side == PositionSide.SHORT:
            return current_price <= self.take_profit
        
        return False


@dataclass
class ExecutionConfig:
    """Configuration for execution layer."""
    
    mode: ExecutionMode = ExecutionMode.PAPER
    
    # Exchange configuration (for live mode)
    exchange: str = "coinbase"
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_passphrase: Optional[str] = None  # For exchanges that require it
    sandbox: bool = True  # Use sandbox/testnet by default
    
    # Risk limits
    max_position_size_usd: float = 10000.0
    max_total_exposure_usd: float = 50000.0
    max_leverage: float = 3.0
    # Paper-mode risk limits (used for fallbacks/degraded execution)
    paper_max_position_size_usd: float = 50000.0
    paper_max_total_exposure_usd: float = 200000.0
    
    # Default stop/take profit
    default_stop_loss_pct: float = 0.05
    default_take_profit_pct: float = 0.10
    
    slippage_tolerance_pct: float = 0.005
    
    order_timeout_seconds: float = 60.0
    
    # Consensus requirements
    require_consensus: bool = True
    min_consensus_confidence: float = 0.6


class ExecutionError(Exception):
    """Base exception for execution errors."""
    pass


class InsufficientFundsError(ExecutionError):
    """Raised when insufficient funds for order."""
    pass


class PositionLimitError(ExecutionError):
    """Raised when position limits exceeded."""
    pass


class OrderRejectedError(ExecutionError):
    """Raised when order is rejected."""
    pass


class ExecutionEngine:
    """
    Main execution engine for trade management.
    
    Supports:
    - Paper trading (simulated execution)
    - Live execution (via exchange APIs)
    - Position tracking and P&L calculation
    - Risk controls and stop-loss automation
    
    All execution requires consensus approval unless disabled.
    """
    
    def __init__(self, config: Optional[ExecutionConfig] = None) -> None:
        """
        Initialize execution engine.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or ExecutionConfig()
        
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._order_history: List[Order] = []
        
        self._balance: float = 100000.0
        self._equity: float = 100000.0
        self._total_exposure: float = 0.0
        
        self._price_cache: Dict[str, float] = {}
        
        self._event_callbacks: List[Callable[[EventEnvelope], None]] = []
        
        self._running = False
        self._monitor_task: Optional[asyncio.Task[None]] = None
        
        # Reality enforcement integration
        self._reality_auditor: RealityAuditorProtocol | None = None
        try:
            from core.reality_auditor import get_reality_auditor
            self._reality_auditor = get_reality_auditor()
            self._logger = get_logger("trading.execution.engine")
            self._logger.info("Reality auditor integrated - execution gating active")
        except Exception as e:
            self._logger = get_logger("trading.execution.engine")
            self._logger.warning(f"Reality auditor not available: {e}")
        
        # MEV defense integration
        self._mev_defender = None
        try:
            from trading.execution.defense import (
                get_mev_defense,
                DefenseAction,
                ThreatLevel,
            )
            self._mev_defender = get_mev_defense()
            self._logger.info("MEV defense integrated - protection active")
        except Exception as e:
            self._logger.warning(f"MEV defense not available: {e}")
        
        # Validation engine integration
        self._validator = None
        try:
            from core.validation.engine import get_validation_engine
            self._validator = get_validation_engine()
            self._logger.info("Validation engine integrated")
        except Exception as e:
            self._logger.warning(f"Validation engine not available: {e}")
        
        # Error handling and self-healing
        self._error_handler = get_error_handler()
        self._state_manager = get_state_manager("execution_engine")
        self._self_healing = get_self_healing()
        self._health_monitor = get_health_monitor()
        
        # Register circuit breakers
        self._order_breaker = self._error_handler.register_circuit_breaker(
            "order_execution", failure_threshold=5, timeout=60.0
        )
        self._position_breaker = self._error_handler.register_circuit_breaker(
            "position_management", failure_threshold=3, timeout=30.0
        )
        
        # Register health check
        self._health_check = self._health_monitor.register_health_check("execution_engine")
        
        # Register self-healing strategy
        self._self_healing.register_healing_strategy(
            "execution_engine",
            self._heal_execution_engine
        )
        
        self._logger.info("Execution engine initialized with full production-grade features")

    def set_reality_auditor(self, auditor: RealityAuditorProtocol | None) -> None:
        """Inject or override the reality auditor (primarily for tests)."""

        self._reality_auditor = auditor

    def set_mev_defender(self, defender) -> None:
        """Inject or override the MEV defender implementation."""

        self._mev_defender = defender

    def _resolve_execution_mode(self) -> ExecutionMode:
        """Determine actual execution mode, accounting for degraded fallbacks."""
        if self.config.mode == ExecutionMode.LIVE:
            if not (self.config.api_key and self.config.api_secret):
                self._logger.warning(
                    "Live mode requested but API credentials missing; executing in PAPER mode"
                )
                return ExecutionMode.PAPER
        return self.config.mode
    
    async def start(self) -> None:
        """Start the execution engine."""
        if self._running:
            return
        
        # Initialize state manager
        await self._state_manager.initialize()
        await self._state_manager.start_auto_save(interval=30.0)
        
        # Restore state if available
        state = await self._state_manager.get_state()
        if state:
            self._balance = state.get("balance", self._balance)
            self._equity = state.get("equity", self._equity)
            self._logger.info("State restored from persistence")
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._position_monitor_loop())
        
        # Start health monitoring
        await self._health_monitor.start_monitoring(interval=30.0)
        
        self._logger.info(
            "Execution engine started: mode=%s, max_position=$%.0f",
            self.config.mode.value, self.config.max_position_size_usd
        )
    
    async def stop(self) -> None:
        """Stop the execution engine."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Save final state
        await self._state_manager.update_state({
            "balance": self._balance,
            "equity": self._equity,
            "total_exposure": self._total_exposure,
            "positions": {k: v.__dict__ for k, v in self._positions.items()},
            "shutdown_time": time.time()
        }, create_recovery_point=True)
        
        await self._state_manager.stop_auto_save()
        await self._health_monitor.stop_monitoring()
        
        self._logger.info("Execution engine stopped")
    
    def update_price(self, symbol: str, price: float) -> None:
        """
        Update cached price for a symbol.
        
        Args:
            symbol: Trading symbol
            price: Current price
        """
        self._price_cache[symbol] = price
        
        if symbol in self._positions:
            position = self._positions[symbol]
            position.update_pnl(price)
        
        self._update_equity()
    
    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        consensus_round_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        portfolio_value: Optional[float] = None,
    ) -> Order:
        """
        Submit a new order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            order_type: Market, limit, etc.
            price: Limit price (for limit orders)
            stop_loss: Stop loss price
            take_profit: Take profit price
            consensus_round_id: Associated consensus round
            strategy_id: Optional strategy identifier for social gating
            sentiment_score: Optional sentiment score for social strategies
            portfolio_value: Optional portfolio value for social sizing
            
        Returns:
            Created Order object
            
        Raises:
            ExecutionError: If order validation fails
        """
        if self.config.mode == ExecutionMode.DISABLED:
            raise ExecutionError("Execution is disabled")

        order_id = str(uuid.uuid4())
        latency_metadata = {
            "symbol": symbol,
            "side": side.value,
            "strategy": strategy_id or "unspecified",
        }
        decision_key = f"order:{order_id}"

        with record_trading_tick(latency_metadata, decision_key=decision_key):
            if strategy_id and sentiment_score is not None:
                try:
                    current_price = price or self._price_cache.get(symbol, 0.0)
                    if current_price == 0.0:
                        self._logger.warning(
                            f"No price available for {symbol}, skipping social gating"
                        )
                    else:
                        pv = portfolio_value or self._equity
                        social_eval = evaluate_social_trade(
                            strategy_id=strategy_id,
                            asset=symbol,
                            portfolio_value=pv,
                            sentiment_score=sentiment_score,
                            market_metrics={"price": current_price},
                            latency_decision_key=f"social:{order_id}",
                        )

                        if not social_eval["allowed"]:
                            reasons = "; ".join(social_eval["reasons"])
                            self._logger.error(
                                f"Social strategy gating blocked order: {reasons}"
                            )
                            raise OrderRejectedError(f"Social gating failed: {reasons}")

                        self._logger.info(
                            f"Social strategy gating passed for {symbol}: size=$%.2f",
                            social_eval["sizing"].get("size_usd", 0.0),
                        )
                except OrderRejectedError:
                    raise
                except Exception as exc:
                    self._logger.error("Social gating error: %s", exc)
                    raise OrderRejectedError(f"Social gating error: {exc}")

            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_loss,
                consensus_round_id=consensus_round_id,
                metadata={
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "strategy_id": strategy_id,
                    "sentiment_score": sentiment_score,
                    "portfolio_value": portfolio_value,
                },
            )

            if self._reality_auditor:
                audit_result = self._reality_auditor.audit_execution_intent(
                    order_id=order.order_id,
                    symbol=symbol,
                    side=side.value,
                    quantity=quantity,
                    order_value=quantity * (price or self._price_cache.get(symbol, 0)),
                )

                if not audit_result.passed:
                    self._logger.error(
                        f"Execution blocked by reality auditor: {audit_result.reason}"
                    )
                    await self._error_handler.handle_error(
                        OrderRejectedError(
                            f"Reality audit failed: {audit_result.reason}"
                        ),
                        "execution_engine",
                        "submit_order",
                        ErrorSeverity.HIGH,
                    )
                    raise OrderRejectedError(
                        f"Reality audit failed: {audit_result.reason}"
                    )

                if audit_result.warnings:
                    for warning in audit_result.warnings:
                        self._logger.warning("Execution warning: %s", warning)

            mev_recommendation = None
            if self._mev_defender:
                try:
                    current_price = price or self._price_cache.get(symbol, 0)
                    order_value = quantity * current_price
                    mev_recommendation = self._mev_defender.get_defense_recommendation(
                        symbol=symbol,
                        venue="default",
                        side=side.value,
                        order_size=order_value,
                        daily_volume=order_value * 100,
                        volatility=0.02,
                    )

                    self._logger.info(
                        "MEV defense recommendation: %s (threat=%s, risk=$%.2f)",
                        mev_recommendation.action.value,
                        mev_recommendation.threat_level.value,
                        mev_recommendation.estimated_mev_risk,
                    )

                    self._mev_defender.front_running_detector.register_pending_order(
                        order_id=order.order_id,
                        symbol=symbol,
                        side=side.value,
                        size=quantity,
                        price=current_price,
                    )

                    order.metadata["mev_recommendation"] = (
                        mev_recommendation.to_dict()
                    )

                    if (
                        _is_abort_action(mev_recommendation.action)
                        and _is_high_threat(mev_recommendation.threat_level)
                    ):
                        raise OrderRejectedError(
                            f"MEV defense aborted order ({mev_recommendation.threat_level.value} threat)"
                        )

                except OrderRejectedError:
                    raise
                except Exception as exc:
                    self._logger.error("MEV defense error: %s", exc)
                    await self._error_handler.handle_error(
                        exc,
                        "execution_engine",
                        "mev_defense",
                        ErrorSeverity.MEDIUM,
                    )

            if self._validator:
                try:
                    validation_result = await self._validator.validate_order(order)
                    if not validation_result.passed:
                        self._logger.error(
                            "Order validation failed: %s",
                            validation_result.reason,
                        )
                        raise OrderRejectedError(
                            f"Validation failed: {validation_result.reason}"
                        )
                except Exception as exc:
                    self._logger.error("Validation error: %s", exc)
                    await self._error_handler.handle_error(
                        exc,
                        "execution_engine",
                        "validation",
                        ErrorSeverity.HIGH,
                    )

            execution_mode = self._resolve_execution_mode()
            order.metadata["execution_mode"] = execution_mode.value

            self._validate_order(order, execution_mode=execution_mode)
            self._orders[order.order_id] = order

            self._emit_event(create_audit_event(
                action="order_submitted",
                actor="execution_engine",
                details={
                    "order_id": order.order_id,
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "order_type": order_type.value,
                },
                severity="info",
            ))

            if execution_mode == ExecutionMode.PAPER:
                await self._execute_paper_order(order, stop_loss, take_profit)
            else:
                await self._execute_live_order(order, stop_loss, take_profit)

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if cancelled successfully
        """
        if order_id not in self._orders:
            return False

        order = self._orders[order_id]

        if order.is_complete():
            return False

        order.status = OrderStatus.CANCELLED
        order.updated_at = time.time()

        self._emit_event(create_audit_event(
            action="order_cancelled",
            actor="execution_engine",
            details={"order_id": order_id},
            severity="info",
        ))

        return True

    async def close_position(
        self,
        symbol: str,
        reason: str = "manual",
    ) -> Optional[Order]:
        """
        Close an open position.

        Args:
            symbol: Position symbol to close
            reason: Reason for closing

        Returns:
            Closing order if position existed
        """
        if symbol not in self._positions:
            return None

        position = self._positions[symbol]
        close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY

        order = await self.submit_order(
            symbol=symbol,
            side=close_side,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
        )

        if (
            position.metadata.get("strategy_id")
            and position.metadata.get("sentiment_score") is not None
        ):
            try:
                position_value = position.quantity * position.current_price
                release_social_position(symbol, position_value)
                self._logger.info(
                    "Released social exposure for %s: $%.2f",
                    symbol,
                    position_value,
                )
            except Exception as exc:
                self._logger.error("Failed to release social exposure: %s", exc)

        self._emit_event(create_audit_event(
            action="position_closed",
            actor="execution_engine",
            details={
                "symbol": symbol,
                "reason": reason,
                "realized_pnl": position.realized_pnl + position.unrealized_pnl,
            },
            severity="info",
        ))

        return order

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self._positions.values())

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def get_open_orders(self) -> List[Order]:
        """Get all open orders."""
        return [o for o in self._orders.values() if not o.is_complete()]

    def get_account_summary(self) -> Dict[str, object]:
        """Get account summary."""
        return {
            "mode": self.config.mode.value,
            "balance": self._balance,
            "equity": self._equity,
            "total_exposure": self._total_exposure,
            "unrealized_pnl": sum(p.unrealized_pnl for p in self._positions.values()),
            "realized_pnl": sum(p.realized_pnl for p in self._positions.values()),
            "open_positions": len(self._positions),
            "open_orders": len([o for o in self._orders.values() if not o.is_complete()]),
            "margin_used": sum(p.margin_used for p in self._positions.values()),
        }

    async def sync_with_exchange(self) -> Dict[str, object]:
        """
        Synchronize positions and balance with exchange.
        Only works in LIVE mode with configured API keys.
        """
        if self.config.mode != ExecutionMode.LIVE:
            return {"status": "skipped", "reason": "Not in live mode"}
        
        if not self.config.api_key or not self.config.api_secret:
            return {"status": "error", "reason": "No API keys configured"}
        
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            return {"status": "error", "reason": "CCXT not installed"}

        try:
            exchange_class = getattr(ccxt_async, self.config.exchange)
            exchange = exchange_class({
                'apiKey': self.config.api_key,
                'secret': self.config.api_secret,
                'enableRateLimit': True,
            })
            
            try:
                # Fetch balance
                balance = await exchange.fetch_balance()
                self._balance = float(balance.get('total', {}).get('USDT', 0))
                
                # Fetch open positions (for futures/margin)
                try:
                    positions = await exchange.fetch_positions()
                    synced_positions = 0
                    
                    for pos in positions:
                        if float(pos.get('contracts', 0)) > 0:
                            symbol = pos.get('symbol')
                            side = PositionSide.LONG if pos.get('side') == 'long' else PositionSide.SHORT
                            
                            self._positions[symbol] = Position(
                                position_id=str(uuid.uuid4()),
                                symbol=symbol,
                                side=side,
                                quantity=float(pos.get('contracts', 0)),
                                entry_price=float(pos.get('entryPrice', 0)),
                                current_price=float(pos.get('markPrice', 0)),
                                unrealized_pnl=float(pos.get('unrealizedPnl', 0)),
                                leverage=float(pos.get('leverage', 1)),
                            )
                            synced_positions += 1
                            
                except Exception:
                    # Exchange may not support positions (spot only)
                    synced_positions = 0
                
                self._update_equity()
                
                return {
                    "status": "synced",
                    "balance": self._balance,
                    "positions_synced": synced_positions,
                    "exchange": self.config.exchange,
                }
                
            finally:
                await exchange.close()
                
        except Exception as e:
            self._logger.error(f"Exchange sync failed: {e}")
            return {"status": "error", "reason": str(e)}
    
    def register_event_callback(
        self,
        callback: Callable[[EventEnvelope], None],
    ) -> None:
        """Register callback for execution events."""
        self._event_callbacks.append(callback)
    
    def _validate_order(
        self,
        order: Order,
        execution_mode: Optional[ExecutionMode] = None,
    ) -> None:
        """
        Validate order against risk controls.
        
        Raises:
            ExecutionError: If validation fails
        """
        mode = execution_mode or self.config.mode
        current_price = self._price_cache.get(order.symbol, 0)
        if current_price == 0 and order.order_type == OrderType.MARKET:
            raise ExecutionError(f"No price available for {order.symbol}")
        
        order_value = order.quantity * (order.price or current_price)

        if mode == ExecutionMode.PAPER:
            max_position = getattr(
                self.config,
                "paper_max_position_size_usd",
                self.config.max_position_size_usd,
            )
            max_total = getattr(
                self.config,
                "paper_max_total_exposure_usd",
                self.config.max_total_exposure_usd,
            )
        else:
            max_position = self.config.max_position_size_usd
            max_total = self.config.max_total_exposure_usd
        
        if order_value > max_position:
            raise PositionLimitError(
                f"Order value ${order_value:.0f} exceeds max position size "
                f"${max_position:.0f}"
            )
        
        new_exposure = self._total_exposure + order_value
        if new_exposure > max_total:
            raise PositionLimitError(
                f"Total exposure ${new_exposure:.0f} would exceed max "
                f"${max_total:.0f}"
            )
        
        if order_value > self._balance:
            raise InsufficientFundsError(
                f"Order value ${order_value:.0f} exceeds available balance "
                f"${self._balance:.0f}"
            )
    
    async def _execute_paper_order(
        self,
        order: Order,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> None:
        """Execute order in paper trading mode."""
        current_price = self._price_cache.get(order.symbol, 100.0)
        
        slippage = current_price * self.config.slippage_tolerance_pct
        if order.side == OrderSide.BUY:
            fill_price = current_price + slippage
        else:
            fill_price = current_price - slippage
        
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.filled_at = time.time()
        order.updated_at = time.time()
        
        self._update_position_from_fill(order, stop_loss, take_profit)
        
        self._order_history.append(order)
        
        self._logger.info(
            "Paper order filled: %s %s %.4f %s @ %.2f",
            order.order_id[:8], order.side.value, order.quantity,
            order.symbol, fill_price
        )
    
    async def _execute_live_order(
        self,
        order: Order,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> None:
        """
        Execute order in live trading mode via CCXT.
        
        Requires exchange API keys to be configured.
        """
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            self._logger.error("CCXT not installed; cannot execute live order")
            self._validate_order(order, execution_mode=ExecutionMode.PAPER)
            await self._execute_paper_order(order, stop_loss, take_profit)
            return

        try:
            # Get exchange from config or default to coinbase
            exchange_id = getattr(self.config, 'exchange', 'coinbase')
            api_key = getattr(self.config, 'api_key', None)
            api_secret = getattr(self.config, 'api_secret', None)
            
            if not api_key or not api_secret:
                self._logger.warning(
                    "No API keys configured for live trading. "
                    "Falling back to paper mode for order %s",
                    order.order_id
                )
                await self._execute_paper_order(order, stop_loss, take_profit)
                return
            
            # Initialize exchange
            exchange_class = getattr(ccxt_async, exchange_id)
            exchange = exchange_class({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
            })
            
            try:
                # Convert symbol format (BTC/USDT -> BTC/USDT)
                symbol = order.symbol
                
                # Place order
                if order.order_type == OrderType.MARKET:
                    if order.side == OrderSide.BUY:
                        result = await exchange.create_market_buy_order(
                            symbol, order.quantity
                        )
                    else:
                        result = await exchange.create_market_sell_order(
                            symbol, order.quantity
                        )
                else:
                    result = await exchange.create_limit_order(
                        symbol,
                        order.side.value,
                        order.quantity,
                        order.price
                    )
                
                # Update order with exchange response
                order.status = OrderStatus.FILLED
                order.filled_quantity = float(result.get('filled', order.quantity))
                order.filled_price = float(result.get('average', result.get('price', 0)))
                order.filled_at = time.time()
                order.updated_at = time.time()
                order.metadata['exchange_order_id'] = result.get('id')
                order.metadata['exchange'] = exchange_id
                
                # Update position
                self._update_position_from_fill(order, stop_loss, take_profit)
                self._order_history.append(order)
                
                self._logger.info(
                    "LIVE order filled: %s %s %.4f %s @ %.2f on %s",
                    order.order_id[:8], order.side.value, order.quantity,
                    order.symbol, order.filled_price, exchange_id
                )
                
            finally:
                await exchange.close()
                
        except Exception as e:
            self._logger.error(
                "Live order execution failed: %s. Falling back to paper mode.",
                str(e)
            )
            self._validate_order(order, execution_mode=ExecutionMode.PAPER)
            await self._execute_paper_order(order, stop_loss, take_profit)
    
    def _update_position_from_fill(
        self,
        order: Order,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> None:
        """Update position based on filled order."""
        symbol = order.symbol
        
        if symbol in self._positions:
            position = self._positions[symbol]
            
            if (order.side == OrderSide.BUY and position.side == PositionSide.SHORT) or \
               (order.side == OrderSide.SELL and position.side == PositionSide.LONG):
                position.realized_pnl += position.unrealized_pnl
                self._balance += position.unrealized_pnl
                
                # Record trade in analytics
                try:
                    from analytics.performance import get_performance_tracker
                    tracker = get_performance_tracker()
                    tracker.record_trade(
                        trade_id=order.order_id,
                        symbol=symbol,
                        side='long' if position.side == PositionSide.LONG else 'short',
                        entry_price=position.entry_price,
                        exit_price=order.filled_price,
                        quantity=position.quantity,
                        entry_time=position.created_at,
                        exit_time=order.filled_at or time.time(),
                    )
                except Exception as e:
                    self._logger.warning(f"Failed to record trade analytics: {e}")
                
                del self._positions[symbol]
                self._total_exposure -= position.quantity * position.entry_price
                return
            
            new_quantity = position.quantity + order.filled_quantity
            new_entry = (
                (position.entry_price * position.quantity) +
                (order.filled_price * order.filled_quantity)
            ) / new_quantity
            
            position.quantity = new_quantity
            position.entry_price = new_entry
            position.updated_at = time.time()
            
        else:
            side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT
            
            position = Position(
                position_id=str(uuid.uuid4()),
                symbol=symbol,
                side=side,
                quantity=order.filled_quantity,
                entry_price=order.filled_price,
                current_price=order.filled_price,
                stop_loss=stop_loss or self._calculate_default_stop(
                    order.filled_price, side
                ),
                take_profit=take_profit or self._calculate_default_target(
                    order.filled_price, side
                ),
                metadata={
                    "strategy_id": order.metadata.get("strategy_id"),
                    "sentiment_score": order.metadata.get("sentiment_score"),
                    "portfolio_value": order.metadata.get("portfolio_value"),
                },
            )
            
            self._positions[symbol] = position
        
        self._total_exposure = sum(
            p.quantity * p.entry_price for p in self._positions.values()
        )
        self._update_equity()
    
    def _calculate_default_stop(
        self,
        entry_price: float,
        side: PositionSide,
    ) -> float:
        """Calculate default stop loss."""
        stop_distance = entry_price * self.config.default_stop_loss_pct
        
        if side == PositionSide.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
    
    def _calculate_default_target(
        self,
        entry_price: float,
        side: PositionSide,
    ) -> float:
        """Calculate default take profit."""
        target_distance = entry_price * self.config.default_take_profit_pct
        
        if side == PositionSide.LONG:
            return entry_price + target_distance
        else:
            return entry_price - target_distance
    
    def _update_equity(self) -> None:
        """Update equity based on positions."""
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        self._equity = self._balance + unrealized
    
    async def _position_monitor_loop(self) -> None:
        """Monitor positions for stop loss / take profit."""
        while self._running:
            try:
                for symbol, position in list(self._positions.items()):
                    current_price = self._price_cache.get(symbol)
                    if current_price is None:
                        continue
                    
                    if position.check_stop_loss(current_price):
                        self._logger.warning(
                            "Stop loss triggered for %s @ %.2f",
                            symbol, current_price
                        )
                        await self.close_position(symbol, reason="stop_loss")
                    
                    elif position.check_take_profit(current_price):
                        self._logger.info(
                            "Take profit triggered for %s @ %.2f",
                            symbol, current_price
                        )
                        await self.close_position(symbol, reason="take_profit")
                
                await asyncio.sleep(1.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Position monitor error: %s", e)
                await asyncio.sleep(5.0)
    
    def _emit_event(self, event: EventEnvelope) -> None:
        """Emit event to all registered callbacks."""
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                self._logger.error("Event callback error: %s", e)
    
    async def _heal_execution_engine(self, error: Exception) -> bool:
        """Self-healing strategy for execution engine."""
        self._logger.info(f"Attempting to heal execution engine after error: {error}")
        
        try:
            # Attempt to restore from last known good state
            state = await self._state_manager.get_state()
            if state:
                self._balance = state.get("balance", self._balance)
                self._equity = state.get("equity", self._equity)
                self._logger.info("State restored during healing")
            
            # Clear corrupted orders if any
            corrupted_orders = [
                oid for oid, order in self._orders.items()
                if order.status == OrderStatus.PENDING and 
                (time.time() - order.created_at) > 300  # 5 minutes old
            ]
            
            for oid in corrupted_orders:
                del self._orders[oid]
                self._logger.warning(f"Cleared stale order: {oid}")
            
            # Verify positions are valid
            for symbol, position in list(self._positions.items()):
                if position.quantity <= 0:
                    del self._positions[symbol]
                    self._logger.warning(f"Cleared invalid position: {symbol}")
            
            # Recalculate totals
            self._update_equity()
            
            self._logger.info("Execution engine healing completed successfully")
            return True
            
        except Exception as healing_error:
            self._logger.error(f"Healing failed: {healing_error}")
            return False


_execution_engine: Optional[ExecutionEngine] = None


def get_execution_engine() -> ExecutionEngine:
    """Get or create execution engine singleton."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine()
    return _execution_engine


async def start_execution_engine(
    config: Optional[ExecutionConfig] = None,
) -> ExecutionEngine:
    """Start the execution engine."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine(config)
    
    await _execution_engine.start()
    return _execution_engine


async def stop_execution_engine() -> None:
    """Stop the execution engine."""
    global _execution_engine
    if _execution_engine is not None:
        await _execution_engine.stop()
