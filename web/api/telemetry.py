"""Frontend Telemetry API — receives structured UI log events from the browser.

Endpoints:
  POST /api/v1/telemetry          — Ingest a single UiLogEntry from the frontend
  POST /api/v1/telemetry/batch    — Ingest multiple UiLogEntry events
  GET  /api/v1/telemetry/recent   — Recent UI error events (ring buffer)
  GET  /api/v1/telemetry/sli      — MERID frontend SLI summary

The UiLogEntry shape matches the frontend `utils/logger.ts` exactly so
`navigator.sendBeacon('/api/v1/telemetry', JSON.stringify(entry))` works
with zero transformation.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.telemetry")

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Models (mirrors frontend UiLogEntry) ─────────────────────────────

class UiLogEntry(BaseModel):
    """Structured log event from the frontend UI."""
    level: str = Field(..., description="error | warn | info")
    component: str = Field(..., description="React component or hook name")
    message: str = Field(..., description="Human-readable description")
    error: Optional[str] = Field(None, description="Error message string")
    stack: Optional[str] = Field(None, description="Error stack trace")
    context: Optional[Dict[str, Any]] = Field(None, description="Extra key-value context")
    timestamp: Optional[str] = Field(None, description="ISO-8601 from browser")
    correlation_id: Optional[str] = Field(None, description="Request correlation ID")


class UiLogBatch(BaseModel):
    """Batch of UI log entries."""
    entries: List[UiLogEntry]


# ── Ring buffer for recent UI errors ─────────────────────────────────

_UI_ERROR_BUFFER: Deque[Dict[str, Any]] = deque(maxlen=500)


# ── SLI counters ─────────────────────────────────────────────────────

class _SliCounters:
    """Simple in-memory SLI counters for frontend health."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.total_events: int = 0
        self.error_count: int = 0
        self.warn_count: int = 0
        self.info_count: int = 0
        self.component_errors: Dict[str, int] = {}
        self.window_start: float = time.time()
        self._recent_latencies: Deque[float] = deque(maxlen=200)

    def record(self, entry: UiLogEntry) -> None:
        self.total_events += 1
        if entry.level == "error":
            self.error_count += 1
            self.component_errors[entry.component] = (
                self.component_errors.get(entry.component, 0) + 1
            )
        elif entry.level == "warn":
            self.warn_count += 1
        else:
            self.info_count += 1

    def snapshot(self) -> Dict[str, Any]:
        elapsed = max(time.time() - self.window_start, 1.0)
        error_rate = self.error_count / elapsed if elapsed > 0 else 0.0
        top_components = sorted(
            self.component_errors.items(), key=lambda x: x[1], reverse=True
        )[:10]
        return {
            "window_seconds": round(elapsed, 1),
            "total_events": self.total_events,
            "error_count": self.error_count,
            "warn_count": self.warn_count,
            "info_count": self.info_count,
            "error_rate_per_sec": round(error_rate, 4),
            "top_error_components": [
                {"component": c, "count": n} for c, n in top_components
            ],
        }


_sli = _SliCounters()


# ── Helpers ───────────────────────────────────────────────────────────

