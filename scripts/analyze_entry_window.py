#!/usr/bin/env python3
"""
Entry Window Backtesting Script

Analyzes historical fills and signals by minutes_to_expiry buckets to validate
entry window settings and identify asset-specific optimal windows.

Usage:
    python scripts/analyze_entry_window.py --db data/kalshi_fills.db --days 30
"""

import argparse
import sqlite3
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional
import json
from pathlib import Path

# PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (entry window analysis not needed for sealed 15m profile)
_profile = os.getenv("MERID_PROFILE", "").lower()
if _profile == "kalshi_crypto_15m_v2":
    print("ERROR: Entry window analysis is disabled for kalshi_crypto_15m_v2 profile.")
    print("The 15m profile uses a sealed product surface with fixed entry windows from profile config.")
    exit(1)


def parse_asset_from_ticker(ticker: str) -> str:
    """Extract asset (BTC/ETH/SOL/XRP/DOGE) from Kalshi ticker."""
    ticker_upper = ticker.upper()
    if ticker_upper.startswith("KXBTC"):
        return "BTC"
    elif ticker_upper.startswith("KXETH"):
        return "ETH"
    elif ticker_upper.startswith("KXSOL"):
        return "SOL"
    elif ticker_upper.startswith("KXXRP"):
        return "XRP"
    elif ticker_upper.startswith("KXDOGE"):
        return "DOGE"
    return "UNKNOWN"


def is_15m_ticker(ticker: str) -> bool:
    """Check if ticker is a 15m crypto market."""
    ticker_upper = ticker.upper()
    # KXBTC15M-... or KXBTC-15M-... pattern
    return "-15M" in ticker_upper or ticker_upper.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"))


def parse_expiry_from_ticker(ticker: str) -> Optional[datetime]:
    """Parse expiry from Kalshi ticker format.
    
    Kalshi ticker format: KXBTC15M-26MAY102115-15
    - 26MAY = May 26, 2026
    - 102115 = 10:21:15 UTC time
    """
    try:
        # Extract the date-time part after the first hyphen
        parts = ticker.split('-')
        if len(parts) < 2:
            return None
        
        datetime_part = parts[1]  # e.g., "26MAY102115"
        
        # Parse format: DDMMMHHMMSS
        if len(datetime_part) < 9:
            return None
        
        day = int(datetime_part[0:2])
        month_str = datetime_part[2:5].upper()
        time_str = datetime_part[5:]  # HHMMSS
        
        # Map month abbreviations
        months = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        
        month = months.get(month_str)
        if month is None:
            return None
        
        # Parse time
        if len(time_str) >= 6:
            hour = int(time_str[0:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6]) if len(time_str) >= 6 else 0
        else:
            return None
        
        # Assume current year (Kalshi markets are typically current year)
        year = datetime.now().year
        
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except Exception as e:
        print(f"WARNING: Failed to parse expiry from ticker {ticker}: {e}")
        return None


