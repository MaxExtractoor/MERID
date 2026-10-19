# PostgreSQL Migration Plan for MERID Kalshi Trading System

## Executive Summary

Migrate from SQLite to PostgreSQL to fix position tracking desync and concurrency issues causing order rejections.

## Current Problems

1. **SQLite Lock Contention**
   - `data/kalshi_fills.db` experiences "database is locked" errors
   - Multiple concurrent writers (WebSocket + HTTP poller + reconciliation)
   - Retry logic causes fill loss during high-volume trading
   - SQLite is single-writer by design

2. **Position Tracking Desync**
   - REST API returns 0 positions but fills ledger shows 2 positions
   - Slot allocator incorrectly cleared when REST returns 0
   - WebSocket fills lost during reconnection (dead-letter queue)
   - Position cache not reflecting actual Kalshi positions

3. **Neo4j Contamination**
   - `merid/settings.py` requires NEO4J_PASSWORD for production
   - Neo4j imported but not used in 15m stack
   - Creates unnecessary dependency and startup validation failures

## Target Architecture

### PostgreSQL Schema

```sql
-- Fills table (replaces SQLite kalshi_fills.db)
CREATE TABLE kalshi_fills (
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
    -- JSONB for flexible Kalshi API responses
    raw_response JSONB,
    -- Indexes for common queries
    INDEX idx_market_ticker (market_ticker),
    INDEX idx_created_at (created_at),
    INDEX idx_order_id (order_id),
    INDEX idx_client_order_id (client_order_id)
);

-- Positions materialized view (for fast position queries)
CREATE MATERIALIZED VIEW kalshi_positions AS
SELECT 
    market_ticker,
    side,
    SUM(CASE WHEN action = 'buy' THEN count ELSE -count END) as net_contracts,
    AVG(CASE WHEN action = 'buy' THEN price_cents END) as avg_entry_price_cents,
    MAX(created_at) as last_updated
FROM kalshi_fills
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY market_ticker, side
HAVING SUM(CASE WHEN action = 'buy' THEN count ELSE -count END) != 0;

-- Refresh positions view every 5 seconds
CREATE OR REPLACE FUNCTION refresh_positions()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kalshi_positions;
END;
$$ LANGUAGE plpgsql;

-- Dead-letter queue for failed fills
CREATE TABLE kalshi_fills_dlq (
    id SERIAL PRIMARY KEY,
    fill_data JSONB NOT NULL,
    error_message TEXT,
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0
);
```

### Connection Pooling

Use `asyncpg` with connection pooling:

```python
import asyncpg
from asyncpg import create_pool

class PostgreSQLFillsLedger:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
    
    async def _ensure_pool(self):
        if self._pool is None:
            self._pool = await create_pool(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                user=os.getenv("POSTGRES_USER", "merid"),
                password=os.getenv("POSTGRES_PASSWORD"),
                database=os.getenv("POSTGRES_DB", "merid"),
                min_size=5,
                max_size=20,
                command_timeout=30.0
            )
    
    async def ingest_fill(self, fill: KalshiFill):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO kalshi_fills 
                   (fill_id, trade_id, order_id, market_ticker, side, action, 
                    count, price_cents, fee_cost, created_at, client_order_id, 
                    intent_id, agent_id, fill_source, raw_response)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                   ON CONFLICT (fill_id) DO NOTHING""",
                fill.fill_id, fill.trade_id, fill.order_id, fill.market_ticker,
                fill.side, fill.action, fill.count, fill.price_cents, fill.fee_cost,
                fill.created_at, fill.client_order_id, fill.intent_id, fill.agent_id,
                fill.fill_source, json.dumps(fill.raw_response)
            )
```

## Migration Steps

### Phase 1: Setup PostgreSQL (1 hour)

1. Install PostgreSQL on local machine or cloud instance
2. Create database and user:
   ```bash
   createdb merid
   psql -d merid -c "CREATE USER merid WITH PASSWORD 'your_password';"
   psql -d merid -c "GRANT ALL PRIVILEGES ON DATABASE merid TO merid;"
   ```
3. Add environment variables to `.env`:
   ```
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_USER=merid
   POSTGRES_PASSWORD=your_password
   POSTGRES_DB=merid
   ```

### Phase 2: Migrate Existing Data (30 minutes)

1. Export SQLite data:
   ```python
   import sqlite3
   import asyncpg
   
   async def migrate_sqlite_to_postgres():
       # Read from SQLite
       sqlite_conn = sqlite3.connect('data/kalshi_fills.db')
       cursor = sqlite_conn.cursor()
       cursor.execute("SELECT * FROM fills")
       rows = cursor.fetchall()
       
       # Write to PostgreSQL
       pool = await asyncpg.create_pool(...)
       async with pool.acquire() as conn:
           for row in rows:
               await conn.execute(
                   "INSERT INTO kalshi_fills (...) VALUES (...)",
                   *row
               )
   ```

### Phase 3: Update Code (2 hours)

1. Replace `aiosqlite` with `asyncpg` in `fills_ledger.py`
2. Update `_init_db()` to use PostgreSQL schema
3. Replace `_flush_to_db()` with PostgreSQL connection pool
4. Remove SQLite-specific retry logic (PostgreSQL handles concurrency)
5. Update `compute_net_positions()` to query materialized view

### Phase 4: Remove Neo4j Dependencies (30 minutes)

1. Remove NEO4J_* from `merid/settings.py` production validation
2. Remove Neo4j imports from startup_validations.py forbidden list
3. Comment out Neo4j initialization in memory/store.py

### Phase 5: Testing (1 hour)

1. Run existing fills_ledger tests
2. Test concurrent fill ingestion (WebSocket + HTTP)
3. Verify position reconciliation
4. Test dead-letter queue processing

### Phase 6: Deployment (30 minutes)

1. Stop production server
2. Run migration script
3. Update environment variables
4. Start production server
5. Monitor logs for errors

## Benefits

1. **No More Lock Contention**
   - PostgreSQL handles concurrent writes natively
   - No "database is locked" errors
   - No fill loss during high volume

2. **Real-Time Position Tracking**
   - Materialized view refreshed every 5 seconds
   - Position queries are O(1) instead of O(N)
   - No desync between fills ledger and position cache

3. **Flexible Schema**
   - JSONB stores raw Kalshi API responses
   - Schema changes don't break existing data
   - Easy to add new fields

4. **Production Ready**
   - Battle-tested in financial systems
   - Built-in replication and backup
   - Mature tooling and monitoring

## Rollback Plan

If migration fails:
1. Stop PostgreSQL-based server
2. Restore SQLite database from backup
3. Revert code changes
4. Restart with SQLite

## Timeline

- Phase 1: 1 hour
- Phase 2: 30 minutes
- Phase 3: 2 hours
- Phase 4: 30 minutes
- Phase 5: 1 hour
- Phase 6: 30 minutes

**Total: 5 hours**

## Risks

1. **Data Loss During Migration**
   - Mitigation: Backup SQLite before migration
   - Test migration on staging first

2. **Performance Regression**
   - Mitigation: Use connection pooling
   - Monitor query performance with EXPLAIN ANALYZE

3. **Environment Configuration**
   - Mitigation: Document all environment variables
   - Use .env file for configuration

## Success Criteria

1. No "database is locked" errors in logs
2. Position cache accurately reflects Kalshi positions
3. Slot allocator correctly tracks exposure
4. Orders no longer rejected due to position desync
5. Neo4j validation removed from production checks
