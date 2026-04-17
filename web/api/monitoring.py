"""
Monitoring & Metrics API Endpoints.

Provides API access to system monitoring, metrics, and health checks.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from monitoring import (
    get_metrics_collector,
    get_system_monitor,
    get_performance_tracker,
    get_health_checker,
)
from monitoring.metrics_collector import MetricType
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.monitoring")


# ============================================
# REQUEST MODELS
# ============================================

class RecordMetricRequest(BaseModel):
    name: str
    value: float
    metric_type: str = "gauge"
    labels: Dict[str, str] = {}


class RecordTradeRequest(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: float
    exit_time: float
    slippage_bps: float = 0.0
    execution_latency_ms: float = 0.0


# ============================================
# METRICS ENDPOINTS
# ============================================

@router.get("/metrics")
async def get_all_metrics() -> Dict[str, Any]:
    """Get all metrics."""
    return get_metrics_collector().get_all_metrics()


@router.get("/metrics/{name}")
async def get_metric(name: str) -> Dict[str, Any]:
    """Get a specific metric."""
    metric = get_metrics_collector().get_metric(name)
    if metric:
        return metric.to_dict()
    raise HTTPException(status_code=404, detail="Metric not found")


@router.post("/metrics/record")
async def record_metric(request: RecordMetricRequest) -> Dict[str, Any]:
    """Record a metric value."""
    get_metrics_collector().record(request.name, request.value, request.labels)
    return {"status": "recorded"}


@router.post("/metrics/increment/{name}")
async def increment_metric(name: str, value: float = 1.0) -> Dict[str, Any]:
    """Increment a counter metric."""
    get_metrics_collector().increment(name, value)
    return {"status": "incremented"}


@router.get("/metrics/prometheus")
async def get_prometheus_metrics() -> str:
    """Get metrics in Prometheus format."""
    return get_metrics_collector().export_prometheus()


@router.post("/metrics/cleanup")
async def cleanup_old_metrics() -> Dict[str, Any]:
    """Cleanup old metric values."""
    removed = get_metrics_collector().cleanup_old_values()
    return {"status": "cleaned", "removed_values": removed}


@router.get("/metrics/prefix/{prefix}")
async def get_metrics_by_prefix(prefix: str) -> Dict[str, Any]:
    """Get metrics matching a prefix."""
    return get_metrics_collector().get_metrics_by_prefix(prefix)


# ============================================
# SYSTEM MONITOR ENDPOINTS
# ============================================

@router.get("/system/status")
async def get_system_status() -> Dict[str, Any]:
    """Get system monitor status."""
    return get_system_monitor().get_status()


@router.post("/system/start")
async def start_system_monitor(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start system monitoring."""
    monitor = get_system_monitor()
    background_tasks.add_task(monitor.start)
    return {"status": "starting"}


@router.post("/system/stop")
async def stop_system_monitor() -> Dict[str, Any]:
    """Stop system monitoring."""
    await get_system_monitor().stop()
    return {"status": "stopped"}


@router.get("/system/stats")
async def get_system_stats() -> Dict[str, Any]:
    """Get current system stats."""
    stats = get_system_monitor().get_current_stats()
    if stats:
        return stats
    return {"error": "No stats available"}


@router.get("/system/history")
async def get_system_history(limit: int = 100) -> Dict[str, Any]:
    """Get system stats history."""
    history = get_system_monitor().get_history(limit)
    return {"count": len(history), "history": history}


@router.get("/system/info")
async def get_system_info() -> Dict[str, Any]:
    """Get system information."""
    return get_system_monitor().get_system_info()


@router.get("/system/components")
async def get_components() -> Dict[str, Any]:
    """Get component statuses."""
    return get_system_monitor().get_components()


@router.post("/system/components/{name}")
async def update_component(
    name: str,
    healthy: bool,
    status: str = "running",
    latency_ms: float = 0.0,
) -> Dict[str, Any]:
    """Update component status."""
    get_system_monitor().update_component(name, healthy, status, latency_ms)
    return {"status": "updated"}


# ============================================
# PERFORMANCE TRACKER ENDPOINTS
# ============================================

@router.get("/performance/status")
async def get_performance_status() -> Dict[str, Any]:
    """Get performance tracker status."""
    return get_performance_tracker().get_status()


@router.post("/performance/trade")
async def record_trade(request: RecordTradeRequest) -> Dict[str, Any]:
    """Record a completed trade."""
    trade = get_performance_tracker().record_trade(
        trade_id=request.trade_id,
        symbol=request.symbol,
        side=request.side,
        entry_price=request.entry_price,
        exit_price=request.exit_price,
        quantity=request.quantity,
        entry_time=request.entry_time,
        exit_time=request.exit_time,
        slippage_bps=request.slippage_bps,
        execution_latency_ms=request.execution_latency_ms,
    )
    return {"status": "recorded", "trade": trade.to_dict()}


@router.get("/performance/summary")
async def get_performance_summary(period: str = "all") -> Dict[str, Any]:
    """Get performance summary."""
    summary = get_performance_tracker().get_summary(period)
    return summary.to_dict()


