"""
Enhanced Watchdog Rules for MERID Swarm Governance
Stricter rules for sensitive areas, retry caps, and role violations
"""

import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum
import re
import os

from swarm.watchdog.monitor import WatchdogViolation, WatchdogConfig
from utils.logger import get_logger

logger = get_logger("swarm.enhanced_watchdog")


class EnhancedViolationType(Enum):
    """Enhanced violation types for stricter governance"""
    SENSITIVE_FILE_EDIT = "sensitive_file_edit"
    EXCESSIVE_RETRIES = "excessive_retries"
    ROLE_VIOLATION = "role_violation"
    LIVE_TRADING_EDIT = "live_trading_edit"
    SECRETS_ACCESS = "secrets_access"
    RISK_PARAMETER_CHANGE = "risk_parameter_change"
    PRODUCTION_CONFIG_CHANGE = "production_config_change"
    CRITICAL_INFRA_CHANGE = "critical_infra_change"
    UNAUTHORIZED_TOOL_USE = "unauthorized_tool_use"


@dataclass
class EnhancedViolationEvent:
    """Enhanced violation event with more context"""
    violation_type: EnhancedViolationType
    agent_id: str
    task_id: str
    timestamp: float
    details: Dict[str, Any]
    severity: str = "medium"
    enforcement_action: Optional[str] = None  # "block", "warn", "log_only"


class EnhancedWatchdogConfig(WatchdogConfig):
    """Enhanced watchdog configuration with stricter rules"""
    
    def __init__(self):
        super().__init__()
        
        # Sensitive file patterns
        self.sensitive_file_patterns = [
            r".*\.key$",
            r".*\.pem$",
            r".*\.p12$",
            r".*passwords?\..*",
            r".*secrets?\..*",
            r".*\.env$",
            r".*config/production\.?.*",
            r".*risk/.*\.json$",
            r".*trading/.*\.json$",
            r".*live/.*\.json$"
        ]
        
        # Critical infrastructure paths
        self.critical_infra_paths = [
            "/etc/kubernetes/",
            "/etc/ssl/",
            "/etc/nginx/",
            "/var/lib/",
            "/opt/",
            "C:\\Windows\\System32\\",
            "C:\\Program Files\\",
            "C:\\ProgramData\\"
        ]
        
        # Per-tool retry caps
        self.tool_retry_caps = {
            "repo_search": 3,
            "file_read": 5,
            "file_write": 2,
            "database_query": 3,
            "api_call": 5,
            "tool_execution": 2,
            "deployment": 1,
            "risk_calculation": 2
        }
        
        # Role-based permissions
        self.role_permissions = {
            "planner": ["repo_search", "file_read", "analysis"],
            "implementer": ["file_write", "tool_execution", "test_runner"],
            "reviewer": ["file_read", "linting", "security_scan"],
            "risk_manager": ["risk_calculation", "monitoring"],
            "trader": ["market_data", "price_analysis", "order_placement"],
            "deployer": ["deployment", "config_update"],
            "governor": ["policy_check", "audit", "approval"]
        }
        
        # Enforcement levels
        self.enforcement_levels = {
            "sensitive_file_edit": "block",
            "excessive_retries": "warn",
            "role_violation": "warn",
            "live_trading_edit": "block",
            "secrets_access": "block",
            "risk_parameter_change": "warn",
            "production_config_change": "block",
            "critical_infra_change": "block",
            "unauthorized_tool_use": "warn"
        }


