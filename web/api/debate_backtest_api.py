"""
Debate Backtest API
Endpoints for running and accessing debate performance backtests.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from merid.prediction.debate_backtest import (
    get_debate_backtester, 
    run_debate_backtest,
    BacktestSummary,
    BacktestResult
)

router = APIRouter(prefix="/debates/backtest", tags=["debate-backtest"])


class BacktestRequest(BaseModel):
    """Request model for running a backtest."""
    days_back: int = 30
    min_debates_per_symbol: int = 1
    include_report: bool = True


class BacktestResponse(BaseModel):
    """Response model for backtest results."""
    timestamp: str
    summary: Dict[str, Any]
    top_performers: List[Dict[str, Any]]
    worst_performers: List[Dict[str, Any]]
    report: Optional[str] = None


# Store for background task results
_background_results: Dict[str, Dict[str, Any]] = {}


@router.post("/run", response_model=Dict[str, Any])
async def run_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks
):
    """
    Run a debate performance backtest.
    
    Args:
        request: Backtest configuration
        background_tasks: FastAPI background tasks
        
    Returns:
        Task ID for tracking backtest progress
    """
    try:
        # Generate unique task ID
        task_id = f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize task status
        _background_results[task_id] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "progress": 0.0,
            "result": None,
            "error": None
        }
        
        # Start background task
        background_tasks.add_task(
            _run_backtest_background,
            task_id,
            request.days_back,
            request.min_debates_per_symbol,
            request.include_report
        )
        
        return {
            "task_id": task_id,
            "status": "started",
            "message": f"Backtest started for last {request.days_back} days"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start backtest: {str(e)}")


@router.get("/status/{task_id}", response_model=Dict[str, Any])
async def get_backtest_status(task_id: str):
    """
    Get the status of a running backtest.
    
    Args:
        task_id: Unique identifier for the backtest task
        
    Returns:
        Current status and progress of the backtest
    """
    if task_id not in _background_results:
        raise HTTPException(status_code=404, detail=f"Backtest task {task_id} not found")
    
    return _background_results[task_id]


@router.get("/results/{task_id}", response_model=BacktestResponse)
async def get_backtest_results(task_id: str):
    """
    Get the results of a completed backtest.
    
    Args:
        task_id: Unique identifier for the backtest task
        
    Returns:
        Detailed backtest results and analysis
    """
    if task_id not in _background_results:
        raise HTTPException(status_code=404, detail=f"Backtest task {task_id} not found")
    
    task_result = _background_results[task_id]
    
    if task_result["status"] != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Backtest task {task_id} not completed. Current status: {task_result['status']}"
        )
    
    if task_result["error"]:
        raise HTTPException(
            status_code=500,
            detail=f"Backtest failed: {task_result['error']}"
        )
    
    result = task_result["result"]
    
    return BacktestResponse(
        timestamp=task_result["started_at"],
        summary=result["summary"],
        top_performers=result["top_performers"],
        worst_performers=result["worst_performers"],
        report=result.get("report")
    )


@router.get("/quick", response_model=Dict[str, Any])
async def run_quick_backtest(days_back: int = 7):
    """
    Run a quick backtest synchronously for recent data.
    
    Args:
        days_back: Number of days to look back (default: 7)
        
    Returns:
        Quick backtest summary
    """
    try:
        summary = await run_debate_backtest(days_back)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "period_days": days_back,
            "summary": {
                "total_markets": summary.total_markets,
                "avg_improvement_pct": round(summary.avg_improvement_pct, 2),
                "markets_with_improvement": summary.markets_with_improvement,
                "markets_with_negative_impact": summary.markets_with_negative_impact,
                "markets_with_debates": summary.markets_with_debates,
                "avg_debate_lift": round(summary.avg_debate_lift, 4),
                "confidence_level": round(summary.confidence_level, 2)
            },
            "recommendation": _generate_recommendation(summary)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run quick backtest: {str(e)}")


@router.get("/tasks", response_model=List[Dict[str, Any]])
async def list_backtest_tasks():
    """
    List all backtest tasks and their statuses.
    
    Returns:
        List of all backtest tasks with their current status
    """
    tasks = []
    for task_id, result in _background_results.items():
        tasks.append({
            "task_id": task_id,
            "status": result["status"],
            "started_at": result["started_at"],
            "progress": result.get("progress", 0.0),
            "has_result": result["result"] is not None,
            "has_error": result["error"] is not None
        })
    
    # Sort by started_at descending
    tasks.sort(key=lambda x: x["started_at"], reverse=True)
    return tasks


async def _run_backtest_background(
    task_id: str,
    days_back: int,
    min_debates_per_symbol: int,
    include_report: bool
):
    """Background task to run the backtest."""
    try:
        # Update progress
        _background_results[task_id]["progress"] = 0.1
        
        # Run backtest with detailed results
        backtester = get_debate_backtester()
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)
        
        _background_results[task_id]["progress"] = 0.3
        
        summary, results = await backtester.run_backtest(start_date, end_date, min_debates_per_symbol)
        
        _background_results[task_id]["progress"] = 0.7
        
        # Generate top and worst performers
        top_results = sorted(results, key=lambda r: r.improvement_pct, reverse=True)[:5]
        worst_results = sorted(results, key=lambda r: r.improvement_pct)[:5]
        
        # Generate report if requested
        report = None
        if include_report:
            report = backtester.generate_report(summary, results)
        
        # Store results
        _background_results[task_id]["result"] = {
            "summary": {
                "total_markets": summary.total_markets,
                "avg_improvement_pct": summary.avg_improvement_pct,
                "markets_with_improvement": summary.markets_with_improvement,
                "markets_with_negative_impact": summary.markets_with_negative_impact,
                "markets_with_debates": summary.markets_with_debates,
                "avg_debate_lift": summary.avg_debate_lift,
                "confidence_level": summary.confidence_level
            },
            "top_performers": [
                {
                    "symbol": r.symbol,
                    "with_debates_brier": r.with_debates_brier,
                    "without_debates_brier": r.without_debates_brier,
                    "debate_lift": r.debate_lift,
                    "debate_count": r.debate_count,
                    "improvement_pct": r.improvement_pct,
                    "statistically_significant": r.statistically_significant,
                }
                for r in top_results
            ],
            "worst_performers": [
                {
                    "symbol": r.symbol,
                    "with_debates_brier": r.with_debates_brier,
                    "without_debates_brier": r.without_debates_brier,
                    "debate_lift": r.debate_lift,
                    "debate_count": r.debate_count,
                    "improvement_pct": r.improvement_pct,
                    "statistically_significant": r.statistically_significant,
                }
                for r in worst_results
            ],
            "report": report
        }
        
        _background_results[task_id]["progress"] = 1.0
        _background_results[task_id]["status"] = "completed"
        
    except Exception as e:
        _background_results[task_id]["status"] = "failed"
        _background_results[task_id]["error"] = str(e)


def _generate_recommendation(summary: BacktestSummary) -> str:
    """Generate recommendation based on backtest results."""
    negative_impact_rate = summary.markets_with_negative_impact / summary.total_markets if summary.total_markets > 0 else 0.0
    
    if summary.avg_improvement_pct > 5.0 and summary.confidence_level > 0.7 and negative_impact_rate < 0.1:
        return "Strong evidence that debates improve prediction accuracy. Continue current debate strategy."
    elif summary.avg_improvement_pct > 0.0 and summary.confidence_level > 0.4 and negative_impact_rate < 0.3:
        return "Moderate evidence that debates help. Consider fine-tuning debate parameters."
    elif summary.avg_improvement_pct < -5.0 and summary.confidence_level > 0.7:
        return "Strong evidence that debates hurt accuracy. Review debate strategy and gate thresholds."
    elif negative_impact_rate > 0.4:
        return "High rate of negative impact detected. Investigate specific markets where debates hurt performance."
    else:
        return "Insufficient evidence to determine debate impact. Collect more data or adjust backtest parameters."
