"""
API endpoints for the AgentOrchestrator.
Exposes cycle status, phase results, and history to the frontend.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])


_orchestrator_instance = None
_orchestrator_lock = threading.Lock()  # FPA-06


def _get_orchestrator():
    """Get the global orchestrator singleton."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        with _orchestrator_lock:
            if _orchestrator_instance is None:
                try:
                    # Bootstrap canonical agents first
                    from merid.agents.bootstrap import ensure_bootstrapped
                    agent_count = ensure_bootstrapped()
                    logger.info(f"Bootstrapped {agent_count} canonical agents")

                    # Create orchestrator with populated registry
                    from merid.agents.orchestrator import AgentOrchestrator
                    from merid.agents.base import get_canonical_registry
                    registry = get_canonical_registry()
                    _orchestrator_instance = AgentOrchestrator(registry=registry)
                    logger.info(f"Orchestrator singleton created: {registry.count()} agents registered")
                except Exception as e:
                    logger.error(f"Failed to create AgentOrchestrator: {e}", exc_info=True)
                    return None
    return _orchestrator_instance


@router.get("/summary")
async def get_orchestrator_summary():
    """Get orchestrator summary including latest cycle."""
    orch = _get_orchestrator()
    if not orch:
        return {"status": "unavailable", "latest_cycle": None}

    try:
        summary = orch.summary()

        history = orch.get_history()
        latest_cycle = None
        if history:
            last = history[-1]
            phases = []
            for phase_result in last.get("phases", []):
                agents = []
                for agent_out in phase_result.get("outputs", []):
                    agents.append({
                        "name": agent_out.get("agent", "unknown"),
                        "status": "success" if agent_out.get("output") else "error",
                        "outputSummary": str(agent_out.get("output", ""))[:80],
                        "durationMs": agent_out.get("duration_ms", 0),
                    })
                phases.append({
                    "name": phase_result.get("phase", "UNKNOWN"),
                    "status": "completed",
                    "agentCount": len(agents),
                    "outputCount": sum(1 for a in agents if a["status"] == "success"),
                    "durationMs": phase_result.get("duration_ms", 0),
                    "agents": agents,
                })

            latest_cycle = {
                "cycleId": last.get("cycle_id", 0),
                "startedAt": last.get("started_at", ""),
                "completedAt": last.get("completed_at", ""),
                "totalDurationMs": last.get("total_duration_ms", 0),
                "phases": phases,
                "proposalsGenerated": last.get("proposals_generated", 0),
                "spikesDetected": last.get("spikes_detected", 0),
                "verdictsIssued": last.get("verdicts_issued", 0),
            }

        return {
            "status": "ok",
            "summary": summary,
            "latest_cycle": latest_cycle,
        }
    except Exception as e:
        logger.error(f"Error fetching orchestrator summary: {e}")
        return {"status": "error", "error": str(e), "latest_cycle": None}


@router.get("/history")
async def get_orchestrator_history(limit: int = Query(default=20)):
    """Get recent orchestrator cycle history."""
    orch = _get_orchestrator()
    if not orch:
        return {"status": "unavailable", "cycles": []}

    try:
        history = orch.get_history()
        cycles = []
        for cycle in history[-limit:]:
            cycles.append({
                "cycleId": cycle.get("cycle_id", 0),
                "startedAt": cycle.get("started_at", ""),
                "completedAt": cycle.get("completed_at", ""),
                "totalDurationMs": cycle.get("total_duration_ms", 0),
                "phaseCount": len(cycle.get("phases", [])),
                "proposalsGenerated": cycle.get("proposals_generated", 0),
            })
        return {"status": "ok", "cycles": cycles}
    except Exception as e:
        logger.error(f"Error fetching orchestrator history: {e}")
        return {"status": "error", "error": str(e), "cycles": []}
