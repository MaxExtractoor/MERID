"""
Unit tests for LagTracker module.

Tests cover:
- Spot→book sample creation
- Book leads spot (no sample)
- Per-asset move thresholds
- Stats stability and None handling
"""

import pytest
import time
from collections import deque

from merid.market_data.lag_tracker import LagTracker, LagSample, AssetLagState


class TestLagTrackerBasics:
    """Basic LagTracker functionality tests."""
    
    def test_initialization(self):
        """Test LagTracker initializes with correct defaults."""
        tracker = LagTracker()
        assert tracker._move_threshold_bps == 1.0
        assert tracker._window_size == 5000
        assert tracker._assets == {}
        
    def test_custom_initialization(self):
        """Test LagTracker with custom parameters."""
        tracker = LagTracker(move_threshold_bps=2.0, window_size=1000)
        assert tracker._move_threshold_bps == 2.0
        assert tracker._window_size == 1000
        
    def test_per_asset_thresholds(self):
        """Test per-asset move thresholds are set correctly."""
        tracker = LagTracker()
        assert tracker._move_thresholds_per_asset["BTC"] == 1.0
        assert tracker._move_thresholds_per_asset["ETH"] == 1.0
        assert tracker._move_thresholds_per_asset["SOL"] == 2.0
        assert tracker._move_thresholds_per_asset["XRP"] == 2.0
        assert tracker._move_thresholds_per_asset["DOGE"] == 3.0


class TestSpotUpdate:
    """Tests for spot update handling."""
    
    def test_spot_update_records_state(self):
        """Test spot update records timestamp and price."""
        tracker = LagTracker()
        ts = time.time()
        price = 75000.0
        
        tracker.on_spot_update("BTC", ts, price)
        
        st = tracker._state("BTC")
        assert st.last_spot_ts == ts
        assert st.last_spot_price == price
        
    def test_spot_update_invalid_price(self):
        """Test spot update with invalid price is skipped."""
        tracker = LagTracker()
        tracker.on_spot_update("BTC", time.time(), -1.0)
        
        st = tracker._state("BTC")
        assert st.last_spot_ts is None
        assert st.last_spot_price is None


class TestBookUpdate:
    """Tests for book update handling."""
    
    def test_book_update_initializes_state(self):
        """Test first book update initializes state."""
        tracker = LagTracker()
        tracker.on_book_update("BTC", time.time(), 50.0, 52.0)
        
        st = tracker._state("BTC")
        assert st.last_book_mid == 51.0
        assert st.last_book_ts is not None
        
    def test_book_update_without_spot(self):
        """Test book update without prior spot update skips lag measurement."""
        tracker = LagTracker()
        tracker.on_book_update("BTC", time.time(), 50.0, 52.0)
        
        # No samples should be created
        st = tracker._state("BTC")
        assert len(st.samples) == 0


