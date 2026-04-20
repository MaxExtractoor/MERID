"""Standalone test for ticker validation without full merid imports."""

import sys
import re
from datetime import datetime
from typing import Optional, Tuple, Set, Dict, List
from dataclasses import dataclass

# Copy the relevant code from ticker_utils to test standalone

KALSHI_15M_TICKER_PATTERN = re.compile(
    r'^KX([A-Z]+)15M-(\d{2})([A-Z]{3})(\d{2})(\d{4})$'
)

VALID_15M_MINUTES = {0, 15, 30, 45}

VALID_CRYPTO_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
}


@dataclass
class ParsedKalshiTicker:
    """Parsed components of a Kalshi ticker."""
    asset: str
    day: int
    month: str
    year: int
    hour: int
    minute: int
    is_valid: bool
    error_message: Optional[str] = None


def _parse_kalshi_ticker_loose(ticker: str) -> Optional[ParsedKalshiTicker]:
    """Parse a Kalshi ticker without enforcing 15m boundary constraint."""
    if not ticker:
        return None
    
    match = KALSHI_15M_TICKER_PATTERN.match(ticker.upper())
    if not match:
        return None
    
    asset, day_str, month, year_short, time_str = match.groups()
    
    try:
        day = int(day_str)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        year = 2000 + int(year_short)
    except ValueError:
        return None
    
    valid_months = {'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                   'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'}
    if month not in valid_months:
        return None
    
    return ParsedKalshiTicker(
        asset=asset, day=day, month=month, year=year,
        hour=hour, minute=minute, is_valid=True
    )


def parse_kalshi_ticker(ticker: str) -> Optional[ParsedKalshiTicker]:
    """Parse and validate a Kalshi 15m ticker string (STRICT validation)."""
    if not ticker:
        return None
    
    match = KALSHI_15M_TICKER_PATTERN.match(ticker.upper())
    if not match:
        return None
    
    asset, day_str, month, year_short, time_str = match.groups()
    
    try:
        day = int(day_str)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        year = 2000 + int(year_short)
    except ValueError:
        return None
    
    if asset not in VALID_CRYPTO_ASSETS:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid asset: {asset}"
        )
    
    if minute not in VALID_15M_MINUTES:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid minute {minute}, must be 00, 15, 30, or 45"
        )
    
    if month not in MONTH_MAP:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid month: {month}"
        )
    
    return ParsedKalshiTicker(
        asset=asset, day=day, month=month, year=year,
        hour=hour, minute=minute, is_valid=True
    )


def is_valid_kalshi_ticker(ticker: str, require_cached: bool = False) -> Tuple[bool, Optional[str]]:
    """Validate a Kalshi ticker string."""
    if not ticker:
        return False, "Empty ticker"
    
    parsed = parse_kalshi_ticker(ticker)
    if not parsed:
        return False, "Invalid ticker format"
    
    if not parsed.is_valid:
        return False, parsed.error_message
    
    return True, None


