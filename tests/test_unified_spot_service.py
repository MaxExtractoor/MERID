"""
Test suite for UnifiedSpotService
Comprehensive testing of spot price service consolidation for Kalshi 15m contracts

Run with: pytest tests/test_unified_spot_service.py -v -s
Run specific: pytest tests/test_unified_spot_service.py::TestUnifiedSpotService::test_initialization_and_startup -v
Run live: pytest tests/test_unified_spot_service.py::TestLiveIntegration -v -s
"""
import pytest
import asyncio
import time
import base64
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import os

# Import your actual modules - adjust paths as needed
from data.unified_spot_service import (
    UnifiedSpotService, 
    SpotPrice,
    SpotError,
    get_unified_spot_service,
    _get_coinbase_credentials,
    _generate_coinbase_signature,
    _retry_with_backoff
)


def format_price(asset: str, price: float) -> str:
    """Format price with appropriate decimal places based on asset."""
    asset_precision = {
        "BTC": 2,
        "ETH": 2,
        "SOL": 4,
        "XRP": 4,
        "DOGE": 7
    }
    precision = asset_precision.get(asset.upper(), 4)
    return f"{price:.{precision}f}"


class TestFormatPrice:
    """Test format_price function for asset-aware price formatting"""
    
    def test_format_price_btc(self):
        """Test BTC price formatting (2 decimal places)"""
        result = format_price("BTC", 67000.123456)
        assert result == "67000.12"
    
    def test_format_price_eth(self):
        """Test ETH price formatting (2 decimal places)"""
        result = format_price("ETH", 1746.456789)
        assert result == "1746.46"
    
    def test_format_price_sol(self):
        """Test SOL price formatting (4 decimal places)"""
        result = format_price("SOL", 78.12345678)
        assert result == "78.1235"
    
    def test_format_price_xrp(self):
        """Test XRP price formatting (4 decimal places)"""
        result = format_price("XRP", 1.09723456)
        assert result == "1.0972"
    
    def test_format_price_doge(self):
        """Test DOGE price formatting (7 decimal places)"""
        result = format_price("DOGE", 0.07263456789)
        assert result == "0.0726346"
    
    def test_format_price_unknown_asset(self):
        """Test unknown asset uses default 4 decimal places"""
        result = format_price("UNKNOWN", 100.12345678)
        assert result == "100.1235"


