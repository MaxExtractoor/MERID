from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.exchange_availability")


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept both "...Z" and "+00:00" forms.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _weekly_thu_maintenance_windows_utc(
    now_utc: datetime,
    *,
    tz_name: str = "America/New_York",
) -> List[Tuple[datetime, datetime]]:
    """Return the canonical weekly Thu 03:00–05:00 ET maintenance windows.

    We include the "this-week" and "next-week" windows so next maintenance is always visible.
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        # If zoneinfo unavailable (unlikely), treat ET as fixed UTC-5 (imperfect but deterministic).
        tz = timezone(timedelta(hours=-5))

    now_et = now_utc.astimezone(tz)
    # ISO weekday: Monday=1 ... Thursday=4
    days_since_thu = (now_et.isoweekday() - 4) % 7
    thu_date = (now_et.date() - timedelta(days=days_since_thu))

    def _mk(date_obj) -> Tuple[datetime, datetime]:
        start_et = datetime(date_obj.year, date_obj.month, date_obj.day, 3, 0, 0, tzinfo=tz)
        end_et = datetime(date_obj.year, date_obj.month, date_obj.day, 5, 0, 0, tzinfo=tz)
        return (_as_utc(start_et), _as_utc(end_et))

    this_week = _mk(thu_date)
    next_week = _mk(thu_date + timedelta(days=7))
    return [this_week, next_week]


@dataclass(frozen=True)
class KalshiExchangeAvailabilitySnapshot:
    trading_open_now: bool
    reason: str  # "open" | "scheduled" | "adhoc" | "unknown"
    now_utc: str
    next_open_time_utc: Optional[str]
    estimated_resume_time_utc: Optional[str]
    active_window_utc: Optional[Tuple[str, str]]
    upcoming_maintenance_windows_utc: List[Tuple[str, str]]
    schedule_fresh_age_s: Optional[float]
    status_fresh_age_s: Optional[float]
    ok: bool
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "trading_open_now": self.trading_open_now,
            "reason": self.reason,
            "now_utc": self.now_utc,
            "next_open_time_utc": self.next_open_time_utc,
            "estimated_resume_time_utc": self.estimated_resume_time_utc,
            "active_window_utc": self.active_window_utc,
            "upcoming_maintenance_windows_utc": self.upcoming_maintenance_windows_utc,
            "schedule_fresh_age_s": self.schedule_fresh_age_s,
            "status_fresh_age_s": self.status_fresh_age_s,
            "ok": self.ok,
            "error": self.error,
        }


def compute_kalshi_exchange_availability(
    *,
    now: Optional[datetime] = None,
    schedule: Optional[Dict[str, Any]] = None,
    status: Optional[Dict[str, Any]] = None,
    maintenance_grace_seconds: int = 120,
    tz_name: str = "America/New_York",
    max_windows_to_surface: int = 10,
) -> KalshiExchangeAvailabilitySnapshot:
    """Pure helper to derive a boolean 'open' plus next-open time.

    Inputs are the raw JSON payloads from:
      - GET /exchange/schedule  (schedule)
      - GET /exchange/status    (status)
    plus MERID-side grace buffer (seconds).
    """
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    grace = timedelta(seconds=max(0, int(maintenance_grace_seconds)))

    windows: List[Tuple[datetime, datetime]] = []

    # 1) API schedule maintenance windows (ad-hoc and scheduled, if provided)
    try:
        raw = (schedule or {}).get("maintenance_windows") or []
        if isinstance(raw, list):
            for w in raw:
                if not isinstance(w, dict):
                    continue
                s = _parse_dt(str(w.get("start_datetime") or w.get("start_time") or w.get("start") or ""))
                e = _parse_dt(str(w.get("end_datetime") or w.get("end_time") or w.get("end") or ""))
                if s is None or e is None:
                    continue
                s_utc = _as_utc(s)
                e_utc = _as_utc(e)
                if e_utc <= s_utc:
                    continue
                windows.append((s_utc, e_utc))
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Window parse failed: {e}")

    # 2) Canonical weekly Thu 03:00–05:00 ET window (fallback / explicit)
    try:
        windows.extend(_weekly_thu_maintenance_windows_utc(now_utc, tz_name=tz_name))
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Weekly window calc failed: {e}")

    # Normalize + sort + apply grace to the window edges.
    win_adj: List[Tuple[datetime, datetime]] = []
    for s, e in windows:
        win_adj.append((s - grace, e + grace))
    win_adj.sort(key=lambda x: x[0])

    # Try to interpret exchange status payload (current downtime wins).
    estimated_resume = None
    is_open_from_status: Optional[bool] = None
    try:
        # Docs mention exchange_estimated_resume_time during maintenance.
        estimated_resume = _parse_dt(
            str(
                (status or {}).get("exchange_estimated_resume_time")
                or (status or {}).get("exchange_estimated_resume_time_utc")
                or (status or {}).get("estimated_resume_time")
                or ""
            )
        )
        if estimated_resume is not None:
            estimated_resume = _as_utc(estimated_resume) + grace
        # Many APIs also provide boolean-ish flags. Be permissive.
        for k in ("trading_open", "exchange_open", "is_open", "open"):
            if k in (status or {}):
                is_open_from_status = bool((status or {}).get(k))
                break
        # Some payloads use status strings.
        st = str((status or {}).get("exchange_status") or (status or {}).get("status") or "").lower().strip()
        if st in {"maintenance", "closed", "down"}:
            is_open_from_status = False
        elif st in {"open", "trading"}:
            is_open_from_status = True
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Status parse failed: {e}")

    active_window: Optional[Tuple[datetime, datetime]] = None
    for s, e in win_adj:
        if s <= now_utc < e:
            active_window = (s, e)
            break

    # Decide open/closed:
    reason = "open"
    trading_open_now = True
    next_open: Optional[datetime] = None

    if estimated_resume is not None and estimated_resume > now_utc:
        trading_open_now = False
        reason = "adhoc"
        next_open = estimated_resume
    elif active_window is not None:
        trading_open_now = False
        reason = "scheduled"
        next_open = active_window[1]
    elif is_open_from_status is False:
        trading_open_now = False
        reason = "unknown"
        next_open = estimated_resume  # maybe None
    elif is_open_from_status is True:
        trading_open_now = True
        reason = "open"

    upcoming: List[Tuple[datetime, datetime]] = []
    for s, e in win_adj:
        if e <= now_utc:
            continue
        upcoming.append((s, e))
        if len(upcoming) >= max_windows_to_surface:
            break

    def _fmt(dt: Optional[datetime]) -> Optional[str]:
        return dt.astimezone(timezone.utc).isoformat() if dt else None

    active_tuple = None
    if active_window is not None:
        active_tuple = (_fmt(active_window[0]) or "", _fmt(active_window[1]) or "")

    upcoming_fmt = [(_fmt(s) or "", _fmt(e) or "") for (s, e) in upcoming]

    return KalshiExchangeAvailabilitySnapshot(
        trading_open_now=bool(trading_open_now),
        reason=reason,
        now_utc=now_utc.isoformat(),
        next_open_time_utc=_fmt(next_open),
        estimated_resume_time_utc=_fmt(estimated_resume),
        active_window_utc=active_tuple,
        upcoming_maintenance_windows_utc=upcoming_fmt,
        schedule_fresh_age_s=None,
        status_fresh_age_s=None,
        ok=True,
        error=None,
    )


class KalshiExchangeAvailability:
    """Venue-level single source of truth for exchange availability.

    - Poll schedule slowly (to cache upcoming maintenance windows).
    - Poll status quickly (to detect current downtime + estimated resume time).
    """

    def __init__(
        self,
        *,
        schedule_poll_s: int = 3600,
        status_poll_s: int = 30,
        maintenance_grace_s: int = 120,
        tz_name: str = "America/New_York",
    ) -> None:
        self.schedule_poll_s = max(30, int(schedule_poll_s))
        self.status_poll_s = max(5, int(status_poll_s))
        self.maintenance_grace_s = max(0, int(maintenance_grace_s))
        self.tz_name = tz_name

        self._lock = threading.Lock()
        self._last_schedule: Optional[Dict[str, Any]] = None
        self._last_status: Optional[Dict[str, Any]] = None
        self._last_schedule_ts: Optional[float] = None
        self._last_status_ts: Optional[float] = None
        self._last_error: Optional[str] = None
        self._running = False

    def snapshot(self) -> KalshiExchangeAvailabilitySnapshot:
        now = datetime.now(timezone.utc)
        with self._lock:
            schedule = self._last_schedule
            status = self._last_status
            s_ts = self._last_schedule_ts
            st_ts = self._last_status_ts
            err = self._last_error

        snap = compute_kalshi_exchange_availability(
            now=now,
            schedule=schedule,
            status=status,
            maintenance_grace_seconds=self.maintenance_grace_s,
            tz_name=self.tz_name,
        )

        age_schedule = (time.time() - s_ts) if s_ts else None
        age_status = (time.time() - st_ts) if st_ts else None

        # "ok" means we have *some* meaningful signal: either fresh-ish status, or at least schedule,
        # or we're outside the canonical weekly maintenance window.
        ok = True
        if age_status is not None and age_status > (self.status_poll_s * 4):
            ok = False
        if age_status is None and age_schedule is None:
            ok = False

        return KalshiExchangeAvailabilitySnapshot(
            trading_open_now=snap.trading_open_now,
            reason=snap.reason if ok else "unknown",
            now_utc=snap.now_utc,
            next_open_time_utc=snap.next_open_time_utc,
            estimated_resume_time_utc=snap.estimated_resume_time_utc,
            active_window_utc=snap.active_window_utc,
            upcoming_maintenance_windows_utc=snap.upcoming_maintenance_windows_utc,
            schedule_fresh_age_s=age_schedule,
            status_fresh_age_s=age_status,
            ok=ok,
            error=err if not ok else None,
        )

    async def run(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info(
            "KalshiExchangeAvailability starting (schedule_poll=%ss status_poll=%ss grace=%ss tz=%s)",
            self.schedule_poll_s,
            self.status_poll_s,
            self.maintenance_grace_s,
            self.tz_name,
        )

        from merid.event_venues.kalshi.client import get_kalshi_client

        while True:
            try:
                now_s = time.time()
                due_schedule = True
                due_status = True
                with self._lock:
                    if self._last_schedule_ts is not None:
                        due_schedule = (now_s - self._last_schedule_ts) >= self.schedule_poll_s
                    if self._last_status_ts is not None:
                        due_status = (now_s - self._last_status_ts) >= self.status_poll_s

                if due_schedule:
                    try:
                        res = await get_kalshi_client().get_exchange_schedule()
                        if res.ok:
                            with self._lock:
                                self._last_schedule = res.data or {}
                                self._last_schedule_ts = time.time()
                                self._last_error = None
                        else:
                            with self._lock:
                                self._last_error = str(res.error)[:200] if res.error else "schedule_error"
                    except Exception as exc:
                        with self._lock:
                            self._last_error = f"schedule_exc:{exc}"[:200]

                if due_status:
                    try:
                        res = await get_kalshi_client().get_exchange_status()
                        if res.ok:
                            with self._lock:
                                self._last_status = res.data or {}
                                self._last_status_ts = time.time()
                                self._last_error = None
                        else:
                            with self._lock:
                                self._last_error = str(res.error)[:200] if res.error else "status_error"
                    except Exception as exc:
                        with self._lock:
                            self._last_error = f"status_exc:{exc}"[:200]

            except asyncio.CancelledError:
                raise
            except Exception as loop_exc:
                with self._lock:
                    self._last_error = f"loop_exc:{loop_exc}"[:200]

            await asyncio.sleep(1.0)


_instance: Optional[KalshiExchangeAvailability] = None
_instance_lock = threading.Lock()


def get_kalshi_exchange_availability() -> KalshiExchangeAvailability:
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        try:
            from merid.settings import settings

            _instance = KalshiExchangeAvailability(
                schedule_poll_s=getattr(settings, "KALSHI_EXCHANGE_SCHEDULE_POLL_S", 3600),
                status_poll_s=getattr(settings, "KALSHI_EXCHANGE_STATUS_POLL_S", 30),
                maintenance_grace_s=getattr(settings, "KALSHI_MAINTENANCE_GRACE_S", 120),
                tz_name="America/New_York",
            )
        except Exception:
            _instance = KalshiExchangeAvailability()
        return _instance

