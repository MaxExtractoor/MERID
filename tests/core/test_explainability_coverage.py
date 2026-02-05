"""Comprehensive tests for core/explainability.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from core.explainability import (
    ExplanationType, ExplainabilityViolation, FeatureAttribution,
    RuleEvaluation, ModelEvidence, CounterfactualScenario,
    DecisionRationale, ExplanationContext, ExplanationRecord,
    ExplainableResult, ExplainabilityService, get_explainability_service,
    _mask_sensitive_inputs
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestExplanationType:
    """Test ExplanationType enum."""

    def test_order(self):
        assert ExplanationType.ORDER.value == "order"

    def test_cancel(self):
        assert ExplanationType.CANCEL.value == "cancel"

    def test_param_change(self):
        assert ExplanationType.PARAM_CHANGE.value == "parameter_change"

    def test_promotion(self):
        assert ExplanationType.PROMOTION.value == "promotion"


# =============================================================================
# Exception Tests
# =============================================================================

class TestExplainabilityViolation:
    """Test ExplainabilityViolation exception."""

    def test_creation(self):
        error = ExplainabilityViolation("Missing rationale")
        assert "Missing rationale" in str(error)


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestFeatureAttribution:
    """Test FeatureAttribution dataclass."""

    def test_creation(self):
        feature = FeatureAttribution(name="price", value=100.0)
        assert feature.name == "price"
        assert feature.value == 100.0

    def test_with_importance(self):
        feature = FeatureAttribution(name="volume", value=1000, importance=0.8)
        assert feature.importance == 0.8


class TestRuleEvaluation:
    """Test RuleEvaluation dataclass."""

    def test_creation(self):
        rule = RuleEvaluation(
            rule_name="max_notional",
            threshold=25000,
            observed_value=20000,
            passed=True
        )
        assert rule.rule_name == "max_notional"
        assert rule.passed is True


class TestModelEvidence:
    """Test ModelEvidence dataclass."""

    def test_creation(self):
        evidence = ModelEvidence(
            model_id="gemma_v1",
            version="1.0.0",
            score=0.95
        )
        assert evidence.model_id == "gemma_v1"
        assert evidence.score == 0.95


class TestCounterfactualScenario:
    """Test CounterfactualScenario dataclass."""

    def test_creation(self):
        scenario = CounterfactualScenario(
            option_id="alt_1",
            summary="Alternative action",
            expected_outcome={"pnl": 100},
            reason_rejected="Too risky"
        )
        assert scenario.option_id == "alt_1"


class TestDecisionRationale:
    """Test DecisionRationale dataclass."""

    def test_creation(self):
        rationale = DecisionRationale(
            reason="Trade approved",
            inputs={"symbol": "BTC"}
        )
        assert rationale.reason == "Trade approved"

    def test_with_features(self):
        rationale = DecisionRationale(
            reason="Signal detected",
            inputs={"symbol": "ETH"},
            features=[FeatureAttribution(name="momentum", value=0.8)]
        )
        assert len(rationale.features) == 1


class TestExplanationContext:
    """Test ExplanationContext dataclass."""

    def test_creation(self):
        context = ExplanationContext(
            inputs={"symbol": "BTC"},
            agent_id="agent_001",
            strategy="momentum",
            constraints={"max_size": 1000},
            expected_effect={"pnl": 100},
            environment_flags={"mode": "paper"}
        )
        assert context.agent_id == "agent_001"


class TestExplanationRecord:
    """Test ExplanationRecord dataclass."""

    def test_creation(self):
        context = ExplanationContext(
            inputs={},
            agent_id="test",
            strategy=None,
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        record = ExplanationRecord(
            record_id="expl_001",
            explanation_type=ExplanationType.ORDER,
            summary="Test explanation",
            expert_notes=None,
            context=context
        )
        assert record.record_id == "expl_001"


class TestExplainableResult:
    """Test ExplainableResult dataclass."""

    def test_creation(self):
        context = ExplanationContext(
            inputs={},
            agent_id="test",
            strategy=None,
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        record = ExplanationRecord(
            record_id="expl_002",
            explanation_type=ExplanationType.ORDER,
            summary="Result",
            expert_notes=None,
            context=context
        )
        result = ExplainableResult(result={"success": True}, explanation_record=record)
        assert result.result["success"] is True


# =============================================================================
# ExplainabilityService Tests
# =============================================================================

@pytest.fixture
def service():
    """Create ExplainabilityService with mocks."""
    with patch("core.explainability.get_data_access_controller") as mock_dac, \
         patch("core.explainability.get_telemetry_manager") as mock_tm:
        mock_dac.return_value = MagicMock()
        mock_dac.return_value.access.return_value = {"sanitized": True}
        mock_tm.return_value = MagicMock()
        
        svc = ExplainabilityService()
        return svc


class TestExplainabilityServiceInit:
    """Test ExplainabilityService initialization."""

    def test_init(self, service):
        assert service._records == []
        assert service._coverage_counts == {}


class TestRecordExplanation:
    """Test record_explanation method."""

    def test_basic_record(self, service):
        context = ExplanationContext(
            inputs={"symbol": "BTC"},
            agent_id="agent_001",
            strategy="momentum",
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        
        record = service.record_explanation(
            ExplanationType.ORDER,
            "Trade executed",
            context
        )
        
        assert record.record_id == "expl_00000001"
        assert len(service._records) == 1

    def test_with_rationale(self, service):
        context = ExplanationContext(
            inputs={},
            agent_id="test",
            strategy=None,
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        rationale = DecisionRationale(
            reason="Signal triggered",
            inputs={"symbol": "ETH"},
            features=[FeatureAttribution(name="rsi", value=70)]
        )
        
        record = service.record_explanation(
            ExplanationType.ORDER,
            "Order placed",
            context,
            rationale=rationale
        )
        
        assert record.rationale is not None


class TestValidateRationale:
    """Test _validate_rationale method."""

    def test_missing_inputs(self, service):
        rationale = DecisionRationale(reason="Test", inputs={})
        
        with pytest.raises(ExplainabilityViolation, match="inputs snapshot"):
            service._validate_rationale(rationale)

    def test_missing_features_and_rules(self, service):
        rationale = DecisionRationale(
            reason="Test",
            inputs={"symbol": "BTC"},
            features=[],
            rules_fired=[]
        )
        
        with pytest.raises(ExplainabilityViolation, match="features or rule"):
            service._validate_rationale(rationale)


class TestRecordLatency:
    """Test record_latency method."""

    def test_records_latency(self, service):
        service.record_latency(0.5)
        service.record_latency(1.0)
        
        assert len(service._latency_stats) == 2


class TestGetMetrics:
    """Test get_metrics method."""

    def test_empty_metrics(self, service):
        metrics = service.get_metrics()
        
        assert metrics["total_records"] == 0
        assert metrics["average_latency_seconds"] == 0.0

    def test_with_data(self, service):
        context = ExplanationContext(
            inputs={},
            agent_id="test",
            strategy=None,
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        service.record_explanation(ExplanationType.ORDER, "Test", context)
        service.record_latency(1.0)
        service.record_latency(2.0)
        
        metrics = service.get_metrics()
        
        assert metrics["total_records"] == 1
        assert metrics["average_latency_seconds"] == 1.5


class TestFetchRecent:
    """Test fetch_recent method."""

    def test_fetch_recent(self, service):
        context = ExplanationContext(
            inputs={},
            agent_id="test",
            strategy=None,
            constraints={},
            expected_effect={},
            environment_flags={}
        )
        for i in range(5):
            service.record_explanation(ExplanationType.ORDER, f"Test {i}", context)
        
        recent = service.fetch_recent(3)
        
        assert len(recent) == 3


# =============================================================================
# Mask Function Tests
# =============================================================================

class TestMaskSensitiveInputs:
    """Test _mask_sensitive_inputs function."""

    def test_masks_keys(self):
        data = {
            "api_key": "secret123",
            "symbol": "BTC",
            "password": "mypass"
        }
        
        result = _mask_sensitive_inputs(data)
        
        assert result["api_key"] == "***redacted***"
        assert result["symbol"] == "BTC"
        assert result["password"] == "***redacted***"

    def test_non_dict(self):
        result = _mask_sensitive_inputs("not a dict")
        assert result == {}


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetExplainabilityService:
    """Test get_explainability_service singleton."""

    def test_returns_service(self):
        import core.explainability as module
        module._service = None
        
        with patch("core.explainability.get_data_access_controller"), \
             patch("core.explainability.get_telemetry_manager"):
            svc = get_explainability_service()
        
        assert isinstance(svc, ExplainabilityService)
