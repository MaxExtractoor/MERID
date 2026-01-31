"""
Exfiltration defense and monitoring system for MERID.

Implements:
- SIEM integration for log aggregation
- DLP (Data Loss Prevention) rules
- Network traffic analysis
- Behavioral anomaly detection
- Real-time alerting and response
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class LogSource(Enum):
    """Log source type."""
    APPLICATION = "application"
    API = "api"
    FIREWALL = "firewall"
    WAF = "waf"
    HSM = "hsm"
    DATABASE = "database"
    BLOCKCHAIN = "blockchain"


class AlertSeverity(Enum):
    """Alert severity."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResponseAction(Enum):
    """Automated response action."""
    LOG_ONLY = "log_only"
    ALERT = "alert"
    BLOCK = "block"
    RATE_LIMIT = "rate_limit"
    CIRCUIT_BREAKER = "circuit_breaker"
    HSM_LOCKDOWN = "hsm_lockdown"


@dataclass
class LogEvent:
    """Log event."""
    event_id: str
    source: LogSource
    
    # Details
    event_type: str
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    
    # Data
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Classification
    suspicious: bool = False
    severity: AlertSeverity = AlertSeverity.INFO
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DLPRule:
    """Data Loss Prevention rule."""
    rule_id: str
    rule_name: str
    
    # Pattern
    pattern_type: str  # regex, keyword, file_type
    pattern: str
    
    # Scope
    applies_to: List[str] = field(default_factory=list)  # api, storage, export
    
    # Action
    action: ResponseAction = ResponseAction.ALERT
    
    # Status
    enabled: bool = True
    violations: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CorrelationRule:
    """SIEM correlation rule."""
    rule_id: str
    rule_name: str
    
    # Conditions
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    time_window_seconds: int = 300  # 5 minutes
    
    # Threshold
    min_occurrences: int = 1
    
    # Response
    severity: AlertSeverity = AlertSeverity.MEDIUM
    action: ResponseAction = ResponseAction.ALERT
    
    # Status
    enabled: bool = True
    triggered_count: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BehavioralProfile:
    """User/entity behavioral profile."""
    entity_id: str
    entity_type: str  # user, agent, operator
    
    # Normal behavior baselines
    typical_withdrawal_amount: Decimal = Decimal("0")
    typical_api_calls_per_hour: int = 0
    typical_login_hours: Set[int] = field(default_factory=set)
    typical_source_ips: Set[str] = field(default_factory=set)
    
    # Anomaly detection
    anomaly_score: float = 0.0  # 0.0 (normal) to 1.0 (highly anomalous)
    
    # History
    last_updated: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecurityIncident:
    """Security incident."""
    incident_id: str
    
    # Classification
    incident_type: str
    severity: AlertSeverity
    
    # Details
    description: str
    affected_entities: List[str] = field(default_factory=list)
    
    # Evidence
    related_events: List[str] = field(default_factory=list)  # event_ids
    indicators: List[str] = field(default_factory=list)
    
    # Response
    actions_taken: List[str] = field(default_factory=list)
    
    # Status
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NetworkFlow:
    """Network traffic flow."""
    flow_id: str
    
    # Source and destination
    source_ip: str
    destination_ip: str
    destination_port: int
    protocol: str
    
    # Volume
    bytes_sent: int = 0
    bytes_received: int = 0
    
    # Classification
    suspicious: bool = False
    blocked: bool = False
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ExfiltrationDefenseSystem:
    """
    Exfiltration defense and monitoring system.
    
    Implements defense-in-depth:
    - SIEM for log aggregation and correlation
    - DLP for sensitive data protection
    - Network traffic analysis
    - Behavioral anomaly detection
    - Real-time alerting and automated response
    """
    
    def __init__(self):
        self._log_events: List[LogEvent] = []
        self._dlp_rules: Dict[str, DLPRule] = {}
        self._correlation_rules: Dict[str, CorrelationRule] = {}
        self._behavioral_profiles: Dict[str, BehavioralProfile] = {}
        self._incidents: List[SecurityIncident] = []
        self._network_flows: List[NetworkFlow] = []
        
        self._initialize_dlp_rules()
        self._initialize_correlation_rules()
    
    def _initialize_dlp_rules(self) -> None:
        """Initialize DLP rules."""
        
        # Private key detection
        self.add_dlp_rule(
            rule_name="Private Key Export",
            pattern_type="regex",
            pattern=r"(0x[a-fA-F0-9]{64}|[A-Za-z0-9+/]{88}==)",
            applies_to=["api", "storage", "export"],
            action=ResponseAction.BLOCK,
        )
        
        # Seed phrase detection
        self.add_dlp_rule(
            rule_name="Seed Phrase Export",
            pattern_type="keyword",
            pattern="mnemonic|seed phrase|recovery phrase",
            applies_to=["api", "storage", "export"],
            action=ResponseAction.BLOCK,
        )
        
        # Bulk data export
        self.add_dlp_rule(
            rule_name="Bulk User Data Export",
            pattern_type="keyword",
            pattern="export_all_users|bulk_export",
            applies_to=["api"],
            action=ResponseAction.ALERT,
        )
        
        logger.info("Initialized DLP rules")
    
    def _initialize_correlation_rules(self) -> None:
        """Initialize SIEM correlation rules."""
        
        # Suspicious admin activity
        self.add_correlation_rule(
            rule_name="Suspicious Admin Activity",
            conditions=[
                {"event_type": "admin_login", "source": "application"},
                {"event_type": "large_withdrawal", "source": "blockchain"},
            ],
            time_window_seconds=300,
            severity=AlertSeverity.HIGH,
            action=ResponseAction.ALERT,
        )
        
        # Data exfiltration pattern
        self.add_correlation_rule(
            rule_name="Data Exfiltration Pattern",
            conditions=[
                {"event_type": "unusual_outbound_traffic", "source": "firewall"},
                {"event_type": "bulk_export", "source": "api"},
            ],
            time_window_seconds=600,
            severity=AlertSeverity.CRITICAL,
            action=ResponseAction.CIRCUIT_BREAKER,
        )
        
        # HSM compromise attempt
        self.add_correlation_rule(
            rule_name="HSM Compromise Attempt",
            conditions=[
                {"event_type": "hsm_auth_failure", "source": "hsm"},
                {"event_type": "unusual_signing_request", "source": "hsm"},
            ],
            time_window_seconds=180,
            min_occurrences=3,
            severity=AlertSeverity.CRITICAL,
            action=ResponseAction.HSM_LOCKDOWN,
        )
        
        logger.info("Initialized SIEM correlation rules")
    
    def ingest_log_event(
        self,
        source: LogSource,
        event_type: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> LogEvent:
        """Ingest log event into SIEM."""
        event_id = f"event_{int(datetime.utcnow().timestamp())}"
        
        event = LogEvent(
            event_id=event_id,
            source=source,
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            data=data or {},
        )
        
        self._log_events.append(event)
        
        # Check DLP rules
        self._check_dlp_rules(event)
        
        # Check correlation rules
        self._check_correlation_rules(event)
        
        # Update behavioral profile
        if user_id:
            self._update_behavioral_profile(user_id, event)
        
        return event
    
    def add_dlp_rule(
        self,
        rule_name: str,
        pattern_type: str,
        pattern: str,
        applies_to: List[str],
        action: ResponseAction = ResponseAction.ALERT,
    ) -> DLPRule:
        """Add DLP rule."""
        rule_id = f"dlp_{int(datetime.utcnow().timestamp())}"
        
        rule = DLPRule(
            rule_id=rule_id,
            rule_name=rule_name,
            pattern_type=pattern_type,
            pattern=pattern,
            applies_to=applies_to,
            action=action,
        )
        
        self._dlp_rules[rule_id] = rule
        
        logger.info(
            f"Added DLP rule '{rule_id}': {rule_name} "
            f"(action: {action.value})"
        )
        
        return rule
    
    def add_correlation_rule(
        self,
        rule_name: str,
        conditions: List[Dict[str, Any]],
        time_window_seconds: int = 300,
        min_occurrences: int = 1,
        severity: AlertSeverity = AlertSeverity.MEDIUM,
        action: ResponseAction = ResponseAction.ALERT,
    ) -> CorrelationRule:
        """Add SIEM correlation rule."""
        rule_id = f"corr_{int(datetime.utcnow().timestamp())}"
        
        rule = CorrelationRule(
            rule_id=rule_id,
            rule_name=rule_name,
            conditions=conditions,
            time_window_seconds=time_window_seconds,
            min_occurrences=min_occurrences,
            severity=severity,
            action=action,
        )
        
        self._correlation_rules[rule_id] = rule
        
        logger.info(
            f"Added correlation rule '{rule_id}': {rule_name} "
            f"(severity: {severity.value}, action: {action.value})"
        )
        
        return rule
    
    def _check_dlp_rules(self, event: LogEvent) -> None:
        """Check event against DLP rules."""
        for rule in self._dlp_rules.values():
            if not rule.enabled:
                continue
            
            # Check if rule applies to this event
            if event.source.value not in rule.applies_to:
                continue
            
            # Check pattern (simplified)
            event_str = str(event.data)
            
            if rule.pattern_type == "keyword":
                if rule.pattern.lower() in event_str.lower():
                    self._handle_dlp_violation(rule, event)
            elif rule.pattern_type == "regex":
                import re
                if re.search(rule.pattern, event_str):
                    self._handle_dlp_violation(rule, event)
    
    def _handle_dlp_violation(self, rule: DLPRule, event: LogEvent) -> None:
        """Handle DLP rule violation."""
        rule.violations += 1
        
        logger.warning(
            f"DLP violation: {rule.rule_name} "
            f"(event: {event.event_id}, action: {rule.action.value})"
        )
        
        # Create incident
        self._create_incident(
            incident_type="dlp_violation",
            severity=AlertSeverity.HIGH,
            description=f"DLP rule '{rule.rule_name}' violated",
            related_events=[event.event_id],
            actions_taken=[rule.action.value],
        )
        
        # Take action
        if rule.action == ResponseAction.BLOCK:
            event.data["blocked"] = True
    
    def _check_correlation_rules(self, event: LogEvent) -> None:
        """Check event against correlation rules."""
        now = datetime.utcnow()
        
        for rule in self._correlation_rules.values():
            if not rule.enabled:
                continue
            
            # Get recent events within time window
            window_start = now - timedelta(seconds=rule.time_window_seconds)
            recent_events = [
                e for e in self._log_events
                if e.timestamp >= window_start
            ]
            
            # Check if conditions are met
            matched_conditions = 0
            for condition in rule.conditions:
                for recent_event in recent_events:
                    if self._event_matches_condition(recent_event, condition):
                        matched_conditions += 1
                        break
            
            # Trigger if all conditions met
            if matched_conditions >= len(rule.conditions):
                if matched_conditions >= rule.min_occurrences:
                    self._trigger_correlation_rule(rule, recent_events)
    
    def _event_matches_condition(
        self,
        event: LogEvent,
        condition: Dict[str, Any],
    ) -> bool:
        """Check if event matches condition."""
        for key, value in condition.items():
            if key == "event_type" and event.event_type != value:
                return False
            if key == "source" and event.source.value != value:
                return False
        return True
    
    def _trigger_correlation_rule(
        self,
        rule: CorrelationRule,
        related_events: List[LogEvent],
    ) -> None:
        """Trigger correlation rule."""
        rule.triggered_count += 1
        
        logger.error(
            f"Correlation rule triggered: {rule.rule_name} "
            f"(severity: {rule.severity.value}, action: {rule.action.value})"
        )
        
        # Create incident
        self._create_incident(
            incident_type="correlation_match",
            severity=rule.severity,
            description=f"Correlation rule '{rule.rule_name}' triggered",
            related_events=[e.event_id for e in related_events],
            actions_taken=[rule.action.value],
        )
    
    def _update_behavioral_profile(
        self,
        entity_id: str,
        event: LogEvent,
    ) -> None:
        """Update behavioral profile."""
        if entity_id not in self._behavioral_profiles:
            self._behavioral_profiles[entity_id] = BehavioralProfile(
                entity_id=entity_id,
                entity_type="user",
            )
        
        profile = self._behavioral_profiles[entity_id]
        
        # Update baselines
        if event.event_type == "withdrawal":
            amount = Decimal(str(event.data.get("amount", 0)))
            if profile.typical_withdrawal_amount == Decimal("0"):
                profile.typical_withdrawal_amount = amount
            else:
                # Moving average
                profile.typical_withdrawal_amount = (
                    profile.typical_withdrawal_amount * Decimal("0.9") +
                    amount * Decimal("0.1")
                )
        
        if event.ip_address:
            profile.typical_source_ips.add(event.ip_address)
        
        # Calculate anomaly score
        anomaly_score = 0.0
        
        # Check for unusual withdrawal
        if event.event_type == "withdrawal":
            amount = Decimal(str(event.data.get("amount", 0)))
            if amount > profile.typical_withdrawal_amount * Decimal("5"):
                anomaly_score += 0.5
        
        # Check for unusual IP
        if event.ip_address and event.ip_address not in profile.typical_source_ips:
            anomaly_score += 0.3
        
        profile.anomaly_score = anomaly_score
        profile.last_updated = datetime.utcnow()
        
        # Alert on high anomaly
        if anomaly_score > 0.7:
            logger.warning(
                f"High anomaly score for entity '{entity_id}': {anomaly_score:.2f}"
            )
            
            self._create_incident(
                incident_type="behavioral_anomaly",
                severity=AlertSeverity.MEDIUM,
                description=f"Unusual behavior detected for entity '{entity_id}'",
                affected_entities=[entity_id],
                related_events=[event.event_id],
            )
    
    def record_network_flow(
        self,
        source_ip: str,
        destination_ip: str,
        destination_port: int,
        protocol: str,
        bytes_sent: int = 0,
    ) -> NetworkFlow:
        """Record network traffic flow."""
        flow_id = f"flow_{int(datetime.utcnow().timestamp())}"
        
        flow = NetworkFlow(
            flow_id=flow_id,
            source_ip=source_ip,
            destination_ip=destination_ip,
            destination_port=destination_port,
            protocol=protocol,
            bytes_sent=bytes_sent,
        )
        
        # Check for suspicious patterns
        if bytes_sent > 10_000_000:  # 10MB
            flow.suspicious = True
            
            logger.warning(
                f"Large outbound transfer detected: {bytes_sent} bytes "
                f"from {source_ip} to {destination_ip}:{destination_port}"
            )
            
            # Create incident
            self._create_incident(
                incident_type="unusual_outbound_traffic",
                severity=AlertSeverity.HIGH,
                description=f"Large outbound transfer: {bytes_sent} bytes",
                indicators=[f"{source_ip} -> {destination_ip}:{destination_port}"],
            )
        
        self._network_flows.append(flow)
        
        return flow
    
    def _create_incident(
        self,
        incident_type: str,
        severity: AlertSeverity,
        description: str,
        affected_entities: Optional[List[str]] = None,
        related_events: Optional[List[str]] = None,
        indicators: Optional[List[str]] = None,
        actions_taken: Optional[List[str]] = None,
    ) -> SecurityIncident:
        """Create security incident."""
        incident_id = f"incident_{int(datetime.utcnow().timestamp())}"
        
        incident = SecurityIncident(
            incident_id=incident_id,
            incident_type=incident_type,
            severity=severity,
            description=description,
            affected_entities=affected_entities or [],
            related_events=related_events or [],
            indicators=indicators or [],
            actions_taken=actions_taken or [],
        )
        
        self._incidents.append(incident)
        
        logger.error(
            f"Security incident created [{severity.value}]: {incident_type} - {description}"
        )
        
        return incident
    
    def get_active_incidents(self) -> List[SecurityIncident]:
        """Get active (unresolved) incidents."""
        return [i for i in self._incidents if not i.resolved]
    
    def get_security_dashboard(self) -> Dict[str, Any]:
        """Get security monitoring dashboard."""
        now = datetime.utcnow()
        last_hour = now - timedelta(hours=1)
        
        recent_events = [e for e in self._log_events if e.timestamp >= last_hour]
        recent_incidents = [i for i in self._incidents if i.created_at >= last_hour]
        
        return {
            "events": {
                "last_hour": len(recent_events),
                "suspicious": sum(1 for e in recent_events if e.suspicious),
            },
            "dlp": {
                "rules": len(self._dlp_rules),
                "violations_last_hour": sum(
                    1 for rule in self._dlp_rules.values()
                    if rule.violations > 0
                ),
            },
            "correlation": {
                "rules": len(self._correlation_rules),
                "triggered_last_hour": sum(
                    1 for rule in self._correlation_rules.values()
                    if rule.triggered_count > 0
                ),
            },
            "incidents": {
                "total": len(self._incidents),
                "active": len(self.get_active_incidents()),
                "last_hour": len(recent_incidents),
                "by_severity": {
                    severity.value: sum(
                        1 for i in self._incidents
                        if i.severity == severity and not i.resolved
                    )
                    for severity in AlertSeverity
                },
            },
            "behavioral": {
                "profiles": len(self._behavioral_profiles),
                "high_anomaly": sum(
                    1 for p in self._behavioral_profiles.values()
                    if p.anomaly_score > 0.7
                ),
            },
            "network": {
                "flows_last_hour": len([
                    f for f in self._network_flows
                    if f.timestamp >= last_hour
                ]),
                "suspicious_flows": sum(1 for f in self._network_flows if f.suspicious),
            },
        }


_exfiltration_defense_system: Optional[ExfiltrationDefenseSystem] = None


def get_exfiltration_defense_system() -> ExfiltrationDefenseSystem:
    """Get global ExfiltrationDefenseSystem instance."""
    global _exfiltration_defense_system
    if _exfiltration_defense_system is None:
        _exfiltration_defense_system = ExfiltrationDefenseSystem()
    return _exfiltration_defense_system