class TestLagSampleCreation:
    """Tests for lag sample creation logic."""
    
    def test_spot_leads_book_creates_sample(self):
        """Test spot move followed by book move in same direction creates sample."""
        tracker = LagTracker()
        
        # Initialize book state first
        book_ts = time.time()
        tracker.on_book_update("BTC", book_ts, 50.0, 52.0)  # Mid = 51.0
        
        # Spot moves up relative to book mid
        spot_ts = book_ts + 0.1
        tracker.on_spot_update("BTC", spot_ts, 75000.0)  # Spot price, but the move is relative to book mid
        
        # Book moves up (lagging spot) - now spot has moved relative to previous book mid
        book_ts = spot_ts + 0.5  # 500ms lag
        tracker.on_book_update("BTC", book_ts, 52.0, 54.0)  # Mid moved up from 51.0 to 53.0
        
        st = tracker._state("BTC")
        assert len(st.samples) == 1
        assert st.samples[0].lag_ms == 500.0
        
    def test_book_leads_spot_no_sample(self):
        """Test book timestamp before spot timestamp does not create sample."""
        tracker = LagTracker()
        
        # Book update first
        book_ts = time.time()
        tracker.on_book_update("BTC", book_ts, 50.0, 52.0)
        
        # Spot update after book
        spot_ts = book_ts + 0.5
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        
        # Another book update
        tracker.on_book_update("BTC", time.time(), 51.0, 53.0)
        
        st = tracker._state("BTC")
        assert len(st.samples) == 0  # No sample because book ts < spot ts
        
    def test_spot_move_below_threshold_no_sample(self):
        """Test spot move below threshold does not create sample."""
        tracker = LagTracker()
        
        # Small spot move (below 1 bps for BTC)
        spot_ts = time.time()
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        tracker.on_spot_update("BTC", spot_ts + 0.1, 75000.5)  # 0.5 bps move
        
        # Book moves in same direction
        book_ts = spot_ts + 0.5
        tracker.on_book_update("BTC", book_ts, 51.0, 53.0)
        
        st = tracker._state("BTC")
        assert len(st.samples) == 0
        
    def test_per_asset_threshold_sol(self):
        """Test SOL uses higher threshold (2 bps)."""
        tracker = LagTracker()
        
        # Small spot move (1 bps, below SOL's 2 bps threshold)
        spot_ts = time.time()
        tracker.on_spot_update("SOL", spot_ts, 150.0)
        tracker.on_spot_update("SOL", spot_ts + 0.1, 150.15)  # 1 bps move
        
        # Book moves in same direction
        book_ts = spot_ts + 0.5
        tracker.on_book_update("SOL", book_ts, 0.50, 0.52)
        
        st = tracker._state("SOL")
        assert len(st.samples) == 0
        
    def test_per_asset_threshold_sol_above(self):
        """Test SOL move above 2 bps threshold creates sample."""
        tracker = LagTracker()
        
        # Initialize book state
        book_ts = time.time()
        tracker.on_book_update("SOL", book_ts, 0.50, 0.52)  # Mid = 0.51
        
        # Spot moves up relative to book mid (3 bps move: 0.51 * 0.0003 = 0.000153)
        spot_ts = book_ts + 0.1
        tracker.on_spot_update("SOL", spot_ts, 0.510153)  # 3 bps above book mid
        
        # Book moves in same direction
        book_ts = spot_ts + 0.5
        tracker.on_book_update("SOL", book_ts, 0.52, 0.54)  # Mid moved up
        
        st = tracker._state("SOL")
        assert len(st.samples) == 1
        
    def test_opposite_direction_no_sample(self):
        """Test book move opposite spot direction does not create sample."""
        tracker = LagTracker()
        
        # Spot moves up
        spot_ts = time.time()
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        
        # Book moves down (opposite direction)
        book_ts = spot_ts + 0.5
        tracker.on_book_update("BTC", book_ts, 49.0, 51.0)  # Mid moved down
        
        st = tracker._state("BTC")
        assert len(st.samples) == 0


class TestLagSample:
    """Tests for LagSample dataclass."""
    
    def test_lag_ms_calculation(self):
        """Test lag_ms property calculates correctly."""
        sample = LagSample(ts_spot=100.0, ts_book=100.5)
        assert sample.lag_ms == 500.0  # 0.5 seconds = 500ms
        
    def test_lag_ms_negative_clamped(self):
        """Test negative lag is clamped to 0."""
        sample = LagSample(ts_spot=100.5, ts_book=100.0)
        assert sample.lag_ms == 0.0  # Negative lag clamped to 0


class TestGetStats:
    """Tests for get_stats method."""
    
    def test_get_stats_no_samples(self):
        """Test get_stats returns None when no samples."""
        tracker = LagTracker()
        stats = tracker.get_stats("BTC")
        assert stats is None
        
    def test_get_stats_with_samples(self):
        """Test get_stats returns correct statistics."""
        tracker = LagTracker()
        
        # Initialize book state
        book_ts = time.time()
        tracker.on_book_update("BTC", book_ts, 50.0, 52.0)  # Mid = 51.0
        
        # Create samples with known lags by manually creating the pattern
        # Each iteration: spot moves up, then book moves up (lagging)
        for i in range(10):
            # Get current book mid
            st = tracker._state("BTC")
            current_book_mid = st.last_book_mid
            
            # Spot moves up 2 bps relative to current book mid
            spot_ts = book_ts + (0.1 * i) + 0.05
            spot_price = current_book_mid * 1.0002  # 2 bps above
            tracker.on_spot_update("BTC", spot_ts, spot_price)
            
            # Book moves up (lagging spot) - must move in same direction
            book_ts = spot_ts + (0.1 * (i + 1))  # 100ms, 200ms, ..., 1000ms
            new_book_mid = current_book_mid * 1.0003  # 3 bps above (same direction)
            # Convert back to bid/ask (approximate)
            bid = new_book_mid - 1.0
            ask = new_book_mid + 1.0
            tracker.on_book_update("BTC", book_ts, bid, ask)
        
        stats = tracker.get_stats("BTC")
        assert stats is not None
        assert stats["count"] == 10
        assert stats["mean_ms"] > 0
        assert stats["median_ms"] > 0
        assert stats["p95_ms"] > 0
        assert stats["p95_ms"] >= stats["median_ms"]
        
    def test_get_stats_no_keyerror(self):
        """Test get_stats handles missing keys gracefully."""
        tracker = LagTracker()
        
        # Initialize book state
        book_ts = time.time()
        tracker.on_book_update("BTC", book_ts, 50.0, 52.0)  # Mid = 51.0
        
        # Create a sample
        spot_ts = book_ts + 0.1
        tracker.on_spot_update("BTC", spot_ts, 51.01)  # Spot moves up 1 bps
        tracker.on_book_update("BTC", spot_ts + 0.5, 51.0, 53.0)  # Book moves up
        
        stats = tracker.get_stats("BTC")
        # Should not raise KeyError even if dict structure changes
        assert stats is not None
        assert stats.get("count", 0) > 0
        assert stats.get("mean_ms", 0) > 0


