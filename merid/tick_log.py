"""§H1 Tick Log — structured per-tick metrics for long-run observability.

Appends one JSON line per tick to a JSONL file so you can:
  - Tail the log in real time
  - Analyze plan generation, execution rates, CQI drift over time
  - Feed into dashboards or alerting

Schema per tick:
  tick_number, timestamp, duration_ms, actions[],
  features{source, freshness}, cqi{domain→score},
  plans_generated, plans_executed, plans_blocked,
  arb_signals, reconciliation_discrepancies,
  execution_guard{kill_switch, throttle_pct},
  error (if any)
"""

from __future__ import annotations

import threading
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.tick_log")

DEFAULT_LOG_DIR = os.path.join("data", "logs")
DEFAULT_LOG_FILE = "merid_ticks.jsonl"


@dataclass
class TickRecord:
    """Structured record for a single loop tick."""
    tick_number: int = 0
    timestamp: float = 0.0
    duration_ms: float = 0.0
    actions: List[str] = field(default_factory=list)

    # Feature freshness
    feature_sources: Dict[str, str] = field(default_factory=dict)    # domain→"live"|"synthetic"
    feature_freshness: Dict[str, float] = field(default_factory=dict) # domain→avg_freshness

    # CQI
    cqi_scores: Dict[str, float] = field(default_factory=dict)       # domain→score

    # Plans
    plans_generated: int = 0
    plans_executed: int = 0
    plans_blocked: int = 0
    execution_details: List[Dict[str, Any]] = field(default_factory=list)

    # Arb
    arb_signals_found: int = 0

    # Reconciliation
    reconciliation_discrepancies: int = 0

    # Guard state
    kill_switch_active: bool = False
    throttle_pcts: Dict[str, float] = field(default_factory=dict)    # domain→throttle

    # Errors
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick": self.tick_number,
            "ts": self.timestamp,
            "duration_ms": round(self.duration_ms, 1),
            "actions": self.actions,
            "features": {
                "sources": self.feature_sources,
                "freshness": {k: round(v, 4) for k, v in self.feature_freshness.items()},
            },
            "cqi": {k: round(v, 4) for k, v in self.cqi_scores.items()},
            "plans": {
                "generated": self.plans_generated,
                "executed": self.plans_executed,
                "blocked": self.plans_blocked,
            },
            "execution": self.execution_details,
            "arb_signals": self.arb_signals_found,
            "reconciliation_discrepancies": self.reconciliation_discrepancies,
            "guard": {
                "kill_switch": self.kill_switch_active,
                "throttle": {k: round(v, 4) for k, v in self.throttle_pcts.items()},
            },
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


class TickLog:
    """Append-only JSONL logger for tick records.

    Usage:
        log = TickLog()
        log.append(record)
        recent = log.recent(20)
    """

    def __init__(self, log_dir: str = DEFAULT_LOG_DIR, log_file: str = DEFAULT_LOG_FILE):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / log_file
        self._in_memory: List[TickRecord] = []
        self._max_memory = 500

    @property
    def path(self) -> Path:
        return self._log_path

    def append(self, record: TickRecord):
        """Write a tick record to the JSONL file and memory buffer."""
        self._in_memory.append(record)
        if len(self._in_memory) > self._max_memory:
            self._in_memory = self._in_memory[-250:]

        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(record.to_json() + "\n")
        except Exception as e:
            logger.warning(f"Failed to write tick log: {e}")

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent tick records from memory."""
        return [r.to_dict() for r in self._in_memory[-limit:]]

    def summary(self) -> Dict[str, Any]:
        """Aggregate stats across recent ticks."""
        records = self._in_memory
        if not records:
            return {"ticks": 0}

        total = len(records)
        errors = sum(1 for r in records if r.error)
        avg_duration = sum(r.duration_ms for r in records) / total
        total_executed = sum(r.plans_executed for r in records)
        total_blocked = sum(r.plans_blocked for r in records)

        # Latest CQI
        latest_cqi = records[-1].cqi_scores if records else {}

        return {
            "ticks": total,
            "errors": errors,
            "error_rate": round(errors / total, 4) if total else 0,
            "avg_duration_ms": round(avg_duration, 1),
            "total_plans_executed": total_executed,
            "total_plans_blocked": total_blocked,
            "latest_cqi": latest_cqi,
            "log_file": str(self._log_path),
        }


def build_tick_record(tick_summary: Dict[str, Any]) -> TickRecord:
    """Build a TickRecord from the loop's tick summary dict."""
    record = TickRecord(
        tick_number=tick_summary.get("tick", 0),
        timestamp=time.time(),
        duration_ms=tick_summary.get("duration_ms", 0),
        actions=tick_summary.get("actions", []),
        cqi_scores=tick_summary.get("cqi_scores", {}),
        error=tick_summary.get("error", ""),
    )

    # Parse actions for plan/execution counts and feed operator session
    session = get_operator_session()
    for action in record.actions:
        if action.startswith("executed:"):
            record.plans_executed += 1
            parts = action.split(":")
            domain = parts[1] if len(parts) > 1 else "unknown"
            size = 0.0
            if len(parts) > 3:
                try:
                    size = float(parts[3])
                except (ValueError, IndexError):
                    logger.debug("silent catch in tick_log:185")
            session.record_execution(domain, size)
        elif action.startswith("blocked:"):
            record.plans_blocked += 1
            parts = action.split(":")
            domain = parts[1] if len(parts) > 1 else "unknown"
            session.record_block(domain)
        elif action.startswith("arb_scan:"):
            try:
                record.arb_signals_found = int(action.split(":")[1].replace("signals", ""))
            except (ValueError, IndexError):
                logger.debug("silent catch in tick_log:196")
        elif action.startswith("reconciled:"):
            try:
                record.reconciliation_discrepancies = int(action.split(":")[1].replace("discrepancies", ""))
            except (ValueError, IndexError):
                logger.debug("silent catch in tick_log:201")

    # Track CQI scores in session
    for domain, score in record.cqi_scores.items():
        session.record_cqi(domain, score)

    return record


