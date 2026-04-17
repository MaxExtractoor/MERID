"""CFB RTI Feed status, settlement health, and adapter info endpoints.

Pipeline stage: DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT

Endpoints:
- GET /api/v1/rti/feed/status   — RTIFeedService metrics (up, gap, ticks, last_error)
- GET /api/v1/rti/settlement/health — Per-market settlement window health (60-slot RTI grids)
- GET /api/v1/rti/adapter/info  — Adapter mode, poll URL (masked), simulator flag
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from utils.logger import get_logger

logger = get_logger("merid.web.api.rti_feed_api")

router = APIRouter(prefix="/api/v1/rti", tags=["rti", "settlement", "kalshi"])


@router.get("/feed/status")
async def get_rti_feed_status() -> Dict[str, Any]:
    """RTI feed loop health: up flag, tick gap, ingestion count, last error."""
    try:
        from merid.data.rti_feed_service import get_rti_feed_service
        svc = get_rti_feed_service()
        m = svc.metrics
        return {
            "up": m.up,
            "last_tick_ts": m.last_tick_ts or None,
            "gap_seconds": round(m.gap_seconds, 3),
            "ticks_ingested": m.ticks_ingested,
            "last_error": m.last_error or None,
            "adapter_mode": os.environ.get("MERID_CFB_RTI_ADAPTER", "null"),
            "stale_threshold_seconds": float(os.environ.get("MERID_RTI_STALE_SECONDS", "5.0")),
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.warning("rti_feed_status error: %s", exc)
        return JSONResponse(status_code=503, content={"error": str(exc), "up": False})


@router.get("/settlement/health")
async def get_settlement_health() -> Dict[str, Any]:
    """Per-market RTI settlement window health for all registered buffers.

    Each market entry shows:
    - filled_count / 60  (RTI slots received in settlement minute)
    - seconds_to_expiry
    - is_settlement_grade  (True when all 60 slots filled)
    - alert_level: ok | warn | critical
    """
    try:
        from merid.data.settlement_observability import settlement_health_summary
        return settlement_health_summary()
    except Exception as exc:
        logger.warning("settlement_health error: %s", exc)
        return JSONResponse(status_code=503, content={"error": str(exc), "buffers": []})


@router.get("/adapter/info")
async def get_adapter_info() -> Dict[str, Any]:
    """CFB RTI adapter configuration — mode, poll URL (host only, masked), flags."""
    mode = os.environ.get("MERID_CFB_RTI_ADAPTER", "null").strip().lower()
    poll_url_raw = os.environ.get("MERID_CFB_RTI_POLL_URL", "").strip()
    # Mask credentials / path — show only scheme + host
    poll_url_display = ""
    if poll_url_raw:
        try:
            from urllib.parse import urlparse
            p = urlparse(poll_url_raw)
            poll_url_display = f"{p.scheme}://{p.netloc}/…" if p.netloc else poll_url_raw[:30] + "…"
        except Exception:
            poll_url_display = poll_url_raw[:20] + "…"

    sim = os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1"
    allow_null = os.environ.get("MERID_ALLOW_NULL_CFB", "").strip() == "1"
    kalshi_env = os.environ.get("KALSHI_ENV", "demo").strip().lower()

    try:
        from merid.signals.cfb_rti_adapter import get_cfb_rti_adapter
        adapter = get_cfb_rti_adapter()
        impl_name = type(adapter).__name__
    except Exception as exc:
        impl_name = f"error:{exc}"

    live_ready = (
        mode in ("live", "simulation", "stub")
        or (allow_null and kalshi_env == "live")
    )

    return {
        "adapter_mode": mode,
        "implementation": impl_name,
        "poll_url_masked": poll_url_display or None,
        "simulate_flag": sim,
        "allow_null_cfb": allow_null,
        "kalshi_env": kalshi_env,
        "live_ready": live_ready,
        "poll_interval_seconds": float(os.environ.get("MERID_CFB_RTI_POLL_INTERVAL", "1.0")),
        "timestamp": time.time(),
    }


@router.get("/metrics/assets")
async def get_rti_asset_metrics() -> Dict[str, Any]:
    """Per-asset RTI metrics: current price, 60s SMA, realized vol, settlement buffer status."""
    try:
        from merid.risk.crypto_rti_monitor import get_global_crypto_rti_monitor
        mon = get_global_crypto_rti_monitor()
        assets = ("BTC", "ETH", "SOL", "XRP", "DOGE")
        data: Dict[str, Any] = {}
        for asset in assets:
            m = mon.get_rti_metrics(asset)
            if not m:
                continue
            data[asset.lower()] = {
                "rti_current": m.get("rti_current", 0.0),
                "rti_60s_sma": round(m.get("rti_60s_sma", 0.0), 4),
                "rti_60s_vol": round(m.get("rti_60s_vol", 0.0), 6),
            }
        return {"data": data, "timestamp": time.time(), "source": "cfb_rti_monitor"}
    except Exception as exc:
        logger.warning("rti_asset_metrics error: %s", exc)
        return JSONResponse(status_code=503, content={"error": str(exc), "data": {}})
