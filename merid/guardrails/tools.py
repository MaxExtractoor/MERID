"""
§1 — Typed Tool Layer

Every external action goes through a typed tool with:
- Strong input/output schemas (Pydantic BaseModel)
- Validity flags: fresh / stale / partial / anomalous / simulated
- Explicit error codes instead of raw exceptions
- Structured payloads (never unstructured blobs)
"""

from __future__ import annotations

import time
import functools
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar
from dataclasses import dataclass, field
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("merid.guardrails.tools")

T = TypeVar("T")


# ── Validity flags ────────────────────────────────────────────────────

class ToolValidity(str, Enum):
    """Validity flag attached to every tool output."""
    FRESH = "fresh"           # Data is current and verified
    STALE = "stale"           # Data is older than its max_age
    PARTIAL = "partial"       # Some fields missing or incomplete
    ANOMALOUS = "anomalous"   # Values outside expected range
    SIMULATED = "simulated"   # Data from sim/paper, not live


class ToolErrorCode(str, Enum):
    """Explicit error codes for tool failures."""
    OK = "ok"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    VENUE_DOWN = "venue_down"
    INTERNAL = "internal"
    BUDGET_EXCEEDED = "budget_exceeded"
    PERMISSION_DENIED = "permission_denied"
    POLICY_BLOCKED = "policy_blocked"


# ── Tool result wrapper ──────────────────────────────────────────────

@dataclass
class ToolResult:
    """
    Structured result from any tool invocation.

    Every tool returns this wrapper so agents always see:
    - success/failure + error code
    - validity flag
    - typed payload (dict serialisable)
    - wall-clock timestamp + latency
    - source provenance
    """
    success: bool
    error_code: ToolErrorCode = ToolErrorCode.OK
    error_message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    validity: ToolValidity = ToolValidity.FRESH
    source: str = ""          # e.g. "kraken", "paper_engine", "kalshi"
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    tool_name: str = ""
    task_id: str = ""         # chain/task ID for dedup & throttle

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error_code": self.error_code.value,
            "error_message": self.error_message,
            "payload": self.payload,
            "validity": self.validity.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "latency_ms": self.latency_ms,
            "tool_name": self.tool_name,
            "task_id": self.task_id,
        }

    @staticmethod
    def ok(payload: Dict[str, Any], *, source: str = "", validity: ToolValidity = ToolValidity.FRESH,
           tool_name: str = "", task_id: str = "") -> "ToolResult":
        return ToolResult(success=True, payload=payload, source=source,
                          validity=validity, tool_name=tool_name, task_id=task_id)

    @staticmethod
    def fail(code: ToolErrorCode, message: str, *, tool_name: str = "", task_id: str = "") -> "ToolResult":
        return ToolResult(success=False, error_code=code, error_message=message,
                          tool_name=tool_name, task_id=task_id)


# ── Tool definition ──────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """Metadata for a registered tool."""
    name: str
    description: str
    input_schema: Dict[str, Any]    # JSON-Schema-like dict
    output_schema: Dict[str, Any]
    risk_level: str = "low"         # low | medium | high | critical
    idempotent: bool = False
    max_calls_per_minute: int = 60
    scopes: List[str] = field(default_factory=lambda: ["research", "paper", "live"])
    handler: Optional[Callable] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk_level": self.risk_level,
            "idempotent": self.idempotent,
            "max_calls_per_minute": self.max_calls_per_minute,
            "scopes": self.scopes,
        }


# ── Tool registry ────────────────────────────────────────────────────

class ToolRegistry:
    """
    Central registry of all typed tools available to agents.

    Tools are registered with schemas, risk levels, and scope restrictions.
    The registry enforces rate limits per tool and provides introspection.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._call_counts: Dict[str, List[float]] = {}  # tool_name → [timestamps]

    def register(self, defn: ToolDefinition) -> None:
        self._tools[defn.name] = defn
        self._call_counts.setdefault(defn.name, [])
        logger.info("Registered tool: %s (risk=%s, scopes=%s)", defn.name, defn.risk_level, defn.scopes)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def is_rate_limited(self, name: str) -> bool:
        """Check if tool has exceeded its per-minute call limit."""
        defn = self._tools.get(name)
        if not defn:
            return False
        now = time.time()
        window = [t for t in self._call_counts.get(name, []) if now - t < 60]
        self._call_counts[name] = window
        return len(window) >= defn.max_calls_per_minute

    def record_call(self, name: str) -> None:
        self._call_counts.setdefault(name, []).append(time.time())

    def get_stats(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "total_tools": len(self._tools),
            "tools": {
                name: {
                    "risk_level": defn.risk_level,
                    "calls_last_minute": len([t for t in self._call_counts.get(name, []) if now - t < 60]),
                }
                for name, defn in self._tools.items()
            },
        }


# ── Decorator for registering tools ─────────────────────────────────

def tool(
    name: str,
    description: str = "",
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    risk_level: str = "low",
    idempotent: bool = False,
    max_calls_per_minute: int = 60,
    scopes: Optional[List[str]] = None,
) -> Callable:
    """
    Decorator to register a function as a typed tool.

    Usage::

        @tool("get_order_book", risk_level="low", idempotent=True)
        async def get_order_book(symbol: str) -> ToolResult:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        defn = ToolDefinition(
            name=name,
            description=description or fn.__doc__ or "",
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            risk_level=risk_level,
            idempotent=idempotent,
            max_calls_per_minute=max_calls_per_minute,
            scopes=scopes or ["research", "paper", "live"],
            handler=fn,
        )
        # Auto-register on import
        get_tool_registry().register(defn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
            t0 = time.time()
            try:
                result = await fn(*args, **kwargs)
                if isinstance(result, ToolResult):
                    result.latency_ms = round((time.time() - t0) * 1000, 2)
                    result.tool_name = name
                    return result
                # If the function returned a plain dict, wrap it
                return ToolResult.ok(result if isinstance(result, dict) else {"value": result},
                                     tool_name=name)
            except Exception as exc:
                return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc), tool_name=name)

        wrapper._tool_definition = defn
        return wrapper

    return decorator


# ── Singleton ────────────────────────────────────────────────────────

_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
