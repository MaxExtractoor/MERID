"""Tests for core/validation/time_window.py - Batch 78."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.validation.time_window import TimeWindowValidator


class TestTimeWindowValidator:
    """Tests for TimeWindowValidator."""

    @pytest.fixture
    def validator(self):
        return TimeWindowValidator()

    def test_name(self, validator):
        """Test validator name."""
        assert validator.name == "time_window"

    def test_weight(self, validator):
        """Test validator weight."""
        assert validator.weight == 0.8

    @pytest.mark.asyncio
    async def test_validate_missing_window_hours(self, validator):
        """Test validate with missing window_hours."""
        energy = {"metadata": {"issued_at": "2024-01-01T00:00:00"}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "pending"
        assert "Missing validation window" in result.details

    @pytest.mark.asyncio
    async def test_validate_missing_issued_at(self, validator):
        """Test validate with missing issued_at."""
        energy = {"metadata": {"validation_window_hours": 24}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_validate_invalid_timestamp(self, validator):
        """Test validate with invalid timestamp."""
        energy = {"metadata": {"validation_window_hours": 24, "issued_at": "invalid"}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_validate_window_not_complete(self, validator):
        """Test validate when window is not complete."""
        future_time = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        energy = {"metadata": {"validation_window_hours": 24, "issued_at": future_time}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "pending"
        assert "Awaiting window completion" in result.details

    @pytest.mark.asyncio
    async def test_validate_window_elapsed_no_outcome(self, validator):
        """Test validate when window elapsed but no outcome."""
        past_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        energy = {"metadata": {"validation_window_hours": 24, "issued_at": past_time}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "pending"
