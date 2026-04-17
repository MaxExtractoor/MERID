"""MERID Pre-Live Benchmark API.

Exposes benchmark report to the dashboard for go-live readiness assessment.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])

_BENCHMARK_TIMEOUT_S = 5
_executor = ThreadPoolExecutor(max_workers=1)

_ERROR_RESPONSE = {
    "overall": "error",
    "benchmarks": [],
    "summary": {"pass": 0, "warn": 0, "fail": 0, "no_data": 0, "total": 0},
    "go_live_ready": False,
}


@router.get("/report")
async def get_benchmark_report():
    """Get full benchmark report with all 5 categories."""
    try:
        from merid.benchmarks import get_benchmark_collector
        collector = get_benchmark_collector()
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(_executor, collector.collect_all),
            timeout=_BENCHMARK_TIMEOUT_S,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning("Benchmark report timed out after %ss", _BENCHMARK_TIMEOUT_S)
        return {**_ERROR_RESPONSE, "error": f"Timed out after {_BENCHMARK_TIMEOUT_S}s"}
    except Exception as e:
        logger.error(f"Benchmark report error: {e}")
        return {**_ERROR_RESPONSE, "error": str(e)}


@router.get("/targets")
async def get_benchmark_targets():
    """Get current benchmark target thresholds."""
    try:
        from merid.benchmarks import TARGETS
        from dataclasses import asdict
        return {"targets": asdict(TARGETS)}
    except Exception as e:
        return {"error": str(e)}
