"""LLM governance models + persistence for instrumentation and guardrails."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.llm.governance")


class LLMRole(str, Enum):
    DEV_SWARM = "dev_swarm"
    COGNITIVE = "cognitive"
    SPORTS = "sports"
    OPS = "ops"
    RESEARCH = "research"
    TRADING = "trading"


@dataclass
class LLMTrace:
    id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    prompt_version: str = ""
    model_name: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tools_used: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    status: str = "completed"
    error: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"llmtr-{uuid.uuid4().hex[:12]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tools_used": self.tools_used,
            "latency_ms": round(self.latency_ms, 2),
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass
class ToolCallRecord:
    id: str = ""
    trace_id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    tool_name: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    input_size: int = 0
    output_size: int = 0
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"llmtool-{uuid.uuid4().hex[:12]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "role": self.role.value,
            "tool_name": self.tool_name,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "input_size": self.input_size,
            "output_size": self.output_size,
            "created_at": self.created_at,
        }


@dataclass
class GuardrailEvent:
    id: str = ""
    trace_id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    event_type: str = ""
    reason: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"llmguard-{uuid.uuid4().hex[:12]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "role": self.role.value,
            "event_type": self.event_type,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass
class PromptVersion:
    id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    name: str = ""
    version: int = 1
    content: str = ""
    created_at: float = 0.0
    created_by: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"llmprompt-{uuid.uuid4().hex[:12]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "name": self.name,
            "version": self.version,
            "content": self.content,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


_DEFAULT_DB = os.path.join("data", "llm_governance.db")


class LLMGovernanceStore:
    """SQLite-backed store for LLM governance traces and guardrails."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.environ.get("MERID_LLM_GOVERNANCE_DB", _DEFAULT_DB)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._lock:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS llm_traces (
                        id TEXT PRIMARY KEY,
                        role TEXT NOT NULL DEFAULT '',
                        prompt_version TEXT NOT NULL DEFAULT '',
                        model_name TEXT NOT NULL DEFAULT '',
                        tokens_prompt INTEGER NOT NULL DEFAULT 0,
                        tokens_completion INTEGER NOT NULL DEFAULT 0,
                        tools_used TEXT NOT NULL DEFAULT '[]',
                        latency_ms REAL NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'completed',
                        error TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS llm_tool_calls (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT '',
                        tool_name TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'ok',
                        latency_ms REAL NOT NULL DEFAULT 0,
                        input_size INTEGER NOT NULL DEFAULT 0,
                        output_size INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS llm_guardrail_events (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT '',
                        event_type TEXT NOT NULL DEFAULT '',
                        reason TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS llm_prompt_versions (
                        id TEXT PRIMARY KEY,
                        role TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL DEFAULT '',
                        version INTEGER NOT NULL DEFAULT 1,
                        content TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL DEFAULT 0,
                        created_by TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_llm_traces_role ON llm_traces(role);
                    CREATE INDEX IF NOT EXISTS idx_llm_traces_created ON llm_traces(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_llm_tool_calls_tool ON llm_tool_calls(tool_name);
                    CREATE INDEX IF NOT EXISTS idx_llm_tool_calls_created ON llm_tool_calls(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_llm_guardrails_type ON llm_guardrail_events(event_type);
                    CREATE INDEX IF NOT EXISTS idx_llm_guardrails_created ON llm_guardrail_events(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_llm_prompts_role ON llm_prompt_versions(role);
                    """
                )
        logger.info("LLM governance DB initialized: %s", self._db_path)

    # ── Records ────────────────────────────────────────────────────

    def record_trace(self, trace: LLMTrace) -> LLMTrace:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_traces
                    (id, role, prompt_version, model_name, tokens_prompt, tokens_completion,
                     tools_used, latency_ms, status, error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.id,
                        trace.role.value,
                        trace.prompt_version,
                        trace.model_name,
                        trace.tokens_prompt,
                        trace.tokens_completion,
                        json.dumps(trace.tools_used),
                        trace.latency_ms,
                        trace.status,
                        trace.error,
                        trace.created_at,
                    ),
                )
        return trace

    def record_tool_call(self, record: ToolCallRecord) -> ToolCallRecord:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_tool_calls
                    (id, trace_id, role, tool_name, status, latency_ms, input_size, output_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.trace_id,
                        record.role.value,
                        record.tool_name,
                        record.status,
                        record.latency_ms,
                        record.input_size,
                        record.output_size,
                        record.created_at,
                    ),
                )
        return record

    def record_guardrail_event(self, event: GuardrailEvent) -> GuardrailEvent:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_guardrail_events
                    (id, trace_id, role, event_type, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.trace_id,
                        event.role.value,
                        event.event_type,
                        event.reason,
                        event.created_at,
                    ),
                )
        return event

    def register_prompt(self, prompt: PromptVersion) -> PromptVersion:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_prompt_versions
                    (id, role, name, version, content, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prompt.id,
                        prompt.role.value,
                        prompt.name,
                        prompt.version,
                        prompt.content,
                        prompt.created_at,
                        prompt.created_by,
                    ),
                )
        return prompt

    # ── Queries ────────────────────────────────────────────────────

    def list_traces(self, role: Optional[LLMRole] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM llm_traces"
        params: List[Any] = []
        if role:
            query += " WHERE role = ?"
            params.append(role.value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_trace(r).to_dict() for r in rows]

    def list_tool_calls(self, tool_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM llm_tool_calls"
        params: List[Any] = []
        if tool_name:
            query += " WHERE tool_name = ?"
            params.append(tool_name)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_tool_call(r).to_dict() for r in rows]

    def list_guardrail_events(
        self,
        event_type: Optional[str] = None,
        role: Optional[LLMRole] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM llm_guardrail_events"
        params: List[Any] = []
        clauses: List[str] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if role:
            clauses.append("role = ?")
            params.append(role.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_guardrail_event(r).to_dict() for r in rows]

    def list_prompts(self, role: Optional[LLMRole] = None, name: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM llm_prompt_versions"
        params: List[Any] = []
        clauses: List[str] = []
        if role:
            clauses.append("role = ?")
            params.append(role.value)
        if name:
            clauses.append("name = ?")
            params.append(name)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY name ASC, version DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_prompt(r).to_dict() for r in rows]

    def get_traces_summary(self, window_s: float = 86400.0) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, status, tokens_prompt, tokens_completion, latency_ms, created_at, error FROM llm_traces"
            ).fetchall()

        total_traces = len(rows)
        by_role: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        latencies: List[float] = []
        errors = 0
        traces_window = 0
        tokens_window = 0
        now = time.time()

        for row in rows:
            role = row["role"] or "unknown"
            status = row["status"] or "unknown"
            by_role[role] = by_role.get(role, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            if status not in {"completed", "ok", "success"} or row["error"]:
                errors += 1
            if row["latency_ms"]:
                latencies.append(float(row["latency_ms"]))
            if now - row["created_at"] <= window_s:
                traces_window += 1
                tokens_window += (row["tokens_prompt"] or 0) + (row["tokens_completion"] or 0)

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        error_rate = errors / total_traces if total_traces else 0.0

        return {
            "total_traces": total_traces,
            "traces_window": traces_window,
            "tokens_window": tokens_window,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate": round(error_rate, 4),
            "by_role": by_role,
            "by_status": by_status,
            "window_s": window_s,
        }

    def get_tools_summary(self, window_s: float = 86400.0) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tool_name, status, latency_ms, created_at FROM llm_tool_calls"
            ).fetchall()

        total_calls = len(rows)
        by_tool: Dict[str, int] = {}
        latencies: List[float] = []
        errors = 0
        calls_window = 0
        now = time.time()

        for row in rows:
            tool = row["tool_name"] or "unknown"
            by_tool[tool] = by_tool.get(tool, 0) + 1
            if row["status"] not in {"ok", "success"}:
                errors += 1
            if row["latency_ms"]:
                latencies.append(float(row["latency_ms"]))
            if now - row["created_at"] <= window_s:
                calls_window += 1

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        error_rate = errors / total_calls if total_calls else 0.0

        return {
            "total_calls": total_calls,
            "calls_window": calls_window,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate": round(error_rate, 4),
            "by_tool": by_tool,
            "window_s": window_s,
        }

    def get_guardrail_summary(self, window_s: float = 86400.0) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_type, created_at FROM llm_guardrail_events"
            ).fetchall()

        total_events = len(rows)
        by_type: Dict[str, int] = {}
        events_window = 0
        now = time.time()

        for row in rows:
            event_type = row["event_type"] or "unknown"
            by_type[event_type] = by_type.get(event_type, 0) + 1
            if now - row["created_at"] <= window_s:
                events_window += 1

        return {
            "total_events": total_events,
            "events_window": events_window,
            "by_type": by_type,
            "window_s": window_s,
        }

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> LLMTrace:
        return LLMTrace(
            id=row["id"],
            role=LLMRole(row["role"]) if row["role"] else LLMRole.RESEARCH,
            prompt_version=row["prompt_version"],
            model_name=row["model_name"],
            tokens_prompt=row["tokens_prompt"],
            tokens_completion=row["tokens_completion"],
            tools_used=json.loads(row["tools_used"]) if row["tools_used"] else [],
            latency_ms=row["latency_ms"],
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_tool_call(row: sqlite3.Row) -> ToolCallRecord:
        return ToolCallRecord(
            id=row["id"],
            trace_id=row["trace_id"],
            role=LLMRole(row["role"]) if row["role"] else LLMRole.RESEARCH,
            tool_name=row["tool_name"],
            status=row["status"],
            latency_ms=row["latency_ms"],
            input_size=row["input_size"],
            output_size=row["output_size"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_guardrail_event(row: sqlite3.Row) -> GuardrailEvent:
        return GuardrailEvent(
            id=row["id"],
            trace_id=row["trace_id"],
            role=LLMRole(row["role"]) if row["role"] else LLMRole.RESEARCH,
            event_type=row["event_type"],
            reason=row["reason"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_prompt(row: sqlite3.Row) -> PromptVersion:
        return PromptVersion(
            id=row["id"],
            role=LLMRole(row["role"]) if row["role"] else LLMRole.RESEARCH,
            name=row["name"],
            version=row["version"],
            content=row["content"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )


_store: Optional[LLMGovernanceStore] = None


def get_llm_governance_store(db_path: Optional[str] = None) -> LLMGovernanceStore:
    global _store
    if _store is None or db_path is not None:
        _store = LLMGovernanceStore(db_path=db_path)
    return _store
