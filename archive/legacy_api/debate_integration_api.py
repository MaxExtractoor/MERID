"""
Debate Integration API
Endpoints for debate-aware position sizing and performance tracking.
"""

import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from web.api.auth import get_current_session
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from merid.prediction.backtest_scheduler import get_backtest_scheduler
from merid.prediction.debate_position_sizing import get_debate_position_sizer, get_debate_adjusted_position_size
from merid.prediction.portfolio_risk_manager import get_portfolio_risk_manager
from merid.prediction.debate_exit_policy import get_debate_exit_policy, evaluate_debate_exit_decision
from merid.prediction.agent_risk_quotas import get_agent_risk_quota_manager, check_agent_risk_quota
from merid.prediction.debate_deployment import get_debate_deployment_manager, DebateMode
from merid.prediction.pnl_attribution import get_pnl_attribution_engine, record_debate_trade, TradeType
from merid.prediction.pnl_attribution_db import get_pnl_attribution_db

router = APIRouter(prefix="/debates/integration", tags=["debate-integration"], dependencies=[Depends(get_current_session)])  # ZT6-01


class ExitPolicyRequest(BaseModel):
    """Request model for exit policy evaluation."""
    symbol: str
    entry_price: float
    current_price: float
    position_size: float
    entry_time: float
    base_kelly_fraction: float
    current_kelly_fraction: float


class ExitPolicyResponse(BaseModel):
    """Response model for exit policy evaluation."""
    symbol: str
    action: str
    reason: str
    confidence: float
    suggested_kelly_fraction: Optional[float]
    stop_loss_price: Optional[float]
    debate_performance: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]


class TradeRecordRequest(BaseModel):
    """Request model for recording a trade."""
    symbol: str
    trade_type: str
    timestamp: float
    price: float
    quantity: int
    trade_id: str
    agent_id: Optional[str] = None
    base_kelly_fraction: float = 0.0
    debate_multiplier: float = 1.0
    final_kelly_fraction: float = 0.0
    debate_recommendation: Optional[str] = None
    exit_reason: Optional[str] = None


class PositionSizingRequest(BaseModel):
    """Request model for position sizing."""
    symbol: str
    base_kelly_fraction: float
    position_size_dollars: Optional[float] = None
    total_equity: Optional[float] = None
    portfolio_var: Optional[float] = None
    agent_id: Optional[str] = None


class PositionSizingResponse(BaseModel):
    """Response model for position sizing."""
    symbol: str
    base_kelly_fraction: float
    debate_multiplier: float
    adjusted_kelly_fraction: float
    recommendation: str
    performance_profile: Optional[Dict[str, Any]] = None
    portfolio_violations: List[Dict[str, Any]] = []
    portfolio_risk_check: bool = False
    agent_quota_violations: List[str] = []
    agent_quota_check: bool = False


