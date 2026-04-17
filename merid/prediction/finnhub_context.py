"""E2-E4: Finnhub Context — Economic Calendar + News Sentiment

Replaces the BLS heuristic release calendar with Finnhub's live economic
calendar (exact dates, impact levels, consensus estimates, actuals) and
adds a market-wide news sentiment signal for SPY and BTC.

Environment
-----------
FINNHUB_API_KEY  — from https://finnhub.io/dashboard  (already set in .env)

Key endpoints used
------------------
  /calendar/economic   — upcoming US macro releases with impact/estimate/actual
  /news-sentiment      — bull/bear percent + buzz score for a symbol
  /market-news         — general market headlines for sentiment scoring
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_FINNHUB_KEY  = os.getenv("FINNHUB_API_KEY", "")
_BASE         = "https://finnhub.io/api/v1"
_CALENDAR_URL = _BASE + "/calendar/economic"
_SENTIMENT_URL = _BASE + "/news-sentiment"
_NEWS_URL      = _BASE + "/market-news?category=general"

_CACHE_TTL  = 600.0    # 10-minute cache — calendar and sentiment stable
_HIGH_IMPACT = {"high", "High", "HIGH"}


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class EconomicRelease:
    event: str           # e.g. "CPI YoY"
    release_time: str    # ISO datetime string
    impact: str          # "high" | "medium" | "low"
    country: str         # "US"
    estimate: Optional[float]
    prev: Optional[float]
    actual: Optional[float]
    days_away: float     # can be fractional (hours matter)

    @property
    def is_surprise(self) -> bool:
        """True when actual differs from estimate by >0.1 (after release)."""
        if self.actual is None or self.estimate is None:
            return False
        return abs(self.actual - self.estimate) > 0.1

    @property
    def surprise_direction(self) -> float:
        """Positive = hotter-than-expected, negative = cooler."""
        if self.actual is None or self.estimate is None:
            return 0.0
        return self.actual - self.estimate


@dataclass
class SentimentScore:
    symbol: str
    bullish_pct: float = 0.5
    bearish_pct: float = 0.5
    buzz_score: float  = 0.0   # 0–1, relative article volume vs 4-week avg
    news_score: float  = 0.5   # 0–1, overall positive/negative news tone
    articles_last_week: int = 0


@dataclass
class FinnhubContextSnapshot:
    releases: List[EconomicRelease] = field(default_factory=list)
    sentiment: Dict[str, SentimentScore] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    # ── Convenience queries ─────────────────────────────────────────────────

    def high_impact_within_days(self, days: float = 1.0) -> List[EconomicRelease]:
        """US high-impact releases within ±days of now."""
        return [
            r for r in self.releases
            if r.country == "US"
            and r.impact in _HIGH_IMPACT
            and abs(r.days_away) <= days
        ]

    def nearest_high_impact_days(self) -> float:
        """Days until the next US high-impact release (99 if none)."""
        upcoming = [r for r in self.releases if r.country == "US"
                    and r.impact in _HIGH_IMPACT and r.days_away >= 0]
        if not upcoming:
            return 99.0
        return min(r.days_away for r in upcoming)

    def get_sentiment(self, symbol: str) -> SentimentScore:
        return self.sentiment.get(symbol.upper(), SentimentScore(symbol=symbol))

    def recent_surprise(self) -> float:
        """Aggregate surprise direction of the latest released high-impact events.

        Positive = hotter-than-expected macro (hawkish), negative = cooler.
        """
        released = [
            r for r in self.releases
            if r.country == "US" and r.impact in _HIGH_IMPACT
            and r.actual is not None and r.days_away >= -3
        ]
        if not released:
            return 0.0
        total = sum(r.surprise_direction for r in released)
        return round(total / len(released), 4)

    # ── Feature dicts ───────────────────────────────────────────────────────

    def to_edge_features(self, crypto_symbol: str = "BTC") -> Dict[str, float]:
        nearest = self.nearest_high_impact_days()
        surprise = self.recent_surprise()
        spy_sent = self.get_sentiment("SPY")
        crypto_sent = self.get_sentiment(crypto_symbol)
        return {
            "fh_nearest_release_days":  min(nearest, 99.0),
            "fh_macro_surprise":        surprise,
            "fh_spy_bullish_pct":       spy_sent.bullish_pct,
            "fh_spy_news_score":        spy_sent.news_score,
            "fh_spy_buzz":              spy_sent.buzz_score,
            "fh_crypto_bullish_pct":    crypto_sent.bullish_pct,
            "fh_crypto_news_score":     crypto_sent.news_score,
            "fh_high_impact_imminent":  float(nearest <= 1.0),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "high_impact_imminent": self.high_impact_within_days(1.0),
            "nearest_release_days": self.nearest_high_impact_days(),
            "recent_surprise": self.recent_surprise(),
            "releases": [
                {
                    "event": r.event, "time": r.release_time,
                    "impact": r.impact, "days_away": round(r.days_away, 2),
                    "estimate": r.estimate, "actual": r.actual,
                    "surprise": r.surprise_direction if r.actual else None,
                }
                for r in self.releases[:20]
            ],
            "sentiment": {
                sym: {
                    "bullish_pct": s.bullish_pct, "bearish_pct": s.bearish_pct,
                    "buzz_score": s.buzz_score, "news_score": s.news_score,
                }
                for sym, s in self.sentiment.items()
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get(url: str, params: Optional[Dict] = None) -> Any:
    import httpx
    p = params or {}
    if _FINNHUB_KEY:
        p["token"] = _FINNHUB_KEY
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, params=p)
        resp.raise_for_status()
        return resp.json()


async def _fetch_economic_calendar(
    from_date: date, to_date: date
) -> List[EconomicRelease]:
    try:
        raw = await _get(_CALENDAR_URL, {
            "from": from_date.isoformat(),
            "to":   to_date.isoformat(),
        })
        now_utc = datetime.now(timezone.utc)
        releases: List[EconomicRelease] = []
        for item in raw.get("economicCalendar", []):
            if item.get("country") != "US":
                continue
            try:
                rel_dt = datetime.fromisoformat(item["time"].replace(" ", "T"))
                if rel_dt.tzinfo is None:
                    rel_dt = rel_dt.replace(tzinfo=timezone.utc)
                days_away = (rel_dt - now_utc).total_seconds() / 86400.0
            except (KeyError, ValueError):
                continue

            releases.append(EconomicRelease(
                event=item.get("event", ""),
                release_time=item.get("time", ""),
                impact=item.get("impact", "low"),
                country="US",
                estimate=_float_or_none(item.get("estimate")),
                prev=_float_or_none(item.get("prev")),
                actual=_float_or_none(item.get("actual")),
                days_away=days_away,
            ))
        return sorted(releases, key=lambda r: r.days_away)
    except Exception as exc:
        logger.debug("finnhub: economic calendar fetch failed: %s", exc)
        return []


async def _fetch_sentiment(symbol: str) -> SentimentScore:
    try:
        raw = await _get(_SENTIMENT_URL, {"symbol": symbol})
        sent = raw.get("sentiment", {})
        buzz = raw.get("buzz", {})
        return SentimentScore(
            symbol=symbol,
            bullish_pct=float(sent.get("bullishPercent", 0.5)),
            bearish_pct=float(sent.get("bearishPercent", 0.5)),
            buzz_score=float(buzz.get("buzz", 0.0)),
            news_score=float(raw.get("companyNewsScore", 0.5)),
            articles_last_week=int(buzz.get("articlesInLastWeek", 0)),
        )
    except Exception as exc:
        logger.debug("finnhub: sentiment fetch failed for %s: %s", symbol, exc)
        return SentimentScore(symbol=symbol)


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Service class ──────────────────────────────────────────────────────────────

class FinnhubContextService:
    """Fetches and caches Finnhub economic calendar + news sentiment."""

    def __init__(self) -> None:
        self._cache: Optional[FinnhubContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> FinnhubContextSnapshot:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        async with self._lock:
            if not force and self._cache and (time.time() - self._cache_ts) < _CACHE_TTL:
                return self._cache
            snap = await self._fetch()
            self._cache = snap
            self._cache_ts = time.time()
            return snap

    async def _fetch(self) -> FinnhubContextSnapshot:
        import asyncio
        if not _FINNHUB_KEY:
            return FinnhubContextSnapshot(source="stub")

        today = date.today()
        from_d = today - timedelta(days=3)
        to_d   = today + timedelta(days=14)

        try:
            releases, spy_sent, btc_sent = await asyncio.gather(
                _fetch_economic_calendar(from_d, to_d),
                _fetch_sentiment("SPY"),
                _fetch_sentiment("BINANCE:BTCUSDT"),
                return_exceptions=True,
            )
            if isinstance(releases, Exception):
                releases = []
            if isinstance(spy_sent, Exception):
                spy_sent = SentimentScore(symbol="SPY")
            if isinstance(btc_sent, Exception):
                btc_sent = SentimentScore(symbol="BINANCE:BTCUSDT")

            real_data = bool(releases) and not isinstance(releases, Exception)
            snap = FinnhubContextSnapshot(
                releases=releases,
                sentiment={"SPY": spy_sent, "BTC": btc_sent},
                source="live" if real_data else "stub",
            )
            logger.debug(
                "finnhub: %d releases loaded, nearest_high_impact=%.1fd, "
                "SPY bullish=%.2f, BTC bullish=%.2f",
                len(releases), snap.nearest_high_impact_days(),
                spy_sent.bullish_pct, btc_sent.bullish_pct,
            )
            return snap
        except Exception as exc:
            logger.warning("finnhub: context fetch failed (%s) — stub", exc)
            return FinnhubContextSnapshot(source="stub")


# ── Singleton ──────────────────────────────────────────────────────────────────

_service: Optional[FinnhubContextService] = None
_svc_lock = Lock()


def get_finnhub_context_service() -> FinnhubContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = FinnhubContextService()
    return _service
