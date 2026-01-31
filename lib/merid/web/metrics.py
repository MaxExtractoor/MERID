from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict


class Metrics:
    """A tiny in-process metrics store with Prometheus-style text output.

    This avoids adding external dependencies while providing basic counters,
    gauges and summaries for observability in tests and local dev.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._summaries: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0.0, "sum": 0.0})

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            s = self._summaries[name]
            s["count"] += 1.0
            s["sum"] += float(value)

    def get_metrics_text(self) -> str:
        with self._lock:
            lines = []
            for k, v in self._counters.items():
                lines.append(f"# HELP {k} Counter metric")
                lines.append(f"# TYPE {k} counter")
                lines.append(f"{k} {int(v)}")
            for k, v in self._gauges.items():
                lines.append(f"# HELP {k} Gauge metric")
                lines.append(f"# TYPE {k} gauge")
                lines.append(f"{k} {v}")
            for k, s in self._summaries.items():
                lines.append(f"# HELP {k}_count Summary count")
                lines.append(f"# TYPE {k}_count counter")
                lines.append(f"{k}_count {int(s['count'])}")
                lines.append(f"# HELP {k}_sum Summary sum")
                lines.append(f"# TYPE {k}_sum counter")
                lines.append(f"{k}_sum {s['sum']}")
            return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._summaries.clear()


# module-level default metrics instance
metrics = Metrics()
