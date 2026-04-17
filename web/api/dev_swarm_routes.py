"""
Dev Swarm API Routes

REST API for MERID Dev Swarm task submission, management, and monitoring.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncio
import time
import uuid

from core.dev_swarm import (
    DevSwarm, DevTask, DevAgent,
    create_merid_dev_swarm, DevAgentRole
)
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.dev_swarm")

router = APIRouter(prefix="/api/dev-swarm", tags=["dev-swarm"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Global swarm instance (singleton)
_swarm_instance: Optional[DevSwarm] = None
_swarm_lock = asyncio.Lock()
_task_registry: Dict[str, Dict[str, Any]] = {}
_is_paused: bool = False


async def _get_swarm() -> DevSwarm:
    global _swarm_instance
    if _swarm_instance is None:
        async with _swarm_lock:
            if _swarm_instance is None:
                _swarm_instance = create_merid_dev_swarm()
    return _swarm_instance


# Request/Response Models
class CreateTaskRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    target_files: List[str] = Field(default=[])
    success_criteria: str = Field(default="Task completed successfully")
    priority: int = Field(default=1, ge=1, le=5)
    estimated_effort: str = Field(default="medium")
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    max_cost_usd: float = Field(default=5.0, ge=0.1, le=50.0)


def _task_entry(task_id: str, req: CreateTaskRequest, status: str = "pending") -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "description": req.description,
        "target_files": req.target_files,
        "success_criteria": req.success_criteria,
        "priority": req.priority,
        "estimated_effort": req.estimated_effort,
        "timeout_seconds": req.timeout_seconds,
        "max_cost_usd": req.max_cost_usd,
        "status": status,
        "created_at": time.time(),
        "started_at": None,
        "completed_at": None,
        "error": None,
        "cost_usd": 0.0,
        "duration_seconds": None,
        "result": None,
    }


@router.post("/tasks", status_code=201)
async def create_task(request: CreateTaskRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Create and queue a new dev swarm task."""
    global _is_paused
    if _is_paused:
        raise HTTPException(status_code=409, detail="Swarm is paused")

    task_id = str(uuid.uuid4())[:8]
    entry = _task_entry(task_id, request, status="pending")
    _task_registry[task_id] = entry

    async def _run():
        entry["status"] = "running"
        entry["started_at"] = time.time()
        try:
            swarm = await _get_swarm()
            core_task = DevTask(
                description=request.description,
                target_files=request.target_files or ["README.md"],
                success_criteria=request.success_criteria,
                priority=request.priority,
                estimated_effort=request.estimated_effort,
            )
            result = await swarm.execute_task(core_task)
            entry["status"] = result.get("status", "completed")
            entry["result"] = result
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        finally:
            entry["completed_at"] = time.time()
            if entry["started_at"]:
                entry["duration_seconds"] = entry["completed_at"] - entry["started_at"]

    background_tasks.add_task(_run)
    return entry


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """List dev swarm tasks."""
    tasks = list(_task_registry.values())

    # Also include tasks from swarm task_history not in registry
    swarm = await _get_swarm()
    registry_ids = set(_task_registry.keys())
    for t in swarm.task_history:
        tid = getattr(t, 'task_id', None) if hasattr(t, 'task_id') else (t.get('task_id') if isinstance(t, dict) else None)
        if tid and tid not in registry_ids:
            if hasattr(t, 'task_id'):
                tasks.append({
                    "task_id": t.task_id, "description": t.description,
                    "status": t.status, "started_at": t.started_at,
                    "completed_at": t.completed_at, "created_at": t.started_at or 0,
                    "error": t.error,
                })
            else:
                tasks.append(t)

    if status:
        tasks = [t for t in tasks if (t.get("status") if isinstance(t, dict) else getattr(t, 'status', None)) == status]
    tasks.sort(key=lambda t: t.get("created_at", 0) if isinstance(t, dict) else getattr(t, 'started_at', 0) or 0, reverse=True)
    paginated = tasks[offset:offset + limit]

    active = sum(1 for t in tasks if (t.get("status") if isinstance(t, dict) else getattr(t, 'status', None)) == "running")
    completed = sum(1 for t in tasks if (t.get("status") if isinstance(t, dict) else getattr(t, 'status', None)) == "completed")
    failed = sum(1 for t in tasks if (t.get("status") if isinstance(t, dict) else getattr(t, 'status', None)) == "failed")

    return {"tasks": paginated, "total": len(tasks), "active": active, "completed": completed, "failed": failed}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    """Get a specific task."""
    # Check task registry first
    if task_id in _task_registry:
        return _task_registry[task_id]

    # Check swarm active_tasks and task_history
    swarm = await _get_swarm()
    if task_id in swarm.active_tasks:
        t = swarm.active_tasks[task_id]
        duration = (time.time() - t.started_at) if t.started_at else None
        return {
            "task_id": t.task_id, "description": t.description,
            "status": t.status, "started_at": t.started_at,
            "completed_at": t.completed_at, "duration_seconds": duration,
            "error": t.error, "result": t.result,
        }
    for t in swarm.task_history:
        tid = getattr(t, 'task_id', None) or (t.get('task_id') if isinstance(t, dict) else None)
        if tid == task_id:
            if hasattr(t, 'task_id'):
                return {
                    "task_id": t.task_id, "description": t.description,
                    "status": t.status, "started_at": t.started_at,
                    "completed_at": t.completed_at, "error": t.error,
                    "duration_seconds": (t.completed_at - t.started_at) if t.started_at and t.completed_at else None,
                }
            return t
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str) -> Dict[str, str]:
    """Cancel a task."""
    # Check registry
    if task_id in _task_registry:
        entry = _task_registry[task_id]
        if entry["status"] not in ("pending", "running"):
            raise HTTPException(status_code=409, detail="Task is not cancellable")
        entry["status"] = "cancelled"
        entry["completed_at"] = time.time()
        return {"message": f"Task {task_id} cancelled"}

    # Check swarm active_tasks
    swarm = await _get_swarm()
    if task_id in swarm.active_tasks:
        await swarm.cancel_task(task_id)
        return {"message": f"Task {task_id} cancelled"}

    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.get("/agents")
