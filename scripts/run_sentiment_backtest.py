#!/usr/bin/env python3
"""CLI script to run sentiment pipeline backtest.

Usage:
    python scripts/run_sentiment_backtest.py --start-date 2024-01-01 --end-date 2024-01-31 --asset BTC
    python scripts/run_sentiment_backtest.py --start-date 2024-01-01 --end-date 2024-01-31
"""

import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from merid.sentiment.backtest_harness import run_backtest
from merid.sentiment.news_event_schema import Asset
from utils.logger import get_logger

logger = get_logger("scripts.run_sentiment_backtest")


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime."""
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}. Use ISO format like 2024-01-01")


def main():
    parser = argparse.ArgumentParser(
        description="Run backtest on sentiment pipeline to measure predictive power"
    )
    
    parser.add_argument(
        "--start-date",
        type=parse_date,
        required=True,
        help="Start date for backtest period (ISO format, e.g., 2024-01-01)",
    )
    
    parser.add_argument(
        "--end-date",
        type=parse_date,
        required=True,
        help="End date for backtest period (ISO format, e.g., 2024-01-31)",
    )
    
    parser.add_argument(
        "--asset",
        type=str,
        choices=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        help="Asset to filter (default: all assets)",
    )
    
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/sentiment.db"),
        help="Path to sentiment SQLite database (default: data/sentiment.db)",
    )
    
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/backtest_results.csv"),
        help="Path to output CSV file (default: data/backtest_results.csv)",
    )
    
    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=3.0,
        help="Edge threshold in cents to generate signal (default: 3.0)",
    )
    
    args = parser.parse_args()
    
    # Convert asset string to enum if provided
    asset_enum = None
    if args.asset:
        asset_enum = Asset(args.asset)
    
    logger.info("Starting backtest from %s to %s", args.start_date, args.end_date)
    if asset_enum:
        logger.info("Filtering by asset: %s", asset_enum.value)
    
    # Run backtest
    summary = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        asset=asset_enum,
        db_path=args.db_path,
        output_path=args.output,
    )
    
    # Print summary
    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Total observations: {summary.total_observations}")
    print(f"Hit rate (15m): {summary.hit_rate_15m:.2%}")
    print(f"Hit rate (1h): {summary.hit_rate_1h:.2%}")
    print(f"Average edge (cents): {summary.avg_edge_cents:.2f}")
    print(f"Calibration error: {summary.calibration_error:.4f}")
    print(f"Buy signals: {summary.buy_count}")
    print(f"Sell signals: {summary.sell_count}")
    print(f"Hold signals: {summary.hold_count}")
    print("=" * 60)
    print(f"\nResults exported to: {args.output}")


if __name__ == "__main__":
    main()
