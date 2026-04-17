"""
MERID Agent Mesh Application - Port 8080
Internal agent-to-agent communication and coordination.
Localhost only - NOT exposed to public internet.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.ports import AGENT_MESH_PORT, get_binding
from utils.logger import get_logger

# Import agent mesh and internal API routers
from agents.mesh import router as mesh_router
from web.api.agents import router as agents_router
from web.api.reflection import router as reflection_router

logger = get_logger("web.agent_app")

# Application context
_app_context: Dict[str, Any] = {}


def create_agent_app() -> FastAPI:
    """Create the agent mesh application."""
    app = FastAPI(
        title="MERID Agent Mesh",
        version="2.0",
        description="Internal agent communication and coordination (localhost only)"
    )
    
    # CORS middleware - localhost only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Session-ID"],
    )
    
    # Security check - ensure binding is localhost only
    binding = get_binding("agent_mesh")
    if binding not in ["127.0.0.1", "localhost"]:
        raise RuntimeError(
            f"SECURITY VIOLATION: Agent mesh must bind to localhost only, got {binding}"
        )
    
    # Include agent mesh routers
    app.include_router(mesh_router)
    app.include_router(agents_router)
    app.include_router(reflection_router)
    
    @app.get("/health")
    async def health():
        """Health check for agent mesh."""
        return {"status": "ok", "service": "agent_mesh", "port": AGENT_MESH_PORT}
    
    @app.get("/")
    async def root():
        """Root endpoint - service info."""
        return {
            "service": "MERID Agent Mesh",
            "version": "2.0",
            "description": "Internal agent communication layer",
            "warning": "This service is for internal agent use only"
        }
    
    logger.info(f"Agent Mesh app created - will bind to {binding} (localhost only)")
    return app


# Create app instance
app = create_agent_app()


if __name__ == "__main__":
    import uvicorn
    binding = get_binding("agent_mesh")
    logger.info(f"Starting Agent Mesh on {binding}:{AGENT_MESH_PORT} (LOCALHOST ONLY)")
    uvicorn.run(app, host=binding, port=AGENT_MESH_PORT)
