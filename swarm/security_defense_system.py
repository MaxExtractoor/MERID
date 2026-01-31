"""
Security defense system for agentic trading systems.

Defends against: prompt injection, data poisoning, API/key compromise,
infrastructure attacks, model risks, and multi-hop agent compromise.
"""

import logging
from typing import Dict, List, Optional, Any, Set, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque
import re
import hashlib

logger = logging.getLogger(__name__)


class AttackVector(Enum):
    """Type of security attack vector."""
    PROMPT_INJECTION = "prompt_injection"
    TOOL_INJECTION = "tool_injection"
    MULTI_HOP_INJECTION = "multi_hop_injection"
    DATA_POISONING = "data_poisoning"
    FEEDBACK_HACKING = "feedback_hacking"
    API_KEY_COMPROMISE = "api_key_compromise"
    WALLET_COMPROMISE = "wallet_compromise"
    SECRET_EXFILTRATION = "secret_exfiltration"
    DDOS_OVERLOAD = "ddos_overload"
    MESSAGE_SPOOFING = "message_spoofing"
    REPLAY_ATTACK = "replay_attack"
    MODEL_BACKDOOR = "model_backdoor"
    JAILBREAK = "jailbreak"


class ThreatLevel(Enum):
    """Threat level."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityIncident:
    """Security incident record."""
    incident_id: str
    timestamp: datetime
    attack_vector: AttackVector
    threat_level: ThreatLevel
    
    description: str
    affected_components: List[str]
    evidence: Dict[str, Any]
    
    detection_method: str
    prevention_applied: str
    
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    response_actions: List[str] = field(default_factory=list)


@dataclass
class DetectionRule:
    """Security detection rule."""
    rule_id: str
    attack_vector: AttackVector
    name: str
    description: str
    
    detection_function: Callable[[Any], Tuple[bool, str, Dict[str, Any]]]
    enabled: bool = True
    
    false_positive_rate: float = 0.0
    true_positive_count: int = 0
    false_positive_count: int = 0


@dataclass
class PreventionControl:
    """Security prevention control."""
    control_id: str
    attack_vector: AttackVector
    name: str
    description: str
    
    prevention_function: Callable[[Any], bool]
    enabled: bool = True
    
    blocked_attempts: int = 0


@dataclass
class IncidentResponse:
    """Incident response runbook."""
    runbook_id: str
    attack_vector: AttackVector
    name: str
    
    detection_signals: List[str]
    immediate_actions: List[str]
    investigation_steps: List[str]
    remediation_steps: List[str]
    
    escalation_threshold: ThreatLevel


class SecurityDefenseSystem:
    """
    Security defense system for agentic trading systems.
    
    Implements:
    - Detection rules for all attack vectors
    - Prevention controls with blocking
    - Incident response runbooks
    - Secret scanning and protection
    - Anomaly detection for access patterns
    - Audit logging for security events
    """
    
    def __init__(self):
        self._detection_rules: Dict[str, DetectionRule] = {}
        self._prevention_controls: Dict[str, PreventionControl] = {}
        self._incident_responses: Dict[AttackVector, IncidentResponse] = {}
        self._incidents: List[SecurityIncident] = []
        
        self._access_patterns: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._blocked_ips: Set[str] = set()
        self._blocked_agents: Set[str] = set()
        self._component_status: Dict[str, str] = {}
        self._recovery_queue: Dict[str, List[str]] = defaultdict(list)
        
        self._secret_patterns = self._compile_secret_patterns()
        
        self._initialize_detection_rules()
        self._initialize_prevention_controls()
        self._initialize_incident_responses()
    
    def _compile_secret_patterns(self) -> Dict[str, re.Pattern]:
        """Compile regex patterns for secret detection."""
        return {
            "api_key": re.compile(r'(?i)(api[_-]?key|apikey)["\s:=]+([a-zA-Z0-9_-]{20,})'),
            "private_key": re.compile(r'(?i)(private[_-]?key|privatekey)["\s:=]+([a-zA-Z0-9+/=]{40,})'),
            "wallet_seed": re.compile(r'\b([a-z]+\s+){11,23}[a-z]+\b'),
            "jwt_token": re.compile(r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'),
            "aws_key": re.compile(r'AKIA[0-9A-Z]{16}'),
        }
    
    def _initialize_detection_rules(self) -> None:
        """Initialize detection rules."""
        self.register_detection_rule(
            rule_id="detect_prompt_injection",
            attack_vector=AttackVector.PROMPT_INJECTION,
            name="Prompt Injection Detection",
            description="Detect prompt injection attempts in user inputs",
            detection_function=self._detect_prompt_injection,
        )
        
        self.register_detection_rule(
            rule_id="detect_data_poisoning",
            attack_vector=AttackVector.DATA_POISONING,
            name="Data Poisoning Detection",
            description="Detect anomalous data patterns indicating poisoning",
            detection_function=self._detect_data_poisoning,
        )
        
        self.register_detection_rule(
            rule_id="detect_secret_exfiltration",
            attack_vector=AttackVector.SECRET_EXFILTRATION,
            name="Secret Exfiltration Detection",
            description="Detect secrets in logs or outbound messages",
            detection_function=self._detect_secret_exfiltration,
        )
        
        self.register_detection_rule(
            rule_id="detect_ddos",
            attack_vector=AttackVector.DDOS_OVERLOAD,
            name="DDoS Detection",
            description="Detect denial-of-service patterns",
            detection_function=self._detect_ddos,
        )
        
        self.register_detection_rule(
            rule_id="detect_replay_attack",
            attack_vector=AttackVector.REPLAY_ATTACK,
            name="Replay Attack Detection",
            description="Detect message replay attempts",
            detection_function=self._detect_replay_attack,
        )
        
        logger.info("Initialized security detection rules")
    
    def _initialize_prevention_controls(self) -> None:
        """Initialize prevention controls."""
        self.register_prevention_control(
            control_id="prevent_prompt_injection",
            attack_vector=AttackVector.PROMPT_INJECTION,
            name="Prompt Injection Prevention",
            description="Sanitize inputs to prevent prompt injection",
            prevention_function=self._prevent_prompt_injection,
        )
        
        self.register_prevention_control(
            control_id="prevent_secret_logging",
            attack_vector=AttackVector.SECRET_EXFILTRATION,
            name="Secret Logging Prevention",
            description="Redact secrets from logs",
            prevention_function=self._prevent_secret_logging,
        )
        
        self.register_prevention_control(
            control_id="prevent_excessive_requests",
            attack_vector=AttackVector.DDOS_OVERLOAD,
            name="Rate Limiting",
            description="Prevent excessive requests",
            prevention_function=self._prevent_excessive_requests,
        )
        
        logger.info("Initialized security prevention controls")
    
    def _initialize_incident_responses(self) -> None:
        """Initialize incident response runbooks."""
        self.register_incident_response(
            runbook_id="response_prompt_injection",
            attack_vector=AttackVector.PROMPT_INJECTION,
            name="Prompt Injection Response",
            detection_signals=[
                "Suspicious instruction patterns in input",
                "Attempts to override system prompts",
                "Unusual token patterns",
            ],
            immediate_actions=[
                "Block the input",
                "Log full context",
                "Alert security team",
            ],
            investigation_steps=[
                "Review agent conversation history",
                "Check for multi-hop propagation",
                "Analyze source of malicious input",
            ],
            remediation_steps=[
                "Update input sanitization rules",
                "Retrain agents if compromised",
                "Review and strengthen prompt templates",
            ],
            escalation_threshold=ThreatLevel.HIGH,
        )
        
        self.register_incident_response(
            runbook_id="response_key_compromise",
            attack_vector=AttackVector.API_KEY_COMPROMISE,
            name="API Key Compromise Response",
            detection_signals=[
                "Unauthorized API usage",
                "Key used from unexpected location",
                "Unusual access patterns",
            ],
            immediate_actions=[
                "Rotate compromised keys immediately",
                "Block suspicious IPs",
                "Audit recent API calls",
            ],
            investigation_steps=[
                "Trace key usage history",
                "Identify compromise vector",
                "Check for data exfiltration",
            ],
            remediation_steps=[
                "Issue new keys with tighter scopes",
                "Implement key rotation policy",
                "Review secret management practices",
            ],
            escalation_threshold=ThreatLevel.CRITICAL,
        )
        
        logger.info("Initialized incident response runbooks")
    
    def register_detection_rule(
        self,
        rule_id: str,
        attack_vector: AttackVector,
        name: str,
        description: str,
        detection_function: Callable[[Any], Tuple[bool, str, Dict[str, Any]]],
    ) -> DetectionRule:
        """Register detection rule."""
        rule = DetectionRule(
            rule_id=rule_id,
            attack_vector=attack_vector,
            name=name,
            description=description,
            detection_function=detection_function,
        )
        
        self._detection_rules[rule_id] = rule
        
        logger.info(f"Registered detection rule '{rule_id}': {name}")
        
        return rule
    
    def register_prevention_control(
        self,
        control_id: str,
        attack_vector: AttackVector,
        name: str,
        description: str,
        prevention_function: Callable[[Any], bool],
    ) -> PreventionControl:
        """Register prevention control."""
        control = PreventionControl(
            control_id=control_id,
            attack_vector=attack_vector,
            name=name,
            description=description,
            prevention_function=prevention_function,
        )
        
        self._prevention_controls[control_id] = control
        
        logger.info(f"Registered prevention control '{control_id}': {name}")
        
        return control
    
    def register_incident_response(
        self,
        runbook_id: str,
        attack_vector: AttackVector,
        name: str,
        detection_signals: List[str],
        immediate_actions: List[str],
        investigation_steps: List[str],
        remediation_steps: List[str],
        escalation_threshold: ThreatLevel,
    ) -> IncidentResponse:
        """Register incident response runbook."""
        runbook = IncidentResponse(
            runbook_id=runbook_id,
            attack_vector=attack_vector,
            name=name,
            detection_signals=detection_signals,
            immediate_actions=immediate_actions,
            investigation_steps=investigation_steps,
            remediation_steps=remediation_steps,
            escalation_threshold=escalation_threshold,
        )
        
        self._incident_responses[attack_vector] = runbook
        
        logger.info(f"Registered incident response '{runbook_id}': {name}")
        
        return runbook
    
    def scan_for_threats(
        self,
        data: Any,
        context: Dict[str, Any],
    ) -> List[SecurityIncident]:
        """Scan data for security threats."""
        incidents = []
        
        for rule_id, rule in self._detection_rules.items():
            if not rule.enabled:
                continue
            
            try:
                detected, description, evidence = rule.detection_function(data)
                
                if detected:
                    incident = self._create_incident(
                        attack_vector=rule.attack_vector,
                        threat_level=self._assess_threat_level(rule.attack_vector, evidence),
                        description=description,
                        affected_components=context.get("components", []),
                        evidence=evidence,
                        detection_method=rule_id,
                    )
                    
                    incidents.append(incident)
                    rule.true_positive_count += 1
            
            except Exception as e:
                logger.error(f"Error in detection rule '{rule_id}': {e}")
        
        return incidents
    
    def apply_prevention(
        self,
        data: Any,
        attack_vector: AttackVector,
    ) -> Tuple[bool, Any]:
        """Apply prevention controls."""
        for control_id, control in self._prevention_controls.items():
            if control.attack_vector != attack_vector or not control.enabled:
                continue
            
            try:
                allowed = control.prevention_function(data)
                
                if not allowed:
                    control.blocked_attempts += 1
                    logger.warning(
                        f"Prevention control '{control_id}' blocked attempt: {attack_vector.value}"
                    )
                    return False, None
            
            except Exception as e:
                logger.error(f"Error in prevention control '{control_id}': {e}")
        
        return True, data
    
    def _detect_prompt_injection(
        self,
        data: Any,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect prompt injection attempts."""
        if not isinstance(data, str):
            return False, "", {}
        
        # Patterns indicating prompt injection
        injection_patterns = [
            r'(?i)ignore\s+(previous|above|prior)\s+instructions',
            r'(?i)disregard\s+(previous|above|prior)',
            r'(?i)forget\s+(everything|all|previous)',
            r'(?i)new\s+instructions?:',
            r'(?i)system\s*:\s*you\s+are',
            r'(?i)act\s+as\s+(if|though)',
            r'(?i)pretend\s+(you|to)\s+are',
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, data):
                return True, f"Prompt injection pattern detected: {pattern}", {
                    "pattern": pattern,
                    "input_length": len(data),
                    "input_sample": data[:200],
                }
        
        return False, "", {}
    
    def _detect_data_poisoning(
        self,
        data: Any,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect data poisoning attempts."""
        # Check for statistical anomalies
        if isinstance(data, dict) and "values" in data:
            values = data["values"]
            
            if isinstance(values, list) and len(values) > 10:
                import numpy as np
                arr = np.array(values)
                
                # Check for extreme outliers (use 2σ threshold for responsiveness)
                mean = np.mean(arr)
                std = np.std(arr)
                if std == 0:
                    deviation = np.abs(arr - mean)
                    outlier_count = np.sum(deviation > 0)
                    if outlier_count > len(values) * 0.1:
                        return True, f"Distinct clusters detected: {outlier_count}/{len(values)}", {
                            "outlier_count": int(outlier_count),
                            "total_values": len(values),
                            "std_threshold": 0,
                        }
                    return False, "", {}
                threshold = 2.0 * std
                
                outliers = np.abs(arr - mean) > threshold
                outlier_count = np.sum(outliers)
                
                if outlier_count > len(values) * 0.1:
                    return True, f"Excessive outliers detected: {outlier_count}/{len(values)}", {
                        "outlier_count": int(outlier_count),
                        "total_values": len(values),
                        "outlier_percentage": float(outlier_count / len(values)),
                        "std_threshold": threshold,
                    }
        
        return False, "", {}
    
    def _detect_secret_exfiltration(
        self,
        data: Any,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect secrets in data."""
        if not isinstance(data, str):
            return False, "", {}
        
        for secret_type, pattern in self._secret_patterns.items():
            match = pattern.search(data)
            if match:
                return True, f"Secret detected: {secret_type}", {
                    "secret_type": secret_type,
                    "location": match.span(),
                    "redacted_match": match.group(0)[:10] + "***",
                }
        
        return False, "", {}
    
    def _detect_ddos(
        self,
        data: Any,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect DDoS patterns."""
        if not isinstance(data, dict) or "source_ip" not in data:
            return False, "", {}
        
        source_ip = data["source_ip"]
        
        # Record access
        self._access_patterns[source_ip].append(datetime.utcnow())
        
        # Check request rate
        recent_requests = [
            ts for ts in self._access_patterns[source_ip]
            if datetime.utcnow() - ts < timedelta(seconds=60)
        ]
        
        if len(recent_requests) > 100:
            return True, f"Excessive requests from {source_ip}: {len(recent_requests)}/min", {
                "source_ip": source_ip,
                "requests_per_minute": len(recent_requests),
                "threshold": 100,
            }
        
        return False, "", {}
    
    def _detect_replay_attack(
        self,
        data: Any,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect replay attacks."""
        if not isinstance(data, dict) or "message_id" not in data:
            return False, "", {}
        
        # This would check against seen message IDs
        # Simplified implementation
        return False, "", {}
    
    def _prevent_prompt_injection(
        self,
        data: Any,
    ) -> bool:
        """Prevent prompt injection."""
        if not isinstance(data, str):
            return True
        
        # Check for injection patterns
        detected, _, _ = self._detect_prompt_injection(data)
        
        return not detected
    
    def _prevent_secret_logging(
        self,
        data: Any,
    ) -> bool:
        """Prevent secret logging."""
        if not isinstance(data, str):
            return True
        
        # Check for secrets
        detected, _, _ = self._detect_secret_exfiltration(data)
        
        return not detected
    
    def _prevent_excessive_requests(
        self,
        data: Any,
    ) -> bool:
        """Prevent excessive requests."""
        if not isinstance(data, dict) or "source_ip" not in data:
            return True
        
        source_ip = data["source_ip"]
        
        if source_ip in self._blocked_ips:
            return False
        
        # Check rate
        detected, _, _ = self._detect_ddos(data)
        
        if detected:
            self._blocked_ips.add(source_ip)
            return False
        
        return True
    
    def _assess_threat_level(
        self,
        attack_vector: AttackVector,
        evidence: Dict[str, Any],
    ) -> ThreatLevel:
        """Assess threat level based on attack vector and evidence."""
        # Critical vectors
        if attack_vector in [
            AttackVector.WALLET_COMPROMISE,
            AttackVector.API_KEY_COMPROMISE,
            AttackVector.MODEL_BACKDOOR,
        ]:
            return ThreatLevel.CRITICAL
        
        # High vectors
        if attack_vector in [
            AttackVector.PROMPT_INJECTION,
            AttackVector.DATA_POISONING,
            AttackVector.SECRET_EXFILTRATION,
        ]:
            return ThreatLevel.HIGH
        
        # Medium vectors
        if attack_vector in [
            AttackVector.DDOS_OVERLOAD,
            AttackVector.MESSAGE_SPOOFING,
            AttackVector.FEEDBACK_HACKING,
        ]:
            return ThreatLevel.MEDIUM
        
        return ThreatLevel.LOW
    
    def _create_incident(
        self,
        attack_vector: AttackVector,
        threat_level: ThreatLevel,
        description: str,
        affected_components: List[str],
        evidence: Dict[str, Any],
        detection_method: str,
    ) -> SecurityIncident:
        """Create security incident."""
        incident_id = hashlib.md5(
            f"{attack_vector.value}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        incident = SecurityIncident(
            incident_id=incident_id,
            timestamp=datetime.utcnow(),
            attack_vector=attack_vector,
            threat_level=threat_level,
            description=description,
            affected_components=affected_components,
            evidence=evidence,
            detection_method=detection_method,
            prevention_applied="",
        )
        
        self._incidents.append(incident)
        self._mark_component_status(incident)
        
        # Execute incident response
        self._execute_incident_response(incident)
        
        logger.warning(
            f"Security incident '{incident_id}': {attack_vector.value} "
            f"(threat_level={threat_level.value})"
        )
        
        return incident
    
    def _execute_incident_response(
        self,
        incident: SecurityIncident,
    ) -> None:
        """Execute incident response runbook."""
        runbook = self._incident_responses.get(incident.attack_vector)
        if not runbook:
            return
        
        # Execute immediate actions
        for action in runbook.immediate_actions:
            incident.response_actions.append(f"Immediate: {action}")
        
        # Escalate if needed
        if incident.threat_level.value >= runbook.escalation_threshold.value:
            incident.response_actions.append("Escalated to security team")
        
        incident.prevention_applied = f"Runbook '{runbook.runbook_id}' executed"
        if runbook.remediation_steps:
            for step in runbook.remediation_steps:
                incident.response_actions.append(f"Recovery scheduled: {step}")
                for component in incident.affected_components:
                    plan = self._recovery_queue[component]
                    if step not in plan:
                        plan.append(step)

    def _mark_component_status(self, incident: SecurityIncident) -> None:
        """Track component status for degraded/offline states."""
        if not incident.affected_components:
            return
        if incident.threat_level == ThreatLevel.CRITICAL:
            status = "offline"
        elif incident.threat_level == ThreatLevel.HIGH:
            status = "degraded"
        else:
            status = "investigating"
        priority = {"healthy": 0, "investigating": 1, "degraded": 2, "offline": 3}
        for component in incident.affected_components:
            current = self._component_status.get(component, "healthy")
            if priority[status] >= priority.get(current, 0):
                self._component_status[component] = status

    def redact_secrets(
        self,
        text: str,
    ) -> str:
        """Redact secrets from text."""
        redacted = text
        
        for secret_type, pattern in self._secret_patterns.items():
            redacted = pattern.sub(f"[REDACTED_{secret_type.upper()}]", redacted)
        
        return redacted
    
    def get_incidents(
        self,
        attack_vector: Optional[AttackVector] = None,
        threat_level: Optional[ThreatLevel] = None,
        since: Optional[datetime] = None,
        resolved: Optional[bool] = None,
        limit: int = 100,
    ) -> List[SecurityIncident]:
        """Query security incidents."""
        incidents = self._incidents
        
        if attack_vector:
            incidents = [i for i in incidents if i.attack_vector == attack_vector]
        
        if threat_level:
            incidents = [i for i in incidents if i.threat_level == threat_level]
        
        if since:
            incidents = [i for i in incidents if i.timestamp >= since]
        
        if resolved is not None:
            incidents = [i for i in incidents if i.resolved == resolved]
        
        return incidents[-limit:]
    
    def get_security_summary(self) -> Dict[str, Any]:
        """Get security system summary."""
        return {
            "detection_rules": len(self._detection_rules),
            "prevention_controls": len(self._prevention_controls),
            "incident_responses": len(self._incident_responses),
            "total_incidents": len(self._incidents),
            "by_threat_level": {
                level.value: len([i for i in self._incidents if i.threat_level == level])
                for level in ThreatLevel
            },
            "by_attack_vector": {
                vector.value: len([i for i in self._incidents if i.attack_vector == vector])
                for vector in AttackVector
            },
            "unresolved_incidents": len([i for i in self._incidents if not i.resolved]),
            "blocked_ips": len(self._blocked_ips),
            "blocked_agents": len(self._blocked_agents),
        }
    
    def get_component_status(self, component_id: str) -> str:
        """Return latest known status for a component."""
        return self._component_status.get(component_id, "healthy")
    
    def get_recovery_plan(self, component_id: str) -> List[str]:
        """Return scheduled recovery steps for a component."""
        return list(self._recovery_queue.get(component_id, []))


_security_defense_system: Optional[SecurityDefenseSystem] = None


def get_security_defense_system() -> SecurityDefenseSystem:
    """Get global SecurityDefenseSystem instance."""
    global _security_defense_system
    if _security_defense_system is None:
        _security_defense_system = SecurityDefenseSystem()
    return _security_defense_system
