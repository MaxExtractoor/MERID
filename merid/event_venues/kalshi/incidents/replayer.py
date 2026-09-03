"""Incident replay harness for Kalshi stress scenarios."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from monitoring.kalshi_metrics import (
    record_kalshi_api_call,
    record_kalshi_order,
    record_kalshi_cb_trigger,
    set_kalshi_ws_connection_state,
    record_kalshi_ws_reconnect,
    set_kalshi_catalog_refresh_timestamp,
)

from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode
from merid.resilience.result import OperationResult

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
class IncidentPosition:
    """Position seed for an exit-order incident replay."""

    market_id: str
    series_ticker: str
    side: str
    size: Any
    avg_entry_price_cents: int
    entry_fill_price_cents: int
    take_profit_price_cents: Optional[int] = None
    stop_loss_price_cents: Optional[int] = None
    risk_params_state: str = "original_persisted"
    risk_params_schema_version: int = 2
    client_order_id: Optional[str] = None
    entry_fill_id: Optional[str] = None
    entry_intent_id: Optional[str] = None
    position_id: Optional[str] = None
    position_key: Optional[str] = None


@dataclass
class IncidentExitAttempt:
    """Durable exit-order attempt seed for an incident replay."""

    exit_intent_id: str
    position_key: str
    ticker: str
    reason: str
    client_order_id: str
    requested_quantity: int
    requested_limit_cents: Optional[int] = None
    exchange_order_id: Optional[str] = None
    initial_state: str = "SUBMISSION_UNKNOWN"


@dataclass
class IncidentExchangeEvidence:
    """Exchange state returned during reconciliation."""

    client_order_id: Optional[str] = None
    order_status: str = "not_found"
    order_id: Optional[str] = None
    order_price: Optional[float] = None
    open_orders: List[Any] = field(default_factory=list)
    exchange_position_size: Optional[Any] = None
    position_market_id: Optional[str] = None


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
    positions: List[IncidentPosition] = field(default_factory=list)
    exit_attempts: List[IncidentExitAttempt] = field(default_factory=list)
    exchange_evidence: List[IncidentExchangeEvidence] = field(default_factory=list)


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

    def _positions(raw_positions: Iterable[Mapping[str, Any]]) -> List[IncidentPosition]:
        return [
            IncidentPosition(
                market_id=p["market_id"],
                series_ticker=p.get("series_ticker", ""),
                side=p.get("side", "yes"),
                size=p.get("size", 1),
                avg_entry_price_cents=int(p.get("avg_entry_price_cents", 0)),
                entry_fill_price_cents=int(p.get("entry_fill_price_cents", 0)),
                take_profit_price_cents=p.get("take_profit_price_cents"),
                stop_loss_price_cents=p.get("stop_loss_price_cents"),
                risk_params_state=p.get("risk_params_state", "original_persisted"),
                risk_params_schema_version=int(p.get("risk_params_schema_version", 2)),
                client_order_id=p.get("client_order_id"),
                entry_fill_id=p.get("entry_fill_id"),
                entry_intent_id=p.get("entry_intent_id"),
                position_id=p.get("position_id"),
                position_key=p.get("position_key"),
            )
            for p in raw_positions
        ]

    def _exit_attempts(raw_attempts: Iterable[Mapping[str, Any]]) -> List[IncidentExitAttempt]:
        return [
            IncidentExitAttempt(
                exit_intent_id=a["exit_intent_id"],
                position_key=a["position_key"],
                ticker=a["ticker"],
                reason=a.get("reason", "take_profit"),
                client_order_id=a["client_order_id"],
                requested_quantity=int(a.get("requested_quantity", 0)),
                requested_limit_cents=a.get("requested_limit_cents"),
                exchange_order_id=a.get("exchange_order_id"),
                initial_state=a.get("initial_state", "SUBMISSION_UNKNOWN"),
            )
            for a in raw_attempts
        ]

    def _exchange_evidence(raw_evidence: Any) -> List[IncidentExchangeEvidence]:
        if raw_evidence is None:
            return []
        if isinstance(raw_evidence, dict):
            raw_evidence = [raw_evidence]
        return [
            IncidentExchangeEvidence(
                client_order_id=e.get("client_order_id"),
                order_status=e.get("order_status", "not_found"),
                order_id=e.get("order_id"),
                order_price=e.get("order_price"),
                open_orders=e.get("open_orders", []),
                exchange_position_size=e.get("exchange_position_size"),
                position_market_id=e.get("position_market_id"),
            )
            for e in raw_evidence
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
        positions=_positions(raw.get("positions", [])),
        exit_attempts=_exit_attempts(raw.get("exit_attempts", [])),
        exchange_evidence=_exchange_evidence(raw.get("exchange_evidence")),
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


class ExitOrderIncidentReplay:
    """End-to-end replay helper for exit-order attempt lifecycle incidents.

    Seeds a durable ``ExitOrderAttempt``, rehydrates it through ``PositionMonitor``
    on a simulated process restart, and drives the reconciliation path against
    staged exchange evidence.
    """

    def __init__(
        self,
        scenario: IncidentScenario,
        store: Optional[Any] = None,
        monitor: Optional[Any] = None,
    ):
        self.scenario = scenario
        self.monitor = monitor
        self._position_id: Optional[str] = None
        self._client_order_id: Optional[str] = None
        self._position_key: Optional[str] = None

        if store is None:
            from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore

            self.store = OrderAttemptStore()
        else:
            self.store = store

    def seed_exit_attempt(self, attempt: Optional[IncidentExitAttempt] = None) -> Any:
        """Seed the durable store with an ExitOrderAttempt in the scenario's initial state."""
        from merid.event_venues.kalshi.order_attempt_store import (
            ExitOrderAttemptState,
            ExitOrderAttemptRecord,
        )

        if attempt is None:
            if not self.scenario.exit_attempts:
                raise ValueError("Scenario has no exit_attempts")
            attempt = self.scenario.exit_attempts[0]

        record = self.store.create_exit_attempt(
            exit_intent_id=attempt.exit_intent_id,
            position_key=attempt.position_key,
            ticker=attempt.ticker,
            reason=attempt.reason,
            client_order_id=attempt.client_order_id,
            requested_quantity=attempt.requested_quantity,
            requested_limit_cents=attempt.requested_limit_cents,
            exchange_order_id=attempt.exchange_order_id,
        )
        self._client_order_id = attempt.client_order_id
        self._position_key = attempt.position_key

        target = ExitOrderAttemptState(attempt.initial_state)
        if target == ExitOrderAttemptState.INTENT_PERSISTED:
            return record

        record = self.store.transition_exit_attempt(
            record.attempt_id,
            ExitOrderAttemptState.SUBMITTING.value,
            actor="replayer",
            reason="seed_submitting",
        )
        if record is None:
            raise RuntimeError("Failed to transition seeded attempt to SUBMITTING")

        if target == ExitOrderAttemptState.SUBMITTING:
            return record

        record = self.store.transition_exit_attempt(
            record.attempt_id,
            target.value,
            actor="replayer",
            reason=f"seed_{target.value.lower()}",
        )
        if record is None:
            raise RuntimeError(f"Failed to transition seeded attempt to {target.value}")

        return record

    def build_position(self, position: Optional[IncidentPosition] = None) -> Any:
        """Build the scenario's Position and add it to a PositionMonitor."""
        from merid.position_management.position import (
            Position,
            PositionSide,
            canonical_position_key,
        )
        from merid.position_management.position_monitor import PositionMonitor

        if self.monitor is None:
            self.monitor = PositionMonitor()

        if position is None:
            if not self.scenario.positions:
                raise ValueError("Scenario has no positions")
            position = self.scenario.positions[0]

        pos_id = position.position_id or position.market_id
        pos = Position(
            position_id=pos_id,
            market_id=position.market_id,
            series_ticker=position.series_ticker,
            side=PositionSide(position.side),
            size=Decimal(str(position.size)),
            avg_entry_price_cents=position.avg_entry_price_cents,
            entry_fill_price_cents=position.entry_fill_price_cents,
            take_profit_price_cents=position.take_profit_price_cents,
            stop_loss_price_cents=position.stop_loss_price_cents,
            risk_params_state=position.risk_params_state,
            risk_params_schema_version=position.risk_params_schema_version,
            client_order_id=position.client_order_id,
            entry_fill_id=position.entry_fill_id,
            entry_intent_id=position.entry_intent_id,
        )
        if pos.position_key is None:
            pos.position_key = canonical_position_key(pos.market_id)
            pos.known_aliases = [pos.market_id]

        self.monitor.add_position(pos)
        self._position_id = pos_id
        return pos

    async def reconcile(self, evidence: Optional[IncidentExchangeEvidence] = None) -> Any:
        """Drive ``PositionMonitor._reconcile_exit_intent`` with staged exchange evidence."""
        from unittest.mock import patch

        if self.monitor is None:
            raise RuntimeError("Call build_position() before reconcile()")
        if self._client_order_id is None or self._position_id is None:
            raise RuntimeError("Call seed_exit_attempt() and build_position() before reconcile()")

        if evidence is None:
            if not self.scenario.exchange_evidence:
                raise ValueError("Scenario has no exchange_evidence")
            evidence = self.scenario.exchange_evidence[0]

        fake_client = self._build_fake_client(evidence)

        with patch("merid.event_venues.kalshi.client.get_kalshi_client", return_value=fake_client):
            await self.monitor._reconcile_exit_intent(
                self._position_id,
                self._client_order_id,
            )

        from merid.event_venues.kalshi.order_attempt_store import ExitOrderAttemptRecord

        return self.store.get_exit_attempt_by_client_order_id(self._client_order_id)

    def _build_fake_client(self, evidence: IncidentExchangeEvidence) -> Any:
        """Return a fake KalshiVenueClient that replays ``IncidentExchangeEvidence``."""

        position_market_id = evidence.position_market_id or self._position_id
        client_order_id = evidence.client_order_id or self._client_order_id

        class _FakeKalshiClient:
            def __init__(self, evidence: IncidentExchangeEvidence, position_market_id: str, client_order_id: str):
                self.evidence = evidence
                self.position_market_id = position_market_id
                self.client_order_id = client_order_id

            async def get_order_by_client_id_result(self, coid: str, market_id: Optional[str] = None) -> OperationResult:
                if self.client_order_id and coid != self.client_order_id:
                    return OperationResult.ok(data=None)
                if self.evidence.order_status in ("not_found", None):
                    return OperationResult.ok(data=None)

                order = SimpleNamespace(
                    status=self.evidence.order_status,
                    order_id=self.evidence.order_id or "ord-evidence",
                )
                if self.evidence.order_price is not None:
                    order.price = Decimal(str(self.evidence.order_price))
                return OperationResult.ok(data=order)

            async def get_open_orders(self, market_id: Optional[str] = None) -> List[Any]:
                return [SimpleNamespace() for _ in self.evidence.open_orders]

            async def get_positions(self) -> List[Any]:
                if self.evidence.exchange_position_size is None:
                    return []
                return [
                    SimpleNamespace(
                        market_id=self.position_market_id,
                        size=Decimal(str(self.evidence.exchange_position_size)),
                    )
                ]

            async def cancel_order_result(self, order_id: str, market_id: Optional[str] = None) -> OperationResult:
                return OperationResult.ok(data=True)

        return _FakeKalshiClient(evidence, position_market_id or "", client_order_id or "")
