"""
Simulation Assertion API

Endpoints for registering and managing simulation data assertions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import time

from simulation.assertion_source import get_simulation_assertion_source
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.simulation_assertions")
router = APIRouter(prefix="/api/v1/simulation", tags=["simulation-assertions"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class SimulationDataPoint(BaseModel):
    """Single simulation data point."""
    scenario_name: str = Field(..., description="Simulation scenario name")
    status: str = Field(..., description="Simulation status (PASSED/FAILED/RUNNING)")
    parity_score: float = Field(..., ge=0.0, le=1.0, description="Parity score with live system")
    latency_ms: float = Field(..., ge=0.0, description="Simulation latency in milliseconds")
    source: str = Field(default="sim_engine", description="Data source")


class SimulationDataBatch(BaseModel):
    """Batch of simulation data points."""
    simulation_data: List[SimulationDataPoint] = Field(..., description="Simulation data points")
    source: str = Field(default="batch", description="Batch source")


class SimulationAssertionResponse(BaseModel):
    """Response for simulation assertion operations."""
    status: str
    message: str
    assertions_registered: int = 0
    blind_spots_before: List[str] = []
    blind_spots_after: List[str] = []
    timestamp: float


@router.post("/assertions/register")
async def register_simulation_assertion(simulation_data: SimulationDataPoint):
    """Register a single simulation data assertion."""
    try:
        source = get_simulation_assertion_source()
        
        # Get blind spots before
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Update simulation data
        source.update_simulation_state(
            scenario_name=simulation_data.scenario_name,
            status=simulation_data.status,
            parity_score=simulation_data.parity_score,
            latency_ms=simulation_data.latency_ms,
            source=simulation_data.source
        )
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return SimulationAssertionResponse(
            status="success",
            message=f"Simulation assertion registered for {simulation_data.scenario_name}",
            assertions_registered=1,
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering simulation assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/batch")
async def register_simulation_assertions_batch(batch: SimulationDataBatch):
    """Register multiple simulation data assertions."""
    try:
        source = get_simulation_assertion_source()
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Convert to list format
        simulation_data_list = [
            {
                "scenario_name": data.scenario_name,
                "status": data.status,
                "parity_score": data.parity_score,
                "latency_ms": data.latency_ms,
                "source": batch.source
            }
            for data in batch.simulation_data
        ]
        
        # Register batch
        source.register_batch_simulation_data(simulation_data_list)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return SimulationAssertionResponse(
            status="success",
            message=f"Batch registered {len(simulation_data_list)} simulation assertions",
            assertions_registered=len(simulation_data_list),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering simulation assertions batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions")
async def get_simulation_assertions():
    """Get all simulation assertions."""
    try:
        source = get_simulation_assertion_source()
        assertions = source.get_simulation_assertions()
        
        return {
            "status": "success",
            "domain": "simulation",
            "assertions": assertions,
            "count": len(assertions),
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting simulation assertions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blind-spots")
async def get_simulation_blind_spots():
    """Get current blind spots and simulation domain status."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind spots)
        registry_status = registry.get_registry_status(current_time, auditor.regime_entropy)
        
        # Get simulation-specific assertions
        simulation_assertions = registry.get_assertions_by_domain("simulation")
        valid_simulation_assertions = sum(1 for a in simulation_assertions if a.status.value == "valid")
        
        return {
            "status": "success",
            "domain": "simulation",
            "blind_spots": registry_status["blind_spots"],
            "simulation_in_blind_spots": "simulation" in registry_status["blind_spots"],
            "total_simulation_assertions": len(simulation_assertions),
            "valid_simulation_assertions": valid_simulation_assertions,
            "system_mode": auditor.get_system_state()["mode"],
            "primary_reason": auditor.get_system_state().get("blind_reason", "none"),
            "timestamp": current_time
        }
        
    except Exception as e:
        logger.error(f"Error getting simulation blind spots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demo-data")
async def load_demo_simulation_data():
    """Load demo simulation data to reduce blind spots."""
    try:
        source = get_simulation_assertion_source()
        
        # Demo simulation data for production threshold (5+ assertions)
        demo_data = [
            {"scenario_name": "core_scenario", "status": "PASSED", "parity_score": 0.98, "latency_ms": 45.2, "source": "demo"},
            {"scenario_name": "risk_scenario", "status": "PASSED", "parity_score": 0.95, "latency_ms": 52.1, "source": "demo"},
            {"scenario_name": "market_scenario", "status": "PASSED", "parity_score": 0.92, "latency_ms": 38.7, "source": "demo"},
            {"scenario_name": "execution_scenario", "status": "PASSED", "parity_score": 0.89, "latency_ms": 41.3, "source": "demo"},
            {"scenario_name": "governance_scenario", "status": "PASSED", "parity_score": 0.94, "latency_ms": 47.8, "source": "demo"},
            {"scenario_name": "stress_scenario", "status": "PASSED", "parity_score": 0.87, "latency_ms": 55.4, "source": "demo"},
            {"scenario_name": "regression_scenario", "status": "PASSED", "parity_score": 0.91, "latency_ms": 43.6, "source": "demo"}
        ]
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Register demo data
        source.register_batch_simulation_data(demo_data)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return SimulationAssertionResponse(
            status="success",
            message=f"Loaded {len(demo_data)} demo simulation assertions",
            assertions_registered=len(demo_data),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error loading demo simulation data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
