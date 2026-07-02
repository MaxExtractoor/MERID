"""
Tests for Spot Price Parity and Symmetric Behavior

Tests the 5-asset symmetric spot behavior with stub provider and
real provider scenarios to ensure SOL is treated identically to other assets.
"""

import asyncio
import time
import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from merid.core.spot_parity_helpers import (
    fetch_spot_symmetric, fetch_all_spot_parity, SpotParitySummary,
    SpotFetchResult, validate_spot_price, log_parity_diagnostics,
    ASSET_CONFIG, get_asset_provider, get_asset_timeout, is_asset_supported,
    get_supported_assets
)


class TestSpotPriceValidation:
    """Test spot price validation across all assets."""
    
    def test_validate_btc_price(self):
        """Test BTC price validation."""
        # Valid prices
        assert validate_spot_price("BTC", 50000.0) == (True, None)
        assert validate_spot_price("BTC", 1000.0) == (True, None)  # Lower bound
        assert validate_spot_price("BTC", 500000.0) == (True, None)  # Upper bound
        
        # Invalid prices
        assert validate_spot_price("BTC", 999.0)[0] is False  # Below range
        assert validate_spot_price("BTC", 500001.0)[0] is False  # Above range
        assert validate_spot_price("BTC", -100.0)[0] is False  # Negative
        assert validate_spot_price("BTC", 2000000.0)[0] is False  # Sanity check
    
    def test_validate_eth_price(self):
        """Test ETH price validation."""
        # Valid prices
        assert validate_spot_price("ETH", 3000.0) == (True, None)
        assert validate_spot_price("ETH", 10.0) == (True, None)  # Lower bound
        assert validate_spot_price("ETH", 20000.0) == (True, None)  # Upper bound
        
        # Invalid prices
        assert validate_spot_price("ETH", 9.0)[0] is False  # Below range
        assert validate_spot_price("ETH", 20001.0)[0] is False  # Above range
    
    def test_validate_sol_price(self):
        """Test SOL price validation."""
        # Valid prices
        assert validate_spot_price("SOL", 150.0) == (True, None)
        assert validate_spot_price("SOL", 0.10) == (True, None)  # Lower bound
        assert validate_spot_price("SOL", 1000.0) == (True, None)  # Upper bound
        
        # Invalid prices
        assert validate_spot_price("SOL", 0.05)[0] is False  # Below range
        assert validate_spot_price("SOL", 1001.0)[0] is False  # Above range
    
    def test_validate_xrp_price(self):
        """Test XRP price validation."""
        # Valid prices
        assert validate_spot_price("XRP", 0.5) == (True, None)
        assert validate_spot_price("XRP", 0.001) == (True, None)  # Lower bound
        assert validate_spot_price("XRP", 100.0) == (True, None)  # Upper bound
        
        # Invalid prices
        assert validate_spot_price("XRP", 0.0005)[0] is False  # Below range
        assert validate_spot_price("XRP", 101.0)[0] is False  # Above range
    
    def test_validate_doge_price(self):
        """Test DOGE price validation."""
        # Valid prices
        assert validate_spot_price("DOGE", 0.08) == (True, None)
        assert validate_spot_price("DOGE", 0.0001) == (True, None)  # Lower bound
        assert validate_spot_price("DOGE", 10.0) == (True, None)  # Upper bound
        
        # Invalid prices
        assert validate_spot_price("DOGE", 0.00005)[0] is False  # Below range
        assert validate_spot_price("DOGE", 11.0)[0] is False  # Above range
    
    def test_validate_unknown_asset(self):
        """Test validation for unknown asset."""
        result = validate_spot_price("UNKNOWN", 100.0)
        assert result[0] is False
        assert "Unknown asset" in result[1]


