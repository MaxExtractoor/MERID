"""
Exit audit DTOs.

Provides a structured, immutable record for every exit decision so that
an observed fill (e.g. BUY_YES 50c -> SELL_YES 42c) can be reconciled
with the exact price snapshot and trigger that produced it, rather than
inferred from the fill price after the fact.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from merid.position_management.position import PositionSide
from merid.position_management.exit_policy import ExitReason


@dataclass
class ExitPriceSnapshot:
    """
    Executable same-side book snapshot used for exit decisions.

    A position is always long its own side.  The liquidation value is the
    best bid on that side (what we can actually sell at), not the mid or
    the opposite-side price.
    """

    market_id: str
    position_side: PositionSide
    mid_cents: int
    own_side_bid_cents: int
    own_side_ask_cents: int
    opposite_bid_cents: Optional[int]
    opposite_ask_cents: Optional[int]
    book_age_ms: int
    data_source: str
    data_quality: str
    executable: bool
    has_bid_size: bool
    snapshot_id: str
    timestamp: float = field(default_factory=time.monotonic)
    min_depth_own_side: int = 0
    seconds_to_expiry: Optional[float] = None
    # CRITICAL FIX (2026-08-10): Full book provenance for exit attribution
    book_sequence: Optional[int] = None
    yes_bid_cents: Optional[int] = None
    yes_ask_cents: Optional[int] = None
    no_bid_cents: Optional[int] = None
    no_ask_cents: Optional[int] = None
    yes_depth: Optional[int] = None
    no_depth: Optional[int] = None
    entry_side_executable_bid_cents: Optional[int] = None
    entry_side_executable_ask_cents: Optional[int] = None

    def is_fresh(self, max_age_ms: int = 10_000) -> bool:
        """Return True if the book is within the freshness window."""
        return self.book_age_ms <= max_age_ms

    def is_executable_for_exit(self) -> bool:
        """Return True only when the snapshot is trusted for an exit decision."""
        return (
            self.executable
            and self.has_bid_size
            and 0 < self.own_side_bid_cents < 100
            and 0 < self.own_side_ask_cents < 100
            and self.data_quality == "GOOD"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for logs/records."""
        d = asdict(self)
        d["position_side"] = (
            self.position_side.value
            if isinstance(self.position_side, PositionSide)
            else str(self.position_side)
        )
        return d


