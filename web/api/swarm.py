"""Swarm intelligence API — agent coordination and task management endpoints."""
from __future__ import annotations

import time
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException

from social.social_aware_quant import get_social_bot_health_monitor
from swarm import swarm_lab
from swarm.swarm_lab import (
    SwarmLabOrchestrator,
    SwarmLabStatus,
)
from web.api.auth import get_current_session


router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# Agent role name mappings for UI display
_ROLE_NAMES = {
    "product_discovery": "Product Discovery",
    "research_strategy": "Research Strategist",
    "tooling_infra": "Tooling & Infra",
    "ui_ux_workflow": "UI/UX Workflow",
    "code_integration": "Code Integration",
    "evaluation_qa": "Evaluation QA",
    "governance_safety": "Governance & Safety",
}


def _get_orchestrator() -> SwarmLabOrchestrator:
    # Access through module so monkeypatches on swarm.swarm_lab resolve here too.
    return swarm_lab.get_swarm_lab_orchestrator()


def _transform_agents_for_ui(backend_agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform backend agent data to frontend expected format."""
    ui_agents = []
    for i, agent in enumerate(backend_agents):
        agent_id = agent.get("agent_id", f"agent-{i}")
        role = agent.get("role", "unknown")
        active = agent.get("active", False)
        
        ui_agents.append({
            "id": agent_id,
            "name": _ROLE_NAMES.get(role, role.replace("_", " ").title()),
            "role": _ROLE_NAMES.get(role, role),
            "status": "active" if active else "idle",
            "tasks_completed": agent.get("tasks_completed", 0),
            "current_task": None,  # Could be enhanced with real task tracking
            "connections": [a.get("agent_id", f"agent-{j}") for j, a in enumerate(backend_agents) if j != i][:3],
            "confidence": 0.85 + (agent.get("tasks_completed", 0) % 15) * 0.01,
        })
    return ui_agents


def _transform_ideas_to_tasks(top_ideas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform ideas to task format for UI."""
    tasks = []
    for idea in top_ideas:
        status_map = {
            "discovered": "pending",
            "prioritized": "pending", 
            "designing": "in_progress",
            "implementing": "in_progress",
            "testing": "in_progress",
            "staging": "in_progress",
            "approved": "completed",
            "deployed": "completed",
            "rejected": "completed",
        }
        idea_status = idea.get("status", "discovered")
        
        # Estimate progress based on status
        progress_map = {
            "discovered": 0, "prioritized": 10, "designing": 25,
            "implementing": 50, "testing": 70, "staging": 85,
            "approved": 95, "deployed": 100, "rejected": 100,
        }
        
        tasks.append({
            "id": idea.get("idea_id", "task-unknown"),
            "title": idea.get("title", "Unknown Task"),
            "type": idea.get("category", "research"),
            "status": status_map.get(idea_status, "pending"),
            "assigned_agents": [],  # Could be enhanced
            "priority": "high" if idea.get("priority_score", 0) > 0.7 else "medium",
            "progress": progress_map.get(idea_status, 0),
            "created_at": idea.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        })
    return tasks


def _get_real_consensus_metrics() -> Dict[str, Any]:
    """Fetch real consensus rate and response time from the consensus engine."""
    try:
        from core.consensus_engine import get_consensus_engine
        engine = get_consensus_engine()
        metrics = engine.consensus_logger.get_metrics()
        total = metrics.get("total_rounds", 0)
        successful = metrics.get("successful", 0)
        consensus_rate = round(successful / total, 3) if total > 0 else 0.0
        # avg_response_time: use consensus_interval as proxy when no real latency tracked
        avg_response_time = round(engine.consensus_interval, 1)
        return {"consensus_rate": consensus_rate, "avg_response_time": avg_response_time}
    except Exception:
        return {"consensus_rate": 0.0, "avg_response_time": 0.0}


def _transform_metrics_for_ui(backend_metrics: Dict[str, Any], agents: List[Dict]) -> Dict[str, Any]:
    """Transform backend metrics to frontend expected format."""
    active_count = sum(1 for a in agents if a.get("status") == "active")
    coordinating = sum(1 for a in agents if a.get("status") == "coordinating")
    real = _get_real_consensus_metrics()

    return {
        "total_agents": backend_metrics.get("total_agents", len(agents)),
        "active_agents": backend_metrics.get("active_agents", active_count),
        "coordinating_agents": coordinating,
        "tasks_in_progress": backend_metrics.get("ideas_by_status", {}).get("implementing", 0) +
                            backend_metrics.get("ideas_by_status", {}).get("testing", 0),
        "consensus_rate": real["consensus_rate"],
        "avg_response_time": real["avg_response_time"],
    }


def _get_kalshi_agents_for_swarm() -> List[Dict[str, Any]]:
    """Return Kalshi trading agents in swarm-panel format."""
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        grid = get_agent_grid()
        summary = grid.summary()
        agents = []
        for a in summary.get("agents", []):
            agents.append({
                "id": a.get("name", "unknown"),
                "name": a.get("name", "unknown"),
                "role": f"Kalshi {a.get('asset', '')} {a.get('timeframe', '')}".strip(),
                "status": a.get("status", "idle"),
                "tasks_completed": a.get("cycles", 0),
                "current_task": f"{len(a.get('active_tickers', []))} active markets",
                "connections": [],
                "confidence": min(1.0, 0.5 + a.get("win_rate", 0) * 0.5),
                "venue": "kalshi",
            })
        return agents
    except Exception:
        return []


@router.get("/status")
async def swarm_status() -> Dict[str, Any]:
    """Get swarm status formatted for frontend SwarmPanel."""
    orchestrator = _get_orchestrator()
    payload = orchestrator.get_status_payload()
    health = get_social_bot_health_monitor().get_health_status()

    # Transform data for frontend
    backend_agents = payload.get("agents", [])
    ui_agents = _transform_agents_for_ui(backend_agents)

    # Merge Kalshi trading agents into the swarm panel
    kalshi_agents = _get_kalshi_agents_for_swarm()
    ui_agents = kalshi_agents + ui_agents

    ui_tasks = _transform_ideas_to_tasks(payload.get("top_ideas", []))
    ui_metrics = _transform_metrics_for_ui(payload.get("metrics", {}), ui_agents)

    # Augment metrics with Kalshi agent count
    ui_metrics["kalshi_agents"] = len(kalshi_agents)
    ui_metrics["total_agents"] = len(ui_agents)

    return {
        "agents": ui_agents,
        "tasks": ui_tasks,
        "metrics": ui_metrics,
        # Also include raw data for debugging/advanced use
        "_raw": {
            "status": payload["status"],
            "cycle_count": payload["cycle_count"],
            "cycle_interval": payload["cycle_interval"],
            "health": health["components"].get("swarm_lab"),
        }
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
