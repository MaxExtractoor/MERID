"""Tests for swarm.dev_swarm_orchestrator high-risk flows."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import swarm.dev_swarm_orchestrator as orchestrator_module
from swarm.dev_swarm_orchestrator import DevSwarmOrchestrator, DevTask, TaskStatus, TaskType
from swarm.command_runner import CommandResult, CommandStatus
from core.policy_engine import PolicyDecision


def make_task(task_id: str, task_type: TaskType, priority: int) -> DevTask:
    return DevTask(
        task_id=task_id,
        task_type=task_type,
        description=f"task {task_id}",
        priority=priority,
        status=TaskStatus.PENDING,
    )


def test_task_queue_assigns_by_capability_and_priority():
    orchestrator = DevSwarmOrchestrator()

    low = make_task("low", TaskType.DOCUMENTATION, priority=1)
    high = make_task("high", TaskType.FEATURE, priority=10)

    orchestrator.submit_task(low)
    orchestrator.submit_task(high)

    assert orchestrator._task_queue[0] == "high"

    selected_agent = orchestrator._select_agent(orchestrator._tasks["high"])
    assert selected_agent is not None
    assert selected_agent.role == "coder"
    assert selected_agent.current_task is None


@pytest.mark.asyncio
async def test_budget_and_rate_limits_enforced(monkeypatch):
    orchestrator = DevSwarmOrchestrator()
    task = make_task("budget", TaskType.FEATURE, priority=5)
    agent = orchestrator._agents["coder_1"]

    class BudgetedGateway:
        def __init__(self):
            self.blocked = False

        async def generate(self, request):
            self.blocked = True
            return None

    fake_gateway = BudgetedGateway()
    monkeypatch.setattr(
        "swarm.local_llm_gateway.get_local_llm_gateway",
        lambda: fake_gateway,
        raising=False,
    )

    success = await orchestrator._execute_task(task, agent)

    assert success is False
    assert task.status == TaskStatus.FAILED
    assert fake_gateway.blocked is True
    assert agent.current_task is None


@pytest.mark.asyncio
async def test_failed_tasks_escalate_with_context(monkeypatch):
    orchestrator = DevSwarmOrchestrator()
    task = make_task("fail", TaskType.FEATURE, priority=2)
    agent = orchestrator._agents["coder_2"]

    class ExplodingGateway:
        async def generate(self, request):
            raise RuntimeError("provider outage")

    events = []

    class LoggerStub:
        def error(self, message):
            events.append(message)

        def info(self, *args, **kwargs):
            pass

    monkeypatch.setattr(orchestrator_module, "logger", LoggerStub())
    monkeypatch.setattr(
        "swarm.local_llm_gateway.get_local_llm_gateway",
        lambda: ExplodingGateway(),
        raising=False,
    )

    result = await orchestrator._execute_task(task, agent)

    assert result is False
    assert task.status == TaskStatus.FAILED
    assert agent.current_task is None
    assert any("fail" in message for message in events)

    assert orchestrator._tasks["fail"].status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_execute_command_records_guardrail_blocks(monkeypatch):
    orchestrator = DevSwarmOrchestrator()
    task = make_task("cmd", TaskType.FEATURE, priority=3)
    orchestrator.submit_task(task)

    guardrail_result = CommandResult(
        status=CommandStatus.DENIED,
        exit_code=None,
        stdout="",
        stderr="blocked",
        guardrail_decision=PolicyDecision.DENY,
        guardrail_id="Test-Guardrail",
        guardrail_rationale="forbidden",
    )

    class StubRunner:
        def __init__(self, result):
            self.result = result
            self.requests = []

        def run(self, request):
            self.requests.append(request)
            return self.result

    stub_runner = StubRunner(guardrail_result)

    monkeypatch.setattr(
        "swarm.dev_swarm_orchestrator.get_command_runner",
        lambda: stub_runner,
        raising=False,
    )

    result = await orchestrator.execute_command(
        task_id="cmd",
        command="rm -rf /",
        agent_id="coder_1",
        surface="dev_swarm",
        action="destroy_system",
    )

    assert result.status == CommandStatus.DENIED
    stored_task = orchestrator._tasks["cmd"]
    assert stored_task.command_history, "command history not recorded"
    assert stored_task.blocked_reason is not None
    assert "Guardrail" in stored_task.blocked_reason
    assert any("COMMAND`" in artifact or "COMMAND" in artifact for artifact in stored_task.artifacts)
