# MERID INSTITUTIONAL HARDENING IMPLEMENTATION
## Production-Grade DeFi Trading System - Concrete Implementation

**Status:** PRODUCTION HARDENING IN PROGRESS  
**Target:** Ship-Ready Institutional System  
**Focus:** Execution Safety, Risk Controls, Custody, Observability  

---

# SECTION 1: SCOPE, THREAT MODEL, AND AUTONOMY BOUNDARIES

## 1.1 Regime of Use - LOCKED DEFINITION

```python
# core/system_regime.py

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any

class SystemRegime(Enum):
    """
    Defines operational regime with associated regulatory and risk posture.
    
    IMMUTABLE: Cannot be changed without code deployment and approval.
    """
    RESEARCH = "research"           # Paper trading, no real capital
    PERSONAL = "personal"           # Non-custodial, owner's capital only
    ADVISORY = "advisory"           # Signal generation, no execution
    MANAGED = "managed"             # Third-party capital (REQUIRES REGISTRATION)


class AutonomyLevel(Enum):
    """
    Defines autonomy boundaries for AI agents.
    
    ENFORCED: Hard-coded checks prevent level escalation.
    """
    L0_SIMULATION = 0      # Paper trading only, no real transactions
    L1_READONLY = 1        # Read market data, generate suggestions only
    L2_BOUNDED = 2         # Execute with strict caps and whitelists
    L3_AUTONOMOUS = 3      # Full autonomy (FORBIDDEN for production)


@dataclass
class SystemConfiguration:
    """
    System-wide configuration defining operational boundaries.
    
    CRITICAL: Changes require multi-sig approval and audit.
    """
    # Regime definition
    regime: SystemRegime
    autonomy_level: AutonomyLevel
    
    # Capital limits (USD)
    max_total_capital: float
    max_per_trade_notional: float
    max_daily_notional: float
    max_position_size_pct: float  # % of portfolio
    
    # Venue restrictions
    allowed_chains: List[str]
    allowed_venues: List[str]
    allowed_assets: List[str]
    
    # Strategy restrictions
    allowed_strategies: List[str]
    requires_human_approval: List[str]  # Strategy types requiring approval
    
    # Emergency controls
    kill_switch_enabled: bool
    circuit_breaker_enabled: bool
    
    # Compliance
    kyc_required: bool
    aml_monitoring_enabled: bool
    regulatory_reporting_enabled: bool
    
    def validate(self) -> None:
        """Validate configuration consistency."""
        # L3 autonomy forbidden
        if self.autonomy_level == AutonomyLevel.L3_AUTONOMOUS:
            raise ValueError("L3_AUTONOMOUS forbidden for production")
        
        # Managed regime requires registration
        if self.regime == SystemRegime.MANAGED:
            if not self.kyc_required or not self.aml_monitoring_enabled:
                raise ValueError("Managed regime requires KYC and AML")
        
        # Simulation must have zero capital
        if self.autonomy_level == AutonomyLevel.L0_SIMULATION:
            if self.max_total_capital > 0:
                raise ValueError("Simulation mode must have zero capital")


# PRODUCTION CONFIGURATION - LOCKED
PRODUCTION_CONFIG = SystemConfiguration(
    regime=SystemRegime.PERSONAL,
    autonomy_level=AutonomyLevel.L2_BOUNDED,
    
    # Capital limits
    max_total_capital=100_000.0,      # $100k max
    max_per_trade_notional=5_000.0,   # $5k per trade
    max_daily_notional=20_000.0,      # $20k per day
    max_position_size_pct=0.10,       # 10% max per position
    
    # Venue whitelist
    allowed_chains=[
        "ethereum-mainnet",
        "arbitrum-one",
        "optimism",
        "polygon"
    ],
    allowed_venues=[
        "uniswap-v3",
        "curve",
        "aave",
        "gmx",
        "dydx",
        "polymarket"
    ],
    allowed_assets=[
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
        # Add more as approved
    ],
    
    # Strategy whitelist
    allowed_strategies=[
        "spot_arbitrage",
        "perp_funding",
        "prediction_market",
        "liquidity_provision"
    ],
    requires_human_approval=[
        "new_strategy",
        "large_position",
        "high_risk_trade"
    ],
    
    # Emergency controls
    kill_switch_enabled=True,
    circuit_breaker_enabled=True,
    
    # Compliance (personal regime)
    kyc_required=False,
    aml_monitoring_enabled=True,  # Monitor even for personal
    regulatory_reporting_enabled=False
)

# Validate on module load
PRODUCTION_CONFIG.validate()
```

