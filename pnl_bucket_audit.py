#!/usr/bin/env python3
"""
Edge vs Realized PnL Audit by Bucket

Analyzes Kalshi fills to compute:
- Win rate and average PnL per price/distance bucket
- Comparison to predicted edge per bucket

Usage:
    python pnl_bucket_audit.py
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json

# Database paths
FILLS_DB = Path("c:/Dev/MERID/data/kalshi_fills.db")
SIGNALS_DB = Path("c:/Dev/MERID/data/signals.db")
PNL_DB = Path("c:/Dev/MERID/merid_pnl_attribution.db")

# Bucket definitions
PRICE_BANDS = [
    (0.00, 0.20, "below_20c"),  # Below price floor
    (0.20, 0.35, "20c_35c"),
    (0.35, 0.50, "35c_50c"),
    (0.50, 0.75, "50c_75c"),
    (0.75, 1.00, "75c_1d"),
    (1.00, float('inf'), "above_1d"),
]

DISTANCE_BANDS = [
    (0.0, 0.5, "0_0.5pct"),
    (0.5, 1.0, "0.5_1.0pct"),
    (1.0, 2.0, "1.0_2.0pct"),
    (2.0, float('inf'), "above_2.0pct"),
]

def get_price_band(price_dollars):
    """Get price band for a given price in dollars."""
    for min_p, max_p, band in PRICE_BANDS:
        if min_p <= price_dollars < max_p:
            return band
    return "unknown"

def get_distance_band(distance_pct):
    """Get distance band for a given distance percentage."""
    for min_d, max_d, band in DISTANCE_BANDS:
        if min_d <= distance_pct < max_d:
            return band
    return "unknown"

def extract_asset_from_ticker(ticker):
    """Extract asset code from Kalshi ticker."""
    if "KXBTC" in ticker:
        return "BTC"
    elif "KXETH" in ticker:
        return "ETH"
    elif "KXSOL" in ticker:
        return "SOL"
    elif "KXXRP" in ticker:
        return "XRP"
    elif "KXDOGE" in ticker:
        return "DOGE"
    return "UNKNOWN"

def load_fills():
    """Load fills from kalshi_fills.db."""
    if not FILLS_DB.exists():
        print(f"Fills database not found: {FILLS_DB}")
        return []
    
    conn = sqlite3.connect(FILLS_DB)
    cursor = conn.cursor()
    
    # Load fills with relevant fields (include all fills for audit)
    cursor.execute("""
        SELECT 
            fill_id,
            market_ticker,
            side,
            action,
            count_fp,
            yes_price_dollars,
            no_price_dollars,
            fee_cost,
            proceeds_dollars,
            created_time,
            agent_id,
            reconciled
        FROM kalshi_fills
        ORDER BY created_time DESC
    """)
    
    fills = []
    for row in cursor.fetchall():
        fill = {
            'fill_id': row[0],
            'market_ticker': row[1],
            'side': row[2],
            'action': row[3],
            'count': row[4],
            'yes_price': row[5],
            'no_price': row[6],
            'fee_cost': row[7],
            'proceeds': row[8],
            'created_time': row[9],
            'agent_id': row[10],
            'reconciled': row[11],
        }
        fills.append(fill)
    
    conn.close()
    print(f"Loaded {len(fills)} fills from kalshi_fills.db")
    return fills

def load_signal_features():
    """Load signal features from signals.db."""
    if not SIGNALS_DB.exists():
        print(f"Signals database not found: {SIGNALS_DB}")
        return {}
    
    conn = sqlite3.connect(SIGNALS_DB)
    cursor = conn.cursor()
    
    # Load signal features for crypto 15m markets
    cursor.execute("""
        SELECT 
            symbol,
            features_json,
            timestamp
        FROM signal_features
        WHERE domain = 'market_edge'
        AND (symbol LIKE 'KXBTC15M%' OR symbol LIKE 'KXETH15M%' OR 
             symbol LIKE 'KXSOL15M%' OR symbol LIKE 'KXXRP15M%' OR 
             symbol LIKE 'KXDOGE15M%')
    """)
    
    features = {}
    for row in cursor.fetchall():
        symbol = row[0]
        try:
            feature_data = json.loads(row[1])
            features[symbol] = {
                'edge_pct': feature_data.get('edge_pct'),
                'implied_prob': feature_data.get('implied_prob'),
                'model_prob': feature_data.get('model_prob'),
                'ev_cents': feature_data.get('ev_cents'),
                'confidence': feature_data.get('confidence'),
                'timestamp': row[2],
            }
        except json.JSONDecodeError:
            continue
    
    conn.close()
    print(f"Loaded {len(features)} signal features from signals.db")
    return features

def analyze_fills_by_bucket(fills, signal_features):
    """Analyze fills by price and distance buckets."""
    # Initialize bucket stats
    bucket_stats = defaultdict(lambda: {
        'count': 0,
        'wins': 0,
        'total_pnl': 0.0,
        'total_edge_pct': 0.0,
        'assets': defaultdict(int),
    })
    
    for fill in fills:
        # Extract asset
        asset = extract_asset_from_ticker(fill['market_ticker'])
        
        # Determine entry price (yes_price for yes side, no_price for no side)
        if fill['side'] == 'yes':
            entry_price = fill['yes_price']
        else:
            entry_price = fill['no_price']
        
        # Get price band
        price_band = get_price_band(entry_price)
        
        # For now, use a default distance band (we'll need spot prices for real distance)
        distance_band = "unknown"
        
        # Calculate PnL (proceeds - cost)
        # For sells: proceeds are positive, cost is entry_price * count
        # For buys: proceeds are negative (cost), need to calculate based on settlement
        # Simplified: use proceeds as PnL proxy for now
        pnl = fill['proceeds']
        
        # Skip fills with None proceeds
        if pnl is None:
            continue
        
        # Determine win/loss (positive PnL = win)
        is_win = pnl > 0
        
        # Get edge from signal features if available
        edge_pct = 0.0
        if fill['market_ticker'] in signal_features:
            edge_pct = signal_features[fill['market_ticker']].get('edge_pct', 0.0)
        
        # Update bucket stats
        bucket_key = (price_band, distance_band)
        stats = bucket_stats[bucket_key]
        stats['count'] += 1
        if is_win:
            stats['wins'] += 1
        stats['total_pnl'] += pnl
        stats['total_edge_pct'] += edge_pct
        stats['assets'][asset] += 1
    
    return bucket_stats

def print_bucket_report(bucket_stats):
    """Print bucket analysis report."""
    print("\n" + "="*80)
    print("EDGE VS REALIZED PNL AUDIT BY BUCKET")
    print("="*80)
    
    print("\n--- Price Band Analysis ---")
    for min_p, max_p, price_band in PRICE_BANDS:
        # Aggregate across all distance bands for this price band
        total_count = 0
        total_wins = 0
        total_pnl = 0.0
        total_edge = 0.0
        assets = defaultdict(int)
        
        for (pb, _), stats in bucket_stats.items():
            if pb == price_band:
                total_count += stats['count']
                total_wins += stats['wins']
                total_pnl += stats['total_pnl']
                total_edge += stats['total_edge_pct']
                for asset, count in stats['assets'].items():
                    assets[asset] += count
        
        if total_count == 0:
            continue
        
        win_rate = (total_wins / total_count) * 100
        avg_pnl = total_pnl / total_count
        avg_edge = total_edge / total_count if total_count > 0 else 0
        
        print(f"\nPrice Band: {price_band}")
        print(f"  Trades: {total_count}")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg PnL: ${avg_pnl:.3f}")
        print(f"  Avg Edge: {avg_edge:.2f}%")
        print(f"  Assets: {dict(assets)}")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    total_trades = sum(stats['count'] for stats in bucket_stats.values())
    total_wins = sum(stats['wins'] for stats in bucket_stats.values())
    total_pnl = sum(stats['total_pnl'] for stats in bucket_stats.values())
    
    if total_trades > 0:
        overall_win_rate = (total_wins / total_trades) * 100
        avg_pnl = total_pnl / total_trades
        print(f"Total Trades: {total_trades}")
        print(f"Overall Win Rate: {overall_win_rate:.1f}%")
        print(f"Overall Avg PnL: ${avg_pnl:.3f}")
    
    # Count trades below price floor
    below_floor = bucket_stats.get(("below_20c", "unknown"), {})
    below_floor_count = below_floor.get('count', 0)
    if below_floor_count > 0:
        print(f"\n⚠️  Trades below 20c price floor: {below_floor_count}")
        print(f"   These should now be rejected by price floor guardrail")

def main():
    """Main analysis function."""
    print("Loading data...")
    fills = load_fills()
    signal_features = load_signal_features()
    
    if not fills:
        print("No fills to analyze")
        return
    
    print("\nAnalyzing fills by bucket...")
    bucket_stats = analyze_fills_by_bucket(fills, signal_features)
    
    print_bucket_report(bucket_stats)
    
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    print("1. Add spot price data to calculate distance bands accurately")
    print("2. Join fills with edge snapshots by timestamp for precise edge values")
    print("3. Track time-to-expiry for TTE-based bucketing")
    print("4. Compare results across volatility regimes (LOW/NORMAL/HIGH/EXTREME)")

if __name__ == "__main__":
    main()
