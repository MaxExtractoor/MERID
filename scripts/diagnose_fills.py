"""Diagnostic script to check incomplete fills in the database."""
import sqlite3

def check_fills():
    conn = sqlite3.connect('data/fills_ledger.db')
    cursor = conn.cursor()
    
    # Check total fills
    cursor.execute('SELECT COUNT(*) FROM fills')
    total = cursor.fetchone()[0]
    print(f'Total fills: {total}')
    
    # Check incomplete fills
    cursor.execute('''
        SELECT fill_id, count_fp, price_cents, yes_price, no_price, 
               market_ticker, side, action, ingestion_source
        FROM fills 
        WHERE count_fp = 0 OR price_cents = 0 OR yes_price IS NULL OR no_price IS NULL
        LIMIT 10
    ''')
    incomplete = cursor.fetchall()
    print(f'\nIncomplete fills in DB: {len(incomplete)}')
    
    for row in incomplete:
        print(f"\nFill ID: {row[0]}")
        print(f"  Ticker: {row[4]}")
        print(f"  Side: {row[5]}")
        print(f"  Action: {row[6]}")
        print(f"  Count: {row[1]}")
        print(f"  Price cents: {row[2]}")
        print(f"  Yes price: {row[3]}")
        print(f"  No price: {row[7]}")
        print(f"  Source: {row[8]}")
    
    # Check sample of complete fills for comparison
    cursor.execute('''
        SELECT fill_id, count_fp, price_cents, yes_price, no_price,
               market_ticker, side, action, ingestion_source
        FROM fills 
        WHERE count_fp > 0 AND price_cents > 0
        LIMIT 5
    ''')
    complete = cursor.fetchall()
    print(f'\nSample complete fills: {len(complete)}')
    
    for row in complete:
        print(f"\nFill ID: {row[0]}")
        print(f"  Ticker: {row[4]}")
        print(f"  Count: {row[1]}")
        print(f"  Price cents: {row[2]}")
    
    conn.close()

if __name__ == '__main__':
    check_fills()
