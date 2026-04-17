"""Policy and Fee Metrics API — Dashboard endpoints for policy/fee insights.

Endpoints:
- GET /api/v1/kalshi/policy-metrics — Daily policy metrics (policy mix, role stats, fee validation)
- GET /api/v1/kalshi/policy-anomalies — Recent anomalies (role mismatches, fee deviations)
- GET /api/v1/kalshi/edge-vs-fees — Edge capture efficiency metrics

Usage::

    # Get today's policy metrics
    GET /api/v1/kalshi/policy-metrics

    # Get metrics for specific date
    GET /api/v1/kalshi/policy-metrics?date=2026-03-24

    # Get recent anomalies
    GET /api/v1/kalshi/policy-anomalies?hours=24
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from utils.logger import get_logger

logger = get_logger("merid.web.api.policy_metrics_api")

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi", "policy", "metrics"])


@router.get("/policy-metrics")
async def get_policy_metrics(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
) -> Dict[str, Any]:
    """Get policy metrics for a specific date.

    Returns:
        - Total fills, contracts, fees
        - Policy mode distribution (counts and percentages)
        - Role statistics (expected vs actual, mismatch rate)
        - Fee validation results (pass/fail rates)
        - Edge metrics (avg edge, net of fees)
        - Health indicators (mismatch rate, fee failure rate)
    """
    try:
        from merid.event_venues.kalshi.policy_sanity_harness import get_policy_sanity_harness

        harness = get_policy_sanity_harness()
        metrics = harness.get_metrics_for_dashboard()

        # If specific date requested, override with that date's summary
        if date:
            summary = harness.get_daily_summary(date)
            metrics["today"] = summary

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": metrics,
        }

    except Exception as exc:
        logger.error("[policy-metrics-api] Failed to get policy metrics: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get policy metrics: {str(exc)}",
            },
        )


@router.get("/policy-anomalies")
async def get_policy_anomalies(
    hours: float = Query(24.0, description="Lookback period in hours", ge=1.0, le=168.0),
    include_role_mismatches: bool = Query(True, description="Include role mismatch anomalies"),
    include_fee_deviations: bool = Query(True, description="Include fee deviation anomalies"),
) -> Dict[str, Any]:
    """Get recent policy/fee anomalies.

    Returns:
        - Role mismatches (expected vs actual role differ)
        - Fee deviations (actual fee differs from regression table)
        - Timestamps and details for each anomaly
    """
    try:
        from merid.event_venues.kalshi.policy_sanity_harness import get_policy_sanity_harness

        harness = get_policy_sanity_harness()
        anomalies = harness.get_recent_anomalies(
            since_hours=hours,
            include_role_mismatches=include_role_mismatches,
            include_fee_deviations=include_fee_deviations,
        )

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lookback_hours": hours,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
        }

    except Exception as exc:
        logger.error("[policy-metrics-api] Failed to get anomalies: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get anomalies: {str(exc)}",
            },
        )


@router.get("/edge-vs-fees")
async def get_edge_vs_fees(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
) -> Dict[str, Any]:
    """Get edge vs fees analysis.

    Returns:
        - Average edge percentage
        - Average fees as percentage of notional
        - Net edge (edge minus fees)
        - Edge capture efficiency by policy mode
    """
    try:
        from merid.event_venues.kalshi.policy_sanity_harness import get_policy_sanity_harness

        harness = get_policy_sanity_harness()

        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        summary = harness.get_daily_summary(date)

        edge_metrics = summary.get("edge_metrics", {})
        total_fills = summary.get("total_fills", 0)
        total_fees_usd = summary.get("total_fees_usd", 0)

        # Calculate efficiency metrics
        avg_edge = edge_metrics.get("avg_edge_pct", 0)
        net_edge = edge_metrics.get("total_net_edge_pct", 0)

        efficiency = {
            "avg_edge_pct": avg_edge,
            "net_edge_pct": net_edge,
            "fee_drag_pct": avg_edge - net_edge if avg_edge > 0 else 0,
            "edge_capture_ratio": (
                net_edge / avg_edge if avg_edge > 0 else 0
            ),
        }

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "total_fills": total_fills,
            "total_fees_usd": total_fees_usd,
            "efficiency": efficiency,
            "raw_edge_metrics": edge_metrics,
        }

    except Exception as exc:
        logger.error("[policy-metrics-api] Failed to get edge vs fees: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get edge vs fees: {str(exc)}",
            },
        )


@router.get("/policy-summary")
async def get_policy_summary() -> Dict[str, Any]:
    """Get high-level policy summary for dashboard cards.

    Returns condensed metrics suitable for dashboard summary cards:
    - Today's fill count
    - Policy mode mix (pie chart data)
    - Role accuracy percentage
    - Fee validation health
    """
    try:
        from merid.event_venues.kalshi.policy_sanity_harness import get_policy_sanity_harness

        harness = get_policy_sanity_harness()
        metrics = harness.get_metrics_for_dashboard()

        today = metrics.get("today", {})
        health = metrics.get("health", {})
        policy_mix = metrics.get("policy_mix_pct", {})

        # Format for dashboard cards
        summary = {
            "today_fills": today.get("total_fills", 0),
            "today_contracts": today.get("total_contracts", 0),
            "today_fees_usd": today.get("total_fees_usd", 0),
            "policy_mix": policy_mix,
            "role_accuracy_pct": round(
                (1 - health.get("role_mismatch_rate", 0)) * 100, 2
            ),
            "fee_validation_pass_pct": round(
                (1 - health.get("fee_validation_failure_rate", 0)) * 100, 2
            ),
            "health_status": "healthy" if (
                health.get("role_mismatch_rate", 0) < 0.05 and
                health.get("fee_validation_failure_rate", 0) < 0.05
            ) else "warning",
        }

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }

    except Exception as exc:
        logger.error("[policy-metrics-api] Failed to get summary: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get summary: {str(exc)}",
            },
        )
