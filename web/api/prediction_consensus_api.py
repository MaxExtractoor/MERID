"""Prediction Market Consensus API — Swarm vs Kalshi odds, Brier scores, plans.

Endpoints:
- GET  /api/v1/prediction/consensus/summary    — Per-symbol swarm vs market consensus
- GET  /api/v1/prediction/consensus/opinions    — Recent prediction opinions
- GET  /api/v1/prediction/consensus/plans       — Prediction trade plans
- GET  /api/v1/prediction/consensus/instruments — Active prediction instruments
- GET  /api/v1/prediction/metrics               — Brier scores + calibration
- POST /api/v1/prediction/consensus/opinions    — Submit a prediction opinion
- POST /api/v1/prediction/consensus/plans       — Submit a prediction plan
- POST /api/v1/prediction/consensus/resolve     — Record a market resolution
- GET  /api/v1/prediction/consensus/plan-check  — Check if a plan is executable

All endpoints follow real-first, stub-fallback pattern.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("web.api.prediction_consensus")

router = APIRouter(prefix="/api/v1/prediction", tags=["prediction-consensus"])


# ── Helpers ──────────────────────────────────────────────────────────

def _get_store():
    """Get the PredictionConsensusStore, or None if unavailable."""
    try:
        from merid.prediction.consensus import get_prediction_consensus_store
        return get_prediction_consensus_store()
    except Exception as exc:
        logger.debug("PredictionConsensusStore unavailable: %s", exc)
        return None


def _get_debate_store():
    """Get the DebateStore, or None if unavailable."""
    try:
        from merid.prediction.debate import get_debate_store
        return get_debate_store()
    except Exception as exc:
        logger.debug("DebateStore unavailable: %s", exc)
        return None


def _stub(data: Dict[str, Any], *, message: str = "Simulated prediction data") -> Dict[str, Any]:
    data["_stub"] = True
    data["_implementation_status"] = "NOT_IMPLEMENTED"
    data["_stub_message"] = message
    return data


# ── Request models ───────────────────────────────────────────────────

class PredictionOpinionRequest(BaseModel):
    agent_id: str
    agent_name: str = ""
    symbol: str
    probability: float  # 0–1
    confidence: float = 0.5
    reasoning: str = ""
    signal_sources: List[str] = []
    horizon: str = "event"
    explanation: Optional[Dict[str, Any]] = None


class PredictionPlanRequest(BaseModel):
    symbol: str
    direction: str = "yes"
    target_size_usd: float = 100.0
    max_edge_threshold: float = 0.05
    confidence: float = 0.5
    supporting_agents: List[str] = []
    opposing_agents: List[str] = []
    max_spread_cents: Optional[float] = None
    min_liquidity: Optional[float] = None
    cutoff_hours_before_expiry: float = 1.0


class ResolveRequest(BaseModel):
    symbol: str
    outcome: int  # 1 = YES, 0 = NO
    pnl_usd: float = 0.0


class CreateTeamRequest(BaseModel):
    name: str
    member_ids: List[str]
    strategy_mix: str = ""


class RunDebateRequest(BaseModel):
    symbol: str
    ticker: str
    market_prob: float
    category: str = ""
    proposer_strategy: str = "mean_reversion"
    arbiter_strategy: str = "arbiter"
    proposer_agent_id: str = "proposer-01"
    challenger_agent_id: str = "challenger-01"
    arbiter_agent_id: str = "debate-coordinator-01"
    team_id: str = ""


class BacktestRequest(BaseModel):
    markets: List[Dict[str, Any]]
    proposer_strategy: str = "mean_reversion"
    arbiter_strategy: str = "arbiter"


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/consensus/summary")
async def prediction_consensus_summary(category: Optional[str] = None):
    """Per-symbol prediction consensus: swarm_prob vs market_prob, edge, stance."""
    store = _get_store()
    if store:
        try:
            summaries = await run_in_threadpool(store.get_consensus_summary, category)
            return {"symbols": summaries, "count": len(summaries)}
        except Exception as exc:
            logger.warning("consensus/summary failed, falling back to stub: %s", exc)

    return _stub({
        "symbols": [
            {
                "symbol": "PRED:KALSHI:FED-25MAR-T4.50:YES",
                "venue": "kalshi",
                "event_id": "FED-25MAR",
                "ticker": "FED-25MAR-T4.50",
                "outcome": "YES",
                "category": "macro",
                "title": "Fed holds rates at 4.50% in March 2025",
                "expiry": "2025-03-19T18:00:00+00:00",
                "swarm_prob": 0.72,
                "market_prob": 0.65,
                "edge": 0.07,
                "stance": "weak_yes",
                "confidence": 0.68,
                "supporting_agents": 4,
                "opposing_agents": 1,
                "active_plans": {"proposed": 1, "approved": 0, "executing": 0},
                "opinion_count": 5,
                "volume": 12500.0,
            },
            {
                "symbol": "PRED:KALSHI:BTCUSD-25MAR-100K:YES",
                "venue": "kalshi",
                "event_id": "BTCUSD-25MAR",
                "ticker": "BTCUSD-25MAR-100K",
                "outcome": "YES",
                "category": "crypto",
                "title": "Bitcoin above $100K on March 31",
                "expiry": "2025-03-31T23:59:59+00:00",
                "swarm_prob": 0.45,
                "market_prob": 0.52,
                "edge": -0.07,
                "stance": "weak_no",
                "confidence": 0.55,
                "supporting_agents": 2,
                "opposing_agents": 3,
                "active_plans": {"proposed": 0, "approved": 1, "executing": 0},
                "opinion_count": 5,
                "volume": 8200.0,
            },
        ],
        "count": 2,
    })


@router.get("/consensus/opinions")
async def prediction_opinions(
    symbol: Optional[str] = None,
    limit: int = 50,
    include_explanation: bool = Query(False, description="Include explanation metadata in response"),
):
    """List recent prediction opinions, optionally filtered by symbol."""
    store = _get_store()
    if store:
        try:
            opinions = store.list_opinions(symbol=symbol, limit=limit)
            return {
                "opinions": [o.to_dict(include_explanation=include_explanation) for o in opinions],
                "count": len(opinions),
            }
        except Exception as exc:
            logger.warning("consensus/opinions failed: %s", exc)

    return _stub({
        "opinions": [],
        "count": 0,
    })


@router.get("/consensus/plans")
async def prediction_plans(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List prediction trade plans."""
    store = _get_store()
    if store:
        try:
            plans = store.list_plans(symbol=symbol, status=status, limit=limit)
            return {"plans": [p.to_dict() for p in plans], "count": len(plans)}
        except Exception as exc:
            logger.warning("consensus/plans failed: %s", exc)

    return _stub({"plans": [], "count": 0})


