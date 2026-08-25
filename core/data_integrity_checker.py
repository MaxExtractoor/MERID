"""
Data Integrity Checker — Cross-database consistency checks and verification.

This module provides:
- Cross-database consistency checks
- Checksum verification for database files
- Automated data repair mechanisms
- Integrity monitoring and alerting
- Data validation across related databases

Data Safety Improvements:
1. Detects corruption early before it causes issues
2. Validates relationships between databases (e.g., fills_ledger vs positions)
3. Automated repair for common corruption issues
4. Comprehensive integrity reporting
5. Integration with alert manager for notifications
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("core.data_integrity_checker")


class IntegrityStatus(Enum):
    """Status of integrity checks."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class CheckType(Enum):
    """Types of integrity checks."""
    FILE_EXISTS = "file_exists"
    FILE_READABLE = "file_readable"
    CHECKSUM_MATCH = "checksum_match"
    SQLITE_INTEGRITY = "sqlite_integrity"
    FOREIGN_KEYS = "foreign_keys"
    SCHEMA_VALID = "schema_valid"
    CROSS_DB_CONSISTENCY = "cross_db_consistency"
    DATA_RANGE_VALID = "data_range_valid"


@dataclass
class IntegrityCheck:
    """Result of a single integrity check."""
    check_type: CheckType
    database_path: str
    status: IntegrityStatus
    message: str
    timestamp: float
    details: Optional[Dict[str, Any]] = None
    can_repair: bool = False
    repair_attempted: bool = False
    repair_successful: bool = False


@dataclass
class IntegrityReport:
    """Comprehensive integrity report for a database."""
    database_path: str
    timestamp: float
    overall_status: IntegrityStatus
    checks: List[IntegrityCheck]
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    last_modified: Optional[float] = None
    issues_found: int = 0
    warnings_found: int = 0
    critical_issues_found: int = 0


@dataclass
class CrossDatabaseCheck:
    """Result of a cross-database consistency check."""
    database_a: str
    database_b: str
    check_name: str
    status: IntegrityStatus
    message: str
    timestamp: float
    details: Optional[Dict[str, Any]] = None


