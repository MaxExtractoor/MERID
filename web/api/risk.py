"""Risk and safety protections API endpoint.

Exposes circuit breaker state, lockdown status, and risk metrics for dashboard display.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)

from trading.guards.trading_guard import TradingGuard, CircuitBreakerState
from trading.config.runtime_config import get_runtime_config, GlobalTradingMode
from merid.execution.portfolio import PortfolioAggregator


router = APIRouter(prefix="/risk", tags=["risk"])


class CircuitBreakerStatus(BaseModel):
    """Circuit breaker state information."""
    state: str = Field(..., description="Current circuit state: CLOSED, OPEN, or HALF_OPEN")
    state_color: str = Field(..., description="Display color: green, red, or yellow")
    error_count: int = Field(0, description="Number of errors in current window")
    window_seconds: float = Field(60.0, description="Error tracking window duration")
    threshold: int = Field(5, description="Error threshold to trip breaker")
    last_error_at: Optional[str] = Field(None, description="ISO timestamp of last error")
    opened_at: Optional[str] = Field(None, description="ISO timestamp when breaker opened")
    cooldown_seconds: float = Field(300.0, description="Cooldown period before half-open")
    half_open_successes: int = Field(0, description="Successful requests in half-open state")


class LockdownStatus(BaseModel):
    """Trading lockdown/kill switch status."""
    trading_suite_enabled: bool = Field(True, description="Whether trading is enabled")
    global_mode: str = Field("simulation", description="Global trading mode")
    spectator_mode: bool = Field(True, description="Whether spectator mode is active")
    lockdown_reason: Optional[str] = Field(None, description="Reason for lockdown if disabled")


class RiskLimitsStatus(BaseModel):
    """Current risk limit status."""
    max_daily_loss_usd: float = Field(10000.0)
    current_daily_pnl: float = Field(0.0)
    daily_loss_utilization_pct: float = Field(0.0)
    max_per_symbol_exposure_usd: float = Field(50000.0)
    max_open_orders: int = Field(100)
    current_open_orders: int = Field(0)


class RiskProtectionsResponse(BaseModel):
    """Complete risk protections status."""
    timestamp: str = Field(..., description="ISO timestamp of this report")
    circuit_breaker: CircuitBreakerStatus
    lockdown: LockdownStatus
    risk_limits: RiskLimitsStatus
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)


# Global state storage - in production, use Redis/shared state
_circuit_breaker_history: List[Dict[str, Any]] = []
_trading_guard_instance: Optional[TradingGuard] = None


def _get_or_create_guard() -> TradingGuard:
    """Get or create the global trading guard instance."""
    global _trading_guard_instance
    if _trading_guard_instance is None:
        _trading_guard_instance = TradingGuard()
    return _trading_guard_instance


def _record_event(event_type: str, details: Dict[str, Any]) -> None:
    """Record a risk/safety event for history."""
    global _circuit_breaker_history
    _circuit_breaker_history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "details": details,
    })
    # Keep only last 100 events
    _circuit_breaker_history = _circuit_breaker_history[-100:]


@router.get("/protections", response_model=RiskProtectionsResponse)
async def get_risk_protections() -> RiskProtectionsResponse:
    """
    Get current risk protections status.
    
    Returns circuit breaker state, lockdown status, and risk limit utilization.
    This endpoint is polled by the dashboard to display safety status badges.
    """
    guard = _get_or_create_guard()
    runtime = get_runtime_config()
    portfolio = PortfolioAggregator()
    
    now = datetime.now(timezone.utc)
    
    # Circuit breaker status
    state = guard.circuit_state
    state_map = {
        CircuitBreakerState.CLOSED: ("CLOSED", "green"),
        CircuitBreakerState.OPEN: ("OPEN", "red"),
        CircuitBreakerState.HALF_OPEN: ("HALF_OPEN", "yellow"),
    }
    state_str, color = state_map.get(state, ("UNKNOWN", "gray"))
    
    # Get last error timestamp if available
    last_error = None
    if guard._error_timestamps:
        last_ts = max(guard._error_timestamps)
        last_error = datetime.fromtimestamp(last_ts).isoformat()
    
    opened_at = None
    if guard._circuit_opened_at:
        opened_at = datetime.fromtimestamp(guard._circuit_opened_at).isoformat()
    
    circuit_status = CircuitBreakerStatus(
        state=state_str,
        state_color=color,
        error_count=len(guard._error_timestamps),
        window_seconds=guard.config.circuit_breaker_window_seconds,
        threshold=guard.config.circuit_breaker_threshold,
        last_error_at=last_error,
        opened_at=opened_at,
        cooldown_seconds=guard.config.circuit_breaker_cooldown_seconds,
        half_open_successes=guard._half_open_successes,
    )
    
    # Lockdown status
    snapshot = runtime.snapshot()
    lockdown_status = LockdownStatus(
        trading_suite_enabled=guard.config.enable_trading_suite,
        global_mode=snapshot.get("mode", "unknown"),
        spectator_mode=snapshot.get("spectator_mode", True),
        lockdown_reason=None if guard.config.enable_trading_suite else "Trading suite disabled via kill switch",
    )
    
    # Risk limits
    daily_pnl = getattr(portfolio, 'daily_pnl', 0.0)
    max_loss = guard.config.max_daily_loss_usd
    utilization = abs(daily_pnl / max_loss * 100) if max_loss > 0 else 0.0
    
    risk_limits = RiskLimitsStatus(
        max_daily_loss_usd=max_loss,
        current_daily_pnl=daily_pnl,
        daily_loss_utilization_pct=min(utilization, 100.0),
        max_per_symbol_exposure_usd=guard.config.max_per_symbol_exposure_usd,
        max_open_orders=guard.config.max_open_orders,
        current_open_orders=getattr(portfolio, 'open_orders_count', 0),
    )
    
    # Recent events (last 10)
    recent = _circuit_breaker_history[-10:] if _circuit_breaker_history else []
    
    return RiskProtectionsResponse(
        timestamp=now.isoformat(),
        circuit_breaker=circuit_status,
        lockdown=lockdown_status,
        risk_limits=risk_limits,
        recent_events=recent,
    )


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker() -> Dict[str, Any]:
    """
    Manually reset the circuit breaker to CLOSED state.
    
    Requires admin privileges in production. Use with caution.
    """
    guard = _get_or_create_guard()
    
    old_state = guard.circuit_state
    guard._circuit_state = CircuitBreakerState.CLOSED
    guard._error_timestamps.clear()
    guard._half_open_successes = 0
    guard._circuit_opened_at = None
    
    _record_event("manual_reset", {
        "old_state": old_state.name,
        "new_state": "CLOSED",
    })
    
    return {
        "success": True,
        "message": f"Circuit breaker reset from {old_state.name} to CLOSED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/commitments")
async def get_historical_commitments() -> Dict[str, Any]:
    """
    Surface historical commitments auditor results in the risk view.

    Returns overdue items, gap counts, and readiness status.
    """
    try:
        from core.historical_commitments_auditor import HistoricalCommitmentsAuditor
        auditor = HistoricalCommitmentsAuditor()
        report = auditor.generate_report()
        return {
            "success": True,
            "overdue_count": report.get("overdue_count", 0),
            "total_commitments": report.get("total_commitments", 0),
            "overdue_items": report.get("overdue_items", []),
            "gap_summary": report.get("gap_summary", {}),
            "readiness_pct": report.get("readiness_pct", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except ImportError:
        return {
            "success": False,
            "message": "HistoricalCommitmentsAuditor not available",
            "overdue_count": 0,
            "total_commitments": 0,
            "overdue_items": [],
            "gap_summary": {},
            "readiness_pct": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.debug("commitment_readiness build skipped: %s", exc)
        return {
            "success": False,
            "message": str(exc),
            "overdue_count": 0,
            "total_commitments": 0,
            "overdue_items": [],
            "gap_summary": {},
            "readiness_pct": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/kill-switch/{action}")
async def toggle_kill_switch(action: str) -> Dict[str, Any]:
    """
    Enable or disable the trading kill switch.
    
    Actions: enable (blocks trades) or disable (allows trades)
    """
    guard = _get_or_create_guard()
    
    if action not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail="Action must be 'enable' or 'disable'")
    
    old_state = guard.config.enable_trading_suite
    
    if action == "enable":
        guard.config.enable_trading_suite = False
        _record_event("kill_switch_enabled", {"previous_state": old_state})
        return {
            "success": True,
            "message": "Kill switch ENABLED - trading blocked",
            "trading_enabled": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    else:
        guard.config.enable_trading_suite = True
        _record_event("kill_switch_disabled", {"previous_state": old_state})
        return {
            "success": True,
            "message": "Kill switch DISABLED - trading allowed",
            "trading_enabled": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
