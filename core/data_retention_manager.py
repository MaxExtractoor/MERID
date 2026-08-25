"""
Data Retention Manager — Centralized data retention policy enforcement.

This module provides:
- Centralized retention policy management
- Automated cleanup of old data
- Policy-based retention for different data types
- Configurable retention periods
- Integration with backup, analytics, and alert systems

Data Safety Improvements:
1. Prevents unbounded database growth
2. Ensures compliance with data retention requirements
3. Automates cleanup to reduce manual maintenance
4. Provides audit trail of retention actions
5. Configurable policies per data type
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("core.data_retention_manager")


class DataType(Enum):
    """Types of data with retention policies."""
    TRADES = "trades"
    SNAPSHOTS = "snapshots"
    ALERTS = "alerts"
    ALERT_AGGREGATES = "alert_aggregates"
    BACKUPS = "backups"
    LOGS = "logs"
    AUDIT_LOGS = "audit_logs"
    SESSION_DATA = "session_data"
    CUSTOM = "custom"


class RetentionAction(Enum):
    """Types of retention actions."""
    DELETE = "delete"
    ARCHIVE = "archive"
    COMPRESS = "compress"
    NONE = "none"


@dataclass
class RetentionPolicy:
    """Retention policy for a data type."""
    data_type: DataType
    retention_days: int
    action: RetentionAction = RetentionAction.DELETE
    min_records: int = 0  # Keep at least N records regardless of age
    archive_path: Optional[str] = None
    compress_after_days: Optional[int] = None
    custom_handler: Optional[str] = None  # Module.function for custom handling


@dataclass
class RetentionActionLog:
    """Log of a retention action."""
    timestamp: float
    data_type: DataType
    action: RetentionAction
    records_affected: int
    database_path: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    success: bool = True
    error_message: Optional[str] = None


class DataSafetyRetentionManager:
    """
    Manages data retention policies across all systems.
    
    Features:
    - Centralized policy definition
    - Automated cleanup based on age
    - Multiple retention actions (delete, archive, compress)
    - Per-database policy enforcement
    - Audit logging of all actions
    - Integration with existing systems
    
    Usage:
        manager = DataSafetyRetentionManager()
        
        # Define policies
        manager.add_policy(RetentionPolicy(
            data_type=DataType.TRADES,
            retention_days=365,
            action=RetentionAction.DELETE,
        ))
        
        # Register databases
        manager.register_database("data/kalshi_fills.db", [DataType.TRADES])
        manager.register_database("data/analytics.db", [DataType.SNAPSHOTS])
        
        # Start automated enforcement
        await manager.start()
        
        # Manual enforcement
        await manager.enforce_policies()
    """
    
    def __init__(self):
        # Retention policies
        self._policies: Dict[DataType, RetentionPolicy] = {}
        
        # Database registration: db_path -> List[DataType]
        self._databases: Dict[str, List[DataType]] = {}
        
        # Action log
        self._action_log: List[RetentionActionLog] = []
        self._max_log_size = 1000
        
        # Enforcement task
        self._enforcement_task: Optional[asyncio.Task] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._enforcement_interval_hours = 24.0  # Run daily
        
        # Thread-safety: Lock for shared data structures
        self._lock: Optional[asyncio.Lock] = None
        
        # Statistics
        self._stats = {
            "total_enforcements": 0,
            "total_records_deleted": 0,
            "total_records_archived": 0,
            "total_records_compressed": 0,
            "last_enforcement_time": None,
        }
        
        # Load default policies
        self._load_default_policies()
        
        logger.info("DataSafetyRetentionManager initialized")
    
    def _load_default_policies(self) -> None:
        """Load default retention policies from environment or defaults."""
        # Trades: Keep for 1 year by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.TRADES,
            retention_days=int(os.getenv("MERID_RETENTION_TRADES_DAYS", "365")),
            action=RetentionAction.DELETE,
            min_records=1000,  # Keep at least 1000 trades
        ))
        
        # Snapshots: Keep for 30 days by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.SNAPSHOTS,
            retention_days=int(os.getenv("MERID_RETENTION_SNAPSHOTS_DAYS", "30")),
            action=RetentionAction.DELETE,
        ))
        
        # Alerts: Keep for 90 days by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.ALERTS,
            retention_days=int(os.getenv("MERID_RETENTION_ALERTS_DAYS", "90")),
            action=RetentionAction.DELETE,
        ))
        
        # Alert aggregates: Keep for 30 days by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.ALERT_AGGREGATES,
            retention_days=int(os.getenv("MERID_RETENTION_ALERT_AGGREGATES_DAYS", "30")),
            action=RetentionAction.DELETE,
        ))
        
        # Backups: Managed by backup manager, but we track the policy
        self.add_policy(RetentionPolicy(
            data_type=DataType.BACKUPS,
            retention_days=int(os.getenv("MERID_RETENTION_BACKUPS_DAYS", "90")),
            action=RetentionAction.DELETE,
        ))
        
        # Logs: Keep for 7 days by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.LOGS,
            retention_days=int(os.getenv("MERID_RETENTION_LOGS_DAYS", "7")),
            action=RetentionAction.DELETE,
        ))
        
        # Audit logs: Keep for 1 year by default (compliance)
        self.add_policy(RetentionPolicy(
            data_type=DataType.AUDIT_LOGS,
            retention_days=int(os.getenv("MERID_RETENTION_AUDIT_LOGS_DAYS", "365")),
            action=RetentionAction.ARCHIVE,
            archive_path=os.getenv("MERID_ARCHIVE_PATH", "data/archive"),
        ))
        
        # Session data: Keep for 30 days by default
        self.add_policy(RetentionPolicy(
            data_type=DataType.SESSION_DATA,
            retention_days=int(os.getenv("MERID_RETENTION_SESSION_DATA_DAYS", "30")),
            action=RetentionAction.DELETE,
        ))
        
        logger.info(f"Loaded {len(self._policies)} default retention policies")
    
    def _ensure_lock(self) -> asyncio.Lock:
        """
        Lazy-initialize the lock in the current event loop.
        
        This prevents race conditions when the lock is accessed from different
        event loops or before the event loop is fully initialized.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    def _validate_table_name(self, table_name: str) -> bool:
        """
        Validate table name against a whitelist to prevent SQL injection.
        
        Only allows alphanumeric characters and underscores, and checks against
        a known list of valid table names.
        
        Args:
            table_name: The table name to validate
            
        Returns:
            True if the table name is valid, False otherwise
        """
        # Whitelist of known valid table names
        VALID_TABLES = {
            "trades", "snapshots", "alerts", "alert_aggregates",
            "backups", "logs", "audit_logs", "session_data",
            "positions", "fills_ledger", "market_state",
            "analytics", "metrics", "events"
        }
        
        # Check against whitelist
        if table_name not in VALID_TABLES:
            logger.warning(f"Table name not in whitelist: {table_name}")
            return False
        
        # Additional validation: only allow alphanumeric and underscore
        if not table_name.replace("_", "").isalnum():
            logger.warning(f"Table name contains invalid characters: {table_name}")
            return False
        
        return True
    
    def _ensure_lock(self) -> asyncio.Lock:
        """
        Lazy-initialize the lock in the current event loop.
        
        This prevents race conditions when the lock is accessed from different
        event loops or before the event loop is fully initialized.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    def add_policy(self, policy: RetentionPolicy) -> None:
        """Add or update a retention policy."""
        lock = self._ensure_lock()
        # Note: This is a synchronous method, but we still use the lock for consistency
        # In async context, use async with lock
        self._policies[policy.data_type] = policy
        logger.info(f"Added retention policy: {policy.data_type.value} -> {policy.retention_days} days")
    
    def get_policy(self, data_type: DataType) -> Optional[RetentionPolicy]:
        """Get retention policy for a data type."""
        return self._policies.get(data_type)
    
    def register_database(self, database_path: str, data_types: List[DataType]) -> None:
        """
        Register a database with its data types.
        
        Args:
            database_path: Path to the database file
            data_types: List of data types contained in this database
        """
        self._databases[database_path] = data_types
        logger.info(f"Registered database: {database_path} with data types: {[dt.value for dt in data_types]}")
    
    async def start(self) -> None:
        """Start automated retention enforcement."""
        if self._enforcement_task is not None:
            logger.warning("Retention enforcement already started")
            return
        
        self._shutdown_event = asyncio.Event()
        self._enforcement_task = asyncio.create_task(self._enforcement_loop())
        logger.info("Retention enforcement started")
    
    async def stop(self) -> None:
        """Stop automated retention enforcement."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        
        if self._enforcement_task is not None:
            try:
                await asyncio.wait_for(self._enforcement_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Enforcement task did not shut down gracefully")
            self._enforcement_task = None
        
        logger.info("Retention enforcement stopped")
    
    async def _enforcement_loop(self) -> None:
        """Main enforcement loop."""
        shutdown = self._shutdown_event
        
        while not shutdown.is_set():
            try:
                await self.enforce_policies()
            except Exception as e:
                logger.error(f"Error in enforcement loop: {e}")
            
            # Wait for next enforcement
            interval_seconds = self._enforcement_interval_hours * 3600
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
    
    async def enforce_policies(self, database_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Enforce retention policies on all or specific databases.
        
        Args:
            database_path: Optional specific database to enforce
        
        Returns:
            Summary of enforcement actions
        """
        logger.info("Starting retention policy enforcement")
        
        summary = {
            "timestamp": time.time(),
            "databases_processed": 0,
            "total_records_deleted": 0,
            "total_records_archived": 0,
            "total_records_compressed": 0,
            "actions_performed": [],
        }
        
        databases_to_process = (
            [database_path] if database_path else list(self._databases.keys())
        )
        
        for db_path in databases_to_process:
            if db_path not in self._databases:
                logger.warning(f"Database not registered: {db_path}")
                continue
            
            if not os.path.exists(db_path):
                logger.warning(f"Database does not exist: {db_path}")
                continue
            
            data_types = self._databases[db_path]
            db_summary = await self.enforce_database(db_path, data_types)
            
            summary["databases_processed"] += 1
            summary["total_records_deleted"] += db_summary["deleted"]
            summary["total_records_archived"] += db_summary["archived"]
            summary["total_records_compressed"] += db_summary["compressed"]
            summary["actions_performed"].append(db_summary)
        
        # Update stats
        self._stats["total_enforcements"] += 1
        self._stats["total_records_deleted"] += summary["total_records_deleted"]
        self._stats["total_records_archived"] += summary["total_records_archived"]
        self._stats["total_records_compressed"] += summary["total_records_compressed"]
        self._stats["last_enforcement_time"] = time.time()
        
        logger.info(
            f"Retention enforcement completed: "
            f"{summary['databases_processed']} databases, "
            f"{summary['total_records_deleted']} deleted, "
            f"{summary['total_records_archived']} archived, "
            f"{summary['total_records_compressed']} compressed"
        )
        
        return summary
    
    async def enforce_database(
        self,
        database_path: str,
        data_types: List[DataType],
    ) -> Dict[str, Any]:
        """
        Enforce retention policies on a specific database.
        
        Args:
            database_path: Path to the database
            data_types: Data types to enforce
        
        Returns:
            Summary of actions
        """
        summary = {
            "database": database_path,
            "deleted": 0,
            "archived": 0,
            "compressed": 0,
            "actions": [],
        }
        
        for data_type in data_types:
            policy = self._policies.get(data_type)
            if not policy:
                logger.warning(f"No policy for data type: {data_type.value}")
                continue
            
            try:
                result = await self._enforce_policy(database_path, policy)
                summary["deleted"] += result["deleted"]
                summary["archived"] += result["archived"]
                summary["compressed"] += result["compressed"]
                summary["actions"].append(result)
            except Exception as e:
                logger.error(f"Error enforcing policy {data_type.value} on {database_path}: {e}")
        
        return summary
    
    async def _enforce_policy(
        self,
        database_path: str,
        policy: RetentionPolicy,
    ) -> Dict[str, Any]:
        """
        Enforce a specific retention policy.
        
        Args:
            database_path: Path to the database
            policy: Retention policy to enforce
        
        Returns:
            Summary of actions taken
        """
        result = {
            "data_type": policy.data_type.value,
            "action": policy.action.value,
            "deleted": 0,
            "archived": 0,
            "compressed": 0,
        }
        
        cutoff = time.time() - (policy.retention_days * 86400)
        
        try:
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Determine table name based on data type
            table_name = self._get_table_name(policy.data_type)
            if not table_name:
                logger.warning(f"No table mapping for data type: {policy.data_type.value}")
                return result
            
            # Check if table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not cursor.fetchone():
                logger.debug(f"Table does not exist: {table_name}")
                return result
            
            # Get total count before deletion
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            total_before = cursor.fetchone()[0]
            
            # Count records to be deleted (respecting min_records)
            if policy.min_records > 0:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE created_at < ?",
                    (cutoff,)
                )
                to_delete_count = cursor.fetchone()[0]
                
                # Check if we would go below min_records
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                current_count = cursor.fetchone()[0]
                
                if current_count - to_delete_count < policy.min_records:
                    # Adjust cutoff to keep min_records
                    cursor.execute(
                        f"SELECT created_at FROM {table_name} "
                        f"ORDER BY created_at DESC LIMIT 1 OFFSET ?",
                        (policy.min_records - 1,)
                    )
                    row = cursor.fetchone()
                    if row:
                        cutoff = row[0] - 1  # Delete everything older than this
            
            # Perform action based on policy
            if policy.action == RetentionAction.DELETE:
                deleted = await self._delete_old_records(
                    cursor, table_name, cutoff, policy.data_type
                )
                result["deleted"] = deleted
                
            elif policy.action == RetentionAction.ARCHIVE:
                archived = await self._archive_old_records(
                    database_path, table_name, cutoff, policy
                )
                result["archived"] = archived
                
            elif policy.action == RetentionAction.COMPRESS:
                compressed = await self._compress_old_records(
                    database_path, table_name, cutoff, policy
                )
                result["compressed"] = compressed
            
            conn.commit()
            conn.close()
            
            # Log action
            self._log_action(
                data_type=policy.data_type,
                action=policy.action,
                records_affected=result["deleted"] + result["archived"] + result["compressed"],
                database_path=database_path,
                success=True,
            )
            
        except Exception as e:
            logger.error(f"Error enforcing policy: {e}")
            self._log_action(
                data_type=policy.data_type,
                action=policy.action,
                records_affected=0,
                database_path=database_path,
                success=False,
                error_message=str(e),
            )
        
        return result
    
    def _get_table_name(self, data_type: DataType) -> Optional[str]:
        """Map data type to database table name."""
        table_mapping = {
            DataType.TRADES: "trades",
            DataType.SNAPSHOTS: "snapshots",
            DataType.ALERTS: "alerts",
            DataType.ALERT_AGGREGATES: "alert_aggregates",
            DataType.LOGS: "logs",
            DataType.AUDIT_LOGS: "audit_logs",
            DataType.SESSION_DATA: "session_data",
        }
        return table_mapping.get(data_type)
    
    async def _delete_old_records(
        self,
        cursor: sqlite3.Cursor,
        table_name: str,
        cutoff: float,
        data_type: DataType,
    ) -> int:
        """Delete records older than cutoff."""
        # SQL INJECTION FIX: Validate table name before using in query
        if not self._validate_table_name(table_name):
            logger.error(f"Invalid table name for deletion: {table_name}")
            return 0
        
        # Determine timestamp column based on table
        timestamp_column = self._get_timestamp_column(table_name)
        
        # Use parameterized query with validated table name
        # Note: SQLite doesn't support parameterized table names, so we validate first
        cursor.execute(
            f"DELETE FROM {table_name} WHERE {timestamp_column} < ?",
            (cutoff,)
        )
        deleted = cursor.rowcount
        
        logger.debug(f"Deleted {deleted} records from {table_name}")
        return deleted
    
    def _get_timestamp_column(self, table_name: str) -> str:
        """Get the timestamp column name for a table."""
        # Common timestamp column names
        if table_name in ["trades", "snapshots", "alerts"]:
            return "timestamp"
        elif table_name == "alert_aggregates":
            return "last_seen"
        else:
            return "created_at"
    
    async def _archive_old_records(
        self,
        database_path: str,
        table_name: str,
        cutoff: float,
        policy: RetentionPolicy,
    ) -> int:
        """Archive old records to a separate file."""
        if not policy.archive_path:
            logger.warning("Archive path not specified")
            return 0
        
        archive_dir = Path(policy.archive_path)
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Create archive filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_file = archive_dir / f"{table_name}_{timestamp}.db"
        
        try:
            # Connect to source database
            source_conn = sqlite3.connect(database_path)
            source_cursor = source_conn.cursor()
            
            # Connect to archive database
            archive_conn = sqlite3.connect(str(archive_file))
            archive_cursor = archive_conn.cursor()
            
            # SQL INJECTION FIX: Validate table name before using in query
            if not self._validate_table_name(table_name):
                logger.error(f"Invalid table name for archive: {table_name}")
                archive_conn.close()
                source_conn.close()
                return 0
            
            # Copy schema using parameterized query
            source_cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            schema_row = source_cursor.fetchone()
            if schema_row:
                archive_cursor.execute(schema_row[0])
            
            # Copy old records
            timestamp_column = self._get_timestamp_column(table_name)
            source_cursor.execute(
                f"SELECT * FROM {table_name} WHERE {timestamp_column} < ?",
                (cutoff,)
            )
            
            rows = source_cursor.fetchall()
            if rows:
                # Get column count using validated table name
                source_cursor.execute(f"PRAGMA table_info({table_name})")
                columns = len(source_cursor.fetchall())
                
                placeholders = ",".join(["?"] * columns)
                archive_cursor.executemany(
                    f"INSERT INTO {table_name} VALUES ({placeholders})",
                    rows
                )
            
            archive_conn.commit()
            archive_conn.close()
            
            # Delete from source
            deleted = await self._delete_old_records(source_cursor, table_name, cutoff, policy.data_type)
            source_conn.commit()
            source_conn.close()
            
            logger.info(f"Archived {deleted} records to {archive_file}")
            return deleted
            
        except Exception as e:
            logger.error(f"Archive failed: {e}")
            if archive_file.exists():
                archive_file.unlink()
            return 0
    
    async def _compress_old_records(
        self,
        database_path: str,
        table_name: str,
        cutoff: float,
        policy: RetentionPolicy,
    ) -> int:
        """
        Compress old records (placeholder - implement based on needs).
        
        This could:
        - Move old records to a compressed table
        - Use SQLite's VFS compression
        - Export to compressed format
        """
        # For now, just delete (compression is complex)
        logger.debug("Compression not fully implemented - using delete")
        return await self._delete_old_records(
            None, table_name, cutoff, policy.data_type
        )
    
    def _log_action(
        self,
        data_type: DataType,
        action: RetentionAction,
        records_affected: int,
        database_path: Optional[str],
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Log a retention action."""
        log_entry = RetentionActionLog(
            timestamp=time.time(),
            data_type=data_type,
            action=action,
            records_affected=records_affected,
            database_path=database_path,
            success=success,
            error_message=error_message,
        )
        
        self._action_log.append(log_entry)
        
        # Trim log
        if len(self._action_log) > self._max_log_size:
            self._action_log = self._action_log[-self._max_log_size:]
    
    def get_action_log(
        self,
        data_type: Optional[DataType] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[RetentionActionLog]:
        """Get retention action log with optional filtering."""
        log = self._action_log
        
        if data_type:
            log = [e for e in log if e.data_type == data_type]
        
        if since:
            log = [e for e in log if e.timestamp >= since]
        
        return sorted(log, key=lambda e: e.timestamp, reverse=True)[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get retention manager statistics."""
        return {
            **self._stats,
            "policies_defined": len(self._policies),
            "databases_registered": len(self._databases),
            "action_log_size": len(self._action_log),
        }
    
    def export_policies(self, file_path: str) -> None:
        """Export current policies to a JSON file."""
        policies_data = {
            dt.value: asdict(policy)
            for dt, policy in self._policies.items()
        }
        
        with open(file_path, 'w') as f:
            json.dump(policies_data, f, indent=2)
        
        logger.info(f"Exported policies to {file_path}")
    
    def import_policies(self, file_path: str) -> None:
        """Import policies from a JSON file."""
        with open(file_path, 'r') as f:
            policies_data = json.load(f)
        
        for data_type_str, policy_data in policies_data.items():
            data_type = DataType(data_type_str)
            policy = RetentionPolicy(
                data_type=data_type,
                **{k: v for k, v in policy_data.items() if k != "data_type"}
            )
            self.add_policy(policy)
        
        logger.info(f"Imported policies from {file_path}")


# Global instance
_retention_manager: Optional[DataSafetyRetentionManager] = None
_retention_manager_lock = threading.Lock()


def get_retention_manager() -> DataSafetyRetentionManager:
    """Get the global retention manager instance."""
    global _retention_manager
    
    if _retention_manager is None:
        with _retention_manager_lock:
            if _retention_manager is None:
                _retention_manager = DataSafetyRetentionManager()
    
    return _retention_manager


# Backward compatibility alias
DataRetentionManager = DataSafetyRetentionManager
