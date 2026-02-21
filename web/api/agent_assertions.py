"""
Agent Assertion API

Endpoints for registering and managing agent data assertions.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import time

from agent.assertion_source import get_agent_assertion_source
from utils.logger import get_logger

logger = get_logger("web.api.agent_assertions")
router = APIRouter(prefix="/api/v1/agent", tags=["agent-assertions"])


class AgentDataPoint(BaseModel):
    """Single agent data point."""
    agent_name: str = Field(..., description="Agent name")
    status: str = Field(..., description="Agent status (ACTIVE/INACTIVE/ERROR)")
    health_score: float = Field(..., ge=0.0, le=1.0, description="Agent health score")
    last_heartbeat: float = Field(..., ge=0.0, description="Last heartbeat timestamp")
    source: str = Field(default="swarm_registry", description="Data source")


class AgentDataBatch(BaseModel):
    """Batch of agent data points."""
    agent_data: List[AgentDataPoint] = Field(..., description="Agent data points")
    source: str = Field(default="batch", description="Batch source")


class AgentAssertionResponse(BaseModel):
    """Response for agent assertion operations."""
    status: str
    message: str
    assertions_registered: int = 0
    blind_spots_before: List[str] = []
    blind_spots_after: List[str] = []
    timestamp: float


@router.post("/assertions/register")
async def register_agent_assertion(agent_data: AgentDataPoint):
    """Register a single agent data assertion."""
    try:
        source = get_agent_assertion_source()
        
        # Get blind spots before
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Update agent data
        source.update_agent_state(
            agent_name=agent_data.agent_name,
            status=agent_data.status,
            health_score=agent_data.health_score,
            last_heartbeat=agent_data.last_heartbeat,
            source=agent_data.source
        )
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return AgentAssertionResponse(
            status="success",
            message=f"Agent assertion registered for {agent_data.agent_name}",
            assertions_registered=1,
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering agent assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/batch")
async def register_agent_assertions_batch(batch: AgentDataBatch):
    """Register multiple agent data assertions."""
    try:
        source = get_agent_assertion_source()
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Convert to list format
        agent_data_list = [
            {
                "agent_name": data.agent_name,
                "status": data.status,
                "health_score": data.health_score,
                "last_heartbeat": data.last_heartbeat,
                "source": batch.source
            }
            for data in batch.agent_data
        ]
        
        # Register batch
        source.register_batch_agent_data(agent_data_list)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return AgentAssertionResponse(
            status="success",
            message=f"Batch registered {len(agent_data_list)} agent assertions",
            assertions_registered=len(agent_data_list),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering agent assertions batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions")
async def get_agent_assertions():
    """Get all agent assertions."""
    try:
        source = get_agent_assertion_source()
        assertions = source.get_agent_assertions()
        
        return {
            "status": "success",
            "domain": "agent",
            "assertions": assertions,
            "count": len(assertions),
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting agent assertions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blind-spots")
async def get_agent_blind_spots():
    """Get current blind spots and agent domain status."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind spots)
        registry_status = registry.get_registry_status(current_time, auditor.regime_entropy)
        
        # Get agent-specific assertions
        agent_assertions = registry.get_assertions_by_domain("agent")
        valid_agent_assertions = sum(1 for a in agent_assertions if a.status.value == "valid")
        
        return {
            "status": "success",
            "domain": "agent",
            "blind_spots": registry_status["blind_spots"],
            "agent_in_blind_spots": "agent" in registry_status["blind_spots"],
            "total_agent_assertions": len(agent_assertions),
            "valid_agent_assertions": valid_agent_assertions,
            "system_mode": auditor.get_system_state()["mode"],
            "primary_reason": auditor.get_system_state().get("blind_reason", "none"),
            "timestamp": current_time
        }
        
    except Exception as e:
        logger.error(f"Error getting agent blind spots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demo-data")
async def load_demo_agent_data():
    """Load demo agent data to reduce blind spots."""
    try:
        source = get_agent_assertion_source()
        current_time = time.time()
        
        # Demo agent data for production threshold (5+ assertions)
        demo_data = [
            {"agent_name": "governance_agent", "status": "ACTIVE", "health_score": 0.95, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "risk_agent", "status": "ACTIVE", "health_score": 0.92, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "execution_agent", "status": "ACTIVE", "health_score": 0.88, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "strategy_agent", "status": "ACTIVE", "health_score": 0.91, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "analysis_agent", "status": "ACTIVE", "health_score": 0.87, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "monitoring_agent", "status": "ACTIVE", "health_score": 0.93, "last_heartbeat": current_time, "source": "demo"},
            {"agent_name": "coordination_agent", "status": "ACTIVE", "health_score": 0.89, "last_heartbeat": current_time, "source": "demo"}
        ]
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Register demo data
        source.register_batch_agent_data(demo_data)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return AgentAssertionResponse(
            status="success",
            message=f"Loaded {len(demo_data)} demo agent assertions",
            assertions_registered=len(demo_data),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error loading demo agent data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
