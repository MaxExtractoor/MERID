"""F3: NOAA/NHC Hurricane Context — Active Storm Tracking

Fetches active Atlantic and Eastern Pacific tropical storm data from the
National Hurricane Center public JSON API (no auth required).

Florida-specific: flags storms threatening the Gulf or Atlantic coasts
within the 5-day forecast cone. Seasonal alpha June–November.

Endpoints used (all free, no key)
-----------------------------------
  https://www.nhc.noaa.gov/CurrentStorms.json  — active storm list
  https://www.nhc.noaa.gov/nhc_at1.xml         — Atlantic RSS feed
  https://api.weather.gov/alerts/active?area=FL — NOAA active FL alerts
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL    = 1800.0   # 30 min — storm tracks update every 6h from NHC
_STORMS_URL   = "https://www.nhc.noaa.gov/CurrentStorms.json"
_FL_ALERTS    = "https://api.weather.gov/alerts/active?area=FL"

_FL_BBOX = {
    "lat_min": 24.5, "lat_max": 31.0,
    "lon_min": -87.6, "lon_max": -80.0,
}

_INTENSITY_ORDER = ["TD", "TS", "H1", "H2", "H3", "H4", "H5"]


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ActiveStorm:
    id: str
    name: str
    basin: str          # "AL" = Atlantic, "EP" = East Pacific
    intensity: str      # "TD" | "TS" | "H1"..."H5"
    wind_mph: int
    lat: float
    lon: float
    movement_dir: str   # e.g. "NNW"
    movement_mph: int
    fl_threat: bool     # within ~500 miles of FL coast
    category: int       # 0 = TD/TS, 1-5 = hurricane category

    @property
    def is_hurricane(self) -> bool:
        return self.category >= 1

    @property
    def threat_level(self) -> float:
        """0–1 threat level weighting category + proximity to FL."""
        if not self.fl_threat:
            return 0.0
        base = min(1.0, self.category / 5.0 + 0.2)
        return round(base, 3)


@dataclass
class HurricaneContextSnapshot:
    active_storms: List[ActiveStorm] = field(default_factory=list)
    fl_active_alerts: int = 0          # count of active NOAA weather alerts for FL
    peak_fl_threat: float = 0.0        # 0–1 highest threat storm
    is_hurricane_season: bool = False  # True Jun 1 – Nov 30
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    @property
    def fl_hurricane_threat(self) -> bool:
        return any(s.fl_threat and s.is_hurricane for s in self.active_storms)

    @property
    def any_fl_threat(self) -> bool:
        return any(s.fl_threat for s in self.active_storms)

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "hurr_active_storms":    float(len(self.active_storms)),
            "hurr_fl_threat":        float(self.any_fl_threat),
            "hurr_fl_hurricane":     float(self.fl_hurricane_threat),
            "hurr_peak_threat":      self.peak_fl_threat,
            "hurr_season":           float(self.is_hurricane_season),
            "hurr_fl_alerts":        float(self.fl_active_alerts),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_storms": [
                {
                    "name": s.name, "id": s.id, "basin": s.basin,
                    "intensity": s.intensity, "wind_mph": s.wind_mph,
                    "lat": s.lat, "lon": s.lon,
                    "fl_threat": s.fl_threat, "category": s.category,
                    "threat_level": s.threat_level,
                }
                for s in self.active_storms
            ],
            "fl_active_alerts": self.fl_active_alerts,
            "peak_fl_threat": self.peak_fl_threat,
            "is_hurricane_season": self.is_hurricane_season,
            "fl_hurricane_threat": self.fl_hurricane_threat,
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_hurricane_season() -> bool:
    now = datetime.now(timezone.utc)
    return 6 <= now.month <= 11


def _near_florida(lat: float, lon: float, radius_deg: float = 8.0) -> bool:
    """Rough check: within radius_deg of Florida's centroid (27.5N, 81.5W)."""
    return abs(lat - 27.5) <= radius_deg and abs(lon - (-81.5)) <= radius_deg


def _parse_intensity(wind_mph: int) -> tuple:
    """Return (intensity_code, category) from sustained wind speed in mph."""
    if wind_mph < 39:
        return "TD", 0
    if wind_mph < 74:
        return "TS", 0
    if wind_mph < 96:
        return "H1", 1
    if wind_mph < 111:
        return "H2", 2
    if wind_mph < 130:
        return "H3", 3
    if wind_mph < 157:
        return "H4", 4
    return "H5", 5


async def _get_json(url: str, headers: Optional[Dict] = None) -> Any:
    import httpx
    h = {"User-Agent": "MERID/1.0 (weather data; contact merid_engine@outlook.com)"}
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, headers=h)
        resp.raise_for_status()
        return resp.json()


async def _fetch_active_storms() -> List[ActiveStorm]:
    try:
        raw = await _get_json(_STORMS_URL)
        storms_data = raw.get("activeStorms", [])
        storms: List[ActiveStorm] = []
        for s in storms_data:
            try:
                wind = int(s.get("maxWindSpeedMph") or s.get("intensity") or 0)
                lat  = float(s.get("latitudeNumeric") or s.get("lat") or 0)
                lon  = float(s.get("longitudeNumeric") or s.get("lon") or 0)
                intensity, category = _parse_intensity(wind)
                storms.append(ActiveStorm(
                    id=s.get("id", ""),
                    name=s.get("name", "Unknown"),
                    basin=s.get("basin", "AL"),
                    intensity=intensity,
                    wind_mph=wind,
                    lat=lat,
                    lon=lon,
                    movement_dir=s.get("movementDir", ""),
                    movement_mph=int(s.get("movementSpeedMph") or 0),
                    fl_threat=_near_florida(lat, lon),
                    category=category,
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return storms
    except Exception as exc:
        logger.debug("hurricane: NHC storms fetch failed: %s", exc)
        return []


async def _fetch_fl_alerts() -> int:
    try:
        raw = await _get_json(_FL_ALERTS)
        alerts = raw.get("features", [])
        # Count only tropical/hurricane alerts
        tropical = [
            a for a in alerts
            if any(kw in str(a.get("properties", {}).get("event", "")).lower()
                   for kw in ("tropical", "hurricane", "storm surge", "typhoon"))
        ]
        return len(tropical)
    except Exception as exc:
        logger.debug("hurricane: FL alerts fetch failed: %s", exc)
        return 0


# ── Service class ──────────────────────────────────────────────────────────────

class HurricaneContextService:
    def __init__(self) -> None:
        self._cache: Optional[HurricaneContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> HurricaneContextSnapshot:
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

    async def _fetch(self) -> HurricaneContextSnapshot:
        import asyncio
        storms, fl_alerts = await asyncio.gather(
            _fetch_active_storms(),
            _fetch_fl_alerts(),
            return_exceptions=True,
        )
        if isinstance(storms, Exception):
            storms = []
        if isinstance(fl_alerts, Exception):
            fl_alerts = 0

        peak = max((s.threat_level for s in storms), default=0.0)
        snap = HurricaneContextSnapshot(
            active_storms=storms,
            fl_active_alerts=fl_alerts,
            peak_fl_threat=peak,
            is_hurricane_season=_is_hurricane_season(),
            source="live",
        )
        logger.debug(
            "hurricane: %d active storms, FL_threat=%s, alerts=%d, season=%s",
            len(storms), snap.any_fl_threat, fl_alerts, snap.is_hurricane_season,
        )
        return snap


_service: Optional[HurricaneContextService] = None
_svc_lock = Lock()


def get_hurricane_context_service() -> HurricaneContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = HurricaneContextService()
    return _service
