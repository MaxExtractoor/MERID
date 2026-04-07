"""
MERID Automated Risk Controls
Enhanced risk management with automated controls, circuit breakers, and position limits
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import logging

from core.error_handling import get_error_handler, ErrorSeverity
from social.social_aware_quant import get_social_aware_quant_engine

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskControlType(Enum):
    """Types of risk controls"""
    POSITION_LIMIT = "position_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    VOLATILITY_LIMIT = "volatility_limit"
    CORRELATION_LIMIT = "correlation_limit"
    EXPOSURE_LIMIT = "exposure_limit"
    LEVERAGE_LIMIT = "leverage_limit"
    CONCENTRATION_LIMIT = "concentration_limit"


@dataclass
class RiskLimit:
    """Risk limit definition"""
    limit_type: RiskControlType
    threshold: float
    current_value: float = 0.0
    breached: bool = False
    breach_count: int = 0
    last_breach_time: Optional[float] = None
    action_on_breach: str = "alert"  # alert, block, reduce
    
    def check_breach(self, value: float) -> bool:
        """Check if limit is breached"""
        self.current_value = value
        
        if value > self.threshold:
            if not self.breached:
                self.breached = True
                self.breach_count += 1
                self.last_breach_time = time.time()
                logger.warning(
                    f"Risk limit breached: {self.limit_type.value} "
                    f"(current: {value:.4f}, threshold: {self.threshold:.4f})"
                )
            return True
        else:
            self.breached = False
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'limit_type': self.limit_type.value,
            'threshold': self.threshold,
            'current_value': self.current_value,
            'breached': self.breached,
            'breach_count': self.breach_count,
            'last_breach_time': self.last_breach_time,
            'action_on_breach': self.action_on_breach
        }


@dataclass
class PositionRisk:
    """Risk metrics for a position"""
    symbol: str
    position_size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    
    # Risk metrics
    volatility: float = 0.0
    var_95: float = 0.0  # Value at Risk 95%
    max_drawdown: float = 0.0
    correlation_to_portfolio: float = 0.0
    
    def calculate_risk_score(self) -> float:
        """Calculate overall risk score (0-100)"""
        # Weighted risk score
        volatility_score = min(self.volatility * 100, 100)
        drawdown_score = min(abs(self.max_drawdown) * 100, 100)
        var_score = min(abs(self.var_95) * 100, 100)
        
        risk_score = (
            volatility_score * 0.4 +
            drawdown_score * 0.4 +
            var_score * 0.2
        )
        
        return risk_score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'position_size': self.position_size,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'volatility': self.volatility,
            'var_95': self.var_95,
            'max_drawdown': self.max_drawdown,
            'correlation_to_portfolio': self.correlation_to_portfolio,
            'risk_score': self.calculate_risk_score()
        }


class PortfolioRiskManager:
    """Manages portfolio-level risk"""
    
    def __init__(
        self,
        max_portfolio_risk: float = 0.15,  # 15% max drawdown
        max_position_size: float = 0.10,  # 10% max per position
        max_leverage: float = 2.0,  # 2x max leverage
        max_correlation: float = 0.70  # 70% max correlation
    ):
        self.max_portfolio_risk = max_portfolio_risk
        self.max_position_size = max_position_size
        self.max_leverage = max_leverage
        self.max_correlation = max_correlation
        
        self.positions: Dict[str, PositionRisk] = {}
        self.risk_limits: List[RiskLimit] = []
        self.total_exposure: float = 0.0
        self.current_leverage: float = 1.0
        self.portfolio_value: float = 0.0
        
        self._initialize_risk_limits()
        
        logger.info("Portfolio risk manager initialized")
    
    def _initialize_risk_limits(self):
        """Initialize risk limits"""
        self.risk_limits = [
            RiskLimit(
                limit_type=RiskControlType.POSITION_LIMIT,
                threshold=self.max_position_size,
                action_on_breach="block"
            ),
            RiskLimit(
                limit_type=RiskControlType.DRAWDOWN_LIMIT,
                threshold=self.max_portfolio_risk,
                action_on_breach="reduce"
            ),
            RiskLimit(
                limit_type=RiskControlType.LEVERAGE_LIMIT,
                threshold=self.max_leverage,
                action_on_breach="block"
            ),
            RiskLimit(
                limit_type=RiskControlType.CORRELATION_LIMIT,
                threshold=self.max_correlation,
                action_on_breach="alert"
            )
        ]
    
    async def check_position_allowed(
        self,
        symbol: str,
        position_size: float,
        price: float,
        strategy_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check if position is allowed based on risk limits"""
        position_value = position_size * price
        position_pct = position_value / self.portfolio_value if self.portfolio_value > 0 else 0
        
        violations = []
        
        # Check position size limit
        if position_pct > self.max_position_size:
            violations.append({
                'type': 'position_size',
                'current': position_pct,
                'limit': self.max_position_size,
                'severity': 'CRITICAL'
            })
        
        # Check leverage limit
        new_exposure = self.total_exposure + position_value
        new_leverage = new_exposure / self.portfolio_value if self.portfolio_value > 0 else 0
        
        if new_leverage > self.max_leverage:
            violations.append({
                'type': 'leverage',
                'current': new_leverage,
                'limit': self.max_leverage,
                'severity': 'HIGH'
            })
        
        # Check social-specific constraints if this is a social strategy
        if strategy_id:
            try:
                social_engine = get_social_aware_quant_engine()
                if social_engine.is_social_asset(symbol):
                    constraints = social_engine.get_position_constraints(symbol)
                    
                    if constraints.get("kill_switch_active"):
                        violations.append({
                            'type': 'social_kill_switch',
                            'current': True,
                            'limit': False,
                            'severity': 'CRITICAL',
                            'reason': constraints.get("kill_switch_reason", "unknown")
                        })
                    
                    if not constraints.get("data_fresh", True):
                        violations.append({
                            'type': 'social_data_stale',
                            'current': True,
                            'limit': False,
                            'severity': 'HIGH',
                            'reason': 'Social data is stale for this asset'
                        })
            except Exception as e:
                logger.error(f"Social risk check failed: {e}")
        
        allowed = len(violations) == 0
        
        if not allowed:
            logger.warning(
                f"Position not allowed for {symbol}: {len(violations)} violations"
            )
        
        return {
            'allowed': allowed,
            'violations': violations,
            'position_size_pct': position_pct,
            'new_leverage': new_leverage
        }
    
    def add_position(self, position: PositionRisk):
        """Add position to risk tracking"""
        self.positions[position.symbol] = position
        self._update_portfolio_metrics()
        
        logger.info(f"Position added to risk tracking: {position.symbol}")
    
    def remove_position(self, symbol: str):
        """Remove position from risk tracking"""
        if symbol in self.positions:
            del self.positions[symbol]
            self._update_portfolio_metrics()
            logger.info(f"Position removed from risk tracking: {symbol}")
    
    def update_position(self, symbol: str, current_price: float):
        """Update position with current price"""
        if symbol in self.positions:
            position = self.positions[symbol]
            position.current_price = current_price
            position.unrealized_pnl = (
                (current_price - position.entry_price) * position.position_size
            )
            position.unrealized_pnl_pct = (
                (current_price - position.entry_price) / position.entry_price
            )
            
            self._update_portfolio_metrics()
    
    def _update_portfolio_metrics(self):
        """Update portfolio-level metrics"""
        self.total_exposure = sum(
            pos.position_size * pos.current_price
            for pos in self.positions.values()
        )
        
        if self.portfolio_value > 0:
            self.current_leverage = self.total_exposure / self.portfolio_value
    
    def get_portfolio_risk_report(self) -> Dict[str, Any]:
        """Get comprehensive portfolio risk report"""
        total_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        total_pnl_pct = total_pnl / self.portfolio_value if self.portfolio_value > 0 else 0
        
        # Calculate portfolio risk score
        position_risk_scores = [
            pos.calculate_risk_score() for pos in self.positions.values()
        ]
        avg_position_risk = (
            sum(position_risk_scores) / len(position_risk_scores)
            if position_risk_scores else 0
        )
        
        # Check all risk limits
        limit_status = []
        for limit in self.risk_limits:
            if limit.limit_type == RiskControlType.POSITION_LIMIT:
                max_position_pct = max(
                    (pos.position_size * pos.current_price / self.portfolio_value)
                    for pos in self.positions.values()
                ) if self.positions and self.portfolio_value > 0 else 0
                limit.check_breach(max_position_pct)
            
            elif limit.limit_type == RiskControlType.LEVERAGE_LIMIT:
                limit.check_breach(self.current_leverage)
            
            elif limit.limit_type == RiskControlType.DRAWDOWN_LIMIT:
                limit.check_breach(abs(total_pnl_pct))
            
            limit_status.append(limit.to_dict())
        
        return {
            'portfolio_value': self.portfolio_value,
            'total_exposure': self.total_exposure,
            'current_leverage': self.current_leverage,
            'total_positions': len(self.positions),
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'avg_position_risk': avg_position_risk,
            'risk_limits': limit_status,
            'positions': [pos.to_dict() for pos in self.positions.values()]
        }


