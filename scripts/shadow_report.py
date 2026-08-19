#!/usr/bin/env python3
"""Deterministic, read-only shadow-soak report for CF-RTI provenance.

Reads newline-delimited or pretty-printed JSON from ``data/shadow/cfb_rti/``
and emits a machine-readable JSON report plus a concise terminal table.
The script never writes to telemetry, configs, or runtime state.

Exit codes:
  0  Report generated; no hard safety violation found
  1  Input/schema/parsing failure in strict mode
  2  Invalid settlement provenance reached a paper-eligible candidate
  3  Invalid confidence provenance reached a paper-eligible candidate
  4  Selected probability <= 0.50 reached a paper-eligible candidate
  5  Side / V2 book side / inventory mapping mismatch
  6  Final-minute entry admitted
  7  Unreconciled lifecycle, duplicate intent, or orphan exposure
  8  Edge accounting mismatch
  9  Replay mismatch
  10 Calibration / P&L thresholds not met (with --enforce-performance)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import NormalDist, mean, median, stdev
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPORT_SCHEMA_VERSION = 1
DEFAULT_MIN_EDGE = 0.03
DEFAULT_FINAL_MINUTE_CUTOFF_S = 60.0
RTI_AGE_THRESHOLD_MS = 5000  # warn above 5s

ORDER_TERMINAL_STATUSES = {
    "filled_paper",
    "filled_live",
    "partial_live",
    "partial_fill",
    "unfilled_ioc",
    "rejected",
    "canceled",
    "expired",
}
ORDER_EXECUTION_STATUSES = {
    "filled_paper",
    "filled_live",
    "partial_live",
    "partial_fill",
}


class ReportError(Exception):
    """Fatal report-generation error."""

    def __init__(self, exit_code: int, message: str):
        super().__init__(message)
        self.exit_code = exit_code


def _coerce_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return default
        return float(value)
    if isinstance(value, Decimal):
        try:
            return float(value)
        except Exception:
            return default
    try:
        return float(value)
    except Exception:
        return default


def _coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    f = _coerce_float(value)
    if f is None:
        return default
    return int(f)


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            # epoch seconds or milliseconds
            ts = float(value)
            if ts > 1e10:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None


def _parse_cli_timestamp(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    dt = _parse_timestamp(value)
    if dt is None:
        raise ReportError(1, f"Invalid timestamp: {value}")
    return dt.timestamp()


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    k = (n - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _distribution(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "std": None, "p50": None, "p95": None, "p99": None}
    return {
        "count": len(values),
        "min": round(min(values), 9),
        "max": round(max(values), 9),
        "mean": round(mean(values), 9),
        "std": round(stdev(values), 9) if len(values) > 1 else 0.0,
        "p50": round(_percentile(values, 50.0) or 0.0, 9),
        "p95": round(_percentile(values, 95.0) or 0.0, 9),
        "p99": round(_percentile(values, 99.0) or 0.0, 9),
    }


def _kalshi_side(outcome: str, action: str) -> str:
    outcome = outcome.lower()
    action = action.lower()
    if action == "buy":
        return "BUY_YES" if outcome == "yes" else "BUY_NO"
    if action == "sell":
        return "SELL_YES" if outcome == "yes" else "SELL_NO"
    return ""


def _v2_book_side(kalshi_side: str) -> Optional[str]:
    ks = str(kalshi_side).upper().strip()
    if ks in ("BUY_YES", "SELL_NO"):
        return "bid"
    if ks in ("SELL_YES", "BUY_NO"):
        return "ask"
    return None


def _outcome_from_kalshi_side(kalshi_side: str) -> Optional[str]:
    s = str(kalshi_side).upper()
    if "YES" in s:
        return "yes"
    if "NO" in s:
        return "no"
    return None


def _p_yes_model(spot: float, strike: float, seconds_to_expiry: float, annualized_vol: float) -> Optional[float]:
    """Replay the settlement-aware normal model used by trade_decision_v2."""
    if spot <= 0 or strike <= 0 or seconds_to_expiry <= 0 or annualized_vol <= 0:
        return None
    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    if t_years <= 0:
        return None
    log_moneyness = math.log(spot / strike)
    z = log_moneyness / (annualized_vol * math.sqrt(t_years))
    return NormalDist(mu=0, sigma=1).cdf(z)


def _basis_bps(public_spot: Optional[float], rti_value: Optional[float]) -> Optional[float]:
    if public_spot is None or rti_value is None or public_spot <= 0 or rti_value <= 0:
        return None
    return 10_000.0 * math.log(public_spot / rti_value)


def _is_paper_eligible(record: Dict[str, Any]) -> bool:
    """A candidate that would have produced an order in paper/shadow mode."""
    if _coerce_str(record.get("record_type"), "candidate") != "candidate":
        return False
    if record.get("rejection_reason"):
        return False
    if _coerce_str(record.get("settlement_reference")) != "cfb_rti_live":
        return False
    if not record.get("confidence_valid"):
        return False
    if _coerce_str(record.get("confidence_source")) != "uncertainty_engine":
        return False
    p = _coerce_float(record.get("p_selected"), 0.0)
    if p <= 0.5:
        return False
    min_edge = _coerce_float(record.get("min_required_edge"), DEFAULT_MIN_EDGE)
    net_edge = _coerce_float(record.get("net_edge"))
    if net_edge is None or net_edge < min_edge:
        return False
    return True


# Ordered trust chain for the 15m decision funnel.  A record is assigned the
# first gate whose predicate fails; later gates are recorded for secondary
# diagnosis but do not change the first-failure label.
_REJECTION_GATES = [
    ("market_state_valid", lambda r: _coerce_str(r.get("data_quality")) not in ("stale", "bad", "unknown")),
    ("rti_valid", lambda r: _coerce_str(r.get("settlement_reference")) == "cfb_rti_live"),
    ("book_valid", lambda r: _coerce_float(r.get("yes_bid_cents")) is not None and _coerce_float(r.get("yes_ask_cents")) is not None and _coerce_float(r.get("no_bid_cents")) is not None and _coerce_float(r.get("no_ask_cents")) is not None),
    ("feature_vector_complete", lambda r: _coerce_float(r.get("p_yes")) is not None and _coerce_float(r.get("p_no")) is not None and _coerce_float(r.get("spot_price")) is not None and _coerce_float(r.get("target_price")) is not None and _coerce_float(r.get("seconds_to_expiry")) is not None),
    ("confidence_valid", lambda r: bool(r.get("confidence_valid")) is True and _coerce_str(r.get("confidence_source")) == "uncertainty_engine"),
    ("selected_probability_gt_50", lambda r: _coerce_float(r.get("p_selected")) is not None and _coerce_float(r.get("p_selected")) > 0.5),
    ("executable_price_in_canonical_range", lambda r: _price_in_canonical_range(r)),
    ("gross_edge_positive", lambda r: _coerce_float(r.get("gross_edge")) is not None and _coerce_float(r.get("gross_edge")) > 0.0),
    ("net_edge_ge_min", lambda r: _coerce_float(r.get("net_edge")) is not None and _coerce_float(r.get("net_edge")) >= _coerce_float(r.get("min_required_edge"), DEFAULT_MIN_EDGE)),
]


def _price_in_canonical_range(record: Dict[str, Any]) -> bool:
    """Check whether either side has executable prices inside the 10c-75c canonical band.

    The agent's pre-decision filter rejects both sides when they are both outside
    10c-75c (deep ITM/OTM).  This gate flags when the candidate's price would have
    been ineligible for that reason.
    """
    yes_bid = _coerce_float(record.get("yes_bid_cents"))
    yes_ask = _coerce_float(record.get("yes_ask_cents"))
    no_bid = _coerce_float(record.get("no_bid_cents"))
    no_ask = _coerce_float(record.get("no_ask_cents"))
    # Duality fallback: yes/no are 100 - reciprocal.
    yes_lo = yes_bid if yes_bid is not None else (100.0 - no_ask) if no_ask is not None else None
    yes_hi = yes_ask if yes_ask is not None else (100.0 - no_bid) if no_bid is not None else None
    no_lo = no_bid if no_bid is not None else (100.0 - yes_ask) if yes_ask is not None else None
    no_hi = no_ask if no_ask is not None else (100.0 - yes_bid) if yes_bid is not None else None
    yes_in = yes_lo is not None and yes_hi is not None and (yes_lo >= 10.0 or yes_hi <= 75.0)
    no_in = no_lo is not None and no_hi is not None and (no_lo >= 10.0 or no_hi <= 75.0)
    # At least one side must have an executable price in the canonical band.
    return bool(yes_in or no_in)


def _first_failure(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return the first failed gate, reason, and input snapshot for a candidate.

    The returned dict is suitable for both `rejection_funnel` aggregation and
    `candidate_rejection` record emission.
    """
    if _coerce_str(record.get("record_type"), "candidate") != "candidate":
        return {
            "first_failed_gate": "not_candidate_record",
            "reason": "record_type is not candidate",
            "input_snapshot": {},
        }

    # Pre-defined reasons that already encode a first-failure source are mapped
    # directly, then the numeric predicates are checked in gate order.
    rejection_reason = _coerce_str(record.get("rejection_reason"))
    direct_gates = {
        "no_net_edge_above_threshold": ("net_edge_ge_min", "both sides below min net edge"),
        "yes_edge_below_threshold": ("net_edge_ge_min", "yes side net edge below min"),
        "no_edge_below_threshold": ("net_edge_ge_min", "no side net edge below min"),
        "cost_basis_override_yes": ("selected_probability_gt_50", "best edge is yes but p_yes <= 0.5"),
        "cost_basis_override_no": ("selected_probability_gt_50", "best edge is no but p_no <= 0.5"),
        "invalid_confidence": ("confidence_valid", "model side qualifies but confidence invalid"),
        "expired_or_no_time": ("final_minute_cutoff", "expired or no time"),
        "final_minute_entry_disabled": ("final_minute_cutoff", "final minute entry disabled"),
    }

    if rejection_reason and not record.get("selected_outcome"):
        gate, base_reason = direct_gates.get(rejection_reason, (None, None))
        if gate:
            # For confidence-override records, the real first failure is confidence
            # if confidence is invalid; otherwise fall through to the edge/p gate.
            if gate == "confidence_valid" and not _REJECTION_GATES[4][1](record):
                pass  # will be caught below
            else:
                return {
                    "first_failed_gate": gate,
                    "reason": f"{base_reason}; rejection_reason={rejection_reason}",
                    "input_snapshot": _rejection_inputs(record),
                }

    # Evaluate the full gate chain to discover the first failure.  This is used
    # both for records that have a less specific rejection reason and as a
    # cross-check on the direct mapping above.
    for gate, predicate in _REJECTION_GATES:
        try:
            if not predicate(record):
                return {
                    "first_failed_gate": gate,
                    "reason": _gate_reason(record, gate),
                    "input_snapshot": _rejection_inputs(record),
                }
        except Exception as exc:
            return {
                "first_failed_gate": f"{gate}_predicate_error",
                "reason": f"predicate raised {exc}",
                "input_snapshot": _rejection_inputs(record),
            }

    return {
        "first_failed_gate": "paper_intent_created",
        "reason": "all gates passed; paper intent created",
        "input_snapshot": _rejection_inputs(record),
    }


