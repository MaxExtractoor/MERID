#!/usr/bin/env python3
"""
Pull Kalshi Trade History

This script fetches trade/fill history from Kalshi and outputs it in various formats.
It can filter by time range, asset, and export to CSV or JSON.

Usage:
    python scripts/pull_kalshi_trade_history.py --days 7 --format csv
    python scripts/pull_kalshi_trade_history.py --start "2026-07-01" --end "2026-07-03" --format json
    python scripts/pull_kalshi_trade_history.py --asset BTC --days 1
"""

import asyncio
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("scripts.pull_kalshi_trade_history")


def parse_datetime(date_str: str) -> datetime:
    """Parse datetime string in various formats."""
    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Unable to parse datetime: {date_str}")


def format_fill(fill: Dict[str, Any]) -> Dict[str, Any]:
    """Format a fill record for output."""
    # Extract key fields - handle various possible field names from Kalshi API
    side = fill.get("side") or fill.get("outcome_side") or ""
    action = fill.get("action") or ""
    
    # Calculate price based on side
    yes_price = float(fill.get("yes_price_dollars") or 0)
    no_price = float(fill.get("no_price_dollars") or 0)
    price = yes_price if side.lower() == "yes" else no_price
    
    # Calculate total cost
    quantity = float(fill.get("count_fp") or fill.get("count") or 0)
    total_cost = quantity * price
    fee = float(fill.get("fee_cost") or 0)
    
    formatted = {
        "fill_id": fill.get("fill_id") or fill.get("trade_id") or fill.get("id") or "",
        "order_id": fill.get("order_id") or fill.get("order_uuid") or "",
        "market_ticker": fill.get("market_ticker") or fill.get("ticker") or fill.get("market_id") or "",
        "side": side.upper(),  # YES/NO
        "action": action,  # buy/sell
        "quantity": quantity,
        "price": price,
        "yes_price": yes_price,
        "no_price": no_price,
        "total_cost": total_cost,
        "fee": fee,
        "net_cost": total_cost + fee,
        "created_time": fill.get("created_time") or "",
        "asset": fill.get("asset") or "",
        "is_taker": fill.get("is_taker", False),
    }
    
    # Parse timestamp for readability
    if formatted["created_time"]:
        try:
            if isinstance(formatted["created_time"], (int, float)):
                ts = formatted["created_time"] / 1000 if formatted["created_time"] > 1e12 else formatted["created_time"]
                formatted["created_time"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except:
            pass
    
    return formatted


def extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset symbol from Kalshi ticker."""
    if ticker.startswith("KX"):
        # Format: KXBTC15M-26JUL030545-45
        parts = ticker.split("-")
        if parts:
            first_part = parts[0]
            # Extract asset from first part (KXBTC15M -> BTC)
            if first_part.startswith("KX"):
                asset_part = first_part[2:]
                # Remove timeframe suffix (15M, 1H, etc.)
                for tf in ["15M", "1H", "30M", "5M", "1D"]:
                    if asset_part.endswith(tf):
                        asset_part = asset_part[:-len(tf)]
                        break
                return asset_part
    return "UNKNOWN"


def filter_fills(
    fills: List[Dict[str, Any]],
    asset: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Filter fills by asset and time range."""
    filtered = []
    
    for fill in fills:
        # Asset filter
        if asset:
            fill_asset = fill.get("asset") or extract_asset_from_ticker(fill.get("market_ticker", ""))
            if fill_asset.upper() != asset.upper():
                continue
        
        # Time filter
        fill_time_str = fill.get("created_time", "")
        if fill_time_str and (start_time or end_time):
            try:
                if isinstance(fill_time_str, (int, float)):
                    ts = fill_time_str / 1000 if fill_time_str > 1e12 else fill_time_str
                    fill_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    fill_time = datetime.fromisoformat(fill_time_str.replace("Z", "+00:00"))
                
                if start_time and fill_time < start_time:
                    continue
                if end_time and fill_time > end_time:
                    continue
            except:
                pass
        
        filtered.append(fill)
    
    return filtered


def output_csv(fills: List[Dict[str, Any]], output_file: str):
    """Output fills to CSV file."""
    if not fills:
        logger.warning("No fills to output to CSV")
        return
    
    formatted_fills = [format_fill(fill) for fill in fills]
    fieldnames = list(formatted_fills[0].keys())
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(formatted_fills)
    
    logger.info(f"Output {len(formatted_fills)} fills to {output_file}")


def output_json(fills: List[Dict[str, Any]], output_file: str):
    """Output fills to JSON file."""
    formatted_fills = [format_fill(fill) for fill in fills]
    
    with open(output_file, 'w') as f:
        json.dump(formatted_fills, f, indent=2, default=str)
    
    logger.info(f"Output {len(formatted_fills)} fills to {output_file}")


def print_summary(fills: List[Dict[str, Any]]):
    """Print summary statistics of fills."""
    if not fills:
        print("No fills found")
        return
    
    # Format fills first to get calculated fields
    formatted_fills = [format_fill(fill) for fill in fills]
    
    # Group by asset
    asset_stats = {}
    total_pnl = 0
    total_volume = 0
    
    for fill in formatted_fills:
        asset = fill.get("asset") or extract_asset_from_ticker(fill.get("market_ticker", ""))
        if asset not in asset_stats:
            asset_stats[asset] = {
                "count": 0,
                "total_cost": 0,
                "total_fee": 0,
                "net_cost": 0,
                "sides": {"YES": 0, "NO": 0}
            }
        
        asset_stats[asset]["count"] += 1
        asset_stats[asset]["total_cost"] += fill.get("total_cost", 0)
        asset_stats[asset]["total_fee"] += fill.get("fee", 0)
        asset_stats[asset]["net_cost"] += fill.get("net_cost", 0)
        
        side = fill.get("side", "").upper()
        if side in asset_stats[asset]["sides"]:
            asset_stats[asset]["sides"][side] += 1
        
        total_volume += fill.get("total_cost", 0)
    
    print("\n" + "="*60)
    print("TRADE HISTORY SUMMARY")
    print("="*60)
    print(f"Total fills: {len(formatted_fills)}")
    print(f"Total volume: ${total_volume:,.2f}")
    print(f"Total fees: ${sum(s['total_fee'] for s in asset_stats.values()):,.2f}")
    print(f"Total net cost: ${sum(s['net_cost'] for s in asset_stats.values()):,.2f}")
    print("\nBy Asset:")
    print("-"*60)
    
    for asset, stats in sorted(asset_stats.items()):
        print(f"\n{asset}:")
        print(f"  Trades: {stats['count']}")
        print(f"  Volume: ${stats['total_cost']:,.2f}")
        print(f"  Fees: ${stats['total_fee']:,.2f}")
        print(f"  Net Cost: ${stats['net_cost']:,.2f}")
        print(f"  YES: {stats['sides']['YES']}, NO: {stats['sides']['NO']}")
    
    print("\n" + "="*60)


async def main():
    parser = argparse.ArgumentParser(description="Pull Kalshi trade history")
    parser.add_argument("--days", type=int, help="Number of days back to fetch")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--asset", type=str, help="Filter by asset (BTC, ETH, SOL, XRP, DOGE)")
    parser.add_argument("--format", type=str, choices=["csv", "json", "print"], default="print",
                       help="Output format")
    parser.add_argument("--output", type=str, help="Output file path (required for csv/json)")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum number of fills to fetch")
    parser.add_argument("--debug", action="store_true", help="Print raw API response structure for first fill")
    
    args = parser.parse_args()
    
    # Parse time range
    end_time = datetime.now(timezone.utc)
    start_time = None
    
    if args.days:
        start_time = end_time - timedelta(days=args.days)
    elif args.start:
        start_time = parse_datetime(args.start)
        if args.end:
            end_time = parse_datetime(args.end)
    else:
        # Default to last 7 days
        start_time = end_time - timedelta(days=7)
    
    logger.info(f"Fetching fills from {start_time} to {end_time}")
    if args.asset:
        logger.info(f"Filtering by asset: {args.asset}")
    
    # Initialize Kalshi client
    try:
        config = get_kalshi_config()
        logger.info(f"Using Kalshi environment: {config.env}")
        client = KalshiVenueClient(config)
    except Exception as e:
        logger.error(f"Failed to initialize Kalshi client: {e}")
        logger.error("Make sure KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM/PATH are set")
        sys.exit(1)
    
    # Fetch fills
    try:
        since_ts = int(start_time.timestamp() * 1000) if start_time else None
        result = await client.get_fills(limit=args.limit, since_ts=since_ts)
        
        if not result.success:
            logger.error(f"Failed to fetch fills: {result.error}")
            sys.exit(1)
        
        fills = result.data or []
        logger.info(f"Fetched {len(fills)} fills from Kalshi")
        
        # Debug: print first fill structure
        if args.debug and fills:
            print("\n" + "="*60)
            print("RAW API RESPONSE STRUCTURE (first fill):")
            print("="*60)
            print(json.dumps(fills[0], indent=2, default=str))
            print("="*60 + "\n")
        
        # Apply filters
        filtered_fills = filter_fills(fills, asset=args.asset, start_time=start_time, end_time=end_time)
        logger.info(f"After filtering: {len(filtered_fills)} fills")
        
        # Output
        if args.format == "print":
            print_summary(filtered_fills)
            if len(filtered_fills) <= 20:
                print("\nRecent fills:")
                print("-"*60)
                for fill in filtered_fills[:10]:
                    f = format_fill(fill)
                    print(f"{f['created_time']} | {f['market_ticker']} | {f['side']} | "
                          f"{f['quantity']} @ ${f['price']:.4f} | ${f['total_cost']:.2f}")
        elif args.format == "csv":
            if not args.output:
                logger.error("--output required for CSV format")
                sys.exit(1)
            output_csv(filtered_fills, args.output)
        elif args.format == "json":
            if not args.output:
                logger.error("--output required for JSON format")
                sys.exit(1)
            output_json(filtered_fills, args.output)
        
    except Exception as e:
        logger.error(f"Error fetching fills: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
