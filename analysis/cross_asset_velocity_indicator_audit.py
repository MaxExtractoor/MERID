"""
Cross-asset velocity and indicator-stack correctness audit.

This script implements the methodology in the 15m indicator audit:
1. Static cross-asset parameter matrix.
2. Sign-consistency check across all five assets on identical controlled price paths.
3. One-bar shift / look-ahead test.
4. SOL-specific source/staleness and settlement reference review.
5. Predictiveness skeleton (requires shadow/historical data file to run).

Run with the repo venv:
    .\.venv\Scripts\python.exe analysis\cross_asset_velocity_indicator_audit.py
"""

from __future__ import annotations

import collections
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repo is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig


ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Static parameter defaults extracted from merid/prediction/agent_grid_15m.py and
# merid/signals/crypto_15m_indicators.py.  These are the values that are in effect
# when kalshi_mode=True unless overridden by environment variables.
VELOCITY_THRESHOLDS = {
    "BTC": 0.00015,
    "ETH": 0.00015,
    "SOL": 0.000225,
    "XRP": 0.000225,
    "DOGE": 0.0003,
}

ANNUALIZED_VOL_DEFAULTS = {
    "BTC": 0.60,
    "ETH": 0.80,
    "SOL": 1.00,
    "XRP": 1.00,
    "DOGE": 1.20,
}

CFB_SETTLEMENT_SYMBOLS = {
    "BTC": "BRTI",
    "ETH": "ETH_RTI",
    "SOL": "SOL_RTI",
    "XRP": "XRP_RTI",
    "DOGE": "DOGE_RTI",
}


@dataclass
class AuditResult:
    """Container for one asset's sign-consistency and shift results."""

    asset: str
    velocity: float
    macd_histogram: float
    rsi: float
    price_above_ema200: bool
    macro_regime: str
    p_yes_bachelier: float
    p_yes_hybrid: float
    sign_agreement: bool
    one_bar_shift_velocity: float
    one_bar_shift_p_yes_hybrid: float
    notes: List[str] = field(default_factory=list)


def _bachelier_p_yes(spot: float, strike: float, seconds_to_expiry: float, annualized_vol: float) -> float:
    """Replica of the Bachelier baseline used by _compute_hybrid_p_yes."""
    t_years = max(seconds_to_expiry, 1.0) / (365.0 * 24.0 * 60.0 * 60.0)
    log_moneyness = math.log(spot / strike) if strike > 0 else 0.0
    sigma = max(annualized_vol, 1e-6)
    z = log_moneyness / (sigma * math.sqrt(t_years))
    return max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


def _hybrid_delta(
    asset: str,
    velocity: float,
    macd_histogram: float,
    rsi: float,
    spot_price: float,
    price_above_ema200: bool,
    macro_regime: str,
) -> float:
    """Replica of the indicator-stack confluence delta used by _compute_hybrid_p_yes."""
    velocity_threshold = VELOCITY_THRESHOLDS[asset]
    velocity_edge = 0.0
    if velocity_threshold and abs(velocity) >= velocity_threshold:
        edge_pct = abs(velocity / velocity_threshold) * 2.0
        max_edge_pct = 15.0
        velocity_edge = math.copysign(min(edge_pct, max_edge_pct) / 100.0, velocity)

    delta = velocity_edge

    # MACD shift, normalized by spot and capped at 5pp.
    macd_delta = 0.0
    if spot_price and math.isfinite(spot_price) and spot_price > 0 and math.isfinite(macd_histogram):
        macd_delta = (macd_histogram / spot_price) * 10.0
        macd_delta = math.copysign(min(abs(macd_delta), 0.05), macd_delta)
    delta += macd_delta

    # RSI shift.
    rsi_delta = 0.0
    if rsi < 35.0:
        rsi_delta = 0.02
    elif rsi > 65.0:
        rsi_delta = -0.02
    delta += rsi_delta

    # Macro-regime alignment penalty.
    regime_delta = 0.0
    if macro_regime == "bull" and not price_above_ema200:
        regime_delta = -0.01
    elif macro_regime == "bear" and price_above_ema200:
        regime_delta = 0.01
    delta += regime_delta

    max_shift = 0.15
    return math.copysign(min(abs(delta), max_shift), delta)


