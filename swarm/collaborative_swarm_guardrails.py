"""
Collaborative Swarm Guardrails for MERID Self-Building System.

Enforces safety constraints, code quality standards, and operational boundaries
for autonomous dev swarm operations.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set
from utils.logger import get_logger

logger = get_logger(__name__)


class GuardrailViolation(Enum):
    CRITICAL_FILE_MODIFICATION = "critical_file_modification"
    UNSAFE_OPERATION = "unsafe_operation"
    QUALITY_THRESHOLD = "quality_threshold"
    SECURITY_RISK = "security_risk"
    RATE_LIMIT = "rate_limit"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class GuardrailCheck:
    check_id: str
    violation_type: GuardrailViolation
    severity: str
    message: str
    blocked: bool
    timestamp: datetime


class CollaborativeSwarmGuardrails:
    """
    Safety guardrails for autonomous dev swarm.
    
    Features:
    - Critical file protection
    - Operation safety checks
    - Code quality enforcement
    - Security scanning
    - Rate limiting
    - Budget controls
    """
    
    def __init__(self):
        self._critical_files: Set[str] = set()
        self._blocked_operations: Set[str] = set()
        self._violation_history: List[GuardrailCheck] = []
        self._daily_operation_limit = 100
        self._operations_today = 0
        self._last_reset = datetime.utcnow().date()
        
        self._initialize_critical_files()
        self._initialize_blocked_operations()
    
    def _initialize_critical_files(self) -> None:
        """Initialize list of critical files that require human approval."""
        self._critical_files = {
            "core/automated_risk_controls.py",
            "trading/execution.py",
            "governance/multi_agent_risk_controls.py",
            "core/memecoin_safety.py",
            "wallet/multi_chain_wallet.py",
            "security/breach_detection.py",
            "core/reality_registry.py",
            "core/reality_auditor.py",
            ".env",
            "config/production.yaml",
            "master_roadmap_checklist.txt",
        }
    
    def _initialize_blocked_operations(self) -> None:
        """Initialize list of operations that are always blocked."""
        self._blocked_operations = {
            "delete_database",
            "drop_table",
            "disable_all_risk_controls",
            "bypass_authentication",
            "expose_private_keys",
            "disable_guardrails",
            "modify_kill_switch",
        }
    
    def check_file_modification(self, file_path: str) -> GuardrailCheck:
        """Check if file modification is allowed."""
        if file_path in self._critical_files:
            check = GuardrailCheck(
                check_id=f"file_mod_{int(datetime.utcnow().timestamp())}",
                violation_type=GuardrailViolation.CRITICAL_FILE_MODIFICATION,
                severity="high",
                message=f"Modification of critical file requires human approval: {file_path}",
                blocked=True,
                timestamp=datetime.utcnow(),
            )
            self._violation_history.append(check)
            logger.warning(f"Blocked critical file modification: {file_path}")
            return check
        
        return GuardrailCheck(
            check_id=f"file_mod_{int(datetime.utcnow().timestamp())}",
            violation_type=GuardrailViolation.CRITICAL_FILE_MODIFICATION,
            severity="info",
            message=f"File modification allowed: {file_path}",
            blocked=False,
            timestamp=datetime.utcnow(),
        )
    
    def check_operation(self, operation: str) -> GuardrailCheck:
        """Check if operation is allowed."""
        if operation in self._blocked_operations:
            check = GuardrailCheck(
                check_id=f"op_{int(datetime.utcnow().timestamp())}",
                violation_type=GuardrailViolation.UNSAFE_OPERATION,
                severity="critical",
                message=f"Operation is permanently blocked: {operation}",
                blocked=True,
                timestamp=datetime.utcnow(),
            )
            self._violation_history.append(check)
            logger.error(f"Blocked unsafe operation: {operation}")
            return check
        
        return GuardrailCheck(
            check_id=f"op_{int(datetime.utcnow().timestamp())}",
            violation_type=GuardrailViolation.UNSAFE_OPERATION,
            severity="info",
            message=f"Operation allowed: {operation}",
            blocked=False,
            timestamp=datetime.utcnow(),
        )
    
    def check_rate_limit(self) -> GuardrailCheck:
        """Check if daily operation rate limit is exceeded."""
        today = datetime.utcnow().date()
        if today != self._last_reset:
            self._operations_today = 0
            self._last_reset = today
        
        self._operations_today += 1
        
        if self._operations_today > self._daily_operation_limit:
            check = GuardrailCheck(
                check_id=f"rate_{int(datetime.utcnow().timestamp())}",
                violation_type=GuardrailViolation.RATE_LIMIT,
                severity="high",
                message=f"Daily operation limit exceeded: {self._operations_today}/{self._daily_operation_limit}",
                blocked=True,
                timestamp=datetime.utcnow(),
            )
            self._violation_history.append(check)
            logger.warning("Daily operation limit exceeded")
            return check
        
        return GuardrailCheck(
            check_id=f"rate_{int(datetime.utcnow().timestamp())}",
            violation_type=GuardrailViolation.RATE_LIMIT,
            severity="info",
            message=f"Rate limit OK: {self._operations_today}/{self._daily_operation_limit}",
            blocked=False,
            timestamp=datetime.utcnow(),
        )
    
    def check_code_quality(self, code: str) -> GuardrailCheck:
        """Check code quality standards."""
        issues = []
        
        if "TODO" in code or "FIXME" in code:
            issues.append("Contains TODO/FIXME markers")
        
        if "import *" in code:
            issues.append("Uses wildcard imports")
        
        if len(code.split("\n")) > 500:
            issues.append("File exceeds 500 lines (consider refactoring)")
        
        if not any(keyword in code for keyword in ["def ", "class ", "async def "]):
            issues.append("No functions or classes defined")
        
        if issues:
            check = GuardrailCheck(
                check_id=f"quality_{int(datetime.utcnow().timestamp())}",
                violation_type=GuardrailViolation.QUALITY_THRESHOLD,
                severity="medium",
                message=f"Code quality issues: {'; '.join(issues)}",
                blocked=False,
                timestamp=datetime.utcnow(),
            )
            self._violation_history.append(check)
            return check
        
        return GuardrailCheck(
            check_id=f"quality_{int(datetime.utcnow().timestamp())}",
            violation_type=GuardrailViolation.QUALITY_THRESHOLD,
            severity="info",
            message="Code quality check passed",
            blocked=False,
            timestamp=datetime.utcnow(),
        )
    
    def check_security(self, code: str) -> GuardrailCheck:
        """Check for security risks in code."""
        risks = []
        
        dangerous_patterns = [
            ("eval(", "Use of eval()"),
            ("exec(", "Use of exec()"),
            ("__import__", "Dynamic imports"),
            ("os.system(", "Direct system calls"),
            ("subprocess.call(", "Subprocess execution"),
            ("pickle.loads(", "Unsafe deserialization"),
        ]
        
        for pattern, risk in dangerous_patterns:
            if pattern in code:
                risks.append(risk)
        
        if "password" in code.lower() or "api_key" in code.lower():
            if "=" in code and '"' in code:
                risks.append("Potential hardcoded credentials")
        
        if risks:
            check = GuardrailCheck(
                check_id=f"security_{int(datetime.utcnow().timestamp())}",
                violation_type=GuardrailViolation.SECURITY_RISK,
                severity="high",
                message=f"Security risks detected: {'; '.join(risks)}",
                blocked=True,
                timestamp=datetime.utcnow(),
            )
            self._violation_history.append(check)
            logger.error(f"Security risks detected: {risks}")
            return check
        
        return GuardrailCheck(
            check_id=f"security_{int(datetime.utcnow().timestamp())}",
            violation_type=GuardrailViolation.SECURITY_RISK,
            severity="info",
            message="Security check passed",
            blocked=False,
            timestamp=datetime.utcnow(),
        )
    
    def add_critical_file(self, file_path: str) -> None:
        """Add file to critical files list."""
        self._critical_files.add(file_path)
        logger.info(f"Added critical file: {file_path}")
    
    def remove_critical_file(self, file_path: str) -> None:
        """Remove file from critical files list."""
        self._critical_files.discard(file_path)
        logger.info(f"Removed critical file: {file_path}")
    
    def get_violation_history(self, limit: int = 50) -> List[GuardrailCheck]:
        """Get recent guardrail violations."""
        return self._violation_history[-limit:]
    
    def get_guardrail_status(self) -> Dict[str, object]:
        """Get guardrail status."""
        recent_violations = [
            v for v in self._violation_history
            if v.blocked and (datetime.utcnow() - v.timestamp).seconds < 3600
        ]
        
        return {
            "critical_files_count": len(self._critical_files),
            "blocked_operations_count": len(self._blocked_operations),
            "operations_today": self._operations_today,
            "daily_limit": self._daily_operation_limit,
            "recent_violations_1h": len(recent_violations),
            "total_violations": len([v for v in self._violation_history if v.blocked]),
        }


_collaborative_swarm_guardrails: Optional[CollaborativeSwarmGuardrails] = None
_collaborative_swarm_guardrails_lock = threading.Lock()


def get_collaborative_swarm_guardrails() -> CollaborativeSwarmGuardrails:
    """Get global CollaborativeSwarmGuardrails instance."""
    global _collaborative_swarm_guardrails
    if _collaborative_swarm_guardrails is None:
        with _collaborative_swarm_guardrails_lock:
            if _collaborative_swarm_guardrails is None:
                _collaborative_swarm_guardrails = CollaborativeSwarmGuardrails()
    return _collaborative_swarm_guardrails
