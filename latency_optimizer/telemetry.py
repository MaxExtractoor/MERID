"""Telemetry helpers for latency optimizer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from core.telemetry_manager import (
    DataClassification,
    MetricPoint,
    RetentionTier,
    TelemetryConfig,
    get_telemetry_manager,
)

LATENCY_STREAM = "latency"
_LATENCY_STREAM_REGISTERED = False


def ensure_latency_stream_registered() -> None:
    global _LATENCY_STREAM_REGISTERED
    if _LATENCY_STREAM_REGISTERED:
        return
    tm = get_telemetry_manager()
    tm.register_stream(
        TelemetryConfig(
            stream_name=LATENCY_STREAM,
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            sampling_rate=1.0,
            retention_days=30,
            metadata={"description": "Latency metrics and critical path analytics"},
        )
    )
    _LATENCY_STREAM_REGISTERED = True


def emit_latency_metric(
    name: str,
    value_ms: float,
    tags: Optional[Dict[str, str]] = None,
    *,
    unit: str = "ms",
) -> Optional[MetricPoint]:
    ensure_latency_stream_registered()
    tm = get_telemetry_manager()
    return tm.record_metric(
        stream_name=LATENCY_STREAM,
        metric_name=name,
        value=value_ms,
        tags=tags or {},
        unit=unit,
    )


def emit_latency_counter(
    name: str,
    *,
    value: float = 1.0,
    tags: Optional[Dict[str, str]] = None,
    unit: str = "count",
) -> Optional[MetricPoint]:
    """Emit a latency-related counter (e.g., fallback activations)."""

    ensure_latency_stream_registered()
    tm = get_telemetry_manager()
    return tm.record_metric(
        stream_name=LATENCY_STREAM,
        metric_name=name,
        value=value,
        tags=tags or {},
        unit=unit,
    )