class TestSymmetricSpotFetch:
    """Test symmetric spot fetch behavior."""
    
    @pytest.mark.asyncio
    async def test_fetch_spot_symmetric_success(self):
        """Test successful symmetric fetch."""
        # Mock fetch function
        mock_fetch = AsyncMock(return_value={
            'price': 50000.0,
            'timestamp': int(time.time() * 1000)
        })
        
        result = await fetch_spot_symmetric("BTC", mock_fetch, cycle_id=1)
        
        assert result.asset == "BTC"
        assert result.success is True
        assert result.price == 50000.0
        assert result.provider == "coinbase_public"
        assert result.latency_ms is not None
        assert result.error_kind is None
    
    @pytest.mark.asyncio
    async def test_fetch_spot_symmetric_timeout(self):
        """Test symmetric fetch timeout."""
        # Mock fetch function that times out
        mock_fetch = AsyncMock(side_effect=asyncio.TimeoutError())
        
        result = await fetch_spot_symmetric("SOL", mock_fetch, cycle_id=1)
        
        assert result.asset == "SOL"
        assert result.success is False
        assert result.error_kind == "timeout"
        assert result.provider == "coinbase_public"
        assert result.latency_ms == 4000.0  # 4s timeout
    
    @pytest.mark.asyncio
    async def test_fetch_spot_symmetric_invalid_price(self):
        """Test symmetric fetch with invalid price."""
        # Mock fetch function returning invalid price
        mock_fetch = AsyncMock(return_value={
            'price': -100.0,  # Invalid negative price
            'timestamp': int(time.time() * 1000)
        })
        
        result = await fetch_spot_symmetric("ETH", mock_fetch, cycle_id=1)
        
        assert result.asset == "ETH"
        assert result.success is False
        assert result.error_kind == "validation_error"
        assert "outside reasonable range" in result.warning_message
    
    @pytest.mark.asyncio
    async def test_fetch_spot_symmetric_parse_error(self):
        """Test symmetric fetch with parse error."""
        # Mock fetch function returning None
        mock_fetch = AsyncMock(return_value=None)
        
        result = await fetch_spot_symmetric("XRP", mock_fetch, cycle_id=1)
        
        assert result.asset == "XRP"
        assert result.success is False
        assert result.error_kind == "fetch_error"
        assert "returned None" in result.warning_message
    
    @pytest.mark.asyncio
    async def test_fetch_spot_symmetric_no_price(self):
        """Test symmetric fetch with missing price."""
        # Mock fetch function returning dict without price
        mock_fetch = AsyncMock(return_value={'timestamp': int(time.time() * 1000)})
        
        result = await fetch_spot_symmetric("DOGE", mock_fetch, cycle_id=1)
        
        assert result.asset == "DOGE"
        assert result.success is False
        assert result.error_kind == "parse_error"
        assert "No price" in result.warning_message


class TestSpotParitySummary:
    """Test spot parity summary functionality."""
    
    def test_parity_summary_success_count(self):
        """Test success count calculation."""
        summary = SpotParitySummary(cycle_id=1, timestamp_ms=int(time.time() * 1000))
        
        # Add some results
        summary.results["BTC"] = SpotFetchResult("BTC", True, price=50000.0)
        summary.results["ETH"] = SpotFetchResult("ETH", True, price=3000.0)
        summary.results["SOL"] = SpotFetchResult("SOL", False, error_kind="timeout")
        summary.results["XRP"] = SpotFetchResult("XRP", True, price=0.5)
        summary.results["DOGE"] = SpotFetchResult("DOGE", False, error_kind="timeout")
        
        assert summary.success_count() == 3
        assert summary.failure_count() == 2
        assert summary.has_parity_violation() is True
        assert set(summary.get_failed_assets()) == {"SOL", "DOGE"}
    
    def test_parity_summary_no_violation(self):
        """Test no parity violation when all succeed or all fail."""
        summary = SpotParitySummary(cycle_id=1, timestamp_ms=int(time.time() * 1000))
        
        # All succeed
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            summary.results[asset] = SpotFetchResult(asset, True, price=100.0)
        
        assert summary.has_parity_violation() is False
        assert summary.get_parity_violation_message() == ""
        
        # All fail
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            summary.results[asset] = SpotFetchResult(asset, False, error_kind="timeout")
        
        assert summary.has_parity_violation() is False
        assert summary.get_parity_violation_message() == ""
    
    def test_parity_summary_error_distribution(self):
        """Test error distribution calculation."""
        summary = SpotParitySummary(cycle_id=1, timestamp_ms=int(time.time() * 1000))
        
        # Add results with different error types
        summary.results["BTC"] = SpotFetchResult("BTC", False, error_kind="timeout")
        summary.results["ETH"] = SpotFetchResult("ETH", False, error_kind="timeout")
        summary.results["SOL"] = SpotFetchResult("SOL", False, error_kind="parse_error")
        summary.results["XRP"] = SpotFetchResult("XRP", False, error_kind="timeout")
        summary.results["DOGE"] = SpotFetchResult("DOGE", False, error_kind="validation_error")
        
        error_dist = summary.get_error_distribution()
        assert error_dist == {"timeout": 3, "parse_error": 1, "validation_error": 1}


