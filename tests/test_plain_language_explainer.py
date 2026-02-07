"""
Tests for plain-language decision explainer (S5-03).

Validates:
- explain_plain_language() output structure and content
- find_by_decision_id() and find_by_correlation_id() lookups
- Plain text includes all rationale components (features, rules, models, counterfactuals)
- Missing decision returns None
- JSON serialization of output
"""

import json
import time
import unittest

from core.explainability import (
    ExplainabilityService,
    ExplanationType,
    ExplanationContext,
    DecisionRationale,
    FeatureAttribution,
    RuleEvaluation,
    ModelEvidence,
    CounterfactualScenario,
)


def _make_context(**overrides):
    defaults = dict(
        inputs={"symbol": "BTC/USDT", "price": 50000.0},
        agent_id="strategy-agent",
        strategy="momentum",
        constraints={"max_position": 5000},
        expected_effect={"pnl_target": 250},
        environment_flags={"mode": "paper"},
    )
    defaults.update(overrides)
    return ExplanationContext(**defaults)


def _make_rationale(**overrides):
    defaults = dict(
        reason="Strong momentum signal with favorable risk/reward",
        inputs={"symbol": "BTC/USDT", "price": 50000.0},
        features=[
            FeatureAttribution("momentum_score", 0.85, importance=0.9),
            FeatureAttribution("volume_surge", True, importance=0.7),
        ],
        rules_fired=[
            RuleEvaluation("max_position_size", 5000, 2500, True, "within limit"),
            RuleEvaluation("daily_loss_limit", -1000, -200, True),
        ],
    )
    defaults.update(overrides)
    return DecisionRationale(**defaults)


class TestExplainPlainLanguage(unittest.TestCase):
    """Core plain-language explanation generation."""

    def setUp(self):
        self.svc = ExplainabilityService()

    def _record_order(self, decision_id="order-001", **kwargs):
        ctx = _make_context(**kwargs.pop("context_overrides", {}))
        rat = _make_rationale(**kwargs.pop("rationale_overrides", {}))
        self.svc.record_explainable_result(
            domain="crypto",
            decision_id=decision_id,
            explanation_type=ExplanationType.ORDER,
            summary="Buy 0.05 BTC at $50,000",
            context=ctx,
            rationale=rat,
            result={"filled": True},
            **kwargs,
        )

    def test_basic_plain_language_output(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["decision_id"], "order-001")
        self.assertIn("plain_text", result)
        self.assertIn("Buy 0.05 BTC", result["plain_text"])

    def test_includes_agent_and_strategy(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("strategy-agent", result["plain_text"])
        self.assertIn("momentum", result["plain_text"])

    def test_includes_reason(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("Strong momentum signal", result["plain_text"])

    def test_includes_features(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("momentum_score", result["plain_text"])
        self.assertIn("volume_surge", result["plain_text"])

    def test_includes_rules(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("max_position_size", result["plain_text"])
        self.assertIn("PASSED", result["plain_text"])

    def test_includes_constraints(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("max_position", result["plain_text"])

    def test_includes_expected_effect(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertIn("pnl_target", result["plain_text"])

    def test_missing_decision_returns_none(self):
        result = self.svc.explain_plain_language("nonexistent")
        self.assertIsNone(result)

    def test_json_serializable(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        serialized = json.dumps(result)
        self.assertIn("order-001", serialized)
        self.assertIn("plain_text", serialized)

    def test_output_has_metadata(self):
        self._record_order()
        result = self.svc.explain_plain_language("order-001")
        self.assertEqual(result["type"], "order")
        self.assertEqual(result["domain"], "crypto")
        self.assertEqual(result["agent_id"], "strategy-agent")
        self.assertIn("timestamp", result)
        self.assertIn("record_id", result)


class TestModelEvidence(unittest.TestCase):
    """Plain text includes model evidence."""

    def test_model_evidence_in_output(self):
        svc = ExplainabilityService()
        rat = _make_rationale(
            model_evidence=[
                ModelEvidence("xgboost-v3", "3.1.0", 0.82, confidence=0.91),
            ]
        )
        svc.record_explainable_result(
            domain="crypto",
            decision_id="model-001",
            explanation_type=ExplanationType.ORDER,
            summary="Model-driven buy",
            context=_make_context(),
            rationale=rat,
            result={},
        )
        result = svc.explain_plain_language("model-001")
        self.assertIn("xgboost-v3", result["plain_text"])
        self.assertIn("0.82", result["plain_text"])


class TestCounterfactuals(unittest.TestCase):
    """Plain text includes counterfactual alternatives."""

    def test_counterfactuals_in_output(self):
        svc = ExplainabilityService()
        rat = _make_rationale(
            counterfactuals=[
                CounterfactualScenario(
                    option_id="alt-1",
                    summary="Short BTC instead",
                    expected_outcome={"pnl": -500},
                    reason_rejected="Momentum strongly bullish",
                ),
            ]
        )
        svc.record_explainable_result(
            domain="crypto",
            decision_id="cf-001",
            explanation_type=ExplanationType.ORDER,
            summary="Long BTC with counterfactual",
            context=_make_context(),
            rationale=rat,
            result={},
        )
        result = svc.explain_plain_language("cf-001")
        self.assertIn("Short BTC instead", result["plain_text"])
        self.assertIn("Momentum strongly bullish", result["plain_text"])


class TestExpertNotes(unittest.TestCase):
    """Plain text includes expert notes."""

    def test_expert_notes_in_output(self):
        svc = ExplainabilityService()
        svc.record_explainable_result(
            domain="crypto",
            decision_id="notes-001",
            explanation_type=ExplanationType.ORDER,
            summary="Buy with expert notes",
            context=_make_context(),
            rationale=_make_rationale(),
            result={},
            expert_notes="Reviewed by senior risk officer — approved",
        )
        result = svc.explain_plain_language("notes-001")
        self.assertIn("senior risk officer", result["plain_text"])


class TestFindByCorrelationId(unittest.TestCase):
    """find_by_correlation_id() returns all related records."""

    def test_find_correlated_records(self):
        svc = ExplainabilityService()
        for i in range(3):
            svc.record_explainable_result(
                domain="crypto",
                decision_id=f"corr-{i}",
                correlation_id="batch-42",
                explanation_type=ExplanationType.ORDER,
                summary=f"Order {i}",
                context=_make_context(),
                rationale=_make_rationale(),
                result={},
            )
        records = svc.find_by_correlation_id("batch-42")
        self.assertEqual(len(records), 3)

    def test_find_correlated_empty(self):
        svc = ExplainabilityService()
        records = svc.find_by_correlation_id("nonexistent")
        self.assertEqual(len(records), 0)


class TestFindByDecisionId(unittest.TestCase):
    """find_by_decision_id() returns the correct record."""

    def test_find_existing(self):
        svc = ExplainabilityService()
        svc.record_explainable_result(
            domain="crypto",
            decision_id="find-001",
            explanation_type=ExplanationType.ORDER,
            summary="Test order",
            context=_make_context(),
            rationale=_make_rationale(),
            result={},
        )
        record = svc.find_by_decision_id("find-001")
        self.assertIsNotNone(record)
        self.assertEqual(record.decision_id, "find-001")

    def test_find_missing(self):
        svc = ExplainabilityService()
        record = svc.find_by_decision_id("missing")
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
