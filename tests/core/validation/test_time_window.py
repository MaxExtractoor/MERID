"""Tests for core/validation/time_window.py."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from core.validation.time_window import TimeWindowValidator


class TestTimeWindowValidator:
    """Test TimeWindowValidator class."""

    def test_default_attributes(self):
        """Test default validator attributes."""
        validator = TimeWindowValidator()
        assert validator.name == "time_window"
        assert validator.weight == 0.8

    @pytest.mark.asyncio
    async def test_validate_missing_window_hours(self):
        """Test validation with missing validation_window_hours."""
        validator = TimeWindowValidator()
        energy = {"metadata": {"issued_at": "2024-01-01T00:00:00"}}  # No window_hours
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "Missing validation window" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_issued_at(self):
        """Test validation with missing issued_at."""
        validator = TimeWindowValidator()
        energy = {"metadata": {"validation_window_hours": 24}}  # No issued_at
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "Missing validation window" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_invalid_timestamp(self):
        """Test validation with invalid timestamp."""
        validator = TimeWindowValidator()
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": "not-a-valid-timestamp"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "error"
        assert "Invalid issued_at" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_not_elapsed(self):
        """Test validation when window has not elapsed."""
        validator = TimeWindowValidator()
        
        # Set issued_at to now (window not elapsed)
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
        assert "remaining" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_window_elapsed_no_outcome(self):
        """Test validation when window elapsed but no outcome."""
        validator = TimeWindowValidator()
        
        # Set issued_at to 25 hours ago (window elapsed)
        past = datetime.utcnow() - timedelta(hours=25)
        issued_at = past.isoformat()
        
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": issued_at
                # No validation_outcome
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "no validation outcome submitted" in verdict.details.lower()

    @pytest.mark.asyncio
    async def test_validate_window_elapsed_confirmed(self):
        """Test validation when window elapsed with confirmed outcome."""
        validator = TimeWindowValidator()
        
        # Set issued_at to 25 hours ago
        past = datetime.utcnow() - timedelta(hours=25)
        issued_at = past.isoformat()
        
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": issued_at,
                "validation_outcome": "confirmed"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "confirmed" in verdict.details.lower()

    @pytest.mark.asyncio
    async def test_validate_window_elapsed_failed(self):
        """Test validation when window elapsed with failed outcome."""
        validator = TimeWindowValidator()
        
        # Set issued_at to 25 hours ago
        past = datetime.utcnow() - timedelta(hours=25)
        issued_at = past.isoformat()
        
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": issued_at,
                "validation_outcome": "failed"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "failed" in verdict.details.lower()

    @pytest.mark.asyncio
    async def test_validate_uses_energy_timestamp(self):
        """Test validation uses energy.timestamp.utc_iso when issued_at not present."""
        validator = TimeWindowValidator()
        
        # Set timestamp to 25 hours ago
        past = datetime.utcnow() - timedelta(hours=25)
        
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                # No issued_at, should fall back to timestamp.utc_iso
            },
            "timestamp": {
                "utc_iso": past.isoformat()
            },
            "validation_outcome": "confirmed"
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"

    @pytest.mark.asyncio
    async def test_validate_handles_z_suffix(self):
        """Test validation handles 'Z' suffix in timestamp."""
        validator = TimeWindowValidator()
        
        # Set timestamp to 25 hours ago with Z suffix
        past = datetime.utcnow() - timedelta(hours=25)
        issued_at = past.isoformat() + "Z"
        
        energy = {
            "metadata": {
                "validation_window_hours": 24,
                "issued_at": issued_at,
                "validation_outcome": "confirmed"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
