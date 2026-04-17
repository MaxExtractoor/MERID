"""
Sniper Engine for MERID - Latency-Sensitive Arbitrage
Low-latency architecture with strict risk controls and performance tracking.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.sniper_engine")


class SniperMode(Enum):
    """Sniper operating modes."""
    DISABLED = "disabled"
    MONITORING = "monitoring"
    ACTIVE = "active"
    AGGRESSIVE = "aggressive"


class OpportunityType(Enum):
    """Types of arbitrage opportunities."""
    CEX_CEX = "cex_cex"
    CEX_DEX = "cex_dex"
    DEX_DEX = "dex_dex"
    CROSS_CHAIN = "cross_chain"
    FUNDING_RATE = "funding_rate"


@dataclass
class SniperOpportunity:
    """Arbitrage opportunity."""
    opportunity_id: str
    opportunity_type: OpportunityType
    symbol: str
    buy_venue: str
    sell_venue: str
    buy_price: float
    sell_price: float
    gap_bps: float
    expected_profit: float
    estimated_slippage: float
    estimated_fees: float
    net_profit: float
    confidence: float
    timestamp: float


@dataclass
class SniperExecution:
    """Sniper execution record."""
    execution_id: str
    opportunity: SniperOpportunity
    executed: bool
    buy_tx_hash: Optional[str]
    sell_tx_hash: Optional[str]
    actual_profit: float
    latency_ms: Dict[str, float]
    timestamp: float


@dataclass
class LatencyBudget:
    """Latency budget per segment."""
    feed_latency_ms: float
    decision_latency_ms: float
    risk_check_latency_ms: float
    signing_latency_ms: float
    submission_latency_ms: float
    confirmation_latency_ms: float
    total_budget_ms: float


class SniperRiskControls:
    """Risk controls for sniper operations."""
    
    def __init__(self):
        # Exposure limits
        self.max_position_size_usd = 10000.0
        self.max_daily_volume_usd = 50000.0
        self.max_open_positions = 5
        self.daily_loss_limit_usd = 5000.0
        
        # Gap thresholds (accounting for slippage and fees)
        self.min_gap_bps = 20.0  # 0.20%
        self.min_net_profit_usd = 10.0
        
        # Timing fail-safes
        self.cancel_if_not_filled_ms = 5000.0
        self.max_leg_imbalance_seconds = 30.0
        
        # Circuit breakers
        self.max_consecutive_losses = 5
        self.max_latency_spike_ms = 1000.0
        self.max_reject_rate = 0.3
        
        # Current state
        self._daily_volume = 0.0
        self._daily_loss = 0.0
        self._open_positions = 0
        self._consecutive_losses = 0
        self._last_reset = time.time()
    
    def check_opportunity(self, opportunity: SniperOpportunity) -> tuple[bool, str]:
        """Check if opportunity passes risk controls."""
        self._reset_daily_if_needed()
        
        # Check gap threshold
        if opportunity.gap_bps < self.min_gap_bps:
            return False, f"Gap {opportunity.gap_bps:.2f}bps below threshold {self.min_gap_bps:.2f}bps"
        
        # Check net profit
        if opportunity.net_profit < self.min_net_profit_usd:
            return False, f"Net profit ${opportunity.net_profit:.2f} below threshold ${self.min_net_profit_usd}"
        
        # Check position size
        position_size = opportunity.expected_profit / (opportunity.gap_bps / 10000)
        if position_size > self.max_position_size_usd:
            return False, f"Position size ${position_size:.2f} exceeds limit ${self.max_position_size_usd}"
        
        # Check daily volume
        if self._daily_volume + position_size > self.max_daily_volume_usd:
            return False, f"Daily volume limit reached: ${self.max_daily_volume_usd}"
        
        # Check daily loss
        if self._daily_loss >= self.daily_loss_limit_usd:
            return False, f"Daily loss limit reached: ${self.daily_loss_limit_usd}"
        
        # Check open positions
        if self._open_positions >= self.max_open_positions:
            return False, f"Max open positions reached: {self.max_open_positions}"
        
        # Check consecutive losses
        if self._consecutive_losses >= self.max_consecutive_losses:
            return False, f"Max consecutive losses reached: {self.max_consecutive_losses}"
        
        return True, "Opportunity approved"
    
    def record_execution(self, execution: SniperExecution) -> None:
        """Record execution result."""
        if execution.executed:
            self._daily_volume += abs(execution.actual_profit)
            
            if execution.actual_profit < 0:
                self._daily_loss += abs(execution.actual_profit)
                self._consecutive_losses += 1
            else:
                self._consecutive_losses = 0
    
    def _reset_daily_if_needed(self) -> None:
        """Reset daily counters if day changed."""
        if time.time() - self._last_reset > 86400:
            self._daily_volume = 0.0
            self._daily_loss = 0.0
            self._consecutive_losses = 0
            self._last_reset = time.time()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get risk control statistics."""
        return {
            "daily_volume": self._daily_volume,
            "daily_loss": self._daily_loss,
            "open_positions": self._open_positions,
            "consecutive_losses": self._consecutive_losses,
            "limits": {
                "max_position_size": self.max_position_size_usd,
                "max_daily_volume": self.max_daily_volume_usd,
                "daily_loss_limit": self.daily_loss_limit_usd
            }
        }


