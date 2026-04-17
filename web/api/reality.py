"""
MERID Reality API - Truth-Bound Endpoints

Exposes reality registry and auditor to UI and external systems.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import time

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
    AssertionStatus,
)
from core.reality_auditor import get_reality_auditor
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.reality")

router = APIRouter(prefix="/api/v1/reality", tags=["reality"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class RegisterAssertionRequest(BaseModel):
    domain: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance_score: float = Field(ge=0.0, le=1.0)
    regime_compatibility: float = Field(ge=0.0, le=1.0)
    decay_rate: float = Field(ge=0.0)
    validity_window: float = Field(gt=0.0)
    sources: List[Dict]


class MarkConflictRequest(BaseModel):
    assertion_id_a: str
    assertion_id_b: str


class AuditComponentRequest(BaseModel):
    component_id: str
    required_assertions: List[str]
    allow_conflict: bool = False
    allow_expired: bool = False
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AuditExecutionRequest(BaseModel):
    intent_id: str
    required_assertions: List[str]
    symbol: str
    amount_usd: float


@router.get("/status")
async def get_reality_status():
    """
    Get overall reality registry status.
    
    This is what the Reality Status Panel displays.
    """
    try:
        auditor = get_reality_auditor()
        registry = get_reality_registry()
        
        current_time = time.time()
        
        # Run audit loop
        is_blind, blind_reason = auditor.audit_loop()
        
        # Get system state
        system_state = auditor.get_system_state()
        
        # Get self-deception metrics
        deception_metrics = auditor.detect_self_deception()
        
        return {
            "status": "success",
            "system_state": system_state,
            "deception_metrics": deception_metrics,
            "timestamp": current_time,
        }
    except Exception as e:
        logger.error(f"Error getting reality status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/register")
async def register_assertion(request: RegisterAssertionRequest):
    """Register a new reality assertion."""
    try:
        registry = get_reality_registry()
        
        # Parse domain
        try:
            domain = AssertionDomain(request.domain.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid domain: {request.domain}")
        
        # Parse sources
        sources = []
        for src in request.sources:
            sources.append(AssertionProvenance(
                source_id=src.get("source_id", "unknown"),
                module_id=src.get("module_id", "unknown"),
                evidence_hash=src.get("evidence_hash", ""),
                weight=src.get("weight", 1.0),
                timestamp=src.get("timestamp", time.time()),
            ))
        
        # Register
        assertion_id = registry.register_assertion(
            domain=domain,
            description=request.description,
            confidence=request.confidence,
            provenance_score=request.provenance_score,
            regime_compatibility=request.regime_compatibility,
            decay_rate=request.decay_rate,
            validity_window=request.validity_window,
            sources=sources,
        )
        
        return {
            "status": "registered",
            "assertion_id": assertion_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions/{assertion_id}")
async def get_assertion(assertion_id: str):
    """Get assertion by ID."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        
        assertion = registry.get_assertion(assertion_id)
        if not assertion:
            raise HTTPException(status_code=404, detail="Assertion not found")
        
        current_time = time.time()
        effective = assertion.effective_confidence(current_time, auditor.regime_entropy)
        usable = assertion.is_usable(current_time, auditor.regime_entropy)
        
        data = assertion.to_dict()
        data["effective_confidence"] = effective
        data["is_usable"] = usable
        
        return {
            "status": "success",
            "assertion": data,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions/domain/{domain}")
async def get_assertions_by_domain(domain: str):
    """Get all assertions for a domain."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        
        try:
            domain_enum = AssertionDomain(domain.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid domain: {domain}")
        
        assertions = registry.get_assertions_by_domain(domain_enum)
        
        current_time = time.time()
        
        result = []
        for assertion in assertions:
            data = assertion.to_dict()
            data["effective_confidence"] = assertion.effective_confidence(current_time, auditor.regime_entropy)
            data["is_usable"] = assertion.is_usable(current_time, auditor.regime_entropy)
            result.append(data)
        
        return {
            "status": "success",
            "domain": domain,
            "assertions": result,
            "count": len(result),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assertions by domain: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/conflict")
async def mark_conflict(request: MarkConflictRequest):
    """Mark two assertions as conflicting."""
    try:
        registry = get_reality_registry()
        
        registry.mark_conflict(request.assertion_id_a, request.assertion_id_b)
        
        return {
            "status": "conflict_marked",
            "assertion_a": request.assertion_id_a,
            "assertion_b": request.assertion_id_b,
        }
    except Exception as e:
        logger.error(f"Error marking conflict: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audit/component")
async def audit_component(request: AuditComponentRequest):
    """
    Audit whether a UI component is allowed to render.
    
    CONSTITUTIONAL: This is the gate that prevents fake UI.
    """
    try:
        auditor = get_reality_auditor()
        
        result = auditor.audit_ui_component(
            component_id=request.component_id,
            required_assertions=request.required_assertions,
            allow_conflict=request.allow_conflict,
            allow_expired=request.allow_expired,
            min_confidence=request.min_confidence,
        )
        
        return {
            "status": "audited",
            "component_id": request.component_id,
            "passed": result.passed,
            "reason": result.reason,
            "blocking_assertions": result.blocking_assertions,
            "warnings": result.warnings,
        }
    except Exception as e:
        logger.error(f"Error auditing component: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audit/execution")
async def audit_execution(request: AuditExecutionRequest):
    """
    Audit whether execution is allowed.
    
    STRICTER than UI audit - no exceptions.
    """
    try:
        auditor = get_reality_auditor()
        
        result = auditor.audit_execution_intent(
            intent_id=request.intent_id,
            required_assertions=request.required_assertions,
            symbol=request.symbol,
            amount_usd=request.amount_usd,
        )
        
        return {
            "status": "audited",
            "intent_id": request.intent_id,
            "passed": result.passed,
            "reason": result.reason,
            "blocking_assertions": result.blocking_assertions,
            "warnings": result.warnings,
        }
    except Exception as e:
        logger.error(f"Error auditing execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateEntropyRequest(BaseModel):
    entropy: float = Field(ge=0.0, le=1.0)


@router.post("/regime/entropy")
async def update_regime_entropy(request: UpdateEntropyRequest):
    """Update current regime entropy."""
    entropy = request.entropy
    try:
        auditor = get_reality_auditor()
        auditor.update_regime_entropy(entropy)
        
        return {
            "status": "updated",
            "regime_entropy": entropy,
        }
    except Exception as e:
        logger.error(f"Error updating regime entropy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_reality_metrics():
    """
    Get comprehensive reality enforcement metrics.
    """
    try:
        auditor = get_reality_auditor()
        registry = get_reality_registry()
        current_time = time.time()
        
        # Get all assertions
        assertions = list(registry._assertions.values())
        
        # Calculate metrics by domain
        domain_metrics = {}
        for domain in AssertionDomain:
            domain_assertions = [a for a in assertions if a.domain == domain]
            valid = sum(1 for a in domain_assertions if a.status == AssertionStatus.VALID)
            total = len(domain_assertions)
            
            domain_metrics[domain.value] = {
                "total": total,
                "valid": valid,
                "valid_pct": (valid / total * 100) if total > 0 else 0,
                "avg_confidence": sum(a.effective_confidence(current_time, auditor.regime_entropy) 
                                     for a in domain_assertions) / total if total > 0 else 0
            }
        
        return {
            "status": "success",
            "timestamp": current_time,
            "domain_metrics": domain_metrics,
            "total_assertions": len(assertions),
            "regime_entropy": auditor.regime_entropy,
            "last_audit": auditor.last_audit
        }
    except Exception as e:
        logger.error(f"Error getting reality metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions/history")
async def get_assertion_history(limit: int = 100):
    """
    Get assertion registration history.
    """
    try:
        registry = get_reality_registry()
        assertions = list(registry._assertions.values())
        
        # Sort by registration time (most recent first)
        sorted_assertions = sorted(assertions, key=lambda a: a.registered_at, reverse=True)[:limit]
        
        history = []
        for assertion in sorted_assertions:
            history.append({
                "id": assertion.assertion_id,
                "domain": assertion.domain.value,
                "description": assertion.description,
                "status": assertion.status.value,
                "confidence": assertion.confidence_score,
                "registered_at": assertion.registered_at,
                "last_verified_at": assertion.last_verified_at
            })
        
        return {
            "status": "success",
            "count": len(history),
            "history": history
        }
    except Exception as e:
        logger.error(f"Error getting assertion history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/{assertion_id}/invalidate")
async def invalidate_assertion(assertion_id: str):
    """
    Manually invalidate an assertion.
    
    CONSTITUTIONAL: Assertions can only be invalidated, never deleted.
    """
    try:
        registry = get_reality_registry()
        
        if assertion_id not in registry._assertions:
            raise HTTPException(status_code=404, detail="Assertion not found")
        
        assertion = registry._assertions[assertion_id]
        assertion.status = AssertionStatus.INVALID
        
        logger.info(f"Assertion {assertion_id} manually invalidated")
        
        return {
            "status": "invalidated",
            "assertion_id": assertion_id,
            "timestamp": time.time()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error invalidating assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def reality_health_check():
    """
    Health check for Reality Enforcement System.
    """
    try:
        auditor = get_reality_auditor()
        registry = get_reality_registry()
        current_time = time.time()
        
        # Check if system is operational
        is_blind, blind_reason = registry.check_blindness_condition(current_time, auditor.regime_entropy)
        
        status = "healthy" if not is_blind else "degraded"
        
        return {
            "status": status,
            "is_blind": is_blind,
            "blind_reason": blind_reason,
            "total_assertions": len(registry._assertions),
            "regime_entropy": auditor.regime_entropy,
            "last_audit": auditor.last_audit,
            "timestamp": current_time
        }
    except Exception as e:
        logger.error(f"Error in reality health check: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@router.get("/blindness")
async def check_blindness():
    """
    Check if system should be in Blindness Mode.
    
    CONSTITUTIONAL: Blindness Mode is success, not failure.
    """
    try:
        auditor = get_reality_auditor()
        registry = get_reality_registry()
        
        current_time = time.time()
        is_blind, reason = registry.check_blindness_condition(current_time, auditor.regime_entropy)
        
        return {
            "status": "checked",
            "is_blind": is_blind,
            "reason": reason,
            "regime_entropy": auditor.regime_entropy,
        }
    except Exception as e:
        logger.error(f"Error checking blindness: {e}")
        raise HTTPException(status_code=500, detail=str(e))
