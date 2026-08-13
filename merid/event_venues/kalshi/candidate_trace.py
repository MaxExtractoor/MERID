"""
End-to-end candidate tracing for probability and edge consistency validation.

This module provides immutable trace records that capture the complete lifecycle
of a trading candidate from signal generation through execution. The trace ensures
that probability interpretations, edge calculations, and economics mode remain
consistent across all stages.

Key invariants enforced:
- signal_model_prob_no + canonical_yes_prob == 1.0 for NO-side candidates
- policy_intended_role determines economics mode unless explicitly overridden
- executable_edge computed from same side basis as signal layer
- Every candidate has exactly one terminal state
- Ledger is replayable into same counters every time
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from uuid import uuid4


class TerminalState(Enum):
    """Terminal states for a candidate lifecycle."""
    SIGNAL_GENERATED = "signal_generated"
    ALLOCATOR_REJECTED = "allocator_rejected"
    PARITY_REJECTED = "parity_rejected"
    MICROSTRUCTURE_REJECTED = "microstructure_rejected"
    RISK_REJECTED = "risk_rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class EconomicsMode(Enum):
    """Economics mode for order execution."""
    MAKER = "maker"  # Limit order: no fee, capture spread
    TAKER = "taker"  # Market order: pay fee, cross spread
    UNKNOWN = "unknown"


class Side(Enum):
    """Trading side."""
    YES = "yes"
    NO = "no"


@dataclass(frozen=True)
class CandidateTrace:
    """
    Immutable trace record for a trading candidate lifecycle.

    This dataclass captures the complete state of a candidate at each stage,
    enabling end-to-end validation of probability and edge consistency.
    """
    # Immutable identifier
    candidate_id: str = field(default_factory=lambda: str(uuid4()))

    # Signal generation stage
    signal_timestamp: Optional[float] = None
    signal_model_prob: Optional[float] = None  # Raw probability from signal layer
    signal_side: Optional[Side] = None  # Side from signal (YES/NO)
    signal_edge_pct: Optional[float] = None  # Edge percentage from signal

    # Canonical probability conversion
    canonical_yes_prob: Optional[float] = None  # YES-space probability (router canonical)
    canonical_no_prob: Optional[float] = None  # NO-space probability (for logging)

    # Allocator/gate stage
    allocator_timestamp: Optional[float] = None
    chosen_side: Optional[Side] = None  # Final side after dual-side selection
    chosen_edge_pct: Optional[float] = None  # Final edge after selection

    # Policy/economics stage
    policy_timestamp: Optional[float] = None
    policy_intended_role: Optional[str] = None  # "maker" or "taker" from policy engine
    economics_mode: Optional[EconomicsMode] = None  # Actual economics mode used
    aggressiveness: Optional[float] = None  # Aggressiveness parameter

    # Microstructure stage
    microstructure_timestamp: Optional[float] = None
    yes_bid_cents: Optional[int] = None
    no_bid_cents: Optional[int] = None
    order_price_cents: Optional[float] = None
    spread_cents: Optional[int] = None
    fee_cents: Optional[float] = None
    raw_edge_cents: Optional[float] = None  # Edge before costs
    executable_edge_cents: Optional[float] = None  # Edge after costs

    # Router/execution stage
    router_timestamp: Optional[float] = None
    execution_timestamp: Optional[float] = None

    # Terminal state
    terminal_state: Optional[TerminalState] = None
    terminal_reason: Optional[str] = None  # Reason for rejection or execution details

    # Metadata
    ticker: Optional[str] = None
    asset: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate_invariants(self) -> list[str]:
        """
        Validate key invariants for this trace.

        Returns:
            List of invariant violation messages (empty if all pass)
        """
        violations = []

        # Invariant 1: Probability duality for NO-side candidates
        if self.signal_side == Side.NO and self.signal_model_prob is not None and self.canonical_yes_prob is not None:
            # For NO orders: signal_model_prob is NO outcome prob, canonical_yes_prob is YES outcome prob
            # They should sum to 1.0
            if not (0.99 <= (self.signal_model_prob + self.canonical_yes_prob) <= 1.01):
                violations.append(
                    f"Probability duality violation: signal_model_prob ({self.signal_model_prob}) + "
                    f"canonical_yes_prob ({self.canonical_yes_prob}) != 1.0 for NO-side candidate"
                )

        # Invariant 2: Policy role determines economics mode
        if self.policy_intended_role and self.economics_mode:
            policy_role = self.policy_intended_role.lower()
            if policy_role == "maker" and self.economics_mode != EconomicsMode.MAKER:
                violations.append(
                    f"Policy-economics mismatch: policy says maker but economics mode is {self.economics_mode.value}"
                )
            elif policy_role == "taker" and self.economics_mode != EconomicsMode.TAKER:
                violations.append(
                    f"Policy-economics mismatch: policy says taker but economics mode is {self.economics_mode.value}"
                )

        # Invariant 3: Executable edge sign consistency
        if self.raw_edge_cents is not None and self.executable_edge_cents is not None:
            # For maker economics: executable_edge should equal raw_edge (no costs)
            # For taker economics: executable_edge should be <= raw_edge (after costs)
            if self.economics_mode == EconomicsMode.MAKER:
                if abs(self.executable_edge_cents - self.raw_edge_cents) > 0.01:
                    violations.append(
                        f"Maker economics edge mismatch: executable_edge ({self.executable_edge_cents}) "
                        f"should equal raw_edge ({self.raw_edge_cents})"
                    )
            elif self.economics_mode == EconomicsMode.TAKER:
                if self.executable_edge_cents > self.raw_edge_cents + 0.01:
                    violations.append(
                        f"Taker economics edge violation: executable_edge ({self.executable_edge_cents}) "
                        f"should be <= raw_edge ({self.raw_edge_cents})"
                    )

        # Invariant 4: Terminal state is set
        if self.terminal_state is None:
            violations.append("Missing terminal state")

        # Invariant 5: Executable ask-side liquidity must be recorded when
        # the producer has started populating liquidity metadata.  This keeps
        # legacy traces (with empty metadata) passing while catching partial or
        # invalid ask-size records from new producers.
        if "yes_ask_size" in self.metadata or "no_ask_size" in self.metadata:
            yes_ask_size = self.metadata.get("yes_ask_size")
            no_ask_size = self.metadata.get("no_ask_size")
            if yes_ask_size is None or no_ask_size is None:
                violations.append("Missing executable ask sizes in trace metadata")
            else:
                if not isinstance(yes_ask_size, int) or yes_ask_size < 0:
                    violations.append(f"Invalid yes_ask_size: {yes_ask_size}")
                if not isinstance(no_ask_size, int) or no_ask_size < 0:
                    violations.append(f"Invalid no_ask_size: {no_ask_size}")

        return violations

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary for logging/serialization."""
        return {
            "candidate_id": self.candidate_id,
            "signal_timestamp": self.signal_timestamp,
            "signal_model_prob": self.signal_model_prob,
            "signal_side": self.signal_side.value if self.signal_side else None,
            "signal_edge_pct": self.signal_edge_pct,
            "canonical_yes_prob": self.canonical_yes_prob,
            "canonical_no_prob": self.canonical_no_prob,
            "allocator_timestamp": self.allocator_timestamp,
            "chosen_side": self.chosen_side.value if self.chosen_side else None,
            "chosen_edge_pct": self.chosen_edge_pct,
            "policy_timestamp": self.policy_timestamp,
            "policy_intended_role": self.policy_intended_role,
            "economics_mode": self.economics_mode.value if self.economics_mode else None,
            "aggressiveness": self.aggressiveness,
            "microstructure_timestamp": self.microstructure_timestamp,
            "yes_bid_cents": self.yes_bid_cents,
            "no_bid_cents": self.no_bid_cents,
            "order_price_cents": self.order_price_cents,
            "spread_cents": self.spread_cents,
            "fee_cents": self.fee_cents,
            "raw_edge_cents": self.raw_edge_cents,
            "executable_edge_cents": self.executable_edge_cents,
            "router_timestamp": self.router_timestamp,
            "execution_timestamp": self.execution_timestamp,
            "terminal_state": self.terminal_state.value if self.terminal_state else None,
            "terminal_reason": self.terminal_reason,
            "ticker": self.ticker,
            "asset": self.asset,
            "metadata": self.metadata,
        }


