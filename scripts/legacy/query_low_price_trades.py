import sqlite3
import json

conn = sqlite3.connect(r'c:\Dev\MERID\data\kalshi_fills.db')
cursor = conn.cursor()

# Query for DOGE and XRP trades, sorted by price
query = """
SELECT market_ticker, side, action, yes_price_dollars, no_price_dollars, 
       proceeds_dollars, created_time, raw_payload
FROM kalshi_fills
WHERE market_ticker LIKE '%DOGE%' OR market_ticker LIKE '%XRP%'
ORDER BY yes_price_dollars ASC, no_price_dollars ASC
LIMIT 20
"""

cursor.execute(query)
rows = cursor.fetchall()

print("DOGE/XRP trades (sorted by price):")
print("=" * 120)
for row in rows:
    ticker, side, action, yes_price, no_price, proceeds, created_time, raw = row
    price = yes_price if side == 'yes' else no_price
    print(f"{ticker} | {side} {action} | price=${price:.3f} | proceeds=${proceeds:.3f} | {created_time}")
    
    # Try to extract more info from raw payload
    try:
        payload = json.loads(raw)
        if 'ticker' in payload:
            print(f"  Raw ticker: {payload['ticker']}")
    except:
        pass

conn.close()