def normalize_ticker_time(ticker: str) -> str:
    """Normalize ticker time to the nearest 15m window floor."""
    parsed = _parse_kalshi_ticker_loose(ticker)
    if not parsed:
        return ticker
    
    floored_minute = (parsed.minute // 15) * 15
    
    new_time = f"{parsed.hour:02d}{floored_minute:02d}"
    normalized = f"KX{parsed.asset}15M-{parsed.day:02d}{parsed.month}{str(parsed.year)[2:]}{new_time}"
    
    if normalized != ticker:
        print(f"  [KALSHI_TICKER_NORMALIZED] {ticker} -> {normalized}")
    
    return normalized


def floor_time_to_15m(dt: datetime) -> datetime:
    """Floor a datetime to the nearest 15-minute boundary."""
    floored_minute = (dt.minute // 15) * 15
    return dt.replace(minute=floored_minute, second=0, microsecond=0)


def format_ticker_for_15m_window(asset: str, window: datetime) -> str:
    """Format a ticker for a specific 15m window."""
    floored = floor_time_to_15m(window)
    day_str = floored.strftime("%d")
    month_str = floored.strftime("%b").upper()
    year_short = floored.strftime("%y")
    time_str = floored.strftime("%H%M")
    return f"KX{asset.upper()}15M-{day_str}{month_str}{year_short}{time_str}"


# Tests
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
        (datetime(2025, 4, 26, 19, 16, 45), 15),
        (datetime(2025, 4, 26, 19, 29, 59), 15),
        (datetime(2025, 4, 26, 19, 31, 0), 30),
        (datetime(2025, 4, 26, 19, 44, 1), 30),
        (datetime(2025, 4, 26, 19, 46, 0), 45),
    ]
    for dt, expected_minute in test_cases:
        floored = floor_time_to_15m(dt)
        print(f"  {dt.strftime('%H:%M:%S')} -> {floored.strftime('%H:%M:%S')}")
        assert floored.minute == expected_minute
    print("  ✓ PASSED\n")


def test_format_ticker():
    """Test formatting tickers for 15m windows."""
    print("Test 5 - Format tickers for 15m windows:")
    window = datetime(2025, 4, 26, 19, 16, 45)
    ticker = format_ticker_for_15m_window("DOGE", window)
    print(f"  Window: {window.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Formatted ticker: {ticker}")
    assert ticker == "KXDOGE15M-26APR251915"
    print("  ✓ PASSED\n")


def test_normalize_ticker():
    """Test normalizing ticker with invalid minute."""
    print("Test 6 - Normalize ticker with invalid minute:")
    test_cases = [
        ("KXDOGE15M-26APR251916", "KXDOGE15M-26APR251915"),  # 16 -> 15
        ("KXDOGE15M-26APR251731", "KXDOGE15M-26APR251730"),  # 31 -> 30
        ("KXDOGE15M-26APR251746", "KXDOGE15M-26APR251745"),  # 46 -> 45
        ("KXDOGE15M-26APR251714", "KXDOGE15M-26APR251715"),  # 14 -> 15
        ("KXDOGE15M-26APR251700", "KXDOGE15M-26APR251700"),  # already valid
    ]
    for input_ticker, expected in test_cases:
        normalized = normalize_ticker_time(input_ticker)
        print(f"  {input_ticker} -> {normalized}")
        assert normalized == expected, f"Expected {expected}, got {normalized}"
    print("  ✓ PASSED\n")


def test_all_crypto_assets():
    """Test all supported crypto assets."""
    print("Test 7 - All supported crypto assets:")
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    for asset in assets:
        ticker = f"KX{asset}15M-26APR251500"
        is_valid, error = is_valid_kalshi_ticker(ticker)
        print(f"  {asset}: {ticker} -> {'✓' if is_valid else '✗'}")
        assert is_valid, f"{asset} should be valid: {error}"
    print("  ✓ PASSED\n")


def test_invalid_minute_rejected():
    """Invalid minute should be rejected by strict validator."""
    print("Test 8 - Invalid minute rejected by strict validator:")
    ticker = "KXDOGE15M-26APR251916"  # 16 is not on 15m boundary
    is_valid, error = is_valid_kalshi_ticker(ticker)
    print(f"  Ticker: {ticker}")
    print(f"  Valid: {is_valid}")
    print(f"  Error: {error}")
    assert not is_valid, f"Expected invalid for minute=16"
    assert "16" in error, f"Error should mention minute 16"
    print("  ✓ PASSED\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Kalshi Ticker Utils - Standalone Tests")
    print("=" * 60 + "\n")
    
    try:
        test_invalid_ticker_with_suffix()
        test_valid_ticker()
        test_parse_valid_ticker()
        test_floor_time()
        test_format_ticker()
        test_normalize_ticker()
        test_all_crypto_assets()
        test_invalid_minute_rejected()
        
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
