from __future__ import annotations

"""Stage 9 Backtesting: historical replay utilities."""

from dataclasses import dataclass
from statistics import mean
from typing import Any, Dict, List

from memory.store import reality_memory


@dataclass
class BacktestSnapshot:
    total_realities: int
    avg_consensus: float
    avg_validation_score: float
    time_span_hours: float
    sources: Dict[str, int]
    keywords: List[str]


def _time_span_hours(entries: List[Dict[str, Any]]) -> float:
    if len(entries) < 2:
        return 0.0
    try:
        from datetime import datetime

        stamps = [
            datetime.fromisoformat(item.get("validated_at") or item.get("approved_at"))
            for item in entries
            if item.get("validated_at") or item.get("approved_at")
        ]
        if len(stamps) < 2:
            return 0.0
        span = max(stamps) - min(stamps)
        return span.total_seconds() / 3600.0
    except Exception:
        return 0.0


def _keyword_summary(entries: List[Dict[str, Any]]) -> List[str]:
    keywords: Dict[str, int] = {}
    for item in entries:
        payload = (item.get("payload") or "").lower()
        for token in payload.split():
            token = "".join(ch for ch in token if ch.isalnum())
            if len(token) < 4:
                continue
            keywords[token] = keywords.get(token, 0) + 1
    return [
        f"{word} ({count})"
        for word, count in sorted(keywords.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]


def run_backtest(limit: int = 100) -> BacktestSnapshot:
    entries = reality_memory.recent(limit)
    if not entries:
        return BacktestSnapshot(0, 0.0, 0.0, 0.0, {}, [])

    avg_consensus = mean(entry.get("consensus", 0.0) for entry in entries)
    avg_validation = mean(entry.get("validation", {}).get("score", 0.0) for entry in entries)
    sources: Dict[str, int] = {}
    for entry in entries:
        src = entry.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    return BacktestSnapshot(
        total_realities=len(entries),
        avg_consensus=avg_consensus,
        avg_validation_score=avg_validation,
        time_span_hours=_time_span_hours(entries),
        sources=sources,
        keywords=_keyword_summary(entries),
    )
