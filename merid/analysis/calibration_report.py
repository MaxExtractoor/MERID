"""Offline calibration & expectancy audit for 15m decision telemetry.

READ-ONLY analysis tool. It is never imported by the live trading loop and
performs no network, no trading-state mutation, and no writes to trading data.

Inputs
------
- Decision telemetry JSONL (schema v1) from ``logs/decision_telemetry.jsonl``.
- Settlement outcomes JSONL keyed by ticker:
  ``{"ticker": "KXBTC15M-...", "outcome": "yes"|"no"|1|0|100}``.
  (The live system does not durably persist settlements; this file can be
  produced by a separate settlement export. Records without an outcome are
  counted as unresolved and excluded from calibration, never treated as 0.)
- Optional fills SQLite DB (``data/kalshi_fills.db``), opened read-only, for
  realized fee-inclusive P&L per ticker.

Terminology (per 2026-08-17 audit finding)
------------------------------------------
The strategy's "model probability" is *derived* from the market price being
evaluated (``model_prob = market_price + capped_edge``). It is NOT an
independently estimated probability. This report therefore labels it
``derived_model_probability`` and measures ``settlement_calibration`` — the
empirical relationship between that derived number and actual resolution.
A good Brier score here is NOT proof of tradable edge: the decisive metrics
are post-cost realized expectancy and predicted-edge vs realized-edge gaps.

CLI
---
    python -m merid.analysis.calibration_report \
        --telemetry logs/decision_telemetry.jsonl \
        --outcomes logs/settlement_outcomes.jsonl \
        --fills-db data/kalshi_fills.db \
        --json-out reports/calibration_report.json
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from merid.risk.probability.calibration_diagnostics import (
    brier_score,
    calibration_summary,
    expected_calibration_error,
    reliability_curve,
)

REPORT_SCHEMA_VERSION = 1

PRICE_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("10-24c", 10.0, 24.999),
    ("25-39c", 25.0, 39.999),
    ("40-49c", 40.0, 49.999),
    ("50-65c", 50.0, 65.999),
    ("66-75c", 66.0, 75.999),
    ("out-of-range", -math.inf, math.inf),  # catch-all, evaluated last
)

TTE_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("0-3min", 0.0, 3.0),
    ("3-7min", 3.0, 7.0),
    ("7-11min", 7.0, 11.0),
    ("11-15min", 11.0, 15.001),
)

SPREAD_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("0-1c", 0.0, 1.0),
    ("2-3c", 1.0, 3.0),
    ("4-6c", 3.0, 6.0),
    (">6c", 6.0, math.inf),
)

DEPTH_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("0-9", 0.0, 9.999),
    ("10-49", 10.0, 49.999),
    ("50-199", 50.0, 199.999),
    (">=200", 200.0, math.inf),
)

# Model-predicted edge vs. the market price of the selected side.  Positive
# means the model thinks the selected side is underpriced by the market;
# negative means the model thinks it is overpriced.  The edge-calibration
# question is whether the model's directional deviation from the market beats
# the market's implied probability.
EDGE_SIGN_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("underpriced", 0.0, math.inf),      # model_p > market_p
    ("overpriced", -math.inf, 0.0),       # model_p < market_p
    ("no_edge", -1e-12, 1e-12),           # model_p ~= market_p
)

EDGE_MAGNITUDE_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("0-2c", 0.0, 2.0),
    ("2-5c", 2.0, 5.0),
    ("5-10c", 5.0, 10.0),
    ("10-20c", 10.0, 20.0),
    (">20c", 20.0, math.inf),
)


# ---------------------------------------------------------------------------
# Pure metric helpers
# ---------------------------------------------------------------------------

def brier(pairs: Sequence[Tuple[float, int]]) -> Optional[float]:
    """mean((p - y)^2). Returns None for empty input."""
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def calibration_bias(pairs: Sequence[Tuple[float, int]]) -> Optional[float]:
    """mean(p - y): positive = overconfident. None for empty input."""
    if not pairs:
        return None
    return sum(p - y for p, y in pairs) / len(pairs)


def expectancy(pnls: Sequence[float]) -> Optional[float]:
    """mean realized P&L per trade (fee-inclusive). None for empty input."""
    if not pnls:
        return None
    return sum(pnls) / len(pnls)


def _bucket(value: Optional[float], buckets: Sequence[Tuple[str, float, float]]) -> Optional[str]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    for name, lo, hi in buckets:
        if name == "out-of-range":
            continue
        if lo <= v <= hi:
            return name
    return "out-of-range"


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _rate(numer: int, denom: int) -> Optional[float]:
    return (numer / denom) if denom else None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_decision_records(path: str | Path) -> List[Dict[str, Any]]:
    """Load decision_record rows from the telemetry JSONL. Skips malformed lines."""
    records: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return records
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("type") == "decision_record":
                records.append(row)
    return records


def _normalize_outcome(value: Any) -> Optional[int]:
    """Normalize a settlement outcome to 1 (YES) / 0 (NO). None if unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if value >= 99.5 or value == 1:
            return 1
        if value <= 0.5:
            return 0
        return None
    s = str(value).strip().lower()
    if s in ("yes", "y", "1", "true"):
        return 1
    if s in ("no", "n", "0", "false"):
        return 0
    return None


