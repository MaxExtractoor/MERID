"""Tests for small swarm modules batch 2."""

from __future__ import annotations

from datetime import datetime

import pytest

from swarm.automated_upgrade_testing import AutomatedUpgradeTester, UpgradeScenario
from swarm.hft_exploit_detection import HFTExploitDetector, ExploitSignal
from swarm.idea_prioritizer import IdeaPrioritizer, IdeaSubmission
from swarm.parameter_optimizer import MLParameterOptimizer
from swarm.scam_pattern_recognition import ScamPatternRecognizer, ScamSignal
from swarm.zk_privacy_bridge import ZKPrivacyBridge


class TestHFTExploitDetector:
    def test_score_returns_zero_with_short_history(self):
        detector = HFTExploitDetector(window_size=20, threshold=2.5)
        signal = ExploitSignal("tx1", "protocol", [1.0, 1.1], timestamp=0.0)

        score = detector.score(signal)
        assert score == 0.0

    def test_is_exploit_triggers_on_high_score(self):
        detector = HFTExploitDetector(window_size=20, threshold=1.0)
        for _ in range(10):
            detector.score(ExploitSignal("tx", "proto", [1.0, 1.1], timestamp=0.0))
        signal = ExploitSignal("tx2", "proto", [10.0, 12.0], timestamp=1.0)

        assert detector.is_exploit(signal) is True


class TestScamPatternRecognizer:
    def test_score_keywords_and_metadata(self):
        recognizer = ScamPatternRecognizer()
        signal = ScamSignal(
            source="social",
            content="Guaranteed returns now",
            metadata={"new_contract": "true", "verified_team": "false"},
            timestamp=datetime.utcnow(),
        )

        score = recognizer.score(signal)
        assert score > 0.5
        assert recognizer.is_scam(signal) is True

    def test_score_safe_content(self):
        recognizer = ScamPatternRecognizer()
        signal = ScamSignal(
            source="social",
            content="Normal market update",
            metadata={"new_contract": "false", "verified_team": "true"},
            timestamp=datetime.utcnow(),
        )

        assert recognizer.score(signal) == 0.0
        assert recognizer.is_scam(signal) is False


class TestAutomatedUpgradeTester:
    def test_register_and_run_scenario(self):
        tester = AutomatedUpgradeTester()
        scenario = UpgradeScenario(
            scenario_id="upgrade-1",
            upgrade_description="Upgrade vault",
            checks=["latency", "throughput"],
        )
        tester.register_scenario(scenario)

        def executor(scenario):
            return []

        result = tester.run("upgrade-1", executor)
        assert result.simulated is True
        assert result.passed is True
        assert result.executed_at is not None

    def test_pending_scenarios(self):
        tester = AutomatedUpgradeTester()
        scenario = UpgradeScenario(
            scenario_id="upgrade-1",
            upgrade_description="Upgrade",
            checks=[],
        )
        tester.register_scenario(scenario)

        pending = tester.pending_scenarios()
        assert len(pending) == 1


class TestIdeaPrioritizer:
    def test_prioritize_orders_by_score(self):
        prioritizer = IdeaPrioritizer()
        prioritizer.submit(
            IdeaSubmission(
                idea_id="idea-1",
                title="Low impact",
                impact_score=0.1,
                effort_score=0.9,
                confidence_score=0.5,
                historical_success_rate=0.5,
                submitted_at=datetime.utcnow(),
            )
        )
        prioritizer.submit(
            IdeaSubmission(
                idea_id="idea-2",
                title="High impact",
                impact_score=0.9,
                effort_score=0.2,
                confidence_score=0.8,
                historical_success_rate=0.7,
                submitted_at=datetime.utcnow(),
            )
        )

        prioritized = prioritizer.prioritize(limit=1)
        assert prioritized[0].idea_id == "idea-2"

    def test_prioritize_returns_rationale(self):
        prioritizer = IdeaPrioritizer()
        prioritizer.submit(
            IdeaSubmission(
                idea_id="idea-1",
                title="Test",
                impact_score=0.5,
                effort_score=0.5,
                confidence_score=0.5,
                historical_success_rate=0.5,
                submitted_at=datetime.utcnow(),
            )
        )

        prioritized = prioritizer.prioritize()
        assert "Impact" in prioritized[0].rationale


class TestMLParameterOptimizer:
    def test_suggest_returns_none_with_insufficient_history(self):
        optimizer = MLParameterOptimizer()
        assert optimizer.suggest("learning_rate") is None

    def test_suggest_returns_nudged_value(self):
        optimizer = MLParameterOptimizer()
        optimizer.record_observation("learning_rate", 0.1, 0.9)
        optimizer.record_observation("learning_rate", 0.2, 0.8)

        suggestion = optimizer.suggest("learning_rate")
        assert suggestion is not None
        assert suggestion.parameter_name == "learning_rate"
        assert suggestion.suggested_value == pytest.approx(0.05)


class TestZKPrivacyBridge:
    def test_create_request(self):
        bridge = ZKPrivacyBridge()
        request = bridge.create_request("req-1", "payload", "circuit-1", {"net": "main"})

        assert request.request_id == "req-1"
        assert "req-1" in bridge._requests

    def test_verify_proof(self):
        bridge = ZKPrivacyBridge()
        request = bridge.create_request("req-1", "payload", "circuit-1", {})
        proof = b"proof-data"

        result = bridge.verify_proof(request.request_id, proof)
        assert result.request_id == "req-1"
        assert result.proof == proof
        assert isinstance(result.verified, bool)