@router.get("/consensus/instruments")
async def prediction_instruments(
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 200,
):
    """List active prediction instruments in MERID's universe."""
    store = _get_store()
    if store:
        try:
            instruments = store.list_instruments(status=status, category=category, limit=limit)
            return {
                "instruments": [i.to_dict() for i in instruments],
                "count": len(instruments),
                "total_active": store.instrument_count(status="active"),
            }
        except Exception as exc:
            logger.warning("consensus/instruments failed: %s", exc)

    return _stub({"instruments": [], "count": 0, "total_active": 0})


@router.get("/metrics")
async def prediction_metrics(window: int = 50):
    """Brier scores, calibration, and agent leaderboard for resolved prediction markets."""
    store = _get_store()
    if store:
        try:
            brier = store.compute_brier_scores(window=window)
            instruments = store.instrument_count()
            active = store.instrument_count(status="active")
            plans = store.list_plans(limit=200)
            plan_counts = {"proposed": 0, "approved": 0, "executing": 0, "closed": 0}
            for p in plans:
                if p.status in plan_counts:
                    plan_counts[p.status] += 1

            return {
                "brier": brier,
                "universe": {
                    "total_instruments": instruments,
                    "active_instruments": active,
                },
                "plans": plan_counts,
            }
        except Exception as exc:
            logger.warning("prediction/metrics failed: %s", exc)

    return _stub({
        "brier": {
            "swarm_brier": 0.22,
            "market_brier": 0.25,
            "swarm_vs_market": "better",
            "agent_briers": {},
            "agent_ranking": [],
            "resolved_count": 0,
            "total_pnl_usd": 0.0,
            "calibration": [],
        },
        "universe": {"total_instruments": 0, "active_instruments": 0},
        "plans": {"proposed": 0, "approved": 0, "executing": 0, "closed": 0},
    })


