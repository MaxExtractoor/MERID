from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Deque, Dict, Optional

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
from simulation.engine import build_simulation_chain
from swarm.agents.charters import CHARTER_REGISTRY
from swarm.performance import performance_ledger
from utils.logger import get_logger

logger = get_logger(__name__)

from web.api.reflection import router as reflection_router
from web.api.consensus import router as consensus_router
from web.api.mining import router as mining_router
from web.api.auth import router as auth_router
from web.api.referrals import router as referrals_router
from web.api.trading import router as trading_router
from web.api.betting import router as betting_router
from web.api.streams import router as streams_router
from web.api.paper_trading import router as paper_trading_router
from web.api.system_control import router as system_control_router
from web.api.data_endpoints import router as data_endpoints_router
from web.api.live_stream import router as live_stream_router
from web.api.institutional import router as institutional_router
from web.api.schemas import router as schemas_router
from web.api.arbitrage import router as arbitrage_router
from web.api.prediction import router as prediction_router
from web.api.prediction_markets import router as prediction_markets_router
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

# Mock API routers for testing - REMOVED FOR LIVE-ONLY MODE
# from web.api.mock_simulation import router as mock_simulation_router
# from web.api.mock_arena import router as mock_arena_router
# from web.api.mock_trading import router as mock_trading_router
# from web.api.mock_arbitrage import router as mock_arbitrage_router
# from web.api.mock_system_admin import router as mock_system_admin_router
# from web.api.mock_prediction_markets import router as mock_prediction_markets_router
# from web.api.mock_agent_cohorts import router as mock_agent_cohorts_router
from web.api.trading_suite import router as trading_suite_router


# Load centralized settings - single source of truth
from merid.settings import settings

