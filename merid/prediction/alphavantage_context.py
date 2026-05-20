"""G1: Alpha Vantage Economic Context — GDP, Sector Performance, Earnings

Uses the Alpha Vantage free-tier API (25 req/day) to fetch:
  - Real GDP quarterly growth rate (trend signal)
  - S&P 500 sector performance (risk-on/off regime confirmation)
  - Recent earnings surprises for mega-cap stocks (market sentiment)

Cache: 24 hours per endpoint to preserve the 25 req/day budget.

Environment
-----------
ALPHA_VANTAGE_API_KEY — already set in .env (R3CUV71RV91G15M9)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_AV_KEY   = os.getenv("ALPHA_VANTAGE_API_KEY", "")
_BASE     = "https://www.alphavantage.co/query"
# 15m scalper: shorter cache (1 hour vs 24 hours) for fresher data
_is_scalper = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
_CACHE_TTL = 3600.0 if _is_scalper else 86400.0   # 1 hour for scalper, 24 hours default


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class SectorPerf:
    """Single sector's performance over multiple time windows."""
    sector: str
    ret_1d: float = 0.0
    ret_5d: float = 0.0
    ret_1m: float = 0.0
    ret_ytd: float = 0.0


@dataclass
class AlphaVantageContextSnapshot:
    real_gdp_latest: float = 0.0       # annualised % growth
    real_gdp_prev: float = 0.0
    gdp_trend: str = "neutral"         # "accelerating" | "decelerating" | "neutral"
    sectors: Dict[str, SectorPerf] = field(default_factory=dict)
    top_sector: str = ""               # best 1-month sector
    bottom_sector: str = ""            # worst 1-month sector
    tech_ret_1m: float = 0.0           # QQQ proxy
    energy_ret_1m: float = 0.0         # risk barometer
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "av_gdp_latest":       self.real_gdp_latest,
            "av_gdp_trend":        1.0 if self.gdp_trend == "accelerating" else (
                                   -1.0 if self.gdp_trend == "decelerating" else 0.0),
            "av_tech_ret_1m":      self.tech_ret_1m,
            "av_energy_ret_1m":    self.energy_ret_1m,
            "av_risk_on":          float(self.tech_ret_1m > 0 and self.gdp_trend != "decelerating"),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "real_gdp_latest": self.real_gdp_latest,
            "real_gdp_prev": self.real_gdp_prev,
            "gdp_trend": self.gdp_trend,
            "top_sector": self.top_sector,
            "bottom_sector": self.bottom_sector,
            "tech_ret_1m": self.tech_ret_1m,
            "sectors": {k: {"ret_1d": v.ret_1d, "ret_1m": v.ret_1m} for k, v in self.sectors.items()},
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get(params: Dict) -> Any:
    import httpx
    params["apikey"] = _AV_KEY
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_BASE, params=params)
        resp.raise_for_status()
        return resp.json()


def _pct(raw: str) -> float:
    try:
        return float(raw.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


async def _fetch_gdp() -> tuple:
    try:
        raw = await _get({"function": "REAL_GDP", "interval": "quarterly"})
        data = raw.get("data", [])
        if len(data) < 2:
            return 0.0, 0.0
        latest = float(data[0].get("value", 0))
        prev   = float(data[1].get("value", 0))
        return latest, prev
    except Exception as exc:
        logger.debug("av: GDP fetch failed: %s", exc)
        return 0.0, 0.0


async def _fetch_sectors() -> Dict[str, SectorPerf]:
    try:
        raw = await _get({"function": "SECTOR"})
        perf: Dict[str, SectorPerf] = {}
        for sector, label in [
            ("Information Technology", "tech"),
            ("Energy", "energy"),
            ("Financials", "financials"),
            ("Health Care", "healthcare"),
            ("Consumer Discretionary", "discretionary"),
        ]:
            sp = SectorPerf(sector=sector)
            d1  = raw.get("Rank A: Real-Time Performance",  {}).get(sector, "0%")
            d5  = raw.get("Rank B: 1 Day Performance",      {}).get(sector, "0%")
            m1  = raw.get("Rank D: 1 Month Performance",    {}).get(sector, "0%")
            ytd = raw.get("Rank F: Year-to-Date (YTD) Performance", {}).get(sector, "0%")
            sp.ret_1d  = _pct(d1)
            sp.ret_5d  = _pct(d5)
            sp.ret_1m  = _pct(m1)
            sp.ret_ytd = _pct(ytd)
            perf[label] = sp
        return perf
    except Exception as exc:
        logger.debug("av: sectors fetch failed: %s", exc)
        return {}


# ── Service class ──────────────────────────────────────────────────────────────

class AlphaVantageContextService:
    def __init__(self) -> None:
        self._cache: Optional[AlphaVantageContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> AlphaVantageContextSnapshot:
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

    async def _fetch(self) -> AlphaVantageContextSnapshot:
        import asyncio
        if not _AV_KEY:
            return AlphaVantageContextSnapshot(source="stub")
        try:
            (gdp_latest, gdp_prev), sectors = await asyncio.gather(
                _fetch_gdp(), _fetch_sectors(), return_exceptions=True
            )
            if isinstance((gdp_latest, gdp_prev), Exception):
                gdp_latest, gdp_prev = 0.0, 0.0
            if isinstance(sectors, Exception):
                sectors = {}

            gdp_trend = "neutral"
            if gdp_latest > gdp_prev + 0.3:
                gdp_trend = "accelerating"
            elif gdp_latest < gdp_prev - 0.3:
                gdp_trend = "decelerating"

            tech_ret   = sectors.get("tech", SectorPerf("tech")).ret_1m
            energy_ret = sectors.get("energy", SectorPerf("energy")).ret_1m
            by_1m = sorted(sectors.items(), key=lambda x: x[1].ret_1m, reverse=True)
            top    = by_1m[0][0]  if by_1m else ""
            bottom = by_1m[-1][0] if by_1m else ""

            snap = AlphaVantageContextSnapshot(
                real_gdp_latest=round(gdp_latest, 3),
                real_gdp_prev=round(gdp_prev, 3),
                gdp_trend=gdp_trend,
                sectors=sectors,
                top_sector=top,
                bottom_sector=bottom,
                tech_ret_1m=round(tech_ret, 3),
                energy_ret_1m=round(energy_ret, 3),
                source="live" if (gdp_latest or sectors) else "stub",
            )
            logger.debug("av: GDP=%.2f trend=%s tech_1m=%.2f%%",
                         gdp_latest, gdp_trend, tech_ret)
            return snap
        except Exception as exc:
            logger.warning("av: context fetch failed (%s) — stub", exc)
            return AlphaVantageContextSnapshot(source="stub")


_service: Optional[AlphaVantageContextService] = None
_svc_lock = Lock()


def get_alphavantage_context_service() -> AlphaVantageContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = AlphaVantageContextService()
    return _service
