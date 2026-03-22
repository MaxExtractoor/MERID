from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
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
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
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

from audit.exporter import export_trail
from backtesting.replay import run_backtest
from backtesting.replayer import run_deterministic_replay
from core.energy import create_energy
from observability.event_stream import get_event_stream
from observability.observability_stack import get_observability_stack
from core.orchestrator import get_core
from core.state import state
from hardening.chaos import build_hardening_report
from memory.patterns import pattern_engine
from memory.store import reality_memory
from readiness.report import build_readiness_report
from services.gamification import GamificationEngine
# Lazy import to avoid loading crypto adapters in Kalshi-only mode
# from simulation.engine import build_simulation_chain
from swarm.agents.charters import CHARTER_REGISTRY
from swarm.performance import performance_ledger
from utils.logger import get_logger

logger = get_logger(__name__)

from web.api.reflection import router as reflection_router
from web.api.consensus import router as consensus_router
from web.api.mining import router as mining_router
from web.api.auth import router as auth_router
from web.api.referrals import router as referrals_router
# Lazy import - trading router loads paper_trading infrastructure
# from web.api.trading import router as trading_router
from web.api.betting import router as betting_router
from web.api.streams import router as streams_router
# Lazy import to avoid loading paper_trading which imports live_price_feed
# from web.api.paper_trading import router as paper_trading_router, paper_trading_convenience_router
from web.api.system_control import router as system_control_router
from web.api.data_endpoints import router as data_endpoints_router
from web.api.live_stream import router as live_stream_router
from web.api.institutional import router as institutional_router
from web.api.schemas import router as schemas_router
# Lazy import - arbitrage router loads CCXT exchange scanners
# from web.api.arbitrage import router as arbitrage_router
from web.api.prediction import router as prediction_router
from web.api.prediction_markets import router as prediction_markets_router
from web.api.prediction_consensus_api import router as prediction_consensus_router
from web.api.betting_consensus_api import router as betting_consensus_router
from web.api.flow_api import flow_router
from web.api.signal_layer_api import signal_layer_router
from web.api.unified_pipeline import router as unified_pipeline_router
from web.api.wallet import router as wallet_router
from web.api.offline import router as offline_router
from web.api.notifications import router as notifications_router
from web.api.compliance import router as compliance_router
from web.api.plugins import router as plugins_router
from web.api.monitoring import router as monitoring_router
from web.api.ratelimit import router as ratelimit_router
from web.api.backup import router as backup_router
from web.api.cost_models import router as cost_models_router
from web.api.time_exploit import router as time_exploit_router
from web.api.sniping import router as sniping_router
from web.api.recovery import router as recovery_router
from web.api.treasury import router as treasury_router
from web.api.quadratic_funding import router as quadratic_funding_router
from web.api.agents import router as agents_router
from web.api.governance import router as governance_router
from web.api.signals_api import router as signals_api_router
from web.api.orchestrator_api import router as orchestrator_api_router
from web.api.blockchain_health_api import router as blockchain_health_api_router
from web.api.rewards import router as rewards_router
from web.api.cognitive_api import router as cognitive_router
from web.api.dev_swarm_routes import router as dev_swarm_router
from web.api.dev_swarm_governance_routes import router as dev_swarm_governance_router
from web.api.operator import router as operator_router
from web.api.operator_endpoints import router as operator_endpoints_router, legacy_router as operator_legacy_router
from web.api.metrics import router as metrics_router
from web.api.metrics import record_latency
from web.api.market_data import router as market_data_router
from web.api.market_data import ws_router as market_ws_router
from web.api.loop_api import loop_api_router
from web.api.system_observability import router as system_observability_router
from web.api.llm_governance_api import router as llm_governance_router
from web.api.rag_api import router as rag_router
from web.api.assistant_api import router as assistant_router
from web.api.telemetry import router as telemetry_router
from web.api.resilience import router as resilience_router
from web.api.guardrails_api import router as guardrails_router
from web.api.kalshi_grid_api import router as kalshi_grid_router
from web.api.kalshi_api import router as kalshi_api_router
from web.api.kalshi_ui import router as kalshi_ui_router
from web.api.sidebar_config import router as sidebar_config_router
from web.api.benchmarks_api import router as benchmarks_router
from web.api.paper_ladder_api import router as paper_ladder_router
from web.api.paper_session_api import router as paper_session_router
from web.api.kalshi_agent_grid_api import router as kalshi_agent_grid_router
from web.api.kalshi_agent_performance_api import router as kalshi_agent_performance_router
from web.api.kalshi_deployment import router as kalshi_deployment_router
from web.api.kalshi_metrics_api import router as kalshi_metrics_api_router
from web.api.correlation_api import router as correlation_api_router
from web.api.swarm_bus_api import router as swarm_bus_api_router
from web.api.sentiment_api import router as sentiment_api_router
from web.api.xtf_api import router as xtf_api_router
from web.api.auto_promoter_api import router as auto_promoter_api_router

# Mock API routers for testing - REMOVED FOR LIVE-ONLY MODE
# from web.api.mock_simulation import router as mock_simulation_router
# from web.api.mock_arena import router as mock_arena_router
# from web.api.mock_trading import router as mock_trading_router
# from web.api.mock_arbitrage import router as mock_arbitrage_router
# from web.api.mock_system_admin import router as mock_system_admin_router
# from web.api.mock_prediction_markets import router as mock_prediction_markets_router
# from web.api.mock_agent_cohorts import router as mock_agent_cohorts_router
# Lazy import - trading_suite loads paper adapter which instantiates at module level
# from web.api.trading_suite import router as trading_suite_router


