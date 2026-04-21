"""
Tests for the MERID Agent Guardrails system.

Covers:
  §1 Typed tool layer (ToolResult, ToolRegistry, validity flags)
  §2 Capabilities (AgentCapabilityMap, CapabilityStore, profiles)
  §2 Policy engine (rules, verdicts, preconditions)
  §3 Budget & context (AgentBudget, AgentContext, cycle detection, fail-fast)
  §3 Trace persistence (TraceStep, AgentTrace, TraceStore)
  §4 Guarded router (full pipeline enforcement)
"""

import os
import sys
import time
import tempfile
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════
# §1 — Typed Tool Layer
# ═══════════════════════════════════════════════════════════════════════

class TestToolResult:
    """ToolResult construction and serialisation."""

    def test_ok_result(self):
        from merid.guardrails.tools import ToolResult, ToolValidity
        r = ToolResult.ok({"price": 69000}, source="kraken", validity=ToolValidity.FRESH)
        assert r.success is True
        assert r.payload["price"] == 69000
        assert r.source == "kraken"
        assert r.validity == ToolValidity.FRESH

    def test_fail_result(self):
        from merid.guardrails.tools import ToolResult, ToolErrorCode
        r = ToolResult.fail(ToolErrorCode.TIMEOUT, "exchange timed out")
        assert r.success is False
        assert r.error_code == ToolErrorCode.TIMEOUT
        assert "timed out" in r.error_message

    def test_to_dict_roundtrip(self):
        from merid.guardrails.tools import ToolResult, ToolValidity
        r = ToolResult.ok({"x": 1}, source="test", validity=ToolValidity.STALE, tool_name="t1")
        d = r.to_dict()
        assert d["success"] is True
        assert d["validity"] == "stale"
        assert d["tool_name"] == "t1"

    def test_validity_enum_values(self):
        from merid.guardrails.tools import ToolValidity
        assert ToolValidity.FRESH.value == "fresh"
        assert ToolValidity.STALE.value == "stale"
        assert ToolValidity.PARTIAL.value == "partial"
        assert ToolValidity.ANOMALOUS.value == "anomalous"
        assert ToolValidity.SIMULATED.value == "simulated"

    def test_error_code_enum_values(self):
        from merid.guardrails.tools import ToolErrorCode
        assert ToolErrorCode.OK.value == "ok"
        assert ToolErrorCode.POLICY_BLOCKED.value == "policy_blocked"
        assert ToolErrorCode.BUDGET_EXCEEDED.value == "budget_exceeded"
        assert ToolErrorCode.PERMISSION_DENIED.value == "permission_denied"


class TestToolRegistry:
    """ToolRegistry registration, lookup, rate limiting."""

    def test_register_and_get(self):
        from merid.guardrails.tools import ToolRegistry, ToolDefinition
        reg = ToolRegistry()
        defn = ToolDefinition(name="test_tool", description="A test", input_schema={}, output_schema={})
        reg.register(defn)
        assert reg.get("test_tool") is defn
        assert "test_tool" in reg.list_names()

    def test_get_nonexistent(self):
        from merid.guardrails.tools import ToolRegistry
        reg = ToolRegistry()
        assert reg.get("nope") is None

    def test_rate_limiting(self):
        from merid.guardrails.tools import ToolRegistry, ToolDefinition
        reg = ToolRegistry()
        defn = ToolDefinition(name="limited", description="", input_schema={}, output_schema={},
                              max_calls_per_minute=3)
        reg.register(defn)
        assert not reg.is_rate_limited("limited")
        reg.record_call("limited")
        reg.record_call("limited")
        reg.record_call("limited")
        assert reg.is_rate_limited("limited")

    def test_stats(self):
        from merid.guardrails.tools import ToolRegistry, ToolDefinition
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="a", description="", input_schema={}, output_schema={}))
        reg.register(ToolDefinition(name="b", description="", input_schema={}, output_schema={}))
        stats = reg.get_stats()
        assert stats["total_tools"] == 2

    def test_tool_definition_to_dict(self):
        from merid.guardrails.tools import ToolDefinition
        defn = ToolDefinition(name="x", description="desc", input_schema={"a": "str"},
                              output_schema={"b": "int"}, risk_level="high", scopes=["live"])
        d = defn.to_dict()
        assert d["name"] == "x"
        assert d["risk_level"] == "high"
        assert d["scopes"] == ["live"]


