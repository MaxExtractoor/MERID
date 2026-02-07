"""§1 Domain objects — InfoEvent, SentimentFeature, SentimentSpike.

Unified event schema for all unstructured data sources (X, Telegram, news).
Everything flows through InfoEvent → SentimentFeature → agents.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.events")


# ── Source enum ──────────────────────────────────────────────────────

class InfoSource(str, Enum):
    X = "x"
    TELEGRAM = "telegram"
    NEWS = "news"
    RSS = "rss"
    MANUAL = "manual"


class EventType(str, Enum):
    TWEET = "tweet"
    TELEGRAM_MSG = "telegram_msg"
    NEWS_ARTICLE = "news_article"
    RSS_ITEM = "rss_item"
    OPERATOR_COMMAND = "operator_command"


# ── InfoEvent — unified raw event ────────────────────────────────────

@dataclass
class InfoEvent:
    """Normalized event from any unstructured source.

    Every tweet, Telegram message, and news article becomes an InfoEvent
    before processing.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source: InfoSource = InfoSource.NEWS
    event_type: EventType = EventType.NEWS_ARTICLE
    raw_text: str = ""
    entities: List[str] = field(default_factory=list)   # Tickers, names
    tickers: List[str] = field(default_factory=list)     # Extracted tickers
    author: str = ""
    url: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_text_hash: str = ""

    def __post_init__(self):
        if self.raw_text and not self.raw_text_hash:
            self.raw_text_hash = hashlib.sha256(self.raw_text.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "source": self.source.value,
            "event_type": self.event_type.value,
            "raw_text": self.raw_text[:200] + "..." if len(self.raw_text) > 200 else self.raw_text,
            "entities": self.entities,
            "tickers": self.tickers,
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "raw_text_hash": self.raw_text_hash,
        }


# ── SentimentFeature — processed sentiment ──────────────────────────

@dataclass
class SentimentFeature:
    """Processed sentiment for a single event or aggregate window."""
    feature_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    event_id: str = ""
    source: InfoSource = InfoSource.NEWS
    ticker: str = ""
    polarity: float = 0.0        # -1.0 (bearish) to +1.0 (bullish)
    magnitude: float = 0.0       # 0.0 to 1.0 (strength)
    relevance: float = 0.0       # 0.0 to 1.0 (trade-relevance)
    actionability: float = 0.0   # 0.0 to 1.0 (is this actionable?)
    topic_tags: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "event_id": self.event_id,
            "source": self.source.value,
            "ticker": self.ticker,
            "polarity": round(self.polarity, 4),
            "magnitude": round(self.magnitude, 4),
            "relevance": round(self.relevance, 4),
            "actionability": round(self.actionability, 4),
            "topic_tags": self.topic_tags,
            "timestamp": self.timestamp.isoformat(),
        }


# ── SentimentSpike — threshold-crossing event ───────────────────────

@dataclass
class SentimentSpike:
    """Detected when short-term sentiment diverges from long-term baseline."""
    spike_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    ticker: str = ""
    source: str = "combined"     # "x", "news", "combined"
    short_window_avg: float = 0.0
    long_window_avg: float = 0.0
    delta: float = 0.0
    short_window_count: int = 0
    long_window_count: int = 0
    direction: str = "neutral"   # "bullish", "bearish", "neutral"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "spike_id": self.spike_id,
            "ticker": self.ticker,
            "source": self.source,
            "short_window_avg": round(self.short_window_avg, 4),
            "long_window_avg": round(self.long_window_avg, 4),
            "delta": round(self.delta, 4),
            "direction": self.direction,
            "short_window_count": self.short_window_count,
            "long_window_count": self.long_window_count,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Aggregate sentiment window ──────────────────────────────────────

@dataclass
class SentimentWindow:
    """Aggregated sentiment for a ticker over a time window."""
    ticker: str = ""
    window: str = "15m"
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    avg_polarity: float = 0.0
    avg_magnitude: float = 0.0
    sample_count: int = 0
    x_count: int = 0
    news_count: int = 0
    telegram_count: int = 0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "window": self.window,
            "avg_polarity": round(self.avg_polarity, 4),
            "avg_magnitude": round(self.avg_magnitude, 4),
            "sample_count": self.sample_count,
            "x_count": self.x_count,
            "news_count": self.news_count,
            "telegram_count": self.telegram_count,
        }


# ── Operator command ─────────────────────────────────────────────────

@dataclass
class OperatorCommand:
    """Parsed operator command from Telegram."""
    command_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    command: str = ""            # "pause", "resume", "status", "kill_switch"
    domain: str = ""             # "crypto", "prediction", "equity", "all"
    reason: str = ""
    source: InfoSource = InfoSource.TELEGRAM
    operator_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "command": self.command,
            "domain": self.domain,
            "reason": self.reason,
            "source": self.source.value,
            "operator_id": self.operator_id,
            "timestamp": self.timestamp.isoformat(),
        }