def _gate_reason(record: Dict[str, Any], gate: str) -> str:
    """Human-readable reason for a specific failed gate."""
    if gate == "market_state_valid":
        return f"data_quality={record.get('data_quality')}"
    if gate == "rti_valid":
        return f"settlement_reference={record.get('settlement_reference')}"
    if gate == "book_valid":
        return "missing yes/no bid or ask cents"
    if gate == "feature_vector_complete":
        return "missing p_yes/p_no/spot/strike/expiry"
    if gate == "confidence_valid":
        reasons = record.get("confidence_reasons") or []
        return "confidence invalid: " + ", ".join(str(r) for r in reasons)
    if gate == "selected_probability_gt_50":
        p = _coerce_float(record.get("p_selected"))
        return f"p_selected={p} not > 0.5"
    if gate == "executable_price_in_canonical_range":
        return f"yes_bid={record.get('yes_bid_cents')} yes_ask={record.get('yes_ask_cents')} no_bid={record.get('no_bid_cents')} no_ask={record.get('no_ask_cents')}"
    if gate == "gross_edge_positive":
        return f"gross_edge={record.get('gross_edge')} not positive"
    if gate == "net_edge_ge_min":
        return f"net_edge={record.get('net_edge')} < min_required_edge={record.get('min_required_edge')}"
    return "unknown gate reason"


