"""Shadow side A/B telemetry for the 15m agent.

Logs one record per trade decision containing the live selected side, the
inverted side, and an alternative side derived from an inverted model
probability.  Downstream settlement jobs can join on decision_id or run_id to
compute realized live-vs-shadow PnL and win rates.

This is pure instrumentation: it never changes the selected side or order.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_SHADOW_PATH = "data/logs/shadow_side_telemetry.jsonl"
_DEFAULT_DECOMPOSITION_PATH = "data/logs/hybrid_model_decomposition.jsonl"

_shadow_writer = None
_decomposition_writer = None
_writer_lock = threading.Lock()
_decomposition_writer_lock = threading.Lock()
_write_errors = 0
_warned_failures = 0


def shadow_telemetry_enabled() -> bool:
    return os.environ.get("MERID_SHADOW_SIDE_TELEMETRY", "1") != "0"


def model_decomposition_enabled() -> bool:
    return os.environ.get("MERID_MODEL_DECOMPOSITION_TELEMETRY", "1") != "0"


def _get_shadow_writer():
    global _shadow_writer
    if _shadow_writer is None:
        with _writer_lock:
            if _shadow_writer is None:
                from utils.jsonl_writer import JsonlWriter

                path = os.environ.get("MERID_SHADOW_SIDE_TELEMETRY_PATH", _DEFAULT_SHADOW_PATH)
                _shadow_writer = JsonlWriter(path, max_bytes=20_000_000, backup_count=5)
    return _shadow_writer


def _get_decomposition_writer():
    global _decomposition_writer
    if _decomposition_writer is None:
        with _decomposition_writer_lock:
            if _decomposition_writer is None:
                from utils.jsonl_writer import JsonlWriter

                path = os.environ.get("MERID_MODEL_DECOMPOSITION_PATH", _DEFAULT_DECOMPOSITION_PATH)
                _decomposition_writer = JsonlWriter(path, max_bytes=20_000_000, backup_count=5)
    return _decomposition_writer


def _reset_writer_for_tests() -> None:
    global _shadow_writer, _decomposition_writer, _write_errors, _warned_failures
    with _writer_lock:
        _shadow_writer = None
    with _decomposition_writer_lock:
        _decomposition_writer = None
    _write_errors = 0
    _warned_failures = 0


def _sanitize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_cents(dollars: Optional[float]) -> float:
    if dollars is None:
        return 0.0
    return dollars * 100.0


def _compute_edge(p_yes: float, side: str, entry_cents: float, fee_cents: float) -> float:
    """Compute a simple gross-vs-net edge in cents.

    Mirrors the trade_decision edge logic in fractional form:
        p_selected = p_yes for yes, 1 - p_yes for no
        gross_edge = p_selected * 100 - entry_price
        net_edge = gross_edge - fee
    """
    if p_yes is None or not math.isfinite(p_yes):
        return float("-inf")
    if side == "yes":
        p_selected = p_yes
    else:
        p_selected = 1.0 - p_yes
    return p_selected * 100.0 - entry_cents - fee_cents


def _select_side_from_edge(p_yes: float, yes_entry_cents: float, no_entry_cents: float, fee_cents: float) -> str:
    yes_edge = _compute_edge(p_yes, "yes", yes_entry_cents, fee_cents)
    no_edge = _compute_edge(p_yes, "no", no_entry_cents, fee_cents)
    if yes_edge >= no_edge:
        return "yes"
    return "no"


def write_shadow_side_record(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    asset: str,
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    fee_per_contract_cents: float,
    p_yes_model: Optional[float],
    selected_side: Optional[str],
    selected_outcome_price_cents: Optional[float],
    selected_net_edge: Optional[float],
    annualized_vol: float,
    velocity: Optional[float] = None,
    regime: Optional[str] = None,
    data_state: Optional[str] = None,
    settlement_reference: Optional[str] = None,
    selection_reason: Optional[str] = None,
    hybrid_probability: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> None:
    """Write a shadow A/B record for a single trade decision.

    Records the live selected side, the simple inverted side, and a
    model-probability-inverted side.  Settlement-time scripts can later join
    these records and compare realized PnL and win rates.
    """
    if not shadow_telemetry_enabled():
        return

    try:
        # Use executable asks as the entry price for each side, matching the
        # trade-decision convention.  The bid/ask are kept so shadow PnL can
        # be recomputed with different spread assumptions later.
        yes_entry = yes_ask_cents
        no_entry = no_ask_cents

        inverted_side = None
        inverted_edge = None
        inverted_p_yes = None
        recalibrated_side = None
        recalibrated_edge = None
        recalibrated_p_yes = None

        if p_yes_model is not None and math.isfinite(p_yes_model):
            # Inverted probability: if p_yes is miscalibrated by a sign flip,
            # 1 - p_yes is the corrected estimate.
            inverted_p_yes = max(0.0, min(1.0, 1.0 - p_yes_model))
            recalibrated_side = _select_side_from_edge(inverted_p_yes, yes_entry, no_entry, fee_per_contract_cents)
            recalibrated_edge = _compute_edge(inverted_p_yes, recalibrated_side, yes_entry if recalibrated_side == "yes" else no_entry, fee_per_contract_cents)

            # Simple opposite side of the live selection.
            if selected_side in ("yes", "no"):
                inverted_side = "no" if selected_side == "yes" else "yes"
                inverted_edge = _compute_edge(p_yes_model, inverted_side, yes_entry if inverted_side == "yes" else no_entry, fee_per_contract_cents)

        record: Dict[str, Any] = {
            "schema_version": 1,
            "process_id": os.environ.get("MERID_PROCESS_ID", ""),
            "run_id": run_id,
            "decision_id": decision_id,
            "ticker": ticker,
            "asset": asset,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "spot_price": _sanitize(spot_price),
            "strike_price": _sanitize(strike_price),
            "seconds_to_expiry": _sanitize(seconds_to_expiry),
            "yes_bid_cents": _sanitize(yes_bid_cents),
            "yes_ask_cents": _sanitize(yes_ask_cents),
            "no_bid_cents": _sanitize(no_bid_cents),
            "no_ask_cents": _sanitize(no_ask_cents),
            "fee_per_contract_cents": _sanitize(fee_per_contract_cents),
            "p_yes_model": _sanitize(p_yes_model),
            "hybrid_probability": {k: _sanitize(v) for k, v in (hybrid_probability or {}).items()},
            "annualized_vol": _sanitize(annualized_vol),
            "velocity": _sanitize(velocity),
            "regime": _sanitize(regime),
            "data_state": _sanitize(data_state),
            "settlement_reference": _sanitize(settlement_reference),
            "selection_reason": _sanitize(selection_reason),
            "live": {
                "selected_side": selected_side,
                "selected_outcome_price_cents": _sanitize(selected_outcome_price_cents),
                "selected_net_edge_cents": _sanitize(selected_net_edge),
                "selected_entry_cents": _sanitize(yes_entry if selected_side == "yes" else (no_entry if selected_side == "no" else None)),
            },
            "shadow_inverted": {
                "selected_side": inverted_side,
                "selected_net_edge_cents": _sanitize(inverted_edge),
                "selected_entry_cents": _sanitize(yes_entry if inverted_side == "yes" else (no_entry if inverted_side == "no" else None)),
            },
            "shadow_recalibrated": {
                "p_yes": _sanitize(recalibrated_p_yes),
                "selected_side": recalibrated_side,
                "selected_net_edge_cents": _sanitize(recalibrated_edge),
                "selected_entry_cents": _sanitize(yes_entry if recalibrated_side == "yes" else (no_entry if recalibrated_side == "no" else None)),
            },
        }

        if extra:
            record["extra"] = {k: _sanitize(v) for k, v in extra.items()}

        _get_shadow_writer().append(record)
    except Exception as exc:
        global _write_errors, _warned_failures
        _write_errors += 1
        if _write_errors - _warned_failures >= 10:
            logger.warning("[SHADOW-SIDE] write failures=%d: %s", _write_errors, exc)
            _warned_failures = _write_errors


def _decision_block(decision: Any) -> Optional[Dict[str, Any]]:
    """Convert a TradeDecision into a model-decomposition sub-record."""
    if decision is None:
        return None
    try:
        bd = getattr(decision, "edge_breakdown", None)
        return {
            "selected_outcome": _sanitize(getattr(decision, "selected_outcome", None)),
            "selected_action": _sanitize(getattr(decision, "selected_action", None)),
            "no_trade_reason": _sanitize(getattr(decision, "no_trade_reason", None)),
            "p_yes_calibrated": _sanitize(float(getattr(decision, "p_yes_calibrated", 0.0))),
            "p_no_calibrated": _sanitize(float(getattr(decision, "p_no_calibrated", 0.0))),
            "p_selected": _sanitize(float(getattr(decision, "p_selected", 0.0)) if getattr(decision, "p_selected", None) is not None else None),
            "gross_edge": _sanitize(float(getattr(decision, "gross_edge", 0.0)) if getattr(decision, "gross_edge", None) is not None else None),
            "net_edge": _sanitize(float(getattr(decision, "net_edge", 0.0)) if getattr(decision, "net_edge", None) is not None else None),
            "yes_net_edge": _sanitize(float(getattr(decision, "yes_net_edge", 0.0)) if getattr(decision, "yes_net_edge", None) is not None else None),
            "no_net_edge": _sanitize(float(getattr(decision, "no_net_edge", 0.0)) if getattr(decision, "no_net_edge", None) is not None else None),
            "confidence": _sanitize(float(getattr(decision, "confidence", 0.0)) if getattr(decision, "confidence", None) is not None else None),
            "confidence_valid": _sanitize(getattr(decision, "confidence_valid", False)),
            "confidence_source": _sanitize(getattr(decision, "confidence_source", None)),
            "confidence_reasons": _sanitize(getattr(decision, "confidence_reasons", None)),
            "edge_threshold": _sanitize(float(getattr(decision, "edge_threshold", 0.0)) if getattr(decision, "edge_threshold", None) is not None else None),
            "executable_entry_price": _sanitize(float(getattr(bd, "executable_entry_price", 0.0)) * 100.0 if bd is not None else None),
            "entry_fee_cents": _sanitize(float(getattr(bd, "entry_fee", 0.0)) * 100.0 if bd is not None else None),
        }
    except Exception as exc:
        logger.debug("[DECOMPOSITION] failed to build decision block: %s", exc)
        return None


def write_model_decomposition_record(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    asset: str,
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    hybrid_probability: Optional[Dict[str, Any]],
    decision: Any,
    decision_bachelier: Optional[Any] = None,
    settlement_reference: Optional[str] = None,
    data_state: Optional[str] = None,
    regime: Optional[str] = None,
) -> None:
    """Write a full model-decomposition record for a single evaluation.

    This record joins the raw inputs, Bachelier baseline, each signed delta,
    the pre-clip and final model probability, and the resulting trade decision.
    Settlement jobs can later join on decision_id to compute component-level
    directional hit rates.
    """
    if not model_decomposition_enabled():
        return

    try:
        hp = hybrid_probability or {}
        p_yes_bachelier = _sanitize(hp.get("p_yes_bachelier"))
        raw_delta_total = _sanitize(hp.get("total_delta"))
        p_yes_pre_clip = None
        if p_yes_bachelier is not None and raw_delta_total is not None:
            p_yes_pre_clip = p_yes_bachelier + raw_delta_total

        record: Dict[str, Any] = {
            "schema_version": 1,
            "process_id": os.environ.get("MERID_PROCESS_ID", ""),
            "run_id": run_id,
            "decision_id": decision_id,
            "ticker": ticker,
            "asset": asset,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "decision_ts": time.time(),
            "time_remaining_s": _sanitize(seconds_to_expiry),
            "spot_now": _sanitize(spot_price),
            "strike_or_open_reference": _sanitize(strike_price),
            "market_yes_bid": _sanitize(yes_bid_cents),
            "market_yes_ask": _sanitize(yes_ask_cents),
            "market_no_bid": _sanitize(no_bid_cents),
            "market_no_ask": _sanitize(no_ask_cents),
            "p_yes_bachelier": p_yes_bachelier,
            "delta_velocity": _sanitize(hp.get("velocity_edge")),
            "delta_macd": _sanitize(hp.get("macd_delta")),
            "delta_rsi": _sanitize(hp.get("rsi_delta")),
            "delta_obi": _sanitize(hp.get("obi_delta")),
            "delta_regime": _sanitize(hp.get("regime_delta")),
            "delta_fvg": _sanitize(hp.get("fvg_delta")),
            "raw_delta_total": raw_delta_total,
            "p_yes_pre_clip": _sanitize(p_yes_pre_clip),
            "p_yes_model": _sanitize(hp.get("p_yes")),
            "annualized_vol": _sanitize(hp.get("annualized_vol")),
            "bars_available": _sanitize(hp.get("bars_available")),
            "max_shift": _sanitize(hp.get("max_shift")),
            "settlement_reference": _sanitize(settlement_reference),
            "data_state": _sanitize(data_state),
            "regime": _sanitize(regime),
            "live": _decision_block(decision),
            "bachelier_only": _decision_block(decision_bachelier),
        }

        _get_decomposition_writer().append(record)
    except Exception as exc:
        global _write_errors, _warned_failures
        _write_errors += 1
        if _write_errors - _warned_failures >= 10:
            logger.warning("[MODEL-DECOMPOSITION] write failures=%d: %s", _write_errors, exc)
            _warned_failures = _write_errors
