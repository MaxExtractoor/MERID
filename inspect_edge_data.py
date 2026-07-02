#!/usr/bin/env python3
"""Inspect edge-related databases for PnL audit."""
import sqlite3
from pathlib import Path

dbs = [
    "c:/Dev/MERID/data/realized_edge.db",
    "c:/Dev/MERID/data/signals.db",
    "c:/Dev/MERID/merid_pnl_attribution.db",
]

for db_path in dbs:
    path = Path(db_path)
    if not path.exists():
        print(f"\n=== Database not found: {db_path} ===")
        continue
    
    print(f"\n=== Database: {db_path} ===")
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables:", tables)
    
    # For each table, show schema and row count
    for table in tables:
        print(f"\n  Table: {table}")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        print("  Columns:")
        for col in columns:
            print(f"    {col[1]} ({col[2]})")
        
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  Row count: {count}")
        
        if count > 0 and count <= 5:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            print("  All rows:")
            for row in rows:
                print(f"    {row}")
        elif count > 0:
            cursor.execute(f"SELECT * FROM {table} LIMIT 2")
            rows = cursor.fetchall()
            print("  Sample rows:")
            for row in rows:
                print(f"    {row}")
    
    conn.close()