def load_outcomes(path: str | Path) -> Dict[str, int]:
    """Load settlement outcomes keyed by ticker. Unknown outcomes are dropped."""
    outcomes: Dict[str, int] = {}
    p = Path(path)
    if not p.exists():
        return outcomes
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ticker = row.get("ticker") or row.get("market_ticker") or row.get("market_id")
            outcome = _normalize_outcome(row.get("outcome", row.get("settlement", row.get("result"))))
            if ticker and outcome is not None:
                outcomes[str(ticker)] = outcome
    return outcomes


def load_fill_pnls(fills_db_path: str | Path) -> Dict[str, Dict[str, float]]:
    """Realized fee-inclusive P&L per ticker from the fills SQLite ledger.

    Returns {ticker: {"realized_pnl_dollars": float, "fees_dollars": float,
                      "fills": int}}. Read-only connection; returns {} if the
    DB is missing or unreadable.
    """
    p = Path(fills_db_path)
    if not p.exists():
        return {}
    uri = f"file:{p.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT market_ticker,
                   COALESCE(SUM(CAST(proceeds_dollars AS REAL)), 0.0),
                   COALESCE(SUM(CAST(fee_cost AS REAL)), 0.0),
                   COUNT(*)
            FROM kalshi_fills
            GROUP BY market_ticker
            """
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return {}
    conn.close()
    result: Dict[str, Dict[str, float]] = {}
    for ticker, pnl, fees, n in rows:
        if ticker:
            result[str(ticker)] = {
                "realized_pnl_dollars": float(pnl or 0.0),
                "fees_dollars": float(fees or 0.0),
                "fills": int(n),
            }
    return result


# ---------------------------------------------------------------------------
# Slice builder
# ---------------------------------------------------------------------------

def _model_p(row: Dict[str, Any]) -> Optional[float]:
    return row.get("model_prob_selected", row.get("model_p_selected"))


def _market_p(row: Dict[str, Any]) -> Optional[float]:
    return row.get("market_p_selected")


def _slice_metrics(name: str, rows: List[Dict[str, Any]], n_bins: int = 5) -> Dict[str, Any]:
    """Metrics for one slice of joined (telemetry + outcome + pnl) rows.

    The canonical calibration metrics (Brier, ECE, reliability) are computed
    by merid.risk.probability.calibration_diagnostics on the exact
    (predicted probability, realized outcome, market reference price) triple.
    """
    n = len(rows)
    resolved = [r for r in rows if r.get("y") is not None]
    probs_model = [_model_p(r) for r in resolved if _model_p(r) is not None]
    outs_model = [r["y"] for r in resolved if _model_p(r) is not None]
    probs_market = [_market_p(r) for r in resolved if _market_p(r) is not None]
    outs_market = [r["y"] for r in resolved if _market_p(r) is not None]
    pnls = [r["realized_pnl_dollars"] for r in rows if r.get("realized_pnl_dollars") is not None]
    candidates = [r for r in rows if r.get("candidate_generated")]
    selected = [r for r in rows if r.get("allocator_selected")]

    # Edge: predicted = model - market; realized = y - market.
    edge_pred = [
        _model_p(r) - _market_p(r)
        for r in resolved
        if _model_p(r) is not None and _market_p(r) is not None
    ]
    edge_real = [
        r["y"] - _market_p(r)
        for r in resolved
        if _market_p(r) is not None
    ]
    edge_gaps = [p - r for p, r in zip(edge_pred, edge_real)]

    # Canonical calibration diagnostics in side space.
    n_bins = min(n_bins, len(probs_model)) if probs_model else n_bins
    cal_model = calibration_summary(probs_model, outs_model, n_bins=n_bins, label="model")
    cal_market = calibration_summary(probs_market, outs_market, n_bins=n_bins, label="market")

    brier_model = cal_model["brier_score"]
    brier_mkt = cal_market["brier_score"]
    brier_skill = None
    if brier_mkt is not None and brier_mkt > 0 and brier_model is not None and math.isfinite(brier_model):
        brier_skill = 1.0 - (brier_model / brier_mkt)

    return {
        "slice": name,
        "evaluated": n,
        "resolved": len(resolved),
        "candidates": len(candidates),
        "candidate_rate": _rate(len(candidates), n),
        "selected": len(selected),
        "selected_rate": _rate(len(selected), n),
        "mean_derived_model_probability": _mean(_model_p(r) for r in rows),
        "mean_market_probability": _mean(_market_p(r) for r in rows),
        "mean_raw_edge_cents": _mean(r.get("raw_edge_cents") for r in rows),
        "mean_robust_ev_cents": _mean(r.get("robust_ev_cents") for r in rows),
        # settlement_calibration: Brier/bias of the DERIVED probability vs outcome
        "brier_derived_model": brier_model,
        "brier_market_reference": brier_mkt,
        "brier_skill_score": brier_skill,
        "calibration_bias": calibration_bias(list(zip(probs_model, outs_model))),
        "expected_calibration_error": cal_model["expected_calibration_error"],
        "reliability_curve": {
            "bin_centers": cal_model["bin_centers"],
            "bin_observed_rates": cal_model["bin_observed_rates"],
            "bin_counts": cal_model["bin_counts"],
        },
        # Edge calibration: does the model's deviation from market price predict
        # the realized deviation from market price?
        "mean_predicted_edge": _mean(edge_pred),
        "mean_realized_edge": _mean(edge_real),
        "mean_predicted_minus_realized_edge": _mean(edge_gaps),
        "trades_with_pnl": len(pnls),
        "fee_inclusive_expectancy_dollars": expectancy(pnls),
        "total_realized_pnl_dollars": sum(pnls) if pnls else None,
        "top_rejection_reasons": _top_rejections(rows),
        "insufficient_sample": len(resolved) < 50,
        "min_required_resolved": 50,
    }


def _top_rejections(rows: List[Dict[str, Any]], limit: int = 3) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        reason = r.get("rejection_reason")
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:limit])


def _group(rows: List[Dict[str, Any]], key_fn) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = key_fn(r)
        if k is None:
            continue
        groups.setdefault(str(k), []).append(r)
    return groups


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _spread_cents(row: Dict[str, Any]) -> Optional[float]:
    """Selected-side spread: yes_ask - yes_bid (or NO side). None if unavailable.

    Missing bid/ask stays None (unavailable), never 0 — absent freshness or
    quote data must not be misread as a zero spread.
    """
    side = str(row.get("selected_side") or "").lower()
    if side == "no":
        ask, bid = row.get("no_ask_cents"), row.get("no_bid_cents")
    else:
        ask, bid = row.get("yes_ask_cents"), row.get("yes_bid_cents")
    if ask is None or bid is None:
        return None
    try:
        return float(ask) - float(bid)
    except (TypeError, ValueError):
        return None


def _edge_sign(row: Dict[str, Any]) -> Optional[str]:
    """Return 'underpriced' if model_p > market_p, 'overpriced' if <, else None.

    The sign of (model_p - market_p) is the model's directional call: positive
    means the selected side is cheaper than the model's fair value, negative
    means it is richer.
    """
    mp = _model_p(row)
    mkt = _market_p(row)
    if mp is None or mkt is None:
        return None
    if mp > mkt + 1e-9:
        return "underpriced"
    if mp < mkt - 1e-9:
        return "overpriced"
    return "no_edge"


def _edge_magnitude(row: Dict[str, Any]) -> Optional[str]:
    """Bucket the absolute model-market edge in probability space (0-1)."""
    mp = _model_p(row)
    mkt = _market_p(row)
    if mp is None or mkt is None:
        return None
    return _bucket(abs(mp - mkt) * 100.0, EDGE_MAGNITUDE_BUCKETS)


def join_rows(
    records: List[Dict[str, Any]],
    outcomes: Dict[str, int],
    fill_pnls: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Join telemetry records with outcomes and realized P&L by ticker."""
    rows: List[Dict[str, Any]] = []
    for rec in records:
        ticker = rec.get("ticker")
        side = str(rec.get("selected_side") or "").lower()
        y: Optional[int] = None
        if ticker in outcomes and side in ("yes", "no"):
            outcome_yes = outcomes[ticker]
            y = outcome_yes if side == "yes" else 1 - outcome_yes
        pnl_info = fill_pnls.get(ticker) if ticker else None
        row = dict(rec)
        row["y"] = y
        row["resolved"] = y is not None
        row["realized_pnl_dollars"] = pnl_info["realized_pnl_dollars"] if pnl_info else None
        row["spread_cents"] = _spread_cents(rec)
        rows.append(row)
    return rows


