"""Swarm Bus API — /api/v1/kalshi/swarm/*

Exposes critic history, edge recalibration status, and execution
subscriber stats for the CalibrationDashboardView (Sprint M).

Endpoints:
  GET  /api/v1/kalshi/swarm/critic/history     — Recent critique messages
  GET  /api/v1/kalshi/swarm/recalibration      — Edge recalibration status
  GET  /api/v1/kalshi/swarm/execution/stats    — Execution subscriber stats
  GET  /api/v1/kalshi/swarm/verdicts           — Recent swarm consensus verdicts (SwarmVerdictFeed)
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from utils.logger import get_logger

logger = get_logger("web.api.swarm_bus_api")

router = APIRouter(
    prefix="/api/v1/kalshi/swarm",
    tags=["kalshi-swarm-bus"],
)


@router.get("/critic/history")
async def get_critic_history() -> Dict[str, Any]:
    """Return recent critique messages from the CriticAgent."""
    try:
        from merid.swarm.critic_agent import get_critic_agent
        agent = get_critic_agent()
        if agent.history:
            return {
                "critiques": agent.history[-50:],
                "count": len(agent.history),
            }
    except Exception as exc:
        logger.debug(f"Critic agent unavailable: {exc}")

    # Fallback: derive critiques from debate store — use full debate metadata
    critiques = []
    try:
        from merid.prediction.debate import get_debate_store
        store = get_debate_store()
        for debate in store.list_debates(limit=20):
            # First try rounds_data for granular critique entries
            for rnd in getattr(debate, "rounds_data", []):
                if rnd.get("role") in ("challenger", "critic", "reviewer"):
                    critiques.append({
                        "debate_id": debate.id,
                        "agent_id": rnd.get("agent_id", rnd.get("role", "unknown")),
                        "role": rnd.get("role", "critic"),
                        "argument": rnd.get("argument", rnd.get("text", ""))[:200],
                        "score_delta": rnd.get("score_delta", 0),
                        "timestamp": rnd.get("timestamp", str(getattr(debate, "created_at", ""))),
                    })
            # If no rounds_data, derive a critique summary from the debate itself
            if not getattr(debate, "rounds_data", []):
                pre = getattr(debate, "pre_debate_prob", 0.5)
                post = getattr(debate, "post_debate_prob", 0.5)
                shift = post - pre
                critiques.append({
                    "debate_id": debate.id,
                    "agent_id": getattr(debate, "team_id", None) or "swarm",
                    "role": "debate_review",
                    "argument": f"Debate on {getattr(debate, 'symbol', '?')}: {getattr(debate, 'rounds', 0)} rounds, prob shifted {pre:.0%}→{post:.0%} ({shift:+.0%})",
                    "score_delta": round(shift, 3),
                    "timestamp": str(getattr(debate, "created_at", "")),
                })
    except Exception as exc2:
        logger.debug(f"Debate store critic fallback: {exc2}")

    # Also include consensus opinions as analytical critiques
    try:
        from merid.prediction.consensus import get_prediction_consensus_store
        ops = get_prediction_consensus_store()
        for op in ops.list_opinions(limit=30):
            prob = getattr(op, "probability", 0.5)
            conf = getattr(op, "confidence", 0.5)
            symbol = getattr(op, "symbol", "")
            critiques.append({
                "agent_id": getattr(op, "agent_id", "unknown"),
                "role": "analyst",
                "argument": f"Opinion on {symbol}: prob={prob:.0%}, confidence={conf:.0%}",
                "score_delta": round(prob - 0.5, 3),
                "timestamp": str(getattr(op, "timestamp", "")),
            })
    except Exception as exc3:
        logger.debug(f"Opinion store critic fallback: {exc3}")

    critiques.sort(key=lambda c: str(c.get("timestamp", "")), reverse=True)
    return {"critiques": critiques[:50], "count": len(critiques)}


@router.get("/recalibration")
async def get_recalibration_status() -> Dict[str, Any]:
    """Return edge recalibration history and current status."""
    try:
        from merid.prediction.edge_recalibrator import get_edge_recalibrator
        recal = get_edge_recalibrator()
        latest = recal.latest
        return {
            "latest": latest.to_dict() if latest else None,
            "history": [r.to_dict() for r in recal.history[-20:]],
            "history_count": len(recal.history),
        }
    except Exception as exc:
        logger.debug(f"Recalibration status unavailable: {exc}")
        return {"latest": None, "history": [], "history_count": 0, "error": str(exc)}


@router.get("/execution/stats")
async def get_execution_stats() -> Dict[str, Any]:
    """Return execution subscriber stats and recent routing history."""
    import asyncio
    def _fetch():
        from merid.swarm.execution_subscriber import get_execution_subscriber
        sub = get_execution_subscriber()
        return {
            "stats": sub.stats,
            "history": sub.history[-30:],
        }
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=5.0)
    except asyncio.TimeoutError:
        return {"stats": {}, "history": [], "error": "Execution stats timed out (5s)"}
    except Exception as exc:
        logger.debug(f"Execution stats unavailable: {exc}")
        return {"stats": {}, "history": [], "error": str(exc)}


@router.get("/verdicts")
async def get_swarm_verdicts(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """Return recent swarm consensus verdicts for SwarmVerdictFeed.

    Maps ConsensusView objects from ConsensusAggregator into the
    SwarmVerdict shape: {ts, asset, timeframe, direction, probability,
    confidence, size_band, agents, rationale}.
    """
    import asyncio as _aio
    from datetime import timezone as _tz

    def _fetch():
        from merid.swarm.consensus_aggregator import get_consensus_aggregator
        agg = get_consensus_aggregator()
        # Use the rolling verdict log (historical timeline) instead of the
        # current-state-per-cell snapshot so operators see actual verdict history.
        recent = agg.get_recent_verdicts(limit=limit)
        verdicts = []
        for cv in recent:
            try:
                # Only include usable, READY verdicts (log already filters these,
                # but be defensive in case old snapshots are in the deque).
                if not getattr(cv, "usable", True):
                    continue
                agents = [p.agent_id for p in cv.raw_proposals] if cv.raw_proposals else []
                # "yes"/"no" → "bullish"/"bearish" for display
                dir_map = {"yes": "bullish", "no": "bearish", "neutral": "neutral"}
                direction = dir_map.get(cv.consensus_direction, cv.consensus_direction)
                verdicts.append({
                    "ts": cv.timestamp.astimezone(_tz.utc).isoformat(),
                    "asset": cv.asset,
                    "timeframe": cv.timeframe,
                    "direction": direction,
                    "probability": round(cv.consensus_probability, 3),
                    "confidence": round(cv.consensus_confidence, 3),
                    "size_band": cv.size_band,
                    "agents": agents[:10],
                    "rationale": cv.size_rationale or (", ".join(cv.confidence_factors[:3]) if cv.confidence_factors else ""),
                })
            except Exception:
                continue
        return verdicts

    try:
        verdicts = await _aio.wait_for(_aio.to_thread(_fetch), timeout=5.0)
        return {"verdicts": verdicts, "count": len(verdicts)}
    except Exception as exc:
        logger.debug("swarm_verdicts unavailable: %s", exc)
        return {"verdicts": [], "count": 0, "error": str(exc)}