@router.post("/position-size", response_model=PositionSizingResponse)
async def get_debate_adjusted_position(request: PositionSizingRequest):
    """
    Get debate-adjusted position size for a Kalshi symbol.
    
    Args:
        request: Position sizing request
        
    Returns:
        Adjusted position size with debate performance context
    """
    try:
        sizer = get_debate_position_sizer()
        
        # Get debate-adjusted position with all risk checks
        multiplier = await sizer.get_position_multiplier(
            request.symbol, 
            request.base_kelly_fraction,
            request.position_size_dollars,
            request.total_equity,
            request.portfolio_var,
            request.agent_id
        )
        adjusted_kelly = request.base_kelly_fraction * multiplier
        
        # Get performance profile if available
        profile = await sizer.get_profile_for_symbol(request.symbol)
        performance_data = None
        if profile:
            performance_data = {
                "avg_improvement_pct": profile.avg_improvement_pct,
                "debate_count": profile.debate_count,
                "success_rate": profile.success_rate,
                "avg_debate_lift": profile.avg_debate_lift,
                "recommendation": profile.recommendation,
                "confidence_level": profile.confidence_level
            }
        
        # Get portfolio risk information if portfolio data provided
        portfolio_violations = []
        portfolio_risk_check = False
        
        if all([request.position_size_dollars, request.total_equity, request.portfolio_var]):
            try:
                risk_manager = get_portfolio_risk_manager()
                portfolio_summary = risk_manager.get_risk_summary()
                portfolio_risk_check = True
                
                # Extract current violations from summary
                if "risk_limits" in portfolio_summary:
                    for limit_name, limit_data in portfolio_summary["risk_limits"].items():
                        if limit_data.get("last_breached") and limit_data.get("breach_count", 0) > 0:
                            portfolio_violations.append({
                                "limit": limit_name,
                                "breach_count": limit_data["breach_count"],
                                "last_breached": limit_data["last_breached"]
                            })
                            
            except Exception as e:
                logger.warning(f"Failed to get portfolio risk info: {e}")
        
        # Get agent quota information if agent provided
        agent_quota_violations = []
        agent_quota_check = False
        
        if request.agent_id and all([request.position_size_dollars, request.total_equity]):
            try:
                quota_manager = get_agent_risk_quota_manager()
                quota_check = await check_agent_risk_quota(
                    request.symbol, request.agent_id, request.position_size_dollars, request.total_equity
                )
                agent_quota_check = True
                
                if not quota_check.passed:
                    agent_quota_violations = [quota_check.violation_type or "quota_exceeded"]
                    
            except Exception as e:
                logger.warning(f"Failed to get agent quota info: {e}")
        
        return PositionSizingResponse(
            symbol=request.symbol,
            base_kelly_fraction=request.base_kelly_fraction,
            debate_multiplier=multiplier,
            adjusted_kelly_fraction=adjusted_kelly,
            recommendation=performance_data["recommendation"] if performance_data else "normal",
            performance_profile=performance_data,
            portfolio_violations=portfolio_violations,
            portfolio_risk_check=portfolio_risk_check,
            agent_quota_violations=agent_quota_violations,
            agent_quota_check=agent_quota_check
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate debate-adjusted position: {str(e)}")


@router.get("/performance-summary", response_model=Dict[str, Any])
async def get_debate_performance_summary():
    """
    Get summary of debate performance across all symbols.
    
    Returns:
        Performance summary with recommendations and top/worst performers
    """
    try:
        sizer = get_debate_position_sizer()
        summary = await sizer.get_performance_summary()
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get performance summary: {str(e)}")


@router.get("/trends", response_model=Dict[str, Any])
async def get_debate_performance_trends(days: int = 30):
    """
    Get debate performance trends over time.
    
    Args:
        days: Number of days to analyze
        
    Returns:
        Performance trends with daily data
    """
    try:
        scheduler = get_backtest_scheduler()
        trends = scheduler.get_performance_trends(days)
        
        if not trends:
            return {"message": "No trend data available"}
        
        return {
            "period_days": days,
            "trend_count": len(trends),
            "latest": {
                "date": trends[-1].date.isoformat(),
                "avg_improvement_pct": trends[-1].avg_improvement_pct,
                "markets_with_improvement": trends[-1].markets_with_improvement,
                "markets_with_negative_impact": trends[-1].markets_with_negative_impact,
                "total_markets": trends[-1].total_markets,
                "confidence_level": trends[-1].confidence_level
            },
            "trend_data": [
                {
                    "date": t.date.isoformat(),
                    "avg_improvement_pct": t.avg_improvement_pct,
                    "markets_with_improvement": t.markets_with_improvement,
                    "markets_with_negative_impact": t.markets_with_negative_impact,
                    "total_markets": t.total_markets,
                    "confidence_level": t.confidence_level
                }
                for t in trends
            ],
            "statistics": {
                "avg_improvement": sum(t.avg_improvement_pct for t in trends) / len(trends),
                "avg_markets_with_improvement": sum(t.markets_with_improvement for t in trends) / len(trends),
                "avg_negative_impact_rate": (
                    sum(t.markets_with_negative_impact / t.total_markets for t in trends if t.total_markets > 0) /
                    len([t for t in trends if t.total_markets > 0])
                ) if any(t.total_markets > 0 for t in trends) else 0.0,
                "avg_confidence": sum(t.confidence_level for t in trends) / len(trends)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get performance trends: {str(e)}")


@router.post("/clear-cache", response_model=Dict[str, str])
async def clear_performance_cache():
    """
    Clear the debate performance cache.
    
    Returns:
        Confirmation message
    """
    try:
        sizer = get_debate_position_sizer()
        sizer.clear_cache()
        return {"message": "Debate performance cache cleared successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@router.get("/symbol-profile/{symbol}", response_model=Dict[str, Any])
async def get_symbol_performance_profile(symbol: str):
    """
    Get detailed performance profile for a specific symbol.
    
    Args:
        symbol: Kalshi symbol
        
    Returns:
        Detailed performance profile
    """
    try:
        sizer = get_debate_position_sizer()
        profile = await sizer.get_profile_for_symbol(symbol)
        
        if not profile:
            raise HTTPException(status_code=404, detail=f"No performance data found for {symbol}")
        
        return {
            "symbol": profile.symbol,
            "avg_improvement_pct": profile.avg_improvement_pct,
            "debate_count": profile.debate_count,
            "success_rate": profile.success_rate,
            "avg_debate_lift": profile.avg_debate_lift,
            "last_updated": datetime.fromtimestamp(profile.last_updated, timezone.utc).isoformat(),
            "confidence_level": profile.confidence_level,
            "recommendation": profile.recommendation,
            "position_multipliers": {
                "boost_2x": profile.avg_improvement_pct > 10.0,
                "boost_1_5x": 5.0 < profile.avg_improvement_pct <= 10.0,
                "boost_1_25x": 2.0 < profile.avg_improvement_pct <= 5.0,
                "normal": 0.0 <= profile.avg_improvement_pct <= 2.0,
                "reduce_0_75x": -2.0 <= profile.avg_improvement_pct < 0.0,
                "avoid_0_5x": profile.avg_improvement_pct < -2.0
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get symbol profile: {str(e)}")


@router.post("/exit-policy/evaluate", response_model=ExitPolicyResponse)
async def evaluate_exit_policy(request: ExitPolicyRequest):
    """
    Evaluate exit policy for a position based on debate performance.
    
    Args:
        request: Exit policy evaluation request
        
    Returns:
        Exit recommendation with action and reasoning
    """
    try:
        recommendation = await evaluate_debate_exit_decision(
            symbol=request.symbol,
            entry_price=request.entry_price,
            current_price=request.current_price,
            position_size=request.position_size,
            entry_time=request.entry_time,
            base_kelly_fraction=request.base_kelly_fraction,
            current_kelly_fraction=request.current_kelly_fraction
        )
        
        return ExitPolicyResponse(
            symbol=request.symbol,
            action=recommendation.action.value,
            reason=recommendation.reason,
            confidence=recommendation.confidence,
            suggested_kelly_fraction=recommendation.suggested_kelly_fraction,
            stop_loss_price=recommendation.stop_loss_price,
            debate_performance=recommendation.debate_performance,
            metadata=recommendation.metadata
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate exit policy: {str(e)}")


@router.post("/exit-policy/record", response_model=Dict[str, str])
async def record_exit_decision(
    symbol: str,
    action: str,
    reason: str,
    execution_price: Optional[float] = None,
    execution_size: Optional[float] = None
):
    """
    Record an exit decision for analytics.
    
    Args:
        symbol: Kalshi symbol
        action: Exit action (hold/trim/exit)
        reason: Reason for the decision
        execution_price: Execution price (if executed)
        execution_size: Execution size (if executed)
        
    Returns:
        Confirmation message
    """
    try:
        from merid.prediction.debate_exit_policy import ExitAction
        
        exit_policy = get_debate_exit_policy()
        
        # Convert string to enum
        action_enum = ExitAction(action.lower())
        
        exit_policy.record_exit_decision(
            symbol=symbol,
            action=action_enum,
            reason=reason,
            execution_price=execution_price,
            execution_size=execution_size
        )
        
        return {"message": f"Recorded exit decision for {symbol}: {action}"}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid action: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record exit decision: {str(e)}")


@router.get("/exit-policy/analytics", response_model=Dict[str, Any])
async def get_exit_analytics(days_back: int = 30):
    """
    Get analytics on exit decisions over time.
    
    Args:
        days_back: Number of days to analyze
        
    Returns:
        Exit decision analytics
    """
    try:
        exit_policy = get_debate_exit_policy()
        analytics = exit_policy.get_exit_analytics(days_back)
        return analytics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get exit analytics: {str(e)}")


@router.post("/exit-policy/update-parameters", response_model=Dict[str, str])
async def update_exit_policy_parameters(
    debate_performance_threshold: Optional[float] = None,
    confidence_threshold: Optional[float] = None,
    trim_factor: Optional[float] = None,
    max_position_age_hours: Optional[float] = None,
    pnl_loss_threshold: Optional[float] = None
):
    """
    Update exit policy parameters.
    
    Args:
        debate_performance_threshold: Debate performance threshold for exit
        confidence_threshold: Confidence threshold for decisions
        trim_factor: Position reduction factor
        max_position_age_hours: Maximum position age before review
        pnl_loss_threshold: P&L loss threshold for forced exit
        
    Returns:
        Confirmation message
    """
    try:
        exit_policy = get_debate_exit_policy()
        exit_policy.update_policy_parameters(
            debate_performance_threshold=debate_performance_threshold,
            confidence_threshold=confidence_threshold,
            trim_factor=trim_factor,
            max_position_age_hours=max_position_age_hours,
            pnl_loss_threshold=pnl_loss_threshold
        )
        
        return {"message": "Exit policy parameters updated"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update parameters: {str(e)}")


@router.post("/exit-policy/clear-states", response_model=Dict[str, str])
async def clear_position_states():
    """
    Clear all position states (useful for end-of-day reset).
    
    Returns:
        Confirmation message
    """
    try:
        exit_policy = get_debate_exit_policy()
        exit_policy.clear_position_states()
        return {"message": "Position states cleared"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear states: {str(e)}")


@router.post("/pnl-attribution/record-trade", response_model=Dict[str, str])
async def record_trade(request: TradeRecordRequest):
    """
    Record a trade for PnL attribution analysis.
    
    Args:
        request: Trade record data
        
    Returns:
        Confirmation message
    """
    try:
        # Convert string to enum
        try:
            trade_type_enum = TradeType(request.trade_type.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid trade type: {request.trade_type}")
        
        await record_debate_trade(
            symbol=request.symbol,
            trade_type=request.trade_type,
            timestamp=request.timestamp,
            price=request.price,
            quantity=request.quantity,
            trade_id=request.trade_id,
            agent_id=request.agent_id,
            base_kelly_fraction=request.base_kelly_fraction,
            debate_multiplier=request.debate_multiplier,
            final_kelly_fraction=request.final_kelly_fraction,
            debate_recommendation=request.debate_recommendation,
            exit_reason=request.exit_reason
        )
        
        return {"message": f"Recorded trade {request.trade_id} for attribution"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record trade: {str(e)}")


@router.get("/pnl-attribution/dashboard", response_model=Dict[str, Any])
async def get_pnl_attribution_dashboard(days_back: int = 30):
    """
    Get PnL attribution dashboard data.
    
    Args:
        days_back: Number of days to analyze
        
    Returns:
        Dashboard data with attribution metrics
    """
    try:
        attribution_engine = get_pnl_attribution_engine()
        dashboard = attribution_engine.get_attribution_dashboard(days_back)
        return dashboard
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attribution dashboard: {str(e)}")


@router.get("/pnl-attribution/summary", response_model=Dict[str, Any])
async def get_pnl_attribution_summary(days_back: int = 30, agent_id: Optional[str] = None, symbol: Optional[str] = None):
    """
    Get PnL attribution summary.
    
    Args:
        days_back: Number of days to analyze
        agent_id: Filter by agent (optional)
        symbol: Filter by symbol (optional)
        
    Returns:
        Attribution summary with detailed metrics
    """
    try:
        attribution_engine = get_pnl_attribution_engine()
        summary = await attribution_engine.generate_attribution_summary(days_back, agent_id, symbol)
        
        return {
            "period_start": summary.period_start.isoformat(),
            "period_end": summary.period_end.isoformat(),
            "total_trades": summary.total_trades,
            "total_realized_pnl": summary.total_realized_pnl,
            "total_base_pnl": summary.total_base_pnl,
            "total_debate_pnl_impact": summary.total_debate_pnl_impact,
            "total_exit_pnl_impact": summary.total_exit_pnl_impact,
            "debate_sizing_win_rate": summary.debate_sizing_win_rate,
            "debate_exit_win_rate": summary.debate_exit_win_rate,
            "overall_debate_contribution_pct": summary.overall_debate_contribution_pct,
            "agent_contributions": summary.agent_contributions,
            "tier_contributions": summary.tier_contributions,
            "symbol_contributions": summary.symbol_contributions
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attribution summary: {str(e)}")


@router.post("/pnl-attribution/clear-records", response_model=Dict[str, str])
async def clear_trade_records(days_back: Optional[int] = None):
    """
    Clear trade records.
    
    Args:
        days_back: Clear records older than this many days (optional, clears all if not provided)
        
    Returns:
        Confirmation message
    """
    try:
        attribution_engine = get_pnl_attribution_engine()
        attribution_engine.clear_trade_records(days_back)
        
        if days_back is None:
            return {"message": "Cleared all trade records"}
        else:
            return {"message": f"Cleared trade records older than {days_back} days"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear trade records: {str(e)}")


@router.get("/pnl-attribution/database-stats", response_model=Dict[str, Any])
async def get_database_stats():
    """
    Get database statistics.
    
    Returns:
        Database statistics including record counts and size
    """
    try:
        db = get_pnl_attribution_db()
        stats = db.get_database_stats()
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get database stats: {str(e)}")


@router.post("/pnl-attribution/cleanup-old-records", response_model=Dict[str, str])
async def cleanup_old_records(days_to_keep: int = 365):
    """
    Clean up old records to manage database size.
    
    Args:
        days_to_keep: Number of days to keep records for
        
    Returns:
        Confirmation message with cleanup results
    """
    try:
        db = get_pnl_attribution_db()
        await db.cleanup_old_records(days_to_keep)
        return {"message": f"Cleaned up records older than {days_to_keep} days"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup old records: {str(e)}")


@router.get("/pnl-attribution/historical-trades", response_model=List[Dict[str, Any]])
async def get_historical_trades(
    symbol: Optional[str] = None,
    agent_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: Optional[int] = 100
):
    """
    Get historical trade records from database.
    
    Args:
        symbol: Filter by symbol (optional)
        agent_id: Filter by agent (optional)
        start_time: Filter by start timestamp (optional)
        end_time: Filter by end timestamp (optional)
        limit: Maximum number of records to return
        
    Returns:
        List of historical trade records
    """
    try:
        db = get_pnl_attribution_db()
        trades = await db.get_trade_records(symbol, agent_id, start_time, end_time, limit)
        
        return [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "timestamp": trade.timestamp,
                "price": trade.price,
                "quantity": trade.quantity,
                "trade_id": trade.trade_id,
                "agent_id": trade.agent_id,
                "base_kelly_fraction": trade.base_kelly_fraction,
                "debate_multiplier": trade.debate_multiplier,
                "final_kelly_fraction": trade.final_kelly_fraction,
                "debate_recommendation": trade.debate_recommendation,
                "exit_reason": trade.exit_reason,
                "realized_pnl": trade.realized_pnl,
                "debate_pnl_impact": trade.debate_pnl_impact,
                "created_at": trade.created_at.isoformat()
            }
            for trade in trades
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get historical trades: {str(e)}")


@router.get("/pnl-attribution/historical-attributions", response_model=List[Dict[str, Any]])
async def get_historical_attributions(
    symbol: Optional[str] = None,
    agent_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    config_version: Optional[str] = None,
    limit: Optional[int] = 100
):
    """
    Get historical attribution records from database.
    
    Args:
        symbol: Filter by symbol (optional)
        agent_id: Filter by agent (optional)
        start_date: Filter by start date (YYYY-MM-DD format, optional)
        end_date: Filter by end date (YYYY-MM-DD format, optional)
        config_version: Filter by configuration version (optional)
        limit: Maximum number of records to return
        
    Returns:
        List of historical attribution records
    """
    try:
        db = get_pnl_attribution_db()
        
        # Parse dates
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        
        attributions = await db.get_attribution_records(symbol, agent_id, start_dt, end_dt, config_version, limit)
        
        return [
            {
                "id": attribution.id,
                "symbol": attribution.symbol,
                "entry_trade_id": attribution.entry_trade_id,
                "exit_trade_id": attribution.exit_trade_id,
                "entry_timestamp": attribution.entry_timestamp,
                "exit_timestamp": attribution.exit_timestamp,
                "holding_period_hours": attribution.holding_period_hours,
                "realized_pnl": attribution.realized_pnl,
                "base_pnl": attribution.base_pnl,
                "debate_sizing_impact": attribution.debate_sizing_impact,
                "debate_exit_impact": attribution.debate_exit_impact,
                "total_debate_contribution": attribution.total_debate_contribution,
                "debate_contribution_pct": attribution.debate_contribution_pct,
                "agent_id": attribution.agent_id,
                "entry_debate_multiplier": attribution.entry_debate_multiplier,
                "exit_debate_driven": attribution.exit_debate_driven,
                "config_version": attribution.config_version,
                "created_at": attribution.created_at.isoformat()
            }
            for attribution in attributions
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get historical attributions: {str(e)}")


@router.get("/deployment/status", response_model=Dict[str, Any])
async def get_deployment_status():
    """
    Get current debate deployment status and configuration.
    
    Returns:
        Deployment status with mode, canary symbols, and kill switch state
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        status = deployment_manager.get_deployment_status()
        return status
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get deployment status: {str(e)}")


@router.post("/deployment/set-mode", response_model=Dict[str, str])
async def set_deployment_mode(
    mode: str,
    updated_by: str,
    reason: str = None,
    canary_symbols: Optional[List[str]] = None
):
    """
    Set the debate deployment mode.
    
    Args:
        mode: Deployment mode (off/canary/full)
        updated_by: Who made the change
        reason: Reason for the change
        canary_symbols: Canary symbols (required for canary mode)
        
    Returns:
        Confirmation message
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        
        # Convert string to enum
        try:
            mode_enum = DebateMode(mode.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
        
        deployment_manager.set_deployment_mode(
            mode=mode_enum,
            updated_by=updated_by,
            reason=reason,
            canary_symbols=canary_symbols
        )
        
        return {"message": f"Deployment mode set to {mode}"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set deployment mode: {str(e)}")


@router.post("/deployment/toggle-kill-switch", response_model=Dict[str, str])
async def toggle_kill_switch(
    activated: bool,
    updated_by: str,
    reason: str = None
):
    """
    Toggle the global debate kill switch.
    
    Args:
        activated: Whether to activate the kill switch
        updated_by: Who made the change
        reason: Reason for the change
        
    Returns:
        Confirmation message
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        deployment_manager.toggle_kill_switch(activated, updated_by, reason)
        
        action = "ACTIVATED" if activated else "DEACTIVATED"
        return {"message": f"Kill switch {action}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle kill switch: {str(e)}")


@router.post("/deployment/update-canary-symbols", response_model=Dict[str, str])
async def update_canary_symbols(
    symbols: List[str],
    updated_by: str,
    reason: str = None
):
    """
    Update the canary symbol set.
    
    Args:
        symbols: New canary symbols list
        updated_by: Who made the change
        reason: Reason for the change
        
    Returns:
        Confirmation message
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        deployment_manager.update_canary_symbols(symbols, updated_by, reason)
        
        return {"message": f"Updated {len(symbols)} canary symbols"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update canary symbols: {str(e)}")


@router.get("/deployment/shadow-recommendations", response_model=Dict[str, Any])
async def get_shadow_recommendations(hours_back: int = 24):
    """
    Get shadow recommendations for analysis.
    
    Args:
        hours_back: Number of hours to look back
        
    Returns:
        Shadow recommendations analysis
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        recommendations = deployment_manager.get_shadow_recommendations(hours_back)
        return recommendations
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get shadow recommendations: {str(e)}")


@router.post("/deployment/clear-shadow-recommendations", response_model=Dict[str, str])
async def clear_shadow_recommendations():
    """
    Clear all shadow recommendations.
    
    Returns:
        Confirmation message
    """
    try:
        deployment_manager = get_debate_deployment_manager()
        deployment_manager.clear_shadow_recommendations()
        return {"message": "Cleared all shadow recommendations"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear shadow recommendations: {str(e)}")


@router.get("/agent-quotas/summary", response_model=Dict[str, Any])
async def get_agent_quota_summary():
    """
    Get summary of agent and team risk quotas and utilization.
    
    Returns:
        Agent and team quota summary with current utilization
    """
    try:
        quota_manager = get_agent_risk_quota_manager()
        summary = quota_manager.get_risk_quota_summary()
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agent quota summary: {str(e)}")


@router.post("/agent-quotas/update-tier", response_model=Dict[str, str])
async def update_agent_tier(agent_id: str, new_tier: str):
    """
    Update an agent's risk tier.
    
    Args:
        agent_id: Agent identifier
        new_tier: New risk tier (gold/silver/bronze/restricted)
        
    Returns:
        Confirmation message
    """
    try:
        from merid.prediction.agent_risk_quotas import RiskTier
        
        quota_manager = get_agent_risk_quota_manager()
        
        # Convert string to enum
        try:
            tier_enum = RiskTier(new_tier.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {new_tier}")
        
        quota_manager.update_agent_tier(agent_id, tier_enum)
        return {"message": f"Updated agent {agent_id} tier to {new_tier}"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update agent tier: {str(e)}")


@router.post("/agent-quotas/allocate-risk", response_model=Dict[str, str])
async def allocate_agent_risk(symbol: str, agent_id: str, risk_amount: float):
    """
    Allocate position risk to an agent.
    
    Args:
        symbol: Kalshi symbol
        agent_id: Agent identifier
        risk_amount: Risk amount in dollars
        
    Returns:
        Confirmation message
    """
    try:
        quota_manager = get_agent_risk_quota_manager()
        await quota_manager.allocate_position_risk(symbol, agent_id, risk_amount)
        return {"message": f"Allocated ${risk_amount:.2f} risk for {agent_id} on {symbol}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to allocate risk: {str(e)}")


@router.post("/agent-quotos/deallocate-risk", response_model=Dict[str, str])
async def deallocate_agent_risk(symbol: str, agent_id: str):
    """
    Deallocate position risk from an agent.
    
    Args:
        symbol: Kalshi symbol
        agent_id: Agent identifier
        
    Returns:
        Confirmation message
    """
    try:
        quota_manager = get_agent_risk_quota_manager()
        quota_manager.deallocate_position_risk(symbol, agent_id)
        return {"message": f"Deallocated risk for {agent_id} on {symbol}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to deallocate risk: {str(e)}")


@router.post("/agent-quotas/clear-allocations", response_model=Dict[str, str])
async def clear_agent_allocations():
    """
    Clear all agent risk allocations (useful for end-of-day reset).
    
    Returns:
        Confirmation message
    """
    try:
        quota_manager = get_agent_risk_quota_manager()
        quota_manager.clear_position_allocations()
        return {"message": "Cleared all agent risk allocations"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear allocations: {str(e)}")


@router.get("/portfolio/risk-summary", response_model=Dict[str, Any])
async def get_portfolio_risk_summary():
    """
    Get portfolio risk summary and limits status.
    
    Returns:
        Portfolio risk summary with limits and violations
    """
    try:
        risk_manager = get_portfolio_risk_manager()
        summary = risk_manager.get_risk_summary()
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get portfolio risk summary: {str(e)}")


@router.post("/portfolio/update-limit", response_model=Dict[str, str])
async def update_portfolio_risk_limit(limit_name: str, threshold: float, action: str = None):
    """
    Update a portfolio risk limit.
    
    Args:
        limit_name: Name of the risk limit to update
        threshold: New threshold value
        action: New action (optional)
        
    Returns:
        Confirmation message
    """
    try:
        risk_manager = get_portfolio_risk_manager()
        risk_manager.update_risk_limit(limit_name, threshold, action)
        return {"message": f"Updated risk limit {limit_name}: threshold={threshold}"}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update risk limit: {str(e)}")


@router.post("/portfolio/clear-allocations", response_model=Dict[str, str])
async def clear_portfolio_allocations():
    """
    Clear all portfolio position allocations.
    
    Returns:
        Confirmation message
    """
    try:
        risk_manager = get_portfolio_risk_manager()
        risk_manager.clear_position_allocations()
        return {"message": "Portfolio position allocations cleared"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear allocations: {str(e)}")


@router.get("/health", response_model=Dict[str, Any])
async def get_integration_health():
    """
    Get health status of debate integration components.
    
    Returns:
        Health status of scheduler and position sizer
    """
    try:
        scheduler = get_backtest_scheduler()
        sizer = get_debate_position_sizer()
        risk_manager = get_portfolio_risk_manager()
        exit_policy = get_debate_exit_policy()
        quota_manager = get_agent_risk_quota_manager()
        deployment_manager = get_debate_deployment_manager()
        attribution_engine = get_pnl_attribution_engine()
        attribution_db = get_pnl_attribution_db()
        
        latest_summary = scheduler.get_latest_summary()
        performance_summary = await sizer.get_performance_summary()
        portfolio_summary = risk_manager.get_risk_summary()
        exit_analytics = exit_policy.get_exit_analytics(days_back=7)
        quota_summary = quota_manager.get_risk_quota_summary()
        deployment_status = deployment_manager.get_deployment_status()
        
        # Get attribution summary
        attribution_summary = await attribution_engine.generate_attribution_summary(days_back=7)
        
        # Get database stats
        db_stats = attribution_db.get_database_stats()
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scheduler": {
                "running": scheduler.is_running,
                "latest_backtest": latest_summary.date.isoformat() if latest_summary else None,
                "trend_history_size": len(scheduler.trend_history)
            },
            "position_sizer": {
                "cache_size": len(sizer.performance_cache),
                "cache_age_seconds": time.time() - sizer.last_cache_update,
                "total_symbols_tracked": performance_summary.get("total_symbols", 0)
            },
            "portfolio_risk": {
                "active_positions": portfolio_summary.get("active_positions", 0),
                "total_risk": portfolio_summary.get("total_risk", 0),
                "debate_boost_share": portfolio_summary.get("debate_boost_share", 0),
                "risk_violations": sum(1 for limit_data in portfolio_summary.get("risk_limits", {}).values() 
                                    if limit_data.get("breach_count", 0) > 0)
            },
            "exit_policy": {
                "active_positions": len(exit_policy.position_states),
                "recent_decisions": exit_analytics.get("total_decisions", 0),
                "exit_rate_7d": exit_analytics.get("exit_rate", 0),
                "trim_rate_7d": exit_analytics.get("trim_rate", 0)
            },
            "agent_quotas": {
                "total_agents": len(quota_summary.get("agent_profiles", {})),
                "total_teams": len(quota_summary.get("team_profiles", {})),
                "tier_distribution": quota_summary.get("tier_distribution", {}),
                "agent_utilization": quota_summary.get("quota_utilization", {}).get("agents", {}).get("utilization", 0),
                "team_utilization": quota_summary.get("quota_utilization", {}).get("teams", {}).get("utilization", 0)
            },
            "deployment": {
                "mode": deployment_status["mode"],
                "kill_switch_active": deployment_status["kill_switch_active"],
                "canary_symbols_count": deployment_status["canary_symbols_count"],
                "is_debate_enabled_globally": deployment_status["is_debate_enabled_globally"],
                "shadow_recommendations_count": deployment_status["shadow_recommendations_count"]
            },
            "pnl_attribution": {
                "tracked_trades": attribution_summary.total_trades,
                "debate_contribution_pct": attribution_summary.overall_debate_contribution_pct,
                "debate_sizing_win_rate": attribution_summary.debate_sizing_win_rate,
                "debate_exit_win_rate": attribution_summary.debate_exit_win_rate,
                "total_debate_contribution": attribution_summary.total_debate_pnl_impact + attribution_summary.total_exit_pnl_impact,
                "database_stats": db_stats
            },
            "overall_health": {
                "healthy": (scheduler.is_running and 
                          len(sizer.performance_cache) > 0 and
                          portfolio_summary.get("total_risk", 0) >= 0 and
                          len(exit_policy.position_states) >= 0 and
                          quota_summary.get("quota_utilization", {}).get("agents", {}).get("utilization", 1.0) <= 1.0 and
                          not deployment_status["kill_switch_active"] and
                          db_stats.get("database_size_mb", 0) < 1000),  # Alert if DB > 1GB
                "issues": []
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get integration health: {str(e)}")