class DynamicPositionSizer:
    """Dynamically sizes positions based on risk"""
    
    def __init__(
        self,
        base_risk_per_trade: float = 0.02,  # 2% risk per trade
        max_risk_per_trade: float = 0.05,  # 5% max risk
        volatility_adjustment: bool = True
    ):
        self.base_risk_per_trade = base_risk_per_trade
        self.max_risk_per_trade = max_risk_per_trade
        self.volatility_adjustment = volatility_adjustment
        
        logger.info("Dynamic position sizer initialized")
    
    def calculate_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss_price: float,
        volatility: Optional[float] = None,
        confidence: float = 1.0
    ) -> Dict[str, Any]:
        """Calculate optimal position size"""
        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss_price)
        
        if risk_per_unit == 0:
            return {
                'position_size': 0,
                'position_value': 0,
                'risk_amount': 0,
                'reason': 'Invalid stop loss (no risk per unit)'
            }
        
        # Adjust risk based on confidence
        adjusted_risk = self.base_risk_per_trade * confidence
        adjusted_risk = min(adjusted_risk, self.max_risk_per_trade)
        
        # Adjust for volatility if enabled
        if self.volatility_adjustment and volatility:
            # Reduce position size in high volatility
            volatility_factor = 1.0 / (1.0 + volatility)
            adjusted_risk *= volatility_factor
        
        # Calculate position size
        risk_amount = portfolio_value * adjusted_risk
        position_size = risk_amount / risk_per_unit
        position_value = position_size * entry_price
        
        return {
            'position_size': position_size,
            'position_value': position_value,
            'position_pct': position_value / portfolio_value,
            'risk_amount': risk_amount,
            'risk_pct': adjusted_risk,
            'risk_per_unit': risk_per_unit,
            'confidence_factor': confidence,
            'volatility_factor': 1.0 / (1.0 + volatility) if volatility else 1.0
        }


