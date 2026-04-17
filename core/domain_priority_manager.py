"""
Domain Priority Manager for SIGHTED_DEGRADED Mode

Enforces strict "observe core, block action" hierarchy with input priorities,
usage permissions, and safety checks.
"""

import threading
import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("core.domain_priority")


class DomainPriority(Enum):
    """Domain priority levels for SIGHTED_DEGRADED mode."""
    HIGHEST = 1    # Market, Onchain
    HIGH = 2       # Simulation
    MEDIUM = 3     # Agent
    BLOCKED = 4    # Execution, Governance, Treasury, System


class UsagePermission(Enum):
    """Usage permissions for domains."""
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    PROPOSALS_ONLY = "proposals_only"
    BLOCKED = "blocked"


@dataclass
class DomainConfig:
    """Configuration for a domain in SIGHTED_DEGRADED mode."""
    domain: str
    priority: DomainPriority
    ingestion_rate: str  # "real_time", "batch", "event_driven", "none"
    usage_permission: UsagePermission
    max_queries_per_minute: int
    rationale: str


@dataclass
class PriorityViolation:
    """Record of a priority rule violation."""
    violation_id: str
    timestamp: float
    domain: str
    operation: str
    reason: str
    severity: str  # "warning", "error", "critical"
    actor_id: Optional[str]


