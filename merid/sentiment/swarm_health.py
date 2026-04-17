"""Health checks for swarm × mood grid (5 assets × 4 timeframes)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from config.kalshi_crypto_config import active_crypto_asset_mood_timeframe_grid
from merid.sentiment.neutral_streak_tracker import advance_neutral_streak
from merid.swarm.consensus_aggregator import get_consensus_aggregator
from merid.swarm.market_mood_bus import get_market_mood_bus

logger = get_logger("merid.sentiment.swarm_health")

_last_health_ts: Optional[float] = None


def _sentiment_fills_last_minutes(minutes: int = 15) -> int:
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

        cut = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        n = 0
        for f in get_fills_ledger().get_fills():
            if getattr(f, "created_time", None) and f.created_time >= cut:
                tid = getattr(f, "decision_trace_id", None) or (
                    (f.raw_payload or {}).get("decision_trace_id") if getattr(f, "raw_payload", None) else None
                )
                if tid:
                    n += 1
        return n
    except Exception as exc:
        logger.debug("sentiment_fills_last_minutes: %s", exc)
        return 0


def evaluate_swarm_grid_health() -> Dict[str, Any]:
    """Return per-cell consensus/mood snapshot, neutral streaks, and simple warnings."""
    global _last_health_ts

    mood = get_market_mood_bus()
    agg = get_consensus_aggregator()
    cells: List[Dict[str, Any]] = []
    warnings: List[str] = []

    now = time.time()
    dt_min = 5.0 if _last_health_ts is None else max(1.0 / 60.0, (now - _last_health_ts) / 60.0)
    _last_health_ts = now

    for asset, tf in active_crypto_asset_mood_timeframe_grid():
        ctx = mood.get_context(asset, tf)
        cv = agg.get_consensus_or_neutral(asset, tf)
        neutral_only = cv.consensus_direction == "neutral" and cv.consensus_probability == 0.5
        streak = advance_neutral_streak(
            asset,
            tf,
            consensus_usable=cv.usable,
            is_probability_neutral=neutral_only,
            dt_minutes=dt_min,
        )
        if streak.get("warn_long_neutral"):
            warnings.append(
                f"{asset}:{tf}: neutral/unusable streak {streak['neutral_streak_minutes']:.1f}m"
            )
        cells.append(
            {
                "asset": asset,
                "timeframe": tf,
                "consensus_usable": cv.usable,
                "consensus_confidence": round(cv.consensus_confidence, 4),
                "consensus_direction": cv.consensus_direction,
                "consensus_probability": round(cv.consensus_probability, 4),
                "status": cv.status.value if hasattr(cv.status, "value") else str(cv.status),
                "mood_fg": getattr(ctx, "fg_index", None) if ctx else None,
                "neutral_streak_minutes": streak["neutral_streak_minutes"],
                "warn_long_neutral": streak["warn_long_neutral"],
            }
        )
        if cv.usable and neutral_only:
            warnings.append(f"{asset}:{tf}: usable but probability neutral (check proposals)")

    return {
        "ok": True,
        "cell_count": len(cells),
        "cells": cells,
        "warnings": warnings,
        "sentiment_tagged_fills_last_15m": _sentiment_fills_last_minutes(15),
    }


def evaluate_sentiment_health() -> Dict[str, Any]:
    """Extended health: grid + fill velocity for sentiment-tagged trades."""
    base = evaluate_swarm_grid_health()
    base["sentiment_orders_last_15m"] = base.get("sentiment_tagged_fills_last_15m", 0)
    return base