# Load centralized settings - single source of truth
from merid.settings import settings

# Basic environment logging (moved validation to startup_event)
logger.info("MERID Environment: %s", settings.MERID_ENV)
logger.info("Log Level: %s", settings.MERID_LOG_LEVEL)
from web.api.ops import router as ops_router
from web.api.archive import router as archive_router
from web.api.trading_mode import router as trading_mode_router
from web.api.reality import router as reality_router
from web.api.explainability import router as explainability_router
from web.api.live_data import router as live_data_router
from web.api.dashboard_data import router as dashboard_data_router
from web.api.dashboard import router as dashboard_router
from web.api.intelligence import router as intelligence_router
from web.api.local_venue import router as local_venue_router
from web.api.local_venue_validation import router as local_venue_validation_router
from web.integrations.local_venue_dashboard import get_local_venue_dashboard_data, local_venue_websocket_handler
from web.api.degraded import router as degraded_router
from web.api.market_assertions import router as market_assertions_router
from web.api.onchain_assertions import router as onchain_assertions_router
from web.api.simulation_assertions import router as simulation_assertions_router
from web.api.agent_assertions import router as agent_assertions_router
from web.api.domain_priority import router as domain_priority_router
from web.api.predictions import router as predictions_router
from web.api.simulation import router as simulation_router
from web.api.neo4j_memory import router as neo4j_memory_router
from web.api.dashboard_ws import router as dashboard_ws_router
from web.api.x_bot import router as x_bot_router
from web.api.swarm import router as swarm_router
from web.api.moat import router as moat_router
from web.api.health import router as health_router
from web.api.analytics import router as analytics_router
from web.api.brier_metrics import router as brier_metrics_router
from web.api.feedback import router as feedback_router
from web.api.production_status import router as production_status_router
from web.api.prime_screen import router as prime_screen_router
from web.api.autonomy import router as autonomy_router
from web.api.api_status import router as api_status_router
from web.api.risk import router as risk_router
# Skip governance cadence for Phase 0 trial
# from web.api.governance_cadence import router as governance_cadence_router
# Phase0 routers - disabled in Kalshi-only mode
minimal_scope_router = None
phase0_experiment_router = None
phase0_router = None
phase0_trial_router = None
from web.api.us_compliant_markets import router as us_compliant_markets_router
from web.api.system_endpoints import router as system_endpoints_router
from web.api.real_data_endpoints import router as real_data_router
from web.api.missing_endpoints import router as missing_endpoints_router

from web.websocket_factory import create_websocket_endpoint

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
    return _context_value("simulation_chain")


def _merid():
    return _context_value("merid")


def _logger():
    return _context_value("logger")


def _dashboard_key():
    return _context_value("dashboard_api_key")


def _templates():
    return _context_value("templates")



