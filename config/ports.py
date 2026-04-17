"""
Port configuration for MERID swarm architecture.

Separates concerns:
- Backend API: Main FastAPI application
- Frontend: React dashboard
- User UI: Public-facing dashboard
- Agent Mesh: Internal agent communication
- Ops Admin: System control (localhost only)
- Telemetry: Metrics export (localhost only)
"""

import os
from typing import Any, Dict


def _safe_port(env_var: str, default: int) -> int:
    """T-046: Safe port parsing — returns default on invalid env var."""
    try:
        port = int(os.getenv(env_var, str(default)))
        if 1 <= port <= 65535:
            return port
    except (TypeError, ValueError):
        pass
    return default


# Port assignments (read from env with fallbacks)
BACKEND_PORT = _safe_port("MERID_BACKEND_PORT", 8000)
FRONTEND_PORT = _safe_port("MERID_FRONTEND_PORT", 5173)
USER_UI_PORT = _safe_port("MERID_USER_UI_PORT", 3000)
AGENT_MESH_PORT = _safe_port("MERID_AGENT_MESH_PORT", 8080)
OPS_ADMIN_PORT = _safe_port("MERID_OPS_PORT", 9090)
TELEMETRY_PORT = _safe_port("MERID_TELEMETRY_PORT", 9091)

# Legacy port (to be deprecated)
LEGACY_PORT = 8001

# Port map
PORTS: Dict[str, int] = {
    "backend": BACKEND_PORT,
    "frontend": FRONTEND_PORT,
    "user_ui": USER_UI_PORT,
    "agent_mesh": AGENT_MESH_PORT,
    "ops_admin": OPS_ADMIN_PORT,
    "telemetry": TELEMETRY_PORT,
    "legacy": LEGACY_PORT,  # Temporary during migration
}

# Firewall/binding configuration
# 0.0.0.0 = public, 127.0.0.1 = localhost only
BINDINGS: Dict[str, str] = {
    "backend": "0.0.0.0",       # Public access - main API
    "frontend": "0.0.0.0",      # Public access - React dashboard
    "user_ui": "0.0.0.0",       # Public access
    "agent_mesh": "127.0.0.1",  # Localhost only - agents should not be exposed
    "ops_admin": "127.0.0.1",   # Localhost only - admin functions
    "telemetry": "127.0.0.1",   # Localhost only - Prometheus scrapes locally
    "legacy": "0.0.0.0",        # Public during migration
}

# Service descriptions
DESCRIPTIONS: Dict[str, str] = {
    "user_ui": "Public dashboard and user-facing API",
    "agent_mesh": "Internal agent-to-agent communication layer",
    "ops_admin": "System control, agent lifecycle, configuration",
    "telemetry": "Metrics aggregation and health monitoring",
}


def get_port(service: str) -> int:
    """Get port for a service."""
    if service not in PORTS:
        raise ValueError(f"Unknown service: {service}. Valid: {list(PORTS.keys())}")
    return PORTS[service]


def get_binding(service: str) -> str:
    """Get binding address for a service."""
    if service not in BINDINGS:
        raise ValueError(f"Unknown service: {service}. Valid: {list(BINDINGS.keys())}")
    return BINDINGS[service]


def get_url(service: str, host: str = "localhost") -> str:
    """Get full URL for a service."""
    port = get_port(service)
    return f"http://{host}:{port}"


def is_public(service: str) -> bool:
    """Check if service is publicly accessible."""
    return get_binding(service) == "0.0.0.0"


def get_service_info() -> Dict[str, Dict[str, Any]]:
    """Get all service information."""
    return {
        service: {
            "port": PORTS[service],
            "binding": BINDINGS[service],
            "public": is_public(service),
            "description": DESCRIPTIONS.get(service, ""),
            "url": get_url(service),
        }
        for service in PORTS.keys()
    }
