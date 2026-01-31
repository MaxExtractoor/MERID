"""
Enhanced telemetry privacy controls with privacy-by-design schemas and access controls.

Extends base telemetry manager with purpose limitation, RBAC, differential views,
and privacy testing/auditing capabilities.
"""

import logging
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import re

from core.telemetry_manager import get_telemetry_manager, TelemetryManager, DataClassification

logger = logging.getLogger(__name__)


class TelemetryPurpose(Enum):
    """Purpose tags for telemetry streams."""
    OPERATIONS = "operations"
    RISK_MANAGEMENT = "risk_management"
    COMPLIANCE = "compliance"
    RESEARCH = "research"
    ANALYTICS = "analytics"
    DEBUGGING = "debugging"
    AUDIT = "audit"


class AccessRole(Enum):
    """Access roles for telemetry data."""
    OPERATOR = "operator"
    RISK_MANAGER = "risk_manager"
    COMPLIANCE_OFFICER = "compliance_officer"
    RESEARCHER = "researcher"
    ENGINEER = "engineer"
    AUDITOR = "auditor"
    ADMIN = "admin"


@dataclass
class PrivacySchema:
    """Privacy-by-design schema for telemetry stream."""
    stream_name: str
    allowed_fields: Set[str]
    prohibited_fields: Set[str]
    pii_fields: Set[str]
    justification: str
    purpose: TelemetryPurpose
    retention_justification: str
    access_roles: Set[AccessRole]


@dataclass
class AccessControl:
    """Access control for telemetry data."""
    role: AccessRole
    allowed_streams: Set[str]
    allowed_purposes: Set[TelemetryPurpose]
    allowed_classifications: Set[DataClassification]
    view_type: str
    can_access_raw: bool
    can_access_aggregated: bool


@dataclass
class PrivacyViolation:
    """Privacy violation detected in telemetry."""
    violation_id: str
    timestamp: datetime
    stream_name: str
    violation_type: str
    severity: str
    field_name: Optional[str]
    detected_value: Optional[str]
    description: str
    remediation: str


