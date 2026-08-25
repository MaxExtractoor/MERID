import sqlite3
import json

conn = sqlite3.connect('kalshi_fills.db')
cursor = conn.cursor()

# Pick a potential exit: side=no, action=sell
exit_fill_id = '5d1e0538-2c7e-519e-4751-a12821416280'
exit_ticker = 'KXDOGE15M-26AUG071345-45'

print(f"Tracing potential exit order: {exit_fill_id}")
print(f"Ticker: {exit_ticker}\n")

# Get the exit fill details
cursor.execute("""
    SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
           yes_price_dollars, no_price_dollars, created_at, raw_payload
    FROM kalshi_fills 
    WHERE fill_id = ?
""", (exit_fill_id,))
exit_fill = cursor.fetchone()

if exit_fill:
    print("EXIT FILL:")
    print(f"  Fill ID: {exit_fill[0]}")
    print(f"  Order ID: {exit_fill[1]}")
    print(f"  Client Order ID: {exit_fill[2]}")
    print(f"  Ticker: {exit_fill[3]}")
    print(f"  Side: {exit_fill[4]}")
    print(f"  Action: {exit_fill[5]}")
    print(f"  Count: {exit_fill[6]}")
    print(f"  Created: {exit_fill[9]}")
    
    if exit_fill[10]:
        raw = json.loads(exit_fill[10])
        print(f"  Raw API: action={raw.get('action')}, book_side={raw.get('book_side')}, outcome_side={raw.get('outcome_side')}")

# Look for corresponding entry fills for the same ticker
print(f"\nLooking for entry fills for ticker {exit_ticker}...")
cursor.execute("""
    SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
           yes_price_dollars, no_price_dollars, created_at, raw_payload
    FROM kalshi_fills 
    WHERE market_ticker = ? AND action = 'buy'
    ORDER BY created_at ASC
""", (exit_ticker,))
entry_fills = cursor.fetchall()

print(f"\nEntry fills for {exit_ticker} ({len(entry_fills)} found):")
for fill in entry_fills:
    print(f"\n  Fill ID: {fill[0]}")
    print(f"    Order ID: {fill[1]}")
    print(f"    Side: {fill[4]}, Action: {fill[5]}, Count: {fill[6]}")
    print(f"    Created: {fill[9]}")
    
    if fill[10]:
        raw = json.loads(fill[10])
        print(f"    Raw API: action={raw.get('action')}, book_side={raw.get('book_side')}, outcome_side={raw.get('outcome_side')}")

conn.close()
