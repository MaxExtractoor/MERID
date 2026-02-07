"""
Reflection Layer API Endpoints.

Exposes agent self-learning and performance metrics.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from agents.reflection_layer import reflection_layer

router = APIRouter(prefix="/api/v1/reflection", tags=["reflection"])


@router.get("/agents/{agent_id}/stats")
async def get_agent_reflection_stats(agent_id: str):
    """Get reflection statistics for a specific agent."""
    stats = reflection_layer.get_agent_stats(agent_id)
    
    if not stats or stats.get("total_decisions", 0) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No reflection data found for agent {agent_id}"
        )
    
    return {
        "agent_id": agent_id,
        "stats": stats
    }


@router.get("/agents/{agent_id}/reflections")
async def get_agent_reflections(agent_id: str, limit: int = 50):
    """Get reflection history for a specific agent."""
    reflections = reflection_layer.get_all_reflections(agent_id=agent_id, limit=limit)
    
    return {
        "agent_id": agent_id,
        "reflections": reflections,
        "count": len(reflections)
    }


@router.get("/reflections")
async def get_all_reflections(limit: int = 100):
    """Get all reflections across all agents."""
    reflections = reflection_layer.get_all_reflections(limit=limit)
    
    return {
        "reflections": reflections,
        "count": len(reflections)
    }


@router.get("/summary")
async def get_reflection_summary():
    """Get summary of reflection layer activity."""
    # Get stats for all agents
    all_reflections = reflection_layer.get_all_reflections(limit=1000)
    
    agent_ids = set(r["agent_id"] for r in all_reflections)
    
    summary = {
        "total_reflections": len(all_reflections),
        "active_agents": len(agent_ids),
        "agents": []
    }
    
    for agent_id in agent_ids:
        stats = reflection_layer.get_agent_stats(agent_id)
        if stats and stats.get("total_decisions", 0) > 0:
            total = stats["total_decisions"]
            correct = stats.get("correct_predictions", 0)
            accuracy = (correct / total * 100) if total > 0 else 0
            
            summary["agents"].append({
                "agent_id": agent_id,
                "total_decisions": total,
                "accuracy": round(accuracy, 2),
                "avg_reality_gap": round(stats.get("avg_reality_gap", 0) * 100, 2),
                "recent_learnings": len(stats.get("learnings", []))
            })
    
    # Sort by accuracy descending
    summary["agents"].sort(key=lambda x: x["accuracy"], reverse=True)
    
    return summary
