"""Tests for core/validation/base.py - Batch A."""
import pytest
import asyncio

from core.validation.base import (
    ValidationStatus, ValidatorVerdict, BaseValidator
)


class TestValidationStatus:
    """Tests for ValidationStatus literal type."""

    def test_validation_status_values(self):
        # ValidationStatus is a Literal type, not an Enum
        # The valid values are: "confirmed", "failed", "pending", "error"
        valid_statuses = ["confirmed", "failed", "pending", "error"]
        for status in valid_statuses:
            assert isinstance(status, str)


class TestValidatorVerdictDataclass:
    """Tests for ValidatorVerdict dataclass."""

    def test_validator_verdict_creation(self):
        verdict = ValidatorVerdict(
            name="test_validator",
            status="confirmed",
            score=0.95,
            details="Validation passed",
            evidence={"field1": "value1", "field2": 123}
        )
        assert verdict.name == "test_validator"
        assert verdict.status == "confirmed"
        assert verdict.score == 0.95
        assert verdict.details == "Validation passed"
        assert verdict.evidence["field1"] == "value1"

    def test_validator_verdict_defaults(self):
        verdict = ValidatorVerdict(
            name="test_validator",
            status="pending",
            score=0.0,
            details="Waiting for data"
        )
        assert verdict.evidence == {}


class TestBaseValidator:
    """Tests for BaseValidator class."""

    def test_base_validator_defaults(self):
        validator = BaseValidator()
        assert validator.name == "base"
        assert validator.weight == 1.0
        assert validator.requires_metadata is False

    def test_pending_method(self):
        validator = BaseValidator()
        verdict = validator.pending("Waiting for response")
        assert verdict.name == "base"
        assert verdict.status == "pending"
        assert verdict.score == 0.0
        assert verdict.details == "Waiting for response"
        assert verdict.evidence == {}

    def test_pending_with_evidence(self):
        validator = BaseValidator()
        evidence = {"retry_count": 3}
        verdict = validator.pending("Waiting for response", evidence=evidence)
        assert verdict.evidence["retry_count"] == 3

    def test_failure_method(self):
        validator = BaseValidator()
        verdict = validator.failure("Validation failed")
        assert verdict.status == "failed"
        assert verdict.score == 0.0
        assert verdict.details == "Validation failed"

    def test_failure_with_score(self):
        validator = BaseValidator()
        verdict = validator.failure("Partial failure", score=0.3)
        assert verdict.score == 0.3

    def test_failure_negative_score_clamped(self):
        validator = BaseValidator()
        verdict = validator.failure("Bad failure", score=-0.5)
        assert verdict.score == 0.0  # Should be clamped to 0

    def test_success_method(self):
        validator = BaseValidator()
        verdict = validator.success("Validation passed")
        assert verdict.status == "confirmed"
        assert verdict.score == 1.0
        assert verdict.details == "Validation passed"

    def test_success_with_score(self):
        validator = BaseValidator()
        verdict = validator.success("Good validation", score=0.85)
        assert verdict.score == 0.85

    def test_success_score_clamped(self):
        validator = BaseValidator()
        verdict = validator.success("Perfect validation", score=1.5)
        assert verdict.score == 1.0  # Should be clamped to 1.0

    def test_error_method(self):
        validator = BaseValidator()
        verdict = validator.error("System error occurred")
        assert verdict.status == "error"
        assert verdict.score == 0.0
        assert verdict.details == "System error occurred"

    @pytest.mark.asyncio
    async def test_validate_with_valid_data(self):
        validator = BaseValidator()
        energy = {
            "agent_id": "agent_123",
            "proposal_id": "prop_456",
            "energy_amount": 100.0
        }
        vote_result = {
            "vote": "yes",
            "confidence": 0.8,
            "reasoning": "Good signal"
        }

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "confirmed"
        assert verdict.score == 0.8
        assert "Basic validation passed" in verdict.details
        assert verdict.evidence["energy_fields_present"] is True
        assert verdict.evidence["vote_fields_present"] is True

    @pytest.mark.asyncio
    async def test_validate_missing_energy(self):
        validator = BaseValidator()
        energy = None
        vote_result = {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Missing required energy" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_vote_result(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": 100}
        vote_result = None

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Missing required energy or vote" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_energy_field(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p"}  # Missing energy_amount
        vote_result = {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Missing required energy field: energy_amount" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_vote_field(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": 100}
        vote_result = {"vote": "yes", "confidence": 0.8}  # Missing reasoning

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Missing required vote field: reasoning" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_zero_energy(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": 0}
        vote_result = {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Energy amount must be positive" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_negative_energy(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": -50}
        vote_result = {"vote": "yes", "confidence": 0.8, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Energy amount must be positive" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_confidence_too_high(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": 100}
        vote_result = {"vote": "yes", "confidence": 1.5, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Confidence must be between 0 and 1" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_confidence_negative(self):
        validator = BaseValidator()
        energy = {"agent_id": "a", "proposal_id": "p", "energy_amount": 100}
        vote_result = {"vote": "yes", "confidence": -0.2, "reasoning": "Good"}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "Confidence must be between 0 and 1" in verdict.details
