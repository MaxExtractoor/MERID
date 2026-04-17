"""Tests for core/validation/polymarket.py - Batch 77."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.validation.polymarket import PolymarketValidator


class TestPolymarketValidator:
    """Tests for PolymarketValidator."""

    @pytest.fixture
    def validator(self):
        return PolymarketValidator()

    def test_name(self, validator):
        """Test validator name."""
        assert validator.name == "polymarket"

    def test_weight(self, validator):
        """Test validator weight."""
        assert validator.weight == 1.0

    @pytest.mark.asyncio
    async def test_validate_no_api_key(self, validator):
        """Test validate with no API key."""
        energy = {"metadata": {"market_id": "test-market"}}
        vote_result = {}
        
        with patch.dict('os.environ', {}, clear=True):
            result = await validator.validate(energy, vote_result)
            
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_validate_missing_market_id(self, validator):
        """Test validate with missing market_id."""
        energy = {"metadata": {}}
        vote_result = {}
        
        result = await validator.validate(energy, vote_result)
        
        assert result.status == "pending"
