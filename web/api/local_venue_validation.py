"""
Local Venue Validation Status API

API endpoint to provide validation status and phase progress for the local venue system.
"""

from __future__ import annotations

import time
import json
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/localvenue", tags=["local-venue-validation"])


class PhaseStatus(BaseModel):
    """Status of a validation phase."""
    phase_name: str = Field(..., description="Phase name (Phase 0, 1, 2, 3)")
    status: str = Field(..., description="Overall status: PASS, FAIL, IN_PROGRESS")
    completion_percentage: float = Field(..., ge=0, le=100, description="Phase completion percentage")
    test_results: Dict[str, Any] = Field(default_factory=dict, description="Test result summary")
    last_run_timestamp: float = Field(default_factory=time.time, description="Last run timestamp")
    blockers: List[str] = Field(default_factory=list, description="Current blockers")
    recommendations: List[str] = Field(default_factory=list, description="Recommendations for improvement")


class ValidationStatus(BaseModel):
    """Overall validation status for local venue."""
    overall_status: str = Field(..., description="Overall status: HEALTHY, DEGRADED, FAILING")
    current_phase: str = Field(..., description="Current active phase")
    phases: List[PhaseStatus] = Field(default_factory=list, description="All phase statuses")
    coverage_metrics: Dict[str, float] = Field(default_factory=dict, description="Coverage percentages")
    performance_metrics: Dict[str, float] = Field(default_factory=dict, description="Performance metrics")
    last_swarm_run: Dict[str, Any] = Field(default_factory=dict, description="Last swarm run details")
    system_health: Dict[str, Any] = Field(default_factory=dict, description="System health indicators")


class ValidationResult(BaseModel):
    """Validation result from test run."""
    success: bool = Field(..., description="Whether validation passed")
    phase: str = Field(..., description="Phase being validated")
    test_type: str = Field(..., description="Type of test run")
    results: Dict[str, Any] = Field(default_factory=dict, description="Detailed results")
    timestamp: float = Field(default_factory=time.time, description="Validation timestamp")


# In-memory storage for validation status (in production, use persistent storage)
_validation_status: ValidationStatus = None
_known_good_snapshot: Dict[str, Any] = {
    "git_ref": "main",
    "test_run_id": None,
    "timestamp": time.time(),
    "status": "unknown"
}


def get_validation_status() -> ValidationStatus:
    """Get current validation status."""
    global _validation_status
    if _validation_status is None:
        _validation_status = ValidationStatus(
            overall_status="UNKNOWN",
            current_phase="Phase 0",
            phases=[
                PhaseStatus(
                    phase_name="Phase 0",
                    status="IN_PROGRESS",
                    completion_percentage=25.0,
                    test_results={"total_tests": 0, "passed": 0, "failed": 0},
                    blockers=["Test suite setup in progress"],
                    recommendations=["Complete basic unit tests"]
                ),
                PhaseStatus(
                    phase_name="Phase 1",
                    status="NOT_STARTED",
                    completion_percentage=0.0,
                    test_results={"total_tests": 0, "passed": 0, "failed": 0},
                    blockers=["Phase 0 not completed"],
                    recommendations=["Wait for Phase 0 completion"]
                ),
                PhaseStatus(
                    phase_name="Phase 2",
                    status="NOT_STARTED",
                    completion_percentage=0.0,
                    test_results={"total_tests": 0, "passed": 0, "failed": 0},
                    blockers=["Phase 1 not completed"],
                    recommendations=["Wait for Phase 1 completion"]
                ),
                PhaseStatus(
                    phase_name="Phase 3",
                    status="NOT_STARTED",
                    completion_percentage=0.0,
                    test_results={"total_tests": 0, "passed": 0, "failed": 0},
                    blockers=["Phase 2 not completed"],
                    recommendations=["Wait for Phase 2 completion"]
                )
            ],
            coverage_metrics={
                "feed_handlers": 0.0,
                "matching_engine": 0.0,
                "ui_components": 0.0,
                "integration_points": 0.0
            },
            performance_metrics={
                "order_submission_ms": 0.0,
                "order_book_updates_ms": 0.0,
                "ui_api_response_ms": 0.0,
                "websocket_updates_ms": 0.0
            },
            last_swarm_run={
                "run_id": None,
                "timestamp": time.time(),
                "status": "not_run",
                "duration_seconds": 0.0
            },
            system_health={
                "engine_running": False,
                "websocket_connected": False,
                "feed_handlers_healthy": 0,
                "total_handlers": 0
            }
        )
    return _validation_status


