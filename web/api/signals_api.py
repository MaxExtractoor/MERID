"""
API endpoints for signals (sentiment, events, alerts).
Exposes merid/signals/ package data to the frontend.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


# ── Response Models ──────────────────────────────────────────────────

class SentimentEventResponse(BaseModel):
    id: str
    timestamp: str
    source: str
    ticker: str
    polarity: float
    magnitude: float
    relevance: float
    headline: str
    isSpike: bool = False


class SentimentWindowResponse(BaseModel):
    ticker: str
    polarity: float
    magnitude: float
    eventCount: int
    sourceBreakdown: Dict[str, int]


class AlertHistoryItem(BaseModel):
    id: str
    timestamp: str
    severity: str
    channel: str
    title: str
    message: str
    acknowledged: bool = False


# ── Helpers ──────────────────────────────────────────────────────────

def _get_processor():
    """Lazy import to avoid circular deps."""
    try:
        from merid.signals.processing import get_sentiment_processor
        return get_sentiment_processor()
    except Exception as e:
        logger.warning(f"SentimentProcessor unavailable: {e}")
        return None


def _get_alert_router():
    try:
        from merid.signals.alerts import get_alert_router
        return get_alert_router()
    except Exception as e:
        logger.warning(f"AlertRouter unavailable: {e}")
        return None


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/sentiment")
async def get_sentiment_all():
    """Get sentiment windows and recent events for all tickers."""
    processor = _get_processor()
    if not processor:
        return {"events": [], "windows": [], "status": "processor_unavailable"}

    try:
        summary = processor.summary()
        windows = []
        events = []

        for ticker, data in summary.get("per_ticker", {}).items():
            windows.append({
                "ticker": ticker,
                "polarity": data.get("avg_polarity", 0.0),
                "magnitude": data.get("avg_magnitude", 0.0),
                "eventCount": data.get("event_count", 0),
                "sourceBreakdown": data.get("source_breakdown", {"x": 0, "news": 0, "telegram": 0}),
            })

        return {"events": events, "windows": windows, "status": "ok"}
    except Exception as e:
        logger.error(f"Error fetching sentiment: {e}")
        return {"events": [], "windows": [], "status": "error", "error": str(e)}


@router.get("/sentiment/{ticker}")
async def get_sentiment_ticker(ticker: str, minutes: int = Query(default=60)):
    """Get sentiment window and events for a specific ticker."""
    processor = _get_processor()
    if not processor:
        return {"events": [], "windows": [], "status": "processor_unavailable"}

    try:
        window = processor.get_window(ticker, minutes=minutes)
        spikes = processor.detect_spikes(ticker)

        window_data = None
        if window:
            window_data = {
                "ticker": window.ticker,
                "polarity": window.avg_polarity,
                "magnitude": window.avg_magnitude,
                "eventCount": window.event_count,
                "sourceBreakdown": {
                    "x": window.source_counts.get("x", 0),
                    "news": window.source_counts.get("news", 0),
                    "telegram": window.source_counts.get("telegram", 0),
                },
            }

        spike_events = []
        for spike in spikes:
            spike_events.append({
                "id": f"spike_{spike.ticker}_{int(spike.detected_at.timestamp())}",
                "timestamp": spike.detected_at.isoformat(),
                "source": "aggregated",
                "ticker": spike.ticker,
                "polarity": spike.short_window_polarity,
                "magnitude": abs(spike.delta),
                "relevance": 1.0,
                "headline": f"Sentiment spike: delta={spike.delta:.2f}",
                "isSpike": True,
            })

        return {
            "events": spike_events,
            "windows": [window_data] if window_data else [],
            "status": "ok",
        }
    except Exception as e:
        logger.error(f"Error fetching sentiment for {ticker}: {e}")
        return {"events": [], "windows": [], "status": "error", "error": str(e)}


@router.get("/events")
async def get_recent_events(limit: int = Query(default=50)):
    """Get recent ingested events."""
    try:
        from merid.signals.ingestion import get_event_buffer
        buffer = get_event_buffer()
        events = []
        for evt in list(buffer._events.values())[-limit:]:
            events.append({
                "id": evt.raw_text_hash[:12],
                "timestamp": evt.timestamp.isoformat(),
                "source": evt.source.value,
                "ticker": evt.tickers[0] if evt.tickers else "",
                "headline": evt.raw_text[:120],
                "eventType": evt.event_type.value,
            })
        return {"events": events, "status": "ok"}
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        return {"events": [], "status": "error", "error": str(e)}


@router.get("/alerts/history")
async def get_alert_history(limit: int = Query(default=100)):
    """Get dispatched alert history."""
    alert_router = _get_alert_router()
    if not alert_router:
        return {"alerts": [], "status": "router_unavailable"}

    try:
        history = alert_router.get_history(limit=limit)
        alerts = []
        for alert in history:
            alerts.append({
                "id": alert.get("id", ""),
                "timestamp": alert.get("timestamp", ""),
                "severity": alert.get("severity", "info"),
                "source": alert.get("source", alert.get("channel", "log")),
                "channel": alert.get("channel", "log"),
                "title": alert.get("title", ""),
                "detail": alert.get("detail", alert.get("message", "")),
                "message": alert.get("message", ""),
                "type": alert.get("type", alert.get("category", "signal")),
                "status": alert.get("status", "active"),
                "actions": alert.get("actions", []),
                "acknowledged": alert.get("acknowledged", False),
            })
        return {"alerts": alerts, "status": "ok"}
    except Exception as e:
        logger.error(f"Error fetching alert history: {e}")
        return {"alerts": [], "status": "error", "error": str(e)}


@router.get("/spikes")
async def get_all_spikes():
    """Detect sentiment spikes across all tracked tickers."""
    processor = _get_processor()
    if not processor:
        return {"spikes": [], "status": "processor_unavailable"}

    try:
        spikes = processor.detect_all_spikes()
        result = []
        for spike in spikes:
            result.append({
                "ticker": spike.ticker,
                "delta": spike.delta,
                "shortWindowPolarity": spike.short_window_polarity,
                "longWindowPolarity": spike.long_window_polarity,
                "detectedAt": spike.detected_at.isoformat(),
            })
        return {"spikes": result, "status": "ok"}
    except Exception as e:
        logger.error(f"Error detecting spikes: {e}")
        return {"spikes": [], "status": "error", "error": str(e)}
