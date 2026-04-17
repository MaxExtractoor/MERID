"""Betting Consensus API — Swarm-driven sports & event betting endpoints.

Endpoints:
- GET  /api/v1/betting/consensus/summary     — All events with merged consensus
- GET  /api/v1/betting/consensus/live/{id}    — Single event live consensus
- GET  /api/v1/betting/consensus/events       — Raw event list
- GET  /api/v1/betting/consensus/plans        — Betting plans
- GET  /api/v1/betting/consensus/metrics      — Betting performance metrics
- POST /api/v1/betting/consensus/opinion      — Submit swarm opinion on event
- POST /api/v1/betting/consensus/plan         — Submit a betting plan
- POST /api/v1/betting/consensus/settle       — Settle a bet
- GET  /api/v1/betting/consensus/plan-check   — Check plan executability
- POST /api/v1/betting/consensus/ingest       — Trigger odds ingestion

All endpoints follow real-first, stub-fallback pattern.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.betting_consensus")

router = APIRouter(prefix="/api/v1/betting/consensus", tags=["betting-consensus"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_store():
    try:
        from merid.betting.store import get_betting_store
        return get_betting_store()
    except Exception as exc:
        logger.debug(f"BettingStore unavailable: {exc}")
        return None


def _get_odds_client():
    try:
        from merid.betting.odds_client import get_odds_client
        return get_odds_client()
    except Exception as exc:
        logger.debug(f"OddsAPIClient unavailable: {exc}")
        return None


def _stub(data: Dict[str, Any], *, message: str = "Simulated betting data") -> Dict[str, Any]:
    data["_stub"] = True
    data["_implementation_status"] = "NOT_IMPLEMENTED"
    data["_stub_message"] = message
    return data


# ── Request models ───────────────────────────────────────────────────

class BettingOpinionRequest(BaseModel):
    agent_id: str
    event_id: str
    outcome_id: str
    probability: float
    confidence: float = 0.5
    reasoning: str = ""


class BettingPlanRequest(BaseModel):
    event_id: str
    outcome_id: str
    outcome_name: str = ""
    market_type: str = "moneyline"
    direction: str = "back"
    stake_usd: float = 100.0
    min_edge_vs_books: float = 0.03
    confidence: float = 0.5
    supporting_agents: List[str] = []


class SettleBetRequest(BaseModel):
    bet_id: str
    event_id: str
    outcome_id: str
    stake_usd: float
    placed_odds: float
    result: str  # won / lost / push
    pnl_usd: float = 0.0


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/summary")
async def betting_consensus_summary(
    sport: Optional[str] = None,
    state: Optional[str] = None,
):
    """All events with merged consensus: sportsbook + prediction market + swarm."""
    store = _get_store()
    if store:
        try:
            # Ensure events are seeded (from odds client)
            _ensure_events_seeded(store)
            consensuses = store.build_all_consensus(sport=sport, state=state)
            return {
                "events": [c.to_dict() for c in consensuses],
                "count": len(consensuses),
                "live_count": sum(1 for c in consensuses if c.state == "live"),
            }
        except Exception as exc:
            logger.warning(f"betting/consensus/summary failed: {exc}")

    return _stub({
        "events": _stub_consensus_list(),
        "count": 4,
        "live_count": 1,
    })


@router.get("/live")
async def betting_live_all(
    sport: Optional[str] = None,
):
    """All live/upcoming events with consensus — used by SportsLiveView dashboard."""
    store = _get_store()
    if store:
        try:
            _ensure_events_seeded(store)
            consensuses = store.build_all_consensus(sport=sport, state=None)
            events = []
            live_odds: List[Dict[str, Any]] = []
            anomalies: List[Dict[str, Any]] = []
            for c in consensuses:
                d = c.to_dict()
                events.append({
                    "event_id": d.get("event_id", ""),
                    "sport": d.get("sport", ""),
                    "league": d.get("league", ""),
                    "home_team": d.get("home_team", d.get("event_id", "")),
                    "away_team": d.get("away_team", ""),
                    "start_time": d.get("start_time", 0),
                    "is_live": d.get("state") == "live",
                    "status": d.get("state", "upcoming"),
                })
            return {
                "events": events,
                "live_odds": live_odds,
                "anomalies": anomalies,
                "stats": {
                    "total_events": len(events),
                    "live_events": sum(1 for e in events if e["is_live"]),
                    "total_anomalies": 0,
                    "unacknowledged": 0,
                },
            }
        except Exception as exc:
            logger.warning(f"betting/consensus/live failed: {exc}")

    return {
        "events": [],
        "live_odds": [],
        "anomalies": [],
        "stats": {"total_events": 0, "live_events": 0, "total_anomalies": 0, "unacknowledged": 0},
    }


@router.get("/live/{event_id}")
async def betting_live_consensus(event_id: str):
    """Single event live consensus — for drill-down and in-play view."""
    store = _get_store()
    if store:
        try:
            consensus = store.build_consensus(event_id)
            if consensus:
                return consensus.to_dict()
            raise HTTPException(404, f"Event {event_id} not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"betting/live/{event_id} failed: {exc}")

    raise HTTPException(404, f"Event {event_id} not found")


@router.get("/events")
async def betting_events(
    sport: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
):
    """Raw event list."""
    store = _get_store()
    if store:
        try:
            _ensure_events_seeded(store)
            events = store.list_events(sport=sport, state=state, limit=limit)
            return {"events": [e.to_dict() for e in events], "count": len(events)}
        except Exception as exc:
            logger.warning(f"betting/events failed: {exc}")

    return _stub({"events": [], "count": 0})


@router.get("/plans")
async def betting_plans(
    event_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List betting plans."""
    store = _get_store()
    if store:
        try:
            plans = store.list_plans(event_id=event_id, status=status, limit=limit)
            return {"plans": [p.to_dict() for p in plans], "count": len(plans)}
        except Exception as exc:
            logger.warning(f"betting/plans failed: {exc}")

    return _stub({"plans": [], "count": 0})


