"""Tests for core/validation/polymarket.py."""
import pytest
import respx
from httpx import Response
from core.validation.polymarket import PolymarketValidator


class TestPolymarketValidator:
    """Test PolymarketValidator class."""

    def test_default_attributes(self):
        """Test default validator attributes."""
        validator = PolymarketValidator()
        assert validator.name == "polymarket"
        assert validator.weight == 1.0
        assert validator.API_BASE == "https://clob.polymarket.com"

    @pytest.mark.asyncio
    async def test_validate_no_market_id(self):
        """Test validation with no market_id."""
        validator = PolymarketValidator()
        energy = {"metadata": {}}  # No polymarket_market_id
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "No Polymarket market_id" in verdict.details

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_market_unresolved(self):
        """Test validation with unresolved market."""
        validator = PolymarketValidator()
        
        # Mock API response
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(200, json={
                "status": "open",
                "resolution": "active"
            })
        )
        
        energy = {"metadata": {"polymarket_market_id": "market_123"}}
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "unresolved" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_market_resolved_no_winning(self):
        """Test validation with resolved market but no winning outcome."""
        validator = PolymarketValidator()
        
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(200, json={
                "status": "resolved",
                "winning_outcome": None
            })
        )
        
        energy = {"metadata": {"polymarket_market_id": "market_123"}}
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "no winning outcome" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_success_with_expected_match(self):
        """Test validation with expected outcome matching."""
        validator = PolymarketValidator()
        
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(200, json={
                "status": "resolved",
                "winning_outcome": "Yes"
            })
        )
        
        energy = {
            "metadata": {
                "polymarket_market_id": "market_123",
                "polymarket_expected_outcome": "Yes"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "matched" in verdict.details.lower()
        assert verdict.evidence["outcome"] == "yes"

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_failure_with_expected_mismatch(self):
        """Test validation with expected outcome mismatch."""
        validator = PolymarketValidator()
        
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(200, json={
                "status": "resolved",
                "winning_outcome": "No"
            })
        )
        
        energy = {
            "metadata": {
                "polymarket_market_id": "market_123",
                "polymarket_expected_outcome": "Yes"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "failed"
        assert "mismatch" in verdict.details.lower()
        assert verdict.evidence["expected"] == "yes"
        assert verdict.evidence["outcome"] == "no"

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_success_no_expected(self):
        """Test validation with no expected outcome specified."""
        validator = PolymarketValidator()
        
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(200, json={
                "status": "resolved",
                "winning_outcome": "Yes"
            })
        )
        
        energy = {
            "metadata": {
                "polymarket_market_id": "market_123"
                # No polymarket_expected_outcome
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "no expected outcome" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_api_error(self):
        """Test validation when API returns error."""
        validator = PolymarketValidator()
        
        respx.get("https://clob.polymarket.com/markets/market_123").mock(
            return_value=Response(500, text="Server Error")
        )
        
        energy = {"metadata": {"polymarket_market_id": "market_123"}}
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "error"
        assert "lookup failed" in verdict.details.lower()
