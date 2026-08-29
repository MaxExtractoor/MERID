"""Order decision ledger: durable, append-only record of every trade decision.

The ledger is written before an order is submitted (the decision-time snapshot)
and is appended to as the order is submitted, filled, marked out, and exited.
The event log is JSONL under ``logs/order_decisions/`` and is fsync'd before
returning so the record survives a process crash.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from merid.config.live_config import get_resolved_live_config
from merid.execution.order_decision_schema import (
    ExitEvent,
    FillEvent,
    MarkoutEvent,
    OrderDecisionRecord,
)

logger = get_logger("merid.execution.order_decision_ledger")


# fsync'd append lock.
_ledger_lock = threading.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _default_log_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "logs" / "order_decisions"


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


class OrderDecisionLedger:
    """In-memory index + durable JSONL event log for order decisions."""

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self.log_dir = log_dir or _default_log_dir()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, OrderDecisionRecord] = {}
        self._log_file = self.log_dir / "order_decisions.jsonl"

    def start(self, record: OrderDecisionRecord) -> None:
        """Write the initial decision-time snapshot.

        Raises ``ValueError`` if the decision_id already exists in this
        process, because every decision must have a single originating record.
        """
        if record.decision_id in self._records:
            raise ValueError(f"decision_id {record.decision_id} already started")

        if record.timestamp_utc is None:
            record.timestamp_utc = _now_utc()

        # Resolve the current live config and build SHA if not already set.
        try:
            resolved = get_resolved_live_config(allow_unresolved=True)
            if resolved and resolved.resolved:
                if record.config_hash is None:
                    record.config_hash = resolved.config_hash
                if record.build_sha is None:
                    record.build_sha = resolved.config_hash
        except Exception:
            pass

        self._records[record.decision_id] = record
        self._append_event(record.decision_id, "start", record.to_dict())

    def record_submission(
        self,
        decision_id: str,
        *,
        entry_mode: str = "unknown",
        submitted_price_cents: Optional[int] = None,
        intended_qty_cc: Optional[int] = None,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> None:
        """Append an order submission to the decision record."""
        record = self._get_record(decision_id)
        if entry_mode:
            record.entry_mode = entry_mode  # type: ignore[assignment]
        if submitted_price_cents is not None:
            record.submitted_price_cents = submitted_price_cents
        if intended_qty_cc is not None:
            record.intended_qty_cc = intended_qty_cc
        if client_order_id is not None:
            record.client_order_id = client_order_id
        if order_id is not None:
            record.order_id = order_id
        if intent_id is not None:
            record.intent_id = intent_id
        record.order_status = "submitted"
        self._append_event(decision_id, "submission", {
            "entry_mode": record.entry_mode,
            "submitted_price_cents": record.submitted_price_cents,
            "intended_qty_cc": record.intended_qty_cc,
            "client_order_id": record.client_order_id,
            "order_id": record.order_id,
            "intent_id": record.intent_id,
            "ts": time.time(),
        })

    def record_fill(self, decision_id: str, fill: FillEvent) -> None:
        """Append a fill to the decision record."""
        record = self._get_record(decision_id)
        record.fills.append(fill)
        record.filled_qty_cc = sum(f.qty_cc for f in record.fills)
        record.fill_latency_ms = fill.latency_ms
        if record.order_status in ("decided", "submitted"):
            record.order_status = "filled"
        if record.client_order_id is None:
            record.client_order_id = fill.client_order_id
        if record.order_id is None:
            record.order_id = fill.order_id
        self._append_event(decision_id, "fill", fill.__dict__)

    def record_markout(self, decision_id: str, markout: MarkoutEvent) -> None:
        """Append a markout observation to the decision record."""
        record = self._get_record(decision_id)
        record.markouts.append(markout)
        horizon = markout.horizon_s
        pnl = _decimal_or_none(markout.pnl_cents)
        if pnl is not None:
            if horizon == 1:
                record.markout_pnl_1s = pnl
            elif horizon == 5:
                record.markout_pnl_5s = pnl
            elif horizon == 15:
                record.markout_pnl_15s = pnl
            elif horizon == 30:
                record.markout_pnl_30s = pnl
            elif horizon == 60:
                record.markout_pnl_60s = pnl
        self._append_event(decision_id, "markout", markout.__dict__)

    def record_exit(
        self,
        decision_id: str,
        exit: ExitEvent,
        *,
        realized_pnl_cents: Optional[int] = None,
    ) -> None:
        """Append an exit to the decision record and update realized P&L."""
        record = self._get_record(decision_id)
        record.exits.append(exit)
        if exit.stop_candidate_id:
            record.stop_candidate_id = exit.stop_candidate_id
        if realized_pnl_cents is not None:
            record.realized_pnl_cents = realized_pnl_cents
            exit.realized_pnl_cents = realized_pnl_cents
        record.order_status = "exited"
        self._append_event(decision_id, "exit", exit.__dict__)

    def get(self, decision_id: str) -> Optional[OrderDecisionRecord]:
        """Return the materialized record for ``decision_id`` if known."""
        return self._records.get(decision_id)

    def _get_record(self, decision_id: str) -> OrderDecisionRecord:
        if decision_id not in self._records:
            raise KeyError(f"decision_id {decision_id} not found; call start() first")
        return self._records[decision_id]

    def _append_event(self, decision_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Persist an append-only ledger event with fsync."""
        line = {
            "decision_id": decision_id,
            "event_type": event_type,
            "ts": time.time(),
            "payload": payload,
        }
        try:
            with _ledger_lock:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(line, default=_json_default, separators=(",", ":")) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
        except Exception as exc:
            logger.warning("[ORDER-DECISION-LEDGER] failed to persist event: %s", exc)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


