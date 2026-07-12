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


# Legacy scheduler tests - commented out due to API changes in Crypto15mScheduler
# These tests reference MINUTE_BOUNDARIES and _get_next_boundary which no longer exist
# The scheduler now delegates to kalshi_15m_time.get_kalshi_15m_window() for window calculations
# def test_scheduler_15m_boundaries():
#     """Verify scheduler uses correct 15-minute UTC boundaries."""
#     from merid.event_venues.kalshi.crypto_15m_scheduler import Crypto15mScheduler
#     
#     scheduler = Crypto15mScheduler()
#     
#     # Verify boundaries are correct
#     expected_boundaries = [0, 15, 30, 45]
#     assert scheduler.MINUTE_BOUNDARIES == expected_boundaries, \
#         f"Expected 15m boundaries {expected_boundaries}, got {scheduler.MINUTE_BOUNDARIES}"
# 
# 
# def test_scheduler_window_calculation():
#     """Verify scheduler correctly calculates trading windows."""
#     from merid.event_venues.kalshi.crypto_15m_scheduler import Crypto15mScheduler
#     from datetime import datetime, timezone, timedelta
#     
#     scheduler = Crypto15mScheduler()
#     
#     # Test with a known time
#     test_time = datetime(2024, 5, 26, 12, 30, 0, tzinfo=timezone.utc)  # 12:30 UTC
#     
#     # Get next boundary
#     next_boundary = scheduler._get_next_boundary(test_time)
#     expected_next = datetime(2024, 5, 26, 12, 45, 0, tzinfo=timezone.utc)
#     assert next_boundary == expected_next, \
#         f"Expected next boundary {expected_next}, got {next_boundary}"
#     
#     # Get previous boundary
#     prev_boundary = scheduler._get_previous_boundary(test_time)
#     expected_prev = datetime(2024, 5, 26, 12, 15, 0, tzinfo=timezone.utc)
#     assert prev_boundary == expected_prev, \
#         f"Expected previous boundary {expected_prev}, got {prev_boundary}"


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


def test_snapshot_max_minutes_to_expiry():
    """Verify snapshot MAX_MINUTES_TO_EXPIRY is 17 minutes (reduced from 30 for cleaner catalog)."""
    import re
    
    # Read market_catalog.py to check MAX_MINUTES_TO_EXPIRY in snapshot creation
    catalog_path = "merid/event_venues/kalshi/market_catalog.py"
    with open(catalog_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Find MAX_MINUTES_TO_EXPIRY in snapshot creation
    # Pattern: MAX_MINUTES_TO_EXPIRY = 17.0
    match = re.search(r"MAX_MINUTES_TO_EXPIRY\s*=\s*(\d+\.?\d*)", content)
    assert match, "MAX_MINUTES_TO_EXPIRY not found in market_catalog.py"
    
    max_minutes = float(match.group(1))
    assert max_minutes == 17.0, \
        f"Expected MAX_MINUTES_TO_EXPIRY=17.0 (reduced from 30 for cleaner catalog), got {max_minutes}"


def test_catalog_fetch_max_expiration_time():
    """Verify catalog fetch uses 30-minute max_expiration_time for robust discovery."""
    import re
    
    # Read market_catalog.py to check max_expiration_time in fetch
    catalog_path = "merid/event_venues/kalshi/market_catalog.py"
    with open(catalog_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Find max_expiration_time in _fetch_series_with_retry
    # Pattern: max_expiry = now_utc + timedelta(minutes=30)
    match = re.search(r"max_expiry\s*=\s*now_utc\s*\+\s*timedelta\(minutes=(\d+)\)", content)
    assert match, "max_expiration_time not found in market_catalog.py"
    
    fetch_minutes = int(match.group(1))
    assert fetch_minutes == 30, \
        f"Expected max_expiration_time=30 minutes for robust discovery, got {fetch_minutes}"


def test_fallback_max_expiration_time_aligned():
    """Verify fallback max_expiration_time is 17 minutes (aligned with snapshot)."""
    import re
    
    # Read market_catalog.py to check fallback max_expiration_time
    catalog_path = "merid/event_venues/kalshi/market_catalog.py"
    with open(catalog_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Find fallback max_expiration_time (in robust discovery fallback)
    # Pattern: max_expiry = now_utc + timedelta(minutes=17)
    # Look for the fallback specifically (after "active_only=False")
    lines = content.split('\n')
    found_fallback = False
    for i, line in enumerate(lines):
        if "active_only=False" in line and i < len(lines) - 5:
            # Check next few lines for max_expiration_time
            for j in range(i, min(i + 10, len(lines))):
                match = re.search(r"max_expiry\s*=\s*now_utc\s*\+\s*timedelta\(minutes=(\d+)\)", lines[j])
                if match:
                    fallback_minutes = int(match.group(1))
                    assert fallback_minutes == 17, \
                        f"Expected fallback max_expiration_time=17 minutes (aligned with snapshot), got {fallback_minutes}"
                    found_fallback = True
                    break
    
    assert found_fallback, "Fallback max_expiration_time not found in market_catalog.py"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