class AutomatedStopLossManager:
    """Manages automated stop losses and take profits"""
    
    def __init__(self):
        self.stop_losses: Dict[str, Dict[str, Any]] = {}
        self.take_profits: Dict[str, Dict[str, Any]] = {}
        self.trailing_stops: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Automated stop loss manager initialized")
    
    def set_stop_loss(
        self,
        symbol: str,
        stop_price: float,
        order_type: str = "market"
    ):
        """Set stop loss for position"""
        self.stop_losses[symbol] = {
            'stop_price': stop_price,
            'order_type': order_type,
            'set_at': time.time()
        }
        
        logger.info(f"Stop loss set for {symbol} at {stop_price}")
    
    def set_take_profit(
        self,
        symbol: str,
        target_price: float,
        order_type: str = "limit"
    ):
        """Set take profit for position"""
        self.take_profits[symbol] = {
            'target_price': target_price,
            'order_type': order_type,
            'set_at': time.time()
        }
        
        logger.info(f"Take profit set for {symbol} at {target_price}")
    
    def set_trailing_stop(
        self,
        symbol: str,
        trail_amount: float,
        trail_percent: Optional[float] = None
    ):
        """Set trailing stop for position"""
        self.trailing_stops[symbol] = {
            'trail_amount': trail_amount,
            'trail_percent': trail_percent,
            'highest_price': 0.0,
            'current_stop': 0.0,
            'set_at': time.time()
        }
        
        logger.info(f"Trailing stop set for {symbol}")
    
    def update_trailing_stop(self, symbol: str, current_price: float) -> Optional[float]:
        """Update trailing stop based on current price"""
        if symbol not in self.trailing_stops:
            return None
        
        trail = self.trailing_stops[symbol]
        
        # Update highest price
        if current_price > trail['highest_price']:
            trail['highest_price'] = current_price
        
        # Calculate new stop price
        if trail['trail_percent']:
            new_stop = trail['highest_price'] * (1 - trail['trail_percent'])
        else:
            new_stop = trail['highest_price'] - trail['trail_amount']
        
        # Update stop if it's higher than current
        if new_stop > trail['current_stop']:
            trail['current_stop'] = new_stop
            logger.info(f"Trailing stop updated for {symbol}: {new_stop}")
        
        return trail['current_stop']
    
    def check_stops(
        self,
        symbol: str,
        current_price: float
    ) -> Dict[str, Any]:
        """Check if any stops are triggered"""
        triggered = []
        
        # Check stop loss
        if symbol in self.stop_losses:
            stop = self.stop_losses[symbol]
            if current_price <= stop['stop_price']:
                triggered.append({
                    'type': 'stop_loss',
                    'trigger_price': stop['stop_price'],
                    'current_price': current_price
                })
        
        # Check take profit
        if symbol in self.take_profits:
            tp = self.take_profits[symbol]
            if current_price >= tp['target_price']:
                triggered.append({
                    'type': 'take_profit',
                    'trigger_price': tp['target_price'],
                    'current_price': current_price
                })
        
        # Check trailing stop
        if symbol in self.trailing_stops:
            trail_stop = self.update_trailing_stop(symbol, current_price)
            if trail_stop and current_price <= trail_stop:
                triggered.append({
                    'type': 'trailing_stop',
                    'trigger_price': trail_stop,
                    'current_price': current_price
                })
        
        return {
            'symbol': symbol,
            'current_price': current_price,
            'triggered': triggered,
            'should_exit': len(triggered) > 0
        }


