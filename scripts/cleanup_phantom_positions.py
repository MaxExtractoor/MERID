#!/usr/bin/env python3
"""Clean up phantom positions in PostgreSQL.

1. Deletes test-ticker fills (unit-test contamination) from kalshi_fills.
2. Rebuilds the kalshi_positions materialized view with settlement-aware
   filtering (30-minute window, test tickers excluded).
3. Verifies the resulting position count.

Usage:
    python scripts/cleanup_phantom_positions.py
"""

import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass


async def cleanup():
    import asyncpg

    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "merid"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "merid"),
    )
    try:
        # 1. Delete test-ticker fills (unit test contamination)
        deleted = await conn.execute("""
            DELETE FROM kalshi_fills
            WHERE market_ticker ILIKE '%TEST%'
               OR market_ticker SIMILAR TO 'KX(BTC|ETH|SOL|XRP|DOGE)-(15M|1H|H|D|W|M|A)'
               OR fill_id LIKE 'concurrent-fill-%'
               OR fill_id LIKE 'duplicate-test-%'
               OR fill_id LIKE 'pos-%'
               OR fill_id LIKE 'fill-0%'
        """)
        print(f"Deleted test fills: {deleted}")

        # 2. Rebuild materialized view with settlement-aware definition
        await conn.execute("DROP MATERIALIZED VIEW IF EXISTS kalshi_positions")
        await conn.execute("""
            CREATE MATERIALIZED VIEW kalshi_positions AS
            SELECT 
                market_ticker,
                side,
                SUM(CASE WHEN action = 'buy' THEN count ELSE -count END) as net_contracts,
                AVG(CASE WHEN action = 'buy' THEN price_cents END) as avg_entry_price_cents,
                MAX(created_at) as last_updated
            FROM kalshi_fills
            WHERE created_at > NOW() - INTERVAL '30 minutes'
              AND market_ticker NOT ILIKE '%TEST%'
              AND market_ticker NOT SIMILAR TO 'KX(BTC|ETH|SOL|XRP|DOGE)-(15M|1H|H|D|W|M|A)'
            GROUP BY market_ticker, side
            HAVING SUM(CASE WHEN action = 'buy' THEN count ELSE -count END) != 0
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX idx_kalshi_positions_unique 
            ON kalshi_positions(market_ticker, side)
        """)
        print("Materialized view rebuilt with settlement-aware filtering")

        # 3. Verify
        fills = await conn.fetchval("SELECT COUNT(*) FROM kalshi_fills")
        positions = await conn.fetchval("SELECT COUNT(*) FROM kalshi_positions")
        print(f"\nVerification: fills={fills} open_positions={positions}")
        if positions == 0:
            print("OK: No phantom positions remain")
        else:
            rows = await conn.fetch("SELECT * FROM kalshi_positions")
            print("WARNING: Positions still present:")
            for r in rows:
                print(f"  {dict(r)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(cleanup())
