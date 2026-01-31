from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from social.social_aware_quant import get_social_bot_health_monitor
from swarm import swarm_lab
from swarm.swarm_lab import (
    SwarmLabOrchestrator,
    SwarmLabStatus,
)


router = APIRouter(prefix="/swarm", tags=["swarm"])


def _get_orchestrator() -> SwarmLabOrchestrator:
    # Access through module so monkeypatches on swarm.swarm_lab resolve here too.
    return swarm_lab.get_swarm_lab_orchestrator()


@router.get("/status")
async def swarm_status() -> Dict[str, Any]:
    orchestrator = _get_orchestrator()
    payload = orchestrator.get_status_payload()
    health = get_social_bot_health_monitor().get_health_status()
    return {
        "status": payload["status"],
        "cycle_count": payload["cycle_count"],
        "cycle_interval": payload["cycle_interval"],
        "metrics": payload["metrics"],
        "top_ideas": payload["top_ideas"],
        "agents": payload["agents"],
        "health": health["components"].get("swarm_lab"),
    }


@router.post("/start")
async def swarm_start(interval: float = 60.0) -> Dict[str, Any]:
    orchestrator = _get_orchestrator()
    if orchestrator.status == SwarmLabStatus.RUNNING:
        return {"status": "already_running"}
    await orchestrator.start(cycle_interval=interval)
    return {"status": "running", "cycle_interval": interval}


@router.post("/stop")
async def swarm_stop() -> Dict[str, Any]:
    orchestrator = _get_orchestrator()
    if orchestrator.status == SwarmLabStatus.STOPPED:
        return {"status": "already_stopped"}
    await orchestrator.stop()
    return {"status": "stopped"}
