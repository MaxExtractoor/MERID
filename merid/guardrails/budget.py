"""
§3 — Recursion Budget & Agent Context

Explicit recursion/iteration budgets per task:
- max_depth, max_steps, max_tool_calls, max_handoffs
- If any threshold is hit → terminate with safe fallback
- Call-graph DAG tracking with cycle detection
- Fail-fast on repeated no-progress steps
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.guardrails.budget")


class TerminalState(str, Enum):
    """Finite set of terminal states for any agent chain."""
    EXECUTED_SAFELY = "executed_safely"
    NO_OP_GUARDRAIL = "no_op_guardrail"
    ESCALATED = "escalated"
    ERRORED = "errored"
    BUDGET_EXCEEDED = "budget_exceeded"
    CYCLE_DETECTED = "cycle_detected"
    CONFIDENCE_STALL = "confidence_stall"


class BudgetExceeded(Exception):
    """Raised when an agent exceeds its recursion/iteration budget."""
    def __init__(self, reason: str, terminal_state: TerminalState = TerminalState.BUDGET_EXCEEDED):
        self.reason = reason
        self.terminal_state = terminal_state
        super().__init__(reason)


@dataclass
class AgentBudget:
    """
    Hard limits for a single agent task execution.

    These are enforced by the GuardedToolRouter — even if an agent
    policy goes off the rails, it cannot exceed these ceilings.
    """
    max_depth: int = 5          # max nesting depth (agent → sub-agent)
    max_steps: int = 20         # max reasoning/action steps
    max_tool_calls: int = 50    # max total tool invocations
    max_handoffs: int = 3       # max delegations to other agents
    max_wall_seconds: int = 300 # max wall-clock time (5 min default)
    max_consecutive_no_progress: int = 3  # fail-fast if confidence stalls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_handoffs": self.max_handoffs,
            "max_wall_seconds": self.max_wall_seconds,
            "max_consecutive_no_progress": self.max_consecutive_no_progress,
        }


@dataclass
class CallGraphEdge:
    """One edge in the call graph DAG."""
    caller: str       # agent_id or "system"
    callee: str       # tool_name or agent_id
    call_type: str    # "tool" | "handoff" | "internal"
    timestamp: float = field(default_factory=time.time)
    task_id: str = ""


@dataclass
class AgentContext:
    """
    Mutable execution context for one agent task.

    Tracks counters, call graph, and confidence history.
    The router checks this before every tool call or handoff.
    """
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    agent_id: str = ""
    scope: str = "paper"                          # research | paper | live
    budget: AgentBudget = field(default_factory=AgentBudget)

    # Counters (mutated by router)
    depth: int = 0
    steps: int = 0
    tool_calls: int = 0
    handoffs: int = 0
    started_at: float = field(default_factory=time.time)

    # Call graph
    call_graph: List[CallGraphEdge] = field(default_factory=list)

    # Confidence history for fail-fast
    confidence_history: List[float] = field(default_factory=list)

    # Capabilities granted to this agent (tool names)
    capabilities: Set[str] = field(default_factory=set)

    # Parent context (for nested agent calls)
    parent_task_id: Optional[str] = None

    # ── Budget checks ────────────────────────────────────────────────

    def check_budget(self) -> None:
        """Raise BudgetExceeded if any limit is hit."""
        if self.depth >= self.budget.max_depth:
            raise BudgetExceeded(
                f"Depth {self.depth} exceeds max {self.budget.max_depth}",
                TerminalState.BUDGET_EXCEEDED,
            )
        if self.steps >= self.budget.max_steps:
            raise BudgetExceeded(
                f"Steps {self.steps} exceeds max {self.budget.max_steps}",
                TerminalState.BUDGET_EXCEEDED,
            )
        if self.tool_calls >= self.budget.max_tool_calls:
            raise BudgetExceeded(
                f"Tool calls {self.tool_calls} exceeds max {self.budget.max_tool_calls}",
                TerminalState.BUDGET_EXCEEDED,
            )
        if self.handoffs >= self.budget.max_handoffs:
            raise BudgetExceeded(
                f"Handoffs {self.handoffs} exceeds max {self.budget.max_handoffs}",
                TerminalState.BUDGET_EXCEEDED,
            )
        elapsed = time.time() - self.started_at
        if elapsed > self.budget.max_wall_seconds:
            raise BudgetExceeded(
                f"Wall time {elapsed:.0f}s exceeds max {self.budget.max_wall_seconds}s",
                TerminalState.BUDGET_EXCEEDED,
            )

    def record_step(self, confidence: float = 0.0) -> None:
        """Increment step counter and check for confidence stall."""
        self.steps += 1
        self.confidence_history.append(confidence)
        self._check_confidence_stall()

    def record_tool_call(self, tool_name: str) -> None:
        """Increment tool call counter and add to call graph."""
        self.tool_calls += 1
        self.call_graph.append(CallGraphEdge(
            caller=self.agent_id,
            callee=tool_name,
            call_type="tool",
            task_id=self.task_id,
        ))

    def record_handoff(self, target_agent_id: str) -> None:
        """Increment handoff counter and add to call graph."""
        self.handoffs += 1
        self.call_graph.append(CallGraphEdge(
            caller=self.agent_id,
            callee=target_agent_id,
            call_type="handoff",
            task_id=self.task_id,
        ))

    def create_child_context(self, child_agent_id: str, child_capabilities: Set[str]) -> "AgentContext":
        """Create a child context for a delegated sub-agent call."""
        return AgentContext(
            task_id=self.task_id,  # same task
            agent_id=child_agent_id,
            scope=self.scope,
            budget=AgentBudget(
                max_depth=self.budget.max_depth,
                max_steps=self.budget.max_steps,
                max_tool_calls=self.budget.max_tool_calls - self.tool_calls,
                max_handoffs=self.budget.max_handoffs - self.handoffs,
                max_wall_seconds=self.budget.max_wall_seconds - int(time.time() - self.started_at),
                max_consecutive_no_progress=self.budget.max_consecutive_no_progress,
            ),
            depth=self.depth + 1,
            started_at=self.started_at,  # inherit start time
            capabilities=child_capabilities,
            parent_task_id=self.task_id,
        )

    # ── Cycle detection ──────────────────────────────────────────────

    def detect_cycles(self, max_ping_pong: int = 3) -> Optional[str]:
        """
        Detect A→B→A ping-pong or any cycle with no state delta.

        Returns a description of the cycle if found, else None.
        """
        # Check for agent-to-agent ping-pong
        handoff_edges = [e for e in self.call_graph if e.call_type == "handoff"]
        if len(handoff_edges) >= 2:
            # Sliding window: look for A→B→A pattern
            for i in range(len(handoff_edges) - 1):
                pattern_count = 0
                a, b = handoff_edges[i].caller, handoff_edges[i].callee
                for j in range(i + 1, len(handoff_edges)):
                    if handoff_edges[j].caller == b and handoff_edges[j].callee == a:
                        pattern_count += 1
                        if pattern_count >= max_ping_pong:
                            return f"Ping-pong detected: {a} ↔ {b} ({pattern_count} times)"
                        # Swap for next iteration
                        a, b = b, a

        # Check for repeated identical tool call sequences (no state delta)
        tool_edges = [e.callee for e in self.call_graph if e.call_type == "tool"]
        if len(tool_edges) >= 4:
            # Look for repeating n-grams (window sizes 2..7)
            for window in range(2, min(len(tool_edges) // 2 + 1, 8)):
                if len(tool_edges) >= 2 * window:
                    tail = tool_edges[-window:]
                    prev = tool_edges[-2 * window:-window]
                    if tail == prev:
                        return f"Repeated tool sequence detected: {tail}"

        return None

    # ── Internal ─────────────────────────────────────────────────────

    def _check_confidence_stall(self) -> None:
        """Fail-fast if confidence hasn't improved over N consecutive steps."""
        n = self.budget.max_consecutive_no_progress
        if len(self.confidence_history) < n + 1:
            return
        recent = self.confidence_history[-n:]
        prev = self.confidence_history[-(n + 1)]
        # All recent confidences are <= the one before them
        if all(c <= prev for c in recent):
            raise BudgetExceeded(
                f"Confidence stall: last {n} steps showed no improvement "
                f"(prev={prev:.3f}, recent={[round(c, 3) for c in recent]})",
                TerminalState.CONFIDENCE_STALL,
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "scope": self.scope,
            "depth": self.depth,
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "handoffs": self.handoffs,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
            "budget": self.budget.to_dict(),
            "capabilities": sorted(self.capabilities),
            "call_graph_size": len(self.call_graph),
            "confidence_history": [round(c, 3) for c in self.confidence_history[-10:]],
        }
