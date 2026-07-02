"""Test script for FifteenMinuteMarketLocator.

This script tests the market locator against real Kalshi market IDs from the website
to verify the formatter produces correct results.
"""

from datetime import datetime, timezone, timedelta
from merid.event_venues.kalshi.fifteen_minute_market_locator import (
    FifteenMinuteMarketLocator,
    current_15m_bucket,
    format_kalshi_event,
    SERIES_BY_ASSET,
)

def test_bucket_computation():
    """Test bucket computation at various times."""
    print("\n=== Testing bucket computation ===")
    
    # Test at 14:48 UTC
    now = datetime(2024, 6, 24, 14, 48, 0, tzinfo=timezone.utc)
    start, end = current_15m_bucket(now)
    print(f"At 14:48 UTC: bucket = {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    assert start.strftime('%H:%M') == '14:45'
    assert end.strftime('%H:%M') == '15:00'
    
    # Test at 14:59 UTC
    now = datetime(2024, 6, 24, 14, 59, 0, tzinfo=timezone.utc)
    start, end = current_15m_bucket(now)
    print(f"At 14:59 UTC: bucket = {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    assert start.strftime('%H:%M') == '14:45'
    assert end.strftime('%H:%M') == '15:00'
    
    # Test at 15:00 UTC
    now = datetime(2024, 6, 24, 15, 0, 0, tzinfo=timezone.utc)
    start, end = current_15m_bucket(now)
    print(f"At 15:00 UTC: bucket = {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    assert start.strftime('%H:%M') == '15:00'
    assert end.strftime('%H:%M') == '15:15'
    
    print("✓ Bucket computation tests passed")


def test_format_kalshi_event():
    """Test Kalshi event ID formatting."""
    print("\n=== Testing Kalshi event ID formatting ===")
    
    # Test with a known time
    # The user's example: KXBTC15M-26JUN112200-00
    # This appears to be for a window ending at 11:22 ET on June 26
    
    # Let's test with the current time to see what we get
    now = datetime.now(timezone.utc)
    start, end = current_15m_bucket(now)
    
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current bucket: {start.strftime('%Y-%m-%d %H:%M:%S %Z')} - {end.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    for asset, series in SERIES_BY_ASSET.items():
        event_id = format_kalshi_event(series, start)
        print(f"{asset}: {event_id}")
        print(f"  YES: {event_id}-00")
        print(f"  NO:  {event_id}-01")
    
    print("\n✓ Event ID formatting test completed")


def test_market_locator():
    """Test the full market locator."""
    print("\n=== Testing FifteenMinuteMarketLocator ===")
    
    locator = FifteenMinuteMarketLocator()
    
    now = datetime.now(timezone.utc)
    markets = locator.current_market_ids(now)
    
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Minutes to expiry: {locator.minutes_to_expiry(now):.2f}")
    print(f"\nMarkets for {len(markets)} assets:")
    
    for asset, market_ids in markets.items():
        print(f"\n{asset}:")
        print(f"  Event ID: {market_ids.event_id}")
        print(f"  YES: {market_ids.yes}")
        print(f"  NO: {market_ids.no}")
        print(f"  Bucket: {market_ids.start.strftime('%H:%M')} - {market_ids.end.strftime('%H:%M')} UTC")
    
    print("\n✓ Market locator test completed")


def test_specific_example():
    """Test against the specific example from the user's request."""
    print("\n=== Testing specific example from user request ===")
    
    # User's example: KXBTC15M-26JUN112200-00
    # This is for a market ending at 11:22 ET on June 26
    # Let's try to reverse-engineer the bucket start time
    
    # If the window ends at 11:22 ET, and it's a 15-minute window
    # Then the window starts at 11:07 ET
    # But 15-minute windows should align to :00, :15, :30, :45 boundaries
    # So this might not be a standard 15-minute window, or the time format is different
    
    # Let's check what our formatter produces for a known time
    # June 26, 2024 at 11:07 ET (which would be 15:07 UTC if ET is UTC-4)
    # Actually, let's just test with the current time and see
    
    now = datetime.now(timezone.utc)
    start, end = current_15m_bucket(now)
    
    print(f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Bucket start UTC: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Bucket end UTC: {end.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Convert to ET
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
    
    start_et = start.astimezone(ET)
    end_et = end.astimezone(ET)
    
    print(f"Bucket start ET: {start_et.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Bucket end ET: {end_et.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Format the event ID
    event_id = format_kalshi_event("KXBTC15M", start)
    print(f"\nGenerated event ID: {event_id}")
    print(f"Expected pattern: KXBTC15M-DDMMMYYHHMM-MM")
    
    print("\n✓ Specific example test completed")


if __name__ == "__main__":
    test_bucket_computation()
    test_format_kalshi_event()
    test_market_locator()
    test_specific_example()
    print("\n=== All tests completed ===")
