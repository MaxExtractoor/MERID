"""
Backup & Recovery API Endpoints.

Provides API access to snapshots, backups, and recovery operations.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from web.api.auth import get_current_session

from backup import (
    get_snapshot_manager,
    get_backup_manager,
    get_recovery_manager,
)
from backup.snapshot import SnapshotType
from utils.logger import get_logger

# ZT6-01: All backup/recovery mutation routes require authentication.
router = APIRouter(
    prefix="/api/v1/backup",
    tags=["backup"],
    dependencies=[Depends(get_current_session)],
)
logger = get_logger("web.api.backup")


# ============================================
# REQUEST MODELS
# ============================================

class SnapshotRequest(BaseModel):
    snapshot_type: str = "full"
    components: List[str] = []
    description: str = ""
    tags: List[str] = []


class BackupRequest(BaseModel):
    backup_type: str = "full"
    components: List[str] = []
    destination: str = ""
    description: str = ""


class ScheduleRequest(BaseModel):
    name: str
    interval_hours: float
    backup_type: str = "incremental"


class RecoveryRequest(BaseModel):
    components: List[str] = []
    create_rollback_point: bool = True


# ============================================
# SNAPSHOT ENDPOINTS
# ============================================

@router.get("/snapshots/status")
async def get_snapshot_status() -> Dict[str, Any]:
    """Get snapshot manager status."""
    return get_snapshot_manager().get_status()


@router.get("/snapshots")
async def list_snapshots(
    snapshot_type: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """List snapshots."""
    st = SnapshotType(snapshot_type) if snapshot_type else None
    snapshots = get_snapshot_manager().list_snapshots(snapshot_type=st, limit=limit)
    return {"count": len(snapshots), "snapshots": [s.to_dict() for s in snapshots]}


@router.post("/snapshots")
async def create_snapshot(request: SnapshotRequest) -> Dict[str, Any]:
    """Create a snapshot."""
    try:
        snapshot_type = SnapshotType(request.snapshot_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid snapshot type: {request.snapshot_type}")
    
    snapshot = get_snapshot_manager().create_snapshot(
        snapshot_type=snapshot_type,
        components=request.components or None,
        description=request.description,
        tags=request.tags,
    )
    return {"status": "created", "snapshot": snapshot.to_dict()}


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """Get snapshot details."""
    snapshots = get_snapshot_manager().list_snapshots()
    for s in snapshots:
        if s.snapshot_id == snapshot_id:
            return s.to_dict()
    raise HTTPException(status_code=404, detail="Snapshot not found")


@router.get("/snapshots/{snapshot_id}/verify")
async def verify_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """Verify snapshot integrity."""
    return get_snapshot_manager().verify_snapshot(snapshot_id)


@router.get("/snapshots/{snapshot_id}/data")
async def get_snapshot_data(snapshot_id: str) -> Dict[str, Any]:
    """Get snapshot data."""
    data = get_snapshot_manager().load_snapshot(snapshot_id)
    if data:
        return data
    raise HTTPException(status_code=404, detail="Snapshot not found")


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """Delete a snapshot."""
    success = get_snapshot_manager().delete_snapshot(snapshot_id)
    if success:
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Snapshot not found")


@router.post("/snapshots/cleanup")
async def cleanup_snapshots(retention_days: int = 30) -> Dict[str, Any]:
    """Cleanup old snapshots."""
    removed = get_snapshot_manager().cleanup_old_snapshots(retention_days)
    return {"status": "cleaned", "removed_count": removed}


# ============================================
# BACKUP ENDPOINTS
# ============================================

@router.get("/status")
async def get_backup_status() -> Dict[str, Any]:
    """Get backup manager status."""
    return get_backup_manager().get_status()


@router.post("/start")
async def start_backup_manager(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start backup manager."""
    manager = get_backup_manager()
    background_tasks.add_task(manager.start)
    return {"status": "starting"}


@router.post("/stop")
async def stop_backup_manager() -> Dict[str, Any]:
    """Stop backup manager."""
    await get_backup_manager().stop()
    return {"status": "stopped"}