def _rejection_inputs(record: Dict[str, Any]) -> Dict[str, Any]:
    """Numeric inputs that explain why the gate failed.

    When no side is selected, the top-level ``p_selected``/``gross_edge``/``net_edge``
    fields are null.  We fall back to the preferred-side breakdown so the report
    can show how close the best candidate came to passing.
    """
    eb = record.get("edge_breakdown") or {}
    p_yes = _coerce_float(record.get("p_yes"))
    p_no = _coerce_float(record.get("p_no"))
    side = _coerce_str(eb.get("selected_side")) if isinstance(eb, dict) else None
    breakdown_p_selected = _coerce_float(eb.get("p_selected")) if isinstance(eb, dict) else None
    breakdown_gross = _coerce_float(eb.get("gross_edge")) if isinstance(eb, dict) else None
    breakdown_net = _coerce_float(eb.get("net_edge")) if isinstance(eb, dict) else None

    p_selected = _coerce_float(record.get("p_selected"))
    gross_edge = _coerce_float(record.get("gross_edge"))
    net_edge = _coerce_float(record.get("net_edge"))

    # If the record did not select a side but has a breakdown, surface the
    # preferred-side edge and probability so the funnel is meaningful.
    if side and p_yes is not None and p_no is not None and p_selected is None:
        p_selected = breakdown_p_selected
    if gross_edge is None:
        gross_edge = breakdown_gross
    if net_edge is None:
        net_edge = breakdown_net

    return {
        "run_id": record.get("run_id"),
        "decision_id": record.get("decision_id"),
        "ticker": record.get("market_ticker"),
        "asset": record.get("asset"),
        "p_yes": p_yes,
        "p_no": p_no,
        "p_selected": p_selected,
        "preferred_side": side,
        "yes_bid_cents": _coerce_float(record.get("yes_bid_cents")),
        "yes_ask_cents": _coerce_float(record.get("yes_ask_cents")),
        "no_bid_cents": _coerce_float(record.get("no_bid_cents")),
        "no_ask_cents": _coerce_float(record.get("no_ask_cents")),
        "spread_cents": _coerce_float(record.get("yes_ask_cents")) - _coerce_float(record.get("yes_bid_cents")) if _coerce_float(record.get("yes_ask_cents")) is not None and _coerce_float(record.get("yes_bid_cents")) is not None else None,
        "entry_fee_cents": _coerce_float(record.get("fee_per_contract_cents")),
        "model_risk_reserve": _coerce_float(record.get("model_risk_reserve")),
        "gross_edge": gross_edge,
        "net_edge": net_edge,
        "min_required_edge": _coerce_float(record.get("min_required_edge"), DEFAULT_MIN_EDGE),
        "confidence": _coerce_float(record.get("confidence")),
        "confidence_valid": record.get("confidence_valid"),
        "confidence_reasons": record.get("confidence_reasons"),
        "seconds_to_expiry": _coerce_float(record.get("seconds_to_expiry")),
        "settlement_reference": record.get("settlement_reference"),
        "data_quality": record.get("data_quality"),
        "regime": record.get("regime"),
    }


def _read_input_files(input_path: Path, strict: bool) -> Tuple[List[Path], List[str]]:
    files: List[Path] = []
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(input_path.rglob("*.jsonl")) + sorted(input_path.rglob("*.json"))
    else:
        if strict:
            raise ReportError(1, f"Input path does not exist: {input_path}")
    return files, []


def _load_records(files: List[Path], strict: bool) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    records: List[Dict[str, Any]] = []
    malformed = 0
    errors: List[str] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except Exception as exc:
            malformed += 1
            msg = f"Cannot read {file}: {exc}"
            if strict:
                raise ReportError(1, msg)
            errors.append(msg)
            continue

        if file.suffix.lower() == ".jsonl":
            lines = [line for line in text.splitlines() if line.strip()]
        else:
            # Single JSON object or array
            stripped = text.strip()
            if stripped.startswith("["):
                try:
                    lines = json.loads(text)
                except Exception as exc:
                    malformed += 1
                    msg = f"Invalid JSON array in {file}: {exc}"
                    if strict:
                        raise ReportError(1, msg)
                    errors.append(msg)
                    continue
            else:
                lines = [text]

        for line in lines:
            try:
                if isinstance(line, dict):
                    record = line
                else:
                    record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record is not a JSON object")
            except Exception as exc:
                malformed += 1
                msg = f"Malformed record in {file}: {exc}"
                if strict:
                    raise ReportError(1, msg)
                errors.append(msg)
                continue
            records.append(record)
    return records, malformed, errors


def _normalize_records(records: List[Dict[str, Any]], strict: bool) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    out: List[Dict[str, Any]] = []
    for i, rec in enumerate(records):
        # schema version
        schema_version = rec.get("schema_version")
        if schema_version is None:
            if strict:
                errors.append(f"Record {i} missing schema_version")
            rec["schema_version"] = 1

        # record type inference / validation
        record_type = rec.get("record_type")
        if record_type is None:
            if "order_status" in rec or "fill_count" in rec:
                record_type = "order"
            elif "settlement_outcome" in rec:
                record_type = "settlement"
            else:
                record_type = "candidate"
            if strict:
                errors.append(f"Record {i} missing record_type; inferred {record_type}")
            rec["record_type"] = record_type

        if record_type not in ("candidate", "order", "settlement"):
            msg = f"Record {i} has unknown record_type: {record_type}"
            if strict:
                errors.append(msg)
            else:
                rec["_malformed"] = True

        out.append(rec)
    return out, errors


def _extract_time_buckets(seconds_to_expiry: Optional[float]) -> List[str]:
    if seconds_to_expiry is None:
        return ["unknown"]
    if seconds_to_expiry <= 60:
        return ["<=60s", "<=5min", "<=15min"]
    if seconds_to_expiry <= 300:
        return ["<=5min", "<=15min"]
    if seconds_to_expiry <= 900:
        return ["<=15min"]
    return [">15min"]