def _ingest(entry: UiLogEntry, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Process a single UI log entry: log it, buffer it, update SLIs."""
    record = entry.model_dump()
    record["server_ts"] = datetime.now(timezone.utc).isoformat()
    record["correlation_id"] = correlation_id or entry.correlation_id or str(uuid.uuid4())

    # Structured log via backend logger
    log_msg = f"[UI:{entry.level.upper()}] {entry.component} — {entry.message}"
    if entry.level == "error":
        logger.error(log_msg)
    elif entry.level == "warn":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Buffer errors and warnings for the /recent endpoint
    if entry.level in ("error", "warn"):
        _UI_ERROR_BUFFER.append(record)

    # Update SLI counters
    _sli.record(entry)

    return record


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("")
async def ingest_telemetry(entry: UiLogEntry, request: Request) -> Dict[str, Any]:
    """Ingest a single UI log event.

    Accepts the exact UiLogEntry shape emitted by the frontend
    `utils/logger.ts` so `navigator.sendBeacon` works directly.
    """
    cid = request.headers.get("x-correlation-id")
    record = _ingest(entry, correlation_id=cid)
    return {"ok": True, "correlation_id": record["correlation_id"]}


@router.post("/batch")
async def ingest_telemetry_batch(
    batch: UiLogBatch, request: Request
) -> Dict[str, Any]:
    """Ingest multiple UI log events in one request."""
    cid = request.headers.get("x-correlation-id")
    count = 0
    for entry in batch.entries:
        _ingest(entry, correlation_id=cid)
        count += 1
    return {"ok": True, "ingested": count}


@router.get("/recent")
async def get_recent_ui_errors(
    limit: int = 50,
) -> Dict[str, Any]:
    """Return recent UI error/warning events from the ring buffer."""
    items = list(_UI_ERROR_BUFFER)[-limit:]
    items.reverse()  # newest first
    return {"events": items, "total_buffered": len(_UI_ERROR_BUFFER)}


@router.get("/sli")
async def get_frontend_sli() -> Dict[str, Any]:
    """Frontend SLI summary: error counts, error rate, top failing components."""
    return {"sli": _sli.snapshot()}


@router.post("/sli/reset")
async def reset_frontend_sli() -> Dict[str, Any]:
    """Reset SLI counters (e.g. after a deploy)."""
    _sli.reset()
    return {"ok": True, "message": "SLI counters reset"}


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus-compatible metrics endpoint.

    Returns SLI counters in Prometheus exposition format so Grafana,
    Prometheus, or any OpenMetrics-compatible scraper can ingest them
    without additional adapters.

    Scrape config example (prometheus.yml):
        - job_name: merid_ui
          metrics_path: /api/v1/telemetry/metrics
          static_configs:
            - targets: ['localhost:8011']
    """
    snap = _sli.snapshot()
    lines: List[str] = []

    # ── Counters ──────────────────────────────────────────────────
    lines.append("# HELP merid_ui_events_total Total UI telemetry events received.")
    lines.append("# TYPE merid_ui_events_total counter")
    lines.append(f'merid_ui_events_total {snap["total_events"]}')

    lines.append("# HELP merid_ui_errors_total Total UI error events.")
    lines.append("# TYPE merid_ui_errors_total counter")
    lines.append(f'merid_ui_errors_total {snap["error_count"]}')

    lines.append("# HELP merid_ui_warnings_total Total UI warning events.")
    lines.append("# TYPE merid_ui_warnings_total counter")
    lines.append(f'merid_ui_warnings_total {snap["warn_count"]}')

    lines.append("# HELP merid_ui_info_total Total UI info events.")
    lines.append("# TYPE merid_ui_info_total counter")
    lines.append(f'merid_ui_info_total {snap["info_count"]}')

    # ── Gauges ────────────────────────────────────────────────────
    lines.append("# HELP merid_ui_error_rate_per_sec Current UI error rate (errors/sec).")
    lines.append("# TYPE merid_ui_error_rate_per_sec gauge")
    lines.append(f'merid_ui_error_rate_per_sec {snap["error_rate_per_sec"]}')

    lines.append("# HELP merid_ui_buffer_size Current number of events in the ring buffer.")
    lines.append("# TYPE merid_ui_buffer_size gauge")
    lines.append(f"merid_ui_buffer_size {len(_UI_ERROR_BUFFER)}")

    # ── Per-component error breakdown ─────────────────────────────
    lines.append("# HELP merid_ui_component_errors_total Errors by React component.")
    lines.append("# TYPE merid_ui_component_errors_total counter")
    for item in snap["top_error_components"]:
        comp = item["component"].replace('"', '\\"')
        lines.append(f'merid_ui_component_errors_total{{component="{comp}"}} {item["count"]}')

    lines.append("")  # trailing newline required by exposition format
    body = "\n".join(lines)
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