def dedupe_latest_per_market(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse repeated per-cycle rows to the latest row per (ticker, side).

    The allocator re-selects the same candidate every cycle within a 15m
    window, so raw rows repeat a market's model/market probabilities dozens
    of times. Calibration and expectancy must be computed on one row per
    market decision; otherwise a single window dominates the Brier score and
    bias. Rows without ticker/side are kept as-is.
    """
    latest: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    passthrough: List[Dict[str, Any]] = []
    for row in rows:
        key = (row.get("ticker"), str(row.get("selected_side") or "").lower())
        if not key[0] or not key[1]:
            passthrough.append(row)
            continue
        if key not in latest:
            order.append(key)
        latest[key] = row  # later rows overwrite: latest event wins
    return [latest[k] for k in order] + passthrough


MIN_SAMPLE_REQUIRED = 50
SETTLEMENT_GRACE_MINUTES = 30.0


def _parse_iso_ts(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _expected_settlement_ts(row: Dict[str, Any]) -> Optional[float]:
    """Approximate settlement time: decision timestamp + minutes_to_expiry."""
    ts = _parse_iso_ts(row.get("event_ts_utc"))
    tte = row.get("minutes_to_expiry")
    if ts is None or tte is None:
        return None
    try:
        return ts + float(tte) * 60.0
    except (TypeError, ValueError):
        return None


def _resolution_state(row: Dict[str, Any], now_ts: float,
                      grace_seconds: float = SETTLEMENT_GRACE_MINUTES * 60.0) -> Tuple[str, str]:
    """(state, reason) for a calibration-eligible row without an outcome.

    States: pending (still inside settlement grace), unresolvable (past grace
    with a coded reason).
    """
    expected = _expected_settlement_ts(row)
    if expected is None:
        return "unresolvable", "missing_expiry_estimate"
    if now_ts < expected + grace_seconds:
        return "pending", "awaiting_settlement"
    return "unresolvable", "no_outcome_record_past_grace"


def build_report(
    records: List[Dict[str, Any]],
    outcomes: Dict[str, int],
    fill_pnls: Dict[str, Dict[str, float]],
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the full calibration audit report as a JSON-safe dict.

    Two-section output:
    - decision_funnel: raw cycle accounting from evaluation to execution.
      Pre-side rejections are counted here and NEVER enter calibration.
    - calibration cohort: one row per (ticker, side) market decision with a
      formed side; Brier/bias/edge-gap computed on resolved records only.
    """
    import time as _time
    if now_ts is None:
        now_ts = _time.time()

    raw_rows = join_rows(records, outcomes, fill_pnls)
    deduped = dedupe_latest_per_market(raw_rows)

    # --- Funnel -------------------------------------------------------------
    pre_side = [r for r in deduped if not r.get("ticker") or not r.get("selected_side")]
    sided = [r for r in deduped if r.get("ticker") and r.get("selected_side")]
    # Eligibility: a resolved row needs ticker, side, and a pair of
    # probabilities. An unresolved row additionally needs event_ts_utc so
    # expected settlement and grace can be computed for pending/unresolvable.
    eligible = [
        r for r in sided
        if _model_p(r) is not None
        and _market_p(r) is not None
        and (r.get("decision_id") or r.get("ticker"))
        and (r.get("resolved") or r.get("event_ts_utc"))
    ]
    executed = [r for r in eligible if r.get("allocator_selected")]
    resolved_rows = [r for r in eligible if r.get("resolved")]
    pending: List[Dict[str, Any]] = []
    unresolvable: List[Dict[str, Any]] = []
    for r in eligible:
        if r.get("resolved"):
            continue
        state, reason = _resolution_state(r, now_ts)
        rec = {
            "ticker": r.get("ticker"),
            "side": r.get("selected_side"),
            "decision_ts": r.get("event_ts_utc"),
            "expected_settlement_ts": _expected_settlement_ts(r),
            "age_minutes": round((now_ts - (_parse_iso_ts(r.get("event_ts_utc")) or now_ts)) / 60.0, 1),
            "resolution_state": state,
            "reason": reason,
        }
        (pending if state == "pending" else unresolvable).append(rec)

    rows = eligible  # calibration cohort
    unresolved = sum(1 for r in rows if not r["resolved"])

    slices: Dict[str, Any] = {"overall": _slice_metrics("overall", rows)}

    for key, key_fn, buckets in [
        ("by_asset", lambda r: r.get("asset"), None),
        ("by_side", lambda r: (str(r.get("selected_side") or "").lower() or None), None),
        ("by_price_bucket", lambda r: _bucket(
            _market_p(r) * 100 if _market_p(r) is not None else None,
            PRICE_BUCKETS), PRICE_BUCKETS),
        ("by_time_to_expiry", lambda r: _bucket(r.get("minutes_to_expiry"), TTE_BUCKETS), TTE_BUCKETS),
        ("by_spread_bucket", lambda r: _bucket(r.get("spread_cents"), SPREAD_BUCKETS), SPREAD_BUCKETS),
        ("by_depth_bucket", lambda r: _bucket(
            r.get("yes_depth") if str(r.get("selected_side") or "").lower() != "no" else r.get("no_depth"),
            DEPTH_BUCKETS), DEPTH_BUCKETS),
        ("by_edge_sign", _edge_sign, None),
        ("by_edge_magnitude", _edge_magnitude, EDGE_MAGNITUDE_BUCKETS),
    ]:
        groups = _group(rows, key_fn)
        ordered = [b[0] for b in buckets] if buckets else sorted(groups)
        slices[key] = {
            name: _slice_metrics(name, groups[name])
            for name in ordered
            if name in groups
        }

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "terminology": {
            "derived_model_probability": (
                "model_prob as used by the strategy = market_price + capped edge. "
                "Constructed from the market price being evaluated; NOT an "
                "independently estimated probability."
            ),
            "settlement_calibration": (
                "empirical relationship between the derived probability and actual "
                "resolution. A good Brier score is not proof of tradable edge; the "
                "decisive metrics are fee_inclusive_expectancy and "
                "mean_predicted_minus_realized_edge."
            ),
            "edge_calibration": (
                "slicing by the sign and magnitude of (model_p - market_p) on the "
                "selected side. Tests whether the model's directional deviation "
                "from the market predicts the realized deviation."
            ),
        },
        "counts": {
            "evaluated_records": len(raw_rows),
            "unique_decision_markets": len(deduped),
            "outcomes_loaded": len(outcomes),
            "tickers_with_fills": len(fill_pnls),
        },
        "decision_funnel": {
            "evaluated_cycles": len(raw_rows),
            "pre_side_rejections": len(pre_side),
            "sided_decision_records": len(sided),
            "calibration_eligible_records": len(eligible),
            "resolution_joinable_records": len(eligible),
            "resolved_records": len(resolved_rows),
            "pending_resolution_records": len(pending),
            "unresolvable_records": len(unresolvable),
            "executed_records": len(executed),
        },
        "resolution_reconciliation": {
            "settlement_grace_minutes": SETTLEMENT_GRACE_MINUTES,
            "pending": pending,
            "unresolvable": unresolvable,
        },
        "slices": slices,
    }


