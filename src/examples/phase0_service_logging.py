"""
MERID Phase 0 Service Layer with Structured Logging
Example of how to integrate structured logging into the service layer
"""

import structlog
from typing import Dict, Any, Optional
from utils.sql_structlog import (
    log_decision_persistence_attempt,
    log_decision_persistence_success,
    log_decision_persistence_failure
)

logger = structlog.get_logger("phase0_service")


class Phase0DecisionService:
    """Phase 0 decision service with structured logging"""
    
    def __init__(self, repository, metrics_service):
        self.repository = repository
        self.metrics_service = metrics_service
    
    async def record_weekly_decision(self, decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record weekly decision with comprehensive structured logging"""
        
        model_id = decision_data.get("model_id")
        human_decision = decision_data.get("human_decision")
        decision_reason = decision_data.get("decision_reason")
        
        logger.info("record_decision_started",
                   model_id=model_id,
                   human_decision=human_decision,
                   decision_reason=decision_reason)
        
        try:
            # Validate basic decision payload
            validation_result = self._validate_decision_payload(decision_data)
            if not validation_result["valid"]:
                error_msg = validation_result["error"]
                log_decision_persistence_failure(model_id, error_msg, "ValidationError")
                logger.error("decision_validation_failed",
                            model_id=model_id,
                            error=error_msg,
                            validation_errors=validation_result.get("errors"))
                return {"status": "error", "message": error_msg}
            
            # Check for performance data (this is the current blocker)
            performance_data = await self._get_performance_data(model_id)
            has_performance_data = performance_data is not None
            
            # Log persistence attempt
            log_decision_persistence_attempt(
                model_id=model_id,
                has_performance_data=has_performance_data,
                decision_data=decision_data
            )
            
            # CURRENT ISSUE: This check blocks decisions without performance data
            if not has_performance_data:
                error_msg = f"No performance data available for {model_id}"
                log_decision_persistence_failure(model_id, error_msg, "MissingPerformanceData")
                logger.error("performance_data_missing",
                            model_id=model_id,
                            error=error_msg)
                return {"status": "error", "message": error_msg}
            
            # FIXED VERSION: Always persist decision regardless of performance data
            # metrics_state = "AVAILABLE" if has_performance_data else "MISSING"
            # decision_record = await self._persist_decision(decision_data, metrics_state)
            
            # For now, simulate the current behavior (failure)
            logger.error("decision_recording_blocked_by_performance_requirement",
                        model_id=model_id,
                        has_performance_data=has_performance_data,
                        fix_required="Remove performance data requirement")
            
            return {"status": "error", "message": f"No performance data available for {model_id}"}
            
        except Exception as e:
            error_msg = f"Unexpected error recording decision: {str(e)}"
            log_decision_persistence_failure(model_id, error_msg, type(e).__name__)
            logger.error("decision_recording_exception",
                        model_id=model_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return {"status": "error", "message": error_msg}
    
    async def _validate_decision_payload(self, decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate decision payload"""
        required_fields = ["model_id", "human_decision", "decision_reason"]
        missing_fields = [field for field in required_fields if field not in decision_data]
        
        if missing_fields:
            return {
                "valid": False,
                "error": f"Missing required fields: {', '.join(missing_fields)}",
                "errors": missing_fields
            }
        
        valid_decisions = ["hold", "buy", "sell"]
        if decision_data["human_decision"] not in valid_decisions:
            return {
                "valid": False,
                "error": f"Invalid decision: {decision_data['human_decision']}. Valid options: {valid_decisions}",
                "errors": ["invalid_human_decision"]
            }
        
        return {"valid": True}
    
    async def _get_performance_data(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get performance data for model"""
        try:
            # This would normally query your performance metrics
            return await self.metrics_service.get_model_performance(model_id)
        except Exception as e:
            logger.warning("performance_data_fetch_failed",
                          model_id=model_id,
                          error=str(e))
            return None
    
    async def _persist_decision(self, decision_data: Dict[str, Any], metrics_state: str) -> Dict[str, Any]:
        """Persist decision to database (fixed version)"""
        try:
            # Add metrics state to decision
            decision_record = decision_data.copy()
            decision_record["metrics_state"] = metrics_state
            decision_record["timestamp"] = structlog.processors.TimeStamper().format_timestamp(None)
            
            # Persist to database
            result = await self.repository.insert_decision(decision_record)
            
            # Log success
            log_decision_persistence_success(
                model_id=decision_data["model_id"],
                decision_id=result.get("id"),
                metrics_state=metrics_state
            )
            
            logger.info("decision_persisted_successfully",
                       model_id=decision_data["model_id"],
                       decision_id=result.get("id"),
                       metrics_state=metrics_state)
            
            return result
            
        except Exception as e:
            error_msg = f"Failed to persist decision: {str(e)}"
            log_decision_persistence_failure(decision_data["model_id"], error_msg, "PersistenceError")
            logger.error("decision_persistence_failed",
                        model_id=decision_data["model_id"],
                        error=str(e),
                        error_type=type(e).__name__)
            raise


# Example of how the fixed service would work
class FixedPhase0DecisionService(Phase0DecisionService):
    """Fixed version that doesn't require performance data"""
    
    async def record_weekly_decision(self, decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record weekly decision without requiring performance data"""
        
        model_id = decision_data.get("model_id")
        human_decision = decision_data.get("human_decision")
        decision_reason = decision_data.get("decision_reason")
        
        logger.info("record_decision_started_fixed",
                   model_id=model_id,
                   human_decision=human_decision,
                   decision_reason=decision_reason)
        
        try:
            # Validate basic decision payload
            validation_result = self._validate_decision_payload(decision_data)
            if not validation_result["valid"]:
                error_msg = validation_result["error"]
                log_decision_persistence_failure(model_id, error_msg, "ValidationError")
                return {"status": "error", "message": error_msg}
            
            # Check for performance data (optional, not blocking)
            performance_data = await self._get_performance_data(model_id)
            has_performance_data = performance_data is not None
            
            # Log persistence attempt
            log_decision_persistence_attempt(
                model_id=model_id,
                has_performance_data=has_performance_data,
                decision_data=decision_data
            )
            
            # FIXED: Always persist decision regardless of performance data
            metrics_state = "AVAILABLE" if has_performance_data else "MISSING"
            decision_record = await self._persist_decision(decision_data, metrics_state)
            
            logger.info("decision_recording_completed_successfully",
                       model_id=model_id,
                       decision_id=decision_record.get("id"),
                       metrics_state=metrics_state,
                       has_performance_data=has_performance_data)
            
            return {
                "status": "success",
                "decision_id": decision_record.get("id"),
                "metrics_state": metrics_state,
                "message": "Decision recorded successfully"
            }
            
        except Exception as e:
            error_msg = f"Unexpected error recording decision: {str(e)}"
            log_decision_persistence_failure(model_id, error_msg, type(e).__name__)
            logger.error("decision_recording_exception",
                        model_id=model_id,
                        error=str(e),
                        error_type=type(e).__name__)
            return {"status": "error", "message": error_msg}
