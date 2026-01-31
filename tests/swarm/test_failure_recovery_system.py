"""Tests for swarm.failure_recovery_system."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import failure_recovery_system as frs


@pytest.fixture()
def system():
    sys = frs.FailureRecoverySystem()

    # Reset mutable state for deterministic tests
    sys._failure_events.clear()
    sys._circuit_breakers.clear()
    sys._backoff_strategies.clear()
    sys._fallback_paths = {
        "primary_trader": ["backup_trader"],
        "llm_router": ["simple_router"],
    }

    for detector in sys._failure_detectors.values():
        detector.detections = 0
        detector.enabled = True

    for action in sys._recovery_actions.values():
        action.successes = 0
        action.failures = 0
        action.enabled = True

    return sys


def test_detect_failures_creates_events(system):
    context = {
        "component_id": "primary_trader",
        "waiting_for": {"agent-a": "agent-b", "agent-b": "agent-a"},
        "message_history": ["a", "b", "a", "b"],
        "messages_last_10s": 150,
        "llm_confidence": 0.1,
        "exploration_rate": 0.8,
    }

    failures = system.detect_failures(context)

    failure_modes = {event.failure_mode for event in failures}
    assert frs.FailureMode.DEADLOCK in failure_modes
    assert frs.FailureMode.MESSAGE_STORM in failure_modes
    assert frs.FailureMode.LLM_HALLUCINATION in failure_modes
    assert frs.FailureMode.OVER_EXPLORATION in failure_modes

    detector_counts = {det.detector_id: det.detections for det in system._failure_detectors.values()}
    assert detector_counts["detect_deadlock"] == 1
    assert detector_counts["detect_message_storm"] == 1


def test_attempt_recovery_opens_circuit_breaker(system):
    system.register_circuit_breaker("primary_trader", failure_threshold=1, timeout_seconds=30)

    event = system._create_failure_event(
        failure_mode=frs.FailureMode.DEADLOCK,
        affected_component="primary_trader",
        description="deadlock",
        evidence={"agents": ["a", "b"]},
    )

    success = system.attempt_recovery(event)
    breaker = system._circuit_breakers["primary_trader"]

    assert success is True
    assert event.recovery_pattern is frs.RecoveryPattern.CIRCUIT_BREAKER
    assert event.resolved is True and breaker.state == "open"
    assert event.recovery_actions_taken == ["circuit_breaker_open"]


def test_backoff_strategy_advances_on_recovery(system):
    system.register_backoff_strategy(
        component_id="llm_router",
        initial_delay_ms=100,
        max_delay_ms=800,
        multiplier=2.0,
        max_attempts=3,
    )

    event = system._create_failure_event(
        failure_mode=frs.FailureMode.LLM_HALLUCINATION,
        affected_component="llm_router",
        description="low confidence",
        evidence={"confidence": 0.1},
    )

    success = system.attempt_recovery(event)
    strategy = system._backoff_strategies["llm_router"]

    assert success is True
    assert event.recovery_pattern is frs.RecoveryPattern.BACKOFF_RETRY
    assert event.resolved is True
    assert strategy.current_attempt == 1
    assert strategy.current_delay_ms <= strategy.max_delay_ms


def test_summary_and_query_helpers(system):
    system.register_circuit_breaker("primary_trader")
    resolved_event = system._create_failure_event(
        failure_mode=frs.FailureMode.DEADLOCK,
        affected_component="primary_trader",
        description="deadlock",
        evidence={},
    )
    system.attempt_recovery(resolved_event)

    unresolved_event = system._create_failure_event(
        failure_mode=frs.FailureMode.DEADLOCK,
        affected_component="no_breaker_component",
        description="deadlock without breaker",
        evidence={},
    )
    attempt = system.attempt_recovery(unresolved_event)
    assert attempt is False

    recent = system.get_failure_events(since=datetime.utcnow() - timedelta(minutes=1))
    unresolved = system.get_failure_events(resolved=False)

    assert resolved_event in recent and unresolved_event in unresolved

    summary = system.get_recovery_summary()
    assert summary["total_failures"] == 2
    assert summary["unresolved_failures"] == 1
    assert summary["recovery_success_rate"] == pytest.approx(0.5)
