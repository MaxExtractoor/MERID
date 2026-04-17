"""F2: Google Trends Context — Search Spike Detection

Uses the unofficial Google Trends API (pytrends) to detect search interest
spikes for key market terms. A spike in "CPI" searches the day before a
release signals heightened attention / expected volatility. A spike in
"bitcoin crash" is a sentiment indicator.

No API key required. Falls back gracefully if pytrends not installed or
if Google rate-limits the request.

Keyword groups tracked
----------------------
  macro   — "CPI", "inflation", "federal reserve", "interest rate"
  crypto  — "bitcoin", "ethereum", "crypto crash", "bitcoin price"
  risk    — "stock market crash", "recession", "bear market"
  event   — "FOMC", "nonfarm payrolls", "earnings"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL = 3600.0   # Trends data changes slowly; 1-hour cache

_KEYWORD_GROUPS: Dict[str, List[str]] = {
    "macro":  ["CPI", "inflation", "federal reserve", "interest rate"],
    "crypto": ["bitcoin", "ethereum", "crypto", "bitcoin price"],
    "risk":   ["stock market crash", "recession", "bear market"],
    "event":  ["FOMC", "nonfarm payrolls", "NFP"],
}

_SPIKE_THRESHOLD = 70   # score > 70/100 in the last period = notable spike


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class TrendScore:
    keyword: str
    current_score: int    # 0–100 (Google Trends relative interest)
    avg_score: float      # average over the fetched window
    spike: bool           # current > threshold AND current > 1.5x average
    spike_magnitude: float  # current / avg  (1.0 = normal)


@dataclass
class TrendsContextSnapshot:
    groups: Dict[str, List[TrendScore]] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    def group_spike_score(self, group: str) -> float:
        """Max spike_magnitude in a keyword group (1.0 = no spike)."""
        scores = self.groups.get(group, [])
        if not scores:
            return 1.0
        return max(s.spike_magnitude for s in scores)

    def any_spike_in(self, group: str, threshold: float = 1.5) -> bool:
        return self.group_spike_score(group) >= threshold

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "trends_macro_spike":    self.group_spike_score("macro"),
            "trends_crypto_spike":   self.group_spike_score("crypto"),
            "trends_risk_spike":     self.group_spike_score("risk"),
            "trends_event_spike":    self.group_spike_score("event"),
            "trends_any_macro":      float(self.any_spike_in("macro")),
            "trends_any_crypto":     float(self.any_spike_in("crypto")),
            "trends_any_risk":       float(self.any_spike_in("risk")),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "groups": {
                grp: [
                    {"keyword": s.keyword, "score": s.current_score,
                     "spike": s.spike, "magnitude": round(s.spike_magnitude, 2)}
                    for s in scores
                ]
                for grp, scores in self.groups.items()
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _fetch_group(group: str, keywords: List[str]) -> List[TrendScore]:
    """Fetch Google Trends for a keyword group using pytrends."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()

        def _blocking():
            from pytrends.request import TrendReq
            pt = TrendReq(hl="en-US", tz=300, timeout=(5, 10),
                          retries=1, backoff_factor=0.5)
            pt.build_payload(keywords[:5], timeframe="now 7-d", geo="US")
            df = pt.interest_over_time()
            return df

        df = await loop.run_in_executor(None, _blocking)

        if df is None or df.empty:
            return []

        scores: List[TrendScore] = []
        for kw in keywords:
            if kw not in df.columns:
                continue
            series = df[kw].dropna()
            if series.empty:
                continue
            current = int(series.iloc[-1])
            avg     = float(series.mean())
            mag     = (current / avg) if avg > 0 else 1.0
            scores.append(TrendScore(
                keyword=kw,
                current_score=current,
                avg_score=round(avg, 1),
                spike=current >= _SPIKE_THRESHOLD and mag >= 1.5,
                spike_magnitude=round(mag, 3),
            ))
        return scores

    except ImportError:
        logger.debug("trends: pytrends not installed — stub")
        return []
    except Exception as exc:
        logger.debug("trends: %s group fetch failed: %s", group, exc)
        return []


# ── Service class ──────────────────────────────────────────────────────────────

class TrendsContextService:
    def __init__(self) -> None:
        self._cache: Optional[TrendsContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> TrendsContextSnapshot:
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

    async def _fetch(self) -> TrendsContextSnapshot:
        import asyncio
        try:
            results = await asyncio.gather(
                *[_fetch_group(g, kws) for g, kws in _KEYWORD_GROUPS.items()],
                return_exceptions=True,
            )
            groups: Dict[str, List[TrendScore]] = {}
            for (group, _), result in zip(_KEYWORD_GROUPS.items(), results):
                if isinstance(result, list):
                    groups[group] = result
                else:
                    groups[group] = []
            has_data = any(bool(v) for v in groups.values())
            snap = TrendsContextSnapshot(
                groups=groups,
                source="live" if has_data else "stub",
            )
            if has_data:
                logger.debug(
                    "trends: macro_spike=%.2f crypto_spike=%.2f risk_spike=%.2f",
                    snap.group_spike_score("macro"),
                    snap.group_spike_score("crypto"),
                    snap.group_spike_score("risk"),
                )
            return snap
        except Exception as exc:
            logger.warning("trends: context fetch failed (%s) — stub", exc)
            return TrendsContextSnapshot(source="stub")


_service: Optional[TrendsContextService] = None
_svc_lock = Lock()


def get_trends_context_service() -> TrendsContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = TrendsContextService()
    return _service
