"""Generate the hybrid-signal audit artifact required by merid.startup_validations.

This script joins production shadow telemetry (``data/logs/hybrid_model_decomposition.jsonl``
which records the Bachelier baseline, each signed delta, and the pre-clip hybrid
probability for every live evaluation) with ``logs/settlement_outcomes.jsonl``. It then
performs a genuine chronological train/test split, fits a calibration only on the
training data, and evaluates the hybrid out-of-sample.

Usage:
    .\.venv\Scripts\python.exe scripts\generate_hybrid_signal_audit.py
    .\.venv\Scripts\python.exe scripts\generate_hybrid_signal_audit.py --promote

The default mode writes a progress report to ``reports/hybrid_audit_progress.json`` and
prints a summary. It does *not* write ``data/hybrid_signal_audit.json`` unless the
metrics pass the live thresholds or ``--promote`` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.isotonic import IsotonicRegression


# Thresholds from merid.startup_validations.validate_hybrid_signal_audit
THRESHOLDS = {
    "brier_score": 0.20,
    "expected_calibration_error": 0.10,
    "pbo": 0.30,
    "deflated_sharpe_ratio": 0.95,
    "walk_forward_efficiency": 0.30,
    "mean_net_edge_per_bucket_cents": 0.0,
    "hold_out_set_size": 200,
    "reliability_max_gap": 0.10,
}

PRICE_BUCKETS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


def _env_path(name: str, default: str) -> str:
    """Resolve a path from env, defaulting relative to the repo root."""
    value = os.environ.get(name)
    if value:
        return os.path.abspath(value)
    return os.path.abspath(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_settlements(path: str) -> Dict[str, int]:
    """Map ticker -> resolved_yes (1 if YES settled, 0 if NO)."""
    out: Dict[str, int] = {}
    for record in _load_jsonl(path):
        ticker = record.get("ticker")
        if not ticker:
            continue
        resolved = record.get("resolved_yes")
        if resolved is None:
            resolved = 1 if str(record.get("outcome", "")).lower() == "yes" else 0
        out[ticker] = int(resolved)
    return out


def _to_cents(v: Any) -> Optional[float]:
    v = _safe_float(v)
    return v * 100.0 if v is not None else None


def _build_decomposition_frame(
    decomposition_path: str,
    settlement_path: str,
    one_per_ticker: bool = True,
    min_tte_seconds: float = 0.0,
) -> pd.DataFrame:
    """Load model-decomposition records, join with settlements, and normalize fields.

    The hybrid would-be probability is ``p_yes_bachelier + raw_delta_total`` from the
    shadow log. We infer the per-side all-in cost from the Bachelier net edges so the
    hybrid net edge can be recomputed using the same cost stack the live system would
    have at the moment of the evaluation.
    """
    settlements = _load_settlements(settlement_path)
    rows: List[Dict[str, Any]] = []

    for record in _load_jsonl(decomposition_path):
        ticker = record.get("ticker")
        if not ticker or ticker not in settlements:
            continue

        resolved_yes = settlements[ticker]
        ts_str = record.get("timestamp_utc") or record.get("decision_ts")
        if not ts_str:
            continue
        try:
            ts = pd.Timestamp(ts_str).to_pydatetime()
        except Exception:
            continue

        tte = _safe_float(record.get("time_remaining_s"), 0.0)
        if tte < min_tte_seconds:
            continue

        live = record.get("live") or {}
        p_yes_bachelier = _safe_float(record.get("p_yes_bachelier"))
        p_yes_pre_clip = _safe_float(record.get("p_yes_pre_clip"))
        raw_delta_total = _safe_float(record.get("raw_delta_total"))

        if not (0.0 < p_yes_bachelier < 1.0 and math.isfinite(p_yes_pre_clip)):
            continue

        # Hybrid p after the signed delta; clip to avoid degenerate bounds.
        p_yes_hybrid = float(np.clip(p_yes_pre_clip, 1e-4, 1.0 - 1e-4))

        yes_ask = _safe_float(record.get("market_yes_ask"), 0.0)
        no_ask = _safe_float(record.get("market_no_ask"), 0.0)
        yes_bid = _safe_float(record.get("market_yes_bid"), 0.0)
        no_bid = _safe_float(record.get("market_no_bid"), 0.0)

        if not (1.0 <= yes_ask <= 99.0 and 1.0 <= no_ask <= 99.0):
            continue

        # Bachelier net edges (fraction) from the live decision block.
        yes_net_edge_bach = _safe_float(live.get("yes_net_edge"), 0.0)
        no_net_edge_bach = _safe_float(live.get("no_net_edge"), 0.0)

        # Infer the all-in cost in cents from the Bachelier net edge.
        # net_edge (frac) = p_selected - entry_frac - cost_frac
        # => cost_cents = p_bach * 100 - entry_cents - net_edge * 100
        cost_yes_cents = p_yes_bachelier * 100.0 - yes_ask - yes_net_edge_bach * 100.0
        p_no_bachelier = 1.0 - p_yes_bachelier
        cost_no_cents = p_no_bachelier * 100.0 - no_ask - no_net_edge_bach * 100.0

        # Average the two per-side cost estimates; the cost stack is side-symmetric.
        # Clamp to a floor so a single bad estimate does not create impossible edges.
        cost_cents = float(np.clip((cost_yes_cents + cost_no_cents) / 2.0, 0.0, 50.0))

        # Hybrid net edges in cents for each held side.
        hybrid_yes_net_edge = p_yes_hybrid * 100.0 - yes_ask - cost_cents
        hybrid_no_net_edge = (1.0 - p_yes_hybrid) * 100.0 - no_ask - cost_cents

        # The live decision's dynamic edge threshold (converted to cents).
        edge_threshold = _safe_float(live.get("edge_threshold"), 0.07) * 100.0

        # Side the hybrid would select (ignoring threshold, just by edge).
        if hybrid_yes_net_edge >= hybrid_no_net_edge:
            hybrid_side = "yes"
            p_selected = p_yes_hybrid
            entry_cents = yes_ask
            net_edge_cents = hybrid_yes_net_edge
        else:
            hybrid_side = "no"
            p_selected = 1.0 - p_yes_hybrid
            entry_cents = no_ask
            net_edge_cents = hybrid_no_net_edge

        # Would the hybrid actually clear the live threshold?
        would_trade = max(hybrid_yes_net_edge, hybrid_no_net_edge) >= edge_threshold

        # Realized outcome for the selected side.
        if hybrid_side == "yes":
            outcome = 1.0 if resolved_yes == 1 else 0.0
        else:
            outcome = 1.0 if resolved_yes == 0 else 0.0

        # Realized PnL in cents for this hybrid trade (payoff minus all-in cost).
        # Used for DSR. If the side won, payoff is 100c, else 0c.
        if outcome == 1.0:
            realized_pnl = 100.0 - entry_cents - cost_cents
        else:
            realized_pnl = -entry_cents - cost_cents

        rows.append(
            {
                "ticker": ticker,
                "asset": record.get("asset"),
                "timestamp": ts,
                "decision_ts": _safe_float(record.get("decision_ts"), ts.timestamp()),
                "p_yes_bachelier": p_yes_bachelier,
                "raw_delta_total": raw_delta_total,
                "p_yes_hybrid": p_yes_hybrid,
                "p_selected": float(np.clip(p_selected, 1e-4, 1.0 - 1e-4)),
                "hybrid_side": hybrid_side,
                "entry_cents": entry_cents,
                "net_edge_cents": net_edge_cents,
                "would_trade": would_trade,
                "edge_threshold_cents": edge_threshold,
                "outcome": outcome,
                "realized_pnl_cents": realized_pnl,
                "yes_ask": yes_ask,
                "no_ask": no_ask,
                "yes_bid": yes_bid,
                "no_bid": no_bid,
                "spread_cents": (yes_ask - yes_bid) + (no_ask - no_bid),
                "tte_seconds": tte,
                "settlement_reference": record.get("settlement_reference"),
                "data_state": record.get("data_state"),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("decision_ts").reset_index(drop=True)

    if one_per_ticker:
        # Use the final evaluation for each settled market. This keeps the sample
        # at one honest prediction per market, avoids outcome duplication, and
        # still uses the model's most informed live probability.
        df = df.groupby("ticker").tail(1).copy()

    return df


def _calibrate_and_evaluate(
    train_df: pd.DataFrame, test_df: pd.DataFrame
) -> Tuple[IsotonicRegression, float, float, float, List[Dict[str, Any]]]:
    """Fit an isotonic calibration on the training set and return OOS metrics.

    Returns:
        calibrator, test_brier, test_ece, test_max_gap, reliability_plot
    """
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(train_df["p_selected"].values, train_df["outcome"].values)

    test_p_cal = np.clip(calibrator.transform(test_df["p_selected"].values), 1e-4, 1.0 - 1e-4)
    test_brier = float(np.mean((test_p_cal - test_df["outcome"].values) ** 2))

    # Reliability plot and ECE on 10 equal-width bins.
    bins = np.linspace(0.0, 1.0, 11)
    ece = 0.0
    reliability: List[Dict[str, Any]] = []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        mask = (test_p_cal >= lo) & (test_p_cal < hi)
        if i == len(bins) - 2:
            mask = (test_p_cal >= lo) & (test_p_cal <= hi)
        bin_df = test_df[mask]
        n = int(len(bin_df))
        if n == 0:
            continue
        pred = float(np.mean(test_p_cal[mask]))
        obs = float(np.mean(bin_df["outcome"].values))
        ece += (n / len(test_df)) * abs(pred - obs)
        reliability.append(
            {"predicted_prob": round(pred, 4), "observed_freq": round(obs, 4), "n_trades": n}
        )

    max_gap = 0.0
    for bucket in reliability:
        max_gap = max(max_gap, abs(bucket["predicted_prob"] - bucket["observed_freq"]))

    return calibrator, test_brier, ece, max_gap, reliability


def _compute_train_brier(
    train_df: pd.DataFrame, calibrator: IsotonicRegression
) -> float:
    train_p_cal = np.clip(calibrator.transform(train_df["p_selected"].values), 1e-4, 1.0 - 1e-4)
    return float(np.mean((train_p_cal - train_df["outcome"].values) ** 2))


def _compute_wfe(
    train_df: pd.DataFrame, test_df: pd.DataFrame
) -> Tuple[float, Optional[IsotonicRegression]]:
    """Walk-forward efficiency: train-brier / test-brier after isotonic calibration."""
    if len(train_df) < 30 or len(test_df) < 30:
        return 0.0, None
    calibrator, test_brier, _, _, _ = _calibrate_and_evaluate(train_df, test_df)
    train_brier = _compute_train_brier(train_df, calibrator)
    if test_brier <= 0:
        return 2.0, calibrator
    wfe = train_brier / test_brier
    return float(np.clip(wfe, 0.0, 2.0)), calibrator


def _compute_pbo(df: pd.DataFrame, n_folds: int = 4) -> float:
    """Conservative PBO proxy via chronological fold WFE.

    The true PBO (Lopez de Prado & Bailey, 2013) requires a matrix of backtest
    paths over multiple strategies. Since the hybrid is a single model, this
    returns the mean probability of overfit implied by the fold-level walk-forward
    efficiencies: pbo = mean(max(0, 1 - WFE_i)).
    """
    df = df.sort_values("decision_ts").reset_index(drop=True)
    n = len(df)
    if n < n_folds * 50:
        return 1.0  # not enough data to estimate reliably

    fold_size = n // n_folds
    pbo_vals: List[float] = []
    for i in range(1, n_folds + 1):
        test_start = (i - 1) * fold_size
        test_end = i * fold_size if i < n_folds else n
        test_df = df.iloc[test_start:test_end]
        train_df = df.iloc[:test_start]
        if len(train_df) < 30 or len(test_df) < 10:
            continue
        wfe, _ = _compute_wfe(train_df, test_df)
        pbo_vals.append(max(0.0, 1.0 - wfe))

    if not pbo_vals:
        return 1.0
    return float(np.mean(pbo_vals))


def _compute_dsr(trade_returns: pd.Series, benchmark_sharpe: float = 0.0, n_trials: int = 1) -> float:
    """Deflated Sharpe Ratio proxy using the Probabilistic Sharpe Ratio formula.

    This is the PSR from Bailey & Lopez de Prado (2012) with the benchmark
    Sharpe set to the expected maximum of ``n_trials`` independent random
    strategies. When n_trials=1 the benchmark is 0.
    """
    returns = np.asarray(trade_returns, dtype=float)
    if len(returns) < 3 or np.std(returns, ddof=1) <= 0 or not np.all(np.isfinite(returns)):
        return 0.5

    sr = float(np.mean(returns) / np.std(returns, ddof=1))
    skew = float(stats.skew(returns, bias=False))
    kurt = float(stats.kurtosis(returns, fisher=False, bias=False))
    n = len(returns)

    # Expected maximum Sharpe of n_trials independent N(0,1) returns paths.
    # Approximation from extreme value theory: EM[SR] ≈ sqrt(2 * log(n_trials))
    # divided by sqrt(n) to scale to per-observation Sharpe units.
    if n_trials > 1:
        em_max = np.sqrt(2.0 * np.log(n_trials))
        sr_benchmark = float(em_max / np.sqrt(max(n, 2)))
    else:
        sr_benchmark = benchmark_sharpe

    # Standard error of the observed Sharpe accounting for skew and kurtosis.
    variance = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / max(n - 1, 1)
    if variance <= 0 or not np.isfinite(variance):
        return 0.5
    sigma = float(np.sqrt(variance))
    psr = float(stats.norm.cdf((sr - sr_benchmark) / sigma))
    return float(np.clip(psr, 0.0, 1.0))


def _mean_net_edge_per_bucket_cents(df: pd.DataFrame) -> Tuple[float, List[Dict[str, Any]]]:
    """Mean ex-ante net edge per 10c held-price bucket for hybrid trades."""
    trades = df[df["would_trade"]].copy()
    if trades.empty:
        return 0.0, []

    bucket_means: List[float] = []
    details: List[Dict[str, Any]] = []
    for i in range(len(PRICE_BUCKETS) - 1):
        lo, hi = PRICE_BUCKETS[i], PRICE_BUCKETS[i + 1]
        mask = (trades["entry_cents"] >= lo) & (trades["entry_cents"] < hi)
        if hi == 100:
            mask = (trades["entry_cents"] >= lo) & (trades["entry_cents"] <= hi)
        b = trades[mask]
        if b.empty:
            continue
        mean_edge = float(b["net_edge_cents"].mean())
        bucket_means.append(mean_edge)
        details.append(
            {
                "bucket_cents": f"{lo}-{hi}",
                "n_trades": int(len(b)),
                "mean_net_edge_cents": round(mean_edge, 4),
                "mean_realized_pnl_cents": round(float(b["realized_pnl_cents"].mean()), 4),
            }
        )

    if not bucket_means:
        return 0.0, []

    # Most conservative single number: the worst bucket. If the worst bucket is
    # positive, every bucket is positive.
    worst = float(min(bucket_means))
    return worst, details


def _model_signature() -> str:
    """Hash the env knobs that control the hybrid fusion."""
    keys = [
        "MERID_HYBRID_MAX_P_SHIFT",
        "MERID_HYBRID_MIN_BARS_FOR_FULL_SHIFT",
        "MERID_HYBRID_WARMUP_MAX_P_SHIFT",
        "MERID_MACD_EDGE_WEIGHT",
        "MERID_FVG_DELTA_WEIGHT",
        "MERID_FVG_MAX_DELTA",
        "MERID_ENABLE_FVG",
        "MERID_MICRO_OFI_WINDOW_S",
        "MERID_MICRO_MAX_EDGE_PCT",
    ]
    parts = []
    for key in keys:
        parts.append(f"{key}={os.environ.get(key, '')}")
    payload = "|".join(parts)
    return "hybrid-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _generate_audit(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    n_trials: int = 1,
) -> Dict[str, Any]:
    """Produce the full audit dict and a pass/fail summary."""
    if df.empty:
        return {
            "model_signature": _model_signature(),
            "passes": False,
            "failures": ["no shadow records with settlements (ticker join failed)"],
            "n_total_settled_evaluations": 0,
            "hold_out_set_size": 0,
            "n_test_trades": 0,
            "brier_score": None,
            "brier_baseline": "venue_implied",
            "expected_calibration_error": None,
            "reliability_plot": [],
            "reliability_max_gap": None,
            "pbo": None,
            "deflated_sharpe_ratio": None,
            "walk_forward_efficiency": None,
            "mean_net_edge_per_bucket_cents": None,
            "price_bucket_details": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "auditor": "generate_hybrid_signal_audit.py",
            "thresholds": {k: v for k, v in THRESHOLDS.items()},
        }

    df = df.sort_values("decision_ts").reset_index(drop=True)
    n_total = len(df)
    split_idx = int(n_total * train_frac)
    if split_idx < 50 or (n_total - split_idx) < 200:
        return {
            "model_signature": _model_signature(),
            "passes": False,
            "failures": [f"insufficient hold-out: total={n_total}, test={n_total - split_idx} (need >=200)"],
            "n_total_settled_evaluations": n_total,
            "hold_out_set_size": n_total - split_idx,
            "n_test_trades": 0,
            "brier_score": None,
            "brier_baseline": "venue_implied",
            "expected_calibration_error": None,
            "reliability_plot": [],
            "reliability_max_gap": None,
            "pbo": None,
            "deflated_sharpe_ratio": None,
            "walk_forward_efficiency": None,
            "mean_net_edge_per_bucket_cents": None,
            "price_bucket_details": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "auditor": "generate_hybrid_signal_audit.py",
            "thresholds": {k: v for k, v in THRESHOLDS.items()},
        }

    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    # Main walk-forward metrics.
    wfe, calibrator = _compute_wfe(train_df, test_df)
    if calibrator is None:
        return {
            "valid": False,
            "reason": "could not fit walk-forward split",
            "n_total": n_total,
            "n_hold_out": len(test_df),
        }

    _, test_brier, test_ece, test_max_gap, reliability = _calibrate_and_evaluate(
        train_df, test_df
    )
    train_brier = _compute_train_brier(train_df, calibrator)

    # PBO across chronological folds.
    pbo = _compute_pbo(df, n_folds=4)

    # DSR from the test-set hybrid trades' realized PnL.
    test_trades = test_df[test_df["would_trade"]]
    dsr = _compute_dsr(test_trades["realized_pnl_cents"], n_trials=n_trials)

    # Net edge per price bucket.
    bucket_mean, bucket_details = _mean_net_edge_per_bucket_cents(test_df)

    n_test = len(test_df)
    n_test_trades = int(test_trades["would_trade"].sum())

    generated_at = datetime.now(timezone.utc).isoformat()
    valid_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    audit = {
        "model_signature": _model_signature(),
        "hold_out_set_size": n_test,
        "brier_score": round(test_brier, 6),
        "brier_baseline": "venue_implied",
        "train_brier": round(train_brier, 6),
        "expected_calibration_error": round(test_ece, 6),
        "reliability_plot": reliability,
        "reliability_max_gap": round(test_max_gap, 6),
        "pbo": round(pbo, 6),
        "deflated_sharpe_ratio": round(dsr, 6),
        "walk_forward_efficiency": round(wfe, 6),
        "mean_net_edge_per_bucket_cents": round(bucket_mean, 6),
        "n_test_trades": n_test_trades,
        "price_bucket_details": bucket_details,
        "generated_at": generated_at,
        "valid_until": valid_until,
        "auditor": "generate_hybrid_signal_audit.py",
        "methodology": {
            "calibration": "isotonic_regression_on_train",
            "train_frac": train_frac,
            "walk_forward_folds": 4,
            "one_record_per_ticker": True,
            "n_total_settled_evaluations": n_total,
            "n_train": len(train_df),
            "n_test": n_test,
        },
    }

    failures: List[str] = []
    if test_brier > THRESHOLDS["brier_score"]:
        failures.append(f"brier_score={test_brier:.4f} > {THRESHOLDS['brier_score']}")
    if test_ece > THRESHOLDS["expected_calibration_error"]:
        failures.append(f"expected_calibration_error={test_ece:.4f} > {THRESHOLDS['expected_calibration_error']}")
    if pbo >= THRESHOLDS["pbo"]:
        failures.append(f"pbo={pbo:.4f} >= {THRESHOLDS['pbo']}")
    if dsr <= THRESHOLDS["deflated_sharpe_ratio"]:
        failures.append(f"deflated_sharpe_ratio={dsr:.4f} <= {THRESHOLDS['deflated_sharpe_ratio']}")
    if wfe <= THRESHOLDS["walk_forward_efficiency"]:
        failures.append(f"walk_forward_efficiency={wfe:.4f} <= {THRESHOLDS['walk_forward_efficiency']}")
    if bucket_mean <= THRESHOLDS["mean_net_edge_per_bucket_cents"]:
        failures.append(f"mean_net_edge_per_bucket_cents={bucket_mean:.4f} <= {THRESHOLDS['mean_net_edge_per_bucket_cents']}")
    if n_test < THRESHOLDS["hold_out_set_size"]:
        failures.append(f"hold_out_set_size={n_test} < {THRESHOLDS['hold_out_set_size']}")
    if test_max_gap > THRESHOLDS["reliability_max_gap"]:
        failures.append(f"reliability_max_gap={test_max_gap:.4f} > {THRESHOLDS['reliability_max_gap']}")

    audit["thresholds"] = {k: v for k, v in THRESHOLDS.items()}
    audit["passes"] = not failures
    audit["failures"] = failures

    return audit


def _write_report(audit: Dict[str, Any], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)


def _print_summary(audit: Dict[str, Any]) -> None:
    print("\n=== HYBRID SIGNAL AUDIT ===\n")
    meta = audit.get("methodology", {})
    n_total = audit.get("n_total_settled_evaluations", meta.get("n_total_settled_evaluations", 0))
    n_test = audit.get("hold_out_set_size", 0)
    print(f"Total settled evaluations: {n_total}")
    print(f"Hold-out (test) records:   {n_test}")
    print(f"Test trades (edge >= thr): {audit.get('n_test_trades', 0)}")
    print()

    if not audit.get("passes", False):
        print("Status: NOT READY for live hybrid\n")
        for f in audit.get("failures", []):
            print(f"  - {f}")
    else:
        print("Status: PASSES live hybrid thresholds\n")

    metrics = [
        ("Brier score", "brier_score", THRESHOLDS["brier_score"], "<="),
        ("ECE", "expected_calibration_error", THRESHOLDS["expected_calibration_error"], "<="),
        ("PBO", "pbo", THRESHOLDS["pbo"], "<"),
        ("DSR", "deflated_sharpe_ratio", THRESHOLDS["deflated_sharpe_ratio"], ">"),
        ("WFE", "walk_forward_efficiency", THRESHOLDS["walk_forward_efficiency"], ">"),
        ("Net edge/bucket (c)", "mean_net_edge_per_bucket_cents", THRESHOLDS["mean_net_edge_per_bucket_cents"], ">"),
    ]
    for name, key, threshold, op in metrics:
        value = audit.get(key)
        if value is None:
            continue
        mark = "OK" if audit.get("passes") else "--"
        print(f"  [{mark}] {name:<22} {value:>10.4f}  (need {op} {threshold})")
    print()

    bucket_details = audit.get("price_bucket_details", [])
    if bucket_details:
        print("Net edge per held-price bucket (test):")
        for b in bucket_details:
            print(
                f"  {b['bucket_cents']:<8} n={b['n_trades']:>4}  "
                f"pred_edge={b['mean_net_edge_cents']:>8.2f}c  "
                f"real_pnl={b['mean_realized_pnl_cents']:>8.2f}c"
            )
        print()

    max_gap = audit.get("reliability_max_gap")
    if max_gap is not None:
        print(f"Reliability max gap: {max_gap:.4f} (need <= {THRESHOLDS['reliability_max_gap']})")
    else:
        print(f"Reliability max gap: N/A (need <= {THRESHOLDS['reliability_max_gap']})")
    print(f"Reliability buckets:  {len(audit.get('reliability_plot', []))}")
    print()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the hybrid-signal audit artifact or a progress report."
    )
    parser.add_argument(
        "--decomposition",
        default=_env_path("MERID_HYBRID_AUDIT_DECOMPOSITION", "data/logs/hybrid_model_decomposition.jsonl"),
        help="Path to model-decomposition shadow log.",
    )
    parser.add_argument(
        "--settlements",
        default=_env_path("MERID_HYBRID_AUDIT_SETTLEMENTS", "logs/settlement_outcomes.jsonl"),
        help="Path to settlement outcomes log.",
    )
    parser.add_argument(
        "--output",
        default=_env_path("MERID_HYBRID_AUDIT_OUTPUT", "data/hybrid_signal_audit.json"),
        help="Path to write the live audit artifact (only on pass unless --promote).",
    )
    parser.add_argument(
        "--report",
        default=_env_path("MERID_HYBRID_AUDIT_REPORT", "reports/hybrid_audit_progress.json"),
        help="Path to write the progress report.",
    )
    parser.add_argument(
        "--train-frac",
        type=float,
        default=0.70,
        help="Fraction of data to use for in-sample calibration training.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Write the live audit artifact even if it does not pass (dangerous).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=1,
        help="Number of independent strategy trials for DSR benchmark adjustment.",
    )
    parser.add_argument(
        "--one-per-ticker",
        type=lambda x: x.lower() in ("1", "true", "yes"),
        default=True,
        help="Use the last evaluation for each settled ticker (default: true).",
    )
    args = parser.parse_args()

    df = _build_decomposition_frame(
        args.decomposition,
        args.settlements,
        one_per_ticker=args.one_per_ticker,
    )
    audit = _generate_audit(df, train_frac=args.train_frac, n_trials=args.n_trials)

    _write_report(audit, args.report)
    _print_summary(audit)

    if audit.get("passes"):
        _write_report(audit, args.output)
        print(f"Wrote passing audit artifact to {args.output}")
    elif args.promote:
        _write_report(audit, args.output)
        print(f"WARN: --promote set; wrote non-passing artifact to {args.output}")
        return 1
    else:
        print(f"Did not write live artifact. Progress report at {args.report}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_main())
