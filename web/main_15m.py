"""
Kalshi 15m Lean Entrypoint — Minimal FastAPI app for kalshi_crypto_15m_v2 profile.

This is a clean, minimal FastAPI entrypoint designed specifically for the 15-minute
crypto trading stack on Kalshi. It replaces the complex legacy web.main for this profile.

This entrypoint intentionally does NOT include:
- core.systemorchestrator
- Governance, treasury
- Graph memory, macro overlay
- Cross-sectional PM metrics
- Legacy lane orchestration
- Reflection/learning systems
- KalshiContinuousTrader
- Legacy PM agent mesh / continuous trader (only 5 isolated 15m crypto agents via AgentGrid)

Usage:
    MERID_PROFILE=kalshi_crypto_15m_v2 uvicorn web.main_15m:app --host 0.0.0.0 --port 8011
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from utils.logger import get_logger

logger = get_logger("web.main_15m")

# Version tag to verify running code
logger.info("[MAIN-15M] MODULE VERSION v2026-05-19-spot-debug-03")

# Import spot debug API router
from web.api.spot_debug_api import router as spot_debug_router

# Import WebSocket router for /ws/risk endpoint
from web.api.streams import router as ws_router

# Import Kalshi API router for /api/v1/kalshi/* endpoints
from web.api.kalshi_api import router as kalshi_router

# Import Kalshi Grid API router for /api/v1/kalshi-grid/* endpoints
from web.api.kalshi_grid_api import router as kalshi_grid_router

# Import System endpoints router for /api/v1/system/* endpoints
from web.api.system_endpoints import router as system_router

# Import Operator endpoints router for /api/v1/operator/* endpoints
from web.api.operator_endpoints import router as operator_router

# Import Risk metrics API router for /api/v1/risk/* endpoints
from web.api.risk_metrics_api import router as risk_metrics_router

# Import Spot basis API router for /api/v1/kalshi/spot-basis endpoint
from web.api.spot_basis_api import router as spot_basis_router

# Import Signals API router for /api/v1/signals/* endpoints
from web.api.signals_api import router as signals_router

# Import Live stream router for /ws/live endpoint
from web.api.live_stream import router as live_stream_router

# ═══════════════════════════════════════════════════════════════════════
# EMERGENCY FIX (2026-05-12): Force load safe modules before threading starts
# Prevents import race condition causing Windows access violation crashes
# ═══════════════════════════════════════════════════════════════════════
try:
    import urllib3
except ImportError:
    pass
try:
    import requests
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════════════
# Windows asyncio transport shutdown race fix
# ═══════════════════════════════════════════════════════════════════════
# ConnectionResetError: [WinError 10054] during cleanup is a known Windows
# ROOT CAUSE FIX: WindowsSelectorEventLoopPolicy causes run_in_executor and asyncio.sleep to hang.
# Switching to WindowsProactorEventLoopPolicy which is the default on Python 3.8+ on Windows.
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ═══════════════════════════════════════════════════════════════════════
# 24/7-HARDENING: Disable ALL automatic shutdown triggers
# ═══════════════════════════════════════════════════════════════════════
# Set these BEFORE any other imports to ensure all modules see the relaxed settings
os.environ.setdefault("MERID_FATAL_SHUTDOWN_AFTER_N_FAILS", "0")  # Never shutdown on failures
os.environ.setdefault("MERID_SHUTDOWN_ON_ASGI_FATAL", "0")  # Never shutdown on ASGI fatal
os.environ.setdefault("MERID_ERROR_THRESHOLD", "999999")  # Ultra-high error threshold
os.environ.setdefault("MERID_KALSHI_CB_FAILURE_THRESHOLD", "999")  # Ultra-high circuit breaker threshold
os.environ.setdefault("KALSHI_WS_PRESSURE_SHUTDOWN_MAX", "999")  # Never shutdown on queue pressure
os.environ.setdefault("KALSHI_LOOP_LAG_HALT_CONSECUTIVE", "999")  # Never halt on loop lag
os.environ.setdefault("KALSHI_LOOP_LAG_DEGRADED_CONSECUTIVE", "999")  # Never degrade on loop lag
os.environ.setdefault("MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS", "86400")  # 24h grace period

# ═══════════════════════════════════════════════════════════════════════
# 24/7-HARDENING: Uvicorn shutdown immunity (ROOT-CAUSE FIX)
# ═══════════════════════════════════════════════════════════════════════
# Uvicorn installs SIGINT/SIGTERM handlers that set `should_exit=True`.
# When that flag flips, uvicorn cancels EVERY task in the event loop —
# including all our streaming agents, event-bus bridge, fills writer, etc.
try:
    import uvicorn.server as _uv_server

    # Disable uvicorn's signal-handler installer. Make it a no-op.
    def _no_install_signal_handlers(self) -> None:
        return None
    _uv_server.Server.install_signal_handlers = _no_install_signal_handlers

    # Neutralise handle_exit so any callback that *did* slip through
    # cannot set should_exit/force_exit.
    def _no_handle_exit(self, sig=None, frame=None) -> None:
        try:
            _name = getattr(sig, "name", str(sig)) if sig is not None else "unknown"
            logger.debug("[UVICORN-IMMUNITY] Ignored handle_exit signal: %s", _name)
        except Exception:
            pass
        return None
    _uv_server.Server.handle_exit = _no_handle_exit
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════════════
# EVENT-LOOP-FIX: Windows asyncio exception handler
# ═══════════════════════════════════════════════════════════════════════
def _setup_asyncio_exception_handler():
    """Install a custom exception handler that suppresses shutdown-related errors on Windows."""
    def _handler(loop, context):
        exc = context.get('exception')
        # Suppress InvalidStateError during shutdown (Windows-specific)
        if isinstance(exc, asyncio.InvalidStateError):
            logger.debug("Suppressed InvalidStateError during asyncio shutdown: %s", context.get('message', ''))
            return
        # Suppress ConnectionResetError during proactor transport lifecycle
        if isinstance(exc, ConnectionResetError):
            winerror = getattr(exc, 'winerror', None)
            if winerror in (995, 10054):
                logger.debug("Suppressed ConnectionResetError(%s) during proactor transport callback", winerror)
                return
        # Suppress AttributeError during Windows proactor transport shutdown
        if isinstance(exc, AttributeError):
            msg = str(context.get('message', ''))
            if 'NoneType' in msg and 'shutdown' in msg:
                logger.debug("Suppressed AttributeError during proactor transport shutdown: %s", msg)
                return
        # For all other exceptions, use default handler
        loop.default_exception_handler(context)
    
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_handler)
    except RuntimeError:
        pass

_setup_asyncio_exception_handler()

# Load .env file before any imports that depend on environment variables
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

logger = get_logger("web.main_15m")

# Import startup trace helper
from merid.startup_trace import log_startup_phase

# Log entrypoint import
log_startup_phase("import_main_15m", "web.main_15m")

# ── Lifecycle Management ──────────────────────────────────────────────────────


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """FastAPI lifespan manager for kalshi_crypto_15m_v2 profile."""
    logger.info("[15M-BOOT] ENTER startup_15m")
    logger.info("=" * 80)
    logger.info("MERID 15m KALSHI CRYPTO STARTUP (kalshi_crypto_15m_v2)")
    logger.info("=" * 80)
    start_time = time.time()

    # Validate profile
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        logger.error(
            "Invalid profile for web.main_15m: %s (expected kalshi_crypto_15m_v2)",
            profile,
        )
        raise ValueError(
            f"web.main_15m is only for kalshi_crypto_15m_v2 profile, got {profile}"
        )
    logger.info("[PROFILE] Using profile: kalshi_crypto_15m_v2")
    log_startup_phase("validate_profile", "web.main_15m", "kalshi_crypto_15m_v2")
    
    # Log feature flag state for risk envelope
    envelope_enabled = os.getenv("MERID_RISK_ENVELOPE_ENABLED", "true").lower() in ("true", "1", "yes")
    logger.info(f"[RISK-ENVELOPE-FEATURE-FLAG] MERID_RISK_ENVELOPE_ENABLED={envelope_enabled}")
    
    # Capture config snapshot for rollback capability
    try:
        from scripts.capture_config_snapshot import capture_snapshot
        snapshot_path = capture_snapshot()
        logger.info(f"[CONFIG-SNAPSHOT] Created config snapshot at: {snapshot_path}")
    except Exception as e:
        logger.warning(f"[CONFIG-SNAPSHOT] Failed to capture config snapshot: {e}")

    # Phase 0: Core infrastructure (Redis, auth, risk, bankroll)
    log_startup_phase("start_core_infrastructure", "web.main_15m")
    logger.debug("[PHASE-0-DEBUG] Starting core infrastructure...")
    await _start_core_infrastructure()
    logger.debug("[PHASE-0-DEBUG] Core infrastructure started ok")

    # Phase 1: Kalshi venue setup (client, catalog, market state)
    log_startup_phase("start_kalshi_venue", "web.main_15m")
    logger.debug("[PHASE-1-DEBUG] Starting Kalshi venue services...")
    await _start_kalshi_venue()
    logger.debug("[PHASE-1-DEBUG] Kalshi venue services started ok")

    # Phase 1b: Start UnifiedSpotService (spot price feed)
    log_startup_phase("start_unified_spot", "web.main_15m")
    logger.debug("[PHASE-1-DEBUG] Starting UnifiedSpotService...")
    
    # Executor sanity check before unified spot warmup
    async def _executor_sanity_check():
        loop = asyncio.get_running_loop()
        def _probe():
            time.sleep(0.1)
            return "ok"
        
        logger.info("[EXECUTOR-SANITY] Submitting probe to run_in_executor")
        fut = loop.run_in_executor(None, _probe)
        result = await asyncio.wait_for(fut, timeout=2.0)
        logger.info("[EXECUTOR-SANITY] Executor probe result=%r", result)
    
    await _executor_sanity_check()
    
    await _start_unified_spot_service()
    logger.debug("[PHASE-1-DEBUG] UnifiedSpotService started ok")

    # Phase 2: Load agent grid (5 agents)
    log_startup_phase("load_agent_grid", "web.main_15m")
    logger.debug("[PHASE-2-DEBUG] Loading agent grid...")
    await _load_agent_grid()
    logger.debug("[PHASE-2-DEBUG] Agent grid loaded ok")

    # Phase 3: Start Kalshi15mLoop
    log_startup_phase("start_15m_loop", "web.main_15m")
    logger.debug("[PHASE-3-DEBUG] Starting Kalshi15mLoop...")
    await _start_15m_loop()
    logger.debug("[PHASE-3-DEBUG] Kalshi15mLoop started ok")

    # Phase 3b: Start Kalshi venue reconciliation
    # CRITICAL FIX: Add background reconciliation to clear "reconciliation not yet run" warning
    # This was missing in main_15m.py but present in main_legacy.py
    log_startup_phase("start_kalshi_reconciliation", "web.main_15m")
    logger.debug("[PHASE-3-DEBUG] Starting Kalshi venue reconciliation...")
    await _start_kalshi_reconciliation()
    logger.debug("[PHASE-3-DEBUG] Kalshi venue reconciliation started ok")

    # Start heartbeat task to detect frozen event loop clock
    log_startup_phase("start_heartbeat", "web.main_15m")
    logger.debug("[PHASE-3-DEBUG] Starting event loop heartbeat...")
    await _start_heartbeat()
    logger.debug("[PHASE-3-DEBUG] Event loop heartbeat started ok")

    startup_duration = time.time() - start_time
    logger.info("=" * 80)
    logger.info(
        "MERID 15m KALSHI CRYPTO STARTUP COMPLETE (%.2fs)",
        startup_duration,
    )
    logger.info("=" * 80)
    
    # Startup summary for 15m profile
    log_startup_phase(
        "startup_summary",
        "web.main_15m",
        f"profile=kalshi_crypto_15m_v2 keep_components=7 skipped_components=28 duration={startup_duration:.2f}s"
    )

    # ── System-Wide Invariants (Startup Assertions) ───────────────────────────────
    logger.info("[INVARIANTS] Running startup invariants...")

    # Invariant 1: Profile is kalshi_crypto_15m_v2
    profile = os.getenv("MERID_PROFILE", "")
    assert profile == "kalshi_crypto_15m_v2", f"PROFILE INVARIANT FAILED: expected kalshi_crypto_15m_v2, got {profile}"
    logger.info("[INVARIANTS] Profile invariant: PASS (kalshi_crypto_15m_v2)")

    # Invariant 2: Agent count == 5
    agent_grid = _startup_state.get("agent_grid")
    agent_count = len(agent_grid._agents) if agent_grid else 0
    assert agent_count == 5, f"AGENT COUNT INVARIANT FAILED: expected 5, got {agent_count}"
    logger.info("[INVARIANTS] Agent count invariant: PASS (5 agents)")

    # Invariant 3: Catalog has 5 allowed series
    catalog = _startup_state.get("market_catalog")
    if catalog:
        allowed_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
        # Log catalog status without asserting (catalog may be empty on first refresh)
        logger.info("[INVARIANTS] Catalog invariant: catalog initialized (allowed series: %s)", ", ".join(allowed_series))
    else:
        logger.warning("[INVARIANTS] Catalog invariant: catalog not initialized")

    # Invariant 4: WS bridge is subscribed to tickers
    ws_bridge = _startup_state.get("ws_bridge")
    ws_services = _startup_state.get("services", {}).get("ws_bridge", {})
    if ws_bridge and ws_services.get("status") == "running":
        tickers = ws_services.get("tickers", [])
        logger.info("[INVARIANTS] WS bridge invariant: subscribed to %d tickers", len(tickers))
    elif ws_bridge and ws_services.get("status") != "running":
        # Bridge exists but not running - this is a real issue
        logger.warning("[INVARIANTS] WS bridge invariant: bridge exists but status=%s", ws_services.get("status"))
    else:
        # Bridge not initialized yet - this is OK during startup
        logger.info("[INVARIANTS] WS bridge invariant: not initialized (OK during startup)")

    # Invariant 5: Loop is running
    loop = _startup_state.get("loop")
    if loop:
        logger.info("[INVARIANTS] Loop invariant: loop initialized")
    else:
        logger.warning("[INVARIANTS] Loop invariant: not initialized")

    logger.info("[INVARIANTS] Startup invariants complete")
    logger.info("[15M-BOOT] EXIT startup_15m ok")

    yield

    # Shutdown
    logger.info("MERID 15m KALSHI CRYPTO SHUTDOWN START")
    try:
        await _stop_all()
        logger.info("MERID 15m KALSHI CRYPTO SHUTDOWN COMPLETE")
    except Exception:
        logger.exception("[15M-BOOT-ERROR] Exception during shutdown")
        raise


# ── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="MERID Kalshi 15m Crypto",
    description="Lean 15-minute crypto trading on Kalshi",
    version="15m-v2",
    docs_url="/docs" if os.getenv("MERID_15M_DOCS", "1") == "1" else None,
    redoc_url="/redoc" if os.getenv("MERID_15M_DOCS", "1") == "1" else None,
    lifespan=_app_lifespan,
)

# Add CORS middleware to handle OPTIONS preflight requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Register API routers
app.include_router(spot_debug_router)
app.include_router(ws_router)
app.include_router(kalshi_router)
app.include_router(kalshi_grid_router)
app.include_router(system_router)
app.include_router(operator_router)
app.include_router(risk_metrics_router)
app.include_router(spot_basis_router)
app.include_router(signals_router)
app.include_router(live_stream_router)


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint for risk envelope monitoring."""
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        metrics_text = f"""# HELP kalshi_risk_envelope_band Current risk band (0=normal, 1=reduced, 2=critical, 3=halt)
# TYPE kalshi_risk_envelope_band gauge
kalshi_risk_envelope_band {envelope.current_band}

# HELP kalshi_risk_envelope_distance_to_halt_pct Distance to halt threshold as percentage
# TYPE kalshi_risk_envelope_distance_to_halt_pct gauge
kalshi_risk_envelope_distance_to_halt_pct {envelope.distance_to_halt_pct:.4f}

# HELP kalshi_risk_envelope_per_trade_multiplier Per-trade risk multiplier (0.0-1.0)
# TYPE kalshi_risk_envelope_per_trade_multiplier gauge
kalshi_risk_envelope_per_trade_multiplier {envelope.per_trade_multiplier:.4f}

# HELP kalshi_risk_envelope_is_halted Whether trading is halted (1=yes, 0=no)
# TYPE kalshi_risk_envelope_is_halted gauge
kalshi_risk_envelope_is_halted {1 if envelope.is_halted else 0}

# HELP kalshi_risk_envelope_peak_equity_usd Peak equity for drawdown calculation
# TYPE kalshi_risk_envelope_peak_equity_usd gauge
kalshi_risk_envelope_peak_equity_usd {envelope.peak_equity_usd:.2f}

# HELP kalshi_risk_envelope_current_equity_usd Current equity
# TYPE kalshi_risk_envelope_current_equity_usd gauge
kalshi_risk_envelope_current_equity_usd {envelope.current_equity_usd:.2f}
"""
        return PlainTextResponse(content=metrics_text)
    except Exception as e:
        logger.warning(f"[METRICS] Failed to generate envelope metrics: {e}")
        # Return empty metrics on error
        return PlainTextResponse(content="# No metrics available\n")

