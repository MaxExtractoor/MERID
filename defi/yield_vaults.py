"""
Yield vaults and automated portfolio management for MERID.

Implements yield vaults that allocate across staking, lending, LP, and RWA
strategies with AI-optimized rebalancing and auto-compounding.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class VaultType(Enum):
    """Vault type."""
    CONSERVATIVE = "conservative"  # Low risk, stable yield
    BALANCED = "balanced"  # Medium risk, balanced return
    AGGRESSIVE = "aggressive"  # High risk, high yield
    CUSTOM = "custom"  # User-defined allocation


class YieldStrategy(Enum):
    """Yield strategy type."""
    STAKING = "staking"
    LIQUID_STAKING = "liquid_staking"
    RESTAKING = "restaking"
    LENDING = "lending"
    LP_FARMING = "lp_farming"
    CONCENTRATED_LIQUIDITY = "concentrated_liquidity"
    RWA_YIELD = "rwa_yield"
    STRUCTURED_CREDIT = "structured_credit"
    CARRY_TRADE = "carry_trade"
    BASIS_TRADE = "basis_trade"


class RebalanceReason(Enum):
    """Rebalance reason."""
    SCHEDULED = "scheduled"
    DRIFT_THRESHOLD = "drift_threshold"
    REGIME_CHANGE = "regime_change"
    RISK_LIMIT = "risk_limit"
    OPPORTUNITY = "opportunity"
    EMERGENCY = "emergency"


@dataclass
class YieldAllocation:
    """Yield strategy allocation."""
    strategy: YieldStrategy
    protocol: str
    asset: str
    
    # Allocation
    target_percentage: Decimal
    current_percentage: Decimal
    current_value_usd: Decimal
    
    # Performance
    apy: Decimal
    realized_yield_usd: Decimal
    unrealized_pnl_usd: Decimal
    
    # Risk
    risk_score: float  # 0.0 (safe) to 1.0 (risky)
    tvl_usd: Decimal
    protocol_risk: str  # "low", "medium", "high"
    
    # Metadata
    last_rebalance: datetime
    last_compound: datetime


@dataclass
class VaultStrategy:
    """Vault strategy definition."""
    vault_id: str
    vault_type: VaultType
    name: str
    description: str
    
    # Target allocations
    target_allocations: List[YieldAllocation] = field(default_factory=list)
    
    # Risk parameters
    max_protocol_concentration: Decimal = Decimal("30.0")  # Max 30% in one protocol
    max_strategy_concentration: Decimal = Decimal("40.0")  # Max 40% in one strategy
    max_risk_score: float = 0.7  # Max average risk score
    
    # Rebalancing
    rebalance_threshold: Decimal = Decimal("5.0")  # Rebalance if >5% drift
    rebalance_frequency_hours: int = 24
    
    # Compounding
    auto_compound: bool = True
    compound_frequency_hours: int = 12
    min_compound_amount_usd: Decimal = Decimal("100")
    
    # Fees
    management_fee_annual: Decimal = Decimal("1.0")  # 1% annual
    performance_fee: Decimal = Decimal("10.0")  # 10% of profits
    
    # Performance
    total_value_usd: Decimal = Decimal("0")
    total_deposited_usd: Decimal = Decimal("0")
    total_yield_usd: Decimal = Decimal("0")
    apy: Decimal = Decimal("0")
    
    # Governance
    dao_controlled: bool = True
    requires_approval_for_new_protocols: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_rebalance: Optional[datetime] = None


@dataclass
class UserVaultPosition:
    """User position in vault."""
    position_id: str
    user_id: str
    vault_id: str
    
    # Position
    shares: Decimal
    deposited_usd: Decimal
    current_value_usd: Decimal
    
    # Performance
    realized_yield_usd: Decimal
    unrealized_pnl_usd: Decimal
    total_return_percentage: Decimal
    
    # Fees paid
    management_fees_paid_usd: Decimal = Decimal("0")
    performance_fees_paid_usd: Decimal = Decimal("0")
    
    # Timestamps
    deposit_timestamp: datetime = field(default_factory=datetime.utcnow)
    last_compound: Optional[datetime] = None


@dataclass
class RebalanceProposal:
    """AI-generated rebalance proposal."""
    proposal_id: str
    vault_id: str
    reason: RebalanceReason
    
    # Current vs target
    current_allocations: List[YieldAllocation]
    proposed_allocations: List[YieldAllocation]
    
    # Expected impact
    expected_apy_change: Decimal
    expected_risk_change: float
    estimated_gas_cost_usd: Decimal
    
    # Rationale
    ai_rationale: str
    market_conditions: Dict[str, Any]
    
    # Approval
    requires_approval: bool = False
    approved: bool = False
    approved_by: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None


class YieldVaults:
    """
    Yield vaults and automated portfolio management for MERID.
    
    Implements:
    - Multi-strategy yield vaults (staking, lending, LP, RWA)
    - AI-optimized rebalancing based on risk, performance, regime
    - Auto-compounding with gas optimization
    - Risk-adjusted allocation across protocols
    - Performance tracking and fee management
    """
    
    def __init__(self):
        self._vaults: Dict[str, VaultStrategy] = {}
        self._user_positions: Dict[str, UserVaultPosition] = {}
        self._rebalance_proposals: List[RebalanceProposal] = []
        
        self._initialize_default_vaults()
    
    def _initialize_default_vaults(self) -> None:
        """Initialize default vault strategies."""
        
        # Conservative vault: Low risk, stable yield
        self.create_vault(
            vault_id="conservative_yield_v1",
            vault_type=VaultType.CONSERVATIVE,
            name="Conservative Yield Vault",
            description="Low-risk stable yield from blue-chip protocols",
            target_allocations=[
                YieldAllocation(
                    strategy=YieldStrategy.LIQUID_STAKING,
                    protocol="lido",
                    asset="ETH",
                    target_percentage=Decimal("30.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("3.5"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.2,
                    tvl_usd=Decimal("10000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.LENDING,
                    protocol="aave",
                    asset="USDC",
                    target_percentage=Decimal("40.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("4.2"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.3,
                    tvl_usd=Decimal("5000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.RWA_YIELD,
                    protocol="ondo",
                    asset="OUSG",
                    target_percentage=Decimal("30.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("5.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.4,
                    tvl_usd=Decimal("500000000"),
                    protocol_risk="medium",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
            ],
            max_risk_score=0.4,
            management_fee_annual=Decimal("0.5"),
            performance_fee=Decimal("5.0"),
        )
        
        # Balanced vault: Medium risk, balanced return
        self.create_vault(
            vault_id="balanced_yield_v1",
            vault_type=VaultType.BALANCED,
            name="Balanced Yield Vault",
            description="Balanced risk-return across DeFi strategies",
            target_allocations=[
                YieldAllocation(
                    strategy=YieldStrategy.RESTAKING,
                    protocol="eigenlayer",
                    asset="ETH",
                    target_percentage=Decimal("25.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("8.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.5,
                    tvl_usd=Decimal("2000000000"),
                    protocol_risk="medium",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.LP_FARMING,
                    protocol="uniswap_v3",
                    asset="ETH-USDC",
                    target_percentage=Decimal("30.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("12.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.6,
                    tvl_usd=Decimal("1000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.LENDING,
                    protocol="compound",
                    asset="USDC",
                    target_percentage=Decimal("25.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("5.5"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.3,
                    tvl_usd=Decimal("3000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.STRUCTURED_CREDIT,
                    protocol="maple",
                    asset="USDC",
                    target_percentage=Decimal("20.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("10.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.7,
                    tvl_usd=Decimal("200000000"),
                    protocol_risk="high",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
            ],
            max_risk_score=0.6,
            management_fee_annual=Decimal("1.0"),
            performance_fee=Decimal("10.0"),
        )
        
        # Aggressive vault: High risk, high yield
        self.create_vault(
            vault_id="aggressive_yield_v1",
            vault_type=VaultType.AGGRESSIVE,
            name="Aggressive Yield Vault",
            description="High-risk, high-yield DeFi strategies",
            target_allocations=[
                YieldAllocation(
                    strategy=YieldStrategy.CONCENTRATED_LIQUIDITY,
                    protocol="uniswap_v3",
                    asset="ETH-USDC",
                    target_percentage=Decimal("30.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("25.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.8,
                    tvl_usd=Decimal("500000000"),
                    protocol_risk="medium",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.CARRY_TRADE,
                    protocol="aave",
                    asset="ETH-USDC",
                    target_percentage=Decimal("25.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("18.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.7,
                    tvl_usd=Decimal("1000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.BASIS_TRADE,
                    protocol="dydx",
                    asset="BTC",
                    target_percentage=Decimal("25.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("15.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.6,
                    tvl_usd=Decimal("800000000"),
                    protocol_risk="medium",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
                YieldAllocation(
                    strategy=YieldStrategy.LP_FARMING,
                    protocol="curve",
                    asset="3pool",
                    target_percentage=Decimal("20.0"),
                    current_percentage=Decimal("0"),
                    current_value_usd=Decimal("0"),
                    apy=Decimal("20.0"),
                    realized_yield_usd=Decimal("0"),
                    unrealized_pnl_usd=Decimal("0"),
                    risk_score=0.5,
                    tvl_usd=Decimal("2000000000"),
                    protocol_risk="low",
                    last_rebalance=datetime.utcnow(),
                    last_compound=datetime.utcnow(),
                ),
            ],
            max_risk_score=0.8,
            management_fee_annual=Decimal("2.0"),
            performance_fee=Decimal("20.0"),
        )
        
        logger.info(f"Initialized {len(self._vaults)} default vaults")
    
    def create_vault(
        self,
        vault_id: str,
        vault_type: VaultType,
        name: str,
        description: str,
        target_allocations: List[YieldAllocation],
        max_risk_score: float = 0.7,
        management_fee_annual: Decimal = Decimal("1.0"),
        performance_fee: Decimal = Decimal("10.0"),
    ) -> VaultStrategy:
        """Create yield vault."""
        vault = VaultStrategy(
            vault_id=vault_id,
            vault_type=vault_type,
            name=name,
            description=description,
            target_allocations=target_allocations,
            max_risk_score=max_risk_score,
            management_fee_annual=management_fee_annual,
            performance_fee=performance_fee,
        )
        
        self._vaults[vault_id] = vault
        
        logger.info(f"Created vault '{vault_id}': {name} ({vault_type.value})")
        
        return vault
    
    def deposit(
        self,
        user_id: str,
        vault_id: str,
        amount_usd: Decimal,
    ) -> UserVaultPosition:
        """Deposit into vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            raise ValueError(f"Vault '{vault_id}' not found")
        
        # Calculate shares (simplified: 1:1 for first deposit)
        if vault.total_value_usd == 0:
            shares = amount_usd
        else:
            shares = amount_usd * (vault.total_deposited_usd / vault.total_value_usd)
        
        position_id = f"pos_{user_id}_{vault_id}_{int(datetime.utcnow().timestamp())}"
        
        position = UserVaultPosition(
            position_id=position_id,
            user_id=user_id,
            vault_id=vault_id,
            shares=shares,
            deposited_usd=amount_usd,
            current_value_usd=amount_usd,
            realized_yield_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
            total_return_percentage=Decimal("0"),
        )
        
        self._user_positions[position_id] = position
        
        # Update vault
        vault.total_deposited_usd += amount_usd
        vault.total_value_usd += amount_usd
        
        logger.info(
            f"User '{user_id}' deposited ${amount_usd} into vault '{vault_id}' "
            f"({shares} shares)"
        )
        
        return position
    
    def propose_rebalance(
        self,
        vault_id: str,
        reason: RebalanceReason,
        proposed_allocations: List[YieldAllocation],
        ai_rationale: str,
        market_conditions: Dict[str, Any],
    ) -> RebalanceProposal:
        """Propose vault rebalance (AI-generated)."""
        vault = self._vaults.get(vault_id)
        if not vault:
            raise ValueError(f"Vault '{vault_id}' not found")
        
        proposal_id = f"rebalance_{vault_id}_{int(datetime.utcnow().timestamp())}"
        
        # Calculate expected impact
        current_apy = self._calculate_weighted_apy(vault.target_allocations)
        proposed_apy = self._calculate_weighted_apy(proposed_allocations)
        
        current_risk = self._calculate_weighted_risk(vault.target_allocations)
        proposed_risk = self._calculate_weighted_risk(proposed_allocations)
        
        proposal = RebalanceProposal(
            proposal_id=proposal_id,
            vault_id=vault_id,
            reason=reason,
            current_allocations=vault.target_allocations.copy(),
            proposed_allocations=proposed_allocations,
            expected_apy_change=proposed_apy - current_apy,
            expected_risk_change=proposed_risk - current_risk,
            estimated_gas_cost_usd=Decimal("50"),  # Simplified
            ai_rationale=ai_rationale,
            market_conditions=market_conditions,
            requires_approval=vault.requires_approval_for_new_protocols,
        )
        
        self._rebalance_proposals.append(proposal)
        
        logger.info(
            f"Proposed rebalance for vault '{vault_id}': "
            f"APY {current_apy:.2f}% → {proposed_apy:.2f}%, "
            f"Risk {current_risk:.2f} → {proposed_risk:.2f}"
        )
        
        return proposal
    
    def _calculate_weighted_apy(self, allocations: List[YieldAllocation]) -> Decimal:
        """Calculate weighted average APY."""
        total_apy = Decimal("0")
        for alloc in allocations:
            total_apy += alloc.apy * alloc.target_percentage / Decimal("100")
        return total_apy
    
    def _calculate_weighted_risk(self, allocations: List[YieldAllocation]) -> float:
        """Calculate weighted average risk score."""
        total_risk = 0.0
        for alloc in allocations:
            total_risk += alloc.risk_score * float(alloc.target_percentage) / 100.0
        return total_risk
    
    def execute_rebalance(self, proposal_id: str) -> None:
        """Execute approved rebalance."""
        proposal = next((p for p in self._rebalance_proposals if p.proposal_id == proposal_id), None)
        if not proposal:
            raise ValueError(f"Proposal '{proposal_id}' not found")
        
        if proposal.requires_approval and not proposal.approved:
            raise ValueError(f"Proposal '{proposal_id}' not approved")
        
        vault = self._vaults.get(proposal.vault_id)
        if not vault:
            raise ValueError(f"Vault '{proposal.vault_id}' not found")
        
        # Update vault allocations
        vault.target_allocations = proposal.proposed_allocations
        vault.last_rebalance = datetime.utcnow()
        
        proposal.executed_at = datetime.utcnow()
        
        logger.info(f"Executed rebalance for vault '{proposal.vault_id}'")
    
    def compound_vault(self, vault_id: str) -> Decimal:
        """Compound vault yields."""
        vault = self._vaults.get(vault_id)
        if not vault:
            raise ValueError(f"Vault '{vault_id}' not found")
        
        if not vault.auto_compound:
            return Decimal("0")
        
        # Calculate total yield to compound
        total_yield = sum(alloc.realized_yield_usd for alloc in vault.target_allocations)
        
        if total_yield < vault.min_compound_amount_usd:
            logger.debug(f"Vault '{vault_id}' yield ${total_yield} below min ${vault.min_compound_amount_usd}")
            return Decimal("0")
        
        # Compound (simplified: add to vault value)
        vault.total_value_usd += total_yield
        vault.total_yield_usd += total_yield
        
        # Reset realized yields
        for alloc in vault.target_allocations:
            alloc.realized_yield_usd = Decimal("0")
            alloc.last_compound = datetime.utcnow()
        
        logger.info(f"Compounded ${total_yield} for vault '{vault_id}'")
        
        return total_yield
    
    def get_vault(self, vault_id: str) -> Optional[VaultStrategy]:
        """Get vault by ID."""
        return self._vaults.get(vault_id)
    
    def get_all_vaults(self) -> List[VaultStrategy]:
        """Get all vaults."""
        return list(self._vaults.values())
    
    def get_user_positions(self, user_id: str) -> List[UserVaultPosition]:
        """Get user positions."""
        return [p for p in self._user_positions.values() if p.user_id == user_id]
    
    def get_pending_rebalances(self, vault_id: Optional[str] = None) -> List[RebalanceProposal]:
        """Get pending rebalance proposals."""
        proposals = [p for p in self._rebalance_proposals if p.executed_at is None]
        
        if vault_id:
            proposals = [p for p in proposals if p.vault_id == vault_id]
        
        return proposals


_yield_vaults: Optional[YieldVaults] = None


def get_yield_vaults() -> YieldVaults:
    """Get global YieldVaults instance."""
    global _yield_vaults
    if _yield_vaults is None:
        _yield_vaults = YieldVaults()
    return _yield_vaults