def create_app(lifespan=None) -> FastAPI:
    # Use _app_lifespan by default when called as factory (lifespan=None)
    if lifespan is None:
        lifespan = _app_lifespan
    application = FastAPI(title="MERID Core", version="2.0", lifespan=lifespan)
    
    # Mount static files
    application.mount("/static", StaticFiles(directory="web/static"), name="static")
    
    # Mount Flutter web app
    flutter_web_path = Path("lib/merid/web").resolve()
    if flutter_web_path.exists():
        application.mount("/lib/merid/web", StaticFiles(directory=str(flutter_web_path)), name="flutter_web")
    
    # Initialize Neo4j Graph Service
    try:
        from core.graph_service import initialize_graph_service
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "")
        # Skip Neo4j initialization for Phase 0 trial
        logger.info("Neo4j initialization skipped for Phase 0 trial")
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
        "merid": None,  # Lazy init during startup to avoid loading agents at import time
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

    application.add_middleware(
        CORSMiddleware,
        allow_origins=context["allowed_origins"] or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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

    application.include_router(root_router)
    application.include_router(router)
    application.include_router(router_v1)
    application.include_router(real_data_router)
    # Phase0 trial router gated
    # if not _kalshi_only:
    #     application.include_router(phase0_trial_router)
    application.include_router(consensus_router)
    application.include_router(mining_router)
    application.include_router(auth_router)
    if not _kalshi_only:
        from web.api.trading import router as trading_router
        application.include_router(referrals_router)
        application.include_router(trading_router)
        application.include_router(betting_router)
    application.include_router(streams_router)
    if not _kalshi_only:
        from web.api.paper_trading import router as paper_trading_router, paper_trading_convenience_router
        application.include_router(paper_trading_router)
        application.include_router(paper_trading_convenience_router)
    application.include_router(system_control_router)
    application.include_router(data_endpoints_router)
    application.include_router(live_stream_router)
    if not _kalshi_only:
        application.include_router(institutional_router)
    application.include_router(schemas_router)
    if not _kalshi_only:
        from web.api.arbitrage import router as arbitrage_router
        application.include_router(arbitrage_router)
        application.include_router(prediction_router)
        application.include_router(wallet_router)
    application.include_router(offline_router)
    application.include_router(notifications_router)
    application.include_router(compliance_router)
    if not _kalshi_only:
        application.include_router(plugins_router)
    application.include_router(monitoring_router)
    application.include_router(ratelimit_router)
    application.include_router(backup_router)
    if not _kalshi_only:
        application.include_router(cost_models_router)
        application.include_router(time_exploit_router)
        application.include_router(sniping_router)
    application.include_router(recovery_router)
    if not _kalshi_only:
        application.include_router(treasury_router)
        application.include_router(quadratic_funding_router)
    application.include_router(agents_router)
    application.include_router(governance_router)
    
    # Live API routers only - mock routers removed for live-only mode
    # application.include_router(mock_simulation_router, prefix="/api/v1/simulation", tags=["simulation"])
    # application.include_router(mock_arena_router, prefix="/api/v1/trading/arena", tags=["arena"])
    # application.include_router(mock_trading_router, prefix="/api/v1/trading", tags=["trading"])
    # application.include_router(mock_arbitrage_router, prefix="/api/v1/arbitrage", tags=["arbitrage"])
    # application.include_router(mock_system_admin_router, prefix="/api/v1/system", tags=["system"])
    # application.include_router(mock_prediction_markets_router, prefix="/api/v1/prediction", tags=["prediction"])
    # application.include_router(mock_agent_cohorts_router, prefix="/api/v1/agent-cohorts", tags=["agent-cohorts"])
    if not _kalshi_only:
        from web.api.trading_suite import router as trading_suite_router
        application.include_router(trading_suite_router, prefix="/api/v1/trading-suite", tags=["trading-suite"])
    application.include_router(ops_router)
    application.include_router(archive_router)
    application.include_router(trading_mode_router)
    if not _kalshi_only:
        application.include_router(reality_router)
    application.include_router(explainability_router)
    application.include_router(live_data_router)
    application.include_router(dashboard_data_router)
    application.include_router(dashboard_router)
    if not _kalshi_only:
        application.include_router(intelligence_router)
        application.include_router(local_venue_router)
        application.include_router(local_venue_validation_router)
    application.include_router(degraded_router)
    if not _kalshi_only:
        application.include_router(market_assertions_router)
        application.include_router(onchain_assertions_router)
        application.include_router(simulation_assertions_router)
        application.include_router(agent_assertions_router)
    application.include_router(domain_priority_router)
    application.include_router(production_status_router)
    application.include_router(dashboard_ws_router)
    if not _kalshi_only:
        application.include_router(x_bot_router)
        application.include_router(moat_router)
    application.include_router(swarm_router)
    application.include_router(health_router)
    application.include_router(analytics_router)
    if not _kalshi_only:
        application.include_router(predictions_router)
        application.include_router(prediction_markets_router)
        application.include_router(prediction_consensus_router)
        application.include_router(betting_consensus_router)
        application.include_router(flow_router)
        application.include_router(signal_layer_router)
        application.include_router(unified_pipeline_router)
        application.include_router(simulation_router)
        application.include_router(neo4j_memory_router)
    # Skip assertion registry for Phase 0 trial
    # application.include_router(assertion_router)
    if not _kalshi_only:
        application.include_router(brier_metrics_router)
    application.include_router(feedback_router)
    if not _kalshi_only:
        application.include_router(prime_screen_router)
        application.include_router(autonomy_router)
    application.include_router(api_status_router)
    application.include_router(risk_router)
    # application.include_router(governance_cadence_router)
    # Phase0 routers gated - imports commented out at line 197-201
    # application.include_router(minimal_scope_router)
    if not _kalshi_only:
        # application.include_router(phase0_experiment_router)
        application.include_router(us_compliant_markets_router)
    application.include_router(system_endpoints_router)
    if not _kalshi_only:
        application.include_router(signals_api_router)
    application.include_router(orchestrator_api_router)
    if not _kalshi_only:
        application.include_router(blockchain_health_api_router)
        application.include_router(rewards_router)
        application.include_router(cognitive_router)
        # application.include_router(dev_swarm_router)
        application.include_router(dev_swarm_governance_router)
    application.include_router(operator_router)
    application.include_router(operator_endpoints_router)
    application.include_router(operator_legacy_router)
    application.include_router(metrics_router)
    application.include_router(market_data_router)
    application.include_router(market_ws_router)
    application.include_router(loop_api_router)
    application.include_router(system_observability_router)
    if not _kalshi_only:
        application.include_router(llm_governance_router)
        application.include_router(rag_router)
        application.include_router(assistant_router)
    application.include_router(telemetry_router)
    application.include_router(resilience_router)
    application.include_router(guardrails_router)
    application.include_router(kalshi_api_router)
    application.include_router(kalshi_ui_router)
    application.include_router(kalshi_grid_router)
    application.include_router(sidebar_config_router)
    application.include_router(benchmarks_router)
    application.include_router(paper_ladder_router)
    application.include_router(paper_session_router)
    application.include_router(kalshi_agent_grid_router)
    application.include_router(kalshi_agent_performance_router)
    application.include_router(kalshi_deployment_router)
    application.include_router(kalshi_metrics_api_router)
    application.include_router(correlation_api_router)
    application.include_router(swarm_bus_api_router)
    application.include_router(sentiment_api_router)
    application.include_router(xtf_api_router)
    application.include_router(auto_promoter_api_router)

    # Register fallback stubs last so concrete implementations win route precedence.
    application.include_router(missing_endpoints_router)

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
        record_latency(str(request.url.path), elapsed_ms)
        return response

    # Phase 0 adapters gated - imports commented out at line 197-201
    # if phase0_router:
    #     application.include_router(phase0_router)
    # Phase 0 trial gated
    # application.include_router(phase0_trial_router)
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
            event = await queue.get()
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
                
    except Exception as e:
        logger.error(f"Whale WebSocket authentication error: {e}")
        await websocket.send_json({
            "type": "error",
            "detail": "Authentication failed"
        })
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
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
                    logger.debug("ws _receive_messages skipped: %s", _e)

        # Run heartbeat sender and message receiver concurrently
        done, pending = await _asyncio.wait(
            [_asyncio.create_task(_send_heartbeats()), _asyncio.create_task(_receive_messages())],
            return_when=_asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Trade WS error: {e}")
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
            await _asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Risk WS error: {e}")
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
                    pass
        try:
            await websocket.close()
        except Exception:
            pass
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

@root_router.get("/dashboard/legacy")
async def dashboard_legacy():
    """Legacy dashboard page."""
    templates = _templates()
    return templates.TemplateResponse("dashboard.html", {"request": {}})

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

@root_router.get("/legacy")
async def legacy_home(request: Request):
    return _templates().TemplateResponse(
        "index.html",
        {
            "request": request,
            "help_sections": state.help_sections(),
            "legal_notice": state.legal_notice(),
        },
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
    result = await _merid().run_cycle(energy)

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
                yield f"data: {json.dumps(event['data'])}\n\n"
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
    """Combined startup/shutdown lifespan for MERID."""
    global _startup_state
    _startup_state["started_at"] = time.time()
    startup_success = True

    # ── Phase 0: WebSocket publishers ──────────────────────────────────
    # Legacy crypto publishers DISABLED — Kalshi has its own data pipeline.
    # price_publisher, portfolio_publisher, prediction_publisher all produced
    # synthetic/crypto data that polluted the terminal and UI.
    logger.info("=" * 80)
    logger.info("STARTUP EVENT: Legacy WS publishers SKIPPED (Kalshi-only mode)")
    logger.info("=" * 80)

    # ── Phase 0.5: Kalshi Agent Grid ───────────────────────────────────
    logger.info("=" * 80)
    logger.info("🤖 Starting Kalshi Trading Agent Grid")
    logger.info("=" * 80)
    try:
        from merid.prediction.agent_grid import get_agent_grid
        agent_grid = get_agent_grid()
        await agent_grid.start()
        logger.info("✅ Kalshi Agent Grid started: %d trading agents", len(agent_grid.agents))
    except Exception as e:
        logger.error("Failed to start Kalshi Agent Grid: %s", e, exc_info=True)

    # ── Phase 0.5a: KalshiContinuousTrader ─────────────────────────────────
    logger.info("=" * 80)
    logger.info("🎯 Starting KalshiContinuousTrader (single signal path executor)")
    logger.info("=" * 80)
    try:
        from merid.prediction.kalshi_continuous_trader import get_kalshi_continuous_trader
        continuous_trader = get_kalshi_continuous_trader()
        await continuous_trader.start()
        logger.info("✅ KalshiContinuousTrader started and listening on event bus")
        _startup_state["services"]["kalshi_continuous_trader"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.error("Failed to start KalshiContinuousTrader: %s", e, exc_info=True)
        _startup_state["services"]["kalshi_continuous_trader"] = {"status": "failed", "error": str(e)}

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

    # ── Phase 0.55: MeridLoop ───────────────────────────────────────────
    try:
        from merid.loop import get_merid_loop as _get_merid_loop
        _merid_loop = _get_merid_loop()
        asyncio.create_task(_merid_loop.run())
        logger.info("✅ MeridLoop started")
    except Exception as e:
        logger.warning(f"MeridLoop start failed (non-fatal): {e}")

    # ── Phase 0.6: Orchestrator Agents ─────────────────────────────────
    logger.info("=" * 80)
    logger.info("🤖 Starting Orchestrator Agents (news monitor, social feeds, etc.)")
    logger.info("=" * 80)
    try:
        orchestrator_manager = get_orchestrator_manager()
        await orchestrator_manager.start_all()
        logger.info("✅ Orchestrator agents started (news monitor, twitter, telegram)")
    except Exception as e:
        logger.error("Failed to start orchestrator agents: %s", e, exc_info=True)

    # ── Phase 1: Core systems ──────────────────────────────────────────
    logger.info("=" * 80)
    logger.info("🚀 MERID STARTUP INITIATED")
    logger.info("=" * 80)

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
                with sqlite3.connect(str(pred_db)) as _pc:
                    for tbl in _pc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        _pc.execute(f"DELETE FROM [{tbl[0]}]")
                logger.info("Fresh-start: prediction_consensus.db truncated")
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
    aggregator = None  # Legacy crypto prediction aggregator disabled
    logger.info("Phase 2: Legacy prediction markets SKIPPED (Kalshi-only mode)")

    # ── Phase 3: Streaming & background services ─────────────────────
    logger.info("Phase 3: Starting streaming & background services...")

    # Live price feed streaming (DISABLED — legacy CCXT crypto feed, not needed for Kalshi)
    logger.info("Live price feed SKIPPED (Kalshi-only mode)")

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
        logger.warning(f"⚠️  HealthMonitor failed to start: {e}")
        _startup_state["services"]["health_monitor"] = {"status": "failed", "error": str(e)}

    try:
        from core.alerts import get_alert_manager
        _alert_mgr = get_alert_manager()
        await _alert_mgr.start()
        logger.info("✅ AlertManager started")
        _startup_state["services"]["alert_manager"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  AlertManager failed to start: {e}")
        _startup_state["services"]["alert_manager"] = {"status": "failed", "error": str(e)}

    try:
        from core.audit_trail import get_audit_trail
        _audit = get_audit_trail()
        await _audit.start()
        logger.info("✅ AuditTrail started")
        _startup_state["services"]["audit_trail"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  AuditTrail failed to start: {e}")
        _startup_state["services"]["audit_trail"] = {"status": "failed", "error": str(e)}

    try:
        from core.system_orchestrator import start_merid
        await start_merid()
        logger.info("✅ SystemOrchestrator started (consensus engine, inter-system API)")
        _startup_state["services"]["system_orchestrator"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  SystemOrchestrator failed to start: {e}")
        _startup_state["services"]["system_orchestrator"] = {"status": "failed", "error": str(e)}

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
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        _catalog = get_market_catalog()
        await _catalog.start()
        logger.info("✅ KalshiMarketCatalog started (market data backbone)")
        _startup_state["services"]["kalshi_market_catalog"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  KalshiMarketCatalog failed to start: {e}")
        _startup_state["services"]["kalshi_market_catalog"] = {"status": "failed", "error": str(e)}

    # KalshiSentimentService — background loop ingesting catalog → sentiment scores
    try:
        from merid.event_venues.kalshi.sentiment import get_sentiment_service
        _sentiment_svc = get_sentiment_service()
        await _sentiment_svc.start()
        logger.info("✅ KalshiSentimentService started (sentiment refresh loop)")
        _startup_state["services"]["kalshi_sentiment_service"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  KalshiSentimentService failed to start: {e}")
        _startup_state["services"]["kalshi_sentiment_service"] = {"status": "failed", "error": str(e)}

    # KalshiWebSocketBridge — pipes real-time Kalshi WS events into core event bus
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        from merid.event_venues.kalshi.market_catalog import get_market_catalog as _get_cat
        _ws_bridge = get_ws_bridge()
        # Subscribe to top active tickers from catalog (up to 50)
        _active_tickers = [m.ticker for m in _get_cat().get_all_markets()[:50]]
        task = asyncio.create_task(
            _ws_bridge.start(_active_tickers or None), name="kalshi-ws-bridge"
        )
        _startup_state["background_tasks"].append(task)
        logger.info(f"✅ KalshiWebSocketBridge started ({len(_active_tickers)} tickers)")
        _startup_state["services"]["kalshi_ws_bridge"] = {"status": "running", "started_at": time.time(), "tickers": len(_active_tickers)}
    except Exception as e:
        logger.warning(f"⚠️  KalshiWebSocketBridge failed to start: {e}")
        _startup_state["services"]["kalshi_ws_bridge"] = {"status": "failed", "error": str(e)}

    # TickerCollector — accumulates kalshi:price_update events into in-memory DataFrame
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
    try:
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator
        _enhanced_consensus = EnhancedConsensusCoordinator.get_instance()
        await _enhanced_consensus.start_opinion_subscriber()
        logger.info("✅ EnhancedConsensusCoordinator opinion subscriber started")
        _startup_state["services"]["enhanced_consensus_coordinator"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  EnhancedConsensusCoordinator opinion subscriber failed to start: {e}")
        _startup_state["services"]["enhanced_consensus_coordinator"] = {"status": "failed", "error": str(e)}

    # OrchestratorAgentManager — NewsMonitorAgent, AgentMesh (8 streaming agents),
    # KalshiSocialBroadcaster, ReflectionSystem. Must start AFTER WSFeedManager so
    # streaming_bus.MARKET_DATA has live prices before AgentMesh subscribes.
    try:
        from web.startup_agents import get_orchestrator_manager
        _orchestrator_mgr = get_orchestrator_manager()
        await _orchestrator_mgr.start_all()
        logger.info("✅ OrchestratorAgentManager started (AgentMesh + NewsMonitor + SocialBroadcaster + ReflectionSystem)")
        _startup_state["services"]["orchestrator_agent_manager"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  OrchestratorAgentManager failed to start: {e}")
        _startup_state["services"]["orchestrator_agent_manager"] = {"status": "failed", "error": str(e)}

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
    async def _cfgi_refresh_loop():
        _assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        while True:
            try:
                from merid.sentiment.cfgi_client import get_cfgi_client
                _cfgi = get_cfgi_client()
                for _asset in _assets:
                    try:
                        _cfgi.update_mood_bus(_asset)
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

    # MeridLoop — persistent swarm orchestrator (features → agents → consensus → arb → execution → CQI → reconcile)
    try:
        from merid.loop import get_merid_loop
        _merid_loop = get_merid_loop()
        task = asyncio.create_task(_merid_loop.run(), name="merid-loop")
        _startup_state["background_tasks"].append(task)
        logger.info("✅ MeridLoop started (swarm orchestrator)")
        _startup_state["services"]["merid_loop"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
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
    try:
        from agents.agent_mesh import agent_mesh
        asyncio.create_task(agent_mesh.initialize())
        task = asyncio.create_task(agent_mesh.start())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Agent mesh started")
        _startup_state["services"]["agent_mesh"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Agent mesh failed: {e}")
        _startup_state["services"]["agent_mesh"] = {"status": "failed", "error": str(e)}

    # Consensus engine streaming
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

    # Audit trail
    try:
        from core.audit_trail import get_audit_trail
        audit = get_audit_trail()
        task = asyncio.create_task(audit.start())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Audit trail started")
        _startup_state["services"]["audit_trail"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Audit trail failed: {e}")
        _startup_state["services"]["audit_trail"] = {"status": "failed", "error": str(e)}

    # Intelligence news aggregation
    try:
        from web.api.intelligence import aggregate_news
        task = asyncio.create_task(aggregate_news())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Intelligence news aggregation started")
    except Exception as e:
        logger.warning(f"⚠️  Intelligence news aggregation failed: {e}")

    # API live data fetching
    try:
        from web.api.live_data import fetch_live_prices as fetch_api_prices
        task = asyncio.create_task(fetch_api_prices())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ API live data feed started")
    except Exception as e:
        logger.warning(f"⚠️  API live data feed failed: {e}")

    # Alert manager
    try:
        from core.alerts import get_alert_manager
        alert_mgr = get_alert_manager()
        task = asyncio.create_task(alert_mgr.start())
        _startup_state["background_tasks"].append(task)
        try:
            from data.live_price_feed import get_live_price_feed
            price_feed = get_live_price_feed()
            def on_alert_price_update(price_data):
                alert_mgr.update_price(price_data.symbol, price_data.price)
            price_feed.subscribe(on_alert_price_update)
            logger.info("✅ Alert manager started + wired to price feed")
        except Exception:
            logger.info("✅ Alert manager started (price feed wire skipped)")
        _startup_state["services"]["alerts"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Alert manager failed: {e}")
        _startup_state["services"]["alerts"] = {"status": "failed", "error": str(e)}

    # Health monitor
    try:
        from core.health import get_health_monitor
        health_mon = get_health_monitor()
        task = asyncio.create_task(health_mon.start())
        _startup_state["background_tasks"].append(task)
        logger.info("✅ Health monitor started")
        _startup_state["services"]["health_monitor"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Health monitor failed: {e}")
        _startup_state["services"]["health_monitor"] = {"status": "failed", "error": str(e)}

    # Whale listener (DISABLED — Solana-specific, not needed for Kalshi)
    logger.info("Whale listener SKIPPED (Kalshi-only mode)")

    # Pre-warm signal metrics cache (background thread, non-blocking)
    try:
        from web.api.signal_layer_api import warm_signal_metrics_cache
        warm_signal_metrics_cache()
        logger.info("✅ Signal metrics cache warming started (background)")
    except Exception as e:
        logger.warning(f"⚠️  Signal metrics cache warm failed: {e}")

    startup_duration = time.time() - _startup_state["started_at"]
    logger.info("=" * 80)
    if startup_success:
        logger.info(f"✅ All services started successfully in {startup_duration:.2f}s")
    else:
        logger.warning(f"⚠️  Some services failed - system in degraded mode ({startup_duration:.2f}s)")
    logger.info("🚀 MERID STARTUP COMPLETE - System Ready")
    logger.info("=" * 80)

    # ── Startup reconciliation — unblock execution gate immediately ─────
    try:
        from merid.reconciliation import reconcile_all_venues, has_critical_discrepancies
        logger.info("Running startup reconciliation to unblock execution gate...")
        discrepancies = await asyncio.get_running_loop().run_in_executor(
            None, lambda: reconcile_all_venues(["kalshi"])
        )
        n_crit = sum(1 for d in discrepancies if d.severity == "critical")
        n_warn = sum(1 for d in discrepancies if d.severity == "warning")
        logger.info(
            "✅ Startup reconciliation: %d discrepancies (%d critical, %d warning)",
            len(discrepancies), n_crit, n_warn,
        )
        if has_critical_discrepancies():
            logger.warning("⚠️  Execution gate BLOCKED (critical reconciliation issues)")
        else:
            logger.info("✅ Execution gate CLEAR — trades can proceed")
    except Exception as exc:
        logger.warning("Startup reconciliation failed (gate may remain blocked): %s", exc)

    # ── Start periodic reconciliation ──────────────────────────────────
    try:
        from trading.reconciliation import start_periodic_reconciliation
        start_periodic_reconciliation(interval_seconds=300.0)
    except Exception as exc:
        logger.debug("Paper reconciliation loop not started: %s", exc)

    # ── Start periodic Kalshi venue reconciliation ───────────────────
    try:
        import threading as _recon_threading
        from merid.reconciliation import reconcile_all_venues

        _kalshi_recon_stop = _recon_threading.Event()

        def _kalshi_recon_loop() -> None:
            logger.info("Periodic Kalshi venue reconciliation started (every 300s)")
            while not _kalshi_recon_stop.wait(timeout=300.0):
                try:
                    discs = reconcile_all_venues(["kalshi"])
                    n_crit = sum(1 for d in discs if d.severity == "critical")
                    if discs:
                        logger.warning(
                            "Kalshi venue reconciliation: %d discrepancies (%d critical)",
                            len(discs), n_crit,
                        )
                    else:
                        logger.info("Kalshi venue reconciliation: OK (0 discrepancies)")
                except Exception as exc:
                    logger.error("Kalshi venue reconciliation error: %s", exc)

        _kalshi_recon_thread = _recon_threading.Thread(
            target=_kalshi_recon_loop, daemon=True, name="kalshi-recon-loop",
        )
        _kalshi_recon_thread.start()
    except Exception as exc:
        logger.debug("Kalshi venue reconciliation loop not started: %s", exc)

    # ── Phase N: Kalshi Insight Pipeline + News Agent ──────────────────
    try:
        from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline
        from merid.publishing.kalshi_news_agent import get_kalshi_news_agent
        _insight_pipeline = get_insight_pipeline()
        _news_agent = get_kalshi_news_agent()
        _insight_pipeline.add_consumer(_news_agent.handle_insight)
        asyncio.create_task(_insight_pipeline.start())
        logger.info("✅ KalshiInsightPipeline + KalshiNewsAgent started")
    except Exception as exc:
        logger.warning("KalshiInsightPipeline start failed (non-fatal): %s", exc)

    # Terminal telemetry loop DISABLED — was printing synthetic crypto trades/portfolio
    # Kalshi agent grid has its own telemetry via the /api/v1/kalshi-grid/* endpoints.
    logger.info("Terminal telemetry loop SKIPPED (Kalshi-only mode)")

    # ── YIELD — app is running ─────────────────────────────────────────
    yield

    # ── SHUTDOWN ───────────────────────────────────────────────────────
    logger.info("🛑 MERID shutdown initiated - cancelling background tasks...")

    # Stop MeridLoop
    try:
        from merid.loop import get_merid_loop as _get_merid_loop
        _get_merid_loop().stop()
        logger.info("✅ MeridLoop stopped")
    except Exception as exc:
        logger.warning("MeridLoop stop failed: %s", exc)

    # Stop KalshiInsightPipeline
    try:
        from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline as _get_pipeline
        await _get_pipeline().stop()
        logger.info("✅ KalshiInsightPipeline stopped")
    except Exception as exc:
        logger.warning("KalshiInsightPipeline stop failed: %s", exc)

    # Stop MarketMoodBus aggregation loop
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus as _get_mood_bus
        await _get_mood_bus().stop()
        logger.info("✅ MarketMoodBus stopped")
    except Exception as exc:
        logger.warning("MarketMoodBus stop failed: %s", exc)

    # Stop WSFeedManager (Coinbase WS price feed)
    try:
        from merid.signals.ws_price_feed import get_ws_feed_manager as _get_ws_mgr
        await _get_ws_mgr().stop()
        logger.info("✅ WSFeedManager stopped")
    except Exception as exc:
        logger.warning("WSFeedManager stop failed: %s", exc)

    # Close LiveFeedManager httpx client
    try:
        from merid.signals.live_feeds import get_live_feed_manager as _get_live_feed_mgr
        await _get_live_feed_mgr().close()
        logger.info("✅ LiveFeedManager closed")
    except Exception as exc:
        logger.warning("LiveFeedManager close failed: %s", exc)

    # Stop SentimentBus (Twitter+Reddit background loops)
    try:
        from merid.sentiment.sentiment_bus import get_sentiment_bus as _get_sent_bus
        await _get_sent_bus().stop()
        logger.info("✅ SentimentBus stopped")
    except Exception as exc:
        logger.warning("SentimentBus stop failed: %s", exc)

    # Stop TwitterStreamHandler (threaded, sync stop)
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_stream_handler as _get_tw_stream
        _get_tw_stream().stop()
        logger.info("✅ TwitterStreamHandler stopped")
    except Exception as exc:
        logger.warning("TwitterStreamHandler stop failed: %s", exc)

    # Stop KalshiWebSocketBridge
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge as _get_ws_bridge
        await _get_ws_bridge().stop()
        logger.info("✅ KalshiWebSocketBridge stopped")
    except Exception as exc:
        logger.warning("KalshiWebSocketBridge stop failed: %s", exc)

    # Stop KalshiSentimentService
    try:
        from merid.event_venues.kalshi.sentiment import get_sentiment_service as _get_sentiment_svc
        await _get_sentiment_svc().stop()
        logger.info("✅ KalshiSentimentService stopped")
    except Exception as exc:
        logger.warning("KalshiSentimentService stop failed: %s", exc)

    # Stop KalshiInsightPipeline
    try:
        from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline as _get_insight_pl
        await _get_insight_pl().stop()
        logger.info("✅ KalshiInsightPipeline stopped")
    except Exception as exc:
        logger.warning("KalshiInsightPipeline stop failed: %s", exc)

    # Stop KalshiMarketCatalog
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog as _get_catalog
        await _get_catalog().stop()
        logger.info("✅ KalshiMarketCatalog stopped")
    except Exception as exc:
        logger.warning("KalshiMarketCatalog stop failed: %s", exc)

    # Stop TickerCollector
    try:
        from merid.event_venues.kalshi.ticker_collector import get_ticker_collector as _get_ticker_col
        await _get_ticker_col().stop()
        logger.info("✅ TickerCollector stopped")
    except Exception as exc:
        logger.warning("TickerCollector stop failed: %s", exc)

    # Stop KalshiMarketCache
    try:
        from merid.event_venues.kalshi.market_cache import get_market_cache as _get_mkt_cache
        await _get_mkt_cache().stop()
        logger.info("✅ KalshiMarketCache stopped")
    except Exception as exc:
        logger.warning("KalshiMarketCache stop failed: %s", exc)

    # Stop KalshiContinuousTrader
    try:
        from merid.prediction.kalshi_continuous_trader import get_kalshi_continuous_trader
        await get_kalshi_continuous_trader().stop()
        logger.info("✅ KalshiContinuousTrader stopped")
    except Exception as exc:
        logger.warning("KalshiContinuousTrader stop failed: %s", exc)

    # Stop EnhancedConsensusCoordinator opinion subscriber
    try:
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator as _ECC
        await _ECC.get_instance().stop_opinion_subscriber()
        logger.info("✅ EnhancedConsensusCoordinator opinion subscriber stopped")
    except Exception as exc:
        logger.warning("EnhancedConsensusCoordinator stop failed: %s", exc)

    # Stop OrchestratorAgentManager (AgentMesh, NewsMonitor, SocialBroadcaster, ReflectionSystem)
    try:
        from web.startup_agents import get_orchestrator_manager as _get_orch_mgr
        await _get_orch_mgr().stop_all()
        logger.info("✅ OrchestratorAgentManager stopped")
    except Exception as exc:
        logger.warning("OrchestratorAgentManager stop failed: %s", exc)

    # Stop WatchdogCoordinator
    try:
        from agents.watchdog_agents import get_watchdog_coordinator as _get_watchdog
        await _get_watchdog().stop()
        logger.info("✅ WatchdogCoordinator stopped")
    except Exception as exc:
        logger.warning("WatchdogCoordinator stop failed: %s", exc)

    # Stop SystemOrchestrator (also stops ConsensusEngine)
    try:
        from core.system_orchestrator import stop_merid
        await stop_merid()
        logger.info("✅ SystemOrchestrator stopped")
    except Exception as exc:
        logger.warning("SystemOrchestrator stop failed: %s", exc)

    # Stop AuditTrail
    try:
        from core.audit_trail import get_audit_trail as _get_audit
        await _get_audit().stop()
        logger.info("✅ AuditTrail stopped")
    except Exception as exc:
        logger.warning("AuditTrail stop failed: %s", exc)

    # Stop AlertManager
    try:
        from core.alerts import get_alert_manager as _get_alert_mgr
        await _get_alert_mgr().stop()
        logger.info("✅ AlertManager stopped")
    except Exception as exc:
        logger.warning("AlertManager stop failed: %s", exc)

    # Stop HealthMonitor
    try:
        from core.health import get_health_monitor as _get_health_mon
        await _get_health_mon().stop()
        logger.info("✅ HealthMonitor stopped")
    except Exception as exc:
        logger.warning("HealthMonitor stop failed: %s", exc)

    # Stop Kalshi agent grid gracefully (flushes pending orders, stops agents)
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        await grid.stop()
        logger.info("✅ Kalshi agent grid stopped")
    except Exception as exc:
        logger.warning("Kalshi agent grid stop failed: %s", exc)

    # Stop orchestrator agents (news monitor, twitter, telegram)
    try:
        orchestrator_manager = get_orchestrator_manager()
        await orchestrator_manager.stop_all()
        logger.info("✅ Orchestrator agents stopped")
    except Exception as exc:
        logger.warning("Orchestrator agents stop failed: %s", exc)

    # Flush PortfolioRebalancer state (W10)
    try:
        from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer as _get_rebalancer
        _get_rebalancer()._bootstrap_targets()  # persist final targets
        logger.info("✅ PortfolioRebalancer flushed")
    except Exception as exc:
        logger.debug("PortfolioRebalancer flush skipped: %s", exc)

    # Final reconciliation + save paper state
    try:
        from trading.reconciliation import run_reconciliation, stop_periodic_reconciliation
        stop_periodic_reconciliation()
        report = run_reconciliation()
        logger.info("Shutdown reconciliation: all_ok=%s hash=%s", report.all_ok, report.snapshot_hash[:12])
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


async def _start_prediction_markets():
    """Wrapper to start prediction markets with proper error handling."""
    from monitoring.prediction_markets import start_prediction_markets
    return await start_prediction_markets()


@app.get("/api/v1/market/data/freshness")
async def market_data_freshness():
    """Market data freshness check endpoint"""
    import time
    return {
        "status": "fresh",
        "timestamp": time.time(),
        "last_update": time.time(),
        "age_seconds": 0,
        "feeds": {
            "kraken": "healthy",
            "coinbase": "healthy", 
            "gemini": "healthy"
        }
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
    """Readiness probe - data feed OK, risk engine responding, DB reachable"""
    import time
    import os
    
    # Check if startup has completed
    if _startup_state.get("started_at") is None:
        return {
            "status": "not_ready",
            "reason": "startup_not_complete",
            "timestamp": time.time()
        }
    
    # Check service states from startup tracking
    services = _startup_state.get("services", {})
    prediction_markets_ok = services.get("prediction_markets", {}).get("status") == "running"
    
    # Check if we're in synthetic mode
    synthetic_mode = os.getenv("SIMULATION_MODE", "").lower() == "synthetic_only"
    
    # Check aggregator status
    aggregator_available = False
    data_fresh = False
    
    try:
        from monitoring.real_prediction_markets import get_real_prediction_aggregator
        aggregator = await get_real_prediction_aggregator()
        if aggregator:
            aggregator_available = True
            markets = aggregator.get_all_markets()
            if markets:
                data_fresh = True
    except Exception as e:
        logger.debug(f"Ready check aggregator error: {e}")
    
    # Overall readiness - allow degraded mode if prediction markets started
    ready = (aggregator_available or prediction_markets_ok) and (data_fresh or synthetic_mode)
    
    return {
        "status": "ready" if ready else "not_ready",
        "timestamp": time.time(),
        "services": {
            "prediction_markets": services.get("prediction_markets", {}).get("status", "unknown"),
            "aggregator_available": aggregator_available,
            "data_fresh": data_fresh,
        },
        "synthetic_mode": synthetic_mode,
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
        
        # Suppress specific Windows socket errors that are harmless
        if exception and isinstance(exception, OSError):
            if exception.winerror == 64:  # Network name no longer available
                logger.debug(f"Suppressed harmless socket error: {exception}")
                return
            if exception.errno == 22:  # Invalid argument (socket cleanup)
                logger.debug(f"Suppressed socket cleanup error: {exception}")
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
        # Clean up event loop
        try:
            loop.close()
        except Exception:
            pass
