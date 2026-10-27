"""Q-Inline Policy Agent

Phase 7 of MERID single-signal hierarchy:
Final execution policy layer that integrates all signal sources and produces
executable trade decisions with position sizing, risk checks, and regime awareness.

The Q-Inline Policy is the "last mile" before execution - it takes all upstream
signals (macro, momentum, BTC anchor, regime, MM state) and produces:
- Final trade direction and confidence
- Position size in contracts
- Execution urgency (immediate vs delayed)
- Risk budget consumption

References:
- Integrates with TopNAllocator for bankroll allocation
- Consumes UnifiedRegimeClassifier for regime adjustments
- Uses KalshiRiskManager for final risk validation
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import Enum
from collections import deque

from merid.signals.unified_regime_classifier import (
    get_unified_regime_classifier,
    UnifiedRegimeState,
    ExecutionRegime,
)
from merid.kalshi.macro_overlay import get_kalshi_macro_overlay
from merid.signals.momentum_ranker import get_momentum_ranker
from merid.signals.btc_anchor_gate import get_btc_anchor_gate
from merid.kalshi.mm_integration import get_market_maker_integration
from utils.logger import get_logger

logger = get_logger("merid.policy.qinline")


class TradeDecision(str, Enum):
    """Final trade execution decision."""
    EXECUTE_LONG = "execute_long"
    EXECUTE_SHORT = "execute_short"
    HOLD = "hold"
    REDUCE = "reduce"
    HALT = "halt"


class Urgency(str, Enum):
    """Execution urgency level."""
    IMMEDIATE = "immediate"    # Execute this cycle
    NEXT_CYCLE = "next_cycle"   # Queue for next cycle
    DELAYED = "delayed"         # Wait for condition
    PASS = "pass"               # Skip this opportunity


@dataclass
class QValue:
    """Q-value for state-action pair with confidence."""
    action: str  # "long", "short", "hold"
    value: float  # Expected return estimate
    confidence: float  # 0-1 confidence in Q-value
    visits: int = 0  # Number of times this state-action seen


@dataclass
class QInlineDecision:
    """Final execution decision from Q-Inline Policy.
    
    This is the output that goes to the execution layer.
    """
    ticker: str
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    
    # Decision
    decision: TradeDecision
    urgency: Urgency
    
    # Sizing
    target_contracts: int
    confidence: float  # 0-1 overall confidence
    
    # Price limits
    max_entry_price_cents: Optional[int] = None
    min_exit_price_cents: Optional[int] = None
    
    # Risk
    risk_budget_consumed_pct: float = 0.0  # % of cycle risk budget
    stop_price_cents: Optional[int] = None
    
    # Signal contributions
    macro_contribution: float = 0.0
    momentum_contribution: float = 0.0
    btc_anchor_contribution: float = 0.0
    regime_multiplier: float = 1.0
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    policy_version: str = "qinline-v1"
    
    @property
    def should_execute(self) -> bool:
        """Whether this decision should result in execution."""
        return self.decision in (TradeDecision.EXECUTE_LONG, TradeDecision.EXECUTE_SHORT)
    
    @property
    def side(self) -> Optional[str]:
        """Trade side if executing."""
        if self.decision == TradeDecision.EXECUTE_LONG:
            return "long"
        elif self.decision == TradeDecision.EXECUTE_SHORT:
            return "short"
        return None


@dataclass
class QInlineState:
    """Aggregated state representation for Q-Inline Policy."""
    ticker: str
    asset: str
    timestamp: float
    
    # Market microstructure
    mid_price_cents: int = 0
    spread_cents: int = 0
    volume_24h: int = 0
    
    # Signal layer inputs (all normalized to -1 to 1)
    macro_score: float = 0.0  # From MacroConvictionScorer
    momentum_score: float = 0.0  # From MomentumRanker
    btc_anchor_score: float = 0.0  # From BtcAnchorGate (normalised)
    
    # Regime state
    execution_regime: ExecutionRegime = ExecutionRegime.NORMAL
    regime_position_multiplier: float = 1.0
    regime_edge_multiplier: float = 1.0
    
    # Inventory state
    current_position: int = 0
    inventory_skew: float = 0.0  # -1 to 1, affects sizing
    
    # Risk state
    remaining_risk_budget_pct: float = 1.0
    daily_pnl_cents: int = 0
    
    @property
    def composite_signal(self) -> float:
        """Weighted composite of all signal scores."""
        # Weights: macro 35%, momentum 30%, BTC anchor 35%
        return (
            0.35 * self.macro_score +
            0.30 * self.momentum_score +
            0.35 * self.btc_anchor_score
        )


class QInlinePolicy:
    """Q-Inline Policy Agent - final execution policy layer.
    
    Integrates all upstream signal layers and produces executable trade decisions.
    Uses a simplified Q-learning approach with value iteration over discrete
    state-action pairs, inlined for execution speed.
    """
    
    # Signal thresholds
    STRONG_SIGNAL_THRESHOLD = 0.4
    WEAK_SIGNAL_THRESHOLD = 0.15
    
    # Position sizing parameters
    BASE_CONTRACTS_PER_SIGNAL_STRENGTH = 10  # Contracts at signal=1.0
    MAX_CONTRACTS_PER_TRADE = 50
    MIN_CONTRACTS_PER_TRADE = 1
    
    # Confidence thresholds
    MIN_CONFIDENCE_TO_TRADE = 0.3
    STRONG_CONFIDENCE_THRESHOLD = 0.7
    
    # Q-value table (state hash -> action -> QValue)
    # In production, this would be backed by a learned model
    _q_table: Dict[str, Dict[str, QValue]] = {}
    _q_table_lock = threading.Lock()
    
    def __init__(self):
        self._regime_classifier = get_unified_regime_classifier()
        self._macro_overlay = get_kalshi_macro_overlay()
        self._momentum_ranker = get_momentum_ranker()
        self._btc_gate = get_btc_anchor_gate()
        self._mm_integration = get_market_maker_integration()
        
        # Decision history for learning
        self._decision_history: deque = deque(maxlen=1000)
        
        # Callbacks for decision events
        self._callbacks: List[Callable[[QInlineDecision], None]] = []
        
        self._lock = threading.Lock()
        
        logger.info("QInlinePolicy initialized")
    
    def evaluate(
        self,
        ticker: str,
        mid_price_cents: int,
        current_position: int = 0,
        remaining_risk_budget_pct: float = 1.0,
    ) -> QInlineDecision:
        """Evaluate current state and produce execution decision.
        
        This is the main entry point for the Q-Inline Policy.
        
        Args:
            ticker: Kalshi ticker symbol
            mid_price_cents: Current mid price
            current_position: Current position in contracts (positive=long)
            remaining_risk_budget_pct: Remaining risk budget (0-1)
            
        Returns:
            QInlineDecision with sizing and execution parameters
        """
        with self._lock:
            asset = self._extract_asset(ticker) or "UNKNOWN"
            
            # Build state representation
            state = self._build_state(
                ticker, asset, mid_price_cents, current_position, remaining_risk_budget_pct
            )
            
            # Check halt regime
            if state.execution_regime == ExecutionRegime.HALT:
                return self._make_halt_decision(ticker, asset, state)
            
            # Compute Q-values for each action
            q_values = self._compute_q_values(state)
            
            # Select best action
            best_action = self._select_action(q_values, state)
            
            # Build decision
            decision = self._build_decision(ticker, asset, state, best_action, q_values)
            
            # Store for learning
            self._decision_history.append(decision)
            
            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(decision)
                except Exception as e:
                    logger.error("Q-Inline callback failed: %s", e)
            
            return decision
    
    def _build_state(
        self,
        ticker: str,
        asset: str,
        mid_price_cents: int,
        current_position: int,
        remaining_risk_budget_pct: float,
    ) -> QInlineState:
        """Build aggregated state from all signal sources."""
        state = QInlineState(
            ticker=ticker,
            asset=asset,
            timestamp=time.time(),
            mid_price_cents=mid_price_cents,
            current_position=current_position,
            remaining_risk_budget_pct=remaining_risk_budget_pct,
        )
        
        # Get regime state
        regime_state = self._regime_classifier.get_current_state()
        if regime_state:
            state.execution_regime = regime_state.execution_regime
            state.regime_position_multiplier = regime_state.position_size_multiplier
            state.regime_edge_multiplier = regime_state.edge_threshold_multiplier
        
        # Get macro score
        convictions = self._macro_overlay.get_conviction_scores()
        if asset in convictions:
            conv = convictions[asset]
            # Convert conviction to -1 to 1 score
            state.macro_score = (conv.score - 0.5) * 2
        
        # Get momentum score
        momentum = self._momentum_ranker.get_current_rankings()
        if momentum and asset in momentum.assets:
            mom = momentum.assets[asset]
            state.momentum_score = (mom.composite_score - 0.5) * 2
        
        # Get BTC anchor score
        btc_state = self._btc_gate.get_current_regime()
        if btc_state:
            # Normalize BTC regime to score
            if btc_state.is_strong_bull:
                state.btc_anchor_score = 0.8
            elif btc_state.regime.value == "bull":
                state.btc_anchor_score = 0.4
            elif btc_state.is_strong_bear:
                state.btc_anchor_score = -0.8
            elif btc_state.regime.value == "bear":
                state.btc_anchor_score = -0.4
            
            # Reduce confidence if BTC trending opposite to desired direction
            if btc_state.is_trending and state.macro_score * state.btc_anchor_score < 0:
                state.btc_anchor_score *= 0.5  # Reduce weight when conflict
        
        # Get inventory skew from MM integration
        inventory = self._mm_integration.get_inventory(ticker)
        if inventory:
            max_inv = 50  # Normalization constant
            state.inventory_skew = max(-1, min(1, inventory.net_position / max_inv))
        
        return state
    
    def _compute_q_values(self, state: QInlineState) -> Dict[str, QValue]:
        """Compute Q-values for each possible action."""
        composite = state.composite_signal
        
        # Base Q-values from signal strength
        q_long = QValue("long", value=composite, confidence=abs(composite))
        q_short = QValue("short", value=-composite, confidence=abs(composite))
        q_hold = QValue("hold", value=0.0, confidence=1.0 - abs(composite))
        
        # Adjust for regime
        if state.execution_regime == ExecutionRegime.DEFENSIVE:
            # In defensive, prefer holding, reduce directional confidence
            q_long.confidence *= 0.7
            q_short.confidence *= 0.7
            q_hold.confidence = min(1.0, q_hold.confidence * 1.3)
        elif state.execution_regime == ExecutionRegime.AGGRESSIVE:
            # In aggressive, boost directional confidence
            q_long.confidence = min(1.0, q_long.confidence * 1.2)
            q_short.confidence = min(1.0, q_short.confidence * 1.2)
        
        # Adjust for inventory skew
        if state.inventory_skew > 0.3:  # Already long
            q_long.value *= (1 - state.inventory_skew * 0.5)  # Reduce long appeal
            q_short.value *= (1 + state.inventory_skew * 0.3)  # Increase short appeal
        elif state.inventory_skew < -0.3:  # Already short
            q_short.value *= (1 + state.inventory_skew * 0.5)  # Reduce short appeal (skew is negative)
            q_long.value *= (1 - state.inventory_skew * 0.3)  # Increase long appeal
        
        # Adjust for risk budget
        if state.remaining_risk_budget_pct < 0.2:
            q_long.confidence *= 0.5
            q_short.confidence *= 0.5
            q_hold.confidence = min(1.0, q_hold.confidence * 1.5)
        
        return {
            "long": q_long,
            "short": q_short,
            "hold": q_hold,
        }
    
    def _select_action(self, q_values: Dict[str, QValue], state: QInlineState) -> str:
        """Select best action based on Q-values and constraints."""
        # Filter by minimum confidence
        viable = {
            action: qv for action, qv in q_values.items()
            if qv.confidence >= self.MIN_CONFIDENCE_TO_TRADE or action == "hold"
        }
        
        if not viable:
            return "hold"
        
        # Select by value (with tie-breaking by confidence)
        best_action = max(viable.items(), key=lambda x: (x[1].value, x[1].confidence))[0]
        
        # Override for extreme regimes
        if state.execution_regime == ExecutionRegime.HALT:
            return "hold"
        
        return best_action
    
    def _build_decision(
        self,
        ticker: str,
        asset: str,
        state: QInlineState,
        action: str,
        q_values: Dict[str, QValue],
    ) -> QInlineDecision:
        """Build final decision from selected action."""
        
        # Determine trade decision
        if action == "long":
            decision = TradeDecision.EXECUTE_LONG
        elif action == "short":
            decision = TradeDecision.EXECUTE_SHORT
        else:
            decision = TradeDecision.HOLD
        
        # Compute sizing
        base_size = self._compute_position_size(state, action)
        adjusted_size = int(base_size * state.regime_position_multiplier)
        
        # Determine urgency
        urgency = self._determine_urgency(state, decision)
        
        # Compute risk budget consumption
        risk_consumed = self._compute_risk_consumption(adjusted_size, state)
        
        # Build decision
        return QInlineDecision(
            ticker=ticker,
            asset=asset,
            decision=decision,
            urgency=urgency,
            target_contracts=adjusted_size if decision != TradeDecision.HOLD else 0,
            confidence=q_values[action].confidence,
            risk_budget_consumed_pct=risk_consumed,
            macro_contribution=state.macro_score * 0.35,
            momentum_contribution=state.momentum_score * 0.30,
            btc_anchor_contribution=state.btc_anchor_score * 0.35,
            regime_multiplier=state.regime_position_multiplier,
            timestamp=time.time(),
        )
    
    def _compute_position_size(self, state: QInlineState, action: str) -> int:
        """Compute base position size from signal strength."""
        signal_strength = abs(state.composite_signal)
        
        # Size proportional to signal strength, regime, and risk budget
        base = int(
            self.BASE_CONTRACTS_PER_SIGNAL_STRENGTH *
            signal_strength *
            state.remaining_risk_budget_pct
        )
        
        # Apply limits
        return max(
            self.MIN_CONTRACTS_PER_TRADE,
            min(self.MAX_CONTRACTS_PER_TRADE, base)
        )
    
    def _determine_urgency(self, state: QInlineState, decision: TradeDecision) -> Urgency:
        """Determine execution urgency."""
        if decision == TradeDecision.HOLD:
            return Urgency.PASS
        
        # High confidence + strong signal = immediate
        if state.composite_signal > self.STRONG_SIGNAL_THRESHOLD:
            return Urgency.IMMEDIATE
        
        # Medium confidence = next cycle
        if state.composite_signal > self.WEAK_SIGNAL_THRESHOLD:
            return Urgency.NEXT_CYCLE
        
        # Low confidence = delayed
        return Urgency.DELAYED
    
    def _compute_risk_consumption(self, contracts: int, state: QInlineState) -> float:
        """Compute percentage of risk budget consumed."""
        if contracts == 0:
            return 0.0
        
        # Simplified: assume each contract = 2% of risk budget at max size
        max_consumption = 0.02 * self.MAX_CONTRACTS_PER_TRADE
        actual_consumption = 0.02 * contracts * state.regime_position_multiplier
        
        return actual_consumption
    
    def _make_halt_decision(self, ticker: str, asset: str, state: QInlineState) -> QInlineDecision:
        """Create halt decision when in halt regime."""
        return QInlineDecision(
            ticker=ticker,
            asset=asset,
            decision=TradeDecision.HALT,
            urgency=Urgency.PASS,
            target_contracts=0,
            confidence=1.0,
            risk_budget_consumed_pct=0.0,
            regime_multiplier=0.0,
            macro_contribution=state.macro_score,
            momentum_contribution=state.momentum_score,
            btc_anchor_contribution=state.btc_anchor_score,
            timestamp=time.time(),
        )
    
    def _extract_asset(self, ticker: str) -> Optional[str]:
        """Extract asset symbol from Kalshi ticker."""
        if ticker.startswith("KXBTC"):
            return "BTC"
        elif ticker.startswith("KXETH"):
            return "ETH"
        elif ticker.startswith("KXSOL"):
            return "SOL"
        elif ticker.startswith("KXXRP"):
            return "XRP"
        elif ticker.startswith("KXDOGE"):
            return "DOGE"
        return None
    
    def register_callback(self, callback: Callable[[QInlineDecision], None]) -> None:
        """Register callback for decision events."""
        with self._lock:
            self._callbacks.append(callback)
            logger.debug("Q-Inline callback registered")
    
    def get_decision_history(
        self,
        since: Optional[float] = None,
        ticker: Optional[str] = None,
    ) -> List[QInlineDecision]:
        """Get decision history with optional filtering."""
        with self._lock:
            decisions = list(self._decision_history)
            
            if since:
                decisions = [d for d in decisions if d.timestamp >= since]
            if ticker:
                decisions = [d for d in decisions if d.ticker == ticker]
            
            return decisions
    
    def reset(self) -> None:
        """Reset policy state."""
        with self._lock:
            self._decision_history.clear()
            self._callbacks.clear()
            with self._q_table_lock:
                self._q_table.clear()
            logger.info("QInlinePolicy reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_policy_instance: Optional[QInlinePolicy] = None
_policy_lock = threading.Lock()


def get_qinline_policy() -> QInlinePolicy:
    """Get or create the singleton QInlinePolicy."""
    global _policy_instance
    if _policy_instance is None:
        with _policy_lock:
            if _policy_instance is None:
                _policy_instance = QInlinePolicy()
                logger.info("QInlinePolicy singleton initialized")
    return _policy_instance


def reset_qinline_policy() -> None:
    """Reset the singleton (for testing)."""
    global _policy_instance
    with _policy_lock:
        _policy_instance = None
        logger.info("QInlinePolicy singleton reset")
