"""Read-only per-cycle decision telemetry for the 15m agent grid.

Emits one structured JSONL record per asset per decision cycle, plus a
compact per-cycle DECISION-SCORECARD, so BTC-vs-altcoin selection can be
decomposed offline (calibration, EV-gate economics, allocator losses)
without touching router, ledger, exit, or allocator behavior.

Guardrails:
- Pure instrumentation: no awaits, no network, no trading-state mutation.
- Every failure is non-fatal: one warning (rate-limited) and a counter.
- Sink is the shared utils.jsonl_writer.JsonlWriter (append-only, rotating).
- No credentials, auth headers, or raw API payloads are ever written here.
"""

from __future__ import annotations

import enum
import logging
import math
import os
import threading
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DECISION_TELEMETRY_SCHEMA_VERSION = 1

_DEFAULT_PATH = "logs/decision_telemetry.jsonl"

# Process-level run id: stable for the lifetime of this process so records
# can be correlated across cycles and with downstream order/fill records.
RUN_ID = uuid.uuid4().hex[:12]

_writer = None
_writer_lock = threading.Lock()
_write_failures = 0
_warned_failures = 0


def telemetry_enabled() -> bool:
    return os.environ.get("MERID_DECISION_TELEMETRY", "1") != "0"


def _get_writer():
    global _writer
    if _writer is None:
        with _writer_lock:
            if _writer is None:
                from utils.jsonl_writer import JsonlWriter

                path = os.environ.get("MERID_DECISION_TELEMETRY_PATH", _DEFAULT_PATH)
                _writer = JsonlWriter(path, max_bytes=20_000_000, backup_count=5)
    return _writer


def _reset_writer_for_tests() -> None:
    global _writer, _write_failures, _warned_failures
    with _writer_lock:
        _writer = None
    _write_failures = 0
    _warned_failures = 0


def sanitize(value: Any) -> Any:
    """Convert a value into a JSON-safe form.

    Decimal -> float (exact string preserved when non-finite-safe float
    conversion is impossible), Enum -> its value, datetime/date -> ISO 8601,
    NaN/Infinity -> None. Dicts and lists are sanitized recursively.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return float(value)
    if isinstance(value, enum.Enum):
        return sanitize(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v) for v in value]
    return str(value)


def _classify_rejection(waterfall: Dict[str, Any], rejection_reason: str) -> str:
    """Bucket a rejection into the scorecard categories.

    Returns one of: no_market_data, signal_failure, economics_failure,
    allocator_loss, selected, none.
    """
    stages = waterfall.get("stages", {}) if waterfall else {}
    for stage in ("market_discovered", "spot_price", "market_open"):
        info = stages.get(stage)
        if info is not None and not info.get("status"):
            return "no_market_data"
    if waterfall and waterfall.get("selected"):
        return "selected"
    if not rejection_reason:
        sig = stages.get("signal_generated")
        cand = stages.get("candidate_generated")
        if sig is not None and not sig.get("status"):
            return "signal_failure"
        if cand is not None and not cand.get("status"):
            return "signal_failure"
        return "none"
    economics = {
        "ev_gate_non_positive",
        "ev_extreme_price",
        "kelly_filter",
        "insufficient_edge",
        "final_price_out_of_range",
    }
    if rejection_reason in economics or rejection_reason.startswith("ev_"):
        return "economics_failure"
    if rejection_reason in {"allocator_not_selected", "allocator_loss"}:
        return "allocator_loss"
    no_data = {
        "no_market",
        "market_not_found",
        "stale_spot",
        "stale_market_data",
        "market_closed",
        "no_quotes",
        "insufficient_depth",
    }
    if rejection_reason in no_data or "stale" in rejection_reason or "market" in rejection_reason and "discovered" in rejection_reason:
        return "no_market_data"
    return "signal_failure"


_FUNNEL_STAGES = ("market_discovered", "spot_price", "market_open",
                  "signal_generated", "candidate_generated")


def _terminal_stage(waterfall: Dict[str, Any], candidate: Optional[Dict[str, Any]],
                    allocator_selected: bool, allocator_note: str) -> str:
    """The single funnel stage where this asset's cycle ended.

    Stages are processed in funnel order; only stages actually present in the
    waterfall are tested, so partial waterfalls (e.g. a direct signal failure)
    return the earliest failed stage that was reached.
    """
    if allocator_selected:
        return "selected"
    stages = waterfall.get("stages", {}) if waterfall else {}
    for stage in _FUNNEL_STAGES:
        info = stages.get(stage)
        if info is not None and not info.get("status"):
            return stage
    # All present stages passed; candidate reached allocator
    if candidate is not None:
        return "allocator"
    if allocator_note:
        return allocator_note
    return "no_signal"


def _rejection_chain(waterfall: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ordered list of failed funnel stages with reasons.

    The funnel is sequential, so only the first failed stage is recorded as
    the terminal point; subsequent stages were never reached.
    """
    chain = []
    stages = waterfall.get("stages", {}) if waterfall else {}
    for stage in _FUNNEL_STAGES:
        info = stages.get(stage)
        if info is not None and not info.get("status"):
            chain.append({"stage": stage, "reason": info.get("reason") or ""})
            break
    return chain


