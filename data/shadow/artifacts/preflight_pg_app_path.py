"""PostgreSQL application-path preflight check."""
from __future__ import annotations

import asyncio

import asyncpg


async def main():
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="merid",
        password="merid",
        database="merid",
    )
    print("[PG-PREFLIGHT] connected to merid database")

    # Verify tables from schema initialization are present.
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('kalshi_fills', 'kalshi_fills_dlq', 'portfolio_events')
        ORDER BY table_name
        """
    )
    print(f"[PG-PREFLIGHT] expected tables: { [r['table_name'] for r in rows] }")

    # Insert and rollback a harmless paper lifecycle event.
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(
            """
            INSERT INTO portfolio_events (
                event_type, market_ticker, metadata
            ) VALUES ('preflight_paper_heartbeat', 'KXBTC15M-TEST-01', '{"source": "preflight", "paper": true, "run_id": "preflight"}'::jsonb)
            """
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM portfolio_events WHERE metadata->>'run_id' = 'preflight'"
        )
        print(f"[PG-PREFLIGHT] paper lifecycle event visible in transaction: count={count}")
    finally:
        await tr.rollback()
    print("[PG-PREFLIGHT] transaction rolled back cleanly")


if __name__ == "__main__":
    asyncio.run(main())
