"""
15-Minute Band Strategy Backtest Runner
========================================

Script to run backtests and parameter optimization for the Bollinger Band
"top edge" strategy on BTC, ETH, SOL, XRP, DOGE.

Usage:
    # Run initial backtest with defaults for BTC
    python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv
    
    # Run grid search for BTC
    python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv --grid-search
    
    # Run walk-forward validation for BTC
    python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv --walk-forward
    
    # Run for all assets
    python scripts/run_band_backtest.py --all-assets --data_dir ./data/crypto_15m/
"""

import argparse
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.strategies.band_backtest_15m import (
    backtest_band_strategy,
    grid_search_band_params,
    walk_forward_validation,
    trades_to_dataframe,
    windows_to_dataframe,
)
from merid.strategies.band_strategy_15m import get_band_strategy_config
from utils.logger import get_logger

logger = get_logger("scripts.run_band_backtest")


def load_ohlc_data(filepath: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    """Load OHLCV data from CSV file with optional date filtering.
    
    Expected columns: timestamp, high, low, close (volume optional)
    Date format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
    
    Args:
        filepath: Path to CSV file
        start_date: Optional start date filter (inclusive)
        end_date: Optional end date filter (inclusive)
    """
    df = pd.read_csv(filepath)
    
    # Ensure datetime index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    elif df.index.name != 'timestamp':
        df.index = pd.to_datetime(df.index)
        df.index.name = 'timestamp'
    
    # Ensure required columns
    required_cols = ['high', 'low', 'close']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    # Sort by timestamp
    df = df.sort_index()
    
    # Apply date filters
    if start_date:
        start_dt = pd.to_datetime(start_date)
        df = df[df.index >= start_dt]
        logger.info(f"Filtered to start date: {start_dt}")
    
    if end_date:
        end_dt = pd.to_datetime(end_date)
        df = df[df.index <= end_dt]
        logger.info(f"Filtered to end date: {end_dt}")
    
    # Check for gaps (log warning if large gaps detected)
    if len(df) > 1:
        time_diffs = df.index.to_series().diff()
        median_diff = time_diffs.median()
        large_gaps = time_diffs[time_diffs > median_diff * 10]
        if len(large_gaps) > 0:
            logger.warning(f"Detected {len(large_gaps)} large time gaps in data (may indicate missing bars)")
    
    logger.info(f"Loaded {len(df)} bars from {filepath}")
    return df


def run_initial_backtest(
    asset: str,
    data_path: str,
    output_dir: str = "./output",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trades_output: Optional[str] = None,
    summary_output: Optional[str] = None,
):
    """Run initial backtest with default parameters.
    
    Args:
        asset: Asset symbol
        data_path: Path to OHLCV CSV file
        output_dir: Base output directory
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        trades_output: Optional custom path for trades CSV
        summary_output: Optional custom path for summary JSON
    """
    logger.info(f"Running initial backtest for {asset} with defaults")
    if start_date or end_date:
        logger.info(f"Date range: {start_date or 'start'} to {end_date or 'end'}")
    
    df = load_ohlc_data(data_path, start_date, end_date)
    config = get_band_strategy_config(asset)
    
    trades, summary = backtest_band_strategy(df, asset, config)
    
    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_suffix = f"_{start_date}_{end_date}" if start_date or end_date else ""
    
    # Use custom output paths if provided, otherwise use defaults
    summary_path = Path(summary_output) if summary_output else output_path / f"{asset}_initial_backtest_summary{date_suffix}_{timestamp}.json"
    trades_path = Path(trades_output) if trades_output else output_path / f"{asset}_initial_backtest_trades{date_suffix}_{timestamp}.csv"
    
    import json
    with open(summary_path, 'w') as f:
        json.dump(summary.to_dict(), f, indent=2)
    
    # Save trades if any
    if trades:
        trades_df = trades_to_dataframe(trades)
        trades_df.to_csv(trades_path, index=False)
    
    # Print key metrics
    print(f"\n{'='*60}")
    print(f"{asset} INITIAL BACKTEST RESULTS (DEFAULTS)")
    print(f"{'='*60}")
    print(f"Total Trades: {summary.total_trades}")
    print(f"Win Rate: {summary.win_rate:.2%}")
    print(f"Range Win Rate: {summary.range_win_rate:.2%}")
    print(f"Total PnL: {summary.total_pnl_pct:.2%}")
    print(f"Max Drawdown: {summary.max_drawdown_pct:.2%}")
    print(f"Avg R:R: {summary.avg_r_multiple:.2f}")
    print(f"TP Exits: {summary.tp_exits}")
    print(f"SL Exits: {summary.sl_exits}")
    print(f"Config: SD={summary.bb_sd_multiplier}, SL ATR={summary.sl_atr_multiplier}")
    print(f"Date Range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Output: {summary_path}")
    if trades:
        print(f"Trades: {trades_path}")
    print(f"{'='*60}\n")
    
    return trades, summary


def run_grid_search(
    asset: str,
    data_path: str,
    output_dir: str = "./output",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    results_output: Optional[str] = None,
):
    """Run grid search over SD and ATR parameters.
    
    Args:
        asset: Asset symbol
        data_path: Path to OHLCV CSV file
        output_dir: Base output directory
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        results_output: Optional custom path for grid search results CSV
    """
    logger.info(f"Running grid search for {asset}")
    if start_date or end_date:
        logger.info(f"Date range: {start_date or 'start'} to {end_date or 'end'}")
    
    df = load_ohlc_data(data_path, start_date, end_date)
    
    # Define search ranges (per spec)
    sd_range = (2.0, 2.5)
    sd_step = 0.1
    sl_atr_range = (1.5, 2.0)
    sl_atr_step = 0.1
    
    results_df = grid_search_band_params(
        df, asset, sd_range, sd_step, sl_atr_range, sl_atr_step
    )
    
    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_suffix = f"_{start_date}_{end_date}" if start_date or end_date else ""
    
    # Use custom output path if provided, otherwise use default
    results_path = Path(results_output) if results_output else output_path / f"{asset}_grid_search{date_suffix}_{timestamp}.csv"
    results_df.to_csv(results_path, index=False)
    
    # Print top results
    print(f"\n{'='*60}")
    print(f"{asset} GRID SEARCH RESULTS (TOP 10)")
    print(f"{'='*60}")
    print(f"Date Range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Output: {results_path}")
    print(f"\n{results_df.head(10).to_string(index=False)}")
    print(f"{'='*60}\n")
    
    return results_df


def run_walk_forward(
    asset: str,
    data_path: str,
    output_dir: str = "./output",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    windows_output: Optional[str] = None,
    summary_output: Optional[str] = None,
):
    """Run walk-forward validation.
    
    Args:
        asset: Asset symbol
        data_path: Path to OHLCV CSV file
        output_dir: Base output directory
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        windows_output: Optional custom path for windows CSV
        summary_output: Optional custom path for summary JSON
    """
    logger.info(f"Running walk-forward validation for {asset}")
    if start_date or end_date:
        logger.info(f"Date range: {start_date or 'start'} to {end_date or 'end'}")
    
    df = load_ohlc_data(data_path, start_date, end_date)
    
    # Default windows: 90d optimize, 30d forward
    result = walk_forward_validation(df, asset)
    
    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_suffix = f"_{start_date}_{end_date}" if start_date or end_date else ""
    
    # Use custom output paths if provided, otherwise use defaults
    windows_path = Path(windows_output) if windows_output else output_path / f"{asset}_walk_forward_windows{date_suffix}_{timestamp}.csv"
    summary_path = Path(summary_output) if summary_output else output_path / f"{asset}_walk_forward_summary{date_suffix}_{timestamp}.json"
    
    # Save windows
    windows_df = windows_to_dataframe(result)
    windows_df.to_csv(windows_path, index=False)
    
    # Save summary
    import json
    with open(summary_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"{asset} WALK-FORWARD VALIDATION RESULTS")
    print(f"{'='*60}")
    print(f"Date Range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Windows: {len(result.windows)}")
    print(f"Total Trades: {result.total_trades}")
    print(f"Aggregate Win Rate: {result.aggregate_win_rate:.2%}")
    print(f"Aggregate Range Win Rate: {result.aggregate_range_win_rate:.2%}")
    print(f"Avg Window Win Rate: {result.avg_window_win_rate:.2%}")
    print(f"Consistency Score (>65% WR): {result.consistency_score:.2%}")
    print(f"Output: {summary_path}")
    print(f"Windows: {windows_path}")
    print(f"{'='*60}\n")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run band strategy backtests with optional date filtering and custom output paths",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initial backtest with defaults
  python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv

  # Backtest with date range
  python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv --start 2023-01-01 --end 2023-12-31

  # Grid search with custom output
  python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv --grid-search --results-output btc_grid.csv

  # Walk-forward validation
  python scripts/run_band_backtest.py --asset BTC --data btc_15m_ohlc.csv --walk-forward

  # All assets
  python scripts/run_band_backtest.py --all-assets --data-dir ./data/crypto_15m/
        """
    )
    
    parser.add_argument(
        "--asset",
        type=str,
        help="Asset symbol (BTC, ETH, SOL, XRP, DOGE)"
    )
    parser.add_argument(
        "--all-assets",
        action="store_true",
        help="Run for all 5 assets"
    )
    parser.add_argument(
        "--data",
        type=str,
        help="Path to OHLCV CSV file"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Directory containing OHLCV CSV files (for --all-assets)"
    )
    parser.add_argument(
        "--grid-search",
        action="store_true",
        help="Run grid search parameter optimization"
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Run walk-forward validation"
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date filter (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date filter (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Output directory for results (default: ./output)"
    )
    parser.add_argument(
        "--trades-output",
        type=str,
        help="Custom path for trades CSV output"
    )
    parser.add_argument(
        "--summary-output",
        type=str,
        help="Custom path for summary JSON output"
    )
    parser.add_argument(
        "--results-output",
        type=str,
        help="Custom path for grid search results CSV output"
    )
    parser.add_argument(
        "--windows-output",
        type=str,
        help="Custom path for walk-forward windows CSV output"
    )
    
    args = parser.parse_args()
    
    if args.all_assets:
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        if not args.data_dir:
            logger.error("--data-dir required for --all-assets")
            sys.exit(1)
        
        for asset in assets:
            data_path = Path(args.data_dir) / f"{asset.lower()}_15m_ohlc.csv"
            if not data_path.exists():
                logger.warning(f"Data file not found for {asset}: {data_path}")
                continue
            
            if args.walk_forward:
                run_walk_forward(
                    asset,
                    str(data_path),
                    args.output_dir,
                    args.start,
                    args.end,
                    args.windows_output,
                    args.summary_output,
                )
            elif args.grid_search:
                run_grid_search(
                    asset,
                    str(data_path),
                    args.output_dir,
                    args.start,
                    args.end,
                    args.results_output,
                )
            else:
                run_initial_backtest(
                    asset,
                    str(data_path),
                    args.output_dir,
                    args.start,
                    args.end,
                    args.trades_output,
                    args.summary_output,
                )
    
    else:
        if not args.asset:
            logger.error("--asset or --all-assets required")
            sys.exit(1)
        
        if not args.data:
            logger.error("--data required for single asset")
            sys.exit(1)
        
        if args.walk_forward:
            run_walk_forward(
                args.asset,
                args.data,
                args.output_dir,
                args.start,
                args.end,
                args.windows_output,
                args.summary_output,
            )
        elif args.grid_search:
            run_grid_search(
                args.asset,
                args.data,
                args.output_dir,
                args.start,
                args.end,
                args.results_output,
            )
        else:
            run_initial_backtest(
                args.asset,
                args.data,
                args.output_dir,
                args.start,
                args.end,
                args.trades_output,
                args.summary_output,
            )


if __name__ == "__main__":
    main()