class TestAllAssetParity:
    """Test parity across all 5 assets."""
    
    @pytest.mark.asyncio
    async def test_fetch_all_spot_parity_all_success(self):
        """Test parity when all assets succeed."""
        # Mock fetch function that succeeds for all assets
        async def mock_fetch(asset: str, timeout: float) -> dict:
            prices = {"BTC": 50000, "ETH": 3000, "SOL": 150, "XRP": 0.5, "DOGE": 0.08}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000)
            }
        
        summary = await fetch_all_spot_parity(mock_fetch, cycle_id=1)
        
        assert summary.cycle_id == 1
        assert summary.success_count() == 5
        assert summary.failure_count() == 0
        assert summary.has_parity_violation() is False
        
        # Check all assets have correct prices
        assert summary.results["BTC"].price == 50000
        assert summary.results["ETH"].price == 3000
        assert summary.results["SOL"].price == 150
        assert summary.results["XRP"].price == 0.5
        assert summary.results["DOGE"].price == 0.08
    
    @pytest.mark.asyncio
    async def test_fetch_all_spot_parity_sol_only_fails(self):
        """Test parity when only SOL fails (the original issue)."""
        async def mock_fetch(asset: str, timeout: float) -> dict:
            if asset == "SOL":
                raise asyncio.TimeoutError()  # SOL times out
            prices = {"BTC": 50000, "ETH": 3000, "XRP": 0.5, "DOGE": 0.08}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000)
            }
        
        summary = await fetch_all_spot_parity(mock_fetch, cycle_id=1)
        
        assert summary.success_count() == 4
        assert summary.failure_count() == 1
        assert summary.has_parity_violation() is True
        assert summary.get_failed_assets() == ["SOL"]
        
        # Check error distribution
        error_dist = summary.get_error_distribution()
        assert error_dist == {"timeout": 1}
        
        # Check parity violation message
        message = summary.get_parity_violation_message()
        assert "SOL" in message
        assert "4/5" in message
    
    @pytest.mark.asyncio
    async def test_fetch_all_spot_parity_multiple_failures(self):
        """Test parity when multiple assets fail."""
        async def mock_fetch(asset: str, timeout: float) -> dict:
            if asset in ["SOL", "DOGE"]:
                raise asyncio.TimeoutError()  # These timeout
            prices = {"BTC": 50000, "ETH": 3000, "XRP": 0.5}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000)
            }
        
        summary = await fetch_all_spot_parity(mock_fetch, cycle_id=1)
        
        assert summary.success_count() == 3
        assert summary.failure_count() == 2
        assert summary.has_parity_violation() is True
        assert set(summary.get_failed_assets()) == {"SOL", "DOGE"}
    
    @pytest.mark.asyncio
    async def test_fetch_all_spot_parity_all_fail(self):
        """Test parity when all assets fail."""
        async def mock_fetch(asset: str, timeout: float) -> dict:
            raise asyncio.TimeoutError()  # All timeout
        
        summary = await fetch_all_spot_parity(mock_fetch, cycle_id=1)
        
        assert summary.success_count() == 0
        assert summary.failure_count() == 5
        assert summary.has_parity_violation() is False  # No violation when all fail
    
    @pytest.mark.asyncio
    async def test_fetch_all_spot_parity_latency_analysis(self):
        """Test latency analysis in parity summary."""
        async def mock_fetch(asset: str, timeout: float) -> dict:
            # Simulate different latencies per asset
            if asset == "SOL":
                await asyncio.sleep(0.1)  # SOL slower
            prices = {"BTC": 50000, "ETH": 3000, "SOL": 150, "XRP": 0.5, "DOGE": 0.08}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000)
            }
        
        summary = await fetch_all_spot_parity(mock_fetch, cycle_id=1)
        
        # Check that SOL has higher latency
        sol_latency = summary.results["SOL"].latency_ms
        btc_latency = summary.results["BTC"].latency_ms
        
        assert sol_latency > btc_latency
        assert sol_latency > 100  # Should be > 100ms due to sleep


