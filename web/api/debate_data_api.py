"""
Debate Data API Endpoints
Provides alerts, historical contribution series, and rollups per the frontend contracts.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/debates", tags=["debate-data"])
logger = get_logger("web.api.debate_data_api")


def _empty_correlation() -> Dict[str, Any]:
    """Return empty-but-valid correlation shape so the UI renders 'no data' cleanly."""
    empty_bucket = {"avg_pnl": 0, "total_trades": 0, "win_rate": 0}
    return {
        "overall_correlation": 0,
        "performance_by_status": {
            "healthy": empty_bucket,
            "degraded": empty_bucket,
            "critical": empty_bucket,
        },
        "recent_trades": [],
    }


# ── Error helpers ───────────────────────────────────────────────────────────


def _json_error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error_code": code,
        "message": message,
    }
    if details:
        payload["details"] = details
    return payload

# ── Response Models ────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    """Single alert item."""
    agent_id: str
    tier: str
    utilization_pct: float
    metric_id: str
    metric_label: str
    severity: str  # "warning" | "critical"
    message: str
    triggered_at: str  # ISO timestamp
    supporting_values: Dict[str, Any]

class AlertsResponse(BaseModel):
    """Alerts feed response."""
    window_days: int
    generated_at: str
    alerts: List[AlertItem]

class HistoricalPoint(BaseModel):
    """Historical contribution point."""
    timestamp: str  # ISO timestamp
    debate_contribution_pct: float
    win_rate: float
    utilization_pct: float

class HistoricalResponse(BaseModel):
    """Historical contribution series response."""
    agent_id: str
    window_days: int
    points: List[HistoricalPoint]

class RollupRow(BaseModel):
    """Rollup row for team/strategy."""
    id: str
    label: str
    debate_contribution_pct: float
    sharpe_delta: float
    drawdown_delta: float
    agents: List[str]
    utilization_pct: float

class RollupsResponse(BaseModel):
    """Rollups response."""
    group_by: str
    window_days: int
    rows: List[RollupRow]

# ── Implementation Helpers ───────────────────────────────────────────────────

def _get_utilization_band(value: float) -> str:
    """Map utilization percentage to band."""
    if value < 0.33:
        return "low"
    elif value < 0.67:
        return "medium"
    else:
        return "high"

def _evaluate_alert_thresholds(
    utilization_pct: float,
    debate_contribution_pct: float,
    tier: str,
    quota_pct: Optional[float] = None
) -> List[AlertItem]:
    """Generate alerts based on thresholds."""
    alerts = []
    
    # Utilization alert
    if utilization_pct > 0.9:
        alerts.append(AlertItem(
            agent_id="",  # Will be filled by caller
            tier=tier,
            utilization_pct=utilization_pct,
            metric_id="quota-saturation",
            metric_label="Quota utilization above 90%",
            severity="critical" if utilization_pct > 0.95 else "warning",
            message=f"Agent has consumed {utilization_pct:.0%} of allocated debate quota",
            triggered_at=datetime.now(timezone.utc).isoformat(),
            supporting_values={
                "quota_pct": quota_pct or 0.25,  # Use real quota if provided
                "debate_contribution_pct": debate_contribution_pct
            }
        ))
    
    # Negative contribution alert
    if debate_contribution_pct < 0:
        alerts.append(AlertItem(
            agent_id="",  # Will be filled by caller
            tier=tier,
            utilization_pct=utilization_pct,
            metric_id="negative-contribution",
            metric_label="Negative debate contribution",
            severity="critical" if debate_contribution_pct < -0.05 else "warning",
            message=f"Agent debate contribution is {debate_contribution_pct:.1%}",
            triggered_at=datetime.now(timezone.utc).isoformat(),
            supporting_values={
                "debate_contribution_pct": debate_contribution_pct,
                "utilization_pct": utilization_pct
            }
        ))
    
    return alerts

# ── API Endpoints ────────────────────────────────────────────────────────

@router.get("/alerts", response_model=AlertsResponse)
async def get_debate_alerts(
    days_back: int = Query(default=7, description="Window in days"),
    tier: str = Query(default="all", description="Filter by tier"),
    utilization_band: str = Query(default="all", description="Filter by utilization band"),
    problems_only: bool = Query(default=False, description="Return only triggered alerts")
):
    """
    Get debate-driven anomalies and alerts.
    
    Args:
        days_back: Window in days to analyze
        tier: Filter by agent tier (gold|silver|bronze|restricted|all)
        utilization_band: Filter by utilization band (low|medium|high|all)
        problems_only: Return only alerts (no informational messages)
        
    Returns:
        Alerts feed with newest→oldest ordering
    """
    request_ctx = {
        "days_back": days_back,
        "tier": tier,
        "utilization_band": utilization_band,
        "problems_only": problems_only,
    }
    logger.info("debate_alerts_request", extra={"request": request_ctx})

    try:
        valid_tiers = {"gold", "silver", "bronze", "restricted", "all"}
        valid_bands = {"low", "medium", "high", "all"}
        if tier not in valid_tiers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_json_error(
                    "DEBATE_INVALID_TIER",
                    "Invalid tier filter",
                    {"tier": tier, "allowed": sorted(valid_tiers)}))
        if utilization_band not in valid_bands:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_json_error(
                    "DEBATE_INVALID_UTILIZATION_BAND",
                    "Invalid utilization band filter",
                    {"utilization_band": utilization_band, "allowed": sorted(valid_bands)}))

        from merid.prediction.agent_risk_quotas import get_agent_risk_quota_manager
        from merid.prediction.pnl_attribution import get_pnl_attribution_engine

        quota_manager = get_agent_risk_quota_manager()
        attribution_engine = get_pnl_attribution_engine()

        quota_summary = quota_manager.get_risk_quota_summary()
        try:
            attribution_summary = await asyncio.wait_for(
                attribution_engine.generate_attribution_summary(period_days=days_back),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.debug("debate_alerts: attribution summary timed out, returning empty")
            return AlertsResponse(
                window_days=days_back,
                generated_at=datetime.now(timezone.utc).isoformat(),
                alerts=[])

        all_alerts = []

        for agent_id, profile in quota_summary.items():
            if tier != "all" and profile["tier"] != tier:
                continue

            if utilization_band != "all":
                band = _get_utilization_band(profile["utilization_pct"])
                if band != utilization_band:
                    continue

            contribution_pct = 0.0
            if agent_id in attribution_summary.agent_contributions:
                contribution_pct = attribution_summary.agent_contributions[agent_id].get("debate_contribution_pct", 0.0)

            agent_alerts = _evaluate_alert_thresholds(
                utilization_pct=profile["utilization_pct"],
                debate_contribution_pct=contribution_pct,
                tier=profile["tier"],
                quota_pct=profile.get("quota_pct"))

            for alert in agent_alerts:
                alert.agent_id = agent_id
                all_alerts.append(alert)

        if problems_only:
            all_alerts = [a for a in all_alerts if a.severity in ("warning", "critical")]

        all_alerts.sort(key=lambda x: x.triggered_at, reverse=True)

        logger.info(
            "debate_alerts_success",
            extra={"request": request_ctx, "alert_count": len(all_alerts)})

        return AlertsResponse(
            window_days=days_back,
            generated_at=datetime.now(timezone.utc).isoformat(),
            alerts=all_alerts)

    except HTTPException:
        raise
    except ModuleNotFoundError as exc:
        logger.debug(
            "debate_alerts_dependency_missing",
            extra={"request": request_ctx, "dependency": str(exc)})
    except Exception as exc:
        logger.debug(
            "debate_alerts_primary_failed",
            extra={"request": request_ctx, "reason": str(exc)})

    # Fallback: derive alerts from debate store + agent grid
    fallback_alerts: List[AlertItem] = []
    _now_iso = datetime.now(timezone.utc).isoformat()
    try:
        from merid.prediction.debate import get_debate_store
        store = get_debate_store()
        for debate in store.list_debates(limit=30):
            prob_shift = abs(getattr(debate, "post_debate_prob", 0.5) - getattr(debate, "pre_debate_prob", 0.5))
            rounds = getattr(debate, "rounds", 0)
            symbol = getattr(debate, "symbol", "?")
            team = getattr(debate, "team_id", "unknown") or "swarm"
            ts = str(getattr(debate, "created_at", _now_iso))

            if prob_shift > 0.05:
                sev = "critical" if prob_shift > 0.2 else "warning"
                fallback_alerts.append(AlertItem(
                    agent_id=team, tier="silver", utilization_pct=prob_shift,
                    metric_id="probability-shift", metric_label="Probability shift detected",
                    severity=sev,
                    message=f"Debate {debate.id[:12]} on {symbol}: probability shifted by {prob_shift:.0%} ({rounds} rounds)",
                    triggered_at=ts,
                    supporting_values={"debate_id": debate.id, "shift": round(prob_shift, 3), "rounds": rounds},
                ))
            elif rounds >= 3:
                fallback_alerts.append(AlertItem(
                    agent_id=team, tier="silver", utilization_pct=0.0,
                    metric_id="multi-round-debate", metric_label="Multi-round debate",
                    severity="warning",
                    message=f"Debate {debate.id[:12]} went {rounds} rounds on {symbol}",
                    triggered_at=ts,
                    supporting_values={"debate_id": debate.id, "rounds": rounds},
                ))
            else:
                # Informational: debate activity
                fallback_alerts.append(AlertItem(
                    agent_id=team, tier="bronze", utilization_pct=0.0,
                    metric_id="debate-activity", metric_label="Debate activity",
                    severity="info" if not problems_only else "warning",
                    message=f"Debate {debate.id[:12]} on {symbol}: {rounds} rounds, shift {prob_shift:.0%}",
                    triggered_at=ts,
                    supporting_values={"debate_id": debate.id, "shift": round(prob_shift, 3), "rounds": rounds},
                ))
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        idle_agents = [a for a in grid.agents if a.state.cycles_run > 0 and a.state.orders_placed == 0]
        if idle_agents:
            sample = ", ".join(a.config.name for a in idle_agents[:5])
            fallback_alerts.append(AlertItem(
                agent_id="fleet", tier="bronze", utilization_pct=0.0,
                metric_id="no-orders", metric_label="No orders placed",
                severity="warning",
                message=f"{len(idle_agents)} agents scanning but 0 orders: {sample}",
                triggered_at=_now_iso,
                supporting_values={"count": len(idle_agents)},
            ))
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    if problems_only:
        fallback_alerts = [a for a in fallback_alerts if a.severity in ("warning", "critical")]

    return AlertsResponse(
        window_days=days_back,
        generated_at=_now_iso,
        alerts=fallback_alerts)


@router.get("/correlation")
async def get_debate_correlation(
    days_back: int = Query(default=7, description="Window in days"),
):
    """Correlation between debate health state and trading PnL.

    Shape consumed by DebateCorrelationPanel.tsx:
      { overall_correlation, performance_by_status: { healthy|degraded|critical: {avg_pnl, total_trades, win_rate} }, recent_trades: [...] }
    """
    try:
        from merid.prediction.pnl_attribution import get_pnl_attribution_engine
        engine = get_pnl_attribution_engine()

        try:
            summary = await asyncio.wait_for(
                engine.generate_attribution_summary(period_days=days_back),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.debug("debate_correlation: attribution summary timed out")
            return _empty_correlation()

        # Aggregate performance by debate status
        buckets: Dict[str, Dict[str, Any]] = {
            "healthy": {"pnl_sum": 0.0, "wins": 0, "total": 0},
            "degraded": {"pnl_sum": 0.0, "wins": 0, "total": 0},
            "critical": {"pnl_sum": 0.0, "wins": 0, "total": 0},
        }

        recent_trades: List[Dict[str, Any]] = []

        for agent_id, contrib in (summary.agent_contributions or {}).items():
            debate_status = contrib.get("debate_status", "healthy")
            pnl = float(contrib.get("pnl", 0))
            win = float(contrib.get("win_rate", 0))
            trades = int(contrib.get("trade_count", 1))
            alerts = int(contrib.get("debate_alerts", 0))

            bucket_key = debate_status if debate_status in buckets else "healthy"
            buckets[bucket_key]["pnl_sum"] += pnl
            buckets[bucket_key]["wins"] += int(win >= 0.5) * trades
            buckets[bucket_key]["total"] += trades

            recent_trades.append({
                "timestamp": contrib.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "pnl": round(pnl, 2),
                "debate_status": debate_status,
                "debate_alerts": alerts,
                "trade_count": trades,
                "win_rate": round(win, 3),
            })

        performance_by_status = {}
        for status, b in buckets.items():
            t = b["total"] or 1
            performance_by_status[status] = {
                "avg_pnl": round(b["pnl_sum"] / t, 2),
                "total_trades": b["total"],
                "win_rate": round(b["wins"] / t, 3),
            }

        # Simple correlation: healthy avg_pnl vs critical avg_pnl
        h_pnl = performance_by_status["healthy"]["avg_pnl"]
        c_pnl = performance_by_status["critical"]["avg_pnl"]
        span = max(abs(h_pnl), abs(c_pnl), 1)
        overall_correlation = round((c_pnl - h_pnl) / span, 3) if span else 0

        recent_trades.sort(key=lambda x: x["timestamp"], reverse=True)

        return {
            "overall_correlation": overall_correlation,
            "performance_by_status": performance_by_status,
            "recent_trades": recent_trades[:20],
        }

    except Exception as exc:
        logger.warning("debate_correlation fallback: %s", exc)
        return _empty_correlation()


@router.get("/historical-contribution", response_model=HistoricalResponse)
async def get_historical_contribution(
    agent_id: str = Query(..., description="Agent ID"),
    days_back: int = Query(default=7, description="Window in days"),
    points: Optional[int] = Query(default=None, description="Number of points to return")
):
    """
    Get historical contribution series for an agent.
    
    Args:
        agent_id: Agent identifier
        days_back: Window in days
        points: Number of points to return (default 6–20 evenly spaced)
        
    Returns:
        Historical contribution points (oldest→newest)
    """
    try:
        from merid.prediction.pnl_attribution import get_pnl_attribution_engine
        
        attribution_engine = get_pnl_attribution_engine()
        
        # Determine number of points
        if points is None:
            points = max(6, min(20, days_back))  # 6–20 points based on window

        # Attempt to get real historical data from the attribution engine.
        # Return empty points list if the engine has no recorded history yet —
        # this is honest: the UI should show "No data" rather than fake trends.
        historical_points = []
        try:
            history = attribution_engine.get_agent_history(agent_id=agent_id, days_back=days_back)
            if history:
                for entry in history[:points]:
                    historical_points.append(HistoricalPoint(
                        timestamp=entry.get("timestamp", ""),
                        debate_contribution_pct=float(entry.get("debate_contribution_pct", 0.0)),
                        win_rate=float(entry.get("win_rate", 0.0)),
                        utilization_pct=float(entry.get("utilization_pct", 0.0))))
        except AttributeError:
            # attribution_engine doesn't implement get_agent_history yet — return empty
            pass

        return HistoricalResponse(
            agent_id=agent_id,
            window_days=days_back,
            points=historical_points
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get historical contribution: {str(e)}")


@router.get("/rollups", response_model=RollupsResponse)
async def get_debate_rollups(
    group_by: str = Query(..., description="Group by: team|strategy|configuration"),
    days_back: int = Query(default=7, description="Window in days")
):
    """
    Get team/strategy rollups for attribution analysis.
    
    Args:
        group_by: Grouping dimension (team|strategy|configuration)
        days_back: Window in days
        
    Returns:
        Rollup rows with aggregated metrics
    """
    try:
        # Validate group_by
        valid_groups = {"team", "strategy", "configuration"}
        if group_by not in valid_groups:
            raise HTTPException(status_code=400, detail=f"Invalid group_by: {group_by}. Must be one of {valid_groups}")

        from merid.prediction.agent_risk_quotas import get_agent_risk_quota_manager
        from merid.prediction.pnl_attribution import get_pnl_attribution_engine
        
        quota_manager = get_agent_risk_quota_manager()
        attribution_engine = get_pnl_attribution_engine()
        
        # Get attribution summary
        attribution_summary = await attribution_engine.generate_attribution_summary(period_days=days_back)
        
        # Group agents by the requested dimension
        groups = {}
        
        if group_by == "team":
            # Group by team_id from quota profiles
            quota_summary = quota_manager.get_risk_quota_summary()
            for agent_id, profile in quota_summary.items():
                team_id = profile.get("team_id", f"unknown_team_{agent_id}")
                if team_id not in groups:
                    groups[team_id] = {"agents": [], "contributions": []}
                groups[team_id]["agents"].append(agent_id)
                if agent_id in attribution_summary.agent_contributions:
                    groups[team_id]["contributions"].append(
                        attribution_summary.agent_contributions[agent_id].get("debate_contribution_pct", 0.0)
                    )
        
        elif group_by == "strategy":
            # Group by strategy (placeholder - using tier as proxy)
            quota_summary = quota_manager.get_risk_quota_summary()
            for agent_id, profile in quota_summary.items():
                strategy = profile.get("tier", "restricted")
                if strategy not in groups:
                    groups[strategy] = {"agents": [], "contributions": []}
                groups[strategy]["agents"].append(agent_id)
                if agent_id in attribution_summary.agent_contributions:
                    groups[strategy]["contributions"].append(
                        attribution_summary.agent_contributions[agent_id].get("debate_contribution_pct", 0.0)
                    )
        
        else:
            # Default to configuration (group all agents)
            groups["all_agents"] = {
                "agents": list(attribution_summary.agent_contributions.keys()),
                "contributions": [
                    attribution_summary.agent_contributions[agent_id].get("debate_contribution_pct", 0.0)
                    for agent_id in attribution_summary.agent_contributions
                ]
            }
        
        # Build rollup rows
        rollup_rows = []
        for group_id, data in groups.items():
            if not data["contributions"]:
                continue
            
            avg_contribution = sum(data["contributions"]) / len(data["contributions"])
            
            # Placeholder metrics (would be calculated from actual data)
            sharpe_delta = avg_contribution * 10  # Simplified
            drawdown_delta = -abs(avg_contribution) * 5  # Simplified
            utilization_pct = min(0.95, 0.5 + avg_contribution * 2)  # Simplified
            
            rollup_rows.append(RollupRow(
                id=group_id,
                label=group_id.replace("_", " ").title(),
                debate_contribution_pct=avg_contribution,
                sharpe_delta=sharpe_delta,
                drawdown_delta=drawdown_delta,
                agents=data["agents"],
                utilization_pct=utilization_pct
            ))
        
        # Sort by contribution (highest first)
        rollup_rows.sort(key=lambda x: x.debate_contribution_pct, reverse=True)
        
        return RollupsResponse(
            group_by=group_by,
            window_days=days_back,
            rows=rollup_rows
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get debate rollups: {str(e)}")
