"""Tick-to-trade latency budgets and degraded-state detection.

2026-10-14 (HDD-aware): the production spindle delivers ~100-200ms random
I/O, so the system's failure mode is not "too many gates" — it is storage
latency leaking into the decision path.  This module collects stage
measurements (quote age at decision time, audit write wait/execution,
decision cycle duration), computes rolling stats, and exposes a
``latency_degraded`` flag so callers can shed verbose extras while the
disk is slow.  Observability only: nothing here gates trading.

Budgets (env-tunable):
  quote_age_at_decision_ms : MERID_LAT_QUOTE_AGE_MS        (default 500)
  decision_cycle_ms        : MERID_LAT_CYCLE_MS            (default 1500)
  audit_write_wait_ms      : MERID_LAT_WRITE_WAIT_MS       (default 250)
  audit_write_exec_ms      : MERID_LAT_WRITE_EXEC_MS       (default 250)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Tuple

logger = logging.getLogger(__name__)

_WINDOW = int(os.getenv("MERID_LAT_WINDOW", "200"))
_LOG_EVERY_S = float(os.getenv("MERID_LAT_LOG_EVERY_S", "60"))

_BUDGETS_MS = {
    "quote_age_at_decision_ms": float(
        os.getenv("MERID_LAT_QUOTE_AGE_MS", "500")
    ),
    "decision_cycle_ms": float(os.getenv("MERID_LAT_CYCLE_MS", "1500")),
    "audit_write_wait_ms": float(os.getenv("MERID_LAT_WRITE_WAIT_MS", "250")),
    "audit_write_exec_ms": float(os.getenv("MERID_LAT_WRITE_EXEC_MS", "250")),
}


def _p95(samples: Deque[float]) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = min(len(s) - 1, int(len(s) * 0.95))
    return s[idx]


class _LatencyBudget:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: Dict[str, Deque[float]] = {
            k: deque(maxlen=_WINDOW) for k in _BUDGETS_MS
        }
        self._exceed_counts: Dict[str, int] = {k: 0 for k in _BUDGETS_MS}
        self._total_counts: Dict[str, int] = {k: 0 for k in _BUDGETS_MS}
        self._degraded_reasons: List[str] = []
        self._degraded_since: float = 0.0
        self._last_emit: float = 0.0

    def record(self, stage: str, value_ms: float) -> None:
        """Record one stage measurement (ms).  No-op for unknown stages."""
        samples = self._samples.get(stage)
        if samples is None:
            return
        with self._lock:
            samples.append(value_ms)
            self._total_counts[stage] += 1
            if value_ms > _BUDGETS_MS[stage]:
                self._exceed_counts[stage] += 1
        self._evaluate()

    def _evaluate(self) -> None:
        """Recompute degraded state.  Degraded when any budgeted stage's
        p95 exceeds its budget with enough samples to mean it."""
        reasons: List[str] = []
        with self._lock:
            for stage, samples in self._samples.items():
                if len(samples) < 10:
                    continue
                p95 = _p95(samples)
                if p95 > _BUDGETS_MS[stage]:
                    reasons.append(f"{stage}:p95={p95:.0f}>{_BUDGETS_MS[stage]:.0f}")
            was = bool(self._degraded_reasons)
            self._degraded_reasons = reasons
            now = time.monotonic()
            if reasons and not was:
                self._degraded_since = now
                logger.warning(
                    "[LATENCY-DEGRADED] entering degraded state: %s",
                    ";".join(reasons),
                )
            elif not reasons and was:
                held = now - self._degraded_since
                self._degraded_since = 0.0
                logger.info(
                    "[LATENCY-DEGRADED] cleared after %.0fs",
                    held,
                )

    def degraded(self) -> bool:
        with self._lock:
            return bool(self._degraded_reasons)

    def degraded_reasons(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._degraded_reasons)

    def snapshot(self) -> Dict[str, object]:
        """Current per-stage stats for heartbeat embedding."""
        out: Dict[str, object] = {}
        with self._lock:
            for stage, samples in self._samples.items():
                n = len(samples)
                if not n:
                    continue
                out[stage] = {
                    "n": n,
                    "p95_ms": round(_p95(samples), 1),
                    "exceeds": self._exceed_counts[stage],
                }
            out["degraded"] = bool(self._degraded_reasons)
            out["degraded_reasons"] = list(self._degraded_reasons)
        return out

    def maybe_emit(self) -> None:
        """Throttled periodic [LATENCY-BUDGET] log line."""
        now = time.monotonic()
        if now - self._last_emit < _LOG_EVERY_S:
            return
        self._last_emit = now
        snap = self.snapshot()
        if not snap.get("degraded") and not any(
            k != "degraded" and k != "degraded_reasons" for k in snap
        ):
            return
        level = logging.WARNING if snap.get("degraded") else logging.INFO
        logger.log(level, "[LATENCY-BUDGET] %s", snap)


_INSTANCE = _LatencyBudget()


def record(stage: str, value_ms: float) -> None:
    _INSTANCE.record(stage, value_ms)


def latency_degraded() -> bool:
    return _INSTANCE.degraded()


def degraded_reasons() -> Tuple[str, ...]:
    return _INSTANCE.degraded_reasons()


def snapshot() -> Dict[str, object]:
    return _INSTANCE.snapshot()


def maybe_emit() -> None:
    _INSTANCE.maybe_emit()