class TradingHaltManager:
    """Manages trading halt state triggered by risk breaches or circuit breakers.

    This is the central authority for whether new orders can be submitted.
    When halted, all order submission must be blocked until an operator
    explicitly resumes or the auto-resume conditions are met.

    Supports reason-specific halts so that staleness-triggered halts can be
    auto-cleared when feeds recover, while operator/kill-switch halts remain manual.
    """

    def __init__(
        self,
        max_daily_loss_pct: float = 0.05,
        max_drawdown_pct: float = 0.15,
        circuit_breaker_halt_threshold: int = 2,
    ):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.circuit_breaker_halt_threshold = circuit_breaker_halt_threshold

        self._halted: bool = False
        self._halt_reasons: Dict[str, float] = {}  # reason -> timestamp
        self._halt_time: Optional[float] = None
        self._halt_history: List[Dict[str, Any]] = []
        self._on_halt_callbacks: List[Callable] = []
        self._on_resume_callbacks: List[Callable] = []

    @property
    def is_halted(self) -> bool:
        return len(self._halt_reasons) > 0

    @property
    def halt_reason(self) -> Optional[str]:
        if not self._halt_reasons:
            return None
        # Return most recent halt reason
        sorted_reasons = sorted(self._halt_reasons.items(), key=lambda x: x[1], reverse=True)
        return sorted_reasons[0][0] if sorted_reasons else None

    def register_on_halt(self, callback: Callable) -> None:
        """Register a callback invoked when trading is halted."""
        self._on_halt_callbacks.append(callback)

    def register_on_resume(self, callback: Callable) -> None:
        """Register a callback invoked when trading is resumed."""
        self._on_resume_callbacks.append(callback)

    def halt(self, reason: str, operator: str = "system") -> bool:
        """Halt all trading.  Returns True if a new reason was added."""
        if reason in self._halt_reasons:
            logger.debug(f"Trading already halted for reason '{reason}'")
            return False

        self._halt_reasons[reason] = time.time()
        if not self._halt_time:
            self._halt_time = time.time()

        entry = {
            "action": "halt",
            "reason": reason,
            "operator": operator,
            "timestamp": time.time(),
        }
        self._halt_history.append(entry)
        logger.critical(f"TRADING HALTED: {reason} (by {operator})")

        # Only fire callbacks on first halt
        if len(self._halt_reasons) == 1:
            for cb in self._on_halt_callbacks:
                try:
                    cb(reason)
                except Exception as exc:
                    logger.error(f"on_halt callback error: {exc}")
        return True

    def clear_reason(self, reason: str, operator: str = "system") -> bool:
        """Clear a specific halt reason.  Returns True if state changed."""
        if reason not in self._halt_reasons:
            return False

        del self._halt_reasons[reason]
        entry = {
            "action": "clear_reason",
            "reason": reason,
            "operator": operator,
            "timestamp": time.time(),
        }
        self._halt_history.append(entry)
        logger.info(f"TRADING HALT CLEARED for reason: {reason} (by {operator})")

        # Fire resume callbacks if all halts cleared
        if len(self._halt_reasons) == 0:
            self._halt_time = None
            for cb in self._on_resume_callbacks:
                try:
                    cb(operator)
                except Exception as exc:
                    logger.error(f"on_resume callback error: {exc}")
        return True

    def resume(self, operator: str = "system") -> bool:
        """Resume trading (clear ALL halt reasons).  Returns True if state changed."""
        if not self._halt_reasons:
            return False

        prev_reasons = list(self._halt_reasons.keys())
        self._halt_reasons.clear()
        self._halt_time = None
        entry = {
            "action": "resume",
            "previous_reasons": prev_reasons,
            "resumed_by": operator,
            "timestamp": time.time(),
        }
        self._halt_history.append(entry)
        logger.info(f"TRADING RESUMED by {operator} (was halted: {', '.join(prev_reasons)})")

        for cb in self._on_resume_callbacks:
            try:
                cb(operator)
            except Exception as exc:
                logger.error(f"on_resume callback error: {exc}")
        return True

    def check_daily_loss(self, daily_pnl: float, portfolio_value: float) -> bool:
        """Check daily loss and halt if threshold breached.  Returns True if halted."""
        if portfolio_value <= 0:
            return False
        loss_pct = abs(daily_pnl) / portfolio_value if daily_pnl < 0 else 0
        if loss_pct >= self.max_daily_loss_pct:
            self.halt(
                f"Daily loss {loss_pct:.1%} exceeds limit {self.max_daily_loss_pct:.1%} "
                f"(${daily_pnl:.2f} on ${portfolio_value:.2f})"
            )
            return True
        return False

    def check_drawdown(self, current_drawdown_pct: float) -> bool:
        """Check drawdown and halt if threshold breached.  Returns True if halted."""
        if current_drawdown_pct >= self.max_drawdown_pct:
            self.halt(
                f"Drawdown {current_drawdown_pct:.1%} exceeds limit {self.max_drawdown_pct:.1%}"
            )
            return True
        return False

    def check_circuit_breakers(self, open_breaker_count: int) -> bool:
        """Halt if too many circuit breakers are open.  Returns True if halted."""
        if open_breaker_count >= self.circuit_breaker_halt_threshold:
            self.halt(
                f"{open_breaker_count} circuit breakers open "
                f"(threshold {self.circuit_breaker_halt_threshold})"
            )
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "halted": self.is_halted,
            "reasons": list(self._halt_reasons.keys()),
            "reason": self.halt_reason,
            "halt_time": self._halt_time,
            "history_count": len(self._halt_history),
            "history": self._halt_history[-10:],
            "limits": {
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_drawdown_pct": self.max_drawdown_pct,
                "circuit_breaker_halt_threshold": self.circuit_breaker_halt_threshold,
            },
        }


