"""
Snapshot Manager.

Creates and manages system state snapshots for backup and recovery.

Version: 1.0.0
"""

from __future__ import annotations

import os
import json
import time
import gzip
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("backup.snapshot")


class SnapshotType(Enum):
    """Types of snapshots."""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class SnapshotStatus(Enum):
    """Status of a snapshot."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CORRUPTED = "corrupted"


@dataclass
class Snapshot:
    """A system state snapshot."""
    snapshot_id: str
    snapshot_type: SnapshotType
    status: SnapshotStatus = SnapshotStatus.PENDING
    
    # Content
    components: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    
    # File info
    file_path: str = ""
    size_bytes: int = 0
    compressed: bool = True
    
    # Integrity
    checksum: str = ""
    
    # Timing
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_seconds: float = 0.0
    
    # Parent (for incremental)
    parent_snapshot_id: Optional[str] = None
    
    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_type": self.snapshot_type.value,
            "status": self.status.value,
            "components": self.components,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "compressed": self.compressed,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "parent_snapshot_id": self.parent_snapshot_id,
            "description": self.description,
            "tags": self.tags,
        }


class SnapshotManager:
    """
    Manages system state snapshots.
    
    Features:
    - Full and incremental snapshots
    - Compression
    - Integrity verification
    - Component-level snapshots
    """
    
    def __init__(self, snapshot_dir: str = "data/snapshots"):
        self.logger = get_logger("backup.snapshot")
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Snapshot registry
        self._snapshots: Dict[str, Snapshot] = {}
        
        # Component collectors
        self._collectors: Dict[str, callable] = {}
        
        # Load existing snapshots
        self._load_snapshot_registry()
        
        # Register default collectors
        self._register_default_collectors()
    
    def _load_snapshot_registry(self) -> None:
        """Load snapshot registry from disk."""
        registry_file = self.snapshot_dir / "registry.json"
        if registry_file.exists():
            try:
                with open(registry_file, "r") as f:
                    data = json.load(f)
                    for snap_data in data.get("snapshots", []):
                        snap = Snapshot(
                            snapshot_id=snap_data["snapshot_id"],
                            snapshot_type=SnapshotType(snap_data["snapshot_type"]),
                            status=SnapshotStatus(snap_data["status"]),
                            components=snap_data.get("components", []),
                            file_path=snap_data.get("file_path", ""),
                            size_bytes=snap_data.get("size_bytes", 0),
                            checksum=snap_data.get("checksum", ""),
                            created_at=snap_data.get("created_at", time.time()),
                            completed_at=snap_data.get("completed_at"),
                            parent_snapshot_id=snap_data.get("parent_snapshot_id"),
                        )
                        self._snapshots[snap.snapshot_id] = snap
            except Exception as e:
                self.logger.error(f"Failed to load snapshot registry: {e}")
    
    def _save_snapshot_registry(self) -> None:
        """Save snapshot registry to disk."""
        registry_file = self.snapshot_dir / "registry.json"
        try:
            with open(registry_file, "w") as f:
                json.dump({
                    "snapshots": [s.to_dict() for s in self._snapshots.values()],
                    "updated_at": time.time(),
                }, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save snapshot registry: {e}")
    
    def _register_default_collectors(self) -> None:
        """Register default component collectors."""
        # Configuration collector
        def collect_config() -> Dict[str, Any]:
            config_files = ["config.json", "settings.json", ".env"]
            config_data = {}
            for cf in config_files:
                path = Path(cf)
                if path.exists():
                    try:
                        with open(path, "r") as f:
                            config_data[cf] = f.read()
                    except Exception as _cf_exc:
                        logger.debug("Config file read failed for %s: %s", cf, _cf_exc)
            return config_data
        
        # Agent state collector
        def collect_agents() -> Dict[str, Any]:
            try:
                from swarm.swarm_coordinator import get_swarm_coordinator
                coordinator = get_swarm_coordinator()
                return coordinator.get_status()
            except Exception as _ag_exc:
                logger.debug("Agent state collection failed: %s", _ag_exc)
                return {}
        
        # Consensus state collector
        def collect_consensus() -> Dict[str, Any]:
            # LEGACY REMOVAL: Consensus module deleted - collector disabled
            logger.debug("Consensus state collection disabled - consensus module deleted")
            return {}
        
        self.register_collector("config", collect_config)
        self.register_collector("agents", collect_agents)
        self.register_collector("consensus", collect_consensus)
    
    def register_collector(self, component: str, collector: callable) -> None:
        """Register a component collector."""
        self._collectors[component] = collector
        self.logger.info(f"Registered collector: {component}")
    
    def create_snapshot(
        self,
        snapshot_type: SnapshotType = SnapshotType.FULL,
        components: Optional[List[str]] = None,
        description: str = "",
        tags: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
    ) -> Snapshot:
        """Create a new snapshot."""
        import uuid
        
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        
        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            status=SnapshotStatus.IN_PROGRESS,
            components=components or list(self._collectors.keys()),
            description=description,
            tags=tags or [],
            parent_snapshot_id=parent_id,
        )
        
        start_time = time.time()
        
        try:
            # Collect data from components
            for component in snapshot.components:
                collector = self._collectors.get(component)
                if collector:
                    try:
                        snapshot.data[component] = collector()
                    except Exception as e:
                        self.logger.error(f"Collector error for {component}: {e}")
                        snapshot.data[component] = {"error": str(e)}
            
            # For incremental, only store changes
            if snapshot_type == SnapshotType.INCREMENTAL and parent_id:
                parent = self._snapshots.get(parent_id)
                if parent:
                    snapshot.data = self._compute_diff(parent.data, snapshot.data)
            
            # Save to file
            snapshot.file_path = str(self._save_snapshot_file(snapshot))
            snapshot.size_bytes = Path(snapshot.file_path).stat().st_size
            
            # Compute checksum
            snapshot.checksum = self._compute_checksum(snapshot.file_path)
            
            snapshot.status = SnapshotStatus.COMPLETED
            snapshot.completed_at = time.time()
            snapshot.duration_seconds = time.time() - start_time
            
            self.logger.info(f"Snapshot created: {snapshot_id} ({snapshot.size_bytes} bytes)")
            
        except Exception as e:
            snapshot.status = SnapshotStatus.FAILED
            self.logger.error(f"Snapshot failed: {e}")
        
        self._snapshots[snapshot_id] = snapshot
        self._save_snapshot_registry()
        
        return snapshot
    
    def _save_snapshot_file(self, snapshot: Snapshot) -> Path:
        """Save snapshot data to file."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{snapshot.snapshot_id}_{timestamp}.json.gz"
        file_path = self.snapshot_dir / filename
        
        data = {
            "metadata": snapshot.to_dict(),
            "data": snapshot.data,
        }
        
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        
        return file_path
    
    def _compute_checksum(self, file_path: str) -> str:
        """Compute file checksum."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _compute_diff(self, old_data: Dict, new_data: Dict) -> Dict:
        """Compute difference between two data sets."""
        diff = {"_type": "diff", "_changes": {}}
        
        for key in set(old_data.keys()) | set(new_data.keys()):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            
            if old_val != new_val:
                diff["_changes"][key] = {
                    "old": old_val,
                    "new": new_val,
                }
        
        return diff
    
    def verify_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Verify snapshot integrity."""
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            return {"valid": False, "error": "Snapshot not found"}
        
        if not snapshot.file_path or not Path(snapshot.file_path).exists():
            return {"valid": False, "error": "Snapshot file not found"}
        
        # Verify checksum
        current_checksum = self._compute_checksum(snapshot.file_path)
        if current_checksum != snapshot.checksum:
            snapshot.status = SnapshotStatus.CORRUPTED
            self._save_snapshot_registry()
            return {"valid": False, "error": "Checksum mismatch"}
        
        # Try to load
        try:
            with gzip.open(snapshot.file_path, "rt", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            return {"valid": False, "error": f"Failed to load: {e}"}
        
        return {"valid": True, "checksum": current_checksum}
    
    def load_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Load snapshot data."""
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot or not snapshot.file_path:
            return None
        
        try:
            with gzip.open(snapshot.file_path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load snapshot: {e}")
            return None
    
    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            return False
        
        # Delete file
        if snapshot.file_path and Path(snapshot.file_path).exists():
            Path(snapshot.file_path).unlink()
        
        del self._snapshots[snapshot_id]
        self._save_snapshot_registry()
        
        return True
    
    def list_snapshots(
        self,
        snapshot_type: Optional[SnapshotType] = None,
        status: Optional[SnapshotStatus] = None,
        limit: int = 100,
    ) -> List[Snapshot]:
        """List snapshots."""
        snapshots = list(self._snapshots.values())
        
        if snapshot_type:
            snapshots = [s for s in snapshots if s.snapshot_type == snapshot_type]
        if status:
            snapshots = [s for s in snapshots if s.status == status]
        
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots[:limit]
    
    def get_latest_snapshot(self, snapshot_type: Optional[SnapshotType] = None) -> Optional[Snapshot]:
        """Get the latest snapshot."""
        snapshots = self.list_snapshots(snapshot_type=snapshot_type, status=SnapshotStatus.COMPLETED, limit=1)
        return snapshots[0] if snapshots else None
    
    def cleanup_old_snapshots(self, retention_days: int = 30) -> int:
        """Remove snapshots older than retention period."""
        cutoff = time.time() - (retention_days * 86400)
        removed = 0
        
        for snapshot_id, snapshot in list(self._snapshots.items()):
            if snapshot.created_at < cutoff:
                self.delete_snapshot(snapshot_id)
                removed += 1
        
        return removed
    
    def get_status(self) -> Dict[str, Any]:
        """Get snapshot manager status."""
        total_size = sum(s.size_bytes for s in self._snapshots.values())
        
        return {
            "snapshot_dir": str(self.snapshot_dir),
            "total_snapshots": len(self._snapshots),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "collectors": list(self._collectors.keys()),
            "latest_snapshot": self.get_latest_snapshot().to_dict() if self.get_latest_snapshot() else None,
        }


# Singleton
_snapshot_manager: Optional[SnapshotManager] = None


def get_snapshot_manager() -> SnapshotManager:
    """Get or create the Snapshot Manager singleton."""
    global _snapshot_manager
    if _snapshot_manager is None:
        _snapshot_manager = SnapshotManager()
    return _snapshot_manager
