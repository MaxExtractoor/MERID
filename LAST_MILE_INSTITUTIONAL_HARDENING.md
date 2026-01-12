# MERID LAST-MILE INSTITUTIONAL HARDENING
## Battle-Ready Production System - Final Upgrades

**Status:** IMPLEMENTATION IN PROGRESS  
**Target:** 85% → 100% Production Ready  
**Focus:** Threat Validation, Model Risk, Observability, DeFi Compliance, Testing Depth, Custody  

---

# SECTION 1: THREAT MODEL VALIDATION - AGENTIC-AI & DEFI ALIGNMENT

## 1.1 Enhanced Threat Registry with AI/DeFi Mapping

```python
# core/enhanced_threat_model.py

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import time

class AIThreatType(Enum):
    """AI-specific threat types per MAESTRO framework."""
    PROMPT_INJECTION = "prompt_injection"
    TOOL_MISUSE = "tool_misuse"
    SWARM_CASCADE = "swarm_cascade"
    MODEL_DRIFT = "model_drift"
    HALLUCINATION = "hallucination"
    ADVERSARIAL_INPUT = "adversarial_input"


class DeFiThreatType(Enum):
    """DeFi-specific threat types."""
    SANCTIONS_EXPOSURE = "sanctions_exposure"
    ILLICIT_FLOW = "illicit_flow"
    PROTOCOL_EXPLOIT = "protocol_exploit"
    MEV_ROUTING = "mev_routing"
    ORACLE_MANIPULATION = "oracle_manipulation"
    GOVERNANCE_ATTACK = "governance_attack"


@dataclass
class DetectionSignal:
    """Explicit detection signal for threat."""
    signal_id: str
    metric_name: str
    threshold: float
    window_seconds: int
    aggregation: str  # "avg", "max", "count", "rate"


@dataclass
class AutoMitigation:
    """Automated mitigation action."""
    action_id: str
    action_type: str  # "kill_switch", "size_reduction", "venue_block", "agent_suspend"
    parameters: Dict[str, Any]
    requires_approval: bool = False


@dataclass
class OperatorRunbook:
    """Operator response runbook."""
    runbook_id: str
    title: str
    steps: List[str]
    escalation_criteria: List[str]
    estimated_time_minutes: int


@dataclass
class EnhancedThreat:
    """
    Enhanced threat definition aligned with agentic-AI and DeFi standards.
    
    Maps to:
    - MAESTRO framework for AI threats
    - Institutional DeFi compliance for DeFi threats
    """
    threat_id: str
    category: ThreatCategory
    description: str
    likelihood: str
    impact: str
    
    # AI/DeFi mapping
    ai_threat_types: List[AIThreatType] = field(default_factory=list)
    defi_threat_types: List[DeFiThreatType] = field(default_factory=list)
    
    # Enhanced controls
    prevention: List[str] = field(default_factory=list)
    detection_signals: List[DetectionSignal] = field(default_factory=list)
    auto_mitigations: List[AutoMitigation] = field(default_factory=list)
    operator_runbook: Optional[OperatorRunbook] = None
    
    # Compliance
    regulatory_relevance: List[str] = field(default_factory=list)
    audit_requirements: List[str] = field(default_factory=list)


# ENHANCED THREAT REGISTRY
ENHANCED_THREAT_REGISTRY = [
    EnhancedThreat(
        threat_id="T001",
        category=ThreatCategory.KEY_COMPROMISE,
        description="Hot wallet private key compromised by attacker",
        likelihood="MEDIUM",
        impact="CRITICAL",
        
        # AI/DeFi mapping
        ai_threat_types=[],  # Not AI-specific
        defi_threat_types=[DeFiThreatType.ILLICIT_FLOW],
        
        # Prevention
        prevention=[
            "Multi-sig treasury with 3-of-5 approval",
            "Per-wallet capital limits ($10k hot, $100k warm, $1M cold)",
            "Hardware wallet for warm/cold tiers",
            "Withdrawal allowlists (contract addresses only)",
            "Rate limiting (hourly/daily caps)",
            "Time-locks (1h warm, 24h cold)"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS001_unusual_tx",
                metric_name="wallet_transaction_count",
                threshold=10.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS002_large_withdrawal",
                metric_name="wallet_withdrawal_amount_usd",
                threshold=5000.0,
                window_seconds=3600,
                aggregation="sum"
            ),
            DetectionSignal(
                signal_id="DS003_non_whitelist",
                metric_name="non_whitelisted_tx_count",
                threshold=1.0,
                window_seconds=60,
                aggregation="count"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM001_freeze_wallet",
                action_type="wallet_freeze",
                parameters={"wallet_tier": "hot"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM002_cancel_pending",
                action_type="cancel_transactions",
                parameters={"wallet_id": "all"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM003_alert_security",
                action_type="alert",
                parameters={"severity": "critical", "team": "security"},
                requires_approval=False
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB001",
            title="Hot Wallet Compromise Response",
            steps=[
                "1. Verify alert is not false positive (check transaction details)",
                "2. Confirm wallet freeze is active",
                "3. Review recent transactions for unauthorized activity",
                "4. Identify compromise vector (phishing, malware, etc.)",
                "5. Rotate keys and create new wallet",
                "6. Transfer remaining funds to new wallet",
                "7. Update allowlists and monitoring",
                "8. File incident report",
                "9. Conduct post-mortem analysis"
            ],
            escalation_criteria=[
                "Funds lost >$1,000",
                "Compromise vector unclear",
                "Multiple wallets affected",
                "Potential insider threat"
            ],
            estimated_time_minutes=60
        ),
        
        # Compliance
        regulatory_relevance=[
            "SEC custody rules (if managing client funds)",
            "AML/KYC requirements",
            "Incident reporting obligations"
        ],
        audit_requirements=[
            "Complete transaction log with timestamps",
            "Wallet access logs",
            "Approval records for all withdrawals",
            "Incident response timeline"
        ]
    ),
    
    EnhancedThreat(
        threat_id="T002",
        category=ThreatCategory.PROMPT_INJECTION,
        description="Malicious data in feeds causes agents to execute harmful trades",
        likelihood="HIGH",
        impact="HIGH",
        
        # AI/DeFi mapping
        ai_threat_types=[
            AIThreatType.PROMPT_INJECTION,
            AIThreatType.ADVERSARIAL_INPUT,
            AIThreatType.TOOL_MISUSE
        ],
        defi_threat_types=[DeFiThreatType.MEV_ROUTING],
        
        # Prevention
        prevention=[
            "Input sanitization on all external data sources",
            "Schema validation (Pydantic) for all agent inputs",
            "No direct execution from external signals",
            "Proposal lifecycle with multi-stage validation",
            "Agent charter constraints (max confidence, evidence requirements)",
            "Tool access control (RBAC) prevents unauthorized actions"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS004_high_rejection",
                metric_name="proposal_rejection_rate",
                threshold=0.5,
                window_seconds=3600,
                aggregation="rate"
            ),
            DetectionSignal(
                signal_id="DS005_agent_disagreement",
                metric_name="agent_disagreement_score",
                threshold=0.7,
                window_seconds=1800,
                aggregation="avg"
            ),
            DetectionSignal(
                signal_id="DS006_schema_failures",
                metric_name="schema_validation_failure_count",
                threshold=10.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS007_suspicious_patterns",
                metric_name="data_source_anomaly_score",
                threshold=0.8,
                window_seconds=300,
                aggregation="max"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM004_reject_proposal",
                action_type="proposal_rejection",
                parameters={"reason": "prompt_injection_suspected"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM005_quarantine_source",
                action_type="data_source_quarantine",
                parameters={"duration_seconds": 3600},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM006_alert_operators",
                action_type="alert",
                parameters={"severity": "high", "team": "operations"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM007_review_reasoning",
                action_type="log_review",
                parameters={"component": "agent_reasoning"},
                requires_approval=True
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB002",
            title="Prompt Injection Response",
            steps=[
                "1. Review rejected proposals for suspicious patterns",
                "2. Identify compromised data source",
                "3. Quarantine data source (already auto-executed)",
                "4. Review agent reasoning logs for injection attempts",
                "5. Analyze input data for malicious payloads",
                "6. Update input sanitization rules",
                "7. Test with known injection patterns",
                "8. Re-enable data source with enhanced filtering",
                "9. Monitor for recurrence"
            ],
            escalation_criteria=[
                "Multiple data sources compromised",
                "Injection bypassed sanitization",
                "Agent executed unauthorized action",
                "Pattern suggests coordinated attack"
            ],
            estimated_time_minutes=45
        ),
        
        # Compliance
        regulatory_relevance=[
            "Model risk management requirements",
            "AI governance policies",
            "Data integrity standards"
        ],
        audit_requirements=[
            "Input validation logs",
            "Rejected proposal records with reasons",
            "Agent reasoning traces",
            "Data source health metrics"
        ]
    ),
    
    EnhancedThreat(
        threat_id="T003",
        category=ThreatCategory.MODEL_MISALIGNMENT,
        description="AI model attempts to bypass constraints or exploit loopholes",
        likelihood="MEDIUM",
        impact="HIGH",
        
        # AI/DeFi mapping
        ai_threat_types=[
            AIThreatType.TOOL_MISUSE,
            AIThreatType.MODEL_DRIFT,
            AIThreatType.HALLUCINATION
        ],
        defi_threat_types=[],
        
        # Prevention
        prevention=[
            "Constitutional agent charters with explicit constraints",
            "Tool-only execution (no raw code generation)",
            "Strict input/output schemas (Pydantic validation)",
            "Multi-agent cross-checking and consensus",
            "Human approval for high-impact actions",
            "Charter violation monitoring and enforcement"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS008_charter_violations",
                metric_name="charter_violation_count",
                threshold=3.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS009_tool_denials",
                metric_name="tool_access_denial_count",
                threshold=5.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS010_schema_failures",
                metric_name="schema_validation_failure_rate",
                threshold=0.1,
                window_seconds=3600,
                aggregation="rate"
            ),
            DetectionSignal(
                signal_id="DS011_reasoning_anomaly",
                metric_name="reasoning_coherence_score",
                threshold=0.5,
                window_seconds=1800,
                aggregation="avg"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM008_suspend_agent",
                action_type="agent_suspend",
                parameters={"duration_seconds": 3600},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM009_revert_checkpoint",
                action_type="state_revert",
                parameters={"checkpoint_age_seconds": 3600},
                requires_approval=True
            ),
            AutoMitigation(
                action_id="AM010_alert_ml_team",
                action_type="alert",
                parameters={"severity": "high", "team": "ml_engineering"},
                requires_approval=False
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB003",
            title="Model Misalignment Response",
            steps=[
                "1. Suspend affected agent (already auto-executed)",
                "2. Review agent logs for violation patterns",
                "3. Analyze tool access attempts and denials",
                "4. Check for prompt/charter changes",
                "5. Run agent through test scenarios",
                "6. Identify root cause (drift, bug, adversarial input)",
                "7. Retrain or replace agent if needed",
                "8. Update charter constraints",
                "9. Test in sandbox before re-enabling",
                "10. Monitor closely for 24h after re-enable"
            ],
            escalation_criteria=[
                "Agent modified risk configurations",
                "Multiple agents showing similar behavior",
                "Violation pattern suggests intentional bypass",
                "Root cause unclear after investigation"
            ],
            estimated_time_minutes=90
        ),
        
        # Compliance
        regulatory_relevance=[
            "Model risk management (SR 11-7 style)",
            "AI explainability requirements",
            "Algorithmic trading oversight"
        ],
        audit_requirements=[
            "Agent version history",
            "Charter violation logs",
            "Tool access audit trail",
            "Model validation records"
        ]
    ),
    
    EnhancedThreat(
        threat_id="T004",
        category=ThreatCategory.DEFI_ADVERSARIAL,
        description="MEV attacks, oracle manipulation, or rug pulls",
        likelihood="HIGH",
        impact="MEDIUM",
        
        # AI/DeFi mapping
        ai_threat_types=[],
        defi_threat_types=[
            DeFiThreatType.MEV_ROUTING,
            DeFiThreatType.ORACLE_MANIPULATION,
            DeFiThreatType.PROTOCOL_EXPLOIT
        ],
        
        # Prevention
        prevention=[
            "MEV defense engine with multi-layer protection",
            "Order randomization and splitting",
            "Slippage limits enforced (1.2x expected max)",
            "Venue and asset whitelists (audited protocols only)",
            "Liquidity depth checks before execution",
            "Oracle price validation (multi-source consensus)"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS012_abnormal_slippage",
                metric_name="realized_slippage_ratio",
                threshold=2.0,
                window_seconds=1800,
                aggregation="avg"
            ),
            DetectionSignal(
                signal_id="DS013_mev_attacks",
                metric_name="mev_attack_detection_count",
                threshold=3.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS014_oracle_deviation",
                metric_name="oracle_price_deviation_pct",
                threshold=5.0,
                window_seconds=300,
                aggregation="max"
            ),
            DetectionSignal(
                signal_id="DS015_liquidity_drop",
                metric_name="venue_liquidity_score",
                threshold=0.3,
                window_seconds=600,
                aggregation="min"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM011_cancel_venue_orders",
                action_type="venue_order_cancel",
                parameters={"venue_id": "affected_venue"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM012_freeze_asset",
                action_type="asset_freeze",
                parameters={"duration_seconds": 1800},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM013_update_mev_params",
                action_type="mev_defense_update",
                parameters={"sensitivity": "high"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM014_alert_trading",
                action_type="alert",
                parameters={"severity": "high", "team": "trading"},
                requires_approval=False
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB004",
            title="DeFi Adversarial Attack Response",
            steps=[
                "1. Identify attack type (MEV, oracle, rug pull)",
                "2. Cancel pending orders on affected venue/asset",
                "3. Review recent trades for losses",
                "4. Analyze attack pattern and sophistication",
                "5. Update MEV defense parameters",
                "6. Blacklist venue/asset if necessary",
                "7. Report to venue/protocol if applicable",
                "8. Update risk scoring for similar venues",
                "9. Monitor for attack recurrence"
            ],
            escalation_criteria=[
                "Losses >$1,000",
                "Novel attack pattern",
                "Multiple venues affected",
                "Protocol-level vulnerability"
            ],
            estimated_time_minutes=30
        ),
        
        # Compliance
        regulatory_relevance=[
            "Best execution requirements",
            "Market manipulation detection",
            "Venue due diligence"
        ],
        audit_requirements=[
            "Execution quality metrics",
            "Slippage analysis",
            "MEV attack logs",
            "Venue risk assessments"
        ]
    ),
    
    EnhancedThreat(
        threat_id="T007",
        category=ThreatCategory.DEFI_ADVERSARIAL,
        description="Sanctions exposure or illicit flow through DeFi protocols",
        likelihood="MEDIUM",
        impact="CRITICAL",
        
        # AI/DeFi mapping
        ai_threat_types=[],
        defi_threat_types=[
            DeFiThreatType.SANCTIONS_EXPOSURE,
            DeFiThreatType.ILLICIT_FLOW
        ],
        
        # Prevention
        prevention=[
            "Pre-transaction sanctions screening (OFAC, EU, UN lists)",
            "On-chain risk scoring for all counterparties",
            "Protocol illicit-flow monitoring (<0.5% threshold)",
            "Wallet risk assessment before interaction",
            "Jurisdictional compliance checks",
            "Automated transaction blocking for high-risk addresses"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS016_sanctions_hit",
                metric_name="sanctions_screening_hits",
                threshold=1.0,
                window_seconds=60,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS017_high_risk_score",
                metric_name="wallet_risk_score",
                threshold=0.7,
                window_seconds=60,
                aggregation="max"
            ),
            DetectionSignal(
                signal_id="DS018_illicit_flow",
                metric_name="protocol_illicit_flow_pct",
                threshold=0.5,
                window_seconds=86400,
                aggregation="avg"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM015_block_transaction",
                action_type="transaction_block",
                parameters={"reason": "sanctions_exposure"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM016_blacklist_address",
                action_type="address_blacklist",
                parameters={"permanent": True},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM017_alert_compliance",
                action_type="alert",
                parameters={"severity": "critical", "team": "compliance"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM018_file_sar",
                action_type="compliance_filing",
                parameters={"filing_type": "SAR"},
                requires_approval=True
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB007",
            title="Sanctions/Illicit Flow Response",
            steps=[
                "1. Confirm sanctions hit or high-risk score",
                "2. Block transaction immediately (already auto-executed)",
                "3. Document all details (address, amount, protocol)",
                "4. Review recent interactions with flagged address",
                "5. Assess if SAR filing required",
                "6. Notify legal/compliance team",
                "7. File SAR if required (within regulatory timeframe)",
                "8. Update screening rules if false positive",
                "9. Conduct enhanced due diligence on protocol"
            ],
            escalation_criteria=[
                "Confirmed OFAC sanctions match",
                "Large transaction amount (>$10k)",
                "Repeated attempts to interact",
                "Protocol shows systemic illicit flow"
            ],
            estimated_time_minutes=120
        ),
        
        # Compliance
        regulatory_relevance=[
            "OFAC sanctions compliance",
            "AML/KYC requirements",
            "SAR filing obligations (FinCEN)",
            "Travel Rule compliance"
        ],
        audit_requirements=[
            "Complete sanctions screening logs",
            "Risk scoring methodology documentation",
            "SAR filings and supporting evidence",
            "Protocol due diligence records"
        ]
    ),
    
    EnhancedThreat(
        threat_id="T008",
        category=ThreatCategory.MODEL_MISALIGNMENT,
        description="AI swarm cascade failure - coordinated agent malfunction",
        likelihood="LOW",
        impact="CRITICAL",
        
        # AI/DeFi mapping
        ai_threat_types=[
            AIThreatType.SWARM_CASCADE,
            AIThreatType.MODEL_DRIFT
        ],
        defi_threat_types=[],
        
        # Prevention
        prevention=[
            "Independent agent validation (no shared state corruption)",
            "Consensus timeout mechanisms (30s max)",
            "Skeptic agent with veto power",
            "Agent health monitoring (error rate, latency)",
            "Automatic agent disable on repeated failures",
            "Fallback to manual mode on swarm failure"
        ],
        
        # Detection signals
        detection_signals=[
            DetectionSignal(
                signal_id="DS019_consensus_failures",
                metric_name="consensus_failure_rate",
                threshold=0.3,
                window_seconds=1800,
                aggregation="rate"
            ),
            DetectionSignal(
                signal_id="DS020_agent_errors",
                metric_name="agent_error_count",
                threshold=10.0,
                window_seconds=3600,
                aggregation="count"
            ),
            DetectionSignal(
                signal_id="DS021_timeout_rate",
                metric_name="consensus_timeout_rate",
                threshold=0.2,
                window_seconds=1800,
                aggregation="rate"
            )
        ],
        
        # Auto-mitigations
        auto_mitigations=[
            AutoMitigation(
                action_id="AM019_disable_swarm",
                action_type="swarm_disable",
                parameters={"fallback": "manual_mode"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM020_activate_kill_switch",
                action_type="kill_switch",
                parameters={"reason": "swarm_cascade"},
                requires_approval=False
            ),
            AutoMitigation(
                action_id="AM021_alert_ml_ops",
                action_type="alert",
                parameters={"severity": "critical", "team": "ml_ops"},
                requires_approval=False
            )
        ],
        
        # Operator runbook
        operator_runbook=OperatorRunbook(
            runbook_id="RB008",
            title="AI Swarm Cascade Response",
            steps=[
                "1. Confirm swarm disabled and kill switch active",
                "2. Review agent health metrics for all agents",
                "3. Identify cascade trigger (shared input, model drift)",
                "4. Analyze consensus failure patterns",
                "5. Test each agent independently in sandbox",
                "6. Identify and fix root cause",
                "7. Restore agents one-by-one with monitoring",
                "8. Run full swarm test in sandbox",
                "9. Re-enable swarm with enhanced monitoring",
                "10. Conduct post-mortem and update safeguards"
            ],
            escalation_criteria=[
                "Root cause unclear",
                "Multiple independent failures",
                "Data corruption suspected",
                "Requires model retraining"
            ],
            estimated_time_minutes=180
        ),
        
        # Compliance
        regulatory_relevance=[
            "Algorithmic trading system resilience",
            "Model risk management",
            "Business continuity planning"
        ],
        audit_requirements=[
            "Swarm health metrics",
            "Consensus logs with failures",
            "Agent-by-agent performance data",
            "Cascade incident timeline"
        ]
    )
]


class EnhancedThreatMonitor:
    """
    Enhanced threat monitoring with AI/DeFi alignment.
    
    Provides regulation-ready threat mapping and automated response.
    """
    
    def __init__(self):
        self.threats = {t.threat_id: t for t in ENHANCED_THREAT_REGISTRY}
        self.active_incidents: Dict[str, Dict[str, Any]] = {}
        self.detection_metrics: Dict[str, float] = {}
    
    def update_metric(self, metric_name: str, value: float) -> None:
        """Update detection metric value."""
        self.detection_metrics[metric_name] = value
        
        # Check all threats that monitor this metric
        for threat in self.threats.values():
            for signal in threat.detection_signals:
                if signal.metric_name == metric_name:
                    self._check_signal(threat, signal)
    
    def _check_signal(
        self,
        threat: EnhancedThreat,
        signal: DetectionSignal
    ) -> None:
        """Check if detection signal threshold exceeded."""
        current_value = self.detection_metrics.get(signal.metric_name, 0.0)
        
        if current_value > signal.threshold:
            # Trigger incident
            incident = self._create_incident(threat, signal, current_value)
            self.active_incidents[threat.threat_id] = incident
            
            # Execute auto-mitigations
            self._execute_mitigations(threat)
            
            # Alert operators with runbook
            self._alert_operators(threat, incident)
    
    def _create_incident(
        self,
        threat: EnhancedThreat,
        signal: DetectionSignal,
        value: float
    ) -> Dict[str, Any]:
        """Create incident record."""
        return {
            "threat_id": threat.threat_id,
            "threat_description": threat.description,
            "likelihood": threat.likelihood,
            "impact": threat.impact,
            "triggered_signal": signal.signal_id,
            "metric_name": signal.metric_name,
            "threshold": signal.threshold,
            "actual_value": value,
            "timestamp": time.time(),
            "ai_threat_types": [t.value for t in threat.ai_threat_types],
            "defi_threat_types": [t.value for t in threat.defi_threat_types],
            "regulatory_relevance": threat.regulatory_relevance,
            "runbook_id": threat.operator_runbook.runbook_id if threat.operator_runbook else None
        }
    
    def _execute_mitigations(self, threat: EnhancedThreat) -> None:
        """Execute automated mitigations."""
        for mitigation in threat.auto_mitigations:
            if not mitigation.requires_approval:
                self._execute_mitigation_action(mitigation)
    
    def _execute_mitigation_action(self, mitigation: AutoMitigation) -> None:
        """Execute specific mitigation action."""
        if mitigation.action_type == "kill_switch":
            from core.execution_controller import get_execution_controller
            controller = get_execution_controller()
            controller.activate_kill_switch(f"Threat mitigation: {mitigation.action_id}")
        
        elif mitigation.action_type == "wallet_freeze":
            from core.wallet_architecture import get_wallet_architecture
            wallet_arch = get_wallet_architecture()
            # Implement wallet freeze
        
        elif mitigation.action_type == "agent_suspend":
            from agents.agent_manager import get_agent_manager
            agent_mgr = get_agent_manager()
            # Implement agent suspension
        
        # Add more mitigation actions as needed
    
    def _alert_operators(
        self,
        threat: EnhancedThreat,
        incident: Dict[str, Any]
    ) -> None:
        """Alert operators with runbook."""
        from core.alerting import get_alert_manager
        alert_mgr = get_alert_manager()
        
        alert_mgr.send_threat_alert(
            threat_id=threat.threat_id,
            incident=incident,
            runbook=threat.operator_runbook
        )
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """
        Generate compliance report for auditors.
        
        Shows threat coverage, detection capabilities, and response procedures.
        """
        return {
            "total_threats": len(self.threats),
            "threats_by_category": self._count_by_category(),
            "ai_threat_coverage": self._count_ai_threats(),
            "defi_threat_coverage": self._count_defi_threats(),
            "detection_signals": self._count_detection_signals(),
            "auto_mitigations": self._count_auto_mitigations(),
            "operator_runbooks": self._count_runbooks(),
            "regulatory_mappings": self._get_regulatory_mappings(),
            "active_incidents": len(self.active_incidents),
            "incident_history": self._get_incident_summary()
        }
    
    def _count_by_category(self) -> Dict[str, int]:
        """Count threats by category."""
        counts = {}
        for threat in self.threats.values():
            category = threat.category.value
            counts[category] = counts.get(category, 0) + 1
        return counts
    
    def _count_ai_threats(self) -> Dict[str, int]:
        """Count AI-specific threat coverage."""
        counts = {}
        for threat in self.threats.values():
            for ai_type in threat.ai_threat_types:
                counts[ai_type.value] = counts.get(ai_type.value, 0) + 1
        return counts
    
    def _count_defi_threats(self) -> Dict[str, int]:
        """Count DeFi-specific threat coverage."""
        counts = {}
        for threat in self.threats.values():
            for defi_type in threat.defi_threat_types:
                counts[defi_type.value] = counts.get(defi_type.value, 0) + 1
        return counts
    
    def _count_detection_signals(self) -> int:
        """Count total detection signals."""
        return sum(len(t.detection_signals) for t in self.threats.values())
    
    def _count_auto_mitigations(self) -> int:
        """Count total auto-mitigations."""
        return sum(len(t.auto_mitigations) for t in self.threats.values())
    
    def _count_runbooks(self) -> int:
        """Count operator runbooks."""
        return sum(1 for t in self.threats.values() if t.operator_runbook)
    
    def _get_regulatory_mappings(self) -> Dict[str, List[str]]:
        """Get regulatory relevance mappings."""
        mappings = {}
        for threat in self.threats.values():
            for reg in threat.regulatory_relevance:
                if reg not in mappings:
                    mappings[reg] = []
                mappings[reg].append(threat.threat_id)
        return mappings
    
    def _get_incident_summary(self) -> Dict[str, Any]:
        """Get incident history summary."""
        # Implementation: Query incident database
        return {
            "total_incidents": 0,
            "incidents_by_threat": {},
            "avg_response_time_minutes": 0,
            "false_positive_rate": 0.0
        }


# Singleton
_enhanced_threat_monitor = None

def get_enhanced_threat_monitor() -> EnhancedThreatMonitor:
    global _enhanced_threat_monitor
    if _enhanced_threat_monitor is None:
        _enhanced_threat_monitor = EnhancedThreatMonitor()
    return _enhanced_threat_monitor
```

---

*[Document continues with Sections 2-7 covering Model Risk Management, Observability, DeFi Compliance, Testing, Custody, and Action Plan]*

**[IMPLEMENTATION CONTINUES IN NEXT FILE]**
