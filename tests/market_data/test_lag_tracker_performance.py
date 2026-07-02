"""
Performance sanity checks for LagTracker to ensure memory/CPU usage is bounded.
"""
import pytest
import time
from merid.market_data.lag_tracker import LagTracker, get_lag_tracker


class TestLagTrackerPerformance:
    """Performance sanity checks for LagTracker."""
    
    def setup_method(self):
        """Reset LagTracker singleton for each test."""
        # Clear existing instance
        if hasattr(LagTracker, '_instance'):
            del LagTracker._instance
    
    def test_window_limit_prevents_unbounded_memory(self):
        """Test that window limit prevents unbounded memory growth."""
        tracker = LagTracker()
        
        # Directly test the deque window limit by creating many lag samples
        # This bypasses the move threshold logic to test the window limit itself
        from merid.market_data.lag_tracker import LagSample
        st = tracker._state("BTC")
        
        # Add 10,000 samples directly
        for i in range(10000):
            sample = LagSample(ts_spot=time.time() - i, ts_book=time.time() - i + 0.001)
            st.samples.append(sample)
        
        stats = tracker.get_stats("BTC")
        
        # Should not exceed window size (5000)
        assert stats is not None
        assert stats["count"] <= 5000, f"LagTracker exceeded window size: {stats['count']}"
        assert stats["count"] == 5000, f"LagTracker should have exactly window size: {stats['count']}"
        
    def test_multiple_assets_memory_bounded(self):
        """Test that tracking multiple assets doesn't cause unbounded memory."""
        tracker = LagTracker()
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # Directly test deque window limit for each asset
        from merid.market_data.lag_tracker import LagSample
        for asset in assets:
            st = tracker._state(asset)
            # Add 5000 samples directly
            for i in range(5000):
                sample = LagSample(ts_spot=time.time() - i, ts_book=time.time() - i + 0.001)
                st.samples.append(sample)
        
        # Each asset should be bounded by window size
        for asset in assets:
            stats = tracker.get_stats(asset)
            assert stats is not None
            assert stats["count"] <= 5000, f"{asset} exceeded window size: {stats['count']}"
            assert stats["count"] == 5000, f"{asset} should have exactly window size: {stats['count']}"
        
    def test_cpu_time_reasonable(self):
        """Test that LagTracker operations complete in reasonable time."""
        tracker = LagTracker()
        
        # Simulate 1000 updates
        # Need to make book move in same direction as spot to create lag samples
        start = time.perf_counter()
        for i in range(1000):
            spot_price = 50000.0 + i * 0.01
            tracker.on_spot_update("BTC", time.time() - i, spot_price)
            tracker.on_book_update("BTC", time.time() - i + 0.001, 50 + i * 0.01, 52 + i * 0.01)
        elapsed = time.perf_counter() - start
        
        # Should complete in under 1 second for 1000 updates
        assert elapsed < 1.0, f"LagTracker too slow: {elapsed:.3f}s for 1000 updates"
        
    def test_stats_computation_fast(self):
        """Test that stats computation is fast even with many samples."""
        tracker = LagTracker()
        
        # Populate with max window size
        # Need to make book move in same direction as spot to create lag samples
        for i in range(1000):
            spot_price = 50000.0 + i * 0.01
            tracker.on_spot_update("BTC", time.time() - i, spot_price)
            tracker.on_book_update("BTC", time.time() - i + 0.001, 50 + i * 0.01, 52 + i * 0.01)
        
        # Time stats computation
        start = time.perf_counter()
        for _ in range(100):
            tracker.get_stats("BTC")
        elapsed = time.perf_counter() - start
        
        # 100 stats calls should complete in under 0.1 second
        assert elapsed < 0.1, f"Stats computation too slow: {elapsed:.3f}s for 100 calls"
        
    def test_singleton_get_fast(self):
        """Test that singleton retrieval is fast."""
        start = time.perf_counter()
        for _ in range(1000):
            get_lag_tracker()
        elapsed = time.perf_counter() - start
        
        # 1000 singleton retrievals should be very fast
        assert elapsed < 0.01, f"Singleton retrieval too slow: {elapsed:.3f}s for 1000 calls"
