"""Tests for core/validation/engine.py."""
import pytest
from unittest.mock import Mock, AsyncMock
from core.validation.engine import ValidationEngine, get_validation_engine, validation_engine
from core.validation.base import BaseValidator, ValidatorVerdict


class MockValidator(BaseValidator):
    """Mock validator for testing."""
    name = "mock"
    
    def __init__(self, return_status="confirmed", return_score=1.0):
        super().__init__()
        self.return_status = return_status
        self.return_score = return_score
    
    async def validate(self, energy, vote_result):
        return ValidatorVerdict(
            name=self.name,
            status=self.return_status,
            score=self.return_score,
            details=f"Mock {self.return_status}",
            evidence={}
        )


class TestValidationEngine:
    """Test ValidationEngine class."""

    @pytest.mark.asyncio
    async def test_validate_with_single_validator(self):
        """Test validation with single validator."""
        validator = MockValidator(return_status="confirmed", return_score=0.9)
        engine = ValidationEngine([validator])
        
        result = await engine.validate(
            {"agent_id": "a1", "proposal_id": "p1", "energy_amount": 100.0},
            {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}
        )
        
        assert result["status"] == "confirmed"
        assert result["score"] == 0.9
        assert len(result["verdicts"]) == 1

    @pytest.mark.asyncio
    async def test_validate_with_multiple_validators(self):
        """Test validation with multiple validators."""
        v1 = MockValidator(return_status="confirmed", return_score=0.9)
        v1.name = "v1"
        v2 = MockValidator(return_status="confirmed", return_score=0.8)
        v2.name = "v2"
        
        engine = ValidationEngine([v1, v2])
        
        result = await engine.validate(
            {"agent_id": "a1", "proposal_id": "p1", "energy_amount": 100.0},
            {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}
        )
        
        assert result["status"] == "confirmed"
        assert result["score"] == 0.85  # Average of 0.9 and 0.8
        assert len(result["verdicts"]) == 2

    @pytest.mark.asyncio
    async def test_validate_with_failure(self):
        """Test validation with one failure."""
        v1 = MockValidator(return_status="confirmed", return_score=0.9)
        v1.name = "v1"
        v2 = MockValidator(return_status="failed", return_score=0.2)
        v2.name = "v2"
        
        engine = ValidationEngine([v1, v2])
        
        result = await engine.validate({}, {})
        
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_validate_with_error(self):
        """Test validation when validator throws exception."""
        validator = Mock()
        validator.name = "failing"
        validator.validate = AsyncMock(side_effect=Exception("Crash"))
        validator.error = Mock(return_value=ValidatorVerdict("failing", "error", 0.0, "Crashed", {}))
        
        engine = ValidationEngine([validator])
        
        result = await engine.validate({}, {})
        
        assert result["status"] == "error"
        assert len(result["verdicts"]) == 1

    @pytest.mark.asyncio
    async def test_validate_order_success(self):
        """Test order validation success."""
        engine = ValidationEngine([])
        
        result = await engine.validate_order({"symbol": "BTC"})
        
        assert result["passed"] is True
        assert result["score"] == 1.0

    def test_aggregate_empty_verdicts(self):
        """Test aggregation with empty verdicts."""
        engine = ValidationEngine([])
        status, score = engine._aggregate([])
        
        assert status == "pending"
        assert score == 0.0

    def test_aggregate_all_confirmed(self):
        """Test aggregation with all confirmed."""
        engine = ValidationEngine([])
        verdicts = [
            ValidatorVerdict("v1", "confirmed", 0.9, "Good", {}),
            ValidatorVerdict("v2", "confirmed", 0.8, "Good", {})
        ]
        status, score = engine._aggregate(verdicts)
        
        assert status == "confirmed"
        assert score == 0.85

    def test_aggregate_partial(self):
        """Test aggregation with partial confirmation."""
        engine = ValidationEngine([])
        verdicts = [
            ValidatorVerdict("v1", "confirmed", 0.9, "Good", {}),
            ValidatorVerdict("v2", "pending", 0.0, "Waiting", {})
        ]
        status, score = engine._aggregate(verdicts)
        
        assert status == "partial"
        assert score == 0.9

    def test_aggregate_all_pending(self):
        """Test aggregation with all pending."""
        engine = ValidationEngine([])
        verdicts = [
            ValidatorVerdict("v1", "pending", 0.0, "Waiting", {}),
        ]
        status, score = engine._aggregate(verdicts)
        
        assert status == "pending"
        assert score == 0.0

    def test_aggregate_all_error(self):
        """Test aggregation with all errors."""
        engine = ValidationEngine([])
        verdicts = [
            ValidatorVerdict("v1", "error", 0.0, "Failed", {}),
        ]
        status, score = engine._aggregate(verdicts)
        
        assert status == "error"
        assert score == 0.0


class TestGetValidationEngine:
    """Test get_validation_engine function."""

    def test_returns_singleton(self):
        """Test get_validation_engine returns singleton."""
        engine1 = get_validation_engine()
        engine2 = get_validation_engine()
        assert engine1 is engine2

    def test_global_instance_exists(self):
        """Test global validation_engine exists."""
        assert validation_engine is not None
        assert isinstance(validation_engine, ValidationEngine)