_ledger_instance: Optional[OrderDecisionLedger] = None


def get_order_decision_ledger(log_dir: Optional[Path] = None) -> OrderDecisionLedger:
    """Return the process-wide order decision ledger singleton."""
    global _ledger_instance
    if _ledger_instance is None:
        _ledger_instance = OrderDecisionLedger(log_dir=log_dir)
    return _ledger_instance


def build_order_decision_record_from_trade_decision(
    decision: "TradeDecision",
    *,
    ev_gate_result: Optional[Dict[str, Any]] = None,
    build_sha: Optional[str] = None,
) -> OrderDecisionRecord:
    """Build an :class:`OrderDecisionRecord` from a :class:`TradeDecision`.

    This is the canonical bridge from the prediction-time decision to the
    execution ledger.  It is evaluated lazily to avoid import cycles.
    """
    from merid.prediction.trade_decision import TradeDecision
    assert isinstance(decision, TradeDecision)

    # Map edge/cost fields to the record's EV decomposition.
    side = decision.selected_outcome
    entry_fee = Decimal("0")
    exit_cost = Decimal("0")
    if side == "yes":
        entry_fee = decision.entry_fee_yes
        exit_cost = decision.exit_cost_reserve_yes
    elif side == "no":
        entry_fee = decision.entry_fee_no
        exit_cost = decision.exit_cost_reserve_no

    executable_price_cents = None
    if decision.selected_outcome_price is not None:
        executable_price_cents = int(decision.selected_outcome_price * Decimal("100"))

    return OrderDecisionRecord(
        decision_id=decision.decision_id,
        run_id=decision.run_id,
        process_id=getattr(decision, "process_id", None),
        timestamp_utc=decision.timestamp_utc,
        ticker=decision.ticker,
        asset=decision.asset,
        settlement_reference=decision.settlement_reference,
        seconds_to_expiry=decision.seconds_to_expiry,
        p_yes_raw=decision.p_yes_raw,
        p_yes_calibrated=decision.p_yes_calibrated,
        p_yes_uncertainty=decision.p_yes_uncertainty,
        p_no_calibrated=decision.p_no_calibrated,
        p_selected=decision.p_selected,
        p_opposite=decision.p_opposite,
        model_version=decision.policy_version,
        data_state=decision.data_state,
        regime_label=decision.regime_label,
        selected_side=side,
        executable_price_cents=executable_price_cents,
        entry_fee_per_contract=entry_fee,
        expected_exit_cost_per_contract=exit_cost,
        adverse_selection_reserve=decision.adverse_selection_reserve,
        uncertainty_reserve=decision.uncertainty_reserve,
        net_ev=Decimal(str(ev_gate_result["net_ev"])) if ev_gate_result else Decimal("0"),
        gross_ev=Decimal(str(ev_gate_result["gross_ev"])) if ev_gate_result else Decimal("0"),
        expected_entry_fee=Decimal(str(ev_gate_result["expected_entry_fee"])) if ev_gate_result else Decimal("0"),
        expected_exit_cost=Decimal(str(ev_gate_result["expected_exit_cost"])) if ev_gate_result else Decimal("0"),
        tail_risk=Decimal(str(ev_gate_result["tail_risk"])) if ev_gate_result else Decimal("0"),
        ev_to_tail_ratio=Decimal(str(ev_gate_result["ev_to_tail_ratio"])) if ev_gate_result and ev_gate_result.get("ev_to_tail_ratio") is not None else None,
        min_dollar_ev=Decimal(str(ev_gate_result["min_dollar_ev"])) if ev_gate_result else Decimal("0"),
        min_ev_to_tail_ratio=Decimal(str(ev_gate_result["min_ev_to_tail_ratio"])) if ev_gate_result else Decimal("0"),
        intended_qty_cc=int(decision.approved_size_cc) if decision.approved_size_cc is not None else None,
        config_hash=decision.config_hash,
        build_sha=build_sha,
    )


def reset_order_decision_ledger(log_dir: Optional[Path] = None) -> OrderDecisionLedger:
    """Reset the singleton; useful for tests and process restarts."""
    global _ledger_instance
    _ledger_instance = OrderDecisionLedger(log_dir=log_dir)
    return _ledger_instance