def calculate_phase_status(phase_name: str, test_results: Dict[str, Any]) -> PhaseStatus:
    """Calculate phase status based on test results."""
    total_tests = test_results.get("total_tests", 0)
    passed_tests = test_results.get("passed", 0)
    failed_tests = test_results.get("failed", 0)
    
    if total_tests == 0:
        status = "NOT_STARTED"
        completion = 0.0
    elif failed_tests == 0:
        status = "PASS"
        completion = 100.0
    elif passed_tests > 0:
        status = "FAIL"
        completion = (passed_tests / total_tests) * 100
    else:
        status = "FAIL"
        completion = 0.0
    
    # Determine blockers and recommendations
    blockers = []
    recommendations = []
    
    if failed_tests > 0:
        blockers.append(f"{failed_tests} tests failing")
        recommendations.append("Fix failing tests before proceeding")
    
    if completion < 100.0:
        recommendations.append(f"Complete remaining {100 - completion:.1f}% of phase")
    
    return PhaseStatus(
        phase_name=phase_name,
        status=status,
        completion_percentage=completion,
        test_results=test_results,
        blockers=blockers,
        recommendations=recommendations
    )


@router.get("/validation-status", response_model=ValidationStatus)
async def get_validation_status_endpoint():
    """Get current validation status for local venue."""
    try:
        status = get_validation_status()
        
        # Update system health indicators
        from execution.simulator import get_execution_simulator
        from data.feed_handlers import get_feed_handler_manager
        
        try:
            simulator = get_execution_simulator()
            status.system_health["engine_running"] = simulator._running if hasattr(simulator, '_running') else False
        except Exception:
            status.system_health["engine_running"] = False
        
        try:
            feed_manager = get_feed_handler_manager()
            handlers = feed_manager.list_handlers()
            status.system_health["total_handlers"] = len(handlers)
            status.system_health["feed_handlers_healthy"] = len([h for h in handlers if h.get("status") == "running"])
        except Exception:
            status.system_health["total_handlers"] = 0
            status.system_health["feed_handlers_healthy"] = 0
        
        # Calculate overall status
        if status.system_health["engine_running"] and status.system_health["feed_handlers_healthy"] > 0:
            status.overall_status = "HEALTHY"
        elif status.system_health["engine_running"] or status.system_health["feed_handlers_healthy"] > 0:
            status.overall_status = "DEGRADED"
        else:
            status.overall_status = "FAILING"
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting validation status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validation-result", response_model=ValidationResult)
async def submit_validation_result(result: ValidationResult):
    """Submit validation result from test run."""
    try:
        global _validation_status, _known_good_snapshot
        
        # Update validation status
        status = get_validation_status()
        
        # Find and update the relevant phase
        phase_index = None
        for i, phase in enumerate(status.phases):
            if phase.phase_name == result.phase:
                phase_index = i
                break
        
        if phase_index is not None:
            # Update phase status
            new_phase_status = calculate_phase_status(result.phase, result.results)
            status.phases[phase_index] = new_phase_status
            
            # Update current phase if this is the latest
            if phase_index >= len(status.phases) - 1:
                status.current_phase = result.phase
        else:
            logger.warning(f"Unknown phase: {result.phase}")
        
        # Update coverage and performance metrics
        if "coverage" in result.results:
            status.coverage_metrics.update(result.results["coverage"])
        
        if "performance" in result.results:
            status.performance_metrics.update(result.results["performance"])
        
        # Update swarm run info
        status.last_swarm_run.update({
            "run_id": result.results.get("run_id"),
            "timestamp": result.timestamp,
            "status": "PASS" if result.success else "FAIL",
            "duration_seconds": result.results.get("duration_seconds", 0.0)
        })
        
        # Update known good snapshot if this is a successful run
        if result.success:
            _known_good_snapshot.update({
                "git_ref": result.results.get("git_ref", "unknown"),
                "test_run_id": result.results.get("run_id"),
                "timestamp": result.timestamp,
                "status": "good"
            })
        
        # Recalculate overall status
        all_phases_pass = all(phase.status == "PASS" for phase in status.phases)
        if all_phases_pass:
            status.overall_status = "HEALTHY"
        elif any(phase.status == "FAIL" for phase in status.phases):
            status.overall_status = "FAILING"
        else:
            status.overall_status = "DEGRADED"
        
        _validation_status = status
        
        return result
        
    except Exception as e:
        logger.error(f"Error submitting validation result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/known-good-snapshot")
