"""
§1 — Observation → Reasoning → Action Trace Persistence

For each agent step, persist a tuple:
  (inputs, tools_called, tool_outputs, reasoning_summary, chosen_action, timestamp)

Forces agents to reference concrete tool outputs in their reasoning.
"""

from __future__ import annotations

import time
import uuid
import sqlite3
import json
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.guardrails.trace")


@dataclass
class TraceStep:
    """One observation→reasoning→action step in an agent's execution."""
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    agent_id: str = ""
    depth: int = 0
    step_index: int = 0
    # Inputs the agent received
    inputs: Dict[str, Any] = field(default_factory=dict)
    # Tools called and their results
    tools_called: List[str] = field(default_factory=list)
    tool_outputs: List[Dict[str, Any]] = field(default_factory=list)
    # Agent's reasoning (must reference tool outputs)
    reasoning_summary: str = ""
    # Chosen action
    chosen_action: str = ""
    action_params: Dict[str, Any] = field(default_factory=dict)
    # Outcome
    outcome: str = ""  # "executed", "no_op", "escalated", "errored", "budget_exceeded"
    confidence: float = 0.0
    # Timing
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentTrace:
    """Full trace for one agent task execution (may span multiple steps)."""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    task_id: str = ""
    agent_id: str = ""
    scope: str = "paper"
    steps: List[TraceStep] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    terminal_state: str = ""  # "executed_safely", "no_op", "escalated", "errored", "budget_exceeded"

    def add_step(self, step: TraceStep) -> None:
        step.task_id = self.task_id
        step.agent_id = self.agent_id
        step.step_index = len(self.steps)
        self.steps.append(step)

    def finish(self, terminal_state: str) -> None:
        self.finished_at = time.time()
        self.terminal_state = terminal_state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "scope": self.scope,
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "terminal_state": self.terminal_state,
            "total_steps": len(self.steps),
            "total_duration_ms": round((self.finished_at - self.started_at) * 1000, 2) if self.finished_at else None,
        }


class TraceStore:
    """
    Persists agent traces to SQLite for audit, replay, and grounding verification.

    Thread-safe — uses a lock around writes.
    """

    def __init__(self, db_path: str = "data/agent_traces.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        logger.info("TraceStore initialized: %s", db_path)

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id   TEXT PRIMARY KEY,
                    task_id    TEXT,
                    agent_id   TEXT,
                    scope      TEXT,
                    started_at REAL,
                    finished_at REAL,
                    terminal_state TEXT,
                    total_steps INTEGER,
                    data       TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_steps (
                    step_id    TEXT PRIMARY KEY,
                    trace_id   TEXT,
                    task_id    TEXT,
                    agent_id   TEXT,
                    step_index INTEGER,
                    tools_called TEXT,
                    chosen_action TEXT,
                    outcome    TEXT,
                    confidence REAL,
                    timestamp  REAL,
                    duration_ms REAL,
                    data       TEXT,
                    FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_task ON traces(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_agent ON traces(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_trace ON trace_steps(trace_id)")
            conn.commit()
            conn.close()

    def save_trace(self, trace: AgentTrace) -> None:
        """Persist a completed trace."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO traces
                       (trace_id, task_id, agent_id, scope, started_at, finished_at,
                        terminal_state, total_steps, data)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (trace.trace_id, trace.task_id, trace.agent_id, trace.scope,
                     trace.started_at, trace.finished_at, trace.terminal_state,
                     len(trace.steps), json.dumps(trace.to_dict())),
                )
                for step in trace.steps:
                    conn.execute(
                        """INSERT OR REPLACE INTO trace_steps
                           (step_id, trace_id, task_id, agent_id, step_index,
                            tools_called, chosen_action, outcome, confidence,
                            timestamp, duration_ms, data)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (step.step_id, trace.trace_id, step.task_id, step.agent_id,
                         step.step_index, json.dumps(step.tools_called),
                         step.chosen_action, step.outcome, step.confidence,
                         step.timestamp, step.duration_ms, json.dumps(step.to_dict())),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT data FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()

    def get_traces_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT data FROM traces WHERE task_id = ? ORDER BY started_at", (task_id,)
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        finally:
            conn.close()

    def get_recent_traces(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        try:
            if agent_id:
                rows = conn.execute(
                    "SELECT data FROM traces WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data FROM traces ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [json.loads(r[0]) for r in rows]
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self._db_path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            by_state = {}
            for row in conn.execute("SELECT terminal_state, COUNT(*) FROM traces GROUP BY terminal_state"):
                by_state[row[0] or "unknown"] = row[1]
            return {"total_traces": total, "by_terminal_state": by_state}
        finally:
            conn.close()


# ── Singleton ────────────────────────────────────────────────────────

_trace_store: Optional[TraceStore] = None


def get_trace_store() -> TraceStore:
    global _trace_store
    if _trace_store is None:
        _trace_store = TraceStore()
    return _trace_store
