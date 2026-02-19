"""
Betting API — Universal "bet on anything" layer for MERID.

Endpoints:
  # Universal market-id endpoints
  POST /api/v1/betting/place                    — Place bet on any market
  POST /api/v1/betting/markets/{market_id}/create  — Create pool for any market
  POST /api/v1/betting/markets/{market_id}/lock    — Lock pool
  POST /api/v1/betting/markets/{market_id}/settle  — Settle pool (consensus or explicit)
  GET  /api/v1/betting/markets/{market_id}         — Pool info
  GET  /api/v1/betting/markets/{market_id}/bets    — Bets in a pool

  # Discovery
  GET  /api/v1/betting/discover                 — Active markets available for betting
  GET  /api/v1/betting/pools/active             — All active pools
  GET  /api/v1/betting/pools/all                — All pools (incl. settled)

  # User & agent
  GET  /api/v1/betting/user/{user_id}/stats     — User stats + position introspection
  GET  /api/v1/betting/user/{user_id}/balance   — User balance
  POST /api/v1/betting/deposit                  — Deposit funds
  POST /api/v1/betting/withdraw                 — Withdraw funds
  GET  /api/v1/betting/leaderboard              — Leaderboard by net profit

  # Agent introspection
  GET  /api/v1/betting/agents/rewards           — Agent reward stats
  GET  /api/v1/betting/agents/{agent_id}/coherence — Agent coherence report
  POST /api/v1/betting/agents/reward            — Reward agents for a market

  # System
  GET  /api/v1/betting/stats                    — Overall system stats
  GET  /api/v1/betting/health                   — Betting health metrics

  # Legacy block-index endpoints (backward compat)
  POST /api/v1/betting/pools/{block_index}/create
  POST /api/v1/betting/pools/{block_index}/lock
  POST /api/v1/betting/pools/{block_index}/settle
  GET  /api/v1/betting/pools/{block_index}
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from trading.agents.bookie_agent import BookieAgent, market_id_for_block
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/betting", tags=["betting"])
logger = get_logger("web.api.betting")

# Global bookie agent instance
_bookie_agent: Optional[BookieAgent] = None


def get_bookie_agent() -> BookieAgent:
    """Get or create bookie agent singleton."""
    global _bookie_agent
    if _bookie_agent is None:
        _bookie_agent = BookieAgent(
            house_cut_pct=5.0,
            min_bet_amount=1.0,
            max_bet_amount=10000.0,
        )
    return _bookie_agent


def _emit_betting_event(**kwargs) -> None:
    """Best-effort emit a BettingEvent into the RewardEngine."""
    try:
        from merid.rewards.events import BettingEvent
        from merid.rewards.engine import get_reward_engine
        evt = BettingEvent(**kwargs)
        engine = get_reward_engine()
        engine.process_event(evt)
    except Exception as exc:
        logger.debug("BettingEvent emission skipped: %s", exc)


# ── Request models ───────────────────────────────────────────────────

class PlaceBetRequest(BaseModel):
    """Universal bet placement request."""
    user_id: str = Field(..., description="User or agent ID")
    market_id: str = Field("", description="Universal market key (e.g. PRED:KALSHI:TICKER:YES, block:42)")
    block_index: Optional[int] = Field(None, description="Legacy block index (converted to block:<N>)")
    prediction: str = Field(..., description="Outcome label to bet on")
    stake_amount: float = Field(..., gt=0, description="Stake amount in USD")
    role: str = Field("directional", description="Agent role: directional, hedging, market_making, arb")
    stated_probability: Optional[float] = Field(None, ge=0, le=1, description="Agent's opinion probability at bet time")


class CreatePoolRequest(BaseModel):
    """Pool creation request for any market."""
    allowed_outcomes: List[str] = Field(default=[], description="Restrict outcomes (empty = any)")


class SettlePoolRequest(BaseModel):
    """Pool settlement request."""
    outcome: Optional[str] = Field(None, description="Explicit outcome (if not using consensus)")
    consensus_approved: Optional[bool] = Field(None, description="Legacy: consensus approved flag")
    consensus_confidence: Optional[float] = Field(None, description="Legacy: consensus confidence")
    use_consensus_store: bool = Field(False, description="Settle from PredictionConsensusStore")


class DepositRequest(BaseModel):
    """Deposit request."""
    user_id: str
    amount: float = Field(..., gt=0)


class WithdrawRequest(BaseModel):
    """Withdraw request."""
    user_id: str
    amount: float = Field(..., gt=0)


class RewardAgentsRequest(BaseModel):
    """Agent reward request."""
    market_id: str = Field("", description="Market to reward for")
    block_index: Optional[int] = Field(None, description="Legacy block index")
    agent_votes: Dict[str, bool] = Field(default={}, description="agent_id → voted_yes")
    reward_pool_pct: float = Field(10.0, ge=0, le=100)


# ── Universal endpoints ──────────────────────────────────────────────

@router.post("/place")
async def place_bet(request: PlaceBetRequest):
    """Place bet on any market outcome."""
    agent = get_bookie_agent()
    market_id = request.market_id
    if not market_id and request.block_index is not None:
        market_id = market_id_for_block(request.block_index)
    if not market_id:
        raise HTTPException(400, "market_id or block_index required")

    try:
        bet = agent.place_bet(
            user_id=request.user_id,
            market_id=market_id,
            prediction=request.prediction,
            stake_amount=request.stake_amount,
            role=request.role,
            stated_probability=request.stated_probability,
        )
        _emit_betting_event(
            action="bet_placed",
            agent_id=request.user_id,
            market_id=market_id,
            bet_id=bet.bet_id,
            prediction=request.prediction,
            stake_amount=request.stake_amount,
            odds=bet.odds,
            stated_probability=request.stated_probability,
            implied_probability=bet.implied_probability,
            role=request.role,
        )
        return bet.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/markets/{market_id:path}/create")
async def create_market_pool(market_id: str, request: CreatePoolRequest = None):
    """Create a new betting pool for any market/instrument/event."""
    if request is None:
        request = CreatePoolRequest()
    agent = get_bookie_agent()
    try:
        pool = agent.create_pool(market_id, allowed_outcomes=request.allowed_outcomes)
        _emit_betting_event(action="pool_created", market_id=market_id)
        return {**pool.to_dict(), "status": "created"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/markets/{market_id:path}/lock")
async def lock_market_pool(market_id: str):
    """Lock a betting pool — no more bets accepted."""
    agent = get_bookie_agent()
    try:
        agent.lock_pool(market_id)
        return {"market_id": market_id, "status": "locked", "message": "Pool locked — no more bets accepted"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/markets/{market_id:path}/settle")
async def settle_market_pool(market_id: str, request: SettlePoolRequest = None):
    """Settle a betting pool with explicit outcome, consensus store, or legacy params."""
    if request is None:
        request = SettlePoolRequest()
    agent = get_bookie_agent()

    try:
        if request.use_consensus_store:
            payouts = agent.settle_from_consensus(market_id)
        elif request.outcome:
            payouts = agent.settle_pool_with_outcome(market_id, request.outcome)
        elif request.consensus_approved is not None and request.consensus_confidence is not None:
            payouts = agent.settle_pool(
                market_id=market_id,
                consensus_approved=request.consensus_approved,
                consensus_confidence=request.consensus_confidence,
            )
        else:
            raise ValueError("Provide outcome, use_consensus_store=true, or consensus_approved+consensus_confidence")

        pool = agent.pools.get(market_id)
        _emit_betting_event(
            action="pool_settled",
            market_id=market_id,
            prediction=pool.actual_outcome if pool else "",
        )
        return {
            "market_id": market_id,
            "status": "settled",
            "outcome": pool.actual_outcome if pool else None,
            "total_payouts": round(sum(payouts.values()), 2),
            "winners": len(payouts),
            "payouts": {k: round(v, 2) for k, v in payouts.items()},
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/markets/{market_id:path}/bets")
async def get_market_bets(market_id: str):
    """List all bets in a pool."""
    agent = get_bookie_agent()
    pool = agent.pools.get(market_id)
    if not pool:
        raise HTTPException(404, "Pool not found")
    return {"market_id": market_id, "bets": [b.to_dict() for b in pool.bets], "count": len(pool.bets)}


@router.get("/markets/{market_id:path}")
async def get_market_pool_info(market_id: str):
    """Get pool info for any market."""
    agent = get_bookie_agent()
    stats = agent.get_pool_stats(market_id=market_id)
    if not stats:
        raise HTTPException(404, "Pool not found")
    return stats


# ── Discovery ────────────────────────────────────────────────────────

@router.get("/discover")
async def discover_markets():
    """Discover active markets available for betting.

    Merges bookie pools with prediction instruments from the consensus store.
    """
    agent = get_bookie_agent()
    active_pools = agent.list_active_pools()

    # Enrich with consensus store instruments
    instruments: list = []
    try:
        from merid.prediction.consensus import get_prediction_consensus_store
        store = get_prediction_consensus_store()
        for inst in store.list_instruments(status="active", limit=50):
            instruments.append({
                "market_id": inst.symbol,
                "title": inst.title,
                "category": inst.category,
                "market_implied_prob": round(inst.market_implied_prob, 4),
                "status": inst.status,
                "has_pool": inst.symbol in agent.pools,
            })
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    return {
        "active_pools": active_pools,
        "instruments": instruments,
        "total_active_pools": len(active_pools),
        "total_instruments": len(instruments),
    }


@router.get("/pools/active")
async def get_active_pools():
    """Get all active (unsettled) betting pools."""
    agent = get_bookie_agent()
    pools = agent.list_active_pools()
    return {"active_pools": pools, "total_active": len(pools)}


@router.get("/pools/all")
async def get_all_pools(include_settled: bool = False):
    """Get all pools, optionally including settled ones."""
    agent = get_bookie_agent()
    pools = agent.list_all_pools(include_settled=include_settled)
    return {"pools": pools, "count": len(pools)}


# ── User endpoints ───────────────────────────────────────────────────

@router.get("/user/{user_id}/stats")
async def get_user_betting_stats(user_id: str):
    """Get user betting statistics with position introspection."""
    agent = get_bookie_agent()
    stats = agent.get_user_stats(user_id)

    # Position introspection: open bets by market
    open_positions: List[Dict] = []
    for pool in agent.pools.values():
        if pool.settled:
            continue
        user_bets = [b for b in pool.bets if b.user_id == user_id]
        if user_bets:
            open_positions.append({
                "market_id": pool.market_id,
                "bets": [b.to_dict() for b in user_bets],
                "total_exposure": round(sum(b.stake_amount for b in user_bets), 2),
            })
    stats["open_positions"] = open_positions
    return stats


@router.get("/user/{user_id}/balance")
async def get_user_balance(user_id: str):
    """Get user balance."""
    agent = get_bookie_agent()
    return {"user_id": user_id, "balance": agent.user_balances.get(user_id, 0.0)}


@router.post("/deposit")
async def deposit_funds(request: DepositRequest):
    """Deposit funds to user balance."""
    agent = get_bookie_agent()
    try:
        agent.deposit(request.user_id, request.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "user_id": request.user_id,
        "deposited": request.amount,
        "new_balance": agent.user_balances.get(request.user_id, 0.0),
    }


@router.post("/withdraw")
async def withdraw_funds(request: WithdrawRequest):
    """Withdraw funds from user balance."""
    agent = get_bookie_agent()
    success = agent.withdraw(request.user_id, request.amount)
    if not success:
        raise HTTPException(400, "Insufficient balance")
    return {
        "user_id": request.user_id,
        "withdrawn": request.amount,
        "new_balance": agent.user_balances.get(request.user_id, 0.0),
    }


@router.get("/leaderboard")
async def get_betting_leaderboard(limit: int = 10):
    """Get betting leaderboard by net profit."""
    agent = get_bookie_agent()
    user_stats = [agent.get_user_stats(uid) for uid in agent.user_balances]
    leaderboard = sorted(user_stats, key=lambda x: x["net_profit"], reverse=True)[:limit]
    return {"leaderboard": leaderboard, "total_users": len(user_stats)}


# ── Agent introspection ──────────────────────────────────────────────

@router.get("/agents/rewards")
async def get_agent_rewards():
    """Get agent reward statistics."""
    agent = get_bookie_agent()
    return {
        "agent_rewards": agent.agent_rewards,
        "total_rewards": round(sum(agent.agent_rewards.values()), 2),
    }


@router.get("/agents/{agent_id}/coherence")
async def get_agent_coherence(agent_id: str):
    """Get agent coherence report: how well bets align with stated opinions."""
    agent = get_bookie_agent()
    return agent.get_agent_coherence(agent_id)


@router.post("/agents/reward")
async def reward_agents(request: RewardAgentsRequest):
    """Reward agents for correct consensus participation on any market."""
    agent = get_bookie_agent()
    market_id = request.market_id
    if not market_id and request.block_index is not None:
        market_id = market_id_for_block(request.block_index)
    if not market_id:
        raise HTTPException(400, "market_id or block_index required")

    agent.reward_agents(
        market_id=market_id,
        agent_votes=request.agent_votes,
        reward_pool_pct=request.reward_pool_pct,
    )
    return {
        "market_id": market_id,
        "status": "agents_rewarded",
        "total_agent_rewards": round(sum(agent.agent_rewards.values()), 2),
    }


# ── System ───────────────────────────────────────────────────────────

@router.get("/stats")
async def get_betting_stats():
    """Get overall betting system statistics including house transparency."""
    agent = get_bookie_agent()
    perf = agent.get_performance_stats()
    perf["house_cut_pct"] = agent.house_cut_pct
    return perf


@router.get("/health")
async def get_betting_health():
    """Betting health metrics for observability dashboards."""
    agent = get_bookie_agent()
    return agent.get_betting_health()


# ── Legacy block-index endpoints (backward compat) ───────────────────

@router.post("/pools/{block_index}/create")
async def create_betting_pool(block_index: int):
    """Legacy: create pool for a block index."""
    agent = get_bookie_agent()
    try:
        pool = agent.create_betting_pool(block_index)
        return {
            "block_index": pool.block_index,
            "market_id": pool.market_id,
            "total_pool": pool.total_pool,
            "house_cut_pct": pool.house_cut_pct,
            "locked": pool.locked,
            "status": "created",
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/pools/{block_index}/lock")
async def lock_betting_pool(block_index: int):
    """Legacy: lock pool for a block index."""
    agent = get_bookie_agent()
    try:
        agent.lock_pool_for_mining(block_index)
        return {"block_index": block_index, "status": "locked", "message": "Pool locked — no more bets accepted"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/pools/{block_index}/settle")
async def settle_betting_pool(
    block_index: int,
    consensus_approved: bool = True,
    consensus_confidence: float = 0.5,
):
    """Legacy: settle pool for a block index."""
    agent = get_bookie_agent()
    try:
        payouts = agent.settle_pool(
            block_index=block_index,
            consensus_approved=consensus_approved,
            consensus_confidence=consensus_confidence,
        )
        return {
            "block_index": block_index,
            "status": "settled",
            "total_payouts": round(sum(payouts.values()), 2),
            "winners": len(payouts),
            "payouts": {k: round(v, 2) for k, v in payouts.items()},
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/pools/{block_index}")
async def get_pool_info(block_index: int):
    """Legacy: get pool info by block index."""
    agent = get_bookie_agent()
    stats = agent.get_pool_stats(block_index=block_index)
    if not stats:
        raise HTTPException(404, "Pool not found")
    return stats


@router.post("/agents/reward/{block_index}")
async def reward_agents_for_block(
    block_index: int,
    agent_votes: dict = {},
    reward_pool_pct: float = 10.0,
):
    """Legacy: reward agents for a block index."""
    agent = get_bookie_agent()
    agent.reward_agents(
        block_index=block_index,
        agent_votes=agent_votes,
        reward_pool_pct=reward_pool_pct,
    )
    return {
        "block_index": block_index,
        "status": "agents_rewarded",
        "total_agent_rewards": round(sum(agent.agent_rewards.values()), 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# Sports & Live Betting endpoints (Sprint 12)
# ═══════════════════════════════════════════════════════════════════════

def _get_sports_manager():
    """Lazy import to avoid circular deps."""
    from merid.betting.live_sports import get_sports_betting_manager
    return get_sports_betting_manager()


# ── Sports event registration ────────────────────────────────────────

class RegisterSportsEventRequest(BaseModel):
    """Register a sports event as a first-class MERID instrument."""
    event_id: str = Field(..., description="Unique event identifier")
    sport: str = Field(..., description="Sport code: nfl, nba, mlb, nhl, soccer, mma, etc.")
    league: str = Field("", description="League display name")
    title: str = Field(..., description="Human-readable title")
    home_team: str = Field("", description="Home team name")
    away_team: str = Field("", description="Away team name")
    start_time: float = Field(0.0, description="Unix epoch start time")
    state: str = Field("pre", description="Event state: pre, live, final, cancelled")
    outcomes: List[str] = Field(default=["home", "away"], description="Outcome labels")
    market_type: str = Field("moneyline", description="Market type")
    line: Optional[float] = Field(None, description="Spread or total line")
    implied_probs: Dict[str, float] = Field(default={}, description="outcome_label → implied probability")


@router.post("/sports/register")
async def register_sports_event(request: RegisterSportsEventRequest):
    """Register a sports event as first-class MERID instruments in the consensus store."""
    mgr = _get_sports_manager()
    from merid.betting.live_sports import SportsOutcomeSchema
    schema = SportsOutcomeSchema(
        market_type=request.market_type,
        outcomes=request.outcomes,
        line=request.line,
    )
    si = mgr.bridge.register_event(
        event_id=request.event_id,
        sport=request.sport,
        league=request.league,
        title=request.title,
        home_team=request.home_team,
        away_team=request.away_team,
        start_time=request.start_time,
        state=request.state,
        outcome_schemas=[schema],
        implied_probs=request.implied_probs or None,
    )
    _emit_betting_event(action="sports_event_registered", market_id=request.event_id)
    return {"status": "registered", "event": si.to_dict()}


class UpdateEventStateRequest(BaseModel):
    state: str = Field(..., description="New state: pre, live, final, cancelled")
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    period: str = ""
    clock: str = ""


@router.post("/sports/{event_id}/state")
async def update_sports_event_state(event_id: str, request: UpdateEventStateRequest):
    """Update live state of a sports event (scores, period, clock)."""
    mgr = _get_sports_manager()
    si = mgr.bridge.update_event_state(
        event_id=event_id,
        state=request.state,
        score_home=request.score_home,
        score_away=request.score_away,
        period=request.period,
        clock=request.clock,
    )
    if not si:
        raise HTTPException(404, f"Event {event_id} not found")
    return {"status": "updated", "event": si.to_dict()}


@router.get("/sports/events")
async def list_sports_events(
    sport: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
):
    """List registered sports events."""
    mgr = _get_sports_manager()
    events = mgr.bridge.list_events(sport=sport, state=state)
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
    }


class SettleSportsEventRequest(BaseModel):
    winning_outcomes: List[str] = Field(..., description="List of winning outcome labels")


@router.post("/sports/{event_id}/settle")
async def settle_sports_event(event_id: str, request: SettleSportsEventRequest):
    """Settle a sports event with final results."""
    mgr = _get_sports_manager()
    try:
        result = mgr.bridge.settle_event(event_id, request.winning_outcomes)
        _emit_betting_event(action="sports_event_settled", market_id=event_id)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ── Live odds ────────────────────────────────────────────────────────

class IngestOddsRequest(BaseModel):
    provider: str = Field(..., description="Odds provider name")
    event_id: str = Field(..., description="Event ID")
    outcome_label: str = Field(..., description="Outcome label")
    american_odds: int = Field(0, description="American odds (e.g. -110, +150)")
    decimal_odds: float = Field(0.0, description="Decimal odds (e.g. 1.91)")
    implied_prob: float = Field(0.0, description="Implied probability (0-1)")
    latency_ms: float = Field(0.0, description="Feed latency in ms")


@router.post("/sports/odds/ingest")
async def ingest_odds_update(request: IngestOddsRequest):
    """Ingest a live odds update from a provider."""
    mgr = _get_sports_manager()
    from merid.betting.live_sports import OddsUpdate
    update = OddsUpdate(
        provider=request.provider,
        event_id=request.event_id,
        outcome_label=request.outcome_label,
        american_odds=request.american_odds,
        decimal_odds=request.decimal_odds,
        implied_prob=request.implied_prob,
        latency_ms=request.latency_ms,
    )
    mgr.odds_feed.ingest_update(update)
    return {"status": "ingested", "provider": request.provider, "event_id": request.event_id}


@router.get("/sports/odds/feed-health")
async def get_odds_feed_health():
    """Get health metrics for all odds feed providers."""
    mgr = _get_sports_manager()
    return mgr.odds_feed.get_feed_health()


@router.get("/sports/{event_id}/lines")
async def get_event_lines(event_id: str):
    """Get platform lines for a sports event."""
    mgr = _get_sports_manager()
    lines = mgr.odds_engine.get_all_lines(event_id=event_id)
    if not lines:
        raise HTTPException(404, f"No lines for event {event_id}")
    return {"event_id": event_id, "lines": [l.to_dict() for l in lines]}


# ── Live bet placement ───────────────────────────────────────────────

class LiveBetRequest(BaseModel):
    event_id: str = Field(..., description="Sports event ID")
    outcome_label: str = Field(..., description="Outcome to bet on")
    stake: float = Field(..., gt=0, description="Stake amount")
    displayed_odds: float = Field(..., description="Odds shown to user at display time")
    user_id: str = Field("", description="User or agent ID")


@router.post("/sports/live-bet")
async def place_live_bet(request: LiveBetRequest):
    """Place a live bet with latency tracking and auto-reprice."""
    mgr = _get_sports_manager()
    result = mgr.betting_engine.accept_bet(
        event_id=request.event_id,
        outcome_label=request.outcome_label,
        stake=request.stake,
        displayed_odds=request.displayed_odds,
        user_id=request.user_id,
    )
    if result.accepted:
        _emit_betting_event(
            action="live_bet_placed",
            agent_id=request.user_id,
            market_id=request.event_id,
            bet_id=result.bet_id,
            prediction=request.outcome_label,
            stake_amount=request.stake,
            odds=result.odds_at_placement,
        )
    return result.to_dict()


@router.get("/sports/slo-metrics")
async def get_live_betting_slo():
    """Get live betting SLO metrics (latency, acceptance rate, reprice rate)."""
    mgr = _get_sports_manager()
    return mgr.betting_engine.get_slo_metrics()


# ── Agent sports forecasting ─────────────────────────────────────────

class SportsForecastRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    event_id: str = Field(..., description="Sports event ID")
    outcome_label: str = Field(..., description="Outcome being forecast")
    probability: float = Field(..., ge=0, le=1, description="Agent's probability estimate")
    confidence: float = Field(0.5, ge=0, le=1, description="Confidence in estimate")
    reasoning: str = Field("", description="Reasoning text")
    signal_sources: List[str] = Field(default=[], description="Data sources used")


@router.post("/sports/forecast")
async def submit_sports_forecast(request: SportsForecastRequest):
    """Submit an agent's sports forecast (registered as PredictionOpinion)."""
    mgr = _get_sports_manager()
    from merid.betting.live_sports import SportsForecast
    forecast = SportsForecast(
        agent_id=request.agent_id,
        event_id=request.event_id,
        outcome_label=request.outcome_label,
        probability=request.probability,
        confidence=request.confidence,
        reasoning=request.reasoning,
        signal_sources=request.signal_sources,
    )
    result = mgr.forecast_engine.submit_forecast(forecast)
    return result


