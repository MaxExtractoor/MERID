"""
Backup Manager.

Manages scheduled backups and backup jobs.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from backup.snapshot import SnapshotManager, get_snapshot_manager, SnapshotType
from utils.logger import get_logger

logger = get_logger("backup.manager")


class BackupStatus(Enum):
    """Status of a backup job."""
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackupJob:
    """A backup job."""
    job_id: str
    status: BackupStatus = BackupStatus.SCHEDULED
    
    # Configuration
    backup_type: SnapshotType = SnapshotType.FULL
    components: List[str] = field(default_factory=list)
    destination: str = ""
    
    # Results
    snapshot_id: str = ""
    file_path: str = ""
    size_bytes: int = 0
    
    # Timing
    scheduled_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: float = 0.0
    
    # Error
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "backup_type": self.backup_type.value,
            "components": self.components,
            "destination": self.destination,
            "snapshot_id": self.snapshot_id,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }


@dataclass
class BackupSchedule:
    """A backup schedule."""
    schedule_id: str
    name: str
    
    # Schedule
    interval_hours: float = 6.0
    backup_type: SnapshotType = SnapshotType.INCREMENTAL
    
    # State
    enabled: bool = True
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    
    # Statistics
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "interval_hours": self.interval_hours,
            "backup_type": self.backup_type.value,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
        }


class BackupManager:
    """
    Manages backup operations and schedules.
    
    Features:
    - Scheduled backups
    - Manual backup triggers
    - Backup to external destinations
    - Job history
    """
    
    def __init__(self, backup_dir: str = "data/backups"):
        self.logger = get_logger("backup.manager")
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self._snapshot_manager = get_snapshot_manager()
        
        # Jobs
        self._jobs: Dict[str, BackupJob] = {}
        self._job_history: List[BackupJob] = []
        self._max_history: int = 100
        
        # Schedules
        self._schedules: Dict[str, BackupSchedule] = {}
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        
        # Initialize default schedule
        self._init_default_schedules()
    
    def _init_default_schedules(self) -> None:
        """Initialize default backup schedules."""
        # Full backup daily
        self._schedules["daily_full"] = BackupSchedule(
            schedule_id="daily_full",
            name="Daily Full Backup",
            interval_hours=24.0,
            backup_type=SnapshotType.FULL,
        )
        
        # Incremental every 6 hours
        self._schedules["incremental_6h"] = BackupSchedule(
            schedule_id="incremental_6h",
            name="6-Hour Incremental",
            interval_hours=6.0,
            backup_type=SnapshotType.INCREMENTAL,
        )
    
    async def start(self) -> None:
        """Start backup manager."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())
        self.logger.info("Backup manager started")
    
    async def stop(self) -> None:
        """Stop backup manager."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Backup manager stopped")
    
    async def _schedule_loop(self) -> None:
        """Main schedule loop."""
        while self._running:
            try:
                now = time.time()
                
                for schedule in self._schedules.values():
                    if not schedule.enabled:
                        continue
                    
                    # Calculate next run
                    if schedule.next_run is None:
                        schedule.next_run = now + (schedule.interval_hours * 3600)
                    
                    # Check if due
                    if now >= schedule.next_run:
                        await self._run_scheduled_backup(schedule)
                        schedule.next_run = now + (schedule.interval_hours * 3600)
                
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Schedule loop error: {e}")
                await asyncio.sleep(300)
    
    async def _run_scheduled_backup(self, schedule: BackupSchedule) -> None:
        """Run a scheduled backup."""
        self.logger.info(f"Running scheduled backup: {schedule.name}")
        
        schedule.total_runs += 1
        schedule.last_run = time.time()
        
        try:
            job = await self.create_backup(
                backup_type=schedule.backup_type,
                description=f"Scheduled: {schedule.name}",
            )
            
            if job.status == BackupStatus.COMPLETED:
                schedule.successful_runs += 1
            else:
                schedule.failed_runs += 1
                
        except Exception as e:
            schedule.failed_runs += 1
            self.logger.error(f"Scheduled backup failed: {e}")
    
    async def create_backup(
        self,
        backup_type: SnapshotType = SnapshotType.FULL,
        components: Optional[List[str]] = None,
        destination: Optional[str] = None,
        description: str = "",
    ) -> BackupJob:
        """Create a backup."""
        import uuid
        
        job_id = f"backup_{uuid.uuid4().hex[:12]}"
        
        job = BackupJob(
            job_id=job_id,
            status=BackupStatus.RUNNING,
            backup_type=backup_type,
            components=components or [],
            destination=destination or str(self.backup_dir),
        )
        
        self._jobs[job_id] = job
        job.started_at = time.time()
        
        try:
            # Get parent for incremental
            parent_id = None
            if backup_type == SnapshotType.INCREMENTAL:
                latest = self._snapshot_manager.get_latest_snapshot(SnapshotType.FULL)
                if latest:
                    parent_id = latest.snapshot_id
            
            # Create snapshot
            snapshot = self._snapshot_manager.create_snapshot(
                snapshot_type=backup_type,
                components=components,
                description=description,
                parent_id=parent_id,
            )
            
            job.snapshot_id = snapshot.snapshot_id
            job.file_path = snapshot.file_path
            job.size_bytes = snapshot.size_bytes
            
            # Copy to destination if different
            if destination and destination != str(self.backup_dir):
                dest_path = Path(destination)
                dest_path.mkdir(parents=True, exist_ok=True)
                dest_file = dest_path / Path(snapshot.file_path).name
                shutil.copy2(snapshot.file_path, dest_file)
                job.file_path = str(dest_file)
            
            job.status = BackupStatus.COMPLETED
            self.logger.info(f"Backup completed: {job_id}")
            
        except Exception as e:
            job.status = BackupStatus.FAILED
            job.error_message = str(e)
            self.logger.error(f"Backup failed: {e}")
        
        job.completed_at = time.time()
        job.duration_seconds = job.completed_at - job.started_at
        
        # Move to history
        self._job_history.append(job)
        if len(self._job_history) > self._max_history:
            self._job_history = self._job_history[-self._max_history:]
        
        del self._jobs[job_id]
        
        return job
    
    def add_schedule(
        self,
        name: str,
        interval_hours: float,
        backup_type: SnapshotType = SnapshotType.INCREMENTAL,
    ) -> BackupSchedule:
        """Add a backup schedule."""
        import uuid
        
        schedule_id = f"schedule_{uuid.uuid4().hex[:8]}"
        
        schedule = BackupSchedule(
            schedule_id=schedule_id,
            name=name,
            interval_hours=interval_hours,
            backup_type=backup_type,
        )
        
        self._schedules[schedule_id] = schedule
        return schedule
    
    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a backup schedule."""
        if schedule_id in self._schedules:
            del self._schedules[schedule_id]
            return True
        return False
    
    def enable_schedule(self, schedule_id: str) -> bool:
        """Enable a schedule."""
        schedule = self._schedules.get(schedule_id)
        if schedule:
            schedule.enabled = True
            return True
        return False
    
    def disable_schedule(self, schedule_id: str) -> bool:
        """Disable a schedule."""
        schedule = self._schedules.get(schedule_id)
        if schedule:
            schedule.enabled = False
            return True
        return False
    
    def get_job(self, job_id: str) -> Optional[BackupJob]:
        """Get a backup job."""
        return self._jobs.get(job_id)
    
    def get_job_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get job history."""
        return [j.to_dict() for j in self._job_history[-limit:]]
    
    def get_schedules(self) -> Dict[str, Dict[str, Any]]:
        """Get all schedules."""
        return {k: v.to_dict() for k, v in self._schedules.items()}
    
    def get_status(self) -> Dict[str, Any]:
        """Get backup manager status."""
        return {
            "running": self._running,
            "backup_dir": str(self.backup_dir),
            "active_jobs": len(self._jobs),
            "job_history_count": len(self._job_history),
            "schedules": self.get_schedules(),
            "recent_jobs": self.get_job_history(10),
        }


# Singleton
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """Get or create the Backup Manager singleton."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
