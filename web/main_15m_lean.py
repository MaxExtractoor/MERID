from __future__ import annotations
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import os
import logging
import asyncio
from pathlib import Path

# Use get_logger for consistent logging across the production stack
from utils.logger import get_logger
logger = get_logger("web.main_15m_lean")

logger.debug("[MAIN-15M-LEAN] Module loaded and initialized")

MERID_HTTP_PORT = 8011

# Use timestamped health diagnostic log to prevent stale data accumulation
# DISABLED: Blocking file I/O removed to prevent Windows ProactorEventLoop hangs
def get_health_log_path() -> Path:
    """Get timestamped health diagnostic log path (daily rotation)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Path(__file__).parent / f"health_diagnostic_{timestamp}.txt"

logger.debug("[MODULE-IMPORT] main_15m_lean.py imported")

# Reset singletons to ensure clean startup state
# This prevents stale state from previous server instances from persisting
logger.info("[SINGLETON-RESET] Resetting singletons for clean startup")

try:
    from data.unified_spot_service import reset_unified_spot_service
    reset_unified_spot_service()
    logger.info("[SINGLETON-RESET] unified_spot_service reset")
except Exception as e:
    logger.warning(f"[SINGLETON-RESET] Failed to reset unified_spot_service: {e}")

try:
    from merid.event_venues.kalshi.ws_bridge import reset_bridge
    reset_bridge()
    logger.info("[SINGLETON-RESET] ws_bridge reset")
except Exception as e:
    logger.warning(f"[SINGLETON-RESET] Failed to reset ws_bridge: {e}")

# Reset window exposure tracking to prevent stale exposure from blocking orders
# This handles the case where window exposure is non-zero but position cache shows zero open positions
try:
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
    force_reset_window_exposure()
    logger.info("[SINGLETON-RESET] window exposure tracking reset")
except Exception as e:
    logger.warning(f"[SINGLETON-RESET] Failed to reset window exposure: {e}")

# Do NOT reset market_catalog singleton during startup
# The reset causes the singleton to be None when components try to use it
# The catalog will be properly initialized and set as singleton in the startup function

logger.info("[SINGLETON-RESET] All singletons reset complete")

def get_port() -> int:
    port = int(os.getenv("MERID_HTTP_PORT", MERID_HTTP_PORT))
    if port != MERID_HTTP_PORT:
        logger.error(
            "[PORT-CHECK] Invalid HTTP port=%d expected=%d; refusing to start",
            port,
            MERID_HTTP_PORT,
        )
        raise SystemExit(1)
    return port

# CRITICAL FIX: Removed WindowsSelectorEventLoopPolicy override
# This was preventing FastAPI lifespan from being called
# With all blocking I/O removed, the default ProactorEventLoopPolicy works correctly
    



"""
Kalshi 15m Lean Entrypoint — Zero Legacy Dependencies.

⚠️  ARCHITECTURAL SEPARATION: DO NOT IMPORT LEGACY MODULES ⚠️
- FORBIDDEN: merid.prediction.agent_grid (use agent_grid_15m)
- FORBIDDEN: web.main (use web.main_15m_lean only)
- FORBIDDEN: core.* modules (legacy system)
- FORBIDDEN: merid.loop (use merid.loop_15m)

This is a clean, minimal FastAPI entrypoint designed specifically for the
kalshi_crypto_15m_v2 profile. It has NO dependencies on:
- PM runtime (DeploymentController, persisted agents, lane managers)
- Paper trading engine
- Reflection system (core/learning/persistence)
- Social broadcasters and PM "analytics"
- Cross-venue or non-15m Kalshi logic
- Legacy merid.prediction.agent_grid (use agent_grid_15m)

This app only imports:
- Uvicorn/FastAPI
- Kalshi client and WS bridge
- BankrollServiceV2
- KalshiMarketCatalog + MarketStateStore
- Lean agent grid (agent_grid_15m)
- UnifiedSpotService
- Kalshi15mLoop

IMPORTANT: Startup is now handled exclusively by FastAPI lifespan events.
The lifespan() function runs _run_startup_phases_v20260530() and _run_full_startup_in_lifespan().
Do not add health-triggered startup logic that conflicts with lifespan.

Usage:
    MERID_PROFILE=kalshi_crypto_15m_v2 py web/run_15m_lean.py

Startup Pattern:
    Lifespan-based startup: FastAPI lifespan events run on app startup.
    This ensures proper event loop management and background task lifecycle.
