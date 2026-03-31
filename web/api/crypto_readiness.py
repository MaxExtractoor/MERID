"""API endpoints for crypto coverage readiness monitoring."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["crypto-readiness"])


# ============================================================================
# Response Models
# ============================================================================

class MarketCellStatus(BaseModel):
    """Status of a single market cell (asset × timeframe)."""
    asset: str
    timeframe: str
    catalog_ok: bool
    strategy_ok: bool
    sizing_ok: bool
    execution_ok: bool
    monitor_ok: bool
    overall_ok: bool
    notes: str = ""


class ReadinessCheckResult(BaseModel):
    """Result of a readiness check run."""
    timestamp: datetime
    live_ready: bool
    blocking_failures: List[str]
    env_vars_valid: int
    env_vars_total: int
    formulas_valid: int
    formulas_total: int
    proposals_valid: int
    proposals_total: int
    markets_covered: int
    markets_total: int = 25  # 5 assets × 5 timeframes
    config_validation: bool
    data_feeds_healthy: bool
    cfb_status: Optional[str] = None
    duration_ms: int


class ReadinessHistory(BaseModel):
    """Historical readiness check results."""
    latest: Optional[ReadinessCheckResult]
    history: List[ReadinessCheckResult]
    uptime_pct: float
    total_checks: int


class Matrix25Status(BaseModel):
    """25-cell matrix status (5 assets × 5 timeframes)."""
    cells: List[MarketCellStatus]
    total_markets: int = 25
    healthy_markets: int
    degraded_markets: int
    failed_markets: int
    last_updated: datetime


# ============================================================================
# Storage Helper
# ============================================================================

READINESS_HISTORY_FILE = Path("data/readiness_history.jsonl")


def _save_readiness_result(result: ReadinessCheckResult) -> None:
    """Append readiness result to history file."""
    READINESS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(READINESS_HISTORY_FILE, "a") as f:
        f.write(result.model_dump_json() + "\n")


def _load_readiness_history(limit: int = 100) -> List[ReadinessCheckResult]:
    """Load recent readiness history from file."""
    if not READINESS_HISTORY_FILE.exists():
        return []

    results = []
    with open(READINESS_HISTORY_FILE, "r") as f:
        lines = f.readlines()
        # Get last N lines
        for line in lines[-limit:]:
            try:
                data = json.loads(line)
                results.append(ReadinessCheckResult(**data))
            except Exception as e:
                logger.warning(f"Failed to parse readiness history line: {e}")

    return results


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/api/v1/crypto/readiness/status", response_model=ReadinessCheckResult)
async def get_readiness_status() -> ReadinessCheckResult:
    """
    Get current crypto coverage readiness status.

    Runs the readiness script and returns the results.
    """
    start_time = time.time()

    try:
        # Run readiness script with JSON output
        result = subprocess.run(
            ["python", "scripts/kalshi_crypto_live_readiness.py", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent.parent.parent,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if result.returncode != 0:
            # Parse what we can from the output
            logger.warning(f"Readiness script failed with exit code {result.returncode}")

        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse readiness script output: {result.stdout[:200]}"
            )

        # Extract key metrics
        readiness_result = ReadinessCheckResult(
            timestamp=datetime.now(),
            live_ready=data.get("live_ready", False),
            blocking_failures=data.get("blocking_failures", []),
            env_vars_valid=sum(1 for v in data.get("env_vars", []) if v.get("is_valid")),
            env_vars_total=len(data.get("env_vars", [])),
            formulas_valid=sum(1 for f in data.get("formulas", []) if f.get("status") == "OK"),
            formulas_total=len(data.get("formulas", [])),
            proposals_valid=sum(1 for p in data.get("proposals", []) if p.get("status") == "OK"),
            proposals_total=len(data.get("proposals", [])),
            markets_covered=sum(1 for c in data.get("coverage", [])
                              if c.get("catalog_ok") and c.get("strategy_ok") and c.get("sizing_ok") and c.get("execution_ok")),
            markets_total=25,
            config_validation=data.get("dry_run", {}).get("config_validation", False),
            data_feeds_healthy=data.get("dry_run", {}).get("data_feeds_healthy", False),
            cfb_status=data.get("dry_run", {}).get("cfb_status"),
            duration_ms=duration_ms,
        )

        # Save to history
        _save_readiness_result(readiness_result)

        return readiness_result

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Readiness check timed out after 30 seconds"
        )
    except Exception as e:
        logger.exception("Failed to run readiness check")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run readiness check: {str(e)}"
        )


@router.get("/api/v1/crypto/readiness/history", response_model=ReadinessHistory)
async def get_readiness_history(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of history entries")
) -> ReadinessHistory:
    """
    Get historical crypto coverage readiness results.

    Returns recent readiness check results with uptime statistics.
    """
    history = _load_readiness_history(limit=limit)

    if not history:
        return ReadinessHistory(
            latest=None,
            history=[],
            uptime_pct=0.0,
            total_checks=0
        )

    # Calculate uptime percentage
    passed_checks = sum(1 for r in history if r.live_ready)
    uptime_pct = (passed_checks / len(history) * 100) if history else 0.0

    return ReadinessHistory(
        latest=history[-1] if history else None,
        history=history,
        uptime_pct=round(uptime_pct, 2),
        total_checks=len(history)
    )


@router.get("/api/v1/crypto/readiness/matrix", response_model=Matrix25Status)
async def get_readiness_matrix() -> Matrix25Status:
    """
    Get 25-cell market coverage matrix status.

    Returns health status for each asset × timeframe combination.
    """
    start_time = time.time()

    try:
        # Run readiness script with JSON output
        result = subprocess.run(
            ["python", "scripts/kalshi_crypto_live_readiness.py", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500,
                detail="Failed to parse readiness script output"
            )

        # Build market cell status list
        cells = []
        for cell_data in data.get("coverage", []):
            overall_ok = (
                cell_data.get("catalog_ok", False) and
                cell_data.get("strategy_ok", False) and
                cell_data.get("sizing_ok", False) and
                cell_data.get("execution_ok", False) and
                cell_data.get("monitor_ok", False)
            )

            cells.append(MarketCellStatus(
                asset=cell_data.get("asset", ""),
                timeframe=cell_data.get("timeframe", ""),
                catalog_ok=cell_data.get("catalog_ok", False),
                strategy_ok=cell_data.get("strategy_ok", False),
                sizing_ok=cell_data.get("sizing_ok", False),
                execution_ok=cell_data.get("execution_ok", False),
                monitor_ok=cell_data.get("monitor_ok", False),
                overall_ok=overall_ok,
                notes=cell_data.get("notes", "")
            ))

        # Count market health
        healthy = sum(1 for c in cells if c.overall_ok)
        degraded = sum(1 for c in cells if not c.overall_ok and (c.catalog_ok or c.strategy_ok))
        failed = sum(1 for c in cells if not c.catalog_ok and not c.strategy_ok)

        return Matrix25Status(
            cells=cells,
            total_markets=25,
            healthy_markets=healthy,
            degraded_markets=degraded,
            failed_markets=failed,
            last_updated=datetime.now()
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Matrix status check timed out"
        )
    except Exception as e:
        logger.exception("Failed to get matrix status")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get matrix status: {str(e)}"
        )


@router.post("/api/v1/crypto/readiness/check")
async def trigger_readiness_check() -> dict:
    """
    Trigger an on-demand readiness check.

    Returns a job ID for tracking the check progress.
    """
    # For simplicity, run synchronously
    result = await get_readiness_status()

    return {
        "status": "completed",
        "result": result.model_dump(),
        "message": "Readiness check completed"
    }
