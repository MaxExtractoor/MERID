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
    """Tests for get_spot_max_age_seconds with timing-aware thresholds"""
    
    def test_btc_timing_buckets(self):
        """Test BTC timing-aware thresholds match design"""
        # < 2 min to expiry: ≤ 5s
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=0.5) == 5.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=1.0) == 5.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=1.9) == 5.0
        
        # 2-5 min to expiry: ≤ 10s
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=2.0) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=3.0) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=4.5) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=4.9) == 10.0
        
        # 5-10 min to expiry: ≤ 15s
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=5.0) == 15.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=7.0) == 15.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=9.5) == 15.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=9.9) == 15.0
        
        # >= 10 min to expiry: base threshold (60s for BTC)
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=12.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=15.0) == 60.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=30.0) == 60.0
    
    def test_eth_timing_buckets(self):
        """Test ETH timing-aware thresholds"""
        # ETH should have same timing buckets as BTC
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=1.0) == 5.0
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=3.0) == 10.0
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=7.0) == 15.0
        assert get_spot_max_age_seconds('ETH', minutes_to_expiry=15.0) == 60.0
    
    def test_sol_timing_buckets(self):
        """Test SOL timing-aware thresholds"""
        assert get_spot_max_age_seconds('SOL', minutes_to_expiry=1.0) == 5.0
        assert get_spot_max_age_seconds('SOL', minutes_to_expiry=3.0) == 10.0
        assert get_spot_max_age_seconds('SOL', minutes_to_expiry=7.0) == 15.0
        # SOL may have different base threshold
        sol_base = get_spot_max_age_seconds('SOL', minutes_to_expiry=15.0)
        assert sol_base >= 15.0
    
    def test_xrp_timing_buckets(self):
        """Test XRP timing-aware thresholds"""
        assert get_spot_max_age_seconds('XRP', minutes_to_expiry=1.0) == 5.0
        assert get_spot_max_age_seconds('XRP', minutes_to_expiry=3.0) == 10.0
        assert get_spot_max_age_seconds('XRP', minutes_to_expiry=7.0) == 15.0
    
    def test_doge_timing_buckets(self):
        """Test DOGE timing-aware thresholds"""
        assert get_spot_max_age_seconds('DOGE', minutes_to_expiry=1.0) == 5.0
        assert get_spot_max_age_seconds('DOGE', minutes_to_expiry=3.0) == 10.0
        assert get_spot_max_age_seconds('DOGE', minutes_to_expiry=7.0) == 15.0
    
    def test_no_minutes_to_expiry_uses_base_threshold(self):
        """Test that None minutes_to_expiry uses base threshold"""
        btc_with_none = get_spot_max_age_seconds('BTC', minutes_to_expiry=None)
        btc_with_10min = get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0)
        assert btc_with_none == btc_with_10min
    
    def test_boundary_conditions(self):
        """Test boundary conditions between timing buckets"""
        # Exactly at boundaries
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=2.0) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=5.0) == 15.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=10.0) == 60.0
        
        # Just below boundaries
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=1.99) == 5.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=4.99) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=9.99) == 15.0
        
        # Just above boundaries
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=2.01) == 10.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=5.01) == 15.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=10.01) == 60.0
    
    def test_negative_minutes_to_expiry(self):
        """Test handling of negative minutes_to_expiry (already expired)"""
        # Should treat as < 2 min bucket (most strict)
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=-1.0) == 5.0
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=-10.0) == 5.0
    
    def test_zero_minutes_to_expiry(self):
        """Test handling of zero minutes_to_expiry (at expiry)"""
        # Should treat as < 2 min bucket (most strict)
        assert get_spot_max_age_seconds('BTC', minutes_to_expiry=0.0) == 5.0


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
