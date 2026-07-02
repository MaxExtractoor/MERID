#!/usr/bin/env python3
"""
Per-Asset Calibration from PnL Data

Uses historical PnL data to suggest calibration values for:
- guardrails_min_contract_price_cents (price floor)
- guardrails_max_dist_pct_trade (OTM distance limit)
- Per-asset edge thresholds

Based on the PnL audit results showing poor performance in low-price bands.
"""
import sqlite3
from pathlib import Path
from collections import defaultdict

FILLS_DB = Path("c:/Dev/MERID/data/kalshi_fills.db")

def analyze_price_band_performance():
    """Analyze win rate by price band to suggest optimal price floor."""
    if not FILLS_DB.exists():
        print(f"Fills database not found: {FILLS_DB}")
        return None
    
    conn = sqlite3.connect(FILLS_DB)
    cursor = conn.cursor()
    
    # Load fills with price and proceeds
    cursor.execute("""
        SELECT 
            market_ticker,
            side,
            yes_price_dollars,
            no_price_dollars,
            proceeds_dollars
        FROM kalshi_fills
        WHERE proceeds_dollars IS NOT NULL
    """)
    
    # Bucket by price bands
    price_bands = defaultdict(lambda: {'count': 0, 'wins': 0, 'total_pnl': 0.0})
    
    for row in cursor.fetchall():
        ticker, side, yes_price, no_price, proceeds = row
        
        # Determine entry price
        if side == 'yes':
            entry_price = yes_price
        else:
            entry_price = no_price
        
        if entry_price is None:
            continue
        
        # Determine price band
        if entry_price < 0.20:
            band = "below_20c"
        elif entry_price < 0.35:
            band = "20c_35c"
        elif entry_price < 0.50:
            band = "35c_50c"
        elif entry_price < 0.75:
            band = "50c_75c"
        else:
            band = "above_75c"
        
        price_bands[band]['count'] += 1
        price_bands[band]['total_pnl'] += proceeds
        if proceeds > 0:
            price_bands[band]['wins'] += 1
    
    conn.close()
    
    # Calculate win rates
    results = {}
    for band, data in price_bands.items():
        if data['count'] > 0:
            win_rate = (data['wins'] / data['count']) * 100
            avg_pnl = data['total_pnl'] / data['count']
            results[band] = {
                'count': data['count'],
                'win_rate': win_rate,
                'avg_pnl': avg_pnl
            }
    
    return results

def suggest_calibration():
    """Suggest calibration values based on PnL analysis."""
    print("="*80)
    print("PER-ASSET CALIBRATION FROM PNL DATA")
    print("="*80)
    
    price_analysis = analyze_price_band_performance()
    
    if not price_analysis:
        print("No data available for calibration")
        return
    
    print("\n--- Price Band Performance ---")
    for band in ["below_20c", "20c_35c", "35c_50c", "50c_75c", "above_75c"]:
        if band in price_analysis:
            data = price_analysis[band]
            print(f"{band}: {data['count']} trades, {data['win_rate']:.1f}% win rate, ${data['avg_pnl']:.3f} avg PnL")
    
    print("\n--- Calibration Recommendations ---")
    
    # Price floor recommendation
    below_20c = price_analysis.get("below_20c", {})
    band_20_35 = price_analysis.get("20c_35c", {})
    band_35_50 = price_analysis.get("35c_50c", {})
    
    if below_20c.get('count', 0) > 0:
        below_20c_winrate = below_20c.get('win_rate', 0)
        print(f"\nPrice Floor Analysis:")
        print(f"  Below 20c: {below_20c_winrate:.1f}% win rate (currently blocked)")
        
        if band_20_35.get('count', 0) > 0:
            band_20_35_winrate = band_20_35.get('win_rate', 0)
            print(f"  20c-35c: {band_20_35_winrate:.1f}% win rate")
            
            if band_20_35_winrate < 5.0:
                print(f"  ⚠️  20c-35c band also shows poor performance (<5% win rate)")
                print(f"  RECOMMENDATION: Consider raising price floor to 35c")
            else:
                print(f"  ✓  20c floor is appropriate (20c-35c shows acceptable performance)")
    
    # Distance limit recommendation
    print(f"\nDistance Limit Analysis:")
    print(f"  Current: guardrails_max_dist_pct_trade = 2.0%")
    print(f"  RECOMMENDATION: No change (need spot price data for distance analysis)")
    
    # Per-asset calibration
    print(f"\nPer-Asset Calibration:")
    print(f"  Current: All assets share same profile values")
    print(f"  RECOMMENDATION: Based on PnL audit, consider:")
    print(f"    - BTC/ETH: May tolerate lower price floor (more liquid)")
    print(f"    - SOL/XRP/DOGE: May need higher price floor (less liquid, more volatile)")
    
    print("\n--- Suggested Profile Changes ---")
    print("""
# Option 1: Conservative (if 20c-35c remains poor)
guardrails:
  min_contract_price_cents: 35  # Raise from 20c to 35c

# Option 2: Moderate (current 20c, monitor 20c-35c band)
guardrails:
  min_contract_price_cents: 20  # Keep at 20c, add monitoring

# Option 3: Per-asset calibration (future enhancement)
guardrails_per_asset:
  BTC:
    min_contract_price_cents: 15
  ETH:
    min_contract_price_cents: 15
  SOL:
    min_contract_price_cents: 25
  XRP:
    min_contract_price_cents: 25
  DOGE:
    min_contract_price_cents: 30
    """)

if __name__ == "__main__":
    suggest_calibration()