class CandidateTraceStore:
    """
    In-memory store for candidate traces.

    This store enables batch-level reconciliation and post-mortem analysis
    of candidate lifecycles.
    """

    def __init__(self):
        self._traces: Dict[str, CandidateTrace] = {}

    def add_trace(self, trace: CandidateTrace) -> None:
        """Add or update a trace record."""
        self._traces[trace.candidate_id] = trace

    def get_trace(self, candidate_id: str) -> Optional[CandidateTrace]:
        """Get a trace record by candidate_id."""
        return self._traces.get(candidate_id)

    def get_all_traces(self) -> list[CandidateTrace]:
        """Get all trace records."""
        return list(self._traces.values())

    def get_traces_by_ticker(self, ticker: str) -> list[CandidateTrace]:
        """Get all traces for a specific ticker."""
        return [t for t in self._traces.values() if t.ticker == ticker]

    def get_traces_by_terminal_state(self, state: TerminalState) -> list[CandidateTrace]:
        """Get all traces with a specific terminal state."""
        return [t for t in self._traces.values() if t.terminal_state == state]

    def reconcile_counters(self) -> Dict[str, int]:
        """
        Reconcile counters from trace records.

        Returns:
            Dictionary mapping terminal states to counts
        """
        counters = {state.value: 0 for state in TerminalState}
        for trace in self._traces.values():
            if trace.terminal_state:
                counters[trace.terminal_state.value] += 1
        return counters

    def validate_all_invariants(self) -> Dict[str, list[str]]:
        """
        Validate invariants for all traces.

        Returns:
            Dictionary mapping candidate_id to list of violations
        """
        violations = {}
        for candidate_id, trace in self._traces.items():
            trace_violations = trace.validate_invariants()
            if trace_violations:
                violations[candidate_id] = trace_violations
        return violations

    def clear(self) -> None:
        """Clear all trace records."""
        self._traces.clear()


# Global trace store instance
_trace_store = CandidateTraceStore()


def get_trace_store() -> CandidateTraceStore:
    """Get the global trace store instance."""
    return _trace_store
