"""D4: Metaculus Calibration Prior

Fetches resolved Metaculus questions that overlap with Kalshi market categories
and uses the community probability as a Bayesian calibration prior.

Metaculus is one of the best-calibrated public prediction aggregators.
Using their resolved track record to set priors for overlapping categories
(Fed rate, CPI, election, crypto) gives the EdgeModel a statistically grounded
baseline before any market-specific signals fire.

API docs: https://www.metaculus.com/api2/  (no key required)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL   = 3600.0   # community probabilities are stable; refresh hourly
_META_BASE   = "https://www.metaculus.com/api2"
_SEARCH_URL  = _META_BASE + "/questions/?status=resolved&order_by=-resolution_date&limit={limit}&search={query}"
_OPEN_URL    = _META_BASE + "/questions/?status=open&order_by=-last_activity_time&limit=20&search={query}"

# Map Kalshi category names → Metaculus search queries
_CATEGORY_QUERIES: Dict[str, str] = {
    "crypto":    "bitcoin price",
    "fed":       "federal reserve rate",
    "cpi":       "inflation CPI",
    "economy":   "GDP recession",
    "election":  "election",
    "weather":   "hurricane",
    "sports":    "championship",
}


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class MetaculusQuestion:
    id: int
    title: str
    category: str
    community_prob: float     # last community forecast (0–1)
    resolution: Optional[float]  # 1.0 = YES, 0.0 = NO, None = unresolved
    resolution_date: str
    num_predictions: int


@dataclass
class CategoryPrior:
    """Aggregated calibration prior for one market category."""
    category: str
    n_resolved: int
    mean_community_prob: float    # average community probability at resolution
    resolution_rate: float        # fraction that resolved YES
    calibration_error: float      # |mean_community_prob - resolution_rate|
    open_questions: List[MetaculusQuestion] = field(default_factory=list)

    @property
    def prior_prob(self) -> float:
        """Best prior estimate for a new question in this category."""
        if self.n_resolved == 0:
            return 0.5
        # Blend: mostly resolution rate, nudged by community prob calibration
        return round(0.7 * self.resolution_rate + 0.3 * self.mean_community_prob, 4)


@dataclass
class MetaculusContextSnapshot:
    priors: Dict[str, CategoryPrior] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    def get_prior(self, category: str) -> float:
        """Return prior probability for a category (0.5 default)."""
        p = self.priors.get(category)
        return p.prior_prob if p else 0.5

    def to_edge_features(self, category: str) -> Dict[str, float]:
        p = self.priors.get(category)
        return {
            f"metaculus_{category}_prior": self.get_prior(category),
            f"metaculus_{category}_cal_error": p.calibration_error if p else 0.0,
            f"metaculus_{category}_n": float(p.n_resolved if p else 0),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priors": {
                cat: {
                    "prior_prob": p.prior_prob,
                    "n_resolved": p.n_resolved,
                    "resolution_rate": p.resolution_rate,
                    "calibration_error": p.calibration_error,
                }
                for cat, p in self.priors.items()
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _fetch_json(url: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


async def _fetch_category_prior(category: str, query: str) -> CategoryPrior:
    """Fetch resolved questions for one category and compute a calibration prior."""
    try:
        raw = await _fetch_json(_SEARCH_URL.format(limit=50, query=query))
        questions = raw.get("results", [])

        resolved: List[Tuple[float, float]] = []   # (community_prob, resolution)
        for q in questions:
            # community_prob is in q["community_prediction"]["full"]["q2"] (median)
            cp_block = q.get("community_prediction") or {}
            full = cp_block.get("full") or {}
            q2 = full.get("q2")
            resolution = q.get("resolution")
            if q2 is None or resolution not in (0.0, 1.0, True, False):
                continue
            resolved.append((float(q2), float(resolution)))

        if not resolved:
            return CategoryPrior(category=category, n_resolved=0,
                                 mean_community_prob=0.5, resolution_rate=0.5,
                                 calibration_error=0.0)

        n = len(resolved)
        mean_cp    = sum(r[0] for r in resolved) / n
        res_rate   = sum(r[1] for r in resolved) / n
        cal_error  = abs(mean_cp - res_rate)

        # Also fetch a few open questions for awareness
        open_qs: List[MetaculusQuestion] = []
        try:
            open_raw = await _fetch_json(_OPEN_URL.format(query=query))
            for q in open_raw.get("results", [])[:5]:
                cp_block = q.get("community_prediction") or {}
                q2 = (cp_block.get("full") or {}).get("q2") or 0.5
                open_qs.append(MetaculusQuestion(
                    id=q.get("id", 0),
                    title=q.get("title", "")[:80],
                    category=category,
                    community_prob=round(float(q2), 3),
                    resolution=None,
                    resolution_date="",
                    num_predictions=q.get("number_of_predictions", 0),
                ))
        except Exception as _mc_exc:
            logger.debug("Metaculus question parsing failed for category %s: %s", category, _mc_exc)

        return CategoryPrior(
            category=category,
            n_resolved=n,
            mean_community_prob=round(mean_cp, 4),
            resolution_rate=round(res_rate, 4),
            calibration_error=round(cal_error, 4),
            open_questions=open_qs,
        )

    except Exception as exc:
        logger.debug("metaculus: %s fetch failed: %s", category, exc)
        return CategoryPrior(category=category, n_resolved=0,
                             mean_community_prob=0.5, resolution_rate=0.5,
                             calibration_error=0.0)


# ── Service class ──────────────────────────────────────────────────────────────

class MetaculusContextService:
    """Fetches and caches Metaculus calibration priors per category."""

    def __init__(self) -> None:
        self._cache: Optional[MetaculusContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> MetaculusContextSnapshot:
        import asyncio
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

    async def _fetch(self) -> MetaculusContextSnapshot:
        import asyncio
        try:
            tasks = [
                _fetch_category_prior(cat, query)
                for cat, query in _CATEGORY_QUERIES.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            priors: Dict[str, CategoryPrior] = {}
            for cat, result in zip(_CATEGORY_QUERIES.keys(), results):
                if isinstance(result, CategoryPrior):
                    priors[cat] = result
                    logger.debug(
                        "metaculus: %s prior=%.3f n=%d cal_err=%.3f",
                        cat, result.prior_prob, result.n_resolved, result.calibration_error,
                    )
            return MetaculusContextSnapshot(priors=priors, source="live" if priors else "stub")
        except Exception as exc:
            logger.warning("metaculus: context fetch failed (%s) — stub", exc)
            return MetaculusContextSnapshot(source="stub")


# ── Singleton ──────────────────────────────────────────────────────────────────

_service: Optional[MetaculusContextService] = None
_svc_lock = Lock()


def get_metaculus_context_service() -> MetaculusContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = MetaculusContextService()
    return _service
