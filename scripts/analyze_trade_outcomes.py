#!/usr/bin/env python3
"""
Analyze Kalshi Trade Outcomes

This script loads trade history from CSV, fetches settlement data from Kalshi,
and analyzes win/loss patterns by side, asset, entry price, and other factors.

Usage:
    python scripts/analyze_trade_outcomes.py --input trade_history_7days.csv
"""

import asyncio
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("scripts.analyze_trade_outcomes")


def load_fills_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    """Load fills from CSV file."""
    fills = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for field in ['quantity', 'price', 'yes_price', 'no_price', 'total_cost', 'fee', 'net_cost']:
                if row.get(field):
                    try:
                        row[field] = float(row[field])
                    except:
                        row[field] = 0.0
            # Convert boolean
            if row.get('is_taker'):
                row['is_taker'] = row['is_taker'].lower() in ('true', '1', 'yes')
            fills.append(row)
    return fills


def detect_trade_history_inversion(fills: List[Dict[str, Any]]) -> Optional[str]:
    """Detect the known trade_history_7days.csv side/action/price inversion bug.

    Inverted rows have the wrong side (e.g. side=YES for a sell NO fill),
    action=sell, price equal to the opposite side's price, and the held side's
    opposite price set to 0.00.  This guard prevents mis-analyzed PnL and win
    rates from being regenerated.
    """
    if not fills:
        return None
    for row in fills:
        side = (row.get('side') or '').upper()
        action = (row.get('action') or '').lower()
        no_price = row.get('no_price', None)
        yes_price = row.get('yes_price', None)
        if side == 'YES' and action == 'sell' and no_price == 0.0:
            return (
                f"Detected side/price inversion in {row.get('market_ticker')}: "
                f"side=YES/action=sell with no_price=0.00. "
                f"Use trade_history_raw_7d.csv or trade_analysis_raw_7d.json instead."
            )
        if side == 'NO' and action == 'buy' and yes_price == 0.0:
            return (
                f"Detected side/price inversion in {row.get('market_ticker')}: "
                f"side=NO/action=buy with yes_price=0.00. "
                f"Use trade_history_raw_7d.csv or trade_analysis_raw_7d.json instead."
            )
    return None


def extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset symbol from Kalshi ticker."""
    if ticker.startswith("KX"):
        parts = ticker.split("-")
        if parts:
            first_part = parts[0]
            if first_part.startswith("KX"):
                asset_part = first_part[2:]
                for tf in ["15M", "1H", "30M", "5M", "1D"]:
                    if asset_part.endswith(tf):
                        asset_part = asset_part[:-len(tf)]
                        break
                return asset_part
    return "UNKNOWN"


async def fetch_settlements(client: KalshiVenueClient, market_tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch settlement data for a list of market tickers."""
    settlements = {}
    
    # Kalshi has a /portfolio/settlements endpoint
    # Use the client's internal request method
    result = await client._request_with_resilience(
        "GET", "/portfolio/settlements", params={"limit": 1000}, operation_name="get_settlements"
    )
    
    if not result.success:
        logger.error(f"Failed to fetch settlements: {result.error}")
        return settlements
    
    data = result.data or {}
    all_settlements = data.get("settlements", [])
    ticker_set = set(market_tickers)
    
    for settlement in all_settlements:
        ticker = settlement.get("market_ticker") or settlement.get("ticker") or ""
        if ticker in ticker_set:
            settlements[ticker] = settlement
    
    logger.info(f"Fetched {len(settlements)} settlements for {len(market_tickers)} markets")
    return settlements