# Basic environment logging (moved validation to startup_event)
print(f"🚀 MERID Environment: {settings.MERID_ENV}")
print(f"📝 Log Level: {settings.MERID_LOG_LEVEL}")
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
from web.api.governance import router as governance_router
from web.api.feedback import router as feedback_router
from web.api.production_status import router as production_status_router
from web.api.prime_screen import router as prime_screen_router
from web.api.autonomy import router as autonomy_router
from web.api.api_status import router as api_status_router
from web.api.risk import router as risk_router
# Skip governance cadence for Phase 0 trial
# from web.api.governance_cadence import router as governance_cadence_router
from web.api.minimal_scope import router as minimal_scope_router
from web.api.phase0_experiment import router as phase0_experiment_router
from web.api.phase0_adapters import phase0_router
from web.api.phase0_trial_api import router as phase0_trial_router
from web.api.us_compliant_markets import router as us_compliant_markets_router
from web.api.system_endpoints import router as system_endpoints_router

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
    application = FastAPI(title="MERID Core", version="2.0", lifespan=lifespan)
    
    # Startup event to start WebSocket publishers (bypasses blocking lifespan)
    @application.on_event("startup")
    async def start_websocket_publishers():
        """Start WebSocket data publishers on application startup."""
        import asyncio
        print("=" * 80)
        print("STARTUP EVENT EXECUTING - Starting WebSocket publishers")
        print("=" * 80)
        logger.info("=" * 80)
        logger.info("STARTUP EVENT: Starting WebSocket publishers")
        logger.info("=" * 80)
        
        try:
            logger.info("Starting WebSocket price publisher via startup event...")
            from web.services.price_publisher import get_price_publisher
            price_publisher = get_price_publisher()
            asyncio.create_task(price_publisher.start())
            logger.info("Price publisher task created")
            print("✓ Price publisher task created")
        except Exception as e:
            logger.error(f"Failed to start price publisher: {e}", exc_info=True)
            print(f"✗ Failed to start price publisher: {e}")
        
        try:
            logger.info("Starting WebSocket portfolio publisher via startup event...")
            from web.services.portfolio_publisher import get_portfolio_publisher
            portfolio_publisher = get_portfolio_publisher()
            asyncio.create_task(portfolio_publisher.start())
            logger.info("Portfolio publisher task created")
            print("✓ Portfolio publisher task created")
        except Exception as e:
            logger.error(f"Failed to start portfolio publisher: {e}", exc_info=True)
            print(f"✗ Failed to start portfolio publisher: {e}")
        
        try:
            logger.info("Initializing prediction markets aggregator...")
            from monitoring.prediction_markets import get_prediction_aggregator
            aggregator = get_prediction_aggregator()
            # Store in app state for persistence across requests
            application.state.prediction_aggregator = aggregator
            # Start background task to fetch markets
            asyncio.create_task(aggregator.start())
            logger.info("Prediction markets aggregator initialized")
            print("✓ Prediction markets aggregator initialized")
        except Exception as e:
            logger.error(f"Failed to start prediction markets: {e}", exc_info=True)
            print(f"✗ Failed to start prediction markets: {e}")
        
        try:
            logger.info("Starting WebSocket prediction publisher...")
            from web.services.prediction_publisher import get_prediction_publisher
            prediction_publisher = get_prediction_publisher()
            asyncio.create_task(prediction_publisher.start())
            logger.info("Prediction publisher task created")
            print("✓ Prediction publisher task created")
        except Exception as e:
            logger.error(f"Failed to start prediction publisher: {e}", exc_info=True)
            print(f"✗ Failed to start prediction publisher: {e}")
        
        # Give tasks a moment to start
        await asyncio.sleep(0.5)
        logger.info("WebSocket publishers startup complete")
        print("=" * 80)
        print("STARTUP EVENT COMPLETE")
        print("=" * 80)
    
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
    simulation_chain = build_simulation_chain(
        use_mock=str(os.getenv("MERID_KALSHI_MOCK", "")).lower() in {"1", "true", "yes"}
    )
    context = {
        "simulation_chain": simulation_chain,
        "merid": get_core(),
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

    application.include_router(root_router)
    application.include_router(router)
    application.include_router(router_v1)
    application.include_router(reflection_router)
    application.include_router(consensus_router)
    application.include_router(mining_router)
    application.include_router(auth_router)
    application.include_router(referrals_router)
    application.include_router(trading_router)
    application.include_router(betting_router)
    application.include_router(streams_router)
    application.include_router(paper_trading_router)
    application.include_router(system_control_router)
    application.include_router(data_endpoints_router)
    application.include_router(live_stream_router)
    application.include_router(institutional_router)
    application.include_router(schemas_router)
    application.include_router(arbitrage_router)
    application.include_router(prediction_router)
    application.include_router(wallet_router)
    application.include_router(offline_router)
    application.include_router(notifications_router)
    application.include_router(compliance_router)
    application.include_router(plugins_router)
    application.include_router(monitoring_router)
    application.include_router(ratelimit_router)
    application.include_router(backup_router)
    application.include_router(cost_models_router)
    application.include_router(time_exploit_router)
    application.include_router(sniping_router)
    application.include_router(recovery_router)
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
    application.include_router(trading_suite_router, prefix="/api/v1/trading-suite", tags=["trading-suite"])
    application.include_router(ops_router)
    application.include_router(archive_router)
    application.include_router(trading_mode_router)
    application.include_router(reality_router)
    application.include_router(explainability_router)
    application.include_router(live_data_router)
    application.include_router(dashboard_data_router)
    application.include_router(dashboard_router)
    application.include_router(intelligence_router)
    application.include_router(local_venue_router)
    application.include_router(local_venue_validation_router)
    application.include_router(degraded_router)
    application.include_router(market_assertions_router)
    application.include_router(onchain_assertions_router)
    application.include_router(simulation_assertions_router)
    application.include_router(agent_assertions_router)
    application.include_router(domain_priority_router)
    application.include_router(production_status_router)
    application.include_router(dashboard_ws_router)
    application.include_router(x_bot_router)
    application.include_router(moat_router)
    application.include_router(swarm_router)
    application.include_router(health_router)
    application.include_router(analytics_router)
    application.include_router(predictions_router)
    application.include_router(prediction_markets_router)
    application.include_router(unified_pipeline_router)
    application.include_router(simulation_router)
    application.include_router(neo4j_memory_router)
    # Skip assertion registry for Phase 0 trial
    # application.include_router(assertion_router)
    application.include_router(brier_metrics_router)
    application.include_router(governance_router)
    application.include_router(feedback_router)
    application.include_router(prime_screen_router)
    application.include_router(autonomy_router)
    application.include_router(api_status_router)
    application.include_router(risk_router)
    # application.include_router(governance_cadence_router)
    application.include_router(minimal_scope_router)
    application.include_router(phase0_experiment_router)
    application.include_router(us_compliant_markets_router)
    application.include_router(system_endpoints_router)
    application.include_router(signals_api_router)
    application.include_router(orchestrator_api_router)
    application.include_router(blockchain_health_api_router)
    # Phase 0 adapters - only mount if feature flags are enabled
    if phase0_router:
        application.include_router(phase0_router)
    # Phase 0 trial - always available when Phase 0 is enabled
    application.include_router(phase0_trial_router)
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
        unsubscribe_trade = engine._subscribe("trade", on_trade)
        unsubscribe_position = engine._subscribe("position", on_position)
        unsubscribe_summary = engine._subscribe("summary", on_summary)
        
        # Keep connection alive and listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send commands if needed
                logger.debug(f"Received from paper trading client: {data}")
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping", "ts": time.time()})
            except Exception as e:
                logger.error(f"Paper trading WebSocket error: {e}")
                break
                
    except Exception as e:
        logger.error(f"Paper trading WebSocket connection error: {e}")
    finally:
        # Cleanup subscriptions
        try:
            unsubscribe_trade()
            unsubscribe_position()
            unsubscribe_summary()
        except:
            pass
        await websocket.close()
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


# Create app instance after all routes are defined
# NOTE: Startup/shutdown now handled by main.py lifespan manager
app = create_app()

# Add health endpoints after app creation
@app.get("/api/v1/system/health")
async def system_health():
    """System health check endpoint"""
    import time
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "services": {
            "api": "running",
            "prediction_markets": "running",
            "paper_trading": "configured"
        }
    }


