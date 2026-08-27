#!/usr/bin/env python3
"""Execution-fidelity / TCA audit for the last 24 hours of MERID trades.

Reads:
- reports/last_24h_fills_with_pairing_and_settlement_*.csv
- reports/last_24h_round_trips_and_open_positions_*.csv
- logs/decision_telemetry.jsonl (attempted; records coverage)

Produces:
- reports/execution_fidelity_audit_YYYYmmdd_HHMMSS.json
- reports/execution_fidelity_audit_YYYYmmdd_HHMMSS.csv

The audit computes execution-quality metrics (spread, slippage, side fidelity,
hold time, PnL, win/loss) from durable fills and round-trip records.  Decision-
time fields (model prob, edge, confidence, thesis) are joined by exact
fill.decision_trace_id -> decision.decision_id when available; otherwise it
falls back to a ticker+side+time window join.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_decimal(value: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _parse_iso_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _fmt_decimal(value: Optional[Decimal], places: int = 4) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), places)
    except (TypeError, ValueError, InvalidOperation):
        return None


# ---------------------------------------------------------------------------
# Raw-payload parsing
# ---------------------------------------------------------------------------

def _parse_raw_payload(raw: Any) -> Dict[str, Any]:
    """Best-effort parse of the raw_payload JSON string."""
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def _extract_book_from_payload(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Return best bid/ask at fill time from the raw payload (cents)."""
    raw_data = payload.get("raw_data") or {}
    # The HTTP/WS fill payload carries the market snapshot inside raw_data.
    return {
        "yes_bid_cents": _safe_float(raw_data.get("yes_bid_cents")),
        "yes_ask_cents": _safe_float(raw_data.get("yes_ask_cents")),
        "no_bid_cents": _safe_float(raw_data.get("no_bid_cents")),
        "no_ask_cents": _safe_float(raw_data.get("no_ask_cents")),
        "is_taker": raw_data.get("is_taker"),
        "book_side": raw_data.get("book_side"),
    }


# ---------------------------------------------------------------------------
# Fill record enrichment
# ---------------------------------------------------------------------------