def _build_replay(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recompute p_yes, p_no, p_selected and net edge from the record inputs.

    Returns a dict with recomputed values and the original comparison,
    or None if inputs are insufficient.
    """
    spot = _coerce_float(record.get("spot_price"))
    strike = _coerce_float(record.get("target_price"))
    seconds = _coerce_float(record.get("seconds_to_expiry"))
    vol = _coerce_float(record.get("annualized_vol"), 0.60)
    if spot is None or strike is None or seconds is None:
        return None

    p_yes = _p_yes_model(spot, strike, seconds, vol)
    if p_yes is None:
        return None
    p_no = 1.0 - p_yes
    selected = _coerce_str(record.get("selected_outcome"), "")
    p_selected = p_yes if selected == "yes" else p_no

    edge_breakdown = record.get("edge_breakdown") or {}
    executable = _coerce_float(edge_breakdown.get("executable_entry_price"))
    if executable is None:
        executable = _coerce_float(record.get("selected_outcome_price"))
    fee = _coerce_float(edge_breakdown.get("entry_fee"))
    if fee is None:
        fee = _coerce_float(record.get("fee_per_contract_cents"), 0.0) / 100.0
    exit_reserve = _coerce_float(edge_breakdown.get("exit_cost_reserve"))
    if exit_reserve is None:
        exit_reserve = _coerce_float(record.get("expected_exit_cost_yes"), 0.0) / 100.0
    model_reserve = _coerce_float(edge_breakdown.get("model_risk_reserve"))
    if model_reserve is None:
        model_reserve = _coerce_float(record.get("model_risk_reserve"), 0.0)

    if executable is not None:
        gross = p_selected - executable
        net = gross - fee - exit_reserve - model_reserve
    else:
        gross = None
        net = None

    return {
        "p_yes": round(p_yes, 9),
        "p_no": round(p_no, 9),
        "p_selected": round(p_selected, 9),
        "gross_edge": round(gross, 9) if gross is not None else None,
        "net_edge": round(net, 9) if net is not None else None,
    }


def _brier_score(pairs: List[Tuple[float, int]]) -> Optional[float]:
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _log_loss(pairs: List[Tuple[float, int]]) -> Optional[float]:
    if not pairs:
        return None
    eps = 1e-9
    total = 0.0
    for p, y in pairs:
        prob = max(eps, min(1 - eps, p))
        total += -math.log(prob if y == 1 else 1 - prob)
    return total / len(pairs)


def _calibration_buckets(pairs: List[Tuple[float, int]]) -> List[Dict[str, Any]]:
    buckets: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for p, y in pairs:
        b = int(p * 10) * 10  # 0-9, 10-19, ... 90-99
        b = min(b, 90)
        buckets[b].append((p, y))
    out = []
    for lo in sorted(buckets):
        items = buckets[lo]
        outcomes = [y for _, y in items]
        out.append({
            "bucket_lo": lo,
            "bucket_hi": lo + 10,
            "count": len(items),
            "avg_predicted": round(mean([p for p, _ in items]), 4),
            "observed_rate": round(mean(outcomes), 4),
            "resolved_yes": sum(outcomes),
            "resolved_no": len(items) - sum(outcomes),
        })
    return out


def _fmt_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    col_widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
        lines.append("  ".join(str(r[i]).ljust(col_widths[i]) for i in range(len(r))))
    return "\n".join(lines)


def _terminal_table(report: Dict[str, Any]) -> str:
    sections: List[List[List[str]]] = []

    run = report["run_integrity"]
    sections.append([
        ["Run integrity", ""],
        ["total_records", str(run["total_records"])],
        ["malformed_records", str(run["malformed_records"])],
        ["schema_versions", ", ".join(map(str, run["schema_versions"]))],
        ["time_range", f"{run['time_min']} .. {run['time_max']}"],
    ])

    rti = report["rti_health"]
    sections.append([
        ["RTI health", ""],
        ["accepted", str(rti["accepted"])],
        ["rejected", str(rti["rejected"])],
        ["rejection_reasons", ", ".join(f"{k}={v}" for k, v in rti["rejection_reason_counts"].items())],
        ["age_ms p50/p95/p99/max", f"{rti['age_ms']['p50']}/{rti['age_ms']['p95']}/{rti['age_ms']['p99']}/{rti['age_ms']['max']}"],
        ["max_stream_gap_ms", str(rti["max_stream_gap_ms"])],
    ])

    basis = report["rti_basis"]
    sections.append([
        ["RTI basis (bps)", ""],
        ["p50/p95/p99/max", f"{basis['p50']}/{basis['p95']}/{basis['p99']}/{basis['max']}"],
        ["by_asset", ", ".join(f"{k}={v['mean']:.2f}" for k, v in basis["by_asset"].items())],
    ])

    funnel = report["candidate_funnel"]
    sections.append([
        ["Candidate funnel", ""],
        ["observed", str(funnel["observed"])],
        ["valid_rti", str(funnel["valid_rti"])],
        ["valid_confidence", str(funnel["valid_confidence"])],
        ["p_selected_gt_0_5", str(funnel["p_selected_gt_0_5"])],
        ["net_edge_valid", str(funnel["net_edge_valid"])],
        ["paper_intent", str(funnel["paper_intent"])],
        ["filled", str(funnel["filled"])],
        ["terminal", str(funnel["terminal"])],
    ])

    # First-failure funnel table
    funnel = report.get("rejection_funnel")
    if funnel and funnel.get("asset_gate_table"):
        table = [["First rejection gate", *funnel["assets"], "Total", "%"]]
        for gate, row in sorted(funnel["asset_gate_table"].items(), key=lambda kv: -kv[1]["total"]):
            table.append([gate] + [str(row.get(asset, 0)) for asset in funnel["assets"]] + [str(row["total"]), str(row["pct"])])
        sections.append(table)

    hard = report["hard_fails"]
    sections.append([
        ["Hard failures", "count"],
        ["invalid_settlement_provenance", str(hard["invalid_settlement_provenance"])],
        ["invalid_confidence_provenance", str(hard["invalid_confidence_provenance"])],
        ["p_selected_le_0_50", str(hard["p_selected_le_0_50"])],
        ["side_v2_mismatch", str(hard["side_v2_mismatch"])],
        ["final_minute_admitted", str(hard["final_minute_admitted"])],
        ["unreconciled_lifecycle", str(hard["unreconciled_lifecycle"])],
        ["edge_accounting_mismatch", str(hard["edge_accounting_mismatch"])],
        ["replay_mismatch", str(hard["replay_mismatch"])],
    ])

    cal = report["calibration"]
    sections.append([
        ["Calibration", ""],
        ["settlement_samples", str(cal["settlement_samples"])],
        ["brier_score", str(cal["brier_score"])],
        ["log_loss", str(cal["log_loss"])],
    ])

    out = ["MERID Shadow-Soak Report", f"generated_at_utc: {report['generated_at_utc']}", ""]
    for sec in sections:
        out.append(_fmt_table(sec))
        out.append("")
    out.append(f"exit_code: {report['exit_code']}")
    out.append(f"exit_reason: {report.get('exit_reason', '')}")
    return "\n".join(out)


def _empty_report() -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at_utc": now,
        "telemetry_schema_versions": [],
        "run_ids": [],
        "git_revisions": [],
        "config_hashes": [],
        "source_files": [],
        "total_records": 0,
        "malformed_records": 0,
        "run_integrity": {},
        "rti_health": {},
        "rti_basis": {},
        "candidate_funnel": {},
        "rejection_funnel": {},
        "decision_quality": {},
        "side_integrity": {},
        "cost_basis_protection": {},
        "final_minute_control": {},
        "lifecycle": {},
        "replay": {},
        "paper_economics": {},
        "calibration": {},
        "hard_fails": {},
        "exit_code": 0,
        "exit_reason": "",
    }


def _build_report(
    records: List[Dict[str, Any]],
    malformed: int,
    errors: List[str],
    files: List[Path],
    since: Optional[float],
    until: Optional[float],
    enforce_performance: bool,
    min_samples: int,
    max_brier: float,
    min_pnl: float,
) -> Dict[str, Any]:
    report = _empty_report()
    report["source_files"] = [str(f) for f in files]
    report["total_records"] = len(records)
    report["malformed_records"] = malformed

    # Filter by time
    def _ts_ok(ts: Any) -> bool:
        dt = _parse_timestamp(ts)
        if dt is None:
            return True
        t = dt.timestamp()
        if since and t < since:
            return False
        if until and t > until:
            return False
        return True

    records = [r for r in records if _ts_ok(r.get("timestamp_utc"))]

    # Run integrity
    schema_versions = sorted({int(r.get("schema_version", 1)) for r in records})
    run_ids = sorted({r.get("run_id") for r in records if r.get("run_id")})
    git_revisions = sorted({r.get("git_revision") for r in records if r.get("git_revision")})
    config_hashes = sorted({r.get("config_hash") for r in records if r.get("config_hash")})
    dts = [d for d in (_parse_timestamp(r.get("timestamp_utc")) for r in records) if d]
    report["telemetry_schema_versions"] = schema_versions
    report["run_ids"] = run_ids
    report["git_revisions"] = git_revisions
    report["config_hashes"] = config_hashes
    report["run_integrity"] = {
        "total_records": len(records),
        "malformed_records": malformed,
        "schema_versions": schema_versions,
        "missing_required_fields": len(errors),
        "time_min": min(dts).isoformat().replace("+00:00", "Z") if dts else None,
        "time_max": max(dts).isoformat().replace("+00:00", "Z") if dts else None,
        "run_ids": run_ids,
        "git_revisions": git_revisions,
        "config_hashes": config_hashes,
    }

    # RTI health
    candidates = [r for r in records if _coerce_str(r.get("record_type"), "candidate") == "candidate"]
    rti_ages: List[float] = []
    rejected_reasons: Counter = Counter()
    accepted = 0
    rejected = 0
    source_mismatch = 0
    symbol_mismatch = 0

    # stream gap: per asset, per run_id, max diff between consecutive source_ts_ms
    by_asset_stream: Dict[Tuple[str, str], List[int]] = defaultdict(list)

    for r in candidates:
        settlement = _coerce_str(r.get("settlement_reference"))
        if settlement == "cfb_rti_live" and _coerce_float(r.get("cfb_value")) is not None:
            accepted += 1
            age = _coerce_float(r.get("cfb_age_ms"))
            if age is not None:
                rti_ages.append(age)
            src_ts = _coerce_int(r.get("cfb_source_ts_ms"))
            if src_ts is not None:
                by_asset_stream[(r.get("asset"), r.get("run_id"))].append(src_ts)
        else:
            rejected += 1
            reason = settlement or r.get("rejection_reason") or "unknown"
            rejected_reasons[reason] += 1

        # source/symbol mapping checks
        if r.get("cfb_source") and _coerce_str(r.get("cfb_source")) != "cf_benchmarks":
            source_mismatch += 1
        if r.get("expected_cfb_symbol") and _coerce_str(r.get("cfb_symbol")) != _coerce_str(r.get("expected_cfb_symbol")):
            symbol_mismatch += 1

    max_gap = 0
    for key, tss in by_asset_stream.items():
        tss = sorted(tss)
        for i in range(1, len(tss)):
            max_gap = max(max_gap, tss[i] - tss[i - 1])

    report["rti_health"] = {
        "accepted": accepted,
        "rejected": rejected,
        "rejection_reason_counts": dict(rejected_reasons),
        "age_ms": _distribution(rti_ages),
        "max_stream_gap_ms": max_gap,
        "source_mismatch_count": source_mismatch,
        "symbol_mismatch_count": symbol_mismatch,
    }

    # RTI basis
    basis_values: List[float] = []
    by_asset_basis: Dict[str, List[float]] = defaultdict(list)
    for r in candidates:
        public_spot = _coerce_float(r.get("public_spot"))
        rti_value = _coerce_float(r.get("cfb_value"))
        b = _basis_bps(public_spot, rti_value)
        if b is not None:
            basis_values.append(abs(b))
            by_asset_basis[_coerce_str(r.get("asset"), "unknown")].append(abs(b))

    report["rti_basis"] = {
        **_distribution(basis_values),
        "by_asset": {a: _distribution(v) for a, v in by_asset_basis.items()},
    }

    # Candidate funnel
    observed = len(candidates)
    valid_rti = 0
    valid_confidence = 0
    p_gt_half = 0
    net_edge_valid = 0

    # link orders by run_id+ticker+timestamp or decision_id
    orders = [r for r in records if _coerce_str(r.get("record_type")) == "order"]
    settlements = [r for r in records if _coerce_str(r.get("record_type")) == "settlement"]

    order_by_decision: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        did = _coerce_str(o.get("decision_id"))
        if did:
            order_by_decision[did] = o

    paper_intents = 0
    filled = 0
    terminal = 0
    for r in candidates:
        settlement = _coerce_str(r.get("settlement_reference"))
        if settlement == "cfb_rti_live":
            valid_rti += 1
        if r.get("confidence_valid") and _coerce_str(r.get("confidence_source")) == "uncertainty_engine":
            valid_confidence += 1
        p = _coerce_float(r.get("p_selected"))
        if p is not None and p > 0.5:
            p_gt_half += 1
        min_edge = _coerce_float(r.get("min_required_edge"), DEFAULT_MIN_EDGE)
        net = _coerce_float(r.get("net_edge"))
        if net is not None and net >= min_edge:
            net_edge_valid += 1
        if _is_paper_eligible(r):
            paper_intents += 1
            did = _coerce_str(r.get("decision_id"))
            if did and did in order_by_decision:
                order = order_by_decision[did]
                if order.get("order_status") in ORDER_EXECUTION_STATUSES:
                    filled += 1
                if order.get("order_status") in ORDER_TERMINAL_STATUSES:
                    terminal += 1

    report["candidate_funnel"] = {
        "observed": observed,
        "valid_rti": valid_rti,
        "valid_confidence": valid_confidence,
        "p_selected_gt_0_5": p_gt_half,
        "net_edge_valid": net_edge_valid,
        "paper_intent": paper_intents,
        "filled": filled,
        "terminal": terminal,
    }

    # Rejection funnel: first-failure gate per candidate, with mutually
    # exclusive counts and per-asset/per-gate numeric distributions.
    first_failures: List[Dict[str, Any]] = []
    gate_asset_counts: Counter = Counter()
    gate_counts: Counter = Counter()
    gate_inputs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for r in candidates:
        ff = _first_failure(r)
        first_failures.append(ff)
        gate = ff["first_failed_gate"]
        asset = _coerce_str(r.get("asset"), "unknown")
        gate_counts[gate] += 1
        gate_asset_counts[(gate, asset)] += 1
        gate_inputs[gate].append(ff["input_snapshot"])

    # Per-gate numeric distributions of the inputs just before the gate.
    gate_distributions: Dict[str, Dict[str, Any]] = {}
    for gate, inputs in gate_inputs.items():
        gate_distributions[gate] = {
            "p_yes": _distribution([i["p_yes"] for i in inputs if i["p_yes"] is not None]),
            "p_selected": _distribution([i["p_selected"] for i in inputs if i["p_selected"] is not None]),
            "yes_ask_cents": _distribution([i["yes_ask_cents"] for i in inputs if i["yes_ask_cents"] is not None]),
            "no_ask_cents": _distribution([i["no_ask_cents"] for i in inputs if i["no_ask_cents"] is not None]),
            "gross_edge": _distribution([i["gross_edge"] for i in inputs if i["gross_edge"] is not None]),
            "net_edge": _distribution([i["net_edge"] for i in inputs if i["net_edge"] is not None]),
            "model_risk_reserve": _distribution([i["model_risk_reserve"] for i in inputs if i["model_risk_reserve"] is not None]),
            "seconds_to_expiry": _distribution([i["seconds_to_expiry"] for i in inputs if i["seconds_to_expiry"] is not None]),
        }

    # Asset-by-gate table: rows are gates, columns are assets.
    assets = sorted({r.get("asset") for r in candidates if r.get("asset")})
    gate_rows: Dict[str, Any] = {}
    for gate, _ in _REJECTION_GATES + [("final_minute_cutoff", None), ("not_candidate_record", None), ("paper_intent_created", None)]:
        row = {"total": 0}
        for asset in assets:
            c = gate_asset_counts.get((gate, asset), 0)
            row[asset] = c
            row["total"] += c
        gate_rows[gate] = row

    # Add any observed gates not in the canonical list.
    for (gate, asset), c in gate_asset_counts.items():
        if gate not in gate_rows:
            if gate not in gate_rows:
                gate_rows[gate] = {a: 0 for a in assets}
                gate_rows[gate]["total"] = 0
            gate_rows[gate][asset] += c
            gate_rows[gate]["total"] += c

    # Percentages relative to total candidates.
    for gate in gate_rows:
        total = gate_rows[gate]["total"]
        gate_rows[gate]["pct"] = round(100.0 * total / len(candidates), 2) if candidates else 0.0

    report["rejection_funnel"] = {
        "first_failures": first_failures,
        "gate_counts": dict(gate_counts),
        "gate_distributions": gate_distributions,
        "asset_gate_table": gate_rows,
        "assets": assets,
        "total_candidates": len(candidates),
    }

    # Decision quality distributions
    p_yes_vals = [_coerce_float(r.get("p_yes")) for r in candidates if _coerce_float(r.get("p_yes")) is not None]
    p_no_vals = [_coerce_float(r.get("p_no")) for r in candidates if _coerce_float(r.get("p_no")) is not None]
    p_sel_vals = [_coerce_float(r.get("p_selected")) for r in candidates if _coerce_float(r.get("p_selected")) is not None]
    confidence_vals = [_coerce_float(r.get("confidence")) for r in candidates if _coerce_float(r.get("confidence")) is not None]
    net_edge_vals = [_coerce_float(r.get("net_edge")) for r in candidates if _coerce_float(r.get("net_edge")) is not None]
    gross_edge_vals = [_coerce_float(r.get("gross_edge")) for r in candidates if _coerce_float(r.get("gross_edge")) is not None]

    report["decision_quality"] = {
        "p_yes": _distribution(p_yes_vals),
        "p_no": _distribution(p_no_vals),
        "p_selected": _distribution(p_sel_vals),
        "confidence": _distribution(confidence_vals),
        "net_edge": _distribution(net_edge_vals),
        "gross_edge": _distribution(gross_edge_vals),
    }

    # Side integrity
    side_mismatches: List[Dict[str, Any]] = []
    expected_sides: Counter = Counter()
    actual_sides: Counter = Counter()

    for r in candidates:
        selected = _coerce_str(r.get("selected_outcome"))
        action = _coerce_str(r.get("selected_action"))
        if not selected or not action:
            continue
        ks = _kalshi_side(selected, action)
        v2 = _v2_book_side(ks)
        expected_sides[(selected, v2)] += 1

        # If an order exists, compare
        did = _coerce_str(r.get("decision_id"))
        order = order_by_decision.get(did)
        if order:
            actual = _coerce_str(order.get("kalshi_side"))
            actual_sides[actual] += 1
            if actual and actual != ks:
                side_mismatches.append({
                    "record_type": "candidate-order",
                    "ticker": r.get("ticker"),
                    "decision_id": did,
                    "expected_kalshi_side": ks,
                    "actual_kalshi_side": actual,
                    "selected_outcome": selected,
                    "action": action,
                })

        # Compare with explicit v2_book_side if present on candidate
        if v2 and r.get("v2_book_side") and _coerce_str(r.get("v2_book_side")) != v2:
            side_mismatches.append({
                "record_type": "candidate",
                "ticker": r.get("ticker"),
                "decision_id": did,
                "expected_v2_book_side": v2,
                "actual_v2_book_side": r.get("v2_book_side"),
            })

    report["side_integrity"] = {
        "expected_outcome_book_side_counts": {f"{k[0]}/{k[1]}": v for k, v in expected_sides.items()},
        "actual_kalshi_side_counts": dict(actual_sides),
        "mismatch_count": len(side_mismatches),
        "mismatches": side_mismatches[:10],
    }

    # Cost-basis protection
    cost_basis_keywords = ("cost_basis", "cost-basis")
    cost_basis_rejections = [r for r in candidates if any(k in _coerce_str(r.get("rejection_reason")).lower() for k in cost_basis_keywords)]
    p_le_half_paper = [r for r in candidates if _is_paper_eligible(r) and _coerce_float(r.get("p_selected"), 0.0) <= 0.5]

    report["cost_basis_protection"] = {
        "cost_basis_rejection_count": len(cost_basis_rejections),
        "p_selected_le_0_5_paper_eligible_count": len(p_le_half_paper),
        "p_selected_le_0_5_examples": [
            {"ticker": r.get("ticker"), "decision_id": r.get("decision_id"), "p_selected": r.get("p_selected")}
            for r in p_le_half_paper[:10]
        ],
    }

    # Final-minute control
    cutoff = _coerce_float(os.environ.get("MERID_FINAL_MINUTE_CUTOFF_S"), DEFAULT_FINAL_MINUTE_CUTOFF_S)
    final_minute_candidates = [r for r in candidates if _coerce_float(r.get("seconds_to_expiry"), 1e9) <= cutoff]
    final_minute_admitted = [r for r in final_minute_candidates if _is_paper_eligible(r)]
    report["final_minute_control"] = {
        "cutoff_seconds": cutoff,
        "candidate_count": len(final_minute_candidates),
        "admitted_count": len(final_minute_admitted),
        "rejection_reason_counts": Counter(r.get("rejection_reason") for r in final_minute_candidates if r.get("rejection_reason")),
        "admitted_examples": [
            {"ticker": r.get("ticker"), "decision_id": r.get("decision_id"), "seconds_to_expiry": r.get("seconds_to_expiry")}
            for r in final_minute_admitted[:10]
        ],
    }

    # Lifecycle
    orphan_count = 0
    duplicate_intents: List[Dict[str, Any]] = []
    non_terminal_orders = [o for o in orders if _coerce_str(o.get("order_status")) not in ORDER_TERMINAL_STATUSES]

    # duplicate intent: same ticker + side + price + run_id within 1ms window? use count
    order_keys: Counter = Counter()
    for o in orders:
        k = (o.get("ticker"), o.get("kalshi_side"), o.get("price_cents"), o.get("run_id"))
        order_keys[k] += 1
    for k, v in order_keys.items():
        if v > 1:
            duplicate_intents.append({"key": k, "count": v})

    for r in candidates:
        if _is_paper_eligible(r):
            did = _coerce_str(r.get("decision_id"))
            if did not in order_by_decision:
                orphan_count += 1

    report["lifecycle"] = {
        "order_count": len(orders),
        "non_terminal_order_count": len(non_terminal_orders),
        "non_terminal_examples": [
            {"ticker": o.get("ticker"), "decision_id": o.get("decision_id"), "status": o.get("order_status")}
            for o in non_terminal_orders[:10]
        ],
        "duplicate_intent_count": len(duplicate_intents),
        "duplicate_intents": duplicate_intents[:10],
        "orphan_paper_candidate_count": orphan_count,
    }

    # Edge accounting
    edge_mismatches: List[Dict[str, Any]] = []
    for r in candidates:
        bd = r.get("edge_breakdown") or {}
        stored_net = _coerce_float(r.get("net_edge"))
        stored_gross = _coerce_float(r.get("gross_edge"))
        executable = _coerce_float(bd.get("executable_entry_price"))
        p_selected = _coerce_float(r.get("p_selected"))
        if p_selected is not None and executable is not None and stored_net is not None and stored_gross is not None:
            fee = _coerce_float(bd.get("entry_fee"), 0.0)
            exit_r = _coerce_float(bd.get("exit_cost_reserve"), 0.0)
            model_r = _coerce_float(bd.get("model_risk_reserve"), 0.0)
            recomp_gross = p_selected - executable
            recomp_net = recomp_gross - fee - exit_r - model_r
            if abs(recomp_gross - stored_gross) > 1e-6 or abs(recomp_net - stored_net) > 1e-6:
                edge_mismatches.append({
                    "ticker": r.get("ticker"),
                    "decision_id": r.get("decision_id"),
                    "stored_gross": stored_gross,
                    "recomputed_gross": recomp_gross,
                    "stored_net": stored_net,
                    "recomputed_net": recomp_net,
                })

    report["edge_accounting"] = {
        "mismatch_count": len(edge_mismatches),
        "mismatches": edge_mismatches[:10],
    }

    # Replay
    replay_mismatches: List[Dict[str, Any]] = []
    replay_unavailable = 0
    replay_matched = 0
    for r in candidates:
        replay = _build_replay(r)
        if replay is None:
            replay_unavailable += 1
            continue
        p_sel = _coerce_float(r.get("p_selected"))
        net = _coerce_float(r.get("net_edge"))
        gross = _coerce_float(r.get("gross_edge"))
        ok = True
        if p_sel is not None and abs(p_sel - replay["p_selected"]) > 1e-3:
            ok = False
        if net is not None and replay["net_edge"] is not None and abs(net - replay["net_edge"]) > 1e-3:
            ok = False
        if gross is not None and replay["gross_edge"] is not None and abs(gross - replay["gross_edge"]) > 1e-3:
            ok = False
        if ok:
            replay_matched += 1
        else:
            replay_mismatches.append({
                "ticker": r.get("ticker"),
                "decision_id": r.get("decision_id"),
                "stored_p_selected": p_sel,
                "replayed_p_selected": replay["p_selected"],
                "stored_net_edge": net,
                "replayed_net_edge": replay["net_edge"],
            })

    report["replay"] = {
        "total_replayable": len(candidates) - replay_unavailable,
        "matched": replay_matched,
        "mismatched": len(replay_mismatches),
        "unavailable": replay_unavailable,
        "mismatches": replay_mismatches[:10],
    }

    # Paper economics
    pnl_by_asset: Dict[str, List[float]] = defaultdict(list)
    pnl_by_side: Dict[str, List[float]] = defaultdict(list)
    realized_pnl: List[float] = []
    expected_pnl: List[float] = []

    for o in orders:
        if o.get("order_status") in ORDER_EXECUTION_STATUSES:
            fill_price = _coerce_float(o.get("fill_price_cents"))
            exec_price = _coerce_float(o.get("price_cents"))
            count = _coerce_float(o.get("count"), 0)
            if fill_price is not None and exec_price is not None:
                slippage = (exec_price - fill_price) / 100.0 * count
                pnl_by_asset[_coerce_str(o.get("asset"), o.get("ticker", "unknown"))].append(slippage)
                side = _outcome_from_kalshi_side(_coerce_str(o.get("kalshi_side")))
                if side:
                    pnl_by_side[side].append(slippage)
                realized_pnl.append(slippage)

    for r in candidates:
        if _is_paper_eligible(r):
            net = _coerce_float(r.get("net_edge"))
            if net is not None:
                expected_pnl.append(net)

    report["paper_economics"] = {
        "realized_pnl_by_asset": {a: _distribution(v) for a, v in pnl_by_asset.items()},
        "realized_pnl_by_side": {s: _distribution(v) for s, v in pnl_by_side.items()},
        "expected_net_edge_distribution": _distribution(expected_pnl),
        "realized_pnl_distribution": _distribution(realized_pnl),
        "total_expected_net_edge": round(sum(expected_pnl), 9),
        "total_realized_pnl": round(sum(realized_pnl), 9),
    }

    # Calibration / settlement
    settlement_pairs: List[Tuple[float, int]] = []
    for s in settlements:
        did = _coerce_str(s.get("decision_id"))
        outcome = _coerce_str(s.get("settlement_outcome"))
        if did and outcome:
            c = next((r for r in candidates if _coerce_str(r.get("decision_id")) == did), None)
            if c:
                p = _coerce_float(c.get("p_selected"))
                if p is not None and outcome in ("yes", "no"):
                    selected = _coerce_str(c.get("selected_outcome"))
                    if selected == outcome:
                        settlement_pairs.append((p, 1))
                    else:
                        settlement_pairs.append((p, 0))

    brier = _brier_score(settlement_pairs)
    logloss = _log_loss(settlement_pairs)
    report["calibration"] = {
        "settlement_samples": len(settlement_pairs),
        "brier_score": round(brier, 9) if brier is not None else None,
        "log_loss": round(logloss, 9) if logloss is not None else None,
        "buckets": _calibration_buckets(settlement_pairs),
    }

    # Hard fails
    hard = {
        "invalid_settlement_provenance": 0,
        "invalid_confidence_provenance": 0,
        "p_selected_le_0_50": 0,
        "side_v2_mismatch": 0,
        "final_minute_admitted": 0,
        "unreconciled_lifecycle": 0,
        "edge_accounting_mismatch": 0,
        "replay_mismatch": 0,
    }

    candidate_by_decision = {c.get("decision_id"): c for c in candidates if c.get("decision_id")}
    emitted_candidates: Dict[str, Dict[str, Any]] = {}

    for r in candidates:
        if _is_paper_eligible(r):
            emitted_candidates[r.get("decision_id")] = r
    for o in orders:
        did = _coerce_str(o.get("decision_id"))
        if did and did in candidate_by_decision:
            emitted_candidates[did] = candidate_by_decision[did]

    for r in emitted_candidates.values():
        if _coerce_str(r.get("settlement_reference")) != "cfb_rti_live":
            hard["invalid_settlement_provenance"] += 1
        if not r.get("confidence_valid") or _coerce_str(r.get("confidence_source")) != "uncertainty_engine":
            hard["invalid_confidence_provenance"] += 1
        p = _coerce_float(r.get("p_selected"), 0.0)
        if p <= 0.5:
            hard["p_selected_le_0_50"] += 1

    hard["side_v2_mismatch"] = len(side_mismatches)
    hard["final_minute_admitted"] = len(final_minute_admitted)
    hard["unreconciled_lifecycle"] = len(non_terminal_orders) + orphan_count
    hard["edge_accounting_mismatch"] = len(edge_mismatches)
    hard["replay_mismatch"] = len(replay_mismatches)

    report["hard_fails"] = hard

    # Determine exit code
    exit_code = 0
    reasons: List[str] = []
    if malformed > 0 and errors:
        exit_code = 1
        reasons.append("input/schema/parsing failure")
    if hard["invalid_settlement_provenance"]:
        exit_code = max(exit_code, 2)
        reasons.append(f"invalid settlement provenance ({hard['invalid_settlement_provenance']})")
    if hard["invalid_confidence_provenance"]:
        exit_code = max(exit_code, 3)
        reasons.append(f"invalid confidence provenance ({hard['invalid_confidence_provenance']})")
    if hard["p_selected_le_0_50"]:
        exit_code = max(exit_code, 4)
        reasons.append(f"p_selected <= 0.50 ({hard['p_selected_le_0_50']})")
    if hard["side_v2_mismatch"]:
        exit_code = max(exit_code, 5)
        reasons.append(f"side/V2 mismatch ({hard['side_v2_mismatch']})")
    if hard["final_minute_admitted"]:
        exit_code = max(exit_code, 6)
        reasons.append(f"final-minute entry admitted ({hard['final_minute_admitted']})")
    if hard["unreconciled_lifecycle"]:
        exit_code = max(exit_code, 7)
        reasons.append(f"unreconciled lifecycle ({hard['unreconciled_lifecycle']})")
    if hard["edge_accounting_mismatch"]:
        exit_code = max(exit_code, 8)
        reasons.append(f"edge accounting mismatch ({hard['edge_accounting_mismatch']})")
    if hard["replay_mismatch"]:
        exit_code = max(exit_code, 9)
        reasons.append(f"replay mismatch ({hard['replay_mismatch']})")

    if enforce_performance:
        perf_reasons = []
        if len(settlement_pairs) < min_samples:
            perf_reasons.append(f"insufficient settlement samples ({len(settlement_pairs)} < {min_samples})")
        if brier is not None and brier > max_brier:
            perf_reasons.append(f"Brier score {brier:.4f} > {max_brier}")
        total_pnl = sum(realized_pnl) + sum(expected_pnl)
        if total_pnl < min_pnl:
            perf_reasons.append(f"total P&L {total_pnl:.4f} < {min_pnl}")
        if perf_reasons:
            exit_code = max(exit_code, 10)
            reasons.extend(perf_reasons)

    report["exit_code"] = exit_code
    report["exit_reason"] = "; ".join(reasons)
    return report


def _write_outputs(report: Dict[str, Any], output_dir: Path, run_id: Optional[str]) -> Tuple[Path, Optional[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_part = f"{run_id}_" if run_id else ""

    json_path = output_dir / f"shadow_report_{run_part}{now}.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    text_path: Optional[Path] = None
    text = _terminal_table(report)
    if text:
        text_path = output_dir / f"shadow_report_{run_part}{now}.txt"
        text_path.write_text(text, encoding="utf-8")

    # Emit candidate_rejection records for replay / dashboard use.
    rejections = report.get("rejection_funnel", {}).get("first_failures")
    if rejections:
        rejections_path = output_dir / f"candidate_rejections_{run_part}{now}.jsonl"
        with rejections_path.open("w", encoding="utf-8") as f:
            for r in rejections:
                rec = {
                    "record_type": "candidate_rejection",
                    "run_id": run_id,
                    "first_failed_gate": r["first_failed_gate"],
                    "reason": r["reason"],
                    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    **r["input_snapshot"],
                }
                f.write(json.dumps(rec, default=str) + "\n")
        return json_path, text_path, rejections_path

    return json_path, text_path, None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CF-RTI shadow-soak report")
    parser.add_argument("--input", required=True, type=Path, help="Directory or JSON/JSONL file")
    parser.add_argument("--output", type=Path, default=Path("data/shadow/reports"), help="Output directory")
    parser.add_argument("--run-id", type=str, help="Filter to a single run_id")
    parser.add_argument("--since", type=str, help="ISO timestamp or epoch lower bound")
    parser.add_argument("--until", type=str, help="ISO timestamp or epoch upper bound")
    parser.add_argument("--strict", action="store_true", help="Fail on malformed records")
    parser.add_argument("--format", type=str, default="both", choices=["json", "text", "both"])
    parser.add_argument("--enforce-performance", action="store_true", help="Fail on calibration/P&L thresholds")
    parser.add_argument("--min-samples", type=int, default=100, help="Minimum settlement samples for performance gate")
    parser.add_argument("--max-brier", type=float, default=0.25, help="Maximum Brier score allowed")
    parser.add_argument("--min-pnl", type=float, default=0.0, help="Minimum total P&L allowed")
    args = parser.parse_args(argv)

    try:
        files, _ = _read_input_files(args.input, args.strict)
        records, malformed, errors = _load_records(files, args.strict)
        records, norm_errors = _normalize_records(records, args.strict)

        if args.run_id:
            records = [r for r in records if _coerce_str(r.get("run_id")) == args.run_id]

        since = _parse_cli_timestamp(args.since) if args.since else None
        until = _parse_cli_timestamp(args.until) if args.until else None

        if args.strict and (errors or norm_errors):
            raise ReportError(1, "; ".join(errors + norm_errors))

        report = _build_report(
            records,
            malformed,
            errors + norm_errors,
            files,
            since,
            until,
            args.enforce_performance,
            args.min_samples,
            args.max_brier,
            args.min_pnl,
        )

        if args.format in ("json", "both"):
            json_path, text_path, rejections_path = _write_outputs(report, args.output, args.run_id)
            print(f"Wrote JSON: {json_path}")
            if text_path:
                print(f"Wrote text: {text_path}")
            if rejections_path:
                print(f"Wrote candidate rejections: {rejections_path}")

        if args.format == "text":
            print(_terminal_table(report))
        elif args.format == "both":
            print("\n" + _terminal_table(report))

        return report["exit_code"]
    except ReportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