# ── Operator Session Tracker ──────────────────────────────────────────

class OperatorSession:
    """Tracks domain-level plan/exec/CQI over an operator session.

    Use this to answer: "What did MERID do over the last N hours?"
    Data feeds into /api/v1/loop/tick-log/summary and operator dashboard.
    """

    def __init__(self):
        self._started_at = time.time()
        self._domain_execs: Dict[str, int] = {}     # domain → count executed
        self._domain_blocks: Dict[str, int] = {}    # domain → count blocked
        self._domain_usd: Dict[str, float] = {}     # domain → total USD executed
        self._cqi_history: List[Dict[str, Any]] = [] # [{ts, domain, score}]
        self._max_cqi_history = 2000

    def record_execution(self, domain: str, size_usd: float):
        self._domain_execs[domain] = self._domain_execs.get(domain, 0) + 1
        self._domain_usd[domain] = self._domain_usd.get(domain, 0.0) + size_usd

    def record_block(self, domain: str):
        self._domain_blocks[domain] = self._domain_blocks.get(domain, 0) + 1

    def record_cqi(self, domain: str, score: float):
        self._cqi_history.append({"ts": time.time(), "domain": domain, "score": round(score, 4)})
        if len(self._cqi_history) > self._max_cqi_history:
            self._cqi_history = self._cqi_history[-1000:]

    def summary(self) -> Dict[str, Any]:
        elapsed = time.time() - self._started_at
        return {
            "session_started": self._started_at,
            "elapsed_seconds": round(elapsed, 1),
            "domain_executions": dict(self._domain_execs),
            "domain_blocks": dict(self._domain_blocks),
            "domain_usd_executed": {k: round(v, 2) for k, v in self._domain_usd.items()},
            "cqi_snapshots": len(self._cqi_history),
        }

    def cqi_series(self, domain: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return CQI time series, optionally filtered by domain."""
        series = self._cqi_history
        if domain:
            series = [s for s in series if s["domain"] == domain]
        return series[-limit:]


# ── Singletons ────────────────────────────────────────────────────────

_tick_log: Optional[TickLog] = None
_tick_log_lock = threading.Lock()
_operator_session: Optional[OperatorSession] = None
_operator_session_lock = threading.Lock()


def get_tick_log() -> TickLog:
    global _tick_log
    if _tick_log is None:
        with _tick_log_lock:
            if _tick_log is None:
                _tick_log = TickLog()
    return _tick_log


def get_operator_session() -> OperatorSession:
    global _operator_session
    if _operator_session is None:
        with _operator_session_lock:
            if _operator_session is None:
                _operator_session = OperatorSession()
    return _operator_session