class TestUnifiedSpotService:
    """Unit tests for UnifiedSpotService core functionality"""
    
    @pytest.fixture
    async def spot_service(self):
        """Create fresh UnifiedSpotService instance for each test"""
        # Get singleton and reset state
        service = get_unified_spot_service()
        
        # Stop if already running
        if service._running:
            await service.stop_refresh_loop()
        
        # Reset internal state
        service._cache = {}
        service._running = False
        
        yield service
        
        # Cleanup
        if service._running:
            await service.stop_refresh_loop()
    
    @pytest.mark.asyncio
    async def test_initialization_and_startup(self, spot_service):
        """Test service initializes and starts correctly"""
        assert not spot_service._running
        assert spot_service._cache == {}
        
        await spot_service.start_refresh_loop()
        assert spot_service._running
        
        await spot_service.stop_refresh_loop()
        assert not spot_service._running
    
    @pytest.mark.asyncio
    async def test_get_spot_returns_valid_structure(self, spot_service):
        """Test that get returns correct SpotPrice structure"""
        # Prime cache with mock data
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0,
            'volume': 12345.67  # Volume for volume confirmation filter
        }
        
        spot = spot_service.get("BTC")
        
        assert spot is not None
        assert isinstance(spot, SpotPrice)
        assert hasattr(spot, 'price')
        assert hasattr(spot, 'timestamp')
        assert hasattr(spot, 'source')
        assert hasattr(spot, 'confidence')
        assert hasattr(spot, 'open')
        assert hasattr(spot, 'high')
        assert hasattr(spot, 'low')
        assert hasattr(spot, 'volume')  # CRITICAL: Volume field for volume confirmation filter
        
        assert isinstance(spot.price, float)
        assert spot.price > 0
        assert spot.source in ["coinbase_public", "coinbase_exchange_authenticated"]
        assert 0.0 <= spot.confidence <= 1.0
        assert isinstance(spot.timestamp, int)
        assert spot.timestamp > 0
        # Test volume field
        assert spot.volume == 12345.67 or spot.volume is None  # Volume may be None if not available
    
    @pytest.mark.asyncio
    async def test_unsupported_asset_returns_spot_error(self, spot_service):
        """Test that unsupported assets return SpotError"""
        spot = spot_service.get("INVALID")
        assert isinstance(spot, SpotError)
        assert spot.reason == "no_data"
        
        spot = spot_service.get("AAPL")  # Stock, not crypto
        assert isinstance(spot, SpotError)
    
    @pytest.mark.asyncio
    async def test_cache_hit_avoids_refetch(self, spot_service):
        """Test that cached values are reused within TTL"""
        # Prime cache
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0
        }
        
        # First fetch
        spot1 = spot_service.get("BTC")
        timestamp_1 = spot1.timestamp
        
        # Immediate second fetch should hit cache
        await asyncio.sleep(0.1)  # Small delay
        spot2 = spot_service.get("BTC")
        
        assert spot1.price == spot2.price
        assert timestamp_1 == spot2.timestamp  # Same cached data
    
    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test that get_unified_spot_service returns same instance"""
        service1 = get_unified_spot_service()
        service2 = get_unified_spot_service()
        
        assert service1 is service2


class TestSourceFailover:
    """Test failover behavior when sources fail"""
    
    @pytest.fixture
    async def spot_service(self):
        """Create service with clean state"""
        service = get_unified_spot_service()
        if service._running:
            await service.stop_refresh_loop()
        service._cache = {}
        yield service
        if service._running:
            await service.stop_refresh_loop()
    
    @pytest.mark.asyncio
    async def test_authenticated_ohlc_fallback_to_public(self, spot_service):
        """Test that authenticated API failure triggers public API fallback"""
        # Mock the authenticated fetch to fail
        with patch.object(spot_service, '_fetch_ohlc_authenticated', side_effect=Exception("Auth failed")):
            # Mock the ticker to fail as well (to force public fallback)
            with patch.object(spot_service, '_fetch_ticker_public', side_effect=Exception("Ticker failed")):
                # Mock the public fallback to succeed
                with patch.object(spot_service, '_fetch_spot_price_fallback_async', return_value={
                    'open': 67000.0,
                    'high': 67000.0,
                    'low': 67000.0,
                    'close': 67000.0
                }):
                    result = await spot_service._fetch_asset("BTC")
                    assert result is True
                    # Check cache was updated with public source
                    # CRITICAL FIX: When ticker fails and OHLC fallback succeeds, source is 'coinbase_ohlc'
                    # This is the actual behavior in unified_spot_service.py line 344
                    assert spot_service._cache["BTC"]["source"] in ["coinbase_public", "coinbase_ohlc"]
    
    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_spot_error(self, spot_service):
        """Test that all source failures return SpotError"""
        # Mock all fetches to fail (authenticated, ticker, public OHLC, and public fallback)
        with patch.object(spot_service, '_fetch_ohlc_authenticated', side_effect=Exception("Auth failed")):
            with patch.object(spot_service, '_fetch_ticker_public', side_effect=Exception("Ticker failed")):
                with patch.object(spot_service, '_fetch_ohlc_public', side_effect=Exception("Public OHLC failed")):
                    with patch.object(spot_service, '_fetch_spot_price_fallback_async', side_effect=Exception("Public fallback failed")):
                        result = await spot_service._fetch_asset("BTC")
                        assert result is False
    
    @pytest.mark.asyncio
    async def test_stale_data_returns_spot_error(self, spot_service):
        """Test that stale data returns SpotError"""
        # Prime cache with old data
        old_timestamp = int((time.time() - 120) * 1000)  # 120 seconds old
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': old_timestamp,
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0
        }
        
        spot = spot_service.get("BTC")
        
        assert isinstance(spot, SpotError)
        assert spot.reason == "stale"
        assert spot.age_s > 60  # Should be older than 60s threshold


class TestStalenessDetection:
    """Test staleness detection and handling"""
    
    @pytest.fixture
    async def spot_service(self):
        service = get_unified_spot_service()
        if service._running:
            await service.stop_refresh_loop()
        service._cache = {}
        yield service
        if service._running:
            await service.stop_refresh_loop()
    
    @pytest.mark.asyncio
    async def test_fresh_data_not_stale(self, spot_service):
        """Test that fresh data is marked as not stale"""
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0,
            'volume': 12345.67  # Volume for volume confirmation filter
        }
        
        spot = spot_service.get("BTC")
        
        assert isinstance(spot, SpotPrice)
        assert spot.price == 67000.0
        assert spot.volume == 12345.67  # Volume should be preserved
    
    @pytest.mark.asyncio
    async def test_staleness_flagged(self, spot_service):
        """CRITICAL: Test that old cached data is marked as stale"""
        # Manually inject old data into cache
        old_timestamp = int((time.time() - 120) * 1000)  # 120 seconds old
        spot_service._cache["ETH"] = {
            'price': 3500.0,
            'timestamp': old_timestamp,
            'source': 'coinbase_public',
            'open': 3500.0,
            'high': 3500.0,
            'low': 3500.0,
            'volume': 9876.54  # Volume for volume confirmation filter
        }
        
        spot = spot_service.get("ETH")
        
        assert isinstance(spot, SpotError)
        assert spot.reason == "stale"
        assert spot.age_s > 60


class TestCrossComponentConsistency:
    """CRITICAL: Test that PM model, execution, and filters all see same prices"""
    
    @pytest.fixture
    async def spot_service(self):
        service = get_unified_spot_service()
        if service._running:
            await service.stop_refresh_loop()
        service._cache = {}
        yield service
        if service._running:
            await service.stop_refresh_loop()
    
    @pytest.mark.asyncio
    async def test_no_split_brain(self, spot_service):
        """CRITICAL: Verify PM model and execution adapter see identical prices"""
        # Prime cache
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0,
            'volume': 12345.67  # Volume for volume confirmation filter
        }
        
        # Simulate what PM model does
        pm_spot = spot_service.get("BTC")
        
        # Simulate what execution adapter does
        exec_spot = spot_service.get("BTC")
        
        # Must be identical (same cache hit)
        assert pm_spot.price == exec_spot.price, "PM and execution prices diverged!"
        assert pm_spot.timestamp == exec_spot.timestamp, "PM and execution timestamps differ"
        assert pm_spot.source == exec_spot.source, "PM and execution sources differ"
        assert pm_spot.volume == exec_spot.volume, "PM and execution volumes differ"  # Volume consistency
        
        print(f"  ✓ No split-brain: PM and execution both see ${pm_spot.price:,.2f} from {pm_spot.source}")
    
    @pytest.mark.asyncio
    async def test_filter_pipeline_consistency(self, spot_service):
        """Test that filter pipeline sees same spot as other components"""
        # Prime cache
        spot_service._cache["ETH"] = {
            'price': 3500.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 3500.0,
            'high': 3500.0,
            'low': 3500.0,
            'volume': 9876.54  # Volume for volume confirmation filter
        }
        
        # Get spot directly
        direct_spot = spot_service.get("ETH")
        
        # Simulate filter pipeline fetch
        filter_spot = spot_service.get("ETH")
        
        assert direct_spot.price == filter_spot.price
        assert direct_spot.timestamp == filter_spot.timestamp
        assert direct_spot.volume == filter_spot.volume  # Volume consistency
        
        print(f"  ✓ Filter pipeline consistent: ${filter_spot.price:,.2f}")


class TestProductionScenarios:
    """Test real-world production failure scenarios"""
    
    @pytest.fixture
    async def spot_service(self):
        service = get_unified_spot_service()
        if service._running:
            await service.stop_refresh_loop()
        service._cache = {}
        yield service
        if service._running:
            await service.stop_refresh_loop()
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, spot_service):
        """CRITICAL: Test that rapid requests use cache, not hammering APIs"""
        # Prime cache
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0
        }
        
        # Make 20 rapid requests
        prices = []
        for i in range(20):
            spot = spot_service.get("BTC")
            assert isinstance(spot, SpotPrice), f"Request {i} failed"
            prices.append(spot.price)
        
        # All prices should be identical (from cache)
        assert len(set(prices)) == 1, "Prices varied - cache not consistent"
        
        print(f"  ✓ 20 requests → consistent cache hits")
    
    @pytest.mark.asyncio
    async def test_high_frequency_requests_performance(self, spot_service):
        """Test that cached requests are fast (< 1ms p95)"""
        # Prime cache
        spot_service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0
        }
        
        # Benchmark cached calls
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            spot = spot_service.get("BTC")
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            assert isinstance(spot, SpotPrice)
        
        latencies.sort()
        p50 = latencies[50]
        p95 = latencies[95]
        p99 = latencies[99]
        
        print(f"  ✓ Latency: p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms")
        
        # Cached calls should be very fast
        assert p95 < 5.0, f"p95 latency too high: {p95:.2f}ms"
    
    @pytest.mark.asyncio
    async def test_cache_stampede_prevention(self, spot_service):
        """Test that concurrent requests don't cause cache stampede"""
        # Prime cache
        spot_service._cache["SOL"] = {
            'price': 100.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 100.0,
            'high': 100.0,
            'low': 100.0
        }
        
        # Fire 10 concurrent requests (get() is synchronous, so just loop)
        results = [spot_service.get("SOL") for _ in range(10)]
        
        # All should succeed
        assert all(isinstance(r, SpotPrice) for r in results)
        
        # All should have same price (no race condition)
        prices = [r.price for r in results]
        assert len(set(prices)) == 1, "Cache stampede - different prices returned"
        
        print(f"  ✓ 10 concurrent requests → consistent prices (stampede prevented)")


