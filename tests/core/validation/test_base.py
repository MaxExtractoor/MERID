"""Tests for core/validation/base.py."""
import pytest
from core.validation.base import ValidatorVerdict, BaseValidator, ValidationStatus


class TestValidatorVerdict:
    """Test ValidatorVerdict dataclass."""

    def test_creation(self):
        """Test ValidatorVerdict creation."""
        verdict = ValidatorVerdict(
            name="test_validator",
            status="confirmed",
            score=0.85,
            details="All checks passed",
            evidence={"field1": "value1"}
        )
        assert verdict.name == "test_validator"
        assert verdict.status == "confirmed"
        assert verdict.score == 0.85
        assert verdict.details == "All checks passed"
        assert verdict.evidence == {"field1": "value1"}

    def test_default_evidence(self):
        """Test ValidatorVerdict with default evidence."""
        verdict = ValidatorVerdict(
            name="test",
            status="pending",
            score=0.0,
            details="Waiting"
        )
        assert verdict.evidence == {}


class TestBaseValidator:
    """Test BaseValidator class."""

    def test_default_attributes(self):
        """Test default validator attributes."""
        validator = BaseValidator()
        assert validator.name == "base"
        assert validator.weight == 1.0
        assert validator.requires_metadata is False

    @pytest.mark.asyncio
    async def test_validate_success(self):
        """Test successful validation."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": 100.0
        }
        vote_result = {
            "vote": "yes",
            "confidence": 0.8,
            "reasoning": "Good proposal"
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert verdict.score == 0.8
        assert "passed" in verdict.details.lower()

    @pytest.mark.asyncio
    async def test_validate_missing_energy(self):
        """Test validation with missing energy data."""
        validator = BaseValidator()
        verdict = await validator.validate(None, {"vote": "yes"})
        
        assert verdict.status == "failed"
        assert "Missing" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_vote_result(self):
        """Test validation with missing vote result."""
        validator = BaseValidator()
        verdict = await validator.validate({"agent_id": "123"}, None)
        
        assert verdict.status == "failed"
        assert "Missing" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_energy_field(self):
        """Test validation with missing energy field."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            # Missing proposal_id and energy_amount
        }
        vote_result = {
            "vote": "yes",
            "confidence": 0.8,
            "reasoning": "Good"
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "proposal_id" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_vote_field(self):
        """Test validation with missing vote field."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": 100.0
        }
        vote_result = {
            "vote": "yes",
            # Missing confidence and reasoning
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "confidence" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_invalid_energy_amount(self):
        """Test validation with invalid energy amount."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": -10.0  # Negative
        }
        vote_result = {
            "vote": "yes",
            "confidence": 0.8,
            "reasoning": "Good"
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "positive" in verdict.details.lower()

    @pytest.mark.asyncio
    async def test_validate_invalid_confidence_high(self):
        """Test validation with confidence > 1."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": 100.0
        }
        vote_result = {
            "vote": "yes",
            "confidence": 1.5,  # Too high
            "reasoning": "Good"
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "0 and 1" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_invalid_confidence_low(self):
        """Test validation with confidence < 0."""
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": 100.0
        }
        vote_result = {
            "vote": "yes",
            "confidence": -0.5,  # Too low
            "reasoning": "Good"
        }
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"

    @pytest.mark.asyncio
    async def test_validate_exception_handling(self):
        """Test validation handles exceptions."""
        validator = BaseValidator()
        # Pass invalid types that will cause exceptions
        verdict = await validator.validate("not_a_dict", "also_not_a_dict")
        
        assert verdict.status == "error"
        assert "Validation error" in verdict.details

    def test_pending_method(self):
        """Test pending helper method."""
        validator = BaseValidator()
        validator.name = "test"
        verdict = validator.pending("Waiting for data")
        
        assert verdict.status == "pending"
        assert verdict.score == 0.0
        assert verdict.details == "Waiting for data"
        assert verdict.name == "test"

    def test_failure_method(self):
        """Test failure helper method."""
        validator = BaseValidator()
        validator.name = "test"
        verdict = validator.failure("Check failed", score=0.3)
        
        assert verdict.status == "failed"
        assert verdict.score == 0.3
        assert verdict.details == "Check failed"

    def test_failure_method_clamps_score(self):
        """Test failure method clamps negative scores."""
        validator = BaseValidator()
        verdict = validator.failure("Failed", score=-0.5)
        
        assert verdict.score == 0.0  # Clamped to 0

    def test_success_method(self):
        """Test success helper method."""
        validator = BaseValidator()
        validator.name = "test"
        verdict = validator.success("All good", score=0.9)
        
        assert verdict.status == "confirmed"
        assert verdict.score == 0.9
        assert verdict.details == "All good"

    def test_success_method_clamps_score(self):
        """Test success method clamps scores above 1."""
        validator = BaseValidator()
        verdict = validator.success("Perfect", score=1.5)
        
        assert verdict.score == 1.0  # Clamped to 1

    def test_error_method(self):
        """Test error helper method."""
        validator = BaseValidator()
        validator.name = "test"
        verdict = validator.error("System error")
        
        assert verdict.status == "error"
        assert verdict.score == 0.0
        assert verdict.details == "System error"