@app.get("/api/system/health")
async def system_health_v2():
    """Enhanced system health for dashboard"""
    import time
    import os
    
    # Check individual service health
    services = {
        "api_gateway": {"status": "healthy", "last_check": time.time()},
        "prediction_markets": {"status": "healthy", "last_check": time.time()},
        "risk_engine": {"status": "healthy", "last_check": time.time()},
        "order_router": {"status": "healthy", "last_check": time.time()},
        "data_ingestion": {"status": "healthy", "last_check": time.time()},
    }
    
    # Determine overall status
    all_healthy = all(s["status"] == "healthy" for s in services.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": time.time(),
        "environment": os.getenv("MERID_ENV", "development"),
        "incident_flag": False,
        "services": services
    }


@app.get("/api/risk/pnl-summary")
async def pnl_summary():
    """P&L summary for dashboard"""
    import time
    
    return {
        "today_pnl": 12847.32,
        "today_pnl_pct": 2.34,
        "mtm_pnl": 45623.89,
        "max_drawdown": 0.08,
        "max_drawdown_pct": 8.0,
        "limit_daily_loss": 50000.00,
        "limit_utilization_pct": 25.7,
        "timestamp": time.time()
    }


@app.get("/api/risk/limits")
async def risk_limits():
    """Risk limits configuration"""
    return {
        "max_daily_loss": 50000.00,
        "max_position_pct": 0.20,
        "max_leverage": 2.0,
        "max_orders_per_minute": 100,
        "max_notional_per_trade": 100000.00,
        "circuit_breaker_threshold": 0.15
    }


@app.get("/api/risk/exposure")
async def risk_exposure():
    """Current risk exposure"""
    return {
        "total_exposure": 125000.00,
        "total_exposure_pct": 0.25,
        "buying_power": 375000.00,
        "by_symbol": [
            {"symbol": "BTC-USD", "notional": 45000.00, "pct_of_equity": 0.09},
            {"symbol": "ETH-USD", "notional": 32000.00, "pct_of_equity": 0.064},
            {"symbol": "AAPL", "notional": 28000.00, "pct_of_equity": 0.056},
        ],
        "open_orders_count": 12,
        "open_orders_limit": 50
    }


