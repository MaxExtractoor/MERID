"""Paper Session API — Endpoints for managing long-running paper trading sessions.

Provides session lifecycle, per-interval PnL, coverage metrics, readiness
checks, and paper→live promotion controls.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/paper-session", tags=["paper-session"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class PromoteRequest(BaseModel):
    agent_name: str
    force: bool = False


class DemoteRequest(BaseModel):
    agent_name: str


# ── Session lifecycle ──────────────────────────────────────────────────

@router.post("/start")
async def start_session(session_id: Optional[str] = None):
    """Start or resume a paper trading session across the full crypto surface."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        sid = session.start_session(session_id)
        return {"status": "started", "session_id": sid, "intervals": len(session._intervals)}
    except Exception as e:
        logger.error(f"Session start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_session_status():
    """Get full paper session status: PnL, coverage, readiness, intervals."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        return session.summary()
    except Exception as e:
        logger.error(f"Session status error: {e}")
        return {"error": str(e), "active": False}


@router.get("/coverage")
async def get_coverage():
    """Get coverage metrics: how much of the crypto surface is actively trading."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        return session.coverage_summary()
    except Exception as e:
        logger.error(f"Coverage error: {e}")
        return {"error": str(e)}


# ── Readiness ──────────────────────────────────────────────────────────

@router.get("/readiness")
async def get_all_readiness():
    """Check readiness benchmarks for all crypto agents."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        verdicts = session.check_all_readiness()
        ready_count = sum(1 for v in verdicts.values() if v.ready)
        return {
            "ready_count": ready_count,
            "total": len(verdicts),
            "agents": {name: v.to_dict() for name, v in verdicts.items()},
        }
    except Exception as e:
        logger.error(f"Readiness error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/readiness/{agent_name}")
async def get_agent_readiness(agent_name: str):
    """Check readiness for a specific agent."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        verdict = session.check_readiness(agent_name)
        return verdict.to_dict()
    except Exception as e:
        logger.error(f"Readiness error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Promotion ──────────────────────────────────────────────────────────

@router.post("/promote")
async def promote_agent(req: PromoteRequest):
    """Promote an agent from paper to live mode (requires readiness or force)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        result = session.promote_to_live(req.agent_name, force=req.force)
        if not result.get("promoted"):
            raise HTTPException(status_code=400, detail=result.get("reason", "Promotion failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Promote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demote")
async def demote_agent(req: DemoteRequest):
    """Demote an agent back to paper mode."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        return session.demote_to_paper(req.agent_name)
    except Exception as e:
        logger.error(f"Demote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Per-interval detail ───────────────────────────────────────────────

@router.get("/interval/{agent_name}")
async def get_interval_detail(agent_name: str):
    """Get detailed PnL for a specific agent interval."""
    try:
        from merid.prediction.paper_session import get_paper_session, get_benchmark_for
        session = get_paper_session()
        interval = session._intervals.get(agent_name)
        if not interval:
            raise HTTPException(status_code=404, detail=f"No interval data for {agent_name}")
        b = get_benchmark_for(agent_name)
        return {
            "interval": interval.to_dict(),
            "readiness": session.check_readiness(agent_name).to_dict(),
            "is_live": session.is_live(agent_name),
            "benchmark": {
                "min_profit_factor": b.min_profit_factor,
                "min_expectancy_cents": b.min_expectancy_cents,
                "min_trades": b.min_trades,
                "min_daily_trades": b.min_daily_trades,
                "max_drawdown_pct": b.max_drawdown_pct,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Interval detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Alerts & monitoring ───────────────────────────────────────────────

@router.get("/alerts/health")
async def get_health_alerts():
    """PF/expectancy/error-rate degradation alerts for all active cells."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        alerts = session.health_alerts()
        return {
            "count": len(alerts),
            "critical": sum(1 for a in alerts if a["level"] == "critical"),
            "warning": sum(1 for a in alerts if a["level"] == "warning"),
            "alerts": alerts,
        }
    except Exception as e:
        logger.error(f"Health alerts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/coverage-gaps")
async def get_coverage_gaps():
    """Flag cells with low trade count vs expected daily volume."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        gaps = session.coverage_gap_alerts()
        return {"count": len(gaps), "gaps": gaps}
    except Exception as e:
        logger.error(f"Coverage gaps error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Promotion candidates & nightly report ─────────────────────────────

@router.get("/candidates")
async def get_promotion_candidates():
    """Ranked list of agents by promotion readiness (best first)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        candidates = session.promotion_candidates()
        return {
            "count": len(candidates),
            "ready": sum(1 for c in candidates if c["tier"] == "ready"),
            "close": sum(1 for c in candidates if c["tier"] == "close"),
            "candidates": candidates,
        }
    except Exception as e:
        logger.error(f"Candidates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nightly-report")
async def get_nightly_report():
    """Generate a nightly readiness report with ranked candidates and alerts."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        return session.nightly_report()
    except Exception as e:
        logger.error(f"Nightly report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Risk governance ───────────────────────────────────────────────────

@router.get("/risk")
async def get_risk_status():
    """Session-wide risk status: halted cells, downsized cells, cluster losses."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        return session.risk_status()
    except Exception as e:
        logger.error(f"Risk status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class HaltRequest(BaseModel):
    agent_name: str
    reason: str = "manual"


@router.post("/halt")
async def halt_cell(req: HaltRequest):
    """Manually halt a cell (stop trading)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        ok = session.halt_cell(req.agent_name, req.reason)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {req.agent_name}")
        return {"halted": True, "agent": req.agent_name, "reason": req.reason}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Halt error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UnhaltRequest(BaseModel):
    agent_name: str


@router.post("/unhalt")
async def unhalt_cell(req: UnhaltRequest):
    """Unhalt a cell (resume trading after review)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        ok = session.unhalt_cell(req.agent_name)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {req.agent_name}")
        return {"unhalted": True, "agent": req.agent_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhalt error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unhalt-all")
async def unhalt_all_cells():
    """Unhalt all cells (e.g. daily reset)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        count = session.unhalt_all()
        return {"unhalted_count": count}
    except Exception as e:
        logger.error(f"Unhalt-all error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/size-factor/{agent_name}")
async def get_size_factor(agent_name: str):
    """Get the effective size factor for an agent (1.0, downsize_factor, or 0.0 if halted)."""
    try:
        from merid.prediction.paper_session import get_paper_session
        session = get_paper_session()
        factor = session.get_size_factor(agent_name)
        return {
            "agent": agent_name,
            "size_factor": factor,
            "halted": session.is_halted(agent_name),
            "downsized": session.is_downsized(agent_name),
        }
    except Exception as e:
        logger.error(f"Size factor error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