# ═══════════════════════════════════════════════════════════════════════
# §2 — Capabilities
# ═══════════════════════════════════════════════════════════════════════

class TestAgentCapabilityMap:
    """Per-agent capability map checks."""

    def test_can_use_tool(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", allowed_tools={"get_ticker", "get_order_book"})
        assert m.can_use_tool("get_ticker")
        assert not m.can_use_tool("place_order")

    def test_wildcard_tools(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", allowed_tools={"*"})
        assert m.can_use_tool("anything")

    def test_scope_check(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", max_scope="paper")
        assert m.can_operate_in_scope("research")
        assert m.can_operate_in_scope("paper")
        assert not m.can_operate_in_scope("live")

    def test_symbol_check(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", allowed_symbols={"BTC/USD", "ETH/USD"})
        assert m.can_access_symbol("BTC/USD")
        assert not m.can_access_symbol("SOL/USD")

    def test_venue_check(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", allowed_venues={"kraken"})
        assert m.can_access_venue("kraken")
        assert not m.can_access_venue("binance")

    def test_to_dict(self):
        from merid.guardrails.capabilities import AgentCapabilityMap
        m = AgentCapabilityMap(agent_id="a1", max_notional_usd=5000, max_scope="live")
        d = m.to_dict()
        assert d["agent_id"] == "a1"
        assert d["max_notional_usd"] == 5000
        assert d["max_scope"] == "live"


class TestCapabilityStore:
    """CapabilityStore registration and profile factories."""

    def test_register_and_get(self):
        from merid.guardrails.capabilities import CapabilityStore, AgentCapabilityMap
        store = CapabilityStore()
        m = AgentCapabilityMap(agent_id="test-1", max_scope="paper")
        store.register(m)
        assert store.get("test-1") is m

    def test_get_or_default(self):
        from merid.guardrails.capabilities import CapabilityStore
        store = CapabilityStore()
        m = store.get_or_default("unknown-agent")
        assert m.agent_id == "unknown-agent"
        assert m.max_scope == "research"  # default is most restrictive

    def test_register_from_profile_research(self):
        from merid.guardrails.capabilities import CapabilityStore
        store = CapabilityStore()
        m = store.register_from_profile("r1", "research")
        assert m.max_notional_usd == 0.0
        assert m.max_orders_per_minute == 0
        assert "place_order" not in m.allowed_tools

    def test_register_from_profile_trading(self):
        from merid.guardrails.capabilities import CapabilityStore
        store = CapabilityStore()
        m = store.register_from_profile("t1", "trading")
        assert m.max_notional_usd > 0
        assert "place_order" in m.allowed_tools

    def test_register_from_profile_risk(self):
        from merid.guardrails.capabilities import CapabilityStore
        store = CapabilityStore()
        m = store.register_from_profile("rk1", "risk")
        assert "trigger_halt" in m.allowed_tools
        assert m.max_notional_usd == 0.0
        assert m.max_scope == "live"

    def test_stats(self):
        from merid.guardrails.capabilities import CapabilityStore
        store = CapabilityStore()
        store.register_from_profile("a", "research")
        store.register_from_profile("b", "trading")
        stats = store.get_stats()
        assert stats["total_agents"] == 2


# ═══════════════════════════════════════════════════════════════════════
# §2 — Policy Engine
# ═══════════════════════════════════════════════════════════════════════

class TestPolicyEngine:
    """Policy engine rule evaluation."""

    def test_default_rules_loaded(self):
        from merid.guardrails.policy import PolicyEngine
        engine = PolicyEngine()
        rules = engine.get_rules()
        assert len(rules) >= 5

    def test_allow_read_only_tool(self):
        from merid.guardrails.policy import PolicyEngine, PolicyVerdict
        engine = PolicyEngine()
        result = engine.evaluate("get_ticker", {"symbol": "BTC"}, {"scope": "paper"})
        assert result.verdict == PolicyVerdict.ALLOW

    def test_deny_live_trading_without_flag(self):
        from merid.guardrails.policy import PolicyEngine, PolicyVerdict
        os.environ.pop("MERID_ALLOW_LIVE_TRADES", None)
        engine = PolicyEngine()
        result = engine.evaluate("place_order", {"symbol": "BTC", "quantity": 1}, {"scope": "live"})
        assert result.verdict == PolicyVerdict.DENY

    def test_deny_max_notional(self):
        from merid.guardrails.policy import PolicyEngine, PolicyVerdict
        engine = PolicyEngine()
        result = engine.evaluate(
            "place_order",
            {"quantity": 100, "price": 70000},  # $7M notional
            {"scope": "paper", "max_notional_usd": 10000, "max_orders_per_minute": 10, "orders_this_minute": 0},
        )
        assert result.verdict == PolicyVerdict.DENY

    def test_require_approval_config_change(self):
        from merid.guardrails.policy import PolicyEngine, PolicyVerdict
        engine = PolicyEngine()
        result = engine.evaluate("update_strategy_config", {}, {"scope": "live"})
        assert result.verdict == PolicyVerdict.REQUIRE_APPROVAL

    def test_order_rate_limit(self):
        from merid.guardrails.policy import PolicyEngine, PolicyVerdict
        engine = PolicyEngine()
        result = engine.evaluate(
            "place_order",
            {"quantity": 0.01, "price": 100},
            {"scope": "paper", "max_notional_usd": 10000, "max_orders_per_minute": 5, "orders_this_minute": 5},
        )
        assert result.verdict == PolicyVerdict.DENY

    def test_policy_check_result_to_dict(self):
        from merid.guardrails.policy import PolicyCheckResult, PolicyVerdict
        r = PolicyCheckResult(verdict=PolicyVerdict.ALLOW, reason="ok", conditions_met=["a"])
        d = r.to_dict()
        assert d["verdict"] == "allow"
        assert "a" in d["conditions_met"]


# ═══════════════════════════════════════════════════════════════════════
# §3 — Budget & Context
# ═══════════════════════════════════════════════════════════════════════

class TestAgentBudget:
    """AgentBudget limits."""

    def test_default_values(self):
        from merid.guardrails.budget import AgentBudget
        b = AgentBudget()
        assert b.max_depth == 5
        assert b.max_steps == 20
        assert b.max_tool_calls == 50

    def test_to_dict(self):
        from merid.guardrails.budget import AgentBudget
        b = AgentBudget(max_depth=3, max_steps=10)
        d = b.to_dict()
        assert d["max_depth"] == 3
        assert d["max_steps"] == 10


class TestAgentContext:
    """AgentContext budget enforcement, cycle detection, fail-fast."""

    def test_check_budget_passes(self):
        from merid.guardrails.budget import AgentContext, AgentBudget
        ctx = AgentContext(budget=AgentBudget(max_steps=10))
        ctx.steps = 5
        ctx.check_budget()  # should not raise

    def test_check_budget_depth_exceeded(self):
        from merid.guardrails.budget import AgentContext, AgentBudget, BudgetExceeded
        ctx = AgentContext(budget=AgentBudget(max_depth=2))
        ctx.depth = 2
        with pytest.raises(BudgetExceeded, match="Depth"):
            ctx.check_budget()

    def test_check_budget_steps_exceeded(self):
        from merid.guardrails.budget import AgentContext, AgentBudget, BudgetExceeded
        ctx = AgentContext(budget=AgentBudget(max_steps=5))
        ctx.steps = 5
        with pytest.raises(BudgetExceeded, match="Steps"):
            ctx.check_budget()

    def test_check_budget_tool_calls_exceeded(self):
        from merid.guardrails.budget import AgentContext, AgentBudget, BudgetExceeded
        ctx = AgentContext(budget=AgentBudget(max_tool_calls=3))
        ctx.tool_calls = 3
        with pytest.raises(BudgetExceeded, match="Tool calls"):
            ctx.check_budget()

    def test_check_budget_wall_time_exceeded(self):
        from merid.guardrails.budget import AgentContext, AgentBudget, BudgetExceeded
        ctx = AgentContext(budget=AgentBudget(max_wall_seconds=1))
        ctx.started_at = time.time() - 2
        with pytest.raises(BudgetExceeded, match="Wall time"):
            ctx.check_budget()

    def test_record_step_increments(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext()
        ctx.record_step(0.5)
        assert ctx.steps == 1
        assert ctx.confidence_history == [0.5]

    def test_record_tool_call(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext(agent_id="a1")
        ctx.record_tool_call("get_ticker")
        assert ctx.tool_calls == 1
        assert len(ctx.call_graph) == 1
        assert ctx.call_graph[0].callee == "get_ticker"

    def test_record_handoff(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext(agent_id="a1")
        ctx.record_handoff("a2")
        assert ctx.handoffs == 1
        assert ctx.call_graph[0].callee == "a2"

    def test_create_child_context(self):
        from merid.guardrails.budget import AgentContext, AgentBudget
        parent = AgentContext(agent_id="parent", budget=AgentBudget(max_depth=5, max_tool_calls=50))
        parent.tool_calls = 10
        child = parent.create_child_context("child", {"get_ticker"})
        assert child.depth == 1
        assert child.agent_id == "child"
        assert child.budget.max_tool_calls == 40  # 50 - 10
        assert child.task_id == parent.task_id

    def test_confidence_stall_detection(self):
        from merid.guardrails.budget import AgentContext, AgentBudget, BudgetExceeded
        ctx = AgentContext(budget=AgentBudget(max_consecutive_no_progress=3))
        ctx.record_step(0.8)  # baseline
        ctx.record_step(0.7)  # drop
        ctx.record_step(0.6)  # drop
        with pytest.raises(BudgetExceeded, match="Confidence stall"):
            ctx.record_step(0.5)  # 3rd consecutive drop

    def test_no_stall_with_improvement(self):
        from merid.guardrails.budget import AgentContext, AgentBudget
        ctx = AgentContext(budget=AgentBudget(max_consecutive_no_progress=3))
        ctx.record_step(0.5)
        ctx.record_step(0.6)
        ctx.record_step(0.7)
        ctx.record_step(0.8)  # improving — no stall

    def test_cycle_detection_no_cycles(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext(agent_id="a1")
        ctx.record_tool_call("get_ticker")
        ctx.record_tool_call("get_order_book")
        assert ctx.detect_cycles() is None

    def test_cycle_detection_repeated_tool_sequence(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext(agent_id="a1")
        # Create a repeating 3-gram: [a, b, c, a, b, c]
        for _ in range(2):
            ctx.record_tool_call("a")
            ctx.record_tool_call("b")
            ctx.record_tool_call("c")
        result = ctx.detect_cycles()
        assert result is not None
        assert "Repeated tool sequence" in result

    def test_to_dict(self):
        from merid.guardrails.budget import AgentContext
        ctx = AgentContext(agent_id="test", scope="paper")
        d = ctx.to_dict()
        assert d["agent_id"] == "test"
        assert d["scope"] == "paper"
        assert "budget" in d


class TestTerminalState:
    """Terminal state enum values."""

    def test_all_states(self):
        from merid.guardrails.budget import TerminalState
        states = [s.value for s in TerminalState]
        assert "executed_safely" in states
        assert "budget_exceeded" in states
        assert "cycle_detected" in states
        assert "confidence_stall" in states
        assert "escalated" in states


# ═══════════════════════════════════════════════════════════════════════
# §3 — Trace Persistence
# ═══════════════════════════════════════════════════════════════════════

class TestTraceStep:
    """TraceStep construction."""

    def test_defaults(self):
        from merid.guardrails.trace import TraceStep
        s = TraceStep()
        assert s.step_index == 0
        assert s.tools_called == []
        assert s.outcome == ""

    def test_to_dict(self):
        from merid.guardrails.trace import TraceStep
        s = TraceStep(agent_id="a1", chosen_action="get_ticker", outcome="success")
        d = s.to_dict()
        assert d["agent_id"] == "a1"
        assert d["chosen_action"] == "get_ticker"


class TestAgentTrace:
    """AgentTrace lifecycle."""

    def test_add_step(self):
        from merid.guardrails.trace import AgentTrace, TraceStep
        t = AgentTrace(task_id="t1", agent_id="a1")
        t.add_step(TraceStep(chosen_action="get_ticker"))
        assert len(t.steps) == 1
        assert t.steps[0].task_id == "t1"
        assert t.steps[0].step_index == 0

    def test_finish(self):
        from merid.guardrails.trace import AgentTrace
        t = AgentTrace()
        t.finish("executed_safely")
        assert t.terminal_state == "executed_safely"
        assert t.finished_at is not None

    def test_to_dict(self):
        from merid.guardrails.trace import AgentTrace, TraceStep
        t = AgentTrace(task_id="t1", agent_id="a1")
        t.add_step(TraceStep(chosen_action="x"))
        t.finish("no_op")
        d = t.to_dict()
        assert d["total_steps"] == 1
        assert d["terminal_state"] == "no_op"
        assert d["total_duration_ms"] is not None


class TestTraceStore:
    """TraceStore SQLite persistence."""

    def test_save_and_retrieve(self):
        from merid.guardrails.trace import TraceStore, AgentTrace, TraceStep
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = TraceStore(db_path=db_path)
            t = AgentTrace(task_id="t1", agent_id="a1")
            t.add_step(TraceStep(chosen_action="get_ticker", outcome="success"))
            t.finish("executed_safely")
            store.save_trace(t)

            retrieved = store.get_trace(t.trace_id)
            assert retrieved is not None
            assert retrieved["task_id"] == "t1"
            assert retrieved["total_steps"] == 1
        finally:
            os.unlink(db_path)

    def test_get_recent_traces(self):
        from merid.guardrails.trace import TraceStore, AgentTrace
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = TraceStore(db_path=db_path)
            for i in range(5):
                t = AgentTrace(task_id=f"t{i}", agent_id="a1")
                t.finish("executed_safely")
                store.save_trace(t)
            recent = store.get_recent_traces(limit=3)
            assert len(recent) == 3
        finally:
            os.unlink(db_path)

    def test_get_stats(self):
        from merid.guardrails.trace import TraceStore, AgentTrace
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = TraceStore(db_path=db_path)
            t = AgentTrace(task_id="t1", agent_id="a1")
            t.finish("executed_safely")
            store.save_trace(t)
            stats = store.get_stats()
            assert stats["total_traces"] == 1
            assert "executed_safely" in stats["by_terminal_state"]
        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════
# §4 — Guarded Router (full pipeline)
# ═══════════════════════════════════════════════════════════════════════

class TestGuardedToolRouter:
    """Full guardrail pipeline enforcement."""

    def _make_router(self):
        """Create a fresh router with isolated registries for testing."""
        from merid.guardrails.tools import ToolRegistry, ToolDefinition
        from merid.guardrails.capabilities import CapabilityStore, AgentCapabilityMap
        from merid.guardrails.policy import PolicyEngine
        from merid.guardrails.trace import TraceStore
        from merid.guardrails.router import GuardedToolRouter

        tools = ToolRegistry()
        caps = CapabilityStore()
        policy = PolicyEngine()

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        traces = TraceStore(db_path=db_path)

        # Register a test tool
        async def _echo(**kwargs):
            from merid.guardrails.tools import ToolResult
            return ToolResult.ok(kwargs, source="test")

        tools.register(ToolDefinition(
            name="echo", description="Echo params", input_schema={}, output_schema={},
            risk_level="low", handler=_echo, scopes=["research", "paper", "live"],
        ))
        tools.register(ToolDefinition(
            name="dangerous", description="Dangerous tool", input_schema={}, output_schema={},
            risk_level="high", handler=_echo, scopes=["live"],
        ))

        # Register agent with limited capabilities
        caps.register(AgentCapabilityMap(
            agent_id="test-agent",
            allowed_tools={"echo"},
            max_scope="paper",
        ))

        return GuardedToolRouter(tools, caps, policy, traces), db_path

    @pytest.mark.asyncio
    async def test_successful_call(self):
        from merid.guardrails.budget import AgentContext
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(agent_id="test-agent", scope="paper")
            ctx.capabilities = {"echo"}
            result = await router.call_tool("echo", {"msg": "hello"}, ctx)
            assert result.success
            assert result.payload["msg"] == "hello"
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        from merid.guardrails.budget import AgentContext
        from merid.guardrails.tools import ToolErrorCode
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(agent_id="test-agent", scope="paper")
            result = await router.call_tool("nonexistent", {}, ctx)
            assert not result.success
            assert result.error_code == ToolErrorCode.NOT_FOUND
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_permission_denied(self):
        from merid.guardrails.budget import AgentContext
        from merid.guardrails.tools import ToolErrorCode
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(agent_id="test-agent", scope="paper")
            result = await router.call_tool("dangerous", {}, ctx)
            assert not result.success
            assert result.error_code == ToolErrorCode.PERMISSION_DENIED
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_scope_denied(self):
        from merid.guardrails.budget import AgentContext
        from merid.guardrails.tools import ToolErrorCode
        from merid.guardrails.capabilities import AgentCapabilityMap
        router, db_path = self._make_router()
        try:
            # Agent has paper scope but tool only available in live
            router._caps.register(AgentCapabilityMap(
                agent_id="scope-test", allowed_tools={"dangerous"}, max_scope="paper",
            ))
            ctx = AgentContext(agent_id="scope-test", scope="paper")
            result = await router.call_tool("dangerous", {}, ctx)
            assert not result.success
            # Tool "dangerous" only in ["live"] scope, agent is in "paper"
            assert result.error_code == ToolErrorCode.PERMISSION_DENIED
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        from merid.guardrails.budget import AgentContext, AgentBudget
        from merid.guardrails.tools import ToolErrorCode
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(
                agent_id="test-agent", scope="paper",
                budget=AgentBudget(max_tool_calls=1),
            )
            ctx.tool_calls = 2  # already exceeded
            result = await router.call_tool("echo", {}, ctx)
            assert not result.success
            assert result.error_code == ToolErrorCode.BUDGET_EXCEEDED
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_trace_recorded(self):
        from merid.guardrails.budget import AgentContext
        from merid.guardrails.trace import AgentTrace
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(agent_id="test-agent", scope="paper")
            trace = AgentTrace(task_id=ctx.task_id, agent_id=ctx.agent_id)
            await router.call_tool("echo", {"x": 1}, ctx, trace=trace)
            assert len(trace.steps) == 1
            assert trace.steps[0].tools_called == ["echo"]
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_stats(self):
        from merid.guardrails.budget import AgentContext
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(agent_id="test-agent", scope="paper")
            await router.call_tool("echo", {}, ctx)
            await router.call_tool("nonexistent", {}, ctx)
            stats = router.get_stats()
            assert stats["total_calls"] == 2
            assert stats["denied_calls"] == 1
        finally:
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_batch_stops_on_hard_failure(self):
        from merid.guardrails.budget import AgentContext, AgentBudget
        router, db_path = self._make_router()
        try:
            ctx = AgentContext(
                agent_id="test-agent", scope="paper",
                budget=AgentBudget(max_tool_calls=2),
            )
            calls = [("echo", {"a": 1}), ("echo", {"a": 2}), ("echo", {"a": 3})]
            results = await router.call_tool_batch(calls, ctx)
            # Should get 2 successes then budget exceeded stops the batch
            assert len(results) == 3
            assert results[0].success
            assert results[1].success
            assert not results[2].success
        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════
# Module-level wiring checks
# ═══════════════════════════════════════════════════════════════════════

class TestModuleWiring:
    """Verify the guardrails package imports and singletons work."""

    def test_package_imports(self):
        from merid.guardrails import (
            ToolResult, ToolValidity, ToolRegistry, get_tool_registry, tool,
            AgentTrace, TraceStep, TraceStore, get_trace_store,
            AgentBudget, AgentContext, BudgetExceeded, TerminalState,
            AgentCapabilityMap, CapabilityStore, get_capability_store,
            PolicyVerdict, PolicyEngine, get_policy_engine,
            GuardedToolRouter, get_guarded_router,
        )
        assert ToolResult is not None
        assert GuardedToolRouter is not None

    def test_singletons_are_stable(self):
        from merid.guardrails.tools import get_tool_registry
        from merid.guardrails.capabilities import get_capability_store
        from merid.guardrails.policy import get_policy_engine
        from merid.guardrails.router import get_guarded_router
        assert get_tool_registry() is get_tool_registry()
        assert get_capability_store() is get_capability_store()
        assert get_policy_engine() is get_policy_engine()
        assert get_guarded_router() is get_guarded_router()

    def test_builtin_tools_registered(self):
        import merid.guardrails.builtin_tools  # noqa: F401
        from merid.guardrails.tools import get_tool_registry
        reg = get_tool_registry()
        names = reg.list_names()
        assert "get_order_book" in names
        assert "get_ticker" in names
        assert "place_order" in names
        assert "trigger_halt" in names

    def test_api_endpoint_file_exists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "web", "api", "guardrails_api.py")
        assert os.path.exists(path)