@router.post("/create")
async def create_backup(request: BackupRequest) -> Dict[str, Any]:
    """Create a backup."""
    try:
        backup_type = SnapshotType(request.backup_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid backup type: {request.backup_type}")
    
    job = await get_backup_manager().create_backup(
        backup_type=backup_type,
        components=request.components or None,
        destination=request.destination or None,
        description=request.description,
    )
    return {"status": job.status.value, "job": job.to_dict()}


@router.get("/jobs")
async def get_backup_jobs() -> Dict[str, Any]:
    """Get backup job history."""
    jobs = get_backup_manager().get_job_history()
    return {"count": len(jobs), "jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_backup_job(job_id: str) -> Dict[str, Any]:
    """Get a specific backup job."""
    job = get_backup_manager().get_job(job_id)
    if job:
        return job.to_dict()
    
    # Check history
    for j in get_backup_manager().get_job_history():
        if j.get("job_id") == job_id:
            return j
    
    raise HTTPException(status_code=404, detail="Job not found")


# ============================================
# SCHEDULE ENDPOINTS
# ============================================

@router.get("/schedules")
async def get_schedules() -> Dict[str, Any]:
    """Get backup schedules."""
    return get_backup_manager().get_schedules()


@router.post("/schedules")
async def add_schedule(request: ScheduleRequest) -> Dict[str, Any]:
    """Add a backup schedule."""
    try:
        backup_type = SnapshotType(request.backup_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid backup type: {request.backup_type}")
    
    schedule = get_backup_manager().add_schedule(
        name=request.name,
        interval_hours=request.interval_hours,
        backup_type=backup_type,
    )
    return {"status": "added", "schedule": schedule.to_dict()}


@router.delete("/schedules/{schedule_id}")
async def remove_schedule(schedule_id: str) -> Dict[str, Any]:
    """Remove a backup schedule."""
    success = get_backup_manager().remove_schedule(schedule_id)
    if success:
        return {"status": "removed"}
    raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/schedules/{schedule_id}/enable")
async def enable_schedule(schedule_id: str) -> Dict[str, Any]:
    """Enable a schedule."""
    success = get_backup_manager().enable_schedule(schedule_id)
    if success:
        return {"status": "enabled"}
    raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/schedules/{schedule_id}/disable")
async def disable_schedule(schedule_id: str) -> Dict[str, Any]:
    """Disable a schedule."""
    success = get_backup_manager().disable_schedule(schedule_id)
    if success:
        return {"status": "disabled"}
    raise HTTPException(status_code=404, detail="Schedule not found")


# ============================================
# RECOVERY ENDPOINTS
# ============================================

@router.get("/recovery/status")
async def get_recovery_status() -> Dict[str, Any]:
    """Get recovery manager status."""
    return get_recovery_manager().get_status()


@router.get("/recovery/points")
async def get_recovery_points() -> Dict[str, Any]:
    """Get available recovery points."""
    points = get_recovery_manager().get_recovery_points()
    return {"count": len(points), "points": [p.to_dict() for p in points]}


@router.post("/recovery/points/refresh")
async def refresh_recovery_points() -> Dict[str, Any]:
    """Refresh recovery points."""
    points = get_recovery_manager().refresh_recovery_points()
    return {"count": len(points), "points": [p.to_dict() for p in points]}


@router.get("/recovery/points/{point_id}/validate")
async def validate_recovery_point(point_id: str) -> Dict[str, Any]:
    """Validate a recovery point."""
    return get_recovery_manager().validate_recovery_point(point_id)


@router.post("/recovery/points/{point_id}/recover")
async def start_recovery(point_id: str, request: RecoveryRequest) -> Dict[str, Any]:
    """Start a recovery operation."""
    operation = await get_recovery_manager().start_recovery(
        point_id=point_id,
        components=request.components or None,
        create_rollback_point=request.create_rollback_point,
    )
    return {"status": operation.status.value, "operation": operation.to_dict()}


@router.get("/recovery/operations")
async def get_recovery_operations() -> Dict[str, Any]:
    """Get recovery operation history."""
    operations = get_recovery_manager().get_operation_history()
    return {"count": len(operations), "operations": operations}


@router.get("/recovery/operations/{operation_id}")
async def get_recovery_operation(operation_id: str) -> Dict[str, Any]:
    """Get a specific recovery operation."""
    operation = get_recovery_manager().get_operation(operation_id)
    if operation:
        return operation.to_dict()
    
    # Check history
    for op in get_recovery_manager().get_operation_history():
        if op.get("operation_id") == operation_id:
            return op
    
    raise HTTPException(status_code=404, detail="Operation not found")
