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
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from merid.risk.probability.calibration_diagnostics import (
    brier_score,
    calibration_summary,
    expected_calibration_error,
    reliability_curve,
    roc_auc_score,
)

try:
    from merid.risk.probability.platt_scaler import PlattScaler
except Exception:
    PlattScaler = None  # type: ignore

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

# TTE band for the edge-admission cohort.  The edge test should focus on the
# TTE at which the candidate was first admitted, before convergence near expiry
# erodes the signal.  5-10 min is the primary capturable window.
TTE_ADMISSION_BUCKETS: Sequence[Tuple[str, float, float]] = (
    ("0-5min", 0.0, 5.0),
    ("5-10min", 5.0, 10.0),
    ("10-15min", 10.0, 15.001),
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


def _std(values: Sequence[float]) -> Optional[float]:
    """Sample standard deviation. Returns None for fewer than 2 points."""
    if len(values) < 2:
        return None
    try:
        return statistics.stdev(values)
    except statistics.StatisticsError:
        return None


def _t_stat(mean: Optional[float], std: Optional[float], n: int) -> Optional[float]:
    """One-sample t-statistic: mean / (std / sqrt(n)). None if not computable."""
    if mean is None or std is None or n <= 1 or std <= 0:
        return None
    return mean / (std / math.sqrt(n))


def _edge_stats(values: Sequence[float], label: str) -> Dict[str, Any]:
    """Mean, std, standard error, t-stat, and n for an edge sample."""
    n = len(values)
    mean = sum(values) / n if n else None
    std = _std(values)
    se = std / math.sqrt(n) if std is not None and n > 1 else None
    return {
        f"{label}_n": n,
        f"{label}_mean": mean,
        f"{label}_std": std,
        f"{label}_se": se,
        f"{label}_t_stat": _t_stat(mean, std, n),
    }


def _predicted_cost_prob(row: Dict[str, Any]) -> float:
    """Model-predicted round-trip cost in probability units (0-1) per contract.

    ``all_in_cost_cents`` in telemetry is the full cost basis
    (held_price + exchange fee + impact reserve).  The round-trip *cost*
    is that basis minus the held price.  We prefer explicit fee/impact
    fields when present, then fall back to subtracting the recorded market
    probability in cents, and finally use the raw all_in_cost_cents only
    as a last resort (which may overstate cost if the held price is included).
    """
    # Explicit fee/impact breakdown is the most accurate cost.
    entry_fee = float(row.get("entry_fee_cents") or 0.0)
    exit_fee = float(row.get("exit_fee_reserve_cents") or row.get("exit_cost_reserve_cents") or 0.0)
    entry_impact = float(row.get("expected_entry_impact_cents") or row.get("impact_reserve_cents") or 0.0)
    exit_impact = float(row.get("expected_exit_impact_reserve_cents") or row.get("exit_impact_reserve_cents") or 0.0)
    if any((entry_fee, exit_fee, entry_impact, exit_impact)):
        return (entry_fee + exit_fee + entry_impact + exit_impact) / 100.0

    all_in = row.get("all_in_cost_cents")
    market_p = _market_p(row)
    if all_in is not None and market_p is not None:
        try:
            v = float(all_in) - float(market_p) * 100.0
            if math.isfinite(v) and v >= 0:
                return v / 100.0
        except (TypeError, ValueError):
            pass

    if all_in is not None:
        try:
            v = float(all_in)
            if math.isfinite(v) and v >= 0:
                return v / 100.0
        except (TypeError, ValueError):
            pass

    return 0.0


def _actual_cost_prob(row: Dict[str, Any]) -> Optional[float]:
    """Realized cost per contract in probability units from the fills ledger.

    Returns None if no fills are recorded for the ticker.
    """
    actual = row.get("actual_cost_per_contract_dollars")
    if actual is not None:
        try:
            v = float(actual)
            if math.isfinite(v) and v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    return None


def _cost_prob(row: Dict[str, Any]) -> float:
    """Best available round-trip cost in probability units for the selected side.

    Prefers the realized fee cost per contract from actual fills; falls back to
    the model's predicted cost otherwise.  The cost is per contract in cents and
    is subtracted from gross edge to judge tradeable net edge.
    """
    actual = _actual_cost_prob(row)
    if actual is not None:
        return actual
    return _predicted_cost_prob(row)


def _platt_recalibration(probs: List[float], outcomes: List[int]) -> Dict[str, Any]:
    """Fit Platt scaling and report before/after metrics.

    Uses the logit of the raw probability as the input to the Platt scaler.
    AUC is reported separately because a monotonic Platt transform cannot
    change the ranking of the probabilities (discrimination is preserved).
    """
    if PlattScaler is None or len(probs) < 10 or len(set(outcomes)) < 2:
        return {"error": "insufficient_data_or_missing_dependency"}

    logits = []
    for p in probs:
        # Bounded logit to avoid infinities at the boundary.
        pclip = max(0.01, min(0.99, float(p)))
        logits.append(math.log(pclip / (1.0 - pclip)))

    try:
        scaler = PlattScaler(min_samples=5)
        scaler.fit(logits, outcomes)
        cal_probs = scaler.predict(logits)
    except Exception as exc:
        return {"error": str(exc)}

    a, b = scaler.get_parameters() or (None, None)
    return {
        "platt_a": float(a) if a is not None else None,
        "platt_b": float(b) if b is not None else None,
        "n_samples": len(probs),
        "brier_raw": brier_score(probs, outcomes),
        "brier_calibrated": brier_score(cal_probs, outcomes),
        "ece_raw": expected_calibration_error(probs, outcomes, n_bins=5),
        "ece_calibrated": expected_calibration_error(cal_probs, outcomes, n_bins=5),
        "auc_raw": roc_auc_score(probs, outcomes),
        "auc_calibrated": roc_auc_score(cal_probs, outcomes),
        "note": (
            "Platt scaling improves Brier/ECE (calibration) but leaves AUC "
            "unchanged because it is a monotonic transform.  If AUC does not "
            "exceed the market reference, recalibration will not create edge."
        ),
    }


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

    Returns a dict keyed by market_ticker with:
        - realized_pnl_dollars: legacy cash-flow sum (proceeds, net of fee for sells)
        - settlement_pnl_linear_a, settlement_pnl_linear_b: coefficients for
          computing settlement PnL = a + b * outcome_yes from canonical fills
        - cash_flow_dollars: gross proceeds sum
        - fees_dollars: total fees paid
        - fills: number of fill rows
        - contracts: total contracts (count_fp) traded
        - actual_cost_per_contract_dollars: fees / contracts (None if unknown)

    Read-only connection; returns {} if the DB is missing or unreadable.
    """
    p = Path(fills_db_path)
    if not p.exists():
        return {}
    uri = f"file:{p.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}

    # Try the canonical fill query first.  Older test DBs may not have all
    # columns; fall back to a simple proceeds/fee/count aggregate in that case.
    detailed_sql = """
        SELECT market_ticker,
               SUM(CASE
                       WHEN side = 'yes' AND action = 'sell'
                           THEN COALESCE(yes_price_dollars, 0.0) - COALESCE(fee_cost, 0.0)
                       WHEN side = 'yes' AND action = 'buy'
                           THEN -COALESCE(yes_price_dollars, 0.0) - COALESCE(fee_cost, 0.0)
                       WHEN side = 'no' AND action = 'buy'
                           THEN 1.0 - COALESCE(no_price_dollars, 0.0) - COALESCE(fee_cost, 0.0)
                       WHEN side = 'no' AND action = 'sell'
                           THEN COALESCE(no_price_dollars, 0.0) - 1.0 - COALESCE(fee_cost, 0.0)
                       ELSE 0.0
                   END),
               SUM(CASE
                       WHEN side = 'yes' AND action = 'buy' THEN 1
                       WHEN side = 'yes' AND action = 'sell' THEN -1
                       WHEN side = 'no' AND action = 'buy' THEN -1
                       WHEN side = 'no' AND action = 'sell' THEN 1
                       ELSE 0
                   END),
               COALESCE(SUM(CAST(fee_cost AS REAL)), 0.0),
               COUNT(*),
               COALESCE(SUM(CAST(count_fp AS INTEGER)), 0)
        FROM kalshi_fills
        GROUP BY market_ticker
    """
    simple_sql = """
        SELECT market_ticker,
               COALESCE(SUM(CAST(proceeds_dollars AS REAL)), 0.0),
               COALESCE(SUM(CAST(fee_cost AS REAL)), 0.0),
               COUNT(*)
        FROM kalshi_fills
        GROUP BY market_ticker
    """

    detailed = True
    try:
        rows = conn.execute(detailed_sql).fetchall()
    except sqlite3.Error:
        try:
            rows = conn.execute(simple_sql).fetchall()
            detailed = False
        except sqlite3.Error:
            conn.close()
            return {}
    conn.close()

    result: Dict[str, Dict[str, float]] = {}
    if detailed:
        for ticker, a, b, fees, n, contracts in rows:
            if not ticker:
                continue
            fees = float(fees or 0.0)
            contracts = int(contracts or 0)
            result[str(ticker)] = {
                "settlement_pnl_linear_a": float(a or 0.0),
                "settlement_pnl_linear_b": float(b or 0.0),
                "cash_flow_dollars": float(a or 0.0),  # legacy alias
                "fees_dollars": fees,
                "fills": int(n),
                "contracts": contracts,
                "actual_cost_per_contract_dollars": (
                    fees / contracts if contracts > 0 else None
                ),
                "realized_pnl_dollars": None,  # computed in join_rows from outcome
            }
    else:
        for ticker, pnl, fees, n in rows:
            if not ticker:
                continue
            result[str(ticker)] = {
                "realized_pnl_dollars": float(pnl or 0.0),
                "cash_flow_dollars": float(pnl or 0.0),
                "fees_dollars": float(fees or 0.0),
                "fills": int(n),
                "contracts": 0,
                "actual_cost_per_contract_dollars": None,
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
    filled = [r for r in resolved if r.get("fill_count", 0) > 0]
    probs_model = [_model_p(r) for r in resolved if _model_p(r) is not None]
    outs_model = [r["y"] for r in resolved if _model_p(r) is not None]
    probs_market = [_market_p(r) for r in resolved if _market_p(r) is not None]
    outs_market = [r["y"] for r in resolved if _market_p(r) is not None]
    pnls = [r["realized_pnl_dollars"] for r in rows if r.get("realized_pnl_dollars") is not None]
    candidates = [r for r in rows if r.get("candidate_generated")]
    selected = [r for r in rows if r.get("allocator_selected")]

    # Gross edge: predicted = model - market; realized = y - market.
    edge_pred, edge_real = [], []
    for r in resolved:
        mp = _model_p(r)
        mkt = _market_p(r)
        if mkt is None:
            continue
        pred = (mp - mkt) if mp is not None else None
        real = r["y"] - mkt
        if pred is not None:
            edge_pred.append(pred)
        edge_real.append(real)
    edge_gaps = [p - r for p, r in zip(edge_pred, edge_real)]

    # Net-of-cost edge: predicted uses the model's telemetry cost, realized uses
    # the actual fee cost from fills (only for trades that actually executed).
    edge_pred_net_all, predicted_costs = [], []
    for r in resolved:
        mp = _model_p(r)
        mkt = _market_p(r)
        if mkt is None:
            continue
        pred = (mp - mkt) if mp is not None else None
        cost_pred = _predicted_cost_prob(r)
        predicted_costs.append(cost_pred)
        if pred is not None:
            edge_pred_net_all.append(pred - cost_pred)

    edge_real_net_filled, actual_costs, filled_gaps_net = [], [], []
    for r in filled:
        mkt = _market_p(r)
        if mkt is None:
            continue
        real = r["y"] - mkt
        cost_actual = _actual_cost_prob(r)
        if cost_actual is None:
            cost_actual = _predicted_cost_prob(r)
        edge_real_net_filled.append(real - cost_actual)
        actual_costs.append(cost_actual)
        mp = _model_p(r)
        if mp is not None:
            filled_gaps_net.append((mp - mkt - _predicted_cost_prob(r)) - (real - cost_actual))

    pred_stats = _edge_stats(edge_pred, "predicted_edge") if edge_pred else {}
    real_stats = _edge_stats(edge_real, "realized_edge") if edge_real else {}
    pred_net_stats = _edge_stats(edge_pred_net_all, "predicted_edge_net") if edge_pred_net_all else {}
    real_net_stats = _edge_stats(edge_real_net_filled, "realized_edge_net") if edge_real_net_filled else {}
    gap_stats = _edge_stats(edge_gaps, "predicted_minus_realized_edge") if edge_gaps else {}
    gap_net_stats = _edge_stats(filled_gaps_net, "predicted_minus_realized_edge_net") if filled_gaps_net else {}

    # Canonical calibration diagnostics in side space.
    n_bins = min(n_bins, len(probs_model)) if probs_model else n_bins
    cal_model = calibration_summary(probs_model, outs_model, n_bins=n_bins, label="model")
    cal_market = calibration_summary(probs_market, outs_market, n_bins=n_bins, label="market")

    brier_model = cal_model["brier_score"]
    brier_mkt = cal_market["brier_score"]
    brier_skill = None
    if brier_mkt is not None and brier_mkt > 0 and brier_model is not None and math.isfinite(brier_model):
        brier_skill = 1.0 - (brier_model / brier_mkt)

    auc_model = cal_model.get("auc_roc")
    auc_mkt = cal_market.get("auc_roc")
    auc_skill = None
    if (
        auc_model is not None and math.isfinite(auc_model)
        and auc_mkt is not None and math.isfinite(auc_mkt)
    ):
        auc_skill = auc_model - auc_mkt

    res_model = cal_model.get("resolution")
    res_mkt = cal_market.get("resolution")
    res_skill = None
    if (
        res_model is not None and math.isfinite(res_model)
        and res_mkt is not None and math.isfinite(res_mkt) and res_mkt > 0
    ):
        res_skill = res_model / res_mkt

    # Cost: prefer actual fee cost for filled records, predicted otherwise.
    mean_actual_cost_cents = _mean(c * 100.0 for c in actual_costs) if actual_costs else None
    mean_predicted_cost_cents = _mean(c * 100.0 for c in predicted_costs) if predicted_costs else None

    return {
        "slice": name,
        "evaluated": n,
        "resolved": len(resolved),
        "candidates": len(candidates),
        "candidate_rate": _rate(len(candidates), n),
        "selected": len(selected),
        "selected_rate": _rate(len(selected), n),
        "filled": len(filled),
        "fill_rate": _rate(len(filled), len(resolved)) if resolved else None,
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
        # Discrimination: AUC and Murphy resolution (independent of calibration)
        "auc_roc_model": auc_model,
        "auc_roc_market": auc_mkt,
        "auc_roc_skill": auc_skill,
        "resolution_model": res_model,
        "resolution_market": res_mkt,
        "resolution_skill": res_skill,
        "brier_reliability_model": cal_model.get("reliability"),
        "brier_reliability_market": cal_market.get("reliability"),
        "brier_uncertainty_model": cal_model.get("uncertainty"),
        # Edge calibration: gross edge (all resolved) and net-of-cost edge
        # (filled records only, using actual fees).  predicted_edge_net uses the
        # model's own all_in cost estimate; realized_edge_net uses realized cost.
        "mean_predicted_edge": _mean(edge_pred),
        "mean_realized_edge": _mean(edge_real),
        "mean_predicted_edge_net": _mean(edge_pred_net_all),
        "mean_realized_edge_net": _mean(edge_real_net_filled),
        "mean_predicted_minus_realized_edge": _mean(edge_gaps),
        "mean_predicted_minus_realized_edge_net": _mean(filled_gaps_net),
        "mean_round_trip_cost_cents": mean_actual_cost_cents,
        "mean_predicted_cost_cents": mean_predicted_cost_cents,
        **pred_stats,
        **real_stats,
        **pred_net_stats,
        **real_net_stats,
        **gap_stats,
        **gap_net_stats,
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
        outcome_yes: Optional[int] = None
        if ticker in outcomes and side in ("yes", "no"):
            outcome_yes = outcomes[ticker]
            y = outcome_yes if side == "yes" else 1 - outcome_yes
        pnl_info = fill_pnls.get(ticker) if ticker else None
        row = dict(rec)
        row["y"] = y
        row["resolved"] = y is not None
        row["outcome_yes"] = outcome_yes

        if pnl_info:
            row["fill_count"] = pnl_info.get("fills", 0)
            row["contracts"] = pnl_info.get("contracts", 0)
            row["fees_dollars"] = pnl_info.get("fees_dollars")
            row["cash_flow_dollars"] = pnl_info.get("cash_flow_dollars")
            row["actual_cost_per_contract_dollars"] = pnl_info.get(
                "actual_cost_per_contract_dollars"
            )

            # Prefer an explicit settlement PnL (from callers/tests), then compute
            # it from the canonical A/B coefficients and the YES outcome.
            pnl = pnl_info.get("realized_pnl_dollars")
            if pnl is None and outcome_yes is not None:
                a = pnl_info.get("settlement_pnl_linear_a")
                b = pnl_info.get("settlement_pnl_linear_b")
                if a is not None and b is not None:
                    pnl = float(a) + float(b) * float(outcome_yes)
            row["realized_pnl_dollars"] = pnl
        else:
            row["realized_pnl_dollars"] = None
            row["fill_count"] = 0
            row["contracts"] = 0
            row["fees_dollars"] = None
            row["cash_flow_dollars"] = None
            row["actual_cost_per_contract_dollars"] = None

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


def dedupe_admission_per_market(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse to the earliest candidate-generating row per (ticker, side).

    The edge question is about the moment a candidate was first admitted,
    before TTE convergence compresses the market-implied probability.  If no
    row for a market has ``candidate_generated=True``, fall back to the
    earliest row with a side.  Rows without ticker/side are kept as-is.
    """
    earliest: Dict[Any, Dict[str, Any]] = {}
    earliest_candidate: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    passthrough: List[Dict[str, Any]] = []
    for row in rows:
        key = (row.get("ticker"), str(row.get("selected_side") or "").lower())
        if not key[0] or not key[1]:
            passthrough.append(row)
            continue
        if key not in earliest:
            order.append(key)
            earliest[key] = row
        if row.get("candidate_generated"):
            if key not in earliest_candidate:
                earliest_candidate[key] = row
            # Keep the earliest candidate, not the first one seen in this loop
            # (rows may not be chronologically sorted, so compare timestamps).
            elif _parse_iso_ts(row.get("event_ts_utc")) is not None and (
                _parse_iso_ts(earliest_candidate[key].get("event_ts_utc")) is None
                or _parse_iso_ts(row.get("event_ts_utc")) < _parse_iso_ts(earliest_candidate[key].get("event_ts_utc"))
            ):
                earliest_candidate[key] = row
    # Prefer earliest candidate, then earliest row if no candidate.
    chosen: Dict[Any, Dict[str, Any]] = {}
    for key in order:
        chosen[key] = earliest_candidate.get(key) or earliest[key]
    return [chosen[k] for k in order] + passthrough


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


def _build_slice_set(
    rows: List[Dict[str, Any]],
    n_bins: int = 5,
    tte_buckets: Sequence[Tuple[str, float, float]] = TTE_BUCKETS,
) -> Dict[str, Any]:
    """Compute all report slices for a given row set."""
    slices: Dict[str, Any] = {"overall": _slice_metrics("overall", rows, n_bins=n_bins)}
    for key, key_fn, buckets in [
        ("by_asset", lambda r: r.get("asset"), None),
        ("by_side", lambda r: (str(r.get("selected_side") or "").lower() or None), None),
        ("by_price_bucket", lambda r: _bucket(
            _market_p(r) * 100 if _market_p(r) is not None else None,
            PRICE_BUCKETS), PRICE_BUCKETS),
        ("by_time_to_expiry", lambda r: _bucket(r.get("minutes_to_expiry"), tte_buckets), tte_buckets),
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
            name: _slice_metrics(name, groups[name], n_bins=n_bins)
            for name in ordered
            if name in groups
        }
    return slices


def build_report(
    records: List[Dict[str, Any]],
    outcomes: Dict[str, int],
    fill_pnls: Dict[str, Dict[str, float]],
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the full calibration audit report as a JSON-safe dict.

    Three-section output:
    - decision_funnel: raw cycle accounting from evaluation to execution.
      Pre-side rejections are counted here and NEVER enter calibration.
    - calibration cohort: one row per (ticker, side) market decision with a
      formed side; Brier/bias/edge-gap computed on resolved records only.
    - edge_admission cohort: the first candidate-generating row per market,
      used for the edge-sign/magnitude/TTE tests where TTE convergence would
      otherwise dilute the signal.
    """
    import time as _time
    if now_ts is None:
        now_ts = _time.time()

    raw_rows = join_rows(records, outcomes, fill_pnls)
    deduped = dedupe_latest_per_market(raw_rows)
    edge_deduped = dedupe_admission_per_market(raw_rows)

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

    slices = _build_slice_set(rows, n_bins=5, tte_buckets=TTE_BUCKETS)

    # Edge-admission cohort: first candidate-generating row per market.
    edge_pre_side = [r for r in edge_deduped if not r.get("ticker") or not r.get("selected_side")]
    edge_sided = [r for r in edge_deduped if r.get("ticker") and r.get("selected_side")]
    edge_eligible = [
        r for r in edge_sided
        if _model_p(r) is not None
        and _market_p(r) is not None
        and (r.get("decision_id") or r.get("ticker"))
        and (r.get("resolved") or r.get("event_ts_utc"))
    ]
    edge_slices = _build_slice_set(edge_eligible, n_bins=5, tte_buckets=TTE_ADMISSION_BUCKETS)
    # Rename edge slice keys so they are clearly distinct from calibration slices.
    edge_slices = {f"{k}_admission": v for k, v in edge_slices.items()}

    # Recalibration demonstration: Platt scaling on the calibration cohort.
    # This is a monotonic transform; it can fix calibration but not discrimination.
    recal_probs = [_model_p(r) for r in resolved_rows if _model_p(r) is not None]
    recal_outs = [r["y"] for r in resolved_rows if _model_p(r) is not None]
    recalibration = _platt_recalibration(recal_probs, recal_outs)

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
            "discrimination": (
                "AUC/ROC and Murphy resolution measure whether the model ranks "
                "outcomes better than the market reference, independent of whether "
                "its probabilities are calibrated. A model with AUC and resolution "
                "similar to the market has no tradable discrimination; one that "
                "clearly exceeds the market may have real edge after recalibration."
            ),
            "edge_admission_cohort": (
                "first candidate-generating row per (ticker, side). Edge tests "
                "use this cohort because the latest row per window is near expiry, "
                "where convergence erodes the edge signal."
            ),
        },
        "counts": {
            "evaluated_records": len(raw_rows),
            "unique_decision_markets": len(deduped),
            "edge_admission_unique_markets": len(edge_deduped),
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
        "edge_admission_funnel": {
            "sided_decision_records": len(edge_sided),
            "calibration_eligible_records": len(edge_eligible),
            "resolved_records": sum(1 for r in edge_eligible if r.get("resolved")),
        },
        "resolution_reconciliation": {
            "settlement_grace_minutes": SETTLEMENT_GRACE_MINUTES,
            "pending": pending,
            "unresolvable": unresolvable,
        },
        "slices": slices,
        "edge_slices": edge_slices,
        "recalibration": recalibration,
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
        if metrics.get("filled"):
            parts.append(f"filled={metrics['filled']}")
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
        if metrics.get("auc_roc_model") is not None and math.isfinite(metrics["auc_roc_model"]):
            parts.append(f"auc={metrics['auc_roc_model']:.3f}")
        if metrics.get("auc_roc_market") is not None and math.isfinite(metrics["auc_roc_market"]):
            parts.append(f"mkt_auc={metrics['auc_roc_market']:.3f}")
        if metrics.get("auc_roc_skill") is not None and math.isfinite(metrics["auc_roc_skill"]):
            parts.append(f"auc_skill={metrics['auc_roc_skill']:+.3f}")
        if metrics.get("resolution_model") is not None and math.isfinite(metrics["resolution_model"]):
            parts.append(f"res={metrics['resolution_model']:.4f}")
        if metrics.get("resolution_market") is not None and math.isfinite(metrics["resolution_market"]):
            parts.append(f"mkt_res={metrics['resolution_market']:.4f}")
        if metrics.get("resolution_skill") is not None and math.isfinite(metrics["resolution_skill"]):
            parts.append(f"res_skill={metrics['resolution_skill']:.3f}")
        if metrics.get("mean_predicted_edge") is not None:
            parts.append(f"pred_edge={metrics['mean_predicted_edge']:+.4f}")
        if metrics.get("mean_realized_edge") is not None:
            n = metrics.get("realized_edge_n")
            parts.append(f"real_edge={metrics['mean_realized_edge']:+.4f}(n={n})")
        if metrics.get("mean_predicted_edge_net") is not None:
            parts.append(f"pred_net={metrics['mean_predicted_edge_net']:+.4f}")
        if metrics.get("mean_realized_edge_net") is not None:
            n = metrics.get("realized_edge_net_n")
            t = metrics.get("realized_edge_net_t_stat")
            t_str = f" t={t:+.2f}" if t is not None else ""
            parts.append(f"real_net={metrics['mean_realized_edge_net']:+.4f}(n={n}){t_str}")
        if metrics.get("mean_predicted_minus_realized_edge") is not None:
            t = metrics.get("predicted_minus_realized_edge_t_stat")
            t_str = f" t={t:+.2f}" if t is not None else ""
            parts.append(f"pred-real_edge={metrics['mean_predicted_minus_realized_edge']:+.4f}{t_str}")
        if metrics.get("fee_inclusive_expectancy_dollars") is not None:
            parts.append(f"expectancy=${metrics['fee_inclusive_expectancy_dollars']:+.4f}")
        if metrics.get("mean_round_trip_cost_cents") is not None:
            parts.append(f"act_cost={metrics['mean_round_trip_cost_cents']:.2f}c")
        if metrics.get("mean_predicted_cost_cents") is not None:
            parts.append(f"pred_cost={metrics['mean_predicted_cost_cents']:.2f}c")
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

    # Edge-admission cohort: first candidate-generating row per market.
    edge_slices = report.get("edge_slices") or {}
    if edge_slices:
        lines.append("")
        lines.append("EDGE-ADMISSION COHORT (first candidate row per market)")
        edge_overall = edge_slices.get("overall_admission")
        if edge_overall:
            _emit("overall_admission", edge_overall)
        for section in ("by_asset_admission", "by_side_admission", "by_price_bucket_admission",
                        "by_time_to_expiry_admission", "by_edge_sign_admission",
                        "by_edge_magnitude_admission"):
            group = edge_slices.get(section) or {}
            if not group:
                continue
            lines.append("")
            lines.append(f"-- {section} " + "-" * max(0, 55 - len(section)))
            for name in sorted(group):
                _emit(name, group[name])

    # Recalibration: Platt scaling demonstration.
    rec = report.get("recalibration") or {}
    lines.append("")
    lines.append("RECALIBRATION (Platt scaling)")
    if not rec or rec.get("error"):
        lines.append(f"  unavailable: {rec.get('error', 'insufficient_data')}")
    else:
        lines.append(f"  n={rec['n_samples']}  a={rec['platt_a']:.4f}  b={rec['platt_b']:.4f}")
        lines.append(
            f"  Brier raw={rec['brier_raw']:.4f} -> cal={rec['brier_calibrated']:.4f}"
        )
        lines.append(
            f"  ECE   raw={rec['ece_raw']:.4f} -> cal={rec['ece_calibrated']:.4f}"
        )
        lines.append(
            f"  AUC   raw={rec['auc_raw']:.4f} -> cal={rec['auc_calibrated']:.4f}  (monotonic; unchanged)"
        )
        lines.append(f"  NOTE: {rec['note']}")

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
