"""
Unit tests for spot SLA configuration and UnifiedSpotService contract.

Tests cover:
- Centralized SLA config per asset
- SpotPrice vs SpotError returns
- Fresh vs stale vs degraded thresholds
- SOL-specific edge cases (longer timeout)
- Structured error reasons
"""

import pytest
import time
from dataclasses import dataclass
from typing import Literal, Optional

from data.spot_sla_config import SpotSLA, get_spot_sla, get_spot_status, SPOT_SLA


class TestSpotSLAConfig:
    """Test centralized SLA configuration."""
    
    def test_sla_config_exists_for_all_assets(self):
        """Verify SLA config exists for all supported assets."""
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        actual_assets = set(SPOT_SLA.keys())
        assert actual_assets == expected_assets
    
    def test_btc_sla_thresholds(self):
        """Test BTC SLA has correct thresholds."""
        sla = get_spot_sla("BTC")
        assert sla.asset == "BTC"
        assert sla.fresh_s == 5.0
        assert sla.stale_s == 10.0
        assert sla.degrade_s == 10.0
    
    def test_eth_sla_thresholds(self):
        """Test ETH SLA has correct thresholds."""
        sla = get_spot_sla("ETH")
        assert sla.asset == "ETH"
        assert sla.fresh_s == 5.0
        assert sla.stale_s == 10.0
        assert sla.degrade_s == 10.0
    
    def test_sol_sla_thresholds(self):
        """Test SOL SLA has higher thresholds (20s degrade)."""
        sla = get_spot_sla("SOL")
        assert sla.asset == "SOL"
        assert sla.fresh_s == 10.0
        assert sla.stale_s == 20.0
        assert sla.degrade_s == 20.0
    
    def test_xrp_sla_thresholds(self):
        """Test XRP SLA has correct thresholds."""
        sla = get_spot_sla("XRP")
        assert sla.asset == "XRP"
        assert sla.fresh_s == 5.0
        assert sla.stale_s == 10.0
        assert sla.degrade_s == 10.0
    
    def test_doge_sla_thresholds(self):
        """Test DOGE SLA has correct thresholds."""
        sla = get_spot_sla("DOGE")
        assert sla.asset == "DOGE"
        assert sla.fresh_s == 5.0
        assert sla.stale_s == 10.0
        assert sla.degrade_s == 10.0
    
    def test_get_spot_sla_defaults_to_btc(self):
        """Test unknown asset defaults to BTC SLA."""
        sla = get_spot_sla("UNKNOWN")
        assert sla.asset == "BTC"
    
    def test_get_spot_status_fresh(self):
        """Test fresh status when age < fresh threshold."""
        status = get_spot_status("BTC", 3.0)
        assert status == "fresh"
    
    def test_get_spot_status_stale(self):
        """Test stale status when age between fresh and stale thresholds."""
        status = get_spot_status("BTC", 7.0)
        assert status == "stale"
    
    def test_get_spot_status_degraded(self):
        """Test degraded status when age >= degrade threshold."""
        status = get_spot_status("BTC", 10.0)
        assert status == "degraded"
    
    def test_sol_fresh_threshold(self):
        """Test SOL has higher fresh threshold."""
        status = get_spot_status("SOL", 8.0)
        assert status == "fresh"  # 8s < 10s fresh threshold
    
    def test_sol_degraded_threshold(self):
        """Test SOL degrades at 20s."""
        status = get_spot_status("SOL", 20.0)
        assert status == "degraded"
    
    def test_negative_age_returns_degraded(self):
        """Test negative age returns degraded."""
        status = get_spot_status("BTC", -1.0)
        assert status == "degraded"


class TestSpotSLADataclass:
    """Test SpotSLA dataclass methods."""
    
    def test_get_status_method_fresh(self):
        """Test SpotSLA.get_status returns fresh for fresh age."""
        sla = SpotSLA(asset="BTC", fresh_s=5.0, stale_s=10.0, degrade_s=10.0)
        status = sla.get_status(3.0)
        assert status == "fresh"
    
    def test_get_status_method_stale(self):
        """Test SpotSLA.get_status returns stale for stale age."""
        sla = SpotSLA(asset="BTC", fresh_s=5.0, stale_s=10.0, degrade_s=10.0)
        status = sla.get_status(7.0)
        assert status == "stale"
    
    def test_get_status_method_degraded(self):
        """Test SpotSLA.get_status returns degraded for degraded age."""
        sla = SpotSLA(asset="BTC", fresh_s=5.0, stale_s=10.0, degrade_s=10.0)
        status = sla.get_status(10.0)
        assert status == "degraded"
    
    def test_get_status_method_zero_age(self):
        """Test SpotSLA.get_status returns fresh for zero age."""
        sla = SpotSLA(asset="BTC", fresh_s=5.0, stale_s=10.0, degrade_s=10.0)
        status = sla.get_status(0.0)
        assert status == "fresh"