def render_text(report: Dict[str, Any]) -> str:
    """Human-readable summary of the report."""
    lines = ["CALIBRATION AUDIT REPORT", "=" * 60]

    # Section 1: decision funnel (raw accounting; includes pre-side rejects)
    f = report["decision_funnel"]
    lines.append("DECISION FUNNEL")
    lines.append(f"  evaluated_cycles={f['evaluated_cycles']}")
    lines.append(f"  pre_side_rejected={f['pre_side_rejections']}")
    lines.append(f"  sided_decisions={f['sided_decision_records']}")
    lines.append(f"  calibration_eligible={f['calibration_eligible_records']}")
    lines.append(f"  pending_resolution={f['pending_resolution_records']}")
    lines.append(f"  unresolvable={f['unresolvable_records']}")
    lines.append(f"  resolved={f['resolved_records']}")
    lines.append(f"  executed={f['executed_records']}")
    lines.append("")

    # Reconciliation table for pending/unresolvable rows
    recon = report.get("resolution_reconciliation", {})
    pending_rows = recon.get("pending") or []
    unres_rows = recon.get("unresolvable") or []
    if pending_rows or unres_rows:
        lines.append(f"RESOLUTION RECONCILIATION (grace={recon.get('settlement_grace_minutes')}min)")
        for r in (pending_rows + unres_rows)[:50]:
            lines.append(
                f"  {r.get('ticker')} | {r.get('side')} | age={r.get('age_minutes')}m "
                f"| {r.get('resolution_state')} | {r.get('reason')}"
            )
        if len(pending_rows) + len(unres_rows) > 50:
            lines.append(f"  ... {len(pending_rows) + len(unres_rows) - 50} more")
        lines.append("")

    # Section 2: calibration cohort (sided, eligible, deduped per market)
    c = report["counts"]
    lines.append("CALIBRATION COHORT (metrics on resolved records only)")
    lines.append(
        f"  unique_markets={c['unique_decision_markets']} "
        f"eligible={f['calibration_eligible_records']} "
        f"outcomes_loaded={c['outcomes_loaded']} "
        f"tickers_with_fills={c['tickers_with_fills']}"
    )
    lines.append("")
    lines.append("NOTE: model probabilities are DERIVED (quoted market price + capped edge).")
    lines.append("Judge edge by fee-inclusive expectancy, predicted-vs-realized edge,")
    lines.append("and by_edge_sign/magnitude slices. Brier/ECE only prove calibration;")
    lines.append("a calibrated model that agrees with the market has no tradable edge.")
    lines.append("")

    def _emit(section: str, metrics: Dict[str, Any]) -> None:
        parts = [f"[{section}] n={metrics['evaluated']} resolved={metrics['resolved']}"]
        if metrics.get("insufficient_sample"):
            parts.append(f"insufficient_sample=true min_required={metrics.get('min_required_resolved', 50)}")
        if metrics.get("brier_derived_model") is not None:
            parts.append(f"brier={metrics['brier_derived_model']:.4f}")
        if metrics.get("brier_market_reference") is not None:
            parts.append(f"mkt_brier={metrics['brier_market_reference']:.4f}")
        if metrics.get("brier_skill_score") is not None:
            parts.append(f"skill={metrics['brier_skill_score']:+.4f}")
        if metrics.get("expected_calibration_error") is not None:
            parts.append(f"ece={metrics['expected_calibration_error']:.4f}")
        if metrics.get("calibration_bias") is not None:
            parts.append(f"bias={metrics['calibration_bias']:+.4f}")
        if metrics.get("mean_predicted_edge") is not None:
            parts.append(f"pred_edge={metrics['mean_predicted_edge']:+.4f}")
        if metrics.get("mean_realized_edge") is not None:
            parts.append(f"real_edge={metrics['mean_realized_edge']:+.4f}")
        if metrics.get("fee_inclusive_expectancy_dollars") is not None:
            parts.append(f"expectancy=${metrics['fee_inclusive_expectancy_dollars']:+.4f}")
        if metrics.get("mean_predicted_minus_realized_edge") is not None:
            parts.append(f"pred-real_edge={metrics['mean_predicted_minus_realized_edge']:+.4f}")
        if metrics.get("candidate_rate") is not None:
            parts.append(f"cand_rate={metrics['candidate_rate']:.2f}")
        lines.append(" ".join(parts))
        top = metrics.get("top_rejection_reasons")
        if top:
            lines.append("    rejections: " + ", ".join(f"{k}={v}" for k, v in top.items()))

    _emit("overall", report["slices"]["overall"])
    for section in ("by_asset", "by_side", "by_price_bucket", "by_time_to_expiry",
                    "by_spread_bucket", "by_depth_bucket",
                    "by_edge_sign", "by_edge_magnitude"):
        group = report["slices"].get(section) or {}
        if not group:
            continue
        lines.append("")
        lines.append(f"-- {section} " + "-" * max(0, 55 - len(section)))
        for name in sorted(group):
            _emit(name, group[name])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline calibration & expectancy audit")
    parser.add_argument("--telemetry", default="logs/decision_telemetry.jsonl")
    parser.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    parser.add_argument("--fills-db", default="data/kalshi_fills.db")
    parser.add_argument("--json-out", default=None, help="Optional path for the JSON report")
    args = parser.parse_args(argv)

    records = load_decision_records(args.telemetry)
    outcomes = load_outcomes(args.outcomes)
    fill_pnls = load_fill_pnls(args.fills_db)
    report = build_report(records, outcomes, fill_pnls)

    print(render_text(report))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nJSON report written to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
