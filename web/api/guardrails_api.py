"""
API endpoints for the MERID Agent Guardrails system.

Provides introspection into:
- Tool registry (registered tools, stats, rate limits)
- Capability store (per-agent capability maps)
- Policy engine (active rules)
- Trace store (agent execution traces)
- Guarded router (call stats, denial rates)
- Budget defaults
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

from utils.logger import get_logger

logger = get_logger("web.api.guardrails")

router = APIRouter(prefix="/api/v1/guardrails", tags=["guardrails"])


def _get_router():
    from merid.guardrails.router import get_guarded_router
    return get_guarded_router()


def _get_tools():
    from merid.guardrails.tools import get_tool_registry
    return get_tool_registry()


def _get_caps():
    from merid.guardrails.capabilities import get_capability_store
    return get_capability_store()


def _get_policy():
    from merid.guardrails.policy import get_policy_engine
    return get_policy_engine()


def _get_traces():
    from merid.guardrails.trace import get_trace_store
    return get_trace_store()


# ── Overview ─────────────────────────────────────────────────────────

@router.get("/status")
async def get_guardrails_status() -> Dict[str, Any]:
    """Get full guardrails system status."""
    return _get_router().get_stats()


# ── Tools ────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools() -> Dict[str, Any]:
    """List all registered tools with schemas and risk levels."""
    reg = _get_tools()
    return {
        "tools": [t.to_dict() for t in reg.list_tools()],
        "total": len(reg.list_names()),
        "stats": reg.get_stats(),
    }


@router.get("/tools/{tool_name}")
async def get_tool_detail(tool_name: str) -> Dict[str, Any]:
    """Get detail for a specific tool."""
    reg = _get_tools()
    defn = reg.get(tool_name)
    if defn is None:
        return {"error": f"Tool '{tool_name}' not found"}
    return defn.to_dict()


# ── Capabilities ─────────────────────────────────────────────────────

@router.get("/capabilities")
async def list_capabilities() -> Dict[str, Any]:
    """List all registered agent capability maps."""
    store = _get_caps()
    agents = store.list_agents()
    maps = []
    for aid in agents:
        m = store.get(aid)
        if m:
            maps.append(m.to_dict())
    return {"agents": maps, "total": len(maps), "stats": store.get_stats()}


@router.get("/capabilities/{agent_id}")
async def get_agent_capabilities(agent_id: str) -> Dict[str, Any]:
    """Get capability map for a specific agent."""
    store = _get_caps()
    m = store.get(agent_id)
    if m is None:
        return {"error": f"No capability map for '{agent_id}'", "default_applied": True,
                "map": store.get_or_default(agent_id).to_dict()}
    return m.to_dict()


# ── Policy ───────────────────────────────────────────────────────────

@router.get("/policy/rules")
async def list_policy_rules() -> Dict[str, Any]:
    """List all active policy rules."""
    engine = _get_policy()
    return {"rules": engine.get_rules(), "total": len(engine.get_rules())}


# ── Traces ───────────────────────────────────────────────────────────

@router.get("/traces")
async def list_traces(
    agent_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """List recent agent execution traces."""
    store = _get_traces()
    traces = store.get_recent_traces(agent_id=agent_id, limit=limit)
    return {"traces": traces, "count": len(traces), "stats": store.get_stats()}


@router.get("/traces/{trace_id}")
async def get_trace_detail(trace_id: str) -> Dict[str, Any]:
    """Get a specific trace by ID."""
    store = _get_traces()
    trace = store.get_trace(trace_id)
    if trace is None:
        return {"error": f"Trace '{trace_id}' not found"}
    return trace
