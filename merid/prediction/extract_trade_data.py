"""Extract trade data from Kalshi fills database for side accuracy analysis.

This script pulls trade data from the last 48 hours from kalshi_fills.db
and converts it to TradeRecord format for analysis.
"""

import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from merid.prediction.agent_performance_tracker import TradeRecord

DB_PATH = Path("data/kalshi_fills.db")


def extract_trades_last_48h(db_path: Path = DB_PATH) -> List[TradeRecord]:
    """Extract trades from the last 48 hours from kalshi_fills.db.
    
    Args:
        db_path: Path to kalshi_fills.db
        
    Returns:
        List of TradeRecord objects
    """
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return []
    
    # Calculate 48 hours ago timestamp
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=48)
    cutoff_timestamp = cutoff_time.timestamp()
    
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # First, check what tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Available tables: {tables}")
        
        trades = []
        
        # Try to find the fills table
        fills_table = None
        for table in tables:
            if 'fill' in table.lower():
                fills_table = table
                break
        
        if not fills_table:
            print("No fills table found in database")
            return []
        
        print(f"Using table: {fills_table}")
        
        # Get table schema
        cursor.execute(f"PRAGMA table_info({fills_table})")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Table columns: {columns}")
        
        # Query for fills in the last 48 hours
        # Try different timestamp column names
        timestamp_col = None
        for col in ['created_time', 'timestamp', 'created_at', 'fill_time', 'time', 'ts']:
            if col in columns:
                timestamp_col = col
                break
        
        if not timestamp_col:
            print("No timestamp column found")
            return []
        
        print(f"Using timestamp column: {timestamp_col}")
        
        query = f"""
        SELECT * FROM {fills_table}
        WHERE {timestamp_col} >= ?
        ORDER BY {timestamp_col} DESC
        """
        
        cursor.execute(query, (cutoff_timestamp,))
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} fills in the last 48 hours")
        
        # Print first row for debugging
        if rows:
            print(f"\nSample row data:")
            print(dict(rows[0]))
        
        for row in rows:
            row_dict = dict(row)
            
            # Extract relevant fields based on actual schema
            try:
                agent_id = row_dict.get('agent_id', 'UNKNOWN')
                market_id = row_dict.get('market_ticker', row_dict.get('ticker', 'UNKNOWN'))
                side = row_dict.get('side', 'unknown').lower()
                
                # Price is in dollars, convert to cents
                yes_price = row_dict.get('yes_price_dollars', 0)
                no_price = row_dict.get('no_price_dollars', 0)
                
                # Use yes_price for YES contracts, no_price for NO contracts
                if side == 'yes':
                    price_cents = int(yes_price * 100) if yes_price else 0
                else:
                    price_cents = int(no_price * 100) if no_price else 0
                
                contracts = int(row_dict.get('count_fp', 1))
                
                # Parse timestamp - it's an ISO string in the database
                ts_str = row_dict.get(timestamp_col)
                if ts_str:
                    try:
                        # Parse ISO format timestamp
                        if isinstance(ts_str, str):
                            entry_ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp()
                        else:
                            entry_ts = float(ts_str)
                    except (ValueError, AttributeError, TypeError):
                        entry_ts = time.time()
                else:
                    entry_ts = time.time()
                
                # Try to get velocity if available
                velocity = row_dict.get('velocity')
                
                # Try to get edge/confidence if available
                predicted_edge = row_dict.get('predicted_edge', row_dict.get('edge', 0.0))
                confidence = row_dict.get('confidence', 0.5)
                
                # Skip if essential fields are missing
                if not market_id or market_id == 'UNKNOWN':
                    print(f"Skipping row with missing market_id: {row_dict}")
                    continue
                
                # Skip if price is 0
                if price_cents == 0:
                    print(f"Skipping row with price_cents=0: {market_id} {side}")
                    continue
                
                trade = TradeRecord(
                    agent_id=agent_id,
                    market_id=market_id,
                    side=side,
                    entry_price_cents=price_cents,
                    contracts=contracts,
                    entry_ts=entry_ts,
                    predicted_edge=predicted_edge,
                    confidence=confidence,
                    velocity=velocity,
                )
                
                trades.append(trade)
                
            except Exception as e:
                print(f"Error processing row: {e}")
                print(f"Row data: {row_dict}")
                continue
        
        print(f"Successfully extracted {len(trades)} TradeRecord objects")
        return trades
    finally:
        conn.close()


def main():
    """Extract and print trade data summary."""
    trades = extract_trades_last_48h()
    
    if not trades:
        print("No trades found in the last 48 hours")
        return
    
    print(f"\n{'='*80}")
    print(f"TRADE DATA SUMMARY (Last 48 Hours)")
    print(f"{'='*80}")
    print(f"Total trades: {len(trades)}")
    
    # Group by agent
    from collections import defaultdict
    by_agent = defaultdict(list)
    for trade in trades:
        by_agent[trade.agent_id].append(trade)
    
    print(f"\nBy agent:")
    for agent, agent_trades in sorted(by_agent.items()):
        print(f"  {agent}: {len(agent_trades)} trades")
    
    # Group by asset
    by_asset = defaultdict(list)
    for trade in trades:
        asset = None
        for a in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if f"KX{a}" in trade.market_id.upper():
                asset = a
                break
        if asset:
            by_asset[asset].append(trade)
    
    print(f"\nBy asset:")
    for asset, asset_trades in sorted(by_asset.items()):
        print(f"  {asset}: {len(asset_trades)} trades")
    
    # Group by side
    by_side = defaultdict(list)
    for trade in trades:
        by_side[trade.side].append(trade)
    
    print(f"\nBy side:")
    for side, side_trades in sorted(by_side.items()):
        print(f"  {side}: {len(side_trades)} trades")
    
    # Time range
    if trades:
        timestamps = [t.entry_ts for t in trades if t.entry_ts]
        if timestamps:
            # Handle both numeric timestamps and ISO string timestamps
            try:
                oldest_ts = min(timestamps)
                newest_ts = max(timestamps)
                
                # Try to parse as ISO string first
                if isinstance(oldest_ts, str):
                    oldest = datetime.fromisoformat(oldest_ts.replace('Z', '+00:00'))
                    newest = datetime.fromisoformat(newest_ts.replace('Z', '+00:00'))
                else:
                    oldest = datetime.fromtimestamp(oldest_ts, timezone.utc)
                    newest = datetime.fromtimestamp(newest_ts, timezone.utc)
                
                print(f"\nTime range: {oldest} to {newest}")
            except Exception as e:
                print(f"\nTime range parsing error: {e}")
    
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
