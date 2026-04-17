"""D1+D2: FRED Macro Context + BLS Release Calendar

Fetches key macroeconomic series from the St. Louis Fed FRED API and detects
upcoming BLS scheduled release days (CPI, PPI, nonfarm payrolls).

The resulting ``MacroContextSnapshot`` exposes ``to_edge_features()`` which the
EdgeModel consumes as additional input signals.

Environment
-----------
FRED_API_KEY  — get a free key at https://fred.stlouisfed.org/docs/api/api_key.html
                Works in stub mode with zeros if key is absent.

Key series fetched
------------------
  FEDFUNDS   — effective federal funds rate (monthly)
  CPIAUCSL   — CPI all-items (monthly, YoY delta computed here)
  UNRATE     — civilian unemployment rate (monthly)
  T10Y2Y     — 10Y−2Y yield spread; negative = inverted curve (daily)
  VIXCLS     — CBOE VIX closing price (daily)
  DGS10      — 10-year treasury constant maturity (daily)
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

_CACHE_TTL = 3600.0            # FRED data is daily at most; 1-hour cache is fine
_FRED_BASE  = "https://api.stlouisfed.org/fred/series/observations"
_FRED_KEY   = os.getenv("FRED_API_KEY", "")


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class MacroSeries:
    """Latest value + 1-period change for a single FRED series."""
    series_id: str
    value: float = 0.0
    prev_value: float = 0.0
    date: str = ""            # YYYY-MM-DD of the latest observation
    delta: float = 0.0        # value − prev_value

    @property
    def pct_change(self) -> float:
        if self.prev_value == 0:
            return 0.0
        return (self.value - self.prev_value) / abs(self.prev_value)


@dataclass
class BLSReleaseAlert:
    """An upcoming or recent BLS scheduled release."""
    report: str               # "CPI" | "PPI" | "NFP"
    release_date: date
    days_away: int            # negative = already passed this many days ago


@dataclass
class MacroContextSnapshot:
    fed_funds_rate: float = 0.0        # %
    cpi_yoy: float = 0.0               # % year-over-year
    unemployment_rate: float = 0.0     # %
    yield_spread_10y2y: float = 0.0    # % (negative = inverted)
    vix: float = 0.0                   # CBOE VIX
    treasury_10y: float = 0.0          # %
    cpi_momentum: float = 0.0          # CPI delta (latest - prior month)
    upcoming_releases: List[BLSReleaseAlert] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"               # "live" | "stub"

    # ── Regime flags (derived) ──────────────────────────────────────────────

    @property
    def is_inverted_curve(self) -> bool:
        return self.yield_spread_10y2y < 0

    @property
    def is_high_inflation(self) -> bool:
        return self.cpi_yoy > 3.5

    @property
    def is_high_vix(self) -> bool:
        return self.vix > 25.0

    @property
    def release_within_days(self) -> int:
        """Minimum |days_away| for any scheduled BLS release in ±3-day window."""
        nearby = [abs(r.days_away) for r in self.upcoming_releases if abs(r.days_away) <= 3]
        return min(nearby) if nearby else 99

    # ── Feature dict for EdgeModel ──────────────────────────────────────────

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "macro_fed_funds_rate": self.fed_funds_rate,
            "macro_cpi_yoy": self.cpi_yoy,
            "macro_cpi_momentum": self.cpi_momentum,
            "macro_unemployment": self.unemployment_rate,
            "macro_yield_spread_10y2y": self.yield_spread_10y2y,
            "macro_vix": self.vix,
            "macro_treasury_10y": self.treasury_10y,
            "macro_inverted_curve": float(self.is_inverted_curve),
            "macro_high_inflation": float(self.is_high_inflation),
            "macro_high_vix": float(self.is_high_vix),
            "macro_release_days_away": float(self.release_within_days),
            "macro_context_age_s": round(time.time() - self.fetched_at, 1),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fed_funds_rate": self.fed_funds_rate,
            "cpi_yoy": self.cpi_yoy,
            "cpi_momentum": self.cpi_momentum,
            "unemployment_rate": self.unemployment_rate,
            "yield_spread_10y2y": self.yield_spread_10y2y,
            "vix": self.vix,
            "treasury_10y": self.treasury_10y,
            "is_inverted_curve": self.is_inverted_curve,
            "is_high_inflation": self.is_high_inflation,
            "is_high_vix": self.is_high_vix,
            "upcoming_releases": [
                {"report": r.report, "date": str(r.release_date), "days_away": r.days_away}
                for r in self.upcoming_releases
            ],
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── FRED fetch helpers ─────────────────────────────────────────────────────────

async def _fred_latest(series_id: str, n: int = 2) -> List[float]:
    """Return the last ``n`` non-null observations for a FRED series."""
    if not _FRED_KEY:
        return [0.0] * n
    import httpx
    params = {
        "series_id": series_id,
        "api_key": _FRED_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(n),
        "observation_start": "2000-01-01",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_FRED_BASE, params=params)
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            values: List[float] = []
            for o in obs:
                v = o.get("value", ".")
                if v != ".":
                    values.append(float(v))
                if len(values) >= n:
                    break
            # Pad with zeros if fewer observations returned
            while len(values) < n:
                values.append(0.0)
            return values
    except Exception as exc:
        logger.debug("FRED %s fetch failed: %s", series_id, exc)
        return [0.0] * n


# ── BLS release calendar (D2) ─────────────────────────────────────────────────
# BLS publishes a full release calendar at:
# https://www.bls.gov/schedule/news_release/releaseCalendar.htm
# We use a heuristic rule-of-thumb rather than scraping, which is stable enough:
#   CPI        — 2nd or 3rd Wednesday of each month  (varies; we use 3rd Wed)
#   PPI        — one business day before CPI
#   NFP        — first Friday of each month

def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th occurrence (1-indexed) of weekday (0=Mon … 6=Sun) in month."""
    d = date(year, month, 1)
    # Advance to first occurrence of weekday
    diff = (weekday - d.weekday()) % 7
    d = d + timedelta(days=diff)
    # Advance n-1 more weeks
    d = d + timedelta(weeks=n - 1)
    return d


