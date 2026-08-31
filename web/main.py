"""Legacy MERID web entrypoint stub.

This module is retained for compatibility with tests and tooling that still
reference ``web.main``. The production 15m entrypoint is ``web.main_15m_lean``.
"""

from __future__ import annotations

import importlib
from contextlib import suppress
from typing import Any, Optional

from fastapi import FastAPI


def _si(module_path: str) -> Any:
    """Safe import a router module and return its router object."""
    try:
        mod = importlib.import_module(module_path)
    except Exception:
        return None
    # Prefer common router variable names
    for name in ("router", "app"):
        if hasattr(mod, name):
            return getattr(mod, name)
    return None


def _reg(router: Any, app: Optional[FastAPI] = None) -> None:
    """Register a router on the current FastAPI app."""
    if router is None:
        return
    target = app or _ensure_app()
    with suppress(Exception):
        target.include_router(router)


_app: Optional[FastAPI] = None


def _ensure_app() -> FastAPI:
    """Return the module-level FastAPI app, creating it if necessary."""
    global _app
    if _app is None:
        _app = FastAPI(title="MERID Legacy Stub")
    return _app


def create_app() -> FastAPI:
    """Create and configure the legacy FastAPI app.

    Imports routers safely so that missing optional modules do not prevent
    the stub from being created in test environments.
    """
    app = _ensure_app()

    kalshi_api_router = _si("web.api.kalshi_api")
    sidebar_config_router = _si("web.api.sidebar_config")
    # Continuous-trader API wiring is optional and guarded; do not fail the app.
    kalshi_continuous_trader_api_router = _si("web.api.kalshi_continuous_trader_api")

    if kalshi_api_router is not None:
        _reg(kalshi_api_router)
    if sidebar_config_router is not None:
        _reg(sidebar_config_router)
    if kalshi_continuous_trader_api_router is not None:
        _reg(kalshi_continuous_trader_api_router)

    return app


# Backward-compatible module-level names
app = _ensure_app()