@dataclass
class ExitDecisionRecord:
    """
    Immutable audit record for one exit decision.

    Filled by PositionMonitor at the moment a trigger is chosen and emitted
    as an `[EXIT-DECISION]` structured log line.  It is not modified by the
    downstream order/fill path; the fill path should emit a separate
    `[EXIT-FILL]` record that references this `decision_id`.
    """

    decision_id: str
    position_key: str
    market_ticker: str
    position_side: str

    entry_order_id: Optional[str] = None
    entry_fill_id: Optional[str] = None
    signal_id: Optional[str] = None
    entry_model: Optional[str] = None
    model_version: Optional[str] = None

    entry_price_cents: int = 0
    entry_tp_cents: Optional[int] = None
    entry_sl_cents: Optional[int] = None
    entry_trail_distance_cents: Optional[int] = None
    entry_trail_activation_cents: Optional[int] = None
    edge_at_entry_pct: float = 0.0
    vol_regime: str = "unknown"
    confidence: str = "unknown"
    size: int = 0

    trigger_time: str = ""
    trigger_reason: str = ""
    trigger_price_source: str = ""
    trigger_mid_cents: int = 0
    trigger_executable_bid_cents: int = 0
    trigger_executable_ask_cents: int = 0
    trigger_opposite_bid_cents: Optional[int] = None
    trigger_opposite_ask_cents: Optional[int] = None
    # CRITICAL FIX (2026-08-10): Full book provenance for exit attribution
    trigger_book_sequence: Optional[int] = None
    trigger_yes_bid_cents: Optional[int] = None
    trigger_yes_ask_cents: Optional[int] = None
    trigger_no_bid_cents: Optional[int] = None
    trigger_no_ask_cents: Optional[int] = None
    trigger_yes_depth: Optional[int] = None
    trigger_no_depth: Optional[int] = None
    trigger_entry_side_executable_bid_cents: Optional[int] = None
    trigger_entry_side_executable_ask_cents: Optional[int] = None
    trigger_book_age_ms: int = 0
    trigger_book_snapshot_id: str = ""
    trigger_data_source: str = ""
    trigger_data_quality: str = ""

    seconds_held: float = 0.0
    high_watermark_cents: int = 0
    low_watermark_cents: int = 0
    current_price_cents: int = 0
    pnl_unrealized_cents: int = 0
    r_multiple: float = 0.0

    trailing_stop_level_cents: Optional[int] = None
    stop_loss_level_cents: Optional[int] = None  # soft trigger level
    hard_stop_level_cents: Optional[int] = None  # emergency liquidation level
    take_profit_level_cents: Optional[int] = None
    dynamic_tp_target_cents: Optional[int] = None

    chosen_exit_reason: str = ""
    chosen_exit_priority: int = 0
    chosen_exit_price_cents: int = 0
    eligible_exit_reasons: List[str] = field(default_factory=list)
    suppressed_exit_reasons: List[str] = field(default_factory=list)

    order_intent_id: Optional[str] = None
    order_client_order_id: Optional[str] = None
    order_exchange_id: Optional[str] = None
    order_price_cents: Optional[int] = None
    fill_price_cents: Optional[int] = None
    fill_id: Optional[str] = None

    decision_status: str = "CHOSEN"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_log_line(self) -> str:
        """Render as a single `[EXIT-DECISION]` log line."""
        fields = {
            "decision_id": self.decision_id,
            "position_key": self.position_key,
            "market_ticker": self.market_ticker,
            "position_side": self.position_side,
            "entry_order_id": self.entry_order_id or "n/a",
            "entry_fill_id": self.entry_fill_id or "n/a",
            "signal_id": self.signal_id or "n/a",
            "entry_model": self.entry_model or "n/a",
            "model_version": self.model_version or "n/a",
            "entry_price_cents": self.entry_price_cents,
            "entry_tp_cents": self.entry_tp_cents if self.entry_tp_cents is not None else "n/a",
            "entry_sl_cents": self.entry_sl_cents if self.entry_sl_cents is not None else "n/a",
            "entry_trail_distance_cents": self.entry_trail_distance_cents if self.entry_trail_distance_cents is not None else "n/a",
            "entry_trail_activation_cents": self.entry_trail_activation_cents if self.entry_trail_activation_cents is not None else "n/a",
            "edge_at_entry_pct": f"{self.edge_at_entry_pct:.6f}",
            "vol_regime": self.vol_regime,
            "confidence": self.confidence,
            "size": self.size,
            "trigger_time": self.trigger_time,
            "trigger_reason": self.trigger_reason,
            "trigger_price_source": self.trigger_price_source,
            "trigger_mid_cents": self.trigger_mid_cents,
            "trigger_executable_bid_cents": self.trigger_executable_bid_cents,
            "trigger_executable_ask_cents": self.trigger_executable_ask_cents,
            "trigger_opposite_bid_cents": self.trigger_opposite_bid_cents if self.trigger_opposite_bid_cents is not None else "n/a",
            "trigger_opposite_ask_cents": self.trigger_opposite_ask_cents if self.trigger_opposite_ask_cents is not None else "n/a",
            "trigger_book_age_ms": self.trigger_book_age_ms,
            "trigger_book_snapshot_id": self.trigger_book_snapshot_id,
            "trigger_book_sequence": self.trigger_book_sequence if self.trigger_book_sequence is not None else "n/a",
            "trigger_yes_bid_cents": self.trigger_yes_bid_cents if self.trigger_yes_bid_cents is not None else "n/a",
            "trigger_yes_ask_cents": self.trigger_yes_ask_cents if self.trigger_yes_ask_cents is not None else "n/a",
            "trigger_no_bid_cents": self.trigger_no_bid_cents if self.trigger_no_bid_cents is not None else "n/a",
            "trigger_no_ask_cents": self.trigger_no_ask_cents if self.trigger_no_ask_cents is not None else "n/a",
            "trigger_yes_depth": self.trigger_yes_depth if self.trigger_yes_depth is not None else "n/a",
            "trigger_no_depth": self.trigger_no_depth if self.trigger_no_depth is not None else "n/a",
            "trigger_entry_side_executable_bid_cents": self.trigger_entry_side_executable_bid_cents if self.trigger_entry_side_executable_bid_cents is not None else "n/a",
            "trigger_entry_side_executable_ask_cents": self.trigger_entry_side_executable_ask_cents if self.trigger_entry_side_executable_ask_cents is not None else "n/a",
            "trigger_data_source": self.trigger_data_source,
            "trigger_data_quality": self.trigger_data_quality,
            "seconds_held": f"{self.seconds_held:.3f}",
            "high_watermark_cents": self.high_watermark_cents,
            "low_watermark_cents": self.low_watermark_cents,
            "current_price_cents": self.current_price_cents,
            "pnl_unrealized_cents": self.pnl_unrealized_cents,
            "r_multiple": f"{self.r_multiple:.4f}",
            "trailing_stop_level_cents": self.trailing_stop_level_cents if self.trailing_stop_level_cents is not None else "n/a",
            "stop_loss_level_cents": self.stop_loss_level_cents if self.stop_loss_level_cents is not None else "n/a",
            "hard_stop_level_cents": self.hard_stop_level_cents if self.hard_stop_level_cents is not None else "n/a",
            "take_profit_level_cents": self.take_profit_level_cents if self.take_profit_level_cents is not None else "n/a",
            "dynamic_tp_target_cents": self.dynamic_tp_target_cents if self.dynamic_tp_target_cents is not None else "n/a",
            "chosen_exit_reason": self.chosen_exit_reason,
            "chosen_exit_priority": self.chosen_exit_priority,
            "chosen_exit_price_cents": self.chosen_exit_price_cents,
            "eligible_exit_reasons": ",".join(self.eligible_exit_reasons) if self.eligible_exit_reasons else "n/a",
            "suppressed_exit_reasons": ",".join(self.suppressed_exit_reasons) if self.suppressed_exit_reasons else "n/a",
            "order_intent_id": self.order_intent_id or "n/a",
            "order_client_order_id": self.order_client_order_id or "n/a",
            "order_exchange_id": self.order_exchange_id or "n/a",
            "order_price_cents": self.order_price_cents if self.order_price_cents is not None else "n/a",
            "fill_price_cents": self.fill_price_cents if self.fill_price_cents is not None else "n/a",
            "fill_id": self.fill_id or "n/a",
            "decision_status": self.decision_status,
        }
        # Merge metadata at the end so extra context never overwrites core fields
        for k, v in self.metadata.items():
            if k not in fields:
                fields[k] = v
        return "[EXIT-DECISION] " + " ".join(f"{k}={v}" for k, v in fields.items())
