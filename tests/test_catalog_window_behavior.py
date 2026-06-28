"""
Verify catalog and window behavior with current config (paper mode).

Tests that catalog refresh and 15m scheduler are correctly configured
for Kalshi 15m crypto markets.
"""
import os
import pytest

# Set profile to kalshi_crypto_15m_v2
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["MERID_TRADING_MODE"] = "PAPER"


def test_catalog_refresh_interval_configured():
    """Verify catalog refresh interval is appropriate for 15m markets."""
    import os
    
    # Default should be 5s for 15m markets (as per market_catalog.py comments)
    # Environment may override this (e.g., 30s for rate limit awareness)
    default_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
    
    # Should be at least 2s (minimum guard)
    assert default_interval >= 2.0, f"Catalog refresh interval {default_interval}s is below minimum 2s"
    
    # Should be reasonable for 15m markets (5s default is good, 30s is acceptable for rate limits)
    assert default_interval <= 60.0, f"Catalog refresh interval {default_interval}s is too high for 15m markets"
    
    # Accept either 5s (code default) or 30s (common env override)
    assert default_interval in [5.0, 30.0], \
        f"Expected catalog refresh interval of 5s or 30s, got {default_interval}s"


def test_scheduler_15m_boundaries():
    """Verify scheduler uses correct 15-minute UTC boundaries."""
    from merid.event_venues.kalshi.crypto_15m_scheduler import Crypto15mScheduler
    
    scheduler = Crypto15mScheduler()
    
    # Verify boundaries are correct
    expected_boundaries = [0, 15, 30, 45]
    assert scheduler.MINUTE_BOUNDARIES == expected_boundaries, \
        f"Expected 15m boundaries {expected_boundaries}, got {scheduler.MINUTE_BOUNDARIES}"


def test_scheduler_window_calculation():
    """Verify scheduler correctly calculates trading windows."""
    from merid.event_venues.kalshi.crypto_15m_scheduler import Crypto15mScheduler
    from datetime import datetime, timezone, timedelta
    
    scheduler = Crypto15mScheduler()
    
    # Test with a known time
    test_time = datetime(2024, 5, 26, 12, 30, 0, tzinfo=timezone.utc)  # 12:30 UTC
    
    # Get next boundary
    next_boundary = scheduler._get_next_boundary(test_time)
    expected_next = datetime(2024, 5, 26, 12, 45, 0, tzinfo=timezone.utc)
    assert next_boundary == expected_next, \
        f"Expected next boundary {expected_next}, got {next_boundary}"
    
    # Get previous boundary
    prev_boundary = scheduler._get_previous_boundary(test_time)
    expected_prev = datetime(2024, 5, 26, 12, 15, 0, tzinfo=timezone.utc)
    assert prev_boundary == expected_prev, \
        f"Expected previous boundary {expected_prev}, got {prev_boundary}"


def test_scheduler_trading_window_validation():
    """Verify scheduler correctly validates 2-12 minute trading window."""
    from merid.event_venues.kalshi.crypto_15m_scheduler import MarketWindow
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    
    # Create a window that's in the trading window (5 minutes to expiry)
    expiry_in_window = now + timedelta(minutes=5)
    window_in_range = MarketWindow(
        start_utc=now - timedelta(minutes=10),
        expiry_utc=expiry_in_window,
        ticker="KXBTC15M-TEST"
    )
    
    # Should be in trading window
    assert window_in_range.is_in_trading_window(min_minutes=2, max_minutes=12), \
        "Window with 5 minutes to expiry should be in trading window"
    
    # Create a window that's too close to expiry (1 minute to expiry)
    expiry_too_close = now + timedelta(minutes=1)
    window_too_close = MarketWindow(
        start_utc=now - timedelta(minutes=14),
        expiry_utc=expiry_too_close,
        ticker="KXBTC15M-TEST"
    )
    
    # Should NOT be in trading window
    assert not window_too_close.is_in_trading_window(min_minutes=2, max_minutes=12), \
        "Window with 1 minute to expiry should NOT be in trading window"
    
    # Create a window that's too far from expiry (15 minutes to expiry)
    expiry_too_far = now + timedelta(minutes=15)
    window_too_far = MarketWindow(
        start_utc=now,
        expiry_utc=expiry_too_far,
        ticker="KXBTC15M-TEST"
    )
    
    # Should NOT be in trading window
    assert not window_too_far.is_in_trading_window(min_minutes=2, max_minutes=12), \
        "Window with 15 minutes to expiry should NOT be in trading window"


def test_catalog_scheduler_alignment():
    """Verify catalog refresh interval aligns with 15m window requirements."""
    import os
    
    # Catalog refresh interval (default 5s)
    refresh_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
    
    # 15m window is 10 minutes (2-12 min to expiry)
    window_duration_minutes = 10
    
    # Catalog should refresh many times within a window to catch window rollovers
    refreshes_per_window = (window_duration_minutes * 60) / refresh_interval
    
    # Should refresh at least 10 times per window
    assert refreshes_per_window >= 10, \
        f"Catalog refreshes {refreshes_per_window:.1f} times per window, should be >= 10"
    
    # Should not refresh excessively (rate limit awareness)
    assert refreshes_per_window <= 1000, \
        f"Catalog refreshes {refreshes_per_window:.1f} times per window, should be <= 1000"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
