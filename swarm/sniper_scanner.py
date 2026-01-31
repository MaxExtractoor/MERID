"""
Timing exploit and sniper opportunity scanner for MERID HFT swarm.

Implements detection and scoring of:
- Legitimate timing-based opportunities (arbitrage, mispricings)
- Predictable flows and skews
- Compliance classification (allowed/restricted/banned)
- Risk and edge estimation
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class OpportunityType(Enum):
    """Type of timing opportunity."""
    ARBITRAGE = "arbitrage"
    MISPRICING = "mispricing"
    PREDICTABLE_FLOW = "predictable_flow"
    SKEW_OPPORTUNITY = "skew_opportunity"
    LIQUIDATION_SNIPE = "liquidation_snipe"
    MEV_OPPORTUNITY = "mev_opportunity"
    FUNDING_RATE_ARB = "funding_rate_arb"


class ComplianceCategory(Enum):
    """Compliance category for opportunity."""
    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    BANNED = "banned"


class TacticType(Enum):
    """Type of execution tactic."""
    SIMPLE_ARB = "simple_arb"
    TRIANGULAR_ARB = "triangular_arb"
    FLASH_LOAN_ARB = "flash_loan_arb"
    FRONT_RUN = "front_run"  # BANNED
    SANDWICH_ATTACK = "sandwich_attack"  # BANNED
    SPOOFING = "spoofing"  # BANNED
    LAYERING = "layering"  # BANNED


@dataclass
class SniperOpportunity:
    """Timing-based sniper opportunity."""
    opportunity_id: str
    opportunity_type: OpportunityType
    
    # Venues
    buy_venue: str
    sell_venue: str
    
    # Asset
    asset: str
    base_asset: Optional[str] = None
    quote_asset: Optional[str] = None
    
    # Pricing
    buy_price: Decimal = Decimal("0")
    sell_price: Decimal = Decimal("0")
    spread_bps: float = 0.0  # Basis points
    
    # Size
    max_size: Decimal = Decimal("0")
    estimated_slippage_bps: float = 0.0
    
    # Edge
    estimated_edge_bps: float = 0.0  # After fees and slippage
    estimated_profit_usd: Decimal = Decimal("0")
    
    # Latency
    required_latency_ms: float = 0.0
    execution_window_ms: float = 0.0
    
    # Risk
    risk_score: float = 0.0  # 0.0 (safe) to 1.0 (risky)
    inventory_risk: float = 0.0
    execution_risk: float = 0.0
    
    # Compliance
    compliance_category: ComplianceCategory = ComplianceCategory.ALLOWED
    compliance_notes: List[str] = field(default_factory=list)
    
    # Tactic
    execution_tactic: TacticType = TacticType.SIMPLE_ARB
    
    # Status
    approved_for_execution: bool = False
    blocked: bool = False
    
    detected_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


@dataclass
class TacticPolicy:
    """Policy for execution tactic."""
    tactic_type: TacticType
    compliance_category: ComplianceCategory
    
    # Restrictions
    allowed: bool = True
    requires_approval: bool = False
    max_size_usd: Optional[Decimal] = None
    max_frequency_per_hour: Optional[int] = None
    
    # Reasoning
    policy_reason: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SniperExecution:
    """Sniper execution record."""
    execution_id: str
    opportunity_id: str
    
    # Execution
    executed_at: datetime
    buy_venue: str
    sell_venue: str
    asset: str
    size: Decimal
    
    # Results
    success: bool = False
    actual_profit_usd: Decimal = Decimal("0")
    actual_edge_bps: float = 0.0
    latency_ms: float = 0.0
    
    # Compliance
    compliance_checked: bool = True
    compliance_approved: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class SniperOpportunityScanner:
    """
    Timing exploit and sniper opportunity scanner for MERID.
    
    Implements:
    - Legitimate timing opportunity detection
    - Edge and risk estimation
    - Compliance classification
    - Tactic filtering (block manipulative tactics)
    - Execution tracking and review
    """
    
    def __init__(self):
        self._tactic_policies: Dict[TacticType, TacticPolicy] = {}
        self._opportunities: List[SniperOpportunity] = []
        self._executions: List[SniperExecution] = []
        self._blocked_tactics: Set[TacticType] = set()
        
        self._initialize_tactic_policies()
    
    def _initialize_tactic_policies(self) -> None:
        """Initialize tactic policies."""
        
        # ALLOWED tactics
        self.register_tactic_policy(
            tactic_type=TacticType.SIMPLE_ARB,
            compliance_category=ComplianceCategory.ALLOWED,
            allowed=True,
            requires_approval=False,
            policy_reason="Simple arbitrage is legitimate price discovery",
        )
        
        self.register_tactic_policy(
            tactic_type=TacticType.TRIANGULAR_ARB,
            compliance_category=ComplianceCategory.ALLOWED,
            allowed=True,
            requires_approval=False,
            policy_reason="Triangular arbitrage is legitimate",
        )
        
        self.register_tactic_policy(
            tactic_type=TacticType.FLASH_LOAN_ARB,
            compliance_category=ComplianceCategory.RESTRICTED,
            allowed=True,
            requires_approval=True,
            max_size_usd=Decimal("100000"),
            policy_reason="Flash loan arbitrage requires approval due to complexity",
        )
        
        # BANNED tactics (market abuse)
        self.register_tactic_policy(
            tactic_type=TacticType.FRONT_RUN,
            compliance_category=ComplianceCategory.BANNED,
            allowed=False,
            policy_reason="Front-running is market manipulation",
        )
        
        self.register_tactic_policy(
            tactic_type=TacticType.SANDWICH_ATTACK,
            compliance_category=ComplianceCategory.BANNED,
            allowed=False,
            policy_reason="Sandwich attacks are market manipulation",
        )
        
        self.register_tactic_policy(
            tactic_type=TacticType.SPOOFING,
            compliance_category=ComplianceCategory.BANNED,
            allowed=False,
            policy_reason="Spoofing is illegal market manipulation",
        )
        
        self.register_tactic_policy(
            tactic_type=TacticType.LAYERING,
            compliance_category=ComplianceCategory.BANNED,
            allowed=False,
            policy_reason="Layering is illegal market manipulation",
        )
        
        # Track blocked tactics
        self._blocked_tactics = {
            TacticType.FRONT_RUN,
            TacticType.SANDWICH_ATTACK,
            TacticType.SPOOFING,
            TacticType.LAYERING,
        }
        
        logger.info("Initialized sniper tactic policies")
    
    def register_tactic_policy(
        self,
        tactic_type: TacticType,
        compliance_category: ComplianceCategory,
        allowed: bool = True,
        requires_approval: bool = False,
        max_size_usd: Optional[Decimal] = None,
        max_frequency_per_hour: Optional[int] = None,
        policy_reason: str = "",
    ) -> TacticPolicy:
        """Register tactic policy."""
        policy = TacticPolicy(
            tactic_type=tactic_type,
            compliance_category=compliance_category,
            allowed=allowed,
            requires_approval=requires_approval,
            max_size_usd=max_size_usd,
            max_frequency_per_hour=max_frequency_per_hour,
            policy_reason=policy_reason,
        )
        
        self._tactic_policies[tactic_type] = policy
        
        logger.info(
            f"Registered tactic policy '{tactic_type.value}': "
            f"{compliance_category.value} ({'allowed' if allowed else 'banned'})"
        )
        
        return policy
    
    def detect_arbitrage_opportunity(
        self,
        asset: str,
        buy_venue: str,
        sell_venue: str,
        buy_price: Decimal,
        sell_price: Decimal,
        max_size: Decimal,
        buy_fee_bps: float = 10.0,
        sell_fee_bps: float = 10.0,
        estimated_slippage_bps: float = 5.0,
        required_latency_ms: float = 100.0,
    ) -> Optional[SniperOpportunity]:
        """Detect arbitrage opportunity."""
        # Calculate spread
        spread = (sell_price - buy_price) / buy_price
        spread_bps = float(spread * Decimal("10000"))
        
        # Calculate edge (after fees and slippage)
        total_cost_bps = buy_fee_bps + sell_fee_bps + estimated_slippage_bps
        estimated_edge_bps = spread_bps - total_cost_bps
        
        # Check if profitable
        if estimated_edge_bps <= 0:
            return None
        
        # Calculate profit
        estimated_profit_usd = (
            max_size * buy_price * Decimal(estimated_edge_bps) / Decimal("10000")
        )
        
        # Create opportunity
        opportunity_id = f"arb_{asset}_{int(datetime.utcnow().timestamp())}"
        
        opportunity = SniperOpportunity(
            opportunity_id=opportunity_id,
            opportunity_type=OpportunityType.ARBITRAGE,
            buy_venue=buy_venue,
            sell_venue=sell_venue,
            asset=asset,
            buy_price=buy_price,
            sell_price=sell_price,
            spread_bps=spread_bps,
            max_size=max_size,
            estimated_slippage_bps=estimated_slippage_bps,
            estimated_edge_bps=estimated_edge_bps,
            estimated_profit_usd=estimated_profit_usd,
            required_latency_ms=required_latency_ms,
            execution_window_ms=500.0,  # 500ms window
            execution_tactic=TacticType.SIMPLE_ARB,
        )
        
        # Score risk
        opportunity.risk_score = self._calculate_risk_score(opportunity)
        
        # Check compliance
        self._check_compliance(opportunity)
        
        # Approve if compliant
        if (
            opportunity.compliance_category == ComplianceCategory.ALLOWED
            and not opportunity.blocked
        ):
            opportunity.approved_for_execution = True
        
        self._opportunities.append(opportunity)
        
        logger.info(
            f"Detected arbitrage opportunity: {asset} "
            f"{buy_venue} → {sell_venue}, edge={estimated_edge_bps:.1f}bps, "
            f"profit=${estimated_profit_usd:.2f}"
        )
        
        return opportunity
    
    def detect_liquidation_opportunity(
        self,
        asset: str,
        venue: str,
        liquidation_price: Decimal,
        market_price: Decimal,
        size: Decimal,
        liquidation_bonus_bps: float = 50.0,
    ) -> Optional[SniperOpportunity]:
        """Detect liquidation snipe opportunity."""
        # Calculate edge (liquidation bonus)
        estimated_edge_bps = liquidation_bonus_bps
        
        # Calculate profit
        estimated_profit_usd = (
            size * market_price * Decimal(estimated_edge_bps) / Decimal("10000")
        )
        
        opportunity_id = f"liq_{asset}_{int(datetime.utcnow().timestamp())}"
        
        opportunity = SniperOpportunity(
            opportunity_id=opportunity_id,
            opportunity_type=OpportunityType.LIQUIDATION_SNIPE,
            buy_venue=venue,
            sell_venue=venue,
            asset=asset,
            buy_price=liquidation_price,
            sell_price=market_price,
            spread_bps=float((market_price - liquidation_price) / liquidation_price * Decimal("10000")),
            max_size=size,
            estimated_edge_bps=estimated_edge_bps,
            estimated_profit_usd=estimated_profit_usd,
            required_latency_ms=50.0,  # Very fast required
            execution_window_ms=100.0,  # Short window
            execution_tactic=TacticType.SIMPLE_ARB,
        )
        
        opportunity.risk_score = self._calculate_risk_score(opportunity)
        self._check_compliance(opportunity)
        
        if (
            opportunity.compliance_category == ComplianceCategory.ALLOWED
            and not opportunity.blocked
        ):
            opportunity.approved_for_execution = True
        
        self._opportunities.append(opportunity)
        
        logger.info(
            f"Detected liquidation opportunity: {asset} on {venue}, "
            f"edge={estimated_edge_bps:.1f}bps, profit=${estimated_profit_usd:.2f}"
        )
        
        return opportunity
    
    def _calculate_risk_score(self, opportunity: SniperOpportunity) -> float:
        """Calculate risk score for opportunity."""
        risk_score = 0.0
        
        # Execution risk (latency requirement)
        if opportunity.required_latency_ms < 50:
            risk_score += 0.3  # Very tight latency
        elif opportunity.required_latency_ms < 100:
            risk_score += 0.15
        
        # Inventory risk (large size)
        size_usd = opportunity.max_size * opportunity.buy_price
        if size_usd > Decimal("100000"):
            risk_score += 0.3
        elif size_usd > Decimal("50000"):
            risk_score += 0.15
        
        # Slippage risk
        if opportunity.estimated_slippage_bps > 20:
            risk_score += 0.2
        elif opportunity.estimated_slippage_bps > 10:
            risk_score += 0.1
        
        # Edge risk (low edge = higher risk of loss)
        if opportunity.estimated_edge_bps < 10:
            risk_score += 0.2
        elif opportunity.estimated_edge_bps < 20:
            risk_score += 0.1
        
        return min(risk_score, 1.0)
    
    def _check_compliance(self, opportunity: SniperOpportunity) -> None:
        """Check compliance for opportunity."""
        # Get tactic policy
        policy = self._tactic_policies.get(opportunity.execution_tactic)
        
        if not policy:
            opportunity.compliance_category = ComplianceCategory.RESTRICTED
            opportunity.compliance_notes.append("No policy defined for tactic")
            opportunity.approved_for_execution = False
            return
        
        # Check if tactic is allowed
        if not policy.allowed:
            opportunity.compliance_category = ComplianceCategory.BANNED
            opportunity.compliance_notes.append(f"Tactic banned: {policy.policy_reason}")
            opportunity.blocked = True
            opportunity.approved_for_execution = False
            
            logger.warning(
                f"Opportunity {opportunity.opportunity_id} BLOCKED: "
                f"tactic {opportunity.execution_tactic.value} is banned"
            )
            return
        
        # Set compliance category
        opportunity.compliance_category = policy.compliance_category
        
        # Check size limits
        if policy.max_size_usd:
            size_usd = opportunity.max_size * opportunity.buy_price
            if size_usd > policy.max_size_usd:
                opportunity.compliance_notes.append(
                    f"Size ${size_usd:.2f} exceeds limit ${policy.max_size_usd:.2f}"
                )
                opportunity.approved_for_execution = False
                opportunity.blocked = True
                return

        # Check if requires approval
        if policy.requires_approval:
            opportunity.compliance_notes.append("Requires governance approval")
            opportunity.approved_for_execution = False
            opportunity.blocked = True
            return
        
        opportunity.compliance_notes.append("Compliant")
    
    def is_tactic_allowed(self, tactic: TacticType) -> bool:
        """Check if tactic is allowed."""
        if tactic in self._blocked_tactics:
            return False
        
        policy = self._tactic_policies.get(tactic)
        return policy.allowed if policy else False
    
    def record_execution(
        self,
        opportunity_id: str,
        success: bool,
        actual_profit_usd: Decimal,
        actual_edge_bps: float,
        latency_ms: float,
    ) -> SniperExecution:
        """Record sniper execution."""
        opportunity = next(
            (o for o in self._opportunities if o.opportunity_id == opportunity_id),
            None,
        )
        
        if not opportunity:
            raise ValueError(f"Opportunity '{opportunity_id}' not found")
        
        execution_id = f"exec_{opportunity_id}_{int(datetime.utcnow().timestamp())}"
        
        execution = SniperExecution(
            execution_id=execution_id,
            opportunity_id=opportunity_id,
            executed_at=datetime.utcnow(),
            buy_venue=opportunity.buy_venue,
            sell_venue=opportunity.sell_venue,
            asset=opportunity.asset,
            size=opportunity.max_size,
            success=success,
            actual_profit_usd=actual_profit_usd,
            actual_edge_bps=actual_edge_bps,
            latency_ms=latency_ms,
            compliance_checked=True,
            compliance_approved=opportunity.approved_for_execution,
        )
        
        self._executions.append(execution)
        
        logger.info(
            f"Recorded sniper execution: {execution_id}, "
            f"success={success}, profit=${actual_profit_usd:.2f}, "
            f"edge={actual_edge_bps:.1f}bps, latency={latency_ms:.1f}ms"
        )
        
        return execution
    
    def get_opportunities(
        self,
        opportunity_type: Optional[OpportunityType] = None,
        compliance_category: Optional[ComplianceCategory] = None,
        approved_only: bool = False,
        min_edge_bps: float = 0.0,
    ) -> List[SniperOpportunity]:
        """Get sniper opportunities."""
        opportunities = self._opportunities
        
        if opportunity_type:
            opportunities = [o for o in opportunities if o.opportunity_type == opportunity_type]
        
        if compliance_category:
            opportunities = [o for o in opportunities if o.compliance_category == compliance_category]
        
        if approved_only:
            opportunities = [o for o in opportunities if o.approved_for_execution]
        
        if min_edge_bps > 0:
            opportunities = [o for o in opportunities if o.estimated_edge_bps >= min_edge_bps]
        
        # Sort by edge (descending)
        opportunities.sort(key=lambda o: o.estimated_edge_bps, reverse=True)
        
        return opportunities
    
    def get_executions(
        self,
        success_only: bool = False,
        since: Optional[datetime] = None,
    ) -> List[SniperExecution]:
        """Get sniper executions."""
        executions = self._executions
        
        if success_only:
            executions = [e for e in executions if e.success]
        
        if since:
            executions = [e for e in executions if e.executed_at >= since]
        
        return executions
    
    def get_execution_stats(
        self,
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get execution statistics."""
        executions = self.get_executions(since=since)
        
        if not executions:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "success_rate": 0.0,
                "total_profit_usd": 0.0,
                "avg_edge_bps": 0.0,
                "avg_latency_ms": 0.0,
            }
        
        successful = [e for e in executions if e.success]
        
        return {
            "total_executions": len(executions),
            "successful_executions": len(successful),
            "success_rate": len(successful) / len(executions),
            "total_profit_usd": float(sum(e.actual_profit_usd for e in successful)),
            "avg_edge_bps": sum(e.actual_edge_bps for e in successful) / len(successful) if successful else 0.0,
            "avg_latency_ms": sum(e.latency_ms for e in executions) / len(executions),
        }


_sniper_opportunity_scanner: Optional[SniperOpportunityScanner] = None


def get_sniper_opportunity_scanner() -> SniperOpportunityScanner:
    """Get global SniperOpportunityScanner instance."""
    global _sniper_opportunity_scanner
    if _sniper_opportunity_scanner is None:
        _sniper_opportunity_scanner = SniperOpportunityScanner()
    return _sniper_opportunity_scanner
