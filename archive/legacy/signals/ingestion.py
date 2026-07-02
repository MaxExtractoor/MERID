"""§2 Ingestion — XWorker, TelegramWorker, NewsWorker.

Workers that consume raw data from X/Twitter, Telegram, and news APIs,
normalize into InfoEvent objects, and push to the event buffer.
"""

from __future__ import annotations

import threading
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.signals.events import (
    EventType,
    InfoEvent,
    InfoSource,
    OperatorCommand,
)

from utils.logger import get_logger

logger = get_logger("merid.signals.ingestion")


# ── Ticker extraction ────────────────────────────────────────────────

# Common crypto + equity tickers
KNOWN_TICKERS = {
    "BTC", "ETH", "SOL", "DOGE", "ADA", "XRP", "AVAX", "POL", "DOT",
    "LINK", "UNI", "AAVE", "CRV", "MKR", "COMP", "SNX",
    "AAPL", "TSLA", "MSFT", "NVDA", "GOOG", "AMZN", "META", "SPY", "QQQ",
    "USDC", "USDT", "DAI",
}

_CASHTAG_RE = re.compile(r"\$([A-Z]{2,6})\b")


def extract_tickers(text: str) -> List[str]:
    """Extract ticker symbols from text via $CASHTAG and known-ticker matching."""
    found = set()
    # Cashtags
    for match in _CASHTAG_RE.finditer(text):
        found.add(match.group(1))
    # Known tickers as standalone words
    words = re.findall(r"\b([A-Z]{2,6})\b", text.upper())
    for w in words:
        if w in KNOWN_TICKERS:
            found.add(w)
    return sorted(found)


# ── Event buffer ─────────────────────────────────────────────────────