@router.post("/consensus/opinions")
async def submit_prediction_opinion(req: PredictionOpinionRequest):
    """Submit a probabilistic opinion on a prediction market."""
    if not 0.0 <= req.probability <= 1.0:
        raise HTTPException(400, "probability must be between 0 and 1")
    if not 0.0 <= req.confidence <= 1.0:
        raise HTTPException(400, "confidence must be between 0 and 1")

    store = _get_store()
    if not store:
        raise HTTPException(503, "PredictionConsensusStore unavailable")

    from merid.prediction.consensus import PredictionOpinion
    op = PredictionOpinion(
        agent_id=req.agent_id,
        agent_name=req.agent_name,
        symbol=req.symbol,
        probability=req.probability,
        confidence=req.confidence,
        reasoning=req.reasoning,
        signal_sources=req.signal_sources,
        horizon=req.horizon,
        explanation=req.explanation,
    )
    store.add_opinion(op)
    return {"status": "ok", "opinion": op.to_dict()}


@router.post("/consensus/plans")
async def submit_prediction_plan(req: PredictionPlanRequest):
    """Submit a prediction trade plan."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "PredictionConsensusStore unavailable")

    from merid.prediction.consensus import PredictionPlan
    plan = PredictionPlan(
        symbol=req.symbol,
        direction=req.direction,
        target_size_usd=req.target_size_usd,
        max_edge_threshold=req.max_edge_threshold,
        confidence=req.confidence,
        supporting_agents=req.supporting_agents,
        opposing_agents=req.opposing_agents,
        max_spread_cents=req.max_spread_cents,
        min_liquidity=req.min_liquidity,
        cutoff_hours_before_expiry=req.cutoff_hours_before_expiry,
    )
    store.add_plan(plan)
    return {"status": "ok", "plan": plan.to_dict()}


@router.post("/consensus/resolve")
async def resolve_prediction_market(req: ResolveRequest):
    """Record a prediction market resolution (YES=1, NO=0)."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "PredictionConsensusStore unavailable")

    if req.outcome not in (0, 1):
        raise HTTPException(400, "outcome must be 0 or 1")

    from merid.prediction.consensus import ResolvedMarket
    rm = ResolvedMarket(
        symbol=req.symbol,
        outcome=req.outcome,
        pnl_usd=req.pnl_usd,
    )
    store.record_resolution(rm)

    # Emit notification
    try:
        from core.notifications import add_notification
        add_notification(
            title=f"Prediction market resolved: {req.symbol}",
            message=f"Outcome: {'YES' if req.outcome == 1 else 'NO'}, PnL: ${req.pnl_usd:.2f}",
            level="info",
            category="prediction",
            metadata={
                "symbol": req.symbol,
                "outcome": req.outcome,
                "pnl_usd": req.pnl_usd,
            },
        )
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    return {"status": "ok", "resolved": rm.to_dict()}


@router.get("/consensus/explainability")
async def prediction_explainability(window_s: float = 3600.0):
    """Explainability metrics for recent prediction opinions."""
    store = _get_store()
    if store:
        try:
            metrics = store.get_explainability_metrics(window_s=window_s)
            return metrics
        except Exception as exc:
            logger.warning("consensus/explainability failed: %s", exc)

    return {"coverage": {"total": 0, "with_explanation": 0, "pct": 0.0},
            "rationale_distribution": {}, "strategy_variety": {},
            "stability": {"instruments_checked": 0, "flips": 0, "flip_rate": 0.0},
            "window_s": window_s}