def _bls_releases_near(today: date, window_days: int = 14) -> List[BLSReleaseAlert]:
    """Return BLS release dates within ±window_days of today."""
    alerts: List[BLSReleaseAlert] = []
    for offset in range(-1, 3):  # check this month and the next 2
        month = today.month + offset
        year  = today.year
        if month <= 0:
            month += 12; year -= 1
        elif month > 12:
            month -= 12; year += 1

        try:
            nfp = _nth_weekday_of_month(year, month, 4, 1)    # first Friday
            cpi = _nth_weekday_of_month(year, month, 2, 3)    # 3rd Wednesday
            ppi = cpi - timedelta(days=1)                      # day before CPI

            for report, rel_date in [("NFP", nfp), ("CPI", cpi), ("PPI", ppi)]:
                days_away = (rel_date - today).days
                if abs(days_away) <= window_days:
                    alerts.append(BLSReleaseAlert(report=report, release_date=rel_date, days_away=days_away))
        except (ValueError, OverflowError):
            continue

    return sorted(alerts, key=lambda a: abs(a.days_away))


# ── E3: Finnhub calendar integration ─────────────────────────────────────────

async def _finnhub_releases_or_bls(today: date) -> List[BLSReleaseAlert]:
    """Use Finnhub economic calendar when key is available; fall back to BLS heuristic.

    Converts Finnhub EconomicRelease objects into BLSReleaseAlert instances so
    the rest of MacroContextSnapshot can remain unchanged.
    """
    try:
        from merid.prediction.finnhub_context import get_finnhub_context_service
        svc = get_finnhub_context_service()
        snap = await svc.get_snapshot()
        if snap.source == "stub" or not snap.releases:
            raise ValueError("finnhub returned no releases")

        alerts: List[BLSReleaseAlert] = []
        for r in snap.releases:
            if r.impact not in {"high", "High", "HIGH"}:
                continue
            if r.country != "US":
                continue
            # Map Finnhub event name → BLS short code for the dashboard
            name = r.event
            if any(k in name for k in ("CPI", "Consumer Price")):
                code = "CPI"
            elif any(k in name for k in ("PPI", "Producer Price")):
                code = "PPI"
            elif any(k in name for k in ("Nonfarm", "Payroll", "Employment")):
                code = "NFP"
            elif any(k in name for k in ("GDP",)):
                code = "GDP"
            elif any(k in name for k in ("Fed", "FOMC", "Rate Decision")):
                code = "FOMC"
            else:
                code = name[:8]
            try:
                rel_date = date.fromisoformat(r.release_time[:10])
            except ValueError:
                continue
            days_away = int((rel_date - today).days)
            alerts.append(BLSReleaseAlert(report=code, release_date=rel_date, days_away=days_away))

        if alerts:
            logger.debug("macro_context: %d high-impact releases from Finnhub", len(alerts))
            return sorted(alerts, key=lambda a: abs(a.days_away))

    except Exception as exc:
        logger.debug("macro_context: Finnhub calendar unavailable (%s) — using BLS heuristic", exc)

    return _bls_releases_near(today)


