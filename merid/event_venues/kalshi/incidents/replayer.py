"""Incident replay harness for Kalshi stress scenarios."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from monitoring.kalshi_metrics import (
    record_kalshi_api_call,
    record_kalshi_order,
    record_kalshi_cb_trigger,
    set_kalshi_ws_connection_state,
    record_kalshi_ws_reconnect,
    set_kalshi_catalog_refresh_timestamp,
)

from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode

DEFAULT_WS_DISCONNECTED = "disconnected"
DEFAULT_WS_CONNECTED = "connected"


@dataclass
class IncidentOrder:
    timestamp: datetime
    request: Mapping[str, Any]
    response: Mapping[str, Any]


@dataclass
class IncidentFill:
    timestamp: datetime
    order_id: str
    price: float
    size: float


@dataclass
class IncidentScenario:
    id: str
    description: str
    time_range_start: datetime
    time_range_end: datetime
    orders: List[IncidentOrder] = field(default_factory=list)
    fills: List[IncidentFill] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    cb_events: List[Mapping[str, Any]] = field(default_factory=list)


def _parse_iso8601(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _epoch_seconds(value: str) -> float:
    return _parse_iso8601(value).timestamp()


def load_scenario(path: Path) -> IncidentScenario:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    def _orders(raw_orders: Iterable[Mapping[str, Any]]) -> List[IncidentOrder]:
        return [
            IncidentOrder(
                timestamp=_parse_iso8601(order["timestamp"]),
                request=order.get("request", {}),
                response=order.get("response", {}),
            )
            for order in raw_orders
        ]

    def _fills(raw_fills: Iterable[Mapping[str, Any]]) -> List[IncidentFill]:
        return [
            IncidentFill(
                timestamp=_parse_iso8601(fill["timestamp"]),
                order_id=fill["order_id"],
                price=fill["price"],
                size=fill["size"],
            )
            for fill in raw_fills
        ]

    time_range = raw.get("time_range", {})
    start = _parse_iso8601(time_range.get("start", datetime.now(timezone.utc).isoformat()))
    end = _parse_iso8601(time_range.get("end", datetime.now(timezone.utc).isoformat()))

    return IncidentScenario(
        id=raw["id"],
        description=raw.get("description", ""),
        time_range_start=start,
        time_range_end=end,
        orders=_orders(raw.get("orders", [])),
        fills=_fills(raw.get("fills", [])),
        metrics=raw.get("metrics", {}),
        cb_events=list(raw.get("cb_events", [])),
    )


class KalshiIncidentReplayer:
    def __init__(self, scenario: IncidentScenario):
        self.scenario = scenario
        self._cb_counter: Counter[str] = Counter()

    def replay_orders(self) -> None:
        for order in self.scenario.orders:
            status = order.response.get("status", "unknown")
            error_code = order.response.get("error_code")
            record_kalshi_order(
                mode="replay",
                status=status,
                error_code=error_code,
            )

    def replay_metrics(self) -> None:
        metrics = self.scenario.metrics

        for latency_ms in metrics.get("latency_ms", []):
            record_kalshi_api_call(
                method="replay",
                endpoint="latency_sample",
                latency_ms=float(latency_ms),
                success=True,
            )

        last_state: Optional[str] = None
        for ws_event in metrics.get("ws_events", []):
            state = ws_event.get("state", "").lower()
            connected = state == DEFAULT_WS_CONNECTED
            set_kalshi_ws_connection_state(connected)

            if state == DEFAULT_WS_CONNECTED and last_state == DEFAULT_WS_DISCONNECTED:
                record_kalshi_ws_reconnect()

            last_state = state

        for timestamp in metrics.get("catalog_refresh_timestamps", []):
            set_kalshi_catalog_refresh_timestamp(_epoch_seconds(timestamp))

    def replay_cb_events(self) -> None:
        for cb_event in self.scenario.cb_events:
            code_name = cb_event.get("error_code")
            try:
                code = KalshiOrderErrorCode[code_name] if code_name else KalshiOrderErrorCode.UNKNOWN
            except KeyError:
                code = KalshiOrderErrorCode.UNKNOWN

            record_kalshi_cb_trigger(code)
            self._cb_counter[code.name] += 1

    def generate_report(self) -> Dict[str, Any]:
        metrics = self.scenario.metrics
        cb_expected = len(self.scenario.cb_events)
        cb_observed = sum(self._cb_counter.values())

        return {
            "scenario_id": self.scenario.id,
            "description": self.scenario.description,
            "expected_cb_events": cb_expected,
            "observed_cb_events": cb_observed,
            "cb_triggers_by_error": dict(self._cb_counter),
            "ws_downtime_seconds": self._calculate_ws_downtime(),
            "max_catalog_age_seconds": self._calculate_catalog_age(),
            "divergences": [] if cb_expected == cb_observed else ["cb_count_mismatch"],
            "latency_samples": len(metrics.get("latency_ms", [])),
        }

    def _calculate_ws_downtime(self) -> float:
        events = self.scenario.metrics.get("ws_events", [])
        downtime = 0.0
        disconnected_at: Optional[datetime] = None

        for event in events:
            state = event.get("state", "").lower()
            timestamp = _parse_iso8601(event["timestamp"])

            if state == DEFAULT_WS_DISCONNECTED:
                disconnected_at = timestamp
            elif state == DEFAULT_WS_CONNECTED and disconnected_at:
                downtime += (timestamp - disconnected_at).total_seconds()
                disconnected_at = None

        return downtime

    def _calculate_catalog_age(self) -> float:
        timestamps = [
            _parse_iso8601(ts)
            for ts in self.scenario.metrics.get("catalog_refresh_timestamps", [])
        ]

        if not timestamps:
            return 0.0

        timestamps.sort()
        max_delta = 0.0

        for earlier, later in zip(timestamps, timestamps[1:]):
            delta = (later - earlier).total_seconds()
            if delta > max_delta:
                max_delta = delta

        tail_delta = (self.scenario.time_range_end - timestamps[-1]).total_seconds()
        return max(max_delta, tail_delta if tail_delta > 0 else 0.0)