class EnhancedWatchdog:
    """Enhanced watchdog with stricter governance rules"""
    
    def __init__(self, config: Optional[EnhancedWatchdogConfig] = None, enforcement_mode: bool = False):
        self.config = config or EnhancedWatchdogConfig()
        self.enforcement_mode = enforcement_mode  # False for staging, True for production
        self.enhanced_violations: List[EnhancedViolationEvent] = []
        self.tool_retry_counts: Dict[str, Dict[str, int]] = {}
        self._lock = None
        
        logger.info(f"Enhanced watchdog initialized - enforcement: {enforcement_mode}")
    
    def check_sensitive_file_access(self, task_id: str, agent_id: str, 
                                  file_path: str, operation: str) -> Optional[EnhancedViolationEvent]:
        """Check for sensitive file access"""
        file_path_normalized = file_path.lower().replace("\\", "/")
        
        # Check against sensitive patterns
        for pattern in self.config.sensitive_file_patterns:
            if re.match(pattern, file_path_normalized, re.IGNORECASE):
                violation = EnhancedViolationEvent(
                    violation_type=EnhancedViolationType.SENSITIVE_FILE_EDIT,
                    agent_id=agent_id,
                    task_id=task_id,
                    timestamp=time.time(),
                    details={
                        "file_path": file_path,
                        "operation": operation,
                        "pattern_matched": pattern,
                        "enforcement_action": self.config.enforcement_levels["sensitive_file_edit"]
                    },
                    severity="critical"
                )
                
                self._handle_violation(violation)
                return violation
        
        return None
    
    def check_tool_retry_limit(self, task_id: str, agent_id: str, 
                               tool_name: str, retry_count: int) -> Optional[EnhancedViolationEvent]:
        """Check for excessive tool retries"""
        cap = self.config.tool_retry_caps.get(tool_name, 3)  # Default cap
        
        if retry_count > cap:
            violation = EnhancedViolationEvent(
                violation_type=EnhancedViolationType.EXCESSIVE_RETRIES,
                agent_id=agent_id,
                task_id=task_id,
                timestamp=time.time(),
                details={
                    "tool_name": tool_name,
                    "retry_count": retry_count,
                    "retry_cap": cap,
                    "excessive_by": retry_count - cap,
                    "enforcement_action": self.config.enforcement_levels["excessive_retries"]
                },
                severity="medium"
            )
            
            self._handle_violation(violation)
            return violation
        
        return None
    
    def check_role_violation(self, task_id: str, agent_id: str, 
                            agent_role: str, tool_name: str) -> Optional[EnhancedViolationEvent]:
        """Check for role-based permission violations"""
        allowed_tools = self.config.role_permissions.get(agent_role, [])
        
        if tool_name not in allowed_tools:
            violation = EnhancedViolationEvent(
                violation_type=EnhancedViolationType.ROLE_VIOLATION,
                agent_id=agent_id,
                task_id=task_id,
                timestamp=time.time(),
                details={
                    "agent_role": agent_role,
                    "tool_name": tool_name,
                    "allowed_tools": allowed_tools,
                    "enforcement_action": self.config.enforcement_levels["role_violation"]
                },
                severity="medium"
            )
            
            self._handle_violation(violation)
            return violation
        
        return None
    
    def check_live_trading_access(self, task_id: str, agent_id: str, 
                                 file_path: str, operation: str) -> Optional[EnhancedViolationEvent]:
        """Check for live trading system access"""
        trading_patterns = [
            r".*live/.*trading.*",
            r".*production/.*trading.*",
            r".*trading/.*live.*",
            r".*market/.*data.*live.*"
        ]
        
        file_path_normalized = file_path.lower().replace("\\", "/")
        
        for pattern in trading_patterns:
            if re.search(pattern, file_path_normalized):
                violation = EnhancedViolationEvent(
                    violation_type=EnhancedViolationType.LIVE_TRADING_EDIT,
                    agent_id=agent_id,
                    task_id=task_id,
                    timestamp=time.time(),
                    details={
                        "file_path": file_path,
                        "operation": operation,
                        "pattern_matched": pattern,
                        "enforcement_action": self.config.enforcement_levels["live_trading_edit"]
                    },
                    severity="critical"
                )
                
                self._handle_violation(violation)
                return violation
        
        return None
    
    def check_critical_infra_access(self, task_id: str, agent_id: str, 
                                     file_path: str) -> Optional[EnhancedViolationEvent]:
        """Check for critical infrastructure access"""
        file_path_normalized = file_path.lower().replace("\\", "/")
        
        for infra_path in self.config.critical_infra_paths:
            infra_path_normalized = infra_path.lower().replace("\\", "/")
            if file_path_normalized.startswith(infra_path_normalized):
                violation = EnhancedViolationEvent(
                    violation_type=EnhancedViolationType.CRITICAL_INFRA_CHANGE,
                    agent_id=agent_id,
                    task_id=task_id,
                    timestamp=time.time(),
                    details={
                        "file_path": file_path,
                        "infra_path": infra_path,
                        "enforcement_action": self.config.enforcement_levels["critical_infra_change"]
                    },
                    severity="critical"
                )
                
                self._handle_violation(violation)
                return violation
        
        return None
    
    def track_tool_retry(self, task_id: str, agent_id: str, tool_name: str):
        """Track tool retry attempts"""
        if task_id not in self.tool_retry_counts:
            self.tool_retry_counts[task_id] = {}
        
        if agent_id not in self.tool_retry_counts[task_id]:
            self.tool_retry_counts[task_id][agent_id] = {}
        
        self.tool_retry_counts[task_id][agent_id][tool_name] = \
            self.tool_retry_counts[task_id][agent_id].get(tool_name, 0) + 1
        
        # Check for excessive retries
        retry_count = self.tool_retry_counts[task_id][agent_id][tool_name]
        return self.check_tool_retry_limit(task_id, agent_id, tool_name, retry_count)
    
    def get_enhanced_violations(self, severity: Optional[str] = None,
                                violation_type: Optional[EnhancedViolationType] = None,
                                task_id: Optional[str] = None) -> List[EnhancedViolationEvent]:
        """Get enhanced violations with filtering"""
        violations = self.enhanced_violations
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        if violation_type:
            violations = [v for v in violations if v.violation_type == violation_type]
        
        if task_id:
            violations = [v for v in violations if v.task_id == task_id]
        
        return violations
    
    def get_violation_summary(self) -> Dict[str, Any]:
        """Get summary of violations"""
        total_violations = len(self.enhanced_violations)
        
        if total_violations == 0:
            return {
                "total_violations": 0,
                "by_severity": {},
                "by_type": {},
                "by_agent": {},
                "enforcement_actions": {}
            }
        
        # Count by various dimensions
        by_severity = {}
        by_type = {}
        by_agent = {}
        enforcement_actions = {}
        
        for violation in self.enhanced_violations:
            # By severity
            by_severity[violation.severity] = by_severity.get(violation.severity, 0) + 1
            
            # By type
            by_type[violation.violation_type.value] = by_type.get(violation.violation_type.value, 0) + 1
            
            # By agent
            by_agent[violation.agent_id] = by_agent.get(violation.agent_id, 0) + 1
            
            # By enforcement action
            if violation.enforcement_action:
                enforcement_actions[violation.enforcement_action] = \
                    enforcement_actions.get(violation.enforcement_action, 0) + 1
        
        return {
            "total_violations": total_violations,
            "by_severity": by_severity,
            "by_type": by_type,
            "by_agent": by_agent,
            "enforcement_actions": enforcement_actions
        }
    
    def _handle_violation(self, violation: EnhancedViolationEvent):
        """Handle a violation based on enforcement mode"""
        self.enhanced_violations.append(violation)
        
        action = violation.enforcement_action
        
        if self.enforcement_mode and action == "block":
            logger.error(f"BLOCKING operation: {violation.violation_type.value} by {violation.agent_id}")
            # In production, this would block the operation
            # For now, we just log it
            raise PermissionError(f"Operation blocked: {violation.violation_type.value}")
        
        elif action == "warn":
            logger.warning(f"WARNING: {violation.violation_type.value} by {violation.agent_id}")
        
        else:  # log_only
            logger.info(f"VIOLATION: {violation.violation_type.value} by {violation.agent_id}")


# Global enhanced watchdog instance
enhanced_watchdog = EnhancedWatchdog(enforcement_mode=False)  # Start in logging mode
