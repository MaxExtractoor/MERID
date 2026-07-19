#!/usr/bin/env python3
"""Clean test-fill contamination from SQLite kalshi_fills.db."""

import sqlite3
from pathlib import Path

db_path = Path("data/kalshi_fills.db")
if not db_path.exists():
    print("SQLite DB not found - nothing to clean")
    exit(0)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Delete test fills
cur.execute("""
    DELETE FROM kalshi_fills
    WHERE market_ticker LIKE '%TEST%'
       OR market_ticker IN ('KXBTC-15M','KXETH-15M','KXSOL-15M','KXXRP-15M','KXDOGE-15M')
       OR fill_id LIKE 'concurrent-fill-%'
       OR fill_id LIKE 'duplicate-test-%'
       OR fill_id LIKE 'pos-%'
       OR fill_id LIKE 'fill-0%'
""")
deleted = cur.rowcount
conn.commit()

remaining = cur.execute("SELECT COUNT(*) FROM kalshi_fills").fetchone()[0]
print(f"Deleted {deleted} test fills from SQLite")
print(f"Remaining fills: {remaining}")

conn.close()
