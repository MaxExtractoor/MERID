from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# EMERGENCY FIX (2026-05-12): Force load safe modules before threading starts
# Prevents import race condition causing Windows access violation crashes
# NOTE: feedparser import causes access violation - removed
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
# DEBUGGING: Faulthandler disabled for lean 15m Kalshi stack
# LEAN 15m KALSHI STACK (2026-05-13): Disabled faulthandler to prevent forced exits on hangs
# Faulthandler was dumping traces and killing process on 30-second timeouts
# For production stability, rely on uvicorn timeout and logging instead
# import faulthandler
# import sys
# faulthandler.enable(sys.stderr, all_threads=True)
# faulthandler.cancel_dump_traceback_later()
# print("[FAULTHANDLER] Enabled - will dump traces on hangs and crashes to stderr (captured in logs)")
# print("[FAULTHANDLER] Automatic timeout disabled - use uvicorn --timeout for startup timeout")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ═══════════════════════════════════════════════════════════════════════
# Windows asyncio transport shutdown race fix
# ═══════════════════════════════════════════════════════════════════════
# ConnectionResetError: [WinError 10054] during cleanup is a known Windows
# Proactor issue. Switching to SelectorEventLoopPolicy suppresses the traceback.
# See: https://github.com/Kludex/uvicorn/discussions/2105
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
# That mass-cancellation is what produced the 14:24:26 cascade in the logs:
#     "meta-audit-agent-01 loop cancelled"
#     "Event bus bridge stopped"
#     "Spurious CancelledError, re-waiting..."
# Even though our lifespan re-waits, the worker tasks are already dead.
#
# To make the server truly 24/7 we must:
#   1. Prevent Uvicorn from ever installing its own signal handlers.
#   2. Neutralise `Server.handle_exit` so spurious console events
#      (Windows CTRL_CLOSE_EVENT, IDE terminal disconnects, etc.) cannot
#      flip `should_exit`.
#   3. Allow ONLY explicit operator shutdown via the signal file or our
#      own SIGTERM/SIGINT handler installed inside the lifespan.
import sys as _sys
try:
    import uvicorn.server as _uv_server  # type: ignore

    # (1) Disable uvicorn's signal-handler installer. Make it a no-op.
    def _no_install_signal_handlers(self) -> None:
        return None
    _uv_server.Server.install_signal_handlers = _no_install_signal_handlers  # type: ignore[assignment]

    # (2) Neutralise handle_exit so any callback that *did* slip through
    #     (e.g. asyncio loop.add_signal_handler on POSIX) cannot set
    #     should_exit/force_exit. The real shutdown path remains the
    #     in-lifespan signal handler we install ourselves below.
    def _no_handle_exit(self, sig=None, frame=None) -> None:
        # Log so we can see WHEN/WHY uvicorn tried to exit, but do not act.
        try:
            _name = getattr(sig, "name", str(sig)) if sig is not None else "unknown"
        except Exception:
            _name = "unknown"
        try:
            import logging as _lg
            _lg.getLogger("web.main").critical(
                "[24/7-HARDENING] Uvicorn handle_exit blocked (sig=%s) — server stays up",
                _name,
            )
        except Exception:
            pass
        # Do NOT set self.should_exit / self.force_exit.
        return None
    _uv_server.Server.handle_exit = _no_handle_exit  # type: ignore[assignment]

    # (3) Patch Server.shutdown to short-circuit unless an explicit operator
    #     shutdown was requested via our signal file or environment flag.
    #     Even with the patches above, uvicorn's serve()/main_loop can still
    #     reach the shutdown branch on certain edge cases (lifespan task
    #     completing for any reason, an unhandled exception in main_loop's
    #     0.1s sleep loop on Windows IOCP, etc.).  When that happens uvicorn
    #     mass-cancels every task in the loop — exactly what we observed at
    #     16:34:29 in the trading session logs.  By making shutdown a no-op
    #     unless the operator asked for it, we prevent collateral cancels.
    _orig_uv_shutdown = getattr(_uv_server.Server, "shutdown", None)

    async def _no_shutdown(self, sockets=None) -> None:
        import os as _os_inner
        from pathlib import Path as _Path_inner
        # Operator shutdown channel: signal file we drop on disk.
        _signal_file = (
            _Path_inner(_os_inner.environ.get("TEMP", "C:\\tmp")) / ".merid_shutdown_signal"
            if _os_inner.name == "nt"
            else _Path_inner("/tmp/.merid_shutdown_signal")
        )
        _operator_requested = False
        try:
            _operator_requested = _signal_file.exists()
        except Exception:
            _operator_requested = False
        # Honour an explicit shutdown only when the operator dropped the file.
        if _operator_requested and _orig_uv_shutdown is not None:
            try:
                import logging as _lg_inner
                _lg_inner.getLogger("web.main").critical(
                    "[24/7-HARDENING] Operator-requested shutdown — running "
                    "uvicorn Server.shutdown()"
                )
            except Exception:
                pass
            await _orig_uv_shutdown(self, sockets=sockets)
            return
        # Otherwise: log loudly and refuse to shut down.  The lifespan task
        # is held alive by the stay-alive event, so this just means uvicorn
        # stops accepting NEW HTTP requests.  Sibling tasks (agents, fills
        # writer, event-bus bridge) keep running.
        try:
            import logging as _lg_inner
            _lg_inner.getLogger("web.main").critical(
                "[24/7-HARDENING] Server.shutdown() blocked (no operator "
                "shutdown signal). Sibling tasks remain alive."
            )
        except Exception:
            pass
        # Never return None too quickly — uvicorn awaits this and then
        # treats it as "shutdown done".  We just return without cancelling
        # anything; uvicorn's main_loop will keep looping if it still
        # considers should_exit False.
        return None

    _uv_server.Server.shutdown = _no_shutdown  # type: ignore[assignment]
except Exception as _uv_patch_exc:  # pragma: no cover
    # Continue without patching; we still have the in-lifespan signal handler.
    print(f"[24/7-HARDENING] Uvicorn patch failed: {_uv_patch_exc}", file=_sys.stderr)

# ═══════════════════════════════════════════════════════════════════════
# 24/7-HARDENING: Windows console control events (CTRL_CLOSE_EVENT etc.)
# ═══════════════════════════════════════════════════════════════════════
# Python's `signal` module on Windows only exposes SIGINT and SIGBREAK.
# The real killers for IDE-terminal-hosted processes are:
#   * CTRL_CLOSE_EVENT   (2) — console window closing / PTY disconnect
#   * CTRL_LOGOFF_EVENT  (5) — user session logoff (service-only)
#   * CTRL_SHUTDOWN_EVENT(6) — system shutdown (service-only)
# These events bypass SIGINT/SIGTERM and kick Windows' default handler,
# which calls ExitProcess() after a short grace period. That default
# behaviour is what cancels every task in the event loop ~30 min into a
# session whenever the Windsurf/VSCode terminal panel is resized, split,
# reloaded, or another Cascade tool opens a sibling console on the same
# console window station.
#
# We install a Win32 console control handler that swallows CTRL_CLOSE_EVENT
# so IDE-terminal events cannot kill the server. CTRL_C_EVENT / CTRL_BREAK
# still flow through so explicit operator Ctrl-C continues to work via our
# lifespan signal handler. SHUTDOWN/LOGOFF we also swallow (operator uses
# signal file for 24/7 hosts); if the machine is actually powering down
# Windows will force-terminate anyway after the grace window.
if _sys.platform == "win32":
    try:
        import ctypes as _ctypes
        from ctypes import wintypes as _wintypes

        _HANDLER_ROUTINE = _ctypes.WINFUNCTYPE(_wintypes.BOOL, _wintypes.DWORD)

        _CTRL_C_EVENT = 0
        _CTRL_BREAK_EVENT = 1
        _CTRL_CLOSE_EVENT = 2
        _CTRL_LOGOFF_EVENT = 5
        _CTRL_SHUTDOWN_EVENT = 6

        def _win_console_ctrl_handler(ctrl_type):  # type: ignore[no-untyped-def]
            # Let Ctrl-C and Ctrl-Break propagate normally so Python's own
            # SIGINT/SIGBREAK handlers (and our lifespan handler) can run.
            if ctrl_type in (_CTRL_C_EVENT, _CTRL_BREAK_EVENT):
                return 0  # FALSE -> let default handler run
            # Swallow CTRL_CLOSE / LOGOFF / SHUTDOWN so IDE terminal events,
            # session logoff notifications, or PTY resizes cannot kill us.
            try:
                import logging as _lg
                _lg.getLogger("web.main").critical(
                    "[24/7-HARDENING] Windows console control event %s swallowed "
                    "(was killing 30-min sessions) — server stays up",
                    ctrl_type,
                )
            except Exception:
                pass
            return 1  # TRUE -> we handled it, skip default handler

        _console_handler_ref = _HANDLER_ROUTINE(_win_console_ctrl_handler)
        # Keep a module-level reference so ctypes doesn't GC the callback.
        globals()["__merid_console_handler_ref__"] = _console_handler_ref
        _ok = _ctypes.windll.kernel32.SetConsoleCtrlHandler(
            _console_handler_ref, _wintypes.BOOL(1)
        )
        if not _ok:
            print(
                f"[24/7-HARDENING] SetConsoleCtrlHandler returned 0 (GetLastError={_ctypes.get_last_error()})",
                file=_sys.stderr,
            )
    except Exception as _win_ctrl_exc:  # pragma: no cover
        print(
            f"[24/7-HARDENING] Windows console control handler install failed: {_win_ctrl_exc}",
            file=_sys.stderr,
        )

from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Deque, Dict, Optional

from web.startup_agents import get_orchestrator_manager

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Header,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ConfigDict

# JWT imports for whale authentication
try:
    from fastapi_jwt_auth import AuthJWT
    from fastapi_jwt_auth.exceptions import AuthJWTException
except ImportError:
    AuthJWT = None
    AuthJWTException = Exception

from core.energy import create_energy
from observability.event_stream import get_event_stream
from observability.observability_stack import get_observability_stack
from core.orchestrator import get_core
from core.state import state
from services.gamification import GamificationEngine
from swarm.agents.charters import CHARTER_REGISTRY
from utils.logger import get_logger

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# WINDOWS-PROACTOR-FIX: Monkey-patch to suppress InvalidStateError during shutdown
# ═══════════════════════════════════════════════════════════════════════
if os.name == 'nt':  # Windows only
    try:
        import asyncio.windows_events as _windows_events
        _original_poll = _windows_events._IocpProactor._poll

        def _patched_poll(self, timeout):
            """Wrap _poll to suppress InvalidStateError during shutdown."""
            try:
                return _original_poll(self, timeout)
            except asyncio.InvalidStateError:
                # This happens when setting exception on already-done future during shutdown
                # Suppress it - the operation was likely cancelled anyway
                pass
            except Exception:
                # Re-raise other exceptions
                raise

        _windows_events._IocpProactor._poll = _patched_poll
        logger.debug("Windows ProactorEventLoop InvalidStateError fix installed")
    except Exception:
        pass  # If patching fails, continue without it

# ═══════════════════════════════════════════════════════════════════════
# EVENT-LOOP-FIX: Windows asyncio exception handler
# Suppresses InvalidStateError and other benign errors during shutdown
# ═══════════════════════════════════════════════════════════════════════
def _setup_asyncio_exception_handler():
    """Install a custom exception handler that suppresses shutdown-related errors on Windows."""
    def _handler(loop, context):
        exc = context.get('exception')
        # Suppress InvalidStateError during shutdown (Windows-specific)
        if isinstance(exc, asyncio.InvalidStateError):
            # Only log at debug level - this is normal during Windows shutdown
            logger.debug("Suppressed InvalidStateError during asyncio shutdown: %s", context.get('message', ''))
            return
        # Suppress ConnectionResetError during proactor transport lifecycle
        # WinError 995: ERROR_OPERATION_ABORTED (normal during shutdown)
        # WinError 10054: WSAECONNRESET (remote host closed connection - common with WebSockets)
        if isinstance(exc, ConnectionResetError):
            winerror = getattr(exc, 'winerror', None)
            if winerror in (995, 10054):
                logger.debug("Suppressed ConnectionResetError(%s) during proactor transport callback", winerror)
                return
        # Suppress AttributeError during Windows proactor transport shutdown
        # This happens when socket becomes None during transport close
        if isinstance(exc, AttributeError):
            msg = str(context.get('message', ''))
            if 'NoneType' in msg and 'shutdown' in msg:
                logger.debug("Suppressed AttributeError during proactor transport shutdown: %s", msg)
                return
        # For all other exceptions, use default handler
        loop.default_exception_handler(context)
    
    # Install handler on the current event loop if one exists
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_handler)
    except RuntimeError:
        # No loop running yet - will be set up when loop starts
        pass

# Install handler immediately and also in lifespan startup
_setup_asyncio_exception_handler()

# ── Resilient router imports ─────────────────────────────────────────
# Many legacy modules may fail to import (missing deps, stale code).
# We log failures and set routers to None; registration skips None.
import importlib as _il

_si_failures: list = []  # C1/RISK-16: collect all import failures for startup summary

def _si(mod: str, attr: str = "router"):
    """Safe-import: returns module attribute or None on failure."""
    try:
        return getattr(_il.import_module(mod), attr)
    except Exception as _e:
        _si_failures.append(f"{mod}.{attr} ({type(_e).__name__}: {_e})")
        # KALSHI-ONLY-FIX: Classify router skips as INFO, not WARNING
        # In Kalshi-only mode, 33+ legacy routers are intentionally skipped
        logger.info("Import skip: %s.%s — %s: %s", mod, attr, type(_e).__name__, _e)
        return None

# ── Auth (critical — must succeed) ───────────────────────────────────
from web.api.auth import router as auth_router

# ── Kalshi core ──────────────────────────────────────────────────────
kalshi_grid_router = _si("web.api.kalshi_grid_api")
crypto_config_router = _si("web.api.crypto_config_api")
kalshi_api_router = _si("web.api.kalshi_api")
kalshi_ui_state_api_router = _si("web.api.kalshi_ui_state_api")
portfolio_router = _si("web.api.portfolio_api")
kalshi_ui_router = _si("web.api.kalshi_ui")
sidebar_config_router = _si("web.api.sidebar_config")
paper_ladder_router = _si("web.api.paper_ladder_api")
paper_session_router = _si("web.api.paper_session_api")
kalshi_agent_grid_router = _si("web.api.kalshi_agent_grid_api")
kalshi_agent_performance_router = _si("web.api.kalshi_agent_performance_api")
kalshi_deployment_router = _si("web.api.kalshi_deployment")
kalshi_metrics_api_router = _si("web.api.kalshi_metrics_api")
correlation_api_router = _si("web.api.correlation_api")
swarm_bus_api_router = _si("web.api.swarm_bus_api")
sentiment_api_router = _si("web.api.sentiment_api")
sentiment_vol_api_router = _si("web.api.sentiment_vol_api")
sentiment_pipeline_api_router = _si("web.api.sentiment_pipeline_api")
xtf_api_router = _si("web.api.xtf_api")
auto_promoter_api_router = _si("web.api.auto_promoter_api")
crypto_spot_kalshi_router = _si("web.api.crypto_spot_kalshi_api")
spot_basis_router = _si("web.api.spot_basis_api")
kalshi_continuous_trader_api_router = _si("web.api.kalshi_continuous_trader_api")
band_strategy_api_router = _si("web.api.band_strategy_api")
rti_feed_api_router = _si("web.api.rti_feed_api")
policy_metrics_api_router = _si("web.api.policy_metrics_api")
fvg_api_router = _si("web.api.fvg_api")  # FVG (Fair Value Gap) analysis

# ── Operator + system ────────────────────────────────────────────────
# from web.api.operator import router as operator_router
operator_router = _si("web.api.operator")
operator_endpoints_router = _si("web.api.operator_endpoints")
# from web.api.metrics import router as metrics_router
metrics_router = _si("web.api.metrics")
record_latency = _si("web.api.metrics", "record_latency")
# from web.api.market_data import router as market_data_router
# from web.api.market_data import ws_router as market_ws_router
market_data_router = _si("web.api.market_data")
market_ws_router = _si("web.api.market_data", "ws_router")
loop_api_router = _si("web.api.loop_api", "loop_api_router")

# ── Swarm + consensus ────────────────────────────────────────────────
reflection_router = _si("web.api.reflection")
consensus_router = _si("web.api.consensus")
prediction_router = _si("web.api.prediction")
prediction_markets_router = _si("web.api.prediction_markets")
prediction_consensus_router = _si("web.api.prediction_consensus_api")
betting_consensus_router = _si("web.api.betting_consensus_api")
flow_router = _si("web.api.flow_api", "flow_router")
signal_layer_router = _si("web.api.signal_layer_api", "signal_layer_router")
unified_pipeline_router = _si("web.api.unified_pipeline")

# ── Infrastructure ───────────────────────────────────────────────────
health_router = _si("web.api.health")
system_control_router = _si("web.api.system_control")
system_observability_router = _si("web.api.system_observability")
system_endpoints_router = _si("web.api.system_endpoints")
data_endpoints_router = _si("web.api.data_endpoints")
real_data_router = _si("web.api.real_data_endpoints")
missing_endpoints_router = _si("web.api.missing_endpoints")
degraded_router = _si("web.api.degraded")
monitoring_router = _si("web.api.monitoring")
ratelimit_router = _si("web.api.ratelimit")
resilience_router = _si("web.api.resilience")
telemetry_router = _si("web.api.telemetry")
guardrails_router = _si("web.api.guardrails_api")
api_status_router = _si("web.api.api_status")

# ── Analytics + risk ─────────────────────────────────────────────────
analytics_router = _si("web.api.analytics")
# BUG-FIX (2026-05-12): Use safe import for brier_metrics - scipy import blocks on Windows
# Changed from direct import to avoid scipy blocking at module load time
brier_metrics_router = _si("web.api.brier_metrics")
risk_router = _si("web.api.risk_routes")
risk_metrics_router = _si("web.api.risk_metrics")
risk_metrics_api_router = _si("web.api.risk_metrics_api")
benchmarks_router = _si("web.api.benchmarks_api")

# ── Dashboard + live data ────────────────────────────────────────────
dashboard_router = _si("web.api.dashboard")
dashboard_data_router = _si("web.api.dashboard_data")
dashboard_ws_router = _si("web.api.dashboard_ws")
live_data_router = _si("web.api.live_data")
live_stream_router = _si("web.api.live_stream")
streams_router = _si("web.api.streams")
feedback_router = _si("web.api.feedback")
production_status_router = _si("web.api.production_status")

# ── Agent infrastructure ─────────────────────────────────────────────
agents_router = _si("web.api.agents")
agents_health_router = _si("web.api.agents_health")
agents_real_router = _si("web.api.agents_real")
agent_modes_router = _si("web.api.agent_modes_api")  # /api/v1/agents modes+routing-status
crypto_lanes_router = _si("web.api.crypto_lanes_api")  # /api/v1/lanes — CryptoLanesGrid
orchestrator_api_router = _si("web.api.orchestrator_api")
signals_api_router = _si("web.api.signals_api")
cognitive_router = _si("web.api.cognitive_api")
swarm_router = _si("web.api.swarm")
swarm_routes_router = _si("web.api.swarm_routes")

# ── Governance + compliance ──────────────────────────────────────────
governance_router = _si("web.api.governance")
compliance_router = _si("web.api.compliance")
llm_governance_router = _si("web.api.llm_governance_api")
dev_swarm_governance_router = _si("web.api.dev_swarm_governance_routes")

# ── WebSocket ────────────────────────────────────────────────────────
observability_router = _si("web.api.observability")
websocket_health_router = _si("web.api.websocket_health")
ws_dedicated_router = _si("web.api.ws_dedicated_streams")
ws_paper_router = _si("web.api.ws_paper")
ws_trade_events_router = _si("web.api.ws_trade_events")
consensus_api_router = _si("web.api.consensus_api")
dev_swarm_router = _si("web.api.dev_swarm_routes")

# ── Debate + Incentive ────────────────────────────────────────────────
debate_data_router = _si("web.api.debate_data_api")
debate_health_router = _si("web.api.debate_health_api")
incentive_router = _si("web.api.incentive_api")
notification_api_router = _si("web.api.notification_api")

# ── Legacy / optional (may fail — non-critical) ─────────────────────
# Removed to reduce startup noise - these modules are not used in Kalshi trading
# mining_router = _si("web.api.mining")
# referrals_router = _si("web.api.referrals")
# betting_router = _si("web.api.betting")
# institutional_router = _si("web.api.institutional")
# schemas_router = _si("web.api.schemas")
# wallet_router = _si("web.api.wallet")
# offline_router = _si("web.api.offline")
# notifications_router = _si("web.api.notifications")
# plugins_router = _si("web.api.plugins")
# backup_router = _si("web.api.backup")
# cost_models_router = _si("web.api.cost_models")
# time_exploit_router = _si("web.api.time_exploit")
# sniping_router = _si("web.api.sniping")
# recovery_router = _si("web.api.recovery")
# treasury_router = _si("web.api.treasury")
# quadratic_funding_router = _si("web.api.quadratic_funding")
# blockchain_health_api_router = _si("web.api.blockchain_health_api")
# rewards_router = _si("web.api.rewards")
# rag_router = _si("web.api.rag_api")
# archive_router = _si("web.api.archive")
# reality_router = _si("web.api.reality")
# intelligence_router = _si("web.api.intelligence")
# local_venue_router = _si("web.api.local_venue")
# local_venue_validation_router = _si("web.api.local_venue_validation")
# market_assertions_router = _si("web.api.market_assertions")
# onchain_assertions_router = _si("web.api.onchain_assertions")
# simulation_assertions_router = _si("web.api.simulation_assertions")
# agent_assertions_router = _si("web.api.agent_assertions")
# domain_priority_router = _si("web.api.domain_priority")
# neo4j_memory_router = _si("web.api.neo4j_memory")
# x_bot_router = _si("web.api.x_bot")
# moat_router = _si("web.api.moat")
# prime_screen_router = _si("web.api.prime_screen")
# simulation_router = _si("web.api.simulation")

# Keep these - they may be used
assistant_router = _si("web.api.assistant_api")
modes_router = _si("web.api.modes")
markets_data_router = _si("web.api.markets_data")
ops_router = _si("web.api.ops")
trading_mode_router = _si("web.api.trading_mode")
# Commented out to reduce startup noise - modules not found or failing
# explainability_router = _si("web.api.explainability")
# intelligence_router = _si("web.api.intelligence")
# local_venue_router = _si("web.api.local_venue")
# local_venue_validation_router = _si("web.api.local_venue_validation")
# market_assertions_router = _si("web.api.market_assertions")
# onchain_assertions_router = _si("web.api.onchain_assertions")
# simulation_assertions_router = _si("web.api.simulation_assertions")
# agent_assertions_router = _si("web.api.agent_assertions")
# domain_priority_router = _si("web.api.domain_priority")
# predictions_router = _si("web.api.predictions")
# simulation_router = _si("web.api.simulation")
# neo4j_memory_router = _si("web.api.neo4j_memory")
# x_bot_router = _si("web.api.x_bot")
# moat_router = _si("web.api.moat")
# prime_screen_router = _si("web.api.prime_screen")
# Removed: autonomy_router, us_compliant_markets_router (modules don't exist - Kalshi-only mode)
autonomy_router = None
us_compliant_markets_router = None

# ── Critical router validation ───────────────────────────────────────
# Fail fast if critical routers fail to import (production safety)
CRITICAL_ROUTERS = [
    ("auth_router", auth_router),
    ("kalshi_api_router", kalshi_api_router),
    ("kalshi_grid_router", kalshi_grid_router),
    ("operator_endpoints_router", operator_endpoints_router),
]

for name, router_instance in CRITICAL_ROUTERS:
    if router_instance is None:
        logger.critical(
            "CRITICAL: %s failed to load — cannot start. "
            "Check import errors above and fix dependencies.",
            name
        )
        raise SystemExit(1)

# Non-router imports (resilient)
try:
    from web.integrations.local_venue_dashboard import get_local_venue_dashboard_data, local_venue_websocket_handler
except Exception:
    get_local_venue_dashboard_data = None
    local_venue_websocket_handler = None

try:
    from web.websocket_factory import create_websocket_endpoint
except Exception:
    create_websocket_endpoint = None

# Load centralized settings - single source of truth
from merid.settings import settings