class SniperEngine:
    """Main sniper engine with hot path optimization."""
    
    def __init__(self):
        self.mode = SniperMode.MONITORING
        self._risk_controls = SniperRiskControls()
        
        # Latency budget
        self._latency_budget = LatencyBudget(
            feed_latency_ms=10.0,
            decision_latency_ms=5.0,
            risk_check_latency_ms=2.0,
            signing_latency_ms=5.0,
            submission_latency_ms=50.0,
            confirmation_latency_ms=500.0,
            total_budget_ms=572.0
        )
        
        # Performance tracking
        self._executions: List[SniperExecution] = []
        self._opportunities_seen = 0
        self._opportunities_executed = 0
    
    async def detect_opportunity(
        self,
        symbol: str,
        venues: List[str]
    ) -> Optional[SniperOpportunity]:
        """Detect arbitrage opportunity (hot path)."""
        start_time = time.time()
        
        # In production:
        # 1. Get prices from all venues (pre-loaded in memory)
        # 2. Calculate gaps
        # 3. Estimate slippage and fees
        # 4. Return best opportunity
        
        # Simulated opportunity
        opportunity = SniperOpportunity(
            opportunity_id=f"opp_{int(time.time() * 1000)}",
            opportunity_type=OpportunityType.CEX_DEX,
            symbol=symbol,
            buy_venue="binance",
            sell_venue="uniswap",
            buy_price=100.0,
            sell_price=100.25,
            gap_bps=25.0,
            expected_profit=25.0,
            estimated_slippage=5.0,
            estimated_fees=5.0,
            net_profit=15.0,
            confidence=0.85,
            timestamp=time.time()
        )
        
        latency_ms = (time.time() - start_time) * 1000
        
        if latency_ms > self._latency_budget.feed_latency_ms:
            logger.warning(f"Feed latency {latency_ms:.2f}ms exceeds budget {self._latency_budget.feed_latency_ms:.2f}ms")
        
        self._opportunities_seen += 1
        
        return opportunity
    
    async def execute_opportunity(
        self,
        opportunity: SniperOpportunity
    ) -> Optional[SniperExecution]:
        """Execute arbitrage opportunity (hot path)."""
        if self.mode == SniperMode.DISABLED:
            return None
        
        start_time = time.time()
        latency_tracker = {}
        
        # Risk check
        risk_start = time.time()
        allowed, reason = self._risk_controls.check_opportunity(opportunity)
        latency_tracker["risk_check"] = (time.time() - risk_start) * 1000
        
        if not allowed:
            logger.info(f"Opportunity rejected: {reason}")
            return None
        
        if self.mode == SniperMode.MONITORING:
            logger.info(f"Monitoring mode: would execute {opportunity.opportunity_id}")
            return None
        
        # Execute (hot path)
        # 1. Build transactions (pre-templated)
        # 2. Sign transactions
        # 3. Submit simultaneously
        # 4. Monitor fills
        
        signing_start = time.time()
        # Sign transactions
        latency_tracker["signing"] = (time.time() - signing_start) * 1000
        
        submission_start = time.time()
        buy_tx_hash = f"0x{'1' * 64}"
        sell_tx_hash = f"0x{'2' * 64}"
        latency_tracker["submission"] = (time.time() - submission_start) * 1000
        
        # Total latency
        total_latency = (time.time() - start_time) * 1000
        latency_tracker["total"] = total_latency
        
        # Check latency budget
        if total_latency > self._latency_budget.total_budget_ms:
            logger.warning(
                f"Total latency {total_latency:.2f}ms exceeds budget "
                f"{self._latency_budget.total_budget_ms:.2f}ms"
            )
        
        execution = SniperExecution(
            execution_id=f"exec_{int(time.time() * 1000)}",
            opportunity=opportunity,
            executed=True,
            buy_tx_hash=buy_tx_hash,
            sell_tx_hash=sell_tx_hash,
            actual_profit=opportunity.net_profit * 0.9,  # Simulated slippage
            latency_ms=latency_tracker,
            timestamp=time.time()
        )
        
        self._executions.append(execution)
        self._opportunities_executed += 1
        self._risk_controls.record_execution(execution)
        
        logger.info(
            f"Executed sniper opportunity: {opportunity.symbol} "
            f"profit ${execution.actual_profit:.2f} latency {total_latency:.2f}ms"
        )
        
        return execution
    
    def set_mode(self, mode: SniperMode) -> None:
        """Set sniper operating mode."""
        old_mode = self.mode
        self.mode = mode
        logger.info(f"Sniper mode changed: {old_mode.value} -> {mode.value}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        if not self._executions:
            return {
                "opportunities_seen": self._opportunities_seen,
                "opportunities_executed": 0,
                "execution_rate": 0.0,
                "average_profit": 0.0,
                "average_latency": 0.0,
                "success_rate": 0.0
            }
        
        successful = [e for e in self._executions if e.actual_profit > 0]
        
        avg_latency = sum(e.latency_ms.get("total", 0) for e in self._executions) / len(self._executions)
        
        return {
            "opportunities_seen": self._opportunities_seen,
            "opportunities_executed": self._opportunities_executed,
            "execution_rate": self._opportunities_executed / self._opportunities_seen if self._opportunities_seen > 0 else 0,
            "average_profit": sum(e.actual_profit for e in self._executions) / len(self._executions),
            "average_latency": avg_latency,
            "success_rate": len(successful) / len(self._executions),
            "total_profit": sum(e.actual_profit for e in self._executions),
            "latency_budget": {
                "total_budget_ms": self._latency_budget.total_budget_ms,
                "average_actual_ms": avg_latency,
                "budget_utilization": avg_latency / self._latency_budget.total_budget_ms
            }
        }
    
    def get_risk_stats(self) -> Dict[str, Any]:
        """Get risk statistics."""
        return self._risk_controls.get_stats()


# Global sniper engine
_sniper_engine: Optional[SniperEngine] = None
_sniper_engine_lock = threading.Lock()


def get_sniper_engine() -> SniperEngine:
    """Get the global sniper engine."""
    global _sniper_engine
    if _sniper_engine is None:
        with _sniper_engine_lock:
            if _sniper_engine is None:
                _sniper_engine = SniperEngine()
    return _sniper_engine