class EventBuffer:
    """In-memory event buffer (Redis/Kafka in production).

    Stores InfoEvents for real-time processing and deduplication.
    """

    def __init__(self, max_size: int = 10000):
        self._events: List[InfoEvent] = []
        self._seen_hashes: set = set()
        self.max_size = max_size

    def push(self, event: InfoEvent) -> bool:
        """Push event to buffer. Returns False if duplicate."""
        if event.raw_text_hash in self._seen_hashes:
            return False
        if event.raw_text_hash:
            self._seen_hashes.add(event.raw_text_hash)
        self._events.append(event)
        # Evict oldest if over capacity
        if len(self._events) > self.max_size:
            evicted = self._events.pop(0)
            self._seen_hashes.discard(evicted.raw_text_hash)
        return True

    def pop_batch(self, limit: int = 100) -> List[InfoEvent]:
        """Pop a batch of events for processing."""
        batch = self._events[:limit]
        self._events = self._events[limit:]
        return batch

    def peek(self, limit: int = 10) -> List[InfoEvent]:
        """Peek at recent events without removing."""
        return self._events[-limit:]

    @property
    def size(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._seen_hashes.clear()


# ── XWorker (Twitter/X ingestion) ────────────────────────────────────

class XWorker:
    """Ingests tweets from X/Twitter and normalizes to InfoEvents.

    In production: subscribes to filtered streams via tweepy.
    Here: provides the typed interface and manual ingestion.
    """

    def __init__(self, buffer: Optional[EventBuffer] = None):
        self._buffer = buffer or EventBuffer()
        self._watchlist: List[str] = []     # Accounts to follow
        self._cashtags: List[str] = []      # Cashtags to track
        self._ingested_count: int = 0

    def watch_account(self, handle: str) -> None:
        if handle not in self._watchlist:
            self._watchlist.append(handle)

    def watch_cashtag(self, tag: str) -> None:
        tag = tag.upper().lstrip("$")
        if tag not in self._cashtags:
            self._cashtags.append(tag)

    def ingest_tweet(self, tweet_data: Dict[str, Any]) -> Optional[InfoEvent]:
        """Normalize a raw tweet dict into an InfoEvent."""
        text = tweet_data.get("text", "")
        if not text:
            return None

        tickers = extract_tickers(text)
        event = InfoEvent(
            source=InfoSource.X,
            event_type=EventType.TWEET,
            raw_text=text,
            tickers=tickers,
            entities=tickers,
            author=tweet_data.get("author", ""),
            url=tweet_data.get("url", ""),
            timestamp=tweet_data.get("created_at", datetime.now(timezone.utc)),
            metadata={
                "tweet_id": tweet_data.get("id", ""),
                "likes": tweet_data.get("likes", 0),
                "retweets": tweet_data.get("retweets", 0),
                "lang": tweet_data.get("lang", "en"),
            },
        )
        pushed = self._buffer.push(event)
        if pushed:
            self._ingested_count += 1
        return event if pushed else None

    def ingest_batch(self, tweets: List[Dict[str, Any]]) -> int:
        """Ingest a batch of tweets. Returns count of new events."""
        count = 0
        for t in tweets:
            if self.ingest_tweet(t):
                count += 1
        return count

    @property
    def buffer(self) -> EventBuffer:
        return self._buffer

    def summary(self) -> dict:
        return {
            "worker": "x",
            "watchlist": self._watchlist,
            "cashtags": self._cashtags,
            "ingested_count": self._ingested_count,
            "buffer_size": self._buffer.size,
        }


# ── TelegramWorker ───────────────────────────────────────────────────

OPERATOR_COMMANDS = {"pause", "resume", "status", "kill_switch", "positions", "risk"}


class TelegramWorker:
    """Ingests Telegram messages and normalizes to InfoEvents or OperatorCommands.

    Separates operator commands from informational messages.
    """

    def __init__(self, buffer: Optional[EventBuffer] = None):
        self._buffer = buffer or EventBuffer()
        self._commands: List[OperatorCommand] = []
        self._ingested_count: int = 0

    def ingest_message(self, msg_data: Dict[str, Any]) -> Optional[InfoEvent]:
        """Normalize a Telegram message into an InfoEvent or OperatorCommand."""
        text = msg_data.get("text", "")
        if not text:
            return None

        # Check for operator command
        if text.startswith("/"):
            cmd = self._parse_command(text, msg_data)
            if cmd:
                self._commands.append(cmd)
                # Also create an InfoEvent for audit
                event = InfoEvent(
                    source=InfoSource.TELEGRAM,
                    event_type=EventType.OPERATOR_COMMAND,
                    raw_text=text,
                    author=msg_data.get("from", "operator"),
                    metadata={"command": cmd.to_dict()},
                )
                self._buffer.push(event)
                self._ingested_count += 1
                return event

        # Regular message
        tickers = extract_tickers(text)
        event = InfoEvent(
            source=InfoSource.TELEGRAM,
            event_type=EventType.TELEGRAM_MSG,
            raw_text=text,
            tickers=tickers,
            entities=tickers,
            author=msg_data.get("from", ""),
            timestamp=msg_data.get("date", datetime.now(timezone.utc)),
        )
        pushed = self._buffer.push(event)
        if pushed:
            self._ingested_count += 1
        return event if pushed else None

    def _parse_command(self, text: str, msg_data: Dict[str, Any]) -> Optional[OperatorCommand]:
        """Parse /command domain=X reason='Y' format."""
        parts = text.strip().split()
        cmd_name = parts[0].lstrip("/").lower()
        if cmd_name not in OPERATOR_COMMANDS:
            return None

        domain = ""
        reason = ""
        for part in parts[1:]:
            if part.startswith("domain="):
                domain = part.split("=", 1)[1]
            elif part.startswith("reason="):
                reason = part.split("=", 1)[1].strip("'\"")
            elif not domain:
                domain = part

        return OperatorCommand(
            command=cmd_name,
            domain=domain,
            reason=reason,
            operator_id=msg_data.get("from", "operator"),
        )

    def get_pending_commands(self) -> List[OperatorCommand]:
        """Get and clear pending operator commands."""
        cmds = list(self._commands)
        self._commands.clear()
        return cmds

    @property
    def buffer(self) -> EventBuffer:
        return self._buffer

    def summary(self) -> dict:
        return {
            "worker": "telegram",
            "ingested_count": self._ingested_count,
            "pending_commands": len(self._commands),
            "buffer_size": self._buffer.size,
        }


# ── NewsWorker ───────────────────────────────────────────────────────

class NewsWorker:
    """Ingests news articles from APIs (NewsAPI, Polygon, Finnhub, RSS).

    Normalizes into InfoEvents with extracted tickers and metadata.
    """

    def __init__(self, buffer: Optional[EventBuffer] = None):
        self._buffer = buffer or EventBuffer()
        self._sources: List[str] = ["newsapi", "polygon", "finnhub", "rss"]
        self._ingested_count: int = 0

    def ingest_article(self, article: Dict[str, Any]) -> Optional[InfoEvent]:
        """Normalize a news article dict into an InfoEvent."""
        headline = article.get("headline", article.get("title", ""))
        body = article.get("body", article.get("description", ""))
        text = f"{headline} {body}".strip()
        if not text:
            return None

        tickers = article.get("tickers", extract_tickers(text))
        if isinstance(tickers, str):
            tickers = [tickers]

        event = InfoEvent(
            source=InfoSource.NEWS,
            event_type=EventType.NEWS_ARTICLE,
            raw_text=text,
            tickers=tickers,
            entities=article.get("entities", tickers),
            author=article.get("source", article.get("provider", "")),
            url=article.get("url", ""),
            timestamp=article.get("published_at", datetime.now(timezone.utc)),
            metadata={
                "provider": article.get("provider", ""),
                "event_type": article.get("event_type", ""),
                "sentiment_score": article.get("sentiment_score"),
                "novelty_score": article.get("novelty_score"),
                "relevance_score": article.get("relevance_score"),
            },
        )
        pushed = self._buffer.push(event)
        if pushed:
            self._ingested_count += 1
        return event if pushed else None

    def ingest_batch(self, articles: List[Dict[str, Any]]) -> int:
        """Ingest a batch of articles. Returns count of new events."""
        count = 0
        for a in articles:
            if self.ingest_article(a):
                count += 1
        return count

    @property
    def buffer(self) -> EventBuffer:
        return self._buffer

    def summary(self) -> dict:
        return {
            "worker": "news",
            "sources": self._sources,
            "ingested_count": self._ingested_count,
            "buffer_size": self._buffer.size,
        }


# ── Module-level shared buffer ───────────────────────────────────────

_ingester: Optional[SignalIngester] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_event_buffer() -> EventBuffer:
    global _buffer
    if _buffer is None:
        _buffer = EventBuffer()
    return _buffer