def _decision_id(ticker: Optional[str], side: Optional[str]) -> Optional[str]:
    """Stable lifecycle identity for a decision: repeated cycles for the same
    market+side update one logical decision rather than creating new ones.
    None when either identity field is missing (pre-side records)."""
    if not ticker or not side:
        return None
    return f"{str(ticker).strip().upper()}:{str(side).strip().lower()}"


def build_asset_record(
    *,
    cycle_id: int,
    asset: str,
    decision: Dict[str, Any],
    waterfall: Dict[str, Any],
    candidate: Optional[Dict[str, Any]],
    candidate_rank: Optional[int] = None,
    allocator_rank: Optional[int] = None,
    allocator_selected: bool = False,
    allocator_note: str = "",
) -> Dict[str, Any]:
    """Assemble one per-asset per-cycle decision record (schema v1)."""
    rejection_reason = str(decision.get("rejection_reason") or waterfall.get("final_reason") or "")
    _side = decision.get("selected_side") or decision.get("signal_side")
    _ticker = decision.get("ticker") or decision.get("market_id")
    _cid = (candidate or {}).get("candidate_id")
    record = {
        "type": "decision_record",
        "schema_version": DECISION_TELEMETRY_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "event_ts_utc": datetime.utcnow().isoformat() + "Z",
        "cycle_id": cycle_id,
        "asset": asset,
        "config_profile": os.environ.get("MERID_PROFILE", ""),
        # Market / data freshness
        "ticker": _ticker,
        "decision_id": _decision_id(_ticker, _side),
        "candidate_id": _cid,
        "terminal_stage": _terminal_stage(waterfall, candidate, allocator_selected, allocator_note),
        "rejection_chain": _rejection_chain(waterfall),
        "minutes_to_expiry": decision.get("minutes_to_expiry"),
        "market_available": bool((waterfall.get("stages", {}).get("market_discovered") or {}).get("status", False)),
        "market_state_age_ms": decision.get("market_state_age_ms"),
        "spot_age_ms": decision.get("spot_age_ms"),
        "ws_age_ms": decision.get("ws_age_ms"),
        "rest_age_ms": decision.get("rest_age_ms"),
        # Quotes / depth
        "yes_bid_cents": decision.get("yes_bid_cents"),
        "yes_ask_cents": decision.get("yes_ask_cents"),
        "no_bid_cents": decision.get("no_bid_cents"),
        "no_ask_cents": decision.get("no_ask_cents"),
        "yes_depth": decision.get("yes_depth"),
        "no_depth": decision.get("no_depth"),
        # Model vs market
        "selected_side": _side,
        "model_p_yes": decision.get("model_p_yes"),
        "model_p_no": decision.get("model_p_no"),
        "model_prob_selected": decision.get("model_prob"),
        "market_p_selected": decision.get("market_prob"),
        "raw_edge_cents": decision.get("raw_edge_cents"),
        # Economics
        "entry_fee_cents": decision.get("entry_fee_cents"),
        "expected_entry_impact_cents": decision.get("expected_entry_impact_cents"),
        "exit_fee_reserve_cents": decision.get("exit_fee_reserve_cents"),
        "exit_impact_reserve_cents": decision.get("exit_impact_reserve_cents"),
        "uncertainty_buffer_cents": decision.get("uncertainty_buffer_cents"),
        "slippage_guard_cents": decision.get("slippage_guard_cents"),
        "all_in_cost_cents": decision.get("all_in_cost_cents"),
        "robust_ev_cents": decision.get("robust_ev_cents"),
        "ev_net_cents": decision.get("ev_net_cents"),
        "edge_pct": decision.get("edge_pct"),
        "capped_edge_pct": decision.get("capped_edge_pct"),
        # Signal indicators
        "velocity": decision.get("velocity"),
        "velocity_threshold": decision.get("velocity_threshold"),
        "spot_price": decision.get("spot_price"),
        "macd_histogram": decision.get("macd_histogram"),
        "macd_hist_pct": decision.get("macd_hist_pct"),
        "base_edge_yes": decision.get("base_edge_yes"),
        "macd_edge_component_yes": decision.get("macd_edge_component_yes"),
        "edge_yes_pct": decision.get("edge_yes_pct"),
        "base_edge_no": decision.get("base_edge_no"),
        "macd_edge_component_no": decision.get("macd_edge_component_no"),
        "edge_no_pct": decision.get("edge_no_pct"),
        "rsi": decision.get("rsi"),
        "fvg_direction": decision.get("fvg_direction"),
        "fvg_confidence": decision.get("fvg_confidence"),
        "order_book_imbalance": decision.get("order_book_imbalance"),
        # Gate outcomes
        "signal_generated": bool((waterfall.get("stages", {}).get("signal_generated") or {}).get("status", False)),
        "candidate_generated": candidate is not None,
        "rejection_stage": _classify_rejection(waterfall, rejection_reason),
        "rejection_reason": rejection_reason or None,
        "candidate_rank": candidate_rank,
        "allocator_rank": allocator_rank,
        "allocator_selected": allocator_selected,
        "allocator_note": allocator_note or None,
    }
    return sanitize(record)


