"""Sentiment Pipeline API Endpoints.

REST API endpoints for the news sentiment to Kalshi market pipeline:
- POST /api/v1/sentiment/event — Submit a news sentiment event
- POST /api/v1/sentiment/headline — Submit a headline for processing
- GET /api/v1/sentiment/scores — Get current sentiment scores
- GET /api/v1/sentiment/comparison/{asset}/{horizon} — Get sentiment vs market comparison
- GET /api/v1/sentiment/snapshot — Get full pipeline snapshot
- GET /api/v1/sentiment/history/{asset} — Get historical sentiment data
- GET /api/v1/sentiment/statistics — Get pipeline statistics
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime
import asyncio

from merid.sentiment.news_event_schema import Asset, EventType, SourceWeight
from merid.sentiment.sentiment_pipeline_orchestrator import (
    get_sentiment_pipeline_orchestrator,
)
from merid.sentiment.sentiment_scoring_service import get_sentiment_scoring_service
from merid.sentiment.kalshi_market_mapper import get_kalshi_market_mapper
from merid.sentiment.sentiment_store import get_sentiment_store
from utils.logger import get_logger

logger = get_logger("web.api.sentiment_pipeline_api")

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


# ── Request/Response Models ────────────────────────────────────────────────

class SubmitEventRequest(BaseModel):
    """Request to submit a sentiment event."""
    asset: str = Field(..., description="Asset code (BTC, ETH, SOL, XRP, DOGE)")
    event_type: str = Field(..., description="Event type (regulation, etf, hack, etc.)")
    sentiment: float = Field(..., ge=-1.0, le=1.0, description="Sentiment score (-1 to +1)")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence (0 to 1)")
    headline: str = Field(..., description="News headline")
    source: str = Field(default="unknown", description="News source")
    url: str = Field(default="", description="Article URL")
    source_weight: str = Field(default="unknown", description="Source weight")
    evidence_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Evidence score")
    is_rumor: bool = Field(default=False, description="Is this a rumor?")
    is_recycled: bool = Field(default=False, description="Is this a recycled story?")
    horizon: str = Field(default="short", description="Time horizon (short, medium, long)")


class SubmitHeadlineRequest(BaseModel):
    """Request to submit a headline for processing."""
    headline: str = Field(..., description="News headline")
    asset: str = Field(..., description="Asset code")
    sentiment_score: float = Field(..., ge=-1.0, le=1.0, description="Sentiment score")
    source: str = Field(default="unknown", description="News source")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence")


class SentimentScoreResponse(BaseModel):
    """Response with sentiment score."""
    asset: str
    sentiment: float
    confidence: float
    event_count: int
    bull_weight: float
    bear_weight: float
    short_sentiment: float
    medium_sentiment: float
    long_sentiment: float
    last_update: str


class ComparisonResponse(BaseModel):
    """Response with sentiment vs market comparison."""
    asset: str
    horizon: str
    ticker: str
    sentiment_score: float
    sentiment_probability: float
    implied_probability: Optional[float]
    difference: Optional[float]
    edge_cents: Optional[float]
    signal: str
    timestamp: str


class PipelineSnapshotResponse(BaseModel):
    """Response with full pipeline snapshot."""
    sentiment_scores: Dict[str, Any]
    market_mappings: Dict[str, Any]
    comparisons: List[Dict[str, Any]]
    timestamp: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/event")
async def submit_event(request: SubmitEventRequest) -> Dict[str, Any]:
    """Submit a news sentiment event to the pipeline.
    
    Processes the event through:
    1. Event storage
    2. Sentiment scoring with decay
    3. Market mapping
    4. Comparison with Kalshi prices
    """
    try:
        # Convert asset string to enum
        asset_enum = Asset(request.asset.upper())
        
        # Convert event type string to enum
        event_type_enum = EventType(request.event_type.lower())
        
        # Convert source weight string to enum
        source_weight_enum = SourceWeight(request.source_weight.lower())
        
        # Create event
        from merid.sentiment.news_event_schema import NewsSentimentEvent
        
        event = NewsSentimentEvent(
            asset=asset_enum,
            event_type=event_type_enum,
            sentiment=request.sentiment,
            confidence=request.confidence,
            headline=request.headline,
            source=request.source,
            url=request.url,
            source_weight=source_weight_enum,
            evidence_score=request.evidence_score,
            is_rumor=request.is_rumor,
            is_recycled=request.is_recycled,
            horizon=request.horizon,
        )
        
        # Process through pipeline
        orchestrator = get_sentiment_pipeline_orchestrator()
        result = await orchestrator.process_event(event)
        
        return result
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {exc}")
    except Exception as exc:
        logger.error("Failed to process sentiment event: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/headline")
async def submit_headline(request: SubmitHeadlineRequest) -> Dict[str, Any]:
    """Submit a headline for automatic processing.
    
    Convenience endpoint that infers event type, source weight, and horizon
    from the headline content.
    """
    try:
        # Convert asset string to enum
        asset_enum = Asset(request.asset.upper())
        
        # Process headline
        orchestrator = get_sentiment_pipeline_orchestrator()
        result = await orchestrator.process_headline(
            headline=request.headline,
            asset=asset_enum,
            sentiment_score=request.sentiment_score,
            source=request.source,
            confidence=request.confidence,
        )
        
        return result
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {exc}")
    except Exception as exc:
        logger.error("Failed to process headline: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/scores")
async def get_sentiment_scores() -> Dict[str, Any]:
    """Get current sentiment scores for all assets.
    
    Returns decay-weighted sentiment scores with confidence metrics.
    """
    try:
        scoring_service = get_sentiment_scoring_service()
        scores = scoring_service.get_all_scores()
        
        return {
            "scores": {asset.value: score.to_dict() for asset, score in scores.items()},
            "timestamp": datetime.utcnow().isoformat(),
        }
        
    except Exception as exc:
        logger.error("Failed to get sentiment scores: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/score/{asset}")
async def get_sentiment_score(asset: str) -> Dict[str, Any]:
    """Get sentiment score for a specific asset.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
    """
    try:
        asset_enum = Asset(asset.upper())
        scoring_service = get_sentiment_scoring_service()
        score = scoring_service.get_score(asset_enum)
        
        if not score:
            raise HTTPException(status_code=404, detail=f"No sentiment data for {asset}")
        
        return score.to_dict()
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid asset: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get sentiment score: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/comparison/{asset}/{horizon}")
async def get_comparison(asset: str, horizon: str) -> Dict[str, Any]:
    """Get sentiment vs market comparison for asset and horizon.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
        horizon: Time horizon (short, medium, long)
    
    Returns comparison of sentiment score vs Kalshi market-implied probabilities.
    """
    try:
        asset_enum = Asset(asset.upper())
        
        if horizon not in ["short", "medium", "long"]:
            raise HTTPException(status_code=400, detail="Invalid horizon (must be short, medium, long)")
        
        orchestrator = get_sentiment_pipeline_orchestrator()
        comparisons = await orchestrator.get_comparison(asset_enum, horizon)
        
        return {
            "asset": asset,
            "horizon": horizon,
            "comparisons": [comp.to_dict() for comp in comparisons],
            "count": len(comparisons),
        }
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get comparison: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/snapshot")
async def get_pipeline_snapshot() -> Dict[str, Any]:
    """Get full pipeline snapshot.
    
    Returns current sentiment scores, market mappings, and comparisons.
    """
    try:
        orchestrator = get_sentiment_pipeline_orchestrator()
        snapshot = await orchestrator.get_snapshot()
        
        return snapshot.to_dict()
        
    except Exception as exc:
        logger.error("Failed to get pipeline snapshot: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history/{asset}")
async def get_sentiment_history(
    asset: str,
    hours: int = 24,
    interval_minutes: int = 5,
) -> Dict[str, Any]:
    """Get historical sentiment data for an asset.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
        hours: Lookback window in hours
        interval_minutes: Minimum interval between snapshots
    """
    try:
        asset_enum = Asset(asset.upper())
        sentiment_store = get_sentiment_store()
        
        snapshots = sentiment_store.get_history(
            asset_enum,
            hours=hours,
            interval_minutes=interval_minutes,
        )
        
        return {
            "asset": asset,
            "hours": hours,
            "interval_minutes": interval_minutes,
            "snapshots": [s.to_dict() for s in snapshots],
            "count": len(snapshots),
        }
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid asset: {exc}")
    except Exception as exc:
        logger.error("Failed to get sentiment history: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/events/{asset}")
async def get_sentiment_events(
    asset: str,
    hours: int = 24,
) -> Dict[str, Any]:
    """Get sentiment events for an asset.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
        hours: Lookback window in hours
    """
    try:
        asset_enum = Asset(asset.upper())
        sentiment_store = get_sentiment_store()
        
        events = sentiment_store.get_events_for_asset(asset_enum, hours=hours)
        
        return {
            "asset": asset,
            "hours": hours,
            "events": events,
            "count": len(events),
        }
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid asset: {exc}")
    except Exception as exc:
        logger.error("Failed to get sentiment events: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/statistics")
async def get_pipeline_statistics() -> Dict[str, Any]:
    """Get pipeline statistics.
    
    Returns event counts, score counts, database size, etc.
    """
    try:
        orchestrator = get_sentiment_pipeline_orchestrator()
        stats = orchestrator.get_statistics()
        
        return stats
        
    except Exception as exc:
        logger.error("Failed to get pipeline statistics: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/refresh-mappings")
async def refresh_market_mappings(force: bool = False) -> Dict[str, Any]:
    """Force refresh Kalshi market mappings.
    
    Args:
        force: Force refresh even if within interval
    """
    try:
        market_mapper = get_kalshi_market_mapper()
        result = await market_mapper.refresh_all_mappings(force=force)
        
        return result
        
    except Exception as exc:
        logger.error("Failed to refresh market mappings: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/mappings")
async def get_market_mappings() -> Dict[str, Any]:
    """Get current market mappings.
    
    Returns mapping of (asset, horizon) to Kalshi market tickers.
    """
    try:
        market_mapper = get_kalshi_market_mapper()
        mappings = market_mapper.get_all_mappings()
        
        return {
            "mappings": {
                f"{asset.value}:{horizon}": mapping.to_dict()
                for (asset, horizon), mapping in mappings.items()
            },
            "count": len(mappings),
        }
        
    except Exception as exc:
        logger.error("Failed to get market mappings: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/start")
async def start_pipeline() -> Dict[str, Any]:
    """Start the sentiment pipeline background refresh loop.
    
    Starts periodic refresh of market mappings and score snapshots.
    """
    try:
        orchestrator = get_sentiment_pipeline_orchestrator()
        await orchestrator.start()
        
        return {"status": "started", "message": "Pipeline refresh loop started"}
        
    except Exception as exc:
        logger.error("Failed to start pipeline: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop")
async def stop_pipeline() -> Dict[str, Any]:
    """Stop the sentiment pipeline background refresh loop."""
    try:
        orchestrator = get_sentiment_pipeline_orchestrator()
        await orchestrator.stop()
        
        return {"status": "stopped", "message": "Pipeline refresh loop stopped"}
        
    except Exception as exc:
        logger.error("Failed to stop pipeline: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/edge-summary")
async def get_edge_summary() -> Dict[str, Any]:
    """Get current edge summary across all assets and horizons.
    
    Returns edge, confidence, and signal for each asset/horizon combination.
    """
    try:
        from merid.sentiment.sentiment_reconciliation_job import (
            get_sentiment_reconciliation_job,
        )
        
        job = get_sentiment_reconciliation_job()
        summary = job.get_edge_summary()
        
        return {
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
    except Exception as exc:
        logger.error("Failed to get edge summary: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reconcile")
async def run_reconciliation() -> Dict[str, Any]:
    """Run sentiment vs market reconciliation once.
    
    Forces an immediate reconciliation run and returns the report.
    """
    try:
        from merid.sentiment.sentiment_reconciliation_job import (
            get_sentiment_reconciliation_job,
        )
        
        job = get_sentiment_reconciliation_job()
        report = await job.run_once()
        
        return report.to_dict()
        
    except Exception as exc:
        logger.error("Failed to run reconciliation: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reconcile/start")
async def start_reconciliation() -> Dict[str, Any]:
    """Start the periodic reconciliation job."""
    try:
        from merid.sentiment.sentiment_reconciliation_job import (
            get_sentiment_reconciliation_job,
        )
        
        job = get_sentiment_reconciliation_job()
        await job.start()
        
        return {"status": "started", "message": "Reconciliation job started"}
        
    except Exception as exc:
        logger.error("Failed to start reconciliation: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reconcile/stop")
async def stop_reconciliation() -> Dict[str, Any]:
    """Stop the periodic reconciliation job."""
    try:
        from merid.sentiment.sentiment_reconciliation_job import (
            get_sentiment_reconciliation_job,
        )
        
        job = get_sentiment_reconciliation_job()
        await job.stop()
        
        return {"status": "stopped", "message": "Reconciliation job stopped"}
        
    except Exception as exc:
        logger.error("Failed to stop reconciliation: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watcher/start")
async def start_market_watcher() -> Dict[str, Any]:
    """Start the Kalshi market watcher for live data."""
    try:
        from merid.sentiment.kalshi_market_watcher import get_kalshi_market_watcher
        
        watcher = get_kalshi_market_watcher()
        await watcher.start()
        
        return {"status": "started", "message": "Market watcher started"}
        
    except Exception as exc:
        logger.error("Failed to start market watcher: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/watcher/stop")
async def stop_market_watcher() -> Dict[str, Any]:
    """Stop the Kalshi market watcher."""
    try:
        from merid.sentiment.kalshi_market_watcher import get_kalshi_market_watcher
        
        watcher = get_kalshi_market_watcher()
        await watcher.stop()
        
        return {"status": "stopped", "message": "Market watcher stopped"}
        
    except Exception as exc:
        logger.error("Failed to stop market watcher: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/watcher/statistics")
async def get_watcher_statistics() -> Dict[str, Any]:
    """Get market watcher statistics."""
    try:
        from merid.sentiment.kalshi_market_watcher import get_kalshi_market_watcher
        
        watcher = get_kalshi_market_watcher()
        stats = watcher.get_statistics()
        
        return stats
        
    except Exception as exc:
        logger.error("Failed to get watcher statistics: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