class TelemetryPrivacyEnhanced:
    """
    Enhanced telemetry privacy controls.
    
    Implements:
    - Privacy-by-design schemas
    - Purpose limitation and opt-out hooks
    - Granular RBAC on telemetry stores
    - Differential views (ops vs research vs compliance)
    - Privacy testing and audits
    """
    
    def __init__(self):
        self.telemetry = get_telemetry_manager()
        
        self._privacy_schemas: Dict[str, PrivacySchema] = {}
        self._access_controls: Dict[AccessRole, AccessControl] = {}
        self._privacy_violations: List[PrivacyViolation] = []
        
        self._pii_patterns = {
            "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            "phone": re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
            "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            "credit_card": re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
            "ip_address": re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
        }
        
        self._initialize_privacy_schemas()
        self._initialize_access_controls()
    
    def _initialize_privacy_schemas(self) -> None:
        """Initialize privacy-by-design schemas."""
        self.register_privacy_schema(
            stream_name="execution",
            allowed_fields={
                "agent_id", "strategy_id", "venue", "asset", "side",
                "size", "price", "timestamp", "correlation_id", "trace_id",
                "order_type", "status", "fill_ratio", "slippage",
            },
            prohibited_fields={
                "user_id", "account_id", "api_key", "wallet_address",
                "private_key", "email", "phone", "ip_address",
            },
            pii_fields=set(),
            justification="Execution telemetry for operational monitoring and risk management",
            purpose=TelemetryPurpose.OPERATIONS,
            retention_justification="30 days for operational debugging and compliance",
            access_roles={AccessRole.OPERATOR, AccessRole.RISK_MANAGER, AccessRole.COMPLIANCE_OFFICER},
        )
        
        self.register_privacy_schema(
            stream_name="research",
            allowed_fields={
                "strategy_id", "regime", "features", "predictions",
                "performance_metrics", "timestamp", "model_version",
            },
            prohibited_fields={
                "user_id", "account_id", "api_key", "email", "phone",
                "ip_address", "wallet_address", "private_key",
            },
            pii_fields=set(),
            justification="Research telemetry for model development (aggregated only)",
            purpose=TelemetryPurpose.RESEARCH,
            retention_justification="730 days for long-term research",
            access_roles={AccessRole.RESEARCHER, AccessRole.ENGINEER},
        )
        
        self.register_privacy_schema(
            stream_name="compliance",
            allowed_fields={
                "agent_id", "strategy_id", "action_type", "timestamp",
                "governance_action", "approver", "reason", "impact",
                "contract_id", "violation_type",
            },
            prohibited_fields={
                "api_key", "private_key", "password", "seed_phrase",
            },
            pii_fields={"user_id"},
            justification="Compliance telemetry for audit and regulatory reporting",
            purpose=TelemetryPurpose.COMPLIANCE,
            retention_justification="7 years for regulatory compliance",
            access_roles={AccessRole.COMPLIANCE_OFFICER, AccessRole.AUDITOR, AccessRole.ADMIN},
        )
    
    def _initialize_access_controls(self) -> None:
        """Initialize RBAC for telemetry access."""
        self.register_access_control(
            role=AccessRole.OPERATOR,
            allowed_streams={"execution", "risk", "system"},
            allowed_purposes={TelemetryPurpose.OPERATIONS, TelemetryPurpose.DEBUGGING},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL},
            view_type="operational",
            can_access_raw=True,
            can_access_aggregated=True,
        )
        
        self.register_access_control(
            role=AccessRole.RISK_MANAGER,
            allowed_streams={"execution", "risk", "governance", "drift"},
            allowed_purposes={TelemetryPurpose.RISK_MANAGEMENT, TelemetryPurpose.OPERATIONS},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL, DataClassification.SENSITIVE},
            view_type="risk",
            can_access_raw=True,
            can_access_aggregated=True,
        )
        
        self.register_access_control(
            role=AccessRole.COMPLIANCE_OFFICER,
            allowed_streams={"compliance", "governance", "execution", "audit"},
            allowed_purposes={TelemetryPurpose.COMPLIANCE, TelemetryPurpose.AUDIT},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL, DataClassification.SENSITIVE},
            view_type="compliance",
            can_access_raw=True,
            can_access_aggregated=True,
        )
        
        self.register_access_control(
            role=AccessRole.RESEARCHER,
            allowed_streams={"research", "analytics"},
            allowed_purposes={TelemetryPurpose.RESEARCH, TelemetryPurpose.ANALYTICS},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL},
            view_type="aggregated",
            can_access_raw=False,
            can_access_aggregated=True,
        )
        
        self.register_access_control(
            role=AccessRole.ENGINEER,
            allowed_streams={"system", "debugging", "analytics"},
            allowed_purposes={TelemetryPurpose.DEBUGGING, TelemetryPurpose.OPERATIONS},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL},
            view_type="technical",
            can_access_raw=True,
            can_access_aggregated=True,
        )
        
        self.register_access_control(
            role=AccessRole.AUDITOR,
            allowed_streams={"compliance", "governance", "audit", "execution", "risk"},
            allowed_purposes={TelemetryPurpose.AUDIT, TelemetryPurpose.COMPLIANCE},
            allowed_classifications={DataClassification.PUBLIC, DataClassification.INTERNAL, DataClassification.SENSITIVE},
            view_type="audit",
            can_access_raw=True,
            can_access_aggregated=True,
        )
    
    def register_privacy_schema(
        self,
        stream_name: str,
        allowed_fields: Set[str],
        prohibited_fields: Set[str],
        pii_fields: Set[str],
        justification: str,
        purpose: TelemetryPurpose,
        retention_justification: str,
        access_roles: Set[AccessRole],
    ) -> PrivacySchema:
        """Register privacy-by-design schema for stream."""
        schema = PrivacySchema(
            stream_name=stream_name,
            allowed_fields=allowed_fields,
            prohibited_fields=prohibited_fields,
            pii_fields=pii_fields,
            justification=justification,
            purpose=purpose,
            retention_justification=retention_justification,
            access_roles=access_roles,
        )
        
        self._privacy_schemas[stream_name] = schema
        
        logger.info(
            f"Registered privacy schema for '{stream_name}': "
            f"purpose={purpose.value}, {len(allowed_fields)} allowed fields"
        )
        
        return schema
    
    def register_access_control(
        self,
        role: AccessRole,
        allowed_streams: Set[str],
        allowed_purposes: Set[TelemetryPurpose],
        allowed_classifications: Set[DataClassification],
        view_type: str,
        can_access_raw: bool,
        can_access_aggregated: bool,
    ) -> AccessControl:
        """Register access control for role."""
        control = AccessControl(
            role=role,
            allowed_streams=allowed_streams,
            allowed_purposes=allowed_purposes,
            allowed_classifications=allowed_classifications,
            view_type=view_type,
            can_access_raw=can_access_raw,
            can_access_aggregated=can_access_aggregated,
        )
        
        self._access_controls[role] = control
        
        logger.info(
            f"Registered access control for {role.value}: "
            f"{len(allowed_streams)} streams, view={view_type}"
        )
        
        return control
    
    def validate_telemetry_fields(
        self,
        stream_name: str,
        fields: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Validate telemetry fields against privacy schema."""
        schema = self._privacy_schemas.get(stream_name)
        if not schema:
            return True, []
        
        violations = []
        
        for field_name in fields.keys():
            if field_name in schema.prohibited_fields:
                violations.append(
                    f"Prohibited field '{field_name}' in stream '{stream_name}'"
                )
                
                self._record_privacy_violation(
                    stream_name=stream_name,
                    violation_type="prohibited_field",
                    severity="CRITICAL",
                    field_name=field_name,
                    description=f"Prohibited field detected: {field_name}",
                    remediation="Remove field from telemetry",
                )
        
        approved = len(violations) == 0
        
        return approved, violations
    
    def scan_for_pii(
        self,
        stream_name: str,
        data: Dict[str, Any],
    ) -> List[str]:
        """Scan data for unintentional PII leakage."""
        detected_pii = []
        
        for field_name, value in data.items():
            if not isinstance(value, str):
                continue
            
            for pii_type, pattern in self._pii_patterns.items():
                if pattern.search(value):
                    detected_pii.append(f"{pii_type} in field '{field_name}'")
                    
                    self._record_privacy_violation(
                        stream_name=stream_name,
                        violation_type="pii_leakage",
                        severity="ERROR",
                        field_name=field_name,
                        detected_value=self._mask_value(value),
                        description=f"Potential {pii_type} detected in {field_name}",
                        remediation="Mask or remove PII from field",
                    )
        
        return detected_pii
    
    def check_access_permission(
        self,
        role: AccessRole,
        stream_name: str,
        purpose: TelemetryPurpose,
        classification: DataClassification,
        raw_access: bool,
    ) -> Tuple[bool, Optional[str]]:
        """Check if role has permission to access telemetry."""
        control = self._access_controls.get(role)
        if not control:
            return False, f"Role '{role.value}' not configured"
        
        if stream_name not in control.allowed_streams:
            return False, f"Stream '{stream_name}' not allowed for role '{role.value}'"
        
        if purpose not in control.allowed_purposes:
            return False, f"Purpose '{purpose.value}' not allowed for role '{role.value}'"
        
        if classification not in control.allowed_classifications:
            return False, f"Classification '{classification.value}' not allowed for role '{role.value}'"
        
        if raw_access and not control.can_access_raw:
            return False, f"Raw access not allowed for role '{role.value}'"
        
        return True, None
    
    def get_filtered_view(
        self,
        role: AccessRole,
        stream_name: str,
        data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Get filtered view of telemetry data based on role."""
        control = self._access_controls.get(role)
        if not control:
            return []
        
        schema = self._privacy_schemas.get(stream_name)
        if not schema:
            return data
        
        if control.view_type == "aggregated":
            return self._create_aggregated_view(data)
        
        elif control.view_type == "compliance":
            return self._create_compliance_view(data, schema)
        
        elif control.view_type == "risk":
            return self._create_risk_view(data, schema)
        
        else:
            return self._create_operational_view(data, schema)
    
    def _create_aggregated_view(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create aggregated view (no individual records)."""
        if not data:
            return []
        
        return [{
            "count": len(data),
            "summary": "Aggregated data (individual records not accessible)",
        }]
    
    def _create_compliance_view(
        self,
        data: List[Dict[str, Any]],
        schema: PrivacySchema,
    ) -> List[Dict[str, Any]]:
        """Create compliance view with audit fields."""
        filtered = []
        
        for record in data:
            filtered_record = {}
            for field in ["timestamp", "agent_id", "action_type", "approver", "reason"]:
                if field in record:
                    filtered_record[field] = record[field]
            
            if schema.pii_fields:
                for pii_field in schema.pii_fields:
                    if pii_field in record:
                        filtered_record[pii_field] = self._mask_value(record[pii_field])
            
            filtered.append(filtered_record)
        
        return filtered
    
    def _create_risk_view(
        self,
        data: List[Dict[str, Any]],
        schema: PrivacySchema,
    ) -> List[Dict[str, Any]]:
        """Create risk view with risk-relevant fields."""
        filtered = []
        
        for record in data:
            filtered_record = {}
            for field in ["timestamp", "agent_id", "strategy_id", "asset", "size", "pnl", "risk_metrics"]:
                if field in record:
                    filtered_record[field] = record[field]
            
            filtered.append(filtered_record)
        
        return filtered
    
    def _create_operational_view(
        self,
        data: List[Dict[str, Any]],
        schema: PrivacySchema,
    ) -> List[Dict[str, Any]]:
        """Create operational view with allowed fields only."""
        filtered = []
        
        for record in data:
            filtered_record = {
                field: value
                for field, value in record.items()
                if field in schema.allowed_fields
            }
            filtered.append(filtered_record)
        
        return filtered
    
    def _mask_value(self, value: str) -> str:
        """Mask sensitive value."""
        if len(value) <= 4:
            return "***"
        return value[:2] + "***" + value[-2:]
    
    def conduct_privacy_audit(
        self,
        stream_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Conduct privacy audit of telemetry."""
        audit_results = {
            "timestamp": datetime.utcnow().isoformat(),
            "streams_audited": [],
            "violations_found": 0,
            "critical_violations": 0,
            "recommendations": [],
        }
        
        streams_to_audit = [stream_name] if stream_name else list(self._privacy_schemas.keys())
        
        for stream in streams_to_audit:
            schema = self._privacy_schemas.get(stream)
            if not schema:
                continue
            
            stream_violations = [
                v for v in self._privacy_violations
                if v.stream_name == stream
            ]
            
            critical = sum(1 for v in stream_violations if v.severity == "CRITICAL")
            
            audit_results["streams_audited"].append({
                "stream_name": stream,
                "violations": len(stream_violations),
                "critical": critical,
                "purpose": schema.purpose.value,
                "access_roles": [r.value for r in schema.access_roles],
            })
            
            audit_results["violations_found"] += len(stream_violations)
            audit_results["critical_violations"] += critical
        
        if audit_results["critical_violations"] > 0:
            audit_results["recommendations"].append(
                "Address critical privacy violations immediately"
            )
        
        if audit_results["violations_found"] > 10:
            audit_results["recommendations"].append(
                "Review privacy schemas and field validation"
            )
        
        logger.info(
            f"Privacy audit completed: {audit_results['violations_found']} violations found "
            f"({audit_results['critical_violations']} critical)"
        )
        
        return audit_results
    
    def _record_privacy_violation(
        self,
        stream_name: str,
        violation_type: str,
        severity: str,
        field_name: Optional[str],
        description: str,
        remediation: str,
        detected_value: Optional[str] = None,
    ) -> None:
        """Record privacy violation."""
        violation_id = hashlib.md5(
            f"{stream_name}_{violation_type}_{field_name}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        violation = PrivacyViolation(
            violation_id=violation_id,
            timestamp=datetime.utcnow(),
            stream_name=stream_name,
            violation_type=violation_type,
            severity=severity,
            field_name=field_name,
            detected_value=detected_value,
            description=description,
            remediation=remediation,
        )
        
        self._privacy_violations.append(violation)
        
        logger.warning(
            f"Privacy violation detected: {violation_type} in {stream_name} "
            f"(severity={severity})"
        )
    
    def get_privacy_violations(
        self,
        stream_name: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[PrivacyViolation]:
        """Query privacy violations."""
        violations = self._privacy_violations
        
        if stream_name:
            violations = [v for v in violations if v.stream_name == stream_name]
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        if since:
            violations = [v for v in violations if v.timestamp >= since]
        
        return violations[-limit:]
    
    def get_privacy_summary(self) -> Dict[str, Any]:
        """Get privacy controls summary."""
        return {
            "privacy_schemas": len(self._privacy_schemas),
            "access_controls": len(self._access_controls),
            "total_violations": len(self._privacy_violations),
            "critical_violations": len([v for v in self._privacy_violations if v.severity == "CRITICAL"]),
            "schemas": {
                name: {
                    "purpose": schema.purpose.value,
                    "allowed_fields": len(schema.allowed_fields),
                    "prohibited_fields": len(schema.prohibited_fields),
                    "pii_fields": len(schema.pii_fields),
                    "access_roles": [r.value for r in schema.access_roles],
                }
                for name, schema in self._privacy_schemas.items()
            },
        }


_telemetry_privacy_enhanced: Optional[TelemetryPrivacyEnhanced] = None


def get_telemetry_privacy_enhanced() -> TelemetryPrivacyEnhanced:
    """Get global TelemetryPrivacyEnhanced instance."""
    global _telemetry_privacy_enhanced
    if _telemetry_privacy_enhanced is None:
        _telemetry_privacy_enhanced = TelemetryPrivacyEnhanced()
    return _telemetry_privacy_enhanced
