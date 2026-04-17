"""
MEV-aware reward system for MERID.

Implements:
- Health-weighted reward pools
- MEV classification (safe/neutral/harmful)
- Protocol health scoring
- Cooperative MEV incentives
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class MEVCategory(Enum):
    """MEV category."""
    SAFE = "safe"  # Benign arbitrage, spread tightening
    NEUTRAL = "neutral"  # Standard MEV
    HARMFUL = "harmful"  # Toxic sandwiching, griefing


class MEVType(Enum):
    """Type of MEV."""
    ARBITRAGE = "arbitrage"
    BACKRUN = "backrun"
    SANDWICH = "sandwich"
    LIQUIDATION = "liquidation"
    FRONTRUN = "frontrun"


@dataclass
class MEVAction:
    """MEV action."""
    action_id: str
    actor_id: str
    
    # Type and category
    mev_type: MEVType
    mev_category: MEVCategory
    
    # Details
    block_number: int = 0
    transaction_hash: str = ""
    
    # Impact
    profit_usd: Decimal = Decimal("0")
    user_impact_usd: Decimal = Decimal("0")  # Negative = harmful to users
    
    # Protocol health impact
    spread_improvement_bps: float = 0.0
    liquidity_improvement_usd: Decimal = Decimal("0")
    slippage_reduction_bps: float = 0.0
    
    # Scoring
    health_score: float = 0.0  # -1.0 (harmful) to 1.0 (beneficial)
    
    # Rewards
    base_reward: Decimal = Decimal("0")
    health_bonus: Decimal = Decimal("0")
    total_reward: Decimal = Decimal("0")
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthMetrics:
    """Protocol health metrics for MEV scoring."""
    
    # Liquidity
    average_depth_usd: Decimal = Decimal("0")
    depth_improvement_pct: float = 0.0
    
    # Spreads
    average_spread_bps: float = 0.0
    spread_improvement_bps: float = 0.0
    
    # Execution quality
    average_slippage_bps: float = 0.0
    slippage_reduction_bps: float = 0.0
    failure_rate: float = 0.0
    
    # Liquidations
    liquidation_quality_score: float = 0.0  # 0.0 (poor) to 1.0 (excellent)
    
    # RWA
    rwa_coverage_pct: float = 0.0
    
    # Overall
    overall_health_score: float = 0.0  # 0.0 (poor) to 1.0 (excellent)
    
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RewardPool:
    """MEV reward pool."""
    pool_id: str
    pool_name: str
    
    # Balance
    total_balance: Decimal = Decimal("0")
    distributed: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    
    # Distribution rules
    safe_mev_share: float = 0.7  # 70% to safe MEV
    neutral_mev_share: float = 0.2  # 20% to neutral MEV
    harmful_mev_penalty: float = -1.0  # Slash harmful MEV
    
    # Health weighting
    health_weight: float = 0.5  # 50% weight on health improvement
    
    # Epoch
    epoch_duration_hours: int = 24
    current_epoch: int = 0
    epoch_start: datetime = field(default_factory=datetime.utcnow)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ActorStats:
    """MEV actor statistics."""
    actor_id: str
    
    # Actions
    total_actions: int = 0
    safe_actions: int = 0
    neutral_actions: int = 0
    harmful_actions: int = 0
    
    # Profit
    total_profit_usd: Decimal = Decimal("0")
    
    # Impact
    total_user_impact_usd: Decimal = Decimal("0")
    total_health_score: float = 0.0
    
    # Rewards
    total_rewards: Decimal = Decimal("0")
    total_penalties: Decimal = Decimal("0")
    
    # Tier
    current_tier: str = "bronze"
    badges: Set[str] = field(default_factory=set)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class MEVRewardSystem:
    """
    MEV-aware reward system for MERID.
    
    Implements:
    - Health-weighted reward pools
    - MEV classification (safe/neutral/harmful)
    - Protocol health scoring
    - Cooperative MEV incentives
    - Penalties for harmful behavior
    """
    
    _action_counter: int = 0
    
    def __init__(self):
        self._mev_actions: List[MEVAction] = []
        self._reward_pools: Dict[str, RewardPool] = {}
        self._actor_stats: Dict[str, ActorStats] = {}
        self._health_metrics = HealthMetrics()
        
        self._initialize_reward_pools()
    
    def _initialize_reward_pools(self) -> None:
        """Initialize reward pools."""
        
        # Main MEV reward pool
        self.create_reward_pool(
            pool_name="Main MEV Rewards",
            initial_balance=Decimal("100000"),
            safe_mev_share=0.7,
            neutral_mev_share=0.2,
            harmful_mev_penalty=-1.0,
            health_weight=0.5,
        )
        
        logger.info("Initialized MEV reward pools")
    
    def create_reward_pool(
        self,
        pool_name: str,
        initial_balance: Decimal,
        safe_mev_share: float = 0.7,
        neutral_mev_share: float = 0.2,
        harmful_mev_penalty: float = -1.0,
        health_weight: float = 0.5,
    ) -> RewardPool:
        """Create reward pool."""
        pool_id = f"pool_{int(datetime.utcnow().timestamp())}"
        
        pool = RewardPool(
            pool_id=pool_id,
            pool_name=pool_name,
            total_balance=initial_balance,
            remaining=initial_balance,
            safe_mev_share=safe_mev_share,
            neutral_mev_share=neutral_mev_share,
            harmful_mev_penalty=harmful_mev_penalty,
            health_weight=health_weight,
        )
        
        self._reward_pools[pool_id] = pool
        
        logger.info(
            f"Created reward pool '{pool_id}': {pool_name} "
            f"(balance: ${initial_balance})"
        )
        
        return pool
    
    def classify_mev_action(
        self,
        mev_type: MEVType,
        user_impact_usd: Decimal,
        spread_improvement_bps: float = 0.0,
    ) -> MEVCategory:
        """Classify MEV action."""
        
        # Harmful MEV
        if mev_type == MEVType.SANDWICH:
            return MEVCategory.HARMFUL
        
        if mev_type == MEVType.FRONTRUN and user_impact_usd < Decimal("0"):
            return MEVCategory.HARMFUL
        
        # Safe MEV (improves protocol health)
        if mev_type == MEVType.ARBITRAGE and spread_improvement_bps > 0:
            return MEVCategory.SAFE
        
        if mev_type == MEVType.LIQUIDATION:
            return MEVCategory.SAFE
        
        if mev_type == MEVType.BACKRUN and user_impact_usd >= Decimal("0"):
            return MEVCategory.SAFE
        
        # Neutral MEV
        return MEVCategory.NEUTRAL
    
    def record_mev_action(
        self,
        actor_id: str,
        mev_type: MEVType,
        block_number: int,
        transaction_hash: str,
        profit_usd: Decimal,
        user_impact_usd: Decimal = Decimal("0"),
        spread_improvement_bps: float = 0.0,
        liquidity_improvement_usd: Decimal = Decimal("0"),
        slippage_reduction_bps: float = 0.0,
    ) -> MEVAction:
        """Record MEV action."""
        MEVRewardSystem._action_counter += 1
        action_id = f"mev_{int(datetime.utcnow().timestamp())}_{MEVRewardSystem._action_counter}"
        
        # Classify action
        mev_category = self.classify_mev_action(
            mev_type=mev_type,
            user_impact_usd=user_impact_usd,
            spread_improvement_bps=spread_improvement_bps,
        )
        
        # Calculate health score
        health_score = self._calculate_health_score(
            mev_category=mev_category,
            user_impact_usd=user_impact_usd,
            spread_improvement_bps=spread_improvement_bps,
            liquidity_improvement_usd=liquidity_improvement_usd,
            slippage_reduction_bps=slippage_reduction_bps,
        )
        
        action = MEVAction(
            action_id=action_id,
            actor_id=actor_id,
            mev_type=mev_type,
            mev_category=mev_category,
            block_number=block_number,
            transaction_hash=transaction_hash,
            profit_usd=profit_usd,
            user_impact_usd=user_impact_usd,
            spread_improvement_bps=spread_improvement_bps,
            liquidity_improvement_usd=liquidity_improvement_usd,
            slippage_reduction_bps=slippage_reduction_bps,
            health_score=health_score,
        )
        
        self._mev_actions.append(action)
        
        # Update actor stats
        self._update_actor_stats(action)
        
        logger.info(
            f"Recorded MEV action: {action_id} by {actor_id} "
            f"({mev_type.value}, {mev_category.value}, "
            f"health_score={health_score:.2f})"
        )
        
        return action
    
    def calculate_reward(
        self,
        action_id: str,
        pool_id: Optional[str] = None,
    ) -> MEVAction:
        """Calculate reward for MEV action."""
        action = next(
            (a for a in self._mev_actions if a.action_id == action_id),
            None,
        )
        
        if not action:
            raise ValueError(f"MEV action '{action_id}' not found")
        
        # Get pool (use first pool if not specified)
        if not pool_id:
            pool_id = list(self._reward_pools.keys())[0]
        
        pool = self._reward_pools[pool_id]
        
        # Base reward (proportional to profit)
        base_reward = action.profit_usd * Decimal("0.1")  # 10% of profit
        
        # Category multiplier
        category_multiplier = {
            MEVCategory.SAFE: Decimal(str(pool.safe_mev_share)),
            MEVCategory.NEUTRAL: Decimal(str(pool.neutral_mev_share)),
            MEVCategory.HARMFUL: Decimal(str(pool.harmful_mev_penalty)),
        }[action.mev_category]
        
        # Health bonus (based on health score and weight)
        health_bonus = Decimal("0")
        if action.health_score > 0:
            health_bonus = (
                base_reward
                * Decimal(str(action.health_score))
                * Decimal(str(pool.health_weight))
            )
        
        # Total reward
        total_reward = (base_reward * category_multiplier) + health_bonus
        
        # Penalties for harmful MEV
        if action.mev_category == MEVCategory.HARMFUL:
            total_reward = min(total_reward, Decimal("0"))  # No positive rewards
        
        action.base_reward = base_reward
        action.health_bonus = health_bonus
        action.total_reward = total_reward
        
        logger.info(
            f"Calculated reward for {action_id}: "
            f"base=${base_reward:.2f}, health_bonus=${health_bonus:.2f}, "
            f"total=${total_reward:.2f}"
        )
        
        return action
    
    def distribute_rewards(
        self,
        pool_id: str,
        action_ids: List[str],
    ) -> Dict[str, Decimal]:
        """Distribute rewards from pool."""
        pool = self._reward_pools.get(pool_id)
        
        if not pool:
            raise ValueError(f"Reward pool '{pool_id}' not found")
        
        rewards_by_actor: Dict[str, Decimal] = {}
        
        for action_id in action_ids:
            action = next(
                (a for a in self._mev_actions if a.action_id == action_id),
                None,
            )
            
            if not action:
                continue
            
            # Calculate reward if not already calculated
            if action.total_reward == Decimal("0"):
                self.calculate_reward(action_id, pool_id)
            
            # Accumulate by actor
            if action.actor_id not in rewards_by_actor:
                rewards_by_actor[action.actor_id] = Decimal("0")
            
            rewards_by_actor[action.actor_id] += action.total_reward
            
            # Update pool
            pool.distributed += action.total_reward
            pool.remaining -= action.total_reward
        
        logger.info(
            f"Distributed rewards from pool '{pool_id}': "
            f"${pool.distributed} to {len(rewards_by_actor)} actors"
        )
        
        return rewards_by_actor
    
    def update_health_metrics(
        self,
        average_depth_usd: Optional[Decimal] = None,
        average_spread_bps: Optional[float] = None,
        average_slippage_bps: Optional[float] = None,
        failure_rate: Optional[float] = None,
        liquidation_quality_score: Optional[float] = None,
        rwa_coverage_pct: Optional[float] = None,
    ) -> HealthMetrics:
        """Update protocol health metrics."""
        if average_depth_usd is not None:
            self._health_metrics.average_depth_usd = average_depth_usd
        
        if average_spread_bps is not None:
            self._health_metrics.average_spread_bps = average_spread_bps
        
        if average_slippage_bps is not None:
            self._health_metrics.average_slippage_bps = average_slippage_bps
        
        if failure_rate is not None:
            self._health_metrics.failure_rate = failure_rate
        
        if liquidation_quality_score is not None:
            self._health_metrics.liquidation_quality_score = liquidation_quality_score
        
        if rwa_coverage_pct is not None:
            self._health_metrics.rwa_coverage_pct = rwa_coverage_pct
        
        # Calculate overall health score
        self._health_metrics.overall_health_score = self._calculate_overall_health()
        
        self._health_metrics.last_updated = datetime.utcnow()
        
        return self._health_metrics
    
    def _calculate_health_score(
        self,
        mev_category: MEVCategory,
        user_impact_usd: Decimal,
        spread_improvement_bps: float,
        liquidity_improvement_usd: Decimal,
        slippage_reduction_bps: float,
    ) -> float:
        """Calculate health score for MEV action."""
        score = 0.0
        
        # Category base score
        if mev_category == MEVCategory.SAFE:
            score += 0.5
        elif mev_category == MEVCategory.HARMFUL:
            score -= 0.5
        
        # User impact
        if user_impact_usd > Decimal("0"):
            score += 0.2
        elif user_impact_usd < Decimal("0"):
            score -= 0.3
        
        # Spread improvement
        if spread_improvement_bps > 0:
            score += min(spread_improvement_bps / 10.0, 0.3)
        
        # Liquidity improvement
        if liquidity_improvement_usd > Decimal("0"):
            score += 0.2
        
        # Slippage reduction
        if slippage_reduction_bps > 0:
            score += min(slippage_reduction_bps / 10.0, 0.2)
        
        # Clamp to [-1.0, 1.0]
        return max(-1.0, min(1.0, score))
    
    def _calculate_overall_health(self) -> float:
        """Calculate overall protocol health score."""
        score = 0.0
        
        # Liquidity depth (higher is better)
        if self._health_metrics.average_depth_usd > Decimal("100000"):
            score += 0.2
        
        # Spreads (lower is better)
        if self._health_metrics.average_spread_bps < 10.0:
            score += 0.2
        
        # Slippage (lower is better)
        if self._health_metrics.average_slippage_bps < 5.0:
            score += 0.2
        
        # Failure rate (lower is better)
        if self._health_metrics.failure_rate < 0.01:
            score += 0.2
        
        # Liquidation quality
        score += self._health_metrics.liquidation_quality_score * 0.2
        
        return score
    
    def _update_actor_stats(self, action: MEVAction) -> None:
        """Update actor statistics."""
        if action.actor_id not in self._actor_stats:
            self._actor_stats[action.actor_id] = ActorStats(actor_id=action.actor_id)
        
        stats = self._actor_stats[action.actor_id]
        
        stats.total_actions += 1
        
        if action.mev_category == MEVCategory.SAFE:
            stats.safe_actions += 1
        elif action.mev_category == MEVCategory.NEUTRAL:
            stats.neutral_actions += 1
        elif action.mev_category == MEVCategory.HARMFUL:
            stats.harmful_actions += 1
        
        stats.total_profit_usd += action.profit_usd
        stats.total_user_impact_usd += action.user_impact_usd
        stats.total_health_score += action.health_score
        
        # Award badges
        if stats.safe_actions >= 100:
            stats.badges.add("safe_mev_specialist")
        
        if stats.total_health_score >= 50.0:
            stats.badges.add("protocol_guardian")
    
    def get_actor_stats(self, actor_id: str) -> Optional[ActorStats]:
        """Get actor statistics."""
        return self._actor_stats.get(actor_id)
    
    def get_health_metrics(self) -> HealthMetrics:
        """Get current health metrics."""
        return self._health_metrics


_mev_reward_system: Optional[MEVRewardSystem] = None
_mev_reward_system_lock = threading.Lock()


def get_mev_reward_system() -> MEVRewardSystem:
    """Get global MEVRewardSystem instance."""
    global _mev_reward_system
    if _mev_reward_system is None:
        with _mev_reward_system_lock:
            if _mev_reward_system is None:
                _mev_reward_system = MEVRewardSystem()
    return _mev_reward_system