def calculate_pnl(fill: Dict[str, Any], settlement: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate PnL for a fill given its settlement."""
    side = fill.get('side', '').upper()
    action = fill.get('action', '').lower()
    quantity = fill.get('quantity', 0)
    total_cost = fill.get('total_cost', 0)
    fee = fill.get('fee', 0)

    if not settlement:
        return {
            'status': 'PENDING',
            'pnl': 0,
            'outcome': 'UNKNOWN',
            'win': False,
            'loss': False
        }

    # Get settlement result from Kalshi API response
    # Fields: "market_result" (yes/no), "value" (0 or 100), "revenue" (payout in cents)
    market_result = settlement.get('market_result', '').lower()
    settlement_value = settlement.get('value')  # This is in cents (0 or 100)

    if settlement_value is None:
        return {
            'status': 'UNKNOWN',
            'pnl': 0,
            'outcome': 'UNKNOWN',
            'win': False,
            'loss': False
        }

    # Convert to dollars (settlement_value is already in cents)
    settlement_price_dollars = settlement_value / 100.0 if settlement_value else 0

    # Final payout per contract at settlement
    if side == 'YES':
        payout = quantity * settlement_price_dollars
    else:  # NO
        payout = quantity * (1.0 - settlement_price_dollars)

    # Cash flow at entry: buyer pays cost + fees; seller receives cost - fees
    if action == 'sell':
        pnl = (total_cost - fee) - payout
    else:  # buy
        pnl = payout - (total_cost + fee)

    if side == 'YES':
        outcome = 'YES_WON' if market_result == 'yes' else 'NO_WON'
    else:
        outcome = 'NO_WON' if market_result == 'no' else 'YES_WON'

    win = pnl > 0
    loss = pnl < 0

    return {
        'status': 'SETTLED',
        'pnl': pnl,
        'outcome': outcome,
        'win': win,
        'loss': loss,
        'settlement_price': settlement_price_dollars,
        'market_result': market_result
    }


def analyze_trades(fills: List[Dict[str, Any]], settlements: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze trades and calculate statistics."""
    analyzed = []
    
    for fill in fills:
        ticker = fill.get('market_ticker', '')
        settlement = settlements.get(ticker)
        pnl_data = calculate_pnl(fill, settlement)
        
        analyzed.append({
            **fill,
            **pnl_data,
            'asset': fill.get('asset') or extract_asset_from_ticker(ticker)
        })
    
    # Calculate statistics
    stats = {
        'total_trades': len(analyzed),
        'settled': sum(1 for t in analyzed if t['status'] == 'SETTLED'),
        'pending': sum(1 for t in analyzed if t['status'] == 'PENDING'),
        'total_pnl': sum(t['pnl'] for t in analyzed),
        'wins': sum(1 for t in analyzed if t['win']),
        'losses': sum(1 for t in analyzed if t['loss']),
        'by_asset': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0, 'yes': 0, 'no': 0}),
        'by_side': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0}),
        'by_price_range': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0}),
    }
    
    for trade in analyzed:
        asset = trade['asset']
        side = trade['side']
        price = trade['price']
        pnl = trade['pnl']
        
        stats['by_asset'][asset]['trades'] += 1
        stats['by_asset'][asset]['pnl'] += pnl
        if trade['win']:
            stats['by_asset'][asset]['wins'] += 1
        if trade['loss']:
            stats['by_asset'][asset]['losses'] += 1
        if str(side).upper() == 'YES':
            stats['by_asset'][asset]['yes'] += 1
        else:
            stats['by_asset'][asset]['no'] += 1
        
        stats['by_side'][side]['trades'] += 1
        stats['by_side'][side]['pnl'] += pnl
        if trade['win']:
            stats['by_side'][side]['wins'] += 1
        if trade['loss']:
            stats['by_side'][side]['losses'] += 1
        
        # Price ranges
        if price < 0.30:
            range_key = '< $0.30'
        elif price < 0.50:
            range_key = '$0.30-$0.50'
        elif price < 0.70:
            range_key = '$0.50-$0.70'
        else:
            range_key = '>= $0.70'
        
        stats['by_price_range'][range_key]['trades'] += 1
        stats['by_price_range'][range_key]['pnl'] += pnl
        if trade['win']:
            stats['by_price_range'][range_key]['wins'] += 1
        if trade['loss']:
            stats['by_price_range'][range_key]['losses'] += 1
    
    return {
        'trades': analyzed,
        'stats': stats
    }


