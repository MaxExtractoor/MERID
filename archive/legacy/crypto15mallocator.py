"""Crypto15MAllocator — Cross-asset risk allocator for Kalshi 15m crypto markets.

PRODUCTION IMPLEMENTATION SPEC: 15m CRYPTO TIMEFRAME & PER-EXPIRY RISK BUDGET

This module implements:
1. Timeframe-wide contract budget (max_contracts_per_tf_crypto_15m)
2. Per-expiry open exposure cap (max_open_contracts_per_expiry_crypto_15m)
3. Market selection by EV ranking (max_markets_per_tf_crypto_15m)
4. Hard safety checks in risk/venue layers

Architecture:
- Agents publish TradeIntent to the allocator (mode="intent_only")
- Allocator scores, ranks, and selects best candidates
- Selected intents forwarded to consensus → orderrouter (mode="live")
- Blocked intents logged with explicit hold reasons

Log Tags:
- CRYPTO15MALLOCATOR — Allocator decisions and lifecycle
- TFBUDGET — Timeframe budget checks and rejections
- EXPIRYLIMIT — Per-expiry open exposure checks

"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto15mallocator")


# =============================================================================
# CONSTANTS
# =============================================================================

CRYPTO_15M_ASSETS: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
CRYPTO_15M_PATTERN = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M-", re.IGNORECASE)

# Time bucket width for 15m timeframe alignment (seconds)
TF_15M_BUCKET_WIDTH_S: int = 900  # 15 minutes

# Decision bucket width for deterministic IDs
DECISION_BUCKET_WIDTH_S: int = 60


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Crypto15MAllocatorConfig:
    """Configuration for 15m crypto cross-asset allocation.
    
    For 15m scalper mode: Set MAX_CONTRACTS_PER_TF_CRYPTO_15M env var.
    """
    
    # Timeframe-wide budget controls - UNIFIED 3%/8% RISK REGIME
    # With $47 bankroll, 3% = $1.41 → max 2-3 contracts at $0.50 each
    max_contracts_per_tf_crypto_15m: int = int(os.getenv("MAX_CONTRACTS_PER_TF_CRYPTO_15M", "2"))  # 2 for unified risk
    max_markets_per_tf_crypto_15m: int = int(os.getenv("MAX_MARKETS_PER_TF_CRYPTO_15M", "2"))  # 2 markets max
    
    # Per-expiry open exposure cap - UNIFIED 3%/8% RISK REGIME
    max_open_contracts_per_expiry_crypto_15m: int = int(os.getenv("MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M", "2"))  # 2 for unified risk
    
    # Bankroll scaling function (linear or constant)
    contract_budget_scale_crypto_15m: str = "constant"  # "constant" | "linear"
    contract_budget_scale_factor: float = float(os.getenv("SCALER15M_SCALE_FACTOR", "1.0"))  # multiplier for linear scaling
    
    # Rollout phase control
    rollout_phase: str = os.getenv("CRYPTO15M_ROLLOUT_PHASE", "soft_gate")  # "dry_run" | "soft_gate" | "hard_gate"
    
    # Minimum equity threshold for scaling
    min_bankroll_for_scaling_usd: float = 100.0
    max_bankroll_for_scaling_usd: float = 10000.0
    
    def compute_effective_budget(self, bankroll_equity_usd: float) -> int:
        """Compute effective contract budget based on bankroll.
        
        Args:
            bankroll_equity_usd: Current bankroll equity in USD
            
        Returns:
            Effective max contracts for this timeframe
        """
        if self.contract_budget_scale_crypto_15m == "constant":
            return self.max_contracts_per_tf_crypto_15m
        
        if self.contract_budget_scale_crypto_15m == "linear":
            # Linear scaling: base + (bankroll * factor), capped at 3x base
            base = float(self.max_contracts_per_tf_crypto_15m)
            scaled = base + (bankroll_equity_usd * self.contract_budget_scale_factor / 100.0)
            max_scaled = base * 3.0  # Cap at 3x base
            effective = min(scaled, max_scaled)
            return max(1, int(effective))
        
        return self.max_contracts_per_tf_crypto_15m


def get_allocator_config() -> Crypto15MAllocatorConfig:
    """Load allocator configuration from environment."""
    config = Crypto15MAllocatorConfig()
    
    # Override from env vars if set
    if os.getenv("MAX_CONTRACTS_PER_TF_CRYPTO_15M"):
        config.max_contracts_per_tf_crypto_15m = int(os.getenv("MAX_CONTRACTS_PER_TF_CRYPTO_15M", "1"))
    if os.getenv("MAX_MARKETS_PER_TF_CRYPTO_15M"):
        config.max_markets_per_tf_crypto_15m = int(os.getenv("MAX_MARKETS_PER_TF_CRYPTO_15M", "2"))
    if os.getenv("MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M"):
        config.max_open_contracts_per_expiry_crypto_15m = int(os.getenv("MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M", "1"))
    if os.getenv("CONTRACT_BUDGET_SCALE_CRYPTO_15M"):
        config.contract_budget_scale_crypto_15m = os.getenv("CONTRACT_BUDGET_SCALE_CRYPTO_15M", "constant")
    if os.getenv("CRYPTO15M_ALLOCATOR_PHASE"):
        config.rollout_phase = os.getenv("CRYPTO15M_ALLOCATOR_PHASE", "dry_run")
    
    return config


# =============================================================================
# DATA MODELS
# =============================================================================

class HoldReason(str, Enum):
    """Hold reasons for blocked intents."""
    TIMEFRAME_BUDGET_EXHAUSTED = "timeframe_budget_exhausted"
    EXPIRY_OPEN_EXPOSURE_EXHAUSTED = "expiry_open_exposure_exhausted"
    MARKETS_LIMIT_REACHED = "markets_limit_reached"
    LOWER_SCORE_THAN_WINNER = "lower_score_than_winner"
    EXPIRY_WINDOW_CLOSED = "expiry_window_closed"
    DIRECTIONAL_MM_CONFLICT = "directional_mm_conflict"


@dataclass
class TradeIntent:
    """A candidate trade intent from an agent."""
    
    # Identification
    intent_id: str
    agent_id: str
    ticker: str
    
    # Market metadata
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    timeframe: str  # "15m" (only 15m supported)
    expiry_id: str  # e.g., "CRYPTO_15M:26APR191400"
    
    # Trade details
    side: str  # "YES" or "NO"
    intended_contracts: int
    limit_price_cents: int
    
    # Scoring inputs
    netedge: float = 0.0  # Model edge (net of fees)
    confidence: float = 0.0  # Model confidence (0-100)
    is_market_maker: bool = False  # True if from CRYPTO15MMM
    consensus_confidence: Optional[float] = None  # For MM scoring
    implied_edge_from_spread: Optional[float] = None  # For MM scoring
    
    # Mode tracking
    mode: str = "intent_only"  # "intent_only" | "live"
    
    # Decision metadata
    score: float = 0.0
    hold_reason: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Normalize asset to uppercase."""
        self.asset = self.asset.upper()
        self.side = self.side.upper()


