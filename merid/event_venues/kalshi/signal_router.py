"""Signal Router — Downstream signal routing for signal-only agents.

SINGLE EXECUTOR PRINCIPLE: Only trading_agent can execute trades.
Signal-only agents (lanes, kalshi_tools, CT, universal_agent) must route
signals through this module to reach trading_agent for execution.

This ensures:
1. All signals are logged and traceable
2. Risk checks happen at the execution point (trading_agent)
3. No agent can bypass the execution guard
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Callable
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Known enum values (used for validation) ──────────────────────────
_VALID_ACTIONS = frozenset({"buy", "sell", "hold", "no_action"})
_VALID_SIDES = frozenset({"yes", "no"})
_VALID_INTENTS = frozenset({"open", "close", "scale_in", "scale_out", "rebalance"})


@dataclass
class AgentSignal:
    """Signal from a signal-only agent requesting execution.

    This is NOT an order — it is a signal/recommendation that trading_agent
    will evaluate and potentially execute after risk checks.

    Two tiers of data:
      1. **Core** (always required): agent_id, agent_type, market_id, action.
      2. **Execution** (required when ``executable=True``): side, size,
         price_cents must all be present and positive.

    Call ``validate()`` before submitting.  If ``validation_errors`` is
    non-empty the signal MUST be dropped.
    """

    # ── Core identification ───────────────────────────────────────────
    agent_id: str
    agent_type: str  # e.g., "btc15m_lane", "kalshi_tools", "ct", "universal_agent"
    market_id: str
    action: str  # e.g., "buy", "sell", "hold", "no_action"
    side: Optional[str] = None  # "yes", "no" for binary markets
    size: Optional[int] = None  # Recommended contract count
    price_cents: Optional[int] = None  # Limit price in cents
    confidence: float = 0.5
    edge: Optional[float] = None  # Edge estimate
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_id: str = field(default_factory=lambda: f"sig-{datetime.now(timezone.utc).timestamp():.6f}")

    # ── Enrichment fields (populated by originating agent) ────────────
    intent: str = "open"  # open | close | scale_in | scale_out | rebalance
    origin_agent: str = ""  # Agent name from YAML grid (e.g., "BTC_15M")
    origin_strategy: str = ""  # Strategy class name
    risk_bucket: str = ""  # Risk category (e.g., "crypto_directional")
    timeframe_label: str = ""  # e.g., "15m", "1h", "daily"

    # ── Validation / readiness ────────────────────────────────────────
    executable: bool = False  # True = all execution fields must be present
    validation_errors: List[str] = field(default_factory=list)

    # ── Quality tracking (populated by SignalRouter) ──────────────────
    quality_score: float = 0.0  # 0-1 quality score
    is_duplicate: bool = False  # True if this is a duplicate signal
    consensus_count: int = 1  # How many agents agree with this signal

    # ── Validation ────────────────────────────────────────────────────

    def validate(self) -> bool:
        """Validate invariants and return True if signal is clean.

        For *executable* signals, side/size/price_cents must be present and
        positive.  For informational signals only core fields are checked.
        Errors are accumulated in ``validation_errors``.
        """
        self.validation_errors.clear()

        # Core checks (always)
        if not self.agent_id:
            self.validation_errors.append("agent_id is required")
        if not self.agent_type:
            self.validation_errors.append("agent_type is required")
        if not self.market_id:
            self.validation_errors.append("market_id is required")
        if self.action not in _VALID_ACTIONS:
            self.validation_errors.append(
                f"action '{self.action}' not in {sorted(_VALID_ACTIONS)}"
            )

        # Execution-tier checks
        if self.executable:
            if self.side not in _VALID_SIDES:
                self.validation_errors.append(
                    f"side '{self.side}' must be 'yes' or 'no' for executable signals"
                )
            if self.size is None or self.size <= 0:
                self.validation_errors.append(
                    "size must be a positive int for executable signals"
                )
            if self.price_cents is None or self.price_cents <= 0:
                self.validation_errors.append(
                    "price_cents must be a positive int for executable signals"
                )
            if self.price_cents is not None and self.price_cents > 99:
                self.validation_errors.append(
                    f"price_cents={self.price_cents} exceeds Kalshi 99c limit"
                )
            if not (0.0 <= self.confidence <= 1.0):
                self.validation_errors.append(
                    f"confidence={self.confidence} outside [0, 1]"
                )

        return len(self.validation_errors) == 0

    @property
    def is_valid(self) -> bool:
        """True if last ``validate()`` call found no errors."""
        return len(self.validation_errors) == 0

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "market_id": self.market_id,
            "action": self.action,
            "side": self.side,
            "size": self.size,
            "price_cents": self.price_cents,
            "confidence": self.confidence,
            "edge": self.edge,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "intent": self.intent,
            "origin_agent": self.origin_agent,
            "origin_strategy": self.origin_strategy,
            "risk_bucket": self.risk_bucket,
            "timeframe_label": self.timeframe_label,
            "executable": self.executable,
            "quality_score": self.quality_score,
            "is_duplicate": self.is_duplicate,
            "consensus_count": self.consensus_count,
        }

    def get_signature(self) -> str:
        """Generate a unique signature for deduplication.

        Signals with the same signature are considered duplicates.
        Signature includes: market, action, side, and time bucket (5-min window).
        """
        # Round timestamp to 5-minute bucket for dedup window
        time_bucket = self.timestamp.replace(
            minute=(self.timestamp.minute // 5) * 5,
            second=0,
            microsecond=0
        )
        return f"{self.market_id}:{self.action}:{self.side}:{time_bucket.isoformat()}"


class SignalRouter:
    """Routes signals from signal-only agents to trading_agent.
    
    This is a pub/sub system where:
    - Signal-only agents publish signals
    - trading_agent subscribes and consumes signals for execution
    """
    
    # Agent type quality weights (higher = more trusted)
    _AGENT_QUALITY_WEIGHTS: Dict[str, float] = {
        "btc15m_lane": 0.85,
        "crypto15m_lane": 0.85,
        "kalshi_tools": 0.75,
        "ct": 0.70,
        "universal_agent": 0.80,
    }
    
    # Minimum quality score for signal to be routed
    _MIN_QUALITY_SCORE: float = 0.30
    
    # Minimum confidence for signal to be considered
    _MIN_CONFIDENCE: float = 0.55
    
    def __init__(self) -> None:
        self._subscribers: List[Callable[[AgentSignal], None]] = []
        self._signal_log: List[AgentSignal] = []
        self._max_log_size = 10000
        self._lock: Optional[asyncio.Lock] = None
        
        # Deduplication tracking: signature -> list of signal IDs
        self._signal_signatures: Dict[str, List[str]] = {}
        self._dedup_window_seconds: int = 300  # 5 minute dedup window
        
        # Agent rate limiting: agent_id -> last signal timestamp
        self._agent_last_signal: Dict[str, datetime] = {}
        self._agent_min_interval: int = 30  # Minimum 30 seconds between signals from same agent
        
        # Consensus tracking: market_id -> list of signals in current window
        self._market_consensus: Dict[str, List[AgentSignal]] = {}
        
    def _get_lock(self) -> asyncio.Lock:
        """Lazy lock creation."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    def subscribe(self, callback: Callable[[AgentSignal], None]) -> None:
        """Subscribe to signals. trading_agent should call this."""
        self._subscribers.append(callback)
        logger.info(f"[SIGNAL_ROUTER] New subscriber: {callback.__name__ if hasattr(callback, '__name__') else callback}")
    
    def unsubscribe(self, callback: Callable[[AgentSignal], None]) -> None:
        """Unsubscribe from signals."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def _calculate_quality_score(self, signal: AgentSignal) -> float:
        """Calculate signal quality score (0-1) based on agent weight, confidence, and edge."""
        agent_weight = self._AGENT_QUALITY_WEIGHTS.get(signal.agent_type, 0.50)
        confidence_score = max(0, (signal.confidence - self._MIN_CONFIDENCE) / (1.0 - self._MIN_CONFIDENCE))
        edge_bonus = min(0.1, max(0, (signal.edge or 0)) * 0.5)
        quality = (agent_weight * 0.6) + (confidence_score * 0.3) + edge_bonus
        return min(1.0, max(0.0, quality))
    
    def _is_duplicate(self, signal: AgentSignal) -> bool:
        """Check if signal is a duplicate within the dedup window."""
        signature = signal.get_signature()
        cutoff = datetime.now(timezone.utc).timestamp() - self._dedup_window_seconds
        
        # Clean old signatures
        self._signal_signatures = {
            sig: ids for sig, ids in self._signal_signatures.items()
            if any(s.timestamp.timestamp() > cutoff for s in self._signal_log if s.signal_id in ids)
        }
        
        if signature in self._signal_signatures and self._signal_signatures[signature]:
            return True
        
        if signature not in self._signal_signatures:
            self._signal_signatures[signature] = []
        self._signal_signatures[signature].append(signal.signal_id)
        return False
    
    def _check_rate_limit(self, signal: AgentSignal) -> bool:
        """Check if agent is rate limited."""
        now = datetime.now(timezone.utc)
        last_signal = self._agent_last_signal.get(signal.agent_id)
        if last_signal and (now - last_signal).total_seconds() < self._agent_min_interval:
            return True
        self._agent_last_signal[signal.agent_id] = now
        return False
    
    async def publish_signal(self, signal: AgentSignal) -> bool:
        """Publish a signal from a signal-only agent with quality filtering.

        Applies validation, deduplication, rate limiting, and quality scoring
        before routing.  Returns True if routed to at least one subscriber.
        """
        # Reject invalid executable signals at the gate
        if signal.executable and not signal.is_valid:
            logger.warning(
                "[SIGNAL_ROUTER] Dropping invalid executable signal %s: %s",
                signal.signal_id, signal.validation_errors,
            )
            return False

        # Calculate quality score
        signal.quality_score = self._calculate_quality_score(signal)
        
        # Check minimum confidence
        if signal.confidence < self._MIN_CONFIDENCE:
            logger.debug(
                f"[SIGNAL_ROUTER] Signal {signal.signal_id} rejected: confidence {signal.confidence:.2f} < {self._MIN_CONFIDENCE}"
            )
            return False
        
        # Check quality score
        if signal.quality_score < self._MIN_QUALITY_SCORE:
            logger.debug(
                f"[SIGNAL_ROUTER] Signal {signal.signal_id} rejected: quality {signal.quality_score:.2f} < {self._MIN_QUALITY_SCORE}"
            )
            return False
        
        # Check rate limiting
        if self._check_rate_limit(signal):
            logger.warning(
                f"[SIGNAL_ROUTER] Signal {signal.signal_id} rejected: agent {signal.agent_id} rate limited"
            )
            return False
        
        # Check for duplicates
        signal.is_duplicate = self._is_duplicate(signal)
        
        async with self._get_lock():
            self._signal_log.append(signal)
            if len(self._signal_log) > self._max_log_size:
                self._signal_log = self._signal_log[-self._max_log_size:]
        
        logger.info(
            "[SIGNAL_ROUTER] Routing %s | %s:%s | ticker=%s side=%s size=%s price=%s "
            "| intent=%s quality=%.2f dup=%s exec=%s",
            signal.signal_id, signal.agent_type, signal.agent_id,
            signal.market_id, signal.side, signal.size, signal.price_cents,
            signal.intent, signal.quality_score, signal.is_duplicate,
            signal.executable,
        )
        
        # Route to all subscribers
        routed = False
        for subscriber in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(signal)
                else:
                    subscriber(signal)
                routed = True
            except Exception as e:
                logger.error(f"[SIGNAL_ROUTER] Failed to route to subscriber: {e}")
        
        if not routed:
            logger.warning(
                f"[SIGNAL_ROUTER] No subscribers for signal {signal.signal_id} - "
                "signal dropped (trading_agent may not be running)"
            )
        
        return routed
    
    def get_recent_signals(self, count: int = 100) -> List[AgentSignal]:
        """Get recent signals for debugging/audit."""
        return self._signal_log[-count:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        return {
            "subscriber_count": len(self._subscribers),
            "signal_log_size": len(self._signal_log),
            "max_log_size": self._max_log_size,
        }


# Global signal router singleton
_signal_router: Optional[SignalRouter] = None


def get_signal_router() -> SignalRouter:
    """Get the global signal router instance."""
    global _signal_router
    if _signal_router is None:
        _signal_router = SignalRouter()
    return _signal_router


def subscribe_to_signals(callback: Callable[[AgentSignal], None]) -> None:
    """Subscribe to signals from signal-only agents.
    
    This is the entry point for trading_agent to receive signals.
    Signal-only agents (lanes, tools, CT) use submit_signal() to publish.
    """
    router = get_signal_router()
    router.subscribe(callback)


# Convenience function for signal-only agents
def submit_signal(
    agent_id: str,
    agent_type: str,
    market_id: str,
    action: str,
    side: Optional[str] = None,
    size: Optional[int] = None,
    price_cents: Optional[int] = None,
    confidence: float = 0.5,
    edge: Optional[float] = None,
    reasoning: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    # ── Enrichment (new) ──────────────────────────────────────────────
    intent: str = "open",
    origin_agent: str = "",
    origin_strategy: str = "",
    risk_bucket: str = "",
    timeframe_label: str = "",
) -> AgentSignal:
    """Submit a signal for routing to trading_agent.

    This is the canonical way for signal-only agents to send signals downstream.
    The signal will be routed to trading_agent for evaluation and potential
    execution.  Signals are automatically marked ``executable=True`` and
    validated; invalid signals are logged and dropped (never routed).

    Example:
        signal = submit_signal(
            agent_id="btc15m_lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout pattern",
            origin_agent="BTC_15M",
            origin_strategy="SpotBasisFairValueStrategy",
            risk_bucket="crypto_directional",
            timeframe_label="15m",
        )
    """
    signal = AgentSignal(
        agent_id=agent_id,
        agent_type=agent_type,
        market_id=market_id,
        action=action,
        side=side,
        size=size,
        price_cents=price_cents,
        confidence=confidence,
        edge=edge,
        reasoning=reasoning,
        metadata=metadata or {},
        intent=intent,
        origin_agent=origin_agent,
        origin_strategy=origin_strategy,
        risk_bucket=risk_bucket,
        timeframe_label=timeframe_label,
        executable=True,
    )

    # Validate before routing — drop invalid signals at origin
    if not signal.validate():
        logger.warning(
            "[SIGNAL_ROUTER] Dropping invalid signal from %s:%s: %s",
            agent_type, agent_id, signal.validation_errors,
        )
        return signal

    # Async publish - fire and forget (router handles errors)
    try:
        router = get_signal_router()
        # Try to get running loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(router.publish_signal(signal))
            logger.debug("[SIGNAL_ROUTER] Signal %s queued for routing", signal.signal_id)
        except RuntimeError:
            # No running loop - log warning, signal will be lost
            # This happens when called from sync context without event loop
            logger.warning(
                "[SIGNAL_ROUTER] No event loop running - signal %s dropped. "
                "Call submit_signal from async context or ensure event loop is running.",
                signal.signal_id,
            )
    except Exception as e:
        logger.error("[SIGNAL_ROUTER] Failed to submit signal: %s", e)

    return signal