# ── Service class ──────────────────────────────────────────────────────────────

class MacroContextService:
    """Fetches FRED series + BLS calendar; caches for 1 hour."""

    def __init__(self) -> None:
        self._cache: Optional[MacroContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> MacroContextSnapshot:
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

    async def _fetch(self) -> MacroContextSnapshot:
        import asyncio
        today = date.today()

        # Fire all FRED requests concurrently
        try:
            (
                fedfunds,
                cpi,
                unrate,
                spread,
                vix,
                dgs10,
            ) = await asyncio.gather(
                _fred_latest("FEDFUNDS", 2),
                _fred_latest("CPIAUCSL", 14),   # 14 months for YoY
                _fred_latest("UNRATE", 2),
                _fred_latest("T10Y2Y", 2),
                _fred_latest("VIXCLS", 2),
                _fred_latest("DGS10", 2),
            )

            # CPI year-over-year: (latest / 12-months-ago - 1) * 100
            cpi_yoy = ((cpi[0] / cpi[12]) - 1.0) * 100 if cpi[12] > 0 else 0.0
            cpi_momentum = cpi[0] - cpi[1]

            # E3: Try Finnhub calendar first (real data); fall back to BLS heuristic
            releases = await _finnhub_releases_or_bls(today)

            snap = MacroContextSnapshot(
                fed_funds_rate=fedfunds[0],
                cpi_yoy=round(cpi_yoy, 3),
                cpi_momentum=round(cpi_momentum, 4),
                unemployment_rate=unrate[0],
                yield_spread_10y2y=spread[0],
                vix=vix[0],
                treasury_10y=dgs10[0],
                upcoming_releases=releases,
                source="live" if _FRED_KEY else "stub",
            )
            logger.debug(
                "macro_context: FFR=%.2f CPI_YoY=%.2f UNR=%.1f Spread=%.2f VIX=%.1f",
                snap.fed_funds_rate, snap.cpi_yoy, snap.unemployment_rate,
                snap.yield_spread_10y2y, snap.vix,
            )
            return snap

        except Exception as exc:
            logger.warning("macro_context: FRED fetch failed (%s) — using stub", exc)
            return MacroContextSnapshot(source="stub", upcoming_releases=_bls_releases_near(today))


# ── Singleton ──────────────────────────────────────────────────────────────────

_service: Optional[MacroContextService] = None
_svc_lock = Lock()


def get_macro_context_service() -> MacroContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = MacroContextService()
    return _service