def _build_synthetic_series(
    start_price: float = 150.0,
    n_bars: int = 120,
    trend_per_bar: float = 0.0004,
    noise_sigma: float = 0.0015,
    seed: int = 42,
) -> List[Tuple[float, float]]:
    """Generate a 1-minute close price series (timestamp, close).

    The last bar is timestamped at the current wall clock so the indicator
    stack staleness gate does not trip during the audit.
    """
    # Simple deterministic pseudo-random noise.
    prices: List[float] = []
    rand_state = seed
    price = start_price
    for i in range(n_bars):
        rand_state = (rand_state * 1103515245 + 12345) % (2**31)
        noise = (rand_state / (2**31) - 0.5) * 2.0 * noise_sigma
        price = price * (1.0 + trend_per_bar + noise)
        prices.append(price)
    now = time.time()
    # Last bar is now, first bar is (n_bars - 1) minutes ago.
    return [(now - (n_bars - 1 - i) * 60.0, p) for i, p in enumerate(prices)]


def _feed_stack(asset: str, series: List[Tuple[float, float]], kalshi_mode: bool = True) -> Any:
    """Instantiate an asset-specific Crypto15mIndicatorStack and feed it a 1m series."""
    cfg = IndicatorConfig(asset=asset, kalshi_mode=kalshi_mode)
    # Disable the staleness gate during the audit so shifted/artificial series are not rejected.
    cfg.staleness_threshold_seconds = 999999.0
    stack = Crypto15mIndicatorStack(config=cfg)
    stack.set_asset_symbol(asset)
    for ts, price in series:
        stack.update_with_timestamp(price, ts)
    return stack


def _internal_multi_window_velocity(
    series: List[Tuple[float, float]],
    windows: List[int] = None,
    weights: List[float] = None,
) -> float:
    """Replica of _calculate_internal_multi_window_velocity (no EMA/Z-score/ATR normalization)."""
    windows = windows or [10, 30, 60]
    weights = weights or [0.2, 0.3, 0.5]
    if len(series) < 2:
        return 0.0
    current_time = int(series[-1][0] * 1000)
    current_price = series[-1][1]
    weighted_velocity = 0.0
    for window_sec, weight in zip(windows, weights):
        target_time = current_time - window_sec * 1000
        prev_price = None
        for entry in reversed(series):
            ts = int(entry[0] * 1000)
            price = entry[1]
            if ts <= target_time:
                prev_price = price
                break
        if prev_price is None or prev_price <= 0:
            continue
        window_velocity = (current_price - prev_price) / prev_price
        weighted_velocity += weight * window_velocity
    return weighted_velocity