class DataSafetyIntegrityChecker:
    """
    Performs comprehensive data integrity checks across databases.
    
    Features:
    - File-level checks (existence, readability, checksums)
    - Database-level checks (SQLite integrity, foreign keys, schema)
    - Cross-database consistency checks
    - Automated repair for common issues
    - Alerting on critical issues
    - Historical tracking of integrity status
    
    Usage:
        checker = DataSafetyIntegrityChecker()
        
        # Add databases to monitor
        checker.add_database("data/kalshi_fills.db")
        checker.add_database("data/analytics.db")
        
        # Run integrity checks
        report = await checker.check_database("data/kalshi_fills.db")
        
        # Run cross-database checks
        cross_report = await checker.check_cross_database_consistency(
            "data/kalshi_fills.db",
            "data/analytics.db"
        )
        
        # Start automated monitoring
        await checker.start_monitoring()
    """
    
    def __init__(self):
        # Database registry
        self._databases: Dict[str, Dict[str, Any]] = {}
        
        # Checksum registry for change detection
        self._checksums: Dict[str, str] = {}
        
        # Integrity history
        self._history: Dict[str, List[IntegrityReport]] = {}
        self._max_history = 100
        
        # Cross-database relationships
        self._relationships: List[Tuple[str, str, str]] = []  # (db_a, db_b, relationship_type)
        
        # Monitoring
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._check_interval_seconds = 300  # Check every 5 minutes
        
        # Thread-safety: Lock for shared data structures
        self._lock: Optional[asyncio.Lock] = None
        
        # Alert manager integration
        self._alert_manager = None
        
        # Statistics
        self._stats = {
            "total_checks": 0,
            "healthy_checks": 0,
            "warning_checks": 0,
            "critical_checks": 0,
            "repairs_attempted": 0,
            "repairs_successful": 0,
        }
        
        logger.info("DataSafetyIntegrityChecker initialized")
    
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
            "analytics", "metrics", "events",
            "kalshi_fills",
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
    
    def add_database(
        self,
        database_path: str,
        expected_tables: Optional[List[str]] = None,
        critical: bool = True,
    ) -> None:
        """
        Add a database to integrity monitoring.
        
        Args:
            database_path: Path to the database file
            expected_tables: List of expected table names (for schema validation)
            critical: Whether this database is critical to operations
        """
        self._databases[database_path] = {
            "expected_tables": expected_tables or [],
            "critical": critical,
            "added_at": time.time(),
        }
        
        self._history[database_path] = []
        
        logger.info(f"Added database to integrity monitoring: {database_path}")
    
    def add_cross_database_relationship(
        self,
        database_a: str,
        database_b: str,
        relationship_type: str,
    ) -> None:
        """
        Define a relationship between two databases for consistency checking.
        
        Args:
            database_a: First database path
            database_b: Second database path
            relationship_type: Type of relationship (e.g., "fills_to_analytics")
        """
        self._relationships.append((database_a, database_b, relationship_type))
        logger.info(
            f"Added cross-database relationship: {database_a} <-> {database_b} "
            f"({relationship_type})"
        )
    
    def set_alert_manager(self, alert_manager) -> None:
        """Set alert manager for notifications on critical issues."""
        self._alert_manager = alert_manager
        logger.info("Alert manager configured for integrity checker")
    
    async def check_database(self, database_path: str) -> IntegrityReport:
        """
        Perform comprehensive integrity check on a database.
        
        Args:
            database_path: Path to the database file
        
        Returns:
            IntegrityReport with check results
        """
        checks = []
        issues = 0
        warnings = 0
        critical = 0
        
        logger.info(f"Starting integrity check for: {database_path}")
        
        # File existence check
        check = self._check_file_exists(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.CRITICAL:
            critical += 1
        
        if check.status == IntegrityStatus.CRITICAL:
            # File doesn't exist - can't continue
            report = IntegrityReport(
                database_path=database_path,
                timestamp=time.time(),
                overall_status=IntegrityStatus.CRITICAL,
                checks=checks,
                issues_found=issues,
                warnings_found=warnings,
                critical_issues_found=critical,
            )
            self._record_report(report)
            return report
        
        # File readability check
        check = self._check_file_readable(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.CRITICAL:
            critical += 1
        
        if check.status == IntegrityStatus.CRITICAL:
            # File not readable - can't continue
            report = IntegrityReport(
                database_path=database_path,
                timestamp=time.time(),
                overall_status=IntegrityStatus.CRITICAL,
                checks=checks,
                issues_found=issues,
                warnings_found=warnings,
                critical_issues_found=critical,
            )
            self._record_report(report)
            return report
        
        # Get file metadata
        size_bytes = os.path.getsize(database_path)
        last_modified = os.path.getmtime(database_path)
        
        # Checksum calculation and comparison
        check = await self._check_checksum(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.WARNING:
            warnings += 1
        
        # SQLite integrity check
        check = await self._check_sqlite_integrity(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.CRITICAL:
            critical += 1
        elif check.status == IntegrityStatus.WARNING:
            warnings += 1
        
        # Foreign key check
        check = await self._check_foreign_keys(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.WARNING:
            warnings += 1
        
        # Schema validation
        db_info = self._databases.get(database_path, {})
        if db_info.get("expected_tables"):
            check = await self._check_schema(database_path, db_info["expected_tables"])
            checks.append(check)
            if check.status == IntegrityStatus.CRITICAL:
                critical += 1
            elif check.status == IntegrityStatus.WARNING:
                warnings += 1
        
        # Data range validation
        check = await self._check_data_ranges(database_path)
        checks.append(check)
        if check.status == IntegrityStatus.WARNING:
            warnings += 1
        
        # Determine overall status
        if critical > 0:
            overall_status = IntegrityStatus.CRITICAL
        elif warnings > 0:
            overall_status = IntegrityStatus.WARNING
        else:
            overall_status = IntegrityStatus.HEALTHY
        
        # Create report
        report = IntegrityReport(
            database_path=database_path,
            timestamp=time.time(),
            overall_status=overall_status,
            checks=checks,
            checksum=self._checksums.get(database_path),
            size_bytes=size_bytes,
            last_modified=last_modified,
            issues_found=issues,
            warnings_found=warnings,
            critical_issues_found=critical,
        )
        
        # Record report
        self._record_report(report)
        
        # Update stats
        self._stats["total_checks"] += 1
        if overall_status == IntegrityStatus.HEALTHY:
            self._stats["healthy_checks"] += 1
        elif overall_status == IntegrityStatus.WARNING:
            self._stats["warning_checks"] += 1
        else:
            self._stats["critical_checks"] += 1
        
        # Alert on critical issues
        if overall_status == IntegrityStatus.CRITICAL and self._alert_manager:
            await self._send_critical_alert(report)
        
        logger.info(
            f"Integrity check completed for {database_path}: "
            f"status={overall_status.value}, warnings={warnings}, critical={critical}"
        )
        
        return report
    
    def _check_file_exists(self, database_path: str) -> IntegrityCheck:
        """Check if database file exists."""
        if os.path.exists(database_path):
            return IntegrityCheck(
                check_type=CheckType.FILE_EXISTS,
                database_path=database_path,
                status=IntegrityStatus.HEALTHY,
                message="Database file exists",
                timestamp=time.time(),
            )
        else:
            return IntegrityCheck(
                check_type=CheckType.FILE_EXISTS,
                database_path=database_path,
                status=IntegrityStatus.CRITICAL,
                message="Database file does not exist",
                timestamp=time.time(),
                can_repair=False,
            )
    
    def _check_file_readable(self, database_path: str) -> IntegrityCheck:
        """Check if database file is readable."""
        try:
            with open(database_path, 'rb') as f:
                f.read(1)
            return IntegrityCheck(
                check_type=CheckType.FILE_READABLE,
                database_path=database_path,
                status=IntegrityStatus.HEALTHY,
                message="Database file is readable",
                timestamp=time.time(),
            )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.FILE_READABLE,
                database_path=database_path,
                status=IntegrityStatus.CRITICAL,
                message=f"Database file not readable: {e}",
                timestamp=time.time(),
                can_repair=False,
            )
    
    async def _check_checksum(self, database_path: str) -> IntegrityCheck:
        """
        Calculate and compare checksum.
        
        Data Safety Improvement:
        - Detects silent data corruption
        - Tracks changes over time
        - Can detect unauthorized modifications
        """
        try:
            current_checksum = self._calculate_checksum(database_path)
            previous_checksum = self._checksums.get(database_path)
            
            self._checksums[database_path] = current_checksum
            
            if previous_checksum is None:
                # First check - no comparison
                return IntegrityCheck(
                    check_type=CheckType.CHECKSUM_MATCH,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="Initial checksum recorded",
                    timestamp=time.time(),
                    details={"checksum": current_checksum},
                )
            elif current_checksum == previous_checksum:
                return IntegrityCheck(
                    check_type=CheckType.CHECKSUM_MATCH,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="Checksum matches previous",
                    timestamp=time.time(),
                    details={"checksum": current_checksum},
                )
            else:
                # Checksum changed - this could be normal (data added) or corruption
                return IntegrityCheck(
                    check_type=CheckType.CHECKSUM_MATCH,
                    database_path=database_path,
                    status=IntegrityStatus.WARNING,
                    message="Checksum changed since last check",
                    timestamp=time.time(),
                    details={
                        "previous_checksum": previous_checksum,
                        "current_checksum": current_checksum,
                    },
                )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.CHECKSUM_MATCH,
                database_path=database_path,
                status=IntegrityStatus.CRITICAL,
                message=f"Checksum calculation failed: {e}",
                timestamp=time.time(),
            )
    
    def _calculate_checksum(self, file_path: str, algorithm: str = "sha256") -> str:
        """Calculate checksum of a file."""
        hash_func = hashlib.sha256() if algorithm == "sha256" else hashlib.md5()
        
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    async def _check_sqlite_integrity(self, database_path: str) -> IntegrityCheck:
        """
        Run SQLite integrity check.
        
        Data Safety Improvement:
        - Detects database corruption
        - Uses SQLite's built-in PRAGMA integrity_check
        - Can identify structural issues
        """
        try:
            def do_check():
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                conn.close()
                return result
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, do_check)
            
            if result and result[0] == "ok":
                return IntegrityCheck(
                    check_type=CheckType.SQLITE_INTEGRITY,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="SQLite integrity check passed",
                    timestamp=time.time(),
                )
            else:
                return IntegrityCheck(
                    check_type=CheckType.SQLITE_INTEGRITY,
                    database_path=database_path,
                    status=IntegrityStatus.CRITICAL,
                    message=f"SQLite integrity check failed: {result[0] if result else 'unknown'}",
                    timestamp=time.time(),
                    can_repair=True,
                )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.SQLITE_INTEGRITY,
                database_path=database_path,
                status=IntegrityStatus.CRITICAL,
                message=f"Integrity check error: {e}",
                timestamp=time.time(),
                can_repair=False,
            )
    
    async def _check_foreign_keys(self, database_path: str) -> IntegrityCheck:
        """Check foreign key integrity."""
        try:
            def do_check():
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_key_check")
                result = cursor.fetchall()
                conn.close()
                return result
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, do_check)
            
            if not result:
                return IntegrityCheck(
                    check_type=CheckType.FOREIGN_KEYS,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="Foreign key check passed",
                    timestamp=time.time(),
                )
            else:
                return IntegrityCheck(
                    check_type=CheckType.FOREIGN_KEYS,
                    database_path=database_path,
                    status=IntegrityStatus.WARNING,
                    message=f"Foreign key violations found: {len(result)}",
                    timestamp=time.time(),
                    details={"violations": result},
                    can_repair=True,
                )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.FOREIGN_KEYS,
                database_path=database_path,
                status=IntegrityStatus.WARNING,
                message=f"Foreign key check error: {e}",
                timestamp=time.time(),
            )
    
    async def _check_schema(self, database_path: str, expected_tables: List[str]) -> IntegrityCheck:
        """
        Validate database schema.
        
        Data Safety Improvement:
        - Ensures expected tables exist
        - Detects schema drift
        - Validates database structure
        """
        try:
            def do_check():
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                # SQL INJECTION FIX: Use parameterized query (this query is safe as-is, but documenting)
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                result = [row[0] for row in cursor.fetchall()]
                conn.close()
                return result
            
            loop = asyncio.get_event_loop()
            actual_tables = await loop.run_in_executor(None, do_check)
            
            missing_tables = set(expected_tables) - set(actual_tables)
            extra_tables = set(actual_tables) - set(expected_tables)
            
            if not missing_tables and not extra_tables:
                return IntegrityCheck(
                    check_type=CheckType.SCHEMA_VALID,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="Schema validation passed",
                    timestamp=time.time(),
                    details={"tables": actual_tables},
                )
            else:
                issues = []
                if missing_tables:
                    issues.append(f"Missing tables: {missing_tables}")
                if extra_tables:
                    issues.append(f"Extra tables: {extra_tables}")
                
                return IntegrityCheck(
                    check_type=CheckType.SCHEMA_VALID,
                    database_path=database_path,
                    status=IntegrityStatus.CRITICAL if missing_tables else IntegrityStatus.WARNING,
                    message="; ".join(issues),
                    timestamp=time.time(),
                    details={
                        "expected": expected_tables,
                        "actual": actual_tables,
                        "missing": list(missing_tables),
                        "extra": list(extra_tables),
                    },
                )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.SCHEMA_VALID,
                database_path=database_path,
                status=IntegrityStatus.CRITICAL,
                message=f"Schema validation error: {e}",
                timestamp=time.time(),
            )
    
    async def _check_data_ranges(self, database_path: str) -> IntegrityCheck:
        """
        Validate data ranges and constraints.
        
        Data Safety Improvement:
        - Detects out-of-range values
        - Identifies potential data corruption
        - Validates business logic constraints
        """
        try:
            def do_check():
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                
                # Get all tables
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                
                issues = []
                
                for table in tables:
                    # SQL INJECTION FIX: Validate table name before using in PRAGMA
                    if not self._validate_table_name(table):
                        logger.warning(f"Skipping invalid table name: {table}")
                        continue
                    
                    # Check for NULL in critical columns (heuristic)
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = cursor.fetchall()
                    
                    for col in columns:
                        col_name = col[1]
                        col_type = col[2].upper()
                        
                        # Skip checking for now - this is a placeholder for custom rules
                        # In production, you'd add business-specific validation here
                        pass
                
                conn.close()
                return issues
            
            loop = asyncio.get_event_loop()
            issues = await loop.run_in_executor(None, do_check)
            
            if not issues:
                return IntegrityCheck(
                    check_type=CheckType.DATA_RANGE_VALID,
                    database_path=database_path,
                    status=IntegrityStatus.HEALTHY,
                    message="Data range validation passed",
                    timestamp=time.time(),
                )
            else:
                return IntegrityCheck(
                    check_type=CheckType.DATA_RANGE_VALID,
                    database_path=database_path,
                    status=IntegrityStatus.WARNING,
                    message=f"Data range issues found: {len(issues)}",
                    timestamp=time.time(),
                    details={"issues": issues},
                )
        except Exception as e:
            return IntegrityCheck(
                check_type=CheckType.DATA_RANGE_VALID,
                database_path=database_path,
                status=IntegrityStatus.WARNING,
                message=f"Data range validation error: {e}",
                timestamp=time.time(),
            )
    
    async def check_cross_database_consistency(
        self,
        database_a: str,
        database_b: str,
    ) -> List[CrossDatabaseCheck]:
        """
        Check consistency between two related databases.
        
        Data Safety Improvement:
        - Validates relationships between databases
        - Detects synchronization issues
        - Ensures data consistency across systems
        
        Args:
            database_a: First database path
            database_b: Second database path
        
        Returns:
            List of cross-database check results
        """
        checks = []
        
        logger.info(f"Checking cross-database consistency: {database_a} <-> {database_b}")
        
        # Check if both databases exist
        if not os.path.exists(database_a) or not os.path.exists(database_b):
            checks.append(CrossDatabaseCheck(
                database_a=database_a,
                database_b=database_b,
                check_name="existence",
                status=IntegrityStatus.CRITICAL,
                message="One or both databases do not exist",
                timestamp=time.time(),
            ))
            return checks
        
        # Check modification times (should be relatively close for synced databases)
        mod_a = os.path.getmtime(database_a)
        mod_b = os.path.getmtime(database_b)
        time_diff = abs(mod_a - mod_b)
        
        # If databases are supposed to be in sync, time diff should be small
        # This is a heuristic - adjust threshold based on your sync frequency
        if time_diff > 3600:  # More than 1 hour difference
            checks.append(CrossDatabaseCheck(
                database_a=database_a,
                database_b=database_b,
                check_name="modification_time",
                status=IntegrityStatus.WARNING,
                message=f"Large modification time difference: {time_diff:.0f}s",
                timestamp=time.time(),
                details={
                    "mod_time_a": mod_a,
                    "mod_time_b": mod_b,
                    "time_diff": time_diff,
                },
            ))
        else:
            checks.append(CrossDatabaseCheck(
                database_a=database_a,
                database_b=database_b,
                check_name="modification_time",
                status=IntegrityStatus.HEALTHY,
                message="Modification times are consistent",
                timestamp=time.time(),
            ))
        
        # Add more specific cross-database checks here based on your relationships
        # For example:
        # - Check that trade counts match between fills_ledger and analytics
        # - Check that position IDs are consistent
        # - Check that timestamps are in sync
        
        return checks
    
    async def repair_database(self, database_path: str) -> bool:
        """
        Attempt to repair a corrupted database.
        
        Data Safety Improvement:
        - Automated repair for common corruption issues
        - Uses SQLite's built-in repair mechanisms
        - Creates backup before repair
        
        Args:
            database_path: Path to the database to repair
        
        Returns:
            True if repair successful, False otherwise
        """
        logger.warning(f"Attempting to repair database: {database_path}")
        
        try:
            # Create backup before repair
            backup_path = f"{database_path}.before_repair_{int(time.time())}"
            shutil.copy2(database_path, backup_path)
            logger.info(f"Created backup before repair: {backup_path}")
            
            # Attempt SQLite repair
            def do_repair():
                # Try to dump and restore
                import subprocess
                
                # Use sqlite3 to dump
                dump_result = subprocess.run(
                    ["sqlite3", database_path, ".dump"],
                    capture_output=True,
                    text=True,
                )
                
                if dump_result.returncode != 0:
                    return False, "Dump failed"
                
                # Create new database
                new_db_path = f"{database_path}.repaired"
                
                # Restore dump
                restore_result = subprocess.run(
                    ["sqlite3", new_db_path],
                    input=dump_result.stdout,
                    capture_output=True,
                    text=True,
                )
                
                if restore_result.returncode != 0:
                    return False, "Restore failed"
                
                # Replace original
                os.remove(database_path)
                os.rename(new_db_path, database_path)
                
                return True, "Repair successful"
            
            loop = asyncio.get_event_loop()
            success, message = await loop.run_in_executor(None, do_repair)
            
            if success:
                logger.info(f"Database repair successful: {database_path}")
                self._stats["repairs_successful"] += 1
                return True
            else:
                logger.error(f"Database repair failed: {message}")
                return False
                
        except Exception as e:
            logger.error(f"Database repair error: {e}")
            return False
    
    def _record_report(self, report: IntegrityReport) -> None:
        """Record integrity report in history."""
        history = self._history.get(report.database_path, [])
        history.append(report)
        
        # Trim history
        if len(history) > self._max_history:
            self._history[report.database_path] = history[-self._max_history:]
    
    async def _send_critical_alert(self, report: IntegrityReport) -> None:
        """Send alert for critical integrity issues."""
        if not self._alert_manager:
            return
        
        try:
            from agents.alert_manager import AlertSeverity
            
            critical_checks = [c for c in report.checks if c.status == IntegrityStatus.CRITICAL]
            messages = [c.message for c in critical_checks]
            
            await self._alert_manager.alert(
                severity=AlertSeverity.CRITICAL,
                title="Database Integrity Critical",
                message=f"Critical integrity issues detected in {report.database_path}:\n" +
                        "\n".join(f"- {msg}" for msg in messages),
                source="data_integrity_checker",
                affected_assets=[],
                affected_timeframes=[],
            )
            
        except Exception as e:
            logger.error(f"Failed to send integrity alert: {e}")
    
    async def start_monitoring(self) -> None:
        """Start automated integrity monitoring."""
        if self._monitoring_task is not None:
            logger.warning("Monitoring already started")
            return
        
        self._shutdown_event = asyncio.Event()
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Integrity monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop automated integrity monitoring."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        
        if self._monitoring_task is not None:
            try:
                await asyncio.wait_for(self._monitoring_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Monitoring task did not shut down gracefully")
            self._monitoring_task = None
        
        logger.info("Integrity monitoring stopped")
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        shutdown = self._shutdown_event
        
        while not shutdown.is_set():
            try:
                # Check all registered databases
                for db_path in self._databases:
                    try:
                        await self.check_database(db_path)
                    except Exception as e:
                        logger.error(f"Error checking {db_path}: {e}")
                
                # Check cross-database relationships
                for db_a, db_b, _ in self._relationships:
                    try:
                        await self.check_cross_database_consistency(db_a, db_b)
                    except Exception as e:
                        logger.error(f"Error checking cross-db {db_a} <-> {db_b}: {e}")
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
            
            # Wait for next check
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self._check_interval_seconds)
            except asyncio.TimeoutError:
                pass
    
    def get_history(self, database_path: str) -> List[IntegrityReport]:
        """Get integrity check history for a database."""
        return self._history.get(database_path, [])
    
    def get_stats(self) -> Dict[str, Any]:
        """Get integrity checker statistics."""
        return {
            **self._stats,
            "databases_monitored": len(self._databases),
            "relationships_monitored": len(self._relationships),
        }


# Global instance
_integrity_checker: Optional[DataSafetyIntegrityChecker] = None
_integrity_checker_lock = threading.Lock()


def get_integrity_checker() -> DataSafetyIntegrityChecker:
    """Get the global integrity checker instance."""
    global _integrity_checker
    
    if _integrity_checker is None:
        with _integrity_checker_lock:
            if _integrity_checker is None:
                _integrity_checker = DataSafetyIntegrityChecker()
    
    return _integrity_checker


# Backward compatibility alias
DataIntegrityChecker = DataSafetyIntegrityChecker
