"""
Domain Priority API

Endpoints for managing and monitoring domain input priorities in SIGHTED_DEGRADED mode.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import time

from core.domain_priority_manager import get_domain_priority_manager
from utils.logger import get_logger

logger = get_logger("web.api.domain_priority")
router = APIRouter(prefix="/api/v1/domain-priority", tags=["domain-priority"])


class DomainAccessRequest(BaseModel):
    """Request to check domain access."""
    domain: str = Field(..., description="Domain name")
    operation: str = Field(..., description="Operation to perform")
    actor_id: Optional[str] = Field(None, description="Actor identifier")


class DomainAccessResponse(BaseModel):
    """Response for domain access requests."""
    allowed: bool
    reason: str
    timestamp: float


class PriorityViolation(BaseModel):
    """Priority violation record."""
    violation_id: str
    timestamp: float
    domain: str
    operation: str
    reason: str
    severity: str
    actor_id: Optional[str]


@router.get("/status")
async def get_domain_priority_status():
    """Get current domain priority status and configuration."""
    try:
        manager = get_domain_priority_manager()
        status = manager.get_domain_status()
        summary = manager.get_priority_summary()
        
        return {
            "status": "success",
            "current_mode": manager.current_mode,
            "domain_configurations": status,
            "priority_summary": summary,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting domain priority status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-access")
async def check_domain_access(request: DomainAccessRequest):
    """Check if a domain operation is allowed under current priority rules."""
    try:
        manager = get_domain_priority_manager()
        allowed, reason = manager.check_domain_access(
            domain=request.domain,
            operation=request.operation,
            actor_id=request.actor_id
        )
        
        return DomainAccessResponse(
            allowed=allowed,
            reason=reason,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error checking domain access: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/violations")
async def get_priority_violations(limit: int = Query(100, ge=1, le=1000)):
    """Get recent priority violations."""
    try:
        manager = get_domain_priority_manager()
        violations = manager.get_priority_violations(limit)
        
        return {
            "status": "success",
            "violations": violations,
            "total_count": len(violations),
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting priority violations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/violations")
async def clear_priority_violations():
    """Clear all priority violations (admin operation)."""
    try:
        manager = get_domain_priority_manager()
        manager.clear_violations()
        
        return {
            "status": "success",
            "message": "All priority violations cleared",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error clearing priority violations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hierarchy")
async def get_priority_hierarchy():
    """Get the current domain priority hierarchy."""
    try:
        manager = get_domain_priority_manager()
        summary = manager.get_priority_summary()
        
        if manager.current_mode != "SIGHTED_DEGRADED":
            return {
                "status": "info",
                "message": f"Priority hierarchy not active in {manager.current_mode} mode",
                "current_mode": manager.current_mode
            }
        
        return {
            "status": "success",
            "mode": manager.current_mode,
            "priority_hierarchy": summary["priority_hierarchy"],
            "accessible_domains": summary["accessible_domains"],
            "blocked_domains": summary["blocked_domains"],
            "enforcement_rules": {
                "highest_priority": ["market", "onchain"],
                "high_priority": ["simulation"],
                "medium_priority": ["agent"],
                "blocked_domains": ["execution", "governance", "treasury", "system"]
            },
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting priority hierarchy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-access")
async def test_domain_access():
    """Test domain access rules for all domains and operations."""
    try:
        manager = get_domain_priority_manager()
        
        test_operations = ["read", "write", "execute", "propose", "monitor"]
        test_results = {}
        
        for domain in manager.domain_configs.keys():
            domain_results = {}
            for operation in test_operations:
                allowed, reason = manager.check_domain_access(domain, operation, "test_actor")
                domain_results[operation] = {
                    "allowed": allowed,
                    "reason": reason
                }
            test_results[domain] = domain_results
        
        return {
            "status": "success",
            "test_results": test_results,
            "mode": manager.current_mode,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error testing domain access: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/safety-checks")
async def run_safety_checks():
    """Run comprehensive safety checks for SIGHTED_DEGRADED mode."""
    try:
        manager = get_domain_priority_manager()
        
        if manager.current_mode != "SIGHTED_DEGRADED":
            return {
                "status": "info",
                "message": f"Safety checks not applicable in {manager.current_mode} mode",
                "current_mode": manager.current_mode
            }
        
        results = manager._run_safety_checks()
        
        return {
            "status": "success",
            "safety_check_results": results,
            "overall_status": "passed" if all(results.values()) else "failed",
            "last_check": manager.last_safety_check,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error running safety checks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query-rates")
async def get_query_rates():
    """Get current query rates for all domains."""
    try:
        manager = get_domain_priority_manager()
        
        query_rates = {}
        for domain in manager.domain_configs.keys():
            current_queries = len([
                q_time for q_time in manager.query_rates[domain]
                if time.time() - q_time < 60.0
            ])
            
            config = manager.domain_configs[domain]
            query_rates[domain] = {
                "current_queries_per_minute": current_queries,
                "max_queries_per_minute": config.max_queries_per_minute,
                "utilization_percent": (current_queries / config.max_queries_per_minute * 100) if config.max_queries_per_minute > 0 else 0,
                "status": "ok" if current_queries < config.max_queries_per_minute else "exceeded"
            }
        
        return {
            "status": "success",
            "query_rates": query_rates,
            "mode": manager.current_mode,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting query rates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulate-violation")
async def simulate_priority_violation(request: DomainAccessRequest):
    """Simulate a priority violation for testing purposes."""
    try:
        manager = get_domain_priority_manager()
        
        # Force a violation by trying to access a blocked domain
        if request.domain in ["execution", "governance", "treasury", "system"]:
            allowed, reason = manager.check_domain_access(
                domain=request.domain,
                operation="execute",  # This should be blocked
                actor_id="test_violation"
            )
            
            return {
                "status": "success",
                "violation_simulated": not allowed,
                "domain": request.domain,
                "operation": "execute",
                "allowed": allowed,
                "reason": reason,
                "timestamp": time.time()
            }
        else:
            return {
                "status": "error",
                "message": f"Domain {request.domain} is not blocked for violation testing",
                "timestamp": time.time()
            }
        
    except Exception as e:
        logger.error(f"Error simulating priority violation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compliance-report")
async def get_compliance_report():
    """Generate a compliance report for SIGHTED_DEGRADED mode."""
    try:
        manager = get_domain_priority_manager()
        
        if manager.current_mode != "SIGHTED_DEGRADED":
            return {
                "status": "info",
                "message": f"Compliance report not applicable in {manager.current_mode} mode",
                "current_mode": manager.current_mode
            }
        
        # Get comprehensive compliance data
        status = manager.get_domain_status()
        violations = manager.get_priority_violations(50)
        safety_checks = manager._run_safety_checks()
        query_rates = await get_query_rates()
        
        # Generate compliance summary
        total_violations = len(violations)
        critical_violations = len([v for v in violations if v["severity"] == "critical"])
        
        compliance_score = 100
        if critical_violations > 0:
            compliance_score -= 50
        if total_violations > 10:
            compliance_score -= 25
        if not all(safety_checks.values()):
            compliance_score -= 25
        
        return {
            "status": "success",
            "compliance_report": {
                "mode": manager.current_mode,
                "compliance_score": max(0, compliance_score),
                "compliance_status": "compliant" if compliance_score >= 90 else "non_compliant",
                "domain_status": status,
                "safety_checks": safety_checks,
                "violation_summary": {
                    "total_violations": total_violations,
                    "critical_violations": critical_violations,
                    "recent_violations": violations[:10]
                },
                "query_utilization": query_rates["query_rates"],
                "audit_trail": {
                    "last_safety_check": manager.last_safety_check,
                    "total_violations_recorded": len(manager.priority_violations)
                }
            },
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error generating compliance report: {e}")
        raise HTTPException(status_code=500, detail=str(e))
