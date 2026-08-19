"""Append-Only Event Log for Kalshi Portfolio Events.

This module provides:
- PortfolioEventLog: SQLite-based append-only event log with sequence IDs
- Event ingestion from various sources (fills, orders, settlements, cash events)
- Deterministic replay capability for state reconstruction
- Thread-safe operations for concurrent access

Design principles:
- Append-only: Events are never deleted or modified
- Sequence ID: Monotonically increasing integer ensures ordering
- Idempotent: Duplicate events (same event_id) are rejected
- Thread-safe: Lock-protected for concurrent access
"""

from __future__ import annotations

import os
import threading
import time as _time
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

# PostgreSQL support (replaces SQLite)
try:
    import asyncpg
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    asyncpg = None

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_models import (
    PortfolioEvent,
    EventType,
    CashEventType,
    Fill,
    Order,
    Position,
    CashLedgerEntry,
)

logger = get_logger("merid.event_venues.kalshi.portfolio_event_log")


# ═══════════════════════════════════════════════════════════════════════════
# Database Configuration
# ═══════════════════════════════════════════════════════════════════════════

_EVENT_LOG_DB_PATH: str = os.getenv(
    "MERID_PORTFOLIO_EVENT_LOG_DB",
    os.path.join(os.path.dirname(__file__), "portfolio_event_log.db")
)

_DB_TIMEOUT: int = int(os.getenv("MERID_EVENT_LOG_DB_TIMEOUT_MS", "30000"))
_DB_BUSY_TIMEOUT_MS: int = int(os.getenv("MERID_EVENT_LOG_DB_BUSY_TIMEOUT_MS", "30000"))
_DB_RETRY_ATTEMPTS: int = int(os.getenv("MERID_EVENT_LOG_DB_RETRY_ATTEMPTS", "3"))
_DB_RETRY_DELAY_INITIAL: float = float(os.getenv("MERID_EVENT_LOG_DB_RETRY_DELAY_INITIAL", "0.05"))
_DB_RETRY_DELAY_MAX: float = float(os.getenv("MERID_EVENT_LOG_DB_RETRY_DELAY_MAX", "0.5"))


def _postgres_required() -> bool:
    """Return True when PostgreSQL persistence is mandatory (soak/audit mode)."""
    return os.getenv("MERID_POSTGRES_REQUIRED", "").strip().lower() in ("1", "true")


# ═══════════════════════════════════════════════════════════════════════════
# Event Log Implementation
# ═══════════════════════════════════════════════════════════════════════════

