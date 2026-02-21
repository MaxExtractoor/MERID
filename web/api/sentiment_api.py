"""Sentiment API — Hashtag, news, and asset sentiment endpoints.

Exposes SentimentBusV2 data to the UI and Telegram monitoring layer.
All endpoints are read-only; no order placement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/sentiment", tags=["sentiment"])


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
        raise HTTPException(status_code=500, detail=str(exc))


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
