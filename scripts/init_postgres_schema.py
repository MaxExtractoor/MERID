#!/usr/bin/env python3
"""
PostgreSQL Schema Initialization for MERID Kalshi Trading System

This script creates the PostgreSQL database schema for fills ledger and position tracking.
Replaces SQLite-based fills_ledger.db with PostgreSQL for better concurrency.

Usage:
    python scripts/init_postgres_schema.py
"""

import asyncio
import os
import sys
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

async def init_postgres_schema():
    """Initialize PostgreSQL schema for fills ledger."""
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Install with: pip install asyncpg")
        sys.exit(1)
    
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
    
    print(f"Connecting to PostgreSQL at {host}:{port} as {user}...")
    
    conn = None
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        print("Connected successfully!")
        
        # Create fills table
        print("Creating kalshi_fills table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kalshi_fills (
                fill_id TEXT PRIMARY KEY,
                trade_id TEXT,
                order_id TEXT,
                market_ticker TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('yes', 'no')),
                action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
                count INTEGER NOT NULL,
                price_cents INTEGER NOT NULL,
                fee_cost DECIMAL(10, 4),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                client_order_id TEXT,
                intent_id TEXT,
                agent_id TEXT,
                fill_source TEXT,
                raw_response JSONB
            )
        """)
        
        # Create indexes
        print("Creating indexes...")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kalshi_fills_market_ticker ON kalshi_fills(market_ticker)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kalshi_fills_created_at ON kalshi_fills(created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kalshi_fills_order_id ON kalshi_fills(order_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kalshi_fills_client_order_id ON kalshi_fills(client_order_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kalshi_fills_agent_id ON kalshi_fills(agent_id)")
        
        # Create dead-letter queue table
        print("Creating kalshi_fills_dlq table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kalshi_fills_dlq (
                id SERIAL PRIMARY KEY,
                fill_data JSONB NOT NULL,
                error_message TEXT,
                queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                processed_at TIMESTAMP WITH TIME ZONE,
                retry_count INTEGER DEFAULT 0
            )
        """)
        
        # Create portfolio event log table
        print("Creating portfolio_events table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_events (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                market_ticker TEXT,
                side TEXT,
                contracts INTEGER,
                price_cents INTEGER,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                metadata JSONB
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_events_timestamp ON portfolio_events(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_events_market_ticker ON portfolio_events(market_ticker)")
        
        # Create materialized view for positions
        print("Creating kalshi_positions materialized view...")
        # NOTE (2026-07-19): 15m Kalshi markets settle within ~15-20 minutes of the
        # last fill, and settlements do NOT generate closing fills. A position whose
        # latest fill is older than 30 minutes is settled - including it would create
        # phantom positions. Test tickers (e.g., KXBTC-15M, %TEST%) are excluded.
        await conn.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS kalshi_positions AS
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
        
        # Create unique index on materialized view
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kalshi_positions_unique 
            ON kalshi_positions(market_ticker, side)
        """)
        
        # Create function to refresh positions view
        print("Creating refresh_positions function...")
        await conn.execute("""
            CREATE OR REPLACE FUNCTION refresh_positions()
            RETURNS void AS $$
            BEGIN
                REFRESH MATERIALIZED VIEW CONCURRENTLY kalshi_positions;
            END;
            $$ LANGUAGE plpgsql
        """)
        
        print("\nOK: PostgreSQL schema initialized successfully!")
        print("\nTables created:")
        print("  - kalshi_fills (with indexes)")
        print("  - kalshi_fills_dlq (dead-letter queue)")
        print("  - portfolio_events")
        print("  - kalshi_positions (materialized view)")
        print("  - refresh_positions() function")
        
    except Exception as e:
        print(f"ERROR: Failed to initialize schema: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn:
            await conn.close()
            print("\nConnection closed.")

if __name__ == "__main__":
    asyncio.run(init_postgres_schema())