class TestSpotErrorHandling:
    """Test SpotError structured error handling."""
    
    def test_spot_error_no_data_reason(self):
        """Test SpotError with no_data reason."""
        from data.unified_spot_service import SpotError
        error = SpotError(reason="no_data", asset="BTC")
        assert error.reason == "no_data"
        assert error.asset == "BTC"
        assert error.age_s is None
    
    def test_spot_error_stale_reason(self):
        """Test SpotError with stale reason includes age."""
        from data.unified_spot_service import SpotError
        error = SpotError(reason="stale", asset="BTC", age_s=7.5)
        assert error.reason == "stale"
        assert error.asset == "BTC"
        assert error.age_s == 7.5
    
    def test_spot_error_timeout_reason(self):
        """Test SpotError with timeout reason."""
        from data.unified_spot_service import SpotError
        error = SpotError(reason="timeout", asset="ETH")
        assert error.reason == "timeout"
        assert error.asset == "ETH"
    
    def test_spot_error_rate_limited_reason(self):
        """Test SpotError with rate_limited reason."""
        from data.unified_spot_service import SpotError
        error = SpotError(reason="rate_limited", asset="SOL")
        assert error.reason == "rate_limited"
        assert error.asset == "SOL"
    
    def test_spot_error_no_provider_reason(self):
        """Test SpotError with no_provider reason."""
        from data.unified_spot_service import SpotError
        error = SpotError(reason="no_provider", asset="XRP")
        assert error.reason == "no_provider"
        assert error.asset == "XRP"
    
    def test_spot_error_message(self):
        """Test SpotError message field."""
        from data.unified_spot_service import SpotError
        error = SpotError(
            reason="stale",
            asset="BTC",
            age_s=7.5,
            message="Spot data age 7.5s exceeds degrade threshold 5.0s"
        )
        assert "7.5s" in error.message
        assert "5.0s" in error.message


class TestSpotPriceDataclass:
    """Test SpotPrice dataclass."""
    
    def test_spot_price_fields(self):
        """Test SpotPrice has required fields."""
        from data.unified_spot_service import SpotPrice
        spot = SpotPrice(price=50000.0, timestamp=1234567890, source="coinbase")
        assert spot.price == 50000.0
        assert spot.timestamp == 1234567890
        assert spot.source == "coinbase"
        assert spot.confidence == 1.0  # default value
    
    def test_spot_price_source_coinbase(self):
        """Test SpotPrice source is coinbase (Coinbase-only)."""
        from data.unified_spot_service import SpotPrice
        spot = SpotPrice(price=50000.0, timestamp=1234567890, source="coinbase")
        assert spot.source == "coinbase"
    
    def test_spot_price_confidence_default(self):
        """Test SpotPrice confidence defaults to 1.0."""
        from data.unified_spot_service import SpotPrice
        spot = SpotPrice(price=50000.0, timestamp=1234567890, source="coinbase")
        assert spot.confidence == 1.0