class TestAssetConfiguration:
    """Test asset configuration functions."""
    
    def test_get_asset_provider(self):
        """Test getting provider for each asset."""
        assert get_asset_provider("BTC") == "coinbase_public"
        assert get_asset_provider("ETH") == "coinbase_public"
        assert get_asset_provider("SOL") == "coinbase_public"
        assert get_asset_provider("XRP") == "coinbase_public"
        assert get_asset_provider("DOGE") == "coinbase_public"
        assert get_asset_provider("UNKNOWN") is None
    
    def test_get_asset_timeout(self):
        """Test getting timeout for each asset."""
        assert get_asset_timeout("BTC") == 4.0
        assert get_asset_timeout("ETH") == 4.0
        assert get_asset_timeout("SOL") == 4.0  # Same as others
        assert get_asset_timeout("XRP") == 4.0
        assert get_asset_timeout("DOGE") == 4.0
        assert get_asset_timeout("UNKNOWN") == 4.0  # Default
    
    def test_is_asset_supported(self):
        """Test asset support checking."""
        assert is_asset_supported("BTC") is True
        assert is_asset_supported("ETH") is True
        assert is_asset_supported("SOL") is True
        assert is_asset_supported("XRP") is True
        assert is_asset_supported("DOGE") is True
        assert is_asset_supported("UNKNOWN") is False
    
    def test_get_supported_assets(self):
        """Test getting all supported assets."""
        assets = get_supported_assets()
        expected = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assert sorted(assets) == sorted(expected)


class TestStubProviderIntegration:
    """Test integration with stub provider to prove contract vs runtime behavior."""
    
    @pytest.mark.asyncio
    async def test_stub_provider_all_success(self):
        """Test stub provider that returns fixed prices for all assets."""
        async def stub_fetch(asset: str, timeout: float) -> dict:
            # Stub provider returns fixed price after 50ms delay
            await asyncio.sleep(0.05)
            prices = {"BTC": 50000, "ETH": 3000, "SOL": 150, "XRP": 0.5, "DOGE": 0.08}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000),
                'source': 'stub_provider'
            }
        
        summary = await fetch_all_spot_parity(stub_fetch, cycle_id=1)
        
        # All should succeed with identical behavior
        assert summary.success_count() == 5
        assert summary.failure_count() == 0
        assert summary.has_parity_violation() is False
        
        # Check latencies are similar (all ~50ms)
        latencies = [r.latency_ms for r in summary.results.values()]
        for latency in latencies:
            assert 45 <= latency <= 60  # Allow some variance
        
        # Check all have same source
        for result in summary.results.values():
            assert result.provider == "coinbase_public"  # From config
    
    @pytest.mark.asyncio
    async def test_stub_provider_sol_timeout_simulation(self):
        """Test stub provider that simulates SOL timeout to isolate the issue."""
        async def stub_fetch(asset: str, timeout: float) -> dict:
            if asset == "SOL":
                await asyncio.sleep(0.1)  # Simulate SOL delay
                raise asyncio.TimeoutError()
            
            await asyncio.sleep(0.01)  # Other assets fast
            prices = {"BTC": 50000, "ETH": 3000, "XRP": 0.5, "DOGE": 0.08}
            return {
                'price': prices[asset],
                'timestamp': int(time.time() * 1000),
                'source': 'stub_provider'
            }
        
        summary = await fetch_all_spot_parity(stub_fetch, cycle_id=1)
        
        # Should detect parity violation
        assert summary.success_count() == 4
        assert summary.failure_count() == 1
        assert summary.has_parity_violation() is True
        assert summary.get_failed_assets() == ["SOL"]
        
        # SOL should have timeout error
        sol_result = summary.results["SOL"]
        assert sol_result.error_kind == "timeout"
        assert sol_result.latency_ms == 4000.0  # Full timeout duration
        
        # Other assets should be fast
        for asset in ["BTC", "ETH", "XRP", "DOGE"]:
            result = summary.results[asset]
            assert result.success is True
            assert result.latency_ms < 50  # Should be fast


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
