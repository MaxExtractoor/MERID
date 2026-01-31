"""Tests for command_runner and workflow_optimizer modules."""

from __future__ import annotations

from types import SimpleNamespace
import subprocess

import pytest

from swarm import command_runner, workflow_optimizer
from core.policy_engine import PolicyDecision


@pytest.fixture()
def runner(monkeypatch):
    # Stub explainability service and recording to avoid heavy dependencies.
    monkeypatch.setattr(command_runner, "get_explainability_service", lambda: SimpleNamespace())
    monkeypatch.setattr(
        command_runner.CommandRunner,
        "_record_explainability",
        lambda self, request, result, latency_decision=None: setattr(
            self, "_explainability_payload", (request, result, latency_decision)
        ),
    )
    return command_runner.CommandRunner()


def test_guardrail_denied_blocks_execution(monkeypatch, runner):
    monkeypatch.setattr(
        command_runner,
        "evaluate_guardrail",
        lambda context: (PolicyDecision.DENY, "Blocked", "guardrail-deny"),
    )
    monkeypatch.setattr(command_runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("should not run"))

    request = command_runner.CommandRequest(
        command="echo hi",
        surface="dev",
        action="danger",
        intent_id="intent-1",
        agent_id="agent-1",
    )
    result = runner.run(request)

    assert result.status == command_runner.CommandStatus.DENIED
    assert result.guardrail_id == "guardrail-deny"
    assert result.stderr == "Guardrail denied execution"


def test_guardrail_requires_approval(monkeypatch, runner):
    monkeypatch.setattr(
        command_runner,
        "evaluate_guardrail",
        lambda context: (PolicyDecision.REQUIRE_APPROVAL, "Needs approval", "guardrail-approval"),
    )
    monkeypatch.setattr(command_runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("should not run"))

    request = command_runner.CommandRequest(
        command="rm -rf /",
        surface="dev",
        action="risky",
        intent_id="intent-2",
        agent_id="agent-1",
    )
    result = runner.run(request)

    assert result.status == command_runner.CommandStatus.PENDING_APPROVAL
    assert result.stderr == "Human approval required"


def test_execute_command_success(monkeypatch, runner):
    monkeypatch.setattr(
        command_runner,
        "evaluate_guardrail",
        lambda context: (PolicyDecision.ALLOW, "Allowed", None),
    )

    def fake_run(args, **kwargs):
        assert args == ["echo", "hello"]
        return SimpleNamespace(returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    request = command_runner.CommandRequest(
        command="echo hello",
        surface="dev",
        action="info",
        intent_id="intent-3",
        agent_id="agent-1",
        cwd="/tmp",
        env={"FOO": "bar"},
        timeout=5,
    )
    result = runner.run(request)

    assert result.status == command_runner.CommandStatus.EXECUTED
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_execute_command_error(monkeypatch, runner):
    monkeypatch.setattr(
        command_runner,
        "evaluate_guardrail",
        lambda context: (PolicyDecision.ALLOW, "Allowed", None),
    )

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    request = command_runner.CommandRequest(
        command="false",
        surface="dev",
        action="info",
        intent_id="intent-4",
        agent_id="agent-1",
    )
    result = runner.run(request)

    assert result.status == command_runner.CommandStatus.ERROR
    assert result.exit_code == 1
    assert result.stderr == "boom"


def test_execute_command_timeout(monkeypatch, runner):
    monkeypatch.setattr(
        command_runner,
        "evaluate_guardrail",
        lambda context: (PolicyDecision.ALLOW, "Allowed", None),
    )

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    request = command_runner.CommandRequest(
        command="sleep 10",
        surface="dev",
        action="slow",
        intent_id="intent-5",
        agent_id="agent-1",
        timeout=1,
    )
    result = runner.run(request)

    assert result.status == command_runner.CommandStatus.ERROR
    assert "Timeout" in result.stderr


def test_build_env_merges_overrides(runner, monkeypatch):
    monkeypatch.setenv("BASE_VAR", "1")
    env = runner._build_env({"BASE_VAR": "2", "NEW": "3"})

    assert env["BASE_VAR"] == "2"
    assert env["NEW"] == "3"


class TestWorkflowOptimizationEngine:
    def test_critical_path_latency(self):
        engine = workflow_optimizer.WorkflowOptimizationEngine()
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="ingest",
                agent_role="collector",
                avg_latency_ms=100.0,
                depends_on=[],
            )
        )
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="analyze",
                agent_role="analyst",
                avg_latency_ms=200.0,
                depends_on=["ingest"],
            )
        )
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="report",
                agent_role="reporter",
                avg_latency_ms=150.0,
                depends_on=["ingest", "analyze"],
            )
        )

        assert engine.critical_path_latency() == pytest.approx(450.0)

    def test_recommend_parallel_steps(self):
        engine = workflow_optimizer.WorkflowOptimizationEngine()
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="fetch",
                agent_role="collector",
                avg_latency_ms=50.0,
                depends_on=[],
            )
        )
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="score",
                agent_role="analyst",
                avg_latency_ms=80.0,
                depends_on=["fetch"],
            )
        )
        engine.register_step(
            workflow_optimizer.WorkflowStep(
                step_id="audit",
                agent_role="auditor",
                avg_latency_ms=60.0,
                depends_on=["fetch"],
            )
        )

        parallel = engine.recommend_parallel_steps()
        assert set(parallel) == {"fetch", "score", "audit"}
