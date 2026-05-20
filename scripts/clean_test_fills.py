#!/usr/bin/env python3
"""
Clean test fills from production database.

This script removes test market fills from the kalshi_fills.db database.
Test tickers are identified by patterns like:
- Contains "TEST" or "KXTEST"
- Short codes like "KX-SK", "KX-DUP", "KX-TK"
- Timeframe-based test tickers like "KXBTC-15M", "KXETH-15M"

Usage:
    python scripts/clean_test_fills.py --dry-run  # Preview what would be deleted
    python scripts/clean_test_fills.py            # Actually delete
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Test ticker patterns
TEST_PATTERNS = [
    "TEST",
    "KXTEST",
    "KX-SK",
    "KX-DUP",
    "KX-TK",
    "KXBTC-15M",
    "KXETH-15M",
]


def is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test market ticker."""
    if not ticker:
        return False
    
    ticker_upper = ticker.upper()
    
    # Explicit test markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True
    
    # Short codes (test development tickers)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True
    
    # Timeframe-based tickers for crypto (may be test-related)
    if ticker_upper.startswith(("KXBTC-", "KXETH-", "KXSOL-", "KXXRP-", "KXDOGE-")):
        parts = ticker_upper.split("-")
        if len(parts) >= 2:
            last_part = parts[-1]
            # Check for timeframe suffixes that indicate test markets
            if last_part in ("15M", "1H", "H", "D", "W", "M", "A"):
                return True
    
    return False


def clean_test_fills(db_path: str, dry_run: bool = True) -> dict:
    """Clean test fills from database.
    
    Args:
        db_path: Path to kalshi_fills.db
        dry_run: If True, only report what would be deleted
        
    Returns:
        Dict with cleanup results
    """
    if not Path(db_path).exists():
        return {"error": f"Database not found: {db_path}"}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all test tickers
    cursor.execute("SELECT DISTINCT market_ticker FROM kalshi_fills")
    all_tickers = [row[0] for row in cursor.fetchall()]
    test_tickers = [t for t in all_tickers if is_test_ticker(t)]
    
    if not test_tickers:
        conn.close()
        return {
            "test_tickers_found": 0,
            "fills_to_delete": 0,
            "test_tickers": []
        }
    
    # Count fills to delete
    placeholders = ",".join("?" * len(test_tickers))
    cursor.execute(
        f"SELECT COUNT(*) FROM kalshi_fills WHERE market_ticker IN ({placeholders})",
        test_tickers
    )
    fills_count = cursor.fetchone()[0]
    
    # Get sample fill IDs for reporting
    cursor.execute(
        f"SELECT fill_id, market_ticker FROM kalshi_fills WHERE market_ticker IN ({placeholders}) LIMIT 10",
        test_tickers
    )
    sample_fills = cursor.fetchall()
    
    result = {
        "test_tickers_found": len(test_tickers),
        "fills_to_delete": fills_count,
        "test_tickers": test_tickers,
        "sample_fills": sample_fills
    }
    
    if not dry_run:
        # Delete the fills
        cursor.execute(
            f"DELETE FROM kalshi_fills WHERE market_ticker IN ({placeholders})",
            test_tickers
        )
        conn.commit()
        result["deleted"] = True
    else:
        result["deleted"] = False
    
    conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Clean test fills from production database")
    parser.add_argument(
        "--db-path",
        default="data/kalshi_fills.db",
        help="Path to kalshi_fills.db (default: data/kalshi_fills.db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    args = parser.parse_args()
    
    result = clean_test_fills(args.db_path, dry_run=True)
    
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"Test Fill Cleanup Report")
    print(f"{'='*60}")
    print(f"Database: {args.db_path}")
    print(f"Test tickers found: {result['test_tickers_found']}")
    print(f"Fills to delete: {result['fills_to_delete']}")
    print(f"\nTest tickers:")
    for ticker in result['test_tickers']:
        print(f"  - {ticker}")
    
    if result['sample_fills']:
        print(f"\nSample fills (first 10):")
        for fill_id, ticker in result['sample_fills']:
            print(f"  - {fill_id} ({ticker})")
    
    print(f"{'='*60}\n")
    
    if args.dry_run:
        print("DRY RUN - No changes made. Use --force to actually delete.")
        sys.exit(0)
    
    if not args.force:
        response = input(f"Delete {result['fills_to_delete']} test fills? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)
    
    # Actually delete
    result = clean_test_fills(args.db_path, dry_run=False)
    print(f"Deleted {result['fills_to_delete']} test fills from database.")
    sys.exit(0)


if __name__ == "__main__":
    main()