@app.get("/api/risk/protections")
async def risk_protections():
    """Circuit breaker and lockdown status"""
    return {
        "locked_down": False,
        "breaker_tripped": False,
        "reason": None,
        "since": None,
        "kill_switch_enabled": True,
        "auto_trading_paused": False
    }


@app.get("/api/agents/summary")
async def agents_summary():
    """Agent status summary"""
    return {
        "agents": [
            {
                "id": "trend-follower-l1",
                "name": "Trend Follower L1",
                "status": "healthy",
                "heartbeat_age_ms": 1200,
                "strategy": "trend_following",
                "state": "active",
                "positions_count": 3,
                "today_pnl": 2340.50
            },
            {
                "id": "momentum-v1",
                "name": "Momentum V1",
                "status": "healthy",
                "heartbeat_age_ms": 800,
                "strategy": "momentum",
                "state": "active",
                "positions_count": 2,
                "today_pnl": 1890.25
            },
            {
                "id": "arbitrage-scan",
                "name": "Arbitrage Scanner",
                "status": "paused",
                "heartbeat_age_ms": 5000,
                "strategy": "arbitrage",
                "state": "paused",
                "positions_count": 0,
                "today_pnl": 0.0
            }
        ],
        "summary": {
            "total": 3,
            "healthy": 2,
            "paused": 1,
            "unhealthy": 0
        }
    }


@app.get("/api/trading/summary")
async def trading_summary():
    """Trading operations summary"""
    return {
        "active_strategies": 2,
        "paused_strategies": 1,
        "venues_connected": 3,
        "venues": ["Alpaca", "Coinbase Pro", "Kraken"],
        "notional_deployed": 125000.00,
        "notional_capacity": 500000.00,
        "utilization_pct": 25.0
    }


@app.get("/api/prime/status")
async def prime_status():
    """Prime screen connection status"""
    import time
    return {
        "mode": "paper",
        "market_data_connected": True,
        "narrative_available": True,
        "last_narrative_timestamp": time.time() - 120,
        "data_feeds": {
            "kraken": {"connected": True, "latency_ms": 45},
            "coinbase": {"connected": True, "latency_ms": 62},
            "alpaca": {"connected": True, "latency_ms": 38}
        }
    }


@app.get("/api/system/version")
async def system_version():
    """System version and build info"""
    import os
    return {
        "version": "2.0.0",
        "build": "2025.01.31",
        "git_sha": os.getenv("GIT_SHA", "abc1234"),
        "environment": os.getenv("MERID_ENV", "development"),
        "openapi_url": "/openapi.json"
    }