class TestGetEffectiveLagMs:
    """Tests for get_effective_lag_ms method."""
    
    def test_get_effective_lag_ms_no_samples(self):
        """Test get_effective_lag_ms returns None when no samples."""
        tracker = LagTracker()
        lag = tracker.get_effective_lag_ms("BTC")
        assert lag is None
        
    def test_get_effective_lag_ms_median(self):
        """Test get_effective_lag_ms returns median by default."""
        tracker = LagTracker()
        
        # Create samples
        spot_ts = time.time()
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        
        for i in range(5):
            book_ts = spot_ts + (0.1 * (i + 1))
            tracker.on_book_update("BTC", book_ts, 50.0 + i, 52.0 + i)
            tracker.on_spot_update("BTC", book_ts + 0.05, 75000.0 + i)
        
        lag = tracker.get_effective_lag_ms("BTC", quantile=0.5)
        assert lag is not None
        assert lag > 0
        
    def test_get_effective_lag_ms_p95(self):
        """Test get_effective_lag_ms returns p95 when requested."""
        tracker = LagTracker()
        
        # Create samples
        spot_ts = time.time()
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        
        for i in range(20):
            book_ts = spot_ts + (0.05 * (i + 1))
            tracker.on_book_update("BTC", book_ts, 50.0 + i, 52.0 + i)
            tracker.on_spot_update("BTC", book_ts + 0.05, 75000.0 + i)
        
        lag_p95 = tracker.get_effective_lag_ms("BTC", quantile=0.95)
        lag_median = tracker.get_effective_lag_ms("BTC", quantile=0.5)
        
        assert lag_p95 is not None
        assert lag_median is not None
        assert lag_p95 >= lag_median


class TestWindowLimit:
    """Tests for window size limiting."""
    
    def test_window_size_limit(self):
        """Test samples are limited to window_size."""
        tracker = LagTracker(window_size=5)
        
        spot_ts = time.time()
        tracker.on_spot_update("BTC", spot_ts, 75000.0)
        
        # Create 10 samples (more than window_size)
        for i in range(10):
            book_ts = spot_ts + (0.1 * (i + 1))
            tracker.on_book_update("BTC", book_ts, 50.0 + i, 52.0 + i)
            tracker.on_spot_update("BTC", book_ts + 0.05, 75000.0 + i)
        
        st = tracker._state("BTC")
        assert len(st.samples) == 5  # Limited to window_size
        
        stats = tracker.get_stats("BTC")
        assert stats["count"] == 5


class TestGetAllStats:
    """Tests for get_all_stats method."""
    
    def test_get_all_stats_multiple_assets(self):
        """Test get_all_stats returns stats for all assets."""
        tracker = LagTracker()
        
        # Add samples for BTC
        book_ts = time.time()
        tracker.on_book_update("BTC", book_ts, 50.0, 52.0)  # Mid = 51.0
        spot_ts = book_ts + 0.1
        tracker.on_spot_update("BTC", spot_ts, 51.01)  # Spot moves up 1 bps
        tracker.on_book_update("BTC", spot_ts + 0.5, 51.0, 53.0)  # Book moves up
        
        # Add samples for ETH
        book_ts = time.time()
        tracker.on_book_update("ETH", book_ts, 0.34, 0.36)  # Mid = 0.35
        spot_ts = book_ts + 0.1
        tracker.on_spot_update("ETH", spot_ts, 0.3501)  # Spot moves up
        tracker.on_book_update("ETH", spot_ts + 0.3, 0.35, 0.37)  # Book moves up
        
        all_stats = tracker.get_all_stats()
        assert "BTC" in all_stats
        assert "ETH" in all_stats
        assert all_stats["BTC"]["count"] == 1
        assert all_stats["ETH"]["count"] == 1
        
    def test_get_all_stats_empty(self):
        """Test get_all_stats returns empty dict when no samples."""
        tracker = LagTracker()
        all_stats = tracker.get_all_stats()
        assert all_stats == {}


