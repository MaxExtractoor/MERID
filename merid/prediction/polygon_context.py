"""F1: Polygon.io Equity Context — SPY/QQQ momentum + CBOE PCR

Uses the Polygon.io free-tier REST API to measure equity market momentum
(5-day return, above/below 20-day MA, daily range expansion) and fetches
the CBOE put/call ratio from their public CDN (no key required).

High put/call ratio → hedging/fear → risk-off → bearish crypto context.
Strong SPY/QQQ momentum → risk-on → supports crypto YES contracts.

Environment
-----------
POLYGON_API_KEY — already set in .env
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_POLY_KEY   = os.getenv("POLYGON_API_KEY", "")
_POLY_BASE  = "https://api.polygon.io"
_AGGS_URL   = _POLY_BASE + "/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"
_CBOE_PCR   = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_EOD.json"
_CACHE_TTL  = 900.0   # 15 min — equity data changes slowly

_TICKERS = ["SPY", "QQQ", "IWM"]   # broad market ETFs


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class EquityMomentum:
    ticker: str
    latest_close: float = 0.0
    ret_5d: float = 0.0        # 5-day log return
    ret_1d: float = 0.0        # 1-day return
    above_ma20: bool = False   # close > 20-day simple MA
    vol_expansion: float = 0.0 # today range / avg range (1=normal, >1.5=expanded)


@dataclass
class PolygonContextSnapshot:
    equities: Dict[str, EquityMomentum] = field(default_factory=dict)
    put_call_ratio: float = 1.0        # CBOE equity PCR; >1.2 = fear
    spy_ret_5d: float = 0.0
    market_regime: str = "neutral"     # "risk_on" | "risk_off" | "neutral"
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    def _derive_regime(self) -> str:
        spy = self.equities.get("SPY")
        if not spy:
            return "neutral"
        if spy.ret_5d > 0.01 and spy.above_ma20 and self.put_call_ratio < 0.9:
            return "risk_on"
        if spy.ret_5d < -0.01 or not spy.above_ma20 or self.put_call_ratio > 1.2:
            return "risk_off"
        return "neutral"

    def to_edge_features(self) -> Dict[str, float]:
        spy = self.equities.get("SPY", EquityMomentum("SPY"))
        qqq = self.equities.get("QQQ", EquityMomentum("QQQ"))
        return {
            "poly_spy_ret_5d":        spy.ret_5d,
            "poly_spy_ret_1d":        spy.ret_1d,
            "poly_spy_above_ma20":    float(spy.above_ma20),
            "poly_qqq_ret_5d":        qqq.ret_5d,
            "poly_pcr":               self.put_call_ratio,
            "poly_risk_on":           float(self.market_regime == "risk_on"),
            "poly_risk_off":          float(self.market_regime == "risk_off"),
            "poly_vol_expansion_spy": spy.vol_expansion,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_regime": self.market_regime,
            "put_call_ratio": self.put_call_ratio,
            "equities": {
                t: {
                    "ret_5d": e.ret_5d, "ret_1d": e.ret_1d,
                    "above_ma20": e.above_ma20, "latest_close": e.latest_close,
                }
                for t, e in self.equities.items()
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get_json(url: str, params: Optional[Dict] = None) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


async def _fetch_equity(ticker: str, days: int = 25) -> EquityMomentum:
    if not _POLY_KEY:
        return EquityMomentum(ticker)
    to_d   = date.today()
    from_d = to_d - timedelta(days=days + 5)   # buffer for weekends
    url    = _AGGS_URL.format(
        ticker=ticker,
        from_date=from_d.isoformat(),
        to_date=to_d.isoformat(),
    )
    try:
        raw = await _get_json(url, {"adjusted": "true", "sort": "asc", "apiKey": _POLY_KEY})
        bars: List[Dict] = raw.get("results", [])
        if len(bars) < 5:
            return EquityMomentum(ticker)

        closes = [float(b["c"]) for b in bars]
        highs  = [float(b["h"]) for b in bars]
        lows   = [float(b["l"]) for b in bars]
        ranges = [h - l for h, l in zip(highs, lows)]

        latest = closes[-1]
        close_5d_ago = closes[-6] if len(closes) >= 6 else closes[0]
        import math
        ret_5d = math.log(latest / close_5d_ago) if close_5d_ago > 0 else 0.0
        ret_1d = math.log(latest / closes[-2]) if len(closes) >= 2 and closes[-2] > 0 else 0.0
        ma20   = sum(closes[-20:]) / min(20, len(closes))
        avg_rng = sum(ranges[-10:]) / max(1, len(ranges[-10:]))
        vol_exp = (ranges[-1] / avg_rng) if avg_rng > 0 else 1.0

        return EquityMomentum(
            ticker=ticker,
            latest_close=round(latest, 2),
            ret_5d=round(ret_5d, 5),
            ret_1d=round(ret_1d, 5),
            above_ma20=latest > ma20,
            vol_expansion=round(vol_exp, 3),
        )
    except Exception as exc:
        logger.debug("polygon: %s fetch failed: %s", ticker, exc)
        return EquityMomentum(ticker)


async def _fetch_pcr() -> float:
    """CBOE public CDN — no auth required."""
    try:
        raw = await _get_json(_CBOE_PCR)
        data = raw.get("data", [])
        if data:
            # Columns: date, open, high, low, close, pcr_calls, pcr_puts, pcr
            latest = data[-1]
            if isinstance(latest, list) and len(latest) >= 8:
                return round(float(latest[7]), 3)
    except Exception as exc:
        logger.debug("polygon: CBOE PCR fetch failed: %s", exc)
    return 1.0


# ── Service class ──────────────────────────────────────────────────────────────

class PolygonContextService:
    def __init__(self) -> None:
        self._cache: Optional[PolygonContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> PolygonContextSnapshot:
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

    async def _fetch(self) -> PolygonContextSnapshot:
        import asyncio
        try:
            tasks = [_fetch_equity(t) for t in _TICKERS] + [_fetch_pcr()]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            equities: Dict[str, EquityMomentum] = {}
            for i, ticker in enumerate(_TICKERS):
                r = results[i]
                equities[ticker] = r if isinstance(r, EquityMomentum) else EquityMomentum(ticker)
            pcr = results[-1] if not isinstance(results[-1], Exception) else 1.0
            snap = PolygonContextSnapshot(
                equities=equities,
                put_call_ratio=pcr,
                spy_ret_5d=equities.get("SPY", EquityMomentum("SPY")).ret_5d,
                source="live" if _POLY_KEY else "stub",
            )
            snap.market_regime = snap._derive_regime()
            logger.debug("polygon: regime=%s SPY_5d=%.3f PCR=%.2f",
                         snap.market_regime, snap.spy_ret_5d, snap.put_call_ratio)
            return snap
        except Exception as exc:
            logger.warning("polygon: context fetch failed (%s) — stub", exc)
            return PolygonContextSnapshot(source="stub")


_service: Optional[PolygonContextService] = None
_svc_lock = Lock()


def get_polygon_context_service() -> PolygonContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = PolygonContextService()
    return _service