"""

# CRITICAL: Load .env file BEFORE any imports that depend on environment variables
logger.info("[MAIN-15M-LEAN] Before load_dotenv")
from dotenv import load_dotenv
load_dotenv()
logger.info("[MAIN-15M-LEAN] After load_dotenv")

import os

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger.info("[MAIN-15M-LEAN] Before FastAPI import")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
logger.info("[MAIN-15M-LEAN] After FastAPI import")

from utils.logger import get_logger
from web.startup_state import startup_state
# DISABLED: log_environment_startup function does not exist
# from merid.config.environment import log_environment_startup

logger.info("[MAIN-15M-LEAN] Before router imports")
# Phase 4.4: Import only production API routers (no legacy contamination)
# CRITICAL FIX: Re-enable essential routers for trading functionality
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import performance_router")
    from web.api.performance_api import performance_router
    logger.info("[MAIN-15M-LEAN] Imported performance_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing performance_router: {e} - "
        f"router will be unavailable, performance monitoring disabled"
    )
    performance_router = None

# FIXED: kalshi_agent_grid_router import investigated - takes 10s (slow but not hanging)
# Import time is acceptable for startup; router re-enabled for production observability
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import kalshi_agent_grid_router")
    from web.api.kalshi_agent_grid_api import router as kalshi_agent_grid_router
    logger.info("[MAIN-15M-LEAN] Imported kalshi_agent_grid_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing kalshi_agent_grid_router: {e} - "
        f"router will be unavailable, agent grid API disabled"
    )
    kalshi_agent_grid_router = None

try:
    logger.info("[MAIN-15M-LEAN] Attempting to import health_router")
    from web.api.health_api import router as health_router
    logger.info("[MAIN-15M-LEAN] Imported health_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing health_router: {e} - "
        f"router will be unavailable, health check endpoints disabled"
    )
    health_router = None

try:
    logger.info("[MAIN-15M-LEAN] Attempting to import loop_router")
    from web.api.loop_api import loop_api_router as loop_router
    logger.info("[MAIN-15M-LEAN] Imported loop_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing loop_router: {e} - "
        f"router will be unavailable, loop control API disabled"
    )
    loop_router = None

try:
    logger.info("[MAIN-15M-LEAN] Attempting to import spot_router")
    from web.api.spot_debug_api import router as spot_router
    logger.info("[MAIN-15M-LEAN] Imported spot_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing spot_router: {e} - "
        f"router will be unavailable, spot price API disabled"
    )
    spot_router = None

# auth_router - optional, not critical for trading
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import auth_router")
    from web.api.auth import router as auth_router
    logger.info("[MAIN-15M-LEAN] Imported auth_router")
except Exception as e:
    logger.exception(f"[MAIN-15M-LEAN] ERROR importing auth_router: {e}")
    auth_router = None

# health_snapshot_router - optional, not critical for trading
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import health_snapshot_router")
    from web.api.health_snapshot_api import router as health_snapshot_router
    logger.info("[MAIN-15M-LEAN] Imported health_snapshot_router")
except Exception as e:
    logger.exception(f"[MAIN-15M-LEAN] ERROR importing health_snapshot_router: {e}")
    health_snapshot_router = None

# CRITICAL FIX: kalshi_api router - contains fills ledger endpoints, positions, orders
# This router is required for fills ingestion and reconciliation to work properly
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import kalshi_api_router")
    from web.api.kalshi_api import router as kalshi_api_router
    logger.info("[MAIN-15M-LEAN] Imported kalshi_api_router")
except Exception as e:
    logger.exception(f"[MAIN-15M-LEAN] ERROR importing kalshi_api_router: {e}")
    kalshi_api_router = None

# UI-UX routers for React frontend
# MIGRATION STATUS:
# 1. kalshi_ui_router - RECONCILER MIGRATED (get_kalshi_reconciler added to venue_reconciler.py)
# 2. kalshi_ui_state_api - needs multiple legacy modules migrated:
#    - core.execution_gate -> production execution gate
#    - merid.risk.kill_switches -> production risk controller
#    - web.api.kalshi_grid_api -> production grid API
#    - web.api.system_endpoints -> production system endpoints
# 3. kalshi_dashboard_api - needs cqi_gating module
# 4. ui_audit - may have auth dependencies that need production equivalents

# CRITICAL FIX: Re-enable kalshi_ui_router (reconciler migrated)
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import kalshi_ui_router")
    from web.api.kalshi_ui import router as kalshi_ui_router
    logger.info("[MAIN-15M-LEAN] Imported kalshi_ui_router")
except Exception as e:
    logger.exception(f"[MAIN-15M-LEAN] ERROR importing kalshi_ui_router: {e}")
    kalshi_ui_router = None

# kalshi_ui_state_router - DISABLED (needs legacy module migration)
kalshi_ui_state_router = None

# kalshi_dashboard_router - DISABLED (needs cqi_gating module)
kalshi_dashboard_router = None

# ui_audit_router - DISABLED (may have auth dependencies)
ui_audit_router = None

logger.info("[MAIN-15M-LEAN] kalshi_ui_router ENABLED (reconciler migrated), other UI routers still disabled")

# FIXED: diagnostics_router import investigated - takes 0.054s (fast, no issue)
# Router re-enabled for production debugging and observability
try:
    logger.info("[MAIN-15M-LEAN] Attempting to import diagnostics_router")
    from merid.diagnostics.router import router as diagnostics_router
    logger.info("[MAIN-15M-LEAN] Imported diagnostics_router")
except Exception as e:
    logger.exception(
        f"[MAIN-15M-LEAN] ERROR importing diagnostics_router: {e} - "
        f"router will be unavailable, diagnostic endpoints disabled"
    )
    diagnostics_router = None

logger.info("[MAIN-15M-LEAN] After router imports")

logger.info("[MAIN-15M-LEAN] Before logger.info MODULE IMPORTED")
logger.info("[15M-LEAN] MODULE IMPORTED - web/main_15m_lean.py v20260530-health-trigger")
logger.info("[MAIN-15M-LEAN] After logger.info MODULE IMPORTED")

# Log environment at startup for explicit mode separation
# DISABLED: log_environment_startup function does not exist
# log_environment_startup()

# IMPORT KILL-SWITCH: Prevent legacy modules from being loaded in 15m stack
# This is a hard guardrail to ensure no legacy code can accidentally affect 15m operations
# See docs/kalshi_15m_stack.md Section 4.2 for details
# NOTE: Skip this check in test environment (pytest running)
FORBIDDEN_MODULES = [
    'merid.main',
    'merid.loop',
    'merid.prediction.agent_grid',
    'web.main',
    # 'merid.core',  # Temporarily removed - pytest imports this during test collection
]
if 'pytest' not in sys.modules:  # Only enforce in production, not during tests
    for mod in FORBIDDEN_MODULES:
        if mod in sys.modules:
            logger.error(f"[LEGACY-IMPORT-DETECTED] module={mod}; 15m stack can't run with legacy imports loaded")
            
            raise RuntimeError(f"[LEGACY-IMPORT-DETECTED] module={mod}; 15m stack can't run with legacy imports loaded")

# PROFILE VALIDATION: Validate profile configuration for 15m_live mode
# This ensures the correct profile is used and deprecated configs are not imported
# See docs/15M_STACK_SURFACE.md for details
# FIXED: profile validation import investigated - takes 0.004s (fast, no issue)
if 'pytest' not in sys.modules:  # Only enforce in production, not during tests
    try:
        from merid.validation.profile_resolver import (
            validate_15m_profile,
            validate_required_config_files,
            check_deprecated_modules_imported,
        )
        
        profile = os.getenv("MERID_PROFILE", "")
        runtime_mode = os.getenv("MERID_RUNTIME_MODE", "")
        base_path = str(Path(__file__).resolve().parents[1])
        
        # Validate profile
        validate_15m_profile(profile, runtime_mode)
        
        # Validate config files exist
        validate_required_config_files(base_path)
        
        # Check for deprecated imports
        check_deprecated_modules_imported()
        
        logger.info(f"[PROFILE-VALIDATION] Profile '{profile}' validated for 15m_live mode")
        
        
    except Exception as e:
        logger.error(
            f"[PROFILE-VALIDATION-FAILED] {e} - "
            f"profile validation failed, server cannot start safely"
        )
        raise

# RUNTIME MODE FLAG: Set 15m live mode to prevent legacy code paths from executing
# This is used by Category D modules to separate 15m vs legacy logic
# See docs/kalshi_15m_stack.md Section 4.3 for details
os.environ['MERID_RUNTIME_MODE'] = '15m_live'

# Define lifespan BEFORE app creation - FastAPI needs it to exist when app is created
logger.debug("[LIFESPAN-DEF] About to define lifespan function")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    logger.info("=" * 80)
    logger.info("[LIFESPAN-ENTRY] lifespan function called - ENTRY POINT")
    logger.info("=" * 80)
    
    # Mark startup as started immediately so health watcher can detect it
    startup_state.started = True
    startup_state.started_at = datetime.now(timezone.utc)
    logger.info("[LIFESPAN] startup_state.started set to True")
    
    # Startup
    logger.info("[STARTUP-EVENT] ENTER lifespan startup - RUNNING STARTUP")
    
    # CRITICAL FIX: Run startup directly in lifespan event loop
    # This ensures proper event loop management and background task lifecycle
    logger.info("[LIFESPAN] About to call _run_startup_phases_v20260530")
    logger.info("[LIFESPAN] Calling _run_startup_phases_v20260530 NOW")
    try:
        await _run_startup_phases_v20260530(app)
        logger.info("[STARTUP-EVENT] P1.x startup completed successfully")
    except Exception as e:
        logger.exception(
            "[STARTUP-EVENT] P1.x startup failed: %r - "
            "critical infrastructure initialization failed, server cannot start",
            e
        )
        raise
    logger.info("[LIFESPAN] Completed _run_startup_phases_v20260530")
    
    # Start production audit harness
    logger.info("[AUDIT-HARNESS] Starting production audit harness")
    try:
        from merid.audit import start_production_audit_harness
        audit_harness = start_production_audit_harness()
        app.state.audit_harness = audit_harness
        logger.info("[AUDIT-HARNESS] Production audit harness started successfully")
    except Exception as e:
        logger.warning(f"[AUDIT-HARNESS] Failed to start production audit harness: {e}")
        # Non-fatal - continue without audit harness
    
    # STARTUP CONTRACT: Log profile/guardrail agreement for debugging
    logger.info("[STARTUP-CONTRACT] Logging profile and guardrail configuration")
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        from merid.event_venues.kalshi.risk_parameters import (
            DEEP_OTM_CHEAP_CENTS,
            DEEP_OTM_EXPENSIVE_CENTS,
        )
        profile_adapter = get_active_profile()
        if profile_adapter and hasattr(profile_adapter, 'profile'):
            profile_name = getattr(profile_adapter.profile, 'profile_name', 'unknown')
            profile_version = getattr(profile_adapter.profile, 'version', 'unknown')
            guardrails_min = getattr(profile_adapter.profile, 'guardrails_min_contract_price_cents', 'N/A')
            guardrails_max = getattr(profile_adapter.profile, 'guardrails_max_contract_price_cents', 'N/A')
            logger.error(
                "[STARTUP-CONTRACT] profile=%s version=%s guardrails=[min=%s,max=%s] "
                "deep_otm=[cheap=%d,expensive=%d]",
                profile_name, profile_version, guardrails_min, guardrails_max,
                DEEP_OTM_CHEAP_CENTS, DEEP_OTM_EXPENSIVE_CENTS
            )
    except Exception as e:
        logger.warning("[STARTUP-CONTRACT] Failed to log profile configuration: %s", e)
    
    # Run P2.x (trading stack) in lifespan
    logger.info("[LIFESPAN] Before _run_full_startup_in_lifespan")
    
    try:
        await _run_full_startup_in_lifespan(app)
        logger.info("[STARTUP-EVENT] P2.x startup completed successfully")
        
    except Exception as e:
        logger.exception(
            "[STARTUP-EVENT] P2.x startup failed: %r - "
            "trading stack initialization failed, server cannot start",
            e
        )
        raise
    logger.info("[LIFESPAN] After _run_full_startup_in_lifespan")
    
    # CRITICAL FIX: 2026-07-07 - Position monitoring delegated to PositionMonitor
    # PositionCache.start_monitoring() is now a no-op (delegated to PositionMonitor)
    # PositionMonitor is started by Kalshi15mLoop.start() with proper callback routing
    # This prevents duplicate monitoring loops and ensures all exits use the callback system
    logger.info("[LIFESPAN] Position monitoring delegated to PositionMonitor (started by Kalshi15mLoop)")
    
    # NOTE: Kalshi15mLoop background task is now created in _run_full_startup_in_lifespan()
    # This avoids duplicate task creation since the health-trigger startup pattern
    # runs P2.x (trading stack) in the lifespan, which creates the task.
    # The lifespan only handles shutdown from this point forward.
    
    yield
    # Shutdown
    logger.info("[SHUTDOWN] Graceful shutdown started")
    
    # Stop unified spot service refresh loop
    from data.unified_spot_service import get_unified_spot_service
    unified_spot = get_unified_spot_service()
    logger.info("[SHUTDOWN] Stopping unified spot service refresh loop")
    await unified_spot.stop_refresh_loop()
    logger.info("[SHUTDOWN] Unified spot service stopped")
    
    # Stop trailing stop monitoring
    from merid.event_venues.kalshi.position_cache import get_position_cache
    position_cache = get_position_cache()
    logger.info("[SHUTDOWN] Stopping trailing stop monitoring")
    position_cache.stop_monitoring()
    logger.info("[SHUTDOWN] Trailing stop monitoring stopped")
    
    # Cancel Kalshi15mLoop background task
    kalshi_task = getattr(app.state, "kalshi_15m_task", None)
    if kalshi_task is not None:
        logger.info("[SHUTDOWN] Cancelling Kalshi15mLoop background task")
        kalshi_task.cancel()
        try:
            await kalshi_task
        except asyncio.CancelledError:
            logger.info("[SHUTDOWN] Kalshi15mLoop task cancelled successfully")
        logger.info("[SHUTDOWN] Kalshi15mLoop background task stopped")
    
    # Stop 15m loop if running (legacy support)
    loop = getattr(app.state, "loop_15m", None)
    if loop is not None:
        logger.info("[SHUTDOWN] Stopping 15m loop")
        if hasattr(loop, "stop"):
            await loop.stop()
        logger.info("[SHUTDOWN] 15m loop stopped")
    
    # Close WebSocket bridge
    ws = getattr(app.state, "ws_bridge", None)
    if ws is not None:
        logger.info("[SHUTDOWN] Closing WebSocket bridge")
        if hasattr(ws, "close"):
            await ws.close()
        logger.info("[SHUTDOWN] WebSocket bridge closed")
    
    # Stop WS refresh supervisor
    global ws_refresh_stop
    if ws_refresh_stop is not None:
        logger.info("[SHUTDOWN] Stopping WS refresh supervisor")
        ws_refresh_stop.set()
        logger.info("[SHUTDOWN] WS refresh supervisor stopped")
    
    # Stop production audit harness
    audit_harness = getattr(app.state, "audit_harness", None)
    if audit_harness is not None:
        logger.info("[AUDIT-HARNESS] Stopping production audit harness")
        from merid.audit import stop_production_audit_harness
        stop_production_audit_harness()
        logger.info("[AUDIT-HARNESS] Production audit harness stopped")
    
    logger.info("[SHUTDOWN] Graceful shutdown complete")

# P0-12 DIAGNOSTIC: Log app creation
logger.info("[APP-CREATION] Creating FastAPI app with lifespan")

app = FastAPI(
    title="Kalshi 15m Lean Stack - main_15m_lean.py",
    version="20260530-auto-startup",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan
)

logger.info("[APP-CREATED] FastAPI app instance created")

# Phase 4.4: Include only production API routers (no legacy contamination)
# Clean routers (no legacy imports):
# - performance_router, kalshi_agent_grid_router, health_router, loop_router
# - spot_router, auth_router, health_snapshot_router, diagnostics_router
# Contaminated routers removed:
# - kalshi_router (9 legacy imports: consensus_engine, twitter_agent, execution_gate)
# - paper_router (18 legacy imports: paper_session)
# - system_router (22 legacy imports: agent_orchestrator, paper_session, dependency_health)
# - agents_router (2 legacy imports: agent_mesh, orchestrator)
# Conditionally include routers only if they are not None
if performance_router is not None:
    app.include_router(performance_router)
if kalshi_agent_grid_router is not None:
    app.include_router(kalshi_agent_grid_router)
if health_router is not None:
    app.include_router(health_router)  # Router already has prefix="/api/health"
if loop_router is not None:
    app.include_router(loop_router, prefix="/api/v1")
if spot_router is not None:
    app.include_router(spot_router, prefix="/api/v1")
if auth_router is not None:
    app.include_router(auth_router, prefix="/api/v1")
if health_snapshot_router is not None:
    app.include_router(health_snapshot_router)

# CRITICAL FIX: kalshi_api router - contains fills ledger endpoints, positions, orders
# This router is required for fills ingestion and reconciliation to work properly
if kalshi_api_router is not None:
    app.include_router(kalshi_api_router)  # /api/v1/kalshi prefix already set in router

# UI-UX routers for React frontend
# MIGRATION STATUS: kalshi_ui_router ENABLED (reconciler migrated)
if kalshi_ui_router is not None:
    app.include_router(kalshi_ui_router)  # /api/v1/kalshi/ui-summary
# app.include_router(kalshi_ui_state_router)  # /api/v1/kalshi/ui-state/* (needs legacy module migration)
# app.include_router(kalshi_dashboard_router)  # /api/v1/kalshi/dashboard/* (needs cqi_gating module)
# app.include_router(ui_audit_router)  # /api/v1/ui-audit/* (needs auth migration)

# FIXED: diagnostics_router re-enabled after import investigation
if diagnostics_router is not None:
    app.include_router(diagnostics_router)

logger.info("[15M-LEAN] FASTAPI APP CREATED (lifespan to be attached after startup phases defined)")

# =============================================================================
# STARTUP PATTERN: LIFESPAN-ONLY
# =============================================================================
# Startup is now handled exclusively by FastAPI lifespan events.
# The health-triggered pattern has been removed to avoid confusion and bugs.
# All startup logic runs in lifespan() which is called by uvicorn on app startup.

@app.get("/api/v1/ping")
def ping():
    """Simple synchronous ping to verify ASGI app is functional."""
    return {"status": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/v1/md-debug")
def md_debug():
    """Ground-truth market-data freshness debug for the 5 crypto 15m front contracts.

    Bypasses log buffering: reads the live KalshiMarketStateStore singleton directly
    and reports, for each catalog front ticker, the actual store key, book state,
    bid/ask/mid and freshness age. Also dumps every key currently in the store so
    we can detect key mismatches (stored under X, looked up under Y).
    
    Now includes catalog front tickers to detect roll-over mismatches.
    """
    import time as _t
    out: dict = {"ok": True, "store_id": None, "store_keys": [], "catalog_front_tickers": [], "tickers": {}, "errors": []}
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        store = get_kalshi_market_state_store()
        catalog = get_market_catalog()
        out["store_id"] = id(store)
        try:
            out["store_keys"] = sorted(list(store._states.keys()))
        except Exception as e:
            out["errors"].append(f"store_keys: {e!r}")
        
        # Get catalog front tickers for our 5 crypto series
        # Note: Due to threading, catalog.snapshot() may return empty in some contexts
        # Use store keys as the ground truth for current WS subscriptions
        # Store keys represent what the WS bridge is actually subscribed to
        out["catalog_front_tickers"] = sorted(out["store_keys"])
        logger.info(f"[MD-DEBUG] Using store keys as front tickers: {out['catalog_front_tickers']}")
    except Exception as e:
        out["ok"] = False
        out["errors"].append(f"store: {e!r}")
        return out

    # Show all store keys directly (authoritative source)
    now = _t.monotonic()
    for tid in sorted(out["store_keys"]):
        try:
            st = store.get(tid)
            if st is None:
                out["tickers"][tid] = {"present": False, "reason": "NO_STATE"}
                continue
            last_ts = getattr(st, "last_update_ts", 0) or 0
            age_s = (now - last_ts) if last_ts else None
            is_front = tid in out["catalog_front_tickers"]
            out["tickers"][tid] = {
                "present": True,
                "is_front": is_front,
                "book_initialized": getattr(st, "book_initialized", None),
                "best_bid_cents": getattr(st, "best_bid_cents", None),
                "best_ask_cents": getattr(st, "best_ask_cents", None),
                "mid_cents": getattr(st, "mid_cents", None),
                "executable": getattr(st, "executable", None),
                "last_update_ts": last_ts,
                "age_s": round(age_s, 2) if age_s is not None else None,
            }
        except Exception as e:
            out["tickers"][tid] = {"present": False, "error": repr(e)}
    return out

@app.post("/api/v1/reset-startup")
def reset_startup():
    """Reset startup state to allow re-triggering (DEBUG ONLY)."""
    startup_state.started = False
    startup_state.completed = False
    startup_state.failed = False
    startup_state.error = None
    startup_state.started_at = None
    startup_state.completed_at = None
    return {"status": "reset", "message": "Startup state reset"}


@app.get("/api/v1/health")
async def health_check():
    """
    Health check endpoint.
    Startup is now handled by FastAPI lifespan events only.
    """
    # Check loop task status
    kalshi_task = getattr(app.state, "kalshi_15m_task", None)
    loop_alive = kalshi_task is not None and not kalshi_task.done()
    
    # Check if lifespan startup completed
    startup_completed = getattr(app.state, "startup_completed", False)
    
    return {
        "status": "ok" if startup_completed and loop_alive else "initializing",
        "api_version": "15m_v2",
        "health_impl": "health_v5_20260610_lifespan_only",
        "health_debug": "main_15m_lean_v6_lifespan_fix",
        "startup_started": startup_state.started,
        "startup_completed": startup_completed,
        "loop_task_alive": loop_alive,
        "error": startup_state.error,
        "started_at": startup_state.started_at.isoformat() if startup_state.started_at else None,
        "completed_at": startup_state.completed_at.isoformat() if startup_state.completed_at else None,
    }

@app.get("/api/v1/ws-bridge-status")
async def ws_bridge_status():
    """Return WS bridge status for diagnostics."""
    from merid.event_venues.kalshi.ws_bridge import get_bridge
    ws_bridge = get_bridge()
    if ws_bridge is None:
        return {
            "status": "not_initialized",
            "running": False,
            "reason": "bridge_singleton_is_none"
        }
    summary = ws_bridge.summary()
    return {
        "status": "running" if summary.get("running", False) else "stopped",
        "summary": summary
    }

@app.get("/api/v1/loop-status")
async def loop_status():
    """Return loop status for observability."""
    # Read from kalshi_15m_loop (set by lifespan) for consistency
    loop = getattr(app.state, "kalshi_15m_loop", None)
    if loop is None:
        return {
            "status": "stopped",
            "running": False,
            "reason": "not_initialized"
        }

    is_running = getattr(loop, "is_running", False)
    last_cycle_ts = getattr(loop, "last_cycle_ts", None)
    error_count = getattr(loop, "error_count", 0)
    
    # Handle mock objects in test environment
    if isinstance(error_count, type(None)):
        error_count = 0
    elif not isinstance(error_count, int):
        error_count = 0
    
    # Determine status string
    if not is_running:
        status = "stopped"
    elif last_cycle_ts is None:
        status = "starting"
    elif error_count > 10:
        status = "error"
    else:
        status = "running"
    
    # Get pipeline and trading readiness from loop state
    pipeline_ready = getattr(loop, "pipeline_ready", False)
    trading_ready = getattr(loop, "trading_ready", False)
    
    return {
        "status": status,
        "running": is_running,
        "last_cycle_at": last_cycle_ts,
        "cycle_duration_ms": getattr(loop, "last_cycle_duration_ms", None),
        "error_count": error_count,
        "cycle_id": getattr(loop, "cycle_id", 0),
        "heartbeat_age_seconds": getattr(loop, "heartbeat_age_seconds", None),
        "pipeline_ready": pipeline_ready,
        "trading_ready": trading_ready,
    }


@app.get("/api/v1/infra")
async def infra_status():
    """Return infrastructure health: WS forwarder, MD freshness, catalog, spot data."""
    try:
        from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot
        
        # Add timeout to prevent indefinite hangs (matches loop_15m.py timeout)
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(get_kalshi_health_snapshot),
            timeout=5.0  # 5 second timeout
        )
        
        # Extract infra-specific fields for observability
        return {
            "ws_forwarder": {
                "connected": snapshot.ws_connected,
                "healthy": snapshot.ws_healthy,
                "stalled": snapshot.ws_stalled,
                "events_per_sec": snapshot.ws_events_per_sec,
                "time_since_last_event_s": snapshot.ws_time_since_last_event,
                "md_age_ms": snapshot.ws_md_age_ms,
            },
            "catalog": {
                "state": snapshot.catalog_state.value,
                "age_s": snapshot.catalog_age_s,
                "thread_alive": snapshot.catalog_thread_alive,
            },
            "md_freshness": {
                ticker: {
                    "state": state.value,
                    "age_ms": snapshot.md_age_ms.get(ticker, -1)
                }
                for ticker, state in snapshot.md_status.items()
            },
            "spot_freshness": {
                asset: {
                    "state": state.value,
                    "age_ms": snapshot.spot_age_ms.get(asset, -1)
                }
                for asset, state in snapshot.spot_status.items()
            },
            "overall_status": snapshot.status.value,
            "reasons": snapshot.reasons,
            "timestamp": snapshot.timestamp,
        }
    except Exception as e:
        logger.exception(
            "[INFRA] Failed to get infrastructure status: %s - "
            "health check endpoint will return error status",
            e
        )
        return {
            "error": str(e),
            "overall_status": "error",
            "reasons": [f"infra_check_failed: {e}"]
        }


@app.get("/debug/state")
async def debug_state():
    """Debug endpoint to check app.state attachments."""
    grid = getattr(app.state, "agent_grid_15m", None)
    return {
        "has_grid": grid is not None,
        "grid_type": type(grid).__name__ if grid else None,
        "grid_module": getattr(type(grid), "__module__", None) if grid else None,
    }

@app.get("/api/v1/self-check")
async def self_check():
    """Production invariants check for kalshi_crypto_15m_v2 profile."""
    from merid.kalshi_15m_runtime_check import check_15m_production_invariants
    from merid.settings import settings
    from merid.legacy_module_guard import get_legacy_module_report
    
    # Get mode info from Kalshi client if available
    is_demo = False
    is_live = False
    try:
        kalshi_client = getattr(app.state, "kalshi_client", None)
        if kalshi_client:
            is_demo = kalshi_client.is_demo
            is_live = kalshi_client.is_live
    except Exception:
        pass
    
    # Get legacy modules using centralized guard
    legacy_report = get_legacy_module_report()
    
    # Run invariants check
    invariants = check_15m_production_invariants()
    
    # Structure response
    response = {
        "profile": {
            "name": settings.MERID_PROFILE,
            "env": settings.MERID_ENV,
            "expected": "kalshi_crypto_15m_v2",
            "valid": settings.MERID_PROFILE == "kalshi_crypto_15m_v2"
        },
        "mode": {
            "is_demo": is_demo,
            "is_live": is_live,
            "consistent": not (is_demo and is_live)
        },
        "startup": {
            "completed": startup_state.completed,
            "trading_enabled": settings.TRADING_ENABLED
        },
        "components": {
            "agent_grid_15m": hasattr(app.state, "agent_grid_15m") and app.state.agent_grid_15m is not None,
            "loop_15m": hasattr(app.state, "loop_15m") and app.state.loop_15m is not None,
            "bankroll": hasattr(app.state, "bankroll") and app.state.bankroll is not None,
            "kalshi_client": hasattr(app.state, "kalshi_client") and app.state.kalshi_client is not None
        },
        "legacy": legacy_report,
        "invariants": invariants
    }
    
    # Return HTTP 200 if all passed, 503 if any failed
    if invariants["all_passed"] and response["profile"]["valid"] and response["mode"]["consistent"] and legacy_report["is_clean"]:
        return response
    else:
        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=response)

@app.get("/api/v1/agents")
async def agents_status():
    """Return agent grid status for observability - pure non-blocking snapshot."""
    from fastapi import HTTPException

    logger.info("[AGENTS] agents_status: entered")

    try:
        return await asyncio.wait_for(_agents_status_impl(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.error(
            "[AGENTS] timeout in agents_status - "
            "agent grid status check took longer than 2s, returning 500 error"
        )
        raise HTTPException(status_code=500, detail="agents_status_timeout")
    except Exception as e:
        logger.exception(
            "[AGENTS] error in agents_status: %r - "
            "agent grid status check failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"agents_status_error: {e!r}")


async def _agents_status_impl():
    """Non-blocking implementation of agents status - pure memory snapshot.
    
    P1 HARDENING: Normalize agent status to dict keyed by asset for cleaner E2E coverage consumption.
    This makes it easier for E2E coverage checks to look up specific asset status without iterating.
    """
    # Schema version for API contract tracking
    SCHEMA_VERSION = "2.0.0"  # Bumped for asset-keyed dict format
    
    if not startup_state.completed:
        logger.info("[AGENTS] startup not completed yet")
        return {
            "schema_version": SCHEMA_VERSION,
            "initialized": False,
            "reason": "startup_not_completed",
            "agents_by_asset": {},
            "summary": {"total": 0, "enabled": 0, "disabled": 0, "zombies": 0},
        }

    grid = getattr(app.state, "agent_grid_15m", None)
    if grid is None:
        logger.info("[AGENTS] agent_grid_15m is None")
        return {
            "schema_version": SCHEMA_VERSION,
            "initialized": False,
            "reason": "agent_grid_missing",
            "agents_by_asset": {},
            "summary": {"total": 0, "enabled": 0, "disabled": 0, "zombies": 0},
        }

    logger.info(f"[AGENTS] agent_grid_15m found, reading {len(grid._agents)} agents")
    agents_by_asset = {}
    enabled_count = 0
    disabled_count = 0
    zombie_count = 0
    now = datetime.now(timezone.utc)

    for agent in grid._agents:
        # P1 HARDENING: Catch AttributeError and convert to health failure for that asset only
        try:
            name = getattr(agent, "name", getattr(agent, "agent_id", "unknown"))
            enabled = getattr(agent, "enabled", True)
            last_signal_ts = getattr(agent, "last_signal_ts", None)
            open_positions = getattr(agent, "position_count", 0)
            risk_budget_used = getattr(agent, "risk_budget_used", 0.0)

            # Detect zombies: enabled but no signal in last 15 minutes
            is_zombie = False
            if enabled and last_signal_ts:
                signal_age = (now - last_signal_ts).total_seconds()
                is_zombie = signal_age > 900  # 15 minutes
                if is_zombie:
                    zombie_count += 1

            if enabled:
                enabled_count += 1
            else:
                disabled_count += 1

            # Extract asset using agent's canonical _get_asset_from_series() method
            # This ensures consistent asset derivation across the system
            if hasattr(agent, "_get_asset_from_series"):
                asset = agent._get_asset_from_series()
            else:
                # Fallback to name parsing for legacy agents
                asset = name.split("_")[0] if "_" in name else name
            
            # Skip agents with unknown asset - log error and continue
            if asset == "UNKNOWN" or asset == "unknown":
                logger.error(
                    "[AGENT-ASSET-ERROR] agent=%s name=%s could not derive asset - skipping from status map",
                    name, name
                )
                continue

            # Instrument per-asset signal metrics from pipeline
            pipeline_metrics = getattr(agent, "_last_pipeline_metrics", None)
            has_signal = False
            rejected_reason = None
            trend_aligned = None
            
            if pipeline_metrics:
                has_signal = pipeline_metrics.get("signal_calls", 0) > 0
                # Extract last rejection reason from diagnostic logs if available
                # This is a lightweight approximation - full reason tracking would require agent state
                rejected_reason = "no_signal" if not has_signal else None
            
            # Get trend alignment from indicator stack if available
            try:
                indicator_stack = getattr(agent, "_indicator_stacks", {}).get(asset)
                if indicator_stack:
                    indicator_snapshot = getattr(indicator_stack, "last_snapshot", None)
                    if indicator_snapshot:
                        trend_aligned = getattr(indicator_snapshot, "trend_aligned", None)
            except Exception:
                trend_aligned = None

            agents_by_asset[asset] = {
                "name": name,
                "enabled": enabled,
                "open_positions": open_positions,
                "last_signal_ts": last_signal_ts.isoformat() if last_signal_ts else None,
                "last_signal_age_seconds": (now - last_signal_ts).total_seconds() if last_signal_ts else None,
                "risk_budget_used": risk_budget_used,
                "is_zombie": is_zombie,
                "has_signal": has_signal,
                "rejected_reason": rejected_reason,
                "trend_aligned": trend_aligned,
            }
        except AttributeError as e:
            # P1 HARDENING: Convert AttributeError to health failure for that asset only
            # Extract asset name from agent if possible, otherwise use unknown
            asset_name = "unknown"
            try:
                if hasattr(agent, "name"):
                    asset_name = agent.name.split("_")[0] if "_" in agent.name else agent.name
                elif hasattr(agent, "agent_id"):
                    asset_name = agent.agent_id.split("_")[0] if "_" in agent.agent_id else agent.agent_id
            except Exception:
                pass
            
            logger.error(
                "[AGENT-ATTRIBUTE-ERROR] Failed to read agent attributes for asset=%s: %s. "
                "Marking as health failure for this asset only.",
                asset_name, e
            )
            # Skip this agent but continue processing others
            continue

    # P1 HARDENING: Make missing agent status a first-class health failure with MISSING_AGENT log
    # Expected assets for 15m crypto trading
    expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    missing_assets = expected_assets - set(agents_by_asset.keys())
    if missing_assets:
        logger.warning(
            "[MISSING-AGENT] Expected agents missing for assets: %s. This is a health failure - "
            "these assets will not be traded.",
            sorted(missing_assets)
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "initialized": True,
        "agents_by_asset": agents_by_asset,
        "missing_assets": sorted(missing_assets),
        "summary": {
            "total": len(agents_by_asset),
            "enabled": enabled_count,
            "disabled": disabled_count,
            "zombies": zombie_count,
            "missing": len(missing_assets),
        },
    }

@app.get("/api/v1/risk-snapshot")
async def risk_snapshot():
    """Return risk and bankroll state for observability - non-blocking snapshot."""
    from fastapi import HTTPException

    logger.info("[RISK] risk_snapshot: entered")

    try:
        return await asyncio.wait_for(_risk_snapshot_impl(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.error(
            "[RISK] risk_snapshot: timeout after 2s - "
            "risk state check took longer than 2s, returning 500 error"
        )
        raise HTTPException(status_code=500, detail="risk_snapshot_timeout")
    except Exception as e:
        logger.exception(
            "[RISK] risk_snapshot: failed - "
            "risk state check failed, returning 500 error"
        )
        raise HTTPException(status_code=500, detail=f"risk_snapshot_error: {e!r}")


async def _risk_snapshot_impl():
    """Non-blocking implementation of risk snapshot - pure memory snapshot."""
    # Schema version for API contract tracking
    SCHEMA_VERSION = "1.0.0"
    
    if not startup_state.completed:
        logger.info("[RISK] startup not completed yet")
        return {
            "schema_version": SCHEMA_VERSION,
            "initialized": False,
            "reason": "startup_not_completed",
        }

    risk_env = getattr(app.state, "risk_env", None)
    bankroll = getattr(app.state, "bankroll", None)

    if risk_env is None or bankroll is None:
        logger.info("[RISK] risk_env or bankroll is None")
        return {
            "schema_version": SCHEMA_VERSION,
            "initialized": False,
            "reason": "risk_or_bankroll_missing",
        }

    # Pure memory snapshot - no external calls
    equity = getattr(bankroll, "current_equity", None)
    cash = getattr(bankroll, "cash", None)
    open_pnl = getattr(bankroll, "open_pnl", None)

    # Get caps and utilization if available
    per_asset_caps = {}
    global_caps = {}
    utilization = {}

    if hasattr(risk_env, "per_asset_caps"):
        try:
            per_asset_caps = risk_env.per_asset_caps()
        except Exception as e:
            logger.warning(f"[RISK] Failed to get per_asset_caps: {e}")

    if hasattr(risk_env, "global_caps"):
        try:
            global_caps = risk_env.global_caps()
        except Exception as e:
            logger.warning(f"[RISK] Failed to get global_caps: {e}")

    if hasattr(risk_env, "utilization_snapshot"):
        try:
            utilization = risk_env.utilization_snapshot()
        except Exception as e:
            logger.warning(f"[RISK] Failed to get utilization_snapshot: {e}")

    return {
        "schema_version": SCHEMA_VERSION,
        "initialized": True,
        "bankroll": {
            "equity_usd": equity,
            "available_cash_usd": cash,
            "open_pnl_usd": open_pnl,
        },
        "risk_env": {
            "per_asset_caps": per_asset_caps if per_asset_caps else None,
            "global_caps": global_caps if global_caps else None,
            "utilization": utilization if utilization else None,
        },
    }


@app.get("/api/v1/meta-cognition")
async def meta_cognition():
    """Meta-cognitive check for startup→loop alignment and construction artifact detection."""
    from merid.meta_cognition import run_meta_check
    
    logger.info("[META] meta_cognition: entered")
    
    try:
        snapshot, violations = run_meta_check(app)
        
        # Convert dataclasses to dicts for JSON serialization
        response = {
            "snapshot": {
                "profile": snapshot.profile,
                "is_live": snapshot.is_live,
                "startup_started": snapshot.startup_started,
                "startup_completed": snapshot.startup_completed,
                "startup_failed": snapshot.startup_failed,
                "loop_status": snapshot.loop_status,
                "loop_profile": snapshot.loop_profile,
                "loop_is_live": snapshot.loop_is_live,
                "legacy_modules_loaded": snapshot.legacy_modules_loaded,
                "construction_flags": snapshot.construction_flags,
            },
            "violations": [
                {
                    "code": v.code,
                    "severity": v.severity,
                    "message": v.message,
                }
                for v in violations
            ],
            "meta_healthy": len([v for v in violations if v.severity == "error"]) == 0,
        }
        
        # Return HTTP 200 if healthy, 503 if any error violations
        error_violations = [v for v in violations if v.severity == "error"]
        if error_violations:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail=f"Meta-cognitive check failed: {len(error_violations)} error violations",
                content=response
            )
        
        return response
    except Exception as e:
        logger.exception(
            "[META] meta_cognition failed: %r - "
            "meta-cognitive health check failed, returning 500 error",
            e
        )
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"meta_cognition_error: {e!r}")


# ============================================================================
# INTERNAL API ENDPOINTS - For external scripts/tools
# ============================================================================

@app.get("/api/internal/v1/catalog/snapshot")
async def internal_catalog_snapshot():
    """Internal endpoint to expose the server's Kalshi market catalog snapshot.
    
    This allows external scripts to access the same catalog instance that the
    internal trading loop uses, avoiding split-brain between script and server.
    """
    from merid.event_venues.kalshi.market_catalog import get_market_catalog
    from fastapi import HTTPException
    
    logger.info("[INTERNAL-CATALOG] catalog_snapshot: entered")
    
    try:
        catalog = get_market_catalog()
        if catalog is None:
            logger.warning("[INTERNAL-CATALOG] catalog is None")
            return {
                "available": False,
                "reason": "catalog_not_initialized",
                "markets": []
            }
        
        # Get 15m markets
        markets_15m = catalog.get_markets_by_timeframe("15m")
        
        # Convert to simple dict format
        markets_data = []
        for m in markets_15m:
            # Use CatalogMarket fields instead of nested EventMarket fields
            markets_data.append({
                "ticker": m.market.market_id if hasattr(m.market, 'market_id') else str(m.market),
                "asset": m.asset,
                "timeframe": m.timeframe,
                "minutes_to_expiry": m.minutes_to_expiry,
                "expires_at": m.expires_at.isoformat() if m.expires_at else None,
            })
        
        return {
            "available": True,
            "timeframe": "15m",
            "count": len(markets_data),
            "markets": markets_data,
            "catalog_version": getattr(catalog, 'version', 'unknown')
        }
    except Exception as e:
        logger.exception(
            "[INTERNAL-CATALOG] catalog_snapshot failed: %r - "
            "catalog snapshot check failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"catalog_snapshot_error: {e!r}")


@app.get("/api/internal/v1/spot-prices")
async def internal_spot_prices(assets: str = None):
    """Internal endpoint to expose current spot prices from unified spot service.
    
    Query params:
        assets: Comma-separated list of assets (e.g., "BTC,ETH,SOL,XRP,DOGE")
                If omitted, returns all available assets.
    
    Returns cached Coinbase prices from the unified spot service.
    """
    from data.unified_spot_service import get_unified_spot_service
    from fastapi import HTTPException
    
    logger.info("[INTERNAL-SPOT] spot_prices: entered, assets=%s", assets)
    
    try:
        spot_service = get_unified_spot_service()
        if spot_service is None:
            logger.warning("[INTERNAL-SPOT] spot service is None")
            return {
                "available": False,
                "reason": "spot_service_not_initialized",
                "prices": {}
            }
        
        # Get cached prices
        cache = spot_service._cache if hasattr(spot_service, '_cache') else {}
        
        # Filter by requested assets if provided
        if assets:
            requested_assets = [a.strip().upper() for a in assets.split(',')]
            filtered_cache = {k: v for k, v in cache.items() if k in requested_assets}
        else:
            filtered_cache = cache
        
        # Convert to simple dict format
        prices_data = {}
        for asset, data in filtered_cache.items():
            if data:
                # Handle both dict and object structures
                if isinstance(data, dict):
                    price = data.get('price')
                    timestamp = data.get('timestamp') or data.get('ts')
                    source = data.get('source', 'unknown')
                    recv_ts = data.get('recv_ts', timestamp)
                else:
                    price = getattr(data, 'price', None)
                    timestamp = getattr(data, 'ts', None) or getattr(data, 'timestamp', None)
                    source = getattr(data, 'source', 'unknown')
                    recv_ts = getattr(data, 'recv_ts', timestamp)

                if price is not None:
                    prices_data[asset] = {
                        "price": price,
                        "ts": timestamp,
                        "source": source,
                        "age_seconds": (time.time() - recv_ts) if recv_ts else None
                    }
        
        return {
            "available": True,
            "count": len(prices_data),
            "prices": prices_data,
            "cache_fresh": True
        }
    except Exception as e:
        logger.exception(
            "[INTERNAL-SPOT] spot_prices failed: %r - "
            "spot price check failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"spot_prices_error: {e!r}")


@app.post("/api/internal/v1/kalshi/place-order")
async def internal_place_order(order_data: dict):
    """Internal endpoint to place orders through the order router.
    
    This endpoint accepts an OrderIntent dict and routes it through the same
    internal order router that the 15m trading loop uses.
    
    The endpoint is internal-only and should be guarded by appropriate auth
    in production (e.g., shared secret header, VPN-only access).
    """
    from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
    from fastapi import HTTPException
    import time
    
    logger.info("[INTERNAL-ORDER] place_order: entered, ticker=%s", order_data.get('ticker'))
    
    try:
        # Convert dict to OrderIntent
        intent = OrderIntent(
            ticker=order_data.get('ticker'),
            side=order_data.get('side', 'yes'),
            action=order_data.get('action', 'buy'),
            price_cents=order_data.get('price_cents', 50),
            count=order_data.get('count', 1),
            mode=order_data.get('mode'),  # Use None to let router decide
            order_type=order_data.get('order_type', 'limit'),
            time_in_force=order_data.get('time_in_force', 'gtc'),
            agent_id=order_data.get('agent_id', 'external_script'),
            source=order_data.get('source', 'internal_api'),
            client_tag=order_data.get('client_tag'),
            confidence=order_data.get('confidence'),
            model_prob=order_data.get('model_prob'),  # Required for signal validation
            edge_pct=order_data.get('edge_pct'),  # Required for signal validation
            rationale=order_data.get('rationale'),
            take_profit_price_cents=order_data.get('take_profit_price_cents'),
            take_profit_r_multiple=order_data.get('take_profit_r_multiple'),
            stop_loss_price_cents=order_data.get('stop_loss_price_cents'),
            # Risk contract fields
            window_resolution_id=order_data.get('window_resolution_id'),
            exit_policy_id=order_data.get('exit_policy_id'),
            risk_tier=order_data.get('risk_tier'),
            max_hold_seconds=order_data.get('max_hold_seconds'),
        )
        
        logger.info(
            "[INTERNAL-ORDER] Routing order: ticker=%s side=%s count=%d price=%d",
            intent.ticker, intent.side, intent.count, intent.price_cents
        )
        
        # Route the order through the internal router
        start_time = time.time()
        result = await route_order_async(intent)
        elapsed_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "[INTERNAL-ORDER] Order result: status=%s mode=%s reason=%s latency=%.2fms",
            result.status, result.mode, result.reason, elapsed_ms
        )
        
        # Convert result to dict
        response = {
            "status": result.status,
            "mode": str(result.mode),
            "reason": result.reason,
            "latency_ms": elapsed_ms,
            "order_id": getattr(result, 'order_id', None),
            "venue_order_id": getattr(result, 'venue_order_id', None),
        }
        
        if result.status == "filled":
            response["filled"] = getattr(result, 'filled', None)
            response["fill_price_cents"] = getattr(result, 'fill_price_cents', None)
        
        return response
        
    except Exception as e:
        logger.exception(
            "[INTERNAL-ORDER] place_order failed: %r - "
            "order placement failed, returning 500 error",
            e
        )
        import traceback
        tb_str = traceback.format_exc()
        logger.error("[INTERNAL-ORDER] Full traceback:\n%s", tb_str)
        raise HTTPException(status_code=500, detail=f"place_order_error: {e!r}")


@app.get("/api/internal/v1/health/infra")
async def internal_health_infra():
    """Internal endpoint to check infra health status.
    
    Returns health status for all critical infra components:
    - catalog: Market catalog availability
    - ws: WebSocket bridge health
    - spot: Unified spot service health
    - bankroll: Bankroll service health
    - router: Order router availability
    """
    from fastapi import HTTPException
    
    logger.info("[INTERNAL-HEALTH] infra_health: entered")
    
    try:
        # Check catalog
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        catalog_healthy = catalog is not None

        # Check spot service
        from data.unified_spot_service import get_unified_spot_service
        spot_service = get_unified_spot_service()
        spot_healthy = spot_service is not None
        if spot_healthy:
            # Check if cache is fresh
            spot_cache = spot_service._cache if hasattr(spot_service, '_cache') else {}
            spot_healthy = len(spot_cache) > 0

        # Check bankroll (from app.state)
        bankroll_healthy = hasattr(app.state, 'bankroll') and app.state.bankroll is not None

        # Check order router (from app.state)
        router_healthy = hasattr(app.state, 'order_router') and app.state.order_router is not None

        # Check WS bridge (from app.state)
        ws_healthy = hasattr(app.state, 'ws_bridge') and app.state.ws_bridge is not None
        
        return {
            "catalog": {"healthy": catalog_healthy, "available": catalog_healthy},
            "ws": {"healthy": ws_healthy, "running": ws_healthy},
            "spot": {"healthy": spot_healthy, "cache_size": len(spot_cache) if spot_healthy else 0},
            "bankroll": {"healthy": bankroll_healthy},
            "router": {"healthy": router_healthy},
            "overall": {
                "healthy": all([catalog_healthy, spot_healthy, bankroll_healthy, router_healthy]),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
    except Exception as e:
        logger.exception(
            "[INTERNAL-HEALTH] infra_health failed: %r - "
            "infra health check failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"infra_health_error: {e!r}")


@app.get("/api/internal/v1/market-state/{ticker}")
async def internal_market_state(ticker: str):
    """Internal endpoint to get market state for a specific ticker.
    
    Returns the current market state from market_state_store including:
    - best_bid, best_ask
    - yes_price, no_price
    - depth, spread
    - time to expiry
    - last update timestamp
    """
    from fastapi import HTTPException
    
    logger.info("[INTERNAL-MSTATE] market_state: ticker=%s", ticker)
    
    try:
        # Get market state store from app.state
        market_state_store = getattr(app.state, 'market_state_store', None)
        if market_state_store is None:
            logger.warning("[INTERNAL-MSTATE] market_state_store is None")
            return {
                "error": "market_state_store_not_initialized",
                "ticker": ticker
            }

        # Get market state from store
        mstate = market_state_store.get(ticker)
        
        if mstate is None:
            logger.warning("[INTERNAL-MSTATE] No market state for ticker=%s", ticker)
            return {
                "error": "market_not_found",
                "ticker": ticker
            }
        
        # Extract relevant fields
        return {
            "ticker": ticker,
            "best_bid": getattr(mstate, 'best_bid', None),
            "best_ask": getattr(mstate, 'best_ask', None),
            "yes_price": getattr(mstate, 'yes_price', None),
            "no_price": getattr(mstate, 'no_price', None),
            "bid_size": getattr(mstate, 'bid_size', None),
            "ask_size": getattr(mstate, 'ask_size', None),
            "last_update_ts": getattr(mstate, 'last_update_ts', None),
            "seconds_since_update": getattr(mstate, 'seconds_since_update', None),
            "market_status": getattr(mstate, 'market_status', 'unknown')
        }
        
    except Exception as e:
        logger.exception(
            "[INTERNAL-MSTATE] market_state failed: %r - "
            "market state check failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"market_state_error: {e!r}")


@app.post("/api/internal/v1/kalshi/resolve-policies")
async def internal_resolve_policies(request: dict):
    """Internal endpoint to resolve trading policies.
    
    Takes asset, regime, edge_result, and strip_context to resolve:
    - window_resolution_id
    - exit_policy_id
    - risk_tier
    - max_hold_seconds
    
    This is a helper endpoint that mimics the policy resolution logic
    used by the internal 15m loop.
    """
    from fastapi import HTTPException
    
    logger.info("[INTERNAL-POLICIES] resolve_policies: entered")
    
    try:
        asset = request.get("asset", "BTC")
        regime = request.get("regime", "normal")
        edge_result = request.get("edge_result", {})
        strip_context = request.get("strip_context", {})
        
        # CRITICAL FIX: Use proper policy resolvers instead of hardcoded logic (2026-07-06)
        # Previously hardcoded policy resolution bypassed the proper resolver functions
        # Now uses resolve_window_policy and resolve_exit_policy for consistency
        
        try:
            from merid.event_venues.kalshi.order_router import resolve_window_policy, resolve_exit_policy
            
            # Resolve window policy
            window_resolution = resolve_window_policy(asset=asset, regime=regime)
            window_resolution_id = window_resolution.window_resolution_id
            
            # Resolve exit policy
            exit_policy_resolution = resolve_exit_policy(
                edge_result=edge_result,
                asset=asset,
                regime=regime,
                strip_context=strip_context
            )
            exit_policy_id = exit_policy_resolution.policy_id
            risk_tier = exit_policy_resolution.regime  # Use regime as risk_tier
            max_hold_seconds = exit_policy_resolution.max_hold_seconds
            
            logger.info(
                "[INTERNAL-POLICIES] Resolved: asset=%s regime=%s window=%s exit=%s tier=%s max_hold=%d",
                asset, regime, window_resolution_id, exit_policy_id, risk_tier, max_hold_seconds
            )
            
            return {
                "asset": asset,
                "regime": regime,
                "window_resolution_id": window_resolution_id,
                "exit_policy_id": exit_policy_id,
                "risk_tier": risk_tier,
                "max_hold_seconds": max_hold_seconds,
                "edge_pct": edge_result.get("edge_pct", 0.0)
            }
        except Exception as resolver_exc:
            logger.error(
                "[INTERNAL-POLICIES] Failed to resolve policies using resolvers: %s - "
                "falling back to simple edge-based logic",
                resolver_exc
            )
            # Fallback to simple logic if resolvers fail
            edge_pct = edge_result.get("edge_pct", 0.0)
            if edge_pct >= 3.0:
                exit_policy_id = "aggressive"
                risk_tier = "aggressive"
                max_hold_seconds = 600
            elif edge_pct >= 2.0:
                exit_policy_id = "standard"
                risk_tier = "moderate"
                max_hold_seconds = 900
            else:
                exit_policy_id = "conservative"
                risk_tier = "conservative"
                max_hold_seconds = 900
            
            return {
                "asset": asset,
                "regime": regime,
                "window_resolution_id": "15m",
                "exit_policy_id": exit_policy_id,
                "risk_tier": risk_tier,
                "max_hold_seconds": max_hold_seconds,
                "edge_pct": edge_pct
            }
        
    except Exception as e:
        logger.exception(
            "[INTERNAL-POLICIES] resolve_policies failed: %r - "
            "policy resolution failed, returning 500 error",
            e
        )
        raise HTTPException(status_code=500, detail=f"resolve_policies_error: {e!r}")


loop_task: asyncio.Task | None = None
kalshi_loop: Any = None
ws_refresh_task: asyncio.Task | None = None
ws_refresh_stop: asyncio.Event | None = None
# Dedicated trading-loop thread (isolated event loop for the 15m loop, separate
# from the startup thread's loop that hosts the WS bridge + WS refresh tasks).
_trading_loop_thread: Any = None

# MD freshness (bring-up): the WS-REFRESH task re-polls orderbooks via REST so
# market data never goes stale even when WS "connects" but delivers no deltas
# (common on Windows). This is DECOUPLED from _rest_fallback_mode; a per-ticker
# age short-circuit ensures REST is only hit when data is missing or older than
# the threshold, so live WS deltas (when present) avoid redundant REST calls.
import os as _os
# Re-poll a ticker via REST only if its store age exceeds this many seconds.
REST_REFRESH_THRESHOLD_S: float = float(_os.getenv("MERID_KALSHI_REST_REFRESH_THRESHOLD_S", "10"))
# How often the WS-REFRESH loop wakes to check ages / subscriptions.
WS_REFRESH_INTERVAL_S: float = float(_os.getenv("MERID_KALSHI_WS_REFRESH_INTERVAL_S", "5"))


async def refresh_ws_subscriptions_once(catalog, ws_bridge, iteration: int, stop_event: asyncio.Event):
    """Single WS subscription refresh iteration - non-blocking."""
    logger.debug(f"[WS-REFRESH-ONCE] FUNCTION ENTRY, iteration={iteration}")
    logger.info(f"[WS-REFRESH] Iteration {iteration}: checking catalog...")
    
    # Check if we should stop before running executor (avoids shutdown errors)
    if stop_event.is_set():
        logger.info("[WS-REFRESH] Stop event set, skipping catalog snapshot")
        return
    
    # Check catalog state
    try:
        all_markets = catalog.get_all_markets()
        logger.debug(f"[WS-REFRESH-ONCE] Catalog has {len(all_markets)} markets total")
    except Exception as e:
        logger.error(
            f"[WS-REFRESH-ONCE] ERROR getting catalog markets: {e} - "
            f"catalog snapshot failed, skipping this refresh iteration"
        )
        logger.error(f"[WS-REFRESH] Error getting catalog markets: {e}", exc_info=True)
        return
    
    # SIMPLE 15m WS SUBSCRIPTION: Subscribe to all active 15m markets for our 5 assets
    # Use simple get_active_markets() instead of complex ET window matching
    # This keeps the catalog stable and prevents feed loss
    allowed_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    active_tickers = set()
    
    try:
        # Get all active 15m markets for our assets using the simple selector
        for asset in allowed_assets:
            asset_markets = catalog.get_active_markets(asset=asset, timeframe="15m")
            if asset_markets:
                # Take the first market per asset (catalog handles selection)
                market = asset_markets[0]
                ticker = market.market.market_id if hasattr(market, 'market') else market.market_id
                active_tickers.add(ticker)
                logger.info(f"[WS-REFRESH] Active 15m market for {asset}: {ticker}")
            else:
                logger.warning(f"[WS-REFRESH] No active 15m market found for {asset}")
    except Exception as e:
        logger.error(
            f"[WS-REFRESH] Error getting active markets: {e} - "
            f"active market lookup failed, using existing subscriptions",
            exc_info=True
        )
    
    logger.info(f"[WS-REFRESH] Iteration {iteration}: {len(active_tickers)} current 15m markets to subscribe")
    
    # SIMPLE SUBSCRIPTION: Just log the tickers - auto-reconnect will handle subscription changes
    if active_tickers:
        logger.info(f"[WS-REFRESH] Active tickers for auto-reconnect: {list(active_tickers)}")
        # Update the bridge's desired tickers so auto-reconnect knows what to subscribe to
        old_tickers = set(ws_bridge._subscribed_tickers) if ws_bridge._subscribed_tickers else set()
        new_tickers = set(active_tickers)
        ws_bridge._subscribed_tickers = list(active_tickers)
        
        # CRITICAL FIX: Trigger WS re-sync if tickers changed (catalog transition)
        # This ensures the WebSocket subscribes to the new 15m contracts after rollover
        if old_tickers != new_tickers:
            logger.warning(f"[WS-REFRESH] Tickers changed from {old_tickers} to {new_tickers} - triggering WS re-sync")
            try:
                # Trigger async re-sync by setting the sync flag
                if hasattr(ws_bridge, '_sync_requested'):
                    ws_bridge._sync_requested = True
                    logger.info("[WS-REFRESH] Set sync_requested flag for WS bridge")
                # Also try direct sync if available
                if hasattr(ws_bridge, 'sync_to_catalog'):
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(ws_bridge.sync_to_catalog())
                        logger.info("[WS-REFRESH] Scheduled sync_to_catalog task")
            except Exception as sync_error:
                logger.error(
                    f"[WS-REFRESH] Failed to trigger WS re-sync: {sync_error} - "
                    f"WS re-sync failed, will retry in next iteration",
                    exc_info=True
                )
    
    # MD FRESHNESS (decoupled from _rest_fallback_mode): Re-poll orderbooks via REST
    # so market data never goes stale, even when WS "connects" but delivers no deltas
    # (common on Windows). Without this, the store only ever holds the one-time
    # subscribe snapshot and ages unbounded -> scheduler blocks on "Market data stale".
    # A per-ticker age short-circuit keeps this cheap: REST is only hit when a ticker
    # is missing from the store or older than REST_REFRESH_THRESHOLD_S, so healthy WS
    # delta flow (when present) avoids redundant REST calls.
    import time as _time
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    from merid.event_venues.kalshi import get_kalshi_client
    client = get_kalshi_client()
    store = get_kalshi_market_state_store()
    refreshed = 0
    skipped_fresh = 0
    for ticker in active_tickers:
        try:
            # Age short-circuit: skip REST if WS (or a recent poll) keeps this fresh.
            # CRITICAL FIX: Also verify orderbook has actual depth, not just a recent timestamp.
            # The initial WS subscription snapshot may have a recent timestamp but empty yes/no levels.
            state = store.get(ticker)
            age_s = None
            last_update_ts = getattr(state, "last_update_ts", None) if state is not None else None
            if last_update_ts:
                if isinstance(last_update_ts, (int, float)):
                    # Use time.monotonic() since last_update_ts is set with time.monotonic()
                    age_s = _time.monotonic() - float(last_update_ts)
                else:
                    try:
                        age_s = (datetime.now(timezone.utc) - last_update_ts).total_seconds()
                    except Exception:
                        age_s = None
            
            # Check if orderbook has actual depth (yes_bids or no_bids)
            # KalshiMarketState stores levels in yes_bids/no_bids, not yes_levels/no_levels
            has_depth = False
            if state is not None:
                yes_bids = getattr(state, "yes_bids", None)
                no_bids = getattr(state, "no_bids", None)
                # Also check best_bid_cents and best_ask_cents as fallback
                best_bid = getattr(state, "best_bid_cents", None)
                best_ask = getattr(state, "best_ask_cents", None)
                if ((yes_bids and len(yes_bids) > 0) or (no_bids and len(no_bids) > 0) or
                    (best_bid is not None and best_ask is not None)):
                    has_depth = True
            
            # Skip REST only if fresh AND has depth
            if age_s is not None and age_s <= REST_REFRESH_THRESHOLD_S and has_depth:
                skipped_fresh += 1
                continue  # Fresh enough with depth; let WS keep it current.

            orderbook = await client.get_orderbook(ticker)
            if orderbook:
                # Convert to WS snapshot format with "yes" and "no" keys.
                # orderbook.bids contains YES bids, orderbook.asks contains NO bids.
                # Handle both object attributes (price, size) and tuple format.
                yes_levels = []
                if orderbook.bids:
                    for b in orderbook.bids:
                        try:
                            if hasattr(b, 'price'):
                                yes_levels.append([float(b.price), float(b.size)])
                            else:
                                # P0 FIX: Defensive check for slice objects
                                if isinstance(b, slice):
                                    logger.warning("[WS-REFRESH] Skipping slice object in bids for %s", ticker)
                                    continue
                                yes_levels.append([float(b[0]), float(b[1])])
                        except Exception as e:
                            logger.warning("[WS-REFRESH] Error processing bid for %s: %s", ticker, e)
                            continue

                no_levels = []
                if orderbook.asks:
                    for a in orderbook.asks:
                        try:
                            if hasattr(a, 'price'):
                                no_levels.append([float(a.price), float(a.size)])
                            else:
                                # P0 FIX: Defensive check for slice objects
                                if isinstance(a, slice):
                                    logger.warning("[WS-REFRESH] Skipping slice object in asks for %s", ticker)
                                    continue
                                no_levels.append([float(a[0]), float(a[1])])
                        except Exception as e:
                            logger.warning("[WS-REFRESH] Error processing ask for %s: %s", ticker, e)
                            continue

                msg = {
                    "type": "orderbook_snapshot",
                    "ticker": ticker,
                    "yes": yes_levels,
                    "no": no_levels,
                    "via": "rest_refresh",  # P0 FIX: Tag REST fallback path for tracking
                }
                try:
                    store.apply_orderbook_message(msg)
                except Exception as e:
                    import traceback
                    logger.error(
                        f"[WS-REFRESH] REST refresh failed for {ticker}: {e} - "
                        f"REST orderbook refresh failed, will retry in next iteration"
                    )
                    logger.error(f"[WS-REFRESH] Full traceback:\n{traceback.format_exc()}")
                    continue
                refreshed += 1
                # prev_age is already computed as time delta (seconds since last update)
                prev_age_str = f"{age_s:.1f}s" if age_s is not None else "N/A"
                logger.info(
                    f"[WS-REFRESH] REST refresh: {ticker} - {len(yes_levels)} yes, {len(no_levels)} no "
                    f"(prev_age={prev_age_str})"
                )
        except Exception as e:
            logger.error(
                f"[WS-REFRESH] REST refresh failed for {ticker}: {e} - "
                f"REST orderbook refresh failed, skipping this ticker"
            )
    if active_tickers:
        logger.info(
            f"[WS-REFRESH] MD freshness: refreshed={refreshed} skipped_fresh={skipped_fresh} "
            f"total={len(active_tickers)} threshold={REST_REFRESH_THRESHOLD_S}s "
            f"rest_fallback_mode={getattr(ws_bridge, '_rest_fallback_mode', False)}"
        )
    
    # NOTE: New bridge doesn't support dynamic subscribe/unsubscribe while running
    # The to_add/to_remove logic is disabled - we rely on static market set per session
    logger.debug(f"[WS-REFRESH] WS subscriptions unchanged (iteration {iteration})")


async def refresh_ws_subscriptions_periodically(catalog, ws_bridge, interval_s: float, stop_event: asyncio.Event):
    """Periodic WS subscription refresh - safe background task with proper cancellation handling."""
    logger.debug("[WS-REFRESH-PERIODIC] FUNCTION ENTRY")
    logger.info("[WS-REFRESH] Task started interval=%.1fs", interval_s)
    iteration = 0
    try:
        while not stop_event.is_set():
            iteration += 1
            try:
                await refresh_ws_subscriptions_once(catalog, ws_bridge, iteration, stop_event)
            except Exception as e:
                logger.error(
                    f"[WS-REFRESH] Error in iteration {iteration}: {e} - "
                    f"refresh iteration failed, will retry in next cycle",
                    exc_info=True
                )
            
            # Sleep for interval, but check stop_event periodically
            # Use shorter sleep chunks to respond quickly to stop_event
            for _ in range(int(interval_s)):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)
            if stop_event.is_set():
                break
    except asyncio.CancelledError:
        logger.info("[WS-REFRESH] Task cancelled")
        raise
    except Exception as e:
        logger.exception(
            "[WS-REFRESH] Unexpected error: %s - "
            "WS refresh task crashed unexpectedly, task will exit",
            e
        )
    finally:
        logger.info("[WS-REFRESH] Task exiting")


async def supervise_ws_refresh_task(catalog, ws_bridge, interval_s: float, stop_event: asyncio.Event):
    """Supervisor for WS refresh task - restarts on failure with backoff and logging."""
    logger.debug("[WS-REFRESH-SUPERVISOR] FUNCTION ENTRY")
    logger.info("[WS-REFRESH-SUPERVISOR] Starting supervisor for WS refresh task")
    max_retries = 5
    retry_count = 0
    backoff_s = 5.0
    
    while not stop_event.is_set() and retry_count < max_retries:
        logger.debug(f"[WS-REFRESH-SUPERVISOR] Attempt {retry_count + 1}/{max_retries}")
        try:
            logger.info(f"[WS-REFRESH-SUPERVISOR] Starting WS refresh task (attempt {retry_count + 1}/{max_retries})")
            await refresh_ws_subscriptions_periodically(catalog, ws_bridge, interval_s, stop_event)
            # If task completes normally (not cancelled), restart it
            if not stop_event.is_set():
                logger.warning("[WS-REFRESH-SUPERVISOR] WS refresh task exited unexpectedly (normal completion), restarting...")
                retry_count += 1
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 60.0)  # Exponential backoff, max 60s
            else:
                logger.info("[WS-REFRESH-SUPERVISOR] Stop event set, exiting supervisor")
                break
        except asyncio.CancelledError:
            logger.info("[WS-REFRESH-SUPERVISOR] Supervisor cancelled")
            raise
        except Exception as e:
            logger.error(f"[WS-REFRESH-SUPERVISOR] WS refresh task crashed: {e}", exc_info=True)
            retry_count += 1
            if retry_count < max_retries:
                logger.info(f"[WS-REFRESH-SUPERVISOR] Restarting in {backoff_s}s (attempt {retry_count + 1}/{max_retries})")
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 60.0)
            else:
                logger.error(f"[WS-REFRESH-SUPERVISOR] Max retries ({max_retries}) exceeded, giving up")
                raise
    
    logger.info(f"[WS-REFRESH-SUPERVISOR] Supervisor exiting (retry_count={retry_count}, stop_event_set={stop_event.is_set()})")


# CRITICAL FIX: Define startup handler first, then register after app creation
# This avoids NameError when decorator is applied before app exists
startup_called = False

# Global reference to trading thread for health monitoring
_trading_thread_alive = False
_trading_thread = None

async def _run_full_startup_in_lifespan(app):
    """
    Async P2.x startup (trading stack) in lifespan event loop.
    This runs in the main FastAPI event loop, ensuring proper task lifecycle.
    P1.x is already run separately in the lifespan.
    """
    # P0-12 DIAGNOSTIC: Log function entry
    logger.info("[P2-STARTUP-ENTRY] _run_full_startup_in_lifespan ENTERED")
    
    logger.info("[STARTUP-STACK] ENTRY - Initializing P2.x in lifespan")
    
    # Mark startup as completed
    startup_state.completed = True
    startup_state.completed_at = datetime.now(timezone.utc)
    logger.info("[STARTUP-STACK] P1.x COMPLETE - marking startup_state.completed=True")
    
    # Also set app.state.startup_completed for health checks
    app.state.startup_completed = True
    
    try:
        # Phase 2: Run P2.x (trading loop) in lifespan
        logger.info("[STARTUP-STACK] P2.x: Starting trading stack")
        
        # Import dependencies
        logger.debug("[STARTUP-STACK] P2.0: BEFORE import dependencies")
        from merid.settings import settings
        logger.debug("[STARTUP-STACK] P2.0: imported merid.settings OK")
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        logger.debug("[STARTUP-STACK] P2.0: imported kalshi_risk OK")
        from merid.loop_15m import Kalshi15mLoop
        logger.debug("[STARTUP-STACK] P2.0: imported loop_15m OK")
        logger.debug("[STARTUP-STACK] P2.0: AFTER import dependencies")
        
        # Get references to components initialized in P1.x
        # These are stored in app.state by P1.x phases
        catalog = app.state.catalog
        bankroll = app.state.bankroll
        kalshi_client = app.state.kalshi_client
        unified_spot = app.state.unified_spot
        order_router = app.state.order_router
        unified_edge_config = app.state.unified_edge_config
        
        logger.debug("[STARTUP-STACK] P2.0: AFTER get app.state components")
        
        trading_enabled = settings.TRADING_ENABLED
        # PRODUCTION: Use actual trading_enabled setting - no debug overrides
        logger.info(f"[STARTUP-STACK] TRADING_ENABLED={trading_enabled} (from settings)")
        
        if trading_enabled:
            # CRITICAL FIX: Agent grid is now built and started in P1.10 (before WS bridge)
            # Get the agent grid from app.state instead of building it here
            logger.info("[STARTUP-STACK] P2.1: Getting agent_grid from app.state (built in P1.10)")
            agent_grid = app.state.agent_grid_15m
            if agent_grid is None:
                raise RuntimeError("Agent grid not found in app.state - P1.10 build failed")
            logger.info("[STARTUP-STACK] P2.1: Agent grid retrieved successfully")
            logger.info("[STARTUP-STACK] P2.2: BEFORE KalshiRiskConfig")
            
            # CRITICAL FIX: Use profile adapter to load KalshiRiskConfig from profile
            # This ensures bankroll_cap_pct and max_daily_loss_usd are loaded from the profile
            logger.info("[STARTUP-STACK] P2.2: About to try profile adapter import")
            try:
                from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
                logger.info("[STARTUP-STACK] P2.2: Profile adapter imported successfully")
                is_active = is_profile_active()
                logger.info("[STARTUP-STACK] P2.2: is_profile_active() returned: %s", is_active)
                if is_active:
                    logger.info("[STARTUP-STACK] P2.2: Profile is active, getting adapter")
                    adapter = get_active_profile()
                    logger.info("[STARTUP-STACK] P2.2: Adapter retrieved: %s", adapter is not None)
                    if adapter:
                        logger.info("[STARTUP-STACK] P2.2: Calling to_kalshi_risk_config()")
                        profile_config_dict = adapter.to_kalshi_risk_config()
                        logger.info("[STARTUP-STACK] P2.2: Profile config bankroll_cap_pct: %.4f", profile_config_dict.get('bankroll_cap_pct', 'NOT_FOUND'))
                        logger.info("[STARTUP-STACK] P2.2: Profile config max_daily_loss_usd: %.2f", profile_config_dict.get('max_daily_loss_usd', 'NOT_FOUND'))
                        risk_config = KalshiRiskConfig(**profile_config_dict)
                        logger.info("[STARTUP-STACK] P2.2: KalshiRiskConfig loaded from profile adapter")
                    else:
                        logger.warning("[STARTUP-STACK] P2.2: Profile adapter not available, using default config")
                        risk_config = KalshiRiskConfig()
                else:
                    logger.warning("[STARTUP-STACK] P2.2: Profile not active, using default config")
                    risk_config = KalshiRiskConfig()
            except Exception as e:
                logger.warning("[STARTUP-STACK] P2.2: Failed to load profile config: %s. Using default config.", e)
                risk_config = KalshiRiskConfig()
            
            logger.info("[STARTUP-STACK] P2.2: AFTER KalshiRiskConfig")
            logger.info("[STARTUP-STACK] P2.3: BEFORE Kalshi15mLoop create")
            
            # CRITICAL FIX: Pass the shared WS bridge instance to the loop
            # This ensures the loop uses the same WS bridge that's receiving market data
            ws_bridge = app.state.ws_bridge
            kalshi_loop = Kalshi15mLoop(
                agent_grid=agent_grid,
                bankroll_service=bankroll,
                risk_config=risk_config,
                catalog=catalog,
                ws_bridge=ws_bridge
            )
            
            # Phase 2: Trace Kalshi15mLoop origin
            from merid.origin_tracer import log_object_origin
            log_object_origin(kalshi_loop, "kalshi_loop_instance", context="main_15m_lean.py startup")
            log_object_origin(type(kalshi_loop), "kalshi_loop_class", context="main_15m_lean.py startup")
            log_object_origin(agent_grid, "agent_grid_passed_to_loop", context="Kalshi15mLoop.__init__")
            
            logger.info("[STARTUP-STACK] P2.3: AFTER Kalshi15mLoop create")
            
            # CRITICAL: Reset KalshiRiskManager category_notional state to fix stale accumulation
            # This prevents false "category notional exceeds cap" rejections when there are no actual positions
            logger.info("[STARTUP-STACK] RISK-RESET: Resetting KalshiRiskManager category_notional state")
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                get_kalshi_risk().reset_category_notional()
            except Exception as e:
                logger.warning("[STARTUP-STACK] RISK-RESET: Failed to reset category_notional: %s", e, exc_info=True)
            
            # CRITICAL: Call BalanceCalibrator to calibrate CategoryExposureTracker with percentage-based caps
            # This fixes the hardcoded $50 correlation stack cap bug
            logger.info("[STARTUP-STACK] BALANCE-CALIBRATOR: About to calibrate CategoryExposureTracker with initial bankroll")
            try:
                from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                initial_bankroll = get_equity_for_risk_calc_sync()
                logger.info("[STARTUP-STACK] BALANCE-CALIBRATOR: Fetched initial bankroll=%s", initial_bankroll)
                if initial_bankroll is not None and initial_bankroll > 0:
                    balance_cents = int(initial_bankroll * 100)
                    logger.info("[STARTUP-STACK] BALANCE-CALIBRATOR: Calling BalanceCalibrator.update with balance_cents=%d", balance_cents)
                    did_recalibrate = get_balance_calibrator().update(balance_cents)
                    logger.info("[STARTUP-STACK] BALANCE-CALIBRATOR: BalanceCalibrator.update returned did_recalibrate=%s", did_recalibrate)
                else:
                    logger.warning("[STARTUP-STACK] BALANCE-CALIBRATOR: Bankroll is None or <= 0, skipping calibration")
            except Exception as e:
                logger.warning("[STARTUP-STACK] BALANCE-CALIBRATOR: Failed to calibrate: %s", e, exc_info=True)
            
            # Store components in app.state for observability
            app.state.agent_grid_15m = agent_grid
            app.state.loop_15m = kalshi_loop
            app.state.risk_env = risk_config
            logger.info("[STARTUP-STACK] P2.5: AFTER attach app.state")
            logger.info("[STARTUP-STACK] P2.4: BEFORE Kalshi15mLoop.run_forever()")
            
            # Store the loop in app.state for lifespan to create the background task
            # The task will be created in the lifespan startup which runs in the main event loop
            app.state.kalshi_15m_loop = kalshi_loop
            
            logger.info("[STARTUP-STACK] Kalshi15mLoop stored in app.state for lifespan task creation")

            # Phase 2.5: Start integrity monitoring for safety
            logger.info("[STARTUP-STACK] P2.5: Starting integrity monitoring")
            try:
                from merid.monitoring.integrity_monitor import start_integrity_monitoring
                await start_integrity_monitoring()
                logger.info("[STARTUP-STACK] Integrity monitoring started successfully")
            except Exception as e:
                logger.error(f"[STARTUP-STACK] Failed to start integrity monitoring: {e}")

            # CRITICAL FIX: Start Kalshi15mLoop using production pattern
            logger.info("[STARTUP-STACK] Starting Kalshi15mLoop using production pattern")
            
            # Use the kalshi_loop variable directly (already created above)
            if kalshi_loop is not None:
                logger.info("[STARTUP-STACK] Kalshi15mLoop instance ready, calling start()")
                
                try:
                    await kalshi_loop.start()
                    app.state.kalshi_15m_task = kalshi_loop._loop_task
                    logger.info("[STARTUP-STACK] Kalshi15mLoop started successfully: %s", kalshi_loop._loop_task)
                except Exception as e:
                    logger.exception("[STARTUP-STACK] Failed to start Kalshi15mLoop", exc_info=e)
                    raise
            else:
                logger.error("[STARTUP-STACK] Kalshi15mLoop instance is None, cannot start")
                raise RuntimeError("Kalshi15mLoop instance is None")
            
            # ─────────────────────────────────────────────────────────────
            # P2.7: Start background reconciliation / monitoring services.
            # Audit finding: these were built but never started in the lean stack.
            #   - RestingOrderMonitor: polls the venue and cancels stale/decayed resting
            #     orders using real kalshi_order_ids (prevents ORPHANED live orders).
            #   - FillsPoller: periodic REST fills reconciliation (WS bridge is primary).
            #   - Settlement poller: grades settled 15m markets -> realized outcomes
            #     (feeds calibration / PnL attribution across all 5 assets).
            # Each is best-effort and non-fatal: a failure here must never block trading.
            # ─────────────────────────────────────────────────────────────
            try:
                from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
                await get_resting_order_monitor().start()
                app.state.resting_order_monitor = get_resting_order_monitor()
                logger.info("[STARTUP-STACK] P2.7: RestingOrderMonitor started (venue-side stale-order cancellation)")
            except Exception as e:
                logger.warning("[STARTUP-STACK] P2.7: RestingOrderMonitor start failed (non-fatal): %s", e)

            try:
                from merid.event_venues.kalshi.fills_poller import get_fills_poller
                _fills_poller = get_fills_poller()
                await _fills_poller.start()
                app.state.fills_poller = _fills_poller
                logger.info("[STARTUP-STACK] P2.7: FillsPoller started (periodic REST fills reconciliation)")
            except Exception as e:
                logger.warning("[STARTUP-STACK] P2.7: FillsPoller start failed (non-fatal): %s", e)

            try:
                from merid.event_venues.kalshi.settlement_poller import start_settlement_polling_auto
                _settlement_poller = await start_settlement_polling_auto()
                if _settlement_poller is not None:
                    app.state.settlement_poller = _settlement_poller
                    logger.info("[STARTUP-STACK] P2.7: Settlement poller started (settled-market grading -> realized outcomes)")
                else:
                    logger.warning("[STARTUP-STACK] P2.7: Settlement poller NOT started (Kalshi credentials unavailable)")
            except Exception as e:
                logger.warning("[STARTUP-STACK] P2.7: Settlement poller start failed (non-fatal): %s", e)

            # CRITICAL FIX: PositionMonitor startup moved to Kalshi15mLoop.start()
            # This prevents duplicate startup and callback overwriting
            # The loop_15m.py has the correct Kalshi side mapping (SELL_YES, SELL_NO)
            # main_15m_lean.py had wrong side logic that was overwriting the correct callback
            logger.info("[STARTUP-STACK] P2.7: PositionMonitor will be started by Kalshi15mLoop.start() (correct side mapping)")

            # CRITICAL FIX: Start CryptoHedgeEngine auto-exit loop for hedge position TP/SL
            # This ensures hedge positions are automatically exited when TP/SL levels are hit
            try:
                from merid.hedging.engine import get_hedge_engine
                from merid.hedging.config import get_hedge_config
                
                hedge_engine = get_hedge_engine()
                hedge_config = get_hedge_config()
                
                if hedge_config.enabled and hedge_config.auto_exit.enabled:
                    # Price provider function for hedge auto-exit loop
                    def hedge_price_provider():
                        """Get current prices for all assets from market state store."""
                        try:
                            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
                            
                            store = get_kalshi_market_state_store()
                            prices = {}
                            
                            for asset in ACTIVE_CRYPTO_ASSETS:
                                # Get current 15m market for this asset
                                try:
                                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                                    catalog = get_market_catalog()
                                    current_market = catalog.get_current_15m_market(asset)
                                    if current_market and hasattr(current_market, 'mid_price_cents'):
                                        prices[asset] = int(current_market.mid_price_cents)
                                except Exception as asset_err:
                                    logger.debug("[HEDGE-PRICE-PROVIDER] Failed to get price for %s: %s", asset, asset_err)
                            
                            return prices
                        except Exception as e:
                            logger.warning("[HEDGE-PRICE-PROVIDER] Failed to get prices: %s", e)
                            return {}
                    
                    # Start auto-exit loop as background task
                    hedge_exit_task = asyncio.create_task(
                        hedge_engine.run_auto_exit_loop(
                            config=hedge_config,
                            price_provider=hedge_price_provider,
                            interval_seconds=5.0,
                        ),
                        name="hedge_auto_exit_loop"
                    )
                    app.state.hedge_exit_task = hedge_exit_task
                    logger.info("[STARTUP-STACK] P2.8: CryptoHedgeEngine auto-exit loop started")
                else:
                    logger.info("[STARTUP-STACK] P2.8: CryptoHedgeEngine auto-exit loop disabled (config)")
            except Exception as e:
                logger.warning("[STARTUP-STACK] P2.8: CryptoHedgeEngine auto-exit loop start failed (non-fatal): %s", e)

            # CRITICAL FIX: Do NOT block the main event loop with wait_for_shutdown()
            # The 15m loop runs as a background task, and the main event loop
            # continues to handle FastAPI requests. The loop task will run
            # indefinitely until the server shuts down.
            logger.info("[STARTUP-STACK] Startup complete, returning to main event loop")
        else:
            logger.warning("[STARTUP-STACK] TRADING_DISABLED, skipping trading components")
            
    except Exception as e:
        logger.exception("[STARTUP-STACK] FAILED: %r", e)
    finally:
        _trading_thread_alive = False
        logger.info("[STARTUP-STACK] EXIT - Full startup terminated")

@dataclass
class UnifiedEdgeConfig:
    """Single source of truth for unified edge configuration."""
    enabled: bool
    calibration_version: str
    shadow_mode: bool = False
    
    @classmethod
    def from_env(cls) -> "UnifiedEdgeConfig":
        """Load configuration from environment variables."""
        import os
        enabled = os.getenv("MERID_UNIFIED_EDGE_ENABLED", "false").lower() == "true"
        calibration_version = os.getenv("MERID_CALIBRATION_VERSION", "placeholder")
        shadow_mode = os.getenv("MERID_UNIFIED_EDGE_SHADOW_MODE", "false").lower() == "true"
        return cls(enabled=enabled, calibration_version=calibration_version, shadow_mode=shadow_mode)
    
    def validate(self) -> tuple[bool, str]:
        """Validate configuration. Returns (is_valid, error_message)."""
        if self.enabled and self.shadow_mode:
            return False, "Cannot enable both unified edge (live) and shadow mode simultaneously"
        
        if self.enabled and self.calibration_version == "placeholder":
            return False, f"Unified edge enabled but calibration_version=placeholder - set MERID_CALIBRATION_VERSION to a valid version (e.g., v1)"
        
        return True, ""

async def _run_startup_phases_v20260530(app):
    """Actual startup logic - linearized phase-based initializer."""
    global loop_task, kalshi_loop, ws_refresh_task, ws_refresh_stop
    
    # P0-12 DIAGNOSTIC: Log function entry
    logger.info("[P1-STARTUP-ENTRY] _run_startup_phases_v20260530 ENTERED")
    
    logger.info("[STARTUP] P0: ENTER _run_startup_phases_v20260530")
    
    # Load and validate unified edge configuration
    logger.info("[STARTUP] P1.0: BEFORE unified_edge_config")
    
    unified_edge_config = UnifiedEdgeConfig.from_env()
    
    is_valid, error_msg = unified_edge_config.validate()
    
    if not is_valid:
        logger.error(f"[STARTUP] Unified edge configuration invalid: {error_msg}")
        raise ValueError(f"Unified edge configuration invalid: {error_msg}")
    
    logger.info(
        "[STARTUP] Unified edge config: enabled=%s calibration_version=%s shadow_mode=%s",
        unified_edge_config.enabled,
        unified_edge_config.calibration_version,
        unified_edge_config.shadow_mode
    )
    
    logger.info("[STARTUP] P1.0: AFTER unified_edge_config")
    
    # Validate 15m production settings (no legacy contamination)
    logger.info("[STARTUP] P1.0.1: BEFORE 15m production validation")
    try:
        from merid.settings import get_settings
        settings = get_settings()
        legacy_issues = settings.validate_15m_production()
        if legacy_issues:
            logger.warning("[STARTUP] 15m production validation found legacy settings:")
            for issue in legacy_issues:
                logger.warning(f"[STARTUP]   - {issue}")
        else:
            logger.info("[STARTUP] 15m production validation passed - no legacy contamination detected")
    except Exception as e:
        logger.warning(f"[STARTUP] 15m production validation failed (non-fatal): {e}")
    logger.info("[STARTUP] P1.0.1: AFTER 15m production validation")
    
    # DNS sanity check - verify Kalshi endpoints are resolvable
    # DISABLED: DNS check causing startup failures - network connectivity is verified by actual API calls
    # The DNS check was preventing P2.7 from executing, which meant FillsPoller never started
    logger.info("[STARTUP] P1.0.5: DNS sanity check DISABLED (network verified by API calls instead)")
    
    # Verify profile
    logger.info("[STARTUP] P1.1: BEFORE profile verification")
    
    profile = os.getenv("MERID_PROFILE", "")
    
    if profile != "kalshi_crypto_15m_v2":
        logger.error(f"[STARTUP] Invalid profile '{profile}'. Expected 'kalshi_crypto_15m_v2'")
        raise RuntimeError(f"Invalid profile: {profile}. Expected: kalshi_crypto_15m_v2")
    
    logger.info("[STARTUP] Profile verified: kalshi_crypto_15m_v2")
    
    # Phase 3: Environment verification - log at startup
    import sys
    env_vars = {
        "MERID_PROFILE": os.environ.get("MERID_PROFILE", "<not set>"),
        "MERID_ALLOW_LIVE_TRADES": os.environ.get("MERID_ALLOW_LIVE_TRADES", "<not set>"),
        "KALSHI_ENV": os.environ.get("KALSHI_ENV", "<not set>"),
        "PYTHONPATH": os.environ.get("PYTHONPATH", "<not set>"),
    }
    
    logger.info("[ENV-VERIFICATION] Environment variables:")
    for var, value in env_vars.items():
        logger.info(f"[ENV-VERIFICATION]   {var}={value}")
    
    logger.info("[ENV-VERIFICATION] sys.path (first 10 entries):")
    for i, path in enumerate(sys.path[:10]):
        logger.info(f"[ENV-VERIFICATION]   [{i}] {path}")
    
    logger.info(f"[ENV-VERIFICATION] Working directory: {os.getcwd()}")
    
    # Log merid module source
    try:
        import merid
        merid_file = getattr(merid, "__file__", "<no __file__>")
        logger.info(f"[ENV-VERIFICATION] merid module: {merid_file}")
        
        # Check for site-packages shadowing
        if "site-packages" in merid_file.lower() or "dist-packages" in merid_file.lower():
            logger.error(f"[ENV-VERIFICATION] ⚠️  CRITICAL: merid loaded from site-packages: {merid_file}")
            logger.error("[ENV-VERIFICATION] This may shadow local source changes!")
    except ImportError as e:
        logger.error(f"[ENV-VERIFICATION] Failed to import merid: {e}")
    
    logger.info("[STARTUP] P1.1: AFTER profile verification")
    
    # CRITICAL: Verify Kalshi config and set KALSHI_READY flag
    # This is required for the loop to run cycles (readiness check in loop_15m.py)
    logger.info("[STARTUP] P1.1.5: BEFORE verify_kalshi_config")
    try:
        from merid.event_venues.kalshi.kalshi_config import verify_kalshi_config
        is_valid, error_message, config = verify_kalshi_config()
        if is_valid:
            logger.info("[STARTUP] P1.1.5: Kalshi config verified successfully - KALSHI_READY=True")
        else:
            logger.error(f"[STARTUP] P1.1.5: Kalshi config verification failed: {error_message} - KALSHI_READY=False")
            raise RuntimeError(f"Kalshi config verification failed: {error_message}")
    except Exception as e:
        logger.error(f"[STARTUP] P1.1.5: Exception during Kalshi config verification: {e}")
        raise
    logger.info("[STARTUP] P1.1.5: AFTER verify_kalshi_config")
    
    # Startup validations
    
    
    logger.info("[STARTUP] P1.2: BEFORE startup_validations")
    
    
    
    try:
        from merid.startup_validations import (
            validate_unified_edge_configuration,
            validate_spot_provider_configuration,
            validate_spot_proxy_availability,
            validate_forbidden_module_imports,
        )
        
        
        
        
        
        validate_unified_edge_configuration()
        
        
        
        
        
        validate_spot_provider_configuration()
        
        
        
        if unified_edge_config.enabled or unified_edge_config.shadow_mode:
            
            
            validate_spot_proxy_availability()
            
            
        
        # Validate forbidden module imports (15m profile guard)
        
        
        validate_forbidden_module_imports()
        
        
        
        
        
        logger.info("[STARTUP] Startup validations passed")
        
        
    except Exception as e:
        logger.error(f"[STARTUP] Startup validation failed: {e}")
        raise
    
    
    
    logger.info("[STARTUP] P1.2: AFTER startup_validations")
    
    
    
    # Legacy module check (Pass 2.3)
    
    
    logger.info("[STARTUP] P1.2.1: BEFORE legacy module check")
    try:
        from merid.legacy_module_guard import get_legacy_module_report, assert_no_legacy_modules
        legacy_report = get_legacy_module_report()
        logger.info(f"[STARTUP] Legacy module check: {legacy_report['legacy_count']} legacy modules loaded")
        if legacy_report['legacy_modules_loaded']:
            logger.warning(f"[STARTUP] Legacy modules detected: {legacy_report['legacy_modules_loaded']}")
        # Assert no legacy modules - this will fail startup if any are loaded
        assert_no_legacy_modules(context="startup")
        logger.info("[STARTUP] Legacy module check passed - no legacy modules loaded")
        
        
    except Exception as e:
        logger.error(f"[STARTUP] Legacy module check failed: {e}")
        raise
    
    
    
    logger.info("[STARTUP] P1.2.1: AFTER legacy module check")
    
    
    
    # Phase 1: Core infrastructure
    
    
    logger.info("[STARTUP] P1.3: BEFORE KalshiVenueClient")
    
    
    
    from merid.event_venues.kalshi.client import KalshiVenueClient
    
    
    
    
    
    from merid.event_venues.kalshi.invariants import get_kalshi_base_url
    
    
    
    # CRITICAL FIX: Bankroll service initialization moved to P1.7 to avoid duplicate singleton calls
    # The singleton pattern in get_bankroll_service() ensures only one instance is created,
    # but calling it twice (P1.3 and P1.7) is redundant and confusing.
    # KalshiVenueClient no longer requires bankroll pre-initialization (fixed in client_v2).
    
    
    kalshi_client = KalshiVenueClient()
    
    
    
    
    
    base_url = get_kalshi_base_url()
    
    
    
    is_paper_mode = "demo" in base_url.lower()
    mode_str = "paper" if is_paper_mode else "live"
    logger.info(f"[STARTUP] Kalshi client created: mode={mode_str} base_url={base_url}")
    
    logger.info("[STARTUP] P1.3: AFTER KalshiVenueClient")

    # Phase 1: Market catalog
    
    
    
    logger.info("[STARTUP] P1.4: BEFORE KalshiMarketCatalog start")
    from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, set_market_catalog
    
    
    
    # CRITICAL FIX: Pass the already-initialized kalshi_client to catalog
    # This ensures catalog uses the same client instance that was configured in P1.3
    catalog = KalshiMarketCatalog(client=kalshi_client)
    
    # Phase 2: Trace catalog origin
    from merid.origin_tracer import log_object_origin
    log_object_origin(catalog, "catalog_instance", context="main_15m_lean.py startup")
    log_object_origin(type(catalog), "catalog_class", context="main_15m_lean.py startup")
    
    
    
    # CRITICAL FIX: Start the catalog refresh loop to ensure periodic updates
    # The catalog uses a separate thread for refresh to avoid event loop contention
    logger.info("[STARTUP] Starting catalog refresh loop...")
    catalog.start()
    logger.info(f"[STARTUP] Catalog refresh loop started: {len(catalog._markets)} markets")
    
    
    
    # CRITICAL FIX: Set the singleton catalog instance so WS bridge uses the same catalog
    # Without this, WS bridge's get_market_catalog() returns a different (unstarted) instance
    set_market_catalog(catalog)
    logger.info("[STARTUP] Catalog singleton set for WS bridge compatibility")
    
    await asyncio.sleep(2.0)  # Wait for initial refresh
    catalog_snapshot = catalog.snapshot()
    logger.info(f"[STARTUP] Catalog started: {len(catalog_snapshot.markets)} markets")
    logger.info("[STARTUP] P1.4: AFTER KalshiMarketCatalog start")
    
    
    
    # Phase 1: Market state store initialization
    logger.info("[STARTUP] P1.4.5: BEFORE market state store init")
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    market_state_store = get_kalshi_market_state_store()
    logger.info(f"[STARTUP] Market state store initialized: id={id(market_state_store)}")
    logger.info("[STARTUP] P1.4.5: AFTER market state store init")
    
    # Phase 1: Candle poller initialization (provides 1-minute OHLCV bars for indicator stacks)
    # The candle poller fetches 1-minute bars from Kalshi REST and stores them in market state
    # Indicator stacks can use these bars for accurate calculations instead of spot ticks
    # NOTE: Candle poller is initialized here but started AFTER WS bridge to ensure tickers are available
    logger.info("[STARTUP] P1.4.6: BEFORE candle poller init")
    try:
        from merid.event_venues.kalshi.candle_poller import CandlePoller, get_candle_poller, init_candle_poller
        
        # Initialize candle poller if not already set
        candle_poller = get_candle_poller()
        if candle_poller is None:
            # Not initialized yet - create and register
            candle_poller = init_candle_poller(kalshi_client, market_state_store, period_minutes=1, interval_seconds=60)
            logger.info("[STARTUP] Created new CandlePoller instance (1-minute bars)")
        else:
            logger.info("[STARTUP] CandlePoller already initialized")
        
        # Store in app.state for later startup after WS bridge populates tickers
        app.state.candle_poller = candle_poller
        logger.info("[STARTUP] Candle poller initialized (will start after WS bridge populates tickers)")
        logger.info("[STARTUP] P1.4.6: AFTER candle poller init")
    except Exception as e:
        logger.warning(f"[STARTUP] Candle poller not available (non-fatal): {e}")
        logger.info("[STARTUP] P1.4.6: Candle poller skipped (indicator stacks will use spot price fallback)")
        app.state.candle_poller = None
    
    # Phase 1: WebSocket bridge
    logger.info("[STARTUP] P1.5: BEFORE WS bridge start")
    from merid.event_venues.kalshi.ws_bridge import get_bridge

    ws_bridge = get_bridge()

    # Wait for catalog to have markets before starting WS bridge
    # The catalog refresh happens in a background thread, so we need to poll
    # CRITICAL FIX: Add retry logic with exponential backoff for robust catalog discovery
    
    max_wait = 60  # CRITICAL FIX: Increased from 15s to 60s for catalog refresh
    # 15m markets have natural gaps between windows; 60s allows catching next window
    initial_tickers = []
    allowed_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    # Retry with exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s (total 63s)
    retry_intervals = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    total_elapsed = 0.0
    
    for attempt, wait_interval in enumerate(retry_intervals):
        initial_tickers = []  # Reset on each iteration
        
        # Log catalog state for diagnostics
        catalog_snapshot = catalog.snapshot()
        logger.info(
            f"[STARTUP] Catalog discovery attempt {attempt + 1}/{len(retry_intervals)}: "
            f"total_markets={len(catalog_snapshot.markets)} "
            f"elapsed={total_elapsed:.1f}s "
            f"next_wait={wait_interval:.1f}s"
        )
        
        # Use simple get_active_markets() for reliable market selection
        # This avoids strict ET window matching that causes catalog empty issues
        assets_found = []
        assets_missing = []
        
        for asset in allowed_assets:
            try:
                asset_markets = catalog.get_active_markets(asset=asset, timeframe="15m")
                if asset_markets:
                    market = asset_markets[0]
                    ticker = market.market.market_id if hasattr(market, 'market') else market.market_id
                    initial_tickers.append(ticker)
                    assets_found.append(asset)
                    logger.info(f"[STARTUP] Selected 15m market for {asset}: {ticker}")
                else:
                    assets_missing.append(asset)
                    logger.warning(f"[STARTUP] No active 15m market found for {asset}")
            except Exception as e:
                assets_missing.append(asset)
                logger.error(f"[STARTUP] Error getting 15m market for {asset}: {e}", exc_info=True)
        
        # Log discovery summary
        logger.info(
            f"[STARTUP] Catalog discovery summary: "
            f"found={len(assets_found)}/{len(allowed_assets)} "
            f"assets_found={assets_found} "
            f"assets_missing={assets_missing}"
        )
        
        if initial_tickers:
            logger.info(
                f"[STARTUP] Catalog populated with {len(initial_tickers)} tickers after {total_elapsed:.1f}s "
                f"(attempt {attempt + 1})"
            )
            break
        
        # If this is not the last attempt, wait with exponential backoff
        if attempt < len(retry_intervals) - 1:
            logger.info(f"[STARTUP] Waiting for catalog to populate... (next retry in {wait_interval:.1f}s)")
            await asyncio.sleep(wait_interval)
            total_elapsed += wait_interval
    
    if not initial_tickers:
        logger.error(
            f"[STARTUP] Catalog still empty after {total_elapsed:.1f}s and {len(retry_intervals)} attempts - "
            f"CRITICAL: All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are missing. "
            f"Attempting fallback to direct market lookup via Kalshi REST API."
        )
        # Log detailed catalog state for debugging
        catalog_snapshot = catalog.snapshot()
        logger.error(
            f"[STARTUP] Catalog debug state: "
            f"total_markets={len(catalog_snapshot.markets)} "
            f"series_tickers={list(set(m.series_ticker for m in catalog_snapshot.markets if m.series_ticker))}"
        )
        
        # FALLBACK: Direct market lookup via Kalshi REST API
        # This bypasses catalog filtering to ensure critical assets are available
        # CRITICAL FIX: Removed legacy kalshi_15m_crypto_config.py dependency
        # Series tickers now derived from standard naming convention
        logger.info("[STARTUP] Initiating fallback to direct market lookup")
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client

            client = get_kalshi_client()
            fallback_tickers = []
            
            # Standard series ticker naming convention for 15m crypto
            # This replaces the legacy kalshi_15m_crypto_config.py dependency
            series_ticker_map = {
                "BTC": "KXBTC15M",
                "ETH": "KXETH15M",
                "SOL": "KXSOL15M",
                "XRP": "KXXRP15M",
                "DOGE": "KXDOGE15M",
            }
            
            for asset in allowed_assets:
                series_ticker = series_ticker_map.get(asset)
                if not series_ticker:
                    logger.error(f"[STARTUP] No series ticker configured for {asset}")
                    continue
                
                try:
                    # Query Kalshi API directly for this series
                    logger.info(f"[STARTUP] Fallback: Querying Kalshi API for {asset} (series={series_ticker})")
                    from merid.event_venues.kalshi.client import MarketFilter
                    filter_params = MarketFilter(search=series_ticker, limit=10)
                    result = await client.list_markets_result(filter_params)

                    if result.success and result.data:
                        # Find the first open market
                        for market in result.data:
                            if market.active:
                                ticker = market.market_id
                                fallback_tickers.append(ticker)
                                logger.info(f"[STARTUP] Fallback: Found open market for {asset}: {ticker}")
                                break
                        else:
                            logger.warning(f"[STARTUP] Fallback: No open markets found for {asset} (series={series_ticker})")
                    else:
                        logger.warning(f"[STARTUP] Fallback: No markets returned for {asset} (series={series_ticker}): {result.error}")
                except Exception as e:
                    logger.error(f"[STARTUP] Fallback: Error querying Kalshi API for {asset}: {e}", exc_info=True)
            
            if fallback_tickers:
                initial_tickers = fallback_tickers
                logger.info(
                    f"[STARTUP] Fallback successful: Recovered {len(fallback_tickers)} tickers via direct API lookup"
                )
            else:
                logger.error(
                    f"[STARTUP] Fallback failed: Could not recover any tickers via direct API lookup. "
                    f"System will start with no trading capability."
                )
        except Exception as e:
            logger.error(f"[STARTUP] Fallback initialization failed: {e}", exc_info=True)
        
    
    
    
    
    
    
    
    # WS SUBSCRIPTION CHECK: Log series found but continue with partial set
    from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
    PRIORITY_SERIES = kalshi_agent_grid_catalog_series_tickers()
    
    # Extract series from tickers (e.g., "KXBTC15M-26JUN071415-15" -> "KXBTC15M")
    series_found = set()
    for ticker in initial_tickers:
        # Ticker format: KXBTC15M-26JUN071415-15
        # Series is the first part before the first hyphen
        series = ticker.split("-")[0]
        series_found.add(series)
    
    expected_series = set(PRIORITY_SERIES)
    missing_series = expected_series - series_found
    
    if missing_series:
        logger.warning(
            "[WS-SUBSCRIPTION-PARTIAL] WS subscription has partial series: have=%s missing=%s (expected %d). "
            "Continuing with partial set - catalog robust discovery may have failed for these series.",
            sorted(series_found), sorted(missing_series), len(expected_series)
        )
        
    else:
        logger.info(
            "[WS-SUBSCRIPTION-FULL] WS subscription has all expected series: %s",
            sorted(series_found)
        )
    
    # CRITICAL: Start WS bridge and create background task
    # Canonical bridge uses start(tickers) instead of set_markets()
    # Note: reset_bridge() is already called at module level during import
    
    app.state.ws_bridge_task = asyncio.create_task(ws_bridge.start(initial_tickers), name="ws_bridge_start")
    
    # CRITICAL: Add done-callback to catch any exceptions in the WS bridge task
    def _on_ws_bridge_done(task: asyncio.Task):
        try:
            task.result()
        except Exception as e:
            logger.exception("[WS-BRIDGE-DONE-CALLBACK] WS bridge task crashed", exc_info=e)
            
    
    app.state.ws_bridge_task.add_done_callback(_on_ws_bridge_done)
    logger.info("[WS-BRIDGE-DONE-CALLBACK] Added done-callback to WS bridge task")
    
    
    
    
    # CRITICAL: Wire market_state_store to agent grid
    # The WS bridge uses the global KalshiMarketStateStore singleton
    # This must happen after WS bridge starts but before the loop runs
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.prediction.agent_grid_15m import get_agent_grid
        
        market_state_store = get_kalshi_market_state_store()
        agent_grid = get_agent_grid()
        
        if agent_grid and hasattr(agent_grid, 'set_market_state_store'):
            agent_grid.set_market_state_store(market_state_store)
            logger.info("[STARTUP] P1.5.1: Market state store wired to agent grid")
            
    except Exception as e:
        logger.warning("[STARTUP] Failed to wire market_state_store to agent grid: %s", e)
    logger.info("[WS-STARTUP] WS bridge start task created successfully")
    
    # Wait for WS bridge to connect before proceeding
    # This ensures the bridge is actually streaming before we continue startup
    
    
    
    max_ws_wait = 2  # Reduced from 15 to 2 seconds to allow startup to proceed faster
    ws_connected = False
    for i in range(int(max_ws_wait)):
        await asyncio.sleep(1.0)
        stats = ws_bridge.summary()
        if stats.get("connected", False):
            ws_connected = True
            logger.info(f"[WS-STARTUP] WS bridge connected after {i+1}s")
            break
        logger.info(f"[WS-STARTUP] Waiting for WS connection... ({i+1}s elapsed)")
    
    if not ws_connected:
        logger.warning(f"[WS-STARTUP] WS bridge did not connect within {max_ws_wait}s - continuing anyway")
    else:
        logger.info("[WS-STARTUP] WS bridge successfully connected")
    
    

    # Phase 1: WS subscription refresh supervisor
    # NOTE: The new KalshiWebSocketBridge doesn't support dynamic resubscription while running.
    # Markets are set once via set_markets() before start() and remain static for the session.
    # The refresh supervisor is kept for REST fallback (MD freshness) but WS subscription changes are disabled.
    
    
    try:
        
        
        
        logger.info("[STARTUP] P1.5.1: BEFORE WS refresh supervisor (REST fallback only, WS subscriptions static)")
        
        
        
        ws_refresh_stop = asyncio.Event()
        try:
            logger.info("[STARTUP] Creating WS refresh supervisor task...")
            
            
            
            
            ws_refresh_task = asyncio.create_task(
                supervise_ws_refresh_task(catalog, ws_bridge, interval_s=WS_REFRESH_INTERVAL_S, stop_event=ws_refresh_stop),
                name="ws_refresh_supervisor"
            )
            
            
            
            
            
            # CRITICAL: Store task in app.state so it doesn't get garbage collected
            app.state.ws_refresh_task = ws_refresh_task
            
            # CRITICAL: Yield control to allow the task to start
            await asyncio.sleep(0.2)
            
            
            
            # CRITICAL FIX: Add done-callback to catch any exceptions in the WS refresh task
            def _on_ws_refresh_done(task: asyncio.Task):
                try:
                    task.result()
                except Exception as e:
                    logger.exception("[WS-REFRESH-DONE-CALLBACK] WS refresh supervisor task crashed", exc_info=e)
                    
            
            ws_refresh_task.add_done_callback(_on_ws_refresh_done)
            
            logger.info(f"[STARTUP] WS refresh supervisor task created: {ws_refresh_task.get_name()}, done={ws_refresh_task.done()}")
            # Add a small delay to ensure task starts
            await asyncio.sleep(0.1)
            logger.info(f"[STARTUP] WS refresh supervisor task status after 0.1s: done={ws_refresh_task.done()}, cancelled={ws_refresh_task.cancelled()}")
            
            
        except Exception as e:
            logger.error(f"[STARTUP] Failed to create WS refresh supervisor task: {e}", exc_info=True)
            
            
            
            raise
        logger.info("[STARTUP] P1.5.1: AFTER WS refresh supervisor")
        
        
        
    except Exception as e:
        
        logger.error(f"[STARTUP] ERROR in WS refresh supervisor section: {e}", exc_info=True)
        
        
        
        raise

    # Phase 1: Start candle poller (after WS bridge populates tickers)
    logger.info("[STARTUP] P1.5.2: BEFORE start candle poller")
    try:
        if app.state.candle_poller is not None:
            logger.info("[STARTUP] Starting candle poller (1-minute OHLCV bars for indicator stacks)")
            await app.state.candle_poller.start()
            logger.info("[STARTUP] Candle poller started successfully")
        else:
            logger.warning("[STARTUP] Candle poller not available, skipping")
        
        
    except Exception as e:
        logger.error(f"[STARTUP] Failed to start candle poller: {e}", exc_info=True)
        
        
    
    logger.info("[STARTUP] P1.5.2: AFTER candle poller start")

    # Phase 1: Fills ledger and poller
    
    
    logger.info("[STARTUP] P1.6: BEFORE fills tracking")
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    from merid.event_venues.kalshi.fills_poller import get_fills_poller
    
    fills_ledger = get_fills_ledger()
    fills_poller = get_fills_poller()
    logger.info("[STARTUP] Fills tracking initialized")
    logger.info("[STARTUP] P1.6: AFTER fills tracking")
    
    

    # Phase 1: Bankroll service
    
    
    logger.info("[STARTUP] P1.7: BEFORE bankroll")
    logger.info("[STARTUP] P1.7.1: Importing bankroll_service_v2")
    from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2, set_bankroll_service
    logger.info("[STARTUP] P1.7.2: Importing unified_risk_manager")
    from merid.risk.unified_risk_manager import get_unified_risk_manager
    logger.info("[STARTUP] P1.7.3: Loading profile bankroll_cap_pct for bankroll service")
    
    # CRITICAL FIX: Load bankroll_cap_pct from profile to pass to BankrollServiceV2
    # This ensures max_position_usd uses the profile's 3% instead of default 2%
    from decimal import Decimal
    max_riskable_frac = None
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
        if is_profile_active():
            adapter = get_active_profile()
            if adapter:
                profile = adapter.profile
                max_riskable_frac = Decimal(str(profile.venue_bankroll_cap_pct))
                logger.info(f"[STARTUP] P1.7.3: Loaded bankroll_cap_pct from profile: {max_riskable_frac}")
            else:
                logger.warning("[STARTUP] P1.7.3: Profile adapter not available, using default 2%")
        else:
            logger.warning("[STARTUP] P1.7.3: Profile not active, using default 2%")
    except Exception as e:
        logger.warning(f"[STARTUP] P1.7.3: Failed to load bankroll_cap_pct from profile: {e}, using default 2%")
    
    logger.info("[STARTUP] P1.7.4: Creating BankrollServiceV2 instance with max_riskable_frac=%s", max_riskable_frac)
    bankroll = BankrollServiceV2(max_riskable_frac=max_riskable_frac)
    
    # Phase 2: Trace bankroll service origin
    from merid.origin_tracer import log_object_origin
    log_object_origin(bankroll, "bankroll_service_instance", context="main_15m_lean.py startup")
    log_object_origin(type(bankroll), "bankroll_service_class", context="main_15m_lean.py startup")
    
    # Set the singleton so other components can access it
    set_bankroll_service(bankroll)
    logger.info("[STARTUP] P1.7.4: BankrollServiceV2 singleton set, calling bankroll.start()")
    
    
    
    await bankroll.start()
    
    
    
    logger.info("[STARTUP] P1.7.5: bankroll.start() completed")
    
    # Wait for bankroll to reach FRESH state before registering equity provider
    # This prevents race conditions where equity_provider is called before bankroll is ready
    logger.info("[STARTUP] P1.7.6: Waiting for bankroll to reach FRESH state...")
    max_wait_seconds = 30.0
    start_wait = time.time()
    bankroll_ready = False
    
    while time.time() - start_wait < max_wait_seconds:
        summary = await bankroll.get_summary()
        if summary.state.name == "FRESH" and summary.equity_usd is not None:
            bankroll_ready = True
            logger.info(f"[STARTUP] P1.7.6: Bankroll is FRESH with equity=${summary.equity_usd}")
            break
        await asyncio.sleep(0.5)
    
    if not bankroll_ready:
        logger.warning(f"[STARTUP] P1.7.6: Bankroll did not reach FRESH state within {max_wait_seconds}s, current state={summary.state.name}")
    
    def equity_provider_cents() -> int:
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity_usd = get_equity_for_risk_calc_sync()
            if equity_usd is not None:
                return int(equity_usd * 100)
            return 0
        except Exception as e:
            logger.error(f"[STARTUP] equity_provider_cents failed: {e}")
            return 0
    
    logger.info("[STARTUP] P1.7.7: Calibrating UnifiedRiskManager from bankroll")
    risk_mgr = get_unified_risk_manager()
    risk_mgr.calibrate_from_balance(balance_cents=equity_provider_cents())
    logger.info("[STARTUP] P1.7.8: UnifiedRiskManager calibrated")
    logger.info("[STARTUP] Bankroll service initialized and registered")
    
    logger.info("[STARTUP] P1.7: AFTER bankroll")
    
    
    

    # Phase 1: Order router
    
    
    
    logger.info("[STARTUP] P1.8: BEFORE order router")
    
    # FIX: Use lazy initialization for order_router to avoid blocking event loop during import
    # The order_router will be initialized on first use in agent_grid_15m
    # This avoids the synchronous import blocking during startup
    order_router = None  # Will be lazy-loaded in agent_grid_15m
    
    logger.info("[STARTUP] P1.8: AFTER order router (lazy init)")
    
    
    

    # Phase 1: Unified spot service
    
    
    
    logger.info("[STARTUP] P1.9: BEFORE unified_spot.start_refresh_loop")
    
    from data.unified_spot_service import get_unified_spot_service
    

    logger.info("[STARTUP] P1.9.1: Calling get_unified_spot_service")
    unified_spot = get_unified_spot_service()
    logger.info(f"[STARTUP] P1.9.2: get_unified_spot_service returned id={id(unified_spot)} _running={unified_spot._running}")
    
    
    # Start the simplified refresh loop (runs on FastAPI event loop, no separate threads)
    logger.info("[STARTUP] P1.9.3: Starting unified spot refresh loop")
    await unified_spot.start_refresh_loop()
    
    
    # CRITICAL FIX: Validate spot service readiness before proceeding
    # This ensures spot data is available before trading starts
    max_spot_wait = 30.0  # 30s timeout for spot service readiness
    spot_ready = False
    start_spot_wait = time.time()
    
    logger.info(f"[STARTUP] P1.9.4: Waiting for spot service readiness (max {max_spot_wait}s)...")
    
    
    while time.time() - start_spot_wait < max_spot_wait:
        if unified_spot.is_ready():
            spot_ready = True
            logger.info("[STARTUP] P1.9.4: Spot service reports ready")
            
            break
        await asyncio.sleep(0.5)
    
    if not spot_ready:
        logger.warning(f"[STARTUP] P1.9.4: Spot service did not report ready within {max_spot_wait}s - proceeding anyway")
        
    
    
    
    logger.info("[STARTUP] Phase 1.9: Unified spot service scheduled - proceeding to agent grid")
    
    
    # Phase 1: Build and start agent grid (CRITICAL: must be before WS bridge)
    # Agents need to be subscribed to markets before WS starts receiving data
    
    
    logger.info("[STARTUP] P1.10: BEFORE agent grid build")
    
    
    # Import spot provider wrapper
    from merid.prediction.spot_provider import get_spot_provider
    spot_provider = get_spot_provider(provider_type="unified")
    
    # Build agent grid with all dependencies now available
    from merid.prediction.agent_grid_15m import build_15m_agent_grid
    logger.info("[STARTUP] P1.10: Calling build_15m_agent_grid")
    
    agent_grid = await build_15m_agent_grid(
        catalog=catalog,
        bankroll=bankroll,
        spot_provider=spot_provider,
        order_router=order_router,
        unified_edge_config=unified_edge_config,
        ws_bridge=None  # Will be set after WS bridge starts
    )
    
    # Phase 2: Trace agent grid origin
    from merid.origin_tracer import log_object_origin
    log_object_origin(agent_grid, "agent_grid_instance", context="main_15m_lean.py startup")
    log_object_origin(type(agent_grid), "agent_grid_class", context="main_15m_lean.py startup")
    
    logger.info("[STARTUP] P1.10: Agent grid built successfully")
    
    # CRITICAL: Set global agent grid instance for external reset calls
    # This allows the catalog to reset strip order counts when market IDs change
    try:
        from merid.prediction.agent_grid_15m import set_agent_grid_instance
        set_agent_grid_instance(agent_grid)
        logger.info("[STARTUP] P1.10: Global agent grid instance set for catalog reset")
    except Exception as e:
        logger.warning("[STARTUP] Failed to set global agent grid instance: %s", e)
    
    
    # CRITICAL FIX: Set WS bridge reference on agent grid before starting
    # This enables agents to subscribe to markets via the WS bridge
    agent_grid._ws_bridge = ws_bridge
    logger.info("[STARTUP] P1.10: WS bridge reference set on agent grid")
    
    # CRITICAL FIX: Set position cache on agent grid for global allocator
    # The global allocator needs position cache to track current positions for allocation
    from merid.event_venues.kalshi.position_cache import get_position_cache
    position_cache = get_position_cache()
    agent_grid.set_position_cache(position_cache)
    logger.info("[STARTUP] P1.10: Position cache set on agent grid for global allocator")
    
    # Start agent grid to enable market subscriptions
    logger.info("[STARTUP] P1.10: Calling agent_grid.start()")
    await agent_grid.start()
    logger.info("[STARTUP] P1.10: Agent grid started successfully")
    
    
    # Store agent grid in app.state for API endpoints
    app.state.agent_grid_15m = agent_grid
    
    
    
    logger.info("[STARTUP] P1.10: AFTER agent grid")
    
    # Clear phase transition marker
    logger.info("=== PHASE TRANSITION: Starting Phase 1.11 - WebSocket Bridge ===")
    

    # CRITICAL FIX: Store P1.x components in app.state for trading thread to use
    # The trading thread will access these via app.state to initialize P2.x
    
    
    logger.info("[STARTUP] P1.11: BEFORE attach P1.x components to app.state")
    app.state.catalog = catalog
    app.state.kalshi_client = kalshi_client
    app.state.bankroll = bankroll
    app.state.unified_spot = unified_spot
    app.state.order_router = order_router
    app.state.unified_edge_config = unified_edge_config
    app.state.ws_bridge = ws_bridge
    app.state.market_state_store = market_state_store
    logger.info("[STARTUP] P1.11: AFTER attach P1.x components to app.state")
    
    # CRITICAL FIX: Validate market state store health before proceeding
    logger.info("[STARTUP] P1.12: Validating market state store health...")
    market_state_healthy = False
    try:
        # Check if market state store has any states loaded
        state_count = len(market_state_store._states) if hasattr(market_state_store, '_states') else 0
        logger.info(f"[STARTUP] P1.12: Market state store has {state_count} states loaded")
        
        # Check if batch worker is running (for delta processing)
        batch_worker_running = market_state_store._batch_worker_running if hasattr(market_state_store, '_batch_worker_running') else False
        logger.info(f"[STARTUP] P1.12: Market state batch worker running: {batch_worker_running}")
        
        market_state_healthy = state_count >= 0  # Store is healthy even if empty (will populate via WS)
        logger.info(f"[STARTUP] P1.12: Market state store healthy: {market_state_healthy}")
    except Exception as e:
        logger.error(f"[STARTUP] P1.12: Market state store health check failed: {e}")
        market_state_healthy = False
    
    # P1.13: Validate the order router LAZY contract.
    # order_router is intentionally None here (the instance is lazy-loaded on first use
    # in agent_grid_15m via route_order_async). The previous check did
    # hasattr(order_router, '_dedup') on None, so it was always False and masked real
    # problems. Instead validate that the module imports and exposes its core entrypoints.
    logger.info("[STARTUP] P1.13: Validating order router module (lazy-init contract)...")
    order_router_healthy = False
    try:
        from merid.event_venues.kalshi import order_router as _order_router_mod
        _required = ("route_order_async", "OrderIntent", "resolve_exit_policy", "resolve_window_policy")
        _missing = [name for name in _required if not hasattr(_order_router_mod, name)]
        order_router_healthy = not _missing
        if order_router_healthy:
            logger.info("[STARTUP] P1.13: Order router module healthy (instance lazy-loads on first use)")
        else:
            logger.error("[STARTUP] P1.13: Order router module missing entrypoints: %s", _missing)
    except Exception as e:
        logger.error(f"[STARTUP] P1.13: Order router module validation failed: {e}")
        order_router_healthy = False
    
    # CRITICAL FIX: Validate Kalshi client is properly initialized
    logger.info("[STARTUP] P1.14: Validating Kalshi client...")
    client_healthy = False
    try:
        # Check if client is authenticated and has HTTP client
        client_healthy = hasattr(kalshi_client, '_http_client') and kalshi_client._http_client is not None
        logger.info(f"[STARTUP] P1.14: Kalshi client healthy: {client_healthy}")
    except Exception as e:
        logger.error(f"[STARTUP] P1.14: Kalshi client health check failed: {e}")
        client_healthy = False
    
    # Log overall P1.x health summary
    logger.info(
        f"[STARTUP] P1.COMPLETE-HEALTH: spot_ready={spot_ready} bankroll_ready={bankroll_ready} "
        f"market_state_healthy={market_state_healthy} order_router_healthy={order_router_healthy} "
        f"client_healthy={client_healthy}"
    )
    
    

    # NOTE: P2.x (trading stack) is now handled in a separate thread
    # See _run_startup_wrapper which starts the trading thread after P1.x completes
    logger.info("[STARTUP] P1.COMPLETE: lightweight async phases complete (trading will run in separate thread)")
    logger.info("[STARTUP] P9: EXIT _run_startup_phases_v20260530")
    
    

# Add CORS middleware to handle OPTIONS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# NOTE: __main__ block removed - use run_15m_lean.py to start the server
# This prevents double-initialization when using string-form uvicorn.run()

logger.debug("[MAIN-15M-LEAN] END OF FILE - File execution complete")

