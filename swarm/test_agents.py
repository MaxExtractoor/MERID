"""Test swarm agent registry and heuristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class TestAgentProfile:
    """Declarative profile describing a test agent specialization."""

    agent_id: str
    role: str = "tester"
    capabilities: Sequence[str] = field(default_factory=list)
    focus_areas: Sequence[str] = field(default_factory=list)
    description: str = ""


_DEFAULT_TEST_AGENT_PROFILES: List[TestAgentProfile] = [
    TestAgentProfile(
        agent_id="tester_unit_core",
        capabilities=["unit_testing", "coverage_analysis", "core_module_focus"],
        focus_areas=["core", "strategy", "execution"],
        description="Targets core modules for coverage/mutation improvements.",
    ),
    TestAgentProfile(
        agent_id="tester_unit_governance",
        capabilities=["unit_testing", "governance_policies", "mutation_testing"],
        focus_areas=["governance", "meta_audit"],
        description="Ensures governance & MetaAuditRuntime coverage stays high.",
    ),
    TestAgentProfile(
        agent_id="tester_integration_api",
        capabilities=["integration_testing", "api_contracts", "trace_replay"],
        focus_areas=["api", "event_bus", "telemetry"],
        description="Builds integration tests from observed API/event traces.",
    ),
    TestAgentProfile(
        agent_id="tester_integration_persistence",
        capabilities=["integration_testing", "persistence", "state_validation"],
        focus_areas=["persistence", "observability"],
        description="Validates persistence + observability wiring end-to-end.",
    ),
    TestAgentProfile(
        agent_id="tester_self_heal",
        capabilities=["flaky_detection", "fixture_refactor", "resilient_testing"],
        focus_areas=["flaky_tests", "self_healing"],
        description="Classifies flaky tests and proposes resilient fixes.",
    ),
    TestAgentProfile(
        agent_id="tester_incident_discovery",
        capabilities=["log_mining", "incident_analysis", "scenario_generation"],
        focus_areas=["incidents", "regressions"],
        description="Turns incidents/log anomalies into regression scenarios.",
    ),
    TestAgentProfile(
        agent_id="tester_coverage_swarm",
        role="DevSwarmCoverageAgent",
        capabilities=["run_swarm_tests", "read_repo_files", "write_repo_tests"],
        focus_areas=[
            "increasing pytest coverage for swarm/* modules",
            "fixing failing tests when possible without weakening assertions",
            "prioritizing high-risk orchestration, safety, security, and trading modules",
        ],
        description=(
            "Autonomous coverage-focused test agent for MERID. "
            "Runs pytest with coverage, analyzes uncovered lines, adds or updates tests under tests/swarm/, "
            "and helps maintain high coverage across swarm modules."
        ),
    ),
    TestAgentProfile(
        agent_id="ui_builder",
        role="DevSwarmUIAgent",
        capabilities=[
            "design_ui_components",
            "build_react_frontend",
            "integrate_observability_dashboards",
        ],
        focus_areas=[
            "MERID command center dashboard (PnL, risk, positions, system health)",
            "swarm / strategy explorer views",
            "governance and guardrails console",
            "observability and replay/debug panels",
        ],
        description=(
            "UI-focused dev swarm agent responsible for designing and implementing the MERID frontend "
            "(e.g., React/TypeScript), integrated with existing observability and governance APIs."
        ),
    ),
]


def iter_default_test_agents() -> Iterable[TestAgentProfile]:
    """Yield default test agent profiles for registration."""

    return list(_DEFAULT_TEST_AGENT_PROFILES)
