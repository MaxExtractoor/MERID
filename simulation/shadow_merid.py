"""
Shadow MERID - Simulation-only parallel instance per MERID Four-System Architecture

This module implements a shadow instance of MERID that:
- Runs in parallel with production
- Executes all intents in simulation mode
- Never touches real capital
- Provides comparison metrics for validation

Shadow MERID is the "what would have happened" oracle.
It turns catastrophic mistakes into recoverable lessons.
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any

from contracts.intents import Intent, IntentStatus, IntentType, SimulationResult
from contracts.system_contracts import SystemID
from utils.logger import get_logger

logger = get_logger("simulation.shadow")


class ShadowMode(Enum):
    """Shadow execution modes."""
    PASSIVE = "passive"
    ACTIVE = "active"
    REPLAY = "replay"


@dataclass
class ShadowPosition:
    """Simulated position in shadow portfolio."""
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)


@dataclass
class ShadowPortfolio:
    """Shadow portfolio state."""
    balance: float = 100000.0
    equity: float = 100000.0
    positions: Dict[str, ShadowPosition] = field(default_factory=dict)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 100000.0
    
    def update_equity(self) -> None:
        """Update equity based on positions."""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        self.equity = self.balance + unrealized
        self.peak_equity = max(self.peak_equity, self.equity)
        drawdown = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0
        self.max_drawdown = max(self.max_drawdown, drawdown)


@dataclass
class ShadowExecution:
    """Record of a shadow execution."""
    execution_id: str
    intent_id: str
    intent_type: IntentType
    source_system: SystemID
    
    simulated_at: float = field(default_factory=time.time)
    
    action: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    simulation_result: Optional[SimulationResult] = None
    
    portfolio_before: Optional[Dict[str, Any]] = None
    portfolio_after: Optional[Dict[str, Any]] = None
    
    production_executed: bool = False
    production_result: Optional[Dict[str, Any]] = None
    
    divergence_detected: bool = False
    divergence_details: Optional[str] = None


@dataclass
class ShadowConfig:
    """Configuration for shadow MERID."""
    
    mode: ShadowMode = ShadowMode.PASSIVE
    
    initial_balance: float = 100000.0
    
    slippage_model: str = "realistic"
    slippage_bps: float = 5.0
    
    latency_model: str = "realistic"
    latency_ms: float = 50.0
    
    track_divergence: bool = True
    divergence_threshold_pct: float = 0.05
    
    max_execution_history: int = 1000
    
    sync_prices_from_production: bool = True


class ShadowMERID:
    """
    Shadow instance of MERID for simulation.
    
    Capabilities:
    - Mirror all production intents
    - Execute in simulation mode
    - Track hypothetical portfolio
    - Detect divergence from production
    - Enable deterministic replay
    
    This is the safety net that makes mistakes survivable.
    """
    
    def __init__(self, config: Optional[ShadowConfig] = None) -> None:
        """
        Initialize shadow MERID.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or ShadowConfig()
        
        self._portfolio = ShadowPortfolio(
            balance=self.config.initial_balance,
            equity=self.config.initial_balance,
            peak_equity=self.config.initial_balance,
        )
        
        self._price_cache: Dict[str, float] = {}
        
        self._execution_history: List[ShadowExecution] = []
        self._intent_queue: asyncio.Queue[Intent] = asyncio.Queue()
        
        self._running = False
        self._process_task: Optional[asyncio.Task[None]] = None
        
        self._divergence_callbacks: List[Callable[[ShadowExecution], None]] = []
        
        self._logger = get_logger("simulation.shadow.merid")
    
    async def start(self) -> None:
        """Start shadow MERID processing."""
        if self._running:
            return
        
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        
        self._logger.info(
            "Shadow MERID started: mode=%s, balance=$%.0f",
            self.config.mode.value, self._portfolio.balance
        )
    
    async def stop(self) -> None:
        """Stop shadow MERID."""
        self._running = False
        
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        
        self._logger.info("Shadow MERID stopped")
    
    def update_price(self, symbol: str, price: float) -> None:
        """
        Update price cache (synced from production).
        
        Args:
            symbol: Trading symbol
            price: Current price
        """
        self._price_cache[symbol] = price
        
        if symbol in self._portfolio.positions:
            position = self._portfolio.positions[symbol]
            position.current_price = price
            
            if position.side == "long":
                position.unrealized_pnl = (price - position.entry_price) * position.quantity
            else:
                position.unrealized_pnl = (position.entry_price - price) * position.quantity
        
        self._portfolio.update_equity()
    
    async def mirror_intent(self, intent: Intent) -> ShadowExecution:
        """
        Mirror a production intent in shadow mode.
        
        Args:
            intent: Intent from production
            
        Returns:
            Shadow execution record
        """
        execution = ShadowExecution(
            execution_id=f"shadow_{int(time.time() * 1000)}",
            intent_id=intent.intent_id,
            intent_type=intent.intent_type,
            source_system=intent.source_system,
            action=intent.payload.action,
            parameters=dict(intent.payload.parameters),
            portfolio_before=self._snapshot_portfolio(),
        )
        
        simulation = await self._simulate_intent(intent)
        execution.simulation_result = simulation
        
        if simulation.success:
            self._apply_simulation(intent, simulation)
        
        execution.portfolio_after = self._snapshot_portfolio()
        
        self._execution_history.append(execution)
        if len(self._execution_history) > self.config.max_execution_history:
            self._execution_history = self._execution_history[-self.config.max_execution_history:]
        
        self._logger.debug(
            "Shadow execution: %s %s -> success=%s",
            intent.intent_type.value, intent.intent_id[:8], simulation.success
        )
        
        return execution
    
    def record_production_result(
        self,
        intent_id: str,
        executed: bool,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record production result for divergence tracking.
        
        Args:
            intent_id: Intent that was executed
            executed: Whether it was executed in production
            result: Production execution result
        """
        for execution in reversed(self._execution_history):
            if execution.intent_id == intent_id:
                execution.production_executed = executed
                execution.production_result = result
                
                if self.config.track_divergence:
                    self._check_divergence(execution)
                
                break
    
    async def replay_window(
        self,
        start_time: float,
        end_time: float,
    ) -> List[ShadowExecution]:
        """
        Replay a time window of executions.
        
        Args:
            start_time: Window start timestamp
            end_time: Window end timestamp
            
        Returns:
            List of replayed executions
        """
        executions = [
            e for e in self._execution_history
            if start_time <= e.simulated_at <= end_time
        ]
        
        self._logger.info(
            "Replaying %d executions from %s to %s",
            len(executions),
            time.ctime(start_time),
            time.ctime(end_time),
        )
        
        return executions
    
    def get_portfolio(self) -> ShadowPortfolio:
        """Get current shadow portfolio state."""
        return self._portfolio
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get shadow performance metrics."""
        total_trades = self._portfolio.total_trades
        win_rate = (
            self._portfolio.winning_trades / total_trades
            if total_trades > 0 else 0.0
        )
        
        return {
            "balance": self._portfolio.balance,
            "equity": self._portfolio.equity,
            "total_pnl": self._portfolio.total_pnl,
            "total_trades": total_trades,
            "winning_trades": self._portfolio.winning_trades,
            "losing_trades": self._portfolio.losing_trades,
            "win_rate": win_rate,
            "max_drawdown": self._portfolio.max_drawdown,
            "open_positions": len(self._portfolio.positions),
            "execution_count": len(self._execution_history),
        }
    
    def get_divergence_report(self) -> Dict[str, Any]:
        """Get divergence report between shadow and production."""
        divergent = [e for e in self._execution_history if e.divergence_detected]
        
        return {
            "total_executions": len(self._execution_history),
            "divergent_executions": len(divergent),
            "divergence_rate": len(divergent) / max(len(self._execution_history), 1),
            "recent_divergences": [
                {
                    "intent_id": e.intent_id,
                    "intent_type": e.intent_type.value,
                    "details": e.divergence_details,
                    "timestamp": e.simulated_at,
                }
                for e in divergent[-10:]
            ],
        }
    
    def register_divergence_callback(
        self,
        callback: Callable[[ShadowExecution], None],
    ) -> None:
        """Register callback for divergence detection."""
        self._divergence_callbacks.append(callback)
    
    def reset(self) -> None:
        """Reset shadow state to initial."""
        self._portfolio = ShadowPortfolio(
            balance=self.config.initial_balance,
            equity=self.config.initial_balance,
            peak_equity=self.config.initial_balance,
        )
        self._execution_history.clear()
        self._logger.info("Shadow MERID reset")
    
    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                intent = await asyncio.wait_for(
                    self._intent_queue.get(),
                    timeout=1.0,
                )
                await self.mirror_intent(intent)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Shadow processing error: %s", e)
    
    async def _simulate_intent(self, intent: Intent) -> SimulationResult:
        """Simulate an intent execution."""
        await asyncio.sleep(self.config.latency_ms / 1000)
        
        warnings: List[str] = []
        side_effects: List[str] = []
        risk_score = 0.3
        
        if intent.intent_type in (IntentType.TRADE, IntentType.HEDGE):
            symbol = intent.payload.symbol
            amount = intent.payload.amount_usd or 0
            
            if symbol and symbol not in self._price_cache:
                warnings.append(f"No price data for {symbol}")
                risk_score += 0.2
            
            if amount > self._portfolio.balance * 0.2:
                warnings.append("Position size exceeds 20% of portfolio")
                risk_score += 0.2
            
            side_effects.append(f"Would open position in {symbol}")
        
        elif intent.intent_type == IntentType.ALLOCATE:
            amount = intent.payload.amount_usd or 0
            if amount > self._portfolio.balance * 0.5:
                warnings.append("Allocation exceeds 50% of balance")
                risk_score += 0.3
        
        return SimulationResult(
            success=risk_score < 0.8,
            predicted_outcome={
                "intent_type": intent.intent_type.value,
                "simulated": True,
            },
            risk_score=min(risk_score, 1.0),
            warnings=warnings,
            estimated_cost_usd=intent.payload.amount_usd or 0,
            estimated_duration_ms=self.config.latency_ms,
            side_effects=side_effects,
        )
    
    def _apply_simulation(self, intent: Intent, simulation: SimulationResult) -> None:
        """Apply simulation result to shadow portfolio."""
        if intent.intent_type in (IntentType.TRADE, IntentType.HEDGE):
            symbol = intent.payload.symbol
            amount = intent.payload.amount_usd or 0
            
            if not symbol:
                return
            
            price = self._price_cache.get(symbol, 100.0)
            slippage = price * (self.config.slippage_bps / 10000)
            
            action = intent.payload.action
            if action in ("buy", "long"):
                fill_price = price + slippage
                side = "long"
            else:
                fill_price = price - slippage
                side = "short"
            
            quantity = amount / fill_price if fill_price > 0 else 0
            
            if symbol in self._portfolio.positions:
                position = self._portfolio.positions[symbol]
                if position.side == side:
                    total_cost = (position.entry_price * position.quantity) + (fill_price * quantity)
                    position.quantity += quantity
                    position.entry_price = total_cost / position.quantity if position.quantity > 0 else 0
                else:
                    pnl = position.unrealized_pnl
                    self._portfolio.balance += pnl
                    self._portfolio.total_pnl += pnl
                    self._portfolio.total_trades += 1
                    if pnl > 0:
                        self._portfolio.winning_trades += 1
                    else:
                        self._portfolio.losing_trades += 1
                    del self._portfolio.positions[symbol]
            else:
                self._portfolio.positions[symbol] = ShadowPosition(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=fill_price,
                    current_price=price,
                )
            
            self._portfolio.update_equity()
        
        elif intent.intent_type == IntentType.CLOSE_POSITION:
            symbol = intent.payload.symbol
            if symbol and symbol in self._portfolio.positions:
                position = self._portfolio.positions[symbol]
                pnl = position.unrealized_pnl
                self._portfolio.balance += pnl
                self._portfolio.total_pnl += pnl
                self._portfolio.total_trades += 1
                if pnl > 0:
                    self._portfolio.winning_trades += 1
                else:
                    self._portfolio.losing_trades += 1
                del self._portfolio.positions[symbol]
                self._portfolio.update_equity()
    
    def _snapshot_portfolio(self) -> Dict[str, Any]:
        """Create snapshot of current portfolio state."""
        return {
            "balance": self._portfolio.balance,
            "equity": self._portfolio.equity,
            "positions": len(self._portfolio.positions),
            "total_pnl": self._portfolio.total_pnl,
            "timestamp": time.time(),
        }
    
    def _check_divergence(self, execution: ShadowExecution) -> None:
        """Check for divergence between shadow and production."""
        if not execution.production_result:
            return
        
        shadow_pnl = (
            execution.portfolio_after.get("total_pnl", 0) -
            execution.portfolio_before.get("total_pnl", 0)
            if execution.portfolio_after and execution.portfolio_before
            else 0
        )
        
        production_pnl = execution.production_result.get("pnl", 0)
        
        if shadow_pnl != 0:
            divergence_pct = abs(shadow_pnl - production_pnl) / abs(shadow_pnl)
        else:
            divergence_pct = abs(production_pnl)
        
        if divergence_pct > self.config.divergence_threshold_pct:
            execution.divergence_detected = True
            execution.divergence_details = (
                f"PnL divergence: shadow=${shadow_pnl:.2f}, "
                f"production=${production_pnl:.2f} ({divergence_pct:.1%})"
            )
            
            self._logger.warning(
                "Divergence detected: %s",
                execution.divergence_details
            )
            
            for callback in self._divergence_callbacks:
                try:
                    callback(execution)
                except Exception as e:
                    self._logger.error("Divergence callback error: %s", e)


_shadow_merid: Optional[ShadowMERID] = None


def get_shadow_merid() -> ShadowMERID:
    """Get or create global shadow MERID."""
    global _shadow_merid
    if _shadow_merid is None:
        _shadow_merid = ShadowMERID()
    return _shadow_merid


async def start_shadow_merid(config: Optional[ShadowConfig] = None) -> ShadowMERID:
    """Start shadow MERID."""
    global _shadow_merid
    if _shadow_merid is None:
        _shadow_merid = ShadowMERID(config)
    await _shadow_merid.start()
    return _shadow_merid


async def stop_shadow_merid() -> None:
    """Stop shadow MERID."""
    global _shadow_merid
    if _shadow_merid is not None:
        await _shadow_merid.stop()