@router.get("/metrics")
async def betting_metrics():
    """Betting performance metrics: win rate, ROI, PnL, exposure."""
    store = _get_store()
    if store:
        try:
            metrics = store.get_betting_metrics()
            return metrics
        except Exception as exc:
            logger.warning(f"betting/metrics failed: {exc}")

    return _stub({
        "total_bets": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "total_staked_usd": 0.0,
        "total_pnl_usd": 0.0, "roi": 0.0,
        "active_events": 0, "live_events": 0,
        "plans": {"proposed": 0, "approved": 0, "executing": 0, "placed": 0, "settled": 0},
    })


@router.post("/opinion")
async def submit_betting_opinion(req: BettingOpinionRequest):
    """Submit a swarm agent opinion on a betting event outcome."""
    if not 0.0 <= req.probability <= 1.0:
        raise HTTPException(400, "probability must be between 0 and 1")

    store = _get_store()
    if not store:
        raise HTTPException(503, "BettingStore unavailable")

    oid = store.add_swarm_opinion(
        agent_id=req.agent_id, event_id=req.event_id,
        outcome_id=req.outcome_id, probability=req.probability,
        confidence=req.confidence, reasoning=req.reasoning,
    )
    return {"status": "ok", "opinion_id": oid}


@router.post("/plan")
async def submit_betting_plan(req: BettingPlanRequest):
    """Submit a betting plan."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "BettingStore unavailable")

    from merid.betting.models import LiveBetPlan
    plan = LiveBetPlan(
        event_id=req.event_id, outcome_id=req.outcome_id,
        outcome_name=req.outcome_name, market_type=req.market_type,
        direction=req.direction, stake_usd=req.stake_usd,
        min_edge_vs_books=req.min_edge_vs_books,
        confidence=req.confidence, supporting_agents=req.supporting_agents,
    )
    store.add_plan(plan)
    return {"status": "ok", "plan": plan.to_dict()}


@router.post("/settle")
async def settle_bet(req: SettleBetRequest):
    """Settle a bet with outcome."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "BettingStore unavailable")

    if req.result not in ("won", "lost", "push"):
        raise HTTPException(400, "result must be won, lost, or push")

    from merid.betting.models import SettledBet
    sb = SettledBet(
        bet_id=req.bet_id, event_id=req.event_id,
        outcome_id=req.outcome_id, stake_usd=req.stake_usd,
        placed_odds=req.placed_odds, result=req.result,
        pnl_usd=req.pnl_usd,
    )
    store.settle_bet(sb)

    # Emit notification
    try:
        from core.notifications import add_notification
        add_notification(
            title=f"Bet settled: {req.result}",
            message=f"Event {req.event_id}, PnL: ${req.pnl_usd:.2f}",
            level="info", category="betting",
            metadata={"bet_id": req.bet_id, "result": req.result, "pnl_usd": req.pnl_usd},
        )
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    return {"status": "ok", "settled": sb.to_dict()}