def format_scorecard(cycle_id: int, records: List[Dict[str, Any]]) -> str:
    """Render the compact per-cycle DECISION-SCORECARD line."""
    parts = [f"DECISION-SCORECARD cycle={cycle_id}"]
    for r in records:
        asset = r.get("asset", "?")
        if r.get("allocator_selected"):
            status = (
                f"PASS | robust_ev={_fmt_ev(r.get('robust_ev_cents'))} "
                f"| rank={r.get('allocator_rank')} | selected"
            )
        elif r.get("candidate_generated") and r.get("rejection_stage") == "allocator_loss":
            status = (
                f"REJECT | allocator_loss | robust_ev={_fmt_ev(r.get('robust_ev_cents'))} "
                f"| candidate_rank={r.get('candidate_rank')}"
            )
        elif not r.get("market_available"):
            status = f"REJECT | {r.get('rejection_stage')} | {r.get('rejection_reason') or 'market_unavailable'}"
        else:
            side = r.get("selected_side") or "-"
            model = r.get("model_prob_selected")
            market = r.get("market_p_selected")
            raw_edge = r.get("raw_edge_cents")
            robust = r.get("robust_ev_cents")
            reason = r.get("rejection_reason") or r.get("rejection_stage") or "no_candidate"
            status = (
                f"REJECT | {reason} | side={side} "
                f"model={_fmt_prob(model)} market={_fmt_prob(market)} "
                f"raw_edge={_fmt_ev(raw_edge)} robust_ev={_fmt_ev(robust)}"
            )
        parts.append(f"{asset}: {status}")
    return "\n".join(parts)


def _fmt_prob(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.0f}c"
    except (TypeError, ValueError):
        return "-"


def _fmt_ev(value: Any) -> str:
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{v:+.0f}c"


def emit_cycle(
    cycle_id: int,
    records: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Write per-asset decision records and the cycle scorecard. Non-fatal.

    Returns True if all writes succeeded. Any failure increments a counter,
    logs a rate-limited warning, and never propagates.
    """
    global _write_failures, _warned_failures
    if not telemetry_enabled():
        return True
    try:
        writer = _get_writer()
        scorecard = format_scorecard(cycle_id, records)
        logger.info("%s", scorecard)
        ok = True
        for record in records:
            ok = writer.append(sanitize(record)) and ok
        scorecard_record = {
            "type": "decision_scorecard",
            "schema_version": DECISION_TELEMETRY_SCHEMA_VERSION,
            "run_id": RUN_ID,
            "event_ts_utc": datetime.utcnow().isoformat() + "Z",
            "cycle_id": cycle_id,
            "scorecard": scorecard,
        }
        if extra:
            scorecard_record.update(sanitize(extra))
        ok = writer.append(scorecard_record) and ok
        if not ok:
            _write_failures += 1
            if _write_failures - _warned_failures >= 1:
                logger.warning(
                    "[DECISION-TELEMETRY] write failure(s)=%d; continuing without telemetry",
                    _write_failures,
                )
                _warned_failures = _write_failures
        return ok
    except Exception as exc:  # pragma: no cover - defensive
        _write_failures += 1
        logger.warning("[DECISION-TELEMETRY] emit failed (non-fatal): %s", exc)
        return False


def stats() -> Dict[str, Any]:
    return {
        "enabled": telemetry_enabled(),
        "run_id": RUN_ID,
        "write_failures": _write_failures,
        "path": os.environ.get("MERID_DECISION_TELEMETRY_PATH", _DEFAULT_PATH),
    }