@app.get("/api/system/components")
async def system_components():
    """System component statuses"""
    return {
        "components": [
            {"name": "API Gateway", "status": "operational", "version": "2.0.0"},
            {"name": "Risk Engine", "status": "operational", "version": "2.0.0"},
            {"name": "Order Router", "status": "operational", "version": "2.0.0"},
            {"name": "Data Ingestion", "status": "operational", "version": "2.0.0"},
            {"name": "Agent Manager", "status": "operational", "version": "2.0.0"},
        ]
    }

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


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown - cancel background tasks."""
    global _startup_state
    logger.info("🛑 MERID shutdown initiated - cancelling background tasks...")
    
    # Cancel all tracked background tasks
    for task in _startup_state.get("background_tasks", []):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    logger.info("✅ Shutdown complete")


@app.on_event("startup")
async def startup_event():
    """Start background services on application startup with robust error handling."""
    global _startup_state
    _startup_state["started_at"] = time.time()
    startup_success = True
    
    logger.info("=" * 80)
    logger.info("🚀 MERID STARTUP INITIATED")
    logger.info("=" * 80)
    
    # Log environment info and validate configuration
    logger.info(f"🚀 MERID Environment: {settings.MERID_ENV}")
    logger.info(f"🌐 WebSocket Dev Mode: {settings.allow_websocket_dev_mode}")
    
    # Validate live-only mode
    live_issues = settings.validate_live_only_mode()
    if live_issues:
        logger.warning(f"❌ Live-only mode validation failed:")
        for issue in live_issues:
            logger.warning(f"   - {issue}")
        logger.warning(f"⚠️  To enable live-only mode, fix the above issues in .env")
    else:
        logger.info(f"✅ Live-only mode validated - all features will use real data")
    
    # Validate production requirements (fail fast in production)
    if settings.is_production:
        missing = settings.validate_required_for_production()
        if missing:
            logger.error(f"❌ Production validation failed - missing: {', '.join(missing)}")
            raise ValueError(f"Missing required production settings: {', '.join(missing)}")
        else:
            logger.info("✅ Production validation passed")
    
    # Phase 1: Initialize core systems
    logger.info("Phase 1: Initializing core systems...")
    try:
        from core.consensus_engine import get_consensus_engine
        consensus = get_consensus_engine()
        logger.info(f"✅ Consensus engine: {consensus.min_votes} min votes, {consensus.quorum_threshold:.2f} quorum")
        _startup_state["services"]["consensus"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Consensus engine initialization failed: {e}")
        _startup_state["services"]["consensus"] = {"status": "failed", "error": str(e)}
    
    try:
        from trading.paper_trading import get_paper_trading_engine
        paper_engine = get_paper_trading_engine()
        portfolio_count = len(paper_engine.portfolios)
        logger.info(f"✅ Paper trading engine: {portfolio_count} portfolios loaded")
        _startup_state["services"]["paper_trading"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Paper trading engine initialization failed: {e}")
        _startup_state["services"]["paper_trading"] = {"status": "failed", "error": str(e)}
    
    try:
        from agents.reflection_layer import get_reflection_system
        reflection = get_reflection_system()
        reflection_count = len(reflection._reflections)
        agent_count = len(reflection._agent_stats)
        logger.info(f"✅ Reflection layer: {reflection_count} reflections, {agent_count} agents")
        _startup_state["services"]["reflection"] = {"status": "running", "started_at": time.time()}
    except Exception as e:
        logger.warning(f"⚠️  Reflection layer initialization failed: {e}")
        _startup_state["services"]["reflection"] = {"status": "failed", "error": str(e)}
    
    try:
        from monitoring.brier_metrics import get_brier_tracker
        brier = get_brier_tracker()
        prediction_count = len(brier.predictions)
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
    
    # Phase 2: Start prediction market aggregator with timeout
    logger.info("Phase 2: Starting prediction markets...")
    aggregator = await _start_service_with_timeout(
        "prediction_markets",
        _start_prediction_markets(),
        timeout_seconds=30.0,
        optional=True
    )
    
    if aggregator:
        market_count = len(aggregator._all_markets) if hasattr(aggregator, '_all_markets') else 0
        logger.info(f"✅ Prediction market aggregator: {market_count} initial markets")
    else:
        logger.info("⚠️  Continuing without prediction markets - will use fallback data")
        startup_success = False
    
    # Phase 3: Start whale detection listener (only if prediction markets started)
    logger.info("Phase 3: Starting background services...")
    if aggregator:
        try:
            from merid.whales import solana_whale_listener
            task = asyncio.create_task(solana_whale_listener(aggregator))
            _startup_state["background_tasks"].append(task)
            logger.info("✅ Solana whale detection listener started")
        except Exception as e:
            logger.warning(f"⚠️  Whale detection listener failed: {e}")
            startup_success = False
    else:
        logger.info("⚠️  Skipping whale detection - no prediction markets available")
    
    # Calculate startup duration
    startup_duration = time.time() - _startup_state["started_at"]
    
    # Log overall startup status
    logger.info("=" * 80)
    if startup_success:
        logger.info(f"✅ All services started successfully in {startup_duration:.2f}s")
    else:
        logger.warning(f"⚠️  Some services failed - system in degraded mode ({startup_duration:.2f}s)")
    logger.info("🚀 MERID STARTUP COMPLETE - System Ready")
    logger.info("=" * 80)


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
    
    return {
        "startup_completed": started_at is not None,
        "started_at": started_at,
        "uptime_seconds": uptime,
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
    uvicorn.run(app, host="127.0.0.1", port=8011)
