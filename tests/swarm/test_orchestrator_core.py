"""Targeted tests for swarm.orchestrator core behaviors."""

from __future__ import annotations

from typing import List, Set

import pytest

from swarm import orchestrator as orch


class StubModelInterface(orch.ModelInterface):
    def __init__(self, *, response: str = "ok", confidence: float = 0.9, should_raise: bool = False):
        self.response = response
        self.confidence = confidence
        self.should_raise = should_raise

    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.7) -> tuple[str, float]:
        if self.should_raise:
            raise RuntimeError("generation failure")
        return self.response, self.confidence

    def classify(self, text: str, labels: List[str]) -> tuple[str, float]:
        return labels[0], 0.5

    def get_capabilities(self) -> Set[orch.ModelCapability]:
        return {orch.ModelCapability.REASONING}


def test_select_model_provider_prefers_privacy():
    orchestrator = orch.SwarmOrchestrator()
    provider = orchestrator.select_model_provider("coordinator_001", prefer_privacy=True)
    assert provider is not None
    assert provider.supports_private_deployment is True


def test_execute_task_without_interface_sets_failure():
    orchestrator = orch.SwarmOrchestrator()
    task = orchestrator.create_task("coordinator_001", "analysis", "Investigate market")
    result = orchestrator.execute_task(task.task_id)
    assert result.success is False
    assert result.error_message.startswith("No interface for provider")


def test_execute_task_failure_applies_model_fallback(monkeypatch):
    orchestrator = orch.SwarmOrchestrator()
    stub_interface = StubModelInterface(should_raise=True)
    orchestrator.register_model_interface("local_llama", stub_interface)

    task = orchestrator.create_task("coordinator_001", "analysis", "Simulate failure")
    result = orchestrator.execute_task(task.task_id)

    assert result.success is False
    assert result.fallback_strategy is orch.FallbackStrategy.MODEL_FALLBACK
    assert result.retry_count == 1


def test_execute_task_success_records_result():
    orchestrator = orch.SwarmOrchestrator()
    stub_interface = StubModelInterface(response="done", confidence=0.42)
    orchestrator.register_model_interface("local_llama", stub_interface)

    task = orchestrator.create_task("coordinator_001", "analysis", "Complete work")
    result = orchestrator.execute_task(task.task_id)

    assert result.success is True
    assert result.result == "done"
    assert pytest.approx(result.confidence, rel=1e-3) == 0.42


def test_apply_fallback_escalates_after_retries():
    orchestrator = orch.SwarmOrchestrator()
    task = orchestrator.create_task("coordinator_001", "analysis", "Escalate")
    task.retry_count = orchestrator.get_agent_config("coordinator_001").max_retries

    orchestrator._apply_fallback(task)

    assert task.fallback_strategy is orch.FallbackStrategy.HUMAN_ESCALATION
