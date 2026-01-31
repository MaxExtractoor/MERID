"""Tests for swarm R&D pipeline, secure yield contracts, and spawner."""

from __future__ import annotations

from decimal import Decimal
from itertools import cycle

import pytest

from swarm.rnd_pipeline import ExperimentStage, SwarmRDPipeline
from swarm.secure_yield_contracts import (
    SafetyState,
    SecureYieldContractDesigner,
    SecurityCheckType,
    YieldSource,
)
import swarm.spawner as spawner_module


class TestSwarmRDPipeline:
    def test_submit_record_and_advance_pipeline_experiments(self):
        pipeline = SwarmRDPipeline()

        experiment = pipeline.submit_experiment(
            title="strategy-x",
            owner="alice",
            hypothesis="increase sharpe via hedging",
        )

        pipeline.record_metric(experiment.experiment_id, "sharpe_ratio", 1.42)
        advanced = pipeline.advance_stage(
            experiment.experiment_id,
            ExperimentStage.RESEARCH,
            approval="risk-team",
        )
        assert advanced.stage == ExperimentStage.RESEARCH
        assert advanced.approvals == ["risk-team"]
        assert advanced.metrics["sharpe_ratio"] == 1.42

        pipeline.advance_stage(experiment.experiment_id, ExperimentStage.BUILD)
        assert not pipeline.list_experiments(stage=ExperimentStage.IDEA)
        build_stage = pipeline.list_experiments(stage=ExperimentStage.BUILD)
        assert build_stage[0].title == "strategy-x"


class TestSecureYieldContractDesigner:
    def test_security_workflow_reports_findings_and_controls(self):
        designer = SecureYieldContractDesigner()
        spec = designer.create_contract_spec(
            contract_name="AtlasYield",
            yield_sources=[YieldSource.TRADING_FEES, YieldSource.LP_FEES],
            max_leverage=Decimal("1.5"),
            max_external_exposure_pct=40.0,
        )
        spec.upgrade_delay_hours = 12  # force upgrade warning
        spec.core_accounting_module = ""

        vulnerable_code = (
            "pragma solidity ^0.7;"
            "contract Y {"
            "  uint256 balance;"
            "  function withdraw() external {"
            "    (bool success, ) = target.call{value: balance}("");"
            "    if(success) { balance = 0; }"
            "  }"
            "  function adminOnly() external onlyOwner { balance += 1; }"
            "}"
        )

        checks = designer.run_security_checklist(spec.contract_id, contract_code=vulnerable_code)
        findings = {check.check_type: check for check in checks}

        assert findings[SecurityCheckType.REENTRANCY].passed is False
        assert findings[SecurityCheckType.ARITHMETIC].passed is False
        assert findings[SecurityCheckType.ACCOUNTING].passed is False

        breaker = designer.add_circuit_breaker(
            spec.contract_id,
            metric="slippage_bps",
            threshold=75.0,
            action=SafetyState.PAUSED,
        )
        triggered = designer.trigger_circuit_breaker(breaker.breaker_id)
        assert triggered.triggered is True

        limit = designer.add_rate_limit(
            spec.contract_id,
            limit_type="withdrawal",
            max_amount_per_block=Decimal("1000"),
            max_amount_per_hour=Decimal("5000"),
            cooldown_seconds=90,
        )
        assert limit.limit_type == "withdrawal"

        report = designer.get_contract_security_report(spec.contract_id)
        assert report["security_checks"]["total"] == len(checks)
        assert report["circuit_breakers"]["triggered"] == 1
        assert report["rate_limits"]["total"] == 1
        assert report["limits"]["max_leverage"] == "1.5"


class TestSwarmSpawner:
    def test_refresh_population_spawns_child_from_best_parent(self, monkeypatch):
        times = cycle(
            [
                {"utc_iso": "2024-01-01T00:00:00"},
                {"utc_iso": "2024-01-01T00:05:00"},
                {"utc_iso": "2024-01-01T00:10:00"},
            ]
        )
        monkeypatch.setattr(spawner_module, "current_time", lambda: next(times))
        monkeypatch.setattr(spawner_module.random, "shuffle", lambda seq: None)
        monkeypatch.setattr(spawner_module.random, "choice", lambda seq: 0)

        class DummyLogger:
            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

        monkeypatch.setattr(spawner_module, "get_logger", lambda _: DummyLogger())

        class DummyLedger:
            def __init__(self):
                self.parent_requests = 0

            def leaderboard(self, limit: int = 20):
                return [
                    {"agent_id": "alpha#0000", "score": 0.8, "votes": 8},
                    {"agent_id": "beta#0000", "score": 0.3, "votes": 9},
                ]

            def best_parent(self, *, min_score: float = 0.55, min_votes: int = 5):
                self.parent_requests += 1
                return {"agent_id": "alpha#0000", "score": 0.82, "votes": 8}

        class DummyAgent:
            def __init__(self, agent_id: str, model_name: str = "atlas", tool_budget: int = 5):
                self.agent_id = agent_id
                self.model_name = model_name
                self.tool_budget = tool_budget
                self.trust = 1.0

        ledger = DummyLedger()
        spawner = spawner_module.SwarmSpawner(
            ledger,
            max_population=3,
            spawn_threshold=0.5,
            min_votes_to_spawn=5,
        )

        spawner.bootstrap([DummyAgent("alpha#0000"), DummyAgent("beta#0000")])
        refreshed = spawner.refresh_population()

        assert len(refreshed) == 3
        assert ledger.parent_requests == 1

        lineage = {record.agent_id: record for record in spawner.lineage()}
        new_children = [agent for agent in refreshed if agent.agent_id not in {"alpha#0000", "beta#0000"}]
        assert new_children, "expected a spawned child"
        child = new_children[0]
        assert lineage[child.agent_id].parent_id == "alpha#0000"
        assert lineage[child.agent_id].generation == 1
        assert lineage["alpha#0000"].generation == 0
