import sqlite3
import json

conn = sqlite3.connect(r'c:\Dev\MERID\data\kalshi_fills.db')
cursor = conn.cursor()

# Get recent fills with side distribution
cursor.execute("""
    SELECT market_ticker, side, action, yes_price_dollars, no_price_dollars, created_time, client_order_id, decision_trace_id
    FROM kalshi_fills
    ORDER BY created_time DESC
    LIMIT 50
""")
rows = cursor.fetchall()

print("Recent fills (last 50):")
print("=" * 140)
yes_count = 0
no_count = 0
for row in rows:
    ticker, side, action, yes_price, no_price, created_time, order_id, trace_id = row
    if side == 'yes':
        yes_count += 1
    else:
        no_count += 1
    print(f"{ticker} | side={side} | action={action} | yes=${yes_price} no=${no_price} | {created_time} | trace={trace_id}")

print("\n" + "=" * 140)
print(f"Side distribution: YES={yes_count} NO={no_count} (ratio: {yes_count/(yes_count+no_count) if (yes_count+no_count) > 0 else 0:.2%})")

# Check if there's a decision traces table
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%trace%'")
trace_tables = cursor.fetchall()
print(f"\nTrace tables: {trace_tables}")

conn.close()
