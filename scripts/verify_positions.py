#!/usr/bin/env python3
"""Verify position counts across SQLite and PostgreSQL."""

import asyncio
import os
import sqlite3
from pathlib import Path

project_root = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

# SQLite check
sqlite_path = project_root / "data/kalshi_fills.db"
if sqlite_path.exists():
    conn = sqlite3.connect(str(sqlite_path))
    sqlite_fills = conn.execute("SELECT COUNT(*) FROM kalshi_fills").fetchone()[0]
    conn.close()
    print(f"SQLite fills: {sqlite_fills}")
else:
    print("SQLite DB not found")
    sqlite_fills = 0

# PostgreSQL check
async def check_postgres():
    import asyncpg
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "merid"),
        password=os.getenv("POSTGRES_PASSWORD"),
        database=os.getenv("POSTGRES_DB", "merid"),
    )
    pg_fills = await conn.fetchval("SELECT COUNT(*) FROM kalshi_fills")
    pg_positions = await conn.fetchval("SELECT COUNT(*) FROM kalshi_positions")
    await conn.close()
    print(f"PostgreSQL fills: {pg_fills}")
    print(f"PostgreSQL open_positions: {pg_positions}")
    return pg_positions

pg_positions = asyncio.run(check_postgres())

if pg_positions == 0:
    print("\nOK: No phantom positions remain")
else:
    print(f"\nWARNING: {pg_positions} phantom positions still present")
