"""
MERID Backup & Recovery System.

Provides state snapshots, incremental backups, and disaster recovery.

Version: 1.0.0
"""

from backup.snapshot import SnapshotManager, Snapshot, get_snapshot_manager
from backup.backup_manager import BackupManager, BackupJob, get_backup_manager
from backup.recovery import RecoveryManager, get_recovery_manager

__all__ = [
    "SnapshotManager",
    "Snapshot",
    "get_snapshot_manager",
    "BackupManager",
    "BackupJob",
    "get_backup_manager",
    "RecoveryManager",
    "get_recovery_manager",
]

# Backup settings
BACKUP_ENABLED = True
AUTO_BACKUP_INTERVAL_HOURS = 6
RETENTION_DAYS = 30
