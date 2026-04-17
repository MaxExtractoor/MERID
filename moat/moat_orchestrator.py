"""
MERID Moat Orchestrator - Encodes moat principles as explicit goals and constraints.

Implements:
- Moat-aware feature development
- Competitive advantage validation
- Moat strengthening recommendations
- Cross-moat synergy detection
- Moat erosion monitoring
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

from moat.proprietary_data import get_proprietary_data_warehouse, DataCategory
from moat.execution_moat import get_execution_moat, InfraComponent
from moat.swarm_architecture_moat import get_swarm_architecture_moat, AgentCapabilityType
from moat.ecosystem_moat import get_ecosystem_moat, IPType

logger = get_logger(__name__)


class MoatPillar(Enum):
    """Core moat pillars."""
    PROPRIETARY_DATA = "proprietary_data"
    EXECUTION_INFRA = "execution_infra"
    SWARM_ARCHITECTURE = "swarm_architecture"
    ECOSYSTEM_NETWORK = "ecosystem_network"
    LEGAL_COMPLIANCE = "legal_compliance"


class MoatStrength(Enum):
    """Moat strength levels."""
    WEAK = "weak"  # < 1.2x competitor
    MODERATE = "moderate"  # 1.2x - 1.5x
    STRONG = "strong"  # 1.5x - 2.0x
    DOMINANT = "dominant"  # > 2.0x


class FeatureImpact(Enum):
    """Feature impact on moat."""
    STRENGTHENS = "strengthens"
    MAINTAINS = "maintains"
    NEUTRAL = "neutral"
    WEAKENS = "weakens"


@dataclass
class MoatPrinciple:
    """Moat principle."""
    principle_id: str
    pillar: MoatPillar
    
    # Principle
    title: str
    description: str
    
    # Validation
    validation_criteria: List[str] = field(default_factory=list)
    
    # Priority
    priority: str = "medium"  # low, medium, high, critical
    
    enabled: bool = True


@dataclass
class FeatureProposal:
    """Feature proposal for moat validation."""
    proposal_id: str
    
    # Feature
    feature_name: str
    feature_description: str
    
    # Moat impact
    moat_impacts: Dict[MoatPillar, FeatureImpact] = field(default_factory=dict)
    
    # Analysis
    strengthens_moat: bool = False
    moat_score: float = 0.0  # -1.0 to 1.0
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    # Approval
    approved: bool = False
    approval_reason: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MoatMetric:
    """Aggregated moat metric."""
    metric_id: str
    pillar: MoatPillar
    
    # Strength
    strength: MoatStrength
    advantage_ratio: float  # vs competitors
    
    # Trend
    trend: str  # improving, stable, declining
    
    # Evidence
    evidence_count: int
    
    measured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MoatSynergy:
    """Cross-pillar moat synergy."""
    synergy_id: str
    
    # Pillars
    pillar_a: MoatPillar
    pillar_b: MoatPillar
    
    # Synergy
    synergy_type: str  # reinforcing, complementary, multiplicative
    synergy_strength: float  # 0.0 to 1.0
    
    # Description
    description: str = ""
    
    # Examples
    examples: List[str] = field(default_factory=list)


@dataclass
class MoatErosionRisk:
    """Moat erosion risk."""
    risk_id: str
    pillar: MoatPillar
    
    # Risk
    risk_type: str
    risk_level: str  # low, medium, high, critical
    
    # Description
    description: str = ""
    
    # Mitigation
    mitigation_actions: List[str] = field(default_factory=list)
    
    detected_at: datetime = field(default_factory=datetime.utcnow)


class MoatOrchestrator:
    """
    MERID Moat Orchestrator - Encodes moat principles as goals and constraints.
    
    Features:
    - Moat principle enforcement
    - Feature moat validation
    - Moat strength measurement
    - Synergy detection
    - Erosion monitoring
    """
    
    def __init__(self):
        self._principles: Dict[str, MoatPrinciple] = {}
        self._feature_proposals: List[FeatureProposal] = []
        self._moat_metrics: List[MoatMetric] = []
        self._synergies: List[MoatSynergy] = []
        self._erosion_risks: List[MoatErosionRisk] = []
        
        # Component references
        self._data_warehouse = get_proprietary_data_warehouse()
        self._execution_moat = get_execution_moat()
        self._swarm_moat = get_swarm_architecture_moat()
        self._ecosystem_moat = get_ecosystem_moat()
        
        self._initialize_principles()
        self._initialize_synergies()
    
    def _initialize_principles(self) -> None:
        """Initialize moat principles."""
        
        # Proprietary data principles
        self.register_principle(
            pillar=MoatPillar.PROPRIETARY_DATA,
            title="High-resolution internal datasets",
            description="Aggregate long-horizon tick data, on-chain state, execution logs, and swarm telemetry with clean schemas and labels",
            validation_criteria=[
                "Data volume > 1TB",
                "Data quality > 90% labeled",
                "Unique data not available to competitors",
            ],
            priority="critical",
        )
        
        self.register_principle(
            pillar=MoatPillar.PROPRIETARY_DATA,
            title="Closed feedback loops",
            description="Every strategy, experiment, and UI change feeds back into Swarm Lab memory for continuous refinement",
            validation_criteria=[
                "Feedback loop application rate > 80%",
                "Model improvement from feedback measurable",
            ],
            priority="high",
        )
        
        # Execution infrastructure principles
        self.register_principle(
            pillar=MoatPillar.EXECUTION_INFRA,
            title="Low-latency infrastructure",
            description="Co-located engines, tuned RPC routing, indexers, and GPU-accelerated analytics",
            validation_criteria=[
                "Latency < 10ms for critical operations",
                "Co-location in 3+ regions",
                "GPU acceleration for ZK/AI workloads",
            ],
            priority="critical",
        )
        
        self.register_principle(
            pillar=MoatPillar.EXECUTION_INFRA,
            title="Industrial-grade risk and safety",
            description="Deep risk controls, HSM/MPC custody, anti-scam/MEV abuse, anti-silent-failure",
            validation_criteria=[
                "Risk control effectiveness > 90%",
                "Institutional-grade custody",
                "Zero silent failures in production",
            ],
            priority="critical",
        )
        
        # Swarm architecture principles
        self.register_principle(
            pillar=MoatPillar.SWARM_ARCHITECTURE,
            title="Model-agnostic multi-agent framework",
            description="Clean orchestration layer with capability-based agents, long-term memory, multi-provider LLM routing",
            validation_criteria=[
                "Support 5+ LLM providers",
                "Agent orchestration efficiency > 2x baseline",
                "Long-term memory retention > 80%",
            ],
            priority="high",
        )
        
        self.register_principle(
            pillar=MoatPillar.SWARM_ARCHITECTURE,
            title="Specialized safety & exploit agents",
            description="Security, sniper, exploit, scam, and social-engineering agents tuned on years of incidents",
            validation_criteria=[
                "Detection accuracy > 90%",
                "False positive rate < 5%",
                "Value protected > $10M annually",
            ],
            priority="critical",
        )
        
        # Ecosystem network principles
        self.register_principle(
            pillar=MoatPillar.ECOSYSTEM_NETWORK,
            title="Strong brand and IP protection",
            description="Protected trademarks, copyrights, patents around MERID name, algorithms, and designs",
            validation_criteria=[
                "Trademarks registered in US, EU",
                "Core algorithms copyrighted",
                "Patent applications filed",
            ],
            priority="high",
        )
        
        self.register_principle(
            pillar=MoatPillar.ECOSYSTEM_NETWORK,
            title="Composable ecosystem and collaboration",
            description="Best hub for agent collaboration with registries, ANP protocols, capability marketplaces",
            validation_criteria=[
                "Active ecosystem participants > 50",
                "Network effect coefficient > 1.5",
                "Integration requests > 10/month",
            ],
            priority="high",
        )
        
        self.register_principle(
            pillar=MoatPillar.ECOSYSTEM_NETWORK,
            title="Sticky products and UX",
            description="Opinionated dashboards, vaults, tooling, and AI assistant tuned for DeFi/HFT",
            validation_criteria=[
                "DAU/MAU ratio > 40%",
                "Day 30 retention > 60%",
                "Switching cost score > 0.7",
            ],
            priority="medium",
        )
        
        # Legal compliance principles
        self.register_principle(
            pillar=MoatPillar.LEGAL_COMPLIANCE,
            title="Compliance-aware design",
            description="Clean audit trails, explainable AI, legal disclaimers, compliant MEV/yield design",
            validation_criteria=[
                "Compliance rate > 95%",
                "Audit trail completeness > 99%",
                "Explainable AI for all decisions",
            ],
            priority="critical",
        )
        
        self.register_principle(
            pillar=MoatPillar.LEGAL_COMPLIANCE,
            title="Security track record",
            description="Public well-handled incidents, bug bounties, published security practices",
            validation_criteria=[
                "Incident resolution time < 24 hours",
                "Well-handled incident rate > 90%",
                "Active bug bounty program",
            ],
            priority="high",
        )
        
        logger.info(f"Initialized {len(self._principles)} moat principles")
    
    def _initialize_synergies(self) -> None:
        """Initialize cross-pillar synergies."""
        
        self.register_synergy(
            pillar_a=MoatPillar.PROPRIETARY_DATA,
            pillar_b=MoatPillar.SWARM_ARCHITECTURE,
            synergy_type="multiplicative",
            synergy_strength=0.9,
            description="Proprietary data trains specialized agents, creating unique capabilities",
            examples=[
                "Tick data trains better execution agents",
                "Incident data trains better security agents",
            ],
        )
        
        self.register_synergy(
            pillar_a=MoatPillar.EXECUTION_INFRA,
            pillar_b=MoatPillar.PROPRIETARY_DATA,
            synergy_type="reinforcing",
            synergy_strength=0.8,
            description="Low-latency infrastructure generates more high-quality data",
            examples=[
                "Fast execution captures more market microstructure",
                "Co-location enables tick-level data collection",
            ],
        )
        
        self.register_synergy(
            pillar_a=MoatPillar.SWARM_ARCHITECTURE,
            pillar_b=MoatPillar.ECOSYSTEM_NETWORK,
            synergy_type="complementary",
            synergy_strength=0.85,
            description="Advanced swarm architecture attracts ecosystem participants",
            examples=[
                "Capability marketplace draws external agents",
                "Multi-agent framework enables rich integrations",
            ],
        )
        
        self.register_synergy(
            pillar_a=MoatPillar.LEGAL_COMPLIANCE,
            pillar_b=MoatPillar.ECOSYSTEM_NETWORK,
            synergy_type="reinforcing",
            synergy_strength=0.75,
            description="Compliance attracts institutional capital and partners",
            examples=[
                "Audit trails enable institutional adoption",
                "Compliance reputation attracts serious capital",
            ],
        )
        
        logger.info(f"Initialized {len(self._synergies)} moat synergies")
    
    def register_principle(
        self,
        pillar: MoatPillar,
        title: str,
        description: str,
        validation_criteria: List[str],
        priority: str,
    ) -> MoatPrinciple:
        """Register moat principle."""
        principle_id = f"principle_{pillar.value}_{len(self._principles)}"
        
        principle = MoatPrinciple(
            principle_id=principle_id,
            pillar=pillar,
            title=title,
            description=description,
            validation_criteria=validation_criteria,
            priority=priority,
        )
        
        self._principles[principle_id] = principle
        
        return principle
    
    def validate_feature_proposal(
        self,
        feature_name: str,
        feature_description: str,
    ) -> FeatureProposal:
        """Validate feature proposal against moat principles."""
        proposal_id = f"proposal_{int(datetime.utcnow().timestamp())}"
        
        proposal = FeatureProposal(
            proposal_id=proposal_id,
            feature_name=feature_name,
            feature_description=feature_description,
        )
        
        # Analyze impact on each pillar
        moat_score = 0.0
        
        # Check for data-related features
        if any(keyword in feature_description.lower() for keyword in ["data", "dataset", "collection", "telemetry"]):
            proposal.moat_impacts[MoatPillar.PROPRIETARY_DATA] = FeatureImpact.STRENGTHENS
            moat_score += 0.3
            proposal.recommendations.append("Ensure data is labeled and integrated into warehouse")
        
        # Check for execution/infra features
        if any(keyword in feature_description.lower() for keyword in ["latency", "performance", "infrastructure", "gpu"]):
            proposal.moat_impacts[MoatPillar.EXECUTION_INFRA] = FeatureImpact.STRENGTHENS
            moat_score += 0.3
            proposal.recommendations.append("Measure latency improvement vs competitors")
        
        # Check for agent/swarm features
        if any(keyword in feature_description.lower() for keyword in ["agent", "swarm", "orchestration", "llm"]):
            proposal.moat_impacts[MoatPillar.SWARM_ARCHITECTURE] = FeatureImpact.STRENGTHENS
            moat_score += 0.3
            proposal.recommendations.append("Document unique capabilities vs generic agent frameworks")
        
        # Check for ecosystem features
        if any(keyword in feature_description.lower() for keyword in ["ecosystem", "integration", "marketplace", "ux"]):
            proposal.moat_impacts[MoatPillar.ECOSYSTEM_NETWORK] = FeatureImpact.STRENGTHENS
            moat_score += 0.2
            proposal.recommendations.append("Measure network effect and stickiness impact")
        
        # Check for compliance features
        if any(keyword in feature_description.lower() for keyword in ["compliance", "audit", "legal", "security"]):
            proposal.moat_impacts[MoatPillar.LEGAL_COMPLIANCE] = FeatureImpact.STRENGTHENS
            moat_score += 0.2
            proposal.recommendations.append("Document compliance improvements")
        
        # Determine if strengthens moat
        proposal.strengthens_moat = moat_score > 0.0
        proposal.moat_score = moat_score
        
        # Approval logic
        if moat_score >= 0.3:
            proposal.approved = True
            proposal.approval_reason = f"Strengthens moat significantly (score: {moat_score:.2f})"
        elif moat_score > 0.0:
            proposal.approved = True
            proposal.approval_reason = f"Strengthens moat moderately (score: {moat_score:.2f})"
        else:
            proposal.approved = False
            proposal.approval_reason = "Does not strengthen moat - consider adding moat-building elements"
        
        self._feature_proposals.append(proposal)
        
        logger.info(
            f"Validated feature '{feature_name}': "
            f"{'approved' if proposal.approved else 'not approved'} "
            f"(moat score: {moat_score:.2f})"
        )
        
        return proposal
    
    def measure_moat_strength(self) -> Dict[MoatPillar, MoatMetric]:
        """Measure current moat strength across all pillars."""
        metrics = {}
        
        # Proprietary data moat
        data_stats = self._data_warehouse.get_data_stats()
        data_advantage = data_stats["competitive_advantages"]["avg_advantage_ratio"]
        
        metrics[MoatPillar.PROPRIETARY_DATA] = MoatMetric(
            metric_id=f"moat_data_{int(datetime.utcnow().timestamp())}",
            pillar=MoatPillar.PROPRIETARY_DATA,
            strength=self._classify_strength(data_advantage),
            advantage_ratio=data_advantage,
            trend="improving",
            evidence_count=data_stats["records"]["total"],
        )
        
        # Execution infrastructure moat
        exec_stats = self._execution_moat.get_execution_moat_stats()
        exec_advantage = exec_stats["execution_edges"]["avg_edge_percentage"] / 100 + 1.0
        
        metrics[MoatPillar.EXECUTION_INFRA] = MoatMetric(
            metric_id=f"moat_exec_{int(datetime.utcnow().timestamp())}",
            pillar=MoatPillar.EXECUTION_INFRA,
            strength=self._classify_strength(exec_advantage),
            advantage_ratio=exec_advantage,
            trend="stable",
            evidence_count=exec_stats["latency"]["measurements"],
        )
        
        # Swarm architecture moat
        swarm_stats = self._swarm_moat.get_swarm_architecture_stats()
        swarm_advantage = swarm_stats["architecture_advantages"]["avg_advantage_percentage"] / 100 + 1.0
        
        metrics[MoatPillar.SWARM_ARCHITECTURE] = MoatMetric(
            metric_id=f"moat_swarm_{int(datetime.utcnow().timestamp())}",
            pillar=MoatPillar.SWARM_ARCHITECTURE,
            strength=self._classify_strength(swarm_advantage),
            advantage_ratio=swarm_advantage,
            trend="improving",
            evidence_count=swarm_stats["specialized_agents"]["total_metrics"],
        )
        
        # Ecosystem network moat
        ecosystem_stats = self._ecosystem_moat.get_ecosystem_moat_stats()
        network_value = ecosystem_stats["network_effects"]["total_network_value"]
        ecosystem_advantage = 1.5  # Estimated based on network effects
        
        metrics[MoatPillar.ECOSYSTEM_NETWORK] = MoatMetric(
            metric_id=f"moat_ecosystem_{int(datetime.utcnow().timestamp())}",
            pillar=MoatPillar.ECOSYSTEM_NETWORK,
            strength=self._classify_strength(ecosystem_advantage),
            advantage_ratio=ecosystem_advantage,
            trend="improving",
            evidence_count=ecosystem_stats["ecosystem"]["total_participants"],
        )
        
        # Legal compliance moat
        compliance_rate = ecosystem_stats["compliance"]["compliance_rate"]
        compliance_advantage = 1.3  # Estimated based on compliance
        
        metrics[MoatPillar.LEGAL_COMPLIANCE] = MoatMetric(
            metric_id=f"moat_legal_{int(datetime.utcnow().timestamp())}",
            pillar=MoatPillar.LEGAL_COMPLIANCE,
            strength=self._classify_strength(compliance_advantage),
            advantage_ratio=compliance_advantage,
            trend="stable",
            evidence_count=ecosystem_stats["compliance"]["total_records"],
        )
        
        self._moat_metrics.extend(metrics.values())
        
        logger.info("Measured moat strength across all pillars")
        
        return metrics
    
    def _classify_strength(self, advantage_ratio: float) -> MoatStrength:
        """Classify moat strength based on advantage ratio."""
        if advantage_ratio >= 2.0:
            return MoatStrength.DOMINANT
        elif advantage_ratio >= 1.5:
            return MoatStrength.STRONG
        elif advantage_ratio >= 1.2:
            return MoatStrength.MODERATE
        else:
            return MoatStrength.WEAK
    
    def register_synergy(
        self,
        pillar_a: MoatPillar,
        pillar_b: MoatPillar,
        synergy_type: str,
        synergy_strength: float,
        description: str,
        examples: List[str],
    ) -> MoatSynergy:
        """Register cross-pillar synergy."""
        synergy_id = f"synergy_{pillar_a.value}_{pillar_b.value}"
        
        synergy = MoatSynergy(
            synergy_id=synergy_id,
            pillar_a=pillar_a,
            pillar_b=pillar_b,
            synergy_type=synergy_type,
            synergy_strength=synergy_strength,
            description=description,
            examples=examples,
        )
        
        self._synergies.append(synergy)
        
        return synergy
    
    def detect_erosion_risks(self) -> List[MoatErosionRisk]:
        """Detect moat erosion risks."""
        risks = []
        
        # Check data moat
        data_stats = self._data_warehouse.get_data_stats()
        if data_stats["records"]["labeled_percentage"] < 70:
            risks.append(MoatErosionRisk(
                risk_id=f"risk_data_{int(datetime.utcnow().timestamp())}",
                pillar=MoatPillar.PROPRIETARY_DATA,
                risk_type="low_labeling_rate",
                risk_level="medium",
                description="Data labeling rate below 70% - reduces training effectiveness",
                mitigation_actions=[
                    "Increase automated labeling",
                    "Hire data labeling team",
                    "Implement active learning",
                ],
            ))
        
        # Check execution moat
        exec_stats = self._execution_moat.get_execution_moat_stats()
        if exec_stats["latency"]["avg_latency_ms"] > 10:
            risks.append(MoatErosionRisk(
                risk_id=f"risk_exec_{int(datetime.utcnow().timestamp())}",
                pillar=MoatPillar.EXECUTION_INFRA,
                risk_type="high_latency",
                risk_level="high",
                description="Average latency above 10ms - execution edge at risk",
                mitigation_actions=[
                    "Optimize RPC routing",
                    "Add more co-location regions",
                    "Upgrade network infrastructure",
                ],
            ))
        
        # Check ecosystem moat
        ecosystem_stats = self._ecosystem_moat.get_ecosystem_moat_stats()
        if ecosystem_stats["product_stickiness"]["avg_day_30_retention"] < 0.5:
            risks.append(MoatErosionRisk(
                risk_id=f"risk_ecosystem_{int(datetime.utcnow().timestamp())}",
                pillar=MoatPillar.ECOSYSTEM_NETWORK,
                risk_type="low_retention",
                risk_level="medium",
                description="Day 30 retention below 50% - product stickiness at risk",
                mitigation_actions=[
                    "Improve onboarding UX",
                    "Add more sticky features",
                    "Increase switching costs",
                ],
            ))
        
        self._erosion_risks.extend(risks)
        
        if risks:
            logger.warning(f"Detected {len(risks)} moat erosion risks")
        
        return risks
    
    def get_moat_orchestrator_stats(self) -> Dict[str, Any]:
        """Get moat orchestrator statistics."""
        
        # Principles
        principles_by_pillar = {
            pillar.value: sum(
                1 for p in self._principles.values()
                if p.pillar == pillar
            )
            for pillar in MoatPillar
        }
        
        # Feature proposals
        approved_proposals = sum(1 for p in self._feature_proposals if p.approved)
        avg_moat_score = (
            sum(p.moat_score for p in self._feature_proposals) /
            len(self._feature_proposals)
            if self._feature_proposals else 0.0
        )
        
        # Moat metrics
        latest_metrics = {}
        for pillar in MoatPillar:
            pillar_metrics = [m for m in self._moat_metrics if m.pillar == pillar]
            if pillar_metrics:
                latest_metrics[pillar.value] = {
                    "strength": pillar_metrics[-1].strength.value,
                    "advantage_ratio": pillar_metrics[-1].advantage_ratio,
                }
        
        # Erosion risks
        risks_by_level = {
            "critical": sum(1 for r in self._erosion_risks if r.risk_level == "critical"),
            "high": sum(1 for r in self._erosion_risks if r.risk_level == "high"),
            "medium": sum(1 for r in self._erosion_risks if r.risk_level == "medium"),
            "low": sum(1 for r in self._erosion_risks if r.risk_level == "low"),
        }
        
        return {
            "principles": {
                "total": len(self._principles),
                "by_pillar": principles_by_pillar,
            },
            "feature_proposals": {
                "total": len(self._feature_proposals),
                "approved": approved_proposals,
                "approval_rate": (
                    approved_proposals / len(self._feature_proposals)
                    if self._feature_proposals else 0.0
                ),
                "avg_moat_score": avg_moat_score,
            },
            "moat_metrics": latest_metrics,
            "synergies": {
                "total": len(self._synergies),
                "avg_strength": (
                    sum(s.synergy_strength for s in self._synergies) /
                    len(self._synergies)
                    if self._synergies else 0.0
                ),
            },
            "erosion_risks": {
                "total": len(self._erosion_risks),
                "by_level": risks_by_level,
            },
        }


_moat_orchestrator: Optional[MoatOrchestrator] = None


def get_moat_orchestrator() -> MoatOrchestrator:
    """Get global MoatOrchestrator instance."""
    global _moat_orchestrator
    if _moat_orchestrator is None:
        _moat_orchestrator = MoatOrchestrator()
    return _moat_orchestrator
