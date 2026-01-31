"""
MERID Operations & Admin Application - Port 9090
System control, administration, and operational endpoints.
Localhost only - NOT exposed to public internet.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.ports import OPS_ADMIN_PORT, get_binding
from utils.logger import get_logger

# Import ops/admin API routers
from web.api.system_control import router as system_control_router
from web.api.ops import router as ops_router
from web.api.monitoring import router as monitoring_router
from web.api.backup import router as backup_router
from web.api.recovery import router as recovery_router
from web.api.ratelimit import router as ratelimit_router
from web.api.compliance import router as compliance_router
from web.api.governance import router as governance_router
from web.api.treasury import router as treasury_router
from web.api.archive import router as archive_router
from web.api.offline import router as offline_router
from web.api.plugins import router as plugins_router
from web.api.cost_models import router as cost_models_router
from web.api.trading_mode import router as trading_mode_router
from web.api.time_exploit import router as time_exploit_router
from web.api.sniping import router as sniping_router
from web.api.mining import router as mining_router
from web.api.prediction import router as prediction_router

logger = get_logger("web.ops_app")

# Application context
_app_context: Dict[str, Any] = {}


def create_ops_app() -> FastAPI:
    """Create the operations & admin application."""
    app = FastAPI(
        title="MERID Operations & Admin",
        version="2.0",
        description="System control and administration (localhost only)"
    )
    
    # CORS middleware - localhost only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:9090", "http://127.0.0.1:9090"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Security check - ensure binding is localhost only
    binding = get_binding("ops_admin")
    if binding not in ["127.0.0.1", "localhost"]:
        raise RuntimeError(
            f"SECURITY VIOLATION: Ops/Admin must bind to localhost only, got {binding}"
        )
    
    # Include ops/admin routers
    app.include_router(system_control_router)
    app.include_router(ops_router)
    app.include_router(monitoring_router)
    app.include_router(backup_router)
    app.include_router(recovery_router)
    app.include_router(ratelimit_router)
    app.include_router(compliance_router)
    app.include_router(governance_router)
    app.include_router(treasury_router)
    app.include_router(archive_router)
    app.include_router(offline_router)
    app.include_router(plugins_router)
    app.include_router(cost_models_router)
    app.include_router(trading_mode_router)
    app.include_router(time_exploit_router)
    app.include_router(sniping_router)
    app.include_router(mining_router)
    app.include_router(prediction_router)
    
    @app.get("/health")
    async def health():
        """Health check for ops/admin."""
        return {"status": "ok", "service": "ops_admin", "port": OPS_ADMIN_PORT}
    
    @app.get("/")
    async def root():
        """Root endpoint - service info."""
        return {
            "service": "MERID Operations & Admin",
            "version": "2.0",
            "description": "System control and administration",
            "warning": "This service is for admin use only - localhost access required"
        }
    
    logger.info(f"Ops/Admin app created - will bind to {binding} (localhost only)")
    return app


# Create app instance
app = create_ops_app()


if __name__ == "__main__":
    import uvicorn
    binding = get_binding("ops_admin")
    logger.info(f"Starting Ops/Admin on {binding}:{OPS_ADMIN_PORT} (LOCALHOST ONLY)")
    uvicorn.run(app, host=binding, port=OPS_ADMIN_PORT)
