"""Quick test for ticker validation - can be run directly."""

import sys
sys.path.insert(0, 'c:\\Dev\\MERID')

from merid.event_venues.kalshi.ticker_utils import (
    is_valid_kalshi_ticker,
    parse_kalshi_ticker,
    format_ticker_for_15m_window,
    floor_time_to_15m,
)
from datetime import datetime

def test_invalid_ticker_with_suffix():
    """The malformed ticker from 404 error should be rejected."""
    ticker = "KXDOGE15M-26APR191645-45"
    is_valid, error = is_valid_kalshi_ticker(ticker)
    print(f"Test 1 - Invalid ticker with suffix '{ticker}':")
    print(f"  Valid: {is_valid}")
    print(f"  Error: {error}")
    assert not is_valid, f"Expected invalid, got valid for {ticker}"
    print("  ✓ PASSED\n")

def test_valid_ticker():
    """Valid ticker should pass."""
    ticker = "KXDOGE15M-26APR251915"
    is_valid, error = is_valid_kalshi_ticker(ticker)
    print(f"Test 2 - Valid ticker '{ticker}':")
    print(f"  Valid: {is_valid}")
    print(f"  Error: {error}")
    assert is_valid, f"Expected valid, got invalid: {error}"
    print("  ✓ PASSED\n")

def test_parse_valid_ticker():
    """Parse components of valid ticker."""
    ticker = "KXBTC15M-26MAR251500"
    result = parse_kalshi_ticker(ticker)
    print(f"Test 3 - Parse valid ticker '{ticker}':")
    print(f"  Asset: {result.asset}")
    print(f"  Day: {result.day}")
    print(f"  Month: {result.month}")
    print(f"  Year: {result.year}")
    print(f"  Hour: {result.hour}")
    print(f"  Minute: {result.minute}")
    print(f"  Is Valid: {result.is_valid}")
    assert result.asset == "BTC"
    assert result.minute == 0
    assert result.is_valid
    print("  ✓ PASSED\n")

def test_floor_time():
    """Test time flooring to 15m boundaries."""
    print("Test 4 - Time flooring to 15m boundaries:")
    test_cases = [
        (datetime(2025, 4, 26, 19, 16, 45), 15),  # 19:16:45 -> 19:15
        (datetime(2025, 4, 26, 19, 29, 59), 15),  # 19:29:59 -> 19:15
        (datetime(2025, 4, 26, 19, 31, 0), 30),   # 19:31:00 -> 19:30
        (datetime(2025, 4, 26, 19, 44, 1), 30),   # 19:44:01 -> 19:30
        (datetime(2025, 4, 26, 19, 46, 0), 45),   # 19:46:00 -> 19:45
    ]
    for dt, expected_minute in test_cases:
        floored = floor_time_to_15m(dt)
        print(f"  {dt.strftime('%H:%M:%S')} -> {floored.strftime('%H:%M:%S')}")
        assert floored.minute == expected_minute, f"Expected {expected_minute}, got {floored.minute}"
    print("  ✓ PASSED\n")

def test_format_ticker():
    """Test formatting tickers for 15m windows."""
    print("Test 5 - Format tickers for 15m windows:")
    window = datetime(2025, 4, 26, 19, 16, 45)  # Should floor to 19:15
    ticker = format_ticker_for_15m_window("DOGE", window)
    print(f"  Window: {window.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Formatted ticker: {ticker}")
    assert ticker == "KXDOGE15M-26APR251915"
    print("  ✓ PASSED\n")

def test_all_crypto_assets():
    """Test all supported crypto assets."""
    print("Test 6 - All supported crypto assets:")
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    for asset in assets:
        ticker = f"KX{asset}15M-26APR251500"
        is_valid, error = is_valid_kalshi_ticker(ticker)
        print(f"  {asset}: {ticker} -> {'✓' if is_valid else '✗'}")
        assert is_valid, f"{asset} should be valid: {error}"
    print("  ✓ PASSED\n")

if __name__ == "__main__":
    print("=" * 60)
    print("Kalshi Ticker Utils - Quick Tests")
    print("=" * 60 + "\n")
    
    try:
        test_invalid_ticker_with_suffix()
        test_valid_ticker()
        test_parse_valid_ticker()
        test_floor_time()
        test_format_ticker()
        test_all_crypto_assets()
        
        print("=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
