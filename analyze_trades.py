#!/usr/bin/env python3
"""Analyze trade history from Kalshi fills database."""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# Connect to fills database
db_path = r'c:\Dev\MERID\data\kalshi_fills.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all fills from the last 5 hours to capture completed trades
cutoff_time = datetime.now() - timedelta(hours=5)

# Query fills
cursor.execute("""
    SELECT fill_id, market_ticker, side, action, count_fp, yes_price_dollars, no_price_dollars, 
           fee_cost, proceeds_dollars, created_time, agent_id, fill_source
    FROM kalshi_fills 
    WHERE created_time >= ?
    ORDER BY created_time DESC
""", (cutoff_time.isoformat(),))

fills = cursor.fetchall()

print(f"Total fills in last 24 hours: {len(fills)}")
print("\n" + "="*80)

# Group by asset
asset_fills = defaultdict(list)
for fill in fills:
    # Extract asset from ticker
    ticker = fill[1]
    asset = 'N/A'
    if ticker:
        if 'BTC' in ticker.upper():
            asset = 'BTC'
        elif 'ETH' in ticker.upper():
            asset = 'ETH'
        elif 'SOL' in ticker.upper():
            asset = 'SOL'
        elif 'XRP' in ticker.upper():
            asset = 'XRP'
        elif 'DOGE' in ticker.upper():
            asset = 'DOGE'
    if asset != 'N/A':
        asset_fills[asset].append(fill)

print("\nFills by asset:")
for asset, fills_list in asset_fills.items():
    print(f"  {asset}: {len(fills_list)} fills")

print("\n" + "="*80)
print("\nRecent fills (last 30):")
print("-" * 80)
for fill in fills[:30]:
    fill_id, ticker, side, action, count, yes_price, no_price, fee, proceeds, created_time, agent_id, fill_source = fill
    # Extract asset from ticker
    asset = 'N/A'
    if ticker:
        if 'BTC' in ticker.upper():
            asset = 'BTC'
        elif 'ETH' in ticker.upper():
            asset = 'ETH'
        elif 'SOL' in ticker.upper():
            asset = 'SOL'
        elif 'XRP' in ticker.upper():
            asset = 'XRP'
        elif 'DOGE' in ticker.upper():
            asset = 'DOGE'
    price = yes_price if yes_price else (no_price if no_price else 0)
    print(f"{created_time} | {asset:5} | {side:3} {action:4} | {count:3} contracts | ${price:.4f} | ${proceeds or 0:.2f} | {fill_source}")

# Try to pair entry/exit fills by market ticker
print("\n" + "="*80)
print("\nAttempting to pair entry/exit fills by market...")
print("-" * 80)

# Group fills by market ticker
market_fills = defaultdict(list)
for fill in fills:
    ticker = fill[1]
    if ticker:
        market_fills[ticker].append(fill)

# Look for buy/sell pairs
paired_trades = []
for ticker, market_fill_list in market_fills.items():
    # Sort by time
    market_fill_list.sort(key=lambda x: x[9])  # created_time
    
    # Look for buy followed by sell (or vice versa)
    for i in range(len(market_fill_list) - 1):
        entry = market_fill_list[i]
        exit_fill = market_fill_list[i + 1]
        
        entry_side = entry[2]  # yes/no
        entry_action = entry[3]  # buy/sell
        exit_side = exit_fill[2]
        exit_action = exit_fill[3]
        
        # Check if this is a complete round trip
        if entry_action == 'buy' and exit_action == 'sell':
            entry_price = entry[5] if entry[5] else (entry[6] if entry[6] else 0)
            exit_price = exit_fill[5] if exit_fill[5] else (exit_fill[6] if exit_fill[6] else 0)
            entry_proceeds = entry[8] or 0
            exit_proceeds = exit_fill[8] or 0
            
            # Calculate PnL
            pnl = exit_proceeds + entry_proceeds  # entry is negative (cost), exit is positive (proceeds)
            
            # Extract asset
            asset = 'N/A'
            if 'BTC' in ticker.upper():
                asset = 'BTC'
            elif 'ETH' in ticker.upper():
                asset = 'ETH'
            elif 'SOL' in ticker.upper():
                asset = 'SOL'
            elif 'XRP' in ticker.upper():
                asset = 'XRP'
            elif 'DOGE' in ticker.upper():
                asset = 'DOGE'
            
            paired_trades.append({
                'ticker': ticker,
                'asset': asset,
                'entry_time': entry[9],
                'exit_time': exit_fill[9],
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': pnl,
                'side': entry_side
            })

print(f"\nFound {len(paired_trades)} completed round-trip trades")

if paired_trades:
    print("\nCompleted trades:")
    print("-" * 80)
    for trade in paired_trades:
        result = "WIN" if trade['pnl'] > 0 else "LOSS"
        print(f"{trade['entry_time']} | {trade['asset']:5} | {trade['side']:3} | Entry: ${trade['entry_price']:.4f} | Exit: ${trade['exit_price']:.4f} | PnL: ${trade['pnl']:.2f} | {result}")
    
    # Summary statistics
    print("\n" + "="*80)
    print("\nSummary Statistics:")
    print("-" * 80)
    
    wins = [t for t in paired_trades if t['pnl'] > 0]
    losses = [t for t in paired_trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in paired_trades)
    win_rate = len(wins) / len(paired_trades) * 100 if paired_trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    
    print(f"Total trades: {len(paired_trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Average win: ${avg_win:.2f}")
    print(f"Average loss: ${avg_loss:.2f}")
    
    # By asset
    print("\n" + "="*80)
    print("\nBy Asset:")
    print("-" * 80)
    asset_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0})
    for trade in paired_trades:
        asset = trade['asset']
        if trade['pnl'] > 0:
            asset_stats[asset]['wins'] += 1
        else:
            asset_stats[asset]['losses'] += 1
        asset_stats[asset]['pnl'] += trade['pnl']
    
    for asset, stats in asset_stats.items():
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        print(f"{asset:5} | {stats['wins']:2}W {stats['losses']:2}L | Win rate: {win_rate:5.1f}% | PnL: ${stats['pnl']:6.2f}")

conn.close()
