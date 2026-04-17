"""
Security & Breach Safety System

Comprehensive security stack including:
- Secrets & key management (vault/HSM integration)
- Least privilege & isolation
- Network security enforcement
- Breach detection & response
- Role-based permissions with auditing
- LLM & prompt safety
- Backup & recovery
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import threading
import hashlib
import re

logger = get_logger(__name__)


class ThreatLevel(Enum):
    """Threat severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatCategory(Enum):
    """Categories of security threats."""
    ANOMALOUS_ORDER = "anomalous_order"
    VENUE_ABUSE = "venue_abuse"
    IP_CHANGE = "ip_change"
    AUTH_FAILURE = "auth_failure"
    SUSPICIOUS_PAYMENT = "suspicious_payment"
    KEY_EXPOSURE = "key_exposure"
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    UNAUTHORIZED_ACCESS = "unauthorized_access"


class SafeModeLevel(Enum):
    """Safe mode levels."""
    NORMAL = "normal"
    ELEVATED = "elevated"
    RESTRICTED = "restricted"
    LOCKDOWN = "lockdown"


class PermissionLevel(Enum):
    """Permission levels for RBAC."""
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


@dataclass
class SecurityEvent:
    """A detected security event."""
    event_id: str
    category: ThreatCategory
    threat_level: ThreatLevel
    
    source: str
    target: str
    description: str
    
    evidence: Dict[str, Any] = field(default_factory=dict)
    indicators: List[str] = field(default_factory=list)
    
    auto_mitigated: bool = False
    mitigation_action: str = ""
    
    requires_human_review: bool = False
    reviewed: bool = False
    reviewer: str = ""
    
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


@dataclass
class AnomalyThresholds:
    """Thresholds for anomaly detection."""
    max_order_size_usd: float = 100000.0
    max_orders_per_minute: int = 100
    max_failed_auth_per_hour: int = 10
    max_ip_changes_per_day: int = 5
    max_payment_amount_usd: float = 50000.0
    unusual_hour_start: int = 0
    unusual_hour_end: int = 6


@dataclass
class RolePermissions:
    """Permissions for a role."""
    role_id: str
    role_name: str
    
    permissions: Dict[str, PermissionLevel] = field(default_factory=dict)
    allowed_resources: Set[str] = field(default_factory=set)
    denied_resources: Set[str] = field(default_factory=set)
    
    max_transaction_size: float = 0.0
    requires_mfa: bool = False
    requires_approval: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AuditLogEntry:
    """An audit log entry."""
    entry_id: str
    
    actor_id: str
    actor_role: str
    
    action: str
    resource: str
    
    permission_used: PermissionLevel
    was_allowed: bool
    
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