@router.get("/sports/forecasts/{event_id}")
async def get_event_forecasts(event_id: str):
    """Get all agent forecasts for a sports event."""
    mgr = _get_sports_manager()
    forecasts = mgr.forecast_engine.get_event_forecasts(event_id)
    return {
        "event_id": event_id,
        "forecasts": [
            {
                "agent_id": f.agent_id,
                "outcome": f.outcome_label,
                "probability": round(f.probability, 4),
                "confidence": round(f.confidence, 4),
                "reasoning": f.reasoning,
            }
            for f in forecasts
        ],
        "count": len(forecasts),
    }


@router.get("/sports/coherence")
async def get_forecast_coherence(agent_id: Optional[str] = Query(None)):
    """Get forecast-vs-bet coherence statistics."""
    mgr = _get_sports_manager()
    return mgr.forecast_engine.get_coherence_stats(agent_id=agent_id)


# ── Quests ───────────────────────────────────────────────────────────

@router.get("/sports/quests")
async def list_quests():
    """List available cross-vertical quests."""
    mgr = _get_sports_manager()
    quests = mgr.quest_engine.list_quests()
    return {"quests": [q.to_dict() for q in quests], "count": len(quests)}


@router.get("/sports/quests/{agent_id}")
async def get_agent_quests(agent_id: str):
    """Get quest progress for an agent."""
    mgr = _get_sports_manager()
    return {"agent_id": agent_id, "quests": mgr.quest_engine.get_agent_quests(agent_id)}


# ── Sports health ───────────────────────────────────────────────────

@router.get("/sports/health")
async def get_sports_betting_health():
    """Comprehensive sports & live betting health metrics."""
    mgr = _get_sports_manager()
    return mgr.get_sports_health()


# ── Single event lookup (MUST be last — catch-all {event_id} path) ──

@router.get("/sports/{event_id}")
async def get_sports_event(event_id: str):
    """Get details for a single sports event."""
    mgr = _get_sports_manager()
    si = mgr.bridge.get_event(event_id)
    if not si:
        raise HTTPException(404, f"Event {event_id} not found")
    return si.to_dict()
