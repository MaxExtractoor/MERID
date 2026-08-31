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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> Optional[float]:
    for v in values:
        f = _coerce_float(v)
        if f is not None:
            return f
    return None


def _first_str(*values: Any) -> Optional[str]:
    for v in values:
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _first_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _resolve(
    candidate: Optional[Dict[str, Any]],
    decision: Dict[str, Any],
    candidate_keys: Sequence[str],
    decision_keys: Sequence[str],
    default: Any = None,
) -> Any:
    """Look up a value from candidate, then decision, with key aliases."""
    if candidate:
        for k in candidate_keys:
            if k in candidate and candidate[k] is not None:
                return candidate[k]
    for k in decision_keys:
        if k in decision and decision[k] is not None:
            return decision[k]
    return default


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
    """Assemble one per-asset per-cycle decision record (schema v1).

    The candidate dict (produced by the signal/trade-decision path) is the
    canonical source of trading economics: side, price, edge, confidence,
    quotes, and provenance.  The decision dict and waterfall supply gate
    diagnostics and rejection reasons.  We prefer candidate, then decision.
    """
    rejection_reason = _resolve(
        candidate, decision,
        ["rejection_reason", "no_trade_reason"],
        ["rejection_reason"],
        default=str(waterfall.get("final_reason") or ""),
    )

    _side = _first_str(
        _resolve(candidate, decision, ["side"], ["selected_side", "signal_side"]),
    )
    _ticker = _first_str(
        _resolve(candidate, decision, ["ticker", "market_ticker"], ["ticker", "market_id"]),
    )
    _cid = _resolve(candidate, decision, ["candidate_id"], ["candidate_id"])
    _did = _first_str(
        _resolve(candidate, decision, ["decision_id"], ["decision_id"]),
    ) or _decision_id(_ticker, _side)

    # Market price for the selected side (fraction, e.g. 0.55).
    _market_p = _coerce_float(
        _resolve(candidate, decision, ["market_prob", "market_p_selected"], ["market_prob", "market_p_selected"]),
    )
    if _market_p is None:
        _price_cents = _first_float(
            _resolve(candidate, decision, ["selected_outcome_price", "price_cents"], ["selected_outcome_price", "price_cents"]),
        )
        if _price_cents is not None:
            _market_p = _price_cents / 100.0

    # Edge in cents. Candidate v2 carries gross_edge_cents; legacy uses edge_pct.
    _raw_edge_cents = _first_float(
        _resolve(candidate, decision, ["gross_edge_cents", "raw_edge_cents", "edge_pct"], ["raw_edge_cents", "edge_pct"]),
    )

    # Fee in cents.
    _entry_fee_cents = _first_float(
        _resolve(candidate, decision, ["entry_fee_cents", "fee_cents"], ["entry_fee_cents"]),
    )

    # Model probabilities.
    _model_prob = _coerce_float(
        _resolve(candidate, decision, ["model_prob", "p_selected"], ["model_prob", "p_selected"]),
    )
    _p_yes = _coerce_float(
        _resolve(candidate, decision, ["p_yes", "model_p_yes"], ["model_p_yes", "p_yes"]),
    )
    _p_no = _coerce_float(
        _resolve(candidate, decision, ["p_no", "model_p_no"], ["model_p_no", "p_no"]),
    )
    if _model_prob is None and _side:
        if str(_side).lower() == "yes" and _p_yes is not None:
            _model_prob = _p_yes
        elif str(_side).lower() == "no" and _p_no is not None:
            _model_prob = _p_no

    # Expiry.
    _minutes_to_expiry = _resolve(candidate, decision, ["minutes_to_expiry"], ["minutes_to_expiry"])
    if _minutes_to_expiry is None:
        _tte_s = _first_float(_resolve(candidate, decision, ["time_to_expiry_seconds"], []))
        if _tte_s is not None:
            _minutes_to_expiry = _tte_s / 60.0

    # Spot / settlement input.
    _spot_price = _first_float(
        _resolve(candidate, decision, ["spot_price", "settlement_input_price"], ["spot_price"]),
    )

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
        "decision_id": _did,
        "candidate_id": _cid,
        "terminal_stage": _terminal_stage(waterfall, candidate, allocator_selected, allocator_note),
        "rejection_chain": _rejection_chain(waterfall),
        "minutes_to_expiry": _minutes_to_expiry,
        "market_available": bool((waterfall.get("stages", {}).get("market_discovered") or {}).get("status", False)),
        "market_state_age_ms": _resolve(candidate, decision, ["market_state_age_ms"], ["market_state_age_ms"]),
        "spot_age_ms": _resolve(candidate, decision, ["spot_age_ms"], ["spot_age_ms"]),
        "ws_age_ms": _resolve(candidate, decision, ["ws_age_ms"], ["ws_age_ms"]),
        "rest_age_ms": _resolve(candidate, decision, ["rest_age_ms"], ["rest_age_ms"]),
        # Quotes / depth
        "yes_bid_cents": _resolve(candidate, decision, ["yes_bid_cents"], ["yes_bid_cents"]),
        "yes_ask_cents": _resolve(candidate, decision, ["yes_ask_cents"], ["yes_ask_cents"]),
        "no_bid_cents": _resolve(candidate, decision, ["no_bid_cents"], ["no_bid_cents"]),
        "no_ask_cents": _resolve(candidate, decision, ["no_ask_cents"], ["no_ask_cents"]),
        "yes_depth": _resolve(candidate, decision, ["yes_depth"], ["yes_depth"]),
        "no_depth": _resolve(candidate, decision, ["no_depth"], ["no_depth"]),
        # Model vs market
        "selected_side": _side,
        "model_p_yes": _p_yes,
        "model_p_no": _p_no,
        "model_prob_selected": _model_prob,
        "market_p_selected": _market_p,
        "raw_edge_cents": _raw_edge_cents,
        # Economics
        "entry_fee_cents": _entry_fee_cents,
        "expected_entry_impact_cents": _resolve(candidate, decision, ["expected_entry_impact_cents"], ["expected_entry_impact_cents"]),
        "exit_fee_reserve_cents": _resolve(candidate, decision, ["exit_fee_reserve_cents"], ["exit_fee_reserve_cents"]),
        "exit_impact_reserve_cents": _resolve(candidate, decision, ["exit_impact_reserve_cents"], ["exit_impact_reserve_cents"]),
        "uncertainty_buffer_cents": _resolve(candidate, decision, ["uncertainty_buffer_cents"], ["uncertainty_buffer_cents"]),
        "slippage_guard_cents": _resolve(candidate, decision, ["slippage_guard_cents"], ["slippage_guard_cents"]),
        "all_in_cost_cents": _resolve(candidate, decision, ["all_in_cost_cents"], ["all_in_cost_cents"]),
        "robust_ev_cents": _resolve(candidate, decision, ["robust_ev_cents"], ["robust_ev_cents"]),
        "ev_net_cents": _resolve(candidate, decision, ["ev_net_cents"], ["ev_net_cents"]),
        "edge_pct": _resolve(candidate, decision, ["edge_pct"], ["edge_pct"]),
        "capped_edge_pct": _resolve(candidate, decision, ["capped_edge_pct"], ["capped_edge_pct"]),
        # Signal indicators
        "velocity": _resolve(candidate, decision, ["velocity"], ["velocity"]),
        "velocity_source": _first_str(
            _resolve(candidate, decision, ["velocity_source"], ["velocity_source"])
        ),
        "velocity_age_ms": _first_float(
            _resolve(candidate, decision, ["velocity_age_ms"], ["velocity_age_ms"])
        ),
        "velocity_threshold": _resolve(candidate, decision, ["velocity_threshold"], ["velocity_threshold"]),
        "spot_price": _spot_price,
        "rti_value": _first_float(
            _resolve(candidate, decision, ["rti_value"], ["rti_value"])
        ),
        "rti_age_ms": _first_float(
            _resolve(candidate, decision, ["rti_age_ms"], ["rti_age_ms"])
        ),
        "rti_returns": _resolve(candidate, decision, ["rti_returns"], ["rti_returns"]) or {},
        "feature_age_ms": _first_float(
            _resolve(candidate, decision, ["feature_age_ms"], ["feature_age_ms"])
        ),
        "feature_valid": _first_bool(
            _resolve(candidate, decision, ["feature_valid"], ["feature_valid"])
        ),
        "feature_missing_reasons": _resolve(candidate, decision, ["feature_missing_reasons"], ["feature_missing_reasons"]) or [],
        "macd_histogram": _resolve(candidate, decision, ["macd_histogram"], ["macd_histogram"]),
        "macd_hist_pct": _resolve(candidate, decision, ["macd_hist_pct"], ["macd_hist_pct"]),
        "base_edge_yes": _resolve(candidate, decision, ["base_edge_yes"], ["base_edge_yes"]),
        "macd_edge_component_yes": _resolve(candidate, decision, ["macd_edge_component_yes"], ["macd_edge_component_yes"]),
        "edge_yes_pct": _resolve(candidate, decision, ["edge_yes_pct"], ["edge_yes_pct"]),
        "base_edge_no": _resolve(candidate, decision, ["base_edge_no"], ["base_edge_no"]),
        "macd_edge_component_no": _resolve(candidate, decision, ["macd_edge_component_no"], ["macd_edge_component_no"]),
        "edge_no_pct": _resolve(candidate, decision, ["edge_no_pct"], ["edge_no_pct"]),
        "rsi": _resolve(candidate, decision, ["rsi"], ["rsi"]),
        "fvg_direction": _resolve(candidate, decision, ["fvg_direction"], ["fvg_direction"]),
        "fvg_confidence": _resolve(candidate, decision, ["fvg_confidence"], ["fvg_confidence"]),
        "fvg_active": _resolve(candidate, decision, ["fvg_active"], ["fvg_active"]),
        "fvg_fill_signal": _resolve(candidate, decision, ["fvg_fill_signal"], ["fvg_fill_signal"]),
        "fvg_size": _resolve(candidate, decision, ["fvg_size"], ["fvg_size"]),
        "fvg_distance_to_fill": _resolve(candidate, decision, ["fvg_distance_to_fill"], ["fvg_distance_to_fill"]),
        "fvg_delta": _resolve(candidate, decision, ["fvg_delta"], ["fvg_delta"]),
        "fvg_price_source": _resolve(candidate, decision, ["fvg_price_source"], ["fvg_price_source"]),
        "fvg_price_staleness_ms": _resolve(candidate, decision, ["fvg_price_staleness_ms"], ["fvg_price_staleness_ms"]),
        "fvg_influenced": _resolve(candidate, decision, ["fvg_influenced"], ["fvg_influenced"]),
        "fvg_size_scale": _resolve(candidate, decision, ["fvg_size_scale"], ["fvg_size_scale"]),
        "order_book_imbalance": _resolve(candidate, decision, ["order_book_imbalance"], ["order_book_imbalance"]),
        # Microstructure features (additive telemetry, gated in live)
        "microstructure_delta_pp": _first_float(
            _resolve(candidate, decision, ["microstructure_delta_pp"], ["microstructure_delta_pp"])
        ),
        "microstructure_book_delta_pp": _first_float(
            _resolve(candidate, decision, ["microstructure_book_delta_pp"], ["microstructure_book_delta_pp"])
        ),
        "microstructure_cross_delta_pp": _first_float(
            _resolve(candidate, decision, ["microstructure_cross_delta_pp"], ["microstructure_cross_delta_pp"])
        ),
        "microstructure_yes_edge_pp": _first_float(
            _resolve(candidate, decision, ["microstructure_yes_edge_pp"], ["microstructure_yes_edge_pp"])
        ),
        "microstructure_no_edge_pp": _first_float(
            _resolve(candidate, decision, ["microstructure_no_edge_pp"], ["microstructure_no_edge_pp"])
        ),
        "microstructure_yes_book_imbalance": None,
        "microstructure_no_book_imbalance": None,
        "microstructure_yes_ofi": None,
        "microstructure_no_ofi": None,
        "microstructure_yes_spread_cents": None,
        "microstructure_no_spread_cents": None,
        "microstructure_btc_log_return": None,
        # Gate outcomes
        "signal_generated": bool((waterfall.get("stages", {}).get("signal_generated") or {}).get("status", False)),
        "candidate_generated": candidate is not None,
        "rejection_stage": _classify_rejection(waterfall, str(rejection_reason or "")),
        "rejection_reason": rejection_reason or None,
        "candidate_rank": candidate_rank,
        "allocator_rank": allocator_rank,
        "allocator_selected": allocator_selected,
        "allocator_note": allocator_note or None,
        # Provenance / intent (new fields, backward-compatible)
        "settlement_reference": _resolve(candidate, decision, ["settlement_reference"], ["settlement_reference"]),
        "data_state": _resolve(candidate, decision, ["data_state"], ["data_state"]),
        "regime_label": _first_str(
            _resolve(candidate, decision, ["regime_label", "regime"], ["regime", "regime_label"]),
        ),
        "regime_probability": _first_float(
            _resolve(candidate, decision, ["regime_probability"], ["regime_probability"]),
        ),
        "confidence_valid": _first_bool(
            _resolve(candidate, decision, ["confidence_valid"], ["confidence_valid"]),
        ),
        "confidence_source": _first_str(
            _resolve(candidate, decision, ["confidence_source"], ["confidence_source"]),
        ),
        "confidence_reasons": _resolve(candidate, decision, ["confidence_reasons"], ["confidence_reasons"]) or [],
        "selected_outcome_price_cents": _first_float(
            _resolve(candidate, decision, ["selected_outcome_price", "price_cents"], ["selected_outcome_price", "price_cents"]),
        ),
        "gross_edge_cents": _first_float(
            _resolve(candidate, decision, ["gross_edge_cents"], ["gross_edge_cents"]),
        ),
        "net_edge_cents": _first_float(
            _resolve(candidate, decision, ["net_edge_cents"], ["net_edge_cents"]),
        ),
        "thesis_side": _first_str(
            _resolve(candidate, decision, ["thesis_side"], ["thesis_side"]),
        ),
        "strategy_intent": _first_str(
            _resolve(candidate, decision, ["strategy_intent"], ["strategy_intent"]),
        ),
        "rationale": _first_str(
            _resolve(candidate, decision, ["rationale"], ["rationale"]),
        ),
    }

    # Flatten microstructure feature dictionaries when present.
    _yes_features = _resolve(candidate, decision, ["microstructure_yes_features"], ["microstructure_yes_features"]) or {}
    _no_features = _resolve(candidate, decision, ["microstructure_no_features"], ["microstructure_no_features"]) or {}
    if isinstance(_yes_features, dict):
        record["microstructure_yes_book_imbalance"] = _first_float(_yes_features.get("book_imbalance"))
        record["microstructure_yes_ofi"] = _first_float(_yes_features.get("ofi"))
        record["microstructure_yes_spread_cents"] = _first_float(_yes_features.get("spread_cents"))
    if isinstance(_no_features, dict):
        record["microstructure_no_book_imbalance"] = _first_float(_no_features.get("book_imbalance"))
        record["microstructure_no_ofi"] = _first_float(_no_features.get("ofi"))
        record["microstructure_no_spread_cents"] = _first_float(_no_features.get("spread_cents"))
    record["microstructure_btc_log_return"] = _first_float(
        _resolve(candidate, decision, ["microstructure_btc_log_return"], ["microstructure_btc_log_return"])
    )

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