def print_analysis(analysis: Dict[str, Any]):
    """Print analysis results."""
    stats = analysis['stats']
    trades = analysis['trades']
    
    print("\n" + "="*70)
    print("TRADE OUTCOME ANALYSIS")
    print("="*70)
    
    print(f"\nOverall:")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Settled: {stats['settled']}")
    print(f"  Pending: {stats['pending']}")
    print(f"  Total PnL: ${stats['total_pnl']:,.2f}")
    print(f"  Wins: {stats['wins']}")
    print(f"  Losses: {stats['losses']}")
    
    if stats['settled'] > 0:
        win_rate = stats['wins'] / stats['settled'] * 100
        print(f"  Win rate: {win_rate:.1f}%")
    
    print("\n" + "-"*70)
    print("By Asset:")
    print("-"*70)
    
    for asset, data in sorted(stats['by_asset'].items()):
        print(f"\n{asset}:")
        print(f"  Trades: {data['trades']}")
        print(f"  PnL: ${data['pnl']:,.2f}")
        print(f"  Wins: {data['wins']}, Losses: {data['losses']}")
        if data['trades'] > 0:
            win_rate = data['wins'] / (data['wins'] + data['losses']) * 100 if (data['wins'] + data['losses']) > 0 else 0
            print(f"  Win rate: {win_rate:.1f}%")
        print(f"  YES: {data['yes']}, NO: {data['no']}")
    
    print("\n" + "-"*70)
    print("By Side:")
    print("-"*70)
    
    for side, data in sorted(stats['by_side'].items()):
        print(f"\n{side}:")
        print(f"  Trades: {data['trades']}")
        print(f"  PnL: ${data['pnl']:,.2f}")
        print(f"  Wins: {data['wins']}, Losses: {data['losses']}")
        if data['trades'] > 0:
            win_rate = data['wins'] / (data['wins'] + data['losses']) * 100 if (data['wins'] + data['losses']) > 0 else 0
            print(f"  Win rate: {win_rate:.1f}%")
    
    print("\n" + "-"*70)
    print("By Entry Price Range:")
    print("-"*70)
    
    for range_key, data in sorted(stats['by_price_range'].items()):
        print(f"\n{range_key}:")
        print(f"  Trades: {data['trades']}")
        print(f"  PnL: ${data['pnl']:,.2f}")
        print(f"  Wins: {data['wins']}, Losses: {data['losses']}")
        if data['trades'] > 0:
            win_rate = data['wins'] / (data['wins'] + data['losses']) * 100 if (data['wins'] + data['losses']) > 0 else 0
            print(f"  Win rate: {win_rate:.1f}%")
    
    print("\n" + "="*70)
    
    # Show recent settled trades
    settled_trades = [t for t in trades if t['status'] == 'SETTLED']
    if settled_trades:
        print(f"\nRecent Settled Trades (last 10):")
        print("-"*70)
        for trade in settled_trades[-10:]:
            print(f"{trade['created_time']} | {trade['asset']} | {trade['side']} | "
                  f"${trade['price']:.2f} | PnL: ${trade['pnl']:.2f} | "
                  f"{'WIN' if trade['win'] else 'LOSS'}")
    
    print("\n" + "="*70)


async def main():
    parser = argparse.ArgumentParser(description="Analyze Kalshi trade outcomes")
    parser.add_argument("--input", type=str, required=True, help="Input CSV file with trade history")
    parser.add_argument("--output", type=str, help="Output JSON file for detailed results")
    
    args = parser.parse_args()
    
    # Load fills from CSV
    logger.info(f"Loading fills from {args.input}")
    fills = load_fills_from_csv(args.input)
    logger.info(f"Loaded {len(fills)} fills")

    # Guard against the known trade_history_7days.csv inversion bug
    inversion = detect_trade_history_inversion(fills)
    if inversion:
        logger.error(f"[ANALYSIS-GUARD] {inversion}")
        print(f"ERROR: {inversion}")
        sys.exit(2)
    
    # Get unique market tickers
    unique_tickers = list(set(f.get('market_ticker', '') for f in fills if f.get('market_ticker')))
    logger.info(f"Found {len(unique_tickers)} unique markets")
    
    # Initialize Kalshi client
    try:
        config = get_kalshi_config()
        logger.info(f"Using Kalshi environment: {config.env}")
        client = KalshiVenueClient(config)
    except Exception as e:
        logger.error(f"Failed to initialize Kalshi client: {e}")
        sys.exit(1)
    
    # Fetch settlements
    logger.info("Fetching settlements...")
    settlements = await fetch_settlements(client, unique_tickers)
    
    # Debug: print first settlement structure
    if settlements:
        logger.info(f"Sample settlement structure: {json.dumps(list(settlements.values())[0], indent=2, default=str)}")
    
    # Analyze trades
    logger.info("Analyzing trades...")
    analysis = analyze_trades(fills, settlements)
    
    # Print analysis
    print_analysis(analysis)
    
    # Save to JSON if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        logger.info(f"Saved detailed results to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
