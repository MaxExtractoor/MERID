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
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import canonical bucket definitions
from merid.metrics.canonical_buckets import (
    CANONICAL_PRICE_BANDS,
    ALL_PRICE_BANDS,
    CANONICAL_DISTANCE_BANDS,
    get_price_bucket,
    get_distance_bucket,
    BucketStats
)

# Database paths
FILLS_DB = Path("c:/Dev/MERID/data/kalshi_fills.db")
SIGNALS_DB = Path("c:/Dev/MERID/data/signals.db")
PNL_DB = Path("c:/Dev/MERID/merid_pnl_attribution.db")
SPOT_DATA_DB = Path("c:/Dev/MERID/data/spot_prices.db")

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

def load_spot_prices():
    """Load spot prices for distance band calculation."""
    if not SPOT_DATA_DB.exists():
        print(f"Spot prices database not found: {SPOT_DATA_DB}")
        return {}
    
    conn = sqlite3.connect(SPOT_DATA_DB)
    cursor = conn.cursor()
    
    # Load latest spot prices per asset
    cursor.execute("""
        SELECT 
            asset,
            price_usd,
            timestamp
        FROM spot_prices
        WHERE asset IN ('BTC', 'ETH', 'SOL', 'XRP', 'DOGE')
        ORDER BY timestamp DESC
    """)
    
    spot_prices = {}
    for row in cursor.fetchall():
        asset = row[0]
        price = row[1]
        timestamp = row[2]
        # Keep only the latest price per asset
        if asset not in spot_prices:
            spot_prices[asset] = {
                'price_usd': price,
                'timestamp': timestamp
            }
    
    conn.close()
    print(f"Loaded spot prices for {len(spot_prices)} assets")
    return spot_prices


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
            reconciled,
            strike_price_usd
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
            'strike_price': row[12] if len(row) > 12 else None,
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

def analyze_fills_by_bucket(fills, signal_features, spot_prices):
    """Analyze fills by price and distance buckets."""
    # Initialize bucket stats using canonical BucketStats
    bucket_stats = defaultdict(BucketStats)
    
    for fill in fills:
        # Extract asset
        asset = extract_asset_from_ticker(fill['market_ticker'])
        
        # Determine entry price in cents
        if fill['side'] == 'yes':
            entry_price_dollars = fill['yes_price']
        else:
            entry_price_dollars = fill['no_price']
        
        entry_price_cents = int(entry_price_dollars * 100) if entry_price_dollars else 0
        
        # Get price band using canonical function
        price_band = get_price_bucket(entry_price_cents)
        
        # Calculate distance band if spot price and strike available
        distance_band = "unknown"
        if fill['strike_price'] and asset in spot_prices:
            spot_price = spot_prices[asset]['price_usd']
            strike_price = fill['strike_price']
            if spot_price > 0:
                distance_pct = abs(spot_price - strike_price) / spot_price * 100
                distance_band = get_distance_bucket(distance_pct)
        
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
        ev_cents = 0.0
        if fill['market_ticker'] in signal_features:
            edge_pct = signal_features[fill['market_ticker']].get('edge_pct', 0.0)
            ev_cents = signal_features[fill['market_ticker']].get('ev_cents', 0.0)
        
        # Update bucket stats
        bucket_key = (price_band, distance_band)
        stats = bucket_stats[bucket_key]
        stats.count += 1
        if is_win:
            stats.wins += 1
        stats.total_pnl += pnl
        stats.total_edge_pct += edge_pct
        stats.total_ev_cents += ev_cents
    
    return bucket_stats

def print_bucket_report(bucket_stats):
    """Print bucket analysis report."""
    print("\n" + "="*80)
    print("EDGE VS REALIZED PNL AUDIT BY BUCKET (CANONICAL)")
    print("="*80)
    
    print("\n--- Price Band Analysis (Canonical 10c-75c Range) ---")
    for min_p, max_p, price_band in CANONICAL_PRICE_BANDS:
        # Aggregate across all distance bands for this price band
        total_count = 0
        total_wins = 0
        total_pnl = 0.0
        total_edge = 0.0
        total_ev = 0.0
        
        for (pb, _), stats in bucket_stats.items():
            if pb == price_band:
                total_count += stats.count
                total_wins += stats.wins
                total_pnl += stats.total_pnl
                total_edge += stats.total_edge_pct
                total_ev += stats.total_ev_cents
        
        if total_count == 0:
            continue
        
        win_rate = (total_wins / total_count) * 100
        avg_pnl = total_pnl / total_count
        avg_edge = total_edge / total_count if total_count > 0 else 0
        avg_ev = total_ev / total_count if total_count > 0 else 0
        
        print(f"\nPrice Band: {price_band}")
        print(f"  Trades: {total_count}")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg PnL: ${avg_pnl:.3f}")
        print(f"  Avg Edge: {avg_edge:.2f}%")
        print(f"  Avg EV: {avg_ev:.2f}¢")
    
    # Check for out-of-range trades (should be rejected by guardrails)
    print("\n--- Out-of-Range Trades (Guardrail Violations) ---")
    for min_p, max_p, price_band in OUT_OF_RANGE_PRICE_BANDS:
        total_count = 0
        for (pb, _), stats in bucket_stats.items():
            if pb == price_band:
                total_count += stats.count
        
        if total_count > 0:
            print(f"⚠️  {price_band}: {total_count} trades (should be rejected by guardrails)")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    total_trades = sum(stats.count for stats in bucket_stats.values())
    total_wins = sum(stats.wins for stats in bucket_stats.values())
    total_pnl = sum(stats.total_pnl for stats in bucket_stats.values())
    total_ev = sum(stats.total_ev_cents for stats in bucket_stats.values())
    
    if total_trades > 0:
        overall_win_rate = (total_wins / total_trades) * 100
        avg_pnl = total_pnl / total_trades
        avg_ev = total_ev / total_trades
        print(f"Total Trades: {total_trades}")
        print(f"Overall Win Rate: {overall_win_rate:.1f}%")
        print(f"Overall Avg PnL: ${avg_pnl:.3f}")
        print(f"Overall Avg EV: {avg_ev:.2f}¢")
    
    # Distance band analysis
    print("\n--- Distance Band Analysis ---")
    distance_counts = defaultdict(int)
    for (_, db), stats in bucket_stats.items():
        distance_counts[db] += stats.count
    
    for min_d, max_d, distance_band in CANONICAL_DISTANCE_BANDS:
        count = distance_counts.get(distance_band, 0)
        if count > 0:
            print(f"{distance_band}: {count} trades")
    
    if distance_counts.get("unknown", 0) > 0:
        print(f"⚠️  Unknown distance: {distance_counts['unknown']} trades (missing spot/strike data)")

def main():
    """Main analysis function."""
    print("Loading data...")
    fills = load_fills()
    signal_features = load_signal_features()
    spot_prices = load_spot_prices()
    
    if not fills:
        print("No fills to analyze")
        return
    
    print("\nAnalyzing fills by bucket...")
    bucket_stats = analyze_fills_by_bucket(fills, signal_features, spot_prices)
    
    print_bucket_report(bucket_stats)
    
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    print("1. Spot price integration enabled - distance bands now calculated")
    print("2. Join fills with edge snapshots by timestamp for precise edge values")
    print("3. Track time-to-expiry for TTE-based bucketing")
    print("4. Compare results across volatility regimes (LOW/NORMAL/HIGH/EXTREME)")

if __name__ == "__main__":
    main()