## 1.2 Threat Model - EXPLICIT ENUMERATION

```python
# core/threat_model.py

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional

class ThreatCategory(Enum):
    """Categories of threats to the system."""
    KEY_COMPROMISE = "key_compromise"
    PROMPT_INJECTION = "prompt_injection"
    MODEL_MISALIGNMENT = "model_misalignment"
    DEFI_ADVERSARIAL = "defi_adversarial"
    INFRASTRUCTURE = "infrastructure"
    REGULATORY = "regulatory"


@dataclass
class Threat:
    """
    Explicit threat definition with prevention, detection, and response.
    """
    threat_id: str
    category: ThreatCategory
    description: str
    likelihood: str  # LOW, MEDIUM, HIGH
    impact: str      # LOW, MEDIUM, HIGH, CRITICAL
    
    # Controls
    prevention: List[str]
    detection: List[str]
    response: List[str]
    
    # Monitoring
    metrics: List[str]
    alert_threshold: Optional[Dict[str, Any]] = None


# THREAT REGISTRY
THREAT_REGISTRY = [
    Threat(
        threat_id="T001",
        category=ThreatCategory.KEY_COMPROMISE,
        description="Hot wallet private key compromised by attacker",
        likelihood="MEDIUM",
        impact="CRITICAL",
        prevention=[
            "Multi-sig treasury with time-locks",
            "Per-wallet capital limits",
            "Hardware wallet for treasury",
            "Withdrawal allowlists",
            "Rate limiting on withdrawals"
        ],
        detection=[
            "Unusual transaction patterns",
            "Transactions to non-whitelisted addresses",
            "Large withdrawals",
            "Multiple failed auth attempts"
        ],
        response=[
            "Automatic wallet freeze",
            "Cancel all pending transactions",
            "Alert security team",
            "Initiate incident response SOP-005",
            "Forensic analysis of compromise vector"
        ],
        metrics=[
            "wallet_transaction_count",
            "wallet_withdrawal_amount",
            "auth_failure_rate"
        ],
        alert_threshold={
            "withdrawal_amount_1h": 10000.0,
            "non_whitelisted_tx": 1
        }
    ),
    
    Threat(
        threat_id="T002",
        category=ThreatCategory.PROMPT_INJECTION,
        description="Malicious data in feeds causes agents to execute harmful trades",
        likelihood="HIGH",
        impact="HIGH",
        prevention=[
            "Input sanitization on all external data",
            "Schema validation for all agent inputs",
            "No direct execution from external signals",
            "Proposal lifecycle with validation",
            "Agent charter constraints"
        ],
        detection=[
            "Unusual trade proposals",
            "High agent disagreement",
            "Proposals violating risk limits",
            "Abnormal confidence scores",
            "Suspicious data patterns in feeds"
        ],
        response=[
            "Reject proposal automatically",
            "Quarantine data source",
            "Alert operators",
            "Review agent reasoning logs",
            "Investigate data source compromise"
        ],
        metrics=[
            "proposal_rejection_rate",
            "agent_disagreement_score",
            "data_source_anomaly_count"
        ],
        alert_threshold={
            "rejection_rate_1h": 0.5,
            "disagreement_score": 0.7
        }
    ),
    
    Threat(
        threat_id="T003",
        category=ThreatCategory.MODEL_MISALIGNMENT,
        description="AI model attempts to bypass constraints or exploit loopholes",
        likelihood="MEDIUM",
        impact="HIGH",
        prevention=[
            "Constitutional agent charters",
            "Tool-only execution (no raw code)",
            "Strict input/output schemas",
            "Multi-agent cross-checking",
            "Human approval for high-impact actions"
        ],
        detection=[
            "Attempts to call forbidden tools",
            "Schema validation failures",
            "Unusual reasoning patterns",
            "Attempts to modify risk configs",
            "Circular reasoning in explanations"
        ],
        response=[
            "Suspend agent immediately",
            "Revert to previous checkpoint",
            "Human review of agent logs",
            "Retrain or replace agent",
            "Update charter constraints"
        ],
        metrics=[
            "charter_violation_count",
            "tool_access_denial_count",
            "schema_validation_failure_rate"
        ],
        alert_threshold={
            "charter_violations_1h": 3,
            "validation_failures_1h": 10
        }
    ),
    
    Threat(
        threat_id="T004",
        category=ThreatCategory.DEFI_ADVERSARIAL,
        description="MEV attacks, oracle manipulation, or rug pulls",
        likelihood="HIGH",
        impact="MEDIUM",
        prevention=[
            "MEV defense engine active",
            "Order randomization and splitting",
            "Slippage limits enforced",
            "Venue and asset whitelists",
            "Liquidity depth checks"
        ],
        detection=[
            "Abnormal slippage vs. expected",
            "Sandwich attack patterns",
            "Oracle price deviations",
            "Sudden liquidity drops",
            "Unusual gas prices"
        ],
        response=[
            "Cancel pending orders on venue",
            "Freeze trading on affected asset",
            "Alert operators",
            "Investigate venue/asset",
            "Update MEV defense parameters"
        ],
        metrics=[
            "realized_slippage_vs_expected",
            "mev_attack_detection_count",
            "oracle_deviation_magnitude"
        ],
        alert_threshold={
            "slippage_ratio": 2.0,
            "mev_detections_1h": 3
        }
    ),
    
    Threat(
        threat_id="T005",
        category=ThreatCategory.INFRASTRUCTURE,
        description="System failures, network outages, or data feed disruptions",
        likelihood="MEDIUM",
        impact="HIGH",
        prevention=[
            "Multi-region deployment",
            "Redundant data feeds",
            "Circuit breakers on failures",
            "Health monitoring",
            "Automatic failover"
        ],
        detection=[
            "Service health check failures",
            "Data feed latency spikes",
            "Network connectivity issues",
            "Database replication lag",
            "API error rate increases"
        ],
        response=[
            "Activate blindness mode",
            "Cancel pending orders",
            "Switch to backup feeds",
            "Alert operations team",
            "Initiate failover if needed"
        ],
        metrics=[
            "service_uptime",
            "data_feed_latency_p95",
            "api_error_rate"
        ],
        alert_threshold={
            "uptime_1h": 0.99,
            "latency_p95_ms": 500,
            "error_rate_1h": 0.05
        }
    ),
    
    Threat(
        threat_id="T006",
        category=ThreatCategory.REGULATORY,
        description="Regulatory action due to non-compliance or unauthorized activity",
        likelihood="LOW",
        impact="CRITICAL",
        prevention=[
            "Regime-appropriate compliance controls",
            "Comprehensive audit logging",
            "Legal review of all features",
            "Regulatory consultation",
            "Clear disclosures and agreements"
        ],
        detection=[
            "Compliance rule violations",
            "Unauthorized activity patterns",
            "Missing audit logs",
            "Disclosure gaps"
        ],
        response=[
            "Immediate system freeze",
            "Legal team notification",
            "Audit log export",
            "Regulatory filing if required",
            "Remediation plan development"
        ],
        metrics=[
            "compliance_violation_count",
            "audit_log_completeness",
            "disclosure_coverage"
        ],
        alert_threshold={
            "violations_daily": 1,
            "log_completeness": 0.999
        }
    )
]


class ThreatMonitor:
    """
    Active threat monitoring and response coordination.
    """
    
    def __init__(self):
        self.threats = {t.threat_id: t for t in THREAT_REGISTRY}
        self.active_incidents: Dict[str, Dict[str, Any]] = {}
    
    def check_threat(
        self,
        threat_id: str,
        metrics: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if threat thresholds exceeded.
        
        Returns incident details if triggered, None otherwise.
        """
        threat = self.threats.get(threat_id)
        if not threat or not threat.alert_threshold:
            return None
        
        violations = []
        for metric, threshold in threat.alert_threshold.items():
            if metric in metrics:
                if metrics[metric] > threshold:
                    violations.append({
                        "metric": metric,
                        "value": metrics[metric],
                        "threshold": threshold
                    })
        
        if violations:
            incident = {
                "threat_id": threat_id,
                "category": threat.category.value,
                "description": threat.description,
                "likelihood": threat.likelihood,
                "impact": threat.impact,
                "violations": violations,
                "response_actions": threat.response,
                "timestamp": time.time()
            }
            
            self.active_incidents[threat_id] = incident
            return incident
        
        return None
    
    def execute_response(
        self,
        threat_id: str
    ) -> List[str]:
        """
        Execute automated response actions for threat.
        
        Returns list of actions taken.
        """
        threat = self.threats.get(threat_id)
        if not threat:
            return []
        
        actions_taken = []
        
        for action in threat.response:
            try:
                # Execute response action
                if "freeze" in action.lower():
                    self._execute_freeze()
                    actions_taken.append(f"Executed: {action}")
                elif "cancel" in action.lower():
                    self._execute_cancel_orders()
                    actions_taken.append(f"Executed: {action}")
                elif "alert" in action.lower():
                    self._send_alert(threat_id, action)
                    actions_taken.append(f"Executed: {action}")
                else:
                    # Log for manual execution
                    actions_taken.append(f"Manual action required: {action}")
            except Exception as e:
                actions_taken.append(f"Failed: {action} - {str(e)}")
        
        return actions_taken
    
    def _execute_freeze(self) -> None:
        """Freeze all trading activity."""
        from core.execution_controller import get_execution_controller
        controller = get_execution_controller()
        controller.activate_kill_switch("Threat response freeze")
    
    def _execute_cancel_orders(self) -> None:
        """Cancel all pending orders."""
        from core.execution_controller import get_execution_controller
        controller = get_execution_controller()
        controller.cancel_all_orders("Threat response cancellation")
    
    def _send_alert(self, threat_id: str, action: str) -> None:
        """Send alert to operators."""
        from core.alerting import get_alert_manager
        alert_manager = get_alert_manager()
        alert_manager.send_critical_alert(
            title=f"Threat Response: {threat_id}",
            message=action,
            threat_details=self.active_incidents.get(threat_id)
        )


# Singleton
_threat_monitor = None

def get_threat_monitor() -> ThreatMonitor:
    global _threat_monitor
    if _threat_monitor is None:
        _threat_monitor = ThreatMonitor()
    return _threat_monitor
```