class TestSpotServiceContract:
    """Test UnifiedSpotService contract with centralized SLA."""
    
    @pytest.fixture
    def spot_service(self):
        """Create a mock spot service for testing."""
        from data.unified_spot_service import UnifiedSpotService
        service = UnifiedSpotService()
        # Pre-populate cache with fresh data
        with service._cache_lock:
            now_ms = int(time.time() * 1000)
            for asset in service.SUPPORTED_ASSETS:
                service._cache[asset] = {
                    'price': 50000.0 if asset == 'BTC' else 3000.0,
                    'timestamp': now_ms,
                    'source': 'coinbase'
                }
                service._asset_success_ts[asset] = time.time()
        return service
    
    def test_get_returns_spotprice_for_fresh_data(self, spot_service):
        """Test get() returns SpotPrice for fresh data."""
        result = spot_service.get("BTC")
        assert not isinstance(result, type(None))
        # Should be SpotPrice, not SpotError
        from data.unified_spot_service import SpotError
        assert not isinstance(result, SpotError)
        assert result.price > 0
        assert result.timestamp > 0
        assert result.source == "coinbase"
    
    def test_get_returns_spoterror_for_stale_data(self, spot_service):
        """Test get() returns SpotError for stale data."""
        # Simulate stale data by setting old timestamp
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 20) * 1000)  # 20 seconds ago
            spot_service._cache["BTC"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["BTC"] = time.time() - 20
        
        result = spot_service.get("BTC")
        from data.unified_spot_service import SpotError
        assert isinstance(result, SpotError)
        assert result.reason == "stale"
        assert result.asset == "BTC"
        assert result.age_s is not None
        assert result.age_s > 5.0  # Should exceed 5s degrade threshold
    
    def test_get_returns_spoterror_for_no_data(self, spot_service):
        """Test get() returns SpotError for missing data."""
        # Remove data from cache
        with spot_service._cache_lock:
            spot_service._cache.pop("BTC", None)
        
        result = spot_service.get("BTC")
        from data.unified_spot_service import SpotError
        assert isinstance(result, SpotError)
        assert result.reason == "no_data"
        assert result.asset == "BTC"
    
    def test_sol_has_higher_degrade_threshold(self, spot_service):
        """Test SOL degrades at 10s, not 5s."""
        # Set SOL data to 8 seconds old (should still be fresh for SOL)
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 8) * 1000)
            spot_service._cache["SOL"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["SOL"] = time.time() - 8
        
        result = spot_service.get("SOL")
        from data.unified_spot_service import SpotError
        # Should not be degraded (8s < 10s threshold)
        assert not isinstance(result, SpotError)
    
    def test_sol_degrades_at_20s(self, spot_service):
        """Test SOL degrades at 20s threshold."""
        # Set SOL data to 22 seconds old (should be degraded)
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 22) * 1000)
            spot_service._cache["SOL"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["SOL"] = time.time() - 22
        
        result = spot_service.get("SOL")
        from data.unified_spot_service import SpotError
        assert isinstance(result, SpotError)
        assert result.reason == "stale"
        assert result.asset == "SOL"
    
    def test_btc_degrades_at_10s(self, spot_service):
        """Test BTC degrades at 10s threshold."""
        # Set BTC data to 12 seconds old (should be degraded)
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 12) * 1000)
            spot_service._cache["BTC"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["BTC"] = time.time() - 12
        
        result = spot_service.get("BTC")
        from data.unified_spot_service import SpotError
        assert isinstance(result, SpotError)
        assert result.reason == "stale"
        assert result.asset == "BTC"
    
    def test_get_all_excludes_degraded_assets(self, spot_service):
        """Test get_all() excludes degraded assets."""
        # Make BTC degraded (need > 10s for new threshold)
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 12) * 1000)
            spot_service._cache["BTC"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["BTC"] = time.time() - 12
        
        result = spot_service.get_all()
        # BTC should not be in result (degraded)
        assert "BTC" not in result
        # Other assets should be present
        assert "ETH" in result
        assert "SOL" in result
    
    def test_health_check_uses_centralized_sla(self, spot_service):
        """Test health_check() uses centralized SLA config."""
        health = spot_service.health_check()
        
        # Check that health check includes SLA thresholds
        for asset in spot_service.SUPPORTED_ASSETS:
            assert asset in health["cache_status"]
            cache_status = health["cache_status"][asset]
            if cache_status["cached"]:
                assert "sla_degrade_s" in cache_status
                # Verify threshold matches centralized config
                sla = get_spot_sla(asset)
                assert cache_status["sla_degrade_s"] == sla.degrade_s
    
    def test_health_check_includes_degraded_count(self, spot_service):
        """Test health_check() includes degraded_count."""
        # Make BTC degraded (need > 10s for new threshold)
        with spot_service._cache_lock:
            old_timestamp = int((time.time() - 12) * 1000)
            spot_service._cache["BTC"]['timestamp'] = old_timestamp
            spot_service._asset_success_ts["BTC"] = time.time() - 12
        
        health = spot_service.health_check()
        assert "degraded_count" in health
        assert health["degraded_count"] >= 1  # At least BTC is degraded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
