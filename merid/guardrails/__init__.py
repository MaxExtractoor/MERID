"""
MERID Agent Guardrails — Grounding, Incursion Control & Recursion Safety.

§1  Typed tool layer with structured payloads and validity flags
§2  Per-agent capability maps, policy engine, scope isolation
§3  AgentBudget / AgentContext with depth/step/tool counters, call-graph DAG, cycle detection
§4  Wiring helpers for the existing orchestrator + agent framework
"""

from merid.guardrails.tools import (
    ToolResult,
    ToolValidity,
    ToolRegistry,
    get_tool_registry,
    tool,
)
from merid.guardrails.trace import (
    AgentTrace,
    TraceStep,
    TraceStore,
    get_trace_store,
)
from merid.guardrails.budget import (
    AgentBudget,
    AgentContext,
    BudgetExceeded,
    TerminalState,
)
from merid.guardrails.capabilities import (
    AgentCapabilityMap,
    CapabilityStore,
    get_capability_store,
)
from merid.guardrails.policy import (
    PolicyVerdict,
    PolicyEngine,
    get_policy_engine,
)
from merid.guardrails.router import (
    GuardedToolRouter,
    get_guarded_router,
)