def analyze_fills(db_path: str, days: int = 30) -> dict:
    """
    Analyze fills from kalshi_fills.db by minutes_to_expiry buckets.
    
    Returns:
        Dict with bucketed statistics per asset
    """
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        return {}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check table structure
    cursor.execute("PRAGMA table_info(kalshi_fills)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    print(f"Database columns: {list(columns.keys())}")
    
    # Check if we have end_date or expiry information
    has_end_date = "end_date" in columns or "expiry" in columns
    
    cutoff = datetime.now() - timedelta(days=days)
    
    # Query fills
    if has_end_date:
        query = """
            SELECT 
                market_ticker,
                side,
                action,
                count_fp,
                yes_price_dollars,
                no_price_dollars,
                fee_cost,
                created_time,
                end_date
            FROM kalshi_fills
            WHERE created_time >= ?
            ORDER BY created_time DESC
        """
        cursor.execute(query, (cutoff.isoformat(),))
        fills = cursor.fetchall()
    else:
        print("No end_date in fills table - will parse expiry from ticker format")
        query = """
            SELECT 
                market_ticker,
                side,
                action,
                count_fp,
                yes_price_dollars,
                no_price_dollars,
                fee_cost,
                created_time
            FROM kalshi_fills
            WHERE created_time >= ?
            ORDER BY created_time DESC
        """
        cursor.execute(query, (cutoff.isoformat(),))
        fills_raw = cursor.fetchall()
        
        # Enrich with expiry from ticker format
        fills = []
        for fill in fills_raw:
            ticker, side, action, count, yes_price, no_price, fee, created_ts = fill
            expiry = parse_expiry_from_ticker(ticker)
            fills.append((ticker, side, action, count, yes_price, no_price, fee, created_ts, expiry))
    
    print(f"Found {len(fills)} fills in last {days} days")
    
    # Bucket by asset and minutes_to_expiry
    # Buckets: 0-2, 2-4, 4-6, 6-8, 8-10, 10+ minutes
    buckets = {
        "0-2": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
        "2-4": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
        "4-6": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
        "6-8": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
        "8-10": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
        "10+": defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "total_fees": 0.0}),
    }
    
    for fill in fills:
        ticker, side, action, count, yes_price, no_price, fee, created_ts, end_date = fill
        
        # Filter for 15m crypto markets
        if not is_15m_ticker(ticker):
            continue
        
        asset = parse_asset_from_ticker(ticker)
        if asset == "UNKNOWN":
            continue
        
        # Calculate minutes_to_expiry
        try:
            # Handle created_time
            if created_ts is None:
                continue
            if isinstance(created_ts, str):
                created_dt = datetime.fromisoformat(created_ts.replace("Z", "+00:00"))
            elif isinstance(created_ts, (int, float)):
                created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
            else:
                created_dt = created_ts  # Assume it's already a datetime
            
            # Handle end_date
            if end_date is None:
                continue
            if isinstance(end_date, str):
                expiry_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            elif isinstance(end_date, (int, float)):
                expiry_dt = datetime.fromtimestamp(end_date, tz=timezone.utc)
            else:
                expiry_dt = end_date  # Assume it's already a datetime
            
            minutes_to_expiry = (expiry_dt - created_dt).total_seconds() / 60.0
        except Exception as e:
            print(f"WARNING: Failed to parse dates for {ticker} (created={created_ts}, end={end_date}): {e}")
            continue
        
        # Determine bucket
        if minutes_to_expiry < 0:
            continue  # Skip expired fills
        elif minutes_to_expiry <= 2:
            bucket = "0-2"
        elif minutes_to_expiry <= 4:
            bucket = "2-4"
        elif minutes_to_expiry <= 6:
            bucket = "4-6"
        elif minutes_to_expiry <= 8:
            bucket = "6-8"
        elif minutes_to_expiry <= 10:
            bucket = "8-10"
        else:
            bucket = "10+"
        
        # Calculate PnL (simplified - just price * count - fee)
        price = yes_price if side == "yes" else no_price
        if price is None:
            continue
        
        pnl = (price * count) - (fee if fee else 0)
        
        buckets[bucket][asset]["count"] += 1
        buckets[bucket][asset]["total_pnl"] += pnl
        buckets[bucket][asset]["total_fees"] += fee if fee else 0
    
    conn.close()
    
    # Calculate averages
    results = {}
    for bucket, asset_data in buckets.items():
        results[bucket] = {}
        for asset, stats in asset_data.items():
            if stats["count"] > 0:
                results[bucket][asset] = {
                    "count": stats["count"],
                    "avg_pnl_per_trade": stats["total_pnl"] / stats["count"],
                    "total_pnl": stats["total_pnl"],
                    "total_fees": stats["total_fees"],
                }
    
    return results


def print_results(results: dict):
    """Print analysis results in a readable format."""
    print("\n" + "="*80)
    print("ENTRY WINDOW BACKTESTING RESULTS")
    print("="*80)
    
    for bucket in ["0-2", "2-4", "4-6", "6-8", "8-10", "10+"]:
        print(f"\nBucket: {bucket} minutes to expiry")
        print("-" * 80)
        
        if not results.get(bucket):
            print("  No data")
            continue
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if asset in results[bucket]:
                stats = results[bucket][asset]
                print(f"  {asset:4s}: {stats['count']:4d} trades | "
                      f"Avg PnL: ${stats['avg_pnl_per_trade']:7.2f} | "
                      f"Total PnL: ${stats['total_pnl']:8.2f}")
            else:
                print(f"  {asset:4s}: No data")


def main():
    parser = argparse.ArgumentParser(description="Analyze entry window performance")
    parser.add_argument("--db", type=str, default="data/kalshi_fills.db",
                        help="Path to kalshi_fills.db")
    parser.add_argument("--days", type=int, default=30,
                        help="Number of days to analyze (default: 30)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    
    args = parser.parse_args()
    
    results = analyze_fills(args.db, args.days)
    
    if results:
        print_results(results)
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
