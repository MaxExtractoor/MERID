"""
Execution Gate for Arbitrage.

Controls whether arbitrage opportunities can be executed.
Enforces profit thresholds, liquidity checks, and kill-switch integration.

EXECUTION IS DISABLED BY DEFAULT.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum

from schemas.arbitrage import ArbitrageOpportunity, ArbitrageStatus
from arbitrage.cost_model import CostModelEngine, get_cost_model_engine
from utils.logger import get_logger

logger = get_logger("arbitrage.execution_gate")


class GateDecision(Enum):
    """Execution gate decision."""
    ALLOW = "allow"
    DENY = "deny"
    PENDING_REVIEW = "pending_review"


class DenyReason(Enum):
    """Reasons for denying execution."""
    EXECUTION_DISABLED = "execution_disabled"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    INSUFFICIENT_PROFIT = "insufficient_profit"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    HIGH_EXECUTION_RISK = "high_execution_risk"
    VENUE_DISABLED = "venue_disabled"
    SYMBOL_DISABLED = "symbol_disabled"
    RATE_LIMITED = "rate_limited"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    OPPORTUNITY_EXPIRED = "opportunity_expired"
    COST_EXCEEDS_PROFIT = "cost_exceeds_profit"
    MANUAL_BLOCK = "manual_block"


@dataclass
class GateResult:
    """Result of execution gate check."""
    decision: GateDecision
    reason: Optional[DenyReason] = None
    message: str = ""
    adjusted_opportunity: Optional[ArbitrageOpportunity] = None
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason.value if self.reason else None,
            "message": self.message,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionLimits:
    """Execution limits configuration."""
    # Global limits
    max_daily_executions: int = 100
    max_daily_volume_usd: float = 1000000.0
    max_concurrent_positions: int = 10
    
    # Per-opportunity limits
    min_profit_usd: float = 10.0
    min_profit_margin_pct: float = 0.1
    max_position_usd: float = 50000.0
    max_slippage_pct: float = 0.5
    
    # Risk limits
    max_execution_risk: float = 0.5
    min_liquidity_score: float = 0.3
    
    # Timing
    min_time_to_expiry_seconds: float = 10.0


class ExecutionGate:
    """
    Gate that controls arbitrage execution.
    
    All opportunities must pass through this gate before execution.
    The gate enforces:
    - Global execution enable/disable
    - Kill-switch integration
    - Profit thresholds
    - Liquidity requirements
    - Rate limiting
    - Daily limits
    """
    
    def __init__(self, limits: Optional[ExecutionLimits] = None):
        self.logger = get_logger("arbitrage.execution_gate")
        self.limits = limits or ExecutionLimits()
        
        # CRITICAL: Execution disabled by default
        self._execution_enabled: bool = False
        
        # Kill switch
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._kill_switch_activated_at: Optional[float] = None
        
        # Venue/symbol controls
        self._disabled_venues: Set[str] = set()
        self._disabled_symbols: Set[str] = set()
        self._whitelisted_venues: Set[str] = set()
        self._whitelisted_symbols: Set[str] = set()
        
        # Daily tracking
        self._daily_executions: int = 0
        self._daily_volume_usd: float = 0.0
        self._daily_reset_time: float = time.time()
        
        # Rate limiting
        self._last_execution_time: float = 0.0
        self._min_execution_interval_seconds: float = 1.0
        
        # Active positions
        self._active_positions: int = 0
        
        # Cost model
        self._cost_model = get_cost_model_engine()
        
        # Audit log
        self._audit_log: List[Dict[str, Any]] = []
    
    def check(self, opportunity: ArbitrageOpportunity) -> GateResult:
        """
        Check if an opportunity can be executed.
        
        Returns GateResult with decision and details.
        """
        checks_passed = []
        checks_failed = []
        
        # Reset daily counters if needed
        self._check_daily_reset()
        
        # 1. Check if execution is enabled
        if not self._execution_enabled:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.EXECUTION_DISABLED,
                message="Arbitrage execution is disabled globally",
                checks_failed=["execution_enabled"],
            )
        checks_passed.append("execution_enabled")
        
        # 2. Check kill switch
        if self._kill_switch_active:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.KILL_SWITCH_ACTIVE,
                message=f"Kill switch active: {self._kill_switch_reason}",
                checks_failed=["kill_switch"],
            )
        checks_passed.append("kill_switch")
        
        # 3. Check opportunity expiry
        if opportunity.is_expired():
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.OPPORTUNITY_EXPIRED,
                message="Opportunity has expired",
                checks_passed=checks_passed,
                checks_failed=["expiry"],
            )
        
        if opportunity.expires_at:
            time_to_expiry = opportunity.expires_at - time.time()
            if time_to_expiry < self.limits.min_time_to_expiry_seconds:
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=DenyReason.OPPORTUNITY_EXPIRED,
                    message=f"Insufficient time to expiry: {time_to_expiry:.1f}s",
                    checks_passed=checks_passed,
                    checks_failed=["time_to_expiry"],
                )
        checks_passed.append("expiry")
        
        # 4. Check venues
        for leg in opportunity.legs:
            if leg.venue in self._disabled_venues:
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=DenyReason.VENUE_DISABLED,
                    message=f"Venue disabled: {leg.venue}",
                    checks_passed=checks_passed,
                    checks_failed=["venue_enabled"],
                )
            if self._whitelisted_venues and leg.venue not in self._whitelisted_venues:
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=DenyReason.VENUE_DISABLED,
                    message=f"Venue not whitelisted: {leg.venue}",
                    checks_passed=checks_passed,
                    checks_failed=["venue_whitelisted"],
                )
        checks_passed.append("venues")
        
        # 5. Check symbols
        for leg in opportunity.legs:
            if leg.symbol in self._disabled_symbols:
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=DenyReason.SYMBOL_DISABLED,
                    message=f"Symbol disabled: {leg.symbol}",
                    checks_passed=checks_passed,
                    checks_failed=["symbol_enabled"],
                )
            if self._whitelisted_symbols and leg.symbol not in self._whitelisted_symbols:
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=DenyReason.SYMBOL_DISABLED,
                    message=f"Symbol not whitelisted: {leg.symbol}",
                    checks_passed=checks_passed,
                    checks_failed=["symbol_whitelisted"],
                )
        checks_passed.append("symbols")
        
        # 6. Recalculate costs with latest data
        updated_cost = self._cost_model.calculate_total_cost(opportunity)
        adjusted_net_profit = opportunity.gross_profit_usd - updated_cost.total_cost()
        
        if adjusted_net_profit <= 0:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.COST_EXCEEDS_PROFIT,
                message=f"Updated costs exceed profit: ${updated_cost.total_cost():.2f} > ${opportunity.gross_profit_usd:.2f}",
                checks_passed=checks_passed,
                checks_failed=["cost_check"],
            )
        checks_passed.append("cost_check")
        
        # 7. Check profit thresholds
        if adjusted_net_profit < self.limits.min_profit_usd:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.INSUFFICIENT_PROFIT,
                message=f"Profit ${adjusted_net_profit:.2f} below minimum ${self.limits.min_profit_usd}",
                checks_passed=checks_passed,
                checks_failed=["min_profit"],
            )
        checks_passed.append("min_profit")
        
        # 8. Check profit margin
        total_value = sum(leg.price * leg.quantity for leg in opportunity.legs) / 2
        margin_pct = (adjusted_net_profit / total_value) * 100 if total_value > 0 else 0
        
        if margin_pct < self.limits.min_profit_margin_pct:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.INSUFFICIENT_MARGIN,
                message=f"Margin {margin_pct:.3f}% below minimum {self.limits.min_profit_margin_pct}%",
                checks_passed=checks_passed,
                checks_failed=["min_margin"],
            )
        checks_passed.append("min_margin")
        
        # 9. Check position size
        if total_value > self.limits.max_position_usd:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.INSUFFICIENT_LIQUIDITY,
                message=f"Position ${total_value:.2f} exceeds max ${self.limits.max_position_usd}",
                checks_passed=checks_passed,
                checks_failed=["max_position"],
            )
        checks_passed.append("max_position")
        
        # 10. Check liquidity
        if opportunity.liquidity_score < self.limits.min_liquidity_score:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.INSUFFICIENT_LIQUIDITY,
                message=f"Liquidity score {opportunity.liquidity_score:.2f} below minimum {self.limits.min_liquidity_score}",
                checks_passed=checks_passed,
                checks_failed=["liquidity"],
            )
        checks_passed.append("liquidity")
        
        # 11. Check execution risk
        if opportunity.execution_risk > self.limits.max_execution_risk:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.HIGH_EXECUTION_RISK,
                message=f"Execution risk {opportunity.execution_risk:.2f} exceeds max {self.limits.max_execution_risk}",
                checks_passed=checks_passed,
                checks_failed=["execution_risk"],
            )
        checks_passed.append("execution_risk")
        
        # 12. Check daily limits
        if self._daily_executions >= self.limits.max_daily_executions:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.DAILY_LIMIT_REACHED,
                message=f"Daily execution limit reached: {self._daily_executions}",
                checks_passed=checks_passed,
                checks_failed=["daily_executions"],
            )
        checks_passed.append("daily_executions")
        
        if self._daily_volume_usd + total_value > self.limits.max_daily_volume_usd:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.DAILY_LIMIT_REACHED,
                message=f"Daily volume limit would be exceeded: ${self._daily_volume_usd + total_value:.2f}",
                checks_passed=checks_passed,
                checks_failed=["daily_volume"],
            )
        checks_passed.append("daily_volume")
        
        # 13. Check concurrent positions
        if self._active_positions >= self.limits.max_concurrent_positions:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.RATE_LIMITED,
                message=f"Max concurrent positions reached: {self._active_positions}",
                checks_passed=checks_passed,
                checks_failed=["concurrent_positions"],
            )
        checks_passed.append("concurrent_positions")
        
        # 14. Check rate limiting
        time_since_last = time.time() - self._last_execution_time
        if time_since_last < self._min_execution_interval_seconds:
            return GateResult(
                decision=GateDecision.DENY,
                reason=DenyReason.RATE_LIMITED,
                message=f"Rate limited: {self._min_execution_interval_seconds - time_since_last:.1f}s remaining",
                checks_passed=checks_passed,
                checks_failed=["rate_limit"],
            )
        checks_passed.append("rate_limit")
        
        # All checks passed
        # Update opportunity with recalculated values
        opportunity.cost_model = updated_cost
        opportunity.net_profit_usd = adjusted_net_profit
        opportunity.profit_margin_pct = margin_pct
        opportunity.status = ArbitrageStatus.VALID
        
        return GateResult(
            decision=GateDecision.ALLOW,
            message="All checks passed",
            adjusted_opportunity=opportunity,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )
    
    def record_execution(self, opportunity: ArbitrageOpportunity) -> None:
        """Record an execution for tracking."""
        total_value = sum(leg.price * leg.quantity for leg in opportunity.legs) / 2
        
        self._daily_executions += 1
        self._daily_volume_usd += total_value
        self._last_execution_time = time.time()
        self._active_positions += 1
        
        # Audit log
        self._audit_log.append({
            "timestamp": time.time(),
            "opportunity_id": opportunity.opportunity_id,
            "arb_type": opportunity.arb_type.value,
            "net_profit_usd": opportunity.net_profit_usd,
            "volume_usd": total_value,
        })
        
        self.logger.info(
            f"Execution recorded: {opportunity.opportunity_id} | "
            f"Daily: {self._daily_executions}/{self.limits.max_daily_executions}"
        )
    
    def release_position(self) -> None:
        """Release a position slot."""
        if self._active_positions > 0:
            self._active_positions -= 1
    
    def enable_execution(self) -> None:
        """Enable arbitrage execution (use with caution)."""
        self._execution_enabled = True
        self.logger.warning("ARBITRAGE EXECUTION ENABLED")
    
    def disable_execution(self) -> None:
        """Disable arbitrage execution."""
        self._execution_enabled = False
        self.logger.info("Arbitrage execution disabled")
    
    def activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self._kill_switch_activated_at = time.time()
        self.logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
    
    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._kill_switch_activated_at = None
        self.logger.warning("Kill switch deactivated")
    
    def disable_venue(self, venue: str) -> None:
        """Disable a venue."""
        self._disabled_venues.add(venue)
        self.logger.info(f"Venue disabled: {venue}")
    
    def enable_venue(self, venue: str) -> None:
        """Enable a venue."""
        self._disabled_venues.discard(venue)
        self.logger.info(f"Venue enabled: {venue}")
    
    def disable_symbol(self, symbol: str) -> None:
        """Disable a symbol."""
        self._disabled_symbols.add(symbol)
        self.logger.info(f"Symbol disabled: {symbol}")
    
    def enable_symbol(self, symbol: str) -> None:
        """Enable a symbol."""
        self._disabled_symbols.discard(symbol)
        self.logger.info(f"Symbol enabled: {symbol}")
    
    def _check_daily_reset(self) -> None:
        """Check if daily counters should be reset."""
        current_time = time.time()
        if current_time - self._daily_reset_time > 86400:  # 24 hours
            self._daily_executions = 0
            self._daily_volume_usd = 0.0
            self._daily_reset_time = current_time
            self.logger.info("Daily counters reset")
    
    def get_status(self) -> Dict[str, Any]:
        """Get execution gate status."""
        return {
            "execution_enabled": self._execution_enabled,
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "daily_executions": self._daily_executions,
            "daily_volume_usd": self._daily_volume_usd,
            "active_positions": self._active_positions,
            "disabled_venues": list(self._disabled_venues),
            "disabled_symbols": list(self._disabled_symbols),
            "limits": {
                "max_daily_executions": self.limits.max_daily_executions,
                "max_daily_volume_usd": self.limits.max_daily_volume_usd,
                "min_profit_usd": self.limits.min_profit_usd,
                "min_profit_margin_pct": self.limits.min_profit_margin_pct,
                "max_position_usd": self.limits.max_position_usd,
            },
            "recent_executions": self._audit_log[-10:],
        }


# Singleton
_execution_gate: Optional[ExecutionGate] = None
_execution_gate_lock = threading.Lock()


def get_execution_gate() -> ExecutionGate:
    """Get or create the Execution Gate singleton."""
    global _execution_gate
    if _execution_gate is None:
        with _execution_gate_lock:
            if _execution_gate is None:
                _execution_gate = ExecutionGate()
    return _execution_gate
