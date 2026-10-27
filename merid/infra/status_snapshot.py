"""Observatory Status Snapshot — Unified health and status endpoint.

Provides a single endpoint/structure for the operator dashboard and
observability systems to query current system state across all
production-hardened components.

Usage:
    from merid.infra.status_snapshot import get_status_snapshot
    snapshot = await get_status_snapshot()
    
    # Or via API endpoint
    GET /api/v1/system/status-snapshot
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.infra.status_snapshot")


@dataclass
class SystemStatusSnapshot:
    """Complete system status snapshot for observatory dashboard."""
    
    # Metadata
    timestamp: str
    mode: str  # "live" or "paper"
    version: str = "1.0.0"
    
    # Execution Gate
    execution_gate: Dict[str, Any] = field(default_factory=dict)
    
    # Kill Switch State
    kill_switch: Dict[str, Any] = field(default_factory=dict)
    
    # Loop Lag Monitor
    loop_lag: Dict[str, Any] = field(default_factory=dict)
    
    # CFB RTI
    cfb_rti: Dict[str, Any] = field(default_factory=dict)
    
    # Redis
    redis: Dict[str, Any] = field(default_factory=dict)
    
    # Portfolio Integrity
    portfolio_integrity: Dict[str, Any] = field(default_factory=dict)
    
    # Background Scheduler
    background_scheduler: Dict[str, Any] = field(default_factory=dict)
    
    # Fills Ledger (Strict Mode)
    fills_ledger: Dict[str, Any] = field(default_factory=dict)
    
    # Asset Inference
    asset_inference: Dict[str, Any] = field(default_factory=dict)
    
    # Overall Health
    overall: Dict[str, Any] = field(default_factory=dict)
    
    # Performance metrics
    status_snapshot_ms: float = 0.0  # Time to generate snapshot in milliseconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "metadata": {
                "timestamp": self.timestamp,
                "mode": self.mode,
                "version": self.version,
                "status_snapshot_ms": round(self.status_snapshot_ms, 2),
            },
            "execution_gate": self.execution_gate,
            "kill_switch": self.kill_switch,
            "loop_lag": self.loop_lag,
            "cfb_rti": self.cfb_rti,
            "redis": self.redis,
            "portfolio_integrity": self.portfolio_integrity,
            "background_scheduler": self.background_scheduler,
            "fills_ledger": self.fills_ledger,
            "asset_inference": self.asset_inference,
            "overall": self.overall,
        }


async def get_status_snapshot() -> SystemStatusSnapshot:
    """Generate complete system status snapshot (cheap - reads cached state only).
    
    All component status functions read from in-memory state; no blocking
    computations or external calls. Suitable for frequent dashboard polling.
    """
    start_time = time.monotonic()
    
    is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
    mode = "live" if is_live else "paper"
    
    snapshot = SystemStatusSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
    )
    
    # Gather each component (all non-blocking reads from cached state)
    snapshot.execution_gate = _get_execution_gate_status()
    snapshot.kill_switch = _get_kill_switch_status()
    snapshot.loop_lag = _get_loop_lag_status()
    snapshot.cfb_rti = _get_cfb_rti_status()
    snapshot.redis = _get_redis_status()
    snapshot.portfolio_integrity = _get_portfolio_integrity_status()  # Reads cached last check
    snapshot.background_scheduler = _get_scheduler_status()
    snapshot.fills_ledger = _get_fills_ledger_status()
    snapshot.asset_inference = _get_asset_inference_status()
    
    # Calculate overall health
    snapshot.overall = _calculate_overall_health(snapshot)
    
    # Record generation time
    snapshot.status_snapshot_ms = (time.monotonic() - start_time) * 1000
    
    return snapshot


def _get_execution_gate_status() -> Dict[str, Any]:
    """Get execution gate status."""
    try:
        from core.execution_gate import check_execution_gate
        status = check_execution_gate()
        
        return {
            "healthy": not status.blocked,
            "state": status.gate_state,
            "safe_to_trade": status.safe_to_trade,
            "reasons_count": len(status.reasons),
            "critical_count": sum(1 for r in status.reasons if r.severity == "critical"),
            "warning_count": sum(1 for r in status.reasons if r.severity == "warning"),
            "sources": [r.source for r in status.reasons],
        }
    except Exception as exc:
        logger.debug("Failed to get execution gate status: %s", exc)
        return {"healthy": False, "error": str(exc)}


def _get_kill_switch_status() -> Dict[str, Any]:
    """Get kill switch state."""
    try:
        from merid.risk.kill_switches import risk_controller
        
        with risk_controller._lock:
            return {
                "engaged": risk_controller._global_kill,
                "reason": risk_controller._kill_reason.value if risk_controller._kill_reason else None,
                "details": risk_controller._kill_details,
                "events_count": len(risk_controller._events),
                "last_event": {
                    "reason": risk_controller._events[-1].reason.value,
                    "timestamp": risk_controller._events[-1].timestamp.isoformat(),
                } if risk_controller._events else None,
            }
    except Exception as exc:
        logger.debug("Failed to get kill switch status: %s", exc)
        return {"engaged": None, "error": str(exc)}


def _get_loop_lag_status() -> Dict[str, Any]:
    """Get loop lag monitor status (cached state only)."""
    try:
        from merid.infra.loop_lag_monitor import get_loop_lag_monitor
        
        monitor = get_loop_lag_monitor()
        if monitor is None:
            return {"healthy": False, "error": "Monitor not initialized"}
        
        health = monitor.health_check()
        stats = monitor.get_statistics()
        
        # Get monotonic timestamps for staleness detection
        now = time.monotonic()
        last_sample_ts = getattr(monitor, '_last_probe_time', None)
        samples_age_sec = now - last_sample_ts if last_sample_ts else None
        
        return {
            "healthy": health.get("healthy", False),
            "status": health.get("status", "unknown"),
            "current_lag_ms": round(monitor.get_recent_ms(), 2),
            "p50_ms": round(stats.p50_ms, 2),
            "p95_ms": round(stats.p95_ms, 2),
            "p99_ms": round(stats.p99_ms, 2),
            "max_ms": round(stats.max_ms, 2),
            "thresholds": health.get("thresholds", {}),
            "running": health.get("running", False),
            "last_ok_ts": last_sample_ts,  # Monotonic timestamp of last sample
            "samples_age_sec": round(samples_age_sec, 2) if samples_age_sec else None,
            "sample_window_count": stats.samples,
        }
    except Exception as exc:
        logger.debug("Failed to get loop lag status: %s", exc)
        return {"healthy": False, "error": str(exc)}


def _get_cfb_rti_status() -> Dict[str, Any]:
    """Get CFB RTI health status."""
    try:
        from core.execution_gate import check_cfb_rti_health
        
        result = check_cfb_rti_health()
        
        return {
            "healthy": result.get("healthy", False),
            "status": result.get("status", "unknown"),
            "adapter_type": result.get("adapter_type", "unknown"),
            "last_tick_age_sec": result.get("last_tick_age_sec"),
            "assets_tracked": result.get("assets_tracked", []),
            "error": result.get("error"),
        }
    except Exception as exc:
        logger.debug("Failed to get CFB RTI status: %s", exc)
        return {"healthy": False, "error": str(exc)}


def _get_redis_status() -> Dict[str, Any]:
    """Get Redis health status."""
    try:
        from merid.infra.redis_resilient import redis_health
        
        health = redis_health()
        
        return {
            "enabled": health.get("enabled", False),
            "healthy": health.get("healthy", False),
            "degraded_ops_count": health.get("degraded_ops_count", 0),
            "fallback_cache_size": health.get("fallback_cache_size", 0),
            "client_initialized": health.get("client_initialized", False),
            "reason": health.get("reason"),
        }
    except Exception as exc:
        logger.debug("Failed to get Redis status: %s", exc)
        return {"healthy": False, "error": str(exc)}


# Module-level cache for last portfolio integrity check result
_last_portfolio_integrity_result: Dict[str, Any] = {}
_last_portfolio_integrity_ts: float = 0.0  # Monotonic timestamp


def _update_cached_integrity_result(healthy: bool, reason: str) -> None:
    """Update cached portfolio integrity result (called by periodic checker)."""
    global _last_portfolio_integrity_result, _last_portfolio_integrity_ts
    _last_portfolio_integrity_result = {"healthy": healthy, "reason": reason}
    _last_portfolio_integrity_ts = time.monotonic()


def _get_portfolio_integrity_status() -> Dict[str, Any]:
    """Get portfolio integrity check status (cached - cheap)."""
    try:
        # Read from cached result instead of running full check
        now = time.monotonic()
        last_check_age_sec = now - _last_portfolio_integrity_ts if _last_portfolio_integrity_ts > 0 else None
        
        # Max staleness guard: 2x the scheduled interval (30s * 2 = 60s)
        MAX_STALENESS_SEC = 60.0
        
        if not _last_portfolio_integrity_result:
            # No check has run yet - try quick check without heavy validation
            from core.execution_gate import check_portfolio_integrity
            from merid.settings import settings
            
            healthy, reason = check_portfolio_integrity(
                fills_ledger=None,
                portfolio_state=None,
                risk_state=None,
                cfb_rti=None,
                settings=settings,
            )
            _update_cached_integrity_result(healthy, reason)
            last_check_age_sec = 0.0
        
        healthy = _last_portfolio_integrity_result.get("healthy", False)
        reason = _last_portfolio_integrity_result.get("reason", "")
        
        # Staleness classification
        is_stale = last_check_age_sec is not None and last_check_age_sec > MAX_STALENESS_SEC
        
        if is_stale:
            # Cache is too old - don't trust the result
            status = "unknown"
            reason = f"Cache stale: last check {last_check_age_sec:.0f}s ago (max {MAX_STALENESS_SEC}s)"
        elif not healthy:
            status = "critical"
        elif reason:
            status = "degraded"
        else:
            status = "ok"
        
        return {
            "healthy": healthy and not is_stale,
            "status": status,
            "reason": reason if reason else None,
            "last_ok_ts": _last_portfolio_integrity_ts,  # Monotonic timestamp
            "last_check_age_sec": round(last_check_age_sec, 1) if last_check_age_sec is not None else None,
            "max_staleness_sec": MAX_STALENESS_SEC,
            "is_stale": is_stale,
        }
    except Exception as exc:
        logger.debug("Failed to get portfolio integrity status: %s", exc)
        return {"healthy": False, "status": "unknown", "error": str(exc)}


def _get_scheduler_status() -> Dict[str, Any]:
    """Get background scheduler status."""
    try:
        from merid.infra.background_scheduler import get_background_scheduler
        
        scheduler = get_background_scheduler()
        health = scheduler.health_check()
        
        return {
            "running": health.get("running", False),
            "uptime_seconds": health.get("uptime_seconds", 0),
            "jobs": health.get("jobs", {}),
            "executions": health.get("executions", {}),
            "io_tasks_active": health.get("io_tasks_active", 0),
        }
    except Exception as exc:
        logger.debug("Failed to get scheduler status: %s", exc)
        return {"running": False, "error": str(exc)}


def _get_fills_ledger_status() -> Dict[str, Any]:
    """Get fills ledger status."""
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        import os
        
        fills_ledger = get_fills_ledger()
        if fills_ledger is None:
            return {"available": False}
        
        summary = fills_ledger.summary()
        strict_mode = os.environ.get("MERID_STRICT_FILL_ID", "").strip() == "1"
        
        return {
            "available": True,
            "strict_mode": strict_mode,
            "total_fills": summary.get("total_fills", 0),
            "derived_fills_pending": summary.get("derived_fills_pending", 0),
            "fills_from_http": summary.get("fills_from_http", 0),
            "fills_from_ws": summary.get("fills_from_ws", 0),
            "orphan_fills": summary.get("orphan_fills", 0),
        }
    except Exception as exc:
        logger.debug("Failed to get fills ledger status: %s", exc)
        return {"available": False, "error": str(exc)}


def _get_asset_inference_status() -> Dict[str, Any]:
    """Get asset inference tracking status."""
    try:
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        
        # Find active agent if any
        # This is a best-effort check
        return {
            "uninferable_tickers_count": 0,  # Would need access to agent instance
            "note": "Check individual agent logs for _seen_uninferable_tickers",
        }
    except Exception as exc:
        logger.debug("Failed to get asset inference status: %s", exc)
        return {"error": str(exc)}


def _calculate_overall_health(snapshot: SystemStatusSnapshot) -> Dict[str, Any]:
    """Calculate overall system health from component states."""
    is_live = snapshot.mode == "live"
    
    # Critical components that must be healthy in live mode
    critical_checks = [
        ("execution_gate", snapshot.execution_gate.get("safe_to_trade", False)),
        ("kill_switch", not snapshot.kill_switch.get("engaged", False)),
        ("loop_lag", snapshot.loop_lag.get("status") != "HALT"),
        ("cfb_rti", snapshot.cfb_rti.get("healthy", False) if is_live else True),
    ]
    
    # Degraded components (warning but not blocking)
    degraded_checks = [
        ("loop_lag", snapshot.loop_lag.get("status") == "DEGRADE"),
        ("redis", not snapshot.redis.get("healthy", True)),
        ("portfolio_integrity", snapshot.portfolio_integrity.get("status") == "degraded"),
    ]
    
    critical_failures = [name for name, ok in critical_checks if not ok]
    degraded_components = [name for name, degraded in degraded_checks if degraded]
    
    healthy = len(critical_failures) == 0
    
    return {
        "healthy": healthy,
        "state": "healthy" if healthy else ("degraded" if len(critical_failures) == 0 else "critical"),
        "trading_permitted": healthy and not snapshot.kill_switch.get("engaged", False),
        "critical_failures": critical_failures,
        "degraded_components": degraded_components,
    }


# ── API Endpoint Helper ─────────────────────────────────────────────────

def get_status_snapshot_dict() -> Dict[str, Any]:
    """Get status snapshot as dictionary (synchronous wrapper)."""
    import asyncio
    try:
        snapshot = asyncio.run(get_status_snapshot())
        return snapshot.to_dict()
    except Exception as exc:
        logger.error("Failed to generate status snapshot: %s", exc)
        return {
            "error": f"Failed to generate snapshot: {exc}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