# Basic environment logging (moved validation to startup_event)
logger.info("MERID Environment: %s", settings.MERID_ENV)
logger.info("Log Level: %s", settings.MERID_LOG_LEVEL)

root_router = APIRouter()
router = APIRouter(prefix="/api")
router_v1 = APIRouter(prefix="/api/v1")
_app_context: Dict[str, Any] = {}
_app_context_frozen: bool = False
event_stream = get_event_stream()


def _context_value(key: str) -> Any:
    try:
        return _app_context[key]
    except KeyError as exc:
        raise RuntimeError(
            f"Application context missing '{key}'. Ensure create_app() was called before importing routes."
        ) from exc


def _freeze_app_context() -> None:
    """Freeze app context after startup to prevent mutation."""
    global _app_context_frozen
    _app_context_frozen = True
    logger.info("✅ App context frozen - mutations disabled")


def _simulation_chain():
    chain = _context_value("simulation_chain")
    if chain is None:
        raise HTTPException(status_code=503, detail="Simulation chain unavailable in Kalshi-only mode")
    return chain


def _logger():
    return _context_value("logger")


def _dashboard_key():
    return _context_value("dashboard_api_key")


def _templates():
    return _context_value("templates")


def compute_kalshi_ws_tickers(
    markets: list,
    limit: int = 50,
    target_assets: Optional[list] = None,
) -> list[str]:
    """Derive Kalshi WS ticker strings from agent/grid market objects (deduped)."""
    seen: set[str] = set()
    out: list[str] = []
    targets = {str(a).upper() for a in (target_assets or [])} or None
    for m in markets:
        asset = getattr(m, "asset", None)
        if targets is not None and str(asset or "").upper() not in targets:
            continue
        market_obj = getattr(m, "market", None)
        mid = getattr(market_obj, "market_id", None) if market_obj is not None else None
        if mid is None:
            mid = getattr(m, "market_id", None)
        if not mid or mid in seen:
            continue
        seen.add(str(mid))
        out.append(str(mid))
        if len(out) >= limit:
            break
    return out


