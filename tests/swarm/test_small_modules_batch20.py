"""Batch 20 tests for Swarm Lab metrics and snapshots."""

from __future__ import annotations

from swarm.swarm_lab import (
    IdeaStatus,
    RiskLevel,
    SwarmLabOrchestrator,
)


def _rename_impl(orchestrator: SwarmLabOrchestrator, implementation, new_id: str) -> None:
    orchestrator._implementations[new_id] = orchestrator._implementations.pop(implementation.implementation_id)
    implementation.implementation_id = new_id


class TestSwarmLabStatusPayload:
    def test_metrics_snapshots_and_payload_alignment(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        sample_agent = next(iter(orchestrator._agents.values()))

        idea1 = orchestrator.discover_idea(
            theme="Execution",
            category="tool",
            title="Latency dashboard",
            problem="Need realtime view",
            discovered_by=sample_agent.agent_id,
        )
        orchestrator.prioritize_idea(idea1.idea_id, 0.8, 0.2, RiskLevel.LOW)
        design = orchestrator.create_design(idea1.idea_id, "Latency Spec", "desc")
        orchestrator.approve_design(design.design_id, sample_agent.agent_id)
        impl = orchestrator.create_implementation(design.design_id)
        orchestrator.mark_implementation_complete(impl.implementation_id)
        orchestrator.create_rollout(impl.implementation_id)

        metrics = orchestrator.get_metrics()
        assert metrics["ideas_total"] >= 1
        assert metrics["designs_total"] >= 1
        assert metrics["implementations_total"] >= 1

        snapshot = orchestrator.get_agents_snapshot(limit=3)
        assert snapshot and snapshot[0]["agent_id"].startswith("lab_")

        top_ideas = orchestrator.get_top_ideas(limit=3)
        assert any(entry["idea_id"] == idea1.idea_id for entry in top_ideas)
        priorities = [entry["priority"] for entry in top_ideas]
        assert priorities == sorted(priorities, reverse=True)

        payload = orchestrator.get_status_payload()
        assert payload["metrics"] == metrics
        assert payload["top_ideas"][: len(top_ideas)] == top_ideas
        assert payload["agents"][: len(snapshot)] == snapshot

    def test_prioritized_and_active_queries(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        idea_high = orchestrator.discover_idea(
            theme="UX",
            category="ui",
            title="Portfolio heatmap",
            problem="Clarity",
        )
        idea_low = orchestrator.discover_idea(
            theme="Governance",
            category="infra",
            title="Proposal shortcuts",
            problem="Speed",
        )
        orchestrator.prioritize_idea(idea_high.idea_id, 0.9, 0.1, RiskLevel.MEDIUM)
        orchestrator.prioritize_idea(idea_low.idea_id, 0.5, 0.4, RiskLevel.LOW)

        prioritized = orchestrator.get_prioritized_ideas(top_n=2)
        assert prioritized
        assert prioritized[0].idea_id == idea_high.idea_id
        if len(prioritized) > 1:
            assert prioritized[0].priority_score >= prioritized[1].priority_score

        design_active = orchestrator.create_design(idea_high.idea_id, "Heatmap", "desc")
        impl_active = orchestrator.create_implementation(design_active.design_id)
        _rename_impl(orchestrator, impl_active, "impl_active")
        design_complete = orchestrator.create_design(idea_low.idea_id, "Shortcut", "desc")
        impl_complete = orchestrator.create_implementation(design_complete.design_id)
        _rename_impl(orchestrator, impl_complete, "impl_complete")

        active_before = orchestrator.get_active_implementations()
        assert any(impl.implementation_id == "impl_active" for impl in active_before)
        assert any(impl.implementation_id == "impl_complete" for impl in active_before)

        orchestrator.mark_implementation_complete(impl_complete.implementation_id)
        active_after = orchestrator.get_active_implementations()
        assert any(impl.implementation_id == "impl_active" for impl in active_after)
        assert all(impl.implementation_id != "impl_complete" for impl in active_after)

        lab_metrics = orchestrator.get_lab_metrics()
        assert lab_metrics["ideas"]["total"] >= 1
        assert lab_metrics["implementations"]["total"] >= 1
        assert lab_metrics["implementations"]["complete"] >= 0
        assert lab_metrics["rollouts"]["total"] >= 0