def compute_score(intent: TradeIntent) -> float:
    """Compute allocation score for an intent.
    
    Directional: score = netedge * confidence
    Market Maker: score = consensus_confidence or implied_edge_from_spread * confidence
    
    Args:
        intent: TradeIntent to score
        
    Returns:
        Numeric score (higher = better)
    """
    if intent.is_market_maker:
        # MM scoring: use implied edge if available, else consensus confidence
        if intent.implied_edge_from_spread is not None and intent.confidence > 0:
            return intent.implied_edge_from_spread * intent.confidence
        elif intent.consensus_confidence is not None:
            return intent.consensus_confidence
        else:
            return intent.confidence * 0.5  # Conservative fallback
    else:
        # Directional scoring
        return intent.netedge * intent.confidence


# =============================================================================
# EXPIRY ID RESOLUTION
# =============================================================================

def resolve_expiry_id_from_ticker(ticker: str) -> Optional[str]:
    """Extract expiry_id from a 15m crypto ticker.
    
    Args:
        ticker: Kalshi ticker like "KXBTC15M-26APR191400-00"
        
    Returns:
        Expiry ID like "CRYPTO_15M:26APR191400" or None if not 15m crypto
    """
    if not is_15m_crypto_ticker(ticker):
        return None
    
    # Extract date/time component from ticker
    # Pattern: KXBTC15M-26APR191400-00 → 26APR191400
    match = re.search(r"-([0-9]{2}[A-Z]{3}[0-9]{6})-", ticker)
    if match:
        expiry_dt = match.group(1)
        return f"CRYPTO_15M:{expiry_dt}"
    
    return None


def is_15m_crypto_ticker(ticker: str) -> bool:
    """Check if ticker is a 15m crypto market.
    
    Args:
        ticker: Market ticker
        
    Returns:
        True if 15m crypto ticker (KXBTC15M-, KXETH15M-, etc.)
    """
    if not ticker:
        return False
    return CRYPTO_15M_PATTERN.match(ticker) is not None


