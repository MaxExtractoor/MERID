import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('merid_pnl_attribution.db')
cursor = conn.cursor()

# Get recent trade records (last 7 days)
cutoff_time = datetime.now() - timedelta(days=7)

cursor.execute("""
    SELECT * FROM trade_records 
    WHERE timestamp >= ?
    ORDER BY timestamp DESC
""", (cutoff_time.timestamp(),))

rows = cursor.fetchall()
columns = [desc[0] for desc in cursor.description]

print(f"Total trade records in last 7 days: {len(rows)}")
print("\nColumns:", columns)
print("\n" + "="*120)

# Group by trade_id to pair entries and exits
trades = {}
for row in rows:
    trade_id = row[6]  # trade_id
    if trade_id not in trades:
        trades[trade_id] = []
    trades[trade_id].append(row)

print(f"\nUnique trades: {len(trades)}")
print("\n" + "="*120)

# Show recent trades
print("\nRecent trades (last 20):")
print("-" * 120)

for i, (trade_id, trade_records) in enumerate(list(trades.items())[:20]):
    print(f"\nTrade ID: {trade_id}")
    for record in trade_records:
        trade_type = record[2]  # entry/exit
        symbol = record[1]
        timestamp = datetime.fromtimestamp(record[3]).strftime('%Y-%m-%d %H:%M:%S')
        price = record[4]
        quantity = record[5]
        agent_id = record[7]
        realized_pnl = record[15]
        exit_reason = record[12]
        
        print(f"  {trade_type.upper():5} | {symbol:40} | {timestamp} | ${price:.4f} | Qty: {quantity} | Agent: {agent_id}")
        if realized_pnl is not None:
            print(f"        Realized PnL: ${realized_pnl:.2f}")
        if exit_reason:
            print(f"        Exit Reason: {exit_reason}")

# Calculate round trips and PnL
print("\n" + "="*120)
print("\nRound Trip Analysis:")
print("-" * 120)

completed_trades = []
for trade_id, records in trades.items():
    if len(records) >= 2:
        # Look for entry and exit pairs
        entries = [r for r in records if r[2] == 'entry']
        exits = [r for r in records if r[2] == 'exit']
        
        if entries and exits:
            entry = entries[0]
            exit_rec = exits[0]
            
            symbol = entry[1]
            entry_price = entry[4]
            exit_price = exit_rec[4]
            entry_time = datetime.fromtimestamp(entry[3]).strftime('%Y-%m-%d %H:%M:%S')
            exit_time = datetime.fromtimestamp(exit_rec[3]).strftime('%Y-%m-%d %H:%M:%S')
            realized_pnl = exit_rec[15] if exit_rec[15] else 0
            exit_reason = exit_rec[12]
            
            completed_trades.append({
                'symbol': symbol,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': realized_pnl,
                'exit_reason': exit_reason
            })

print(f"Completed round trips: {len(completed_trades)}")

if completed_trades:
    print("\nRecent completed trades:")
    for trade in completed_trades[:15]:
        result = "WIN" if trade['pnl'] > 0 else "LOSS"
        print(f"{trade['entry_time']} -> {trade['exit_time']} | {trade['symbol']:40} | Entry: ${trade['entry_price']:.4f} | Exit: ${trade['exit_price']:.4f} | PnL: ${trade['pnl']:.2f} | {result}")
        if trade['exit_reason']:
            print(f"  Exit Reason: {trade['exit_reason']}")
    
    # Summary statistics
    print("\n" + "="*120)
    print("\nSummary Statistics:")
    print("-" * 120)
    
    wins = [t for t in completed_trades if t['pnl'] > 0]
    losses = [t for t in completed_trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in completed_trades)
    win_rate = len(wins) / len(completed_trades) * 100 if completed_trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    
    print(f"Total trades: {len(completed_trades)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Average win: ${avg_win:.2f}")
    print(f"Average loss: ${avg_loss:.2f}")
    
    # By asset
    print("\n" + "="*120)
    print("\nBy Asset:")
    print("-" * 120)
    
    from collections import defaultdict
    asset_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0})
    for trade in completed_trades:
        # Extract asset from symbol
        symbol = trade['symbol']
        asset = 'OTHER'
        if 'BTC' in symbol.upper():
            asset = 'BTC'
        elif 'ETH' in symbol.upper():
            asset = 'ETH'
        elif 'SOL' in symbol.upper():
            asset = 'SOL'
        elif 'XRP' in symbol.upper():
            asset = 'XRP'
        elif 'DOGE' in symbol.upper():
            asset = 'DOGE'
        
        if trade['pnl'] > 0:
            asset_stats[asset]['wins'] += 1
        else:
            asset_stats[asset]['losses'] += 1
        asset_stats[asset]['pnl'] += trade['pnl']
    
    for asset, stats in sorted(asset_stats.items()):
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        print(f"{asset:5} | {stats['wins']:2}W {stats['losses']:2}L | Win rate: {win_rate:5.1f}% | PnL: ${stats['pnl']:6.2f}")

conn.close()
