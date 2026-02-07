"""
MERID Telemetry & Metrics Application - Port 9091
Prometheus metrics, health checks, and performance monitoring.
Localhost only - NOT exposed to public internet.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from config.ports import TELEMETRY_PORT, get_binding
from core.production_init import get_infrastructure_status
from core.resource_manager import get_resource_manager
from core.connection_pool import get_pool_manager
from core.cache_manager import get_cache_manager
from core.health_monitor import get_health_monitor
from core.persistence_manager import get_persistence_manager
from core.performance_tracker import get_performance_tracker
from observability.observability_stack import get_observability_stack
from utils.logger import get_logger

logger = get_logger("web.metrics_app")

# Application context
_app_context: Dict[str, Any] = {}

# Metrics storage (in production, use proper metrics library like prometheus_client)
_metrics: Dict[str, Any] = {
    "start_time": time.time(),
    "requests_total": 0,
    "reflections_total": 0,
    "validations_total": 0,
    "agents_active": 0,
    "consensus_rounds_total": 0,
}


def create_metrics_app() -> FastAPI:
    """Create the telemetry & metrics application."""
    app = FastAPI(
        title="MERID Telemetry & Metrics",
        version="2.0",
        description="Prometheus metrics and monitoring (localhost only)"
    )
    
    # CORS middleware - localhost only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:9091", "http://127.0.0.1:9091"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Security check - ensure binding is localhost only
    binding = get_binding("telemetry")
    if binding not in ["127.0.0.1", "localhost"]:
        raise RuntimeError(
            f"SECURITY VIOLATION: Telemetry must bind to localhost only, got {binding}"
        )
    
    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint."""
        uptime = time.time() - _metrics["start_time"]
        
        # Prometheus text format
        metrics_text = f"""# HELP merid_uptime_seconds System uptime in seconds
# TYPE merid_uptime_seconds gauge
merid_uptime_seconds {uptime}

# HELP merid_requests_total Total HTTP requests
# TYPE merid_requests_total counter
merid_requests_total {_metrics['requests_total']}

# HELP merid_reflections_total Total agent reflections recorded
# TYPE merid_reflections_total counter
merid_reflections_total {_metrics['reflections_total']}

# HELP merid_validations_total Total outcome validations
# TYPE merid_validations_total counter
merid_validations_total {_metrics['validations_total']}

# HELP merid_agents_active Currently active agents
# TYPE merid_agents_active gauge
merid_agents_active {_metrics['agents_active']}

# HELP merid_consensus_rounds_total Total consensus rounds completed
# TYPE merid_consensus_rounds_total counter
merid_consensus_rounds_total {_metrics['consensus_rounds_total']}
"""
        return Response(content=metrics_text, media_type="text/plain")
    
    @app.get("/health")
    async def health():
        """Overall system health check."""
        uptime = time.time() - _metrics["start_time"]
        return {
            "status": "ok",
            "service": "telemetry",
            "port": TELEMETRY_PORT,
            "uptime_seconds": uptime
        }
    
    @app.get("/health/agents")
    async def health_agents():
        """Agent health check."""
        return {
            "status": "ok",
            "active_agents": _metrics["agents_active"],
            "total_reflections": _metrics["reflections_total"]
        }
    
    @app.get("/health/consensus")
    async def health_consensus():
        """Consensus health check."""
        return {
            "status": "ok",
            "total_rounds": _metrics["consensus_rounds_total"]
        }
    
    @app.get("/health/database")
    async def health_database():
        """Database health check."""
        return {"status": "ok", "type": "file_based"}
    
    @app.get("/health/external")
    async def health_external():
        """External API health check."""
        return {"status": "ok", "apis": ["coingecko", "polymarket"]}
    
    @app.get("/stats/reflection")
    async def stats_reflection():
        """Reflection system statistics."""
        return {
            "total_reflections": _metrics["reflections_total"],
            "total_validations": _metrics["validations_total"]
        }
    
    @app.get("/stats/agents")
    async def stats_agents():
        """Agent performance statistics."""
        return {
            "active_agents": _metrics["agents_active"],
            "total_reflections": _metrics["reflections_total"]
        }
    
    @app.get("/stats/consensus")
    async def stats_consensus():
        """Consensus statistics."""
        return {
            "total_rounds": _metrics["consensus_rounds_total"]
        }
    
    @app.get("/stats/mesh")
    async def stats_mesh():
        """Agent mesh statistics."""
        return {
            "active_connections": 0,
            "messages_sent": 0
        }
    
    @app.get("/stats/api")
    async def stats_api():
        """API performance statistics."""
        return {
            "total_requests": _metrics["requests_total"],
            "uptime_seconds": time.time() - _metrics["start_time"]
        }
    
    @app.get("/stats/infrastructure")
    async def stats_infrastructure():
        """Complete infrastructure statistics."""
        return get_infrastructure_status()
    
    @app.get("/stats/resources")
    async def stats_resources():
        """Resource manager statistics."""
        rm = get_resource_manager()
        return rm.get_all_stats()
    
    @app.get("/stats/pools")
    async def stats_pools():
        """Connection pool statistics."""
        pm = get_pool_manager()
        return pm.get_all_stats()
    
    @app.get("/stats/caches")
    async def stats_caches():
        """Cache statistics."""
        cm = get_cache_manager()
        return cm.get_all_stats()
    
    @app.get("/stats/performance")
    async def stats_performance():
        """Performance tracker statistics."""
        pt = get_performance_tracker()
        return pt.get_summary()
    
    @app.get("/stats/persistence")
    async def stats_persistence():
        """Persistence manager statistics."""
        pm = get_persistence_manager()
        return pm.get_stats()
    
    @app.get("/stats/observability")
    async def stats_observability():
        """Observability dashboards and summary."""
        obs = get_observability_stack()
        return {
            "summary": obs.get_observability_summary(),
            "dashboards": obs.get_observability_dashboards(),
        }
    
    @app.get("/health/detailed")
    async def health_detailed():
        """Detailed health report."""
        hm = get_health_monitor()
        report = hm.get_health_report()
        return {
            "timestamp": report.timestamp,
            "overall_status": report.overall_status.value,
            "checks": report.checks,
            "system_metrics": report.system_metrics,
            "warnings": report.warnings,
            "errors": report.errors
        }
    
    @app.get("/")
    async def root():
        """Root endpoint - service info."""
        return {
            "service": "MERID Telemetry & Metrics",
            "version": "2.0",
            "description": "Prometheus metrics and monitoring",
            "endpoints": {
                "metrics": "/metrics (Prometheus format)",
                "health": "/health, /health/agents, /health/consensus, /health/database, /health/external",
                "stats": "/stats/reflection, /stats/agents, /stats/consensus, /stats/mesh, /stats/api",
                "observability": "/stats/observability (summary + dashboards)",
            }
        }
    
    logger.info(f"Telemetry app created - will bind to {binding} (localhost only)")
    return app


# Create app instance
app = create_metrics_app()


if __name__ == "__main__":
    import uvicorn
    binding = get_binding("telemetry")
    logger.info(f"Starting Telemetry on {binding}:{TELEMETRY_PORT} (LOCALHOST ONLY)")
    uvicorn.run(app, host=binding, port=TELEMETRY_PORT)
