# web/api/kalshi_execution_telemetry_api.py
"""Kalshi execution telemetry API endpoint."""

from fastapi import APIRouter, Depends
from web.api.auth import get_current_session
from utils.logger import get_logger
from merid.kalshi.execution_telemetry import get_execution_telemetry_tracker

logger = get_logger("web.api.kalshi_execution_telemetry")

router = APIRouter(
    prefix="/api/v1/kalshi-grid/performance",
    tags=["Kalshi Execution Telemetry"],
)


@router.get("/execution")
async def get_execution_telemetry():
    """Get execution latency and slippage metrics for crypto products."""
    try:
        tracker = get_execution_telemetry_tracker()
        metrics = tracker.get_all_metrics()
        
        # Add threshold status
        thresholds = {
            "submit_ack_p50_good": 50.0,  # ms
            "submit_ack_p90_good": 100.0,
            "submit_fill_p50_good": 200.0,
            "submit_fill_p90_good": 500.0,
            "avg_slippage_cents_good": 2.0,
        }
        
        status = {}
        for product, product_metrics in metrics.items():
            product_status = {}
            for metric, value in product_metrics.items():
                threshold_key = f"{metric.split('_', 1)[1]}_good"  # Remove product prefix
                if threshold_key in thresholds:
                    product_status[metric] = {
                        "value": value,
                        "status": "good" if value <= thresholds[threshold_key] else "warning",
                        "threshold": thresholds[threshold_key]
                    }
                else:
                    product_status[metric] = {"value": value, "status": "info"}
            status[product] = product_status
        
        return {
            "metrics": metrics,
            "status": status,
            "timestamp": logger.info("Execution telemetry retrieved")
        }
    except Exception as exc:
        logger.error(f"Failed to get execution telemetry: {exc}")
        return {
            "metrics": {},
            "status": {},
            "error": str(exc)
        }