@router.get("/plan-check")
async def check_plan_executable(plan_id: str):
    """Check if a betting plan should execute."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "BettingStore unavailable")

    plans = store.list_plans(limit=500)
    plan = next((p for p in plans if p.id == plan_id), None)
    if not plan:
        raise HTTPException(404, f"Plan {plan_id} not found")

    result = store.check_plan_executable(plan)
    return {"plan_id": plan_id, **result}


@router.post("/ingest")
async def trigger_odds_ingestion(sport: Optional[str] = None):
    """Trigger odds ingestion from the configured odds API."""
    store = _get_store()
    client = _get_odds_client()
    if not store or not client:
        raise HTTPException(503, "BettingStore or OddsAPIClient unavailable")

    try:
        results = client.fetch_all_odds(sport=sport)
        for ev, snap in results:
            store.upsert_event(ev)
            store.store_odds_snapshot(snap)
        return {
            "status": "ok",
            "events_ingested": len(results),
            "source": "live" if client.is_configured else "synthetic",
        }
    except Exception as exc:
        raise HTTPException(500, f"Ingestion failed: {exc}")


# ── Helpers ──────────────────────────────────────────────────────────

_seeded = False


def _ensure_events_seeded(store) -> None:
    """Seed synthetic events on first access if store is empty."""
    global _seeded
    if _seeded:
        return
    _seeded = True

    if store.event_count() > 0:
        return

    client = _get_odds_client()
    if not client:
        return

    try:
        results = client.fetch_all_odds()
        for ev, snap in results:
            store.upsert_event(ev)
            store.store_odds_snapshot(snap)
        logger.info(f"Seeded {len(results)} betting events")
    except Exception as exc:
        logger.warning(f"Failed to seed events: {exc}")


def _stub_consensus_list() -> List[Dict]:
    """Stub consensus data for development."""
    now = time.time()
    return [
        {
            "event_id": "nfl-sb-2026",
            "event": {
                "id": "nfl-sb-2026", "sport": "nfl", "league": "NFL",
                "title": "Kansas City Chiefs @ San Francisco 49ers",
                "state": "pre", "start_time": now + 86400 * 7,
                "home_team": "San Francisco 49ers", "away_team": "Kansas City Chiefs",
            },
            "sportsbook_consensus_prob": {"nfl-sb-h": 0.50, "nfl-sb-a": 0.50},
            "swarm_prob": {"nfl-sb-h": 0.55, "nfl-sb-a": 0.45},
            "edge_vs_books": {"nfl-sb-h": 0.05, "nfl-sb-a": -0.05},
            "stance": "weak_yes", "max_edge": 0.05,
            "state": "pre", "book_count": 5,
            "swarm_confidence": 0.72, "swarm_opinion_count": 6,
            "swarm_supporting_agents": 4, "swarm_opposing_agents": 2,
            "active_plans": {"proposed": 1, "approved": 0, "executing": 0},
            "arbitrage_flag": False,
        },
        {
            "event_id": "nba-gsw-den",
            "event": {
                "id": "nba-gsw-den", "sport": "nba", "league": "NBA",
                "title": "Denver Nuggets @ Golden State Warriors",
                "state": "live", "start_time": now - 3600,
                "score_home": 67, "score_away": 72, "period": "Q3", "clock": "4:23",
            },
            "sportsbook_consensus_prob": {"nba-gd-h": 0.42, "nba-gd-a": 0.58},
            "swarm_prob": {"nba-gd-h": 0.38, "nba-gd-a": 0.62},
            "edge_vs_books": {"nba-gd-h": -0.04, "nba-gd-a": 0.04},
            "stance": "weak_yes", "max_edge": 0.04,
            "state": "live", "book_count": 3,
            "swarm_confidence": 0.65, "swarm_opinion_count": 4,
            "swarm_supporting_agents": 3, "swarm_opposing_agents": 1,
            "active_plans": {"proposed": 0, "approved": 0, "executing": 0},
            "arbitrage_flag": False,
        },
    ]
