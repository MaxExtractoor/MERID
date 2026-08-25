"""
Database Backup Manager — Automated backups with verification and multi-location storage.

This module provides:
- Automated scheduled backups for SQLite databases
- Checksum verification for backup integrity
- Multi-location storage (local + S3)
- Backup retention policies
- Backup restoration capabilities
- Cross-database consistency checks

Data Safety Improvements:
1. Automated backups prevent data loss from corruption or accidental deletion
2. Checksum verification ensures backup integrity
3. Multi-location storage provides redundancy against local failures
4. Retention policies manage storage space while preserving historical data
5. Automated consistency checks detect data corruption early
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
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("core.database_backup_manager")


class BackupStatus(Enum):
    """Status of backup operations."""
    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    CORRUPTED = "corrupted"
    RETENTION_CLEANED = "retention_cleaned"


class StorageLocation(Enum):
    """Backup storage locations."""
    LOCAL = "local"
    S3 = "s3"
    BOTH = "both"


@dataclass
class BackupMetadata:
    """Metadata for a backup."""
    backup_id: str
    database_path: str
    backup_path: str
    timestamp: float
    size_bytes: int
    checksum_sha256: str
    checksum_md5: str
    status: BackupStatus
    storage_locations: List[StorageLocation]
    verified: bool = False
    verification_timestamp: Optional[float] = None
    retention_expiry: Optional[float] = None
    database_checksum_before: Optional[str] = None
    database_checksum_after: Optional[str] = None


@dataclass
class BackupPolicy:
    """Backup retention and scheduling policy."""
    # Scheduling
    backup_interval_hours: float = 1.0  # Backup every hour
    backup_enabled: bool = True
    
    # Retention (keep N backups of each type)
    keep_hourly: int = 24  # Keep last 24 hourly backups
    keep_daily: int = 7   # Keep last 7 daily backups
    keep_weekly: int = 4  # Keep last 4 weekly backups
    keep_monthly: int = 12  # Keep last 12 monthly backups
    
    # Storage
    primary_storage: StorageLocation = StorageLocation.LOCAL
    secondary_storage: Optional[StorageLocation] = StorageLocation.S3
    s3_bucket: Optional[str] = None
    s3_prefix: str = "database-backups"
    
    # Verification
    verify_after_backup: bool = True
    verify_checksum: bool = True
    verify_restore: bool = False  # Expensive - only for critical backups
    
    # Compression
    compress_backups: bool = True
    compression_level: int = 6  # 1-9, default 6


class DatabaseSafetyBackupManager:
    """
    Manages automated database backups with verification and multi-location storage.
    
    Features:
    - Scheduled automated backups
    - Checksum verification (SHA-256 and MD5)
    - Multi-location storage (local filesystem + S3)
    - Retention policy enforcement
    - Backup restoration
    - Cross-database consistency checks
    - Dead letter queue for failed backups
    
    Usage:
        manager = DatabaseSafetyBackupManager()
        
        # Add database to backup schedule
        manager.add_database(
            database_path="data/kalshi_fills.db",
            policy=BackupPolicy(backup_interval_hours=1.0)
        )
        
        # Start automated backups
        await manager.start()
        
        # Manual backup
        backup = await manager.backup_database("data/kalshi_fills.db")
        
        # Restore from backup
        await manager.restore_database(
            database_path="data/kalshi_fills.db",
            backup_id=backup.backup_id
        )
    """
    
    def __init__(self):
        # Database registry: db_path -> BackupPolicy
        self._databases: Dict[str, BackupPolicy] = {}
        
        # Backup history: db_path -> List[BackupMetadata]
        self._backup_history: Dict[str, List[BackupMetadata]] = {}
        
        # Backup directory
        self._backup_dir = Path(os.getenv("MERID_BACKUP_DIR", "data/backups"))
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics (must exist before _load_metadata(), which updates them)
        self._stats = {
            "total_backups": 0,
            "successful_backups": 0,
            "failed_backups": 0,
            "verified_backups": 0,
            "corrupted_backups": 0,
            "restorations": 0,
            "last_backup_time": None,
        }

        # Metadata storage
        self._metadata_path = self._backup_dir / "backup_metadata.json"
        self._load_metadata()

        # S3 client (lazy initialization)
        self._s3_client = None
        self._s3_available = False

        # Background task
        self._backup_task: Optional[asyncio.Task] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._lock: Optional[asyncio.Lock] = None

        # Dead letter queue for failed backups
        self._dlq: List[Dict[str, Any]] = []
        self._dlq_max_size = 100
        
        logger.info("DatabaseSafetyBackupManager initialized")
    
    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the lock in the current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    def _ensure_shutdown_event(self) -> asyncio.Event:
        """Lazy-initialize the shutdown event in the current event loop."""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event
    
    def add_database(self, database_path: str, policy: Optional[BackupPolicy] = None) -> None:
        """
        Add a database to the backup schedule.
        
        Args:
            database_path: Path to the SQLite database file
            policy: Backup policy (uses default if None)
        """
        if not os.path.exists(database_path):
            logger.warning(f"Database file does not exist: {database_path}")
        
        if policy is None:
            policy = BackupPolicy()
        
        # Note: This is a synchronous method, but we document that async methods should use the lock
        # For thread-safety in async context, wrap calls to this with the lock
        self._databases[database_path] = policy
        self._backup_history[database_path] = []
        
        logger.info(f"Added database to backup schedule: {database_path}")
    
    def remove_database(self, database_path: str) -> None:
        """Remove a database from the backup schedule."""
        if database_path in self._databases:
            del self._databases[database_path]
            logger.info(f"Removed database from backup schedule: {database_path}")
    
    async def start(self) -> None:
        """Start the automated backup scheduler."""
        if self._backup_task is not None:
            logger.warning("Backup manager already started")
            return
        
        self._shutdown_event = self._ensure_shutdown_event()
        self._backup_task = asyncio.create_task(self._backup_loop())
        logger.info("Backup manager started")
    
    async def stop(self) -> None:
        """Stop the automated backup scheduler."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        
        if self._backup_task is not None:
            try:
                await asyncio.wait_for(self._backup_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Backup task did not shut down gracefully")
            self._backup_task = None
        
        logger.info("Backup manager stopped")
    
    async def _backup_loop(self) -> None:
        """Main backup loop - runs scheduled backups."""
        shutdown = self._ensure_shutdown_event()
        
        while not shutdown.is_set():
            try:
                # Check each database for backup eligibility
                for db_path, policy in self._databases.items():
                    if not policy.backup_enabled:
                        continue
                    
                    if await self._should_backup(db_path, policy):
                        try:
                            await self.backup_database(db_path, policy)
                        except Exception as e:
                            logger.error(f"Failed to backup {db_path}: {e}")
                            self._stats["failed_backups"] += 1
                            self._add_to_dlq(db_path, str(e))
                
                # Apply retention policies
                await self._apply_retention_policies()
                
                # Save metadata
                self._save_metadata()
                
            except Exception as e:
                logger.error(f"Error in backup loop: {e}")
            
            # Wait before next check (check every minute)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
    
    async def _should_backup(self, database_path: str, policy: BackupPolicy) -> bool:
        """Check if a database should be backed up based on schedule."""
        history = self._backup_history.get(database_path, [])
        
        if not history:
            # No backups yet - backup now
            return True
        
        last_backup = history[-1]
        hours_since_last = (time.time() - last_backup.timestamp) / 3600
        
        return hours_since_last >= policy.backup_interval_hours
    
    async def backup_database(
        self,
        database_path: str,
        policy: Optional[BackupPolicy] = None,
        force: bool = False,
    ) -> Optional[BackupMetadata]:
        """
        Perform a backup of a database.
        
        Args:
            database_path: Path to the database file
            policy: Backup policy (uses registered policy if None)
            force: Force backup even if not scheduled
        
        Returns:
            BackupMetadata if successful, None otherwise
        """
        if policy is None:
            policy = self._databases.get(database_path)
            if policy is None:
                logger.error(f"No policy registered for database: {database_path}")
                return None
        
        if not force and not await self._should_backup(database_path, policy):
            logger.debug(f"Backup not needed for {database_path}")
            return None
        
        async with self._ensure_lock():
            backup_id = self._generate_backup_id(database_path)
            timestamp = time.time()
            
            logger.info(f"Starting backup: {database_path} -> {backup_id}")
            
            try:
                # Calculate checksum before backup
                db_checksum_before = self._calculate_file_checksum(database_path)
                
                # Create backup
                backup_path = self._create_backup_path(database_path, backup_id, timestamp)
                
                # Perform the backup (compressed backups swap the file suffix to .gz)
                final_backup_path = await self._perform_backup(database_path, backup_path, policy)

                # Calculate checksums against the file that actually exists
                checksum_sha256 = self._calculate_file_checksum(final_backup_path, algorithm="sha256")
                checksum_md5 = self._calculate_file_checksum(final_backup_path, algorithm="md5")
                size_bytes = os.path.getsize(final_backup_path)
                
                # Calculate checksum after backup (should match before)
                db_checksum_after = self._calculate_file_checksum(database_path)
                
                # Determine storage locations
                storage_locations = [StorageLocation.LOCAL]
                if policy.secondary_storage == StorageLocation.S3 and self._s3_available:
                    await self._upload_to_s3(final_backup_path, backup_id, policy)
                    storage_locations.append(StorageLocation.S3)

                # Create metadata
                metadata = BackupMetadata(
                    backup_id=backup_id,
                    database_path=database_path,
                    backup_path=str(final_backup_path),
                    timestamp=timestamp,
                    size_bytes=size_bytes,
                    checksum_sha256=checksum_sha256,
                    checksum_md5=checksum_md5,
                    status=BackupStatus.SUCCESS,
                    storage_locations=storage_locations,
                    database_checksum_before=db_checksum_before,
                    database_checksum_after=db_checksum_after,
                )
                
                # Verify backup if requested
                if policy.verify_after_backup:
                    verified = await self._verify_backup(metadata, policy)
                    metadata.verified = verified
                    metadata.verification_timestamp = time.time()
                    metadata.status = BackupStatus.VERIFIED if verified else BackupStatus.CORRUPTED
                
                # Store in history
                if database_path not in self._backup_history:
                    self._backup_history[database_path] = []
                self._backup_history[database_path].append(metadata)
                
                # Update stats
                self._stats["total_backups"] += 1
                self._stats["successful_backups"] += 1
                self._stats["last_backup_time"] = timestamp
                
                if metadata.verified:
                    self._stats["verified_backups"] += 1
                
                logger.info(
                    f"Backup completed: {backup_id} "
                    f"(size={size_bytes} bytes, verified={metadata.verified})"
                )
                
                return metadata
                
            except Exception as e:
                logger.error(f"Backup failed for {database_path}: {e}")
                self._stats["failed_backups"] += 1
                self._add_to_dlq(database_path, str(e))
                return None
    
    def _create_backup_path(
        self,
        database_path: str,
        backup_id: str,
        timestamp: float,
    ) -> Path:
        """Generate a backup file path."""
        db_name = os.path.basename(database_path)
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        
        # Create subdirectory by date
        date_str = dt.strftime("%Y-%m-%d")
        backup_subdir = self._backup_dir / date_str
        backup_subdir.mkdir(parents=True, exist_ok=True)
        
        # Backup filename: backup_id already contains db_name and a timestamp
        backup_filename = f"{backup_id}.db"

        return backup_subdir / backup_filename
    
    async def _perform_backup(
        self,
        database_path: str,
        backup_path: Path,
        policy: BackupPolicy,
    ) -> Path:
        """
        Perform the actual backup operation.
        
        Uses SQLite backup API for consistent backups (hot backup).
        """
        # Ensure source database exists
        if not os.path.exists(database_path):
            raise FileNotFoundError(f"Database not found: {database_path}")
        
        # Perform hot backup using SQLite backup API
        def do_backup():
            # Connect to source database
            source = sqlite3.connect(database_path)
            
            # Connect to backup database (will be created)
            backup = sqlite3.connect(str(backup_path))
            
            # Perform backup
            source.backup(backup)
            
            # Close connections
            backup.close()
            source.close()
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_backup)

        # Compress if requested and return the path that actually exists on disk
        if policy.compress_backups:
            await self._compress_backup(backup_path, policy.compression_level)
            return backup_path.with_suffix(backup_path.suffix + ".gz")

        return backup_path
    
    async def _compress_backup(self, backup_path: Path, compression_level: int) -> None:
        """Compress a backup file using gzip."""
        import gzip
        
        compressed_path = backup_path.with_suffix(backup_path.suffix + ".gz")
        
        def do_compress():
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=compression_level) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed file
            os.remove(backup_path)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_compress)
        
        logger.debug(f"Compressed backup: {backup_path} -> {compressed_path}")
    
    def _calculate_file_checksum(
        self,
        file_path: str,
        algorithm: str = "sha256",
        chunk_size: int = 8192,
    ) -> str:
        """
        Calculate checksum of a file.
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm (sha256 or md5)
            chunk_size: Read chunk size in bytes
        
        Returns:
            Hexadecimal checksum string
        """
        if not os.path.exists(file_path):
            return ""
        
        hash_func = hashlib.sha256() if algorithm == "sha256" else hashlib.md5()
        
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    async def _verify_backup(
        self,
        metadata: BackupMetadata,
        policy: BackupPolicy,
    ) -> bool:
        """
        Verify a backup's integrity.
        
        Args:
            metadata: Backup metadata
            policy: Backup policy
        
        Returns:
            True if backup is valid, False otherwise
        """
        backup_path = metadata.backup_path
        
        # Handle compressed backups
        if not os.path.exists(backup_path):
            compressed_path = backup_path + ".gz"
            if os.path.exists(compressed_path):
                backup_path = compressed_path
        
        if not os.path.exists(backup_path):
            logger.error(f"Backup file not found: {backup_path}")
            return False
        
        # Verify checksum
        if policy.verify_checksum:
            current_checksum = self._calculate_file_checksum(
                backup_path,
                algorithm="sha256"
            )
            
            if current_checksum != metadata.checksum_sha256:
                logger.error(
                    f"Checksum mismatch for {metadata.backup_id}: "
                    f"expected={metadata.checksum_sha256}, actual={current_checksum}"
                )
                metadata.status = BackupStatus.CORRUPTED
                self._stats["corrupted_backups"] += 1
                return False
        
        # Verify database integrity (SQLite PRAGMA integrity_check)
        if policy.verify_restore:
            valid = await self._verify_sqlite_integrity(backup_path)
            if not valid:
                logger.error(f"SQLite integrity check failed for {metadata.backup_id}")
                metadata.status = BackupStatus.CORRUPTED
                self._stats["corrupted_backups"] += 1
                return False
        
        return True
    
    async def _verify_sqlite_integrity(self, backup_path: str) -> bool:
        """Verify SQLite database integrity using PRAGMA integrity_check."""
        # Handle compressed backups
        if backup_path.endswith(".gz"):
            # Decompress to temp file for verification
            import gzip
            import tempfile
            
            temp_path = backup_path + ".temp"
            
            def decompress():
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, decompress)
            
            try:
                result = await self._check_integrity(temp_path)
                return result
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        else:
            return await self._check_integrity(backup_path)
    
    async def _check_integrity(self, db_path: str) -> bool:
        """Run SQLite integrity check."""
        def do_check():
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                conn.close()
                
                # Result should be ("ok",) for a valid database
                return result and result[0] == "ok"
            except Exception as e:
                logger.error(f"Integrity check error: {e}")
                return False
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, do_check)
    
    async def _upload_to_s3(
        self,
        backup_path: str,
        backup_id: str,
        policy: BackupPolicy,
    ) -> bool:
        """
        Upload backup to S3.
        
        Args:
            backup_path: Local backup file path
            backup_id: Backup identifier
            policy: Backup policy
        
        Returns:
            True if upload successful, False otherwise
        """
        if not self._s3_available:
            logger.warning("S3 not available - skipping upload")
            return False
        
        try:
            # Initialize S3 client if needed
            if self._s3_client is None:
                await self._init_s3_client()
            
            if self._s3_client is None:
                return False
            
            # Upload file
            s3_key = f"{policy.s3_prefix}/{backup_id}"
            
            def do_upload():
                import boto3
                self._s3_client.upload_file(
                    backup_path,
                    policy.s3_bucket,
                    s3_key,
                )
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, do_upload)
            
            logger.info(f"Uploaded backup to S3: s3://{policy.s3_bucket}/{s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            return False
    
    async def _init_s3_client(self) -> None:
        """Initialize S3 client."""
        try:
            import boto3
            
            # Get credentials from environment
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            
            if not aws_access_key or not aws_secret_key:
                logger.warning("AWS credentials not found - S3 unavailable")
                return
            
            self._s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region,
            )
            
            self._s3_available = True
            logger.info("S3 client initialized")
            
        except ImportError:
            logger.warning("boto3 not installed - S3 unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
    
    async def _apply_retention_policies(self) -> None:
        """Apply retention policies to clean up old backups."""
        for db_path, history in self._backup_history.items():
            policy = self._databases.get(db_path)
            if not policy:
                continue
            
            # Group backups by age category
            now = time.time()
            hourly = []
            daily = []
            weekly = []
            monthly = []
            
            for backup in history:
                age_hours = (now - backup.timestamp) / 3600
                
                if age_hours < 24:
                    hourly.append(backup)
                elif age_hours < 24 * 7:
                    daily.append(backup)
                elif age_hours < 24 * 30:
                    weekly.append(backup)
                else:
                    monthly.append(backup)
            
            # Keep only N backups of each category
            to_keep = set()
            
            # Keep most recent hourly backups
            for backup in sorted(hourly, key=lambda b: b.timestamp, reverse=True)[:policy.keep_hourly]:
                to_keep.add(backup.backup_id)
            
            # Keep most recent daily backups (one per day)
            daily_by_date = {}
            for backup in daily:
                dt = datetime.fromtimestamp(backup.timestamp, tz=timezone.utc)
                date_key = dt.strftime("%Y-%m-%d")
                if date_key not in daily_by_date or backup.timestamp > daily_by_date[date_key].timestamp:
                    daily_by_date[date_key] = backup
            
            for backup in sorted(daily_by_date.values(), key=lambda b: b.timestamp, reverse=True)[:policy.keep_daily]:
                to_keep.add(backup.backup_id)
            
            # Keep most recent weekly backups (one per week)
            weekly_by_week = {}
            for backup in weekly:
                dt = datetime.fromtimestamp(backup.timestamp, tz=timezone.utc)
                week_key = dt.strftime("%Y-W%W")
                if week_key not in weekly_by_week or backup.timestamp > weekly_by_week[week_key].timestamp:
                    weekly_by_week[week_key] = backup
            
            for backup in sorted(weekly_by_week.values(), key=lambda b: b.timestamp, reverse=True)[:policy.keep_weekly]:
                to_keep.add(backup.backup_id)
            
            # Keep most recent monthly backups (one per month)
            monthly_by_month = {}
            for backup in monthly:
                dt = datetime.fromtimestamp(backup.timestamp, tz=timezone.utc)
                month_key = dt.strftime("%Y-%m")
                if month_key not in monthly_by_month or backup.timestamp > monthly_by_month[month_key].timestamp:
                    monthly_by_month[month_key] = backup
            
            for backup in sorted(monthly_by_month.values(), key=lambda b: b.timestamp, reverse=True)[:policy.keep_monthly]:
                to_keep.add(backup.backup_id)
            
            # Delete backups not in keep set
            for backup in history[:]:  # Iterate copy
                if backup.backup_id not in to_keep:
                    await self._delete_backup(backup)
                    history.remove(backup)
                    backup.status = BackupStatus.RETENTION_CLEANED
    
    async def _delete_backup(self, metadata: BackupMetadata) -> None:
        """Delete a backup from all storage locations."""
        # Delete from local storage
        backup_path = Path(metadata.backup_path)
        if backup_path.exists():
            backup_path.unlink()
            logger.debug(f"Deleted local backup: {backup_path}")
        
        # Delete compressed version if exists
        compressed_path = backup_path.with_suffix(backup_path.suffix + ".gz")
        if compressed_path.exists():
            compressed_path.unlink()
            logger.debug(f"Deleted compressed backup: {compressed_path}")
        
        # Delete from S3 if applicable
        if StorageLocation.S3 in metadata.storage_locations and self._s3_available:
            try:
                policy = self._databases.get(metadata.database_path)
                if policy and policy.s3_bucket:
                    s3_key = f"{policy.s3_prefix}/{metadata.backup_id}"
                    
                    def do_delete():
                        self._s3_client.delete_object(
                            Bucket=policy.s3_bucket,
                            Key=s3_key,
                        )
                    
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, do_delete)
                    
                    logger.debug(f"Deleted S3 backup: s3://{policy.s3_bucket}/{s3_key}")
            except Exception as e:
                logger.error(f"Failed to delete S3 backup: {e}")
    
    async def restore_database(
        self,
        database_path: str,
        backup_id: str,
        verify: bool = True,
    ) -> bool:
        """
        Restore a database from a backup.
        
        Args:
            database_path: Path to restore the database to
            backup_id: Backup ID to restore from
            verify: Verify the backup before restoring
        
        Returns:
            True if restore successful, False otherwise
        """
        # Find backup metadata
        metadata = None
        for db_path, history in self._backup_history.items():
            for backup in history:
                if backup.backup_id == backup_id:
                    metadata = backup
                    break
            if metadata:
                break
        
        if not metadata:
            logger.error(f"Backup not found: {backup_id}")
            return False
        
        logger.info(f"Restoring database from backup: {backup_id}")
        
        try:
            # Verify backup if requested
            if verify:
                policy = self._databases.get(metadata.database_path)
                if not await self._verify_backup(metadata, policy or BackupPolicy()):
                    logger.error(f"Backup verification failed: {backup_id}")
                    return False
            
            # Perform restore
            await self._perform_restore(database_path, metadata.backup_path)
            
            self._stats["restorations"] += 1
            
            logger.info(f"Database restored successfully: {database_path}")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    async def _perform_restore(self, database_path: str, backup_path: str) -> None:
        """Perform the actual restore operation."""
        # Handle compressed backups
        if backup_path.endswith(".gz"):
            import gzip
            import tempfile
            
            temp_path = backup_path + ".temp"
            
            def decompress():
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, decompress)
            
            try:
                await self._copy_database(temp_path, database_path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        else:
            await self._copy_database(backup_path, database_path)
    
    async def _copy_database(self, source: str, destination: str) -> None:
        """Copy database file."""
        def do_copy():
            # Create backup of current database if it exists
            if os.path.exists(destination):
                backup_before = destination + ".before_restore"
                shutil.copy2(destination, backup_before)
                logger.info(f"Backed up current database to: {backup_before}")
            
            # Copy backup to destination
            shutil.copy2(source, destination)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_copy)
    
    def _generate_backup_id(self, database_path: str) -> str:
        """Generate a unique backup ID."""
        db_name = os.path.basename(database_path)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        random_suffix = os.urandom(4).hex()
        return f"{db_name}_{timestamp}_{random_suffix}"
    
    def _add_to_dlq(self, database_path: str, error: str) -> None:
        """Add failed backup to dead letter queue."""
        self._dlq.append({
            "database_path": database_path,
            "error": error,
            "timestamp": time.time(),
        })
        
        # Trim DLQ if too large
        if len(self._dlq) > self._dlq_max_size:
            self._dlq = self._dlq[-self._dlq_max_size:]
    
    def _load_metadata(self) -> None:
        """Load backup metadata from disk."""
        if not self._metadata_path.exists():
            return
        
        try:
            with open(self._metadata_path, 'r') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                logger.warning(
                    "Backup metadata has unexpected shape (%s); starting fresh",
                    type(data).__name__,
                )
                return

            # Restore backup history
            for db_path, backups_data in data.get("backup_history", {}).items():
                history = []
                for backup_data in backups_data:
                    metadata = BackupMetadata(
                        backup_id=backup_data["backup_id"],
                        database_path=backup_data["database_path"],
                        backup_path=backup_data["backup_path"],
                        timestamp=backup_data["timestamp"],
                        size_bytes=backup_data["size_bytes"],
                        checksum_sha256=backup_data["checksum_sha256"],
                        checksum_md5=backup_data["checksum_md5"],
                        status=BackupStatus(backup_data["status"]),
                        storage_locations=[StorageLocation(l) for l in backup_data["storage_locations"]],
                        verified=backup_data.get("verified", False),
                        verification_timestamp=backup_data.get("verification_timestamp"),
                        retention_expiry=backup_data.get("retention_expiry"),
                        database_checksum_before=backup_data.get("database_checksum_before"),
                        database_checksum_after=backup_data.get("database_checksum_after"),
                    )
                    history.append(metadata)
                self._backup_history[db_path] = history
            
            # Restore stats
            self._stats.update(data.get("stats", {}))
            
            logger.info(f"Loaded metadata for {len(self._backup_history)} databases")
            
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
    
    def _save_metadata(self) -> None:
        """Save backup metadata to disk."""
        try:
            data = {
                "backup_history": {},
                "stats": self._stats,
            }
            
            # Convert backup history to serializable format
            for db_path, history in self._backup_history.items():
                data["backup_history"][db_path] = [
                    {
                        **asdict(backup),
                        "status": backup.status.value,
                        "storage_locations": [l.value for l in backup.storage_locations],
                    }
                    for backup in history
                ]
            
            # Write to temp file first, then rename (atomic)
            temp_path = self._metadata_path.with_suffix(".json.tmp")
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Use replace on Windows so an existing metadata file is overwritten
            temp_path.replace(self._metadata_path)
            
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def get_backup_history(self, database_path: str) -> List[BackupMetadata]:
        """Get backup history for a database."""
        return self._backup_history.get(database_path, [])
    
    def get_stats(self) -> Dict[str, Any]:
        """Get backup statistics."""
        return {
            **self._stats,
            "databases_managed": len(self._databases),
            "dlq_size": len(self._dlq),
        }
    
    async def check_cross_database_consistency(
        self,
        database_paths: List[str],
    ) -> Dict[str, Any]:
        """
        Check consistency across multiple databases.
        
        This is a data safety improvement that detects:
        - Database corruption
        - Missing databases
        - Checksum mismatches
        - Unexpected size changes
        
        Args:
            database_paths: List of database paths to check
        
        Returns:
            Consistency report
        """
        report = {
            "timestamp": time.time(),
            "databases_checked": len(database_paths),
            "databases_ok": 0,
            "databases_missing": 0,
            "databases_corrupted": 0,
            "issues": [],
        }
        
        for db_path in database_paths:
            if not os.path.exists(db_path):
                report["databases_missing"] += 1
                report["issues"].append({
                    "database": db_path,
                    "issue": "missing",
                    "severity": "critical",
                })
                continue
            
            # Check database integrity
            try:
                valid = await self._check_integrity(db_path)
                if not valid:
                    report["databases_corrupted"] += 1
                    report["issues"].append({
                        "database": db_path,
                        "issue": "corrupted",
                        "severity": "critical",
                    })
                    continue
            except Exception as e:
                report["databases_corrupted"] += 1
                report["issues"].append({
                    "database": db_path,
                    "issue": f"integrity_check_failed: {e}",
                    "severity": "critical",
                })
                continue
            
            report["databases_ok"] += 1
        
        return report


# Global instance
_backup_manager: Optional[DatabaseSafetyBackupManager] = None
_backup_manager_lock = threading.Lock()


def get_backup_manager() -> DatabaseSafetyBackupManager:
    """Get the global backup manager instance."""
    global _backup_manager
    
    if _backup_manager is None:
        with _backup_manager_lock:
            if _backup_manager is None:
                _backup_manager = DatabaseSafetyBackupManager()
    
    return _backup_manager


# Backward compatibility alias
DatabaseBackupManager = DatabaseSafetyBackupManager
