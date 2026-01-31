"""Tests for swarm.dev_swarm_orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from core.policy_engine import PolicyDecision

import swarm.dev_swarm_orchestrator as orchestrator_module
from swarm import local_llm_gateway as local_llm_module
from swarm.command_runner import CommandResult, CommandStatus
from swarm.dev_swarm_orchestrator import (
    DevAgent,
    DevSwarmOrchestrator,
    DevTask,
    TaskStatus,
    TaskType,
    get_dev_swarm_orchestrator,
)


@pytest.fixture()
def orchestrator(monkeypatch):
    orch = DevSwarmOrchestrator()

    real_sleep = asyncio.sleep

    async def fast_sleep(*_args, **_kwargs):
        await real_sleep(0)

    monkeypatch.setattr(orchestrator_module.asyncio, "sleep", fast_sleep)

    class DummyTelemetry:
        def log_structured(self, **kwargs):  # pragma: no cover - no side effects
            self.last = kwargs

    monkeypatch.setattr(orch, "_telemetry", DummyTelemetry())

    async def fake_execute_task(task: DevTask, agent: DevAgent):
        task.status = TaskStatus.IN_PROGRESS
        await asyncio.sleep(0)
        task.status = TaskStatus.REVIEW
        orch._task_queue.append(task.task_id)
        return True

    monkeypatch.setattr(orch, "_execute_task", fake_execute_task)
    async def fake_review_task(task: DevTask):
        task.status = TaskStatus.TESTING
        return True

    monkeypatch.setattr(orch, "_review_task", fake_review_task)
    async def fake_test_task(task: DevTask):
        task.status = TaskStatus.COMPLETED
        return True

    monkeypatch.setattr(orch, "_test_task", fake_test_task)
    return orch


def _make_task(task_id: str, *, priority: int = 1, task_type: TaskType = TaskType.FEATURE) -> DevTask:
    return DevTask(
        task_id=task_id,
        task_type=task_type,
        description="desc",
        priority=priority,
        status=TaskStatus.PENDING,
    )


def test_submit_task_orders_queue_by_priority(orchestrator):
    high = _make_task("high", priority=10)
    low = _make_task("low", priority=1)

    orchestrator.submit_task(low)
    orchestrator.submit_task(high)

    assert orchestrator._task_queue == ["high", "low"]


def test_select_agent_prefers_role_match(orchestrator):
    task = _make_task("t1", task_type=TaskType.TEST)
    agent = orchestrator._select_agent(task)

    assert agent is not None
    assert agent.role == "tester"


@pytest.mark.asyncio
async def test_orchestrate_advances_task_states(orchestrator):
    task = _make_task("t-progress")
    orchestrator.submit_task(task)

    task_statuses: List[TaskStatus] = []

    async def stop_when_done():
        while task.status != TaskStatus.COMPLETED:
            task_statuses.append(task.status)
            await asyncio.sleep(0)
        orchestrator.stop()

    orchestrate_task = asyncio.create_task(orchestrator.orchestrate())
    await asyncio.wait_for(stop_when_done(), timeout=1)
    await asyncio.sleep(0)
    orchestrate_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await orchestrate_task

    assert TaskStatus.IN_PROGRESS in task_statuses
    assert TaskStatus.REVIEW in task_statuses
    assert TaskStatus.TESTING in task_statuses
    assert task.status == TaskStatus.COMPLETED


def test_record_command_result_tracks_history(monkeypatch, orchestrator):
    task = _make_task("cmd")
    orchestrator.submit_task(task)

    class DummyResult:
        status = TaskStatus.COMPLETED  # type: ignore[assignment]
        guardrail_decision = PolicyDecision.ALLOW
        guardrail_id = "policy123"
        guardrail_rationale = "ok"
        stdout = "hello"
        stderr = ""
        exit_code = 0

    orchestrator._record_command_result(task, "echo hi", DummyResult(), latency_decision=None)

    assert task.command_history
    assert "COMMAND `echo hi`" in task.artifacts[-1]


def test_get_swarm_status_reports_counts(orchestrator):
    orchestrator.submit_task(_make_task("one", task_type=TaskType.TEST))
    orchestrator.submit_task(_make_task("two", task_type=TaskType.FEATURE))

    status = orchestrator.get_swarm_status()

    assert status["tasks"]["pending"] == 2
    assert "coder_1" in status["agents"]


def test_register_agent_replaces_existing(orchestrator):
    agent = DevAgent(agent_id="coder_1", role="coder", capabilities=["python"], active=False)

    orchestrator.register_agent(agent)

    assert orchestrator._agents["coder_1"].active is False


def test_get_dev_swarm_orchestrator_returns_singleton():
    first = get_dev_swarm_orchestrator()
    second = get_dev_swarm_orchestrator()

    assert first is second


class _DummyTelemetry:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def log_structured(self, **kwargs: Any) -> None:  # pragma: no cover - simple storage
        self.events.append(kwargs)


class _DummyLatencyProbe:
    def __init__(self, metadata: Dict[str, str]):
        self.domain = "dev_swarm"
        self.workflow = "command_execution"
        self.metadata = metadata
        self.decision = SimpleNamespace(
            domain=self.domain,
            workflow=self.workflow,
            status="within_slo",
            observed_ms=5.0,
            fallback=SimpleNamespace(strategy_id="scale_out"),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - no cleanup needed
        return False


@pytest.fixture()
def orchestrator_real(monkeypatch):
    orch = DevSwarmOrchestrator()

    orch._telemetry = _DummyTelemetry()

    @contextlib.contextmanager
    def fake_llm_probe(*_args, **_kwargs):
        yield None

    def fake_dev_probe(metadata, *, decision_key=None):  # noqa: ARG001
        probe = _DummyLatencyProbe(metadata)
        return contextlib.contextmanager(lambda: (yield probe))()  # type: ignore[misc]

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(orchestrator_module, "record_llm_request", fake_llm_probe)
    monkeypatch.setattr(orchestrator_module, "record_dev_swarm_command", fake_dev_probe)
    monkeypatch.setattr(orchestrator_module.asyncio, "to_thread", immediate_to_thread)

    return orch


@pytest.mark.asyncio
async def test_execute_task_transitions_to_review(monkeypatch, orchestrator_real):
    class DummyGateway:
        async def generate(self, request):  # pragma: no cover - simple mock
            return SimpleNamespace(response_text=f"response for {request.request_id}")

    monkeypatch.setattr(
        local_llm_module,
        "get_local_llm_gateway",
        lambda: DummyGateway(),
    )

    task = _make_task("exec-review", task_type=TaskType.FEATURE)
    agent = orchestrator_real._agents["coder_1"]

    success = await orchestrator_real._execute_task(task, agent)

    assert success is True
    assert task.status == TaskStatus.REVIEW
    assert any("response for task_exec-review" in artifact for artifact in task.artifacts)
    assert orchestrator_real._telemetry.events[-1]["event_type"] == "task_progress"


@pytest.mark.asyncio
async def test_execute_task_handles_missing_response(monkeypatch, orchestrator_real):
    class NullGateway:
        async def generate(self, request):  # pragma: no cover - simple mock
            return None

    monkeypatch.setattr(
        local_llm_module,
        "get_local_llm_gateway",
        lambda: NullGateway(),
    )

    task = _make_task("exec-fail", task_type=TaskType.FEATURE)
    agent = orchestrator_real._agents["coder_1"]

    success = await orchestrator_real._execute_task(task, agent)

    assert success is False
    assert task.status == TaskStatus.FAILED
    assert orchestrator_real._telemetry.events[-1]["event_type"] == "task_failed"


def test_select_agent_falls_back_to_any_available_agent():
    orchestrator = DevSwarmOrchestrator()
    for agent in orchestrator._agents.values():
        if agent.role == "coder":
            agent.active = False

    task = _make_task("fallback", task_type=TaskType.FEATURE)
    selected = orchestrator._select_agent(task)

    assert selected is not None
    assert selected.role != "coder"


@pytest.mark.asyncio
async def test_execute_task_completes_non_feature(monkeypatch, orchestrator_real):
    class DummyGateway:
        async def generate(self, request):  # pragma: no cover - simple mock
            return SimpleNamespace(response_text=f"done for {request.request_id}")

    monkeypatch.setattr(
        local_llm_module,
        "get_local_llm_gateway",
        lambda: DummyGateway(),
    )

    task = _make_task("doc-complete", task_type=TaskType.TEST)
    agent = orchestrator_real._agents["tester_unit_core"]

    success = await orchestrator_real._execute_task(task, agent)

    assert success is True
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_execute_command_unknown_task_raises(orchestrator_real):
    with pytest.raises(ValueError, match="Unknown task_id"):
        await orchestrator_real.execute_command("missing", "echo hi")


@pytest.mark.asyncio
async def test_execute_command_unknown_agent_raises(orchestrator_real):
    task = _make_task("cmd-agent")
    orchestrator_real.submit_task(task)

    with pytest.raises(ValueError, match="Unknown agent_id"):
        await orchestrator_real.execute_command(task.task_id, "echo hi", agent_id="ghost")


@pytest.mark.asyncio
async def test_execute_command_denied_updates_task(monkeypatch, orchestrator_real):
    denied_result = CommandResult(
        status=CommandStatus.DENIED,
        exit_code=None,
        stdout="",
        stderr="forbidden",
        guardrail_decision=PolicyDecision.DENY,
        guardrail_id="ga-1",
        guardrail_rationale="blocked",
    )

    class DummyRunner:
        def __init__(self, result):
            self.result = result

        def run(self, request):  # pragma: no cover - simple mock
            self.last_request = request
            return self.result

    monkeypatch.setattr(orchestrator_module, "get_command_runner", lambda: DummyRunner(denied_result))

    task = _make_task("cmd-deny")
    orchestrator_real.submit_task(task)

    result = await orchestrator_real.execute_command(task.task_id, "echo blocked")

    assert result.status is CommandStatus.DENIED
    assert task.status == TaskStatus.FAILED
    assert "guardrail" in (task.blocked_reason or "").lower()
    assert any(event["event_type"] == "task_guardrail_denied" for event in orchestrator_real._telemetry.events)


@pytest.mark.asyncio
async def test_execute_command_success_emits_event(monkeypatch, orchestrator_real):
    ok_result = CommandResult(
        status=CommandStatus.EXECUTED,
        exit_code=0,
        stdout="done",
        stderr="",
        guardrail_decision=PolicyDecision.ALLOW,
        guardrail_id="policy-allow",
        guardrail_rationale="ok",
    )

    class DummyRunner:
        def __init__(self, result):
            self.result = result

        def run(self, request):  # pragma: no cover - simple mock
            self.last_request = request
            return self.result

    monkeypatch.setattr(orchestrator_module, "get_command_runner", lambda: DummyRunner(ok_result))

    task = _make_task("cmd-ok")
    orchestrator_real.submit_task(task)

    result = await orchestrator_real.execute_command(task.task_id, "echo ok")

    assert result.status is CommandStatus.EXECUTED
    assert task.blocked_reason is None
    assert task.command_history[-1].latency_status == "within_slo"
    assert task.command_history[-1].latency_fallback == "scale_out"
    assert any(event["event_type"] == "command_executed" for event in orchestrator_real._telemetry.events)


def test_record_command_result_pending_sets_blocked_reason(orchestrator_real):
    task = _make_task("pending-block")
    orchestrator_real.submit_task(task)

    pending = CommandResult(
        status=CommandStatus.PENDING_APPROVAL,
        exit_code=None,
        stdout="waiting",
        stderr="",
        guardrail_decision=PolicyDecision.REQUIRE_APPROVAL,
        guardrail_id="ga",
        guardrail_rationale="needs approval",
    )

    orchestrator_real._record_command_result(task, "echo hold", pending)

    assert "requires approval" in (task.blocked_reason or "")


def test_emit_task_event_includes_metadata(orchestrator_real):
    telemetry = _DummyTelemetry()
    orchestrator_real._telemetry = telemetry
    task = _make_task("meta-task")
    task.metadata["risk"] = "high"

    orchestrator_real._emit_task_event("custom", task, {"extra": "field"})

    fields = telemetry.events[-1]["fields"]
    assert fields["meta.risk"] == "high"
    assert fields["extra"] == "field"


def test_emit_task_event_handles_telemetry_errors(orchestrator_real, caplog):
    class BrokenTelemetry:
        def log_structured(self, **kwargs):  # pragma: no cover - forced failure
            raise RuntimeError("boom")

    orchestrator_real._telemetry = BrokenTelemetry()
    task = _make_task("telemetry-error")

    with caplog.at_level("ERROR"):
        orchestrator_real._emit_task_event("broken", task, None)

    assert any("Failed to emit telemetry" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_review_task_handles_no_reviewer(monkeypatch, orchestrator_real):
    for agent in orchestrator_real._agents.values():
        if agent.role == "reviewer":
            agent.current_task = "busy"

    task = _make_task("no-review")
    task.status = TaskStatus.REVIEW

    result = await orchestrator_real._review_task(task)
    assert result is False


@pytest.mark.asyncio
async def test_review_task_transitions_to_testing(monkeypatch, orchestrator_real):
    async def immediate_sleep(_):
        return None

    monkeypatch.setattr(orchestrator_module.asyncio, "sleep", immediate_sleep)

    task = _make_task("review-pass")
    task.status = TaskStatus.REVIEW

    result = await orchestrator_real._review_task(task)

    assert result is True
    assert task.status == TaskStatus.TESTING


@pytest.mark.asyncio
async def test_test_task_handles_no_tester(orchestrator_real):
    for agent in orchestrator_real._agents.values():
        if agent.role == "tester":
            agent.current_task = "busy"

    task = _make_task("no-test")
    task.status = TaskStatus.TESTING

    result = await orchestrator_real._test_task(task)
    assert result is False


@pytest.mark.asyncio
async def test_test_task_completes_and_emits(monkeypatch, orchestrator_real):
    async def immediate_sleep(_):
        return None

    monkeypatch.setattr(orchestrator_module.asyncio, "sleep", immediate_sleep)

    task = _make_task("test-pass")
    task.status = TaskStatus.TESTING

    result = await orchestrator_real._test_task(task)

    assert result is True
    assert task.status == TaskStatus.COMPLETED
