"""§3 Processing — NLP/sentiment, feature extraction, spike detection.

Turns raw InfoEvents into SentimentFeatures and detects SentimentSpikes.
"""

from __future__ import annotations

import threading
import re
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from merid.signals.events import (
    InfoEvent,
    InfoSource,
    SentimentFeature,
    SentimentSpike,
    SentimentWindow,
)

from utils.logger import get_logger

logger = get_logger("merid.signals.processing")


# ── Simple keyword-based sentiment (production: use LLM or FinBERT) ──

_BULLISH_WORDS = {
    "bullish", "moon", "pump", "rally", "breakout", "surge", "soar",
    "buy", "long", "upgrade", "beat", "outperform", "growth", "profit",
    "partnership", "launch", "adoption", "approval", "record",
}
_BEARISH_WORDS = {
    "bearish", "dump", "crash", "plunge", "sell", "short", "downgrade",
    "miss", "underperform", "loss", "hack", "exploit", "rug", "scam",
    "delisting", "ban", "lawsuit", "sec", "fraud", "liquidation",
}
_HIGH_RELEVANCE_WORDS = {
    "breaking", "urgent", "alert", "just in", "confirmed", "official",
    "sec", "fed", "fomc", "cpi", "gdp", "earnings", "ipo",
}


def _simple_sentiment(text: str) -> tuple[float, float, float, float]:
    """Return (polarity, magnitude, relevance, actionability) from text.

    Simple keyword approach. In production, replace with FinBERT or LLM.
    """
    words = set(re.findall(r"\b\w+\b", text.lower()))
    bull = len(words & _BULLISH_WORDS)
    bear = len(words & _BEARISH_WORDS)
    total = bull + bear

    if total == 0:
        polarity = 0.0
        magnitude = 0.0
    else:
        polarity = (bull - bear) / total
        magnitude = min(1.0, total / 5.0)

    relevance_hits = len(words & _HIGH_RELEVANCE_WORDS)
    relevance = min(1.0, relevance_hits / 2.0)
    actionability = min(1.0, (magnitude + relevance) / 2.0)

    return polarity, magnitude, relevance, actionability


# ── SentimentProcessor ───────────────────────────────────────────────

