"""Flow domain models — tokens, entities, flow events, opinions, plans, sniper orders.

Covers:
  - Token: on-chain token/memecoin with liquidity and launch info
  - Entity: whale, smart wallet, KOL, deployer, CEX endpoint
  - FlowEvent: normalized on-chain/off-chain event
  - FlowOpinion: swarm opinion on a token in flow context
  - MemePlan / WhalePlan / KOLPlan: specialized trade plans
  - SniperOrder / SniperFill: MEV-aware execution records
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────

class Chain(str, Enum):
    """Supported chains."""
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    BASE = "base"
    ARBITRUM = "arbitrum"
    POLYGON = "polygon"
    BSC = "bsc"
    AVALANCHE = "avalanche"
    OPTIMISM = "optimism"


class EntityType(str, Enum):
    """Type of on-chain entity."""
    WHALE = "whale"
    SMART_WALLET = "smart_wallet"
    KOL = "kol"
    DEPLOYER = "deployer"
    CEX = "cex"


class FlowEventType(str, Enum):
    """Types of flow events in the domain."""
    TOKEN_LAUNCH = "token_launch"
    LP_ADDED = "lp_added"
    LP_REMOVED = "lp_removed"
    LARGE_BUY = "large_buy"
    LARGE_SELL = "large_sell"
    BRIDGE_IN = "bridge_in"
    BRIDGE_OUT = "bridge_out"
    CEX_DEPOSIT = "cex_deposit"
    CEX_WITHDRAWAL = "cex_withdrawal"
    WHALE_POSITION_CHANGE = "whale_position_change"
    KOL_BUY = "kol_buy"
    KOL_SELL = "kol_sell"
    KOL_MENTION = "kol_mention"
    NEW_CEX_LISTING = "new_cex_listing"
    DEPLOYER_ACTION = "deployer_action"
    AIRDROP = "airdrop"


class FlowStance(str, Enum):
    """Swarm stance on a token in flow context."""
    AVOID = "avoid"
    WATCH = "watch"
    SPEC_LONG = "spec_long"
    SPEC_SHORT = "spec_short"


class MevRiskTolerance(str, Enum):
    """MEV risk tolerance for sniper orders."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStatus(str, Enum):
    """Status lifecycle for flow plans."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIAL_FILL = "partial_fill"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RouteType(str, Enum):
    """Execution routing type."""
    STANDARD = "standard"
    MEV_PROTECTED = "mev_protected"
    PRIVATE_TX = "private_tx"


# ── Helpers ───────────────────────────────────────────────────────────

def _uid(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


def _now() -> float:
    return time.time()


def estimate_price_impact(size_usd: float, pool_liquidity_usd: float) -> float:
    """Rough price impact estimate: size / (2 * liquidity).

    Returns a fraction (e.g., 0.02 = 2%).
    """
    if pool_liquidity_usd <= 0:
        return 1.0
    return min(size_usd / (2.0 * pool_liquidity_usd), 1.0)


def classify_entity_quality(pnl_usd: float, hit_rate: float, trade_count: int) -> str:
    """Classify entity quality based on historical performance.

    Returns: 'elite', 'good', 'average', 'poor', 'unknown'.
    """
    if trade_count < 5:
        return "unknown"
    if hit_rate >= 0.65 and pnl_usd > 10000:
        return "elite"
    if hit_rate >= 0.55 and pnl_usd > 1000:
        return "good"
    if hit_rate >= 0.45:
        return "average"
    return "poor"


def compute_flow_score(
    whale_buys: int, whale_sells: int,
    kol_buys: int, kol_mentions: int,
    lp_adds: int, lp_removes: int,
    age_hours: float,
) -> float:
    """Compute a 0-100 flow score for a token based on recent activity.

    Higher = more bullish flow signal.
    """
    score = 50.0

    # Whale net flow
    whale_net = whale_buys - whale_sells
    score += min(whale_net * 5.0, 20.0)
    score -= min(max(-whale_net, 0) * 5.0, 20.0)

    # KOL activity
    score += min(kol_buys * 4.0, 15.0)
    score += min(kol_mentions * 2.0, 10.0)

    # Liquidity health
    lp_net = lp_adds - lp_removes
    score += min(lp_net * 3.0, 10.0)
    score -= min(max(-lp_net, 0) * 5.0, 15.0)

    # Age penalty: very new tokens get a small boost, very old get neutral
    if age_hours < 1:
        score += 5.0  # fresh launch bonus
    elif age_hours > 168:  # > 1 week
        score -= 5.0

    return max(0.0, min(100.0, score))


# ── Token ─────────────────────────────────────────────────────────────

@dataclass
class LiquidityInfo:
    """Liquidity snapshot for a token."""
    pool_address: str = ""
    dex: str = ""  # e.g., "raydium", "uniswap_v3", "orca"
    base_token: str = ""  # e.g., "SOL", "ETH", "USDC"
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    price_usd: float = 0.0
    pool_created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Token:
    """On-chain token / memecoin that MERID tracks."""
    id: str = ""
    symbol: str = ""
    name: str = ""
    contract_address: str = ""
    chain: str = Chain.SOLANA.value
    decimals: int = 9
    logo_url: str = ""
    tags: List[str] = field(default_factory=list)

    # Launch info
    deployer_address: str = ""
    first_lp_timestamp: float = 0.0
    initial_mcap_usd: float = 0.0
    fdv_usd: float = 0.0

    # Current liquidity
    liquidity: List[LiquidityInfo] = field(default_factory=list)
    total_liquidity_usd: float = 0.0
    cex_listings: List[str] = field(default_factory=list)

    # Tracking state
    is_active: bool = True
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("tok-")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["liquidity"] = [li if isinstance(li, dict) else asdict(li) for li in (self.liquidity or [])]
        return d

    @property
    def age_hours(self) -> float:
        if self.first_lp_timestamp <= 0:
            return 0.0
        return (_now() - self.first_lp_timestamp) / 3600.0

    @property
    def best_liquidity_usd(self) -> float:
        if not self.liquidity:
            return self.total_liquidity_usd
        return max((li.liquidity_usd for li in self.liquidity), default=0.0)

    @property
    def current_price_usd(self) -> float:
        if not self.liquidity:
            return 0.0
        # Use the pool with highest liquidity
        best = max(self.liquidity, key=lambda li: li.liquidity_usd)
        return best.price_usd


# ── Entity ────────────────────────────────────────────────────────────

@dataclass
class Entity:
    """On-chain entity MERID tracks: whale, smart wallet, KOL, deployer, CEX."""
    id: str = ""
    address: str = ""
    chain: str = Chain.SOLANA.value
    entity_type: str = EntityType.WHALE.value
    label: str = ""  # human-readable name
    tags: List[str] = field(default_factory=list)

    # Social / identity (for KOLs)
    social_handle: str = ""  # X/Twitter handle
    telegram_handle: str = ""
    follower_count: int = 0

    # Historical performance
    historical_pnl_usd: float = 0.0
    hit_rate: float = 0.0  # fraction [0,1]
    trade_count: int = 0
    avg_holding_hours: float = 0.0

    # State
    is_active: bool = True
    quality: str = "unknown"  # elite/good/average/poor/unknown
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("ent-")
        if self.quality == "unknown" and self.trade_count > 0:
            self.quality = classify_entity_quality(
                self.historical_pnl_usd, self.hit_rate, self.trade_count
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── FlowEvent ─────────────────────────────────────────────────────────

@dataclass
class FlowEvent:
    """Normalized flow event — things that happen in the meme/whale/KOL domain."""
    id: str = ""
    event_type: str = FlowEventType.LARGE_BUY.value
    chain: str = Chain.SOLANA.value
    token_id: str = ""
    token_symbol: str = ""
    entity_id: str = ""
    entity_address: str = ""
    entity_type: str = ""

    # Transaction details
    size_usd: float = 0.0
    size_tokens: float = 0.0
    direction: str = "buy"  # buy/sell/add/remove/bridge
    tx_hash: str = ""
    price_usd: float = 0.0

    # Impact
    price_impact: float = 0.0
    slippage: float = 0.0
    pool_liquidity_before: float = 0.0
    pool_liquidity_after: float = 0.0

    # Off-chain (for KOL mentions)
    mention_text: str = ""
    mention_sentiment: float = 0.0  # -1 to +1
    mention_engagement: int = 0
    mention_source: str = ""  # "x", "telegram", "news"

    timestamp: float = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("fe-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_bullish(self) -> bool:
        bullish_types = {
            FlowEventType.LARGE_BUY.value,
            FlowEventType.KOL_BUY.value,
            FlowEventType.LP_ADDED.value,
            FlowEventType.CEX_WITHDRAWAL.value,
            FlowEventType.BRIDGE_IN.value,
            FlowEventType.NEW_CEX_LISTING.value,
        }
        return self.event_type in bullish_types

    @property
    def is_bearish(self) -> bool:
        bearish_types = {
            FlowEventType.LARGE_SELL.value,
            FlowEventType.KOL_SELL.value,
            FlowEventType.LP_REMOVED.value,
            FlowEventType.CEX_DEPOSIT.value,
            FlowEventType.BRIDGE_OUT.value,
        }
        return self.event_type in bearish_types


# ── Flow opinions ─────────────────────────────────────────────────────

@dataclass
class FlowOpinion:
    """Swarm opinion on a token in flow context."""
    id: str = ""
    agent_id: str = ""
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value
    contract_address: str = ""

    stance: str = FlowStance.WATCH.value
    probability: float = 0.5  # expected probability of positive return
    expected_return_1h: float = 0.0  # expected % return next 1h
    expected_return_24h: float = 0.0
    confidence: float = 0.5
    reasoning: str = ""

    # Drivers — references to flow events that informed this opinion
    driver_event_ids: List[str] = field(default_factory=list)
    driver_entity_ids: List[str] = field(default_factory=list)

    timestamp: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("fop-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Plans ─────────────────────────────────────────────────────────────

@dataclass
class MemePlan:
    """Plan triggered by new token launch + flow patterns."""
    id: str = ""
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value
    contract_address: str = ""

    # Entry
    entry_size_usd: float = 50.0
    max_slippage_bps: int = 300  # 3%
    max_price_impact: float = 0.05
    min_liquidity_usd: float = 10000.0

    # Exit rules
    take_profit_pct: float = 50.0  # +50% TP
    stop_loss_pct: float = 30.0  # -30% SL
    max_holding_hours: float = 24.0
    trailing_stop_pct: float = 0.0  # 0 = disabled

    # MEV
    mev_risk_tolerance: str = MevRiskTolerance.LOW.value
    max_gas_usd: float = 5.0

    # State
    status: str = PlanStatus.PROPOSED.value
    triggered_by: List[str] = field(default_factory=list)  # flow event IDs
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    confidence: float = 0.5

    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("mp-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WhalePlan:
    """Plan triggered by whale/smart wallet entering or exiting a position."""
    id: str = ""
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value
    contract_address: str = ""

    # Whale context
    entity_id: str = ""
    entity_label: str = ""
    entity_quality: str = "unknown"
    whale_action: str = "buy"  # buy/sell/accumulate/distribute
    whale_size_usd: float = 0.0

    # Strategy
    strategy: str = "follow"  # follow/front_run/fade
    entry_size_usd: float = 100.0
    max_slippage_bps: int = 200
    max_price_impact: float = 0.03

    # Exit rules
    take_profit_pct: float = 30.0
    stop_loss_pct: float = 15.0
    max_holding_hours: float = 48.0

    # MEV
    mev_risk_tolerance: str = MevRiskTolerance.MEDIUM.value
    max_gas_usd: float = 10.0

    # State
    status: str = PlanStatus.PROPOSED.value
    triggered_by: List[str] = field(default_factory=list)
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    confidence: float = 0.5

    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("wp-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KOLPlan:
    """Plan triggered by KOL mention + on-chain KOL buy."""
    id: str = ""
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value
    contract_address: str = ""

    # KOL context
    entity_id: str = ""
    kol_handle: str = ""
    kol_follower_count: int = 0
    mention_text: str = ""
    mention_sentiment: float = 0.0
    has_onchain_buy: bool = False

    # Entry — smaller, more speculative
    entry_size_usd: float = 25.0
    max_slippage_bps: int = 500  # 5% — higher tolerance for memes
    max_price_impact: float = 0.08

    # Exit — very tight risk
    take_profit_pct: float = 100.0  # 2x or bust
    stop_loss_pct: float = 40.0
    max_holding_hours: float = 12.0

    # MEV
    mev_risk_tolerance: str = MevRiskTolerance.HIGH.value
    max_gas_usd: float = 3.0

    # State
    status: str = PlanStatus.PROPOSED.value
    triggered_by: List[str] = field(default_factory=list)
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    confidence: float = 0.5

    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("kp-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Sniper execution records ─────────────────────────────────────────

@dataclass
class SniperOrder:
    """Pre-trade sniper order with MEV constraints."""
    id: str = ""
    plan_id: str = ""  # MemePlan / WhalePlan / KOLPlan ID
    plan_type: str = "meme"  # meme/whale/kol
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value
    contract_address: str = ""

    # Order
    direction: str = "buy"
    size_usd: float = 0.0
    size_tokens: float = 0.0

    # Constraints
    max_slippage_bps: int = 300
    max_gas_usd: float = 5.0
    min_liquidity_usd: float = 10000.0
    max_price_impact: float = 0.05
    mev_risk_tolerance: str = MevRiskTolerance.LOW.value

    # Routing
    route_type: str = RouteType.STANDARD.value
    dex_router: str = ""  # e.g., "jupiter", "1inch", "uniswap_v3"
    mev_relay: str = ""  # e.g., "jito", "flashbots", ""

    # Pre-trade simulation
    sim_price_impact: float = 0.0
    sim_output_tokens: float = 0.0
    sim_passed: bool = False
    sim_reason: str = ""

    # State
    status: str = PlanStatus.PROPOSED.value
    created_at: float = field(default_factory=_now)

    def __post_init__(self):
        if not self.id:
            self.id = _uid("snp-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SniperFill:
    """Post-trade fill record for a sniper order."""
    id: str = ""
    order_id: str = ""
    plan_id: str = ""
    token_id: str = ""
    token_symbol: str = ""
    chain: str = Chain.SOLANA.value

    # Fill details
    direction: str = "buy"
    filled_size_usd: float = 0.0
    filled_tokens: float = 0.0
    fill_price_usd: float = 0.0
    expected_price_usd: float = 0.0

    # Execution quality
    actual_slippage_bps: int = 0
    actual_price_impact: float = 0.0
    gas_used_usd: float = 0.0
    latency_ms: float = 0.0
    route_type_used: str = RouteType.STANDARD.value

    # MEV
    mev_detected: bool = False
    mev_loss_usd: float = 0.0
    mev_details: str = ""

    # Transaction
    tx_hash: str = ""
    block_number: int = 0
    timestamp: float = field(default_factory=_now)

    # Result
    success: bool = True
    error: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = _uid("fill-")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def slippage_vs_plan(self) -> float:
        """How much worse the actual slippage was vs expected (bps)."""
        if self.expected_price_usd <= 0:
            return 0.0
        actual_slip = abs(self.fill_price_usd - self.expected_price_usd) / self.expected_price_usd
        return actual_slip * 10000  # convert to bps
