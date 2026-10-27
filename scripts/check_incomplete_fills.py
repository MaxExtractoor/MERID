"""Diagnostic script to check incomplete fills in the database."""
import asyncio
import aiosqlite

async def check_fills():
    async with aiosqlite.connect('data/fills_ledger.db') as db:
        db.row_factory = aiosqlite.Row
        
        # Check total fills
        cursor = await db.execute('SELECT COUNT(*) as total FROM fills')
        total = (await cursor.fetchone())['total']
        print(f'Total fills in DB: {total}')
        
        # Check incomplete fills
        cursor = await db.execute('''
            SELECT fill_id, count_fp, price_cents, yes_price, no_price, 
                   market_ticker, side, action, ingestion_source
            FROM fills 
            WHERE count_fp = 0 OR price_cents = 0 OR yes_price IS NULL OR no_price IS NULL
            LIMIT 10
        ''')
        incomplete = await cursor.fetchall()
        print(f'\nIncomplete fills in DB: {len(incomplete)}')
        
        for row in incomplete:
            print(f"\nFill ID: {row['fill_id']}")
            print(f"  Ticker: {row['market_ticker']}")
            print(f"  Side: {row['side']}")
            print(f"  Action: {row['action']}")
            print(f"  Count: {row['count_fp']}")
            print(f"  Price cents: {row['price_cents']}")
            print(f"  Yes price: {row['yes_price']}")
            print(f"  No price: {row['no_price']}")
            print(f"  Source: {row['ingestion_source']}")
        
        # Check sample of complete fills for comparison
        cursor = await db.execute('''
            SELECT fill_id, count_fp, price_cents, yes_price, no_price,
                   market_ticker, side, action, ingestion_source
            FROM fills 
            WHERE count_fp > 0 AND price_cents > 0
            LIMIT 5
        ''')
        complete = await cursor.fetchall()
        print(f'\nSample complete fills: {len(complete)}')
        
        for row in complete:
            print(f"\nFill ID: {row['fill_id']}")
            print(f"  Ticker: {row['market_ticker']}")
            print(f"  Count: {row['count_fp']}")
            print(f"  Price cents: {row['price_cents']}")

if __name__ == '__main__':
    asyncio.run(check_fills())
