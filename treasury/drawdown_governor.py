"""
MERID Treasury Drawdown Governor - Phase 22

Independent drawdown management for treasury operations.
Separate from trading system drawdown controls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("treasury.drawdown_governor")


class DrawdownState(Enum):
    """Drawdown state levels."""
    NORMAL = "normal"
    CAUTION = "caution"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class DrawdownAction(Enum):
    """Actions taken by drawdown governor."""
    NONE = "none"
    REDUCE_RISK = "reduce_risk"
    PAUSE_NEW_DEPOSITS = "pause_new_deposits"
    PARTIAL_UNWIND = "partial_unwind"
    FULL_UNWIND = "full_unwind"
    EMERGENCY_EXIT = "emergency_exit"


@dataclass
class DrawdownEvent:
    """Recorded drawdown event."""
    event_id: str
    timestamp: float
    drawdown_pct: float
    peak_value_usd: float
    current_value_usd: float
    state: DrawdownState
    action_taken: DrawdownAction
    recovery_target_usd: float
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "drawdown_pct": self.drawdown_pct,
            "peak_value_usd": self.peak_value_usd,
            "current_value_usd": self.current_value_usd,
            "state": self.state.value,
            "action_taken": self.action_taken.value,
            "recovery_target_usd": self.recovery_target_usd,
            "notes": self.notes,
        }


@dataclass
class DrawdownLimits:
    """Configurable drawdown limits."""
    caution_pct: float = 3.0
    warning_pct: float = 5.0
    critical_pct: float = 8.0
    emergency_pct: float = 12.0
    max_daily_loss_pct: float = 2.0
    max_weekly_loss_pct: float = 5.0
    max_monthly_loss_pct: float = 10.0
    recovery_buffer_pct: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "caution_pct": self.caution_pct,
            "warning_pct": self.warning_pct,
            "critical_pct": self.critical_pct,
            "emergency_pct": self.emergency_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_weekly_loss_pct": self.max_weekly_loss_pct,
            "max_monthly_loss_pct": self.max_monthly_loss_pct,
            "recovery_buffer_pct": self.recovery_buffer_pct,
        }


class DrawdownGovernor:
    """
    Independent drawdown governor for treasury.
    
    Monitors and controls drawdown independently of trading system.
    """
    
    def __init__(self, limits: Optional[DrawdownLimits] = None):
        self.limits = limits or DrawdownLimits()
        self._peak_value_usd = 0.0
        self._current_value_usd = 0.0
        self._current_drawdown_pct = 0.0
        self._state = DrawdownState.NORMAL
        self._events: List[DrawdownEvent] = []
        self._daily_pnl: List[Tuple[float, float]] = []
        self._weekly_pnl: List[Tuple[float, float]] = []
        self._monthly_pnl: List[Tuple[float, float]] = []
        self._paused = False
        self._last_action = DrawdownAction.NONE
    
    def update_value(self, current_value_usd: float) -> DrawdownAction:
        """Update current value and check drawdown."""
        self._current_value_usd = current_value_usd
        
        # Update peak
        if current_value_usd > self._peak_value_usd:
            self._peak_value_usd = current_value_usd
        
        # Calculate drawdown
        if self._peak_value_usd > 0:
            self._current_drawdown_pct = (
                (self._peak_value_usd - current_value_usd) / self._peak_value_usd * 100
            )
        else:
            self._current_drawdown_pct = 0.0
        
        # Determine state and action
        old_state = self._state
        action = self._evaluate_state()
        
        # Log state change
        if self._state != old_state:
            logger.warning(
                "Treasury drawdown state changed: %s -> %s (%.2f%%)",
                old_state.value,
                self._state.value,
                self._current_drawdown_pct,
            )
            
            # Record event
            event = DrawdownEvent(
                event_id=f"dd_{int(time.time())}",
                timestamp=time.time(),
                drawdown_pct=self._current_drawdown_pct,
                peak_value_usd=self._peak_value_usd,
                current_value_usd=current_value_usd,
                state=self._state,
                action_taken=action,
                recovery_target_usd=self._peak_value_usd * (1 - self.limits.recovery_buffer_pct / 100),
            )
            self._events.append(event)
        
        self._last_action = action
        return action
    
    def _evaluate_state(self) -> DrawdownAction:
        """Evaluate current state and determine action."""
        dd = self._current_drawdown_pct
        
        if dd >= self.limits.emergency_pct:
            self._state = DrawdownState.EMERGENCY
            return DrawdownAction.EMERGENCY_EXIT
        elif dd >= self.limits.critical_pct:
            self._state = DrawdownState.CRITICAL
            return DrawdownAction.FULL_UNWIND
        elif dd >= self.limits.warning_pct:
            self._state = DrawdownState.WARNING
            return DrawdownAction.PARTIAL_UNWIND
        elif dd >= self.limits.caution_pct:
            self._state = DrawdownState.CAUTION
            return DrawdownAction.REDUCE_RISK
        else:
            self._state = DrawdownState.NORMAL
            return DrawdownAction.NONE
    
    def record_pnl(self, pnl_usd: float) -> None:
        """Record PnL for time-based limits."""
        now = time.time()
        
        self._daily_pnl.append((now, pnl_usd))
        self._weekly_pnl.append((now, pnl_usd))
        self._monthly_pnl.append((now, pnl_usd))
        
        # Clean old entries
        day_ago = now - 86400
        week_ago = now - 604800
        month_ago = now - 2592000
        
        self._daily_pnl = [(t, p) for t, p in self._daily_pnl if t > day_ago]
        self._weekly_pnl = [(t, p) for t, p in self._weekly_pnl if t > week_ago]
        self._monthly_pnl = [(t, p) for t, p in self._monthly_pnl if t > month_ago]
    
    def check_time_limits(self) -> Tuple[bool, List[str]]:
        """Check time-based loss limits."""
        violations = []
        
        # Daily limit
        daily_loss = sum(p for _, p in self._daily_pnl if p < 0)
        daily_loss_pct = abs(daily_loss / self._peak_value_usd * 100) if self._peak_value_usd > 0 else 0
        if daily_loss_pct > self.limits.max_daily_loss_pct:
            violations.append(f"Daily loss {daily_loss_pct:.2f}% exceeds limit {self.limits.max_daily_loss_pct}%")
        
        # Weekly limit
        weekly_loss = sum(p for _, p in self._weekly_pnl if p < 0)
        weekly_loss_pct = abs(weekly_loss / self._peak_value_usd * 100) if self._peak_value_usd > 0 else 0
        if weekly_loss_pct > self.limits.max_weekly_loss_pct:
            violations.append(f"Weekly loss {weekly_loss_pct:.2f}% exceeds limit {self.limits.max_weekly_loss_pct}%")
        
        # Monthly limit
        monthly_loss = sum(p for _, p in self._monthly_pnl if p < 0)
        monthly_loss_pct = abs(monthly_loss / self._peak_value_usd * 100) if self._peak_value_usd > 0 else 0
        if monthly_loss_pct > self.limits.max_monthly_loss_pct:
            violations.append(f"Monthly loss {monthly_loss_pct:.2f}% exceeds limit {self.limits.max_monthly_loss_pct}%")
        
        return len(violations) == 0, violations
    
    def pause(self, reason: str) -> None:
        """Pause treasury operations."""
        self._paused = True
        logger.warning("Treasury operations PAUSED: %s", reason)
    
    def resume(self, approval: str) -> bool:
        """Resume treasury operations."""
        if not approval:
            return False
        
        self._paused = False
        logger.info("Treasury operations RESUMED with approval: %s", approval[:20])
        return True
    
    def reset_peak(self, new_peak: Optional[float] = None) -> None:
        """Reset peak value (after recovery or rebase)."""
        if new_peak:
            self._peak_value_usd = new_peak
        else:
            self._peak_value_usd = self._current_value_usd
        
        self._current_drawdown_pct = 0.0
        self._state = DrawdownState.NORMAL
        logger.info("Peak reset to $%.2f", self._peak_value_usd)
    
    def get_status(self) -> Dict[str, Any]:
        """Get drawdown governor status."""
        time_ok, time_violations = self.check_time_limits()
        
        return {
            "state": self._state.value,
            "paused": self._paused,
            "current_drawdown_pct": self._current_drawdown_pct,
            "peak_value_usd": self._peak_value_usd,
            "current_value_usd": self._current_value_usd,
            "last_action": self._last_action.value,
            "limits": self.limits.to_dict(),
            "time_limits_ok": time_ok,
            "time_violations": time_violations,
            "recent_events": [e.to_dict() for e in self._events[-10:]],
            "daily_pnl_count": len(self._daily_pnl),
            "weekly_pnl_count": len(self._weekly_pnl),
            "monthly_pnl_count": len(self._monthly_pnl),
        }


class AutoRebalancer:
    """
    Auto-rebalancing across yield sources.
    
    Maintains target allocations and rebalances when drift exceeds threshold.
    """
    
    def __init__(
        self,
        drift_threshold_pct: float = 5.0,
        min_rebalance_interval_hours: float = 24.0,
        max_rebalance_cost_pct: float = 0.5,
    ):
        self.drift_threshold_pct = drift_threshold_pct
        self.min_rebalance_interval_hours = min_rebalance_interval_hours
        self.max_rebalance_cost_pct = max_rebalance_cost_pct
        self._last_rebalance = 0.0
        self._rebalance_history: List[Dict[str, Any]] = []
    
    def check_drift(
        self,
        target_allocations: Dict[str, float],
        current_allocations: Dict[str, float],
    ) -> Tuple[bool, Dict[str, float]]:
        """Check if allocations have drifted beyond threshold."""
        drifts = {}
        needs_rebalance = False
        
        for source_id, target_pct in target_allocations.items():
            current_pct = current_allocations.get(source_id, 0.0)
            drift = abs(current_pct - target_pct)
            drifts[source_id] = drift
            
            if drift > self.drift_threshold_pct:
                needs_rebalance = True
        
        return needs_rebalance, drifts
    
    def calculate_rebalance(
        self,
        target_allocations: Dict[str, float],
        current_allocations: Dict[str, float],
        total_value_usd: float,
    ) -> List[Dict[str, Any]]:
        """Calculate rebalance trades needed."""
        trades = []
        
        for source_id, target_pct in target_allocations.items():
            current_pct = current_allocations.get(source_id, 0.0)
            diff_pct = target_pct - current_pct
            
            if abs(diff_pct) < 0.5:  # Skip tiny adjustments
                continue
            
            amount_usd = total_value_usd * (diff_pct / 100)
            
            trades.append({
                "source_id": source_id,
                "action": "deposit" if diff_pct > 0 else "withdraw",
                "amount_usd": abs(amount_usd),
                "from_pct": current_pct,
                "to_pct": target_pct,
            })
        
        return trades
    
    def can_rebalance(self) -> Tuple[bool, str]:
        """Check if rebalancing is allowed."""
        now = time.time()
        hours_since_last = (now - self._last_rebalance) / 3600
        
        if hours_since_last < self.min_rebalance_interval_hours:
            return False, f"Too soon since last rebalance ({hours_since_last:.1f}h < {self.min_rebalance_interval_hours}h)"
        
        return True, "OK"
    
    def execute_rebalance(
        self,
        trades: List[Dict[str, Any]],
        estimated_cost_usd: float,
        total_value_usd: float,
    ) -> Dict[str, Any]:
        """Execute rebalance (record only - actual execution is external)."""
        cost_pct = (estimated_cost_usd / total_value_usd * 100) if total_value_usd > 0 else 0
        
        if cost_pct > self.max_rebalance_cost_pct:
            return {
                "executed": False,
                "reason": f"Cost too high: {cost_pct:.2f}% > {self.max_rebalance_cost_pct}%",
            }
        
        self._last_rebalance = time.time()
        
        record = {
            "timestamp": time.time(),
            "trades": trades,
            "estimated_cost_usd": estimated_cost_usd,
            "cost_pct": cost_pct,
            "total_value_usd": total_value_usd,
        }
        self._rebalance_history.append(record)
        
        return {
            "executed": True,
            "trades": trades,
            "cost_usd": estimated_cost_usd,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get rebalancer status."""
        can_rebal, reason = self.can_rebalance()
        
        return {
            "drift_threshold_pct": self.drift_threshold_pct,
            "min_rebalance_interval_hours": self.min_rebalance_interval_hours,
            "max_rebalance_cost_pct": self.max_rebalance_cost_pct,
            "last_rebalance": self._last_rebalance,
            "can_rebalance": can_rebal,
            "rebalance_reason": reason,
            "rebalance_count": len(self._rebalance_history),
            "recent_rebalances": self._rebalance_history[-5:],
        }


