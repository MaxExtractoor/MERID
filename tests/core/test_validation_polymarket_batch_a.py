"""Tests for core/validation/polymarket.py - Batch A simplified."""
import pytest

from core.validation.polymarket import PolymarketValidator


class TestPolymarketValidator:
    """Tests for PolymarketValidator."""

    def test_validator_properties(self):
        validator = PolymarketValidator()
        assert validator.name == "polymarket"
        assert validator.weight == 1.0
        assert validator.API_BASE == "https://clob.polymarket.com"

    @pytest.mark.asyncio
    async def test_validate_no_market_id(self):
        validator = PolymarketValidator()
        energy = {"metadata": {}}
        vote_result = {}

        verdict = await validator.validate(energy, vote_result)

        assert verdict.status == "pending"
        assert "No Polymarket market_id" in verdict.details
