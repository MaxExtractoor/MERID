"""Tests for Inference + Explainability sprint.

Covers:
  - OpinionExplanation dataclass and serialization
  - OpinionEstimate with explanation field
  - All 3 strategies produce valid explanations
  - MLExplanationAdapter (SHAP, LIME, feature importances)
  - PredictionOpinion stores/retrieves explanations via consensus store
  - Explainability metrics (coverage, rationale distribution, stability)
  - Observability alert rules (explanation_coverage_low, explanation_missing_critical)
  - API endpoint: include_explanation query param
  - API endpoint: /consensus/explainability
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from merid.prediction.opinion_strategy import (
    CalibrationAwareStrategy,
    HashBiasStrategy,
    MeanReversionStrategy,
    MLExplanationAdapter,
    OpinionEstimate,
    OpinionExplanation,
)


# ── OpinionExplanation Tests ─────────────────────────────────────────

class TestOpinionExplanation:
    """Verify OpinionExplanation dataclass and serialization."""

    def test_default_construction(self):
        exp = OpinionExplanation()
        assert exp.inputs_used == {}
        assert exp.contributions == {}
        assert exp.rationale == ""

    def test_construction_with_values(self):
        exp = OpinionExplanation(
            inputs_used={"market_prob": 0.7, "category": "macro"},
            contributions={"market": 0.7, "bias": 0.05},
            rationale="hash_deterministic_bias",
        )
        assert exp.inputs_used["market_prob"] == 0.7
        assert exp.contributions["bias"] == 0.05
        assert exp.rationale == "hash_deterministic_bias"

    def test_to_dict(self):
        exp = OpinionExplanation(
            inputs_used={"market_prob": 0.6},
            contributions={"market": 0.6, "adjustment": -0.05},
            rationale="mean_reversion_pull_toward_0.5",
        )
        d = exp.to_dict()
        assert d["inputs_used"] == {"market_prob": 0.6}
        assert d["contributions"]["adjustment"] == -0.05
        assert d["rationale"] == "mean_reversion_pull_toward_0.5"

    def test_to_dict_is_json_serializable(self):
        exp = OpinionExplanation(
            inputs_used={"market_prob": 0.5, "ticker": "TEST-TICKER"},
            contributions={"market": 0.5},
            rationale="test",
        )
        serialized = json.dumps(exp.to_dict())
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["rationale"] == "test"


# ── OpinionEstimate with Explanation Tests ───────────────────────────

class TestOpinionEstimateExplanation:
    """Verify OpinionEstimate carries explanation correctly."""

    def test_estimate_without_explanation(self):
        est = OpinionEstimate(
            agent_prob=0.65, confidence=0.7, edge=0.05,
            reasoning_tag="test", signal_sources=["market"],
        )
        assert est.explanation is None
        d = est.to_dict()
        assert "explanation" not in d

    def test_estimate_with_explanation(self):
        exp = OpinionExplanation(
            inputs_used={"market_prob": 0.6},
            contributions={"market": 0.6, "bias": 0.05},
            rationale="test_rationale",
        )
        est = OpinionEstimate(
            agent_prob=0.65, confidence=0.7, edge=0.05,
            reasoning_tag="test", signal_sources=["market"],
            explanation=exp,
        )
        assert est.explanation is not None
        d = est.to_dict()
        assert "explanation" in d
        assert d["explanation"]["rationale"] == "test_rationale"

    def test_to_dict_includes_all_fields(self):
        est = OpinionEstimate(
            agent_prob=0.55, confidence=0.6, edge=0.03,
            reasoning_tag="hash_bias", signal_sources=["market_implied_prob"],
            explanation=OpinionExplanation(rationale="test"),
        )
        d = est.to_dict()
        assert d["agent_prob"] == 0.55
        assert d["confidence"] == 0.6
        assert d["edge"] == 0.03
        assert d["reasoning_tag"] == "hash_bias"
        assert d["signal_sources"] == ["market_implied_prob"]
        assert d["explanation"]["rationale"] == "test"


# ── Strategy Explanation Tests ───────────────────────────────────────

class TestHashBiasStrategyExplanation:
    """Verify HashBiasStrategy produces valid explanations."""

    def test_explanation_present(self):
        strategy = HashBiasStrategy(bias_range=0.10, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.5)
        if est is not None:
            assert est.explanation is not None
            assert est.explanation.rationale == "hash_deterministic_bias"
            assert "market_prob" in est.explanation.inputs_used
            assert "hash_bias" in est.explanation.contributions

    def test_explanation_inputs_match_strategy(self):
        strategy = HashBiasStrategy(bias_range=0.20, min_edge=0.01)
        est = strategy.estimate("agent-2", "TICKER-B", 0.7)
        if est is not None:
            assert est.explanation.inputs_used["market_prob"] == 0.7
            assert est.explanation.inputs_used["bias_range"] == 0.20
            assert est.explanation.inputs_used["agent_id"] == "agent-2"
            assert est.explanation.inputs_used["ticker"] == "TICKER-B"

    def test_explanation_contributions_sum_to_agent_prob(self):
        strategy = HashBiasStrategy(bias_range=0.10, min_edge=0.01)
        est = strategy.estimate("agent-3", "TICKER-C", 0.5)
        if est is not None:
            c = est.explanation.contributions
            # market + hash_bias ≈ agent_prob (before clamping)
            raw_sum = c["market"] + c["hash_bias"]
            assert abs(raw_sum - est.agent_prob) < 0.01

    def test_no_explanation_when_skipped(self):
        strategy = HashBiasStrategy(min_edge=0.50)  # Very high threshold
        est = strategy.estimate("agent-1", "TICKER-A", 0.5)
        assert est is None  # Skipped, no explanation to check


class TestMeanReversionStrategyExplanation:
    """Verify MeanReversionStrategy produces valid explanations."""

    def test_explanation_present_extreme_prob(self):
        strategy = MeanReversionStrategy(reversion_strength=0.15, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.85)
        assert est is not None
        assert est.explanation is not None
        assert "mean_reversion" in est.explanation.contributions
        assert est.explanation.inputs_used["distance_from_center"] == 0.35

    def test_strong_reversion_rationale(self):
        strategy = MeanReversionStrategy(reversion_strength=0.15, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.80)
        if est is not None:
            # market_prob=0.80, distance=0.30, |0.30| > 0.15 → strong rationale
            assert est.explanation.rationale == "mean_reversion_pull_toward_0.5"

    def test_mild_reversion_rationale(self):
        strategy = MeanReversionStrategy(reversion_strength=0.15, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.60)
        if est is not None:
            # market_prob=0.60, distance=0.10, |0.10| <= 0.15 → mild rationale
            assert est.explanation.rationale == "mild_mean_reversion"

    def test_reversion_contribution_is_negative_for_high_prob(self):
        strategy = MeanReversionStrategy(reversion_strength=0.15, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.85)
        if est is not None:
            assert est.explanation.contributions["mean_reversion"] < 0

    def test_reversion_contribution_is_positive_for_low_prob(self):
        strategy = MeanReversionStrategy(reversion_strength=0.15, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.15)
        if est is not None:
            assert est.explanation.contributions["mean_reversion"] > 0


class TestCalibrationAwareStrategyExplanation:
    """Verify CalibrationAwareStrategy produces valid explanations."""

    def test_explanation_present(self):
        strategy = CalibrationAwareStrategy(blend_weight=0.20, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.80, category="macro")
        if est is not None:
            assert est.explanation is not None
            assert "category_base_rate" in est.explanation.contributions
            assert est.explanation.inputs_used["category"] == "macro"
            assert est.explanation.inputs_used["blend_weight"] == 0.20

    def test_calibration_adjustment_rationale(self):
        strategy = CalibrationAwareStrategy(blend_weight=0.20, min_edge=0.01)
        # macro base_rate=0.45, market_prob=0.80 → |0.45-0.80|=0.35 > 0.05
        est = strategy.estimate("agent-1", "TICKER-A", 0.80, category="macro")
        if est is not None:
            assert "calibration_adjustment_to_macro_base_rate" in est.explanation.rationale

    def test_minor_adjustment_rationale(self):
        strategy = CalibrationAwareStrategy(blend_weight=0.20, min_edge=0.01)
        # politics base_rate=0.50, market_prob=0.52 → |0.50-0.52|=0.02 <= 0.05
        est = strategy.estimate("agent-1", "TICKER-A", 0.52, category="politics")
        if est is not None:
            assert est.explanation.rationale == "calibration_minor_adjustment"

    def test_contributions_decompose_blend(self):
        strategy = CalibrationAwareStrategy(blend_weight=0.20, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.80, category="macro")
        if est is not None:
            c = est.explanation.contributions
            # market contribution = 0.80 * 0.80 = 0.64
            assert abs(c["market"] - 0.64) < 0.001
            # base_rate contribution = 0.20 * 0.45 = 0.09
            assert abs(c["category_base_rate"] - 0.09) < 0.001

    def test_unknown_category_uses_other(self):
        strategy = CalibrationAwareStrategy(blend_weight=0.20, min_edge=0.01)
        est = strategy.estimate("agent-1", "TICKER-A", 0.80, category="")
        if est is not None:
            assert est.explanation.inputs_used["category"] == "other"


# ── ML Explanation Adapter Tests ─────────────────────────────────────

class TestMLExplanationAdapter:
    """Verify MLExplanationAdapter converts ML artifacts correctly."""

    def test_from_shap(self):
        adapter = MLExplanationAdapter()
        exp = adapter.from_shap(
            shap_values={"market_prob": 0.12, "volume": -0.03, "days_to_expiry": 0.05},
            base_value=0.5,
            model_name="xgboost_v1",
        )
        assert isinstance(exp, OpinionExplanation)
        assert exp.inputs_used["base_value"] == 0.5
        assert exp.inputs_used["model"] == "xgboost_v1"
        assert exp.contributions["market_prob"] == 0.12
        assert exp.rationale == "shap_market_prob_dominant"

    def test_from_shap_with_extra_inputs(self):
        exp = MLExplanationAdapter.from_shap(
            shap_values={"feature_a": 0.1},
            base_value=0.5,
            extra_inputs={"ticker": "TEST"},
        )
        assert exp.inputs_used["ticker"] == "TEST"

    def test_from_lime(self):
        exp = MLExplanationAdapter.from_lime(
            lime_weights=[("market_prob", 0.15), ("category", -0.02)],
            model_name="lstm_v2",
        )
        assert isinstance(exp, OpinionExplanation)
        assert exp.contributions["market_prob"] == 0.15
        assert exp.contributions["category"] == -0.02
        assert exp.rationale == "lime_market_prob_dominant"
        assert exp.inputs_used["model"] == "lstm_v2"

    def test_from_feature_importances(self):
        exp = MLExplanationAdapter.from_feature_importances(
            importances={"market_prob": 0.7, "volume": 0.2, "spread": 0.1},
            prediction=0.65,
            model_name="prophet_v1",
        )
        assert isinstance(exp, OpinionExplanation)
        assert exp.inputs_used["prediction"] == 0.65
        assert exp.rationale == "ml_market_prob_primary_driver"

    def test_empty_shap_values(self):
        exp = MLExplanationAdapter.from_shap(shap_values={}, base_value=0.5)
        assert exp.rationale == "shap_unknown_dominant"

    def test_empty_lime_weights(self):
        exp = MLExplanationAdapter.from_lime(lime_weights=[])
        assert exp.rationale == "lime_unknown_dominant"

    def test_adapter_output_is_serializable(self):
        exp = MLExplanationAdapter.from_shap(
            shap_values={"a": 0.1, "b": -0.2},
            base_value=0.5,
        )
        serialized = json.dumps(exp.to_dict())
        assert isinstance(serialized, str)


# ── Consensus Store Explanation Persistence Tests ────────────────────

class TestConsensusStoreExplanationPersistence:
    """Verify PredictionConsensusStore stores and retrieves explanations."""

    @pytest.fixture(autouse=True)
    def setup_store(self, tmp_path):
        """Create a fresh in-memory store for each test."""
        db_path = str(tmp_path / "test_consensus.db")
        from merid.prediction.consensus import PredictionConsensusStore
        self.store = PredictionConsensusStore(db_path=db_path)

    def test_opinion_with_explanation_roundtrip(self):
        from merid.prediction.consensus import PredictionOpinion
        explanation = {
            "inputs_used": {"market_prob": 0.7},
            "contributions": {"market": 0.7, "bias": 0.05},
            "rationale": "hash_deterministic_bias",
        }
        op = PredictionOpinion(
            agent_id="agent-1", agent_name="TestAgent",
            symbol="PRED:KALSHI:TEST:YES", probability=0.75,
            confidence=0.6, reasoning="test", signal_sources=["market"],
            explanation=explanation,
        )
        self.store.add_opinion(op)
        opinions = self.store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 1
        retrieved = opinions[0]
        assert retrieved.explanation is not None
        assert retrieved.explanation["rationale"] == "hash_deterministic_bias"
        assert retrieved.explanation["inputs_used"]["market_prob"] == 0.7

    def test_opinion_without_explanation_roundtrip(self):
        from merid.prediction.consensus import PredictionOpinion
        op = PredictionOpinion(
            agent_id="agent-1", agent_name="TestAgent",
            symbol="PRED:KALSHI:TEST:YES", probability=0.75,
            confidence=0.6, reasoning="test",
        )
        self.store.add_opinion(op)
        opinions = self.store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 1
        assert opinions[0].explanation is None

    def test_to_dict_with_explanation(self):
        from merid.prediction.consensus import PredictionOpinion
        explanation = {"rationale": "test", "inputs_used": {}, "contributions": {}}
        op = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.6, explanation=explanation,
        )
        d = op.to_dict(include_explanation=True)
        assert "explanation" in d
        assert d["explanation"]["rationale"] == "test"

    def test_to_dict_without_explanation_flag(self):
        from merid.prediction.consensus import PredictionOpinion
        explanation = {"rationale": "test", "inputs_used": {}, "contributions": {}}
        op = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.6, explanation=explanation,
        )
        d = op.to_dict(include_explanation=False)
        assert "explanation" not in d

    def test_multiple_opinions_with_mixed_explanations(self):
        from merid.prediction.consensus import PredictionOpinion
        # Opinion with explanation
        op1 = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.7, explanation={"rationale": "test1"},
            created_at=time.time() - 10,
        )
        # Opinion without explanation
        op2 = PredictionOpinion(
            agent_id="agent-2", symbol="PRED:KALSHI:TEST:YES",
            probability=0.6,
            created_at=time.time(),
        )
        self.store.add_opinion(op1)
        self.store.add_opinion(op2)
        opinions = self.store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 2
        has_exp = sum(1 for o in opinions if o.explanation is not None)
        assert has_exp == 1


# ── Explainability Metrics Tests ─────────────────────────────────────

class TestExplainabilityMetrics:
    """Verify get_explainability_metrics computes correctly."""

    @pytest.fixture(autouse=True)
    def setup_store(self, tmp_path):
        db_path = str(tmp_path / "test_metrics.db")
        from merid.prediction.consensus import PredictionConsensusStore
        self.store = PredictionConsensusStore(db_path=db_path)

    def test_empty_store_returns_zeros(self):
        metrics = self.store.get_explainability_metrics()
        assert metrics["coverage"]["total"] == 0
        assert metrics["coverage"]["pct"] == 0.0
        assert metrics["rationale_distribution"] == {}
        assert metrics["stability"]["flip_rate"] == 0.0

    def test_coverage_all_explained(self):
        from merid.prediction.consensus import PredictionOpinion
        for i in range(5):
            op = PredictionOpinion(
                agent_id=f"agent-{i}", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6, explanation={"rationale": "test"},
            )
            self.store.add_opinion(op)
        metrics = self.store.get_explainability_metrics()
        assert metrics["coverage"]["total"] == 5
        assert metrics["coverage"]["with_explanation"] == 5
        assert metrics["coverage"]["pct"] == 100.0

    def test_coverage_partial(self):
        from merid.prediction.consensus import PredictionOpinion
        # 3 with explanation, 2 without
        for i in range(3):
            op = PredictionOpinion(
                agent_id=f"agent-{i}", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6, explanation={"rationale": "test"},
            )
            self.store.add_opinion(op)
        for i in range(3, 5):
            op = PredictionOpinion(
                agent_id=f"agent-{i}", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6,
            )
            self.store.add_opinion(op)
        metrics = self.store.get_explainability_metrics()
        assert metrics["coverage"]["total"] == 5
        assert metrics["coverage"]["with_explanation"] == 3
        assert metrics["coverage"]["pct"] == 60.0

    def test_rationale_distribution(self):
        from merid.prediction.consensus import PredictionOpinion
        rationales = [
            "mean_reversion_pull_toward_0.5",
            "mean_reversion_pull_toward_0.5",
            "calibration_adjustment_to_macro_base_rate",
            "hash_deterministic_bias",
        ]
        for i, r in enumerate(rationales):
            op = PredictionOpinion(
                agent_id=f"agent-{i}", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6, explanation={"rationale": r},
            )
            self.store.add_opinion(op)
        metrics = self.store.get_explainability_metrics()
        dist = metrics["rationale_distribution"]
        assert dist["mean_reversion_pull_toward_0.5"] == 2
        assert dist["calibration_adjustment_to_macro_base_rate"] == 1
        assert dist["hash_deterministic_bias"] == 1

    def test_strategy_variety(self):
        from merid.prediction.consensus import PredictionOpinion
        rationales = [
            "mean_reversion_pull_toward_0.5",
            "mild_mean_reversion",
            "calibration_adjustment_to_macro_base_rate",
            "hash_deterministic_bias",
        ]
        for i, r in enumerate(rationales):
            op = PredictionOpinion(
                agent_id=f"agent-{i}", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6, explanation={"rationale": r},
            )
            self.store.add_opinion(op)
        metrics = self.store.get_explainability_metrics()
        variety = metrics["strategy_variety"]
        assert variety["mean_reversion"] == 2  # Two mean_reversion rationale tags
        assert variety["calibration_aware"] == 1
        assert variety["hash_bias"] == 1

    def test_stability_no_flips(self):
        from merid.prediction.consensus import PredictionOpinion
        # Same agent, same symbol, same direction (all > 0.5)
        for i in range(3):
            op = PredictionOpinion(
                agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
                probability=0.6 + i * 0.01,
                created_at=time.time() - (3 - i),
            )
            self.store.add_opinion(op)
        metrics = self.store.get_explainability_metrics()
        assert metrics["stability"]["flips"] == 0
        assert metrics["stability"]["flip_rate"] == 0.0

    def test_stability_with_flip(self):
        from merid.prediction.consensus import PredictionOpinion
        # Agent flips from YES (0.7) to NO (0.3)
        # Space opinions >60s apart to bypass dedup window
        op1 = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.7, created_at=time.time() - 120,
        )
        op2 = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.3, created_at=time.time(),
        )
        self.store.add_opinion(op1)
        self.store.add_opinion(op2)
        metrics = self.store.get_explainability_metrics()
        assert metrics["stability"]["flips"] == 1
        assert metrics["stability"]["flip_rate"] == 1.0

    def test_window_filtering(self):
        from merid.prediction.consensus import PredictionOpinion
        # Opinion outside window
        old_op = PredictionOpinion(
            agent_id="agent-1", symbol="PRED:KALSHI:TEST:YES",
            probability=0.6, explanation={"rationale": "old"},
            created_at=time.time() - 7200,  # 2 hours ago
        )
        # Opinion inside window
        new_op = PredictionOpinion(
            agent_id="agent-2", symbol="PRED:KALSHI:TEST:YES",
            probability=0.7, explanation={"rationale": "new"},
            created_at=time.time(),
        )
        self.store.add_opinion(old_op)
        self.store.add_opinion(new_op)
        metrics = self.store.get_explainability_metrics(window_s=3600.0)
        assert metrics["coverage"]["total"] == 1  # Only the recent one


# ── Observability Alert Rule Tests ───────────────────────────────────

class TestExplanationCoverageLowAlert:
    """Verify explanation coverage low alert fires correctly."""

    def test_not_firing_when_coverage_high(self):
        from web.api.system_observability import ExplanationCoverageLowAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 10, "pct": 100.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationCoverageLowAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_coverage_low(self):
        from web.api.system_observability import ExplanationCoverageLowAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 5, "pct": 50.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationCoverageLowAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "warning"
            assert result["detail"]["coverage_pct"] == 50.0

    def test_not_firing_when_no_opinions(self):
        from web.api.system_observability import ExplanationCoverageLowAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 0, "with_explanation": 0, "pct": 0.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationCoverageLowAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_graceful_on_error(self):
        from web.api.system_observability import ExplanationCoverageLowAlert
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    side_effect=Exception("unavailable")):
            alert = ExplanationCoverageLowAlert()
            result = alert.evaluate()
            assert result["firing"] is False
            assert "error" in result["detail"]


class TestExplanationMissingCriticalAlert:
    """Verify explanation missing critical alert fires correctly."""

    def test_not_firing_when_explanations_present(self):
        from web.api.system_observability import ExplanationMissingCriticalAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 8, "pct": 80.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationMissingCriticalAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_zero_explanations(self):
        from web.api.system_observability import ExplanationMissingCriticalAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 0, "pct": 0.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationMissingCriticalAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "critical"

    def test_not_firing_when_too_few_opinions(self):
        from web.api.system_observability import ExplanationMissingCriticalAlert
        mock_store = MagicMock()
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 3, "with_explanation": 0, "pct": 0.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            alert = ExplanationMissingCriticalAlert()
            result = alert.evaluate()
            assert result["firing"] is False  # < 5 opinions, don't fire

    def test_graceful_on_error(self):
        from web.api.system_observability import ExplanationMissingCriticalAlert
        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    side_effect=Exception("unavailable")):
            alert = ExplanationMissingCriticalAlert()
            result = alert.evaluate()
            assert result["firing"] is False


# ── Agent Explanation Plumbing Tests ─────────────────────────────────

class TestAgentExplanationPlumbing:
    """Verify PredictionMarketAgentV2 attaches explanations."""

    def test_scan_opportunities_includes_explanation(self):
        """Verify that _scan_opportunities attaches explanation from strategy."""
        import asyncio
        from merid.agents.research import PredictionMarketAgentV2
        from merid.prediction.consensus import PredictionInstrument

        agent = PredictionMarketAgentV2(
            agent_id="test-agent",
            venue="kalshi",
            strategy="mean_reversion",
        )

        mock_inst = PredictionInstrument(
            symbol="PRED:KALSHI:TEST:YES",
            ticker="TEST",
            category="macro",
            title="Test instrument",
            market_implied_prob=0.80,
            status="active",
        )

        mock_store = MagicMock()
        mock_store.list_instruments.return_value = [mock_inst]

        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            opps = asyncio.get_event_loop().run_until_complete(
                agent._scan_opportunities({})
            )

        if opps:
            assert "explanation" in opps[0]
            exp = opps[0]["explanation"]
            assert exp is not None
            assert "rationale" in exp
            assert "inputs_used" in exp
            assert "contributions" in exp

    def test_submit_opinions_passes_explanation(self):
        """Verify _submit_opinions passes explanation to PredictionOpinion."""
        from merid.agents.research import PredictionMarketAgentV2

        agent = PredictionMarketAgentV2(
            agent_id="test-agent",
            venue="kalshi",
        )

        mock_store = MagicMock()
        opportunities = [{
            "symbol": "PRED:KALSHI:TEST:YES",
            "ticker": "TEST",
            "venue": "kalshi",
            "category": "macro",
            "title": "Test",
            "market_implied_prob": 0.80,
            "agent_estimated_prob": 0.68,
            "edge": -0.12,
            "direction": "no",
            "confidence": 0.6,
            "strategy": "mean_reversion",
            "reasoning_tag": "mean_reversion",
            "explanation": {
                "inputs_used": {"market_prob": 0.80},
                "contributions": {"market": 0.80, "mean_reversion": -0.12},
                "rationale": "mean_reversion_pull_toward_0.5",
            },
            "scanned_at": time.time(),
        }]

        with patch("merid.prediction.consensus.get_prediction_consensus_store",
                    return_value=mock_store):
            count = agent._submit_opinions(opportunities)

        assert count == 1
        # Verify the PredictionOpinion was created with explanation
        call_args = mock_store.add_opinion.call_args[0][0]
        assert call_args.explanation is not None
        assert call_args.explanation["rationale"] == "mean_reversion_pull_toward_0.5"


# ── Observability Integration Tests ──────────────────────────────────

class TestObservabilityAlertRegistryUpdate:
    """Verify alert registry includes new explainability alerts."""

    def test_alert_count_updated(self):
        from web.api.system_observability import ALERT_RULES
        assert len(ALERT_RULES) == 28

    def test_explainability_alerts_registered(self):
        from web.api.system_observability import ALERT_RULES
        names = [r.name for r in ALERT_RULES]
        assert "explanation_coverage_low" in names
        assert "explanation_missing_critical" in names

    def test_all_rules_return_valid_result(self):
        from web.api.system_observability import ALERT_RULES
        for rule in ALERT_RULES:
            result = rule.evaluate()
            assert "firing" in result
            assert "name" in result
            assert "severity" in result
            assert isinstance(result["firing"], bool)
