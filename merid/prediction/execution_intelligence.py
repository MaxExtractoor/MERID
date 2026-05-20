"""Execution Intelligence — Sprint O.

Smart order routing that decides between crossing the spread (market order)
and joining the queue (limit order at the touch) based on orderbook
microstructure signals.

Decision factors:
1. **Spread width** — Narrow spread → cheaper to cross; wide → join queue
2. **Queue position value** — Depth at touch → longer wait, but better fill
3. **Urgency** — Time-to-expiry proximity increases urgency → cross
4. **Edge magnitude** — Large edge → cross (capture before it disappears)
5. **Orderbook imbalance** — Favourable imbalance → join queue (price moving our way)

Usage::

    intel = get_execution_intel()
    decision = intel.decide(
        bid=0.45, ask=0.52, side="buy",
        edge=0.08, minutes_to_expiry=30.0,
        bid_depth=100, ask_depth=50,
    )
    # decision.strategy == "cross" or "join_queue"
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.execution_intelligence")


@dataclass
class ExecutionDecision:
    """Result of the queue-join vs market-cross analysis."""
    strategy: str           # "cross" | "join_queue" | "join_far"
    reason: str             # Human-readable reason
    suggested_price: float  # Suggested limit price (cents fraction)
    urgency_score: float    # 0.0 (patient) → 1.0 (urgent)
    spread_cents: float     # Current spread
    edge_pct: float         # Edge magnitude
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "reason": self.reason,
            "suggested_price": self.suggested_price,
            "urgency_score": round(self.urgency_score, 3),
            "spread_cents": round(self.spread_cents, 4),
            "edge_pct": round(self.edge_pct, 4),
            "timestamp": self.timestamp,
        }


# Thresholds
_NARROW_SPREAD = 0.03    # 3 cents — cheap to cross
_WIDE_SPREAD = 0.08      # 8 cents — expensive to cross
_HIGH_EDGE = 0.06        # 6% edge — worth crossing for
_URGENT_MINUTES = 30.0   # < 30 min = urgent
_DEEP_QUEUE = 200        # > 200 contracts at touch = long wait


class ExecutionIntelligence:
    """Decides between crossing the spread and joining the queue.

    Maintains history of decisions for analysis and tuning.
    """

    def __init__(self):
        self._history: Deque[ExecutionDecision] = deque(maxlen=500)
        self._cross_count = 0
        self._join_count = 0

    def decide(
        self,
        bid: Optional[float],
        ask: Optional[float],
        side: str = "buy",
        edge: float = 0.0,
        minutes_to_expiry: Optional[float] = None,
        bid_depth: int = 0,
        ask_depth: int = 0,
        **kwargs,
    ) -> ExecutionDecision:
        """Decide between crossing the spread and joining the queue.

        Args:
            bid: Best bid price (0.0 - 1.0 fraction)
            ask: Best ask price (0.0 - 1.0 fraction)
            side: "buy" or "sell"
            edge: Expected edge (fraction, e.g. 0.05 = 5%)
            minutes_to_expiry: Minutes until contract expiry
            bid_depth: Number of contracts at best bid
            ask_depth: Number of contracts at best ask
        """
        if bid is None or ask is None or ask <= bid:
            decision = ExecutionDecision(
                strategy="cross",
                reason="No valid orderbook — default to cross",
                suggested_price=ask if ask else 0.5,
                urgency_score=1.0,
                spread_cents=0.0,
                edge_pct=edge,
            )
            self._record(decision)
            return decision

        spread = ask - bid
        mid = (bid + ask) / 2.0

        # ── Score components ────────────────────────────────────────
        scores: Dict[str, float] = {}

        # 1. Spread cost score: narrow → cross is cheap (favours cross)
        if spread <= _NARROW_SPREAD:
            scores["spread"] = 0.8  # Cheap to cross
        elif spread >= _WIDE_SPREAD:
            scores["spread"] = 0.1  # Expensive to cross
        else:
            scores["spread"] = 0.8 - 0.7 * ((spread - _NARROW_SPREAD) / (_WIDE_SPREAD - _NARROW_SPREAD))

        # 2. Edge magnitude: big edge → cross to capture
        if abs(edge) >= _HIGH_EDGE:
            scores["edge"] = 0.9
        elif abs(edge) >= 0.05:  # CONSERVATIVE: 5% edge threshold
            scores["edge"] = 0.5
        else:
            scores["edge"] = 0.2

        # 3. Urgency: near expiry → cross
        if minutes_to_expiry is not None:
            if minutes_to_expiry < 10:
                scores["urgency"] = 1.0
            elif minutes_to_expiry < _URGENT_MINUTES:
                scores["urgency"] = 0.7
            elif minutes_to_expiry < 120:
                scores["urgency"] = 0.3
            else:
                scores["urgency"] = 0.1
        else:
            scores["urgency"] = 0.4  # Default medium

        # 4. Queue depth: deep queue → long wait → cross
        relevant_depth = ask_depth if side == "buy" else bid_depth
        if relevant_depth > _DEEP_QUEUE:
            scores["queue"] = 0.7  # Long wait
        elif relevant_depth > 50:
            scores["queue"] = 0.4
        else:
            scores["queue"] = 0.2  # Short queue, worth joining

        # 5. Imbalance: if buying and bid-heavy, price likely to rise → cross
        if bid_depth > 0 and ask_depth > 0:
            total = bid_depth + ask_depth
            imbalance = (bid_depth - ask_depth) / total
            if side == "buy" and imbalance > 0.3:
                scores["imbalance"] = 0.7  # Bid-heavy, price rising → cross
            elif side == "sell" and imbalance < -0.3:
                scores["imbalance"] = 0.7  # Ask-heavy, price falling → cross
            else:
                scores["imbalance"] = 0.3  # Neutral or favourable
        else:
            scores["imbalance"] = 0.4

        # ── Weighted combination ────────────────────────────────────
        weights = {
            "spread": 0.25,
            "edge": 0.25,
            "urgency": 0.20,
            "queue": 0.15,
            "imbalance": 0.15,
        }
        urgency_score = sum(scores[k] * weights[k] for k in weights)

        # ── Decision ────────────────────────────────────────────────
        if urgency_score >= 0.60:
            # Cross the spread
            if side == "buy":
                price = ask  # Lift the ask
            else:
                price = bid  # Hit the bid

            decision = ExecutionDecision(
                strategy="cross",
                reason=self._format_reason(scores, "cross"),
                suggested_price=round(price, 4),
                urgency_score=urgency_score,
                spread_cents=spread,
                edge_pct=edge,
            )
        elif urgency_score >= 0.35:
            # Join queue at the touch
            if side == "buy":
                price = bid  # Join the bid
            else:
                price = ask  # Join the ask

            decision = ExecutionDecision(
                strategy="join_queue",
                reason=self._format_reason(scores, "join_queue"),
                suggested_price=round(price, 4),
                urgency_score=urgency_score,
                spread_cents=spread,
                edge_pct=edge,
            )
        else:
            # Patient: join far side (inside the spread but not at touch)
            if side == "buy":
                price = bid + spread * 0.25  # Improve bid slightly
            else:
                price = ask - spread * 0.25  # Improve ask slightly

            decision = ExecutionDecision(
                strategy="join_far",
                reason=self._format_reason(scores, "join_far"),
                suggested_price=round(price, 4),
                urgency_score=urgency_score,
                spread_cents=spread,
                edge_pct=edge,
            )

        self._record(decision)
        return decision

    def _format_reason(self, scores: Dict[str, float], strategy: str) -> str:
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
        factors = ", ".join(f"{k}={v:.2f}" for k, v in top)
        return f"{strategy}: top factors [{factors}]"

    def _record(self, decision: ExecutionDecision) -> None:
        self._history.append(decision)
        if decision.strategy == "cross":
            self._cross_count += 1
        else:
            self._join_count += 1

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._cross_count + self._join_count
        return {
            "total_decisions": total,
            "cross_count": self._cross_count,
            "join_count": self._join_count,
            "cross_pct": round(self._cross_count / total * 100, 1) if total else 0.0,
        }

    @property
    def history(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._history]


# ── Singleton ────────────────────────────────────────────────────────────

_intel: Optional[ExecutionIntelligence] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _intel_lock = threading.Lock()
_intel_lock = None  # Disabled to prevent startup hang


def get_execution_intel() -> ExecutionIntelligence:
    """Get or create the singleton ExecutionIntelligence."""
    global _intel
    if _intel is None:
        if _intel_lock is not None:
            with _intel_lock:
                if _intel is None:
                    _intel = ExecutionIntelligence()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _intel = ExecutionIntelligence()
    return _intel
