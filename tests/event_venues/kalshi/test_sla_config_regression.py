"""
Regression tests for SLA config timing-aware thresholds.

Tests for:
1. Timing-aware spot SLA thresholds
2. SLA function behavior with minutes_to_expiry
3. Edge cases and boundary conditions

Run with: pytest tests/event_venues/kalshi/test_sla_config_regression.py -v
"""
import pytest
from merid.event_venues.kalshi.sla_config import (
    get_spot_max_age_seconds, get_spot_status, get_spot_sla,
    SpotSLA, SPOT_SLAS
)


class TestSpotMaxAgeSeconds:
    """Tests for get_spot_max_age_seconds with single hard threshold"""
    
    def test_single_threshold_for_all_assets(self):
        """Test that all assets use the same 60s threshold (new design)"""
        # New design: single hard threshold (60s) for all assets
        # minutes_to_expiry is now unused (spot is reference anchor, not primary trading venue)
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=0.5) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=1.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=15.0) == 60.0
        
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=1.0) == 60.0
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=10.0) == 60.0
        
        assert get_spot_max_age_seconds('SOL', minutes_to_expiry=1.0) == 60.0
        assert get_spot_max_age_seconds('SOL', minutes_to_expiry=10.0) == 60.0
        
        assert get_spot_max_age_seconds('XRP', minutes_to_expiry=1.0) == 60.0
        assert get_spot_max_age_seconds('XRP', minutes_to_expiry=10.0) == 60.0
        
        assert get_spot_max_age_seconds('DOGE', minutes_to_expiry=1.0) == 60.0
        assert get_spot_max_age_seconds('DOGE', minutes_to_expiry=10.0) == 60.0
    
    def test_no_minutes_to_expiry_uses_base_threshold(self):
        """Test that None minutes_to_expiry uses base threshold"""
        btc_with_none = get_spot_max_age_seconds('BTC', minutes_to_expiry=None)
        btc_with_10min = get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0)
        assert btc_with_none == btc_with_10min == 60.0
    
    def test_boundary_conditions(self):
        """Test boundary conditions (all return 60s in new design)"""
        # All return 60s regardless of minutes_to_expiry
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=0.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=2.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=5.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=15.0) == 60.0
    
    def test_negative_minutes_to_expiry(self):
        """Test handling of negative minutes_to_expiry (already expired)"""
        # Still returns 60s (single threshold)
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=-1.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=-10.0) == 60.0


class TestSpotStatus:
    """Tests for get_spot_status function"""
    
    def test_spot_status_ok(self):
        """Test OK status for fresh data"""
        # BTC: OK ≤ 5s
        assert get_spot_status('BTC', 4000) == 'ok'
        assert get_spot_status('BTC', 5000) == 'ok'
        
        # ETH: OK ≤ 5s
        assert get_spot_status('ETH', 3000) == 'ok'
    
    def test_spot_status_stale(self):
        """Test stale status for moderately old data"""
        # BTC: warn ≤ 30s
        assert get_spot_status('BTC', 10000) == 'stale'
        assert get_spot_status('BTC', 30000) == 'stale'
        
        # ETH: warn ≤ 30s
        assert get_spot_status('ETH', 15000) == 'stale'
    
    def test_spot_status_bad(self):
        """Test bad status for very old data"""
        # BTC: block > 60s
        assert get_spot_status('BTC', 61000) == 'bad'
        assert get_spot_status('BTC', 120000) == 'bad'
        
        # ETH: block > 60s
        assert get_spot_status('ETH', 65000) == 'bad'
    
    def test_spot_status_boundary_conditions(self):
        """Test boundary conditions for status transitions"""
        # BTC boundaries (5s OK, 30s stale, 60s bad)
        assert get_spot_status('BTC', 5000) == 'ok'
        assert get_spot_status('BTC', 5001) == 'stale'
        assert get_spot_status('BTC', 30000) == 'stale'
        assert get_spot_status('BTC', 30001) == 'bad'
        assert get_spot_status('BTC', 60000) == 'bad'


class TestSpotSLA:
    """Tests for SpotSLA dataclass and get_spot_sla"""
    
    def test_get_spot_sla_returns_valid_sla(self):
        """Test that get_spot_sla returns valid SpotSLA objects"""
        btc_sla = get_spot_sla('BTC')
        assert isinstance(btc_sla, SpotSLA)
        assert btc_sla.ok_threshold_ms > 0
        assert btc_sla.warn_threshold_ms > btc_sla.ok_threshold_ms
        assert btc_sla.block_threshold_ms > btc_sla.warn_threshold_ms
    
    def test_get_spot_sla_defaults_to_btc(self):
        """Test that unknown assets default to BTC SLA"""
        unknown_sla = get_spot_sla('UNKNOWN')
        btc_sla = get_spot_sla('BTC')
        assert unknown_sla.ok_threshold_ms == btc_sla.ok_threshold_ms
        assert unknown_sla.warn_threshold_ms == btc_sla.warn_threshold_ms
        assert unknown_sla.block_threshold_ms == btc_sla.block_threshold_ms
    
    def test_spot_sla_get_status(self):
        """Test SpotSLA.get_status method"""
        btc_sla = get_spot_sla('BTC')
        
        # OK range
        assert btc_sla.get_status(btc_sla.ok_threshold_ms) == 'ok'
        assert btc_sla.get_status(btc_sla.ok_threshold_ms - 1) == 'ok'
        
        # Stale range
        assert btc_sla.get_status(btc_sla.warn_threshold_ms) == 'stale'
        assert btc_sla.get_status(btc_sla.ok_threshold_ms + 1) == 'stale'
        
        # Bad range
        assert btc_sla.get_status(btc_sla.block_threshold_ms) == 'bad'
        assert btc_sla.get_status(btc_sla.warn_threshold_ms + 1) == 'bad'
    
    def test_all_supported_assets_have_sla(self):
        """Test that all supported assets have SLA definitions"""
        supported_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        
        for asset in supported_assets:
            sla = get_spot_sla(asset)
            assert sla.ok_threshold_ms > 0
            assert sla.warn_threshold_ms > sla.ok_threshold_ms
            assert sla.block_threshold_ms > sla.warn_threshold_ms


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