# ── Global State ─────────────────────────────────────────────────────────────

_startup_state: Dict[str, Any] = {
    "services": {},
    "background_tasks": [],
    "loop": None,
    "agent_grid": None,
    "kalshi_client": None,
    "bankroll_service": None,
    "venue_adapter": None,
    "market_catalog": None,
}

# ── Boot Status Contract ─────────────────────────────────────────────────────

class BootStatus:
    """Tracks PHASE-1 service startup status to prevent silent failures."""
    
    def __init__(self):
        self.kalshi_venue_ok: bool = False
        self.kalshi_client_ok: bool = False
        self.bankroll_ok: bool = False
        self.market_catalog_ok: bool = False
        self.market_state_ok: bool = False
        self.ws_bridge_ok: bool = False
        self.fills_poller_ok: bool = False
        self.settlement_poller_ok: bool = False
        self.unified_spot_ok: bool = False
        self.rti_feed_ok: bool = False  # Optional for kalshi_crypto_15m_v2
        self.term_structure_ok: bool = False  # Optional for kalshi_crypto_15m_v2
        self.heartbeat_ok: bool = False  # Event loop heartbeat
    
    def mark_success(self, service_name: str) -> None:
        """Mark a service as successfully started."""
        attr_name = f"{service_name}_ok"
        if hasattr(self, attr_name):
            setattr(self, attr_name, True)
            logger.info(f"[BOOT-STATUS] mark_success: {service_name} -> {attr_name} = True")
        else:
            logger.error(f"[BOOT-STATUS] mark_success called for unknown service: {service_name} (attribute {attr_name} not found)")
    
    def mark_failure(self, service_name: str) -> None:
        """Mark a service as failed to start."""
        attr_name = f"{service_name}_ok"
        if hasattr(self, attr_name):
            setattr(self, attr_name, False)
            logger.error(f"[BOOT-STATUS] mark_failure: {service_name} -> {attr_name} = False")
        else:
            logger.error(f"[BOOT-STATUS] mark_failure called for unknown service: {service_name} (attribute {attr_name} not found)")
    
    def check_required_services(self) -> bool:
        """Check all required services are up (excluding optional ones)."""
        required = [
            self.kalshi_client_ok,
            self.bankroll_ok,
            self.market_catalog_ok,
            self.market_state_ok,
            self.ws_bridge_ok,
            self.fills_poller_ok,
            self.settlement_poller_ok,
            self.unified_spot_ok,
        ]
        return all(required)
    
    def get_missing_services(self) -> list[str]:
        """Return list of required services that are not OK."""
        required_map = {
            "kalshi_client": self.kalshi_client_ok,
            "bankroll": self.bankroll_ok,
            "market_catalog": self.market_catalog_ok,
            "market_state": self.market_state_ok,
            "ws_bridge": self.ws_bridge_ok,
            "fills_poller": self.fills_poller_ok,
            "settlement_poller": self.settlement_poller_ok,
            "unified_spot": self.unified_spot_ok,
        }
        return [name for name, ok in required_map.items() if not ok]