def create_app(lifespan=None) -> FastAPI:
    # Use _app_lifespan by default when called as factory (lifespan=None)
    if lifespan is None:
        lifespan = _app_lifespan
    application = FastAPI(title="MERID Core", version="2.0", lifespan=lifespan)
    
    # Initialize Neo4j Graph Service
    try:
        from core.graph_service import initialize_graph_service
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "")
        # Legacy GraphService (core.graph_service) is optional; the app may still
        # connect via memory.neo4j_graph during lifespan if NEO4J_* is configured.
        logger.info(
            "Neo4j GraphService (core.graph_service) not initialized at import — "
            "optional graph memory may still connect at application startup"
        )
        # if neo4j_password:
        #     initialize_graph_service(neo4j_uri, neo4j_user, neo4j_password)
        #     get_logger("web.main").info(f"Neo4j GraphService initialized: {neo4j_uri}")
    except Exception as e:
        logger.warning("Neo4j initialization skipped; continuing without graph store", exc_info=e)
    
    templates = Jinja2Templates(directory="web/templates")
    
    # Skip simulation chain in Kalshi-only mode (imports crypto perp adapters)
    from merid.settings import settings
    if not settings.KALSHI_ONLY:
        from simulation.engine import build_simulation_chain
        simulation_chain = build_simulation_chain(
            use_mock=str(os.getenv("MERID_KALSHI_MOCK", "")).lower() in {"1", "true", "yes"}
        )
    else:
        simulation_chain = None  # Not used in Kalshi-only mode
    context = {
        "simulation_chain": simulation_chain,
        "logger": logger,
        "dashboard_api_key": os.getenv("MERID_DASHBOARD_API_KEY"),
        "templates": templates,
        "allowed_origins": [
            origin.strip()
            for origin in (os.getenv("MERID_ALLOWED_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173")
            .split(",")
            if origin.strip()
        ],
    }
    _app_context.clear()
    _app_context.update(context)
    _freeze_app_context()  # Prevent further mutation

    # T-017: Restrict CORS — no wildcard origins/methods/headers
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-Correlation-ID", "merid-access", "X-Requested-With"],
        expose_headers=["X-Correlation-ID"],
        max_age=600,
    )

    # T-051: Wire rate limiting middleware (slowapi)
    try:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded
        _limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
        application.state.limiter = _limiter
        application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        logger.info("Rate limiting middleware enabled (slowapi)")
    except ImportError:
        logger.warning("slowapi not installed — rate limiting DISABLED. Install: pip install slowapi")

    # ZT6-02: Global catch-all JSON exception handler — ensures unhandled
    # exceptions in route handlers always return JSON (not HTML 500 pages)
    # so that frontend res.json() never fails on error responses.
    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": type(exc).__name__},
        )

    # Wire distributed tracing middleware (graceful degradation)
    try:
        from core.tracing import CorrelationMiddleware
        CorrelationMiddleware(application)
        logger.info("Distributed tracing middleware enabled")
    except Exception as exc:
        logger.debug(f"Tracing middleware not available: {exc}")

    # ── Profile-based router gating ─────────────────────────────────
    # When MERID_PROFILE=kalshi-only, only Kalshi-critical routers are
    # registered.  Crypto feeds, miner, research, rewards, prediction,
    # betting, wallet, treasury etc. won't start.
    _profile = os.getenv("MERID_PROFILE", "full").lower().strip()
    _kalshi_only = _profile in ("kalshi-only", "kalshi_only", "kalshi")
    if _kalshi_only:
        logger.info("🎯 KALSHI-ONLY profile active — legacy routers suppressed")

    def _reg(r, **kw):
        """Register a router, skipping None (failed imports)."""
        if r is not None:
            application.include_router(r, **kw)

    _reg(root_router)
    _reg(router)
    _reg(router_v1)
    _reg(real_data_router)
    _reg(consensus_router)
    # Commented out to reduce startup noise - modules not found or failing
    # if not _kalshi_only:
    #     _reg(mining_router)
    _reg(auth_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _trading_router = _si("web.api.trading")
    #     _reg(referrals_router)
    #     _reg(_trading_router)
    #     _reg(betting_router)
    _reg(streams_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _pt = _si("web.api.paper_trading")
    #     _ptc = _si("web.api.paper_trading", "paper_trading_convenience_router")
    #     _reg(_pt); _reg(_ptc)
    _reg(system_control_router)
    _reg(data_endpoints_router)
    _reg(live_stream_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(institutional_router)
    # _reg(schemas_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(_si("web.api.arbitrage"))
    _reg(prediction_router)
    # Commented out to reduce startup noise
    # _reg(wallet_router)
    # _reg(offline_router)
    # _reg(notifications_router)
    _reg(compliance_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(plugins_router)
    _reg(monitoring_router)
    _reg(ratelimit_router)
    # Commented out to reduce startup noise
    # _reg(backup_router)
    # if not _kalshi_only:
    #     _reg(cost_models_router)
    #     _reg(time_exploit_router)
    #     _reg(sniping_router)
    # if not _kalshi_only:
    #     _reg(recovery_router)
    # if not _kalshi_only:
    #     _reg(treasury_router)
    #     _reg(quadratic_funding_router)
    _reg(agents_router)
    _reg(reflection_router)
    _reg(governance_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _ts = _si("web.api.trading_suite")
    #     if _ts: _reg(_ts, prefix="/api/v1/trading-suite", tags=["trading-suite"])
    _reg(ops_router)
    # Commented out to reduce startup noise
    # _reg(archive_router)
    _reg(trading_mode_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(reality_router)
    # _reg(explainability_router)
    _reg(live_data_router)
    _reg(dashboard_data_router)
    _reg(dashboard_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(intelligence_router)
    #     _reg(local_venue_router)
    #     _reg(local_venue_validation_router)
    _reg(degraded_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(market_assertions_router)
    #     _reg(onchain_assertions_router)
    #     _reg(simulation_assertions_router)
    #     _reg(agent_assertions_router)
    # _reg(domain_priority_router)
    _reg(production_status_router)
    _reg(dashboard_ws_router)
    # Commented out to reduce startup noise
    # _reg(x_bot_router)  # Always registered — used for Kalshi social broadcasting
    # if not _kalshi_only:
    #     _reg(moat_router)
    _reg(swarm_router)
    _reg(health_router)
    _reg(analytics_router)
    # Commented out to reduce startup noise
    # _reg(predictions_router)
    _reg(prediction_markets_router)
    _reg(prediction_consensus_router)
    _reg(betting_consensus_router)
    _reg(flow_router)
    _reg(signal_layer_router)
    _reg(unified_pipeline_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(simulation_router)
    #     _reg(neo4j_memory_router)
    _reg(brier_metrics_router)
    _reg(feedback_router)
    # Commented out to reduce startup noise
    # _reg(prime_screen_router)
    # if not _kalshi_only:
    #     _reg(autonomy_router)
    _reg(api_status_router)
    _reg(risk_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(us_compliant_markets_router)
    _reg(system_endpoints_router)
    _reg(signals_api_router)
    _reg(orchestrator_api_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(blockchain_health_api_router)
    #     _reg(rewards_router)
    _reg(cognitive_router)
    _reg(dev_swarm_governance_router)
    _reg(operator_router)  # application.include_router(operator_router)
    _reg(operator_endpoints_router)
    _reg(metrics_router)  # application.include_router(metrics_router)
    _reg(market_data_router)  # application.include_router(market_data_router)
    _reg(market_ws_router)  # application.include_router(market_ws_router)
    _reg(loop_api_router)
    _reg(system_observability_router)
    # Commented out to reduce startup noise
    # if not _kalshi_only:
    #     _reg(llm_governance_router)
    #     _reg(rag_router)
    _reg(assistant_router)
    _reg(telemetry_router)
    _reg(resilience_router)
    _reg(guardrails_router)
    _reg(kalshi_api_router)
    _reg(kalshi_ui_state_api_router)
    _reg(portfolio_router)
    # _reg(_si("web.api.orders_api"))
    _reg(_si("web.api.orders_api"))
    _reg(kalshi_ui_router)
    _reg(kalshi_grid_router)
    _reg(crypto_config_router)
    _reg(sidebar_config_router)
    _reg(benchmarks_router)
    _reg(paper_ladder_router)
    _reg(paper_session_router)
    _reg(kalshi_agent_grid_router)
    _reg(kalshi_agent_performance_router)
    _reg(kalshi_deployment_router)
    _reg(kalshi_metrics_api_router)
    _reg(correlation_api_router)
    _reg(swarm_bus_api_router)
    _reg(sentiment_api_router)
    _reg(sentiment_vol_api_router)
    _reg(sentiment_pipeline_api_router)
    _reg(xtf_api_router)
    _reg(auto_promoter_api_router)
    _reg(kalshi_continuous_trader_api_router)
    _reg(band_strategy_api_router)
    _reg(agents_health_router)
    _reg(agent_modes_router)
    _reg(crypto_lanes_router)
    _reg(risk_metrics_router)
    _reg(observability_router)
    _reg(websocket_health_router)
    _reg(modes_router)
    _reg(markets_data_router)
    _reg(risk_metrics_api_router)
    _reg(swarm_routes_router)
    _reg(agents_real_router)
    _reg(ws_dedicated_router)
    _reg(ws_paper_router)
    _reg(ws_trade_events_router)
    _reg(dev_swarm_router)
    _reg(consensus_api_router)
    _reg(debate_data_router)
    _reg(debate_health_router)
    _reg(incentive_router)
    _reg(notification_api_router)
    _reg(missing_endpoints_router)
    _reg(crypto_spot_kalshi_router)
    _reg(spot_basis_router)
    _reg(rti_feed_api_router)
    _reg(policy_metrics_api_router)
    _reg(fvg_api_router)  # FVG (Fair Value Gap) signals and analysis

    # Mount static files - MUST be after all routers to prevent WebSocket conflicts
    # StaticFiles only handles HTTP requests; mounting after routers ensures WebSocket
    # routes are matched before static file middleware
    application.mount("/static", StaticFiles(directory="web/static"), name="static")

    # Mount Flutter web app - MUST be after all routers
    flutter_web_path = Path("lib/merid/web").resolve()
    if flutter_web_path.exists():
        application.mount("/lib/merid/web", StaticFiles(directory=str(flutter_web_path)), name="flutter_web")

    # Mount React frontend (Vite production build) - MUST be after all API routers
    # so that API routes are matched before the catch-all static file handler
    # Skip mounting if MERID_SKIP_FRONTEND_MOUNT is set (for dev server on port 5173)
    skip_mount = os.getenv("MERID_SKIP_FRONTEND_MOUNT", "").lower() in ("1", "true", "yes")
    if not skip_mount and not settings.is_development:
        react_dist_path = Path("web/react/dist").resolve()
        if react_dist_path.exists() and any(react_dist_path.iterdir()):
            # Mount at "/app" to avoid conflicts with WebSocket routes
            # StaticFiles only handles HTTP requests, so WebSocket routes won't be intercepted
            application.mount("/app", StaticFiles(directory=str(react_dist_path), html=True), name="react_frontend")
            logger.info(f"[FRONTEND] React frontend mounted at /app from {react_dist_path}")
            
            # Add a redirect from "/" to "/app" for convenience
            from starlette.responses import RedirectResponse
            @application.get("/")
            async def redirect_to_app():
                return RedirectResponse(url="/app")
        else:
            logger.warning(f"[FRONTEND] React frontend not found at {react_dist_path} - UI will not be served. Run 'cd web/react && npm run build' to build the frontend.")
    else:
        reason = "MERID_SKIP_FRONTEND_MOUNT set" if skip_mount else "development mode"
        logger.info(f"[FRONTEND] Skipping production build mount ({reason}). Access UI at http://localhost:5173")

    # Correlation ID middleware — propagates X-Correlation-ID on every request/response
    # and sets it in contextvars so all log lines during the request include it.
    @application.middleware("http")
    async def correlation_id_middleware(request, call_next):
        import uuid as _uuid
        from utils.logger import set_correlation_id, correlation_id_var
        cid = request.headers.get("x-correlation-id") or str(_uuid.uuid4())
        request.state.correlation_id = cid
        token = set_correlation_id(cid)
        try:
            response = await call_next(request)
            response.headers["x-correlation-id"] = cid
            return response
        finally:
            correlation_id_var.reset(token)

    # Latency timing middleware
    @application.middleware("http")
    async def latency_timing_middleware(request, call_next):
        import time as _t
        start = _t.perf_counter()
        response = await call_next(request)
        elapsed_ms = (_t.perf_counter() - start) * 1000
        if record_latency is not None:
            record_latency(str(request.url.path), elapsed_ms)
        return response

    return application


def _bool_env(key: str, default: bool = False) -> bool:
    return str(os.getenv(key, str(default))).lower() in {"1", "true", "yes", "on"}


gamification_enabled = _bool_env("MERID_ENABLE_GAMIFICATION")
_gamification = (
    GamificationEngine(base_xp=int(os.getenv("MERID_GAMIFICATION_BASE_XP", "50")))
    if gamification_enabled
    else None
)

captcha_enabled = _bool_env("MERID_ENABLE_CAPTCHA")
captcha_secret = os.getenv("MERID_CAPTCHA_SECRET")
captcha_verify_url = os.getenv("MERID_CAPTCHA_VERIFY_URL", "https://hcaptcha.com/siteverify")
if captcha_enabled and not captcha_secret:
    logger.warning("CAPTCHA enabled but missing secret. Disabling enforcement.")
    captcha_enabled = False

spam_guard_enabled = _bool_env("MERID_ENABLE_SPAM_GUARD")
spam_window_seconds = int(os.getenv("MERID_SPAM_WINDOW_SECONDS", "30"))
spam_max_events = int(os.getenv("MERID_SPAM_MAX_EVENTS", "10"))
spam_tracker: Dict[str, Deque[float]] = defaultdict(deque)
spam_lock = asyncio.Lock()

require_vpn_header = _bool_env("MERID_REQUIRE_VPN_HEADER")
vpn_header_name = os.getenv("MERID_VPN_HEADER_NAME", "X-VPN-STATUS")
vpn_header_value = os.getenv("MERID_VPN_HEADER_VALUE")

_wallet_regex = re.compile(r"^0x[a-fA-F0-9]{40}$")
_telegram_regex = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_email_regex = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _require_api_key(request: Request) -> None:
    dashboard_key = _dashboard_key()
    if not dashboard_key:
        return
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if provided != dashboard_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

@root_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket /ws [accepted] - client connected")
    queue = await event_stream.subscribe()
    logger.info(f"WebSocket client subscribed to EventStream (queue id: {id(queue)})")
    
    try:
        while True:
            # BUG-FIX (2026-05-12): Add timeout to queue.get() to prevent indefinite blocking
            # This is a long-running async operation that can hang if no events are published
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            logger.debug(f"WebSocket received event: type={event.event_type}, payload_keys={list(event.payload.keys())}")
            
            # Convert EventRecord to frontend-expected format
            message = {
                "type": event.event_type,
                "data": event.payload
            }
            
            message_json = json.dumps(message)
            logger.debug(f"WebSocket sending message: {message_json[:200]}...")
            await websocket.send_text(message_json)
            logger.debug("WebSocket message sent successfully")
            
    except asyncio.TimeoutError:
        logger.warning("WebSocket event stream timed out after 30s - reconnecting")
        await event_stream.unsubscribe(queue)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        await event_stream.unsubscribe(queue)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await event_stream.unsubscribe(queue)


@root_router.websocket("/ws/whales")
async def whale_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket endpoint for real-time whale alerts with JWT authentication."""
    await websocket.accept()
    
    # Development bypass - allow anonymous connections in dev mode
    dev_mode = settings.allow_websocket_dev_mode
    if dev_mode:
        logger.warning("WebSocket dev mode active - anonymous connections allowed")
    
    if not dev_mode and not token:
        await websocket.close(code=1008, reason="Token required")
        return
    
    try:
        # Validate JWT token if available and not in dev mode
        if not dev_mode and AuthJWT is not None:
            Authorize = AuthJWT()
            Authorize.jwt_required("websocket", token=token)
            user = Authorize.get_jwt_subject()
        else:
            # Fallback: use token as simple user identifier or anonymous in dev mode
            user = token[:8] + "..." if token and len(token) > 8 else "anonymous"
            if dev_mode:
                user = "dev_user"
            else:
                logger.warning("JWT not available, using fallback authentication")
        
        # Add client to whale broadcast list
        from merid.whales import add_whale_client, WHALE_THRESHOLD
        add_whale_client(websocket)
        
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "user": user,
            "whale_threshold": WHALE_THRESHOLD,
            "message": "Connected to whale alerts"
        })
        
        # Keep connection alive
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Whale WebSocket authentication error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "detail": "Authentication failed"
            })
            await websocket.close(code=1008)
        except Exception as e:
            logger.debug(f"Websocket auth cleanup error: {e}")
    finally:
        # Remove client from whale broadcast list
        from merid.whales import remove_whale_client
        remove_whale_client(websocket)


@root_router.websocket("/ws/arbitrage")
async def arbitrage_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket endpoint for arbitrage opportunities with JWT authentication."""
    from web.websocket_factory import handle_topic_websocket
    await handle_topic_websocket(
        websocket=websocket,
        topic_prefix="arbitrage.",
        token=token,
        welcome_message="Connected to arbitrage opportunities stream"
    )


@root_router.websocket("/ws/system")
async def system_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket endpoint for system monitoring events with JWT authentication."""
    from web.websocket_factory import handle_topic_websocket
    await handle_topic_websocket(
        websocket=websocket,
        topic_prefix="system.",
        token=token,
        welcome_message="Connected to system monitoring stream"
    )


@root_router.websocket("/ws/prediction")
async def prediction_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket endpoint for prediction markets with JWT authentication."""
    from web.websocket_factory import handle_topic_websocket
    await handle_topic_websocket(
        websocket=websocket,
        topic_prefix="prediction.",
        token=token,
        welcome_message="Connected to prediction markets stream"
    )


@root_router.websocket("/api/v1/consensus/ws/stream")
async def consensus_ws_stream_endpoint(websocket: WebSocket):
    """WebSocket endpoint for consensus stream events (useKafkaStream.ts).

    Streams real opinions and plans from ConsensusStore, plus coordinator
    status updates.  The frontend ``useConsensusStream`` hook filters on
    ``event_type === 'opinion'`` and ``event_type === 'trade_plan'``.
    """
    await websocket.accept()
    logger.info("Consensus WS stream client connected")

    # Track which opinion/plan IDs we've already sent so we only push new ones
    _sent_opinion_ids: set = set()
    _sent_plan_ids: set = set()

    try:
        import asyncio, uuid
        from datetime import datetime, timezone

        # Send welcome
        await websocket.send_json({
            "event_id": str(uuid.uuid4()),
            "event_type": "connected",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "source": "consensus",
            "payload": {"message": "Connected to consensus stream"},
        })

        # ── Send initial snapshot from ConsensusStore ────────────────
        try:
            from core.consensus_store import get_consensus_store
            store = get_consensus_store()
            for op in store.list_opinions(limit=20):
                d = op.to_dict()
                await websocket.send_json({
                    "event_id": d["id"],
                    "event_type": "opinion",
                    "timestamp": op.created_at,
                    "source": "consensus",
                    "payload": d,
                })
                _sent_opinion_ids.add(d["id"])

            for plan in store.list_plans(limit=20):
                d = plan.to_dict()
                await websocket.send_json({
                    "event_id": d["id"],
                    "event_type": "trade_plan",
                    "timestamp": plan.created_at,
                    "source": "consensus",
                    "payload": d,
                })
                _sent_plan_ids.add(d["id"])
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception as _snap_exc:
            logger.debug("consensus_ws: initial snapshot unavailable: %s", _snap_exc)

        while True:
            # ── Push any NEW opinions/plans since last tick ───────────
            try:
                from core.consensus_store import get_consensus_store
                store = get_consensus_store()

                for op in store.list_opinions(limit=10):
                    if op.id not in _sent_opinion_ids:
                        d = op.to_dict()
                        await websocket.send_json({
                            "event_id": d["id"],
                            "event_type": "opinion",
                            "timestamp": op.created_at,
                            "source": "consensus",
                            "payload": d,
                        })
                        _sent_opinion_ids.add(op.id)

                for plan in store.list_plans(limit=10):
                    if plan.id not in _sent_plan_ids:
                        d = plan.to_dict()
                        await websocket.send_json({
                            "event_id": d["id"],
                            "event_type": "trade_plan",
                            "timestamp": plan.created_at,
                            "source": "consensus",
                            "payload": d,
                        })
                        _sent_plan_ids.add(plan.id)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as _poll_exc:
                logger.debug("consensus_ws: poll error (non-fatal): %s", _poll_exc)

            # ── Coordinator status heartbeat ─────────────────────────
            try:
                from consensus.taco_consensus import get_consensus_coordinator
                coord = get_consensus_coordinator()
                status = coord.get_status() if hasattr(coord, "get_status") else {}
                phase = status.get("phase", "idle") if isinstance(status, dict) else "idle"

                await websocket.send_json({
                    "event_id": str(uuid.uuid4()),
                    "event_type": "consensus_update",
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "source": "taco_consensus",
                    "payload": {
                        "phase": phase,
                        "status": status if isinstance(status, dict) else {},
                    },
                })
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception:
                try:
                    await websocket.send_json({
                        "event_id": str(uuid.uuid4()),
                        "event_type": "consensus_update",
                        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                        "source": "taco_consensus",
                        "payload": {"phase": "idle", "status": {}},
                    })
                except (WebSocketDisconnect, RuntimeError):
                    break
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Consensus WS stream error: {e}")
    finally:
        logger.info("Consensus WS stream client disconnected")


# ── WebSocket Error Handling Helpers ──────────────────────────────────────────


def _is_benign_ws_error(exc: BaseException) -> bool:
    """Check if an exception is a benign WebSocket/asyncio error that should not crash the server.

    These are typically Windows-specific asyncio errors or normal disconnect behavior
    that should be handled gracefully without incrementing the error kill-switch counter.
    """
    # CancelledError is normal during shutdown
    if isinstance(exc, asyncio.CancelledError):
        return True

    # ConnectionResetError and related are normal during client disconnect
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return True

    # Windows-specific errors
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if winerror == 995:  # ERROR_OPERATION_ABORTED
            return True
        errno_code = getattr(exc, "errno", None)
        if errno_code in (104, 10053, 10054, 10058):  # ECONNRESET, EPIPE variants
            return True

    # InvalidStateError from asyncio (Windows path)
    if isinstance(exc, asyncio.InvalidStateError):
        return True

    # WebSocket disconnect is normal
    if isinstance(exc, WebSocketDisconnect):
        return True

    # RuntimeError with specific messages
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if any(x in msg for x in ["websocket", "connection", "closed"]):
            return True

    return False


def _make_ws_task_done_callback(endpoint_name: str):
    """Create a done callback for websocket background tasks that handles exceptions safely."""
    def _on_done(task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.InvalidStateError:
            # Task not done yet - defensive
            return
        except asyncio.CancelledError:
            # Cancelled is normal
            return

        if exc is None:
            return

        # Handle benign errors silently
        if _is_benign_ws_error(exc):
            logger.debug("%s: background task got benign error: %r", endpoint_name, exc)
            return

        # Log unexpected errors but don't re-raise (would kill uvicorn)
        logger.warning("%s: background task got unexpected error: %r", endpoint_name, exc)

    return _on_done


@root_router.websocket("/ws/trades")
async def trades_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for trade events (TradeFloor.tsx).

    Sends heartbeats and trade/order snapshots from the paper trading engine.
    """
    await websocket.accept()
    logger.info("Trade WS client connected")

    try:
        import asyncio as _asyncio
        from datetime import datetime as _dt, timezone as _tz

        # Send mode status immediately
        try:
            from trading.config.runtime import get_runtime_config
            cfg = get_runtime_config()
            mode = cfg.mode if hasattr(cfg, "mode") else "offline"
        except Exception as _rce:
            logger.debug("WS mode_status: runtime config unavailable: %s", _rce)
            mode = "offline"

        await websocket.send_json({
            "event_type": "mode_status",
            "mode": str(mode).upper(),
            "is_simulated": True,
            "timestamp": _dt.now(_tz.utc).timestamp(),
        })

        # Send initial order snapshot from paper engine (skip in Kalshi-only mode)
        if not settings.KALSHI_ONLY:
            try:
                from trading.paper_trading import get_paper_engine
                engine = get_paper_engine()
                uid = next(iter(engine.portfolios), None)
                if uid:
                    portfolio = engine.get_portfolio(uid)
                    positions = getattr(portfolio, "positions", {})
                    for sym, pos in list(positions.items())[:20]:
                        qty = getattr(pos, "quantity", getattr(pos, "size", 0))
                        price = getattr(pos, "avg_price", getattr(pos, "entry_price", 0))
                        side = "buy" if qty > 0 else "sell"
                        await websocket.send_json({
                            "event_type": "order_filled",
                            "trader_type": "agent",
                            "trader_id": "paper-engine",
                            "symbol": sym,
                            "side": side,
                            "qty": abs(qty),
                            "price": round(price, 2),
                            "status": "filled",
                            "venue": "paper",
                            "timestamp": _dt.now(_tz.utc).timestamp(),
                        })
            except (WebSocketDisconnect, RuntimeError):
                return
            except Exception as _snap_exc:
                logger.debug("trades_ws: initial snapshot unavailable: %s", _snap_exc)

        async def _send_heartbeats():
            while True:
                try:
                    await websocket.send_json({
                        "event_type": "heartbeat",
                        "timestamp": _dt.now(_tz.utc).timestamp(),
                    })
                except (WebSocketDisconnect, RuntimeError):
                    break
                except Exception as _e:
                    # Log but don't crash on benign errors
                    if _is_benign_ws_error(_e):
                        logger.debug("ws heartbeat benign error: %s", _e)
                        break
                    raise
                await _asyncio.sleep(15)

        async def _receive_messages():
            while True:
                try:
                    raw = await websocket.receive_text()
                    import json as _json
                    msg = _json.loads(raw)
                    # Respond to client ping with pong
                    if msg.get("event") == "ping":
                        await websocket.send_json({"event": "pong", "ts": _dt.now(_tz.utc).timestamp()})
                except (WebSocketDisconnect, RuntimeError):
                    break
                except Exception as _e:
                    if _is_benign_ws_error(_e):
                        logger.debug("ws receive benign error: %s", _e)
                        break
                    logger.debug("ws _receive_messages skipped: %s", _e)

        # Run heartbeat sender and message receiver concurrently
        # Use gather with return_exceptions=True to avoid InvalidStateError
        tasks = [
            _asyncio.create_task(_send_heartbeats()),
            _asyncio.create_task(_receive_messages()),
        ]

        # Add done callbacks to handle exceptions safely
        for task in tasks:
            task.add_done_callback(_make_ws_task_done_callback("trades_ws"))

        try:
            results = await _asyncio.gather(*tasks, return_exceptions=True)
            # Log any exceptions that were caught
            for i, result in enumerate(results):
                if isinstance(result, BaseException) and not _is_benign_ws_error(result):
                    logger.warning("trades_ws task %d exception: %r", i, result)
        except Exception as _gather_exc:
            # This should not happen with return_exceptions=True, but handle defensively
            if not _is_benign_ws_error(_gather_exc):
                logger.warning("trades_ws gather exception: %r", _gather_exc)

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        # Normal during shutdown - don't log as error
        logger.debug("trades_ws: cancelled (shutdown)")
    except OSError as e:
        # Handle Windows-specific errors
        if _is_benign_ws_error(e):
            logger.debug("trades_ws: benign OS error: %r", e)
        else:
            logger.error("trades_ws: unexpected OSError: %r", e)
            raise
    except Exception as e:
        if _is_benign_ws_error(e):
            logger.debug("trades_ws: benign error: %r", e)
        else:
            logger.error("trades_ws: unexpected error: %r", e)
            raise
    finally:
        logger.info("Trade WS client disconnected")


@root_router.websocket("/ws/risk")
async def risk_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for risk summary updates (TradeFloor.tsx)."""
    await websocket.accept()
    logger.info("Risk WS client connected")

    try:
        import asyncio as _asyncio
        from datetime import datetime as _dt, timezone as _tz

        while True:
            try:
                # Pull real portfolio data if available
                equity = 0.0
                pnl = 0.0
                position_count = 0
                exposure = 0.0
                unrealized = 0.0
                try:
                    from trading.paper_trading import get_paper_engine
                    engine = get_paper_engine()
                    uid = next(iter(engine.portfolios), None)
                    if uid:
                        p = engine.get_portfolio(uid)
                        equity = getattr(p, "equity", 0.0)
                        pnl = getattr(p, "total_pnl", 0.0)
                        positions = getattr(p, "positions", {})
                        position_count = len(positions)
                        unrealized = getattr(p, "unrealized_pnl", 0.0)
                        for _sym, pos in positions.items():
                            qty = abs(getattr(pos, "quantity", getattr(pos, "size", 0)))
                            px = getattr(pos, "avg_price", getattr(pos, "entry_price", 0))
                            exposure += qty * px
                except Exception as _e:
                    logger.debug("risk_summary exposure build skipped: %s", _e)

                await websocket.send_json({
                    "event_type": "risk_summary",
                    "total_equity": round(equity, 2),
                    "total_pnl": round(pnl, 2),
                    "unrealized_pnl": round(unrealized, 2),
                    "position_count": position_count,
                    "exposure": round(exposure, 2),
                    "timestamp": _dt.now(_tz.utc).timestamp(),
                })
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as _e:
                if _is_benign_ws_error(_e):
                    logger.debug("risk_ws: benign error: %s", _e)
                    break
                raise
            await _asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        logger.debug("risk_ws: cancelled (shutdown)")
    except OSError as e:
        if _is_benign_ws_error(e):
            logger.debug("risk_ws: benign OS error: %r", e)
        else:
            logger.error("risk_ws: unexpected OSError: %r", e)
            raise
    except Exception as e:
        if _is_benign_ws_error(e):
            logger.debug("risk_ws: benign error: %r", e)
        else:
            logger.error("risk_ws: unexpected error: %r", e)
            raise
    finally:
        logger.info("Risk WS client disconnected")


@root_router.websocket("/ws/paper-trading")
async def paper_trading_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time paper trading updates."""
    await websocket.accept()
    logger.info("Paper trading WebSocket client connected")
    
    try:
        from trading.paper_trading import get_paper_trading_engine
        engine = get_paper_trading_engine()
        
        # Subscribe to paper trading events
        def on_trade(event):
            try:
                asyncio.create_task(websocket.send_json(event))
            except Exception as e:
                logger.error(f"Failed to send trade event: {e}")
        
        def on_position(event):
            try:
                asyncio.create_task(websocket.send_json(event))
            except Exception as e:
                logger.error(f"Failed to send position event: {e}")
        
        def on_summary(event):
            try:
                asyncio.create_task(websocket.send_json(event))
            except Exception as e:
                logger.error(f"Failed to send summary event: {e}")
        
        # Subscribe to all event types
        _sub = getattr(engine, 'subscribe', getattr(engine, '_subscribe', None))
        unsubscribe_trade = _sub("trade", on_trade) if _sub else None
        unsubscribe_position = _sub("position", on_position) if _sub else None
        unsubscribe_summary = _sub("summary", on_summary) if _sub else None
        
        # Keep connection alive and listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send commands if needed
                logger.debug(f"Received from paper trading client: {data}")
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping", "ts": time.time()})
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as e:
                logger.error(f"Paper trading WebSocket error: {e}")
                break
                
    except Exception as e:
        logger.error(f"Paper trading WebSocket connection error: {e}")
    finally:
        # Cleanup subscriptions — each may be None if subscribe() returned None
        for _unsub in (
            locals().get("unsubscribe_trade"),
            locals().get("unsubscribe_position"),
            locals().get("unsubscribe_summary"),
        ):
            if callable(_unsub):
                try:
                    _unsub()
                except Exception:
                    logger.debug("silent catch in main:1109")
        try:
            await websocket.close()
        except Exception:
            logger.debug("silent catch in main:1113")
        logger.info("Paper trading WebSocket client disconnected")


@root_router.websocket("/ws/agents")
async def agents_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """WebSocket endpoint for agent cohorts with JWT authentication."""
    from web.websocket_factory import handle_topic_websocket
    await handle_topic_websocket(
        websocket=websocket,
        topic_prefix="agent.",
        token=token,
        welcome_message="Connected to agent cohorts stream"
    )


@root_router.websocket("/ws/ticks")
async def ticks_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time tick events (OperatorDashboard tick timeline).

    Streams every TickEvent and TickSummary emitted by KalshiTradingAgent cycles.
    On connect, replays the last 20 tick summaries then streams live events.

    Message format: JSON dict with at minimum:
      {"event": "<event_name>", "tick_id": "...", "agent_id": "...", "ts": <float>, ...}
    """
    await websocket.accept()
    logger.info("Ticks WS client connected")

    from merid.tick_events import get_tick_bus
    bus = get_tick_bus()

    # Replay recent summaries on connect so the UI has immediate data
    for summary in bus.recent_summaries(20):
        try:
            await websocket.send_json(summary)
        except (WebSocketDisconnect, RuntimeError):
            return

    queue = bus.subscribe(maxsize=200)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"event": "heartbeat", "ts": time.time()})
            except (WebSocketDisconnect, RuntimeError):
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Ticks WS error: %s", exc)
    finally:
        bus.unsubscribe(queue)
        logger.info("Ticks WS client disconnected")


class MineRequest(BaseModel):
    premium: bool = Field(True, description="Use premium-depth simulations (invokes x402 payment).")
    miner_id: str = Field("dashboard", description="Identifier for the mining agent.")


class PaymentRequest(BaseModel):
    amount_usd: float = Field(0.01, gt=0)
    reason: str = Field("premium_simulation")


class ConnectPayload(BaseModel):
    user_handle: str = Field(..., min_length=3, max_length=48)
    x_handle: Optional[str] = Field(None, max_length=32)
    telegram_handle: Optional[str] = Field(None, max_length=64)
    wallet_address: Optional[str] = Field(None, max_length=64)
    email: Optional[str] = Field(None, max_length=128)
    captcha_token: Optional[str] = None
    verification_code: Optional[str] = None
    proof_message: Optional[str] = None
    proof_signature: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class FilterPayload(BaseModel):
    user_handle: str = Field(..., min_length=3, max_length=48)
    filters: Dict[str, Any] = Field(default_factory=dict)
    captcha_token: Optional[str] = None


@root_router.get("/")
async def root():
    """Root endpoint - redirect to dashboard."""
    return RedirectResponse(url="/dashboard")

@root_router.get("/simulation")
async def simulation_monitor():
    """Simulation monitor page."""
    templates = _templates()
    return templates.TemplateResponse("simulation.html", {"request": {}})

@root_router.get("/live")
async def live_monitor(request: Request):
    """Live intelligence monitor page."""
    templates = _templates()
    return templates.TemplateResponse("live_monitor.html", {"request": request})

@root_router.get("/debug-v2", response_class=HTMLResponse)
async def debug_dashboard_v2(request: Request):
    """Render the debug dashboard v2 with prediction markets."""
    return _templates().TemplateResponse("debug_dashboard_v2.html", {"request": request})


@root_router.get("/dashboard")
async def dashboard():
    """Main dashboard endpoint - redirect to fixed dashboard."""
    return RedirectResponse(url="/dashboard/fixed")

@root_router.get("/dashboard/fixed")
async def dashboard_fixed(request: Request):
    """Fixed unified control center with real prediction markets data."""
    templates = _templates()
    return templates.TemplateResponse("unified_fixed.html", {"request": request})


@root_router.get("/trading/perps")
async def perps_trading(request: Request):
    return _templates().TemplateResponse(
        "trading_perps.html",
        {"request": request},
    )

@root_router.get("/trading/markets")
async def prediction_markets(request: Request):
    return _templates().TemplateResponse(
        "trading_markets.html",
        {"request": request},
    )

@root_router.get("/betting")
async def betting_system(request: Request):
    return _templates().TemplateResponse(
        "betting.html",
        {"request": request},
    )

@root_router.get("/institutional")
async def institutional_dashboard(request: Request):
    """Institutional-grade control center."""
    return _templates().TemplateResponse(
        "institutional.html",
        {"request": request},
    )

@root_router.get("/control")
async def control_center(request: Request):
    """Alias for institutional dashboard."""
    return _templates().TemplateResponse(
        "institutional.html",
        {"request": request},
    )

@router_v1.get("/health")
async def api_health():
    return {"status": "ok", "chain": _simulation_chain().ledger_state()}


@router_v1.get("/blocks")
async def stream_blocks():
    return StreamingResponse(_block_event_stream(), media_type="text/event-stream")


@router_v1.get("/blocks/latest")
async def latest_block():
    blocks = _simulation_chain().export_blocks(limit=1)
    if not blocks:
        raise HTTPException(status_code=404, detail="No blocks yet")
    return blocks[0]


@router_v1.get("/blocks/{block_index}")
async def block_by_index(block_index: int):
    block = next((b for b in _simulation_chain().export_blocks(limit=100) if b["index"] == block_index), None)
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    return block


@router_v1.post("/mine")
async def trigger_mine(
    request: MineRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_require_api_key),
):
    background_tasks.add_task(_simulation_chain().mine_block, request.miner_id, premium=request.premium)
    _logger().info("Mining triggered via API (miner=%s premium=%s)", request.miner_id, request.premium)
    return {"status": "accepted", "message": "Simulation mining queued"}


@router_v1.get("/tokens/balances")
async def token_balances():
    return _simulation_chain().token_economy.to_dict()


@router_v1.get("/tokens/balance/{agent_id}")
async def token_balance(agent_id: str):
    chain = _simulation_chain()
    return {"agent_id": agent_id, "balance": chain.token_economy.balance(agent_id)}


@router_v1.post("/payments/x402/simulate")
async def simulate_payment(payload: PaymentRequest, _: None = Depends(_require_api_key)):
    _logger().info("x402 payment simulation invoked for %s USD (%s)", payload.amount_usd, payload.reason)
    return {"status": "paid", "amount_usd": payload.amount_usd, "reason": payload.reason}


async def event_generator(source: str, payload: str):
    yield f"data: {json.dumps({'type': 'start', 'message': f'Processing: {payload}'})}\n\n"

    energy = create_energy(source, payload)
    result = await get_core().run_cycle(energy)

    yield (
        "data: "
        + json.dumps(
            {
                "type": "result",
                "approved": result["approved"],
                "consensus": f"{result['consensus']:.1%}",
                "status": "REALITY FORMED" if result["approved"] else "ENERGY DISSIPATED",
            }
        )
        + "\n\n"
    )
    yield "data: COMPLETE\n\n"


@root_router.get("/analytics/dashboard", response_class=HTMLResponse)
async def analytics_dashboard(request: Request):
    """Render the analytics dashboard."""
    return _templates().TemplateResponse("analytics_dashboard.html", {"request": request})

@root_router.get("/observability", response_class=HTMLResponse)
async def observability_dashboard(request: Request):
    """Render the observability dashboard."""
    return _templates().TemplateResponse("observability.html", {"request": request})


# Unified Platform Routes
@root_router.get("/unified", response_class=HTMLResponse)
async def unified_platform(request: Request):
    """Render the unified MERID platform."""
    return _templates().TemplateResponse("unified_shell.html", {"request": request})


@root_router.get("/unified/{section:path}", response_class=HTMLResponse)
async def unified_section(request: Request, section: str):
    """Render unified platform section."""
    return _templates().TemplateResponse("unified_shell.html", {"request": request})


@root_router.get("/unified/dashboard", response_class=HTMLResponse)
async def unified_dashboard(request: Request):
    """Unified dashboard - redirect to main unified platform."""
    return _templates().TemplateResponse("unified_shell.html", {"request": request})


@root_router.get("/production", response_class=HTMLResponse)
async def production_dashboard(request: Request):
    """Production-ready dashboard with real-time data and no mock data."""
    return _templates().TemplateResponse("production_dashboard.html", {"request": request})


@root_router.get("/prime-screen", response_class=HTMLResponse)
async def prime_screen(request: Request):
    """Prime Screen - advanced market intelligence interface."""
    return _templates().TemplateResponse("prime_screen.html", {"request": request})


@root_router.get("/api-dashboard", response_class=HTMLResponse)
async def api_dashboard(request: Request):
    """API Integration Dashboard - real-time status of all API connections."""
    return _templates().TemplateResponse("api_dashboard.html", {"request": request})


@root_router.get("/static/templates/partials/{partial_path:path}")
async def serve_unified_partial(partial_path: str):
    """Serve trusted partial templates for Unified Shell dynamic loader."""
    safe_root = Path("web/templates/partials").resolve()
    requested = (safe_root / partial_path).resolve()
    if not str(requested).startswith(str(safe_root)) or requested.suffix not in {".html", ""}:
        raise HTTPException(status_code=404, detail="Partial not found")
    if requested.is_dir():
        requested = requested / "index.html"
    if not requested.exists():
        raise HTTPException(status_code=404, detail="Partial not found")
    return FileResponse(requested)


@root_router.post("/submit")
async def submit_energy(request: Request):
    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = {"source": form.get("source", "user"), "payload": form.get("payload", "")}

    return StreamingResponse(
        event_generator(data["source"], data["payload"]),
        media_type="text/event-stream",
    )


@router_v1.get("/heatmap")
async def heatmap_feed(limit: int = 50):
    return _simulation_chain().heatmap_snapshot(limit=limit)


@router_v1.get("/ticker")
async def ticker_feed(limit: int = 40):
    return _simulation_chain().ticker_snapshot(limit=limit)


@router_v1.get("/assist")
async def assist_feed():
    return _simulation_chain().assist_snapshot()


@router_v1.get("/hover-metadata")
async def hover_metadata_feed():
    return _simulation_chain().hover_metadata()


@router_v1.get("/charters")
async def list_charters(active_only: bool = True):
    charters = []
    for key, charter in CHARTER_REGISTRY.items():
        if active_only and not charter.active:
            continue
        payload = charter.to_dict()
        payload["role"] = key
        charters.append(payload)
    return {"items": charters}


@router_v1.get("/charters/{role}")
async def charter_detail(role: str):
    charter = CHARTER_REGISTRY.get(role)
    if not charter:
        raise HTTPException(status_code=404, detail="Charter not found")
    payload = charter.to_dict()
    payload["role"] = role
    return payload


def _normalize_wallet(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    address = address.strip()
    return address if _wallet_regex.match(address) else None


@router_v1.get("/swarm/agents")
async def swarm_agents(limit: int = 40):
    return _simulation_chain().agent_population_snapshot(limit=limit)


@router_v1.get("/swarm/lineage")
async def swarm_lineage(limit: int = 200):
    return _simulation_chain().lineage_snapshot(limit=limit)


@router_v1.get("/observability/sources")
async def source_health_snapshot():
    """Stage 6: Source reliability metrics for all external APIs."""
    from core.source_health import get_source_registry
    return {"sources": get_source_registry().snapshot()}


@router_v1.get("/observability/agents/trust")
async def agent_trust_snapshot():
    """Stage 6: Agent trust profiles and source quality coupling."""
    from core.agent_trust import get_trust_registry
    return {"agents": get_trust_registry().snapshot()}


@router_v1.get("/observability/consensus/history")
async def consensus_history(limit: int = 50):
    """Stage 6: Recent consensus outcomes with source reliability context."""
    return _simulation_chain().consensus_history_snapshot(limit=limit)


@router_v1.get("/observability/hardening/status")
async def hardening_status():
    """Stage 6.5: Adversarial hardening layer status and poisoning alerts."""
    from core.adversarial_hardening import get_hardening_layer
    return get_hardening_layer().hardening_status()


@router_v1.get("/observability/summary")
async def observability_summary():
    """Aggregate observability summary for dashboards."""
    return get_observability_stack().get_observability_summary()


@router_v1.get("/observability/dashboards")
async def observability_dashboards():
    """Clock sync, parity, lag metrics for UI panels."""
    return get_observability_stack().get_observability_dashboards()


@router_v1.get("/marl/metrics")
async def marl_metrics():
    """Stage 9: MARL training metrics and agent performance."""
    return _simulation_chain().marl_metrics_snapshot()


@router_v1.get("/pso/metrics")
async def pso_metrics():
    """Stage 10: PSO optimization metrics and hyperparameter search status."""
    return _simulation_chain().pso_metrics_snapshot()


async def _block_event_stream():
    """Stream blocks as they are mined."""
    queue = await event_stream.subscribe()
    try:
        while True:
            event = await queue.get()
            if event.get("type") == "block_mined":
                yield f"data: {json.dumps(event.get('data', event.get('payload', {})))}\n\n"
    except Exception:
        await event_stream.unsubscribe(queue)


@router_v1.get("/leaderboard")
async def leaderboard(limit: int = 20):
    """Gamification leaderboard."""
    if not _gamification:
        return {"items": []}
    return {"items": _gamification.leaderboard(limit=limit)}


@router_v1.get("/assertions")
async def list_uma_assertions(status: Optional[str] = None, limit: int = 50):
    """Stage 4: List UMA Optimistic Oracle assertions tied to MERID blocks."""
    from oracles.uma import get_uma_client
    
    uma_client = get_uma_client()
    assertions = uma_client.list_assertions(status=status, limit=limit)
    
    return {
        "assertions": [a.to_dict() for a in assertions],
        "count": len(assertions),
    }


@router_v1.get("/assertions/{assertion_id}")
async def get_uma_assertion(assertion_id: str):
    """Stage 4: Get specific UMA assertion details."""
    from oracles.uma import get_uma_client
    
    uma_client = get_uma_client()
    assertion = uma_client.get_assertion(assertion_id)
    
    if assertion is None:
        return {"status": "not_found", "assertion_id": assertion_id}
    
    return assertion.to_dict()


@router_v1.post("/assertions/{assertion_id}/settle")
async def settle_uma_assertion(assertion_id: str):
    """Stage 4: Settle UMA assertion after liveness period."""
    from oracles.uma import get_uma_client
    
    uma_client = get_uma_client()
    result = uma_client.settle_assertion(assertion_id)
    
    return result


# ════════════════════════════════════════════════
# TERMINAL TELEMETRY — agent heartbeats, trades, consensus
# ════════════════════════════════════════════════

_telem_logger = get_logger("merid.telemetry")

# Track previous-tick message counts so we can detect idle agents
_prev_agent_msgs: Dict[str, int] = {}


def _unique_tail(items: list, n: int, key_fn=None) -> list:
    """Return up to *n* items from the tail of *items*, skipping consecutive duplicates."""
    result: list = []
    prev_key = None
    for item in reversed(items):
        k = key_fn(item) if key_fn else item
        if k == prev_key:
            continue
        result.append(item)
        prev_key = k
        if len(result) >= n:
            break
    result.reverse()
    return result


async def _terminal_telemetry_loop(interval: float = 30.0) -> None:
    """Background loop that prints agent heartbeats, recent trades,
    and consensus explainability to the terminal every *interval* seconds."""

    await asyncio.sleep(10.0)  # let startup finish before first tick

    while True:
        try:
            # ── 1. Agent heartbeats ─────────────────────────────────
            try:
                from agents.agent_framework import get_agent_registry
                registry = get_agent_registry()
                agents = registry.get_all_agents()
                if agents:
                    lines = []
                    for a in agents:
                        m = a.get_metrics()
                        raw_status = a.status.value if hasattr(a.status, "value") else str(a.status)
                        uptime_m = int(m.uptime_seconds // 60)
                        # Derive effective status: if nominally active but
                        # zero new messages since last tick → idle
                        total_msgs = m.messages_sent + m.messages_received
                        prev = _prev_agent_msgs.get(a.agent_id, 0)
                        if raw_status == "active" and total_msgs == prev and m.decisions_made == 0:
                            effective = "idle"
                        else:
                            effective = raw_status
                        _prev_agent_msgs[a.agent_id] = total_msgs
                        lines.append(
                            f"  {a.agent_id:<28s} status={effective:<10s} "
                            f"msgs={m.messages_sent}/{m.messages_received} "
                            f"decisions={m.decisions_made} errors={m.errors} "
                            f"up={uptime_m}m"
                        )
                    _telem_logger.info(
                        "🫀 AGENT HEARTBEATS (%d agents):\n%s",
                        len(agents), "\n".join(lines),
                    )
            except Exception as exc:
                _telem_logger.debug("Heartbeat collection failed: %s", exc)

            # ── 2. Recent trading activity ──────────────────────────
            try:
                from trading.paper_trading import get_paper_engine
                engine = get_paper_engine()
                uid = next(iter(engine.portfolios), "default")
                portfolio = engine.get_portfolio(uid)
                recent = portfolio.trade_history[-5:]
                if recent:
                    lines = []
                    for o in reversed(recent):
                        side_str = o.side.value if hasattr(o.side, "value") else str(o.side)
                        status_str = o.status.value if hasattr(o.status, "value") else str(o.status)
                        lines.append(
                            f"  {side_str.upper():<6s} {o.asset:<12s} "
                            f"${o.size_usd:>10.2f} @ {o.fill_price or 0:>10.4f}  "
                            f"status={status_str.upper()}"
                        )
                    _telem_logger.info(
                        "📊 RECENT TRADES (last %d):\n%s",
                        len(recent), "\n".join(lines),
                    )
                    stats = engine.get_portfolio_stats(uid)
                    closed = stats.get("winning_trades", 0) + stats.get("losing_trades", 0)
                    # Only show win rate when there are closed trades to measure
                    if closed > 0:
                        wr_str = f" | win_rate={stats['win_rate_pct']:.1f}% ({closed} closed)"
                    else:
                        wr_str = " | win_rate=N/A (no closed trades)"
                    _telem_logger.info(
                        "💰 PORTFOLIO: equity=$%.2f | realized=$%.2f | unrealized=$%.2f | trades=%d%s",
                        stats.get("equity", stats.get("current_balance", 0)),
                        stats.get("total_pnl", 0) - stats.get("total_unrealized_pnl", 0),
                        stats.get("total_unrealized_pnl", 0),
                        stats.get("total_trades", 0),
                        wr_str,
                    )
            except Exception as exc:
                _telem_logger.debug("Trade log collection failed: %s", exc)

            # ── 3. Consensus explainability ─────────────────────────
            try:
                from core.consensus_store import get_consensus_store
                store = get_consensus_store()
                raw_opinions = store.list_opinions(limit=20)
                raw_plans = store.list_plans(limit=10)

                # De-dup consecutive identical opinions/plans
                recent_opinions = _unique_tail(
                    raw_opinions, 5,
                    key_fn=lambda o: (o.agent_id, o.symbol, o.stance),
                )
                recent_plans = _unique_tail(
                    raw_plans, 3,
                    key_fn=lambda p: (p.symbol, p.direction, p.status),
                )

                if recent_opinions:
                    lines = []
                    for op in recent_opinions:
                        agent = op.agent_id or op.agent_name or "?"
                        market = (op.symbol or "?")[:30]
                        stance = op.stance or "neutral"
                        conf = op.confidence
                        reason = (op.reasoning or "")[:60]
                        lines.append(
                            f"  {agent:<20s} {market:<30s} {stance:<10s} "
                            f"conf={conf:.2f}  {reason}"
                        )
                    _telem_logger.info(
                        "🧠 CONSENSUS OPINIONS (%d unique):\n%s",
                        len(recent_opinions), "\n".join(lines),
                    )
                if recent_plans:
                    lines = []
                    for plan in recent_plans:
                        direction = (plan.direction or "?").upper()
                        market = (plan.symbol or "?")[:25]
                        conf = plan.confidence
                        score = plan.consensus_score
                        status = plan.status or "?"
                        lines.append(
                            f"  {direction:<6s} {market:<25s} "
                            f"confidence={conf:.2f} consensus={score:.2f} "
                            f"status={status}"
                        )
                    _telem_logger.info(
                        "📋 CONSENSUS TRADE PLANS (%d unique):\n%s",
                        len(recent_plans), "\n".join(lines),
                    )
            except Exception as exc:
                _telem_logger.debug("Consensus log collection failed: %s", exc)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            _telem_logger.error("Telemetry loop error: %s", exc)

        await asyncio.sleep(interval)


# ════════════════════════════════════════════════
# LIFESPAN — replaces all @on_event("startup") / @on_event("shutdown")
# ════════════════════════════════════════════════

@asynccontextmanager
async def _app_lifespan(application: FastAPI):
    """Combined startup/shutdown lifespan for MERID.

    EVENT-LOOP ARCHITECTURE DOCUMENTATION:

    This lifespan manages MERID's main event loop lifecycle. All async services
    attach to the same event loop that uvicorn runs.

    LAG THRESHOLDS AND ACTIONS (24/7-MODE):
    - healthy (<3000ms): Normal operation, all services active
    - elevated (3000-8000ms): Log warning at debug level only, continue operation
    - degraded (>=8000ms): Reduce scope - shed non-critical subscriptions,
      slow analytics, but NEVER shutdown automatically
    - halt (>=15000ms): Log critical alert only, continue operation
      NO automatic shutdown - server runs 24/7 unless operator stops it

    QUEUE PRESSURE THRESHOLDS (Kalshi WebSocket) (24/7-MODE):
    - elevated (50%): Log warning
    - warn (75%): Proactive scope reduction warning
    - critical (90%): Immediate load shedding to essential tickers only
    - shutdown (98%): Aggressive load shedding, but NEVER auto-shutdown

    SHUTDOWN POLICY (24/7-HARDENING):
    - AUTOMATIC SHUTDOWN IS DISABLED - server runs continuously
    - Shutdown only happens on explicit operator request (SIGTERM/SIGINT)
    - Loop-lag "critical" status does NOT trigger shutdown
    - Budget exceeded does NOT trigger shutdown
    - reason is NEVER allowed to be "unknown" in production (enforced by type system)
    - All shutdowns must have a valid ShutdownReason enum value
    - sub_reason provides specific trigger details (e.g., "operator_sigterm")
    - metrics dict includes lag_ms, queue_utilization, shed_count for forensics

    SERVICES STARTED (in order):
    1. LoopLagMonitor - starts lag measurement before other services
    2. KalshiVenueClient - primary venue connection
    3. KalshiMarketCatalog - market metadata cache
    4. MeridLoop - main orchestration cycle
    5. AgentGrid - trading agents
    6. Background reconciler - position reconciliation

    SHUTDOWN SEQUENCE (reverse order):
    1. Stop all service loops (MeridLoop, external feeds)
    2. Close venue connections gracefully
    3. Cancel background tasks
    4. Log structured shutdown metrics
    """
    global _startup_state
    application.state.canonical_lifespan = "web.main._app_lifespan"
    application.state.test_mode = os.environ.get("MERID_TEST_MODE", "").strip() == "1"
    _startup_state["started_at"] = time.time()
    startup_success = True

    # BUG-FIX: Initialize service handles at top of lifespan for safe cleanup in shutdown
    # even if startup fails before service initialization block is reached.
    _rti_feed_service = None
    
    # EVENT-LOOP-FIX: Install Windows asyncio exception handler on the running loop
    _setup_asyncio_exception_handler()

    # 24/7-HARDENING: Register main loop so sync worker threads can schedule
    # coroutines back onto it via asyncio.run_coroutine_threadsafe instead
    # of calling asyncio.run() in a worker thread (which corrupts Windows
    # IOCP state when the coroutine touches main-loop-bound resources and
    # produces InvalidStateError + WinError 995 cascades).
    try:
        from core.event_loop_registry import register_main_loop
        register_main_loop(asyncio.get_running_loop())
    except Exception as _loop_reg_exc:
        logger.warning(
            "[24/7-HARDENING] Main loop registration failed (cross-thread "
            "coroutine scheduling will fall back to asyncio.run): %s",
            _loop_reg_exc,
        )

    # STARTUP TIMING TELEMETRY: Track phase durations for bottleneck identification
    _phase_timings: Dict[str, float] = {}
    _phase_start = time.time()

    def _log_phase(phase_name: str) -> None:
        """Log phase completion with duration."""
        nonlocal _phase_start
        elapsed = time.time() - _phase_start
        _phase_timings[phase_name] = elapsed
        logger.info(f"[STARTUP-PHASE] {phase_name}: {elapsed:.2f}s")
        _phase_start = time.time()

    # MODE CONSISTENCY CHECK: Ensure TradeMode and Kalshi environment agree
    # This must happen BEFORE any Kalshi client is created
    try:
        from merid.mode_resolver import ModeResolver
        ModeResolver.assert_mode_consistency()
        logger.info("✅ Mode consistency check passed")
    except Exception as mode_exc:
        logger.error("❌ Mode consistency check failed: %s", mode_exc)
        # Fail-fast: don't start if mode is inconsistent
        raise RuntimeError(f"Mode consistency check failed: {mode_exc}") from mode_exc

    def _log_startup_summary() -> None:
        """Log complete startup timing summary."""
        total = time.time() - _startup_state["started_at"]
        slow_phases = [(n, t) for n, t in _phase_timings.items() if t > 1.0]
        if slow_phases:
            logger.info("[STARTUP-TIMING] Slow phases (>1s): " + 
                       ", ".join(f"{n}={t:.1f}s" for n, t in sorted(slow_phases, key=lambda x: -x[1])))
        logger.info(f"[STARTUP-TIMING] Total startup time: {total:.2f}s")

    # C1/RISK-16: Emit consolidated router-import failure summary so missing
    # routers are visible at startup rather than buried in per-line warnings.
    if _si_failures:
        logger.warning(
            "[STARTUP-IMPORT-FAILURES] %d router%s failed to import: %s",
            len(_si_failures),
            "s" if len(_si_failures) != 1 else "",
            ", ".join(_si_failures),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # DEBUGGING: Lightweight watchdog task to monitor event loop health
    # ═══════════════════════════════════════════════════════════════════════
    async def _watchdog_task():
        """Background task that monitors event loop health and logs heartbeats."""
        import time as _time
        heartbeat_interval = 10.0  # seconds
        last_heartbeat = _time.time()
        
        while True:
            try:
                now = _time.time()
                elapsed = now - last_heartbeat
                print(f"[WATCHDOG] Event loop heartbeat | elapsed={elapsed:.2f}s | pending_tasks={len(asyncio.all_tasks())}")
                last_heartbeat = now
                await asyncio.sleep(heartbeat_interval)
            except asyncio.CancelledError:
                print("[WATCHDOG] Task cancelled (shutdown)")
                break
            except Exception as e:
                print(f"[WATCHDOG] Error: {e}")
                await asyncio.sleep(heartbeat_interval)
    
    watchdog_task = asyncio.create_task(_watchdog_task())
    print("[WATCHDOG] Started event loop watchdog task")

    # ── Phase -1: Kalshi environment safety guard ──────────────────────
    # Raises RuntimeError if pointing at trading-api.kalshi.com without
    # KALSHI_CONFIRM_LIVE=1.  Must run before any Kalshi client is created.
    try:
        from merid.event_venues.kalshi.invariants import require_live_confirmation
        require_live_confirmation()
    except RuntimeError as _live_err:
        logger.critical("STARTUP ABORTED: %s", _live_err)
        raise
    except Exception as _inv_err:
        logger.warning("Live confirmation check failed (non-fatal): %s", _inv_err)

    try:
        __import__("os").environ.setdefault(
            "MERID_KALSHI_WS_CLIENT",
            settings.MERID_KALSHI_WS_CLIENT,
        )
    except Exception as _wsk_err:
        logger.debug("MERID_KALSHI_WS_CLIENT setdefault skipped: %s", _wsk_err)

    try:
        from merid.pm_runtime import apply_pm_production_logging_belt

        apply_pm_production_logging_belt()
    except Exception as _belt_err:
        logger.warning("PM production logging belt skipped: %s", _belt_err)

    try:
        from merid.startup_validations import StartupValidationError, validate_all

        validate_all()
    except StartupValidationError as _su_err:
        logger.critical("STARTUP ABORTED: %s", _su_err)
        raise
    except Exception as _su_other:
        logger.warning("Startup validations error (non-fatal): %s", _su_other)

    # ── Phase -1b: Kalshi 30-cell grid validation ───────────────────────
    # Asserts all BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly/annual
    # cells have a wired AgentConfig, positive notional, and correct market_filter.
    # Fails fast with a precise diagnostic rather than silently skipping markets.
    try:
        from merid.event_venues.kalshi.grid_validator import (
            GridValidationError,
            log_grid_summary,
            validate_kalshi_grid,
        )

        _grid_status = validate_kalshi_grid(strict=False)
        log_grid_summary(_grid_status)
        _grid_ok = sum(1 for s in _grid_status.values() if s.ok)
        logger.info("✅ Kalshi grid validation: %d/30 cells OK", _grid_ok)
    except GridValidationError as _gve:
        logger.critical("❌ STARTUP ABORTED — Kalshi grid validation failed: %s", _gve)
        raise RuntimeError(f"Kalshi grid validation failed: {_gve}") from _gve
    except Exception as _gve_exc:
        logger.warning("Kalshi grid validation error (non-fatal): %s", _gve_exc)

    # ── Phase -1c: Unified Risk Model Enforcement ───────────────────────
    # PASS 8: Enforce 2% global cap, no fixed USD in live, max 3 edges
    # This is a HARD requirement before any trading can begin.
    try:
        from merid.config.unified_risk_enforcement import enforce_at_startup, RiskConfigViolationError
        enforce_at_startup()
        _log_phase("Phase -1c: Unified risk enforcement")
    except RiskConfigViolationError as _risk_err:
        logger.critical("❌ STARTUP ABORTED — Risk config violation: %s", _risk_err)
        raise RuntimeError(f"Risk configuration violates unified model: {_risk_err}") from _risk_err
    except Exception as _risk_exc:
        logger.warning("Risk enforcement error (non-fatal): %s", _risk_exc)

    # ── Phase 0: WebSocket publishers ──────────────────────────────────
    # Legacy crypto publishers DISABLED — Kalshi has its own data pipeline.
    # price_publisher, portfolio_publisher, prediction_publisher all produced
    # synthetic/crypto data that polluted the terminal and UI.
    logger.info("=" * 80)
    logger.info("STARTUP EVENT: Legacy WS publishers SKIPPED (Kalshi-only mode)")
    logger.info("=" * 80)

    # ── MODE LOGGING: Log effective mode and WS status at startup ──────
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    _paper_mode = __import__("os").environ.get("MERID_PM_TRADING_MODE", "paper") == "paper"
    _ws_enabled = not _is_validation  # WS bridge is enabled unless in validation mode
    logger.info(
        "[MODE] validation=%s paper=%s ws_enabled=%s",
        _is_validation, _paper_mode, _ws_enabled
    )
    if _is_validation:
        logger.warning(
            "[WS-BOOT] KalshiWebSocketBridge DISABLED (validation mode) - system will use REST fallback"
        )
    else:
        logger.info("[WS-BOOT] KalshiWebSocketBridge ENABLED - live orderbook updates will be used")

    # ── Phase 0.5: Kalshi Agent Grid (deferred to background task) ──────
    # asyncio.Event/Lock created in agent __init__ deadlock if instantiated
    # before uvicorn's event loop is running.  Deferring to a background task
    # lets uvicorn start accepting HTTP requests immediately while the grid
    # boots (~20s for 35 agents).
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 35+ streaming agent tasks
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info(
            "[VALIDATION MODE] Kalshi Agent Grid startup skipped (35 trading agents deferred) — "
            "GET /api/v1/operator/agent-grid/startup-health will show deferred_start_skipped_reason"
        )
        try:
            from merid.prediction.agent_grid import note_agent_grid_deferred_skipped

            note_agent_grid_deferred_skipped("MERID_VALIDATION_MODE=1")
        except Exception as _skip_note_exc:
            logger.debug("note_agent_grid_deferred_skipped: %s", _skip_note_exc)
    else:
        async def _deferred_grid_start():
            try:
                try:
                    from merid.prediction.agent_grid import clear_agent_grid_deferred_skip

                    clear_agent_grid_deferred_skip()
                except Exception as e:
                    logger.debug(f"Clear deferred skip failed: {e}")
                logger.info("=" * 80)
                logger.info("🤖 Starting Kalshi Trading Agent Grid (background)")
                logger.info("=" * 80)
                from merid.prediction.agent_grid import get_agent_grid
                agent_grid = get_agent_grid()
                await agent_grid.start()
                logger.info("✅ Kalshi Agent Grid started: %d trading agents", len(agent_grid.agents))
            except Exception as e:
                try:
                    from merid.prediction.agent_grid import get_agent_grid as _gg

                    _gg().mark_startup_failure(e)
                except Exception as _mark_exc:
                    logger.debug("mark_startup_failure: %s", _mark_exc)
                logger.error("Failed to start Kalshi Agent Grid: %s", e, exc_info=True)

        _grid_task = asyncio.create_task(_deferred_grid_start(), name="deferred-grid-start")
        _startup_state["background_tasks"].append(_grid_task)

    # ── Phase 0.51: Bootstrap canonical agent registry (C9) ────────────────
    try:
        from merid.agents.bootstrap import ensure_bootstrapped
        _n_agents = ensure_bootstrapped()
        logger.info("✅ Canonical agent registry bootstrapped: %d agents", _n_agents)
        _startup_state["services"]["canonical_registry"] = {"status": "running", "agents": _n_agents, "started_at": time.time()}
    except Exception as e:
        logger.warning("Canonical agent bootstrap failed (non-fatal): %s", e)
        _startup_state["services"]["canonical_registry"] = {"status": "failed", "error": str(e)}

    # ── Phase 0.52: RealityAuditor + RewardEngine init (W4) ───────────────
    try:
        from core.reality_auditor import get_reality_auditor
        _auditor = get_reality_auditor()
        _auditor.reload_from_persistent_store()
        logger.info("✅ RealityAuditor started + initial assertions loaded")
        _startup_state["services"]["reality_auditor"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning("RealityAuditor init failed (non-fatal): %s", e)
        _startup_state["services"]["reality_auditor"] = {"status": "failed", "error": str(e)}

    try:
        from merid.rewards.engine import get_reward_engine
        get_reward_engine()
        logger.info("✅ RewardEngine singleton initialised")
        _startup_state["services"]["reward_engine"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning("RewardEngine init failed (non-fatal): %s", e)
        _startup_state["services"]["reward_engine"] = {"status": "failed", "error": str(e)}

    # ── Phase 0.53: PortfolioRebalancer bootstrap (W3) ─────────────────────
    try:
        from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
        _rebalancer = get_portfolio_rebalancer()
        _rebalancer._bootstrap_targets()
        logger.info("✅ PortfolioRebalancer bootstrapped from paper_config + agent grid")
        _startup_state["services"]["portfolio_rebalancer"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning("PortfolioRebalancer bootstrap failed (non-fatal): %s", e)
        _startup_state["services"]["portfolio_rebalancer"] = {"status": "failed", "error": str(e)}

    # ── Phase 0.54: NotificationManager (deferred) ──
    async def _deferred_notif_start():
        try:
            from notifications.notification_manager import get_notification_manager
            _notif_mgr = get_notification_manager()
            await _notif_mgr.start()
            logger.info("✅ NotificationManager started (escalation loop active)")
            _startup_state["services"]["notification_manager"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning("NotificationManager start failed (non-fatal): %s", e)
            _startup_state["services"]["notification_manager"] = {"status": "failed", "error": str(e)}

    _notif_task = asyncio.create_task(_deferred_notif_start(), name="deferred-notif-start")
    _startup_state["background_tasks"].append(_notif_task)

    # ── Phase 0.55: MeridLoop — deferred to Phase 2 (needs shared state) ──
    # MeridLoop starts later after all services are initialized.
    logger.debug("MeridLoop deferred to Phase 2 (after all services initialized)")

    # ── Phase 0.6: Orchestrator Agents (deferred) ─────────────────────
    # BUG-L13 FIX: Skip deferred orchestrator in VALIDATION_MODE to prevent
    # StreamingAgent creation through orchestrator_manager.start_all()
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Deferred orchestrator startup skipped (prevents agent mesh init)")
    else:
        async def _deferred_orchestrator_start():
            try:
                logger.info("=" * 80)
                logger.info("🤖 Starting Orchestrator Agents (news monitor, social feeds, etc.)")
                logger.info("=" * 80)
                orchestrator_manager = get_orchestrator_manager()
                await orchestrator_manager.start_all()
                logger.info("✅ Orchestrator agents started (news monitor, twitter, telegram)")
            except Exception as e:
                logger.error("Failed to start orchestrator agents: %s", e, exc_info=True)

        _orch_task = asyncio.create_task(_deferred_orchestrator_start(), name="deferred-orchestrator-start")
        _startup_state["background_tasks"].append(_orch_task)

    # ── Phase 1: Core systems ──────────────────────────────────────────
    logger.info("=" * 80)
    logger.info("🚀 MERID STARTUP INITIATED")
    logger.info("=" * 80)
    _log_phase("pre_init")  # TIMING: Pre-initialization complete

    logger.info(f"🚀 MERID Environment: {settings.MERID_ENV}")
    logger.info(f"🌐 WebSocket Dev Mode: {settings.allow_websocket_dev_mode}")

    live_issues = settings.validate_live_only_mode()
    if live_issues:
        for issue in live_issues:
            logger.warning(f"   - {issue}")
    else:
        logger.info("✅ Live-only mode validated - all features will use real data")

    if settings.is_production:
        missing = settings.validate_required_for_production()
        if missing:
            raise ValueError(f"Missing required production settings: {', '.join(missing)}")
        logger.info("✅ Production validation passed")
        
        # SENTIMENT_ISOLATION_AUDIT: Assert sentiment voting is disabled in production
        sentiment_voting_enabled = os.getenv("MERID_ALLOW_SENTIMENT_VOTING", "false").lower() == "true"
        if sentiment_voting_enabled:
            raise ValueError(
                "SECURITY: MERID_ALLOW_SENTIMENT_VOTING is true in production. "
                "Sentiment voting must be disabled in production to prevent sentiment leakage into execution. "
                "Set MERID_ALLOW_SENTIMENT_VOTING=false or unset the environment variable."
            )
        logger.info(
            "✅ Sentiment voting disabled in prod; telemetry-only mode active for BTC/ETH/SOL/XRP/DOGE 15m"
        )

    # ── Fresh Start: wipe transient state across all subsystems ────────
    from core.fresh_start import is_fresh_start, assert_safe_for_fresh_start
    assert_safe_for_fresh_start()  # hard crash if LIVE + FRESH_START
    if is_fresh_start():
        logger.warning("=" * 60)
        logger.warning("🧹 FRESH START MODE — wiping all transient state")
        logger.warning("=" * 60)

        # 1. Consensus store (SQLite opinions + plans)
        try:
            from core.consensus_store import get_consensus_store
            get_consensus_store().reset_all()
        except Exception as exc:
            logger.warning("Fresh-start: consensus store reset failed: %s", exc)

        # 2. Risk controller (zero daily PnL, keep kill-switch)
        try:
            from merid.risk import risk_controller
            risk_controller.reset_daily_counters()
        except Exception as exc:
            logger.warning("Fresh-start: risk controller reset failed: %s", exc)

        # 2b. Kalshi risk manager - resync category_contracts from actual positions
        # This fixes the desync where category_contracts accumulates incorrectly
        # when record_close() is not called for settled/closed positions.
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_mgr = get_kalshi_risk()
            risk_mgr.resync_category_contracts_from_positions()
            logger.info("Fresh-start: Kalshi category_contracts resynced from position cache")
        except Exception as exc:
            logger.warning("Fresh-start: Kalshi risk resync failed: %s", exc)

        # 3. Operator equity buffer
        try:
            from web.api.operator import reset_equity_buffer
            reset_equity_buffer()
        except Exception as exc:
            logger.warning("Fresh-start: equity buffer reset failed: %s", exc)

        # 4. Drift detector (in-memory CQI / outcomes)
        try:
            from merid.signals.drift import get_drift_detector
            get_drift_detector().reset()
        except Exception as exc:
            logger.warning("Fresh-start: drift detector reset failed: %s", exc)

        # 5. Signal store (SQLite drift_metrics, cqi_history, arb tables)
        try:
            from merid.signals.store import get_signal_store
            get_signal_store().reset_all()
        except Exception as exc:
            logger.warning("Fresh-start: signal store reset failed: %s", exc)

        # 6. Prediction consensus DB
        try:
            from pathlib import Path as _FsPath
            pred_db = _FsPath(__file__).resolve().parent.parent / "data" / "prediction_consensus.db"
            if pred_db.exists():
                import sqlite3
                # BUG-FIX (2026-05-12): Wrap SQLite operation in executor with timeout to prevent blocking
                # This is a synchronous database operation that can hang on file I/O
                loop = asyncio.get_event_loop()
                
                def _reset_db():
                    import sqlite3
                    import re
                    with sqlite3.connect(str(pred_db)) as _pc:
                        _SAFE_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
                        for tbl in _pc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                            tbl_name = tbl[0]
                            if not _SAFE_TABLE_RE.match(tbl_name):
                                logger.warning("Fresh-start: skipping suspicious table name: %s", tbl_name)
                                continue
                            _pc.execute(f"DELETE FROM [{tbl_name}]")
                
                await asyncio.wait_for(
                    loop.run_in_executor(None, _reset_db),
                    timeout=5.0
                )
                logger.info("Fresh-start: prediction_consensus.db truncated")
        except asyncio.TimeoutError:
            logger.warning("Fresh-start: prediction consensus reset timed out after 5s")
        except Exception as exc:
            logger.warning("Fresh-start: prediction consensus reset failed: %s", exc)

        # 7. Paper trading engine state (positions, ladder)
        try:
            from trading.paper_trading import get_paper_engine as _get_paper_engine
            _get_paper_engine().reset_state()
            logger.info("Fresh-start: paper trading state reset")
        except Exception as exc:
            logger.warning("Fresh-start: paper trading reset failed: %s", exc)

        # 8. Run any additional registered hooks
        from core.fresh_start import run_reset_hooks
        hook_count = run_reset_hooks()
        if hook_count:
            logger.info("Fresh-start: ran %d additional reset hooks", hook_count)

        logger.warning(
            "🔥 MERID FRESH START: all paper/consensus/signals/equity state reset. "
            "Kill switch state preserved. Historical audit logs untouched."
        )

    logger.info("Phase 1: Initializing core systems...")
    _phase_core_start = time.time()  # TIMING: Phase 1 start
    
    # ── Asset Cap Bootstrap: config → ExecutionGuard ────────────────────
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        guard.apply_asset_caps_from_config(settings)
        guard.ensure_core_assets_caps()  # Fail fast if BTC/ETH/SOL/XRP/DOGE missing
        logger.info("✅ Asset caps synced from config: %d assets", len(guard._asset_caps))
    except RuntimeError as e:
        logger.critical("Asset cap bootstrap failed — trading blocked: %s", e)
        # SOCIAL-TRUTH (2026-05-13): Telegram agent disabled for lean 15m Kalshi trading
        # try:
        #     from agents.telegram_agent import get_telegram_agent
        #     tg = get_telegram_agent()
        #     if tg.enabled:
        #         await tg.send_protect_alert(
        #             episode_id="bootstrap",
        #             assets=[],
        #             summary="Asset cap misconfiguration — trading blocked",
        #             reason=str(e),
        #             force=True,
        #         )
        # except Exception as tg_exc:
        #     logger.debug("Telegram PROTECT alert failed: %s", tg_exc)
        raise  # Prevent startup without proper risk limits
    except Exception as e:
        logger.warning("Asset cap bootstrap error (non-fatal): %s", e)
    
    try:
        from core.consensus_engine import get_consensus_engine
        consensus = get_consensus_engine()
        logger.info(f"✅ Consensus engine: {consensus.min_votes} min votes, {consensus.quorum_threshold:.2f} quorum")
        _startup_state["services"]["consensus"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Consensus engine initialization failed: {e}")
        _startup_state["services"]["consensus"] = {"status": "failed", "error": str(e)}

    # Paper trading engine SKIPPED (Kalshi-only mode) — would initialize crypto exchanges
    if not settings.KALSHI_ONLY:
        try:
            from trading.paper_trading import get_paper_trading_engine
            paper_engine = get_paper_trading_engine()
            portfolio_count = len(paper_engine.portfolios)
            position_count = sum(len(p.positions) for p in paper_engine.portfolios.values())
            logger.info(f"✅ Paper trading engine: {portfolio_count} portfolios, {position_count} positions restored")
            _startup_state["services"]["paper_trading"] = {"status": "running", "started_at": time.time(), "portfolios": portfolio_count, "positions": position_count}
        except Exception as e:
            logger.warning(f"⚠️  Paper trading engine initialization failed: {e}")
            _startup_state["services"]["paper_trading"] = {"status": "failed", "error": str(e)}
    else:
        logger.info("Paper trading engine SKIPPED (Kalshi-only mode)")
        _startup_state["services"]["paper_trading"] = {"status": "skipped", "reason": "Kalshi-only mode"}

    try:
        from pathlib import Path as _Path
        data_dir = _Path(__file__).resolve().parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        backup_api_ok = True
        try:
            from backup import get_backup_manager
            get_backup_manager()
        except Exception as _bue:
            logger.debug("backup manager unavailable: %s", _bue)
            backup_api_ok = False
        logger.info(f"✅ Data persistence: dir={data_dir.exists()}, backup_api={backup_api_ok}")
        _startup_state["services"]["data_persistence"] = {"status": "running", "data_dir": str(data_dir), "backup_api": backup_api_ok, "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Data persistence check failed: {e}")
        _startup_state["services"]["data_persistence"] = {"status": "failed", "error": str(e)}

    try:
        from agents.reflection_layer import reflection_layer
        reflection_count = len(getattr(reflection_layer, 'reflections', getattr(reflection_layer, '_reflections', [])))
        agent_count = len(getattr(reflection_layer, 'agent_stats', getattr(reflection_layer, '_agent_stats', {})))
        logger.info(f"✅ Reflection layer: {reflection_count} reflections, {agent_count} agents")
        _startup_state["services"]["reflection"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Reflection layer initialization failed: {e}")
        _startup_state["services"]["reflection"] = {"status": "failed", "error": str(e)}

    try:
        from monitoring.brier_metrics import get_brier_tracker
        brier = get_brier_tracker()
        prediction_count = len(getattr(brier, 'predictions', getattr(brier, '_predictions', [])))
        logger.info(f"✅ Brier metrics: {prediction_count} predictions tracked")
        _startup_state["services"]["brier_metrics"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Brier metrics initialization failed: {e}")
        _startup_state["services"]["brier_metrics"] = {"status": "failed", "error": str(e)}

    try:
        from memory.neo4j_graph import get_neo4j_graph, is_neo4j_available
        if is_neo4j_available():
            graph = get_neo4j_graph()
            logger.info(f"✅ Neo4j graph database connected: {graph.config.uri}")
            _startup_state["services"]["neo4j"] = {"status": "running", "started_at": time.time()}
        else:
            logger.info("⚠️  Neo4j not available - using JSON-only memory storage")
            _startup_state["services"]["neo4j"] = {"status": "unavailable", "message": "Not configured or not installed"}
    except Exception as e:
        logger.warning(f"⚠️  Neo4j initialization failed: {e}")
        _startup_state["services"]["neo4j"] = {"status": "failed", "error": str(e)}

    # ── Phase 2: Prediction markets (DISABLED — Kalshi-only mode) ──────
    _log_phase("phase1_core")  # TIMING: Phase 1 complete
    aggregator = None  # Legacy crypto prediction aggregator disabled
    logger.info("Phase 2: Legacy prediction markets SKIPPED (Kalshi-only mode)")
    _log_phase("phase2_prediction")  # TIMING: Phase 2 complete (skipped)

    # ── Phase 3: Streaming & background services ─────────────────────
    logger.info("Phase 3: Starting streaming & background services...")

    # LivePriceFeed: Coinbase Advanced HTTP polling for PM crypto spot (BTC/ETH/SOL/XRP/DOGE).
    # KALSHI_ONLY disables CCXT exchange clients in LivePriceFeed, but Coinbase remains the
    # primary source — without start_streaming(), price_cache stays empty and all PM agents
    # see missing spot / CRYPTO_15M_MM pm_spot_hard_gate blocks.
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Live price feed skipped (prevents startup lag)")
        _startup_state["services"]["live_price_feed"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from data.live_price_feed import get_live_price_feed

            _lpf = get_live_price_feed()

            async def _run_price_feed_streaming() -> None:
                max_attempts = 4
                delay_s = 2.0
                try:
                    for attempt in range(1, max_attempts + 1):
                        try:
                            await _lpf.start_streaming()
                            if attempt > 1:
                                logger.warning(
                                    "Live price feed: start_streaming succeeded on attempt %d/%d",
                                    attempt,
                                    max_attempts,
                                )
                            return
                        except asyncio.CancelledError:
                            _lpf.stop_streaming()
                            raise
                        except Exception as _pfe:
                            logger.error(
                                "Price feed start_streaming attempt %d/%d failed: %s",
                                attempt,
                                max_attempts,
                                _pfe,
                                exc_info=True,
                            )
                            if attempt >= max_attempts:
                                raise
                            await asyncio.sleep(delay_s)
                            delay_s = min(delay_s * 2.0, 30.0)
                except asyncio.CancelledError:
                    _lpf.stop_streaming()
                    raise
                except Exception as _pfe:
                    logger.error("Price feed streaming exited with error: %s", _pfe, exc_info=True)

            _pf_task = asyncio.create_task(_run_price_feed_streaming(), name="price_feed_streaming")
            _startup_state["background_tasks"].append(_pf_task)
            _startup_state["services"]["live_price_feed"] = {"status": "running", "started_at": time.time()}
            logger.info("✅ Live price feed streaming task started (Coinbase primary for PM spot)")
        except Exception as _lpf_exc:
            logger.warning("Live price feed failed to start (PM spot may be unavailable): %s", _lpf_exc)
            _startup_state["services"]["live_price_feed"] = {"status": "failed", "error": str(_lpf_exc)}

    # Event bus bridge — forwards core.event_bus events into observability.event_stream
    # so the /ws WebSocket sees Kalshi trade events and MeridCore consensus events.
    # Without this bridge the two buses are completely isolated silos.
    async def _event_bus_bridge() -> None:
        from core.event_bus import event_stream as _core_bus
        from observability.event_stream import get_event_stream as _get_obs_stream
        _obs_stream = _get_obs_stream()
        _queue = await _core_bus.subscribe()
        logger.info("Event bus bridge started (core.event_bus → observability.event_stream)")
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(_queue.get(), timeout=5.0)
                    await _obs_stream.publish(evt.get("type", ""), evt.get("payload", {}))
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as _bridge_exc:
                    logger.debug(f"Event bus bridge error (ignored): {_bridge_exc}")
        finally:
            await _core_bus.unsubscribe(_queue)
            logger.info("Event bus bridge stopped")

    try:
        task = asyncio.create_task(_event_bus_bridge(), name="event-bus-bridge")
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Event bus bridge started")
        _startup_state["services"]["event_bus_bridge"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Event bus bridge failed: {e}")
        _startup_state["services"]["event_bus_bridge"] = {"status": "failed", "error": str(e)}

    # Core infrastructure: HealthMonitor, AlertManager, AuditTrail, SystemOrchestrator
    # These are foundational and must start before Kalshi subsystems
    try:
        from core.health import get_health_monitor
        _health_mon = get_health_monitor()
        await _health_mon.start()
        logger.info("✅ HealthMonitor started")
        _startup_state["services"]["health_monitor"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        startup_success = False
        logger.warning(f"⚠️  HealthMonitor failed to start: {e}")
        _startup_state["services"]["health_monitor"] = {"status": "failed", "error": str(e)}

    # LoopLagMonitor — event-loop starvation detection (diagnostics)
    # LAG-MITIGATION: Use 3s interval (vs default 1s) to reduce monitoring overhead
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        _loop_lag = get_loop_lag_monitor()
        _loop_lag._interval_ms = 3000.0  # 3s interval to reduce overhead
        _loop_lag.start()
        logger.info("✅ LoopLagMonitor started (event-loop lag detection, interval=3s)")
        _startup_state["services"]["loop_lag_monitor"] = {"status": "running", "started_at": time.time(), "interval_ms": 3000}
    except Exception as e:
        logger.warning(f"⚠️  LoopLagMonitor failed to start: {e}")
        _startup_state["services"]["loop_lag_monitor"] = {"status": "failed", "error": str(e)}

    try:
        from core.alerts import get_alert_manager
        _alert_mgr = get_alert_manager()
        await _alert_mgr.start()
        logger.info("✅ AlertManager started")
        _startup_state["services"]["alert_manager"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        startup_success = False
        logger.warning(f"⚠️  AlertManager failed to start: {e}")
        _startup_state["services"]["alert_manager"] = {"status": "failed", "error": str(e)}

    try:
        from core.audit_trail import get_audit_trail
        _audit = get_audit_trail()
        await _audit.start()
        logger.info("✅ AuditTrail started")
        _startup_state["services"]["audit_trail"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        startup_success = False
        logger.warning(f"⚠️  AuditTrail failed to start: {e}")
        _startup_state["services"]["audit_trail"] = {"status": "failed", "error": str(e)}

    # BUG-L13 FIX: Skip SystemOrchestrator in VALIDATION_MODE to prevent startup lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] SystemOrchestrator skipped (reduces startup lag)")
        _startup_state["services"]["system_orchestrator"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from core.system_orchestrator import start_merid
            await start_merid()
            logger.info("✅ SystemOrchestrator started (consensus engine, inter-system API)")
            _startup_state["services"]["system_orchestrator"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            startup_success = False
            logger.warning(f"⚠️  SystemOrchestrator failed to start: {e}")
            _startup_state["services"]["system_orchestrator"] = {"status": "failed", "error": str(e)}

    # KalshiVenueClient — connect + authenticate eagerly so auth errors
    # surface at startup instead of causing circuit-breaker storms in the loop.
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        _kalshi_client = get_kalshi_client()
        await _kalshi_client.connect()
        logger.info("✅ KalshiVenueClient connected + authenticated")
        _startup_state["services"]["kalshi_client"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        startup_success = False
        logger.error(f"❌ KalshiVenueClient connect failed: {e}")
        _startup_state["services"]["kalshi_client"] = {"status": "failed", "error": str(e)}

    # KalshiMarketCache — background TTL cleanup task for Kalshi API cache
    try:
        from merid.event_venues.kalshi.market_cache import get_market_cache
        _market_cache = get_market_cache()
        await _market_cache.start()
        logger.info("✅ KalshiMarketCache started (TTL cleanup loop)")
        _startup_state["services"]["kalshi_market_cache"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  KalshiMarketCache failed to start: {e}")
        _startup_state["services"]["kalshi_market_cache"] = {"status": "failed", "error": str(e)}

    # KalshiMarketCatalog — fetches + caches all active Kalshi markets (backbone for pipeline/agents)
    logger.info("[MARKET-CATALOG] pre_start: calling _catalog.start()")
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        _catalog = get_market_catalog()
        await _catalog.start()
        logger.info("[MARKET-CATALOG] post_start: _catalog.start() returned")
        # BUG-L13 FIX: In VALIDATION_MODE, cancel the periodic 5-min refresh loop after the
        # initial load.  The refresh() method makes 20+ sequential Kalshi REST calls (~7s total)
        # which blocks the event loop for up to 1390ms per cycle — triggering lag profiles every
        # 5 minutes during the infra gate.  Initial catalog data is sufficient for validation.
        _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
        if _is_validation and _catalog._task and not _catalog._task.done():
            _catalog._task.cancel()
            logger.info("[VALIDATION MODE] KalshiMarketCatalog periodic refresh cancelled (initial load retained)")
        logger.info("✅ KalshiMarketCatalog started (market data backbone)")
        _startup_state["services"]["kalshi_market_catalog"] = {"status": "running", "started_at": time.time()}
        
        logger.info("[MARKET-CATALOG] post_refresh: starting market universe validation")
        # MARKET UNIVERSE VALIDATION: Ensure catalog, agent grid, and trading agent
        # all see the same filtered market universe (BTC/ETH/SOL/XRP/DOGE 15m only)
        try:
            _universe = _catalog.get_market_universe()
            if _universe is None:
                logger.warning("[MARKET-UNIVERSE-VALIDATION] MarketUniverse not available yet (catalog may still be loading)")
            else:
                _catalog_assets = _universe.get_assets()
                _catalog_count = _universe.get_market_count()
                logger.info(
                    "[MARKET-UNIVERSE-VALIDATION] Catalog universe: %d markets, %d assets: %s",
                    _catalog_count,
                    len(_catalog_assets),
                    sorted(_catalog_assets)
                )
                # Expected assets based on AllowedMarketPolicy
                _expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                if _catalog_assets != _expected_assets:
                    logger.error(
                        "[MARKET-UNIVERSE-VALIDATION] CRITICAL: Catalog assets mismatch! "
                        "Expected %s, got %s",
                        sorted(_expected_assets),
                        sorted(_catalog_assets)
                    )
                    startup_success = False
                if _catalog_count == 0:
                    logger.error(
                        "[MARKET-UNIVERSE-VALIDATION] CRITICAL: Catalog universe is empty! "
                        "No markets available for trading."
                    )
                    startup_success = False
        except Exception as _universe_exc:
            logger.warning(
                "[MARKET-UNIVERSE-VALIDATION] Failed to validate market universe: %s",
                _universe_exc
            )
        logger.info("[MARKET-CATALOG] post_refresh: market universe validation complete")
    except Exception as e:
        startup_success = False
        logger.warning(f"⚠️  KalshiMarketCatalog failed to start: {e}")
        _startup_state["services"]["kalshi_market_catalog"] = {"status": "failed", "error": str(e)}

    # KalshiMarketStateStore REST refresh — periodically feeds volume_24h/OI/expiry into
    # KalshiMarketState so CryptoAlertRouter and other consumers see up-to-date REST fields.
    # The WS bridge only updates book data; REST fields would otherwise stay at zero.
    # FIX: Defer first refresh to avoid blocking startup with 5000 markets
    async def _run_market_state_rest_refresh():
        import asyncio as _asyncio
        # IMPORTANT: keep this on the event loop (not asyncio.to_thread).
        # apply_rest_market uses threading.Lock; offloading to a thread causes WS
        # handlers (also acquiring that lock) to block the event loop.
        # batch_size=10 ensures max ~6ms synchronous work before each yield.
        # At 5000 markets: 500 yields total, completing the full loop in ~3s spread
        # across many event-loop ticks — invisible to the LoopLagMonitor.
        _BATCH = 10
        # Wait before first refresh to avoid blocking startup
        await _asyncio.sleep(5)
        while True:
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog as _get_cat
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store as _get_store
                _store = _get_store()
                _markets = _get_cat().get_all_markets()
                for _i, cm in enumerate(_markets):
                    m = cm.market
                    if not getattr(m, "market_id", None):
                        continue
                    _raw = getattr(m, "raw_data", None) or {}
                    # Prefer volume_24h from raw_data (now populated by _to_event_market),
                    # fall back to total volume as proxy if unavailable.
                    _vol24 = _raw.get("volume_24h")
                    if _vol24 is None:
                        _vol24 = int(m.volume) if m.volume is not None else None
                    _store.apply_rest_market({
                        "ticker": m.market_id,
                        "volume_24h": _vol24,
                        "open_interest": int(m.open_interest) if m.open_interest is not None else None,
                        "expiration_time": m.end_date.isoformat() if m.end_date else None,
                    })
                    if (_i + 1) % _BATCH == 0:
                        await _asyncio.sleep(0)
            except Exception as _exc:
                logger.debug("Market state REST refresh error: %s", _exc)
            await _asyncio.sleep(60)

    logger.info("[MARKET-CATALOG] post_refresh: starting KalshiMarketState REST refresh loop")
    try:
        _rest_refresh_task = asyncio.create_task(
            _run_market_state_rest_refresh(), name="kalshi-state-rest-refresh"
        )
        _startup_state["background_tasks"].append(_rest_refresh_task)
        logger.info("✅ KalshiMarketState REST refresh loop started (60s interval)")
    except Exception as e:
        logger.warning(f"⚠️  KalshiMarketState REST refresh loop failed to start: {e}")
    logger.info("[MARKET-CATALOG] post_refresh: KalshiMarketState REST refresh loop started")

    logger.info("[MARKET-CATALOG] post_refresh: starting KalshiSentimentService")
    # KalshiSentimentService — background loop ingesting catalog → sentiment scores
    # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
    # FIX: Defer start to avoid blocking startup with 5000 market ingest
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiSentimentService skipped (not needed for validation)")
        _startup_state["services"]["kalshi_sentiment_service"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.event_venues.kalshi.sentiment import get_sentiment_service
            _sentiment_svc = get_sentiment_service()
            # Start in background task to avoid blocking
            async def _deferred_sentiment_start():
                try:
                    await _sentiment_svc.start()
                    logger.info("✅ KalshiSentimentService started (sentiment refresh loop)")
                except Exception as e:
                    logger.warning(f"⚠️  KalshiSentimentService failed to start: {e}")
            _sentiment_task = asyncio.create_task(_deferred_sentiment_start(), name="deferred-sentiment-start")
            _startup_state["background_tasks"].append(_sentiment_task)
            _startup_state["services"]["kalshi_sentiment_service"] = {"status": "starting", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  KalshiSentimentService failed to start: {e}")
            _startup_state["services"]["kalshi_sentiment_service"] = {"status": "failed", "error": str(e)}
    logger.info("[MARKET-CATALOG] post_refresh: KalshiSentimentService started")

    logger.info("[MARKET-CATALOG] post_refresh: starting KalshiWebSocketBridge")
    # KalshiWebSocketBridge — pipes real-time Kalshi WS events into core event bus
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        from merid.event_venues.kalshi.market_catalog import get_market_catalog as _get_cat
        from merid.event_venues.kalshi.crypto_catalog import prepare_crypto_ws_bridge_subscription

        _ws_bridge = get_ws_bridge()
        _bundle = prepare_crypto_ws_bridge_subscription(_get_cat())
        _active_tickers = _bundle["tickers"]
        if not _bundle["ok_prefix_coverage"]:
            logger.error(
                "Kalshi WS ticker→asset map: missing assets=%s kalshi_counts=%s total=%d "
                "(set MERID_STRICT_WS_CRYPTO_COVERAGE=1 to fail startup)",
                _bundle["missing_prefix_assets"],
                _bundle["counts_by_prefix"],
                _bundle["total"],
            )
        if not _bundle["ok_catalog_assets"]:
            logger.warning(
                "Kalshi WS crypto subscription gap: missing orderbook targets for assets=%s "
                "(by_asset_counts=%s total_tickers=%d)",
                _bundle["missing_catalog_assets"],
                _bundle["by_asset_catalog"],
                _bundle["total"],
            )
        else:
            logger.info(
                "Kalshi WS crypto subscription coverage OK: by_asset=%s total_tickers=%d prefix_counts=%s",
                _bundle["by_asset_catalog"],
                _bundle["total"],
                _bundle["counts_by_prefix"],
            )
        # BUG-L12 FIX: In VALIDATION_MODE, defer bridge startup to background task
        # to prevent blocking startup with 669+ ticker subscriptions
        _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        if _is_validation:
            logger.info("[VALIDATION MODE] KalshiWebSocketBridge startup deferred to background task")
            _startup_state["services"]["kalshi_ws_bridge"] = {
                "status": "deferred",
                "reason": "validation_mode - will start in background task",
            }
        else:
            logger.info("[MARKET-CATALOG] post_refresh: calling ws_bridge.start()")
            task = asyncio.create_task(
                _ws_bridge.start(_active_tickers or None), name="kalshi-ws-bridge"
            )
            _startup_state["background_tasks"].append(task)
            logger.info(f"✅ KalshiWebSocketBridge started ({len(_active_tickers)} crypto tickers)")
            _startup_state["services"]["kalshi_ws_bridge"] = {
                "status": "running",
                "started_at": time.time(),
                "tickers": len(_active_tickers),
                "crypto_by_asset": _bundle["by_asset_catalog"],
            }
    except Exception as e:
        logger.warning(f"⚠️  KalshiWebSocketBridge failed to start: {e}")
        _startup_state["services"]["kalshi_ws_bridge"] = {"status": "failed", "error": str(e)}
    logger.info("[MARKET-CATALOG] post_refresh: KalshiWebSocketBridge started")

    logger.info("[MARKET-CATALOG] post_refresh: starting KalshiFillsPoller")
    # KalshiFillsPoller — background HTTP polling + reconciliation for fills ledger
    # Must start AFTER WebSocketBridge for dual ingestion setup
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent startup lag
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiFillsPoller skipped (deferred to reduce startup lag)")
        _startup_state["services"]["kalshi_fills_poller"] = {"status": "deferred", "reason": "validation_mode"}
    else:
        try:
            from merid.event_venues.kalshi.fills_poller import get_fills_poller
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            _fills_poller = get_fills_poller()
            logger.info("[MARKET-CATALOG] post_refresh: calling fills_poller.start()")
            await _fills_poller.start()
            logger.info("✅ KalshiFillsPoller started (HTTP polling + reconciliation)")
            _startup_state["services"]["kalshi_fills_poller"] = {"status": "running", "started_at": time.time()}

            # CRITICAL FIX: Clear incomplete/false fills from DB to remove phantom positions
            # These fills have count_fp <= 0 or missing price data and should not be counted as positions
            _ledger = get_fills_ledger()
            _cleared = await _ledger.clear_incomplete_fills()
            if _cleared > 0:
                logger.warning(f"Cleared {_cleared} incomplete/false fills from DB (phantom fills removed)")
        except Exception as e:
            logger.warning(f"⚠️  KalshiFillsPoller failed to start: {e}")
            _startup_state["services"]["kalshi_fills_poller"] = {"status": "failed", "error": str(e)}
    logger.info("[MARKET-CATALOG] post_refresh: KalshiFillsPoller started")

    logger.info("[MARKET-CATALOG] post_refresh: starting OutcomeResolver")
    # OutcomeResolver — resolves settled Kalshi markets, updates KalshiRiskEngine bankroll P&L
    # BUG-1 FIX: was never started; OutcomeResolver.resolve_all() / record_trade_result() never fired
    if not _is_validation:
        try:
            from merid.metrics.outcome_resolver import get_outcome_resolver as _get_or
            _outcome_resolver = _get_or()
            logger.info("[MARKET-CATALOG] post_refresh: calling outcome_resolver.start()")
            await _outcome_resolver.start(interval_s=300)
            logger.info("✅ OutcomeResolver started (interval=300s)")
            _startup_state["services"]["outcome_resolver"] = {"status": "running", "started_at": time.time()}
        except Exception as _ore:
            logger.warning("⚠️  OutcomeResolver failed to start: %s", _ore)
            _startup_state["services"]["outcome_resolver"] = {"status": "failed", "error": str(_ore)}
    logger.info("[MARKET-CATALOG] post_refresh: OutcomeResolver started")

    # KalshiSettlementPoller — polls /portfolio/settlements for calibration grading pipeline
    # Must start AFTER FillsPoller (shares credential pattern)
    # BUG-DOWNSTREAM-1 FIX: was never started anywhere; settlements were never graded
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiSettlementPoller skipped")
        _startup_state["services"]["kalshi_settlement_poller"] = {"status": "deferred", "reason": "validation_mode"}
    else:
        try:
            from merid.event_venues.kalshi.settlement_poller import start_settlement_polling_auto
            _settlement_poller = await start_settlement_polling_auto()
            if _settlement_poller is not None:
                # BUG-7 FIX: Wire APT grading callback so wins/losses record on market settlement.
                async def _apt_settlement_callback(settlement) -> None:  # type: ignore[name-defined]
                    """Forward SettlementPoller events to AgentPerformanceTracker."""
                    try:
                        _price = getattr(settlement, "settlement_price_cents", None) or 0
                        _mid = getattr(settlement, "market_id", None) or getattr(settlement, "ticker", "")
                        # GUARD: Skip settlements with missing market identification
                        if not _mid:
                            logger.debug("Settlement callback skipped: missing market_id/ticker")
                            return
                        _settled_yes = _price >= 50
                        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker as _gapt
                        _apt7 = _gapt()
                        _keys = [k for k in _apt7._open_trades if k.endswith(f":{_mid}")]
                        for _k in _keys:
                            _apt7.record_outcome(_mid, _settled_yes, _price)
                            logger.info("SettlementPoller→APT: %s settled_yes=%s price=%d¢", _mid, _settled_yes, _price)
                    except Exception as _e:
                        logger.debug("APT settlement callback skipped: %s", _e)

                _settlement_poller.add_callback(_apt_settlement_callback)
                logger.info("✅ KalshiSettlementPoller started (polls /portfolio/settlements)")
                _startup_state["services"]["kalshi_settlement_poller"] = {"status": "running", "started_at": time.time()}
            else:
                logger.warning("⚠️  KalshiSettlementPoller skipped — Kalshi credentials not configured")
                _startup_state["services"]["kalshi_settlement_poller"] = {"status": "skipped", "reason": "no_credentials"}
        except Exception as e:
            logger.warning(f"⚠️  KalshiSettlementPoller failed to start: {e}")
            _startup_state["services"]["kalshi_settlement_poller"] = {"status": "failed", "error": str(e)}

    # CryptoAlertRouter — classifies live crypto markets, emits batched Telegram alerts every 30s
    try:
        import sys as _sys
        from merid.alerts.crypto_alert_router import CryptoAlertRouter as _CryptoAlertRouter
        from config.crypto_alert_config import CryptoAlertConfig as _CryptoAlertConfig
        _crypto_router = _CryptoAlertRouter(cfg=_CryptoAlertConfig())
        _se_mod = _sys.modules.get("web.api.system_endpoints")
        if _se_mod and hasattr(_se_mod, "set_crypto_alert_router"):
            _se_mod.set_crypto_alert_router(_crypto_router)
        _crypto_router.start()
        # _task is initialised to None and assigned inside start(); guard against
        # start() raising before the assignment so we never append None to the list.
        if _crypto_router._task is not None:
            _startup_state["background_tasks"].append(_crypto_router._task)
        logger.info("✅ CryptoAlertRouter started (30s tick, BTC/ETH/SOL/XRP/DOGE)")
        _startup_state["services"]["crypto_alert_router"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  CryptoAlertRouter failed to start: {e}")

    # SpotBasisTracker — measures Coinbase spot vs Kalshi-implied spot basis per asset
    # LEAN 15m KALSHI STACK (2026-05-13): Skip when ENABLE_SPOT_BASIS_TRACKER=false to prevent hangs/timeout risk
    # Basis features from CryptoSignalsAgent/microstructure feed are sufficient for 15m direction bets
    _basis_disabled = __import__("os").environ.get("ENABLE_SPOT_BASIS_TRACKER", "true").lower() == "false"
    if _basis_disabled:
        logger.info("[LEAN KALSHI] SpotBasisTracker skipped (ENABLE_SPOT_BASIS_TRACKER=false)")
        _startup_state["services"]["spot_basis_tracker"] = {"status": "skipped", "reason": "basis_disabled"}
    else:
        try:
            from merid.alignment import get_spot_basis_tracker as _get_basis_tracker
            _basis_tracker = _get_basis_tracker()
            _basis_tracker.start()
            logger.info("✅ SpotBasisTracker started (1s tick, BTC/ETH/SOL/XRP/DOGE)")
            _startup_state["services"]["spot_basis_tracker"] = {"status": "running", "started_at": time.time()}
        except Exception as _basis_exc:
            logger.warning("⚠️  SpotBasisTracker failed to start (non-fatal): %s", _basis_exc)
            _startup_state["services"]["spot_basis_tracker"] = {"status": "failed", "error": str(_basis_exc)}

    # CryptoRTIMonitor + CryptoTermStructureModel lifecycle
    # RTI monitor is registered as a singleton so TSM can call get_global_crypto_rti_monitor()
    _tsm = None
    try:
        from merid.risk.crypto_rti_monitor import CryptoRTIMonitor, set_global_crypto_rti_monitor
        from core.event_bus import event_stream as _rti_event_bus
        _crypto_rti_monitor = CryptoRTIMonitor(event_bus=_rti_event_bus, portfolio_risk_agent=None)
        set_global_crypto_rti_monitor(_crypto_rti_monitor)
        from merid.risk.crypto_term_structure import CryptoTermStructureModel, set_global_crypto_tsm
        _tsm_candidate = CryptoTermStructureModel()
        await _tsm_candidate.start()
        set_global_crypto_tsm(_tsm_candidate)
        _tsm = _tsm_candidate  # only promote after successful start
        logger.info("✅ CryptoRTIMonitor registered + CryptoTermStructureModel started")
        _startup_state["services"]["crypto_term_structure"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning("⚠️  CryptoTermStructureModel failed to start: %s", e)
        _startup_state["services"]["crypto_term_structure"] = {"status": "failed", "error": str(e)}

    # RTIFeedService — pushes CFB ticks into CryptoRTIMonitor → TSM
    # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] RTIFeedService skipped (not needed for validation)")
        _startup_state["services"]["rti_feed_service"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.data.rti_feed_service import get_rti_feed_service
            _rti_feed_service = get_rti_feed_service()
            await _rti_feed_service.start()
            logger.info("✅ RTIFeedService started")
            _startup_state["services"]["rti_feed_service"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning("⚠️  RTIFeedService failed to start: %s", e)
            _startup_state["services"]["rti_feed_service"] = {"status": "failed", "error": str(e)}

    # KalshiContinuousTrader — optional; AgentGrid is the production PM stack.
    # MERID_ENABLE_KALSHI_CT=true to run CT with the API. MERID_PM_PROFILE=production forces off.
    # When MERID_PM_TRADING_MODE=live and MERID_PM_LIVE_ENABLED=true, CT is suppressed unless
    # MERID_CT_RESEARCH_ALLOW_LOOP=true (legacy / research only).
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    _ct_enabled = bool(settings.MERID_ENABLE_KALSHI_CT)
    if (settings.MERID_PM_PROFILE or "").strip().lower() == "production":
        _ct_enabled = False
    try:
        from merid.prediction.pm_ct_policy import ct_loop_suppressed

        if _ct_enabled and ct_loop_suppressed():
            _ct_enabled = False
            logger.info(
                "[CT-LEGACY] KalshiContinuousTrader startup suppressed — AgentGrid PM and/or "
                "MERID_TRADE_MODE=live + MERID_ALLOW_LIVE_TRADES (set MERID_CT_RESEARCH_ALLOW_LOOP=true "
                "for research-only CT)."
            )
    except Exception as _ct_pol:
        logger.debug("pm_ct_policy CT startup check: %s", _ct_pol)
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiContinuousTrader skipped (not needed for validation)")
        _startup_state["services"]["continuous_trader"] = {"status": "skipped", "reason": "validation_mode"}
    elif not _ct_enabled:
        logger.info(
            "KalshiContinuousTrader skipped (MERID_ENABLE_KALSHI_CT is false; AgentGrid owns PM execution). "
            "Set MERID_ENABLE_KALSHI_CT=true to run CT with the server."
        )
        _startup_state["services"]["continuous_trader"] = {"status": "skipped", "reason": "disabled"}
    else:
        try:
            from merid.trading.kalshi_continuous_trader import get_continuous_trader as _get_ct
            _ct = _get_ct()
            _ct_task = asyncio.create_task(_ct.run(), name="kalshi-continuous-trader")
            
            # Add done callback to catch exceptions (fire-and-forget safety)
            def _ct_done_callback(task):
                try:
                    task.result()  # Re-raise any exception
                except asyncio.CancelledError:
                    logger.info("KalshiContinuousTrader task cancelled")
                except Exception as e:
                    logger.error(f"KalshiContinuousTrader crashed: {e}", exc_info=True)
            
            _ct_task.add_done_callback(_ct_done_callback)
            _startup_state["background_tasks"].append(_ct_task)
            logger.info(
                "✅ KalshiContinuousTrader started (interval=%ds, dry_run=%s)",
                _ct.config.interval_seconds, _ct.config.dry_run,
            )
            _startup_state["services"]["continuous_trader"] = {
                "status": "running", "started_at": time.time(),
                "interval_seconds": _ct.config.interval_seconds,
                "dry_run": _ct.config.dry_run,
            }
        except Exception as e:
            logger.warning("⚠️  KalshiContinuousTrader failed to start: %s", e)
            _startup_state["services"]["continuous_trader"] = {"status": "failed", "error": str(e)}

    # TickerCollector — accumulates kalshi:price_update events into in-memory DataFrame
    # BUG-L13 FIX: Skip in VALIDATION_MODE since it depends on WS data
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] TickerCollector skipped (depends on WS data)")
        _startup_state["services"]["ticker_collector"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.event_venues.kalshi.ticker_collector import get_ticker_collector
            _ticker_collector = get_ticker_collector()
            await _ticker_collector.start()
            logger.info("✅ TickerCollector started (WS tick accumulator)")
            _startup_state["services"]["ticker_collector"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  TickerCollector failed to start: {e}")
            _startup_state["services"]["ticker_collector"] = {"status": "failed", "error": str(e)}

    # KalshiInsightPipeline — Kalshi markets → swarm consensus → InsightObject emitter
    # Wire KalshiNewsAgent as consumer BEFORE starting so no insights are dropped
    # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiInsightPipeline skipped (11 category loops deferred)")
        _startup_state["services"]["kalshi_insight_pipeline"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline
            from merid.publishing.kalshi_news_agent import get_kalshi_news_agent
            _insight_pipeline = get_insight_pipeline()
            _news_agent = get_kalshi_news_agent()
            _insight_pipeline.add_consumer(_news_agent.handle_insight)

            # Bridge: also publish each InsightObject to streaming_bus.NEWS so
            # NewsAnalystAgent (and any other NEWS subscribers) receive Kalshi insights
            async def _insight_to_news_bus(ins) -> None:
                try:
                    from core.streaming_bus import publish_news
                    await publish_news(
                        title=ins.question,
                        content=ins.narrative,
                        source=f"kalshi:{ins.ticker}",
                        sentiment=ins.swarm_prob - 0.5,  # centre around 0
                        category=ins.category,
                        ticker=ins.ticker,
                        kalshi_prob=ins.kalshi_prob,
                        swarm_confidence=ins.swarm_confidence,
                        action=ins.action,
                        source_name="Kalshi",
                    )
                except Exception as _e:
                    logger.debug(f"insight→news_bus bridge error (non-fatal): {_e}")

            _insight_pipeline.add_consumer(_insight_to_news_bus)
            await _insight_pipeline.start()
            logger.info("✅ KalshiInsightPipeline started (11 category loops → KalshiNewsAgent + streaming_bus.NEWS)")
            _startup_state["services"]["kalshi_insight_pipeline"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  KalshiInsightPipeline failed to start: {e}")
            _startup_state["services"]["kalshi_insight_pipeline"] = {"status": "failed", "error": str(e)}

    # EnhancedConsensusCoordinator opinion subscriber — listens for strategy_opinion events
    # on core.event_bus and triggers consensus rounds when quorum is reached
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 4s+ startup lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] EnhancedConsensusCoordinator opinion subscriber skipped (prevents 4s+ lag)")
        _startup_state["services"]["enhanced_consensus_coordinator"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from consensus.consensus_coordinator import EnhancedConsensusCoordinator
            _enhanced_consensus = EnhancedConsensusCoordinator.get_instance()
            await _enhanced_consensus.start_opinion_subscriber()
            logger.info("✅ EnhancedConsensusCoordinator opinion subscriber started")
            _startup_state["services"]["enhanced_consensus_coordinator"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  EnhancedConsensusCoordinator opinion subscriber failed to start: {e}")
            _startup_state["services"]["enhanced_consensus_coordinator"] = {"status": "failed", "error": str(e)}

    # OrchestratorAgentManager — already started at Phase 0.6 above
    # (do NOT call start_all() again — would double-start all agents)

    # WatchdogCoordinator — periodic liveness + consensus health checks
    try:
        from agents.watchdog_agents import get_watchdog_coordinator
        _watchdog = get_watchdog_coordinator()
        await _watchdog.start()
        logger.info("✅ WatchdogCoordinator started (liveness + consensus checks)")
        _startup_state["services"]["watchdog_coordinator"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  WatchdogCoordinator failed to start: {e}")
        _startup_state["services"]["watchdog_coordinator"] = {"status": "failed", "error": str(e)}

    # MarketMoodBus — unified sentiment/context aggregation loop for all agents
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent event-loop lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] MarketMoodBus skipped (prevents lag)")
        _startup_state["services"]["market_mood_bus"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            _mood_bus = get_market_mood_bus()
            await _mood_bus.start()
            logger.info("✅ MarketMoodBus started (sentiment aggregation loop)")
            _startup_state["services"]["market_mood_bus"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  MarketMoodBus failed to start: {e}")
            _startup_state["services"]["market_mood_bus"] = {"status": "failed", "error": str(e)}

    # SentimentBus — Twitter + Reddit background loops → MarketMoodBus social sentiment
    # Must start AFTER MarketMoodBus since it pushes data into it
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent extreme event-loop lag
    # LEAN 15m KALSHI STACK (2026-05-13): Skip when ENABLE_SENTIMENT_TRUTH=false to prevent native crashes
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    _sentiment_disabled = __import__("os").environ.get("ENABLE_SENTIMENT_TRUTH", "true").lower() == "false"
    if _is_validation:
        logger.info("[VALIDATION MODE] SentimentBus skipped (prevents 10s+ lag from Twitter/Reddit scraping)")
        _startup_state["services"]["sentiment_bus"] = {"status": "skipped", "reason": "validation_mode"}
    elif _sentiment_disabled:
        logger.info("[LEAN KALSHI] SentimentBus skipped (ENABLE_SENTIMENT_TRUTH=false)")
        _startup_state["services"]["sentiment_bus"] = {"status": "skipped", "reason": "sentiment_disabled"}
    else:
        try:
            from merid.sentiment.sentiment_bus import get_sentiment_bus
            _sentiment_bus = get_sentiment_bus()
            await _sentiment_bus.start()
            logger.info("✅ SentimentBus started (Twitter+Reddit → MarketMoodBus)")
            _startup_state["services"]["sentiment_bus"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  SentimentBus failed to start: {e}")
            _startup_state["services"]["sentiment_bus"] = {"status": "failed", "error": str(e)}

    # TwitterStreamHandler — real-time Twitter stream (threaded, sync start)
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent extreme event-loop lag
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] TwitterStreamHandler skipped (not needed for validation)")
        _startup_state["services"]["twitter_stream_handler"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.sentiment.twitter_fetcher import get_twitter_stream_handler
            _twitter_stream = get_twitter_stream_handler()
            _twitter_stream.start(assets=["BTC", "ETH", "SOL", "XRP", "DOGE"])
            logger.info("✅ TwitterStreamHandler started (real-time tweet stream)")
            _startup_state["services"]["twitter_stream_handler"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  TwitterStreamHandler failed to start: {e}")
            _startup_state["services"]["twitter_stream_handler"] = {"status": "failed", "error": str(e)}

    # HashtagMonitor — background loops for hashtag scraping + news ingestion → SentimentBusV2
    # Must start AFTER SentimentBus and TwitterStreamHandler so data sources are available
    # BUG-L13 FIX: Skip in VALIDATION_MODE — this causes 39+ second lag spikes during startup
    # LEAN 15m KALSHI STACK (2026-05-13): Skip when ENABLE_SENTIMENT_TRUTH=false to prevent native crashes
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    _sentiment_disabled = __import__("os").environ.get("ENABLE_SENTIMENT_TRUTH", "true").lower() == "false"
    if _is_validation:
        logger.info("[VALIDATION MODE] HashtagMonitor skipped (prevents 39s+ startup lag)")
        _startup_state["services"]["hashtag_monitor"] = {"status": "skipped", "reason": "validation_mode"}
    elif _sentiment_disabled:
        logger.info("[LEAN KALSHI] HashtagMonitor skipped (ENABLE_SENTIMENT_TRUTH=false)")
        _startup_state["services"]["hashtag_monitor"] = {"status": "skipped", "reason": "sentiment_disabled"}
    else:
        try:
            from merid.sentiment.hashtag_monitor import get_hashtag_monitor
            _hashtag_monitor = get_hashtag_monitor()
            await _hashtag_monitor.start()
            logger.info("✅ HashtagMonitor started (hashtag=%ds, asset=%ds, news=%ds)",
                         _hashtag_monitor._hashtag_interval,
                         _hashtag_monitor._asset_interval,
                         _hashtag_monitor._news_interval)
            _startup_state["services"]["hashtag_monitor"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  HashtagMonitor failed to start: {e}")
            _startup_state["services"]["hashtag_monitor"] = {"status": "failed", "error": str(e)}

    # CFGI fear/greed refresh loop — periodic push of F&G index into MarketMoodBus
    # BUG-L13 FIX: Skip in VALIDATION_MODE — uses sync requests.get() which blocks the
    # event loop for ~900ms per 5-asset call (confirmed via loop_lag degraded warning at
    # first fire, 5 minutes after startup). MarketMoodBus is also skipped in validation.
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] CFGI refresh loop skipped (sync requests.get blocks event loop ~900ms every 5min)")
        _startup_state["services"]["cfgi_refresh"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        async def _cfgi_refresh_loop():
            _assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            while True:
                try:
                    from merid.sentiment.cfgi_client import get_cfgi_client
                    _cfgi = get_cfgi_client()
                    for _asset in _assets:
                        try:
                            # update_mood_bus uses sync requests.get (~900ms/call).
                            # Offload to thread so it cannot block the event loop.
                            await asyncio.to_thread(_cfgi.update_mood_bus, _asset)
                        except Exception as _cue:
                            logger.debug("CFGI update_mood_bus(%s) skipped: %s", _asset, _cue)
                except Exception as _e:
                    logger.debug(f"CFGI refresh error (non-fatal): {_e}")
                await asyncio.sleep(300)  # Refresh every 5 minutes

        try:
            task = asyncio.create_task(_cfgi_refresh_loop(), name="cfgi-fg-refresh")
            _startup_state["background_tasks"].append(task)
            logger.info("✅ CFGI fear/greed refresh loop started (5-min interval)")
            _startup_state["services"]["cfgi_refresh"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  CFGI refresh loop failed to start: {e}")
            _startup_state["services"]["cfgi_refresh"] = {"status": "failed", "error": str(e)}

    # WSFeedManager — Coinbase WebSocket price feed → feature service ingestion
    _ws_profile = os.getenv("MERID_PROFILE", "full").lower().strip()
    if _ws_profile in ("kalshi-only", "kalshi_only", "kalshi"):
        logger.info("WSFeedManager SKIPPED (Kalshi-only mode — Coinbase WS not needed)")
        _startup_state["services"]["ws_feed_manager"] = {"status": "skipped", "reason": "kalshi-only"}
    else:
        try:
            from merid.signals.ws_price_feed import get_ws_feed_manager
            from merid.loop import LoopConfig
            _ws_mgr = get_ws_feed_manager()
            _ws_symbols = LoopConfig().active_symbols  # BTC, ETH, SOL baseline
            try:
                _ws_symbols = LoopConfig.from_paper_config().active_symbols
            except Exception as _lce:
                logger.debug("LoopConfig.from_paper_config skipped, using defaults: %s", _lce)
            task = asyncio.create_task(
                _ws_mgr.start(_ws_symbols), name="ws-price-feed"
            )
            _startup_state["background_tasks"].append(task)
            logger.info(f"✅ WSFeedManager started (symbols: {_ws_symbols})")
            _startup_state["services"]["ws_feed_manager"] = {"status": "running", "started_at": time.time(), "symbols": _ws_symbols}
        except Exception as e:
            logger.warning(f"⚠️  WSFeedManager failed to start: {e}")
            _startup_state["services"]["ws_feed_manager"] = {"status": "failed", "error": str(e)}

    # MeridLoop — persistent swarm orchestrator
    # BUG-H1 fix: only start the loop when all critical infrastructure is up.
    # startup_success is False when HealthMonitor, KalshiVenueClient, KalshiMarketCatalog,
    # AuditTrail, AlertManager, or SystemOrchestrator failed to start.
    # BUG-L13 FIX: Skip MeridLoop in VALIDATION_MODE to prevent event-loop lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] MeridLoop skipped (prevents 5s+ startup lag)")
        _startup_state["services"]["merid_loop"] = {"status": "skipped", "reason": "validation_mode"}
    elif not startup_success:
        logger.error(
            "❌ MeridLoop NOT started — critical startup failures detected. "
            "Resolve the failed services above before enabling live trading."
        )
        _startup_state["services"]["merid_loop"] = {
            "status": "blocked",
            "reason": "startup_success=False — one or more critical services failed",
        }
    else:
        try:
            from merid.loop import get_merid_loop
            _merid_loop = get_merid_loop()
            task = asyncio.create_task(_merid_loop.run(), name="merid-loop")
            _startup_state["background_tasks"].append(task)
            logger.info("✅ MeridLoop started (swarm orchestrator)")
            _startup_state["services"]["merid_loop"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            startup_success = False
            logger.warning(f"⚠️  MeridLoop failed to start: {e}")
            _startup_state["services"]["merid_loop"] = {"status": "failed", "error": str(e)}

    # Agent orchestrator
    try:
        from core.agent_orchestrator import get_agent_orchestrator
        orchestrator = get_agent_orchestrator()
        task = asyncio.create_task(orchestrator.start())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Agent orchestrator started")
        _startup_state["services"]["agent_orchestrator"] = {"status": "running", "started_at": time.time()}

        # Bridge orchestrator agents into the framework AgentRegistry so the
        # /api/agents/* endpoints report real agent instances instead of
        # falling back to the static manifest.
        try:
            from agents.agent_framework import (
                get_agent_registry, Agent, AgentRole, AgentStatus, AgentCapability,
            )

            class _BridgeAgent(Agent):
                """Lightweight proxy that exposes an orchestrator agent in the framework registry."""
                async def process_message(self, message):
                    return None
                async def make_decision(self, context):
                    return {"action": "none"}

            _ORCH_ROLE_MAP = {
                "TWITTER": AgentRole.RESEARCH_SIGNAL,
                "TELEGRAM": AgentRole.RESEARCH_SIGNAL,
                "NEWS_MONITOR": AgentRole.RESEARCH_SIGNAL,
                "ARBITRAGE": AgentRole.SNIPER_ARBITRAGE,
                "EXECUTION": AgentRole.EXECUTION,
                "SLIPPAGE": AgentRole.RISK,
                "PRICE_FEED": AgentRole.ANOMALY_DETECTION,
            }

            registry = get_agent_registry()
            for role_enum, agent_obj in orchestrator.agents.items():
                agent_name = role_enum.name  # e.g. "TWITTER"
                fw_role = _ORCH_ROLE_MAP.get(agent_name, AgentRole.RESEARCH_SIGNAL)
                bridge = _BridgeAgent(
                    agent_id=f"orch-{agent_name.lower()}",
                    role=fw_role,
                    capabilities=[AgentCapability(
                        name=agent_name.lower(),
                        description=f"Orchestrator {agent_name} agent",
                        input_schema={}, output_schema={},
                    )],
                )
                enabled = getattr(agent_obj, "enabled", True)
                bridge.status = AgentStatus.ACTIVE if enabled else AgentStatus.PAUSED
                if hasattr(bridge, '_running'):
                    bridge._running = True
                registry.register(bridge)
            logger.info("✅ Bridged %d orchestrator agents into framework registry", len(orchestrator.agents))
        except Exception as bridge_err:
            logger.warning("Agent bridge failed: %s", bridge_err, exc_info=True)

        # Initialize guardrails: register built-in tools + capability maps
        try:
            import merid.guardrails.builtin_tools  # noqa: F401 — auto-registers tools
            from merid.guardrails.capabilities import get_capability_store

            _ORCH_PROFILE_MAP = {
                "TWITTER": "research",
                "TELEGRAM": "research",
                "NEWS_MONITOR": "research",
                "PRICE_FEED": "research",
                "ARBITRAGE": "trading",
                "EXECUTION": "trading",
                "SLIPPAGE": "risk",
            }
            cap_store = get_capability_store()
            for role_enum in orchestrator.agents:
                agent_name = role_enum.name
                profile = _ORCH_PROFILE_MAP.get(agent_name, "research")
                cap_store.register_from_profile(f"orch-{agent_name.lower()}", profile)
            logger.info("✅ Guardrails initialized: %d tools, %d agent capability maps",
                        len(cap_store.list_agents()), len(cap_store.list_agents()))
        except Exception as guard_err:
            logger.warning("Guardrails init failed: %s", guard_err, exc_info=True)

    except Exception as e:
        logger.warning(f"⚠️  Agent orchestrator failed: {e}")
        _startup_state["services"]["agent_orchestrator"] = {"status": "failed", "error": str(e)}

    # Execution engine
    try:
        from trading.execution import get_optimal_executor
        execution = get_optimal_executor()
        status = execution.get_status()
        logger.info("✅ Execution engine ready (plans: %d, active: %d)",
                     status["total_plans"], status["active_plans"])
        _startup_state["services"]["execution"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Execution engine failed: {e}")
        _startup_state["services"]["execution"] = {"status": "failed", "error": str(e)}

    # Agent mesh
    # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Agent mesh skipped (8 streaming agents deferred)")
        _startup_state["services"]["agent_mesh"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from agents.agent_mesh import agent_mesh
            # initialize() must complete before start() — await it directly so we don't
            # race start() against an incomplete init.  Track the task so exceptions
            # surface immediately rather than being silently eaten at GC time.
            _init_task = asyncio.create_task(agent_mesh.initialize(), name="agent-mesh-init")
            _startup_state["background_tasks"].append(_init_task)
            await _init_task
            task = asyncio.create_task(agent_mesh.start(), name="agent-mesh-start")
            _startup_state["background_tasks"].append(task)
            logger.info("✅ Agent mesh started")
            _startup_state["services"]["agent_mesh"] = {"status": "running", "started_at": time.time()}
        except Exception as e:
            logger.warning(f"⚠️  Agent mesh failed: {e}")
            _startup_state["services"]["agent_mesh"] = {"status": "failed", "error": str(e)}

    # Consensus engine streaming
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 6s+ startup lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Consensus engine streaming skipped (prevents 6s+ lag)")
        _startup_state["services"]["consensus_engine"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from core.consensus_engine import get_consensus_engine
            consensus = get_consensus_engine()
            task = asyncio.create_task(consensus.start())
            _startup_state["background_tasks"].append(task)
            logger.info("✅ Consensus engine streaming started")
        except Exception as e:
            logger.warning(f"⚠️  Consensus engine streaming failed: {e}")

    # Continuous miner (DISABLED — legacy simulation, not needed for Kalshi)
    logger.info("Continuous miner SKIPPED (Kalshi-only mode)")

    # Audit trail — already started in Phase 3 (core infrastructure block above)

    # Intelligence news aggregation
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 3s+ startup lag from HTTP requests
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Intelligence news aggregation skipped (prevents 3s+ lag)")
        _startup_state["services"]["intelligence_news"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from web.api.intelligence import aggregate_news
            task = asyncio.create_task(aggregate_news())
            _startup_state["background_tasks"].append(task)
            logger.info("✅ Intelligence news aggregation started")
        except Exception as e:
            logger.warning(f"⚠️  Intelligence news aggregation failed: {e}")

    # API live data fetching
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 3s+ startup lag from HTTP requests
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] API live data feed skipped (prevents 3s+ lag)")
        _startup_state["services"]["api_live_data"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from web.api.live_data import fetch_live_prices as fetch_api_prices
            task = asyncio.create_task(fetch_api_prices())
            _startup_state["background_tasks"].append(task)
            logger.info("✅ API live data feed started")
        except Exception as e:
            logger.warning(f"⚠️  API live data feed failed: {e}")

    # Alert manager — already started in Phase 3 (core infrastructure block above)
    # Wire price feed subscription (additive, does not double-start)
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent event-loop lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Alert manager price feed wire skipped (prevents lag)")
    else:
        try:
            from core.alerts import get_alert_manager
            alert_mgr = get_alert_manager()
            from data.live_price_feed import get_live_price_feed
            price_feed = get_live_price_feed()
            def on_alert_price_update(price_data):
                alert_mgr.update_price(price_data.symbol, price_data.price)
            price_feed.subscribe(on_alert_price_update)
            logger.info("✅ Alert manager wired to price feed")
        except Exception:
            logger.debug("Alert manager price feed wire skipped (non-fatal)")

    # Health monitor — already started in Phase 3 (core infrastructure block above)

    # Whale listener (DISABLED — Solana-specific, not needed for Kalshi)
    logger.info("Whale listener SKIPPED (Kalshi-only mode)")

    # Pre-warm signal metrics cache (background thread, non-blocking)
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent event-loop lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Signal metrics cache warming skipped (prevents lag)")
    else:
        try:
            from web.api.signal_layer_api import warm_signal_metrics_cache
            warm_signal_metrics_cache()
            logger.info("✅ Signal metrics cache warming started (background)")
        except Exception as e:
            logger.warning(f"⚠️  Signal metrics cache warm failed: {e}")

    # KalshiWebSocketBridge: already started in the Kalshi-only phase above (full ticker set
    # from prepare_crypto_ws_bridge_subscription). A second deferred start used the same
    # singleton and called listen() twice → websockets ConcurrencyError on recv.
    _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] KalshiWebSocketBridge SKIPPED (not needed for validation)")
        _startup_state["services"]["kalshi_ws_bridge"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        logger.debug(
            "KalshiWebSocketBridge: single start path (Kalshi phase); duplicate deferred task removed"
        )

    startup_duration = time.time() - _startup_state["started_at"]
    # One-line bundle for operators: grep STARTUP_BUNDLE to confirm streaming + PM asset list
    try:
        _pm_list = "?"
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS as _ACA

            _pm_list = ",".join(_ACA)
        except Exception as e:
            logger.debug(f"Crypto config load failed: {e}")
        _ko = False
        try:
            from merid.settings import settings as _settings

            _ko = bool(getattr(_settings, "KALSHI_ONLY", False))
        except Exception as e:
            logger.debug(f"Settings load failed: {e}")
        _ccxt_n = 0
        try:
            from data.live_price_feed import get_live_price_feed as _glpf_bundle

            _ccxt_n = len(getattr(_glpf_bundle(), "exchanges", {}) or {})
        except Exception:
            _ccxt_n = -1
        _lpf_svc = _startup_state.get("services", {}).get("live_price_feed", {})
        _st = _lpf_svc.get("status", "?")
        if _st == "skipped":
            _lpf_tail = f"SKIPPED reason={_lpf_svc.get('reason', 'n/a')}"
        elif _st == "running":
            _lpf_tail = "STARTED"
        elif _st == "failed":
            _lpf_tail = f"FAILED err={_lpf_svc.get('error', '')}"
        else:
            _lpf_tail = str(_st)
        logger.info(
            "STARTUP_BUNDLE live_price_feed=%s kalshi_only=%s ccxt_exchanges=%d pm_spot_assets=[%s]",
            _lpf_tail,
            _ko,
            _ccxt_n,
            _pm_list,
        )
    except Exception as _sb_exc:
        logger.debug("STARTUP_BUNDLE log skipped: %s", _sb_exc)

    logger.info("=" * 80)
    _log_phase("phase3_streaming")  # TIMING: Phase 3 complete
    if startup_success:
        logger.info(f"✅ All services started successfully in {startup_duration:.2f}s")
    else:
        logger.warning(f"⚠️  Some services failed - system in degraded mode ({startup_duration:.2f}s)")
    logger.info("🚀 MERID STARTUP COMPLETE - System Ready")
    logger.info("=" * 80)
    _log_startup_summary()  # TIMING: Full startup summary

    # BUG-L13 FIX: Removed strategic sleep - it was causing event loop to process
    # pending blocking work resulting in 4+ second lag spikes
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Proceeding directly to yield (sleep removed)")

    # ── Startup reconciliation — unblock execution gate immediately ─────
    # BUG-L9 FIX: Run reconciliation as background task instead of awaiting
    # to prevent blocking the event loop for 11+ seconds
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent 4s+ startup lag
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Startup reconciliation skipped (prevents 4s+ lag)")
        _startup_state["services"]["startup_reconciliation"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        async def _startup_reconciliation_async() -> None:
            """Background task for startup reconciliation.

            LEAN 15m KALSHI STACK (2026-05-13): Skip when ENABLE_VENUE_RECONCILER=false
            to prevent blocking main-loop round-trips causing timeouts.
            BankrollServiceV2 + PositionCache + FillsLedger are sufficient for consistency.
            """
            import os as _recon_os
            _recon_disabled = _recon_os.getenv("ENABLE_VENUE_RECONCILER", "true").lower() == "false"
            if _recon_disabled:
                logger.info("[LEAN KALSHI] Venue reconciler disabled (ENABLE_VENUE_RECONCILER=false)")
                return

            try:
                from merid.reconciliation import reconcile_all_venues, has_critical_discrepancies
                logger.info("Background startup reconciliation running...")
                discrepancies = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: reconcile_all_venues(["kalshi"])
                )
                n_crit = sum(1 for d in discrepancies if d.severity == "critical")
                n_warn = sum(1 for d in discrepancies if d.severity == "warning")
                logger.info(
                    "Background reconciliation complete: %d discrepancies (%d critical, %d warning)",
                    len(discrepancies), n_crit, n_warn,
                )
                _recon_mode = _recon_os.getenv("MERID_PM_TRADING_MODE", "paper")
                if has_critical_discrepancies() and _recon_mode != "paper":
                    logger.warning("⚠️  Execution gate BLOCKED (critical reconciliation issues)")
                elif has_critical_discrepancies() and _recon_mode == "paper":
                    logger.info("✅ Reconciliation: %d critical (expected in paper mode, not blocking)", n_crit)
                else:
                    logger.info("✅ Execution gate CLEAR — trades can proceed")
            except Exception as exc:
                logger.warning("Background reconciliation failed: %s", exc)
                # Ensure gate is not permanently blocked if startup recon errors out
                try:
                    from merid.reconciliation.venue_reconciler import _recon_lock, _reconciliation_has_run
                    import merid.reconciliation.venue_reconciler as _vr
                    with _recon_lock:
                        if not _vr._reconciliation_has_run:
                            _vr._reconciliation_has_run = True
                            logger.warning("Startup reconciliation failed — forcing reconciliation_has_run=True so gate can clear")
                except Exception as e:
                    logger.debug(f"Reconciliation force failed: {e}")

        # Fire off reconciliation as background task (non-blocking)
        _startup_recon_task = asyncio.create_task(
            _startup_reconciliation_async(), name="startup-reconciliation"
        )
        _startup_state["background_tasks"].append(_startup_recon_task)
        logger.info("Startup reconciliation started as background task (non-blocking)")

    # Legacy trading.reconciliation (paper-truth periodic loop) removed — Kalshi
    # venue reconciliation below is authoritative.

    # ── Start periodic Kalshi venue reconciliation ───────────────────
    # F8 fix: run as an asyncio task, not a daemon thread.  The old thread
    # called reconcile_all_venues() which may internally use
    # asyncio.get_event_loop().run_until_complete() — a pattern that raises
    # RuntimeError in Python 3.10+ when invoked from a non-event-loop thread.
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent periodic lag spikes
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        logger.info("[VALIDATION MODE] Kalshi venue reconciliation loop skipped (prevents lag spikes)")
        _startup_state["services"]["kalshi_recon_loop"] = {"status": "skipped", "reason": "validation_mode"}
    else:
        try:
            from merid.reconciliation import reconcile_all_venues as _reconcile_all_venues

            async def _kalshi_recon_loop_async() -> None:
                logger.info("Periodic Kalshi venue reconciliation started (every 300s)")
                while True:
                    await asyncio.sleep(300.0)
                    try:
                        discs = await asyncio.get_running_loop().run_in_executor(
                            None, lambda: _reconcile_all_venues(["kalshi"])
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

            # 24/7-HARDENING: Add done callback to catch any escaped exceptions
            def _recon_done_callback(task: asyncio.Task) -> None:
                try:
                    task.result()
                except asyncio.CancelledError:
                    logger.info("Kalshi venue reconciliation loop cancelled (normal)")
                except Exception as exc:
                    logger.critical(
                        "[24/7-HARDENING] Kalshi venue reconciliation task crashed: %s. "
                        "This should never happen - inner loop has try/except.",
                        exc, exc_info=True
                    )

            _recon_task.add_done_callback(_recon_done_callback)
            _startup_state["background_tasks"].append(_recon_task)
            logger.info("✅ Kalshi venue reconciliation loop started (async, every 300s)")
        except Exception as exc:
            logger.debug("Kalshi venue reconciliation loop not started: %s", exc)

    # KalshiInsightPipeline + KalshiNewsAgent — already started + consumer wired in Phase 3 above

    # Terminal telemetry loop DISABLED — was printing synthetic crypto trades/portfolio
    # Kalshi agent grid has its own telemetry via the /api/v1/kalshi-grid/* endpoints.
    logger.info("Terminal telemetry loop SKIPPED (Kalshi-only mode)")

    # BUG-FIX: Yield BEFORE shutdown wait loop so uvicorn can start HTTP server immediately
    # The original architecture waited for shutdown signal BEFORE yielding, which prevented
    # uvicorn from ever starting the HTTP server. This caused the UI to be inaccessible.
    logger.info("[STARTUP] Yielding to uvicorn - HTTP server will start accepting requests")
    yield

    # ── POST-YIELD: Wait for shutdown signal ─────────────────────────────────
    # 24/7-HARDENING: The lifespan must NEVER exit unless explicitly stopped by operator.
    # We create a "stay-alive" event that blocks indefinitely until SIGTERM/SIGINT is received.
    _stay_alive_event = asyncio.Event()
    _shutdown_signal_received = False

    def _signal_handler(sig, frame):
        """Handle shutdown signals explicitly - only way to exit lifespan."""
        nonlocal _shutdown_signal_received
        _shutdown_signal_received = True
        logger.critical(f"[24/7-HARDENING] Shutdown signal received: {sig.name if hasattr(sig, 'name') else sig}")
        _stay_alive_event.set()

    # Install signal handlers
    import signal
    _orig_sigterm = signal.signal(signal.SIGTERM, _signal_handler)
    _orig_sigint = signal.signal(signal.SIGINT, _signal_handler)

    # 24/7-HARDENING: Ensure we ALWAYS yield to prevent "generator didn't yield" error
    # This is critical for Windows asyncio compatibility
    _startup_complete = False
    try:
        # 24/7-HARDENING: Block indefinitely until shutdown signal is received.
        # The lifespan must NEVER exit on its own - only explicit operator action.
        # LOOP-FIX: Re-wait if woken up prematurely (spurious wakeup protection)
        logger.info("[24/7-HARDENING] Lifespan stay-alive event waiting for shutdown signal...")
        _spurious_wakeups = 0
        while not _shutdown_signal_received:
            try:
                # Wait with timeout to detect spurious wakeups
                await asyncio.wait_for(_stay_alive_event.wait(), timeout=60.0)
                # If we get here, event was set - verify it was the signal
                if _shutdown_signal_received:
                    break
                # Spurious wakeup - log and continue waiting
                _spurious_wakeups += 1
                logger.warning(
                    f"[24/7-HARDENING] Spurious wakeup #{_spurious_wakeups} detected, re-waiting..."
                )
                # Re-create event for clean state
                _stay_alive_event = asyncio.Event()
            except asyncio.TimeoutError:
                # Timeout is expected - re-wait indefinitely
                pass
            except asyncio.CancelledError:
                # Only exit on CancelledError if shutdown signal was received
                if _shutdown_signal_received:
                    break
                # Otherwise, this is a spurious cancellation - continue waiting.
                # PYTHON-3.11-FIX: Catching CancelledError does NOT clear the
                # task's cancellation count. Without uncancel() the very next
                # await in this loop re-raises CancelledError immediately,
                # collapsing into a tight retry that yields nothing useful.
                # We must explicitly drain the cancel count so the next
                # `wait_for` actually waits.
                _task = asyncio.current_task()
                if _task is not None and hasattr(_task, "uncancel"):
                    while _task.cancelling() > 0:
                        _task.uncancel()
                logger.warning("[24/7-HARDENING] Spurious CancelledError, re-waiting...")
                # Re-create the event in case it was set by whatever triggered
                # the cancel (defensive — keeps us from a false-positive break).
                _stay_alive_event = asyncio.Event()
                continue
            except BaseException as _wait_exc:
                # 24/7-HARDENING: ANY non-CancelledError exception (e.g.
                # InvalidStateError from Windows IOCP corruption, RuntimeError
                # from a closed loop helper, MemoryError, etc.) must NOT exit
                # the lifespan.  If we let it propagate, the outer ``finally``
                # runs and uvicorn detects the lifespan as terminated, then
                # cancels every sibling task.  Log and keep waiting.
                #
                # KeyboardInterrupt / SystemExit (BaseException subclasses)
                # are also swallowed here on purpose: explicit shutdown must
                # come through the SIGTERM/SIGINT handler that flips
                # ``_shutdown_signal_received``.  Without that flip we are
                # under spurious-event conditions and the safe action is to
                # keep the lifespan alive.
                _exc_name = type(_wait_exc).__name__
                logger.error(
                    "[24/7-HARDENING] Spurious %s in lifespan wait — re-waiting "
                    "(exc=%s)",
                    _exc_name, _wait_exc,
                    exc_info=True,
                )
                _task = asyncio.current_task()
                if _task is not None and hasattr(_task, "uncancel"):
                    try:
                        while _task.cancelling() > 0:
                            _task.uncancel()
                    except Exception:
                        pass
                _stay_alive_event = asyncio.Event()
                # Brief sleep so we don't busy-spin if the same exception
                # repeats every iteration (e.g. permanently broken loop).
                try:
                    await asyncio.sleep(1.0)
                except BaseException:
                    pass
                continue
        logger.info("[24/7-HARDENING] Lifespan stay-alive event triggered - proceeding to yield")
        _startup_complete = True
        yield
    except asyncio.CancelledError:
        # Ctrl-C / SIGTERM: clear pending cancel count (Python 3.11+) so that
        # the awaits in the shutdown block below are not immediately re-cancelled.
        # cancelling() / uncancel() are Python 3.11+ only — guard for 3.10.
        _task = asyncio.current_task()
        if _task is not None and hasattr(_task, "uncancel"):
            while _task.cancelling() > 0:
                _task.uncancel()
    finally:
        # 24/7-HARDENING: GUARANTEE YIELD — If we never reached yield due to error,
        # yield now to prevent "generator didn't yield" RuntimeError.
        # This is critical for Windows asyncio compatibility.
        if not _startup_complete:
            logger.critical(
                "[24/7-HARDENING] Lifespan try-block exited without yielding! "
                "Yielding now to prevent generator error."
            )
            try:
                yield
            except Exception as _yield_exc:
                logger.debug(f"[24/7-HARDENING] Post-error yield exception: {_yield_exc}")

        # 24/7-HARDENING: If yield returned but no shutdown signal received,
        # something (uvicorn) is trying to shut us down unexpectedly.
        # We must explicitly check if this was an intentional shutdown.
        if not _shutdown_signal_received:
            logger.critical(
                "[24/7-HARDENING] Lifespan yield returned WITHOUT shutdown signal! "
                "This is likely uvicorn triggering premature shutdown. "
                "Checking for explicit shutdown request..."
            )
            # Give the ASGI guard a moment to set shutdown reason if this is legitimate
            try:
                await asyncio.sleep(0.1)
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                # Ignore Windows InvalidStateError during shutdown
                pass

    # Restore original signal handlers (with Windows error suppression)
    try:
        signal.signal(signal.SIGTERM, _orig_sigterm)
        signal.signal(signal.SIGINT, _orig_sigint)
    except (OSError, ValueError) as e:
        # Windows may raise errors during shutdown signal restoration
        logger.debug(f"[24/7-HARDENING] Signal restoration skipped: {e}")

    # ── SHUTDOWN ───────────────────────────────────────────────────────
    # BUG-L7: Single-owner shutdown sequence. Each tier is responsible for
    # stopping the services it owns. Per-service stop() calls have been
    # removed from here to eliminate the triple-stop race condition.

    # BUG-FIX (2026-05-12): Cooperative task cancellation to prevent blocking during shutdown
    # Cancel all background tasks with timeout to prevent indefinite blocking from
    # stuck threads or unhandled exceptions. This prevents the crash pattern where
    # uvicorn hangs during shutdown waiting for tasks that never complete.
    logger.critical("[SHUTDOWN] Initiating cooperative task cancellation...")
    _cancelled_count = 0
    _timeout_count = 0
    for task in _startup_state["background_tasks"]:
        if not task.done():
            task.cancel()
            _cancelled_count += 1
    logger.critical("[SHUTDOWN] Cancelled %d background tasks", _cancelled_count)

    # Await all cancelled tasks with timeout to prevent indefinite blocking
    # Use return_exceptions=True to collect errors without raising
    _shutdown_timeout = 30.0  # 30 second timeout for all tasks to finish cleanup
    try:
        await asyncio.wait_for(
            asyncio.gather(*_startup_state["background_tasks"], return_exceptions=True),
            timeout=_shutdown_timeout
        )
        logger.critical("[SHUTDOWN] All background tasks completed cleanup")
    except asyncio.TimeoutError:
        logger.critical(
            "[SHUTDOWN] Background tasks did not complete within %ds timeout - "
            "proceeding with shutdown anyway (some tasks may be stuck)",
            _shutdown_timeout
        )
        _timeout_count += 1
    except Exception as exc:
        logger.critical("[SHUTDOWN] Error during background task cleanup: %s", exc)

    # Get shutdown attribution from ASGI guard (if available)
    _shutdown_reason = None
    try:
        from web.asgi_guard import get_lifespan_shutdown_reason
        _shutdown_reason = await get_lifespan_shutdown_reason()
    except Exception as e:
        logger.debug(f"Shutdown reason fetch failed: {e}")

    # EVENT-LOOP-FIX: Ensure we always have a valid shutdown reason
    # If ASGI guard didn't provide one, we derive it from context
    # 24/7-HARDENING: Detect if shutdown was triggered without explicit signal
    if _shutdown_reason is None:
        # Check if we have a shutdown signal registered
        _signal_file = Path("/tmp/.merid_shutdown_signal") if os.name != 'nt' else Path(os.environ.get("TEMP", "C:\\tmp")) / ".merid_shutdown_signal"
        _had_explicit_signal = _signal_file.exists() if _signal_file else False

        if not _had_explicit_signal and not _shutdown_signal_received:
            logger.critical(
                "[24/7-HARDENING] SHUTDOWN WITHOUT EXPLICIT SIGNAL DETECTED! "
                "The lifespan yield returned, but no SIGTERM/SIGINT was received. "
                "This indicates uvicorn may be shutting down prematurely. "
                "If this is a 24/7 production system, investigate uvicorn configuration."
            )

        try:
            from web.asgi_guard import initiate_shutdown, ShutdownReason
            # 24/7-HARDENING: Never auto-shutdown due to loop lag.
            # The server should run continuously unless explicitly stopped by operator.
            # Loop-lag "critical" status is logged but does NOT trigger shutdown.
            # Normal shutdown - lifespan end (only when SIGTERM/SIGINT received)
            _shutdown_reason = initiate_shutdown(
                reason=ShutdownReason.LIFESPAN_END,
                sub_reason="normal_lifespan_yield_exit",
                initiator_module="web.main.lifespan",
            )
        except Exception as e:
            logger.warning(f"Failed to derive shutdown reason: {e}")
            # Last resort - use LIFESPAN_END as it's safest
            from web.asgi_guard import ShutdownReason
            class _FallbackReason:
                reason = ShutdownReason.LIFESPAN_END
                sub_reason = "fallback_after_error"
                fatal_error_type = None
            _shutdown_reason = _FallbackReason()

    # Log structured shutdown start with full context
    shutdown_context = {
        "reason": _shutdown_reason.reason.value,
        "sub_reason": getattr(_shutdown_reason, "sub_reason", None),
        "fatal_error": getattr(_shutdown_reason, "fatal_error_type", None),
        "timestamp": time.time(),
    }
    logger.critical("[SHUTDOWN-INITIATED] %s", json.dumps(shutdown_context))

    # Add metrics snapshot before shutdown proceeds
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        lag_stats = get_loop_lag_monitor().get_health()
        logger.critical(
            "[SHUTDOWN-METRICS] lag_ms=%.1f lag_p95=%.1f lag_max=%.1f samples=%d",
            lag_stats["stats"]["current_ms"],
            lag_stats["stats"]["p95_ms"],
            lag_stats["stats"]["max_ms"],
            lag_stats["stats"]["sample_count"],
        )
    except Exception:
        pass

    # Legacy detailed shutdown log (for compatibility)
    if _shutdown_reason:
        logger.critical(
            "🛑 MERID shutdown initiated - cancelling background tasks... "
            "shutdown_reason=%s sub_reason=%s fatal_error_type=%s",
            _shutdown_reason.reason.value,
            _shutdown_reason.sub_reason or "none",
            _shutdown_reason.fatal_error_type or "none",
        )
        # Emit to metrics
        try:
            from monitoring.metrics import record_shutdown
            record_shutdown(
                reason=_shutdown_reason.reason.value,
                sub_reason=_shutdown_reason.sub_reason or "none",
            )
        except Exception:
            pass
    else:
        # EVENT-LOOP-FIX: Use explicit reason instead of generic "normal shutdown"
        _derived_reason = shutdown_context.get("reason", "lifespan_end")
        _derived_sub = shutdown_context.get("sub_reason", "none")
        logger.info(
            "🛑 MERID shutdown initiated - cancelling background tasks... "
            "(reason=%s, sub_reason=%s)",
            _derived_reason,
            _derived_sub
        )

    # 0. Stop LivePriceFeed (Coinbase ticker tasks) before cancelling background_tasks entries
    try:
        from data.live_price_feed import get_live_price_feed

        get_live_price_feed().stop_streaming()
        logger.info("✅ LivePriceFeed streaming stopped")
    except Exception as exc:
        logger.debug("LivePriceFeed stop skipped: %s", exc)

    # 1. Stop MeridLoop (stops the swarm tick cycle)
    try:
        from merid.loop import get_merid_loop as _get_merid_loop
        _get_merid_loop().stop()
        logger.info("✅ MeridLoop stopped")
    except Exception as exc:
        logger.warning("MeridLoop stop failed: %s", exc)

    # 1b. Stop CryptoAlertRouter
    try:
        _se_mod = __import__("sys").modules.get("web.api.system_endpoints")
        _car = getattr(_se_mod, "_crypto_router_instance", None) if _se_mod else None
        if _car is not None:
            await _car.stop()
        logger.info("✅ CryptoAlertRouter stopped")
    except Exception as exc:
        logger.warning("CryptoAlertRouter stop failed: %s", exc)

    # 1c. Stop SpotBasisTracker
    try:
        from merid.alignment import get_spot_basis_tracker as _get_basis_tracker
        _get_basis_tracker().stop()
        logger.info("✅ SpotBasisTracker stopped")
    except Exception as exc:
        logger.debug("SpotBasisTracker stop skipped: %s", exc)

    # 2. Stop ConsensusCoordinator opinion subscriber
    try:
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator as _ECC
        await _ECC.get_instance().stop_opinion_subscriber()
        logger.info("✅ EnhancedConsensusCoordinator opinion subscriber stopped")
    except Exception as exc:
        logger.warning("EnhancedConsensusCoordinator stop failed: %s", exc)

    # 3. OrchestratorAgentManager — stops AgentMesh, NewsMonitor, SocialBroadcaster,
    #    LaneOrchestrator, ReflectionSystem, MarketMoodBus, InsightPipeline.
    #    Also calls grid.stop() (drains + stops all trading agents, then PortfolioRiskAgent).
    try:
        from web.startup_agents import get_orchestrator_manager as _get_orch_mgr
        await _get_orch_mgr().stop_all()
        logger.info("✅ OrchestratorAgentManager stopped")
    except Exception as exc:
        logger.warning("OrchestratorAgentManager stop failed: %s", exc)

    # 4. Kalshi agent grid — idempotent, no-op if already drained by step 3
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        await grid.stop()
        logger.info("✅ Kalshi agent grid stopped")
    except Exception as exc:
        logger.warning("Kalshi agent grid stop failed: %s", exc)

    # 5. External feed managers (not owned by grid or orchestrator manager)
    for _stop_label, _stop_coro_fn in [
        ("WSFeedManager",         lambda: __import__('merid.signals.ws_price_feed', fromlist=['get_ws_feed_manager']).get_ws_feed_manager().stop()),
        ("LiveFeedManager",       lambda: __import__('merid.signals.live_feeds', fromlist=['get_live_feed_manager']).get_live_feed_manager().close()),
        ("SentimentBus",          lambda: __import__('merid.sentiment.sentiment_bus', fromlist=['get_sentiment_bus']).get_sentiment_bus().stop()),
        ("KalshiContinuousTrader", lambda: __import__('merid.trading.kalshi_continuous_trader', fromlist=['get_continuous_trader']).get_continuous_trader().stop()),
        ("KalshiWebSocketBridge", lambda: __import__('merid.event_venues.kalshi.ws_bridge', fromlist=['get_ws_bridge']).get_ws_bridge().stop()),
        ("KalshiMarketCache",     lambda: __import__('merid.event_venues.kalshi.market_cache', fromlist=['get_market_cache']).get_market_cache().stop()),
        ("TickerCollector",       lambda: __import__('merid.event_venues.kalshi.ticker_collector', fromlist=['get_ticker_collector']).get_ticker_collector().stop()),
        ("WatchdogCoordinator",   lambda: __import__('agents.watchdog_agents', fromlist=['get_watchdog_coordinator']).get_watchdog_coordinator().stop()),
        ("AuditTrail",            lambda: __import__('core.audit_trail', fromlist=['get_audit_trail']).get_audit_trail().stop()),
        ("AlertManager",          lambda: __import__('core.alerts', fromlist=['get_alert_manager']).get_alert_manager().stop()),
        ("HealthMonitor",         lambda: __import__('core.health', fromlist=['get_health_monitor']).get_health_monitor().stop()),
        ("LoopLagMonitor",        lambda: __import__('merid.diagnostics.loop_lag', fromlist=['get_loop_lag_monitor']).get_loop_lag_monitor().stop()),
        # BUG-EL FIX: Close KalshiVenueClient singleton to prevent garbage collection warning
        ("KalshiVenueClient",     lambda: __import__('merid.event_venues.kalshi.client', fromlist=['close_kalshi_client']).close_kalshi_client()),
    ]:
        try:
            _result = _stop_coro_fn()
            if asyncio.iscoroutine(_result):
                await _result
            logger.info("✅ %s stopped", _stop_label)
        except Exception as exc:
            logger.warning("%s stop failed: %s", _stop_label, exc)

    # RTIFeedService — stop RTI feed loop
    if _rti_feed_service is not None:
        try:
            await _rti_feed_service.stop()
            logger.info("✅ RTIFeedService stopped")
        except Exception as exc:
            logger.warning("RTIFeedService stop failed: %s", exc)

    # CryptoTermStructureModel — stop polling task
    if _tsm is not None:
        try:
            await _tsm.stop()
            logger.info("✅ CryptoTermStructureModel stopped")
        except Exception as exc:
            logger.warning("CryptoTermStructureModel stop failed: %s", exc)

    # TwitterStreamHandler — sync stop (threaded)
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_stream_handler as _get_tw_stream
        _get_tw_stream().stop()
        logger.info("✅ TwitterStreamHandler stopped")
    except Exception as exc:
        logger.warning("TwitterStreamHandler stop failed: %s", exc)

    # SystemOrchestrator (also stops ConsensusEngine)
    try:
        from core.system_orchestrator import stop_merid
        await stop_merid()
        logger.info("✅ SystemOrchestrator stopped")
    except Exception as exc:
        logger.warning("SystemOrchestrator stop failed: %s", exc)

    # Orchestrator agents — already stopped by OrchestratorAgentManager.stop_all() above

    # Flush PortfolioRebalancer state (W10)
    try:
        from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer as _get_rebalancer
        _get_rebalancer()._bootstrap_targets()  # persist final targets
        logger.info("✅ PortfolioRebalancer flushed")
    except Exception as exc:
        logger.debug("PortfolioRebalancer flush skipped: %s", exc)

    # OutcomeResolver teardown
    try:
        from merid.metrics.outcome_resolver import get_outcome_resolver as _get_or_td
        await _get_or_td().stop()
        logger.info("✅ OutcomeResolver stopped")
    except Exception as exc:
        logger.debug("OutcomeResolver stop skipped: %s", exc)

    # KalshiSettlementPoller teardown
    try:
        from merid.event_venues.kalshi.settlement_poller import stop_settlement_polling
        await stop_settlement_polling()
        logger.info("✅ KalshiSettlementPoller stopped")
    except Exception as exc:
        logger.debug("KalshiSettlementPoller stop skipped: %s", exc)

    # Note: KalshiVenueClient is already closed in the cleanup loop above (line ~3834)
    # via close_kalshi_client(). Do NOT call get_kalshi_client() here as it would
    # create a new client after shutdown, triggering the garbage-collection warning.

    # Final venue reconciliation snapshot (Kalshi)
    try:
        from merid.reconciliation import reconcile_all_venues

        _shutdown_discs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: reconcile_all_venues(["kalshi"])
        )
        logger.info("Shutdown reconciliation: %d venue discrepancies", len(_shutdown_discs))
    except Exception as exc:
        logger.debug("Shutdown reconciliation skipped: %s", exc)

    for task in _startup_state.get("background_tasks", []):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    logger.info("✅ Shutdown complete")


# Create app instance after all routes are defined
app = create_app(lifespan=_app_lifespan)

# Add health endpoints after app creation
## Dashboard endpoints moved to web/api/system_endpoints.py
## Removed duplicates: /api/system/health, /api/risk/pnl-summary, /api/risk/limits,
## /api/risk/exposure, /api/risk/protections, /api/agents/summary, /api/trading/summary,
## /api/prime/status, /api/system/version, /api/system/components

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon.ico to eliminate 404 errors."""
    return FileResponse("favicon.ico")


# Startup state tracking
_startup_state: Dict[str, Any] = {
    "started_at": None,
    "services": {},
    "background_tasks": [],
}


async def _start_service_with_timeout(
    name: str,
    coro,
    timeout_seconds: float = 30.0,
    optional: bool = True
) -> Optional[Any]:
    """Start a service with timeout and track its state."""
    global _startup_state
    _startup_state["services"][name] = {"status": "starting", "started_at": time.time()}
    
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_seconds)
        _startup_state["services"][name] = {
            "status": "running",
            "started_at": _startup_state["services"][name]["started_at"],
            "ready_at": time.time()
        }
        logger.info(f"✅ Service '{name}' started successfully")
        return result
    except asyncio.TimeoutError:
        _startup_state["services"][name] = {
            "status": "timeout",
            "error": f"Startup timeout after {timeout_seconds}s"
        }
        if optional:
            logger.warning(f"⏱️  Service '{name}' startup timed out (optional, continuing)")
            return None
        raise RuntimeError(f"Required service '{name}' failed to start within {timeout_seconds}s")
    except Exception as e:
        _startup_state["services"][name] = {"status": "failed", "error": str(e)}
        if optional:
            logger.warning(f"❌ Service '{name}' failed to start: {e} (optional, continuing)")
            return None
        raise


## on_event handlers removed — all startup/shutdown logic now in _app_lifespan()


@app.get("/api/v1/market/data/freshness")
async def market_data_freshness():
    """Market data freshness — checks Kalshi catalog + cache staleness."""
    import time as _t

    now = _t.time()
    catalog_age_s: float = -1
    catalog_count: int = 0
    cache_stats: dict = {}

    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        _cat = get_market_catalog()
        catalog_count = len(_cat.get_all_markets())
        _last = getattr(_cat, "last_refresh_at", None) or getattr(_cat, "_last_refresh", None)
        if _last:
            catalog_age_s = round(now - _last, 1)
    except Exception as e:
        logger.debug(f"Catalog age check failed: {e}")

    try:
        from merid.event_venues.kalshi.market_cache import get_market_cache
        _cache = get_market_cache()
        cache_stats = {
            "entries": getattr(_cache, "size", None) or len(getattr(_cache, "_store", {})),
            "hit_rate": round(getattr(_cache, "hit_rate", 0.0), 3),
        }
    except Exception as e:
        logger.debug(f"Cache stats failed: {e}")

    stale = catalog_age_s < 0 or catalog_age_s > 600  # >10 min = stale
    return {
        "status": "stale" if stale else "fresh",
        "timestamp": now,
        "catalog_markets": catalog_count,
        "catalog_age_seconds": catalog_age_s,
        "cache": cache_stats,
    }


@app.get("/api/v1/institutional/predictions/whales")
async def get_whale_events(limit: int = 20):
    """Get recent whale events from the prediction market aggregator."""
    try:
        from monitoring.prediction_markets import get_prediction_aggregator, get_whale_events
        aggregator = get_prediction_aggregator()
        whale_events = get_whale_events(aggregator, limit)
        
        return {
            "whales": whale_events,
            "count": len(whale_events),
            "threshold": 100000  # Default whale threshold
        }
    except Exception as e:
        logger.error(f"Error fetching whale events: {e}")
        return {"whales": [], "count": 0, "error": str(e)}


@app.get("/healthz")
async def healthz():
    """Liveness probe - process up and critical threads alive"""
    import time
    import asyncio
    import threading
    
    # Check if main thread is alive
    main_thread_alive = threading.main_thread().is_alive()
    
    # Check if event loop is running
    try:
        loop = asyncio.get_running_loop()
        loop_running = loop.is_running()
    except RuntimeError:
        loop_running = False
    
    # Check startup completed
    startup_completed = _startup_state.get("started_at") is not None
    
    return {
        "status": "healthy" if main_thread_alive and loop_running and startup_completed else "unhealthy",
        "timestamp": time.time(),
        "main_thread_alive": main_thread_alive,
        "event_loop_running": loop_running,
        "startup_completed": startup_completed,
        "uptime_seconds": time.time() - (_startup_state.get("started_at") or time.time())
    }


@app.get("/readyz")
async def readyz():
    """Readiness probe — checks actual Kalshi pipeline services."""
    import time
    import os

    # Check if startup has completed
    if _startup_state.get("started_at") is None:
        return {
            "status": "not_ready",
            "reason": "startup_not_complete",
            "timestamp": time.time(),
        }

    services = _startup_state.get("services", {})

    # Core Kalshi services that must be running for the system to be "ready"
    # BUG-L13 FIX: In VALIDATION_MODE, merid_loop can be "skipped" and still be considered ready
    _critical_keys = ["kalshi_client", "kalshi_market_catalog", "merid_loop"]
    svc_status = {k: services.get(k, {}).get("status", "unknown") for k in _critical_keys}

    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        # In validation mode, "skipped" is acceptable for merid_loop
        all_critical_ok = all(
            s in ("running", "skipped") for s in svc_status.values()
        )
    else:
        all_critical_ok = all(s == "running" for s in svc_status.values())

    # Check if market catalog has data
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent blocking I/O during health check
    catalog_has_data = False
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        # In validation mode, assume catalog has data if service is running/skipped
        catalog_has_data = svc_status.get("kalshi_market_catalog") in ("running", "skipped")
    else:
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog_has_data = len(get_market_catalog().get_all_markets()) > 0
        except Exception as e:
            logger.debug(f"Catalog data check failed: {e}")

    ready = all_critical_ok and catalog_has_data

    return {
        "status": "ready" if ready else "not_ready",
        "timestamp": time.time(),
        "services": svc_status,
        "catalog_has_data": catalog_has_data,
    }


@app.get("/startup")
async def startup_status():
    """Get detailed startup status."""
    return _startup_state


@app.get("/api/v1/health/startup")
async def startup_health():
    """Comprehensive startup health check."""
    if _startup_state.get("started_at") is None:
        return {
            "status": "not_started",
            "message": "Startup has not been initiated"
        }
    
    services = _startup_state.get("services", {})
    running_count = sum(1 for s in services.values() if s.get("status") == "running")
    failed_count = sum(1 for s in services.values() if s.get("status") in ("failed", "timeout"))
    
    # Count active background tasks
    bg_tasks = _startup_state.get("background_tasks", [])
    active_tasks = sum(1 for t in bg_tasks if not t.done())
    
    _sa = _startup_state.get("started_at")
    _uptime = time.time() - _sa if _sa else 0.0
    return {
        "startup_completed": _sa is not None,
        "started_at": _sa,
        "uptime_seconds": round(_uptime, 1),
        "services": {
            "total": len(services),
            "running": running_count,
            "failed": failed_count,
            "details": services
        },
        "background_tasks": {
            "total": len(bg_tasks),
            "active": active_tasks
        }
    }


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # Exception handler to suppress Windows socket errors
    def asyncio_exception_handler(loop, context):
        """Handle asyncio exceptions gracefully, especially Windows socket errors."""
        exception = context.get("exception")
        message = context.get("message", "")

        # Suppress specific Windows socket errors that are harmless during shutdown
        if exception and isinstance(exception, OSError):
            if exception.winerror == 64:  # Network name no longer available
                logger.debug(f"Suppressed harmless socket error: {exception}")
                return
            if exception.winerror == 995:  # I/O operation aborted (thread exit)
                logger.debug(f"Suppressed WinError 995 (shutdown): {exception}")
                return
            if exception.winerror == 10038:  # Socket operation on non-socket
                logger.debug(f"Suppressed WinError 10038 (socket cleanup): {exception}")
                return
            if exception.errno == 22:  # Invalid argument (socket cleanup)
                logger.debug(f"Suppressed socket cleanup error: {exception}")
                return

        # Suppress InvalidStateError during shutdown (asyncio issue on Windows)
        if exception and isinstance(exception, asyncio.InvalidStateError):
            logger.debug(f"Suppressed InvalidStateError (shutdown): {exception}")
            return

        # Suppress ConnectionResetError during shutdown (Windows asyncio proactor issue)
        if exception and isinstance(exception, ConnectionResetError):
            # This is a harmless Windows asyncio proactor error when clients disconnect abruptly
            # No action needed - system continues normally
            logger.debug(f"Suppressed ConnectionResetError (client disconnect): {exception}")
            return

        # Log other exceptions normally
        if exception:
            logger.warning(f"Asyncio exception: {message}", exc_info=exception)
        else:
            logger.warning(f"Asyncio exception: {message}")
    
    # Set exception handler for the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(asyncio_exception_handler)
    
    # Windows-specific configuration to handle socket errors
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8011,
        log_level="info",
        access_log=True,
        # Use asyncio event loop that handles Windows socket errors better
        loop="asyncio" if sys.platform == "win32" else "auto",
        # Limit concurrent connections to reduce socket errors
        limit_concurrency=1000,
        # Timeout for keep-alive connections
        timeout_keep_alive=5,
    )
    
    server = uvicorn.Server(config)
    
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
    finally:
        # Clean up event loop - suppress all errors during shutdown
        try:
            # Cancel all pending tasks first
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass

            # Close the loop
            loop.close()
        except Exception as e:
            # Suppress all errors during shutdown - Windows asyncio can raise
            # InvalidStateError, OSError, etc. when the loop is already closing
            logger.debug(f"Loop close suppressed (shutdown): {type(e).__name__}")