@router.get("/consensus/plan-check")
async def check_plan_executable(plan_id: str):
    """Check if a prediction plan should execute given current market conditions."""
    store = _get_store()
    if not store:
        raise HTTPException(503, "PredictionConsensusStore unavailable")

    plans = store.list_plans(limit=500)
    plan = next((p for p in plans if p.id == plan_id), None)
    if not plan:
        raise HTTPException(404, f"Plan {plan_id} not found")

    result = store.check_plan_executable(plan)
    return {"plan_id": plan_id, **result}


# ── Debate, Team & Reward endpoints ─────────────────────────────────

@router.post("/consensus/debates")
async def run_debate(req: RunDebateRequest):
    """Run a structured proposer→challenger→arbiter debate on an instrument."""
    from merid.agents.coordination import DebateCoordinatorAgent

    coordinator = DebateCoordinatorAgent()
    instrument = {
        "symbol": req.symbol,
        "ticker": req.ticker,
        "market_prob": req.market_prob,
        "category": req.category,
    }
    context = {
        "proposer_strategy": req.proposer_strategy,
        "arbiter_strategy": req.arbiter_strategy,
        "proposer_agent_id": req.proposer_agent_id,
        "challenger_agent_id": req.challenger_agent_id,
        "arbiter_agent_id": req.arbiter_agent_id,
        "team_id": req.team_id,
    }
    result = coordinator.run_debate(instrument, context)
    if not result:
        raise HTTPException(422, "Debate produced no result (strategy declined to opine)")
    return {"status": "ok", "debate": result}


