"""Sentiment API — Hashtag, news, and asset sentiment endpoints.

Exposes SentimentBusV2 data to the UI and Telegram monitoring layer.
All endpoints are read-only; no order placement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/sentiment", tags=["sentiment"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_bus():
    from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
    return get_sentiment_bus_v2()


def _get_monitor():
    from merid.sentiment.hashtag_monitor import get_hashtag_monitor
    return get_hashtag_monitor()


# ── Asset context ─────────────────────────────────────────────────────────

@router.get("/asset/{asset}")
async def get_asset_sentiment(asset: str) -> Dict[str, Any]:
    """Full sentiment context for a crypto asset (FG + social + news + hashtag)."""
    try:
        bus = _get_bus()
        ctx = bus.get_asset_context(asset.upper())
        return ctx.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/assets")
async def get_all_asset_sentiments() -> Dict[str, Any]:
    """Sentiment context for all tracked crypto assets."""
    try:
        bus = _get_bus()
        return {
            asset: ctx.to_dict()
            for asset, ctx in bus.get_all_asset_contexts().items()
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Event context ─────────────────────────────────────────────────────────

@router.get("/event/{event_id}")
async def get_event_sentiment(
    event_id: str,
    category: str = Query(default=""),
    asset: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Sentiment context for a specific Kalshi event."""
    try:
        bus = _get_bus()
        ctx = bus.get_event_context(
            event_id,
            category=category,
            asset=asset.upper() if asset else None,
        )
        return ctx.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Market context ────────────────────────────────────────────────────────

@router.get("/market/{market_id}")
async def get_market_sentiment(
    market_id: str,
    event_id: Optional[str] = Query(default=None),
    asset: Optional[str] = Query(default=None),
    category: str = Query(default=""),
) -> Dict[str, Any]:
    """Composite sentiment context for a Kalshi market."""
    try:
        bus = _get_bus()
        ctx = bus.get_market_context(
            market_id,
            event_id=event_id,
            asset=asset.upper() if asset else None,
            category=category,
        )
        return ctx.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Hashtag summary ───────────────────────────────────────────────────────

@router.get("/hashtags")
async def get_hashtag_summary() -> Dict[str, Any]:
    """All hashtag contexts — scores, volumes, directions, top tags."""
    try:
        bus = _get_bus()
        return bus.get_hashtag_summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/hashtags/signals")
async def get_latest_signals() -> Dict[str, Any]:
    """Latest HashtagSignal objects from the most recent monitor cycle."""
    try:
        monitor = _get_monitor()
        signals = monitor.get_latest_signals()
        if signals:
            return {
                "count": len(signals),
                "signals": [
                    {
                        "asset_or_event": s.asset_or_event,
                        "direction": s.direction,
                        "strength": s.strength,
                        "reason": s.reason,
                        "score": s.score,
                        "volume": s.volume,
                        "tags": s.tags[:6],
                        "category": s.category,
                        "timestamp": s.timestamp.isoformat(),
                    }
                    for s in signals
                ],
            }
    except Exception as exc:
        logger.debug(f"hashtag_signals monitor: {exc}")

    # Fallback: derive from sentiment bus asset contexts
    from datetime import datetime as _dt, timezone as _tz
    _now = _dt.now(_tz.utc)
    derived_signals = []
    try:
        bus = _get_bus()
        for asset, ctx in bus.get_all_asset_contexts().items():
            ctx_d = ctx.to_dict() if hasattr(ctx, "to_dict") else ctx
            score = ctx_d.get("fg_index", 50)
            social = ctx_d.get("social_score", 0)
            if score != 50 or social != 0:
                direction = "bullish" if score > 55 else ("bearish" if score < 45 else "neutral")
                strength = abs(score - 50) / 50.0
                derived_signals.append({
                    "asset_or_event": asset,
                    "direction": direction,
                    "strength": round(strength, 3),
                    "reason": f"FG={score}, social={social:.2f}" if isinstance(social, float) else f"FG={score}",
                    "score": round((score - 50) / 50.0, 3),
                    "volume": 0,
                    "tags": [asset.lower(), direction],
                    "category": "crypto",
                    "timestamp": _now.isoformat(),
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    # Fallback: Reddit sentiment
    try:
        from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
        reddit = get_reddit_sentiment_service()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            result = reddit.get_cached_sentiment(asset)
            if result and result.get("score", 0) != 0:
                sc = result["score"]
                derived_signals.append({
                    "asset_or_event": asset,
                    "direction": "bullish" if sc > 0 else "bearish",
                    "strength": round(min(abs(sc), 1.0), 3),
                    "reason": f"Reddit sentiment: {sc:+.3f}, confidence={result.get('confidence', 0):.2f}",
                    "score": round(sc, 3),
                    "volume": result.get("volume", 0),
                    "tags": [asset.lower(), "reddit"],
                    "category": "social",
                    "timestamp": _now.isoformat(),
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    return {"count": len(derived_signals), "signals": derived_signals}


# ── News summary ──────────────────────────────────────────────────────────

@router.get("/news")
async def get_news_summary() -> Dict[str, Any]:
    """All news sentiment contexts — scores, labels, headline counts."""
    try:
        bus = _get_bus()
        return bus.get_news_summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Risk overlay ──────────────────────────────────────────────────────────

@router.get("/risk/{asset}")
async def get_risk_overlay(asset: str) -> Dict[str, Any]:
    """Risk-relevant sentiment fields for the FG clamp layer."""
    try:
        bus = _get_bus()
        return bus.get_risk_overlay(asset.upper())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Monitor status ────────────────────────────────────────────────────────

@router.get("/monitor/status")
async def get_monitor_status() -> Dict[str, Any]:
    """HashtagMonitor runtime stats."""
    try:
        monitor = _get_monitor()
        return monitor.get_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class ForceCycleResponse(BaseModel):
    signals_generated: int
    signals: List[Dict[str, Any]]


@router.post("/monitor/force-cycle")
async def force_hashtag_cycle() -> ForceCycleResponse:
    """Trigger an immediate hashtag scrape cycle (operator/debug use)."""
    try:
        monitor = _get_monitor()
        signals = await monitor.force_hashtag_cycle()
        return ForceCycleResponse(
            signals_generated=len(signals),
            signals=[
                {
                    "asset_or_event": s.asset_or_event,
                    "direction": s.direction,
                    "strength": s.strength,
                    "reason": s.reason,
                }
                for s in signals
            ],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/monitor/force-news-cycle")
async def force_news_cycle() -> Dict[str, Any]:
    """Trigger an immediate news ingestion cycle."""
    try:
        monitor = _get_monitor()
        await monitor.force_news_cycle()
        return {"status": "ok", "message": "News cycle triggered"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
