"""Batch 24 tests for security defense system and Test Swarm planner."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import pytest

from swarm.security_defense_system import (
    AttackVector,
    SecurityDefenseSystem,
    get_security_defense_system,
)
from swarm.test_swarm_planner import DiffStat, TaskType, TestSwarmPlanner


class TestSecurityDefenseSystemCoverage:
    def test_incident_filters_and_prevention_fallback(self) -> None:
        system = SecurityDefenseSystem()

        # Disable default prompt rule to exercise skip branch and add one that raises
        system._detection_rules["detect_prompt_injection"].enabled = False

        def broken_detection(data):  # pragma: no cover - exercising exception logging
            raise RuntimeError("rule failure")

        system.register_detection_rule(
            rule_id="broken_rule",
            attack_vector=AttackVector.JAILBREAK,
            name="Broken",
            description="raises",
            detection_function=broken_detection,
        )

        # Register wallet compromise detector for CRITICAL incidents
        def wallet_detection(data):
            return True, "Wallet compromised", {"detail": "simulated"}

        system.register_detection_rule(
            rule_id="wallet_detector",
            attack_vector=AttackVector.WALLET_COMPROMISE,
            name="Wallet Detector",
            description="critical incident",
            detection_function=wallet_detection,
        )

        # Register prevention control that raises to hit error handling
        def raising_control(data):
            raise RuntimeError("control failure")

        system.register_prevention_control(
            control_id="unstable_control",
            attack_vector=AttackVector.PROMPT_INJECTION,
            name="Unstable",
            description="raises",
            prevention_function=raising_control,
        )

        allowed, _ = system.apply_prevention("safe input", AttackVector.PROMPT_INJECTION)
        assert allowed is True  # built-in control still allows benign input

        # Trigger secret detection and wallet incident
        incidents = system.scan_for_threats(
            "api_key=AKIA1234567890123456",
            context={"components": ["router-core"]},
        )
        assert any(inc.attack_vector == AttackVector.WALLET_COMPROMISE for inc in incidents)
        assert system.get_component_status("router-core") == "offline"
        assert system.get_component_status("unknown") == "healthy"

        # Exercise zero-variance poisoning branch
        detected, _, _ = system._detect_data_poisoning({"values": [1.0] * 12})
        assert detected is False

        # Incident filters and summaries
        wallet_incidents = system.get_incidents(attack_vector=AttackVector.WALLET_COMPROMISE)
        assert wallet_incidents
        recent = system.get_incidents(since=datetime.utcnow() - timedelta(minutes=5))
        assert recent
        summary = system.get_security_summary()
        assert summary["total_incidents"] >= 1

        singleton = get_security_defense_system()
        assert isinstance(singleton, SecurityDefenseSystem)


class StubOrchestrator:
    def __init__(self) -> None:
        self.submitted: List = []

    def submit_task(self, task):
        self.submitted.append(task)
        return task.task_id


class TestSwarmPlannerFlows:
    def test_task_generation_across_modes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = StubOrchestrator()
        monkeypatch.setattr(
            "swarm.test_swarm_planner.get_dev_swarm_orchestrator",
            lambda: stub,
        )

        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps({"api": {"statement_coverage": 70.0}}), encoding="utf-8")
        mutation_path = tmp_path / "mutation.json"
        mutation_path.write_text("{invalid", encoding="utf-8")  # triggers safe default
        flaky_path = tmp_path / "flaky.json"
        flaky_path.write_text(
            json.dumps(
                [
                    {
                        "test": "tests/test_latency.py::test_flaky",
                        "failure_rate": 0.4,
                        "file": "observability/latency.py",
                    }
                ]
            ),
            encoding="utf-8",
        )

        planner = TestSwarmPlanner(
            coverage_report=coverage_path,
            mutation_report=mutation_path,
            flaky_report=flaky_path,
        )

        diffs = [
            DiffStat(
                file_path="api/router.py",
                lines_added=210,
                lines_deleted=5,
                risk_tier="critical",
            )
        ]
        task_ids = planner.plan_for_diff(diffs)
        assert len(task_ids) == 1
        first_task = stub.submitted[0]
        assert first_task.task_type == TaskType.INTEGRATION_TEST
        assert first_task.priority == 10  # escalated by size, coverage, and risk tier
        assert first_task.metadata["coverage"] == 70.0

        self_heal_ids = planner.plan_self_healing()
        assert len(self_heal_ids) == 1
        flaky_task = stub.submitted[-1]
        assert flaky_task.task_type == TaskType.TEST_SELF_HEAL
        assert flaky_task.priority == 8
        assert flaky_task.metadata["module"] == "observability"

        incident_ids = planner.plan_incident_discovery(
            [{"id": "INC123", "module": "core", "severity": "critical"}]
        )
        assert len(incident_ids) == 1
        incident_task = stub.submitted[-1]
        assert incident_task.task_type == TaskType.TEST_DISCOVERY
        assert incident_task.priority == 9
        assert incident_task.metadata["incident_id"] == "INC123"
