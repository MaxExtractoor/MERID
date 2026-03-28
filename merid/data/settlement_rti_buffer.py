"""CFB RTI (CF Benchmarks Real-Time Index) buffer and safety gate.

Kalshi settles crypto contracts via 60-second averaged CFB RTIs for CFTC
compliance. This module provides:

- ``SettlementRtiBuffer``  — poll adapter that fetches RTI ticks from CF
  Benchmarks and buffers the most recent value.
- ``require_cfb_for_live_trading()`` — safety gate that blocks live
  Kalshi trading unless the RTI feed is healthy (only enforced when
  ``KALSHI_ENV=live``).
- ``get_rti_buffer()`` — process-wide singleton accessor.

Environment variables
---------------------
``MERID_CFB_RTI_POLL_URL``
    Full URL to the CF Benchmarks RTI endpoint, e.g.
    ``https://api.cfbenchmarks.com/v1/rtis/BRTI/value``.
    Required when ``MERID_CFB_RTI_ADAPTER=live``.

``MERID_CFB_RTI_ADAPTER``
    ``live``       — polls the real CF Benchmarks API (default in production).
    ``simulation`` — uses synthetic replay ticks (dev / paper trading).

``MERID_CFB_RTI_SIMULATE``
    Set to ``1`` to force simulation mode regardless of adapter setting.

``MERID_ALLOW_NULL_CFB``
    Set to ``1`` to bypass the safety gate even when no ticks are
    available.  **Non-production only.**  Unblocks trading when the
    CF Benchmarks feed is temporarily unavailable (e.g., off-season).

``KALSHI_ENV``
    ``live`` — RTI health is enforced as a hard gate before order
    submission.  Any other value (``paper``, ``demo``, etc.) causes the
    safety gate to return immediately without blocking.

``CFB_API_KEY``
    API key for the CF Benchmarks endpoint (sent as ``X-Api-Key`` header).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.data.settlement_rti_buffer")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: How many RTI ticks to retain in the rolling buffer.
RTI_BUFFER_SIZE = 60

#: Default poll interval in seconds (matches Kalshi's 60-s averaging window).
RTI_POLL_INTERVAL_S = 60.0

#: Tick older than this many seconds is considered stale.
RTI_STALE_THRESHOLD_S = 180.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RtiTick:
    """A single RTI value received from CF Benchmarks."""

    index_name: str
    value: float
    received_at: float = field(default_factory=time.time)
    raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

class _LiveRtiAdapter:
    """Fetches RTI ticks from the real CF Benchmarks REST API."""

    def __init__(self, poll_url: str, api_key: Optional[str] = None) -> None:
        if not poll_url:
            raise ValueError(
                "MERID_CFB_RTI_POLL_URL must be set when MERID_CFB_RTI_ADAPTER=live"
            )
        self._url = poll_url
        self._api_key = api_key

    def fetch(self) -> Optional[RtiTick]:
        """Return a fresh ``RtiTick`` or ``None`` on failure."""
        try:
            import httpx  # soft dependency — already in requirements

            headers: Dict[str, str] = {}
            if self._api_key:
                headers["X-Api-Key"] = self._api_key

            resp = httpx.get(self._url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

            # CF Benchmarks v1 envelope: {"value": ..., "name": ..., ...}
            value = float(data.get("value") or data.get("price") or 0)
            name = str(data.get("name") or data.get("index") or "CFB_RTI")

            return RtiTick(index_name=name, value=value, raw=data)
        except Exception as exc:
            logger.warning("CFB RTI fetch failed: %s", exc)
            return None


class _SimulationRtiAdapter:
    """Produces synthetic RTI ticks for dev / paper-trading environments."""

    _BASE = 95_000.0  # nominal BTC price for replay

    def __init__(self) -> None:
        self._counter = 0

    def fetch(self) -> Optional[RtiTick]:
        import math

        # Simple sine-wave oscillation around the base so tests see variety
        delta = 500.0 * math.sin(self._counter * 0.1)
        self._counter += 1
        return RtiTick(
            index_name="BRTI_SIM",
            value=self._BASE + delta,
        )


# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------

class SettlementRtiBuffer:
    """Rolling buffer of CFB RTI ticks with a background poll loop.

    Parameters
    ----------
    adapter_type:
        ``"live"`` or ``"simulation"`` (overrides env).
    poll_url:
        CF Benchmarks endpoint URL (only used by live adapter).
    api_key:
        CF Benchmarks API key.
    poll_interval_s:
        Seconds between polls.
    """

    def __init__(
        self,
        *,
        adapter_type: Optional[str] = None,
        poll_url: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval_s: float = RTI_POLL_INTERVAL_S,
    ) -> None:
        # Resolve adapter type from env if not explicitly provided
        if os.getenv("MERID_CFB_RTI_SIMULATE", "0") == "1":
            adapter_type = "simulation"
        if adapter_type is None:
            adapter_type = os.getenv("MERID_CFB_RTI_ADAPTER", "live")

        poll_url = poll_url or os.getenv("MERID_CFB_RTI_POLL_URL", "")
        api_key = api_key or os.getenv("CFB_API_KEY")

        if adapter_type == "simulation":
            self._adapter: _LiveRtiAdapter | _SimulationRtiAdapter = (
                _SimulationRtiAdapter()
            )
        else:
            self._adapter = _LiveRtiAdapter(poll_url=poll_url, api_key=api_key)

        self._adapter_type = adapter_type
        self._poll_interval = poll_interval_s

        self._ticks: List[RtiTick] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        logger.info(
            "SettlementRtiBuffer initialised (adapter=%s, poll_interval=%.0fs)",
            adapter_type,
            poll_interval_s,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="rti-buffer-poll",
            daemon=True,
        )
        self._thread.start()
        logger.info("CFB RTI poll thread started")

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("CFB RTI poll thread stopped")

    def poll_once(self) -> Optional[RtiTick]:
        """Fetch a single tick synchronously and store it.

        Useful in tests or one-shot contexts.
        """
        tick = self._adapter.fetch()
        if tick:
            self._push(tick)
        return tick

    @property
    def tick_count(self) -> int:
        """Number of ticks currently in the buffer."""
        with self._lock:
            return len(self._ticks)

    @property
    def last_tick(self) -> Optional[RtiTick]:
        """Most recent RTI tick, or ``None`` if the buffer is empty."""
        with self._lock:
            return self._ticks[-1] if self._ticks else None

    def is_healthy(self) -> bool:
        """Return ``True`` if the buffer has at least one non-stale tick."""
        tick = self.last_tick
        if tick is None:
            return False
        age = time.time() - tick.received_at
        return age < RTI_STALE_THRESHOLD_S

    def health_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable health snapshot for the /health/cfb_rti endpoint."""
        tick = self.last_tick
        now = time.time()
        return {
            "status": "healthy" if self.is_healthy() else "no_data",
            "adapter": self._adapter_type,
            "tick_count": self.tick_count,
            "last_tick": {
                "index_name": tick.index_name,
                "value": tick.value,
                "received_at": tick.received_at,
                "age_seconds": round(now - tick.received_at, 1),
            }
            if tick
            else None,
            "stale_threshold_s": RTI_STALE_THRESHOLD_S,
            "poll_interval_s": self._poll_interval,
            "timestamp": now,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _push(self, tick: RtiTick) -> None:
        with self._lock:
            self._ticks.append(tick)
            if len(self._ticks) > RTI_BUFFER_SIZE:
                self._ticks.pop(0)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                tick = self._adapter.fetch()
                if tick:
                    self._push(tick)
                    logger.debug(
                        "CFB RTI tick: %s = %.2f", tick.index_name, tick.value
                    )
                else:
                    logger.warning(
                        "CFB RTI adapter returned no tick (status: no_data)"
                    )
            except Exception as exc:
                logger.error("CFB RTI poll error: %s", exc)
            self._stop_event.wait(self._poll_interval)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Optional[SettlementRtiBuffer] = None
_singleton_lock = threading.Lock()


def get_rti_buffer() -> SettlementRtiBuffer:
    """Return (and lazily create) the process-wide ``SettlementRtiBuffer``."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = SettlementRtiBuffer()
        return _singleton


# ---------------------------------------------------------------------------
# Safety gate
# ---------------------------------------------------------------------------

class CfbRtiUnhealthyError(RuntimeError):
    """Raised when live trading is attempted with no healthy CFB RTI feed."""


def require_cfb_for_live_trading() -> None:
    """Enforce CFB RTI health before allowing live Kalshi trading.

    Behaviour
    ---------
    - Only active when ``KALSHI_ENV=live``.
    - Skipped when ``MERID_ALLOW_NULL_CFB=1`` (acknowledged bypass).
    - Uses the process-wide ``SettlementRtiBuffer`` singleton.
    - Raises ``CfbRtiUnhealthyError`` if no healthy tick is available.

    Raises
    ------
    CfbRtiUnhealthyError
        When ``KALSHI_ENV=live``, ``MERID_ALLOW_NULL_CFB`` is not set,
        and the RTI buffer has no healthy tick.
    """
    kalshi_env = os.getenv("KALSHI_ENV", "paper").lower()
    if kalshi_env != "live":
        return  # gate only active in live mode

    if os.getenv("MERID_ALLOW_NULL_CFB", "0") == "1":
        logger.warning(
            "MERID_ALLOW_NULL_CFB=1: bypassing CFB RTI health gate (non-prod only)"
        )
        return

    buf = get_rti_buffer()
    if not buf.is_healthy():
        raise CfbRtiUnhealthyError(
            "CFB RTI feed is unhealthy (no ticks received). "
            "Set MERID_CFB_RTI_ADAPTER=simulation for dev/paper, or "
            "configure MERID_CFB_RTI_POLL_URL for live. "
            "To bypass (non-prod only): set MERID_ALLOW_NULL_CFB=1."
        )
    logger.debug("CFB RTI healthy — %d ticks buffered", buf.tick_count)
