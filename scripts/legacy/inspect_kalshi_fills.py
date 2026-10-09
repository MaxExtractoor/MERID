#!/usr/bin/env python3
"""Inspect kalshi_fills.db structure for PnL audit."""
import sqlite3
from pathlib import Path

db_path = Path("c:/Dev/MERID/data/kalshi_fills.db")
if not db_path.exists():
    print(f"Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print("Tables:", tables)

# For each table, show schema and sample rows
for table in tables:
    print(f"\n=== Table: {table} ===")
    cursor.execute(f"PRAGMA table_info({table})")
    columns = cursor.fetchall()
    print("Columns:")
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"Row count: {count}")
    
    if count > 0:
        cursor.execute(f"SELECT * FROM {table} LIMIT 3")
        rows = cursor.fetchall()
        print("Sample rows:")
        for row in rows:
            print(f"  {row}")

conn.close()