class EmergencyUnwindManager:
    """
    Emergency unwind logic for DeFi protocols.
    
    Handles graceful and emergency exits from yield positions.
    """
    
    def __init__(self):
        self._unwind_queue: List[Dict[str, Any]] = []
        self._unwind_history: List[Dict[str, Any]] = []
        self._protocol_priorities = {
            "tier_5_degen": 1,  # Exit first
            "tier_4_high": 2,
            "tier_3_medium": 3,
            "tier_2_low": 4,
            "tier_1_safe": 5,  # Exit last
        }
    
    def queue_unwind(
        self,
        source_id: str,
        protocol: str,
        amount_usd: float,
        risk_tier: str,
        urgency: str = "normal",
        reason: str = "",
    ) -> str:
        """Queue a position for unwinding."""
        unwind_id = f"unwind_{int(time.time())}_{source_id[:8]}"
        
        priority = self._protocol_priorities.get(risk_tier, 3)
        if urgency == "emergency":
            priority = 0
        elif urgency == "high":
            priority = max(0, priority - 2)
        
        unwind = {
            "unwind_id": unwind_id,
            "source_id": source_id,
            "protocol": protocol,
            "amount_usd": amount_usd,
            "risk_tier": risk_tier,
            "urgency": urgency,
            "priority": priority,
            "reason": reason,
            "queued_at": time.time(),
            "status": "queued",
        }
        
        self._unwind_queue.append(unwind)
        self._unwind_queue.sort(key=lambda x: x["priority"])
        
        logger.warning("Unwind queued: %s ($%.2f) - %s", source_id, amount_usd, reason)
        
        return unwind_id
    
    def get_next_unwind(self) -> Optional[Dict[str, Any]]:
        """Get next position to unwind."""
        for unwind in self._unwind_queue:
            if unwind["status"] == "queued":
                return unwind
        return None
    
    def complete_unwind(
        self,
        unwind_id: str,
        actual_amount_usd: float,
        slippage_pct: float,
    ) -> bool:
        """Mark unwind as complete."""
        for unwind in self._unwind_queue:
            if unwind["unwind_id"] == unwind_id:
                unwind["status"] = "completed"
                unwind["completed_at"] = time.time()
                unwind["actual_amount_usd"] = actual_amount_usd
                unwind["slippage_pct"] = slippage_pct
                
                self._unwind_history.append(unwind)
                self._unwind_queue.remove(unwind)
                
                logger.info("Unwind completed: %s ($%.2f, %.2f%% slippage)", 
                           unwind_id, actual_amount_usd, slippage_pct)
                return True
        
        return False
    
    def emergency_unwind_all(self, reason: str) -> List[str]:
        """Queue emergency unwind for all positions."""
        # This would be called with actual positions from the system
        logger.critical("EMERGENCY UNWIND ALL: %s", reason)
        return []
    
    def get_status(self) -> Dict[str, Any]:
        """Get unwind manager status."""
        return {
            "queue_length": len(self._unwind_queue),
            "queued_value_usd": sum(u["amount_usd"] for u in self._unwind_queue if u["status"] == "queued"),
            "unwind_queue": self._unwind_queue,
            "recent_unwinds": self._unwind_history[-10:],
            "total_unwound": len(self._unwind_history),
        }


# Singleton instances
_drawdown_governor: Optional[DrawdownGovernor] = None
_auto_rebalancer: Optional[AutoRebalancer] = None
_emergency_unwind: Optional[EmergencyUnwindManager] = None


def get_drawdown_governor() -> DrawdownGovernor:
    global _drawdown_governor
    if _drawdown_governor is None:
        _drawdown_governor = DrawdownGovernor()
    return _drawdown_governor


def get_auto_rebalancer() -> AutoRebalancer:
    global _auto_rebalancer
    if _auto_rebalancer is None:
        _auto_rebalancer = AutoRebalancer()
    return _auto_rebalancer


def get_emergency_unwind() -> EmergencyUnwindManager:
    global _emergency_unwind
    if _emergency_unwind is None:
        _emergency_unwind = EmergencyUnwindManager()
    return _emergency_unwind
