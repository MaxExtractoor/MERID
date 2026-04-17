"""
CFB RTI–aligned adapter (settlement reference for Kalshi crypto contracts).

Env:
- ``MERID_CFB_RTI_ADAPTER``: ``null`` | ``disabled`` | ``live`` | ``simulation`` | ``stub``
- ``MERID_ALLOW_NULL_CFB=1``: allow null adapter with KALSHI_ENV=live (emergency only)
- ``MERID_CFB_RTI_SIMULATE=1``: emit synthetic ~1 Hz ticks (dev/test; not official CFB)
- ``MERID_CFB_RTI_POLL_URL``: HTTPS JSON endpoint returning tick payload (see below), or ``file://...`` for simulation
- ``MERID_CFB_RTI_API_KEY``: optional Bearer token for poll URL
- ``MERID_CFB_RTI_POLL_INTERVAL``: seconds between polls (default 1.0)

Expected JSON (poll): ``{"ticks":[{"asset":"BTC","price":95000.0,"ts":1700000000.0},...]}``
Operator must point ``MERID_CFB_RTI_POLL_URL`` at their CF Benchmarks–licensed gateway.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from utils.logger import get_logger

logger = get_logger("merid.signals.cfb_rti_adapter")

_CFB_ADAPTER_BOOT_LOGGED = False


class CFBRTIConfigurationError(RuntimeError):
    """Raised when live CFB RTI is required but not configured."""


@dataclass
class SpotSample:
    price: float
    ts_utc: datetime
    source_id: str


@dataclass
class NormalizedRTITick:
    asset: str
    index_id: str
    price: float
    ts_utc: float


@runtime_checkable
class CFBRTIAdapter(Protocol):
    async def get_spot(self, asset: str) -> Optional[SpotSample]:
        ...


class NullCFBRTIAdapter:
    """Placeholder — no settlement RTI; use only with MERID_ALLOW_NULL_CFB or non-live."""

    async def get_spot(self, asset: str) -> Optional[SpotSample]:
        return None


class StubCFBRTIAdapter:
    """Returns a static diagnostic sample (not official settlement)."""

    async def get_spot(self, asset: str) -> Optional[SpotSample]:
        return SpotSample(
            price=1.0,
            ts_utc=datetime.now(timezone.utc),
            source_id="stub_cfb_rti",
        )


class LiveCFBRTIAdapter:
    """Live adapter: polls MERID_CFB_RTI_POLL_URL; caches last tick per asset."""

    def __init__(self) -> None:
        self.poll_url = os.environ.get("MERID_CFB_RTI_POLL_URL", "").strip()
        self.api_key = os.environ.get("MERID_CFB_RTI_API_KEY", "").strip()
        self.interval = float(os.environ.get("MERID_CFB_RTI_POLL_INTERVAL", "1.0"))
        self._last: Dict[str, NormalizedRTITick] = {}

    def is_configured(self) -> bool:
        return bool(self.poll_url) or os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1"

    def validate_or_raise(self) -> None:
        if not self.is_configured():
            raise CFBRTIConfigurationError(
                "LiveCFBRTIAdapter: set MERID_CFB_RTI_POLL_URL to your CFB-licensed "
                "gateway or MERID_CFB_RTI_SIMULATE=1 for non-production simulation."
            )

    async def get_spot(self, asset: str) -> Optional[SpotSample]:
        t = self._last.get(asset.upper())
        if not t:
            return None
        return SpotSample(price=t.price, ts_utc=datetime.fromtimestamp(t.ts_utc, tz=timezone.utc), source_id=t.index_id)

    def cache_tick(self, tick: NormalizedRTITick) -> None:
        self._last[tick.asset.upper()] = tick

    async def poll_once(self, httpx_client: Any) -> List[NormalizedRTITick]:
        """One HTTP poll; parses ticks from JSON body."""
        if os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1":
            return []

        if self.poll_url.lower().startswith("file://"):
            path = self.poll_url[7:]
            with open(path, "r", encoding="utf-8") as f:
                body = __import__("json").load(f)
        else:
            headers: Dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            r = await httpx_client.get(self.poll_url, headers=headers, timeout=20.0)
            r.raise_for_status()
            body = r.json()
        ticks: List[NormalizedRTITick] = []
        for row in body.get("ticks", body.get("indices", [])):
            asset = str(row.get("asset") or row.get("symbol") or "").upper()
            if not asset:
                continue
            px = float(row.get("price") or row.get("value") or row.get("px"))
            ts = row.get("ts") or row.get("time") or row.get("t")
            if ts is None:
                continue
            ts_f = float(ts)
            if ts_f > 1e12:
                ts_f /= 1000.0
            idx = str(row.get("index_id") or row.get("id") or asset)
            nt = NormalizedRTITick(asset=asset, index_id=idx, price=px, ts_utc=ts_f)
            ticks.append(nt)
            self.cache_tick(nt)
        return ticks


def get_cfb_rti_adapter() -> CFBRTIAdapter:
    """Return the active adapter and log once which implementation is in use."""
    global _CFB_ADAPTER_BOOT_LOGGED
    mode_raw = os.environ.get("MERID_CFB_RTI_ADAPTER")
    mode = (mode_raw or "null").strip().lower()
    sim = os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1"
    poll_url = os.environ.get("MERID_CFB_RTI_POLL_URL", "").strip()

    # Safe inference: if operator set simulate flag or a poll URL but forgot adapter mode,
    # infer a consistent explicit mode instead of blocking forever.
    if mode_raw is None or mode in ("none", ""):
        if sim:
            mode = "simulation"
        elif poll_url.lower().startswith("file://"):
            mode = "simulation"
        elif poll_url:
            mode = "live"
        else:
            mode = "null"
    if mode not in ("null", "disabled", "live", "simulation", "stub"):
        logger.warning("MERID_CFB_RTI_ADAPTER=%r invalid — using null", mode)
        mode = "null"

    if mode == "live":
        impl: CFBRTIAdapter = LiveCFBRTIAdapter()
    elif mode == "simulation":
        # Explicitly non-live CFB mode. The feed loop can use MERID_CFB_RTI_SIMULATE=1
        # for synthetic ticks, or MERID_CFB_RTI_POLL_URL=file://... for file-backed ticks.
        impl = LiveCFBRTIAdapter()
    elif mode == "stub":
        impl = StubCFBRTIAdapter()
    else:
        impl = NullCFBRTIAdapter()

    if not _CFB_ADAPTER_BOOT_LOGGED:
        _CFB_ADAPTER_BOOT_LOGGED = True
        k_env = os.environ.get("KALSHI_ENV", "demo").strip().lower()
        allow_null = os.environ.get("MERID_ALLOW_NULL_CFB", "").strip() == "1"
        logger.warning(
            "CFB_RTI_ADAPTER_BOOT MERID_CFB_RTI_ADAPTER=%s implementation=%s kalshi_env=%s MERID_ALLOW_NULL_CFB=%s",
            mode,
            type(impl).__name__,
            k_env,
            allow_null,
        )
        if k_env == "live" and isinstance(impl, NullCFBRTIAdapter) and not allow_null:
            logger.error(
                "CFB_RTI_ADAPTER: Null implementation while KALSHI_ENV=live — set "
                "MERID_CFB_RTI_ADAPTER=live with MERID_CFB_RTI_POLL_URL, MERID_ALLOW_NULL_CFB=1, or use demo."
            )
    return impl


def reset_cfb_rti_adapter_boot_log() -> None:
    global _CFB_ADAPTER_BOOT_LOGGED
    _CFB_ADAPTER_BOOT_LOGGED = False


def require_cfb_for_live_trading() -> None:
    """Hard validation before RTI-settled trading in Kalshi live."""
    k_env = os.environ.get("KALSHI_ENV", "demo").strip().lower()
    if k_env != "live":
        return
    mode_raw = os.environ.get("MERID_CFB_RTI_ADAPTER")
    mode = (mode_raw or "null").strip().lower()
    allow = os.environ.get("MERID_ALLOW_NULL_CFB", "").strip() == "1"
    sim = os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1"
    if allow:
        return
    if mode in ("", "none"):
        mode = "null"

    # Safe inference: treat SIMULATE=1 as an explicit non-live choice even if adapter isn't set.
    # Likewise, file:// implies simulation, and a non-empty poll URL implies live intent.
    if mode_raw is None or mode in ("null", "disabled"):
        poll_url = os.environ.get("MERID_CFB_RTI_POLL_URL", "").strip()
        if sim:
            mode = "simulation"
        elif poll_url.lower().startswith("file://"):
            mode = "simulation"
        elif poll_url:
            mode = "live"

    if mode in ("null", "disabled"):
        raise CFBRTIConfigurationError(
            "KALSHI_ENV=live requires an explicit CFB RTI mode. Set one of:\n"
            "- MERID_CFB_RTI_ADAPTER=live and MERID_CFB_RTI_POLL_URL=https://...\n"
            "- MERID_CFB_RTI_ADAPTER=simulation (optionally MERID_CFB_RTI_POLL_URL=file://... or MERID_CFB_RTI_SIMULATE=1)\n"
            "- MERID_ALLOW_NULL_CFB=1 (explicitly accept no CFB RTI; not recommended)"
        )

    if mode == "simulation":
        adapter = LiveCFBRTIAdapter()
        has_file_url = adapter.poll_url.lower().startswith("file://")
        if not sim and not has_file_url and not adapter.poll_url:
            raise CFBRTIConfigurationError(
                "MERID_CFB_RTI_ADAPTER=simulation requires either MERID_CFB_RTI_SIMULATE=1 "
                "or MERID_CFB_RTI_POLL_URL=file://... (or an https poll url)."
            )
        return

    if mode == "live":
        adapter = LiveCFBRTIAdapter()
        # In live mode we require an explicit URL; simulation ticks are allowed only if the operator
        # deliberately opts into MERID_CFB_RTI_SIMULATE=1.
        if not adapter.poll_url and not sim:
            raise CFBRTIConfigurationError(
                "MERID_CFB_RTI_ADAPTER=live requires MERID_CFB_RTI_POLL_URL=https://... "
                "(or set MERID_CFB_RTI_SIMULATE=1 for non-production simulation)."
            )
        return

    if mode == "stub":
        return

    raise CFBRTIConfigurationError(f"MERID_CFB_RTI_ADAPTER={mode!r} is not a supported mode for KALSHI_ENV=live")
