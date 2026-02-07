"""
Ecosystem and governance moat for MERID's competitive advantage.

Implements:
- Brand and IP protection tracking
- Trademark and patent portfolio management
- Composable ecosystem metrics
- Agent collaboration network effects
- Product stickiness and UX measurement
- Legal compliance and reputation tracking
"""

import logging
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class IPType(Enum):
    """Intellectual property types."""
    TRADEMARK = "trademark"
    COPYRIGHT = "copyright"
    PATENT = "patent"
    TRADE_SECRET = "trade_secret"


class IPStatus(Enum):
    """IP status."""
    FILED = "filed"
    PENDING = "pending"
    GRANTED = "granted"
    ACTIVE = "active"
    EXPIRED = "expired"


class EcosystemRole(Enum):
    """Ecosystem participant roles."""
    HUB = "hub"  # Central coordinator
    PROVIDER = "provider"  # Service provider
    CONSUMER = "consumer"  # Service consumer
    CONTRIBUTOR = "contributor"  # Open source contributor


class NetworkEffectType(Enum):
    """Network effect types."""
    DIRECT = "direct"  # More users = more value
    INDIRECT = "indirect"  # More providers = more value
    DATA = "data"  # More data = better service
    PLATFORM = "platform"  # More sides = more value


@dataclass
class IntellectualProperty:
    """Intellectual property record."""
    ip_id: str
    ip_type: IPType
    
    # Details
    title: str
    description: str
    
    # Status
    status: IPStatus
    
    # Jurisdiction
    jurisdictions: List[str] = field(default_factory=list)
    
    # Filing
    filing_date: Optional[datetime] = None
    grant_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    
    # Reference
    filing_number: str = ""
    registration_number: str = ""
    
    # Value
    estimated_value: Decimal = Decimal("0.0")
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BrandMetric:
    """Brand strength metric."""
    metric_id: str
    
    # Metric
    metric_name: str  # recognition, trust, preference
    metric_value: float  # 0.0 to 1.0
    
    # Segment
    segment: str  # institutional, retail, developer
    
    # Comparison
    competitor_avg: Optional[float] = None
    advantage_percentage: Optional[float] = None
    
    # Evidence
    survey_size: int = 0
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EcosystemParticipant:
    """Ecosystem participant."""
    participant_id: str
    
    # Identity
    name: str
    role: EcosystemRole
    
    # Engagement
    integration_date: datetime
    active: bool = True
    
    # Metrics
    interactions_count: int = 0
    value_contributed: Decimal = Decimal("0.0")
    value_consumed: Decimal = Decimal("0.0")
    
    # Stickiness
    retention_days: int = 0
    churn_risk: float = 0.0  # 0.0 to 1.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NetworkEffect:
    """Network effect measurement."""
    effect_id: str
    effect_type: NetworkEffectType
    
    # Measurement
    participant_count: int
    value_per_participant: Decimal
    total_network_value: Decimal
    
    # Growth
    growth_rate: float  # Percentage per month
    
    # Strength
    network_effect_coefficient: float  # How much value increases with each new participant
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ProductStickiness:
    """Product stickiness metric."""
    metric_id: str
    
    # Product
    product_name: str
    
    # Usage
    daily_active_users: int
    monthly_active_users: int
    dau_mau_ratio: float
    
    # Retention
    day_1_retention: float
    day_7_retention: float
    day_30_retention: float
    
    # Engagement
    avg_session_duration_minutes: float
    avg_sessions_per_day: float
    
    # Switching costs
    switching_cost_score: float  # 0.0 to 1.0
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ComplianceRecord:
    """Compliance record."""
    record_id: str
    
    # Compliance type
    compliance_type: str  # audit_trail, explainable_ai, legal_disclaimers, mev_compliance
    
    # Status
    compliant: bool
    compliance_score: float  # 0.0 to 1.0
    
    # Evidence
    evidence_urls: List[str] = field(default_factory=list)
    
    # Audit
    last_audit_date: Optional[datetime] = None
    next_audit_date: Optional[datetime] = None
    
    # Certification
    certifications: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecurityIncident:
    """Security incident record."""
    incident_id: str
    
    # Incident
    incident_type: str
    severity: str  # critical, high, medium, low
    
    # Response
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_time_hours: Optional[float] = None
    
    # Handling
    handled_well: bool = False
    public_disclosure: bool = False
    
    # Impact
    impact_description: str = ""
    estimated_loss: Decimal = Decimal("0.0")
    
    # Reputation
    reputation_impact: float = 0.0  # -1.0 to 1.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class EcosystemMoat:
    """
    Ecosystem and governance moat tracker.
    
    Features:
    - IP portfolio management
    - Brand strength tracking
    - Ecosystem network effects
    - Product stickiness measurement
    - Compliance tracking
    - Security reputation management
    """
    
    def __init__(self):
        self._ip_portfolio: Dict[str, IntellectualProperty] = {}
        self._brand_metrics: List[BrandMetric] = []
        self._ecosystem_participants: Dict[str, EcosystemParticipant] = {}
        self._network_effects: List[NetworkEffect] = []
        self._product_stickiness: List[ProductStickiness] = []
        self._compliance_records: Dict[str, ComplianceRecord] = {}
        self._security_incidents: List[SecurityIncident] = []
        
        self._initialize_ip_portfolio()
        self._initialize_compliance()
    
    def _initialize_ip_portfolio(self) -> None:
        """Initialize IP portfolio."""
        
        # Trademark
        self.register_ip(
            ip_type=IPType.TRADEMARK,
            title="MERID",
            description="MERID brand name and logo",
            status=IPStatus.GRANTED,
            jurisdictions=["US", "EU"],
            filing_date=datetime(2024, 1, 1),
            grant_date=datetime(2024, 6, 1),
            estimated_value=Decimal("500000.0"),
        )
        
        # Copyright
        self.register_ip(
            ip_type=IPType.COPYRIGHT,
            title="MERID Core Algorithms",
            description="Proprietary trading and risk algorithms",
            status=IPStatus.ACTIVE,
            jurisdictions=["US", "EU", "International"],
            filing_date=datetime(2024, 1, 1),
            estimated_value=Decimal("2000000.0"),
        )
        
        # Patent (pending)
        self.register_ip(
            ip_type=IPType.PATENT,
            title="Multi-Agent DeFi Orchestration System",
            description="System and method for coordinating multiple AI agents in DeFi trading",
            status=IPStatus.PENDING,
            jurisdictions=["US"],
            filing_date=datetime(2025, 1, 1),
            estimated_value=Decimal("1000000.0"),
        )
        
        logger.info(f"Initialized IP portfolio with {len(self._ip_portfolio)} items")
    
    def _initialize_compliance(self) -> None:
        """Initialize compliance records."""
        
        self.record_compliance(
            compliance_type="audit_trail",
            compliant=True,
            compliance_score=0.95,
            evidence_urls=["https://merid.xyz/compliance/audit-trail"],
            certifications=["SOC2"],
        )
        
        self.record_compliance(
            compliance_type="explainable_ai",
            compliant=True,
            compliance_score=0.90,
            evidence_urls=["https://merid.xyz/compliance/explainable-ai"],
        )
        
        logger.info(f"Initialized {len(self._compliance_records)} compliance records")
    
    def register_ip(
        self,
        ip_type: IPType,
        title: str,
        description: str,
        status: IPStatus,
        jurisdictions: List[str],
        filing_date: Optional[datetime] = None,
        grant_date: Optional[datetime] = None,
        estimated_value: Decimal = Decimal("0.0"),
        filing_number: str = "",
        registration_number: str = "",
    ) -> IntellectualProperty:
        """Register intellectual property."""
        ip_id = f"ip_{ip_type.value}_{int(time.time())}"
        
        ip = IntellectualProperty(
            ip_id=ip_id,
            ip_type=ip_type,
            title=title,
            description=description,
            status=status,
            jurisdictions=jurisdictions,
            filing_date=filing_date,
            grant_date=grant_date,
            estimated_value=estimated_value,
            filing_number=filing_number,
            registration_number=registration_number,
        )
        
        self._ip_portfolio[ip_id] = ip
        
        logger.info(
            f"Registered {ip_type.value} '{title}': {status.value} "
            f"in {len(jurisdictions)} jurisdictions"
        )
        
        return ip
    
    def record_brand_metric(
        self,
        metric_name: str,
        metric_value: float,
        segment: str,
        competitor_avg: Optional[float] = None,
        survey_size: int = 0,
    ) -> BrandMetric:
        """Record brand strength metric."""
        metric_id = f"brand_{metric_name}_{int(time.time())}"
        
        advantage_percentage = None
        if competitor_avg and competitor_avg > 0:
            advantage_percentage = (metric_value - competitor_avg) / competitor_avg * 100
        
        metric = BrandMetric(
            metric_id=metric_id,
            metric_name=metric_name,
            metric_value=metric_value,
            segment=segment,
            competitor_avg=competitor_avg,
            advantage_percentage=advantage_percentage,
            survey_size=survey_size,
        )
        
        self._brand_metrics.append(metric)
        
        logger.info(
            f"Recorded brand metric '{metric_name}' for {segment}: {metric_value:.2f}"
        )
        
        return metric
    
    def register_ecosystem_participant(
        self,
        name: str,
        role: EcosystemRole,
    ) -> EcosystemParticipant:
        """Register ecosystem participant."""
        participant_id = f"participant_{int(time.time())}"
        
        participant = EcosystemParticipant(
            participant_id=participant_id,
            name=name,
            role=role,
            integration_date=datetime.utcnow(),
        )
        
        self._ecosystem_participants[participant_id] = participant
        
        logger.info(f"Registered ecosystem participant '{name}' as {role.value}")
        
        return participant
    
    def record_participant_interaction(
        self,
        participant_id: str,
        value_contributed: Decimal = Decimal("0.0"),
        value_consumed: Decimal = Decimal("0.0"),
    ) -> None:
        """Record participant interaction."""
        participant = self._ecosystem_participants.get(participant_id)
        
        if not participant:
            logger.warning(f"Participant '{participant_id}' not found")
            return
        
        participant.interactions_count += 1
        participant.value_contributed += value_contributed
        participant.value_consumed += value_consumed
        
        # Update retention
        participant.retention_days = (datetime.utcnow() - participant.integration_date).days
    
    def measure_network_effect(
        self,
        effect_type: NetworkEffectType,
        participant_count: int,
        value_per_participant: Decimal,
        growth_rate: float,
        network_effect_coefficient: float,
    ) -> NetworkEffect:
        """Measure network effect."""
        effect_id = f"network_{effect_type.value}_{int(time.time())}"
        
        total_network_value = value_per_participant * participant_count
        
        effect = NetworkEffect(
            effect_id=effect_id,
            effect_type=effect_type,
            participant_count=participant_count,
            value_per_participant=value_per_participant,
            total_network_value=total_network_value,
            growth_rate=growth_rate,
            network_effect_coefficient=network_effect_coefficient,
        )
        
        self._network_effects.append(effect)
        
        logger.info(
            f"Measured {effect_type.value} network effect: "
            f"{participant_count} participants, ${total_network_value:,.0f} total value"
        )
        
        return effect
    
    def record_product_stickiness(
        self,
        product_name: str,
        daily_active_users: int,
        monthly_active_users: int,
        day_1_retention: float,
        day_7_retention: float,
        day_30_retention: float,
        avg_session_duration_minutes: float,
        avg_sessions_per_day: float,
        switching_cost_score: float,
    ) -> ProductStickiness:
        """Record product stickiness metric."""
        metric_id = f"sticky_{product_name}_{int(time.time())}"
        
        dau_mau_ratio = daily_active_users / monthly_active_users if monthly_active_users > 0 else 0.0
        
        stickiness = ProductStickiness(
            metric_id=metric_id,
            product_name=product_name,
            daily_active_users=daily_active_users,
            monthly_active_users=monthly_active_users,
            dau_mau_ratio=dau_mau_ratio,
            day_1_retention=day_1_retention,
            day_7_retention=day_7_retention,
            day_30_retention=day_30_retention,
            avg_session_duration_minutes=avg_session_duration_minutes,
            avg_sessions_per_day=avg_sessions_per_day,
            switching_cost_score=switching_cost_score,
        )
        
        self._product_stickiness.append(stickiness)
        
        logger.info(
            f"Recorded product stickiness for '{product_name}': "
            f"DAU/MAU={dau_mau_ratio:.2%}, D30 retention={day_30_retention:.2%}"
        )
        
        return stickiness
    
    def record_compliance(
        self,
        compliance_type: str,
        compliant: bool,
        compliance_score: float,
        evidence_urls: List[str],
        certifications: List[str] = None,
    ) -> ComplianceRecord:
        """Record compliance status."""
        record_id = f"compliance_{compliance_type}"
        
        record = ComplianceRecord(
            record_id=record_id,
            compliance_type=compliance_type,
            compliant=compliant,
            compliance_score=compliance_score,
            evidence_urls=evidence_urls,
            certifications=certifications or [],
        )
        
        self._compliance_records[record_id] = record
        
        logger.info(
            f"Recorded compliance for '{compliance_type}': "
            f"{'compliant' if compliant else 'non-compliant'} ({compliance_score:.2%})"
        )
        
        return record
    
    def record_security_incident(
        self,
        incident_type: str,
        severity: str,
        detected_at: datetime,
        resolved_at: Optional[datetime] = None,
        handled_well: bool = False,
        public_disclosure: bool = False,
        impact_description: str = "",
        estimated_loss: Decimal = Decimal("0.0"),
        reputation_impact: float = 0.0,
    ) -> SecurityIncident:
        """Record security incident."""
        incident_id = f"incident_{int(time.time())}"
        
        resolution_time_hours = None
        if resolved_at:
            resolution_time_hours = (resolved_at - detected_at).total_seconds() / 3600
        
        incident = SecurityIncident(
            incident_id=incident_id,
            incident_type=incident_type,
            severity=severity,
            detected_at=detected_at,
            resolved_at=resolved_at,
            resolution_time_hours=resolution_time_hours,
            handled_well=handled_well,
            public_disclosure=public_disclosure,
            impact_description=impact_description,
            estimated_loss=estimated_loss,
            reputation_impact=reputation_impact,
        )
        
        self._security_incidents.append(incident)
        
        logger.info(
            f"Recorded security incident '{incident_type}': {severity} severity, "
            f"{'resolved' if resolved_at else 'ongoing'}"
        )
        
        return incident
    
    def get_ecosystem_moat_stats(self) -> Dict[str, Any]:
        """Get ecosystem moat statistics."""
        
        # IP portfolio
        total_ip_value = sum(ip.estimated_value for ip in self._ip_portfolio.values())
        
        granted_ip = sum(
            1 for ip in self._ip_portfolio.values()
            if ip.status in [IPStatus.GRANTED, IPStatus.ACTIVE]
        )
        
        # Brand metrics
        avg_brand_strength = (
            sum(m.metric_value for m in self._brand_metrics) /
            len(self._brand_metrics)
            if self._brand_metrics else 0.0
        )
        
        # Ecosystem
        active_participants = sum(
            1 for p in self._ecosystem_participants.values()
            if p.active
        )
        
        total_ecosystem_value = sum(
            p.value_contributed for p in self._ecosystem_participants.values()
        )
        
        # Network effects
        total_network_value = sum(
            e.total_network_value for e in self._network_effects
        )
        
        avg_growth_rate = (
            sum(e.growth_rate for e in self._network_effects) /
            len(self._network_effects)
            if self._network_effects else 0.0
        )
        
        # Product stickiness
        avg_dau_mau = (
            sum(s.dau_mau_ratio for s in self._product_stickiness) /
            len(self._product_stickiness)
            if self._product_stickiness else 0.0
        )
        
        avg_day_30_retention = (
            sum(s.day_30_retention for s in self._product_stickiness) /
            len(self._product_stickiness)
            if self._product_stickiness else 0.0
        )
        
        # Compliance
        compliance_rate = (
            sum(1 for c in self._compliance_records.values() if c.compliant) /
            len(self._compliance_records)
            if self._compliance_records else 0.0
        )
        
        # Security
        well_handled_incidents = sum(
            1 for i in self._security_incidents
            if i.handled_well
        )
        
        avg_resolution_time = (
            sum(
                i.resolution_time_hours for i in self._security_incidents
                if i.resolution_time_hours is not None
            ) / sum(
                1 for i in self._security_incidents
                if i.resolution_time_hours is not None
            )
            if any(i.resolution_time_hours for i in self._security_incidents) else 0.0
        )
        
        return {
            "ip_portfolio": {
                "total_items": len(self._ip_portfolio),
                "granted": granted_ip,
                "total_estimated_value": float(total_ip_value),
                "by_type": {
                    ip_type.value: sum(
                        1 for ip in self._ip_portfolio.values()
                        if ip.ip_type == ip_type
                    )
                    for ip_type in IPType
                },
            },
            "brand": {
                "metrics": len(self._brand_metrics),
                "avg_strength": avg_brand_strength,
            },
            "ecosystem": {
                "total_participants": len(self._ecosystem_participants),
                "active_participants": active_participants,
                "total_value_contributed": float(total_ecosystem_value),
            },
            "network_effects": {
                "total_measurements": len(self._network_effects),
                "total_network_value": float(total_network_value),
                "avg_growth_rate": avg_growth_rate,
            },
            "product_stickiness": {
                "products": len(self._product_stickiness),
                "avg_dau_mau_ratio": avg_dau_mau,
                "avg_day_30_retention": avg_day_30_retention,
            },
            "compliance": {
                "total_records": len(self._compliance_records),
                "compliance_rate": compliance_rate,
            },
            "security": {
                "total_incidents": len(self._security_incidents),
                "well_handled": well_handled_incidents,
                "avg_resolution_time_hours": avg_resolution_time,
            },
        }


_ecosystem_moat: Optional[EcosystemMoat] = None


def get_ecosystem_moat() -> EcosystemMoat:
    """Get global EcosystemMoat instance."""
    global _ecosystem_moat
    if _ecosystem_moat is None:
        _ecosystem_moat = EcosystemMoat()
    return _ecosystem_moat
