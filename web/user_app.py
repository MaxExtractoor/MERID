"""
MERID User UI Application - Port 3000
Public-facing dashboard and user interactions.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.ports import USER_UI_PORT, get_binding
from utils.logger import get_logger

# Import user-facing API routers
from web.api.dashboard_data import router as dashboard_data_router
from web.api.live_data import router as live_data_router
from web.api.intelligence import router as intelligence_router
from web.api.predictions import router as predictions_router
from web.api.institutional import router as institutional_router
from web.api.trading import router as trading_router
from web.api.betting import router as betting_router
from web.api.wallet import router as wallet_router
from web.api.notifications import router as notifications_router
from web.api.auth import router as auth_router
from web.api.referrals import router as referrals_router
from web.api.paper_trading import router as paper_trading_router
from web.api.arbitrage import router as arbitrage_router
from web.api.schemas import router as schemas_router
from web.api.streams import router as streams_router
from web.api.live_stream import router as live_stream_router
from web.api.data_endpoints import router as data_endpoints_router
from web.api.dashboard_ws import router as dashboard_ws_router

logger = get_logger("web.user_app")

# Application context
_app_context: Dict[str, Any] = {}


def _context_value(key: str) -> Any:
    try:
        return _app_context[key]
    except KeyError as exc:
        raise RuntimeError(
            f"Application context missing '{key}'. Ensure create_user_app() was called."
        ) from exc


def _templates():
    return _context_value("templates")


def create_user_app() -> FastAPI:
    """Create the user-facing UI application."""
    app = FastAPI(
        title="MERID User Interface",
        version="2.0",
        description="Public dashboard and user interactions"
    )
    
    # Mount static files
    app.mount("/static", StaticFiles(directory="web/static"), name="static")
    
    # Initialize templates
    templates = Jinja2Templates(directory="web/templates")
    
    # Store context
    context = {
        "templates": templates,
        "allowed_origins": [
            origin.strip()
            for origin in (os.getenv("MERID_ALLOWED_ORIGINS") or "http://localhost:3000,http://127.0.0.1:3000")
            .split(",")
            if origin.strip()
        ],
    }
    _app_context.clear()
    _app_context.update(context)
    
    # CORS middleware — restrict to known origins (match web/main.py policy)
    _user_cors_origins = context["allowed_origins"] or [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_user_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-Correlation-ID"],
    )
    
    # Include user-facing API routers
    app.include_router(dashboard_data_router)
    app.include_router(live_data_router)
    app.include_router(intelligence_router)
    app.include_router(predictions_router)
    app.include_router(institutional_router)
    app.include_router(trading_router)
    app.include_router(betting_router)
    app.include_router(wallet_router)
    app.include_router(notifications_router)
    app.include_router(auth_router)
    app.include_router(referrals_router)
    app.include_router(paper_trading_router)
    app.include_router(arbitrage_router)
    app.include_router(schemas_router)
    app.include_router(streams_router)
    app.include_router(live_stream_router)
    app.include_router(data_endpoints_router)
    app.include_router(dashboard_ws_router)
    
    # HTML template routes
    @app.get("/")
    async def root():
        """Root endpoint - redirect to dashboard."""
        return RedirectResponse(url="/dashboard")
    
    @app.get("/dashboard")
    async def dashboard(request: Request):
        """Unified control center - main dashboard."""
        templates = _templates()
        return templates.TemplateResponse("unified_standalone.html", {"request": request})
    
    @app.get("/institutional")
    async def institutional_dashboard(request: Request):
        """Institutional-grade control center."""
        templates = _templates()
        return templates.TemplateResponse("institutional.html", {"request": request})
    
    @app.get("/simulation")
    async def simulation_monitor(request: Request):
        """Simulation monitor page."""
        templates = _templates()
        return templates.TemplateResponse("simulation.html", {"request": request})
    
    @app.get("/live")
    async def live_monitor(request: Request):
        """Live intelligence monitor page."""
        templates = _templates()
        return templates.TemplateResponse("live_monitor.html", {"request": request})
    
    @app.get("/trading/perps")
    async def perps_trading(request: Request):
        """Perpetual trading interface."""
        templates = _templates()
        return templates.TemplateResponse("trading_perps.html", {"request": request})
    
    @app.get("/trading/markets")
    async def prediction_markets(request: Request):
        """Prediction markets interface."""
        templates = _templates()
        return templates.TemplateResponse("trading_markets.html", {"request": request})
    
    @app.get("/betting")
    async def betting_system(request: Request):
        """Betting system interface."""
        templates = _templates()
        return templates.TemplateResponse("betting.html", {"request": request})
    
    logger.info(f"User UI app created - will bind to {get_binding('user_ui')}")
    return app


# Create app instance
app = create_user_app()


if __name__ == "__main__":
    import uvicorn
    binding = get_binding("user_ui")
    logger.info(f"Starting User UI on {binding}:{USER_UI_PORT}")
    uvicorn.run(app, host=binding, port=USER_UI_PORT)