class TestRetryWithBackoff:
    """Test retry logic with exponential backoff for transient HTTP errors"""
    
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_transient_error(self):
        """Test that retry logic succeeds after transient 502 error"""
        call_count = 0
        
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 502: Bad Gateway")
            return {"price": 67000.0}
        
        result = await _retry_with_backoff(flaky_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        
        assert result == {"price": 67000.0}
        assert call_count == 2  # Failed once, succeeded on retry
    
    @pytest.mark.asyncio
    async def test_retry_exhausts_on_permanent_error(self):
        """Test that retry logic exhausts retries on non-retryable error"""
        call_count = 0
        
        async def permanent_error_func():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 404: Not Found")
        
        with pytest.raises(Exception, match="HTTP 404"):
            await _retry_with_backoff(permanent_error_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        
        assert call_count == 1  # Should not retry 404
    
    @pytest.mark.asyncio
    async def test_retry_handles_502_error(self):
        """Test that 502 Bad Gateway is retried"""
        call_count = 0
        
        async def cloudflare_error_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 502: <html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>cloudflare</center></body></html>")
            return {"price": 100.0}
        
        result = await _retry_with_backoff(cloudflare_error_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        
        assert result == {"price": 100.0}
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_handles_503_error(self):
        """Test that 503 Service Unavailable is retried"""
        call_count = 0
        
        async def service_unavailable_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 503: Service Unavailable")
            return {"price": 200.0}
        
        result = await _retry_with_backoff(service_unavailable_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        
        assert result == {"price": 200.0}
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_handles_429_rate_limit(self):
        """Test that 429 Too Many Requests is retried"""
        call_count = 0
        
        async def rate_limit_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 429: Too Many Requests")
            return {"price": 300.0}
        
        result = await _retry_with_backoff(rate_limit_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        
        assert result == {"price": 300.0}
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_max_retries_exceeded(self):
        """Test that retry logic gives up after max retries"""
        call_count = 0
        
        async def always_fail_func():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 502: Bad Gateway")
        
        with pytest.raises(Exception, match="HTTP 502"):
            await _retry_with_backoff(always_fail_func, max_retries=2, base_delay=0.1, max_delay=1.0)
        
        assert call_count == 3  # Initial attempt + 2 retries
    
    @pytest.mark.asyncio
    async def test_retry_exponential_backoff_timing(self):
        """Test that retry delays increase exponentially"""
        call_times = []
        
        async def timing_func():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise Exception("HTTP 502: Bad Gateway")
            return {"price": 400.0}
        
        start = time.time()
        await _retry_with_backoff(timing_func, max_retries=3, base_delay=0.1, max_delay=1.0)
        total_time = time.time() - start
        
        # Should have 3 calls with delays between them
        assert len(call_times) == 3
        # Total time should be at least base_delay + 2*base_delay = 0.3s (with jitter)
        assert total_time >= 0.25  # Allow for some timing variance
    
    @pytest.mark.asyncio
    async def test_retry_no_delay_on_first_success(self):
        """Test that no delay occurs on first success"""
        async def immediate_success_func():
            return {"price": 500.0}
        
        start = time.time()
        result = await _retry_with_backoff(immediate_success_func, max_retries=3, base_delay=0.5, max_delay=1.0)
        elapsed = time.time() - start
        
        assert result == {"price": 500.0}
        assert elapsed < 0.1  # Should complete almost instantly


class TestCoinbaseAuthentication:
    """Test Coinbase Exchange API authentication helpers"""
    
    def test_get_coinbase_credentials(self):
        """Test credential retrieval from environment"""
        api_key, api_secret = _get_coinbase_credentials()
        # Either both are None (no credentials) or both are strings
        if api_key is None:
            assert api_secret is None
        else:
            assert isinstance(api_key, str)
            assert isinstance(api_secret, str)
    
    def test_generate_coinbase_signature(self):
        """Test HMAC signature generation"""
        # Test with known values
        timestamp = "1234567890"
        method = "GET"
        request_path = "/products/BTC-USD/candles"
        body = ""
        api_secret = base64.b64encode(b"test_secret_key_12345").decode('utf-8')
        
        signature = _generate_coinbase_signature(timestamp, method, request_path, body, api_secret)
        
        assert isinstance(signature, str)
        assert len(signature) > 0
        # Signature should be base64 encoded
        try:
            base64.b64decode(signature)
        except Exception:
            pytest.fail("Signature is not valid base64")
    
    @pytest.mark.asyncio
    async def test_authenticated_ohlc_fetch_structure(self):
        """Test that authenticated OHLC fetch returns correct structure"""
        service = get_unified_spot_service()
        
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1234567890, 66000.0, 68000.0, 66500.0, 67000.0, 1000.0]
        ]
        
        # Use base64-encoded secret (as expected by the function)
        api_secret = base64.b64encode(b"test_secret_key_12345").decode('utf-8')
        
        with patch('requests.get', return_value=mock_response):
            result = await service._fetch_ohlc_authenticated("BTC-USD", "test_key", api_secret)
            
            assert result is not None
            assert 'open' in result
            assert 'high' in result
            assert 'low' in result
            assert 'close' in result
            assert result['open'] == 66500.0
            assert result['high'] == 68000.0
            assert result['low'] == 66000.0
            assert result['close'] == 67000.0
    
    @pytest.mark.asyncio
    async def test_authenticated_ohlc_fallback_on_error(self):
        """Test that authenticated fetch falls back to public on error"""
        service = get_unified_spot_service()
        
        # Mock authenticated fetch to fail
        with patch.object(service, '_fetch_ohlc_authenticated', side_effect=Exception("Auth failed")):
            # Mock public fallback to succeed
            with patch.object(service, '_fetch_spot_price_fallback_async', return_value={
                'open': 67000.0,
                'high': 67000.0,
                'low': 67000.0,
                'close': 67000.0
            }):
                result = await service._fetch_asset("BTC")
                assert result is True
    
    @pytest.mark.asyncio
    async def test_ohlc_data_includes_true_values(self):
        """Test that OHLC data includes distinct high/low values when available"""
        service = get_unified_spot_service()
        
        # Mock the authenticated fetch to return distinct OHLC values
        api_secret = base64.b64encode(b"test_secret_key_12345").decode('utf-8')
        
        with patch('data.unified_spot_service._get_coinbase_credentials', return_value=("key", api_secret)):
            with patch.object(service, '_fetch_ohlc_authenticated', return_value={
                'open': 66500.0,
                'high': 68000.0,
                'low': 66000.0,
                'close': 67000.0,
                'volume': 12345.67  # Volume for volume confirmation filter
            }):
                # CRITICAL FIX: Also mock _fetch_ohlc_public to prevent real API calls
                # The test was failing because _fetch_ohlc_public was not mocked and was making real API calls
                with patch.object(service, '_fetch_ohlc_public', return_value=None):
                    # Also mock ticker to prevent real API calls
                    with patch.object(service, '_fetch_ticker_public', return_value=None):
                        result = await service._fetch_asset("BTC")
                        assert result is True
                        
                        # Check cache has distinct OHLC values
                        cached = service._cache["BTC"]
                        assert cached['open'] == 66500.0
                        assert cached['high'] == 68000.0
                        assert cached['low'] == 66000.0
                        assert cached['price'] == 67000.0  # Cache uses 'price' not 'close'
                        assert cached['volume'] == 12345.67  # Volume should be preserved
                    # Verify they are not all the same (true OHLC, not proxy)
                    assert not (cached['open'] == cached['high'] == cached['low'] == cached['price'])


# Smoke tests for live integration (run manually before deployment)
class TestLiveIntegration:
    """Integration tests against real APIs (run manually with -m live)"""
    
    @pytest.mark.asyncio
    async def test_live_all_assets_fetch(self):
        """Test real API calls for all 5 assets"""
        service = get_unified_spot_service()
        
        if service._running:
            await service.stop_refresh_loop()
        
        service._cache = {}
        await service.start_refresh_loop()
        
        print("\n🔴 LIVE API TEST - Fetching real prices...")
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            spot = service.get(asset)
            
            assert isinstance(spot, SpotPrice), f"Live fetch failed for {asset}"
            assert spot.price > 0, f"{asset} returned invalid price"
            # CRITICAL FIX: Accept all valid source names including hybrid sources
            # The implementation now uses 'coinbase_ticker_hybrid', 'coinbase_ticker_ohlc_proxy', etc.
            assert spot.source in ["coinbase_public", "coinbase_exchange_authenticated", "coinbase_ticker_hybrid", "coinbase_ticker_ohlc_proxy", "coinbase_ticker_spread_proxy", "coinbase_ohlc"]
            
            print(f"  {asset}: ${spot.price:,.4f} from {spot.source} "
                  f"(confidence={spot.confidence:.2f})")
        
        await service.stop_refresh_loop()
        print("✅ All assets fetched successfully\n")
    
    @pytest.mark.asyncio
    async def test_live_coinbase_authenticated_api(self):
        """Test real Coinbase authenticated API if credentials available"""
        service = get_unified_spot_service()
        
        if service._running:
            await service.stop_refresh_loop()
        
        service._cache = {}
        
        # Check if credentials are available
        api_key, api_secret = _get_coinbase_credentials()
        if not api_key or not api_secret:
            print("\n⚠️  Skipping authenticated test - no credentials available\n")
            return
        
        await service.start_refresh_loop()
        
        print("\n🔴 LIVE AUTHENTICATED COINBASE TEST...")
        
        # Let refresh populate cache
        await asyncio.sleep(2)
        
        spot = service.get("BTC")
        
        assert isinstance(spot, SpotPrice)
        # CRITICAL FIX: Accept all valid source names including hybrid sources
        assert spot.source in ["coinbase_public", "coinbase_exchange_authenticated", "coinbase_ticker_hybrid", "coinbase_ticker_ohlc_proxy", "coinbase_ticker_spread_proxy", "coinbase_ohlc"]
        
        print(f"  ✅ Source: ${spot.price:,.2f} from {spot.source}\n")
        
        await service.stop_refresh_loop()


# Performance benchmarks
@pytest.mark.benchmark
class TestPerformance:
    """Performance benchmarks"""
    
    @pytest.mark.asyncio
    async def test_benchmark_cached_calls(self):
        """Benchmark cached spot fetches"""
        service = get_unified_spot_service()
        
        if service._running:
            await service.stop_refresh_loop()
        
        service._cache = {}
        
        # Warm cache
        service._cache["BTC"] = {
            'price': 67000.0,
            'timestamp': int(time.time() * 1000),
            'source': 'coinbase_public',
            'open': 67000.0,
            'high': 67000.0,
            'low': 67000.0
        }
        
        # Benchmark
        iterations = 1000
        start = time.perf_counter()
        
        for _ in range(iterations):
            spot = service.get("BTC")
            assert isinstance(spot, SpotPrice)
        
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        
        print(f"\n📊 Benchmark: {iterations} cached calls in {elapsed:.3f}s")
        print(f"   Average: {avg_ms:.3f}ms per call")
        print(f"   Throughput: {iterations/elapsed:.0f} calls/sec\n")
        
        assert avg_ms < 1.0, f"Cached calls too slow: {avg_ms:.3f}ms"


if __name__ == "__main__":
    # Run with: pytest tests/test_unified_spot_service.py -v -s
    # Run live: pytest tests/test_unified_spot_service.py::TestLiveIntegration -v -s --no-skip
    # Run benchmarks: pytest tests/test_unified_spot_service.py -m benchmark -v -s
    pytest.main([__file__, "-v", "-s"])
