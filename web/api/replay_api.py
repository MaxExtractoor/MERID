"""Replay API Endpoints — Run and compare historical replays."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web.api.replay_harness import (
    get_replay_harness,
    ReplayScenario,
    ReplayMode,
    run_replay_comparison)
from utils.logger import get_logger

logger = get_logger("web.api.replay")
router = APIRouter(prefix="/api/v1/replay", tags=["replay"])


# ── Request/Response Models ────────────────────────────────────────────


class ReplayRunRequest(BaseModel):
    """Request to run a single replay scenario."""
    start_time: float = Field(..., description="Unix timestamp for window start")
    end_time: float = Field(..., description="Unix timestamp for window end")
    mode: str = Field("baseline", description="'baseline' or 'incentive_tuned'")
    market_filters: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class ReplayCompareRequest(BaseModel):
    """Request to run baseline vs tuned comparison."""
    start_time: float = Field(..., description="Unix timestamp for window start")
    end_time: float = Field(..., description="Unix timestamp for window end")
    market_filters: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class ReplayStatusResponse(BaseModel):
    """Status of a replay run."""
    run_id: str
    status: str  # "running", "completed", "error"
    mode: str
    progress_pct: float
    current_pnl: float
    elapsed_seconds: float


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/run")
async def run_single_replay(req: ReplayRunRequest) -> Dict[str, Any]:
    """Run a single replay scenario (baseline or incentive-tuned).
    
    Returns the full result after completion.
    """
    harness = get_replay_harness()
    
    # Validate mode
    try:
        mode = ReplayMode(req.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode}")
    
    scenario = ReplayScenario(
        start_time=req.start_time,
        end_time=req.end_time,
        market_filters=req.market_filters,
        description=req.description or f"Replay {datetime.fromtimestamp(req.start_time, tz=timezone.utc)}")
    
    logger.info("API: Starting replay run: mode=%s, window=%.0f-%.0f", 
                mode.value, req.start_time, req.end_time)
    
    try:
        result = await harness.run_scenario(scenario, mode)
        
        return {
            "run_id": result.run_id,
            "mode": result.mode.value,
            "status": "completed",
            "scenario": {
                "start_time": result.scenario.start_time,
                "end_time": result.scenario.end_time,
                "description": result.scenario.description,
            },
            "metrics": {
                "total_pnl": result.total_pnl,
                "hit_rate": result.hit_rate,
                "max_drawdown": result.max_drawdown,
                "max_drawdown_pct": result.max_drawdown_pct,
                "total_markets": result.total_markets,
                "resolved_markets": result.resolved_markets,
                "duration_seconds": result.duration_seconds(),
            },
            "agent_leaderboard": result.agent_leaderboard,
            "timestamp": time.time(),
        }
    
    except Exception as exc:
        logger.error("Replay run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/compare")
async def run_comparison(req: ReplayCompareRequest) -> Dict[str, Any]:
    """Run baseline vs incentive-tuned comparison.
    
    Returns both runs plus computed differences.
    """
    harness = get_replay_harness()
    
    scenario = ReplayScenario(
        start_time=req.start_time,
        end_time=req.end_time,
        market_filters=req.market_filters,
        description=req.description or f"Comparison {datetime.fromtimestamp(req.start_time, tz=timezone.utc)}")
    
    logger.info("API: Starting comparison: window=%.0f-%.0f", 
                req.start_time, req.end_time)
    
    try:
        comparison = await harness.compare_runs(scenario)
        
        def result_to_dict(r):
            return {
                "run_id": r.run_id,
                "mode": r.mode.value,
                "metrics": {
                    "total_pnl": r.total_pnl,
                    "hit_rate": r.hit_rate,
                    "max_drawdown": r.max_drawdown,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "total_markets": r.total_markets,
                    "resolved_markets": r.resolved_markets,
                    "duration_seconds": r.duration_seconds(),
                },
                "agent_leaderboard": r.agent_leaderboard,
            }
        
        return {
            "comparison_id": comparison.comparison_id,
            "status": "completed",
            "scenario": {
                "start_time": req.start_time,
                "end_time": req.end_time,
                "description": scenario.description,
            },
            "baseline": result_to_dict(comparison.baseline),
            "incentive_tuned": result_to_dict(comparison.tuned),
            "differences": {
                "pnl_diff": comparison.pnl_diff,
                "pnl_diff_pct": comparison.pnl_diff_pct,
                "hit_rate_diff": comparison.hit_rate_diff,
                "drawdown_diff": comparison.drawdown_diff,
            },
            "timestamp": time.time(),
        }
    
    except Exception as exc:
        logger.error("Comparison failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/results/{run_id}")
async def get_result(run_id: str) -> Dict[str, Any]:
    """Get a specific replay result by ID."""
    harness = get_replay_harness()
    result = harness.get_result(run_id)
    
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    return {
        "run_id": result.run_id,
        "mode": result.mode.value,
        "metrics": {
            "total_pnl": result.total_pnl,
            "hit_rate": result.hit_rate,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_pct": result.max_drawdown_pct,
            "total_markets": result.total_markets,
            "resolved_markets": result.resolved_markets,
            "duration_seconds": result.duration_seconds(),
        },
        "agent_leaderboard": result.agent_leaderboard,
    }


@router.get("/results")
async def list_results(limit: int = 50) -> Dict[str, Any]:
    """List recent replay results."""
    harness = get_replay_harness()
    results = harness.list_results(limit=limit)
    
    return {
        "count": len(results),
        "results": [
            {
                "run_id": r.run_id,
                "mode": r.mode.value,
                "total_pnl": r.total_pnl,
                "hit_rate": r.hit_rate,
                "timestamp": r.start_time,
            }
            for r in results
        ],
    }


@router.post("/quick-compare")
async def quick_compare() -> Dict[str, Any]:
    """Quick comparison using last 24 hours of synthetic data.
    
    Useful for smoke testing the replay system.
    """
    end_time = time.time()
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago
    
    return await run_comparison(
        ReplayCompareRequest(
            start_time=start_time,
            end_time=end_time,
            description="Quick 24h comparison")
    )