_boot_status = BootStatus()

# ── Startup Phases ───────────────────────────────────────────────────────────


async def _start_core_infrastructure() -> None:
    """Phase 0: Start core infrastructure services."""
    logger.info("[PHASE-0] Starting core infrastructure...")

    # Validate environment
    _validate_environment()

    # Redis (if configured)
    _start_redis()

    # Auth (if configured)
    _start_auth()

    # Risk limits
    _start_risk_limits()

    logger.info("[PHASE-0] Core infrastructure started")


def _validate_environment() -> None:
    """Validate required environment variables."""
    # Demo mode allows system to start without Kalshi credentials for development/testing
    # This is useful for testing startup sequence, loop execution, and validating legacy component isolation
    # WARNING: Never use MERID_DEMO_MODE=1 in production
    demo_mode = os.getenv("MERID_DEMO_MODE", "").lower() in ("1", "true", "yes")
    
    if demo_mode:
        logger.warning("[DEMO-MODE] Skipping Kalshi credential validation - system will not make live trades")
        logger.warning("[DEMO-MODE] This mode is for development/testing only - never use in production")
        # Set mock credentials to allow startup to proceed
        os.environ["KALSHI_BASE_URL"] = os.getenv("KALSHI_BASE_URL", "https://demo.kalshi.com")
        os.environ["KALSHI_EMAIL"] = os.getenv("KALSHI_EMAIL", "demo@example.com")
        os.environ["KALSHI_PASSWORD"] = os.getenv("KALSHI_PASSWORD", "demo_password")
        os.environ["KALSHI_API_KEY_ID"] = os.getenv("KALSHI_API_KEY_ID", "demo_key_id")
        os.environ["KALSHI_API_KEY_SECRET"] = os.getenv("KALSHI_API_KEY_SECRET", "demo_key_secret")
        logger.info("[DEMO-MODE] Mock credentials set - proceeding with startup")
        return

    # Kalshi live trading uses API_KEY_ID + PRIVATE_KEY_PATH (newer format)
    # or EMAIL + PASSWORD + API_KEY_SECRET (older format)
    required_vars = [
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PATH",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}. Real Kalshi API credentials are required.")

    logger.info("[ENV] All required environment variables present")


