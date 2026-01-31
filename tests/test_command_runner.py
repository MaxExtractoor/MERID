"""Unit tests for the guardrail-aware command runner."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.policy_engine import PolicyDecision
from swarm.command_runner import CommandRequest, CommandRunner, CommandStatus


class ExplainabilityStub:
    def __init__(self) -> None:
        self.records = []

    def record_explanation(self, *args, **kwargs):
        self.records.append({"args": args, "kwargs": kwargs})


@pytest.fixture
def explainability_stub(monkeypatch):
    stub = ExplainabilityStub()
    monkeypatch.setattr("swarm.command_runner.get_explainability_service", lambda: stub)
    return stub


def test_command_runner_executes_when_guardrail_allows(monkeypatch, explainability_stub):
    monkeypatch.setattr(
        "swarm.command_runner.evaluate_guardrail",
        lambda context: (PolicyDecision.ALLOW, "safe", "Test-Allow"),
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("swarm.command_runner.subprocess.run", fake_run)

    runner = CommandRunner()
    request = CommandRequest(
        command="echo hello",
        surface="dev_swarm",
        action="execute_command",
        intent_id="intent-1",
        agent_id="agent-1",
    )

    result = runner.run(request)

    assert result.status == CommandStatus.EXECUTED
    assert result.exit_code == 0
    assert explainability_stub.records, "Explainability record not created"


def test_command_runner_denies_without_executing(monkeypatch, explainability_stub):
    monkeypatch.setattr(
        "swarm.command_runner.evaluate_guardrail",
        lambda context: (PolicyDecision.DENY, "blocked", "Test-Deny"),
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be invoked when denied")

    monkeypatch.setattr("swarm.command_runner.subprocess.run", fail_run)

    runner = CommandRunner()
    request = CommandRequest(
        command="rm -rf /",
        surface="dev_swarm",
        action="destroy_system",
        intent_id="intent-2",
        agent_id="agent-2",
    )

    result = runner.run(request)

    assert result.status == CommandStatus.DENIED
    assert result.guardrail_decision == PolicyDecision.DENY
    assert "denied" in result.stderr.lower()


def test_command_runner_requires_approval_without_execution(monkeypatch, explainability_stub):
    monkeypatch.setattr(
        "swarm.command_runner.evaluate_guardrail",
        lambda context: (PolicyDecision.REQUIRE_APPROVAL, "needs review", "Test-Approval"),
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be invoked when approval is required")

    monkeypatch.setattr("swarm.command_runner.subprocess.run", fail_run)

    runner = CommandRunner()
    request = CommandRequest(
        command="deploy prod",
        surface="dev_swarm",
        action="deploy_production",
        intent_id="intent-3",
        agent_id="agent-3",
    )

    result = runner.run(request)

    assert result.status == CommandStatus.PENDING_APPROVAL
    assert result.guardrail_decision == PolicyDecision.REQUIRE_APPROVAL
    assert "approval" in result.stderr.lower()


def test_command_runner_records_latency_metadata(monkeypatch, explainability_stub):
    monkeypatch.setattr(
        "swarm.command_runner.evaluate_guardrail",
        lambda context: (PolicyDecision.ALLOW, "fast-path", "Test-Allow"),
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("swarm.command_runner.subprocess.run", fake_run)

    decision = SimpleNamespace(
        domain="dev_swarm",
        workflow="command_execution",
        status="breached_slo",
        observed_ms=123.4,
        fallback=SimpleNamespace(strategy_id="fast_risk_path"),
    )

    class DummyProbe:
        def __init__(self, decision):
            self.decision = decision

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "swarm.command_runner.CommandRunner._build_latency_probe",
        lambda self, request: DummyProbe(decision),
    )

    runner = CommandRunner()
    request = CommandRequest(
        command="echo hello",
        surface="dev_swarm",
        action="execute_command",
        intent_id="intent-4",
        agent_id="agent-latency",
    )

    result = runner.run(request)

    assert result.status == CommandStatus.EXECUTED
    assert explainability_stub.records, "Explainability record missing"
    recorded_kwargs = explainability_stub.records[-1]["kwargs"]
    assert recorded_kwargs["latency_domain"] == "dev_swarm"
    assert recorded_kwargs["latency_workflow"] == "command_execution"
    assert recorded_kwargs["latency_status"] == "breached_slo"
    assert recorded_kwargs["latency_observed_ms"] == 123.4
    assert recorded_kwargs["latency_fallback_strategy"] == "fast_risk_path"
