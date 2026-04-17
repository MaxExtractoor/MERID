"""Network Configuration — Canonical source for all host/port constants.

Import from here instead of scattering hardcoded ports across the codebase.

Usage::

    from config.network import BACKEND_PORT, FRONTEND_DEV_PORT, backend_url
"""

from __future__ import annotations

import os

# ── Backend ──────────────────────────────────────────────────────────────

# Primary FastAPI application port
BACKEND_HOST: str = os.getenv("MERID_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT: int = int(os.getenv("MERID_BACKEND_PORT", "8000"))

# Operations / metrics FastAPI app (separate process)
OPS_HOST: str = os.getenv("MERID_OPS_HOST", "127.0.0.1")
OPS_PORT: int = int(os.getenv("MERID_OPS_PORT", "8011"))

# ── Frontend (dev only) ──────────────────────────────────────────────────

# Vite dev server
FRONTEND_DEV_HOST: str = os.getenv("MERID_FRONTEND_HOST", "127.0.0.1")
FRONTEND_DEV_PORT: int = int(os.getenv("MERID_FRONTEND_PORT", "5173"))

# ── External services ────────────────────────────────────────────────────

# Kalshi REST API base (must include /trade-api/v2; see merid.event_venues.kalshi.invariants)
KALSHI_API_BASE_URL: str = os.getenv(
    "KALSHI_API_BASE_URL",
    "https://demo-api.kalshi.co/trade-api/v2",
)

# NATS message broker (for cluster deployments)
NATS_URL: str = os.getenv("NATS_URL", "nats://127.0.0.1:4222")

# Redis cache
REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

# ── Convenience helpers ──────────────────────────────────────────────────

def backend_url(path: str = "") -> str:
    """Build a full backend URL from a path fragment."""
    base = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def ops_url(path: str = "") -> str:
    """Build a full ops-app URL from a path fragment."""
    base = f"http://{OPS_HOST}:{OPS_PORT}"
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def ws_url(path: str) -> str:
    """Build a WebSocket URL for the backend."""
    return f"ws://{BACKEND_HOST}:{BACKEND_PORT}/{path.lstrip('/')}"
