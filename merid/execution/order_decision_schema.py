"""Common schema for the order decision ledger and executable-cost EV gate.

An :class:`OrderDecisionRecord` is the single durable record of a trading
decision from decision time through all fills, markouts, and exits.  It is
written before any order is submitted and is appended (not overwritten) as the
trade lifecycle progresses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional


@dataclass
class ExitEvent:
    """One realized or attempted exit for a decision."""

    exit_at: datetime
    reason: str
    order_id: Optional[str] = None
    exit_price_cents: Optional[int] = None
    qty_cc: Optional[int] = None
    realized_pnl_cents: Optional[int] = None
    stop_candidate_id: Optional[str] = None
    exit_latency_ms: Optional[float] = None


@dataclass
class FillEvent:
    """One fill for a decision."""

    fill_id: str
    fill_at: datetime
    side: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    qty_cc: int
    price_cents: int
    fee_cents: int
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class MarkoutEvent:
    """A markout observation at a fixed horizon after the decision."""

    horizon_s: int
    observed_at: datetime
    mid_cents: Optional[int] = None
    own_side_bid_cents: Optional[int] = None
    own_side_ask_cents: Optional[int] = None
    pnl_cents: Optional[int] = None


@dataclass
class OrderDecisionRecord:
    """Canonical decision-time record for one trading decision.

    This record is created before any order is submitted and is mutated
    (append-only for sub-events) as fills, markouts, and exits arrive.
    """

    # Identity
    decision_id: str
    run_id: str
    process_id: Optional[str] = None
    timestamp_utc: Optional[datetime] = None

    # Market / settlement
    ticker: str = ""
    asset: str = ""
    settlement_reference: str = "unknown"
    spot_price: Optional[Decimal] = None
    strike_price: Optional[Decimal] = None
    seconds_to_expiry: Optional[Decimal] = None
    market_implied_probability: Optional[Decimal] = None

    # Probability / model
    p_yes_raw: Optional[Decimal] = None
    p_yes_calibrated: Optional[Decimal] = None
    p_yes_uncertainty: Optional[Decimal] = None
    p_no_calibrated: Optional[Decimal] = None
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None
    calibration_version: str = "unknown"
    model_version: str = "unknown"
    data_state: str = "unknown"
    regime_label: str = "unknown"

    # Executable economics
    selected_side: Optional[Literal["yes", "no"]] = None
    executable_price_cents: Optional[int] = None
    executable_price_age_ms: Optional[int] = None
    executable_price_stale: bool = False
    book_snapshot_id: Optional[str] = None
    l2_book: Optional[Dict[str, Any]] = None
    entry_fee_per_contract: Decimal = Decimal("0")
    expected_exit_cost_per_contract: Decimal = Decimal("0")

    # EV decomposition
    gross_ev: Decimal = Decimal("0")
    expected_entry_fee: Decimal = Decimal("0")
    expected_exit_cost: Decimal = Decimal("0")
    adverse_selection_reserve: Decimal = Decimal("0")
    uncertainty_reserve: Decimal = Decimal("0")
    net_ev: Decimal = Decimal("0")
    tail_risk: Decimal = Decimal("0")
    ev_to_tail_ratio: Optional[Decimal] = None
    min_dollar_ev: Decimal = Decimal("0")
    min_ev_to_tail_ratio: Decimal = Decimal("0")

    # Features
    features: Dict[str, Any] = field(default_factory=dict)
    feature_versions: Dict[str, str] = field(default_factory=dict)
    signal_source: str = "unknown"

    # Execution
    entry_mode: Literal["passive", "aggressive", "unknown"] = "unknown"
    submitted_price_cents: Optional[int] = None
    intended_qty_cc: Optional[int] = None
    filled_qty_cc: Optional[int] = None
    fill_latency_ms: Optional[float] = None
    order_status: str = "decided"

    # Lifecycle events
    fills: List[FillEvent] = field(default_factory=list)
    markouts: List[MarkoutEvent] = field(default_factory=list)
    exits: List[ExitEvent] = field(default_factory=list)

    # Markout P&L (pre-computed)
    markout_pnl_1s: Optional[Decimal] = None
    markout_pnl_5s: Optional[Decimal] = None
    markout_pnl_15s: Optional[Decimal] = None
    markout_pnl_30s: Optional[Decimal] = None
    markout_pnl_60s: Optional[Decimal] = None
    markout_pnl_exit: Optional[Decimal] = None
    realized_pnl_cents: Optional[int] = None

    # Provenance
    intent_id: Optional[str] = None
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
    parent_decision_id: Optional[str] = None
    stop_candidate_id: Optional[str] = None
    entry_fill_id: Optional[str] = None
    config_hash: Optional[str] = None
    build_sha: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "process_id": self.process_id,
            "timestamp_utc": self.timestamp_utc.isoformat() if self.timestamp_utc else None,
            "ticker": self.ticker,
            "asset": self.asset,
            "settlement_reference": self.settlement_reference,
            "spot_price": str(self.spot_price) if self.spot_price is not None else None,
            "strike_price": str(self.strike_price) if self.strike_price is not None else None,
            "seconds_to_expiry": str(self.seconds_to_expiry) if self.seconds_to_expiry is not None else None,
            "market_implied_probability": str(self.market_implied_probability) if self.market_implied_probability is not None else None,
            "p_yes_raw": str(self.p_yes_raw) if self.p_yes_raw is not None else None,
            "p_yes_calibrated": str(self.p_yes_calibrated) if self.p_yes_calibrated is not None else None,
            "p_yes_uncertainty": str(self.p_yes_uncertainty) if self.p_yes_uncertainty is not None else None,
            "p_no_calibrated": str(self.p_no_calibrated) if self.p_no_calibrated is not None else None,
            "p_selected": str(self.p_selected) if self.p_selected is not None else None,
            "p_opposite": str(self.p_opposite) if self.p_opposite is not None else None,
            "calibration_version": self.calibration_version,
            "model_version": self.model_version,
            "data_state": self.data_state,
            "regime_label": self.regime_label,
            "selected_side": self.selected_side,
            "executable_price_cents": self.executable_price_cents,
            "executable_price_age_ms": self.executable_price_age_ms,
            "executable_price_stale": self.executable_price_stale,
            "book_snapshot_id": self.book_snapshot_id,
            "l2_book": self.l2_book,
            "entry_fee_per_contract": str(self.entry_fee_per_contract),
            "expected_exit_cost_per_contract": str(self.expected_exit_cost_per_contract),
            "gross_ev": str(self.gross_ev),
            "expected_entry_fee": str(self.expected_entry_fee),
            "expected_exit_cost": str(self.expected_exit_cost),
            "adverse_selection_reserve": str(self.adverse_selection_reserve),
            "uncertainty_reserve": str(self.uncertainty_reserve),
            "net_ev": str(self.net_ev),
            "tail_risk": str(self.tail_risk),
            "ev_to_tail_ratio": str(self.ev_to_tail_ratio) if self.ev_to_tail_ratio is not None else None,
            "min_dollar_ev": str(self.min_dollar_ev),
            "min_ev_to_tail_ratio": str(self.min_ev_to_tail_ratio),
            "features": self.features,
            "feature_versions": self.feature_versions,
            "signal_source": self.signal_source,
            "entry_mode": self.entry_mode,
            "submitted_price_cents": self.submitted_price_cents,
            "intended_qty_cc": self.intended_qty_cc,
            "filled_qty_cc": self.filled_qty_cc,
            "fill_latency_ms": self.fill_latency_ms,
            "order_status": self.order_status,
            "fills": [self._fill_to_dict(f) for f in self.fills],
            "markouts": [self._markout_to_dict(m) for m in self.markouts],
            "exits": [self._exit_to_dict(e) for e in self.exits],
            "markout_pnl_1s": str(self.markout_pnl_1s) if self.markout_pnl_1s is not None else None,
            "markout_pnl_5s": str(self.markout_pnl_5s) if self.markout_pnl_5s is not None else None,
            "markout_pnl_15s": str(self.markout_pnl_15s) if self.markout_pnl_15s is not None else None,
            "markout_pnl_30s": str(self.markout_pnl_30s) if self.markout_pnl_30s is not None else None,
            "markout_pnl_60s": str(self.markout_pnl_60s) if self.markout_pnl_60s is not None else None,
            "markout_pnl_exit": str(self.markout_pnl_exit) if self.markout_pnl_exit is not None else None,
            "realized_pnl_cents": self.realized_pnl_cents,
            "intent_id": self.intent_id,
            "client_order_id": self.client_order_id,
            "order_id": self.order_id,
            "parent_decision_id": self.parent_decision_id,
            "stop_candidate_id": self.stop_candidate_id,
            "entry_fill_id": self.entry_fill_id,
            "config_hash": self.config_hash,
            "build_sha": self.build_sha,
        }

    @staticmethod
    def _fill_to_dict(f: FillEvent) -> Dict[str, Any]:
        return {
            "fill_id": f.fill_id,
            "fill_at": f.fill_at.isoformat(),
            "side": f.side,
            "action": f.action,
            "qty_cc": f.qty_cc,
            "price_cents": f.price_cents,
            "fee_cents": f.fee_cents,
            "order_id": f.order_id,
            "client_order_id": f.client_order_id,
            "latency_ms": f.latency_ms,
        }

    @staticmethod
    def _markout_to_dict(m: MarkoutEvent) -> Dict[str, Any]:
        return {
            "horizon_s": m.horizon_s,
            "observed_at": m.observed_at.isoformat(),
            "mid_cents": m.mid_cents,
            "own_side_bid_cents": m.own_side_bid_cents,
            "own_side_ask_cents": m.own_side_ask_cents,
            "pnl_cents": m.pnl_cents,
        }

    @staticmethod
    def _exit_to_dict(e: ExitEvent) -> Dict[str, Any]:
        return {
            "exit_at": e.exit_at.isoformat(),
            "reason": e.reason,
            "order_id": e.order_id,
            "exit_price_cents": e.exit_price_cents,
            "qty_cc": e.qty_cc,
            "realized_pnl_cents": e.realized_pnl_cents,
            "stop_candidate_id": e.stop_candidate_id,
            "exit_latency_ms": e.exit_latency_ms,
        }
