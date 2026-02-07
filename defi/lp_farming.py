"""
Liquidity pool farming and DEX LP management for MERID.

Implements LP position management, concentrated liquidity, farming optimization,
and inventory hedging, all AI-optimized for best risk-adjusted returns.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class LPType(Enum):
    """LP type."""
    CONSTANT_PRODUCT = "constant_product"  # Uniswap V2-style
    CONCENTRATED = "concentrated"  # Uniswap V3-style
    STABLE_SWAP = "stable_swap"  # Curve-style
    WEIGHTED = "weighted"  # Balancer-style


class PriceRangeStrategy(Enum):
    """Price range strategy for concentrated liquidity."""
    NARROW = "narrow"  # Tight range, high fees, high IL risk
    MEDIUM = "medium"  # Balanced range
    WIDE = "wide"  # Wide range, lower fees, lower IL risk
    FULL_RANGE = "full_range"  # Full range (like V2)


class RewardType(Enum):
    """Reward type."""
    TRADING_FEES = "trading_fees"
    LIQUIDITY_MINING = "liquidity_mining"
    GOVERNANCE_TOKENS = "governance_tokens"
    BOOSTED_REWARDS = "boosted_rewards"


@dataclass
class LPPosition:
    """LP position."""
    position_id: str
    user_id: str
    
    # Pool info
    protocol: str
    pool_address: str
    lp_type: LPType
    token0: str
    token1: str
    
    # Position
    liquidity: Decimal
    token0_amount: Decimal
    token1_amount: Decimal
    total_value_usd: Decimal
    
    # Concentrated liquidity (if applicable)
    price_range_lower: Optional[Decimal] = None
    price_range_upper: Optional[Decimal] = None
    price_range_strategy: Optional[PriceRangeStrategy] = None
    in_range: bool = True
    
    # Performance
    fees_earned_usd: Decimal = Decimal("0")
    rewards_earned_usd: Decimal = Decimal("0")
    impermanent_loss_usd: Decimal = Decimal("0")
    net_pnl_usd: Decimal = Decimal("0")
    
    # APY breakdown
    fee_apy: Decimal = Decimal("0")
    reward_apy: Decimal = Decimal("0")
    total_apy: Decimal = Decimal("0")
    
    # Risk
    il_risk_score: float = 0.5
    volatility_24h: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_rebalance: Optional[datetime] = None


@dataclass
class FarmingOpportunity:
    """Farming opportunity."""
    opportunity_id: str
    protocol: str
    pool_address: str
    
    # Pool info
    token0: str
    token1: str
    lp_type: LPType
    tvl_usd: Decimal
    
    # Rewards
    base_fee_apy: Decimal
    liquidity_mining_apy: Decimal
    boosted_apy: Decimal
    total_apy: Decimal
    
    # Reward tokens
    reward_tokens: List[str] = field(default_factory=list)
    
    # Risk
    il_risk_score: float = 0.5
    protocol_risk: str = "medium"
    volatility_24h: float = 0.0
    
    # Incentive details
    incentive_program: Optional[str] = None
    incentive_end_date: Optional[datetime] = None
    
    # AI score
    ai_score: float = 0.0  # 0.0 to 1.0
    ai_rationale: Optional[str] = None
    
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RebalanceAction:
    """LP rebalance action."""
    action_id: str
    position_id: str
    
    # Action
    action_type: str  # "adjust_range", "add_liquidity", "remove_liquidity", "migrate"
    
    # Current state
    current_price_range: Optional[Tuple[Decimal, Decimal]] = None
    current_liquidity: Decimal = Decimal("0")
    
    # Proposed state
    new_price_range: Optional[Tuple[Decimal, Decimal]] = None
    new_liquidity: Decimal = Decimal("0")
    
    # Expected impact
    expected_fee_apy_change: Decimal = Decimal("0")
    expected_il_change: Decimal = Decimal("0")
    estimated_gas_cost_usd: Decimal = Decimal("0")
    
    # Rationale
    reason: str = ""
    ai_rationale: Optional[str] = None
    
    # Execution
    approved: bool = False
    executed: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None


@dataclass
class InventoryHedge:
    """Inventory hedge for LP position."""
    hedge_id: str
    position_id: str
    
    # Hedge details
    hedged_asset: str
    hedge_amount: Decimal
    hedge_type: str  # "perp_short", "options_put", "spot_sell"
    
    # Cost
    hedge_cost_usd: Decimal
    funding_rate: Optional[Decimal] = None
    
    # Effectiveness
    il_reduction_percentage: Decimal = Decimal("0")
    net_apy_impact: Decimal = Decimal("0")
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None


class LPFarming:
    """
    Liquidity pool farming and DEX LP management for MERID.
    
    Implements:
    - LP position management across DEXs
    - Concentrated liquidity optimization
    - Farming opportunity discovery
    - Price range rebalancing
    - Inventory hedging
    - Gas-optimized compounding
    """
    
    def __init__(self):
        self._positions: Dict[str, LPPosition] = {}
        self._opportunities: Dict[str, FarmingOpportunity] = {}
        self._rebalance_actions: List[RebalanceAction] = []
        self._hedges: Dict[str, InventoryHedge] = {}
        
        self._initialize_opportunities()
    
    def _initialize_opportunities(self) -> None:
        """Initialize farming opportunities."""
        
        # Uniswap V3 ETH-USDC (high volume, tight spreads)
        self.add_opportunity(
            opportunity_id="uniswap_v3_eth_usdc_005",
            protocol="uniswap_v3",
            pool_address="0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
            token0="ETH",
            token1="USDC",
            lp_type=LPType.CONCENTRATED,
            tvl_usd=Decimal("500000000"),
            base_fee_apy=Decimal("15.0"),
            liquidity_mining_apy=Decimal("5.0"),
            boosted_apy=Decimal("0"),
            il_risk_score=0.6,
            protocol_risk="low",
            volatility_24h=0.03,
        )
        
        # Curve 3pool (stable, low IL)
        self.add_opportunity(
            opportunity_id="curve_3pool",
            protocol="curve",
            pool_address="0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7",
            token0="USDC",
            token1="USDT",
            lp_type=LPType.STABLE_SWAP,
            tvl_usd=Decimal("2000000000"),
            base_fee_apy=Decimal("3.0"),
            liquidity_mining_apy=Decimal("8.0"),
            boosted_apy=Decimal("4.0"),
            reward_tokens=["CRV", "CVX"],
            il_risk_score=0.1,
            protocol_risk="low",
            volatility_24h=0.001,
        )
        
        # Balancer 80/20 ETH-USDC (weighted, lower IL)
        self.add_opportunity(
            opportunity_id="balancer_eth_usdc_8020",
            protocol="balancer",
            pool_address="0x96646936b91d6b9d7d0c47c496afbf3d6ec7b6f8",
            token0="ETH",
            token1="USDC",
            lp_type=LPType.WEIGHTED,
            tvl_usd=Decimal("100000000"),
            base_fee_apy=Decimal("8.0"),
            liquidity_mining_apy=Decimal("12.0"),
            boosted_apy=Decimal("0"),
            reward_tokens=["BAL"],
            il_risk_score=0.4,
            protocol_risk="medium",
            volatility_24h=0.025,
        )
        
        logger.info(f"Initialized {len(self._opportunities)} farming opportunities")
    
    def add_opportunity(
        self,
        opportunity_id: str,
        protocol: str,
        pool_address: str,
        token0: str,
        token1: str,
        lp_type: LPType,
        tvl_usd: Decimal,
        base_fee_apy: Decimal,
        liquidity_mining_apy: Decimal,
        boosted_apy: Decimal,
        il_risk_score: float = 0.5,
        protocol_risk: str = "medium",
        volatility_24h: float = 0.0,
        reward_tokens: Optional[List[str]] = None,
    ) -> FarmingOpportunity:
        """Add farming opportunity."""
        opportunity = FarmingOpportunity(
            opportunity_id=opportunity_id,
            protocol=protocol,
            pool_address=pool_address,
            token0=token0,
            token1=token1,
            lp_type=lp_type,
            tvl_usd=tvl_usd,
            base_fee_apy=base_fee_apy,
            liquidity_mining_apy=liquidity_mining_apy,
            boosted_apy=boosted_apy,
            total_apy=base_fee_apy + liquidity_mining_apy + boosted_apy,
            reward_tokens=reward_tokens or [],
            il_risk_score=il_risk_score,
            protocol_risk=protocol_risk,
            volatility_24h=volatility_24h,
        )
        
        # Calculate AI score (risk-adjusted return)
        opportunity.ai_score = self._calculate_opportunity_score(opportunity)
        
        self._opportunities[opportunity_id] = opportunity
        
        return opportunity
    
    def _calculate_opportunity_score(self, opp: FarmingOpportunity) -> float:
        """Calculate AI score for opportunity (0.0 to 1.0)."""
        # Risk-adjusted return
        risk_penalty = opp.il_risk_score * 0.5 + opp.volatility_24h * 10
        risk_adjusted_apy = float(opp.total_apy) - risk_penalty * 10
        
        # Protocol risk penalty
        protocol_penalty = {"low": 0, "medium": 5, "high": 15}.get(opp.protocol_risk, 10)
        risk_adjusted_apy -= protocol_penalty
        
        # Normalize to 0-1 (assume max APY ~100%)
        score = max(0.0, min(1.0, risk_adjusted_apy / 100.0))
        
        return score
    
    def create_lp_position(
        self,
        user_id: str,
        opportunity_id: str,
        token0_amount: Decimal,
        token1_amount: Decimal,
        price_range_strategy: Optional[PriceRangeStrategy] = None,
    ) -> LPPosition:
        """Create LP position."""
        opportunity = self._opportunities.get(opportunity_id)
        if not opportunity:
            raise ValueError(f"Opportunity '{opportunity_id}' not found")
        
        position_id = f"lp_{user_id}_{opportunity_id}_{int(datetime.utcnow().timestamp())}"
        
        # Calculate liquidity (simplified)
        liquidity = (token0_amount + token1_amount) / 2
        total_value_usd = token0_amount + token1_amount  # Simplified: assume 1:1 USD
        
        position = LPPosition(
            position_id=position_id,
            user_id=user_id,
            protocol=opportunity.protocol,
            pool_address=opportunity.pool_address,
            lp_type=opportunity.lp_type,
            token0=opportunity.token0,
            token1=opportunity.token1,
            liquidity=liquidity,
            token0_amount=token0_amount,
            token1_amount=token1_amount,
            total_value_usd=total_value_usd,
            price_range_strategy=price_range_strategy,
            fee_apy=opportunity.base_fee_apy,
            reward_apy=opportunity.liquidity_mining_apy + opportunity.boosted_apy,
            total_apy=opportunity.total_apy,
            il_risk_score=opportunity.il_risk_score,
            volatility_24h=opportunity.volatility_24h,
        )
        
        # Set price range for concentrated liquidity
        if opportunity.lp_type == LPType.CONCENTRATED and price_range_strategy:
            position.price_range_lower, position.price_range_upper = self._calculate_price_range(
                price_range_strategy
            )
        
        self._positions[position_id] = position
        
        logger.info(
            f"Created LP position '{position_id}' for user '{user_id}': "
            f"{opportunity.protocol} {opportunity.token0}-{opportunity.token1} "
            f"(${total_value_usd}, APY: {opportunity.total_apy}%)"
        )
        
        return position
    
    def _calculate_price_range(
        self,
        strategy: PriceRangeStrategy,
        current_price: Decimal = Decimal("1.0"),
    ) -> Tuple[Decimal, Decimal]:
        """Calculate price range for concentrated liquidity."""
        if strategy == PriceRangeStrategy.NARROW:
            # ±5% range
            return (current_price * Decimal("0.95"), current_price * Decimal("1.05"))
        elif strategy == PriceRangeStrategy.MEDIUM:
            # ±10% range
            return (current_price * Decimal("0.90"), current_price * Decimal("1.10"))
        elif strategy == PriceRangeStrategy.WIDE:
            # ±20% range
            return (current_price * Decimal("0.80"), current_price * Decimal("1.20"))
        else:  # FULL_RANGE
            # Full range (0 to infinity)
            return (Decimal("0"), Decimal("999999999"))
    
    def propose_rebalance(
        self,
        position_id: str,
        action_type: str,
        reason: str,
        new_price_range: Optional[Tuple[Decimal, Decimal]] = None,
        ai_rationale: Optional[str] = None,
    ) -> RebalanceAction:
        """Propose LP position rebalance."""
        position = self._positions.get(position_id)
        if not position:
            raise ValueError(f"Position '{position_id}' not found")
        
        action_id = f"rebalance_{position_id}_{int(datetime.utcnow().timestamp())}"
        
        action = RebalanceAction(
            action_id=action_id,
            position_id=position_id,
            action_type=action_type,
            current_price_range=(position.price_range_lower, position.price_range_upper) if position.price_range_lower else None,
            current_liquidity=position.liquidity,
            new_price_range=new_price_range,
            reason=reason,
            ai_rationale=ai_rationale,
        )
        
        self._rebalance_actions.append(action)
        
        logger.info(
            f"Proposed rebalance for position '{position_id}': {action_type} - {reason}"
        )
        
        return action
    
    def execute_rebalance(self, action_id: str) -> None:
        """Execute approved rebalance."""
        action = next((a for a in self._rebalance_actions if a.action_id == action_id), None)
        if not action:
            raise ValueError(f"Action '{action_id}' not found")
        
        if not action.approved:
            raise ValueError(f"Action '{action_id}' not approved")
        
        position = self._positions.get(action.position_id)
        if not position:
            raise ValueError(f"Position '{action.position_id}' not found")
        
        # Update position
        if action.new_price_range:
            position.price_range_lower, position.price_range_upper = action.new_price_range
        
        position.last_rebalance = datetime.utcnow()
        action.executed = True
        action.executed_at = datetime.utcnow()
        
        logger.info(f"Executed rebalance for position '{action.position_id}'")
    
    def create_inventory_hedge(
        self,
        position_id: str,
        hedged_asset: str,
        hedge_amount: Decimal,
        hedge_type: str,
        hedge_cost_usd: Decimal,
    ) -> InventoryHedge:
        """Create inventory hedge for LP position."""
        position = self._positions.get(position_id)
        if not position:
            raise ValueError(f"Position '{position_id}' not found")
        
        hedge_id = f"hedge_{position_id}_{int(datetime.utcnow().timestamp())}"
        
        hedge = InventoryHedge(
            hedge_id=hedge_id,
            position_id=position_id,
            hedged_asset=hedged_asset,
            hedge_amount=hedge_amount,
            hedge_type=hedge_type,
            hedge_cost_usd=hedge_cost_usd,
        )
        
        self._hedges[hedge_id] = hedge
        
        logger.info(
            f"Created inventory hedge for position '{position_id}': "
            f"{hedge_type} {hedge_amount} {hedged_asset}"
        )
        
        return hedge
    
    def get_top_opportunities(
        self,
        limit: int = 10,
        min_tvl_usd: Optional[Decimal] = None,
        max_il_risk: Optional[float] = None,
    ) -> List[FarmingOpportunity]:
        """Get top farming opportunities by AI score."""
        opportunities = list(self._opportunities.values())
        
        # Filter
        if min_tvl_usd:
            opportunities = [o for o in opportunities if o.tvl_usd >= min_tvl_usd]
        
        if max_il_risk:
            opportunities = [o for o in opportunities if o.il_risk_score <= max_il_risk]
        
        # Sort by AI score
        opportunities.sort(key=lambda o: o.ai_score, reverse=True)
        
        return opportunities[:limit]
    
    def get_user_positions(self, user_id: str) -> List[LPPosition]:
        """Get user LP positions."""
        return [p for p in self._positions.values() if p.user_id == user_id]
    
    def get_position(self, position_id: str) -> Optional[LPPosition]:
        """Get LP position by ID."""
        return self._positions.get(position_id)
    
    def get_pending_rebalances(self, position_id: Optional[str] = None) -> List[RebalanceAction]:
        """Get pending rebalance actions."""
        actions = [a for a in self._rebalance_actions if not a.executed]
        
        if position_id:
            actions = [a for a in actions if a.position_id == position_id]
        
        return actions


_lp_farming: Optional[LPFarming] = None


def get_lp_farming() -> LPFarming:
    """Get global LPFarming instance."""
    global _lp_farming
    if _lp_farming is None:
        _lp_farming = LPFarming()
    return _lp_farming
