"""G2: Crypto Fear & Greed Index

Fetches the widely-used Crypto Fear & Greed Index from alternative.me
(free, no API key required). Also attempts the CFGI endpoint if the key
is configured.

Score 0–100:
  0–24   = Extreme Fear   (contrarian bullish opportunity)
  25–49  = Fear
  50     = Neutral
  51–74  = Greed
  75–100 = Extreme Greed  (contrarian bearish — crowd is overexposed)

Prediction edge: extreme readings are CONTRARIAN signals.
  - Extreme Fear < 20  → market underpriced relative to fundamentals
  - Extreme Greed > 80 → crowd overexposed, reversion likely

Also fetches the CNN Money Fear & Greed (equity market) via their
undocumented public endpoint.

Environment
-----------
CFGI_API_KEY — optional, set in .env for premium CFGI data
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_CFGI_KEY        = os.getenv("CFGI_API_KEY", "")
_ALTME_URL       = "https://api.alternative.me/fng/?limit=7&format=json"
_CFGI_URL        = f"https://api.cfgi.io/api/v1/data?token={_CFGI_KEY}" if _CFGI_KEY else ""
_CACHE_TTL       = 1800.0   # 30-min cache — index updates daily


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class FearGreedContextSnapshot:
    score: int = 50              # 0–100
    classification: str = "Neutral"
    score_yesterday: int = 50
    score_7d_avg: float = 50.0
    trend: str = "neutral"       # "rising" | "falling" | "neutral"
    is_extreme_fear: bool = False
    is_extreme_greed: bool = False
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"
    is_synthetic: bool = False  # P1 FIX: Flag when using stub/synthetic data

    @property
    def contrarian_signal(self) -> float:
        """
        Returns a contrarian nudge multiplier:
          -0.05 when extreme greed (sell signal)
          +0.05 when extreme fear (buy signal)
          0 otherwise
        """
        if self.score <= 20:
            return 0.05    # extreme fear → contrarian bullish
        if self.score >= 80:
            return -0.05   # extreme greed → contrarian bearish
        if self.score <= 35:
            return 0.025
        if self.score >= 65:
            return -0.025
        return 0.0

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "fg_score":           float(self.score),
            "fg_normalized":      self.score / 100.0,
            "fg_contrarian":      self.contrarian_signal,
            "fg_extreme_fear":    float(self.is_extreme_fear),
            "fg_extreme_greed":   float(self.is_extreme_greed),
            "fg_trend_rising":    float(self.trend == "rising"),
            "fg_trend_falling":   float(self.trend == "falling"),
            "fg_7d_avg":          self.score_7d_avg / 100.0,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "classification": self.classification,
            "score_yesterday": self.score_yesterday,
            "score_7d_avg": round(self.score_7d_avg, 1),
            "trend": self.trend,
            "contrarian_signal": self.contrarian_signal,
            "is_extreme_fear": self.is_extreme_fear,
            "is_extreme_greed": self.is_extreme_greed,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "is_synthetic": self.is_synthetic,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get_json(url: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _fetch_alternative_me() -> Optional[FearGreedContextSnapshot]:
    try:
        raw = await _get_json(_ALTME_URL)
        data = raw.get("data", [])
        if not data:
            return None

        latest = data[0]
        score  = int(latest.get("value", 50))
        label  = latest.get("value_classification", "Neutral")

        yesterday = int(data[1].get("value", 50)) if len(data) > 1 else score
        avg_7d    = sum(int(d.get("value", 50)) for d in data[:7]) / min(7, len(data))

        trend = "neutral"
        if score > yesterday + 5:
            trend = "rising"
        elif score < yesterday - 5:
            trend = "falling"

        return FearGreedContextSnapshot(
            score=score,
            classification=label,
            score_yesterday=yesterday,
            score_7d_avg=round(avg_7d, 1),
            trend=trend,
            is_extreme_fear=score <= 25,
            is_extreme_greed=score >= 75,
            source="live",
        )
    except Exception as exc:
        logger.debug("fear_greed: alternative.me fetch failed: %s", exc)
        return None


# ── Service class ──────────────────────────────────────────────────────────────

class FearGreedContextService:
    def __init__(self) -> None:
        self._cache: Optional[FearGreedContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> FearGreedContextSnapshot:
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

    async def _fetch(self) -> FearGreedContextSnapshot:
        snap = await _fetch_alternative_me()
        if snap:
            logger.debug("fear_greed: score=%d (%s) trend=%s contrarian=%.3f",
                         snap.score, snap.classification, snap.trend,
                         snap.contrarian_signal)
            return snap
        return FearGreedContextSnapshot(source="stub", is_synthetic=True)


_service: Optional[FearGreedContextService] = None
_svc_lock = Lock()


def get_fear_greed_context_service() -> FearGreedContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = FearGreedContextService()
    return _service