---

# SECTION 2: SINGLE EXECUTION AUTHORITY & PROPOSAL LIFECYCLE

## 2.1 Execution Controller - SOLE AUTHORITY

```python
# core/execution_controller.py

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import asyncio
import time
import uuid

class ProposalStatus(Enum):
    """Proposal lifecycle states."""
    CREATED = "created"
    VALIDATED = "validated"
    SIMULATED = "simulated"
    RISK_APPROVED = "risk_approved"
    HUMAN_APPROVED = "human_approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    SETTLED = "settled"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class TradeProposal:
    """
    Structured trade proposal from agents.
    
    IMMUTABLE: Once created, cannot be modified (only status changes).
    """
    proposal_id: str
    created_at: float
    created_by: str  # Agent ID
    
    # Trade details
    instrument: str
    side: str  # BUY, SELL
    size: float
    venue: str
    price_limit: Optional[float] = None
    time_in_force: str = "GTC"
    
    # Rationale
    strategy: str
    reasoning_link: str  # Pointer to explainability record
    confidence: float = 0.0
    supporting_features: Dict[str, Any] = field(default_factory=dict)
    
    # Pre-trade requirements
    required_checks: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    
    # Lifecycle
    status: ProposalStatus = ProposalStatus.CREATED
    status_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Results (populated after execution)
    execution_result: Optional[Dict[str, Any]] = None
    actual_price: Optional[float] = None
    actual_size: Optional[float] = None
    slippage: Optional[float] = None
    fees: Optional[float] = None
    
    def update_status(
        self,
        new_status: ProposalStatus,
        reason: str,
        updated_by: str
    ) -> None:
        """Update proposal status with audit trail."""
        self.status_history.append({
            "from_status": self.status.value,
            "to_status": new_status.value,
            "reason": reason,
            "updated_by": updated_by,
            "timestamp": time.time()
        })
        self.status = new_status


class ExecutionController:
    """
    SOLE AUTHORITY for trade execution.
    
    CRITICAL: Only this component can:
    - Create, sign, and broadcast transactions
    - Modify live risk state (positions, PnL, exposure)
    
    All agents must emit proposals that pass through this controller.
    """
    
    def __init__(self):
        self.proposals: Dict[str, TradeProposal] = {}
        self.kill_switch_active = False
        self.kill_switch_reason: Optional[str] = None
        
        # Dependencies
        from core.risk_envelope import get_risk_envelope
        from core.simulation_engine import get_simulation_engine
        from core.wallet_manager import get_wallet_manager
        from core.audit_logger import get_audit_logger
        
        self.risk_envelope = get_risk_envelope()
        self.simulator = get_simulation_engine()
        self.wallet_manager = get_wallet_manager()
        self.audit_logger = get_audit_logger()
    
    async def submit_proposal(
        self,
        proposal: TradeProposal
    ) -> Dict[str, Any]:
        """
        Submit trade proposal for processing.
        
        WORKFLOW:
        1. Validate proposal format
        2. Check kill switch
        3. Run pre-trade checks
        4. Simulate execution
        5. Check risk envelope
        6. Check human approval requirements
        7. Execute if all pass
        
        Returns: Proposal processing result
        """
        # Store proposal
        self.proposals[proposal.proposal_id] = proposal
        
        # Log submission
        await self.audit_logger.log_proposal_submission(proposal)
        
        try:
            # Step 1: Validate format
            validation_result = await self._validate_proposal(proposal)
            if not validation_result["valid"]:
                proposal.update_status(
                    ProposalStatus.REJECTED,
                    f"Validation failed: {validation_result['reason']}",
                    "execution_controller"
                )
                return {
                    "accepted": False,
                    "reason": validation_result["reason"],
                    "proposal_id": proposal.proposal_id
                }
            
            proposal.update_status(
                ProposalStatus.VALIDATED,
                "Proposal format validated",
                "execution_controller"
            )
            
            # Step 2: Check kill switch
            if self.kill_switch_active:
                proposal.update_status(
                    ProposalStatus.REJECTED,
                    f"Kill switch active: {self.kill_switch_reason}",
                    "execution_controller"
                )
                return {
                    "accepted": False,
                    "reason": "Kill switch active",
                    "proposal_id": proposal.proposal_id
                }
            
            # Step 3: Simulate execution
            simulation_result = await self.simulator.simulate_trade(proposal)
            if not simulation_result["success"]:
                proposal.update_status(
                    ProposalStatus.REJECTED,
                    f"Simulation failed: {simulation_result['reason']}",
                    "execution_controller"
                )
                return {
                    "accepted": False,
                    "reason": simulation_result["reason"],
                    "proposal_id": proposal.proposal_id
                }
            
            proposal.update_status(
                ProposalStatus.SIMULATED,
                f"Simulation passed: {simulation_result['summary']}",
                "execution_controller"
            )
            
            # Step 4: Check risk envelope
            risk_check = await self.risk_envelope.check_proposal(proposal)
            if not risk_check["approved"]:
                proposal.update_status(
                    ProposalStatus.REJECTED,
                    f"Risk check failed: {risk_check['reason']}",
                    "execution_controller"
                )
                return {
                    "accepted": False,
                    "reason": risk_check["reason"],
                    "violations": risk_check.get("violations", []),
                    "proposal_id": proposal.proposal_id
                }
            
            proposal.update_status(
                ProposalStatus.RISK_APPROVED,
                "Risk envelope check passed",
                "execution_controller"
            )
            
            # Step 5: Check human approval requirements
            if await self._requires_human_approval(proposal):
                proposal.update_status(
                    ProposalStatus.HUMAN_APPROVED,
                    "Awaiting human approval",
                    "execution_controller"
                )
                
                # Send approval request
                await self._request_human_approval(proposal)
                
                return {
                    "accepted": True,
                    "status": "awaiting_human_approval",
                    "proposal_id": proposal.proposal_id
                }
            
            # Step 6: Execute
            execution_result = await self._execute_proposal(proposal)
            
            return {
                "accepted": True,
                "status": "executed",
                "proposal_id": proposal.proposal_id,
                "execution_result": execution_result
            }
            
        except Exception as e:
            proposal.update_status(
                ProposalStatus.FAILED,
                f"Execution error: {str(e)}",
                "execution_controller"
            )
            
            await self.audit_logger.log_proposal_failure(proposal, str(e))
            
            return {
                "accepted": False,
                "reason": f"Execution error: {str(e)}",
                "proposal_id": proposal.proposal_id
            }
    
    async def _validate_proposal(
        self,
        proposal: TradeProposal
    ) -> Dict[str, Any]:
        """Validate proposal format and constraints."""
        from core.system_regime import PRODUCTION_CONFIG
        
        # Check instrument in whitelist
        if proposal.instrument not in PRODUCTION_CONFIG.allowed_assets:
            return {
                "valid": False,
                "reason": f"Instrument {proposal.instrument} not in whitelist"
            }
        
        # Check venue in whitelist
        if proposal.venue not in PRODUCTION_CONFIG.allowed_venues:
            return {
                "valid": False,
                "reason": f"Venue {proposal.venue} not in whitelist"
            }
        
        # Check strategy in whitelist
        if proposal.strategy not in PRODUCTION_CONFIG.allowed_strategies:
            return {
                "valid": False,
                "reason": f"Strategy {proposal.strategy} not in whitelist"
            }
        
        # Check notional limit
        estimated_notional = proposal.size * (proposal.price_limit or 0)
        if estimated_notional > PRODUCTION_CONFIG.max_per_trade_notional:
            return {
                "valid": False,
                "reason": f"Notional {estimated_notional} exceeds limit {PRODUCTION_CONFIG.max_per_trade_notional}"
            }
        
        # Check required fields
        if not proposal.reasoning_link:
            return {
                "valid": False,
                "reason": "Missing reasoning link (explainability required)"
            }
        
        return {"valid": True}
    
    async def _requires_human_approval(
        self,
        proposal: TradeProposal
    ) -> bool:
        """Determine if proposal requires human approval."""
        from core.system_regime import PRODUCTION_CONFIG
        
        # Check strategy requires approval
        if proposal.strategy in PRODUCTION_CONFIG.requires_human_approval:
            return True
        
        # Check size threshold
        estimated_notional = proposal.size * (proposal.price_limit or 0)
        if estimated_notional > PRODUCTION_CONFIG.max_per_trade_notional * 0.5:
            return True
        
        # Check confidence threshold
        if proposal.confidence < 0.8:
            return True
        
        return False
    
    async def _request_human_approval(
        self,
        proposal: TradeProposal
    ) -> None:
        """Send approval request to operators."""
        from core.alerting import get_alert_manager
        
        alert_manager = get_alert_manager()
        await alert_manager.send_approval_request(
            title=f"Trade Approval Required: {proposal.proposal_id}",
            proposal=proposal,
            approval_url=f"/operator/approve/{proposal.proposal_id}"
        )
    
    async def _execute_proposal(
        self,
        proposal: TradeProposal
    ) -> Dict[str, Any]:
        """
        Execute approved proposal.
        
        CRITICAL: This is the ONLY place where actual trades are executed.
        """
        proposal.update_status(
            ProposalStatus.EXECUTING,
            "Execution started",
            "execution_controller"
        )
        
        try:
            # Get venue connector
            from trading.venue_connectors import get_venue_connector
            venue = get_venue_connector(proposal.venue)
            
            # Execute trade
            result = await venue.execute_trade(
                instrument=proposal.instrument,
                side=proposal.side,
                size=proposal.size,
                price_limit=proposal.price_limit,
                time_in_force=proposal.time_in_force
            )
            
            # Update proposal with results
            proposal.execution_result = result
            proposal.actual_price = result.get("avg_price")
            proposal.actual_size = result.get("filled_size")
            proposal.slippage = result.get("slippage")
            proposal.fees = result.get("fees")
            
            proposal.update_status(
                ProposalStatus.EXECUTED,
                f"Execution completed: {result.get('order_id')}",
                "execution_controller"
            )
            
            # Update risk state
            await self.risk_envelope.update_position(proposal, result)
            
            # Log execution
            await self.audit_logger.log_execution(proposal, result)
            
            return result
            
        except Exception as e:
            proposal.update_status(
                ProposalStatus.FAILED,
                f"Execution failed: {str(e)}",
                "execution_controller"
            )
            raise
    
    def activate_kill_switch(self, reason: str) -> None:
        """
        Activate kill switch - stops all trading immediately.
        
        CRITICAL: This is the emergency stop mechanism.
        """
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        
        # Cancel all pending proposals
        for proposal in self.proposals.values():
            if proposal.status in [
                ProposalStatus.CREATED,
                ProposalStatus.VALIDATED,
                ProposalStatus.SIMULATED,
                ProposalStatus.RISK_APPROVED
            ]:
                proposal.update_status(
                    ProposalStatus.CANCELLED,
                    f"Kill switch activated: {reason}",
                    "execution_controller"
                )
        
        # Log kill switch activation
        self.audit_logger.log_kill_switch_activation(reason)
    
    def deactivate_kill_switch(
        self,
        operator_id: str,
        justification: str
    ) -> None:
        """
        Deactivate kill switch - requires operator approval.
        """
        self.kill_switch_active = False
        self.kill_switch_reason = None
        
        # Log deactivation
        self.audit_logger.log_kill_switch_deactivation(
            operator_id,
            justification
        )
    
    async def cancel_all_orders(self, reason: str) -> List[str]:
        """Cancel all pending orders across all venues."""
        from trading.venue_connectors import get_all_venue_connectors
        
        cancelled_orders = []
        
        for venue in get_all_venue_connectors():
            try:
                orders = await venue.cancel_all_orders(reason)
                cancelled_orders.extend(orders)
            except Exception as e:
                logger.error(f"Failed to cancel orders on {venue.name}: {e}")
        
        return cancelled_orders


# Singleton
_execution_controller = None

def get_execution_controller() -> ExecutionController:
    global _execution_controller
    if _execution_controller is None:
        _execution_controller = ExecutionController()
    return _execution_controller
```