@router.get("/consensus/debates")
async def list_debates(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List debate sessions, optionally filtered by symbol or status."""
    ds = _get_debate_store()
    if not ds:
        return _stub({"debates": [], "count": 0})
    try:
        debates = ds.list_debates(symbol=symbol, status=status, limit=limit)
        return {"debates": [d.to_dict() for d in debates], "count": len(debates)}
    except Exception as exc:
        logger.warning("consensus/debates failed: %s", exc)
        return {"debates": [], "count": 0}


@router.get("/consensus/debates/{debate_id}")
async def get_debate_detail(debate_id: str):
    """Get a debate session with its arguments."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    debate = ds.get_debate(debate_id)
    if not debate:
        raise HTTPException(404, f"Debate {debate_id} not found")
    args = ds.list_arguments(debate_id)
    return {
        "debate": debate.to_dict(),
        "arguments": [a.to_dict() for a in args],
    }


@router.post("/consensus/debates/{debate_id}/resolve")
async def resolve_debate(debate_id: str, outcome: int = Query(..., ge=0, le=1)):
    """Resolve a debate with the actual outcome and compute debate lift."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    debate = ds.resolve_debate(debate_id, outcome)
    if not debate:
        raise HTTPException(404, f"Debate {debate_id} not found")
    return {"status": "ok", "debate": debate.to_dict()}


@router.get("/consensus/debate-metrics")
async def debate_metrics(window_s: float = 3600.0):
    """Debate health metrics: lift, disagreement width, argument counts."""
    ds = _get_debate_store()
    if not ds:
        return _stub({"active_debates": 0, "total_debates": 0, "avg_debate_lift": 0.0})
    try:
        return ds.get_debate_metrics(window_s=window_s)
    except Exception as exc:
        logger.warning("consensus/debate-metrics failed: %s", exc)
        return {"active_debates": 0, "total_debates": 0, "avg_debate_lift": 0.0}


@router.post("/consensus/teams")
async def create_team(req: CreateTeamRequest):
    """Create a named agent team."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    from merid.prediction.debate import AgentTeam
    team = AgentTeam(name=req.name, member_ids=req.member_ids, strategy_mix=req.strategy_mix)
    ds.create_team(team)
    return {"status": "ok", "team": team.to_dict()}


@router.get("/consensus/teams")
async def list_teams(limit: int = 50):
    """List agent teams."""
    ds = _get_debate_store()
    if not ds:
        return _stub({"teams": [], "count": 0})
    try:
        teams = ds.list_teams(limit=limit)
        return {"teams": [t.to_dict() for t in teams], "count": len(teams)}
    except Exception as exc:
        logger.warning("consensus/teams failed: %s", exc)
        return {"teams": [], "count": 0}


@router.get("/consensus/leaderboard")
async def leaderboard(limit: int = 20, decay_lambda: Optional[float] = None):
    """Agent and team leaderboards based on reward points (with optional time-decay)."""
    ds = _get_debate_store()
    if not ds:
        return _stub({"agents": [], "teams": [], "debate_impact": []})
    try:
        return ds.compute_leaderboard(limit=limit, decay_lambda=decay_lambda)
    except Exception as exc:
        logger.warning("consensus/leaderboard failed: %s", exc)
        return {"agents": [], "teams": [], "debate_impact": []}


@router.get("/consensus/badges/{agent_id}")
async def agent_badges(agent_id: str):
    """Compute badges earned by an agent."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    try:
        badges = ds.compute_badges(agent_id)
        return {"agent_id": agent_id, "badges": badges}
    except Exception as exc:
        logger.warning("consensus/badges failed: %s", exc)
        return {"agent_id": agent_id, "badges": []}


@router.get("/consensus/rewards/{agent_id}")
async def agent_rewards(agent_id: str, limit: int = 100):
    """Get reward history and total points for an agent."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    try:
        rewards = ds.get_agent_rewards(agent_id, limit=limit)
        total = ds.get_agent_total_points(agent_id)
        return {
            "agent_id": agent_id,
            "total_points": round(total, 2),
            "rewards": [r.to_dict() for r in rewards],
            "count": len(rewards),
        }
    except Exception as exc:
        logger.warning("consensus/rewards failed: %s", exc)
        return {"agent_id": agent_id, "total_points": 0, "rewards": [], "count": 0}


# ── Sprint 8: Debate Tuning endpoints ─────────────────────────────────

@router.post("/consensus/backtest")
async def run_backtest(req: BacktestRequest):
    """Run a debate backtest on resolved markets."""
    from merid.prediction.debate import DebateBacktester
    bt = DebateBacktester()
    try:
        report = await run_in_threadpool(
            bt.run_backtest, req.markets,
            proposer_strategy=req.proposer_strategy,
            arbiter_strategy=req.arbiter_strategy,
        )
        return {"status": "ok", "report": report}
    except Exception as exc:
        logger.warning("consensus/backtest failed: %s", exc)
        raise HTTPException(500, f"Backtest failed: {exc}")


@router.get("/consensus/parameter-sweep")
async def parameter_sweep():
    """Run reward parameter sensitivity sweep with default grid."""
    from merid.prediction.debate import RewardParameterSweep
    sweep = RewardParameterSweep()
    try:
        result = await run_in_threadpool(sweep.sweep)
        return {"status": "ok", "sweep": result}
    except Exception as exc:
        logger.warning("consensus/parameter-sweep failed: %s", exc)
        raise HTTPException(500, f"Parameter sweep failed: {exc}")


@router.get("/consensus/calibration/{agent_id}")
async def agent_calibration(agent_id: str, n_bins: int = 10):
    """Compute calibration score for an agent (single source of truth)."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    try:
        result = ds.compute_calibration_score(agent_id, n_bins=n_bins)
        return result
    except Exception as exc:
        logger.warning("consensus/calibration failed: %s", exc)
        return {"agent_id": agent_id, "calibration_score": None, "total_predictions": 0, "bins": []}


@router.get("/consensus/teams/{team_id}/diversity")
async def team_diversity(team_id: str):
    """Compute strategy diversity score for a team."""
    ds = _get_debate_store()
    if not ds:
        raise HTTPException(503, "DebateStore unavailable")
    try:
        return ds.compute_team_diversity_score(team_id)
    except Exception as exc:
        logger.warning("consensus/teams/diversity failed: %s", exc)
        return {"team_id": team_id, "diversity_score": 0.0, "strategies": []}