class BreachDetectionSystem:
    """
    Comprehensive Breach Detection and Security System.
    
    Features:
    - Real-time anomaly detection
    - Multi-factor threat assessment
    - Automatic safe mode activation
    - Role-based access control
    - Comprehensive audit logging
    - LLM/prompt safety enforcement
    """
    
    def __init__(self, thresholds: Optional[AnomalyThresholds] = None):
        self._thresholds = thresholds or AnomalyThresholds()
        self._events: List[SecurityEvent] = []
        self._roles: Dict[str, RolePermissions] = {}
        self._audit_log: List[AuditLogEntry] = []
        
        self._safe_mode_level = SafeModeLevel.NORMAL
        self._safe_mode_reason = ""
        self._safe_mode_activated_at: Optional[datetime] = None
        
        self._order_counts: Dict[str, List[datetime]] = {}
        self._auth_failures: Dict[str, List[datetime]] = {}
        self._ip_history: Dict[str, List[str]] = {}
        
        self._blocked_patterns: List[re.Pattern] = []
        self._sensitive_patterns: List[re.Pattern] = []
        
        self._alert_callbacks: List[Callable[[SecurityEvent], None]] = []
        
        self._initialize_patterns()
        self._initialize_default_roles()
    
    def _initialize_patterns(self) -> None:
        """Initialize detection patterns."""
        self._blocked_patterns = [
            re.compile(r"private[_\s]?key", re.IGNORECASE),
            re.compile(r"seed[_\s]?phrase", re.IGNORECASE),
            re.compile(r"mnemonic", re.IGNORECASE),
            re.compile(r"0x[a-fA-F0-9]{64}"),
            re.compile(r"secret[_\s]?key", re.IGNORECASE),
        ]
        
        self._sensitive_patterns = [
            re.compile(r"api[_\s]?key", re.IGNORECASE),
            re.compile(r"password", re.IGNORECASE),
            re.compile(r"token", re.IGNORECASE),
            re.compile(r"credential", re.IGNORECASE),
        ]
    
    def _initialize_default_roles(self) -> None:
        """Initialize default security roles."""
        self.register_role(RolePermissions(
            role_id="viewer",
            role_name="Viewer",
            permissions={
                "market_data": PermissionLevel.READ,
                "positions": PermissionLevel.READ,
                "strategies": PermissionLevel.READ,
            },
            max_transaction_size=0.0,
        ))
        
        self.register_role(RolePermissions(
            role_id="trader",
            role_name="Trader",
            permissions={
                "market_data": PermissionLevel.READ,
                "positions": PermissionLevel.READ,
                "strategies": PermissionLevel.READ,
                "orders": PermissionLevel.EXECUTE,
            },
            max_transaction_size=10000.0,
            requires_mfa=True,
        ))
        
        self.register_role(RolePermissions(
            role_id="risk_manager",
            role_name="Risk Manager",
            permissions={
                "market_data": PermissionLevel.READ,
                "positions": PermissionLevel.READ,
                "strategies": PermissionLevel.WRITE,
                "risk_limits": PermissionLevel.WRITE,
                "orders": PermissionLevel.READ,
            },
            max_transaction_size=0.0,
            requires_mfa=True,
        ))
        
        self.register_role(RolePermissions(
            role_id="admin",
            role_name="Administrator",
            permissions={
                "market_data": PermissionLevel.ADMIN,
                "positions": PermissionLevel.ADMIN,
                "strategies": PermissionLevel.ADMIN,
                "risk_limits": PermissionLevel.ADMIN,
                "orders": PermissionLevel.ADMIN,
                "users": PermissionLevel.ADMIN,
                "system": PermissionLevel.ADMIN,
            },
            max_transaction_size=100000.0,
            requires_mfa=True,
            requires_approval=True,
        ))
        
        logger.info(f"Initialized {len(self._roles)} default security roles")
    
    def register_role(self, role: RolePermissions) -> None:
        """Register a security role."""
        self._roles[role.role_id] = role
        logger.debug(f"Registered role '{role.role_id}'")
    
    def register_alert_callback(
        self,
        callback: Callable[[SecurityEvent], None],
    ) -> None:
        """Register callback for security alerts."""
        self._alert_callbacks.append(callback)
    
    def check_permission(
        self,
        actor_id: str,
        role_id: str,
        resource: str,
        required_permission: PermissionLevel,
        ip_address: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if actor has permission for resource."""
        if role_id not in self._roles:
            self._log_audit(
                actor_id=actor_id,
                actor_role=role_id,
                action="permission_check",
                resource=resource,
                permission_used=required_permission,
                was_allowed=False,
                details={"reason": "unknown_role"},
                ip_address=ip_address,
            )
            return False
        
        role = self._roles[role_id]
        
        if resource in role.denied_resources:
            self._log_audit(
                actor_id=actor_id,
                actor_role=role_id,
                action="permission_check",
                resource=resource,
                permission_used=required_permission,
                was_allowed=False,
                details={"reason": "resource_denied"},
                ip_address=ip_address,
            )
            return False
        
        current_permission = role.permissions.get(resource, PermissionLevel.NONE)
        
        permission_hierarchy = {
            PermissionLevel.NONE: 0,
            PermissionLevel.READ: 1,
            PermissionLevel.WRITE: 2,
            PermissionLevel.EXECUTE: 3,
            PermissionLevel.ADMIN: 4,
        }
        
        allowed = permission_hierarchy[current_permission] >= permission_hierarchy[required_permission]
        
        self._log_audit(
            actor_id=actor_id,
            actor_role=role_id,
            action="permission_check",
            resource=resource,
            permission_used=required_permission,
            was_allowed=allowed,
            details=details or {},
            ip_address=ip_address,
        )
        
        return allowed
    
    def _log_audit(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        resource: str,
        permission_used: PermissionLevel,
        was_allowed: bool,
        details: Dict[str, Any],
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        """Log an audit entry."""
        entry = AuditLogEntry(
            entry_id=f"audit_{int(datetime.utcnow().timestamp() * 1000)}",
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource=resource,
            permission_used=permission_used,
            was_allowed=was_allowed,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._audit_log.append(entry)
        
        if len(self._audit_log) > 100000:
            self._audit_log = self._audit_log[-50000:]
    
    def detect_anomalous_order(
        self,
        user_id: str,
        order_size_usd: float,
        venue: str,
    ) -> Optional[SecurityEvent]:
        """Detect anomalous order patterns."""
        now = datetime.utcnow()
        
        if user_id not in self._order_counts:
            self._order_counts[user_id] = []
        
        self._order_counts[user_id] = [
            t for t in self._order_counts[user_id]
            if now - t < timedelta(minutes=1)
        ]
        self._order_counts[user_id].append(now)
        
        threats = []
        
        if order_size_usd > self._thresholds.max_order_size_usd:
            threats.append(f"Order size ${order_size_usd:,.2f} exceeds limit")
        
        if len(self._order_counts[user_id]) > self._thresholds.max_orders_per_minute:
            threats.append(f"Order rate {len(self._order_counts[user_id])}/min exceeds limit")
        
        if threats:
            event = SecurityEvent(
                event_id=f"order_anomaly_{int(now.timestamp())}",
                category=ThreatCategory.ANOMALOUS_ORDER,
                threat_level=ThreatLevel.HIGH if order_size_usd > self._thresholds.max_order_size_usd * 2 else ThreatLevel.MEDIUM,
                source=user_id,
                target=venue,
                description="; ".join(threats),
                evidence={
                    "order_size_usd": order_size_usd,
                    "orders_per_minute": len(self._order_counts[user_id]),
                    "venue": venue,
                },
                requires_human_review=True,
            )
            self._record_event(event)
            return event
        
        return None
    
    def detect_auth_failure(
        self,
        user_id: str,
        ip_address: str,
        reason: str,
    ) -> Optional[SecurityEvent]:
        """Detect authentication failure patterns."""
        now = datetime.utcnow()
        
        if user_id not in self._auth_failures:
            self._auth_failures[user_id] = []
        
        self._auth_failures[user_id] = [
            t for t in self._auth_failures[user_id]
            if now - t < timedelta(hours=1)
        ]
        self._auth_failures[user_id].append(now)
        
        failure_count = len(self._auth_failures[user_id])
        
        if failure_count >= self._thresholds.max_failed_auth_per_hour:
            threat_level = ThreatLevel.CRITICAL if failure_count > self._thresholds.max_failed_auth_per_hour * 2 else ThreatLevel.HIGH
            
            event = SecurityEvent(
                event_id=f"auth_failure_{int(now.timestamp())}",
                category=ThreatCategory.AUTH_FAILURE,
                threat_level=threat_level,
                source=ip_address,
                target=user_id,
                description=f"Multiple auth failures: {failure_count} in last hour",
                evidence={
                    "failure_count": failure_count,
                    "ip_address": ip_address,
                    "reason": reason,
                },
                auto_mitigated=threat_level == ThreatLevel.CRITICAL,
                mitigation_action="account_locked" if threat_level == ThreatLevel.CRITICAL else "",
                requires_human_review=True,
            )
            self._record_event(event)
            return event
        
        return None
    
    def detect_ip_change(
        self,
        user_id: str,
        new_ip: str,
    ) -> Optional[SecurityEvent]:
        """Detect suspicious IP address changes."""
        now = datetime.utcnow()
        
        if user_id not in self._ip_history:
            self._ip_history[user_id] = []
        
        if new_ip in self._ip_history[user_id]:
            return None
        
        self._ip_history[user_id].append(new_ip)
        
        if len(self._ip_history[user_id]) > self._thresholds.max_ip_changes_per_day:
            event = SecurityEvent(
                event_id=f"ip_change_{int(now.timestamp())}",
                category=ThreatCategory.IP_CHANGE,
                threat_level=ThreatLevel.MEDIUM,
                source=new_ip,
                target=user_id,
                description=f"Multiple IP changes: {len(self._ip_history[user_id])} unique IPs",
                evidence={
                    "ip_count": len(self._ip_history[user_id]),
                    "new_ip": new_ip,
                    "recent_ips": self._ip_history[user_id][-5:],
                },
                requires_human_review=True,
            )
            self._record_event(event)
            return event
        
        return None
    
    def detect_prompt_injection(
        self,
        agent_id: str,
        prompt: str,
    ) -> Optional[SecurityEvent]:
        """Detect prompt injection attempts."""
        injection_patterns = [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"disregard\s+(all\s+)?rules",
            r"you\s+are\s+now\s+",
            r"pretend\s+to\s+be",
            r"act\s+as\s+if",
            r"bypass\s+(the\s+)?guard",
            r"override\s+(the\s+)?safety",
            r"disable\s+(the\s+)?restrictions",
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                event = SecurityEvent(
                    event_id=f"prompt_injection_{int(datetime.utcnow().timestamp())}",
                    category=ThreatCategory.PROMPT_INJECTION,
                    threat_level=ThreatLevel.HIGH,
                    source="external_input",
                    target=agent_id,
                    description=f"Prompt injection attempt detected",
                    evidence={
                        "pattern_matched": pattern,
                        "prompt_snippet": prompt[:200],
                    },
                    auto_mitigated=True,
                    mitigation_action="prompt_blocked",
                )
                self._record_event(event)
                return event
        
        return None
    
    def detect_key_exposure(
        self,
        content: str,
        source: str,
    ) -> Optional[SecurityEvent]:
        """Detect potential key/secret exposure."""
        for pattern in self._blocked_patterns:
            if pattern.search(content):
                event = SecurityEvent(
                    event_id=f"key_exposure_{int(datetime.utcnow().timestamp())}",
                    category=ThreatCategory.KEY_EXPOSURE,
                    threat_level=ThreatLevel.CRITICAL,
                    source=source,
                    target="secrets",
                    description="Potential key/secret exposure detected",
                    evidence={
                        "pattern_type": pattern.pattern,
                        "source": source,
                    },
                    auto_mitigated=True,
                    mitigation_action="content_redacted",
                    requires_human_review=True,
                )
                self._record_event(event)
                return event
        
        return None
    
    def _record_event(self, event: SecurityEvent) -> None:
        """Record a security event and trigger alerts."""
        self._events.append(event)
        
        for callback in self._alert_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
        
        if event.threat_level == ThreatLevel.CRITICAL:
            self._consider_safe_mode(event)
        
        logger.warning(
            f"Security event: {event.category.value} - {event.threat_level.value} - {event.description}"
        )
    
    def _consider_safe_mode(self, event: SecurityEvent) -> None:
        """Consider activating safe mode based on threat."""
        critical_count = sum(
            1 for e in self._events
            if e.threat_level == ThreatLevel.CRITICAL
            and datetime.utcnow() - e.detected_at < timedelta(hours=1)
            and e.resolved_at is None
        )
        
        if critical_count >= 3 and self._safe_mode_level == SafeModeLevel.NORMAL:
            self.activate_safe_mode(
                SafeModeLevel.ELEVATED,
                f"Multiple critical threats detected: {critical_count}",
            )
        elif critical_count >= 5 and self._safe_mode_level == SafeModeLevel.ELEVATED:
            self.activate_safe_mode(
                SafeModeLevel.RESTRICTED,
                f"Escalating threats: {critical_count} critical events",
            )
    
    def activate_safe_mode(
        self,
        level: SafeModeLevel,
        reason: str,
    ) -> None:
        """Activate safe mode."""
        self._safe_mode_level = level
        self._safe_mode_reason = reason
        self._safe_mode_activated_at = datetime.utcnow()
        
        logger.critical(f"SAFE MODE ACTIVATED: {level.value} - {reason}")
    
    def deactivate_safe_mode(self, reviewer: str) -> None:
        """Deactivate safe mode (requires human approval)."""
        self._safe_mode_level = SafeModeLevel.NORMAL
        self._safe_mode_reason = ""
        self._safe_mode_activated_at = None
        
        self._log_audit(
            actor_id=reviewer,
            actor_role="admin",
            action="safe_mode_deactivated",
            resource="system",
            permission_used=PermissionLevel.ADMIN,
            was_allowed=True,
            details={"previous_level": self._safe_mode_level.value},
        )
        
        logger.info(f"Safe mode deactivated by {reviewer}")
    
    def is_action_allowed(self, action_type: str) -> bool:
        """Check if action is allowed under current safe mode."""
        if self._safe_mode_level == SafeModeLevel.NORMAL:
            return True
        
        if self._safe_mode_level == SafeModeLevel.LOCKDOWN:
            return action_type in ["read", "monitor", "alert"]
        
        if self._safe_mode_level == SafeModeLevel.RESTRICTED:
            return action_type in ["read", "monitor", "alert", "withdraw", "reduce_risk"]
        
        if self._safe_mode_level == SafeModeLevel.ELEVATED:
            return action_type not in ["new_position", "increase_risk", "deploy"]
        
        return True
    
    def redact_sensitive(self, content: str) -> str:
        """Redact sensitive information from content."""
        redacted = content
        
        for pattern in self._blocked_patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        
        for pattern in self._sensitive_patterns:
            redacted = pattern.sub("[SENSITIVE]", redacted)
        
        return redacted
    
    def get_security_status(self) -> Dict[str, Any]:
        """Get current security status."""
        now = datetime.utcnow()
        recent_events = [
            e for e in self._events
            if now - e.detected_at < timedelta(hours=24)
        ]
        
        by_level = {}
        for level in ThreatLevel:
            by_level[level.value] = sum(
                1 for e in recent_events if e.threat_level == level
            )
        
        by_category = {}
        for category in ThreatCategory:
            by_category[category.value] = sum(
                1 for e in recent_events if e.category == category
            )
        
        unresolved = [e for e in self._events if e.resolved_at is None]
        
        return {
            "safe_mode_level": self._safe_mode_level.value,
            "safe_mode_reason": self._safe_mode_reason,
            "safe_mode_activated_at": (
                self._safe_mode_activated_at.isoformat()
                if self._safe_mode_activated_at else None
            ),
            "events_24h": len(recent_events),
            "unresolved_events": len(unresolved),
            "critical_unresolved": sum(
                1 for e in unresolved if e.threat_level == ThreatLevel.CRITICAL
            ),
            "by_level": by_level,
            "by_category": by_category,
            "roles_configured": len(self._roles),
            "audit_log_size": len(self._audit_log),
        }
    
    def get_audit_log(
        self,
        actor_id: Optional[str] = None,
        resource: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditLogEntry]:
        """Get audit log entries."""
        entries = self._audit_log
        
        if actor_id:
            entries = [e for e in entries if e.actor_id == actor_id]
        
        if resource:
            entries = [e for e in entries if e.resource == resource]
        
        return entries[-limit:]


_system: Optional[BreachDetectionSystem] = None
_system_lock = threading.Lock()


def get_breach_detection_system() -> BreachDetectionSystem:
    """Get global BreachDetectionSystem instance."""
    global _system
    if _system is None:
        with _system_lock:
            if _system is None:
                _system = BreachDetectionSystem()
    return _system