def _run_sign_and_shift_test(asset: str, series: List[Tuple[float, float]]) -> AuditResult:
    """Run sign-consistency and one-bar shift checks for one asset."""
    stack = _feed_stack(asset, series)
    snap = stack.snapshot()
    price_change = series[-1][1] - series[-2][1]
    price = series[-1][1]

    # Internal velocity (fallback path used when Coinbase signal is stale).
    velocity = _internal_multi_window_velocity(series)

    # Bachelier + hybrid with strike equal to the current price so the
    # baseline is 0.5 and only the indicator shift drives direction.
    strike = price
    seconds_to_expiry = 300.0
    p_yes_bachelier = _bachelier_p_yes(price, strike, seconds_to_expiry, ANNUALIZED_VOL_DEFAULTS[asset])
    hybrid_delta = _hybrid_delta(
        asset,
        velocity,
        snap.macd_histogram,
        snap.rsi,
        price,
        snap.price_above_ema_200,
        snap.macro_regime,
    )
    p_yes_hybrid = max(1e-6, min(1.0 - 1e-6, p_yes_bachelier + hybrid_delta))

    # One-bar shift: recompute with the previous bar treated as the current bar.
    shifted_series = series[:-1]
    shifted_velocity = _internal_multi_window_velocity(shifted_series)
    shifted_price = shifted_series[-1][1]
    shifted_snap = _feed_stack(asset, shifted_series).snapshot()
    shifted_p_yes_bachelier = _bachelier_p_yes(
        shifted_price, shifted_price, seconds_to_expiry + 60.0, ANNUALIZED_VOL_DEFAULTS[asset]
    )
    shifted_hybrid_delta = _hybrid_delta(
        asset,
        shifted_velocity,
        shifted_snap.macd_histogram,
        shifted_snap.rsi,
        shifted_price,
        shifted_snap.price_above_ema_200,
        shifted_snap.macro_regime,
    )
    shifted_p_yes_hybrid = max(1e-6, min(1.0 - 1e-6, shifted_p_yes_bachelier + shifted_hybrid_delta))

    # Sign agreement: the computed indicators must match the direction of the
    # last price change. For a rising last bar we expect positive velocity,
    # RSI >= 50, p_yes >= 0.5; for a falling last bar the opposite.
    expected_up = price_change > 0
    if expected_up:
        sign_agreement = (
            (velocity > 0)
            and (snap.rsi >= 50)
            and (p_yes_hybrid >= 0.5)
            and not (snap.macd_histogram < 0)
        )
    else:
        sign_agreement = (
            (velocity < 0)
            and (snap.rsi <= 50)
            and (p_yes_hybrid <= 0.5)
            and not (snap.macd_histogram > 0)
        )

    return AuditResult(
        asset=asset,
        velocity=velocity,
        macd_histogram=snap.macd_histogram,
        rsi=snap.rsi,
        price_above_ema200=snap.price_above_ema_200,
        macro_regime=snap.macro_regime,
        p_yes_bachelier=p_yes_bachelier,
        p_yes_hybrid=p_yes_hybrid,
        sign_agreement=sign_agreement,
        one_bar_shift_velocity=shifted_velocity,
        one_bar_shift_p_yes_hybrid=shifted_p_yes_hybrid,
    )


def build_parameter_matrix() -> Dict[str, Dict[str, Any]]:
    """Build the cross-asset parameter matrix from live class instances."""
    matrix = {}
    for asset in ASSETS:
        cfg = IndicatorConfig(asset=asset, kalshi_mode=True)
        matrix[asset] = {
            "annualized_vol_default": ANNUALIZED_VOL_DEFAULTS[asset],
            "velocity_threshold": VELOCITY_THRESHOLDS[asset],
            "cfb_settlement_symbol": CFB_SETTLEMENT_SYMBOLS[asset],
            "ema_trend_period": cfg.ema_trend_period,
            "ema_fast_period": cfg.ema_fast_period,
            "ema_slow_period": cfg.ema_slow_period,
            "rsi_oversold": cfg.rsi_oversold_asset or cfg.rsi_oversold,
            "rsi_overbought": cfg.rsi_overbought_asset or cfg.rsi_overbought,
            "atr_min_move_pct": cfg.atr_min_move_pct,
            "consecutive_closes_required": cfg.consecutive_closes_required,
            "macd_persistence_bars": cfg.macd_persistence_bars,
            "macd_histogram_min_pct": cfg.macd_histogram_min_pct,
            "kalshi_mode": cfg.kalshi_mode,
        }
    return matrix


def format_matrix(matrix: Dict[str, Dict[str, Any]]) -> str:
    rows = []
    rows.append("| Param | BTC | ETH | SOL | XRP | DOGE |")
    rows.append("|---|---|---|---|---|---|")
    keys = list(matrix["BTC"].keys())
    for key in keys:
        vals = [str(matrix[a][key]) for a in ASSETS]
        rows.append(f"| {key} | {' | '.join(vals)} |")
    return "\n".join(rows)


