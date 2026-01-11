from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Deque, Dict, Optional

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Header,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from audit.exporter import export_trail
from backtesting.replay import run_backtest
from backtesting.replayer import run_deterministic_replay
from core.energy import create_energy
from core.event_bus import event_stream
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
from web.api.reflection import router as reflection_router
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
from web.api.agents import router as agents_router
from web.api.governance import router as governance_router
from web.api.ops import router as ops_router
from web.api.archive import router as archive_router

root_router = APIRouter()
router = APIRouter(prefix="/api")
router_v1 = APIRouter(prefix="/api/v1")
_app_context: Dict[str, Any] = {}


def _context_value(key: str) -> Any:
    try:
        return _app_context[key]
    except KeyError as exc:
        raise RuntimeError(
            f"Application context missing '{key}'. Ensure create_app() was called before importing routes."
        ) from exc


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
    
    # Mount static files
    application.mount("/static", StaticFiles(directory="web/static"), name="static")
    
    templates = Jinja2Templates(directory="web/templates")
    simulation_chain = build_simulation_chain(
        use_mock=str(os.getenv("MERID_POLYMARKET_MOCK", "")).lower() in {"1", "true", "yes"}
    )
    context = {
        "simulation_chain": simulation_chain,
        "merid": get_core(),
        "logger": get_logger("web.main"),
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
    application.include_router(agents_router)
    application.include_router(governance_router)
    application.include_router(ops_router)
    application.include_router(archive_router)
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
    queue = await event_stream.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        await event_stream.unsubscribe(queue)
    except Exception:
        await event_stream.unsubscribe(queue)


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

    class Config:
        allow_population_by_field_name = True


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

@root_router.get("/dashboard")
async def dashboard(request: Request):
    """Unified control center - combines dashboard and institutional views."""
    templates = _templates()
    return templates.TemplateResponse("unified.html", {"request": request})

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
app = create_app()

# Initialize and start agent orchestrator on startup
@app.on_event("startup")
async def startup_event():
    """Initialize system on startup."""
    from core.agent_orchestrator import get_agent_orchestrator
    from core.consensus_engine import get_consensus_engine
    from utils.logger import get_logger
    import asyncio
    
    startup_logger = get_logger("web.main.startup")
    startup_logger.info("Initializing MERID agent orchestrator...")
    orchestrator = get_agent_orchestrator()
    
    # Start orchestrator in background
    asyncio.create_task(orchestrator.start())
    
    # Start consensus engine
    startup_logger.info("Starting consensus engine...")
    consensus = get_consensus_engine()
    asyncio.create_task(consensus.start())
    
    # Start continuous simulation miner
    startup_logger.info("Starting simulation miner...")
    from simulation.continuous_miner import get_continuous_miner
    miner = get_continuous_miner()
    asyncio.create_task(miner.start())
    
    # Start audit trail
    startup_logger.info("Starting audit trail...")
    from core.audit_trail import get_audit_trail
    audit = get_audit_trail()
    asyncio.create_task(audit.start())
    
    # Start execution engine
    startup_logger.info("Starting execution engine...")
    from trading.execution import get_execution_engine
    execution = get_execution_engine()
    asyncio.create_task(execution.start())
    
    # Start streaming agent mesh (8 mandatory agents)
    startup_logger.info("Starting streaming agent mesh...")
    from agents.agent_mesh import agent_mesh
    asyncio.create_task(agent_mesh.initialize())
    asyncio.create_task(agent_mesh.start())
    
    # Start prediction markets aggregator
    startup_logger.info("Starting prediction markets aggregator...")
    from monitoring.prediction_markets import get_prediction_aggregator
    prediction_agg = get_prediction_aggregator()
    asyncio.create_task(prediction_agg.start())
    
    # Start alert manager and wire to price feed
    startup_logger.info("Starting alert manager...")
    from core.alerts import get_alert_manager
    from data.live_price_feed import get_live_price_feed
    alert_mgr = get_alert_manager()
    asyncio.create_task(alert_mgr.start())
    
    # Wire alerts to live price feed
    price_feed = get_live_price_feed()
    def on_price_update(price_data):
        alert_mgr.update_price(price_data.symbol, price_data.price)
    price_feed.subscribe(on_price_update)
    
    # Start health monitor
    startup_logger.info("Starting health monitor...")
    from core.health import get_health_monitor
    health_mon = get_health_monitor()
    asyncio.create_task(health_mon.start())
    
    startup_logger.info("MERID system started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    from core.agent_orchestrator import get_agent_orchestrator
    from core.consensus_engine import get_consensus_engine
    from simulation.continuous_miner import get_continuous_miner
    from core.audit_trail import get_audit_trail
    from trading.execution import get_execution_engine
    from agents.agent_mesh import agent_mesh
    from monitoring.prediction_markets import get_prediction_aggregator
    from core.alerts import get_alert_manager
    from core.health import get_health_monitor
    from utils.logger import get_logger
    
    shutdown_logger = get_logger("web.main.shutdown")
    shutdown_logger.info("Shutting down MERID system...")
    
    # Stop health monitor
    health_mon = get_health_monitor()
    await health_mon.stop()
    
    # Stop alert manager
    alert_mgr = get_alert_manager()
    await alert_mgr.stop()
    
    # Stop prediction markets
    prediction_agg = get_prediction_aggregator()
    await prediction_agg.stop()
    
    # Stop streaming agent mesh
    await agent_mesh.stop()
    
    # Stop execution engine
    execution = get_execution_engine()
    await execution.stop()
    
    # Stop audit trail (to capture final events)
    audit = get_audit_trail()
    await audit.stop()
    
    # Stop simulation miner
    miner = get_continuous_miner()
    await miner.stop()
    
    # Stop consensus engine
    consensus = get_consensus_engine()
    await consensus.stop()
    
    # Stop orchestrator
    orchestrator = get_agent_orchestrator()
    orchestrator.stop()
    shutdown_logger.info("MERID system stopped")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
