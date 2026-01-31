"""Tests for orchestration pattern library."""

from __future__ import annotations

from swarm import orchestration_patterns as patterns


def test_get_library_seeds_default_pattern():
    library = patterns.get_orchestration_pattern_library()
    default = library.get_pattern("guardian_handoff")

    assert default is not None
    assert "governor" in default.topology
    assert "intent_bus" in default.communication_channels


def test_register_and_list_patterns():
    library = patterns.OrchestrationPatternLibrary()
    assert len(library.list_patterns()) == 1

    new_pattern = patterns.OrchestrationPattern(
        pattern_id="rapid_incident",
        name="Rapid Incident Response",
        description="Hot swap agents to isolate incident",
        topology={"incident_lead": ["triage"], "triage": ["resolution"], "resolution": []},
        communication_channels=["incident_bus"],
        safety_gates=["incident_review"],
        recommended_use_cases=["incident_response"],
    )

    library.register_pattern(new_pattern)

    listed = library.list_patterns()
    assert len(listed) == 2
    assert any(p.pattern_id == "rapid_incident" for p in listed)