class SentimentProcessor:
    """Processes InfoEvents into SentimentFeatures.

    Maintains a feature store (in-memory; Mongo in production) for
    per-ticker sentiment aggregation and spike detection.
    """

    _MAX_FEATURES = 10000
    _MAX_BY_TICKER = 2000
    _MAX_SPIKES = 10000

    def __init__(self, spike_threshold: float = 0.5):
        self.spike_threshold = spike_threshold
        self._features: List[SentimentFeature] = []
        self._spikes: List[SentimentSpike] = []
        self._by_ticker: Dict[str, List[SentimentFeature]] = defaultdict(list)

    # ── Process single event ─────────────────────────────────────────

    def process_event(self, event: InfoEvent) -> List[SentimentFeature]:
        """Extract sentiment features from an InfoEvent.

        Returns one SentimentFeature per ticker mentioned.
        """
        # Use pre-computed sentiment from metadata if available (e.g., RavenPack)
        meta_sentiment = event.metadata.get("sentiment_score")
        meta_relevance = event.metadata.get("relevance_score")

        if meta_sentiment is not None:
            polarity = float(meta_sentiment)
            magnitude = abs(polarity)
            relevance = float(meta_relevance or 0.5)
            actionability = min(1.0, (magnitude + relevance) / 2.0)
        else:
            polarity, magnitude, relevance, actionability = _simple_sentiment(event.raw_text)

        # Topic tags from event type metadata
        topic_tags = []
        if event.metadata.get("event_type"):
            topic_tags.append(event.metadata["event_type"])

        tickers = event.tickers or ["GENERAL"]
        features = []
        for ticker in tickers:
            feat = SentimentFeature(
                event_id=event.event_id,
                source=event.source,
                ticker=ticker,
                polarity=polarity,
                magnitude=magnitude,
                relevance=relevance,
                actionability=actionability,
                topic_tags=topic_tags,
                timestamp=event.timestamp,
            )
            self._features.append(feat)
            if len(self._features) > self._MAX_FEATURES:
                self._features = self._features[-self._MAX_FEATURES :]
            self._by_ticker[ticker].append(feat)
            if len(self._by_ticker[ticker]) > self._MAX_BY_TICKER:
                self._by_ticker[ticker] = self._by_ticker[ticker][
                    -self._MAX_BY_TICKER :
                ]
            features.append(feat)

        return features

    def process_batch(self, events: List[InfoEvent]) -> List[SentimentFeature]:
        """Process a batch of events."""
        all_features = []
        for event in events:
            all_features.extend(self.process_event(event))
        return all_features

    # ── Aggregation ──────────────────────────────────────────────────

    def get_window(
        self,
        ticker: str,
        window_minutes: int = 15,
        as_of: Optional[datetime] = None,
    ) -> SentimentWindow:
        """Get aggregated sentiment for a ticker over a time window."""
        as_of = as_of or datetime.now(timezone.utc)
        since = as_of - timedelta(minutes=window_minutes)

        features = [
            f for f in self._by_ticker.get(ticker, [])
            if f.timestamp >= since
        ]

        if not features:
            return SentimentWindow(ticker=ticker, window=f"{window_minutes}m")

        avg_pol = sum(f.polarity for f in features) / len(features)
        avg_mag = sum(f.magnitude for f in features) / len(features)
        x_count = sum(1 for f in features if f.source == InfoSource.X)
        news_count = sum(1 for f in features if f.source == InfoSource.NEWS)
        tg_count = sum(1 for f in features if f.source == InfoSource.TELEGRAM)

        return SentimentWindow(
            ticker=ticker,
            window=f"{window_minutes}m",
            window_start=since,
            window_end=as_of,
            avg_polarity=avg_pol,
            avg_magnitude=avg_mag,
            sample_count=len(features),
            x_count=x_count,
            news_count=news_count,
            telegram_count=tg_count,
        )

    # ── Spike detection ──────────────────────────────────────────────

    def detect_spikes(
        self,
        ticker: str,
        short_window_minutes: int = 15,
        long_window_minutes: int = 360,
        min_short_count: int = 3,
        min_long_count: int = 10,
    ) -> Optional[SentimentSpike]:
        """Detect sentiment spike: short-term vs long-term divergence."""
        short = self.get_window(ticker, short_window_minutes)
        long = self.get_window(ticker, long_window_minutes)

        if short.sample_count < min_short_count or long.sample_count < min_long_count:
            return None

        delta = short.avg_polarity - long.avg_polarity
        if abs(delta) < self.spike_threshold:
            return None

        direction = "bullish" if delta > 0 else "bearish"
        spike = SentimentSpike(
            ticker=ticker,
            source="combined",
            short_window_avg=short.avg_polarity,
            long_window_avg=long.avg_polarity,
            delta=delta,
            short_window_count=short.sample_count,
            long_window_count=long.sample_count,
            direction=direction,
        )
        self._spikes.append(spike)
        if len(self._spikes) > self._MAX_SPIKES:
            self._spikes = self._spikes[-self._MAX_SPIKES :]
        logger.info(f"Sentiment spike detected: {ticker} {direction} delta={delta:.4f}")
        return spike

    def detect_all_spikes(self) -> List[SentimentSpike]:
        """Run spike detection for all tracked tickers."""
        spikes = []
        for ticker in self._by_ticker:
            spike = self.detect_spikes(ticker)
            if spike:
                spikes.append(spike)
        return spikes

    # ── Accessors ────────────────────────────────────────────────────

    def get_features(self, ticker: Optional[str] = None, limit: int = 100) -> List[SentimentFeature]:
        if ticker:
            return self._by_ticker.get(ticker, [])[-limit:]
        return self._features[-limit:]

    def get_spikes(self, limit: int = 50) -> List[SentimentSpike]:
        return self._spikes[-limit:]

    def get_tracked_tickers(self) -> List[str]:
        return sorted(self._by_ticker.keys())

    def summary(self) -> dict:
        return {
            "total_features": len(self._features),
            "total_spikes": len(self._spikes),
            "tracked_tickers": len(self._by_ticker),
            "tickers": self.get_tracked_tickers(),
        }


# ── Module singleton ─────────────────────────────────────────────────

_processor: Optional[SentimentProcessor] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _processor_lock = threading.Lock()
_processor_lock = None  # Disabled to prevent startup hang


def get_sentiment_processor() -> SentimentProcessor:
    global _processor
    if _processor is None:
        if _processor_lock is not None:
            with _processor_lock:
                if _processor is None:
                    _processor = SentimentProcessor()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _processor = SentimentProcessor()
    return _processor
