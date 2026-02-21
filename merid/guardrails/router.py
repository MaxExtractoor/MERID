"""
§4 — Guarded Tool Router

The single entry-point for all agent tool invocations.
Enforces in order:
  1. Budget check (depth, steps, tool calls, wall time)
  2. Cycle detection
  3. Capability check (is agent allowed to call this tool?)
  4. Scope check (is tool available in this scope?)
  5. Rate-limit check
  6. Policy engine (preconditions, kill switch, notional limits)
  7. Execute tool + record trace step
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from merid.guardrails.tools import (
    ToolErrorCode,
    ToolRegistry,
    ToolResult,
    ToolValidity,
    get_tool_registry,
)
from merid.guardrails.trace import (
    AgentTrace,
    TraceStep,
    TraceStore,
    get_trace_store,
)
from merid.guardrails.budget import (
    AgentContext,
    BudgetExceeded,
    TerminalState,
)
from merid.guardrails.capabilities import (
    CapabilityStore,
    get_capability_store,
)
from merid.guardrails.policy import (
    PolicyEngine,
    PolicyVerdict,
    get_policy_engine,
)
from utils.logger import get_logger

logger = get_logger("merid.guardrails.router")


class GuardedToolRouter:
    """
    Central router that enforces all guardrails before executing a tool.

    Usage::

        router = get_guarded_router()
        ctx = AgentContext(agent_id="arb-01", scope="paper", ...)
        result = await router.call_tool("get_order_book", {"symbol": "BTC/USDT"}, ctx)
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        capability_store: Optional[CapabilityStore] = None,
        policy_engine: Optional[PolicyEngine] = None,
        trace_store: Optional[TraceStore] = None,
    ) -> None:
        self._tools = tool_registry or get_tool_registry()
        self._caps = capability_store or get_capability_store()
        self._policy = policy_engine or get_policy_engine()
        self._traces = trace_store or get_trace_store()
        self._total_calls = 0
        self._denied_calls = 0
        logger.info("GuardedToolRouter initialized")

    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        ctx: AgentContext,
        *,
        trace: Optional[AgentTrace] = None,
    ) -> ToolResult:
        """
        Execute a tool call through the full guardrail pipeline.

        Returns ToolResult — never raises (errors are encoded in the result).
        """
        t0 = time.time()
        self._total_calls += 1

        # ── 1. Budget check ──────────────────────────────────────────
        try:
            ctx.check_budget()
        except BudgetExceeded as exc:
            self._denied_calls += 1
            logger.warning("Budget exceeded for %s: %s", ctx.agent_id, exc.reason)
            return ToolResult.fail(
                ToolErrorCode.BUDGET_EXCEEDED, exc.reason,
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 2. Cycle detection ───────────────────────────────────────
        cycle = ctx.detect_cycles()
        if cycle:
            self._denied_calls += 1
            logger.warning("Cycle detected for %s: %s", ctx.agent_id, cycle)
            return ToolResult.fail(
                ToolErrorCode.BUDGET_EXCEEDED, f"Cycle detected: {cycle}",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 3. Tool exists? ──────────────────────────────────────────
        tool_defn = self._tools.get(tool_name)
        if tool_defn is None:
            self._denied_calls += 1
            return ToolResult.fail(
                ToolErrorCode.NOT_FOUND, f"Tool '{tool_name}' not registered",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 4. Capability check ──────────────────────────────────────
        cap_map = self._caps.get_or_default(ctx.agent_id)

        if not cap_map.can_use_tool(tool_name):
            self._denied_calls += 1
            logger.warning(
                "Permission denied: agent=%s tool=%s (not in capability set)",
                ctx.agent_id, tool_name,
            )
            return ToolResult.fail(
                ToolErrorCode.PERMISSION_DENIED,
                f"Agent '{ctx.agent_id}' is not allowed to call '{tool_name}'",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 5. Scope check ──────────────────────────────────────────
        if not cap_map.can_operate_in_scope(ctx.scope):
            self._denied_calls += 1
            return ToolResult.fail(
                ToolErrorCode.PERMISSION_DENIED,
                f"Agent '{ctx.agent_id}' cannot operate in scope '{ctx.scope}' "
                f"(max_scope={cap_map.max_scope})",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        if ctx.scope not in tool_defn.scopes:
            self._denied_calls += 1
            return ToolResult.fail(
                ToolErrorCode.PERMISSION_DENIED,
                f"Tool '{tool_name}' not available in scope '{ctx.scope}' "
                f"(allowed: {tool_defn.scopes})",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 6. Rate-limit check ─────────────────────────────────────
        if self._tools.is_rate_limited(tool_name):
            self._denied_calls += 1
            return ToolResult.fail(
                ToolErrorCode.RATE_LIMITED,
                f"Tool '{tool_name}' rate limit exceeded",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 7. Policy engine ────────────────────────────────────────
        policy_ctx = {
            **ctx.to_dict(),
            "max_notional_usd": cap_map.max_notional_usd,
            "max_orders_per_minute": cap_map.max_orders_per_minute,
        }
        policy_result = self._policy.evaluate(tool_name, params, policy_ctx)

        if policy_result.verdict == PolicyVerdict.DENY:
            self._denied_calls += 1
            logger.warning(
                "Policy DENY: agent=%s tool=%s reason=%s",
                ctx.agent_id, tool_name, policy_result.reason,
            )
            return ToolResult.fail(
                ToolErrorCode.POLICY_BLOCKED, policy_result.reason,
                tool_name=tool_name, task_id=ctx.task_id,
            )

        if policy_result.verdict == PolicyVerdict.REQUIRE_APPROVAL:
            self._denied_calls += 1
            return ToolResult.fail(
                ToolErrorCode.POLICY_BLOCKED,
                f"Requires approval from: {policy_result.required_approvers}. "
                f"Reason: {policy_result.reason}",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        # ── 8. Execute ──────────────────────────────────────────────
        ctx.record_tool_call(tool_name)
        self._tools.record_call(tool_name)

        result: ToolResult
        if tool_defn.handler:
            try:
                raw = tool_defn.handler(**params) if not asyncio.iscoroutinefunction(tool_defn.handler) \
                    else await tool_defn.handler(**params)
                if isinstance(raw, ToolResult):
                    result = raw
                elif isinstance(raw, dict):
                    result = ToolResult.ok(raw, tool_name=tool_name, task_id=ctx.task_id)
                else:
                    result = ToolResult.ok({"value": raw}, tool_name=tool_name, task_id=ctx.task_id)
            except Exception as exc:
                result = ToolResult.fail(ToolErrorCode.INTERNAL, str(exc),
                                         tool_name=tool_name, task_id=ctx.task_id)
        else:
            result = ToolResult.fail(
                ToolErrorCode.INTERNAL, f"Tool '{tool_name}' has no handler",
                tool_name=tool_name, task_id=ctx.task_id,
            )

        result.latency_ms = round((time.time() - t0) * 1000, 2)
        result.task_id = ctx.task_id

        # ── 9. Record trace step ─────────────────────────────────────
        if trace:
            step = TraceStep(
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
                depth=ctx.depth,
                inputs=params,
                tools_called=[tool_name],
                tool_outputs=[result.to_dict()],
                chosen_action=tool_name,
                action_params=params,
                outcome="success" if result.success else result.error_code.value,
                confidence=0.0,
                duration_ms=result.latency_ms,
            )
            trace.add_step(step)

        return result

    async def call_tool_batch(
        self,
        calls: list,
        ctx: AgentContext,
        *,
        trace: Optional[AgentTrace] = None,
    ) -> list:
        """
        Execute multiple tool calls sequentially through the guardrail pipeline.

        Each call is a (tool_name, params) tuple.
        """
        results = []
        for tool_name, params in calls:
            result = await self.call_tool(tool_name, params, ctx, trace=trace)
            results.append(result)
            if not result.success and result.error_code in (
                ToolErrorCode.BUDGET_EXCEEDED,
                ToolErrorCode.PERMISSION_DENIED,
                ToolErrorCode.POLICY_BLOCKED,
            ):
                break  # Stop batch on hard failures
        return results

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_calls": self._total_calls,
            "denied_calls": self._denied_calls,
            "denial_rate": round(self._denied_calls / max(self._total_calls, 1) * 100, 1),
            "tools": self._tools.get_stats(),
            "capabilities": self._caps.get_stats(),
            "policy_rules": len(self._policy.get_rules()),
            "traces": self._traces.get_stats(),
        }


# ── Singleton ────────────────────────────────────────────────────────

_guarded_router: Optional[GuardedToolRouter] = None


def get_guarded_router() -> GuardedToolRouter:
    global _guarded_router
    if _guarded_router is None:
        _guarded_router = GuardedToolRouter()
    return _guarded_router
