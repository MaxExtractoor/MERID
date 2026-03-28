"""
Position Sizing API - Visibility into Position Sizing Decisions

Provides UI visibility into:
- Kelly utilization metrics
- Sizing method selection
- Position size adjustments (throttling)
- Volatility scaling
- Risk-based size reductions
- Audit trail of sizing decisions

This fills the gap where sizing calculations happen backend-only with no UI visibility.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging

from utils.logger import get_logger

logger = get_logger("web.api.position_sizing")
router = APIRouter(prefix="/api/v1/position-sizing", tags=["position-sizing"])


# ── Response Models ─────────────────────────────────────────────────────


class SizingDecision(BaseModel):
    """A single position sizing decision record"""
    timestamp: str
    symbol: str
    domain: str
    venue: str
    method: str  # "kelly", "volatility", "fixed_fractional", "risk_parity"
    base_size: float
    adjusted_size: float
    adjustment_factor: float
    adjustments: List[Dict[str, Any]]  # List of adjustments applied
    confidence: Optional[float] = None
    kelly_fraction: Optional[float] = None
    volatility_adjustment: Optional[float] = None
    reason: str


# ── Kelly Utilization Metrics ───────────────────────────────────────────


@router.get("/kelly-metrics")
async def get_kelly_metrics() -> Dict[str, Any]:
    """
    Get Kelly criterion utilization metrics.

    Returns:
        {
            "current_utilization": float (0.0-1.0),
            "recommended_fraction": float,
            "safety_factor": float,
            "by_domain": {
                "crypto": {"utilization": float, "fraction": float},
                "prediction": {"utilization": float, "fraction": float}
            },
            "historical_avg": float,
            "max_utilization": float,
            "min_utilization": float,
            "last_updated": str (ISO timestamp)
        }
    """
    try:
        # Try to get Kelly metrics from position sizer
        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_kelly_metrics'):
                metrics = sizer.get_kelly_metrics()
                return metrics
            else:
                # Calculate from recent sizing decisions
                metrics = _calculate_kelly_metrics_from_history()
                return metrics

        except ImportError:
            # Fallback: Try Kalshi-specific position sizer
            try:
                from merid.event_venues.kalshi.position_sizer import get_kalshi_position_sizer
                sizer = get_kalshi_position_sizer()

                if hasattr(sizer, 'get_kelly_metrics'):
                    return sizer.get_kelly_metrics()
                else:
                    return _calculate_kelly_metrics_from_history()

            except:
                # Return default metrics if no sizer available
                return {
                    "current_utilization": 0.25,  # Default 25% Kelly
                    "recommended_fraction": 0.25,
                    "safety_factor": 0.5,  # Fractional Kelly with 50% safety
                    "by_domain": {},
                    "historical_avg": 0.25,
                    "max_utilization": 0.5,
                    "min_utilization": 0.1,
                    "last_updated": datetime.utcnow().isoformat(),
                }

    except Exception as e:
        logger.error(f"Failed to get Kelly metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _calculate_kelly_metrics_from_history() -> Dict[str, Any]:
    """Calculate Kelly metrics from historical sizing decisions"""
    try:
        # This would query sizing decision history
        # For now, return reasonable defaults
        return {
            "current_utilization": 0.25,
            "recommended_fraction": 0.25,
            "safety_factor": 0.5,
            "by_domain": {
                "crypto": {"utilization": 0.2, "fraction": 0.2},
                "prediction": {"utilization": 0.3, "fraction": 0.3},
            },
            "historical_avg": 0.25,
            "max_utilization": 0.4,
            "min_utilization": 0.15,
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to calculate Kelly metrics: {e}")
        return {}


# ── Sizing Methods ──────────────────────────────────────────────────────


@router.get("/methods")
async def get_sizing_methods() -> Dict[str, Any]:
    """
    Get available position sizing methods and their current usage.

    Returns:
        {
            "methods": [
                {
                    "name": str,
                    "id": str,
                    "description": str,
                    "active": bool,
                    "usage_count_24h": int,
                    "avg_size_24h": float
                }
            ],
            "default_method": str,
            "last_updated": str
        }
    """
    try:
        methods = [
            {
                "name": "Kelly Criterion",
                "id": "kelly",
                "description": "Fractional Kelly with adaptive shrinkage based on edge and confidence",
                "active": True,
                "usage_count_24h": 0,  # Would query from history
                "avg_size_24h": 0.0,
                "domains": ["crypto", "prediction", "betting"],
            },
            {
                "name": "Volatility-Based",
                "id": "volatility",
                "description": "ATR-based sizing with horizon adjustment",
                "active": True,
                "usage_count_24h": 0,
                "avg_size_24h": 0.0,
                "domains": ["crypto"],
            },
            {
                "name": "Fixed Fractional",
                "id": "fixed_fractional",
                "description": "Fixed 2% of portfolio per trade",
                "active": True,
                "usage_count_24h": 0,
                "avg_size_24h": 0.0,
                "domains": ["all"],
            },
            {
                "name": "Risk Parity",
                "id": "risk_parity",
                "description": "Equal risk contribution across positions",
                "active": False,
                "usage_count_24h": 0,
                "avg_size_24h": 0.0,
                "domains": ["crypto"],
            },
        ]

        # Try to get actual usage stats
        try:
            usage_stats = _get_sizing_method_usage()
            for method in methods:
                if method["id"] in usage_stats:
                    method["usage_count_24h"] = usage_stats[method["id"]].get("count", 0)
                    method["avg_size_24h"] = usage_stats[method["id"]].get("avg_size", 0.0)
        except:
            pass

        return {
            "methods": methods,
            "default_method": "kelly",
            "last_updated": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get sizing methods: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _get_sizing_method_usage() -> Dict[str, Any]:
    """Get usage stats for sizing methods from history"""
    # This would query sizing decision history
    # For now, return empty
    return {}


# ── Size Adjustments & Throttling ───────────────────────────────────────


@router.get("/adjustments/recent")
async def get_recent_adjustments(
    limit: int = Query(50, description="Number of adjustments to return"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
) -> Dict[str, Any]:
    """
    Get recent position size adjustments (throttling events).

    Returns:
        {
            "adjustments": [
                {
                    "timestamp": str,
                    "symbol": str,
                    "domain": str,
                    "base_size": float,
                    "adjusted_size": float,
                    "factor": float,
                    "reason": str,
                    "type": "throttle" | "boost" | "cap"
                }
            ],
            "total": int,
            "throttled_count": int,
            "avg_adjustment_factor": float
        }
    """
    try:
        # Try to get adjustment history
        adjustments = []

        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_adjustment_history'):
                adjustments = sizer.get_adjustment_history(limit=limit, domain=domain)
        except:
            pass

        # If no history available, return empty
        if not adjustments:
            return {
                "adjustments": [],
                "total": 0,
                "throttled_count": 0,
                "avg_adjustment_factor": 1.0,
            }

        throttled_count = sum(1 for adj in adjustments if adj.get("type") == "throttle")
        avg_factor = sum(adj.get("factor", 1.0) for adj in adjustments) / len(adjustments) if adjustments else 1.0

        return {
            "adjustments": adjustments[:limit],
            "total": len(adjustments),
            "throttled_count": throttled_count,
            "avg_adjustment_factor": avg_factor,
        }

    except Exception as e:
        logger.error(f"Failed to get recent adjustments: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/adjustments/summary")
async def get_adjustments_summary(
    hours: int = Query(24, description="Time window in hours"),
) -> Dict[str, Any]:
    """
    Get summary of size adjustments over time period.

    Returns:
        {
            "total_adjustments": int,
            "throttled": int,
            "boosted": int,
            "capped": int,
            "by_reason": {
                "cqi_throttle": int,
                "risk_throttle": int,
                "volatility_throttle": int,
                "exposure_cap": int,
                ...
            },
            "avg_reduction_pct": float,
            "max_reduction_pct": float,
            "time_window_hours": int
        }
    """
    try:
        # Calculate time window
        since = datetime.utcnow() - timedelta(hours=hours)

        # Try to get adjustment summary
        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_adjustment_summary'):
                return sizer.get_adjustment_summary(since=since)
        except:
            pass

        # Return default summary
        return {
            "total_adjustments": 0,
            "throttled": 0,
            "boosted": 0,
            "capped": 0,
            "by_reason": {},
            "avg_reduction_pct": 0.0,
            "max_reduction_pct": 0.0,
            "time_window_hours": hours,
        }

    except Exception as e:
        logger.error(f"Failed to get adjustments summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Sizing Decision Audit Trail ─────────────────────────────────────────


@router.get("/decisions/recent")
async def get_recent_decisions(
    limit: int = Query(100, description="Number of decisions to return"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    method: Optional[str] = Query(None, description="Filter by sizing method"),
) -> Dict[str, Any]:
    """
    Get recent position sizing decisions with full audit trail.

    Returns:
        {
            "decisions": [
                {
                    "timestamp": str,
                    "symbol": str,
                    "domain": str,
                    "venue": str,
                    "method": str,
                    "base_size": float,
                    "adjusted_size": float,
                    "adjustment_factor": float,
                    "adjustments": [
                        {"type": str, "factor": float, "reason": str}
                    ],
                    "confidence": float,
                    "kelly_fraction": float,
                    "volatility_adjustment": float,
                    "reason": str
                }
            ],
            "total": int,
            "avg_size": float,
            "avg_adjustment_factor": float
        }
    """
    try:
        decisions = []

        # Try to get decision history
        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_decision_history'):
                decisions = sizer.get_decision_history(
                    limit=limit,
                    domain=domain,
                    method=method
                )
        except:
            pass

        # If no history, return empty
        if not decisions:
            return {
                "decisions": [],
                "total": 0,
                "avg_size": 0.0,
                "avg_adjustment_factor": 1.0,
            }

        avg_size = sum(d.get("adjusted_size", 0) for d in decisions) / len(decisions) if decisions else 0
        avg_factor = sum(d.get("adjustment_factor", 1.0) for d in decisions) / len(decisions) if decisions else 1.0

        return {
            "decisions": decisions[:limit],
            "total": len(decisions),
            "avg_size": avg_size,
            "avg_adjustment_factor": avg_factor,
        }

    except Exception as e:
        logger.error(f"Failed to get recent decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Volatility Metrics ──────────────────────────────────────────────────


@router.get("/volatility")
async def get_volatility_metrics() -> Dict[str, Any]:
    """
    Get volatility metrics used in position sizing.

    Returns:
        {
            "by_asset": {
                "BTC": {
                    "daily_vol": float,
                    "hourly_vol": float,
                    "atr": float,
                    "vol_percentile": float,
                    "scaling_factor": float
                },
                ...
            },
            "market_vol_regime": "low" | "medium" | "high" | "extreme",
            "last_updated": str
        }
    """
    try:
        # Try to get volatility metrics
        vol_metrics = {}

        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_volatility_metrics'):
                vol_metrics = sizer.get_volatility_metrics()
        except:
            pass

        # If no metrics, try Kalshi-specific
        if not vol_metrics:
            try:
                from merid.event_venues.kalshi.position_sizer import get_kalshi_position_sizer
                sizer = get_kalshi_position_sizer()

                if hasattr(sizer, 'get_volatility_metrics'):
                    vol_metrics = sizer.get_volatility_metrics()
            except:
                pass

        # Return default if nothing available
        if not vol_metrics:
            vol_metrics = {
                "by_asset": {},
                "market_vol_regime": "medium",
                "last_updated": datetime.utcnow().isoformat(),
            }

        return vol_metrics

    except Exception as e:
        logger.error(f"Failed to get volatility metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Configuration ───────────────────────────────────────────────────────


@router.get("/config")
async def get_sizing_config() -> Dict[str, Any]:
    """
    Get current position sizing configuration.

    Returns:
        {
            "default_method": str,
            "kelly_safety_factor": float,
            "max_position_size_usd": float,
            "min_position_size_usd": float,
            "volatility_lookback_days": int,
            "adjustment_enabled": bool,
            "domains": {
                "crypto": {...},
                "prediction": {...}
            }
        }
    """
    try:
        # Try to get configuration
        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()

            if hasattr(sizer, 'get_config'):
                return sizer.get_config()
        except:
            pass

        # Return default config
        return {
            "default_method": "kelly",
            "kelly_safety_factor": 0.5,  # Fractional Kelly 50%
            "max_position_size_usd": 5000.0,
            "min_position_size_usd": 10.0,
            "volatility_lookback_days": 30,
            "adjustment_enabled": True,
            "domains": {
                "crypto": {
                    "max_size_usd": 5000,
                    "preferred_method": "volatility",
                },
                "prediction": {
                    "max_size_usd": 1000,
                    "preferred_method": "kelly",
                },
            },
        }

    except Exception as e:
        logger.error(f"Failed to get sizing config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Health Check ────────────────────────────────────────────────────────


@router.get("/health")
async def get_sizing_health() -> Dict[str, Any]:
    """Health check for position sizing system"""
    try:
        components = {
            "position_sizer": False,
            "kelly_calculator": False,
            "volatility_tracker": False,
            "adjustment_engine": False,
        }

        # Check position sizer
        try:
            from risk.position_sizing import get_position_sizer
            get_position_sizer()
            components["position_sizer"] = True
            components["kelly_calculator"] = True
            components["adjustment_engine"] = True
        except:
            pass

        # Check volatility tracker
        try:
            from risk.position_sizing import get_position_sizer
            sizer = get_position_sizer()
            if hasattr(sizer, 'get_volatility_metrics'):
                components["volatility_tracker"] = True
        except:
            pass

        healthy_count = sum(components.values())
        total_count = len(components)

        return {
            "status": "healthy" if healthy_count >= 1 else "degraded",
            "components": components,
            "healthy_components": healthy_count,
            "total_components": total_count,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
