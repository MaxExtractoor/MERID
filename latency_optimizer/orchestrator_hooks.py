"""Helper context managers to capture latency and emit telemetry."""
from __future__ import annotations

from utils.logger import get_logger
import time
from dataclasses import dataclass
from typing import Dict, Optional

from latency_optimizer.policies import OptimizationDecision, get_latency_policy
from latency_optimizer.registry import record_latency_decision
from latency_optimizer.telemetry import emit_latency_metric, emit_latency_counter
from latency_optimizer.tracer import LatencySpan, get_latency_tracer

logger = get_logger(__name__)


@dataclass
class LatencyProbe:
    domain: str
    workflow: str
    metadata: Dict[str, str]
    decision_key: Optional[str] = None
    span: Optional[LatencySpan] = None
    duration_ms: Optional[float] = None
    decision: Optional[OptimizationDecision] = None

    def __enter__(self) -> LatencyProbe:
        tracer = get_latency_tracer()
        self._start_ns = time.perf_counter_ns()
        self.span = tracer.start_span(
            category=self.domain,
            name=self.workflow,
            metadata=self.metadata,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        tracer = get_latency_tracer()
        if self.span is not None:
            tracer.end_span(self.span)
        self.duration_ms = (time.perf_counter_ns() - self._start_ns) / 1_000_000
        emit_latency_metric(
            name=f"{self.domain}.{self.workflow}",
            value_ms=self.duration_ms,
            tags=self.metadata,
        )
        emit_latency_counter(
            name=f"{self.domain}.{self.workflow}.count",
            tags=self.metadata,
        )
        policy = get_latency_policy()
        self.decision = policy.evaluate(self.domain, self.workflow, self.duration_ms)
        if self.decision:
            status_metric = (
                f"{self.domain}.{self.workflow}.status.{self.decision.status}"
            )
            emit_latency_counter(status_metric, tags=self.metadata)
            if self.decision_key:
                record_latency_decision(self.decision_key, self.decision)
            if self.decision.fallback:
                emit_latency_counter(
                    name=f"{self.domain}.{self.workflow}.fallback",
                    tags=self.metadata,
                )
                logger.info(
                    "Latency fallback suggested domain=%s workflow=%s status=%s fallback=%s",
                    self.domain,
                    self.workflow,
                    self.decision.status,
                    self.decision.fallback.strategy_id,
                )


def record_dev_swarm_command(metadata: Dict[str, str], *, decision_key: Optional[str] = None) -> LatencyProbe:
    return LatencyProbe(
        domain="dev_swarm",
        workflow="command_execution",
        metadata=metadata,
        decision_key=decision_key,
    )


def record_llm_request(metadata: Dict[str, str], *, decision_key: Optional[str] = None) -> LatencyProbe:
    return LatencyProbe(
        domain="llm",
        workflow="default_request",
        metadata=metadata,
        decision_key=decision_key,
    )


def record_trading_tick(metadata: Dict[str, str], *, decision_key: Optional[str] = None) -> LatencyProbe:
    return LatencyProbe(
        domain="trading",
        workflow="tick_to_order",
        metadata=metadata,
        decision_key=decision_key,
    )


def record_social_signal(metadata: Dict[str, str], *, decision_key: Optional[str] = None) -> LatencyProbe:
    return LatencyProbe(
        domain="social",
        workflow="signal_gate",
        metadata=metadata,
        decision_key=decision_key,
    )
