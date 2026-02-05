"""Tests for core/validation/time_window.py - Batch A."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.validation.time_window import TimeWindowValidator


class TestTimeWindowValidator:
    """Tests for TimeWindowValidator."""

    def test_validator_properties(self):
        validator = TimeWindowValidator()
        assert validator.name == "time_window"
        assert validator.weight == 0.8

    @pytest.mark.asyncio
    async def test_validate_missing_window_hours(self):
        validator = TimeWindowValidator()
        energy = {"metadata": {"issued_at": "2024-01-01T00:00:00"}}
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
        assert "Missing validation window" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_issued_at(self):
        validator = TimeWindowValidator()
        energy = {"metadata": {"validation_window_hours": 24}}
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
        assert "Missing validation window" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_invalid_timestamp(self):
        validator = TimeWindowValidator()
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": "invalid-timestamp"
            }
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "error"
        assert "Invalid issued_at" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_not_complete(self):
        validator = TimeWindowValidator()
        # Set issued_at to now so window is definitely not complete
        now = datetime.utcnow()
        issued_at = now.isoformat()

        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": issued_at
            }
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
        assert "Awaiting window completion" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_complete_no_outcome(self):
        validator = TimeWindowValidator()
        # Set issued_at to past so window is complete
        past = datetime.utcnow() - timedelta(hours=25)

        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": past.isoformat()
            }
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
        assert "no validation outcome submitted" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_complete_confirmed(self):
        validator = TimeWindowValidator()
        past = datetime.utcnow() - timedelta(hours=25)

        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": past.isoformat(),
                "validation_outcome": "confirmed"
            }
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "confirmed"
        assert "reported as confirmed" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_complete_failed(self):
        validator = TimeWindowValidator()
        past = datetime.utcnow() - timedelta(hours=25)

        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": past.isoformat(),
                "validation_outcome": "failed"
            }
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "failed"
        assert "reported as failed" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_with_timestamp_from_energy(self):
        validator = TimeWindowValidator()
        past = datetime.utcnow() - timedelta(hours=25)

        # Use timestamp from energy instead of metadata
        energy = {
            "metadata": {"validation_window_hours": 24},
            "timestamp": {"utc_iso": past.isoformat()}
        }
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