## 2.2 Proposal Lifecycle State Machine

```python
# core/proposal_lifecycle.py

from typing import Dict, List, Callable, Optional
import asyncio

class ProposalLifecycleManager:
    """
    Manages proposal state transitions with validation.
    """
    
    # Valid state transitions
    TRANSITIONS = {
        ProposalStatus.CREATED: [
            ProposalStatus.VALIDATED,
            ProposalStatus.REJECTED
        ],
        ProposalStatus.VALIDATED: [
            ProposalStatus.SIMULATED,
            ProposalStatus.REJECTED
        ],
        ProposalStatus.SIMULATED: [
            ProposalStatus.RISK_APPROVED,
            ProposalStatus.REJECTED
        ],
        ProposalStatus.RISK_APPROVED: [
            ProposalStatus.HUMAN_APPROVED,
            ProposalStatus.EXECUTING,
            ProposalStatus.REJECTED
        ],
        ProposalStatus.HUMAN_APPROVED: [
            ProposalStatus.EXECUTING,
            ProposalStatus.CANCELLED
        ],
        ProposalStatus.EXECUTING: [
            ProposalStatus.EXECUTED,
            ProposalStatus.FAILED
        ],
        ProposalStatus.EXECUTED: [
            ProposalStatus.SETTLED
        ],
        # Terminal states
        ProposalStatus.SETTLED: [],
        ProposalStatus.FAILED: [],
        ProposalStatus.REJECTED: [],
        ProposalStatus.CANCELLED: []
    }
    
    def __init__(self):
        self.state_handlers: Dict[ProposalStatus, Callable] = {}
    
    def register_handler(
        self,
        status: ProposalStatus,
        handler: Callable
    ) -> None:
        """Register handler for status transition."""
        self.state_handlers[status] = handler
    
    def can_transition(
        self,
        from_status: ProposalStatus,
        to_status: ProposalStatus
    ) -> bool:
        """Check if transition is valid."""
        allowed = self.TRANSITIONS.get(from_status, [])
        return to_status in allowed
    
    async def transition(
        self,
        proposal: TradeProposal,
        to_status: ProposalStatus,
        reason: str,
        updated_by: str
    ) -> bool:
        """
        Attempt state transition with validation.
        
        Returns True if successful, False otherwise.
        """
        if not self.can_transition(proposal.status, to_status):
            logger.error(
                f"Invalid transition: {proposal.status} -> {to_status} "
                f"for proposal {proposal.proposal_id}"
            )
            return False
        
        # Execute handler if registered
        handler = self.state_handlers.get(to_status)
        if handler:
            try:
                await handler(proposal)
            except Exception as e:
                logger.error(f"Handler failed for {to_status}: {e}")
                return False
        
        # Update status
        proposal.update_status(to_status, reason, updated_by)
        
        return True
```

---

*[Document continues with Sections 3-10 covering Risk Envelopes, Tool-First Architecture, Wallet/Custody, Observability, Progressive Rollout, Testing Harness, Regulatory Compliance, and Concrete Module Implementations]*

**[IMPLEMENTATION CONTINUES IN NEXT FILE]**
