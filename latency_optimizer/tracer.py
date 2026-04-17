"""Latency tracing primitives for MERID workflows."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class LatencySpan:
    span_id: str
    category: str
    name: str
    start_ns: int
    end_ns: Optional[int] = None
    metadata: Dict[str, str] | None = None

    def close(self) -> None:
        if self.end_ns is None:
            self.end_ns = time.perf_counter_ns()

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_ns is None:
            return None
        return (self.end_ns - self.start_ns) / 1_000_000


class LatencyTracer:
    def __init__(self) -> None:
        self._local = threading.local()

    def _get_stack(self) -> List[LatencySpan]:
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def start_span(self, category: str, name: str, metadata: Optional[Dict[str, str]] = None) -> LatencySpan:
        span = LatencySpan(
            span_id=f"span_{time.perf_counter_ns()}",
            category=category,
            name=name,
            start_ns=time.perf_counter_ns(),
            metadata=metadata or {},
        )
        self._get_stack().append(span)
        return span

    def end_span(self, span: LatencySpan) -> None:
        span.close()
        stack = self._get_stack()
        if stack and stack[-1] is span:
            stack.pop()

    @contextmanager
    def span(self, category: str, name: str, metadata: Optional[Dict[str, str]] = None):
        span = self.start_span(category, name, metadata)
        try:
            yield span
        finally:
            self.end_span(span)

    def current_trace(self) -> List[LatencySpan]:
        return list(self._get_stack())


_tracer: Optional[LatencyTracer] = None
_tracer_lock = threading.Lock()


def get_latency_tracer() -> LatencyTracer:
    global _tracer
    if _tracer is None:
        with _tracer_lock:
            if _tracer is None:
                _tracer = LatencyTracer()
    return _tracer