async def get_known_good_snapshot():
    """Get the known good snapshot for rollback reference."""
    try:
        global _known_good_snapshot
        return _known_good_snapshot
    except Exception as e:
        logger.error(f"Error getting known good snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback-to-snapshot")
async def rollback_to_snapshot(snapshot_ref: str):
    """Rollback to a known good snapshot."""
    try:
        global _known_good_snapshot
        
        if _known_good_snapshot["status"] != "good":
            raise HTTPException(status_code=400, detail="No good snapshot available for rollback")
        
        # In a real implementation, this would trigger actual rollback logic
        logger.info(f"Rollback requested to snapshot: {snapshot_ref}")
        
        return {
            "success": True,
            "message": f"Rollback to snapshot {snapshot_ref} initiated",
            "snapshot": _known_good_snapshot
        }
        
    except Exception as e:
        logger.error(f"Error during rollback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/phase-progress")
async def get_phase_progress():
    """Get detailed progress for all phases."""
    try:
        status = get_validation_status()
        
        progress_data = {}
        for phase in status.phases:
            progress_data[phase.phase_name] = {
                "status": phase.status,
                "completion": phase.completion_percentage,
                "test_results": phase.test_results,
                "blockers": phase.blockers,
                "recommendations": phase.recommendations,
                "last_run": phase.last_run_timestamp
            }
        
        return progress_data
        
    except Exception as e:
        logger.error(f"Error getting phase progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions for swarm integration
def update_validation_from_test_results(test_results: Dict[str, Any], phase: str = "Phase 0"):
    """Update validation status from pytest results."""
    try:
        global _validation_status
        
        # Extract test metrics
        total_tests = len(test_results.get("tests", {}))
        passed_tests = len([t for t in test_results.get("tests", {}).values() if t.get("outcome") == "passed"])
        failed_tests = len([t for t in test_results.get("tests", {}).values() if t.get("outcome") == "failed"])
        
        # Extract coverage
        coverage = test_results.get("coverage", {})
        
        # Extract performance
        performance = test_results.get("performance", {})
        
        # Create validation result
        result = ValidationResult(
            success=failed_tests == 0,
            phase=phase,
            test_type="pytest",
            results={
                "total_tests": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "coverage": coverage,
                "performance": performance,
                "duration_seconds": test_results.get("duration", 0.0),
                "run_id": test_results.get("run_id")
            }
        )
        
        # Submit the result
        import asyncio
        asyncio.create_task(submit_validation_result(result))
        
        logger.info(f"Updated validation status for {phase}: {passed_tests}/{total_tests} tests passed")
        
    except Exception as e:
        logger.error(f"Error updating validation from test results: {e}")


def get_validation_summary() -> Dict[str, Any]:
    """Get a summary of validation status for dashboard display."""
    try:
        status = get_validation_status()
        
        return {
            "overall_status": status.overall_status,
            "current_phase": status.current_phase,
            "total_phases": len(status.phases),
            "completed_phases": len([p for p in status.phases if p.status == "PASS"]),
            "failed_phases": len([p for p in status.phases if p.status == "FAIL"]),
            "average_coverage": sum(status.coverage_metrics.values()) / len(status.coverage_metrics) if status.coverage_metrics else 0.0,
            "last_swarm_run": status.last_swarm_run,
            "system_health": status.system_health
        }
        
    except Exception as e:
        logger.error(f"Error getting validation summary: {e}")
        return {
            "overall_status": "ERROR",
            "current_phase": "Unknown",
            "total_phases": 0,
            "completed_phases": 0,
            "failed_phases": 0,
            "average_coverage": 0.0,
            "last_swarm_run": {},
            "system_health": {}
        }