class DomainPriorityManager:
    """
    Enforces strict domain input priorities for SIGHTED_DEGRADED mode.
    
    Implements "observe core, block action" hierarchy with comprehensive
    safety checks and audit logging.
    """
    
    def __init__(self):
        self.current_mode = "BLIND"
        self.domain_configs = self._initialize_domain_configs()
        self.priority_violations: List[PriorityViolation] = []
        self.query_rates: Dict[str, List[float]] = {}
        self.last_safety_check = 0.0
        self.safety_check_interval = 300.0  # 5 minutes
        
        # Initialize query rate tracking
        for domain in self.domain_configs:
            self.query_rates[domain] = []
    
    def _initialize_domain_configs(self) -> Dict[str, DomainConfig]:
        """Initialize domain configurations according to priority rules."""
        return {
            "market": DomainConfig(
                domain="market",
                priority=DomainPriority.HIGHEST,
                ingestion_rate="real_time",
                usage_permission=UsagePermission.READ_ONLY,
                max_queries_per_minute=1000,
                rationale="Live price/vol data grounds all reasoning"
            ),
            "onchain": DomainConfig(
                domain="onchain",
                priority=DomainPriority.HIGHEST,
                ingestion_rate="real_time",
                usage_permission=UsagePermission.READ_ONLY,
                max_queries_per_minute=500,
                rationale="External capital reality; required for risk invariants"
            ),
            "simulation": DomainConfig(
                domain="simulation",
                priority=DomainPriority.HIGH,
                ingestion_rate="batch",
                usage_permission=UsagePermission.READ_WRITE,
                max_queries_per_minute=100,
                rationale="Tests hypotheses safely using sighted data"
            ),
            "agent": DomainConfig(
                domain="agent",
                priority=DomainPriority.MEDIUM,
                ingestion_rate="event_driven",
                usage_permission=UsagePermission.PROPOSALS_ONLY,
                max_queries_per_minute=50,
                rationale="Reasoning/planning OK; no autonomous action"
            ),
            "execution": DomainConfig(
                domain="execution",
                priority=DomainPriority.BLOCKED,
                ingestion_rate="none",
                usage_permission=UsagePermission.BLOCKED,
                max_queries_per_minute=0,
                rationale="No live orders allowed"
            ),
            "governance": DomainConfig(
                domain="governance",
                priority=DomainPriority.BLOCKED,
                ingestion_rate="none",
                usage_permission=UsagePermission.BLOCKED,
                max_queries_per_minute=0,
                rationale="Phase 0 conservative"
            ),
            "treasury": DomainConfig(
                domain="treasury",
                priority=DomainPriority.BLOCKED,
                ingestion_rate="none",
                usage_permission=UsagePermission.BLOCKED,
                max_queries_per_minute=0,
                rationale="Capital protection"
            ),
            "system": DomainConfig(
                domain="system",
                priority=DomainPriority.BLOCKED,
                ingestion_rate="none",
                usage_permission=UsagePermission.BLOCKED,
                max_queries_per_minute=0,
                rationale="Infra stability first"
            )
        }
    
    def set_mode(self, mode: str):
        """Update the current system mode."""
        old_mode = self.current_mode
        self.current_mode = mode
        
        if mode == "SIGHTED_DEGRADED":
            logger.info(f"Domain priority manager activated for {mode}")
            self._run_safety_checks()
        elif old_mode == "SIGHTED_DEGRADED" and mode == "BLIND":
            logger.info(f"Domain priority manager deactivated - rolling back to {mode}")
            self._clear_query_rates()
    
    def check_domain_access(self, domain: str, operation: str, actor_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if a domain operation is allowed under current priority rules.
        
        Returns (allowed, reason) tuple.
        """
        if self.current_mode != "SIGHTED_DEGRADED":
            return True, f"Mode {self.current_mode} - no priority restrictions"
        
        if domain not in self.domain_configs:
            violation = PriorityViolation(
                violation_id=str(uuid.uuid4()),
                timestamp=time.time(),
                domain=domain,
                operation=operation,
                reason="UNKNOWN_DOMAIN",
                severity="error",
                actor_id=actor_id
            )
            self.priority_violations.append(violation)
            return False, f"Unknown domain: {domain}"
        
        config = self.domain_configs[domain]
        
        # Check if domain is blocked
        if config.usage_permission == UsagePermission.BLOCKED:
            violation = PriorityViolation(
                violation_id=str(uuid.uuid4()),
                timestamp=time.time(),
                domain=domain,
                operation=operation,
                reason="DOMAIN_BLOCKED",
                severity="error",
                actor_id=actor_id
            )
            self.priority_violations.append(violation)
            return False, f"Domain {domain} is blocked in SIGHTED_DEGRADED mode"
        
        # Check query rate limits
        if not self._check_query_rate_limit(domain):
            violation = PriorityViolation(
                violation_id=str(uuid.uuid4()),
                timestamp=time.time(),
                domain=domain,
                operation=operation,
                reason="RATE_LIMIT_EXCEEDED",
                severity="warning",
                actor_id=actor_id
            )
            self.priority_violations.append(violation)
            return False, f"Query rate limit exceeded for {domain}"
        
        # Check operation-specific permissions
        if not self._check_operation_permission(domain, operation):
            violation = PriorityViolation(
                violation_id=str(uuid.uuid4()),
                timestamp=time.time(),
                domain=domain,
                operation=operation,
                reason="OPERATION_NOT_PERMITTED",
                severity="error",
                actor_id=actor_id
            )
            self.priority_violations.append(violation)
            return False, f"Operation {operation} not permitted for {domain}"
        
        # Log the query for rate limiting
        self._log_query(domain)
        
        return True, f"Access granted for {domain} {operation}"
    
    def _check_query_rate_limit(self, domain: str) -> bool:
        """Check if domain is within query rate limits."""
        config = self.domain_configs[domain]
        current_time = time.time()
        
        # Clean old queries (older than 1 minute)
        self.query_rates[domain] = [
            q_time for q_time in self.query_rates[domain]
            if current_time - q_time < 60.0
        ]
        
        # Check against limit
        return len(self.query_rates[domain]) < config.max_queries_per_minute
    
    def _log_query(self, domain: str):
        """Log a query for rate limiting."""
        self.query_rates[domain].append(time.time())
    
    def _check_operation_permission(self, domain: str, operation: str) -> bool:
        """Check if specific operation is allowed for the domain."""
        config = self.domain_configs[domain]
        
        # Map operations to permission requirements
        write_operations = {"write", "create", "update", "delete", "execute", "transfer", "order"}
        proposal_operations = {"propose", "suggest", "recommend"}
        read_operations = {"read", "get", "list", "query", "monitor"}
        
        operation_lower = operation.lower()
        
        if config.usage_permission == UsagePermission.READ_ONLY:
            return any(op in operation_lower for op in read_operations)
        elif config.usage_permission == UsagePermission.READ_WRITE:
            return True  # All operations allowed
        elif config.usage_permission == UsagePermission.PROPOSALS_ONLY:
            return any(op in operation_lower for op in read_operations + proposal_operations)
        elif config.usage_permission == UsagePermission.BLOCKED:
            return False
        
        return False
    
    def _run_safety_checks(self) -> Dict[str, bool]:
        """Run comprehensive safety checks for SIGHTED_DEGRADED mode."""
        current_time = time.time()
        self.last_safety_check = current_time
        
        results = {
            "priority_violations": len(self.priority_violations) == 0,
            "query_rates_ok": self._check_all_query_rates(),
            "domain_configs_valid": self._validate_domain_configs(),
            "cascade_conditions": self._check_cascade_conditions()
        }
        
        # Log safety check results
        logger.info(f"SIGHTED_DEGRADED safety checks: {results}")
        
        return results
    
    def _check_all_query_rates(self) -> bool:
        """Check all domains are within query rate limits."""
        for domain in self.domain_configs:
            if not self._check_query_rate_limit(domain):
                return False
        return True
    
    def _validate_domain_configs(self) -> bool:
        """Validate domain configurations are consistent."""
        # Check priority hierarchy
        priorities = set(config.priority for config in self.domain_configs.values())
        expected_priorities = {DomainPriority.HIGHEST, DomainPriority.HIGH, DomainPriority.MEDIUM, DomainPriority.BLOCKED}
        
        return priorities == expected_priorities
    
    def _check_cascade_conditions(self) -> bool:
        """Check cascade conditions (higher priority domains must be healthy)."""
        # In SIGHTED_DEGRADED, all core domains should be sighted
        # This would typically check actual domain health
        return True  # Placeholder
    
    def _clear_query_rates(self):
        """Clear all query rate tracking."""
        for domain in self.query_rates:
            self.query_rates[domain] = []
    
    def get_domain_status(self) -> Dict[str, Dict]:
        """Get current status of all domains."""
        status = {}
        
        for domain, config in self.domain_configs.items():
            current_queries = len([
                q_time for q_time in self.query_rates[domain]
                if time.time() - q_time < 60.0
            ])
            
            status[domain] = {
                "priority": config.priority.value,
                "ingestion_rate": config.ingestion_rate,
                "usage_permission": config.usage_permission.value,
                "max_queries_per_minute": config.max_queries_per_minute,
                "current_queries_per_minute": current_queries,
                "rationale": config.rationale,
                "accessible": config.usage_permission != UsagePermission.BLOCKED
            }
        
        return status
    
    def get_priority_violations(self, limit: int = 100) -> List[Dict]:
        """Get recent priority violations."""
        violations = self.priority_violations[-limit:]
        return [
            {
                "violation_id": v.violation_id,
                "timestamp": v.timestamp,
                "domain": v.domain,
                "operation": v.operation,
                "reason": v.reason,
                "severity": v.severity,
                "actor_id": v.actor_id
            }
            for v in violations
        ]
    
    def clear_violations(self):
        """Clear all priority violations."""
        self.priority_violations.clear()
    
    def get_priority_summary(self) -> Dict:
        """Get a summary of domain priorities and current state."""
        if self.current_mode != "SIGHTED_DEGRADED":
            return {"mode": self.current_mode, "message": "Priority rules not active"}
        
        status = self.get_domain_status()
        violations = self.get_priority_violations(10)
        
        return {
            "mode": self.current_mode,
            "priority_hierarchy": {
                "highest": [d for d, s in status.items() if s["priority"] == 1],
                "high": [d for d, s in status.items() if s["priority"] == 2],
                "medium": [d for d, s in status.items() if s["priority"] == 3],
                "blocked": [d for d, s in status.items() if s["priority"] == 4]
            },
            "accessible_domains": [d for d, s in status.items() if s["accessible"]],
            "blocked_domains": [d for d, s in status.items() if not s["accessible"]],
            "recent_violations": violations,
            "last_safety_check": self.last_safety_check,
            "total_violations": len(self.priority_violations)
        }


# Global instance
_domain_priority_manager: Optional[DomainPriorityManager] = None
_domain_priority_manager_lock = threading.Lock()


def get_domain_priority_manager() -> DomainPriorityManager:
    """Get the global domain priority manager."""
    global _domain_priority_manager
    if _domain_priority_manager is None:
        with _domain_priority_manager_lock:
            if _domain_priority_manager is None:
                _domain_priority_manager = DomainPriorityManager()
    return _domain_priority_manager
