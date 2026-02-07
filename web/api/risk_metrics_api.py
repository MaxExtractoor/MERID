"""
Risk Metrics API Endpoint

Provides real-time risk metrics including P&L, drawdown, margin utilization, and exposure.
Also exposes trading halt/resume controls and feed staleness status.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("web.api.risk_metrics_api")

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


class HaltRequest(BaseModel):
    reason: str = "operator_manual_halt"


class ResumeRequest(BaseModel):
    operator: str = "operator"


@router.get("/metrics")
async def get_risk_metrics() -> Dict[str, Any]:
    """
    Get current risk metrics for the trading system.
    
    Returns:
        {
            "totalPnL": float,
            "dailyDrawdown": float,
            "maxDrawdown": float,
            "marginUsed": float,
            "marginAvailable": float,
            "exposure": {
                "BTC": {"long": float, "short": float},
                "ETH": {"long": float, "short": float},
                ...
            },
            "alerts": [
                {
                    "id": str,
                    "metric": str,
                    "value": float,
                    "threshold": float,
                    "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
                    "createdAt": str (ISO timestamp)
                }
            ]
        }
    """
    try:
        from trading.paper_trading import get_paper_engine
        from risk.risk_controller import get_risk_controller
        
        paper_engine = get_paper_engine()
        risk_controller = get_risk_controller()
        
        # Get global stats from paper engine
        global_stats = paper_engine.get_global_stats()
        
        # Calculate aggregate metrics
        total_pnl = global_stats.get("total_pnl", 0.0)
        total_equity = global_stats.get("equity", 0.0)
        total_cash = global_stats.get("cash", 0.0)
        
        # Calculate drawdown (simplified)
        starting_balance = 10000.0  # Default starting balance
        max_equity = max(total_equity, starting_balance)
        current_drawdown = ((max_equity - total_equity) / max_equity * 100) if max_equity > 0 else 0
        
        # Calculate margin metrics
        positions = global_stats.get("positions", [])
        margin_used = sum(
            pos.get("size_usd", 0) / pos.get("leverage", 1) 
            for pos in positions
        )
        margin_available = total_cash
        
        # Calculate exposure by symbol
        exposure: Dict[str, Dict[str, float]] = {}
        for pos in positions:
            symbol = pos.get("asset", "UNKNOWN")
            side = pos.get("side", "long").lower()
            size = pos.get("size_usd", 0.0)
            
            if symbol not in exposure:
                exposure[symbol] = {"long": 0.0, "short": 0.0}
            
            exposure[symbol][side] += size
        
        # Get risk alerts from risk controller
        alerts = []
        if risk_controller:
            # Check if kill switch is active
            if not risk_controller.can_trade():
                alerts.append({
                    "id": "kill_switch_active",
                    "metric": "trading_enabled",
                    "value": 0,
                    "threshold": 1,
                    "severity": "CRITICAL",
                    "createdAt": risk_controller.kill_switch_triggered_at.isoformat() if hasattr(risk_controller, 'kill_switch_triggered_at') else ""
                })
            
            # Check daily loss limit
            daily_pnl = risk_controller.daily_pnl if hasattr(risk_controller, 'daily_pnl') else 0
            daily_loss_limit = risk_controller.daily_loss_limit if hasattr(risk_controller, 'daily_loss_limit') else -1000
            if daily_pnl < daily_loss_limit * 0.8:  # 80% of limit
                alerts.append({
                    "id": "daily_loss_warning",
                    "metric": "daily_pnl",
                    "value": daily_pnl,
                    "threshold": daily_loss_limit,
                    "severity": "HIGH" if daily_pnl < daily_loss_limit else "MEDIUM",
                    "createdAt": ""
                })
        
        # Check drawdown alerts
        if current_drawdown > 15:
            alerts.append({
                "id": "drawdown_warning",
                "metric": "drawdown",
                "value": current_drawdown,
                "threshold": 15.0,
                "severity": "HIGH" if current_drawdown > 20 else "MEDIUM",
                "createdAt": ""
            })
        
        # Check margin utilization
        margin_total = margin_used + margin_available
        margin_util_pct = (margin_used / margin_total * 100) if margin_total > 0 else 0
        if margin_util_pct > 80:
            alerts.append({
                "id": "margin_utilization_warning",
                "metric": "margin_utilization",
                "value": margin_util_pct,
                "threshold": 80.0,
                "severity": "HIGH" if margin_util_pct > 90 else "MEDIUM",
                "createdAt": ""
            })
        
        return {
            "totalPnL": total_pnl,
            "dailyDrawdown": current_drawdown,
            "maxDrawdown": current_drawdown,  # Simplified - would track historical max
            "marginUsed": margin_used,
            "marginAvailable": margin_available,
            "exposure": exposure,
            "alerts": alerts
        }
        
    except Exception as e:
        logger.error(f"Failed to get risk metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/protections")
async def get_risk_protections() -> Dict[str, Any]:
    """
    Get current risk protection settings and status.
    
    Returns:
        {
            "killSwitchActive": bool,
            "dailyLossLimit": float,
            "dailyPnL": float,
            "maxDrawdownLimit": float,
            "currentDrawdown": float,
            "maxPositionSize": float,
            "maxLeverage": int
        }
    """
    try:
        from risk.risk_controller import get_risk_controller
        
        risk_controller = get_risk_controller()
        
        if not risk_controller:
            return {
                "killSwitchActive": False,
                "dailyLossLimit": -1000.0,
                "dailyPnL": 0.0,
                "maxDrawdownLimit": 20.0,
                "currentDrawdown": 0.0,
                "maxPositionSize": 5000.0,
                "maxLeverage": 10
            }
        
        return {
            "killSwitchActive": not risk_controller.can_trade(),
            "dailyLossLimit": getattr(risk_controller, 'daily_loss_limit', -1000.0),
            "dailyPnL": getattr(risk_controller, 'daily_pnl', 0.0),
            "maxDrawdownLimit": getattr(risk_controller, 'max_drawdown_limit', 20.0),
            "currentDrawdown": 0.0,  # Would calculate from portfolio
            "maxPositionSize": getattr(risk_controller, 'max_position_size', 5000.0),
            "maxLeverage": getattr(risk_controller, 'max_leverage', 10)
        }
        
    except Exception as e:
        logger.error(f"Failed to get risk protections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Trading Halt / Resume ────────────────────────────────────────────


def _get_coordinator():
    """Lazy import to avoid circular deps at module load."""
    from core.automated_risk_controls import get_risk_coordinator
    return get_risk_coordinator()


def _get_staleness_monitor():
    from core.feed_staleness_monitor import get_feed_staleness_monitor
    return get_feed_staleness_monitor()


@router.post("/halt")
async def halt_trading(req: HaltRequest) -> Dict[str, Any]:
    """Operator-initiated trading halt."""
    try:
        coord = _get_coordinator()
        changed = coord.halt_manager.halt(req.reason)
        return {
            "halted": coord.halt_manager.is_halted,
            "reason": coord.halt_manager.halt_reason,
            "changed": changed,
        }
    except Exception as e:
        logger.error(f"Halt trading error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume")
async def resume_trading(req: ResumeRequest) -> Dict[str, Any]:
    """Operator-initiated trading resume."""
    try:
        coord = _get_coordinator()
        changed = coord.halt_manager.resume(req.operator)
        return {
            "halted": coord.halt_manager.is_halted,
            "changed": changed,
        }
    except Exception as e:
        logger.error(f"Resume trading error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/halt-status")
async def get_halt_status() -> Dict[str, Any]:
    """Get current trading halt status including history."""
    try:
        coord = _get_coordinator()
        return {
            "can_trade": coord.can_trade(),
            **coord.halt_manager.get_status(),
        }
    except Exception as e:
        logger.error(f"Halt status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/staleness")
async def get_feed_staleness() -> Dict[str, Any]:
    """Get per-feed staleness summary and paused instruments."""
    try:
        monitor = _get_staleness_monitor()
        return monitor.get_summary()
    except Exception as e:
        logger.error(f"Feed staleness error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_risk_summary() -> Dict[str, Any]:
    """
    Consolidated risk summary: halt status, protections, staleness, exposure.
    Single endpoint for the operator dashboard.
    """
    try:
        coord = _get_coordinator()
        monitor = _get_staleness_monitor()

        halt_status = coord.halt_manager.get_status()
        staleness = monitor.get_summary()

        # Portfolio risk from coordinator
        risk_status = coord.get_comprehensive_risk_status()

        return {
            "can_trade": coord.can_trade(),
            "halt": halt_status,
            "staleness": staleness,
            "portfolio_risk": risk_status.get("portfolio_risk", {}),
            "active_stops": risk_status.get("active_stops", {}),
            "monitoring_active": risk_status.get("monitoring_active", False),
        }
    except Exception as e:
        logger.error(f"Risk summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