class PortfolioEventLog:
    """Append-only event log for portfolio events.
    
    Thread-safe singleton that stores all portfolio events in SQLite
    with monotonically increasing sequence IDs for deterministic replay.
    """
    
    _instance: Optional["PortfolioEventLog"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "PortfolioEventLog":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._db_path = _EVENT_LOG_DB_PATH
        self._local_lock = threading.Lock()
        self._use_postgres = POSTGRES_AVAILABLE and os.getenv("POSTGRES_PASSWORD")
        if _postgres_required() and not self._use_postgres:
            raise RuntimeError(
                "MERID_POSTGRES_REQUIRED is set but PostgreSQL is not configured "
                "(asyncpg unavailable or POSTGRES_PASSWORD missing)"
            )
        self._postgres_pool = None
        self._initialized = True
        self._init_db()
        
        logger.info(
            "PortfolioEventLog initialized (PostgreSQL=%s) at %s",
            self._use_postgres,
            self._db_path
        )
    
    async def _ensure_postgres_pool(self) -> asyncpg.Pool:
        """Ensure PostgreSQL connection pool is initialized.

        If MERID_POSTGRES_REQUIRED is set, a connection failure is fatal and
        raises instead of silently falling back to SQLite.
        """
        if self._postgres_pool is None and self._use_postgres:
            try:
                from merid.settings import get_settings
                settings = get_settings()
                
                self._postgres_pool = await asyncpg.create_pool(
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    database=settings.POSTGRES_DB,
                    min_size=2,
                    max_size=10,
                    command_timeout=30.0
                )
                logger.info("PortfolioEventLog PostgreSQL connection pool established")
            except Exception as e:
                logger.error(f"Failed to create PostgreSQL pool: {e}")
                if _postgres_required():
                    raise RuntimeError(f"PostgreSQL required for soak but unavailable: {e}") from e
                self._use_postgres = False
                logger.warning("PortfolioEventLog falling back to SQLite")
        
        return self._postgres_pool
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a SQLite database connection with retry logic (fallback)."""
        import sqlite3
        
        for attempt in range(_DB_RETRY_ATTEMPTS):
            try:
                return sqlite3.connect(
                    self._db_path,
                    timeout=_DB_BUSY_TIMEOUT_MS / 1000,
                    check_same_thread=False,
                )
            except sqlite3.OperationalError as e:
                if "database is locked" not in str(e):
                    raise
                delay = min(
                    _DB_RETRY_DELAY_INITIAL * (2 ** attempt),
                    _DB_RETRY_DELAY_MAX
                )
                logger.warning(
                    "EventLog DB busy (attempt %d/%d), retrying in %.2fs: %s",
                    attempt + 1,
                    _DB_RETRY_ATTEMPTS,
                    delay,
                    e
                )
                _time.sleep(delay)
        
        raise RuntimeError("Failed to acquire database connection after retries")
    
    def _init_db(self) -> None:
        """Initialize database schema (PostgreSQL or SQLite)."""
        if self._use_postgres:
            # PostgreSQL initialization is handled by init_postgres_schema.py
            # Just log that we're using PostgreSQL
            logger.info("PortfolioEventLog using PostgreSQL (schema initialized by init_postgres_schema.py)")
        else:
            self._init_sqlite()
    
    def _init_sqlite(self) -> None:
        """Initialize SQLite schema (fallback)."""
        import sqlite3
        
        conn = self._get_connection()
        try:
            # Events table - append-only with sequence ID
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_events (
                    event_id TEXT PRIMARY KEY,
                    sequence_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Index for efficient queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_sequence 
                ON portfolio_events(sequence_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_account 
                ON portfolio_events(account_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type 
                ON portfolio_events(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp 
                ON portfolio_events(timestamp)
            """)
            
            # Sequence counter table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sequence_counter (
                    counter INTEGER PRIMARY KEY
                )
            """)
            
            # Initialize sequence counter if empty
            cursor = conn.execute("SELECT counter FROM sequence_counter")
            if cursor.fetchone() is None:
                conn.execute("INSERT INTO sequence_counter (counter) VALUES (0)")
            
            conn.commit()
            logger.debug("PortfolioEventLog SQLite schema initialized")
        finally:
            conn.close()
    
    def _get_next_sequence_id(self, conn) -> int:
        """Get the next sequence ID atomically."""
        if self._use_postgres:
            # PostgreSQL uses SERIAL for auto-increment
            # This is handled by the database schema
            return 0  # Placeholder, actual sequence ID generated by DB
        else:
            # SQLite manual sequence counter
            cursor = conn.execute(
                "UPDATE sequence_counter SET counter = counter + 1 RETURNING counter"
            )
            result = cursor.fetchone()
            if result is None:
                # Fallback: get current and increment
                cursor = conn.execute("SELECT counter FROM sequence_counter")
                current = cursor.fetchone()[0]
                new_id = current + 1
                conn.execute("UPDATE sequence_counter SET counter = ?", (new_id,))
                return new_id
            return result[0]
    
    async def append_event(self, event: PortfolioEvent) -> bool:
        """Append an event to the log (idempotent).
        
        Args:
            event: PortfolioEvent to append
            
        Returns:
            True if event was appended, False if duplicate (event_id already exists)
        """
        if self._use_postgres:
            return await self._append_event_postgres(event)
        else:
            return self._append_event_sqlite(event)
    
    async def _append_event_postgres(self, event: PortfolioEvent) -> bool:
        """Append event to PostgreSQL."""
        pool = await self._ensure_postgres_pool()
        if not pool:
            logger.error("PostgreSQL pool not available, cannot append event")
            return False
        
        async with pool.acquire() as conn:
            try:
                # Check for duplicate event_id
                exists = await conn.fetchval(
                    "SELECT event_id FROM portfolio_events WHERE event_id = $1",
                    event.event_id
                )
                if exists:
                    logger.debug(
                        "EventLog: duplicate event_id %s, skipping",
                        event.event_id
                    )
                    return False
                
                # Insert event (PostgreSQL uses SERIAL for sequence_id)
                await conn.execute("""
                    INSERT INTO portfolio_events 
                    (event_type, market_ticker, side, contracts, price_cents, timestamp, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, (
                    event.event_type.value,
                    getattr(event, 'market_ticker', None),
                    getattr(event, 'side', None),
                    getattr(event, 'contracts', None),
                    getattr(event, 'price_cents', None),
                    event.timestamp,
                    json.dumps(event.data) if isinstance(event.data, dict) else str(event.data)
                ))
                
                logger.debug(
                    "EventLog: appended event_id=%s type=%s",
                    event.event_id,
                    event.event_type.value
                )
                return True
            except Exception as e:
                logger.warning(
                    "EventLog: error appending event %s: %s",
                    event.event_id,
                    e
                )
                return False
    
    def _append_event_sqlite(self, event: PortfolioEvent) -> bool:
        """Append event to SQLite (fallback)."""
        import sqlite3
        
        with self._local_lock:
            conn = self._get_connection()
            try:
                # Check for duplicate event_id
                cursor = conn.execute(
                    "SELECT event_id FROM portfolio_events WHERE event_id = ?",
                    (event.event_id,)
                )
                if cursor.fetchone() is not None:
                    logger.debug(
                        "EventLog: duplicate event_id %s, skipping",
                        event.event_id
                    )
                    return False
                
                # Assign sequence ID if not set
                if event.sequence_id == 0:
                    sequence_id = self._get_next_sequence_id(conn)
                    # Create new event with assigned sequence ID
                    event = PortfolioEvent(
                        event_id=event.event_id,
                        sequence_id=sequence_id,
                        event_type=event.event_type,
                        account_id=event.account_id,
                        timestamp=event.timestamp,
                        data=event.data,
                    )
                
                # Insert event
                conn.execute("""
                    INSERT INTO portfolio_events 
                    (event_id, sequence_id, event_type, account_id, timestamp, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.sequence_id,
                    event.event_type.value,
                    event.account_id,
                    event.timestamp.isoformat(),
                    event.data if isinstance(event.data, str) else str(event.data),
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
                
                logger.debug(
                    "EventLog: appended event_id=%s sequence_id=%d type=%s account=%s",
                    event.event_id,
                    event.sequence_id,
                    event.event_type.value,
                    event.account_id
                )
                return True
            except sqlite3.IntegrityError as e:
                logger.warning(
                    "EventLog: integrity error appending event %s: %s",
                    event.event_id,
                    e
                )
                conn.rollback()
                return False
            finally:
                conn.close()
    
    def get_events_since(
        self,
        sequence_id: int = 0,
        account_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[PortfolioEvent]:
        """Get events since a given sequence ID.
        
        Args:
            sequence_id: Starting sequence ID (exclusive)
            account_id: Filter by account (optional)
            limit: Maximum number of events to return (optional)
            
        Returns:
            List of PortfolioEvents ordered by sequence_id
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                query = """
                    SELECT event_id, sequence_id, event_type, account_id, timestamp, data
                    FROM portfolio_events
                    WHERE sequence_id > ?
                """
                params: List[Any] = [sequence_id]
                
                if account_id:
                    query += " AND account_id = ?"
                    params.append(account_id)
                
                query += " ORDER BY sequence_id ASC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor = conn.execute(query, params)
                events = []
                for row in cursor.fetchall():
                    event = PortfolioEvent(
                        event_id=row["event_id"],
                        sequence_id=row["sequence_id"],
                        event_type=EventType(row["event_type"]),
                        account_id=row["account_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        data=row["data"],
                    )
                    events.append(event)
                
                logger.debug(
                    "EventLog: retrieved %d events since sequence_id=%d (account=%s)",
                    len(events),
                    sequence_id,
                    account_id or "all"
                )
                return events
            finally:
                conn.close()
    
    def get_latest_sequence_id(self, account_id: Optional[str] = None) -> int:
        """Get the latest sequence ID in the log.
        
        Args:
            account_id: Filter by account (optional)
            
        Returns:
            Latest sequence ID, or 0 if log is empty
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                query = "SELECT MAX(sequence_id) as max_seq FROM portfolio_events"
                params: List[Any] = []
                
                if account_id:
                    query += " WHERE account_id = ?"
                    params.append(account_id)
                
                cursor = conn.execute(query, params)
                result = cursor.fetchone()
                return result["max_seq"] if result["max_seq"] else 0
            finally:
                conn.close()
    
    def get_event_count(self, account_id: Optional[str] = None) -> int:
        """Get total number of events in the log.
        
        Args:
            account_id: Filter by account (optional)
            
        Returns:
            Number of events
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                query = "SELECT COUNT(*) as count FROM portfolio_events"
                params: List[Any] = []
                
                if account_id:
                    query += " WHERE account_id = ?"
                    params.append(account_id)
                
                cursor = conn.execute(query, params)
                result = cursor.fetchone()
                return result["count"]
            finally:
                conn.close()
    
    def replay_events(
        self,
        from_sequence_id: int = 0,
        to_sequence_id: Optional[int] = None,
        account_id: Optional[str] = None,
    ) -> List[PortfolioEvent]:
        """Replay events for state reconstruction.
        
        Args:
            from_sequence_id: Starting sequence ID (inclusive)
            to_sequence_id: Ending sequence ID (inclusive), None for all
            account_id: Filter by account (optional)
            
        Returns:
            List of PortfolioEvents in sequence order
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                query = """
                    SELECT event_id, sequence_id, event_type, account_id, timestamp, data
                    FROM portfolio_events
                    WHERE sequence_id >= ?
                """
                params: List[Any] = [from_sequence_id]
                
                if account_id:
                    query += " AND account_id = ?"
                    params.append(account_id)
                
                if to_sequence_id is not None:
                    query += " AND sequence_id <= ?"
                    params.append(to_sequence_id)
                
                query += " ORDER BY sequence_id ASC"
                
                cursor = conn.execute(query, params)
                events = []
                for row in cursor.fetchall():
                    event = PortfolioEvent(
                        event_id=row["event_id"],
                        sequence_id=row["sequence_id"],
                        event_type=EventType(row["event_type"]),
                        account_id=row["account_id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        data=row["data"],
                    )
                    events.append(event)
                
                logger.debug(
                    "EventLog: replayed %d events from sequence_id=%d to %s (account=%s)",
                    len(events),
                    from_sequence_id,
                    to_sequence_id or "end",
                    account_id or "all"
                )
                return events
            finally:
                conn.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get event log statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                # Total events
                cursor = conn.execute("SELECT COUNT(*) as count FROM portfolio_events")
                total_events = cursor.fetchone()["count"]
                
                # Latest sequence ID
                cursor = conn.execute("SELECT MAX(sequence_id) as max_seq FROM portfolio_events")
                latest_seq = cursor.fetchone()["max_seq"] or 0
                
                # Events by type
                cursor = conn.execute("""
                    SELECT event_type, COUNT(*) as count
                    FROM portfolio_events
                    GROUP BY event_type
                    ORDER BY count DESC
                """)
                events_by_type = {row["event_type"]: row["count"] for row in cursor.fetchall()}
                
                # Events by account
                cursor = conn.execute("""
                    SELECT account_id, COUNT(*) as count
                    FROM portfolio_events
                    GROUP BY account_id
                    ORDER BY count DESC
                """)
                events_by_account = {row["account_id"]: row["count"] for row in cursor.fetchall()}
                
                # Earliest and latest timestamps
                cursor = conn.execute("""
                    SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
                    FROM portfolio_events
                """)
                ts_row = cursor.fetchone()
                
                return {
                    "total_events": total_events,
                    "latest_sequence_id": latest_seq,
                    "events_by_type": events_by_type,
                    "events_by_account": events_by_account,
                    "earliest_timestamp": ts_row["min_ts"],
                    "latest_timestamp": ts_row["max_ts"],
                    "db_path": self._db_path,
                }
            finally:
                conn.close()

    def check_integrity(self) -> Dict[str, Any]:
        """Perform integrity checks on the event log.
        
        Returns:
            Dictionary with integrity check results
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                results = {
                    "sequence_gaps": [],
                    "timestamp_order_violations": [],
                    "duplicate_event_ids": [],
                    "corrupted_events": [],
                    "passed": True,
                }
                
                # Check for sequence ID gaps
                cursor = conn.execute("SELECT sequence_id FROM portfolio_events ORDER BY sequence_id ASC")
                sequence_ids = [row["sequence_id"] for row in cursor.fetchall()]
                
                if sequence_ids:
                    expected = sequence_ids[0]
                    for seq_id in sequence_ids:
                        if seq_id != expected:
                            results["sequence_gaps"].append({
                                "expected": expected,
                                "found": seq_id,
                                "gap": seq_id - expected
                            })
                        expected = seq_id + 1
                
                # Check for timestamp order violations (events should be in order by sequence_id)
                cursor = conn.execute("""
                    SELECT sequence_id, timestamp FROM portfolio_events 
                    ORDER BY sequence_id ASC
                """)
                rows = cursor.fetchall()
                prev_timestamp = None
                for row in rows:
                    current_timestamp = datetime.fromisoformat(row["timestamp"])
                    if prev_timestamp and current_timestamp < prev_timestamp:
                        results["timestamp_order_violations"].append({
                            "sequence_id": row["sequence_id"],
                            "timestamp": row["timestamp"],
                            "prev_timestamp": prev_timestamp.isoformat()
                        })
                    prev_timestamp = current_timestamp
                
                # Check for corrupted events (invalid JSON in data field)
                cursor = conn.execute("SELECT event_id, sequence_id, data FROM portfolio_events")
                for row in cursor.fetchall():
                    try:
                        data_str = row["data"]
                        if data_str and not data_str.startswith("{") and not data_str.startswith("["):
                            # Try to parse as JSON
                            json.loads(data_str)
                    except (json.JSONDecodeError, ValueError) as e:
                        results["corrupted_events"].append({
                            "event_id": row["event_id"],
                            "sequence_id": row["sequence_id"],
                            "error": str(e)
                        })
                
                # Check database file integrity using SQLite integrity check
                try:
                    cursor = conn.execute("PRAGMA integrity_check")
                    integrity_result = cursor.fetchone()[0]
                    if integrity_result != "ok":
                        results["sqlite_integrity"] = integrity_result
                        results["passed"] = False
                except sqlite3.Error as e:
                    results["sqlite_integrity_error"] = str(e)
                    results["passed"] = False
                
                # Overall pass/fail
                if (results["sequence_gaps"] or 
                    results["timestamp_order_violations"] or 
                    results["duplicate_event_ids"] or 
                    results["corrupted_events"]):
                    results["passed"] = False
                
                logger.info(
                    "EventLog integrity check: passed=%s, gaps=%d, timestamp_violations=%d, corrupted=%d",
                    results["passed"],
                    len(results["sequence_gaps"]),
                    len(results["timestamp_order_violations"]),
                    len(results["corrupted_events"])
                )
                
                return results
            finally:
                conn.close()

    def verify_event_hash(self, event: PortfolioEvent) -> str:
        """Generate a hash for an event for verification.
        
        Args:
            event: PortfolioEvent to hash
            
        Returns:
            SHA256 hash string
        """
        hash_input = f"{event.event_id}|{event.sequence_id}|{event.event_type.value}|{event.account_id}|{event.timestamp.isoformat()}|{event.data}"
        return hashlib.sha256(hash_input.encode()).hexdigest()

    def repair_sequence_gaps(self) -> int:
        """Attempt to repair sequence ID gaps by renumbering.
        
        WARNING: This operation modifies the event log and should only be used
        if gaps are detected and you understand the implications.
        
        Returns:
            Number of events renumbered
        """
        with self._local_lock:
            conn = self._get_connection()
            try:
                # Get all events ordered by sequence_id
                cursor = conn.execute("SELECT event_id, sequence_id FROM portfolio_events ORDER BY sequence_id ASC")
                events = cursor.fetchall()
                
                if not events:
                    return 0
                
                # Renumber starting from 1
                updates = 0
                for new_seq, (event_id, old_seq) in enumerate(events, start=1):
                    if old_seq != new_seq:
                        conn.execute(
                            "UPDATE portfolio_events SET sequence_id = ? WHERE event_id = ?",
                            (new_seq, event_id)
                        )
                        updates += 1
                
                # Reset sequence counter
                conn.execute("UPDATE sequence_counter SET counter = ?", (len(events),))
                
                conn.commit()
                logger.warning("EventLog: renumbered %d events to repair sequence gaps", updates)
                return updates
            except sqlite3.Error as e:
                logger.error("EventLog: failed to repair sequence gaps: %s", e)
                conn.rollback()
                raise
            finally:
                conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

def get_portfolio_event_log() -> PortfolioEventLog:
    """Get the singleton PortfolioEventLog instance."""
    return PortfolioEventLog()
