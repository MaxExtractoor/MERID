#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script for MERID Kalshi Trading System

This script migrates existing SQLite fills ledger data to PostgreSQL.
Run this after initializing the PostgreSQL schema with init_postgres_schema.py.

Usage:
    python scripts/migrate_sqlite_to_postgres.py
"""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file so POSTGRES_* variables are available
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

async def migrate_sqlite_to_postgres():
    """Migrate SQLite fills ledger to PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Install with: pip install asyncpg")
        sys.exit(1)
    
    # SQLite database path
    sqlite_db_path = project_root / "data" / "kalshi_fills.db"
    
    if not sqlite_db_path.exists():
        print(f"WARNING: SQLite database not found at {sqlite_db_path}")
        print("No data to migrate. Exiting.")
        return
    
    # Get connection parameters from environment or defaults
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "merid")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB", "merid")
    
    if not password:
        print("ERROR: POSTGRES_PASSWORD environment variable required")
        print("Set it with: export POSTGRES_PASSWORD=your_password")
        sys.exit(1)
    
    print(f"Reading from SQLite: {sqlite_db_path}")
    print(f"Writing to PostgreSQL: {host}:{port}/{database}")
    
    # Connect to SQLite
    sqlite_conn = None
    postgres_conn = None
    
    try:
        sqlite_conn = sqlite3.connect(str(sqlite_db_path))
        sqlite_conn.row_factory = sqlite3.Row
        cursor = sqlite_conn.cursor()
        
        # Check if fills table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kalshi_fills'")
        if not cursor.fetchone():
            print("WARNING: No 'kalshi_fills' table found in SQLite database")
            return
        
        # Get all fills from SQLite
        cursor.execute("SELECT * FROM kalshi_fills")
        rows = cursor.fetchall()
        
        if not rows:
            print("No fills found in SQLite database")
            return
        
        print(f"Found {len(rows)} fills in SQLite database")
        
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL...")
        postgres_conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        print("Connected to PostgreSQL!")
        
        # Migrate fills
        migrated = 0
        skipped = 0
        errors = 0
        
        for row in rows:
            try:
                fill_dict = dict(row)
                
                # Convert SQLite row to PostgreSQL format
                fill_id = fill_dict.get('fill_id')
                if not fill_id:
                    skipped += 1
                    continue
                
                # Parse JSON fields if they exist (SQLite column: raw_payload)
                raw_response = None
                if fill_dict.get('raw_payload'):
                    try:
                        raw_response = json.loads(fill_dict['raw_payload'])
                    except (json.JSONDecodeError, TypeError):
                        raw_response = fill_dict['raw_payload']
                
                # Convert timestamp (SQLite column: created_time)
                created_at = fill_dict.get('created_time')
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    except ValueError:
                        created_at = datetime.now(timezone.utc)
                elif created_at is None:
                    created_at = datetime.now(timezone.utc)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                # Derive price_cents from side-specific dollar price
                side = fill_dict.get('side')
                if side == 'yes':
                    price_dollars = fill_dict.get('yes_price_dollars')
                else:
                    price_dollars = fill_dict.get('no_price_dollars')
                if price_dollars is None:
                    price_dollars = fill_dict.get('yes_price_dollars') or fill_dict.get('no_price_dollars') or 0
                price_cents = int(round(float(price_dollars) * 100))
                
                # Insert into PostgreSQL
                await postgres_conn.execute("""
                    INSERT INTO kalshi_fills 
                    (fill_id, trade_id, order_id, market_ticker, side, action, 
                     count, price_cents, fee_cost, created_at, client_order_id, 
                     intent_id, agent_id, fill_source, raw_response)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                    ON CONFLICT (fill_id) DO NOTHING
                """,
                    fill_id,
                    fill_dict.get('trade_id'),
                    fill_dict.get('order_id'),
                    fill_dict.get('market_ticker'),
                    side,
                    fill_dict.get('action'),
                    int(fill_dict.get('count_fp') or 0),
                    price_cents,
                    fill_dict.get('fee_cost'),
                    created_at,
                    fill_dict.get('client_order_id'),
                    fill_dict.get('intent_id'),
                    fill_dict.get('agent_id'),
                    fill_dict.get('fill_source'),
                    json.dumps(raw_response) if raw_response else None
                )
                
                migrated += 1
                
                if migrated % 100 == 0:
                    print(f"Migrated {migrated}/{len(rows)} fills...")
                    
            except Exception as e:
                errors += 1
                print(f"ERROR migrating fill {fill_dict.get('fill_id')}: {e}")
        
        print(f"\nMigration complete!")
        print(f"  Migrated: {migrated}")
        print(f"  Skipped: {skipped}")
        print(f"  Errors: {errors}")
        
        # Refresh materialized view
        print("\nRefreshing kalshi_positions materialized view...")
        try:
            await postgres_conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY kalshi_positions")
        except Exception:
            await postgres_conn.execute("REFRESH MATERIALIZED VIEW kalshi_positions")
        print("Materialized view refreshed!")
        
    except Exception as e:
        print(f"ERROR: Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if postgres_conn:
            await postgres_conn.close()
            print("PostgreSQL connection closed.")

if __name__ == "__main__":
    asyncio.run(migrate_sqlite_to_postgres())