def _enrich_fill(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add execution-quality fields to a single fill row."""
    payload = _parse_raw_payload(row.get("raw_payload"))
    book = _extract_book_from_payload(payload)

    side = str(row.get("canonical_position_side") or row.get("side") or "").lower()
    action = str(row.get("canonical_position_action") or row.get("action") or "").lower()
    fill_price = _safe_float(row.get("execution_price_cents")) or _safe_float(row.get("canonical_leg_price_cents"))
    is_exit = bool(int(row.get("is_exit") or 0))
    quantity_cc = _safe_int(row.get("quantity_cc")) or 0
    fee_cents = _safe_float(row.get("realized_fee_cents")) or _safe_float(row.get("fee_cost"))
    if fee_cents is None:
        fee_cents = 0.0
    gross_pnl = _safe_float(row.get("realized_gross_pnl_cents"))
    net_pnl = _safe_float(row.get("realized_net_pnl_cents"))

    bid, ask, mid, spread, fill_vs_mid, fill_vs_touch = None, None, None, None, None, None
    if side == "yes":
        bid = book.get("yes_bid_cents")
        ask = book.get("yes_ask_cents")
    elif side == "no":
        bid = book.get("no_bid_cents")
        ask = book.get("no_ask_cents")

    if bid is not None and ask is not None:
        spread = ask - bid
        mid = (bid + ask) / 2.0

    if fill_price is not None and mid is not None:
        fill_vs_mid = fill_price - mid

    if fill_price is not None:
        if action == "buy" and ask is not None:
            fill_vs_touch = fill_price - ask
        elif action == "sell" and bid is not None:
            fill_vs_touch = bid - fill_price

    created = _parse_iso_ts(row.get("created_time"))
    ingested = _parse_iso_ts(row.get("ingested_at"))
    ingestion_delay_s = None
    if created and ingested:
        ingestion_delay_s = (ingested - created).total_seconds()

    return {
        **row,
        "fill_side": side,
        "fill_action": action,
        "fill_price_cents": fill_price,
        "quantity_cc": quantity_cc,
        "fee_cents": fee_cents,
        "gross_pnl_cents": gross_pnl,
        "net_pnl_cents": net_pnl,
        "yes_bid_cents": book.get("yes_bid_cents"),
        "yes_ask_cents": book.get("yes_ask_cents"),
        "no_bid_cents": book.get("no_bid_cents"),
        "no_ask_cents": book.get("no_ask_cents"),
        "is_taker": book.get("is_taker"),
        "book_side": book.get("book_side"),
        "spread_at_fill_cents": spread,
        "mid_at_fill_cents": mid,
        "fill_slippage_vs_mid_cents": fill_vs_mid,
        "fill_vs_best_touch_cents": fill_vs_touch,
        "exchange_to_ingestion_latency_seconds": ingestion_delay_s,
        "is_exit": is_exit,
        "entry_or_exit": row.get("entry_or_exit") or ("exit" if is_exit else "entry"),
    }


# ---------------------------------------------------------------------------
# Round-trip enrichment
# ---------------------------------------------------------------------------

def _enrich_round_trip(
    rt: Dict[str, Any],
    fills_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Join entry and exit fills onto a round-trip record."""
    entry_fill = fills_by_id.get(rt.get("entry_fill_id") or "")
    exit_fill = fills_by_id.get(rt.get("exit_fill_id") or "")

    entry_enriched = _enrich_fill(entry_fill) if entry_fill else {}
    exit_enriched = _enrich_fill(exit_fill) if exit_fill else {}

    def _prefix(prefix: str, src: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in keys:
            out[f"{prefix}_{k}"] = src.get(k)
        return out

    entry_keys = (
        "fill_side", "fill_action", "fill_price_cents", "quantity_cc", "fee_cents",
        "gross_pnl_cents", "net_pnl_cents",
        "yes_bid_cents", "yes_ask_cents", "no_bid_cents", "no_ask_cents",
        "spread_at_fill_cents", "mid_at_fill_cents", "fill_slippage_vs_mid_cents",
        "fill_vs_best_touch_cents", "exchange_to_ingestion_latency_seconds", "is_taker", "book_side",
        "client_order_id", "intent_id", "agent_id", "fill_source", "hedge_reason",
        "created_time", "ingested_at", "ingestion_source", "market_ticker",
        "decision_trace_id",
    )
    exit_keys = entry_keys

    enriched = {
        **rt,
        **_prefix("entry", entry_enriched, entry_keys),
        **_prefix("exit", exit_enriched, exit_keys),
        "entry_fill_present": entry_fill is not None,
        "exit_fill_present": exit_fill is not None,
    }

    # Side / action derived from entry fill (canonical).
    side = enriched.get("entry_fill_side") or ""
    action = enriched.get("entry_fill_action") or ""
    enriched["executed_side"] = side
    enriched["executed_action"] = action

    # Decision/intent placeholders — filled later if decision log is joinable.
    enriched["entry_decision_trace_id"] = entry_enriched.get("decision_trace_id")
    enriched["decision_id"] = None
    enriched["intended_side"] = None
    enriched["intended_price_cents"] = None
    enriched["model_prob_selected"] = None
    enriched["edge_at_decision_cents"] = None
    enriched["confidence"] = None
    enriched["confidence_valid"] = None
    enriched["confidence_source"] = None
    enriched["thesis"] = None
    enriched["strategy_intent"] = None
    enriched["settlement_reference"] = None
    enriched["data_state"] = None
    enriched["regime_label"] = None
    enriched["yes_bid_cents"] = None
    enriched["yes_ask_cents"] = None
    enriched["no_bid_cents"] = None
    enriched["no_ask_cents"] = None

    # Edge decay / implementation shortfall — requires decision fields.
    enriched["edge_decay_cents"] = None
    enriched["implementation_shortfall_cents"] = None
    enriched["side_fidelity"] = None

    # Win/loss and derived economics.
    net_pnl = _safe_float(rt.get("net_pnl_cents"))
    gross_pnl = _safe_float(rt.get("gross_pnl_cents"))
    quantity_contracts = _safe_float(rt.get("quantity_contracts")) or 0.0
    total_fee = _safe_float(rt.get("total_fee_cents")) or 0.0
    enriched["is_net_win"] = net_pnl is not None and net_pnl > 0
    enriched["is_net_loss"] = net_pnl is not None and net_pnl < 0
    enriched["is_gross_win"] = gross_pnl is not None and gross_pnl > 0
    enriched["is_gross_loss"] = gross_pnl is not None and gross_pnl < 0
    enriched["gross_pnl_per_contract_cents"] = round(gross_pnl / quantity_contracts, 4) if quantity_contracts and gross_pnl is not None else None
    enriched["net_pnl_per_contract_cents"] = round(net_pnl / quantity_contracts, 4) if quantity_contracts and net_pnl is not None else None
    enriched["fee_drag_cents"] = round(total_fee / quantity_contracts, 4) if quantity_contracts else None

    return enriched


# ---------------------------------------------------------------------------
# Decision telemetry loading
# ---------------------------------------------------------------------------

def _load_decision_telemetry(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load selected decision records and a coverage summary."""
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records, {"exists": False, "reason": "file_not_found"}

    selected = 0
    with_ticker = 0
    with_side = 0
    with_edge = 0
    with_model_prob = 0
    with_confidence = 0
    with_decision_id = 0
    total = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "decision_record":
                continue
            total += 1
            if rec.get("allocator_selected"):
                selected += 1
                if rec.get("ticker"):
                    with_ticker += 1
                if rec.get("selected_side"):
                    with_side += 1
                if rec.get("edge_pct") is not None:
                    with_edge += 1
                if rec.get("model_prob_selected") is not None:
                    with_model_prob += 1
                if rec.get("confidence") is not None:
                    with_confidence += 1
                if rec.get("decision_id"):
                    with_decision_id += 1
                records.append(rec)

    coverage = {
        "exists": True,
        "path": str(path),
        "total_records": total,
        "selected_records": selected,
        "selected_with_ticker": with_ticker,
        "selected_with_side": with_side,
        "selected_with_edge_pct": with_edge,
        "selected_with_model_prob": with_model_prob,
        "selected_with_confidence": with_confidence,
        "selected_with_decision_id": with_decision_id,
    }
    return records, coverage


def _apply_decision_to_round_trip(
    rt: Dict[str, Any],
    rec: Dict[str, Any],
    match_type: str,
    distance: Optional[float] = None,
) -> None:
    """Copy decision fields into a round trip and compute fidelity metrics."""
    rt["decision_match_type"] = match_type
    rt["decision_id"] = rec.get("decision_id")
    rt["intended_side"] = rec.get("selected_side")
    rt["intended_price_cents"] = rec.get("selected_outcome_price_cents")
    rt["model_prob_selected"] = rec.get("model_prob_selected")
    rt["edge_at_decision_cents"] = rec.get("raw_edge_cents")
    rt["confidence"] = rec.get("confidence")
    rt["confidence_valid"] = rec.get("confidence_valid")
    rt["confidence_source"] = rec.get("confidence_source")
    rt["thesis"] = rec.get("rationale") or rec.get("thesis_side")
    rt["strategy_intent"] = rec.get("strategy_intent")
    rt["settlement_reference"] = rec.get("settlement_reference")
    rt["data_state"] = rec.get("data_state")
    rt["regime_label"] = rec.get("regime_label")
    rt["yes_bid_cents"] = rec.get("yes_bid_cents")
    rt["yes_ask_cents"] = rec.get("yes_ask_cents")
    rt["no_bid_cents"] = rec.get("no_bid_cents")
    rt["no_ask_cents"] = rec.get("no_ask_cents")
    rt["decision_match_distance_seconds"] = round(distance, 3) if distance is not None else None

    # Side fidelity.
    if rt.get("executed_side") and rt.get("intended_side"):
        rt["side_fidelity"] = str(rt["executed_side"]).lower() == str(rt["intended_side"]).lower()

    # Implementation shortfall (decision price vs fill price), positive = worse.
    intended_price = _safe_float(rt.get("intended_price_cents"))
    fill_price = _safe_float(rt.get("entry_fill_price_cents"))
    action = str(rt.get("executed_action") or "").lower()
    if intended_price is not None and fill_price is not None and action:
        if action == "buy":
            rt["implementation_shortfall_cents"] = fill_price - intended_price
        else:  # sell
            rt["implementation_shortfall_cents"] = intended_price - fill_price

    # Edge decay: intended gross edge - realized gross edge (model prob - fill price).
    raw_edge = _safe_float(rt.get("edge_at_decision_cents"))
    model_prob = _safe_float(rt.get("model_prob_selected"))
    if raw_edge is not None and model_prob is not None and fill_price is not None:
        realized_edge_cents = (model_prob * 100.0) - fill_price
        rt["edge_decay_cents"] = raw_edge - realized_edge_cents


def _match_decisions_to_round_trips(
    round_trips: List[Dict[str, Any]],
    decision_records: List[Dict[str, Any]],
) -> int:
    """Enrich round trips with decision fields.

    First attempt an exact join on fills that carry a decision trace id.
    Fall back to a ticker+side+time window join for legacy fills.
    Returns match count.
    """
    if not decision_records:
        return 0

    # Exact index by decision_id.
    by_decision_id: Dict[str, Dict[str, Any]] = {}
    for rec in decision_records:
        did = rec.get("decision_id")
        if did and did not in by_decision_id:
            by_decision_id[did] = rec

    # Fuzzy index by (ticker, side).
    by_ticker_side: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for rec in decision_records:
        ticker = rec.get("ticker")
        side = str(rec.get("selected_side") or "").lower()
        if ticker and side:
            by_ticker_side[(ticker, side)].append(rec)

    exact_matches = 0
    fuzzy_matches = 0
    for rt in round_trips:
        # 1. Exact linkage: entry fill persisted the candidate's decision_id as decision_trace_id.
        trace_id = rt.get("entry_decision_trace_id")
        if trace_id and trace_id in by_decision_id:
            _apply_decision_to_round_trip(rt, by_decision_id[trace_id], "exact")
            exact_matches += 1
            continue

        # 2. Fuzzy fallback: ticker + side + nearest decision time within 15 minutes.
        ticker = rt.get("ticker")
        side = rt.get("executed_side")
        if not ticker or not side:
            continue
        entry_time = _parse_iso_ts(rt.get("entry_time"))
        if not entry_time:
            continue
        candidates = by_ticker_side.get((ticker, side), [])
        best: Optional[Dict[str, Any]] = None
        best_delta: Optional[float] = None
        for rec in candidates:
            ts = _parse_iso_ts(rec.get("event_ts_utc"))
            if not ts:
                continue
            delta = abs((entry_time - ts).total_seconds())
            if best_delta is None or delta < best_delta:
                best = rec
                best_delta = delta

        if best and best_delta is not None and best_delta <= 900:
            _apply_decision_to_round_trip(rt, best, "fuzzy", best_delta)
            fuzzy_matches += 1

    return {"exact": exact_matches, "fuzzy": fuzzy_matches, "total": exact_matches + fuzzy_matches}


# ---------------------------------------------------------------------------
# Metric aggregations
# ---------------------------------------------------------------------------

def _mean(vals: Iterable[Optional[float]]) -> Optional[float]:
    v = [float(x) for x in vals if x is not None and math.isfinite(float(x))]
    return round(mean(v), 4) if v else None


def _median_f(vals: Iterable[Optional[float]]) -> Optional[float]:
    v = [float(x) for x in vals if x is not None and math.isfinite(float(x))]
    return round(median(v), 4) if v else None


def _sum_f(vals: Iterable[Optional[float]]) -> float:
    return sum(float(x) for x in vals if x is not None and math.isfinite(float(x)))


def _count_non_null(vals: Iterable[Any]) -> int:
    return sum(1 for v in vals if v is not None)


def _percentile(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[f], 4)
    return round(s[f] + (s[c] - s[f]) * (k - f), 4)


def _build_asset_summary(round_trips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-asset and overall metrics."""
    by_asset: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rt in round_trips:
        by_asset[rt.get("asset", "UNKNOWN")].append(rt)

    def _metrics(rts: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(rts)
        net_wins = sum(1 for r in rts if r.get("is_net_win"))
        net_losses = sum(1 for r in rts if r.get("is_net_loss"))
        gross_wins = sum(1 for r in rts if r.get("is_gross_win"))
        gross_losses = sum(1 for r in rts if r.get("is_gross_loss"))
        return {
            "round_trips": n,
            "gross_wins": gross_wins,
            "gross_losses": gross_losses,
            "net_wins": net_wins,
            "net_losses": net_losses,
            "gross_win_rate": round(gross_wins / n, 4) if n else None,
            "net_win_rate": round(net_wins / n, 4) if n else None,
            "total_gross_pnl_cents": round(_sum_f(r.get("gross_pnl_cents") for r in rts), 4),
            "total_net_pnl_cents": round(_sum_f(r.get("net_pnl_cents") for r in rts), 4),
            "total_fees_cents": round(_sum_f(r.get("total_fee_cents") for r in rts), 4),
            "total_contracts": round(_sum_f(r.get("quantity_contracts") for r in rts), 4),
            "avg_hold_seconds": _mean(r.get("hold_time_seconds") for r in rts),
            "median_hold_seconds": _median_f(r.get("hold_time_seconds") for r in rts),
            "avg_entry_spread_cents": _mean(r.get("entry_spread_at_fill_cents") for r in rts),
            "avg_exit_spread_cents": _mean(r.get("exit_spread_at_fill_cents") for r in rts if r.get("exit_fill_present")),
            "avg_entry_slippage_vs_mid_cents": _mean(r.get("entry_fill_slippage_vs_mid_cents") for r in rts),
            "avg_exit_slippage_vs_mid_cents": _mean(r.get("exit_fill_slippage_vs_mid_cents") for r in rts if r.get("exit_fill_present")),
            "avg_entry_fill_vs_touch_cents": _mean(r.get("entry_fill_vs_best_touch_cents") for r in rts),
            "avg_exit_fill_vs_touch_cents": _mean(r.get("exit_fill_vs_best_touch_cents") for r in rts if r.get("exit_fill_present")),
            "avg_entry_exchange_to_ingestion_latency_seconds": _mean(r.get("entry_exchange_to_ingestion_latency_seconds") for r in rts),
            "entry_exchange_to_ingestion_p50_seconds": _percentile([float(r.get("entry_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("entry_exchange_to_ingestion_latency_seconds") is not None], 50.0),
            "entry_exchange_to_ingestion_p90_seconds": _percentile([float(r.get("entry_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("entry_exchange_to_ingestion_latency_seconds") is not None], 90.0),
            "entry_exchange_to_ingestion_p95_seconds": _percentile([float(r.get("entry_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("entry_exchange_to_ingestion_latency_seconds") is not None], 95.0),
            "entry_exchange_to_ingestion_p99_seconds": _percentile([float(r.get("entry_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("entry_exchange_to_ingestion_latency_seconds") is not None], 99.0),
            "entry_exchange_to_ingestion_max_seconds": max((float(r.get("entry_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("entry_exchange_to_ingestion_latency_seconds") is not None), default=None),
            "avg_exit_exchange_to_ingestion_latency_seconds": _mean(r.get("exit_exchange_to_ingestion_latency_seconds") for r in rts if r.get("exit_fill_present")),
            "exit_exchange_to_ingestion_p50_seconds": _percentile([float(r.get("exit_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("exit_fill_present") and r.get("exit_exchange_to_ingestion_latency_seconds") is not None], 50.0),
            "exit_exchange_to_ingestion_p90_seconds": _percentile([float(r.get("exit_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("exit_fill_present") and r.get("exit_exchange_to_ingestion_latency_seconds") is not None], 90.0),
            "exit_exchange_to_ingestion_p95_seconds": _percentile([float(r.get("exit_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("exit_fill_present") and r.get("exit_exchange_to_ingestion_latency_seconds") is not None], 95.0),
            "exit_exchange_to_ingestion_p99_seconds": _percentile([float(r.get("exit_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("exit_fill_present") and r.get("exit_exchange_to_ingestion_latency_seconds") is not None], 99.0),
            "exit_exchange_to_ingestion_max_seconds": max((float(r.get("exit_exchange_to_ingestion_latency_seconds")) for r in rts if r.get("exit_fill_present") and r.get("exit_exchange_to_ingestion_latency_seconds") is not None), default=None),
            "avg_gross_pnl_per_contract_cents": round(_sum_f(r.get("gross_pnl_cents") for r in rts) / _sum_f(r.get("quantity_contracts") for r in rts), 4) if _sum_f(r.get("quantity_contracts") for r in rts) else None,
            "avg_net_pnl_per_contract_cents": round(_sum_f(r.get("net_pnl_cents") for r in rts) / _sum_f(r.get("quantity_contracts") for r in rts), 4) if _sum_f(r.get("quantity_contracts") for r in rts) else None,
            "avg_fee_drag_cents": round(_sum_f(r.get("total_fee_cents") for r in rts) / _sum_f(r.get("quantity_contracts") for r in rts), 4) if _sum_f(r.get("quantity_contracts") for r in rts) else None,
            "decision_match_count": _count_non_null(r.get("decision_id") for r in rts),
            "decision_match_exact_count": sum(1 for r in rts if r.get("decision_match_type") == "exact"),
            "decision_match_fuzzy_count": sum(1 for r in rts if r.get("decision_match_type") == "fuzzy"),
            "side_fidelity_true": sum(1 for r in rts if r.get("side_fidelity") is True),
            "side_fidelity_false": sum(1 for r in rts if r.get("side_fidelity") is False),
            "avg_implementation_shortfall_cents": _mean(r.get("implementation_shortfall_cents") for r in rts),
            "avg_edge_decay_cents": _mean(r.get("edge_decay_cents") for r in rts),
        }

    overall = _metrics(round_trips)
    by_asset_out = {asset: _metrics(rts) for asset, rts in sorted(by_asset.items())}
    return overall, by_asset_out


# ---------------------------------------------------------------------------
# CSV / JSON output
# ---------------------------------------------------------------------------

def _serialize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool, list, dict)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _write_csv(path: Path, round_trips: List[Dict[str, Any]]) -> None:
    if not round_trips:
        return
    path.parent.mkdir(parents=True, exist_ok=True)

    # Flatten and pick a stable column order.
    columns = [
        "round_trip_id", "asset", "ticker", "status",
        "entry_time", "exit_time", "hold_time_seconds",
        "quantity_cc", "quantity_contracts",
        "entry_fill_id", "exit_fill_id",
        "entry_fill_present", "exit_fill_present",
        "executed_side", "executed_action",
        "entry_decision_trace_id", "decision_match_type",
        "intended_side", "side_fidelity",
        "entry_fill_price_cents", "exit_fill_price_cents",
        "entry_mid_at_fill_cents", "exit_mid_at_fill_cents",
        "entry_spread_at_fill_cents", "exit_spread_at_fill_cents",
        "entry_fill_slippage_vs_mid_cents", "exit_fill_slippage_vs_mid_cents",
        "entry_fill_vs_best_touch_cents", "exit_fill_vs_best_touch_cents",
        "entry_is_taker", "exit_is_taker",
        "entry_book_side", "exit_book_side",
        "entry_exchange_to_ingestion_latency_seconds", "exit_exchange_to_ingestion_latency_seconds",
        "entry_fee_cents", "exit_fee_cents", "total_fee_cents",
        "gross_pnl_cents", "net_pnl_cents",
        "gross_pnl_per_contract_cents", "net_pnl_per_contract_cents",
        "fee_drag_cents",
        "is_gross_win", "is_net_win",
        "market_result", "settlement_value_cents",
        "decision_id", "intended_side", "intended_price_cents",
        "model_prob_selected", "edge_at_decision_cents",
        "confidence", "confidence_valid", "confidence_source",
        "thesis", "strategy_intent", "settlement_reference", "data_state", "regime_label",
        "yes_bid_cents", "yes_ask_cents", "no_bid_cents", "no_ask_cents",
        "edge_decay_cents", "implementation_shortfall_cents",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rt in round_trips:
            row = {c: _serialize_value(rt.get(c)) for c in columns}
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _latest_file(pattern: str) -> Optional[Path]:
    matches = list(Path(".").glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_audit(
    fills_path: Path,
    round_trips_path: Path,
    telemetry_path: Path,
) -> Dict[str, Any]:
    """Build the full audit structure."""
    fills = _load_csv(fills_path)
    fills_by_id: Dict[str, Dict[str, Any]] = {f.get("fill_id"): f for f in fills if f.get("fill_id")}

    round_trips = _load_csv(round_trips_path)
    enriched_round_trips = [_enrich_round_trip(rt, fills_by_id) for rt in round_trips]

    decision_records, decision_coverage = _load_decision_telemetry(telemetry_path)
    match_result = _match_decisions_to_round_trips(enriched_round_trips, decision_records)
    decision_coverage["round_trips_matched"] = match_result["total"]
    decision_coverage["round_trips_matched_exact"] = match_result["exact"]
    decision_coverage["round_trips_matched_fuzzy"] = match_result["fuzzy"]

    overall, by_asset = _build_asset_summary(enriched_round_trips)

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fills_source": str(fills_path),
            "round_trips_source": str(round_trips_path),
            "decision_telemetry_source": str(telemetry_path) if telemetry_path.exists() else None,
            "total_round_trips": len(enriched_round_trips),
            "total_fills": len(fills),
            "decision_telemetry_coverage": decision_coverage,
            "coverage_verdict": _coverage_verdict(decision_coverage),
            "metric_definitions": {
                "exchange_to_ingestion_latency_seconds": "fill.ingested_at - fill.created_time (time from exchange trade to MERID ingestion; not decision-to-fill latency)",
                "avg_entry_spread_cents": "decision-time inside spread; null when decision log lacks yes/no bid/ask",
                "entry_fill_slippage_vs_mid_cents": "fill price vs decision-time mid; null when no decision-time book",
                "implementation_shortfall_cents": "fill price - intended decision price, positive means worse execution",
                "edge_decay_cents": "intended raw_edge_cents - realized edge (model_prob - fill_price) in cents",
            },
        },
        "overall": overall,
        "by_asset": by_asset,
        "trades": enriched_round_trips,
    }


def _coverage_verdict(coverage: Dict[str, Any]) -> str:
    if not coverage.get("exists"):
        return "decision_telemetry_missing"
    if coverage.get("selected_records", 0) == 0:
        return "no_selected_decisions_in_telemetry"
    if coverage.get("selected_with_ticker", 0) == 0 or coverage.get("selected_with_side", 0) == 0:
        return "selected_decisions_lack_ticker_or_side"
    if coverage.get("selected_with_edge_pct", 0) == 0:
        return "selected_decisions_lack_edge"
    if coverage.get("round_trips_matched", 0) == 0:
        return "decisions_present_but_unmatched_to_round_trips"
    return "partial"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 24h execution-fidelity / TCA audit")
    parser.add_argument(
        "--fills",
        type=Path,
        default=None,
        help="Path to last_24h_fills_with_pairing_and_settlement_*.csv",
    )
    parser.add_argument(
        "--round-trips",
        type=Path,
        default=None,
        help="Path to last_24h_round_trips_and_open_positions_*.csv",
    )
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=Path("logs/decision_telemetry.jsonl"),
        help="Path to decision_telemetry.jsonl",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Output JSON path",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Output CSV path",
    )
    args = parser.parse_args()

    fills_path = args.fills or _latest_file("reports/last_24h_fills_with_pairing_and_settlement_*.csv")
    round_trips_path = args.round_trips or _latest_file("reports/last_24h_round_trips_and_open_positions_*.csv")

    if not fills_path or not fills_path.exists():
        raise SystemExit(f"Fills CSV not found: {fills_path}")
    if not round_trips_path or not round_trips_path.exists():
        raise SystemExit(f"Round trips CSV not found: {round_trips_path}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = args.out_json or Path(f"reports/execution_fidelity_audit_{ts}.json")
    out_csv = args.out_csv or Path(f"reports/execution_fidelity_audit_{ts}.csv")

    audit = build_audit(fills_path, round_trips_path, args.telemetry)
    _write_json(out_json, audit)
    _write_csv(out_csv, audit["trades"])

    print(f"Wrote JSON: {out_json}")
    print(f"Wrote CSV:  {out_csv}")
    print(f"Round trips: {audit['_meta']['total_round_trips']}")
    print(f"Coverage:    {audit['_meta']['coverage_verdict']}")


if __name__ == "__main__":
    main()
