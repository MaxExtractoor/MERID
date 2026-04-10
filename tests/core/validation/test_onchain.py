"""Tests for core/validation/onchain.py."""
import pytest
respx = pytest.importorskip("respx")
from httpx import Response
from core.validation.onchain import OnChainPriceValidator


class TestOnChainPriceValidator:
    """Test OnChainPriceValidator class."""

    def test_default_attributes(self):
        """Test default validator attributes."""
        validator = OnChainPriceValidator()
        assert validator.name == "onchain_price"
        assert validator.weight == 0.9
        assert validator._endpoint == "https://api.coingecko.com/api/v3/simple/price"

    @pytest.mark.asyncio
    async def test_validate_missing_asset(self):
        """Test validation with missing asset_id."""
        validator = OnChainPriceValidator()
        energy = {"metadata": {"target_price": 50000.0}}  # No asset_id
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "No asset_id" in verdict.details

    @pytest.mark.asyncio
    async def test_validate_missing_target_price(self):
        """Test validation with missing target_price."""
        validator = OnChainPriceValidator()
        energy = {"metadata": {"asset_id": "bitcoin"}}  # No target_price
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "target_price" in verdict.details

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_absolute_target_success(self):
        """Test validation with absolute target price success."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"bitcoin": {"usd": 50000.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 50000.0,
                "target_tolerance": 0.01  # 1% tolerance
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "reached target" in verdict.details.lower()
        assert verdict.evidence["price"] == 50000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_absolute_target_pending(self):
        """Test validation with absolute target price pending."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"bitcoin": {"usd": 48000.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 50000.0,
                "target_tolerance": 0.01
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "Waiting for price" in verdict.details

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_direction_above_success(self):
        """Test validation with direction above success."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"ethereum": {"usd": 3100.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "ethereum",
                "target_price": 3000.0,
                "target_direction": "above"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "above threshold" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_direction_above_pending(self):
        """Test validation with direction above pending."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"ethereum": {"usd": 2900.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "ethereum",
                "target_price": 3000.0,
                "target_direction": "above"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "not yet above" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_direction_below_success(self):
        """Test validation with direction below success."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"bitcoin": {"usd": 29000.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 30000.0,
                "target_direction": "below"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert "below threshold" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_direction_below_pending(self):
        """Test validation with direction below pending."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"bitcoin": {"usd": 31000.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 30000.0,
                "target_direction": "below"
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "not yet below" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_unknown_direction(self):
        """Test validation with unknown direction."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"bitcoin": {"usd": 50000.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 50000.0,
                "target_direction": "sideways"  # Unknown direction
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "pending"
        assert "Unknown direction" in verdict.details

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_api_error(self):
        """Test validation when API returns error."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(500, text="Server Error")
        )
        
        energy = {
            "metadata": {
                "asset_id": "bitcoin",
                "target_price": 50000.0
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "error"
        assert "lookup failed" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_missing_asset_in_response(self):
        """Test validation when asset missing in API response."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"other_coin": {"usd": 100.0}})
        )
        
        energy = {
            "metadata": {
                "asset_id": "unknown_coin",
                "target_price": 100.0
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "error"
        assert "missing" in verdict.details.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_validate_uses_coingecko_id(self):
        """Test validation uses coingecko_id when asset_id not present."""
        validator = OnChainPriceValidator()
        
        respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
            return_value=Response(200, json={"ethereum": {"usd": 3000.0}})
        )
        
        energy = {
            "metadata": {
                "coingecko_id": "ethereum",  # Using coingecko_id instead of asset_id
                "target_price": 3000.0
            }
        }
        vote_result = {}
        
        verdict = await validator.validate(energy, vote_result)
        
        assert verdict.status == "confirmed"
        assert verdict.evidence["asset"] == "ethereum"
