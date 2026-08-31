"""Rejection counterfactual logger for the 15m trade-decision path.

Every candidate that is rejected by an economic gate (edge threshold, cost
basis floor, pi* EV gate, held-price floor) is appended as a JSONL record to
``logs/rejected_candidates.jsonl``.  A post-settlement join script
(``scripts/rejection_counterfactual_report.py``) matches each record to the
market's realized outcome and classifies the rejection as:

- ``saved``   - the trade would have lost money (correct rejection)
- ``missed``  - the trade would have been net profitable (wrong rejection)
- ``flat``    - counterfactual P&L within +/-1c of zero
- ``unclassifiable`` - no settlement outcome found for the ticker

This is deliberately write-only and exception-safe: a logging failure must
never alter or delay a trading decision.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.rejection_counterfactual")

_DEFAULT_PATH = os.path.join("logs", "rejected_candidates.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get("MERID_REJECTION_COUNTERFACTUAL_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Only economic rejections are interesting for counterfactual analysis.
# Infrastructure rejections (no market, stale data, halted reconciliation)
# carry no signal about threshold calibration.
_COUNTERFACTUAL_REASON_PREFIXES = (
    "yes_edge_below_threshold",
    "no_edge_below_threshold",
    "cost_basis_override_",
    "p_selected_below_pi_star",
    "held_entry_price_below_floor",
)


def should_log(reason: Optional[str]) -> bool:
    if not reason:
        return False
    return any(reason.startswith(p) for p in _COUNTERFACTUAL_REASON_PREFIXES)


def log_rejected_candidate(
    *,
    reason: str,
    run_id: str,
    decision_id: str,
    asset: str,
    ticker: Optional[str],
    side: Optional[str],
    model_p_selected: Optional[float],
    held_price_cents: Optional[float],
    gross_edge: Optional[float],
    net_edge: Optional[float],
    edge_threshold: Optional[float] = None,
    pi_star: Optional[float] = None,
    min_p_selected: Optional[float] = None,
    tte_seconds: Optional[float] = None,
    spot_price: Optional[float] = None,
    strike_price: Optional[float] = None,
    fee_cents: Optional[float] = None,
) -> None:
    """Append one rejected-candidate record.  Never raises."""
    if not _ENABLED or not should_log(reason):
        return
    try:
        record = {
            "type": "rejected_candidate",
            "schema_version": 1,
            "event_ts_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "decision_id": decision_id,
            "asset": asset,
            "ticker": ticker,
            "side": side,
            "model_p_selected": model_p_selected,
            "held_price_cents": held_price_cents,
            "gross_edge": gross_edge,
            "net_edge": net_edge,
            "edge_threshold": edge_threshold,
            "pi_star": pi_star,
            "min_p_selected": min_p_selected,
            "tte_seconds": tte_seconds,
            "spot_price": spot_price,
            "strike_price": strike_price,
            "fee_cents": fee_cents,
            "reject_reason": reason,
        }
        path = os.environ.get("MERID_REJECTED_CANDIDATES_LOG", _DEFAULT_PATH)
        line = json.dumps(record, default=str)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[REJECTED-CANDIDATE] failed to write record: %s", e)
