"""Trade-vs-Hold Decision — first-class decision object for every cycle.

Every cycle of every agent produces exactly ONE ``Decision`` per market
evaluated.  The Decision captures *what* the system decided (TRADE or HOLD),
*why* (a mandatory ``HoldReason`` or "all_checks_passed"), and the full
context that led to the decision (signal, risk check, config snapshot).

Usage::

    from merid.prediction.decision import Decision, DecisionAction, HoldReason

    # Build a HOLD
    d = Decision.hold(HoldReason.WARMUP, "agent still warming up (12s elapsed)")

    # Build a TRADE
    d = Decision.trade(signal=signal, risk_check=check)

    # Gate downstream
    if d.action == DecisionAction.TRADE:
        await route_order(...)
    else:
        logger.info("[DECISION] HOLD: %s — %s", d.hold_reason.value, d.detail)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class DecisionAction(str, Enum):
    """Top-level action: either we trade or we hold."""
    TRADE = "trade"
    HOLD = "hold"


class HoldReason(str, Enum):
    """Mandatory reason when action == HOLD.

    Ordered roughly by pipeline stage (earliest gate first).
    """
    # ── Infrastructure / lifecycle ────────────────────────────────────
    CONFIG_DISABLED = "config_disabled"          # Agent or trading disabled in config
    KILL_SWITCH = "kill_switch"                  # Global or per-agent kill switch active
    SESSION_CLOSED = "session_closed"            # Outside Kalshi trading hours
    WARMUP = "warmup"                            # Agent in WARMING_UP lifecycle
    VENUE_BLOCKED = "venue_blocked"              # VenueGate blocks non-Kalshi venues

    # ── Market resolution ─────────────────────────────────────────────
    NO_MARKETS = "no_markets"                    # No markets resolved for this agent
    OUTSIDE_ENTRY_WINDOW = "outside_entry_window"  # Market not in entry window
    EXPIRY_PROXIMITY = "expiry_proximity"        # Too close to expiry (≤90s guard)

    # ── Strategy / signal ─────────────────────────────────────────────
    NO_EDGE = "no_edge"                          # Strategy returned NO_ACTION (no edge)
    EDGE_BELOW_THRESHOLD = "edge_below_threshold"  # Edge present but below min
    CONFIDENCE_TOO_LOW = "confidence_too_low"    # Model confidence below threshold
    STALE_DATA = "stale_data"                    # Snapshot or spot price stale
    SPOT_STRIKE_VETO = "spot_strike_veto"        # Spot–strike anomaly veto
    LIQUIDITY_GUARD = "liquidity_guard"          # Volume or OI below minimum
    CONVICTION_VETO = "conviction_veto"          # Structural conviction below floor
    PM_SPOT_GATE = "pm_spot_gate"                # MM spot data missing/stale

    # ── Consensus / swarm ─────────────────────────────────────────────
    CONSENSUS_FORMING = "consensus_forming"      # Swarm consensus still forming
    CONSENSUS_CONFLICTED = "consensus_conflicted"  # Swarm agents disagree
    CONSENSUS_DIRECTION_MISMATCH = "consensus_direction_mismatch"
    SOLO_WINDOW = "solo_window"                  # Waiting for solo execution threshold
    SOLO_CAP_REACHED = "solo_cap_reached"        # Solo trade cap exhausted
    SOLO_WALL_CLOCK = "solo_wall_clock"          # Degraded wall-clock limit
    TOP3_EXCLUDED = "top3_excluded"              # Not in top-3 edge allocation for cycle

    # ── Risk / pre-trade ──────────────────────────────────────────────
    RISK_LIMIT = "risk_limit"                    # PredictionMarketRisk rejected
    RISK_HALT = "risk_halt"                      # Risk manager halted trading
    RISK_REDUCE = "risk_reduce"                  # Risk wants size reduction (treated as hold at 0)
    ORDER_LIMIT = "order_limit"                  # Per-window order count exceeded
    RATE_LIMIT = "rate_limit"                    # Orders/min or /hour exceeded

    # ── Execution ─────────────────────────────────────────────────────
    EXECUTION_ERROR = "execution_error"          # Order placement failed

    # ── Catch-all ─────────────────────────────────────────────────────
    UNKNOWN = "unknown"                          # Should never appear in production


@dataclass(frozen=True)
class Decision:
    """Immutable record of a single trade-vs-hold decision.

    Attributes:
        action:         TRADE or HOLD.
        hold_reason:    Why we held (None when action == TRADE).
        detail:         Human-readable elaboration (always set).
        market_id:      Kalshi ticker this decision applies to (may be None for
                        cycle-level holds like WARMUP or SESSION_CLOSED).
        agent_name:     Name of the agent that produced this decision.
        cycle_number:   Which cycle produced this decision.
        timestamp:      UTC wall-clock when the decision was made.
        signal_summary: Compact dict of the StrategySignal (for TRADE / post-signal HOLD).
        risk_summary:   Compact dict of the PreTradeCheck (for TRADE / post-risk HOLD).
        config_snapshot: Key thresholds active at decision time.
        elapsed_ms:     Wall-clock ms from cycle start to decision point.
    """
    action: DecisionAction
    hold_reason: Optional[HoldReason] = None
    detail: str = ""
    market_id: Optional[str] = None
    agent_name: str = ""
    cycle_number: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_summary: Dict[str, Any] = field(default_factory=dict)
    risk_summary: Dict[str, Any] = field(default_factory=dict)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    # ── Convenience constructors ──────────────────────────────────────

    @classmethod
    def trade(
        cls,
        *,
        market_id: str,
        agent_name: str = "",
        cycle_number: int = 0,
        detail: str = "all_checks_passed",
        signal_summary: Optional[Dict[str, Any]] = None,
        risk_summary: Optional[Dict[str, Any]] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
        elapsed_ms: float = 0.0,
    ) -> Decision:
        return cls(
            action=DecisionAction.TRADE,
            hold_reason=None,
            detail=detail,
            market_id=market_id,
            agent_name=agent_name,
            cycle_number=cycle_number,
            signal_summary=signal_summary or {},
            risk_summary=risk_summary or {},
            config_snapshot=config_snapshot or {},
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def hold(
        cls,
        reason: HoldReason,
        detail: str,
        *,
        market_id: Optional[str] = None,
        agent_name: str = "",
        cycle_number: int = 0,
        signal_summary: Optional[Dict[str, Any]] = None,
        risk_summary: Optional[Dict[str, Any]] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
        elapsed_ms: float = 0.0,
    ) -> Decision:
        return cls(
            action=DecisionAction.HOLD,
            hold_reason=reason,
            detail=detail,
            market_id=market_id,
            agent_name=agent_name,
            cycle_number=cycle_number,
            signal_summary=signal_summary or {},
            risk_summary=risk_summary or {},
            config_snapshot=config_snapshot or {},
            elapsed_ms=elapsed_ms,
        )

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Flat dict suitable for structured logging / JSON export."""
        return {
            "action": self.action.value,
            "hold_reason": self.hold_reason.value if self.hold_reason else None,
            "detail": self.detail[:500],
            "market_id": self.market_id,
            "agent_name": self.agent_name,
            "cycle_number": self.cycle_number,
            "timestamp": self.timestamp.isoformat(),
            "signal_summary": self.signal_summary,
            "risk_summary": self.risk_summary,
            "config_snapshot": self.config_snapshot,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    def log_line(self) -> str:
        """One-line structured log suitable for ``[PM_DECISION]`` tag."""
        hr = self.hold_reason.value if self.hold_reason else "-"
        return (
            f"[PM_DECISION] action={self.action.value} hold_reason={hr} "
            f"market={self.market_id or '-'} agent={self.agent_name} "
            f"cycle={self.cycle_number} elapsed_ms={self.elapsed_ms:.1f} "
            f"detail={self.detail[:200]}"
        )


class DecisionTimer:
    """Context-manager / helper to measure elapsed_ms for a decision."""

    def __init__(self) -> None:
        self._start: float = time.monotonic()

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000.0

    def __enter__(self) -> "DecisionTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        pass
