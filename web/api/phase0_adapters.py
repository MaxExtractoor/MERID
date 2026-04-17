"""
MERID Phase 0 Thin Adapters

FastAPI adapters that follow the thin adapter pattern:
- No business logic in adapters
- Validate input and delegate to services
- Map domain objects to JSON DTOs
- Honor feature flags
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import json

from core.phase0_config import Phase0Config, get_phase0_config
from core.merid_minimal_scope import get_minimal_live_scope, GovernanceScorecard
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("phase0_adapters")

# Pydantic models for API contracts
class HumanReviewInput(BaseModel):
    model_id: str
    action: str = Field(..., description="Human decision: promote, demote, hold, suspend, retire")
    notes: str = Field(..., description="Reason for decision")
    reviewer: str = Field(..., description="Person making the decision")

class ScorecardDTO(BaseModel):
    """Data Transfer Object for governance scorecard."""
    model_id: str
    timestamp: str
    metrics: Dict[str, Any]
    governance: Dict[str, Any]
    safety: Dict[str, Any]
    human_review: Dict[str, Any]

class ContractTestResultDTO(BaseModel):
    """Data Transfer Object for contract test results."""
    model_id: str
    timestamp: str
    tests: Dict[str, bool]
    all_passed: bool
    failed_tests: List[str]

# Dependency injection functions
def get_phase0_enabled():
    """Check if Phase 0 is enabled via feature flags."""
    config = get_phase0_config()
    if not config.is_phase0_active():
        raise HTTPException(status_code=404, detail="Phase 0 is not enabled")
    return config

def get_governance_service():
    """Get the governance service (minimal scope implementation)."""
    return get_minimal_live_scope()

# FastAPI router with feature flag guard
def create_phase0_router() -> Optional[APIRouter]:
    """Create Phase 0 router if feature flags are enabled."""
    config = get_phase0_config()
    
    if not config.minimal_scope_enabled:
        logger.info("Phase 0 minimal scope feature flag is disabled - not mounting router")
        return None
    
    router = APIRouter(prefix="/api/v1/minimal", tags=["phase0_minimal"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
    
    @router.get("/scope")
    async def get_minimal_scope_info(config: Phase0Config = Depends(get_phase0_enabled)):
        """Get minimal scope configuration."""
        try:
            scope = get_governance_service()
            
            return {
                "success": True,
                "scope": {
                    "focused_models": scope.config.FOCUSED_MODELS,
                    "calibration_archetypes": {
                        model_id: archetype.value 
                        for model_id, archetype in scope.config.CALIBRATION_ARCHETYPES.items()
                    },
                    "governance_template": scope.config.GOVERNANCE_TEMPLATE,
                    "risk_limits": {
                        tier.value: limits 
                        for tier, limits in scope.config.RISK_LIMITS.items()
                    }
                },
                "feature_flags": {
                    "human_review_required": config.human_review_required,
                    "contract_enforced": config.contract_enforced,
                    "conservative_limits": config.conservative_limits,
                    "dry_run": config.dry_run
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get minimal scope info: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/scorecards")
    async def get_all_governance_scorecards(
        config: Phase0Config = Depends(get_phase0_enabled),
        service = Depends(get_governance_service)
    ):
        """Get governance scorecards for all models in minimal scope."""
        try:
            scorecards = service.get_all_scorecards()
            
            # Convert to DTOs
            dtos = [ScorecardDTO(
                model_id=sc.model_id,
                timestamp=sc.timestamp.isoformat(),
                metrics=sc.metrics,
                governance=sc.governance,
                safety=sc.safety,
                human_review=sc.human_review
            ) for sc in scorecards]
            
            return {
                "success": True,
                "scorecards": [dto.model_dump() for dto in dtos],
                "total_models": len(dtos)
            }
            
        except Exception as e:
            logger.error(f"Failed to get governance scorecards: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/scorecards/{model_id}")
    async def get_model_governance_scorecard(
        model_id: str,
        config: Phase0Config = Depends(get_phase0_enabled),
        service = Depends(get_governance_service)
    ):
        """Get governance scorecard for a specific model."""
        try:
            # Validate model is in scope
            if model_id not in service.config.FOCUSED_MODELS:
                raise HTTPException(status_code=404, detail=f"Model {model_id} not in minimal scope")
            
            scorecard = service.generate_governance_scorecard(model_id)
            
            # Convert to DTO
            dto = ScorecardDTO(
                model_id=scorecard.model_id,
                timestamp=scorecard.timestamp.isoformat(),
                metrics=scorecard.metrics,
                governance=scorecard.governance,
                safety=scorecard.safety,
                human_review=scorecard.human_review
            )
            
            return {
                "success": True,
                "scorecard": dto.model_dump()
            }
            
        except Exception as e:
            logger.error(f"Failed to get governance scorecard for {model_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/human-review")
    async def submit_human_review(
        payload: HumanReviewInput,
        config: Phase0Config = Depends(get_phase0_enabled),
        service = Depends(get_governance_service)
    ):
        """
        Submit human review for governance decision.
        
        Human-centered governance: system provides recommendations, humans make final decisions.
        """
        try:
            # Validate model is in scope
            if payload.model_id not in service.config.FOCUSED_MODELS:
                raise HTTPException(status_code=404, detail=f"Model {payload.model_id} not in minimal scope")
            
            # Check if human review is required
            if config.human_review_required:
                # Submit human review
                result = service.submit_human_review(
                    model_id=payload.model_id,
                    action=payload.action,
                    notes=payload.notes,
                    reviewer=payload.reviewer
                )
                
                logger.info(f"Human review submitted for {payload.model_id}: {payload.action} by {payload.reviewer}")
                
                return {
                    "success": result["success"],
                    "review": result.get("review"),
                    "message": result.get("message")
                }
            else:
                # Human review not required, but still log the decision
                logger.info(f"Human review not required for {payload.model_id}: {payload.action}")
                
                return {
                    "success": True,
                    "message": f"Human review not required for {payload.model_id}"
                }
            
        except Exception as e:
            logger.error(f"Failed to submit human review: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/human-reviews")
    async def get_human_review_summary(
        config: Phase0Config = Depends(get_phase0_enabled),
        service = Depends(get_governance_service)
    ):
        """Get summary of human review patterns and alignment."""
        try:
            summary = service.get_human_review_summary()
            
            return {
                "success": True,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"Failed to get human review summary: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/contract-tests")
    async def run_contract_tests(
        model_id: Optional[str] = Query(None),
        config: Phase0Config = Depends(get_phase0_enabled),
        service = Depends(get_governance_service)
    ):
        """Run contract tests for all models or specific model."""
        try:
            if model_id:
                # Validate model is in scope
                if model_id not in service.config.FOCUSED_MODELS:
                    raise HTTPException(status_code=404, detail=f"Model {model_id} not in minimal scope")
                
                # Run tests for specific model
                results = service.contract_tests.run_all_contract_tests(model_id)
                
                if "error" in results:
                    raise HTTPException(status_code=500, detail=results["error"])
                
                # Convert to DTO
                failed_tests = [test for test, passed in results.items() if not passed]
                dto = ContractTestResultDTO(
                    model_id=model_id,
                    timestamp=json.dumps({"timestamp": "now"}),  # Simplified
                    tests=results,
                    all_passed=all(results.values()),
                    failed_tests=failed_tests
                )
                
                return {
                    "success": True,
                    "result": dto.model_dump()
                }
            else:
                # Run tests for all models
                results = service.run_contract_tests_all_models()
                
                # Convert to list of DTOs
                dtos = []
                for model_id, test_results in results.items():
                    if "error" not in test_results:
                        failed_tests = [test for test, passed in test_results.items() if not passed]
                        dto = ContractTestResultDTO(
                            model_id=model_id,
                            timestamp=json.dumps({"timestamp": "now"}),
                            tests=test_results,
                            all_passed=all(test_results.values()),
                            failed_tests=failed_tests
                        )
                        dtos.append(dto)
                
                return {
                    "success": True,
                    "results": [dto.model_dump() for dto in dtos],
                    "summary": {
                        "total_models": len(dtos),
                        "all_passed": all(dto.all_passed for dto in dtos),
                        "total_failed_tests": sum(len(dto.failed_tests) for dto in dtos)
                    }
                }
            
        except Exception as e:
            logger.error(f"Failed to run contract tests: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/health")
    async def minimal_scope_health(config: Phase0Config = Depends(get_phase0_enabled)):
        """Health check for minimal scope deployment."""
        try:
            service = get_governance_service()
            
            # Basic health checks
            scorecards = service.get_all_scorecards()
            contract_results = service.run_contract_tests_all_models()
            
            # Determine health status
            total_models = len(scorecards)
            failed_contract_tests = sum(
                1 for results in contract_results.values()
                if "error" not in results and not all(results.values())
            )
            
            if failed_contract_tests > 0:
                health_status = "DEGRADED"
                health_message = f"{failed_contract_tests} models failing contract tests"
            elif total_models == 0:
                health_status = "WARNING"
                health_message = "No models in scope"
            else:
                health_status = "HEALTHY"
                health_message = f"All {total_models} models operating normally"
            
            return {
                "success": True,
                "health": {
                    "status": health_status,
                    "message": health_message,
                    "models_in_scope": total_models,
                    "contract_test_failures": failed_contract_tests,
                    "timestamp": json.dumps({"timestamp": "now"})  # Simplified
                },
                "config": {
                    "phase0_enabled": config.enabled,
                    "human_review_required": config.human_review_required,
                    "contract_enforced": config.contract_enforced,
                    "dry_run": config.dry_run
                }
            }
            
        except Exception as e:
            logger.error(f"Minimal scope health check failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    return router

# Create the router (will be None if feature flags are disabled)
phase0_router = create_phase0_router()