def run_sign_consistency_audit() -> Tuple[List[AuditResult], List[Tuple[float, float]]]:
    """Run the sign-consistency and one-bar shift test on all five assets."""
    series = _build_synthetic_series(start_price=150.0, n_bars=120, trend_per_bar=0.0010, noise_sigma=0.0015)
    price_change = series[-1][1] - series[-2][1]
    total_return = (series[-1][1] - series[0][1]) / series[0][1]
    results = []
    for asset in ASSETS:
        res = _run_sign_and_shift_test(asset, series)
        res.notes.append(f"series total return = {total_return:.4%}")
        res.notes.append(f"last-bar price change = {price_change:.4f}")
        results.append(res)
    return results, series


def run_declining_series_test() -> List[AuditResult]:
    """Run the same checks on a declining series to verify negative signs."""
    series = _build_synthetic_series(start_price=170.0, n_bars=120, trend_per_bar=-0.0010, noise_sigma=0.0015, seed=43)
    results = []
    for asset in ASSETS:
        res = _run_sign_and_shift_test(asset, series)
        res.notes.append(f"declining series total return = {(series[-1][1] - series[0][1]) / series[0][1]:.4%}")
        results.append(res)
    return results


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
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


def _to_ms(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _side_match(selected: Optional[str], realized: Optional[str]) -> bool:
    if not selected or not realized:
        return False
    return selected.lower() == realized.lower()


def _bin_staleness(ms: Optional[float]) -> str:
    if ms is None:
        return "missing"
    if ms < 1000:
        return "<1s"
    if ms < 10000:
        return "1-10s"
    if ms < 30000:
        return "10-30s"
    if ms < 60000:
        return "30-60s"
    if ms < 120000:
        return "60-120s"
    return ">120s"


def run_predictiveness_audit(
    shadow_path: Optional[str] = None,
    settlement_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute feed-alignment / feature-target correlations from shadow telemetry.

    If a settlement JSONL is supplied, it should contain at least `decision_id`
    and `realized_outcome` (yes/no) per line. The audit joins it to the shadow
    records and computes wrong-side rates by feed staleness, velocity source,
    and CF RTI eligibility.
    """
    if not shadow_path or not Path(shadow_path).exists():
        return {
            "status": "no_data",
            "message": (
                "Predictiveness audit requires a shadow telemetry file. "
                "Set MERID_SHADOW_SIDE_TELEMETRY_PATH or pass a path to a JSONL file."
            ),
        }

    records = _read_jsonl(shadow_path)
    if not records:
        return {"status": "empty", "path": str(shadow_path)}

    realized_by_decision: Dict[str, str] = {}
    if settlement_path and Path(settlement_path).exists():
        for row in _read_jsonl(settlement_path):
            decision_id = row.get("decision_id")
            if decision_id:
                realized_by_decision[decision_id] = str(row.get("realized_outcome", "")).lower()
    else:
        # Some deployments inline the realized outcome in the shadow record.
        for row in records:
            decision_id = row.get("decision_id")
            realized = row.get("realized_outcome")
            if decision_id and realized:
                realized_by_decision[decision_id] = str(realized).lower()

    rows = []
    for rec in records:
        extra = rec.get("extra") or {}
        decision_id = rec.get("decision_id")
        asset = rec.get("asset", "UNKNOWN")
        selected = (rec.get("live") or {}).get("selected_side")
        realized = realized_by_decision.get(decision_id)
        wrong = False
        if selected and realized:
            wrong = selected.lower() != realized

        rows.append(
            {
                "asset": asset,
                "selected_side": selected,
                "realized_outcome": realized,
                "wrong": wrong,
                "p_yes_model": _to_ms(rec.get("p_yes_model")),
                "velocity": _to_ms(rec.get("velocity")),
                "spot_staleness_ms": _to_ms(extra.get("spot_staleness_ms")),
                "spot_source": extra.get("spot_source"),
                "spot_timestamp_ms": _to_ms(extra.get("spot_timestamp_ms")),
                "velocity_age_ms": _to_ms(extra.get("velocity_age_ms")),
                "velocity_source": extra.get("velocity_source"),
                "velocity_signal_type": extra.get("velocity_signal_type"),
                "velocity_threshold_used": _to_ms(extra.get("velocity_threshold_used")),
                "cfb_age_ms": _to_ms(extra.get("cfb_age_ms")),
                "cfb_execution_eligible": extra.get("cfb_execution_eligible"),
                "cfb_source_ts_ms": _to_ms(extra.get("cfb_source_ts_ms")),
                "cfb_observed_ts_ms": _to_ms(extra.get("cfb_observed_ts_ms")),
                "settlement_reference": extra.get("cfb_settlement_reference")
                    or rec.get("settlement_reference"),
            }
        )

    if not rows:
        return {"status": "no_parsable_records", "path": str(shadow_path)}

    # Per-asset feed-alignment summary.
    per_asset: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        per_asset.setdefault(r["asset"], []).append(r)

    summary: Dict[str, Any] = {
        "status": "ok",
        "total_records": len(rows),
        "records_with_outcome": sum(1 for r in rows if r["realized_outcome"]),
        "per_asset": {},
    }

    for asset, recs in per_asset.items():
        n = len(recs)
        spot_staleness = [s for s in (r["spot_staleness_ms"] for r in recs) if s is not None]
        velocity_age = [a for a in (r["velocity_age_ms"] for r in recs) if a is not None]
        cfb_age = [a for a in (r["cfb_age_ms"] for r in recs) if a is not None]

        fallback_pct = (
            sum(1 for r in recs if r["velocity_source"] == "internal_fallback") / n * 100.0
            if n else 0.0
        )
        cfb_ineligible_pct = (
            sum(1 for r in recs if r["cfb_execution_eligible"] is False) / n * 100.0
            if n else 0.0
        )

        asset_summary = {
            "n_records": n,
            "mean_spot_staleness_ms": statistics.mean(spot_staleness) if spot_staleness else None,
            "median_spot_staleness_ms": statistics.median(spot_staleness) if spot_staleness else None,
            "mean_velocity_age_ms": statistics.mean(velocity_age) if velocity_age else None,
            "median_velocity_age_ms": statistics.median(velocity_age) if velocity_age else None,
            "mean_cfb_age_ms": statistics.mean(cfb_age) if cfb_age else None,
            "median_cfb_age_ms": statistics.median(cfb_age) if cfb_age else None,
            "velocity_internal_fallback_pct": fallback_pct,
            "cfb_ineligible_pct": cfb_ineligible_pct,
        }

        if any(r["realized_outcome"] for r in recs):
            outcomes = [r for r in recs if r["realized_outcome"]]
            wrong_rate = sum(1 for r in outcomes if r["wrong"]) / len(outcomes) * 100.0
            asset_summary["n_with_outcome"] = len(outcomes)
            asset_summary["wrong_side_rate_pct"] = wrong_rate

            # Wrong-side rate by spot staleness bin.
            bin_stats: Dict[str, Dict[str, int]] = {}
            for r in outcomes:
                b = _bin_staleness(r["spot_staleness_ms"])
                bin_stats.setdefault(b, {"n": 0, "wrong": 0})
                bin_stats[b]["n"] += 1
                if r["wrong"]:
                    bin_stats[b]["wrong"] += 1
            asset_summary["wrong_rate_by_spot_staleness_bin"] = {
                b: {"n": s["n"], "wrong_pct": s["wrong"] / s["n"] * 100.0}
                for b, s in sorted(bin_stats.items(), key=lambda x: x[1]["n"], reverse=True)
                if s["n"] > 0
            }

            # Wrong-side rate by velocity source.
            source_stats: Dict[str, Dict[str, int]] = {}
            for r in outcomes:
                src = r["velocity_source"] or "unknown"
                source_stats.setdefault(src, {"n": 0, "wrong": 0})
                source_stats[src]["n"] += 1
                if r["wrong"]:
                    source_stats[src]["wrong"] += 1
            asset_summary["wrong_rate_by_velocity_source"] = {
                src: {"n": s["n"], "wrong_pct": s["wrong"] / s["n"] * 100.0}
                for src, s in sorted(source_stats.items(), key=lambda x: x[1]["n"], reverse=True)
                if s["n"] > 0
            }

            # Simple Pearson correlation of wrong side with feed ages.
            def _corr(x: List[float], y: List[int]) -> Optional[float]:
                if len(x) < 2:
                    return None
                n = len(x)
                mean_x = sum(x) / n
                mean_y = sum(y) / n
                num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
                den_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
                den_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
                if den_x == 0 or den_y == 0:
                    return None
                return num / (den_x * den_y)

            wrong_int = [1 if r["wrong"] else 0 for r in outcomes]
            asset_summary["correlation_wrong_with_spot_staleness"] = _corr(
                [r["spot_staleness_ms"] for r in outcomes if r["spot_staleness_ms"] is not None],
                [1 if r["wrong"] else 0 for r in outcomes if r["spot_staleness_ms"] is not None],
            )
            asset_summary["correlation_wrong_with_velocity_age"] = _corr(
                [r["velocity_age_ms"] for r in outcomes if r["velocity_age_ms"] is not None],
                [1 if r["wrong"] else 0 for r in outcomes if r["velocity_age_ms"] is not None],
            )
            asset_summary["correlation_wrong_with_cfb_age"] = _corr(
                [r["cfb_age_ms"] for r in outcomes if r["cfb_age_ms"] is not None],
                [1 if r["wrong"] else 0 for r in outcomes if r["cfb_age_ms"] is not None],
            )

        summary["per_asset"][asset] = asset_summary

    # Global flag: any bin with elevated wrong-side rate.
    elevated: List[str] = []
    for asset, asset_summary in summary["per_asset"].items():
        for b, s in asset_summary.get("wrong_rate_by_spot_staleness_bin", {}).items():
            if s["n"] >= 10 and s["wrong_pct"] > 60:
                elevated.append(f"{asset} spot_staleness_bin={b}: {s['wrong_pct']:.1f}% wrong (n={s['n']})")
        for src, s in asset_summary.get("wrong_rate_by_velocity_source", {}).items():
            if s["n"] >= 10 and s["wrong_pct"] > 60:
                elevated.append(f"{asset} velocity_source={src}: {s['wrong_pct']:.1f}% wrong (n={s['n']})")

    summary["feed_alignment_elevated_wrong_rate"] = elevated
    if elevated:
        summary["feed_alignment_conclusion"] = (
            "Elevated wrong-side rates cluster with feed staleness/fallback source. "
            "This supports the feed-alignment inversion hypothesis."
        )
    else:
        summary["feed_alignment_conclusion"] = (
            "No strong clustering of wrong-side trades with staleness/fallback source "
            "was observed in the provided data."
        )

    return summary


def main() -> None:
    print("=" * 80)
    print("CROSS-ASSET VELOCITY & INDICATOR-STACK CORRECTNESS AUDIT")
    print("=" * 80)

    # 1. Parameter matrix.
    print("\n--- 1. Cross-asset parameter matrix (kalshi_mode=True) ---\n")
    matrix = build_parameter_matrix()
    print(format_matrix(matrix))

    # 1b. Identify parameter copy-paste candidates.
    print("\n--- 1b. Parameter copy-paste / identity flags ---\n")
    dupes: Dict[str, List[str]] = {}
    for key in matrix["BTC"]:
        groups: Dict[Any, List[str]] = {}
        for asset in ASSETS:
            groups.setdefault(matrix[asset][key], []).append(asset)
        for value, assets in groups.items():
            if len(assets) > 1 and key not in ("kalshi_mode",):
                dupes.setdefault(key, []).append(f"{value}: {','.join(assets)}")
    if dupes:
        for key, items in dupes.items():
            for item in items:
                print(f"  {key} shared: {item}")
    else:
        print("  No duplicate parameter values detected.")

    # 2. Sign-consistency + shift test.
    print("\n--- 2. Sign-consistency and one-bar shift test ---\n")
    results, series = run_sign_consistency_audit()
    print(f"Synthetic series: {len(series)} bars, start={series[0][1]:.4f}, end={series[-1][1]:.4f}")
    print(f"Overall price change (last - first): {series[-1][1] - series[0][1]:.4f}")
    print(f"Last-bar price change: {series[-1][1] - series[-2][1]:.4f}")
    print()
    print("| Asset | Velocity | MACD hist | RSI | p_yes_bach | p_yes_hyb | sign_ok | shift_velocity | shift_p_yes |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r.asset} | {r.velocity:.6f} | {r.macd_histogram:.6f} | {r.rsi:.2f} | "
            f"{r.p_yes_bachelier:.4f} | {r.p_yes_hybrid:.4f} | {r.sign_agreement} | "
            f"{r.one_bar_shift_velocity:.6f} | {r.one_bar_shift_p_yes_hybrid:.4f} |"
        )

    # 2b. Declining-series sign check.
    print("\n--- 2b. Declining-series sign-consistency check ---\n")
    decline_results = run_declining_series_test()
    print("| Asset | Velocity | MACD hist | RSI | p_yes_bach | p_yes_hyb | sign_ok |")
    print("|---|---|---|---|---|---|---|")
    for r in decline_results:
        print(
            f"| {r.asset} | {r.velocity:.6f} | {r.macd_histogram:.6f} | {r.rsi:.2f} | "
            f"{r.p_yes_bachelier:.4f} | {r.p_yes_hybrid:.4f} | {r.sign_agreement} |"
        )

    # 3. Classify fingerprints.
    print("\n--- 3. Cross-asset fingerprint classification ---\n")
    # Use the hybrid p_yes to pick a side and compare to the known rising series.
    for r in results:
        side = "YES" if r.p_yes_hybrid >= 0.5 else "NO"
        correct = side == "YES"
        print(f"  {r.asset}: selected={side}, correct_vs_series={correct}")
    for r in decline_results:
        side = "YES" if r.p_yes_hybrid >= 0.5 else "NO"
        correct = side == "NO"
        print(f"  {r.asset} (decline): selected={side}, correct_vs_series={correct}")

    # 4. SOL-specific source/staleness notes.
    print("\n--- 4. SOL-specific settlement reference and source notes ---\n")
    sol_cfg = IndicatorConfig(asset="SOL", kalshi_mode=True)
    print(f"  SOL CF-RTI symbol: {CFB_SETTLEMENT_SYMBOLS['SOL']}")
    print(f"  SOL indicator staleness threshold (s): {sol_cfg.staleness_threshold_seconds}")
    print(f"  SOL annualized_vol default: {ANNUALIZED_VOL_DEFAULTS['SOL']}")
    print(f"  SOL velocity_threshold: {VELOCITY_THRESHOLDS['SOL']}")
    print("  Notes:")
    print("    - _get_settlement_input_price uses cfb_60s_average when execution_eligible.")
    print("    - Coinbase velocity is authoritative when fresh (<120s); internal fallback otherwise.")
    print("    - Agent 1m bars are built from per-tick spot provider updates (see _indicator_stack_price_buffer).")

    # 5. Predictiveness / feed-alignment audit.
    print("\n--- 5. Predictiveness / feature-importance audit ---\n")
    shadow_path = os.environ.get("MERID_SHADOW_SIDE_TELEMETRY_PATH", "logs/shadow_side_telemetry.jsonl")
    settlement_path = os.environ.get("MERID_SHADOW_SETTLEMENT_PATH")
    pred = run_predictiveness_audit(shadow_path, settlement_path)
    print(f"  Status: {pred['status']}")
    if "message" in pred:
        print(f"  {pred['message']}")
    if pred.get("status") == "ok":
        print(f"  Total records: {pred['total_records']}")
        print(f"  Records with realized outcome: {pred['records_with_outcome']}")
        print("  Per-asset feed-alignment summary:")
        for asset, s in sorted(pred["per_asset"].items()):
            print(f"    {asset}: n={s['n_records']}", end="")
            if s.get("wrong_side_rate_pct") is not None:
                print(f" wrong_rate={s['wrong_side_rate_pct']:.2f}%", end="")
            if s.get("mean_spot_staleness_ms") is not None:
                print(f" spot_staleness_ms={s['mean_spot_staleness_ms']:.0f}", end="")
            if s.get("mean_velocity_age_ms") is not None:
                print(f" velocity_age_ms={s['mean_velocity_age_ms']:.0f}", end="")
            if s.get("mean_cfb_age_ms") is not None:
                print(f" cfb_age_ms={s['mean_cfb_age_ms']:.0f}", end="")
            print()
            for b, bs in s.get("wrong_rate_by_spot_staleness_bin", {}).items():
                print(f"      spot_bin={b}: n={bs['n']}, wrong={bs['wrong_pct']:.1f}%")
            for src, ss in s.get("wrong_rate_by_velocity_source", {}).items():
                print(f"      velocity_source={src}: n={ss['n']}, wrong={ss['wrong_pct']:.1f}%")
            if s.get("correlation_wrong_with_spot_staleness") is not None:
                print(f"      corr(wrong, spot_staleness)={s['correlation_wrong_with_spot_staleness']:.3f}")
            if s.get("correlation_wrong_with_velocity_age") is not None:
                print(f"      corr(wrong, velocity_age)={s['correlation_wrong_with_velocity_age']:.3f}")
            if s.get("correlation_wrong_with_cfb_age") is not None:
                print(f"      corr(wrong, cfb_age)={s['correlation_wrong_with_cfb_age']:.3f}")
        if pred.get("feed_alignment_elevated_wrong_rate"):
            print("  Feed-alignment red flags:")
            for e in pred["feed_alignment_elevated_wrong_rate"]:
                print(f"    - {e}")
        print(f"  Conclusion: {pred['feed_alignment_conclusion']}")

    # 6. Key findings / warnings.
    print("\n--- 6. Auditor warnings ---\n")
    warnings: List[str] = []

    # Warning: IndicatorConfig asset-specific EMA/RSI tuning may still be overridden
    # by the momentum_fvg signal path in agent_grid_15m.py (hardcoded 30/70 and
    # regime-shifted 35/75/25/65 thresholds at lines 4770-4802).
    btc_cfg = IndicatorConfig(asset="BTC", kalshi_mode=True)
    sol_cfg = IndicatorConfig(asset="SOL", kalshi_mode=True)
    if btc_cfg.rsi_oversold_asset == sol_cfg.rsi_oversold_asset:
        warnings.append(
            "NOTE: IndicatorConfig per-asset RSI thresholds are set, but the "
            "momentum_fvg signal path in agent_grid_15m.py recalculates rsi_zone "
            "with hardcoded thresholds and does not read IndicatorConfig."
        )

    # Warning: SOL and XRP share annualized_vol and velocity_threshold.
    if ANNUALIZED_VOL_DEFAULTS["SOL"] == ANNUALIZED_VOL_DEFAULTS["XRP"]:
        warnings.append(
            "SOL and XRP share the same annualized_vol (1.00). If their realized "
            "volatilities differ, the Bachelier z-score is mis-scaled for one of them."
        )
    if VELOCITY_THRESHOLDS["SOL"] == VELOCITY_THRESHOLDS["XRP"]:
        warnings.append(
            "SOL and XRP share the same velocity_threshold (0.000225). A copy-paste "
            "calibration error is possible if their typical 60s returns differ."
        )

    # Sign-check warnings.
    for r in results:
        if not r.sign_agreement:
            warnings.append(
                f"{r.asset}: sign-consistency FAILED on a rising synthetic series "
                f"(velocity={r.velocity:.6f}, macd_hist={r.macd_histogram:.6f}, "
                f"rsi={r.rsi:.2f}, p_yes_hybrid={r.p_yes_hybrid:.4f})."
            )

    if warnings:
        for w in warnings:
            print(f"  - {w}")
    else:
        print("  No warnings generated.")

    print("\n" + "=" * 80)
    print("Audit complete.")
    print("=" * 80)


if __name__ == "__main__":
    main()