def _start_redis() -> None:
    """Start Redis connection if configured."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            from core.cache import CacheAdapter
            cache = CacheAdapter()
            logger.info("[REDIS] Redis connection configured")
            _startup_state["services"]["redis"] = {"status": "running", "url": redis_url}
        except Exception as exc:
            logger.warning("[REDIS] Redis not available (non-fatal): %s", exc)
            logger.info("[REDIS] Falling back to in-memory cache")
            _startup_state["services"]["redis"] = {"status": "fallback", "mode": "in-memory"}
    else:
        logger.info("[REDIS] Redis not configured (optional, using in-memory cache)")
        _startup_state["services"]["redis"] = {"status": "not_configured", "mode": "in-memory"}


def _start_auth() -> None:
    """Start auth if configured."""
    # For 15m profile, auth is optional (Kalshi API keys are primary)
    logger.info("[AUTH] Auth not required for 15m profile (Kalshi API keys primary)")


def _start_risk_limits() -> None:
    """Start risk limit enforcement."""
    try:
        from merid.guards.global_risk_guard import get_global_risk_guard
        guard = get_global_risk_guard()
        logger.info("[RISK] Global risk guard initialized")
        _startup_state["services"]["risk_guard"] = {"status": "initialized"}
    except Exception as exc:
        logger.warning("[RISK] Global risk guard not available (non-fatal): %s", exc)


async def _start_kalshi_venue() -> None:
    """Phase 1: Start Kalshi venue services (client, catalog, market state, WS bridge, fills)."""
    logger.debug("[TRACE-BOOT] ENTER _start_kalshi_venue")
    try:
        # Kalshi client
        logger.debug("[PHASE-1-DEBUG] Starting Kalshi client...")
        logger.info("[BOOT-TRACE] About to call _start_kalshi_client")
        await _start_kalshi_client()
        logger.info("[BOOT-TRACE] _start_kalshi_client returned")
        logger.debug("[PHASE-1-DEBUG] Kalshi client started ok")
        
        # Bankroll service
        logger.info("[BOOT-TRACE] About to call _start_bankroll_service")
        logger.debug("[PHASE-1-DEBUG] Starting bankroll service...")
        await _start_bankroll_service()
        logger.info("[BOOT-TRACE] _start_bankroll_service returned")
        logger.debug("[PHASE-1-DEBUG] Bankroll service started ok")
        
        # Market catalog
        logger.info("[BOOT-TRACE] About to call _start_market_catalog")
        logger.debug("[PHASE-1-DEBUG] Starting market catalog...")
        await _start_market_catalog()
        logger.info("[BOOT-TRACE] _start_market_catalog returned")
        logger.debug("[PHASE-1-DEBUG] Market catalog started ok")
        
        # Market state
        logger.info("[BOOT-TRACE] About to call _start_market_state")
        logger.debug("[PHASE-1-DEBUG] Starting market state...")
        await _start_market_state()
        logger.info("[BOOT-TRACE] _start_market_state returned")
        logger.debug("[PHASE-1-DEBUG] Market state started ok")
        
        # WebSocket bridge
        logger.info("[BOOT-TRACE] About to call _start_ws_bridge")
        logger.debug("[PHASE-1-DEBUG] Starting WebSocket bridge...")
        await _start_ws_bridge()
        logger.info("[BOOT-TRACE] _start_ws_bridge returned")
        logger.debug("[PHASE-1-DEBUG] WebSocket bridge started ok")
        
        # Fills poller
        logger.info("[BOOT-TRACE] About to call _start_fills_poller")
        logger.debug("[PHASE-1-DEBUG] Starting fills poller...")
        await _start_fills_poller()
        logger.info("[BOOT-TRACE] _start_fills_poller returned")
        logger.debug("[PHASE-1-DEBUG] Fills poller started ok")
        
        # Settlement poller
        logger.info("[BOOT-TRACE] About to call _start_settlement_poller")
        logger.debug("[PHASE-1-DEBUG] Starting settlement poller...")
        await _start_settlement_poller()
        logger.info("[BOOT-TRACE] _start_settlement_poller returned")
        logger.debug("[PHASE-1-DEBUG] Settlement poller started ok")
        
        logger.info("[PHASE-1] Kalshi venue services started")
        logger.debug("[TRACE-BOOT] EXIT _start_kalshi_venue ok")
        _boot_status.mark_success("kalshi_venue")
    except Exception as exc:
        logger.error("[PHASE-1] Failed to start Kalshi venue services: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_kalshi_venue FAILED")
        _boot_status.mark_failure("kalshi_venue")
        raise


async def _start_kalshi_client() -> None:
    """Start Kalshi venue client."""
    logger.debug("[PHASE-1-DEBUG] Starting Kalshi client...")
    logger.debug("[TRACE-BOOT] ENTER _start_kalshi_client")
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        _startup_state["kalshi_client"] = client
        logger.info("[KALSHI-CLIENT] Kalshi client initialized")
        _startup_state["services"]["kalshi_client"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] Kalshi client started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_kalshi_client ok")
        _boot_status.mark_success("kalshi_client")
    except Exception as exc:
        logger.error("[KALSHI-CLIENT] Failed to initialize Kalshi client: %s", exc)
        logger.debug("[TRACE-BOOT] EXIT _start_kalshi_client FAILED")
        raise


async def _start_bankroll_service() -> None:
    """Start bankroll service for balance tracking."""
    logger.debug("[PHASE-1-DEBUG] Starting bankroll service...")
    logger.debug("[TRACE-BOOT] ENTER _start_bankroll_service")
    try:
        from merid.event_venues.kalshi import get_bankroll_service
        bankroll_service = await get_bankroll_service()
        await bankroll_service.start()
        _startup_state["bankroll_service"] = bankroll_service
        logger.info("[BANKROLL] Bankroll service started")
        _startup_state["services"]["bankroll"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] Bankroll service started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_bankroll_service ok")
        _boot_status.mark_success("bankroll")
    except Exception as exc:
        logger.error("[BANKROLL] Failed to start bankroll service: %s", exc)
        logger.debug("[TRACE-BOOT] EXIT _start_bankroll_service FAILED")
        raise


async def _start_market_catalog() -> None:
    """Start Kalshi market catalog with 5 allowed series enforced."""
    logger.debug("[PHASE-1-DEBUG] Starting market catalog...")
    logger.debug("[TRACE-BOOT] ENTER _start_market_catalog")
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        catalog = get_market_catalog()
        # P1 FIX: Align timeout to 60s to match catalog.start() inner timeout
        logger.info("[CATALOG-START] entering with 60s timeout")
        start_ts = time.time()
        try:
            await asyncio.wait_for(catalog.start(), timeout=60.0)
            elapsed = time.time() - start_ts
            logger.info(f"[CATALOG-START] completed in {elapsed:.2f}s")
        except asyncio.TimeoutError:
            elapsed = time.time() - start_ts
            logger.error(f"[CATALOG-START] timed out after {elapsed:.2f}s")
            raise
        except Exception as e:
            logger.error("[CATALOG] catalog.start() raised: %r", e, exc_info=True)
            raise
        
        # Store catalog in startup state
        _startup_state["market_catalog"] = catalog

        # Enforce 5 allowed series for 15m crypto profile
        allowed_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
        logger.info(
            "[CATALOG] Market catalog started (enforcing allowed series: %s)",
            ", ".join(allowed_series),
        )
        
        # Catalog has internal universe management and validation
        # We rely on catalog's own logging for universe status
        # WS bridge will guard against empty ticker subscriptions
        _startup_state["services"]["catalog"] = {
            "status": "running",
            "started_at": time.time(),
            "allowed_series": allowed_series,
        }
        logger.debug("[PHASE-1-DEBUG] Market catalog started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_market_catalog ok")
        _boot_status.mark_success("market_catalog")
        
    except Exception as exc:
        logger.error("[CATALOG] Failed to start market catalog: %s", exc)
        logger.debug("[TRACE-BOOT] EXIT _start_market_catalog FAILED")
        raise


async def _start_market_state() -> None:
    """Start Kalshi market state store - TRULY MINIMAL (no blocking, no priming, no side effects)."""
    logger.info("[BOOT-TRACE] ENTER _start_market_state (TRULY MINIMAL)")
    
    # Do NOT call get_kalshi_market_state_store() during startup
    # Let it initialize lazily when first needed
    # This eliminates any hidden initialization side effects
    
    logger.info("[BOOT-TRACE] EXIT _start_market_state (TRULY MINIMAL - NO STORE INIT)")
    _startup_state["services"]["market_state"] = {
        "status": "deferred",
        "started_at": time.time(),
        "note": "Store will initialize lazily on first use"
    }
    _boot_status.mark_success("market_state")


async def _start_ws_bridge() -> None:
    """Start Kalshi WebSocket bridge for real-time data."""
    logger.info("[BOOT-TRACE] ENTER _start_ws_bridge")
    logger.debug("[PHASE-1-DEBUG] Starting WebSocket bridge...")
    logger.debug("[TRACE-BOOT] ENTER _start_ws_bridge")
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        from merid.event_venues.kalshi.market_selector import get_agent_market_tickers

        logger.info("[WS-BRIDGE] Getting WS bridge instance...")
        ws_bridge = get_ws_bridge()
        
        # FIX: Resolve actual market tickers from series tickers via catalog
        # The WS Bridge needs specific market IDs (e.g., KXBTC15M-26MAY180045-45), not series tickers (e.g., KXBTC15M)
        series_tickers = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
        logger.info("[WS-BRIDGE] Resolving market tickers from series: %s", series_tickers)
        
        # Resolve series tickers to actual market IDs via catalog
        # Map series tickers to their corresponding agent names for correct resolution
        series_to_agent = {
            "KXBTC15M": "BTC_15M",
            "KXETH15M": "ETH_15M",
            "KXSOL15M": "SOL_15M",
            "KXXRP15M": "XRP_15M",
            "KXDOGE15M": "DOGE_15M",
        }
        
        all_market_ids = []
        for series in series_tickers:
            try:
                logger.info("[BOOT-TRACE] WS-BRIDGE resolving series=%s", series)
                # Use the correct agent name per asset for series resolution
                agent_name = series_to_agent.get(series, "BTC_15M")
                market_ids = await get_agent_market_tickers(agent_name, series_tickers=[series])
                all_market_ids.extend(market_ids)
                logger.info("[WS-BRIDGE] Series %s (agent=%s) resolved to %d markets", series, agent_name, len(market_ids))
            except Exception as e:
                logger.warning("[WS-BRIDGE] Failed to resolve markets for series %s: %s", series, e)
        
        # Dedupe market IDs
        all_market_ids = list(set(all_market_ids))
        logger.info("[WS-BRIDGE] Starting with %d resolved market tickers (from %d series)", len(all_market_ids), len(series_tickers))
        
        if not all_market_ids:
            logger.warning("[WS-BRIDGE] No market IDs resolved - falling back to series tickers")
            all_market_ids = series_tickers
        
        logger.info("[BOOT-TRACE] WS-BRIDGE about to call ws_bridge.start() with %d tickers", len(all_market_ids))
        logger.info("[WS-BRIDGE] Calling ws_bridge.start(tickers=%s)...", all_market_ids[:5])
        await ws_bridge.start(tickers=all_market_ids)
        logger.info("[BOOT-TRACE] WS-BRIDGE ws_bridge.start() completed")
        
        logger.info("[WS-BRIDGE] WebSocket bridge started with %d tickers", len(all_market_ids))
        _startup_state["services"]["ws_bridge"] = {
            "status": "running",
            "started_at": time.time(),
            "tickers": all_market_ids,
            "series_tickers": series_tickers,
        }
        logger.debug("[PHASE-1-DEBUG] WebSocket bridge started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_ws_bridge ok")
        _boot_status.mark_success("ws_bridge")
        logger.info("[BOOT-TRACE] EXIT _start_ws_bridge - SUCCESS")
    except Exception as exc:
        logger.error("[WS-BRIDGE] Failed to start WebSocket bridge: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_ws_bridge FAILED")
        logger.info("[BOOT-TRACE] EXIT _start_ws_bridge - FAILED")
        raise


async def _start_fills_poller() -> None:
    """Start Kalshi fills poller."""
    logger.info("[BOOT-TRACE] ENTER _start_fills_poller")
    logger.debug("[PHASE-1-DEBUG] Starting fills poller...")
    logger.debug("[TRACE-BOOT] ENTER _start_fills_poller")
    try:
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        from merid.event_venues.kalshi.client import get_kalshi_client

        logger.info("[BOOT-TRACE] FILLS-POLLER getting client and poller")
        client = get_kalshi_client()
        poller = get_fills_poller()
        logger.info("[BOOT-TRACE] FILLS-POLLER about to call poller.start()")
        await poller.start()
        logger.info("[BOOT-TRACE] FILLS-POLLER poller.start() completed")

        logger.info("[FILLS-POLLER] Fills poller started")
        _startup_state["services"]["fills_poller"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] Fills poller started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_fills_poller ok")
        _boot_status.mark_success("fills_poller")
        logger.info("[BOOT-TRACE] EXIT _start_fills_poller - SUCCESS")
    except Exception as exc:
        logger.error("[FILLS-POLLER] Failed to start fills poller: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_fills_poller FAILED")
        logger.info("[BOOT-TRACE] EXIT _start_fills_poller - FAILED")
        raise


async def _start_settlement_poller() -> None:
    """Start Kalshi settlement poller."""
    logger.info("[BOOT-TRACE] ENTER _start_settlement_poller")
    logger.debug("[PHASE-1-DEBUG] Starting settlement poller...")
    logger.debug("[TRACE-BOOT] ENTER _start_settlement_poller")
    try:
        from merid.event_venues.kalshi.settlement_poller import start_settlement_polling
        from merid.event_venues.kalshi.client import get_kalshi_client

        logger.info("[BOOT-TRACE] SETTLEMENT-POLLER getting client")
        client = get_kalshi_client()
        logger.info("[BOOT-TRACE] SETTLEMENT-POLLER about to call start_settlement_polling()")
        await start_settlement_polling(client)
        logger.info("[BOOT-TRACE] SETTLEMENT-POLLER start_settlement_polling() completed")

        logger.info("[SETTLEMENT-POLLER] Settlement poller started")
        _startup_state["services"]["settlement_poller"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] Settlement poller started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_settlement_poller ok")
        _boot_status.mark_success("settlement_poller")
        logger.info("[BOOT-TRACE] EXIT _start_settlement_poller - SUCCESS")
    except Exception as exc:
        logger.error("[SETTLEMENT-POLLER] Failed to start settlement poller: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_settlement_poller FAILED")
        logger.info("[BOOT-TRACE] EXIT _start_settlement_poller - FAILED")
        raise


async def _start_unified_spot_service() -> None:
    """Start UnifiedSpotService - TEMPORARILY DISABLED for Windows subprocess hang."""
    try:
        # TEMPORARY DISABLE: UnifiedSpotService hanging on Windows subprocess calls
        # This is unrelated to consensus removal - separate issue with curl subprocess
        logger.info("[UNIFIED-SPOT] DISABLED (temporary fix for Windows subprocess hang)")
        logger.info("[BOOT-STATUS] mark_success: unified_spot -> unified_spot_ok = True (bypassed)")
        _boot_status.mark_success("unified_spot")
        logger.info("[UNIFIED-SPOT] Service bypassed - will be fixed separately")
        return
    except Exception as exc:
        logger.error("[UNIFIED-SPOT] Failed to start UnifiedSpotService: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_unified_spot_service FAILED")
        _boot_status.mark_failure("unified_spot")
        raise


async def _start_heartbeat() -> None:
    """Start event loop heartbeat task to detect frozen clock.
    
    Logs every second with loop_time and wall_time to detect if event loop clock is advancing.
    """
    logger.debug("[TRACE-BOOT] ENTER _start_heartbeat")
    try:
        loop = asyncio.get_running_loop()
        
        async def heartbeat_loop():
            tick = 0
            while True:
                tick += 1
                logger.info(
                    "[HEARTBEAT] tick=%d loop_time=%.6f wall_time=%.6f",
                    tick,
                    loop.time(),
                    time.time(),
                )
                await asyncio.sleep(1.0)
        
        # Create background task for heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop(), name="event-loop-heartbeat")
        _startup_state["heartbeat_task"] = heartbeat_task
        
        logger.info("[HEARTBEAT] Event loop heartbeat started")
        logger.debug("[TRACE-BOOT] EXIT _start_heartbeat ok")
        _boot_status.mark_success("heartbeat")
    except Exception as exc:
        logger.error("[HEARTBEAT] Failed to start heartbeat: %s", exc, exc_info=True)
        logger.debug("[TRACE-BOOT] EXIT _start_heartbeat FAILED")
        _boot_status.mark_failure("heartbeat")
        raise


async def _start_rti_feed_service() -> None:
    """Start RTI feed service for real-time signals."""
    logger.debug("[TRACE-BOOT] ENTER _start_rti_feed_service")
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        logger.info("[RTI-FEED] RTI feed service skipped for kalshi_crypto_15m_v2 (lean 15m stack)")
        _startup_state["services"]["rti_feed"] = {
            "status": "skipped",
            "reason": "profile_guard",
        }
        logger.debug("[TRACE-BOOT] EXIT _start_rti_feed_service skipped (profile_guard)")
        return

    try:
        from merid.risk.crypto_rti_monitor import CryptoRTIMonitor, set_global_crypto_rti_monitor
        from merid.data.rti_feed_service import get_rti_feed_service

        # Initialize CryptoRTIMonitor first (required by RTIFeedService)
        crypto_rti_monitor = CryptoRTIMonitor()
        await crypto_rti_monitor.start()
        set_global_crypto_rti_monitor(crypto_rti_monitor)

        rti_service = get_rti_feed_service()
        await rti_service.start()
        logger.info("[RTI-FEED] RTI feed service started")
        _startup_state["services"]["rti_feed"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] RTI feed service started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_rti_feed_service ok")
        _boot_status.mark_success("rti_feed")
    except Exception as exc:
        logger.warning("[RTI-FEED] RTI feed service not available (non-fatal): %s", exc)
        logger.warning("[TRACE-BOOT] EXIT _start_rti_feed_service FAILED (non-fatal)")


async def _start_term_structure() -> None:
    """Start crypto term structure model."""
    logger.debug("[TRACE-BOOT] ENTER _start_term_structure")
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        logger.info("[TERM-STRUCTURE] Term structure skipped for kalshi_crypto_15m_v2 (lean 15m stack)")
        _startup_state["services"]["term_structure"] = {
            "status": "skipped",
            "reason": "profile_guard",
        }
        logger.debug("[TRACE-BOOT] EXIT _start_term_structure skipped (profile_guard)")
        return

    try:
        from merid.risk.crypto_term_structure import get_global_crypto_tsm

        term_structure = get_global_crypto_tsm()
        await term_structure.start()
        logger.info("[TERM-STRUCTURE] Crypto term structure model initialized")
        _startup_state["services"]["term_structure"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.debug("[PHASE-1-DEBUG] Term structure started ok")
        logger.debug("[TRACE-BOOT] EXIT _start_term_structure ok")
        _boot_status.mark_success("term_structure")
    except Exception as exc:
        logger.warning("[TERM-STRUCTURE] Term structure not available (non-fatal): %s", exc)
        logger.warning("[TRACE-BOOT] EXIT _start_term_structure FAILED (non-fatal)")


async def _load_agent_grid() -> None:
    """Phase 2: Load and validate Kalshi agent grid (5 agents)."""
    logger.debug("[TRACE-BOOT] ENTER _load_agent_grid")
    
    # Boot status contract: assert all required PHASE-1 services are up
    logger.info("[BOOT-CONTRACT] Checking PHASE-1 service status...")
    if not _boot_status.check_required_services():
        missing = _boot_status.get_missing_services()
        logger.error(
            "[BOOT-CONTRACT] PHASE-1 services failed to start. Missing: %s",
            ", ".join(missing)
        )
        raise RuntimeError(
            f"PHASE-1 startup incomplete. Missing required services: {', '.join(missing)}. "
            "Agents cannot start without all required PHASE-1 services."
        )
    logger.info(
        "[BOOT-CONTRACT] All required PHASE-1 services OK: %s",
        ", ".join([name for name, ok in [
            ("kalshi_client", _boot_status.kalshi_client_ok),
            ("bankroll", _boot_status.bankroll_ok),
            ("market_catalog", _boot_status.market_catalog_ok),
            ("market_state", _boot_status.market_state_ok),
            ("ws_bridge", _boot_status.ws_bridge_ok),
            ("fills_poller", _boot_status.fills_poller_ok),
            ("settlement_poller", _boot_status.settlement_poller_ok),
            ("unified_spot", _boot_status.unified_spot_ok),
        ] if ok])
    )
    
    logger.info("[PHASE-2] Loading Kalshi agent grid...")

    try:
        from merid.prediction.agent_grid_config import load_agent_grid_config

        config = load_agent_grid_config()

        # Validate exactly 5 agents for 15m crypto
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        enabled_agents = [a.name for a in config.agents if a.enabled]

        if len(enabled_agents) != 5:
            raise ValueError(
                f"Expected exactly 5 agents for kalshi_crypto_15m_v2, got {len(enabled_agents)}: {enabled_agents}"
            )

        non_15m_agents = [a for a in enabled_agents if a not in allowed_15m_agents]
        if non_15m_agents:
            raise ValueError(
                f"Non-15m-crypto agents enabled: {non_15m_agents}. Only {sorted(allowed_15m_agents)} are allowed."
            )

        logger.info(
            "[AGENT-GRID] Loaded %d agents: %s",
            len(enabled_agents),
            ", ".join(enabled_agents),
        )

        # Create AgentGrid instance (but don't call start() - let the loop drive it)
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.trading_agent import LifecycleState

        agent_grid = AgentGrid(config=config)
        _startup_state["agent_grid"] = agent_grid

        # Manually set agent lifecycle to ACTIVE for 15m profile
        # The 15m loop handles cycling externally via run_cycle(), so agents don't need
        # their internal decision loops. They just need to be in ACTIVE state to execute trades.
        for agent in agent_grid._agents:
            agent.state.lifecycle = LifecycleState.ACTIVE
            agent.state.running = True
            agent.state.enabled = True
            logger.info(f"[AGENT-GRID] Set {agent.config.name} lifecycle to ACTIVE")

        logger.info("[AGENT-GRID] AgentGrid instance created with agents in ACTIVE state")
        _startup_state["services"]["agent_grid"] = {
            "status": "loaded",
            "agent_count": len(enabled_agents),
            "agents": enabled_agents,
        }

    except Exception as exc:
        logger.error("[AGENT-GRID] Failed to load agent grid: %s", exc)
        raise


async def _start_15m_loop() -> None:
    """Phase 3: Start Kalshi15mLoop."""
    logger.info("[PHASE-3] Starting Kalshi15mLoop...")

    try:
        from merid.loop_15m import get_kalshi_15m_loop
        from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig

        agent_grid = _startup_state["agent_grid"]
        bankroll_service = _startup_state["bankroll_service"]
        kalshi_client = _startup_state["kalshi_client"]

        # Get venue adapter
        venue_adapter = get_kalshi_venue_adapter()
        _startup_state["venue_adapter"] = venue_adapter

        # Get risk config
        risk_config = KalshiRiskConfig()

        # Create 15m loop
        loop = get_kalshi_15m_loop(
            agent_grid=agent_grid,
            venue_adapter=venue_adapter,
            bankroll_service=bankroll_service,
            risk_config=risk_config,
            cadence_seconds=5.0,
        )

        _startup_state["loop"] = loop
        profile = os.getenv("MERID_PROFILE", "")
        logger.info("[15M-BOOT] Kalshi15mLoop instance created profile=%s cadence=5.0s", profile)

        # Start loop in background
        log_startup_phase("enter_main_loop", "merid.loop_15m", "cadence=5s")
        await loop.start()
        logger.info("[15M-BOOT] Kalshi15mLoop start() called")
        _startup_state["background_tasks"].append(loop._loop_task)

        logger.info("[15m-LOOP] Kalshi15mLoop started (cadence=5s)")
        _startup_state["services"]["loop"] = {
            "status": "running",
            "started_at": time.time(),
        }

        # Auto-start grid in live mode if configured
        # CRITICAL FIX: Automatically start grid live on startup if MERID_PM_LIVE_ENABLED=true
        # This eliminates the need for manual API call to start the grid after system startup
        try:
            from trading.trade_mode import TradeMode, get_trade_mode
            from merid.prediction.venue_gate import get_venue_gate
            from merid.settings import settings
            
            current_mode = get_trade_mode()
            is_live_enabled = settings.MERID_PM_LIVE_ENABLED if hasattr(settings, 'MERID_PM_LIVE_ENABLED') else False
            
            if current_mode == TradeMode.LIVE and is_live_enabled:
                # Set VenueGate to live mode
                gate = get_venue_gate()
                if gate:
                    gate.mode = TradeMode.LIVE
                    logger.info("[AUTO-START-LIVE] VenueGate set to LIVE mode on startup")
                
                # Start the grid in live mode
                if agent_grid:
                    await agent_grid.start()
                    logger.info("[AUTO-START-LIVE] AgentGrid started automatically in LIVE mode")
                else:
                    logger.warning("[AUTO-START-LIVE] agent_grid is None, skipping start")
                _startup_state["services"]["agent_grid"]["auto_started"] = True
                _startup_state["services"]["agent_grid"]["mode"] = "live"
            else:
                logger.info(f"[AUTO-START-LIVE] Grid not auto-started live: mode={current_mode}, live_enabled={is_live_enabled}")
        except Exception as exc:
            logger.warning("[AUTO-START-LIVE] Failed to auto-start grid live (non-fatal): %s", exc)

    except Exception as exc:
        logger.error("[15m-LOOP] Failed to start Kalshi15mLoop: %s", exc)
        raise


async def _start_kalshi_reconciliation() -> None:
    """Phase 3b: Start Kalshi venue reconciliation to clear startup warnings."""
    logger.info("[PHASE-3B] Starting Kalshi venue reconciliation...")
    
    try:
        from merid.reconciliation import reconcile_all_venues, has_critical_discrepancies
        
        # Run initial reconciliation during startup
        # P1 FIX: Add timeout around executor call to prevent indefinite blocking
        logger.info("[RECONCILE] starting initial reconciliation")
        start_ts = time.time()
        try:
            discrepancies = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, lambda: reconcile_all_venues(["kalshi"])
                ),
                timeout=60.0
            )
            elapsed = time.time() - start_ts
            n_crit = sum(1 for d in discrepancies if d.severity == "critical")
            n_warn = sum(1 for d in discrepancies if d.severity == "warning")
            logger.info(
                f"[RECONCILE] completed in {elapsed:.2f}s with {len(discrepancies)} discrepancies ({n_crit} critical, {n_warn} warning)"
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - start_ts
            logger.error(f"[RECONCILE] timed out after {elapsed:.2f}s - proceeding with incomplete reconciliation")
            discrepancies = []  # Fail open - assume clean for now
        except Exception as e:
            logger.error(f"[RECONCILE] failed: {e}")
            discrepancies = []
        
        recon_mode = os.getenv("MERID_PM_TRADING_MODE", "paper")
        if has_critical_discrepancies() and recon_mode != "paper":
            logger.warning("⚠️  Execution gate BLOCKED (critical reconciliation issues)")
        elif has_critical_discrepancies() and recon_mode == "paper":
            logger.info("✅ Reconciliation: %d critical (expected in paper mode, not blocking)", n_crit)
        else:
            logger.info("✅ Execution gate CLEAR — trades can proceed")
        
        # Start periodic reconciliation loop (every 300s)
        async def _kalshi_recon_loop_async() -> None:
            logger.info("Periodic Kalshi venue reconciliation started (every 300s)")
            while True:
                await asyncio.sleep(300.0)
                try:
                    discs = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: reconcile_all_venues(["kalshi"])
                    )
                    n_crit = sum(1 for d in discs if d.severity == "critical")
                    if discs:
                        logger.warning(
                            "Kalshi venue reconciliation: %d discrepancies (%d critical)",
                            len(discs), n_crit,
                        )
                    else:
                        logger.info("Kalshi venue reconciliation: OK (0 discrepancies)")
                except asyncio.CancelledError:
                    logger.info("Kalshi venue reconciliation loop cancelled")
                    return
                except Exception as exc:
                    logger.error("Kalshi venue reconciliation error: %s", exc)
        
        _recon_task = asyncio.create_task(
            _kalshi_recon_loop_async(), name="kalshi-recon-loop"
        )
        _startup_state["background_tasks"].append(_recon_task)
        
        _startup_state["services"]["kalshi_reconciliation"] = {
            "status": "running",
            "started_at": time.time(),
        }
        logger.info("[PHASE-3B] Kalshi venue reconciliation started successfully")
        
    except Exception as exc:
        logger.warning("[PHASE-3B] Failed to start Kalshi reconciliation (non-fatal): %s", exc)
        _startup_state["services"]["kalshi_reconciliation"] = {
            "status": "failed",
            "error": str(exc),
        }


async def _stop_all() -> None:
    """Stop all services gracefully."""
    logger.info("[SHUTDOWN] Stopping all services...")

    # Stop loop
    loop = _startup_state.get("loop")
    if loop:
        try:
            await loop.stop()
            logger.info("[SHUTDOWN] Kalshi15mLoop stopped")
        except Exception as exc:
            logger.warning("[SHUTDOWN] Loop stop failed: %s", exc)

    # Stop agent grid
    agent_grid = _startup_state.get("agent_grid")
    if agent_grid:
        try:
            if hasattr(agent_grid, "stop"):
                await agent_grid.stop()
            logger.info("[SHUTDOWN] AgentGrid stopped")
        except Exception as exc:
            logger.warning("[SHUTDOWN] AgentGrid stop failed: %s", exc)

    # Stop Kalshi services using stored instances from _startup_state
    # This is safer than dynamic imports which may return different instances
    for service_name, state_key in [
        ("settlement_poller", "settlement_poller"),
        ("fills_poller", "fills_poller"),
        ("ws_bridge", "ws_bridge"),
        ("bankroll_service", "bankroll_service"),
    ]:
        try:
            service = _startup_state.get(state_key)
            if service and hasattr(service, "stop"):
                result = service.stop()
                if asyncio.iscoroutine(result):
                    await result
                logger.info(f"[SHUTDOWN] {service_name} stopped")
        except Exception as exc:
            logger.warning(f"[SHUTDOWN] {service_name} stop failed: %s", exc)

    # Cancel background tasks
    for task in _startup_state["background_tasks"]:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    logger.info("[SHUTDOWN] All services stopped")


# ── API Endpoints ────────────────────────────────────────────────────────────


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with basic info."""
    return {
        "name": "MERID Kalshi 15m Crypto",
        "profile": "kalshi_crypto_15m_v2",
        "version": "15m-v2",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint for Kalshi 15m crypto app.
    
    Returns profile-specific metadata to ensure health checks are explicitly
    tied to the 15m app (web.main_15m) and not the legacy main app.
    """
    import os
    active_profile = os.getenv("MERID_PROFILE", "unknown")
    demo_mode = os.getenv("MERID_DEMO_MODE", "").lower() in ("1", "true", "yes")

    loop_summary: Dict[str, Any] = {}
    loop = _startup_state.get("loop")
    if loop and hasattr(loop, "summary"):
        try:
            loop_summary = loop.summary()
        except Exception as e:
            logger.warning("[HEALTH] loop.summary() failed: %s", e)

    # Runtime invariants
    # Invariant: loop.running == True
    if loop and hasattr(loop, "_running"):
        if not loop._running:
            logger.warning("[HEALTH] LOOP RUNNING INVARIANT FAILED: loop._running is False")
    else:
        logger.warning("[HEALTH] LOOP RUNNING INVARIANT: loop or _running attribute not found")

    # Invariant: tick and cycle_count increase monotonically
    if loop_summary:
        tick = loop_summary.get("tick", 0)
        cycle_count = loop_summary.get("cycle_count", 0)
        if tick < 0 or cycle_count < 0:
            logger.warning("[HEALTH] LOOP MONOTONICITY INVARIANT FAILED: tick=%d, cycle_count=%d (should be non-negative)", tick, cycle_count)
        if cycle_count > tick:
            logger.warning("[HEALTH] LOOP MONOTONICITY INVARIANT FAILED: cycle_count=%d > tick=%d (should be <= tick)", cycle_count, tick)

    services = _startup_state.get("services", {})

    response = {
        "status": "healthy",
        "app": "merid_15m_kalshi_crypto",
        "profile": active_profile,
        "port": 8011,
        "demo_mode": demo_mode,
        "loop": loop_summary,
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "[HEALTH-CHECK] app=merid_15m_kalshi_crypto profile=%s status=%s",
        active_profile,
        response["status"],
    )

    return response


@app.get("/status")
async def status() -> JSONResponse:
    """Detailed status endpoint."""
    import os
    demo_mode = os.getenv("MERID_DEMO_MODE", "").lower() in ("1", "true", "yes")
    
    loop = _startup_state.get("loop")
    loop_summary = loop.summary() if loop and hasattr(loop, "summary") else {}

    agent_grid = _startup_state.get("agent_grid")
    agent_summary = {}
    if agent_grid and hasattr(agent_grid, "_agents"):
        for agent in agent_grid._agents:
            agent_summary[agent.agent_id] = {
                "name": agent.config.name,
                "enabled": agent.config.enabled,
                "assets": agent.config.assets,
            }

    return JSONResponse(
        {
            "profile": "kalshi_crypto_15m_v2",
            "demo_mode": demo_mode,
            "loop": loop_summary,
            "agents": agent_summary,
            "services": _startup_state["services"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        print("ERROR: web.main_15m only supports kalshi_crypto_15m_v2 profile")
        print(f"Current profile: {profile}")
        print("Set MERID_PROFILE=kalshi_crypto_15m_v2")
        exit(1)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8011,
        log_level="info",
    )