def extract_asset_from_ticker(ticker: str) -> Optional[str]:
    """Extract asset symbol from 15m crypto ticker.
    
    Args:
        ticker: Kalshi ticker like "KXBTC15M-26APR191400-00"
        
    Returns:
        Asset symbol like "BTC" or None
    """
    if not is_15m_crypto_ticker(ticker):
        return None
    
    match = re.search(r"^KX([A-Z]+)15M-", ticker, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


# =============================================================================
# TF BUCKET COMPUTATION
# =============================================================================

def compute_15m_tf_bucket(timestamp: Optional[float] = None) -> Tuple[int, str]:
    """Compute the current 15m timeframe bucket.
    
    Args:
        timestamp: Optional epoch seconds (default: now)
        
    Returns:
        Tuple of (bucket_start_epoch, bucket_iso_string)
    """
    ts = timestamp if timestamp is not None else time.time()
    bucket_start = int(ts // TF_15M_BUCKET_WIDTH_S) * TF_15M_BUCKET_WIDTH_S
    
    dt = datetime.fromtimestamp(bucket_start, tz=timezone.utc)
    iso_str = dt.strftime("%Y%m%d_%H%M")
    
    return bucket_start, iso_str


# =============================================================================
# POSITION TRACKING (PER-EXPIRY)
# =============================================================================

@dataclass
class ExpiryExposureState:
    """Tracks open exposure for a specific expiry."""
    expiry_id: str
    open_contracts_long: int = 0  # YES contracts
    open_contracts_short: int = 0  # NO contracts
    pending_open_contracts: int = 0  # Intents approved but not yet filled
    last_updated: float = field(default_factory=time.time)
    
    @property
    def net_open_contracts(self) -> int:
        """Total open contracts (both directions count toward cap)."""
        return self.open_contracts_long + self.open_contracts_short
    
    @property
    def total_exposure_including_pending(self) -> int:
        """Total including pending orders."""
        return self.net_open_contracts + self.pending_open_contracts
    
    def can_accommodate_new_contracts(self, requested: int, max_cap: int) -> bool:
        """Check if new contracts would exceed cap.
        
        Args:
            requested: Number of new contracts requested
            max_cap: Maximum allowed open contracts
            
        Returns:
            True if within cap, False if would exceed
        """
        return (self.total_exposure_including_pending + requested) <= max_cap
    
    def remaining_capacity(self, max_cap: int) -> int:
        """Compute remaining contract capacity.
        
        Args:
            max_cap: Maximum allowed open contracts
            
        Returns:
            Remaining capacity (may be zero or negative)
        """
        return max_cap - self.total_exposure_including_pending


@dataclass
class TimeframeBudgetState:
    """Tracks contract budget for a 15m timeframe."""
    tf_bucket_start: int
    tf_bucket_iso: str
    contracts_used: int = 0
    contracts_pending: int = 0
    markets_admitted: Set[str] = field(default_factory=set)
    intents_approved: List[str] = field(default_factory=list)
    intents_blocked: List[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)
    
    @property
    def markets_count(self) -> int:
        """Number of distinct markets admitted."""
        return len(self.markets_admitted)
    
    def can_accommodate_contracts(self, requested: int, max_contracts: int) -> bool:
        """Check if new contracts would exceed budget."""
        total = self.contracts_used + self.contracts_pending + requested
        return total <= max_contracts
    
    def can_accommodate_market(self, ticker: str, max_markets: int) -> bool:
        """Check if new market would exceed markets limit."""
        if ticker in self.markets_admitted:
            return True  # Already admitted
        return self.markets_count < max_markets
    
    def remaining_contract_capacity(self, max_contracts: int) -> int:
        """Compute remaining contract budget."""
        return max_contracts - (self.contracts_used + self.contracts_pending)


# =============================================================================
# MAIN ALLOCATOR
# =============================================================================

class Crypto15MAllocator:
    """Cross-asset risk allocator for Kalshi 15m crypto markets.
    
    Responsibilities:
    1. Collect TradeIntents from 15m agents
    2. Score and rank intents by EV
    3. Select best subset respecting budgets and caps
    4. Forward approved intents to consensus/orderrouter
    5. Log blocked intents with explicit hold reasons
    
    Thread-safe. Uses fine-grained locking per expiry/bucket.
    """
    
    def __init__(self, config: Optional[Crypto15MAllocatorConfig] = None):
        self._config = config or get_allocator_config()
        
        # State tracking
        self._expiry_states: Dict[str, ExpiryExposureState] = {}
        self._tf_states: Dict[int, TimeframeBudgetState] = {}
        
        # Intent storage for current cycle
        self._current_intents: Dict[str, TradeIntent] = {}
        
        # Locking
        self._state_lock = threading.RLock()
        
        # Position cache reference (lazy loaded)
        self._position_cache: Optional[Any] = None
        
        logger.info(
            "[CRYPTO15MALLOCATOR] Initialized phase=%s max_contracts=%d max_markets=%d max_expiry=%d",
            self._config.rollout_phase,
            self._config.max_contracts_per_tf_crypto_15m,
            self._config.max_markets_per_tf_crypto_15m,
            self._config.max_open_contracts_per_expiry_crypto_15m,
        )
    
    @property
    def config(self) -> Crypto15MAllocatorConfig:
        return self._config
    
    def _get_position_cache(self) -> Optional[Any]:
        """Lazy load position cache."""
        if self._position_cache is None:
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                self._position_cache = get_position_cache()
            except Exception as e:
                logger.debug(f"Position cache unavailable: {e}")
        return self._position_cache
    
    def _get_or_create_expiry_state(self, expiry_id: str) -> ExpiryExposureState:
        """Get or create exposure state for an expiry."""
        with self._state_lock:
            if expiry_id not in self._expiry_states:
                self._expiry_states[expiry_id] = ExpiryExposureState(expiry_id=expiry_id)
            return self._expiry_states[expiry_id]
    
    def _get_or_create_tf_state(self, bucket_start: int, bucket_iso: str) -> TimeframeBudgetState:
        """Get or create budget state for a timeframe bucket."""
        with self._state_lock:
            if bucket_start not in self._tf_states:
                self._tf_states[bucket_start] = TimeframeBudgetState(
                    tf_bucket_start=bucket_start,
                    tf_bucket_iso=bucket_iso
                )
            return self._tf_states[bucket_start]
    
    def _prune_old_tf_states(self, current_bucket: int) -> None:
        """Remove timeframe states older than current bucket."""
        with self._state_lock:
            old_buckets = [b for b in self._tf_states.keys() if b < current_bucket]
            for b in old_buckets:
                state = self._tf_states.pop(b)
                logger.debug(
                    "[CRYPTO15MALLOCATOR] Pruned old TF state bucket=%s used=%d markets=%d",
                    state.tf_bucket_iso, state.contracts_used, state.markets_count
                )
    
    def _compute_scores(self, intents: List[TradeIntent]) -> List[TradeIntent]:
        """Compute scores for all intents."""
        for intent in intents:
            intent.score = compute_score(intent)
        return intents
    
    def _resolve_directional_mm_conflict(
        self, 
        intents: List[TradeIntent]
    ) -> List[TradeIntent]:
        """Resolve conflicts where both directional and MM intents exist for same ticker.
        
        Rule: Only allow the higher-scoring intent for each ticker.
        
        Args:
            intents: All intents for this cycle
            
        Returns:
            All intents with hold_reason set on losers (for downstream blocking)
        """
        by_ticker: Dict[str, List[TradeIntent]] = {}
        for intent in intents:
            if intent.ticker not in by_ticker:
                by_ticker[intent.ticker] = []
            by_ticker[intent.ticker].append(intent)
        
        result = []
        for ticker, ticker_intents in by_ticker.items():
            if len(ticker_intents) == 1:
                # No conflict, keep as-is
                result.append(ticker_intents[0])
                continue
            
            # Sort by score descending
            ticker_intents.sort(key=lambda x: x.score, reverse=True)
            
            # Winner is highest score
            winner = ticker_intents[0]
            winner.hold_reason = None
            result.append(winner)
            
            # Losers are blocked but still returned for tracking
            for loser in ticker_intents[1:]:
                loser.hold_reason = HoldReason.DIRECTIONAL_MM_CONFLICT.value
                result.append(loser)  # Include loser in result so it gets blocked downstream
                logger.info(
                    "[CRYPTO15MALLOCATOR] BLOCK ticker=%s asset=%s reason=%s score=%.4f agent=%s "
                    "(lost to winner with score=%.4f)",
                    loser.ticker, loser.asset, loser.hold_reason, loser.score, loser.agent_id,
                    winner.score
                )
        
        return result
    
    def submit_intent(self, intent: TradeIntent) -> None:
        """Submit an intent for consideration in the next allocation cycle.
        
        Args:
            intent: TradeIntent from an agent
        """
        # Validate intent
        if not is_15m_crypto_ticker(intent.ticker):
            logger.debug(
                "[CRYPTO15MALLOCATOR] Rejecting non-15m-crypto intent: %s", intent.ticker
            )
            return
        
        # Compute expiry_id if not set
        if not intent.expiry_id:
            intent.expiry_id = resolve_expiry_id_from_ticker(intent.ticker)
        
        # Compute score
        intent.score = compute_score(intent)
        
        with self._state_lock:
            self._current_intents[intent.intent_id] = intent
        
        logger.debug(
            "[CRYPTO15MALLOCATOR] Intent submitted intent_id=%s ticker=%s asset=%s "
            "side=%s contracts=%d score=%.4f agent=%s",
            intent.intent_id, intent.ticker, intent.asset, intent.side,
            intent.intended_contracts, intent.score, intent.agent_id
        )
    
    def run_allocation_cycle(
        self,
        bankroll_equity_usd: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Tuple[List[TradeIntent], List[TradeIntent]]:
        """Run allocation cycle: score, rank, select, and return approved/blocked.
        
        Args:
            bankroll_equity_usd: Current bankroll for budget scaling
            timestamp: Optional timestamp for bucket alignment
            
        Returns:
            Tuple of (approved_intents, blocked_intents)
        """
        # Get current timeframe bucket
        bucket_start, bucket_iso = compute_15m_tf_bucket(timestamp)
        
        # Prune old states
        self._prune_old_tf_states(bucket_start)
        
        # Get or create TF state
        tf_state = self._get_or_create_tf_state(bucket_start, bucket_iso)
        
        # Compute effective budget
        effective_budget = self._config.compute_effective_budget(bankroll_equity_usd)
        
        # Collect intents for this cycle
        with self._state_lock:
            intents = list(self._current_intents.values())
            self._current_intents.clear()
        
        if not intents:
            logger.debug("[CRYPTO15MALLOCATOR] No intents for cycle bucket=%s", bucket_iso)
            return [], []
        
        logger.info(
            "[CRYPTO15MALLOCATOR] CYCLE_START bucket=%s candidates=%d budget=%d markets_limit=%d",
            bucket_iso, len(intents), effective_budget, self._config.max_markets_per_tf_crypto_15m
        )
        
        # Compute scores
        intents = self._compute_scores(intents)
        
        # Resolve directional/MM conflicts
        intents = self._resolve_directional_mm_conflict(intents)
        
        # Sort by score descending
        intents.sort(key=lambda x: x.score, reverse=True)
        
        # Selection pass
        approved: List[TradeIntent] = []
        blocked: List[TradeIntent] = []
        
        # Track approved contracts per expiry within this cycle (for cap calculation)
        approved_this_cycle_by_expiry: Dict[str, int] = {}
        
        for intent in intents:
            # Skip if already blocked (e.g., directional/MM conflict)
            if intent.hold_reason:
                blocked.append(intent)
                continue
            
            # Get expiry state
            expiry_state = self._get_or_create_expiry_state(intent.expiry_id)
            
            # Check 1: Timeframe budget
            if not tf_state.can_accommodate_contracts(intent.intended_contracts, effective_budget):
                remaining = tf_state.remaining_contract_capacity(effective_budget)
                intent.hold_reason = HoldReason.TIMEFRAME_BUDGET_EXHAUSTED.value
                blocked.append(intent)
                logger.info(
                    "[CRYPTO15MALLOCATOR] BLOCK ticker=%s asset=%s reason=%s "
                    "requested=%d remaining=%d score=%.4f agent=%s",
                    intent.ticker, intent.asset, intent.hold_reason,
                    intent.intended_contracts, remaining, intent.score, intent.agent_id
                )
                continue
            
            # Check 2: Markets limit
            if not tf_state.can_accommodate_market(intent.ticker, self._config.max_markets_per_tf_crypto_15m):
                intent.hold_reason = HoldReason.MARKETS_LIMIT_REACHED.value
                blocked.append(intent)
                logger.info(
                    "[CRYPTO15MALLOCATOR] BLOCK ticker=%s asset=%s reason=%s "
                    "markets_used=%d markets_limit=%d score=%.4f agent=%s",
                    intent.ticker, intent.asset, intent.hold_reason,
                    tf_state.markets_count, self._config.max_markets_per_tf_crypto_15m,
                    intent.score, intent.agent_id
                )
                continue
            
            # Check 3: Per-expiry open exposure cap
            # Calculate total including already-approved in this cycle
            already_approved_this_cycle = approved_this_cycle_by_expiry.get(intent.expiry_id, 0)
            total_with_this_intent = (
                expiry_state.net_open_contracts + 
                expiry_state.pending_open_contracts +
                already_approved_this_cycle +
                intent.intended_contracts
            )
            
            if total_with_this_intent > self._config.max_open_contracts_per_expiry_crypto_15m:
                remaining = max(0, 
                    self._config.max_open_contracts_per_expiry_crypto_15m - 
                    expiry_state.net_open_contracts - 
                    expiry_state.pending_open_contracts -
                    already_approved_this_cycle
                )
                intent.hold_reason = HoldReason.EXPIRY_OPEN_EXPOSURE_EXHAUSTED.value
                blocked.append(intent)
                logger.info(
                    "[CRYPTO15MALLOCATOR] BLOCK ticker=%s asset=%s expiry=%s reason=%s "
                    "requested=%d remaining=%d score=%.4f agent=%s",
                    intent.ticker, intent.asset, intent.expiry_id, intent.hold_reason,
                    intent.intended_contracts, remaining, intent.score, intent.agent_id
                )
                continue
            
            # APPROVE
            intent.mode = "live"
            approved.append(intent)
            
            # Update state
            tf_state.contracts_pending += intent.intended_contracts
            tf_state.markets_admitted.add(intent.ticker)
            tf_state.intents_approved.append(intent.intent_id)
            
            expiry_state.pending_open_contracts += intent.intended_contracts
            approved_this_cycle_by_expiry[intent.expiry_id] = already_approved_this_cycle + intent.intended_contracts
            
            logger.info(
                "[CRYPTO15MALLOCATOR] APPROVE ticker=%s asset=%s expiry=%s side=%s "
                "contracts=%d score=%.4f agent=%s bucket=%s",
                intent.ticker, intent.asset, intent.expiry_id, intent.side,
                intent.intended_contracts, intent.score, intent.agent_id, bucket_iso
            )
        
        # Update TF state tracking
        tf_state.intents_blocked.extend([i.intent_id for i in blocked])
        
        # Log summary
        logger.info(
            "[CRYPTO15MALLOCATOR] CYCLE_END bucket=%s approved=%d blocked=%d "
            "contracts_pending=%d markets_admitted=%d",
            bucket_iso, len(approved), len(blocked),
            tf_state.contracts_pending, tf_state.markets_count
        )
        
        # Log blocked summary
        if blocked:
            by_reason: Dict[str, int] = {}
            for b in blocked:
                by_reason[b.hold_reason or "unknown"] = by_reason.get(b.hold_reason, 0) + 1
            for reason, count in by_reason.items():
                logger.info(
                    "[CRYPTO15MALLOCATOR] BLOCKED_SUMMARY bucket=%s reason=%s count=%d",
                    bucket_iso, reason, count
                )
        
        return approved, blocked
    
    def record_fill(
        self,
        ticker: str,
        contracts: int,
        side: str,
        expiry_id: Optional[str] = None
    ) -> None:
        """Record a fill to update exposure state.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts filled
            side: "YES" or "NO"
            expiry_id: Optional expiry_id (will resolve from ticker if not provided)
        """
        if not is_15m_crypto_ticker(ticker):
            return
        
        if not expiry_id:
            expiry_id = resolve_expiry_id_from_ticker(ticker)
        
        if not expiry_id:
            return
        
        expiry_state = self._get_or_create_expiry_state(expiry_id)
        
        with self._state_lock:
            # Move from pending to open
            if contracts <= expiry_state.pending_open_contracts:
                expiry_state.pending_open_contracts -= contracts
            else:
                expiry_state.pending_open_contracts = 0
            
            # Add to open contracts
            if side.upper() == "YES":
                expiry_state.open_contracts_long += contracts
            else:
                expiry_state.open_contracts_short += contracts
            
            expiry_state.last_updated = time.time()
        
        logger.debug(
            "[CRYPTO15MALLOCATOR] FILL_RECORDED ticker=%s expiry=%s side=%s "
            "contracts=%d open_long=%d open_short=%d pending=%d",
            ticker, expiry_id, side, contracts,
            expiry_state.open_contracts_long,
            expiry_state.open_contracts_short,
            expiry_state.pending_open_contracts
        )
    
    def record_position_close(
        self,
        ticker: str,
        contracts: int,
        side: str,
        expiry_id: Optional[str] = None
    ) -> None:
        """Record position closure to update exposure state.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts closed
            side: "YES" or "NO" (the side being closed)
            expiry_id: Optional expiry_id
        """
        if not is_15m_crypto_ticker(ticker):
            return
        
        if not expiry_id:
            expiry_id = resolve_expiry_id_from_ticker(ticker)
        
        if not expiry_id:
            return
        
        expiry_state = self._get_or_create_expiry_state(expiry_id)
        
        with self._state_lock:
            if side.upper() == "YES":
                expiry_state.open_contracts_long = max(0, expiry_state.open_contracts_long - contracts)
            else:
                expiry_state.open_contracts_short = max(0, expiry_state.open_contracts_short - contracts)
            
            expiry_state.last_updated = time.time()
        
        logger.debug(
            "[CRYPTO15MALLOCATOR] CLOSE_RECORDED ticker=%s expiry=%s side=%s "
            "contracts=%d open_long=%d open_short=%d",
            ticker, expiry_id, side, contracts,
            expiry_state.open_contracts_long,
            expiry_state.open_contracts_short
        )
    
    def sync_from_position_cache(self) -> None:
        """Sync expiry exposure state from position cache."""
        cache = self._get_position_cache()
        if cache is None:
            return
        
        positions = cache.get_all_positions()
        
        with self._state_lock:
            # Reset all expiry states
            for state in self._expiry_states.values():
                state.open_contracts_long = 0
                state.open_contracts_short = 0
                state.pending_open_contracts = 0
            
            # Rebuild from positions
            for ticker, position in positions.items():
                if not is_15m_crypto_ticker(ticker):
                    continue
                
                expiry_id = resolve_expiry_id_from_ticker(ticker)
                if not expiry_id:
                    continue
                
                expiry_state = self._get_or_create_expiry_state(expiry_id)
                
                if position.side.upper() == "YES":
                    expiry_state.open_contracts_long += position.contracts
                else:
                    expiry_state.open_contracts_short += position.contracts
        
        logger.info(
            "[CRYPTO15MALLOCATOR] SYNC_FROM_CACHE positions=%d expiry_states=%d",
            len(positions), len(self._expiry_states)
        )
    
    def get_expiry_exposure(self, expiry_id: str) -> Optional[ExpiryExposureState]:
        """Get current exposure state for an expiry."""
        with self._state_lock:
            return self._expiry_states.get(expiry_id)
    
    def get_tf_budget_state(self, bucket_start: int) -> Optional[TimeframeBudgetState]:
        """Get current budget state for a timeframe bucket."""
        with self._state_lock:
            return self._tf_states.get(bucket_start)
    
    def get_all_expiry_exposures(self) -> Dict[str, Dict[str, Any]]:
        """Get all expiry exposure states as serializable dicts."""
        with self._state_lock:
            return {
                expiry_id: {
                    "expiry_id": state.expiry_id,
                    "open_contracts_long": state.open_contracts_long,
                    "open_contracts_short": state.open_contracts_short,
                    "net_open_contracts": state.net_open_contracts,
                    "pending_open_contracts": state.pending_open_contracts,
                    "total_exposure": state.total_exposure_including_pending,
                    "last_updated": state.last_updated,
                }
                for expiry_id, state in self._expiry_states.items()
            }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get allocator metrics."""
        with self._state_lock:
            return {
                "expiry_state_count": len(self._expiry_states),
                "tf_state_count": len(self._tf_states),
                "pending_intents": len(self._current_intents),
                "config": {
                    "max_contracts_per_tf": self._config.max_contracts_per_tf_crypto_15m,
                    "max_markets_per_tf": self._config.max_markets_per_tf_crypto_15m,
                    "max_open_per_expiry": self._config.max_open_contracts_per_expiry_crypto_15m,
                    "rollout_phase": self._config.rollout_phase,
                }
            }
    
    def reset(self) -> None:
        """Reset all state (testing/emergency use only)."""
        with self._state_lock:
            self._expiry_states.clear()
            self._tf_states.clear()
            self._current_intents.clear()
        
        logger.warning("[CRYPTO15MALLOCATOR] STATE_RESET complete")


# =============================================================================
# GLOBAL SINGLETON
# =============================================================================

_allocator_instance: Optional[Crypto15MAllocator] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_crypto15m_allocator() -> Crypto15MAllocator:
    """Get the global Crypto15MAllocator singleton."""
    global _allocator_instance
    if _allocator_instance is not None:
        return _allocator_instance
    
    _allocator_instance = Crypto15MAllocator()
    return _allocator_instance


def reset_crypto15m_allocator_for_testing() -> None:
    """Reset the global singleton (testing only)."""
    global _allocator_instance
    _allocator_instance = None


# =============================================================================
# RISK GATE INTEGRATION HELPERS
# =============================================================================

def check_timeframe_budget(
    ticker: str,
    requested_contracts: int,
    bankroll_equity_usd: float,
    timestamp: Optional[float] = None
) -> Tuple[bool, int, str]:
    """Check if order would exceed timeframe budget.
    
    Args:
        ticker: Market ticker
        requested_contracts: Number of contracts requested
        bankroll_equity_usd: Current bankroll for budget computation
        timestamp: Optional timestamp
        
    Returns:
        Tuple of (allowed, approved_contracts, reason)
        - allowed: True if within budget or reduction
        - approved_contracts: Contracts allowed (may be sliced)
        - reason: Description of decision
    """
    if not is_15m_crypto_ticker(ticker):
        return True, requested_contracts, "not_15m_crypto"
    
    allocator = get_crypto15m_allocator()
    config = allocator.config
    
    # Get current timeframe bucket
    bucket_start, bucket_iso = compute_15m_tf_bucket(timestamp)
    tf_state = allocator.get_tf_budget_state(bucket_start)
    
    if tf_state is None:
        # No state yet = no budget used
        return True, requested_contracts, "tf_state_empty"
    
    effective_budget = config.compute_effective_budget(bankroll_equity_usd)
    remaining = tf_state.remaining_contract_capacity(effective_budget)
    
    if remaining <= 0:
        return False, 0, f"timeframe_budget_exhausted bucket={bucket_iso} remaining=0"
    
    if requested_contracts > remaining:
        # Slice down to remaining capacity
        return True, remaining, f"timeframe_budget_capped requested={requested_contracts} approved={remaining}"
    
    return True, requested_contracts, "timeframe_budget_ok"


def check_expiry_open_cap(
    ticker: str,
    requested_contracts: int,
    is_increasing_exposure: bool,
    timestamp: Optional[float] = None
) -> Tuple[bool, int, str]:
    """Check if order would exceed per-expiry open exposure cap.
    
    Args:
        ticker: Market ticker
        requested_contracts: Number of contracts requested
        is_increasing_exposure: True if this increases net exposure
        timestamp: Optional timestamp
        
    Returns:
        Tuple of (allowed, approved_contracts, reason)
    """
    if not is_15m_crypto_ticker(ticker):
        return True, requested_contracts, "not_15m_crypto"
    
    # Reductions are always allowed
    if not is_increasing_exposure:
        return True, requested_contracts, "expiry_reduction_always_allowed"
    
    expiry_id = resolve_expiry_id_from_ticker(ticker)
    if not expiry_id:
        return True, requested_contracts, "expiry_id_unresolved"
    
    allocator = get_crypto15m_allocator()
    config = allocator.config
    
    expiry_state = allocator.get_expiry_exposure(expiry_id)
    if expiry_state is None:
        # No state yet = no exposure
        return True, requested_contracts, "expiry_state_empty"
    
    remaining = expiry_state.remaining_capacity(config.max_open_contracts_per_expiry_crypto_15m)
    
    if remaining <= 0:
        return False, 0, f"expiry_limit_exhausted expiry={expiry_id} net_open={expiry_state.net_open_contracts}"
    
    if requested_contracts > remaining:
        # Slice down to remaining capacity
        return True, remaining, f"expiry_limit_capped requested={requested_contracts} approved={remaining}"
    
    return True, requested_contracts, "expiry_limit_ok"


def is_increasing_exposure_check(
    ticker: str,
    side: str,
    requested_contracts: int,
    existing_position_contracts: int,
    existing_position_side: Optional[str] = None
) -> bool:
    """Determine if order increases net exposure.
    
    Args:
        ticker: Market ticker
        side: Order side ("YES" or "NO")
        requested_contracts: Contracts to trade
        existing_position_contracts: Current position size
        existing_position_side: Current position side (if any)
        
    Returns:
        True if order increases net exposure
    """
    # If no existing position, it's an increase
    if existing_position_contracts == 0:
        return True
    
    # If same side, it's an increase
    if existing_position_side and existing_position_side.upper() == side.upper():
        return True
    
    # If opposite side and size <= existing, it's a reduction or close
    if requested_contracts <= existing_position_contracts:
        return False
    
    # Opposite side but larger than existing = net flip (treat as increase)
    return True
