"""Flow domain REST API — memecoins, whales, KOLs, snipers & MEV.

Endpoints:
  GET  /api/v1/flow/radar          — Full radar summary (tokens + consensus)
  GET  /api/v1/flow/tokens         — All tracked tokens
  GET  /api/v1/flow/token/{id}     — Single token consensus
  GET  /api/v1/flow/entities       — Tracked entities (whales, KOLs, etc.)
  GET  /api/v1/flow/events         — Recent flow events
  GET  /api/v1/flow/plans          — All active plans (meme/whale/kol)
  GET  /api/v1/flow/sniper/status  — Sniper/MEV execution status
  GET  /api/v1/flow/sniper/fills   — Recent sniper fills
  GET  /api/v1/flow/risk           — Risk status
  GET  /api/v1/flow/metrics        — Domain metrics
  POST /api/v1/flow/opinion        — Submit a flow opinion
  POST /api/v1/flow/plan/meme      — Submit a meme plan
  POST /api/v1/flow/plan/whale     — Submit a whale plan
  POST /api/v1/flow/plan/kol       — Submit a KOL plan
  POST /api/v1/flow/ingest         — Trigger ingestion cycle
  POST /api/v1/flow/risk/resume    — Resume halted domain
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Router ────────────────────────────────────────────────────────────

flow_router = APIRouter(prefix="/api/v1/flow", tags=["flow"])


# ── Request models ────────────────────────────────────────────────────

class FlowOpinionRequest(BaseModel):
    agent_id: str
    token_id: str
    token_symbol: str = ""
    chain: str = "solana"
    contract_address: str = ""
    stance: str = "watch"
    probability: float = 0.5
    expected_return_1h: float = 0.0
    expected_return_24h: float = 0.0
    confidence: float = 0.5
    reasoning: str = ""
    driver_event_ids: List[str] = []
    driver_entity_ids: List[str] = []


class MemePlanRequest(BaseModel):
    token_id: str
    token_symbol: str = ""
    chain: str = "solana"
    contract_address: str = ""
    entry_size_usd: float = 50.0
    max_slippage_bps: int = 300
    max_price_impact: float = 0.10
    min_liquidity_usd: float = 10000.0
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 30.0
    max_holding_hours: float = 24.0
    mev_risk_tolerance: str = "low"
    triggered_by: List[str] = []


class WhalePlanRequest(BaseModel):
    token_id: str
    token_symbol: str = ""
    chain: str = "solana"
    contract_address: str = ""
    entity_id: str = ""
    entity_label: str = ""
    whale_action: str = "buy"
    whale_size_usd: float = 0.0
    strategy: str = "follow"
    entry_size_usd: float = 100.0
    max_slippage_bps: int = 200
    max_price_impact: float = 0.03
    take_profit_pct: float = 30.0
    stop_loss_pct: float = 15.0
    max_holding_hours: float = 48.0
    mev_risk_tolerance: str = "medium"
    triggered_by: List[str] = []


class KOLPlanRequest(BaseModel):
    token_id: str
    token_symbol: str = ""
    chain: str = "solana"
    contract_address: str = ""
    entity_id: str = ""
    kol_handle: str = ""
    kol_follower_count: int = 0
    mention_text: str = ""
    mention_sentiment: float = 0.0
    has_onchain_buy: bool = False
    entry_size_usd: float = 25.0
    max_slippage_bps: int = 500
    max_price_impact: float = 0.08
    take_profit_pct: float = 100.0
    stop_loss_pct: float = 40.0
    max_holding_hours: float = 12.0
    mev_risk_tolerance: str = "high"
    triggered_by: List[str] = []


# ── Helpers ───────────────────────────────────────────────────────────

def _get_store():
    from merid.flow.store import get_flow_store
    return get_flow_store()


def _get_ingestion():
    from merid.flow.ingestion import get_ingestion_service
    return get_ingestion_service()


def _get_sniper():
    from merid.flow.sniper import get_sniper_executor
    return get_sniper_executor()


def _get_risk():
    from merid.flow.risk import get_flow_risk
    return get_flow_risk()


def _stub_radar() -> Dict[str, Any]:
    """Generate stub radar data using synthetic ingestion."""
    from merid.flow.ingestion import FlowIngestionService
    from merid.flow.models import compute_flow_score, FlowEventType, FlowStance

    svc = FlowIngestionService()
    data = svc.ingest_all()

    tokens = data["tokens"]
    entities = data["entities"]
    events = data["events"]

    token_summaries = []
    for tok in tokens:
        tok_events = [e for e in events if e.token_id == tok.id]
        whale_buys = sum(1 for e in tok_events if e.event_type == FlowEventType.LARGE_BUY.value)
        whale_sells = sum(1 for e in tok_events if e.event_type == FlowEventType.LARGE_SELL.value)
        kol_buys = sum(1 for e in tok_events if e.event_type == FlowEventType.KOL_BUY.value)
        kol_mentions = sum(1 for e in tok_events if e.event_type == FlowEventType.KOL_MENTION.value)
        lp_adds = sum(1 for e in tok_events if e.event_type == FlowEventType.LP_ADDED.value)
        lp_removes = sum(1 for e in tok_events if e.event_type == FlowEventType.LP_REMOVED.value)

        score = compute_flow_score(
            whale_buys, whale_sells, kol_buys, kol_mentions,
            lp_adds, lp_removes, tok.age_hours,
        )

        # Determine stance from flow score
        if score >= 70:
            stance = FlowStance.SPEC_LONG.value
        elif score >= 55:
            stance = FlowStance.WATCH.value
        elif score >= 40:
            stance = FlowStance.WATCH.value
        else:
            stance = FlowStance.AVOID.value

        token_summaries.append({
            "token_id": tok.id,
            "symbol": tok.symbol,
            "name": tok.name,
            "chain": tok.chain,
            "contract_address": tok.contract_address,
            "liquidity_usd": tok.total_liquidity_usd,
            "price_usd": tok.current_price_usd,
            "age_hours": round(tok.age_hours, 1),
            "flow_score": round(score, 1),
            "event_summary": {
                "total": len(tok_events),
                "whale_buys": whale_buys,
                "whale_sells": whale_sells,
                "kol_buys": kol_buys,
                "kol_mentions": kol_mentions,
                "lp_adds": lp_adds,
                "lp_removes": lp_removes,
            },
            "opinion_summary": {
                "total": 0,
                "stance_distribution": {s.value: 0 for s in FlowStance},
                "dominant_stance": stance,
                "avg_confidence": 0.0,
            },
            "plan_summary": {
                "meme_plans": 0, "whale_plans": 0, "kol_plans": 0, "active_plans": 0,
            },
        })

    token_summaries.sort(key=lambda x: x["flow_score"], reverse=True)

    return {
        "tokens": token_summaries,
        "entities": [e.to_dict() for e in entities],
        "recent_events": [e.to_dict() for e in sorted(events, key=lambda e: e.timestamp, reverse=True)[:20]],
        "source": "stub",
        "token_count": len(tokens),
        "entity_count": len(entities),
        "event_count": len(events),
    }


# ── Endpoints ─────────────────────────────────────────────────────────

@flow_router.get("/radar")
def get_radar(chain: Optional[str] = Query(None)):
    """Full radar summary: tokens + consensus + entities + events."""
    try:
        store = _get_store()
        tokens = store.list_tokens(chain=chain)
        if not tokens:
            return _stub_radar()

        consensus = store.build_all_consensus(chain=chain)
        entities = store.list_entities()
        events = store.list_events(since_hours=24)

        return {
            "tokens": consensus,
            "entities": [e.to_dict() for e in entities],
            "recent_events": [e.to_dict() for e in events[:20]],
            "source": "live",
            "token_count": len(tokens),
            "entity_count": len(entities),
            "event_count": len(events),
        }
    except Exception:
        return _stub_radar()


@flow_router.get("/tokens")
def list_tokens(chain: Optional[str] = Query(None)):
    """List all tracked tokens."""
    try:
        store = _get_store()
        tokens = store.list_tokens(chain=chain)
        if tokens:
            return {"tokens": [t.to_dict() for t in tokens], "source": "live"}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    svc = _get_ingestion()
    data = svc.ingest_all(chain=chain)
    return {
        "tokens": [t.to_dict() for t in data["tokens"]],
        "source": "stub",
    }


@flow_router.get("/token/{token_id}")
def get_token_consensus(token_id: str):
    """Single token consensus view."""
    try:
        store = _get_store()
        consensus = store.build_token_consensus(token_id)
        if consensus:
            return {"consensus": consensus, "source": "live"}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))
    raise HTTPException(status_code=404, detail=f"Token {token_id} not found")


@flow_router.get("/entities")
def list_entities(entity_type: Optional[str] = Query(None)):
    """List tracked entities (whales, KOLs, etc.)."""
    try:
        store = _get_store()
        entities = store.list_entities(entity_type=entity_type)
        if entities:
            return {"entities": [e.to_dict() for e in entities], "source": "live"}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    from merid.flow.ingestion import WhaleTracker
    tracker = WhaleTracker()
    entities = tracker.get_tracked_entities(entity_type=entity_type)
    return {"entities": [e.to_dict() for e in entities], "source": "stub"}


@flow_router.get("/events")
def list_events(
    token_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    since_hours: float = Query(24),
):
    """List recent flow events."""
    try:
        store = _get_store()
        events = store.list_events(
            token_id=token_id, entity_id=entity_id,
            event_type=event_type, since_hours=since_hours,
        )
        if events:
            return {"events": [e.to_dict() for e in events], "source": "live"}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    svc = _get_ingestion()
    data = svc.ingest_all()
    events = data["events"]
    if token_id:
        events = [e for e in events if e.token_id == token_id]
    if entity_id:
        events = [e for e in events if e.entity_id == entity_id]
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    return {"events": [e.to_dict() for e in events[:100]], "source": "stub"}


@flow_router.get("/plans")
def list_plans(plan_type: Optional[str] = Query(None), status: Optional[str] = Query(None)):
    """List active plans (meme/whale/kol)."""
    try:
        store = _get_store()
        result: Dict[str, Any] = {}
        if not plan_type or plan_type == "meme":
            result["meme_plans"] = [p.to_dict() for p in store.list_meme_plans(status=status)]
        if not plan_type or plan_type == "whale":
            result["whale_plans"] = [p.to_dict() for p in store.list_whale_plans(status=status)]
        if not plan_type or plan_type == "kol":
            result["kol_plans"] = [p.to_dict() for p in store.list_kol_plans(status=status)]
        return result
    except Exception:
        return {"meme_plans": [], "whale_plans": [], "kol_plans": []}


@flow_router.get("/sniper/status")
def sniper_status(chain: Optional[str] = Query(None)):
    """Sniper/MEV execution status and route health."""
    sniper = _get_sniper()
    chains = [chain] if chain else ["solana", "ethereum", "base", "arbitrum"]
    route_health = {c: sniper.check_route_health(c) for c in chains}
    return {
        "is_live": sniper.is_live,
        "route_health": route_health,
    }


@flow_router.get("/sniper/fills")
def sniper_fills(limit: int = Query(50)):
    """Recent sniper fills."""
    try:
        store = _get_store()
        fills = store.list_sniper_fills(limit=limit)
        return {"fills": [f.to_dict() for f in fills], "count": len(fills)}
    except Exception:
        return {"fills": [], "count": 0}


@flow_router.get("/risk")
def risk_status():
    """Flow domain risk status."""
    risk = _get_risk()
    return risk.get_status()


@flow_router.get("/metrics")
def flow_metrics():
    """Flow domain aggregate metrics."""
    try:
        store = _get_store()
        return store.get_flow_metrics()
    except Exception:
        return {
            "tokens_tracked": 0, "entities_tracked": 0,
            "whale_count": 0, "kol_count": 0,
            "events_24h": 0, "opinions_total": 0,
            "plans": {"meme": {}, "whale": {}, "kol": {}},
            "sniper": {"total_fills": 0, "success_rate": 0},
        }


@flow_router.post("/opinion")
def submit_opinion(req: FlowOpinionRequest):
    """Submit a flow opinion from an agent."""
    from merid.flow.models import FlowOpinion
    store = _get_store()
    opinion = FlowOpinion(
        agent_id=req.agent_id, token_id=req.token_id,
        token_symbol=req.token_symbol, chain=req.chain,
        contract_address=req.contract_address,
        stance=req.stance, probability=req.probability,
        expected_return_1h=req.expected_return_1h,
        expected_return_24h=req.expected_return_24h,
        confidence=req.confidence, reasoning=req.reasoning,
        driver_event_ids=req.driver_event_ids,
        driver_entity_ids=req.driver_entity_ids,
    )
    store.add_opinion(opinion)
    return {"status": "ok", "opinion_id": opinion.id}


@flow_router.post("/plan/meme")
def submit_meme_plan(req: MemePlanRequest):
    """Submit a meme plan."""
    from merid.flow.models import MemePlan
    store = _get_store()
    plan = MemePlan(
        token_id=req.token_id, token_symbol=req.token_symbol,
        chain=req.chain, contract_address=req.contract_address,
        entry_size_usd=req.entry_size_usd,
        max_slippage_bps=req.max_slippage_bps,
        max_price_impact=req.max_price_impact,
        min_liquidity_usd=req.min_liquidity_usd,
        take_profit_pct=req.take_profit_pct,
        stop_loss_pct=req.stop_loss_pct,
        max_holding_hours=req.max_holding_hours,
        mev_risk_tolerance=req.mev_risk_tolerance,
        triggered_by=req.triggered_by,
    )
    store.add_meme_plan(plan)
    return {"status": "ok", "plan_id": plan.id, "plan_type": "meme"}


@flow_router.post("/plan/whale")
def submit_whale_plan(req: WhalePlanRequest):
    """Submit a whale plan."""
    from merid.flow.models import WhalePlan
    store = _get_store()
    plan = WhalePlan(
        token_id=req.token_id, token_symbol=req.token_symbol,
        chain=req.chain, contract_address=req.contract_address,
        entity_id=req.entity_id, entity_label=req.entity_label,
        whale_action=req.whale_action, whale_size_usd=req.whale_size_usd,
        strategy=req.strategy, entry_size_usd=req.entry_size_usd,
        max_slippage_bps=req.max_slippage_bps,
        max_price_impact=req.max_price_impact,
        take_profit_pct=req.take_profit_pct,
        stop_loss_pct=req.stop_loss_pct,
        max_holding_hours=req.max_holding_hours,
        mev_risk_tolerance=req.mev_risk_tolerance,
        triggered_by=req.triggered_by,
    )
    store.add_whale_plan(plan)
    return {"status": "ok", "plan_id": plan.id, "plan_type": "whale"}


@flow_router.post("/plan/kol")
def submit_kol_plan(req: KOLPlanRequest):
    """Submit a KOL plan."""
    from merid.flow.models import KOLPlan
    store = _get_store()
    plan = KOLPlan(
        token_id=req.token_id, token_symbol=req.token_symbol,
        chain=req.chain, contract_address=req.contract_address,
        entity_id=req.entity_id, kol_handle=req.kol_handle,
        kol_follower_count=req.kol_follower_count,
        mention_text=req.mention_text,
        mention_sentiment=req.mention_sentiment,
        has_onchain_buy=req.has_onchain_buy,
        entry_size_usd=req.entry_size_usd,
        max_slippage_bps=req.max_slippage_bps,
        max_price_impact=req.max_price_impact,
        take_profit_pct=req.take_profit_pct,
        stop_loss_pct=req.stop_loss_pct,
        max_holding_hours=req.max_holding_hours,
        mev_risk_tolerance=req.mev_risk_tolerance,
        triggered_by=req.triggered_by,
    )
    store.add_kol_plan(plan)
    return {"status": "ok", "plan_id": plan.id, "plan_type": "kol"}


@flow_router.post("/ingest")
def trigger_ingest(chain: Optional[str] = Query(None)):
    """Trigger a full ingestion cycle."""
    try:
        svc = _get_ingestion()
        data = svc.ingest_all(chain=chain)
        store = _get_store()

        # Persist
        for tok in data["tokens"]:
            store.upsert_token(tok)
        for ent in data["entities"]:
            store.upsert_entity(ent)
        for ev in data["events"]:
            store.add_event(ev)

        return {
            "status": "ok",
            "source": data["source"],
            "tokens_ingested": data["token_count"],
            "entities_ingested": data["entity_count"],
            "events_ingested": data["event_count"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@flow_router.post("/risk/resume")
def resume_risk():
    """Resume halted flow domain."""
    risk = _get_risk()
    risk.resume()
    return {"status": "ok", "state": risk.state.to_dict()}
