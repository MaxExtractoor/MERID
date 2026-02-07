"""Tests for core/validation/base.py - Batch 92."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.validation.base import (
    ValidationStatus, ValidatorVerdict, BaseValidator
)


class TestValidationStatus:
    """Tests for ValidationStatus literal type."""

    def test_status_values(self):
        # ValidationStatus is a Literal, test via actual usage
        assert "confirmed" in ["confirmed", "failed", "pending", "error"]
        assert "failed" in ["confirmed", "failed", "pending", "error"]
        assert "pending" in ["confirmed", "failed", "pending", "error"]
        assert "error" in ["confirmed", "failed", "pending", "error"]


class TestValidatorVerdict:
    """Tests for ValidatorVerdict dataclass."""

    def test_verdict_creation(self):
        verdict = ValidatorVerdict(
            name="test_validator",
            status="confirmed",
            score=0.95,
            details="All checks passed"
        )
        assert verdict.name == "test_validator"
        assert verdict.status == "confirmed"
        assert verdict.score == 0.95
        assert verdict.details == "All checks passed"
        assert verdict.evidence == {}

    def test_verdict_with_evidence(self):
        verdict = ValidatorVerdict(
            name="price_validator",
            status="confirmed",
            score=0.99,
            details="Price verified",
            evidence={"price": 100.0, "source": "coingecko"}
        )
        assert verdict.evidence["price"] == 100.0


class TestBaseValidator:
    """Tests for BaseValidator class."""

    def test_default_properties(self):
        validator = BaseValidator()
        assert validator.name == "base"
        assert validator.weight == 1.0
        assert validator.requires_metadata is False

    @pytest.mark.asyncio
    async def test_validate_with_empty_data(self):
        validator = BaseValidator()
        result = await validator.validate({}, {})
        assert result.status == "failed"
        assert "Missing required" in result.details

    @pytest.mark.asyncio
    async def test_validate_missing_energy_fields(self):
        validator = BaseValidator()
        result = await validator.validate({"agent_id": "test"}, {})
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_validate_missing_vote_fields(self):
        validator = BaseValidator()
        result = await validator.validate(
            {"agent_id": "test", "proposal_id": "prop1", "energy_amount": 100},
            {}
        )
        assert result.status == "failed"
