"""
Test suite for PostgreSQL created_at column migration in fills_ledger.py

This test suite validates the fix for the database schema error where
the kalshi_fills table was missing the created_at column, causing
"no such column: created_at" errors during fill persistence.

Fix:
- Added migration logic in _init_postgres() to check for and add created_at column
- Migration runs when table exists but column is missing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger


class TestPostgresCreatedAtMigration:
    """Test PostgreSQL created_at column migration."""
    
    @pytest.mark.asyncio
    async def test_migration_adds_created_at_column_when_missing(self):
        """Test that migration adds created_at column when it's missing."""
        # Mock the PostgreSQL pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        # Simulate table exists but created_at column is missing
        mock_conn.fetchval = AsyncMock(return_value=True)  # table exists
        mock_conn.fetch = AsyncMock(return_value=[
            {'column_name': 'fill_id'},
            {'column_name': 'trade_id'},
            {'column_name': 'order_id'},
            # created_at is NOT in the list
        ])
        
        # Mock the ALTER TABLE execution
        mock_conn.execute = AsyncMock()
        
        # Create ledger instance
        ledger = KalshiFillsLedger()
        ledger._postgres_pool = mock_pool
        ledger._use_postgres = True
        ledger._db_initialized = False
        
        # Run the migration
        await ledger._init_postgres()
        
        # Verify that ALTER TABLE was called to add created_at column
        alter_calls = [call for call in mock_conn.execute.call_args_list 
                      if 'ALTER TABLE kalshi_fills ADD COLUMN created_at' in str(call)]
        assert len(alter_calls) == 1, "Migration should add created_at column"
    
    @pytest.mark.asyncio
    async def test_migration_skips_when_created_at_exists(self):
        """Test that migration skips when created_at column already exists."""
        # Mock the PostgreSQL pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        # Simulate table exists with created_at column
        mock_conn.fetchval = AsyncMock(return_value=True)  # table exists
        mock_conn.fetch = AsyncMock(return_value=[
            {'column_name': 'fill_id'},
            {'column_name': 'trade_id'},
            {'column_name': 'order_id'},
            {'column_name': 'created_at'},  # created_at IS in the list
        ])
        
        # Mock the ALTER TABLE execution
        mock_conn.execute = AsyncMock()
        
        # Create ledger instance
        ledger = KalshiFillsLedger()
        ledger._postgres_pool = mock_pool
        ledger._use_postgres = True
        ledger._db_initialized = False
        
        # Run the migration
        await ledger._init_postgres()
        
        # Verify that ALTER TABLE was NOT called (column already exists)
        alter_calls = [call for call in mock_conn.execute.call_args_list 
                      if 'ALTER TABLE kalshi_fills ADD COLUMN created_at' in str(call)]
        assert len(alter_calls) == 0, "Migration should skip when created_at already exists"
    
    @pytest.mark.asyncio
    async def test_migration_creates_table_when_missing(self):
        """Test that migration creates table when it doesn't exist."""
        # Mock the PostgreSQL pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        # Simulate table does NOT exist
        mock_conn.fetchval = AsyncMock(return_value=False)  # table does not exist
        
        # Mock the CREATE TABLE execution
        mock_conn.execute = AsyncMock()
        
        # Create ledger instance
        ledger = KalshiFillsLedger()
        ledger._postgres_pool = mock_pool
        ledger._use_postgres = True
        ledger._db_initialized = False
        
        # Run the migration
        await ledger._init_postgres()
        
        # Verify that CREATE TABLE was called
        create_calls = [call for call in mock_conn.execute.call_args_list 
                       if 'CREATE TABLE IF NOT EXISTS kalshi_fills' in str(call)]
        assert len(create_calls) == 1, "Migration should create table when missing"
        
        # Verify created_at is in the CREATE TABLE statement
        create_stmt = str(create_calls[0])
        assert 'created_at TIMESTAMP WITH TIME ZONE NOT NULL' in create_stmt, \
            "CREATE TABLE should include created_at column"
    
    @pytest.mark.asyncio
    async def test_migration_handles_exceptions_gracefully(self):
        """Test that migration handles exceptions gracefully."""
        # Mock the PostgreSQL pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        
        # Simulate table exists but created_at column is missing
        mock_conn.fetchval = AsyncMock(return_value=True)  # table exists
        mock_conn.fetch = AsyncMock(return_value=[
            {'column_name': 'fill_id'},
            {'column_name': 'trade_id'},
            # created_at is NOT in the list
        ])
        
        # Mock ALTER TABLE to raise an exception
        mock_conn.execute = AsyncMock(side_effect=Exception("Database error"))
        
        # Create ledger instance
        ledger = KalshiFillsLedger()
        ledger._postgres_pool = mock_pool
        ledger._use_postgres = True
        ledger._db_initialized = False
        
        # Run the migration - should not raise exception
        try:
            await ledger._init_postgres()
            # Migration should handle exception gracefully
            assert True, "Migration should handle exceptions gracefully"
        except Exception as e:
            pytest.fail(f"Migration should handle exceptions gracefully, but raised: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