async def list_agents() -> List[Dict[str, Any]]:
    """List registered agents."""
    try:
        # Use existing instance if already initialized (avoid heavy init in request)
        if _swarm_instance is not None:
            return [
                {
                    "name": a.name,
                    "role": a.role.value,
                    "llm_model": getattr(a, "llm_model", "unknown"),
                    "max_iterations": getattr(a, "max_iterations", 3),
                    "timeout_seconds": getattr(a, "timeout_seconds", 1800),
                }
                for a in _swarm_instance.agents
            ]
    except Exception as e:
        logger.error(f"Failed to list dev swarm agents: {e}")
    # Return known agent definitions without heavy init
    return [
        {"name": "CoveragePlanner", "role": "planner", "llm_model": "deepseek-chat", "max_iterations": 3, "timeout_seconds": 1800},
        {"name": "PyTestCoder", "role": "coder", "llm_model": "deepseek-chat", "max_iterations": 5, "timeout_seconds": 1800},
        {"name": "TestValidator", "role": "tester", "llm_model": "deepseek-chat", "max_iterations": 3, "timeout_seconds": 1800},
        {"name": "CodeReviewer", "role": "reviewer", "llm_model": "deepseek-chat", "max_iterations": 2, "timeout_seconds": 1800},
    ]


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """Swarm statistics."""
    swarm = await _get_swarm()
    tasks = list(_task_registry.values())
    completed = [t for t in tasks if t["status"] == "completed"]
    failed = [t for t in tasks if t["status"] == "failed"]
    total = len(tasks)
    durations = [t["duration_seconds"] for t in completed if t.get("duration_seconds")]

    return {
        "active_tasks": sum(1 for t in tasks if t["status"] == "running"),
        "total_tasks": total,
        "completed": len(completed),
        "failed": len(failed),
        "timeout": sum(1 for t in tasks if t["status"] == "timeout"),
        "cancelled": sum(1 for t in tasks if t["status"] == "cancelled"),
        "success_rate": len(completed) / max(total, 1),
        "avg_duration_seconds": sum(durations) / max(len(durations), 1) if durations else 0,
        "daily_cost_usd": sum(t.get("cost_usd", 0) for t in tasks),
        "cost_budget_remaining": max(0.0, float(__import__('os').getenv('MERID_DAILY_COST_BUDGET', '100')) - sum(t.get("cost_usd", 0) for t in tasks)),
    }


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check."""
    swarm = await _get_swarm()
    active = sum(1 for t in _task_registry.values() if t["status"] == "running")
    checks = {
        "agents_registered": len(swarm.agents) > 0,
        "not_shutdown": not getattr(swarm, 'shutdown', getattr(swarm, '_shutdown', False)),
        "not_paused": not _is_paused,
    }
    status = "healthy" if all(checks.values()) else "degraded"
    return {
        "status": status,
        "active_tasks": active,
        "agents": len(swarm.agents),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/config")
async def update_config(
    max_concurrent_tasks: Optional[int] = Query(None),
    max_daily_cost_usd: Optional[float] = Query(None),
    default_task_timeout: Optional[int] = Query(None),
) -> Dict[str, Any]:
    """Update swarm configuration."""
    swarm = await _get_swarm()
    updates = {}
    if max_concurrent_tasks is not None:
        swarm.config.max_concurrent_tasks = max_concurrent_tasks
        updates["max_concurrent_tasks"] = max_concurrent_tasks
    if max_daily_cost_usd is not None:
        swarm.config.max_daily_cost_usd = max_daily_cost_usd
        updates["max_daily_cost_usd"] = max_daily_cost_usd
    if default_task_timeout is not None:
        swarm.config.default_task_timeout = default_task_timeout
        updates["default_task_timeout"] = default_task_timeout
    if not updates:
        return {"message": "No configuration changes requested", "updates": {}}
    return {"message": "Configuration updated", "updates": updates}


# Readiness audit
@router.get("/readiness")
async def get_readiness() -> Dict[str, Any]:
    """Run the Dev Swarm Readiness Auditor and return results."""
    from core.dev_swarm_readiness_auditor import run_audit
    report = run_audit()
    return {
        "passed": report.passed,
        "drift_count": report.drift_count,
        "checks": [
            {"area": r.area, "item": r.item, "status": r.status.value, "evidence": r.evidence, "fix_plan": r.fix_plan}
            for r in report.results
        ],
    }


@router.get("/codebase-drift")
async def get_codebase_drift() -> Dict[str, Any]:
    """Run the Codebase Drift Auditor."""
    from core.codebase_drift_auditor import run_drift_audit
    report = run_drift_audit()
    return report.to_dict()


@router.get("/readiness/slo")
async def get_readiness_slo() -> Dict[str, Any]:
    """Return SLO metrics from readiness audit history."""
    from core.dev_swarm_readiness_auditor import compute_slo, load_history
    from dataclasses import asdict
    slo = compute_slo()
    history = load_history(max_records=30)
    return {**asdict(slo), "history": history[-30:]}


@router.post("/pause")
async def pause_swarm() -> Dict[str, Any]:
    """Pause the swarm."""
    global _is_paused
    changed = not _is_paused
    _is_paused = True
    return {"paused": True, "changed": changed}


@router.post("/resume")
async def resume_swarm() -> Dict[str, Any]:
    """Resume the swarm."""
    global _is_paused
    changed = _is_paused
    _is_paused = False
    return {"paused": False, "changed": changed}


@router.post("/shutdown")
async def shutdown_swarm() -> Dict[str, Any]:
    """Shutdown the dev swarm — pauses and clears task queue."""
    global _is_paused, _task_registry
    _is_paused = True
    cancelled = 0
    for tid, entry in _task_registry.items():
        if entry.get("status") in ("pending", "running"):
            entry["status"] = "cancelled"
            cancelled += 1
    swarm = await _get_swarm()
    await swarm.shutdown()
    return {
        "message": "Swarm shutdown initiated",
        "warning": "All pending tasks have been cancelled",
        "shutdown": True,
        "paused": True,
        "cancelled_tasks": cancelled,
    }