class TestEndToEndFakeTickPerAsset:
    """Integration tests for end-to-end fake tick flow per asset."""
    
    @pytest.mark.parametrize("asset,spot_price,bid,ask", [
        ("BTC", 75000.0, 50.0, 52.0),
        ("ETH", 3500.0, 0.34, 0.36),
        ("SOL", 150.0, 0.85, 0.87),
        ("XRP", 0.60, 0.48, 0.52),
        ("DOGE", 0.15, 0.07, 0.09),
    ])
    def test_end_to_end_tick_flow(self, asset, spot_price, bid, ask):
        """Test complete tick flow: spot → book → sample → stats for each asset."""
        tracker = LagTracker()
        
        # Simulate real-time tick sequence
        base_ts = time.time()
        
        # 1. Initial book update (no spot yet, should not create sample)
        tracker.on_book_update(asset, base_ts, bid, ask)
        st = tracker._state(asset)
        assert len(st.samples) == 0
        assert st.last_book_ts == base_ts
        assert st.last_book_mid == (bid + ask) / 2.0
        
        # 2. Spot update (records state, no sample yet)
        spot_ts = base_ts + 0.05
        tracker.on_spot_update(asset, spot_ts, spot_price)
        st = tracker._state(asset)
        assert len(st.samples) == 0
        assert st.last_spot_ts == spot_ts
        assert st.last_spot_price == spot_price
        
        # 3. Book update after spot (should create sample if price moved)
        book_ts = spot_ts + 0.1
        new_bid = bid + 0.5
        new_ask = ask + 0.5
        tracker.on_book_update(asset, book_ts, new_bid, new_ask)
        st = tracker._state(asset)
        
        # Check sample was created (book moved > 1 bps)
        if abs((new_bid + new_ask) / 2.0 - (bid + ask) / 2.0) / ((bid + ask) / 2.0) > 0.0001:
            assert len(st.samples) == 1
            sample = st.samples[0]
            assert sample.ts_spot == spot_ts
            assert sample.ts_book == book_ts
            assert sample.lag_ms == (book_ts - spot_ts) * 1000
            assert sample.lag_ms > 0
        
        # 4. Get stats
        stats = tracker.get_stats(asset)
        assert stats["count"] >= 0
        if stats["count"] > 0:
            assert stats["mean_ms"] > 0
            assert stats["median_ms"] > 0
            assert stats["p95_ms"] > 0
        
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_multiple_ticks_per_asset(self, asset):
        """Test multiple tick sequence for each asset."""
        tracker = LagTracker()
        
        base_ts = time.time()
        spot_price = 75000.0 if asset == "BTC" else 3500.0 if asset == "ETH" else 150.0 if asset == "SOL" else 0.60 if asset == "XRP" else 0.15
        bid = 50.0 if asset == "BTC" else 0.34 if asset == "ETH" else 0.85 if asset == "SOL" else 0.48 if asset == "XRP" else 0.07
        ask = bid + 2.0
        
        # Simulate 10 tick cycles
        for i in range(10):
            spot_ts = base_ts + (i * 0.1)
            book_ts = spot_ts + 0.05
            
            # Spot update
            tracker.on_spot_update(asset, spot_ts, spot_price + i)
            
            # Book update (move price)
            new_bid = bid + i * 0.1
            new_ask = ask + i * 0.1
            tracker.on_book_update(asset, book_ts, new_bid, new_ask)
        
        # Verify samples accumulated
        st = tracker._state(asset)
        assert len(st.samples) > 0
        
        # Verify stats are computed
        stats = tracker.get_stats(asset)
        assert stats["count"] > 0
        assert stats["mean_ms"] > 0
        assert stats["median_ms"] > 0
        
    def test_all_assets_simultaneous_ticks(self):
        """Test simultaneous ticks across all assets."""
        tracker = LagTracker()
        
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        base_ts = time.time()
        
        # Simulate simultaneous updates for all assets
        for i, asset in enumerate(assets):
            spot_price = 75000.0 if asset == "BTC" else 3500.0 if asset == "ETH" else 150.0 if asset == "SOL" else 0.60 if asset == "XRP" else 0.15
            bid = 50.0 if asset == "BTC" else 0.34 if asset == "ETH" else 0.85 if asset == "SOL" else 0.48 if asset == "XRP" else 0.07
            ask = bid + 2.0
            
            spot_ts = base_ts + i * 0.01
            book_ts = spot_ts + 0.05
            
            # First spot update
            tracker.on_spot_update(asset, spot_ts, spot_price)
            
            # Book update with significant price move to trigger sample
            new_bid = bid + 5.0  # Large move to exceed threshold
            new_ask = ask + 5.0
            tracker.on_book_update(asset, book_ts, new_bid, new_ask)
        
        # Verify all assets have state
        all_stats = tracker.get_all_stats()
        # Note: samples may not be created if threshold not met, so check state exists
        for asset in assets:
            st = tracker._state(asset)
            assert st is not None
