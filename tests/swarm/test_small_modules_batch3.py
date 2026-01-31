"""Tests for additional small swarm modules (batch 3)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from swarm.cross_chain_invariants import (
    ChainState,
    CrossChainInvariantEnforcer,
    Invariant,
)
from swarm.cross_protocol_health import CrossProtocolHealthCorrelator
from swarm.multi_model_ensemble import MultiModelEnsemble, ModelOutput


class TestCrossChainInvariantEnforcer:
    def test_record_state_and_register_invariant(self):
        enforcer = CrossChainInvariantEnforcer()
        state = ChainState(
            chain_id="chain-a",
            reserves_usd=Decimal("100"),
            liabilities_usd=Decimal("80"),
            circulating_supply=Decimal("1000"),
            last_updated=datetime.utcnow(),
        )
        enforcer.record_state(state)
        enforcer.register_invariant(
            Invariant(
                invariant_id="supply",
                description="Supply parity",
                tolerance_pct=Decimal("5"),
            )
        )

        assert enforcer._states["chain-a"].chain_id == "chain-a"
        assert enforcer._invariants["supply"].description == "Supply parity"

    def test_check_supply_parity_detects_breach(self):
        enforcer = CrossChainInvariantEnforcer()
        enforcer.register_invariant(
            Invariant(
                invariant_id="supply",
                description="Supply parity",
                tolerance_pct=Decimal("1"),
            )
        )
        enforcer.record_state(
            ChainState(
                chain_id="chain-a",
                reserves_usd=Decimal("100"),
                liabilities_usd=Decimal("80"),
                circulating_supply=Decimal("1000"),
                last_updated=datetime.utcnow(),
            )
        )
        enforcer.record_state(
            ChainState(
                chain_id="chain-b",
                reserves_usd=Decimal("100"),
                liabilities_usd=Decimal("80"),
                circulating_supply=Decimal("1200"),
                last_updated=datetime.utcnow(),
            )
        )

        breaches = enforcer.check_supply_parity("supply")
        assert len(breaches) == 1
        assert breaches[0].chain_a == "chain-a"
        assert breaches[0].chain_b == "chain-b"
        assert breaches[0].deviation_pct > Decimal("1")


class TestCrossProtocolHealthCorrelator:
    def test_record_series_and_detect_correlations(self):
        correlator = CrossProtocolHealthCorrelator(correlation_threshold=0.9)
        values_a = [1, 2, 3, 4, 5, 6]
        values_b = [2, 4, 6, 8, 10, 12]
        correlator.record_series("dex", "latency", values_a)
        correlator.record_series("lending", "latency", values_b)

        alerts = correlator.detect_correlations()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.protocol_a == "dex"
        assert alert.protocol_b == "lending"
        assert alert.metric_name == "latency"
        assert alert.severity == "critical"

    def test_record_series_mismatched_metrics_no_alert(self):
        correlator = CrossProtocolHealthCorrelator()
        correlator.record_series("dex", "latency", [1, 2, 3, 4, 5])
        correlator.record_series("lending", "throughput", [2, 3, 4, 5, 6])

        assert correlator.detect_correlations() == []


class TestMultiModelEnsemble:
    def test_aggregate_votes_raises_without_outputs(self):
        ensemble = MultiModelEnsemble()
        with pytest.raises(ValueError, match="No model outputs"):
            ensemble.aggregate_votes([])

    def test_aggregate_votes_prefers_confident_model(self):
        ensemble = MultiModelEnsemble()
        outputs = [
            ModelOutput(model_id="model-a", task_type="task", content="buy", confidence=0.9),
            ModelOutput(model_id="model-b", task_type="task", content="sell", confidence=0.4),
            ModelOutput(model_id="model-c", task_type="task", content="buy", confidence=0.8),
        ]

        vote = ensemble.aggregate_votes(outputs)
        assert vote.winning_content == "buy"
        assert set(vote.participating_models) == {"model-a", "model-b", "model-c"}
        assert 0.0 < vote.support_ratio <= 1.0

    def test_update_performance_and_best_model(self):
        ensemble = MultiModelEnsemble()
        ensemble.update_performance("model-a", success=True)
        ensemble.update_performance("model-a", success=True)
        ensemble.update_performance("model-b", success=False)

        best = ensemble.best_model_for_task("task", ["model-a", "model-b"])
        assert best == "model-a"
