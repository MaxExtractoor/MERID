"""
Runtime Error Handling for Assertion Failures.

Defines classification and response model for assertion failures,
with recoverable vs non-recoverable handling strategies.
"""

import time
import traceback
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

from core.reality_registry import AssertionStatus, AssertionDomain
from core.mode_transition_auditor import log_rollback
from utils.logger import get_logger

logger = get_logger("core.assertion_error_handler")


class AssertionFailureType(Enum):
    """Classification of assertion failures."""
    RECOVERABLE = "recoverable"
    NON_RECOVERABLE = "non_recoverable"
    TRANSIENT = "transient"
    LOGIC_BUG = "logic_bug"
    DATA_ANOMALY = "data_anomaly"
    FEED_ISSUE = "feed_issue"


class AssertionFailureSeverity(Enum):
    """Severity levels for assertion failures."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AssertionFailure:
    """Structured assertion failure information."""
    assertion_id: str
    domain: AssertionDomain
    failure_type: AssertionFailureType
    severity: AssertionFailureSeverity
    error_message: str
    stack_trace: Optional[str]
    timestamp: float
    context: Dict[str, Any]
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[float] = None


class AssertionErrorHandler:
    """Handles assertion failures with appropriate recovery strategies."""
    
    def __init__(self):
        self.failure_history: List[AssertionFailure] = []
        self.recovery_strategies = {
            AssertionFailureType.RECOVERABLE: self._handle_recoverable_failure,
            AssertionFailureType.NON_RECOVERABLE: self._handle_non_recoverable_failure,
            AssertionFailureType.TRANSIENT: self._handle_transient_failure,
            AssertionFailureType.LOGIC_BUG: self._handle_logic_bug_failure,
            AssertionFailureType.DATA_ANOMALY: self._handle_data_anomaly_failure,
            AssertionFailureType.FEED_ISSUE: self._handle_feed_issue_failure
        }
        self.max_recovery_attempts = 3
        self.recovery_backoff_seconds = 30
    
    def classify_failure(self, assertion_id: str, domain: AssertionDomain, 
                        error: Exception, context: Dict[str, Any]) -> AssertionFailure:
        """Classify an assertion failure and determine its type and severity."""
        
        error_message = str(error)
        stack_trace = traceback.format_exc()
        
        # Classify failure type based on error characteristics
        failure_type = self._determine_failure_type(error, error_message, context)
        severity = self._determine_severity(failure_type, domain, error_message)
        
        failure = AssertionFailure(
            assertion_id=assertion_id,
            domain=domain,
            failure_type=failure_type,
            severity=severity,
            error_message=error_message,
            stack_trace=stack_trace,
            timestamp=time.time(),
            context=context
        )
        
        # Record failure
        self.failure_history.append(failure)
        
        logger.warning(f"Assertion failure classified: {failure_type.value} - {severity.value} - {error_message}")
        
        return failure
    
    def _determine_failure_type(self, error: Exception, error_message: str, 
                               context: Dict[str, Any]) -> AssertionFailureType:
        """Determine the type of assertion failure."""
        
        # Transient failures (network, timeout, temporary resource issues)
        if any(keyword in error_message.lower() for keyword in [
            "timeout", "connection", "network", "temporary", "rate limit"
        ]):
            return AssertionFailureType.TRANSIENT
        
        # Feed issues (data source problems)
        if any(keyword in error_message.lower() for keyword in [
            "feed", "source", "provider", "api", "websocket", "stream"
        ]):
            return AssertionFailureType.FEED_ISSUE
        
        # Data anomalies (invalid data, out of range values)
        if any(keyword in error_message.lower() for keyword in [
            "invalid", "out of range", "nan", "infinity", "null", "missing"
        ]):
            return AssertionFailureType.DATA_ANOMALY
        
        # Logic bugs (assertion failures, invariant violations)
        if any(keyword in error_message.lower() for keyword in [
            "assertion", "invariant", "logic", "algorithm", "calculation"
        ]):
            return AssertionFailureType.LOGIC_BUG
        
        # Default to non-recoverable for unknown errors
        return AssertionFailureType.NON_RECOVERABLE
    
    def _determine_severity(self, failure_type: AssertionFailureType, 
                          domain: AssertionDomain, error_message: str) -> AssertionFailureSeverity:
        """Determine the severity of assertion failure."""
        
        # Critical domains have higher severity
        if domain in [AssertionDomain.EXECUTION, AssertionDomain.GOVERNANCE, AssertionDomain.TREASURY]:
            return AssertionFailureSeverity.CRITICAL
        
        # Logic bugs are always high severity
        if failure_type == AssertionFailureType.LOGIC_BUG:
            return AssertionFailureSeverity.HIGH
        
        # Feed issues are medium severity for core domains
        if failure_type == AssertionFailureType.FEED_ISSUE:
            if domain in [AssertionDomain.MARKET, AssertionDomain.ONCHAIN]:
                return AssertionFailureSeverity.HIGH
            else:
                return AssertionFailureSeverity.MEDIUM
        
        # Data anomalies are medium severity
        if failure_type == AssertionFailureType.DATA_ANOMALY:
            return AssertionFailureSeverity.MEDIUM
        
        # Transient failures are low severity
        if failure_type == AssertionFailureType.TRANSIENT:
            return AssertionFailureSeverity.LOW
        
        # Default to medium severity
        return AssertionFailureSeverity.MEDIUM
    
    def handle_failure(self, failure: AssertionFailure) -> bool:
        """Handle an assertion failure using appropriate recovery strategy."""
        
        logger.info(f"Handling assertion failure: {failure.failure_type.value} for {failure.assertion_id}")
        
        # Check if we've exceeded recovery attempts
        if failure.recovery_attempts >= self.max_recovery_attempts:
            logger.error(f"Max recovery attempts exceeded for {failure.assertion_id}")
            return self._escalate_failure(failure)
        
        # Get appropriate recovery strategy
        strategy = self.recovery_strategies.get(failure.failure_type)
        if strategy is None:
            logger.error(f"No recovery strategy for failure type: {failure.failure_type}")
            return self._escalate_failure(failure)
        
        # Update recovery attempt count
        failure.recovery_attempts += 1
        failure.last_recovery_attempt = time.time()
        
        try:
            return strategy(failure)
        except Exception as e:
            logger.error(f"Recovery strategy failed: {e}")
            return self._escalate_failure(failure)
    
    def _handle_recoverable_failure(self, failure: AssertionFailure) -> bool:
        """Handle recoverable assertion failures."""
        
        logger.info(f"Attempting recovery for recoverable failure: {failure.assertion_id}")
        
        # Mark assertion as invalid but don't fail the whole system
        self._mark_assertion_invalid(failure.assertion_id)
        
        # Log structured event
        self._log_failure_event(failure, "recoverable_failure_handled")
        
        return True  # Recovery successful
    
    def _handle_non_recoverable_failure(self, failure: AssertionFailure) -> bool:
        """Handle non-recoverable assertion failures."""
        
        logger.error(f"Non-recoverable failure detected: {failure.assertion_id}")
        
        # Fail fast - trigger system rollback
        return self._trigger_system_rollback(failure, "non_recoverable_failure")
    
    def _handle_transient_failure(self, failure: AssertionFailure) -> bool:
        """Handle transient assertion failures."""
        
        logger.info(f"Handling transient failure: {failure.assertion_id}")
        
        # Implement exponential backoff
        backoff_time = self.recovery_backoff_seconds * (2 ** (failure.recovery_attempts - 1))
        
        if failure.last_recovery_attempt:
            time_since_last = time.time() - failure.last_recovery_attempt
            if time_since_last < backoff_time:
                logger.info(f"Waiting for backoff period: {backoff_time}s")
                return False
        
        # Retry the operation
        try:
            # Attempt to re-evaluate the assertion
            success = self._retry_assertion_evaluation(failure.assertion_id)
            
            if success:
                logger.info(f"Transient failure recovered: {failure.assertion_id}")
                self._log_failure_event(failure, "transient_failure_recovered")
                return True
            else:
                logger.warning(f"Transient failure retry failed: {failure.assertion_id}")
                return False
                
        except Exception as e:
            logger.error(f"Transient failure retry exception: {e}")
            return False
    
    def _handle_logic_bug_failure(self, failure: AssertionFailure) -> bool:
        """Handle logic bug assertion failures."""
        
        logger.error(f"Logic bug detected: {failure.assertion_id}")
        
        # Logic bugs are non-recoverable - trigger immediate rollback
        return self._trigger_system_rollback(failure, "logic_bug_detected")
    
    def _handle_data_anomaly_failure(self, failure: AssertionFailure) -> bool:
        """Handle data anomaly assertion failures."""
        
        logger.warning(f"Data anomaly detected: {failure.assertion_id}")
        
        # Mark assertion as invalid but allow system to continue
        self._mark_assertion_invalid(failure.assertion_id)
        
        # If too many anomalies in a domain, degrade the domain
        domain_anomalies = self._count_domain_anomalies(failure.domain)
        if domain_anomalies > 5:  # Threshold for domain degradation
            logger.warning(f"Too many anomalies in {failure.domain.value}, degrading domain")
            self._degrade_domain(failure.domain)
        
        self._log_failure_event(failure, "data_anomaly_handled")
        return True
    
    def _handle_feed_issue_failure(self, failure: AssertionFailure) -> bool:
        """Handle feed issue assertion failures."""
        
        logger.warning(f"Feed issue detected: {failure.assertion_id}")
        
        # Mark assertion as invalid
        self._mark_assertion_invalid(failure.assertion_id)
        
        # If core domain feed issues, trigger rollback
        if failure.domain in [AssertionDomain.MARKET, AssertionDomain.ONCHAIN]:
            logger.error(f"Core domain feed issue in {failure.domain.value}, triggering rollback")
            return self._trigger_system_rollback(failure, "core_domain_feed_issue")
        
        self._log_failure_event(failure, "feed_issue_handled")
        return True
    
    def _escalate_failure(self, failure: AssertionFailure) -> bool:
        """Escalate a failure when recovery attempts are exhausted."""
        
        logger.error(f"Escalating failure: {failure.assertion_id}")
        
        # For critical domains, always trigger rollback
        if failure.severity == AssertionFailureSeverity.CRITICAL:
            return self._trigger_system_rollback(failure, "critical_failure_escalation")
        
        # For non-critical domains, mark as invalid and continue
        self._mark_assertion_invalid(failure.assertion_id)
        self._log_failure_event(failure, "failure_escalated")
        
        return False  # Recovery failed
    
    def _trigger_system_rollback(self, failure: AssertionFailure, reason: str) -> bool:
        """Trigger system rollback due to critical failure."""
        
        logger.critical(f"Triggering system rollback due to {reason}: {failure.assertion_id}")
        
        # Log rollback event
        log_rollback(
            old_mode="SIGHTED_DEGRADED",
            new_mode="BLIND",
            reason_code=reason,
            reason_detail=failure.error_message,
            system_state={
                "failed_assertion": failure.assertion_id,
                "failure_type": failure.failure_type.value,
                "severity": failure.severity.value,
                "domain": failure.domain.value
            },
            triggering_actor="assertion_error_handler"
        )
        
        # In a real system, this would trigger the actual mode change
        # For now, we just log it
        
        return False  # Recovery failed, system rolled back
    
    def _mark_assertion_invalid(self, assertion_id: str):
        """Mark an assertion as invalid."""
        
        try:
            from core.reality_registry import get_reality_registry, AssertionStatus
            
            registry = get_reality_registry()
            
            # Get the assertion
            assertion = registry.get_assertion(assertion_id)
            if assertion:
                # Mark as invalid
                assertion.status = AssertionStatus.INVALID
                logger.info(f"Marked assertion {assertion_id} as invalid")
            else:
                logger.warning(f"Assertion {assertion_id} not found for invalid marking")
                
        except Exception as e:
            logger.error(f"Failed to mark assertion {assertion_id} as invalid: {e}")
    
    def _retry_assertion_evaluation(self, assertion_id: str) -> bool:
        """Retry assertion evaluation."""
        
        try:
            from core.reality_registry import get_reality_registry
            
            registry = get_reality_registry()
            assertion = registry.get_assertion(assertion_id)
            
            if not assertion:
                return False
            
            # Re-evaluate the assertion
            current_time = time.time()
            is_valid = assertion.is_usable(current_time, registry.regime_entropy)
            
            if is_valid:
                assertion.status = AssertionStatus.VALID
                return True
            else:
                assertion.status = AssertionStatus.INVALID
                return False
                
        except Exception as e:
            logger.error(f"Failed to retry assertion evaluation for {assertion_id}: {e}")
            return False
    
    def _count_domain_anomalies(self, domain: AssertionDomain) -> int:
        """Count recent anomalies in a domain."""
        
        current_time = time.time()
        recent_window = 3600  # Last hour
        
        return sum(1 for failure in self.failure_history 
                  if failure.domain == domain 
                  and failure.failure_type == AssertionFailureType.DATA_ANOMALY
                  and current_time - failure.timestamp < recent_window)
    
    def _degrade_domain(self, domain: AssertionDomain):
        """Degrade a domain due to too many anomalies."""
        
        logger.warning(f"Degrading domain {domain.value} due to excessive anomalies")
        
        # In a real system, this would:
        # 1. Reduce priority of the domain
        # 2. Increase monitoring frequency
        # 3. Alert operators
        # 4. Possibly disable certain operations
        
        # For now, we just log it
        self._log_failure_event(None, f"domain_degraded_{domain.value}")
    
    def _log_failure_event(self, failure: Optional[AssertionFailure], event_type: str):
        """Log a structured failure event."""
        
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            "assertion_id": failure.assertion_id if failure else None,
            "domain": failure.domain.value if failure else None,
            "failure_type": failure.failure_type.value if failure else None,
            "severity": failure.severity.value if failure else None,
            "error_message": failure.error_message if failure else None,
            "recovery_attempts": failure.recovery_attempts if failure else None
        }
        
        logger.info(f"Failure event: {event}")
    
    def get_failure_statistics(self) -> Dict[str, Any]:
        """Get statistics about assertion failures."""
        
        current_time = time.time()
        recent_window = 3600  # Last hour
        
        recent_failures = [
            f for f in self.failure_history 
            if current_time - f.timestamp < recent_window
        ]
        
        stats = {
            "total_failures": len(self.failure_history),
            "recent_failures": len(recent_failures),
            "failure_types": {},
            "severity_distribution": {},
            "domain_distribution": {},
            "recovery_success_rate": 0.0
        }
        
        # Count failure types
        for failure in recent_failures:
            failure_type = failure.failure_type.value
            stats["failure_types"][failure_type] = stats["failure_types"].get(failure_type, 0) + 1
        
        # Count severity distribution
        for failure in recent_failures:
            severity = failure.severity.value
            stats["severity_distribution"][severity] = stats["severity_distribution"].get(severity, 0) + 1
        
        # Count domain distribution
        for failure in recent_failures:
            domain = failure.domain.value
            stats["domain_distribution"][domain] = stats["domain_distribution"].get(domain, 0) + 1
        
        # Calculate recovery success rate
        recovered_failures = sum(1 for f in recent_failures if f.recovery_attempts > 0)
        total_attempted = sum(f.recovery_attempts for f in recent_failures)
        
        if total_attempted > 0:
            stats["recovery_success_rate"] = recovered_failures / total_attempted
        
        return stats


# Global error handler instance
_error_handler = None


def get_assertion_error_handler() -> AssertionErrorHandler:
    """Get the global assertion error handler."""
    global _error_handler
    if _error_handler is None:
        _error_handler = AssertionErrorHandler()
    return _error_handler


def handle_assertion_error(assertion_id: str, domain: AssertionDomain, 
                          error: Exception, context: Dict[str, Any]) -> bool:
    """Handle an assertion error using the global error handler."""
    
    handler = get_assertion_error_handler()
    failure = handler.classify_failure(assertion_id, domain, error, context)
    return handler.handle_failure(failure)