class RiskControlCoordinator:
    """Coordinates all risk control systems"""
    
    def __init__(self):
        self.portfolio_manager = PortfolioRiskManager()
        self.position_sizer = DynamicPositionSizer()
        self.stop_loss_manager = AutomatedStopLossManager()
        self.halt_manager = TradingHaltManager()
        self.error_handler = get_error_handler()
        self.staleness_monitor = None  # Set via wire_staleness_monitor()
        
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._circuit_breakers: Dict[str, Any] = {}
        
        logger.info("Risk control coordinator initialized")

    def wire_staleness_monitor(self, monitor) -> None:
        """Wire a FeedStalenessMonitor so stale feeds auto-halt trading."""
        self.staleness_monitor = monitor

        def on_stale_callback(feed_id: str, instrument: str, age: float) -> None:
            reason = f"feed_stale:{feed_id}:{instrument}"
            self.halt_manager.halt(reason=reason, operator="staleness_monitor")

        def on_recovered_callback(feed_id: str, instrument: str) -> None:
            reason = f"feed_stale:{feed_id}:{instrument}"
            self.halt_manager.clear_reason(reason=reason, operator="staleness_monitor")

        monitor.on_stale(on_stale_callback)
        monitor.on_recovered(on_recovered_callback)
        logger.info("Staleness monitor wired to risk coordinator with auto-resume")

    def register_circuit_breaker(self, name_or_breaker: Any, breaker: Any = None) -> None:
        """Register an external circuit breaker for monitoring.

        Accepts either (name, breaker) or just (breaker,) where breaker.name is used.
        """
        if breaker is None:
            # Single-arg form: register_circuit_breaker(breaker)
            breaker = name_or_breaker
            name = getattr(breaker, "name", str(id(breaker)))
        else:
            name = name_or_breaker
        self._circuit_breakers[name] = breaker
        logger.info(f"Circuit breaker registered: {name}")

    def can_trade(self) -> bool:
        """Central gate: returns False if trading is halted."""
        return not self.halt_manager.is_halted
    
    async def start_monitoring(self, interval: float = 1.0):
        """Start risk monitoring"""
        self._monitoring = True
        
        async def monitor_loop():
            while self._monitoring:
                try:
                    await self._check_all_risks()
                    await asyncio.sleep(interval)
                except Exception as e:
                    logger.error(f"Risk monitoring error: {e}")
                    await asyncio.sleep(interval)
        
        self._monitor_task = asyncio.create_task(monitor_loop())
        logger.info("Risk monitoring started")
    
    async def stop_monitoring(self):
        """Stop risk monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Risk monitoring stopped")
    
    async def _check_all_risks(self):
        """Check all risk controls and auto-halt on critical breaches."""
        risk_report = self.portfolio_manager.get_portfolio_risk_report()
        
        # --- Drawdown auto-halt ---
        drawdown_pct = abs(risk_report.get('total_pnl_pct', 0))
        self.halt_manager.check_drawdown(drawdown_pct)

        # --- Circuit breaker auto-halt ---
        open_count = 0
        for name, breaker in self._circuit_breakers.items():
            state = breaker.get_state() if hasattr(breaker, 'get_state') else {}
            if state.get('state') == 'open':
                open_count += 1
        self.halt_manager.check_circuit_breakers(open_count)

        # --- Feed staleness auto-halt ---
        if self.staleness_monitor is not None:
            self.staleness_monitor.check_all()

        # --- Anomaly detection auto-halt ---
        try:
            from ops.anomaly_detection import get_anomaly_detection
            anomaly_stack = get_anomaly_detection()
            should_halt, reason = anomaly_stack.should_halt()
            if should_halt:
                self.halt_manager.halt(f"Anomaly detection: {reason}")
        except ImportError:
            pass  # anomaly detection module not available
        except Exception as exc:
            logger.debug(f"Anomaly detection check error: {exc}")

        # --- Legacy: critical violation → error handler ---
        critical_violations = [
            limit for limit in risk_report['risk_limits']
            if limit['breached'] and limit['action_on_breach'] == 'block'
        ]
        
        if critical_violations:
            await self.error_handler.handle_error(
                Exception(f"Critical risk violations: {len(critical_violations)}"),
                "risk_control",
                "risk_monitoring",
                ErrorSeverity.CRITICAL
            )
    
    def get_comprehensive_risk_status(self) -> Dict[str, Any]:
        """Get comprehensive risk status"""
        return {
            'portfolio_risk': self.portfolio_manager.get_portfolio_risk_report(),
            'active_stops': {
                'stop_losses': len(self.stop_loss_manager.stop_losses),
                'take_profits': len(self.stop_loss_manager.take_profits),
                'trailing_stops': len(self.stop_loss_manager.trailing_stops)
            },
            'monitoring_active': self._monitoring,
            'trading_halt': self.halt_manager.get_status(),
            'can_trade': self.can_trade(),
            'staleness': self.staleness_monitor.get_summary() if self.staleness_monitor else {},
        }


# Global risk control coordinator
_risk_coordinator: Optional[RiskControlCoordinator] = None


def get_risk_coordinator() -> RiskControlCoordinator:
    """Get global risk control coordinator"""
    global _risk_coordinator
    if _risk_coordinator is None:
        _risk_coordinator = RiskControlCoordinator()
    return _risk_coordinator