@router.get("/performance/trades")
async def get_recent_trades(limit: int = 100) -> Dict[str, Any]:
    """Get recent trades."""
    trades = get_performance_tracker().get_recent_trades(limit)
    return {"count": len(trades), "trades": trades}


@router.get("/performance/trades/{symbol}")
async def get_trades_by_symbol(symbol: str) -> Dict[str, Any]:
    """Get trades for a symbol."""
    trades = get_performance_tracker().get_trades_by_symbol(symbol)
    return {"count": len(trades), "trades": trades}


@router.get("/performance/equity")
async def get_equity_curve(limit: int = 1000) -> Dict[str, Any]:
    """Get equity curve."""
    curve = get_performance_tracker().get_equity_curve(limit)
    return {"count": len(curve), "curve": curve}


@router.get("/performance/by-symbol")
async def get_symbol_performance() -> Dict[str, Any]:
    """Get performance by symbol."""
    return get_performance_tracker().get_symbol_performance()


# ============================================
# HEALTH CHECK ENDPOINTS
# ============================================

@router.get("/health")
async def get_health() -> Dict[str, Any]:
    """Get overall health status."""
    return get_health_checker().get_overall_health()


@router.get("/health/status")
async def get_health_status() -> Dict[str, Any]:
    """Get health checker status."""
    return get_health_checker().get_status()


@router.post("/health/start")
async def start_health_checker(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start health checking."""
    checker = get_health_checker()
    background_tasks.add_task(checker.start)
    return {"status": "starting"}


@router.post("/health/stop")
async def stop_health_checker() -> Dict[str, Any]:
    """Stop health checking."""
    await get_health_checker().stop()
    return {"status": "stopped"}


@router.get("/health/checks")
async def get_all_checks() -> Dict[str, Any]:
    """Get all health checks."""
    return get_health_checker().get_all_checks()


@router.get("/health/checks/{name}")
async def get_check(name: str) -> Dict[str, Any]:
    """Get a specific health check."""
    check = get_health_checker().get_check(name)
    if check:
        return check
    raise HTTPException(status_code=404, detail="Check not found")


@router.post("/health/checks/{name}/run")
async def run_check(name: str) -> Dict[str, Any]:
    """Run a specific health check now."""
    result = await get_health_checker().run_check_now(name)
    return result


@router.get("/health/unhealthy")
async def get_unhealthy_checks() -> Dict[str, Any]:
    """Get unhealthy checks."""
    checks = get_health_checker().get_unhealthy_checks()
    return {"count": len(checks), "checks": checks}


@router.get("/health/is-healthy")
async def is_healthy() -> Dict[str, Any]:
    """Check if system is healthy."""
    healthy = get_health_checker().is_healthy()
    return {"healthy": healthy}


# ============================================
# DASHBOARD ENDPOINT
# ============================================

@router.get("/dashboard")
async def get_monitoring_dashboard() -> Dict[str, Any]:
    """Get comprehensive monitoring dashboard data."""
    return {
        "health": get_health_checker().get_overall_health(),
        "system": get_system_monitor().get_current_stats(),
        "performance": get_performance_tracker().get_status(),
        "metrics_summary": {
            "total_metrics": len(get_metrics_collector()._metrics),
            "http_requests": get_metrics_collector().get_value("http_requests_total"),
            "trades_total": get_metrics_collector().get_value("trades_total"),
            "ws_connections": get_metrics_collector().get_value("ws_connections"),
        },
    }


# ============================================
# AUDIT ENDPOINTS
# ============================================

@router.get("/audit/recent")
async def get_recent_audit_events(limit: int = 20) -> Dict[str, Any]:
    """Get recent audit events for dashboard."""
    try:
        from core.audit_trail import get_audit_trail
        audit = get_audit_trail()
        events = audit.get_recent_entries(limit) if hasattr(audit, 'get_recent_entries') else []
        return {
            "events": events,
            "count": len(events)
        }
    except Exception as e:
        logger.error(f"Audit fetch error: {e}")
        return {"events": [], "count": 0, "error": str(e)}


# ============================================
# ANALYTICS ENDPOINTS
# ============================================

@router.get("/analytics/summary")
async def get_analytics_summary() -> Dict[str, Any]:
    """Get analytics summary for dashboard."""
    try:
        perf = get_performance_tracker()
        stats = perf.get_status() if hasattr(perf, 'get_status') else {}
        
        return {
            "win_rate": stats.get('win_rate', 0),
            "total_trades": stats.get('total_trades', 0),
            "total_pnl": stats.get('total_pnl', 0),
            "sharpe_ratio": stats.get('sharpe_ratio', 0),
            "max_drawdown": stats.get('max_drawdown', 0),
            "avg_trade_duration": stats.get('avg_trade_duration', 0)
        }
    except Exception as e:
        logger.error(f"Analytics fetch error: {e}")
        return {
            "win_rate": 0,
            "total_trades": 0,
            "total_pnl": 0,
            "error": str(e)
        }
