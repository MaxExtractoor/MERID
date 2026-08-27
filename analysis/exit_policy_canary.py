#!/usr/bin/env python3
"""
Forward exit-policy canary for MERID / Kalshi 15m crypto.

This is a shadow (paper) harness.  It does not submit orders.  It tails the
live fills table and the live ``EXIT_EVAL`` telemetry, maintains a
``safety_rails`` exit policy state, and paper-executes safety exits at the
executable price captured by ``PositionMonitor`` at the moment the trigger
fires.  For each completed round trip it records:

- what the live system actually did (``actual_active``)
- what a safety-rails-only policy would have done, using the real-time book
  price logged in ``EXIT_EVAL``
- whether the safety paper exit would have filled, by comparing it to any
  subsequent real fill
- whether production fills have no matching ``EXIT_EVAL`` trigger

Run it as a cron every 60-300 seconds, or with ``--watch`` to poll continuously.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Load the replay module as a library.
_CANARY_DIR = Path(__file__).resolve().parent
_REPLAY_PATH = _CANARY_DIR / "exit_strategy_replay.py"
_spec = importlib.util.spec_from_file_location("exit_strategy_replay", _REPLAY_PATH)
_replay = importlib.util.module_from_spec(_spec)
sys.modules["exit_strategy_replay"] = _replay
_spec.loader.exec_module(_replay)

# Re-export the names the canary needs.
Fill = _replay.Fill
ExitEval = _replay.ExitEval
RoundTrip = _replay.RoundTrip
StrategyResult = _replay.StrategyResult
SAFETY_EXIT_REASONS = _replay.SAFETY_EXIT_REASONS
ACTIVE_EXIT_REASONS = _replay.ACTIVE_EXIT_REASONS


def _rt_key(rt: RoundTrip) -> Tuple[str, str, str, float]:
    return (rt.market_ticker, rt.side, rt.entry_time.isoformat(), rt.size)


def _match_key(m: _replay.TriggerMatch) -> Tuple[str, str, str, float]:
    return (m.market_ticker, m.side, m.actual_exit_time.isoformat(), m.size)


def _actual_exit_key(rt: RoundTrip) -> Optional[Tuple[str, str, str, float]]:
    if not rt.actual_exit or rt.exit_time is None:
        return None
    return (rt.market_ticker, rt.side, rt.exit_time.isoformat(), rt.size)


def _parse_watermark(path: Path) -> Optional[datetime]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return datetime.fromisoformat(data["last_processed_at"])
    except Exception:
        return None


def _write_watermark(path: Path, ts: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"last_processed_at": ts.isoformat()}, f, indent=2)


def build_canary_record(
    actual: RoundTrip,
    safety: RoundTrip,
    match: Optional[_replay.TriggerMatch],
    settlements: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a single per-trade canary record."""
    settlement = settlements.get(actual.market_ticker, {})
    outcome = settlement.get("outcome")
    settlement_time = settlement.get("settlement_timestamp_utc")

    # Safety paper exit state (what safety_rails would do).
    safety_paper_filled = (
        safety.filled
        and safety.exit_reason is not None
        and safety.exit_reason != "HOLD_TO_SETTLEMENT"
        and not safety.exit_reason.startswith("UNFILLED_")
    )
    safety_unfilled = not safety.filled and str(safety.exit_reason or "").startswith("UNFILLED_")
    safety_trigger_time = safety.exit_time if safety_paper_filled or safety_unfilled else None
    safety_trigger_reason = safety.exit_reason if safety_paper_filled or safety_unfilled else None
    safety_paper_exit_price = safety.exit_price_cents if safety_paper_filled else None

    # Actual production fill: nearest EXIT_EVAL trigger that explains it, if any.
    actual_matched_reason = match.trigger_reason if match else None
    actual_matched_price = match.trigger_price_cents if match else None

    # Did the production exit have no EXIT_EVAL trigger at all?
    no_exit_eval = actual.actual_exit and (match is None or match.status == "no_exit_eval")

    # Heuristic classification of unexplained production exits.
    no_exit_eval_cause = None
    if no_exit_eval and actual.exit_time and settlement_time:
        seconds_to_settlement = (settlement_time - actual.exit_time).total_seconds()
        if seconds_to_settlement <= 120:
            no_exit_eval_cause = "near_settlement"
        elif (actual.exit_price_cents or 0.0) >= 95.0 or (actual.exit_price_cents or 0.0) <= 5.0:
            no_exit_eval_cause = "near_boundary_99_or_0"
        elif actual.net_pnl_cents < 0:
            no_exit_eval_cause = "suspected_stop_loss"
        elif actual.net_pnl_cents > 0:
            no_exit_eval_cause = "suspected_manual_or_tp"
        else:
            no_exit_eval_cause = "unknown"

    # Determine whether the actual fill confirms the paper safety fill.
    # "Exact" confirmation: actual fill within 5c and 30s of the paper safety exit.
    paper_confirmed = False
    paper_vs_actual_price_gap: Optional[float] = None
    paper_vs_actual_time_gap: Optional[float] = None
    if safety_paper_filled and actual.actual_exit and actual.exit_time and safety_trigger_time:
        paper_vs_actual_time_gap = (actual.exit_time - safety_trigger_time).total_seconds()
        paper_vs_actual_price_gap = (actual.exit_price_cents or 0.0) - (safety_paper_exit_price or 0.0)
        paper_confirmed = abs(paper_vs_actual_price_gap) <= 5.0 and 0 <= paper_vs_actual_time_gap <= 30

    # Near-coincidence cross-check: any actual fill within 15s and 3c of the
    # paper safety trigger.  This is the independent real-fill validation the
    # safety side needs, even when the live system exited for a different reason.
    safety_near_coincidence = False
    safety_near_coincidence_price_gap: Optional[float] = None
    safety_near_coincidence_time_gap: Optional[float] = None
    if safety_paper_filled and actual.actual_exit and actual.exit_time and safety_trigger_time:
        safety_near_coincidence_time_gap = (actual.exit_time - safety_trigger_time).total_seconds()
        safety_near_coincidence_price_gap = (actual.exit_price_cents or 0.0) - (safety_paper_exit_price or 0.0)
        safety_near_coincidence = (
            abs(safety_near_coincidence_price_gap) <= 3.0
            and -5 <= safety_near_coincidence_time_gap <= 15
        )

    return {
        "market_ticker": actual.market_ticker,
        "side": actual.side,
        "size": actual.size,
        "entry_time": actual.entry_time.isoformat() if actual.entry_time else None,
        "entry_price_cents": actual.entry_price_cents,
        "entry_fee_cents": actual.entry_fee_cents,
        "settlement_outcome": outcome,
        "settlement_time": settlement_time.isoformat() if settlement_time else None,
        "actual_exit": actual.actual_exit,
        "actual_exit_time": actual.exit_time.isoformat() if actual.exit_time else None,
        "actual_exit_price_cents": actual.exit_price_cents,
        "actual_exit_fee_cents": actual.exit_fee_cents,
        "actual_net_pnl_cents": actual.net_pnl_cents,
        "actual_matched_trigger_reason": actual_matched_reason,
        "actual_matched_trigger_price_cents": actual_matched_price,
        "actual_no_exit_eval": no_exit_eval,
        "actual_no_exit_eval_suspected_cause": no_exit_eval_cause,
        "safety_trigger_time": safety_trigger_time.isoformat() if safety_trigger_time else None,
        "safety_trigger_reason": safety_trigger_reason,
        "safety_executable_price_cents": safety_paper_exit_price,
        "safety_book_valid": safety_paper_filled or safety_unfilled,
        "safety_paper_filled": safety_paper_filled,
        "safety_paper_would_fill": safety_paper_filled,  # True only when book_valid was True
        "safety_paper_exit_price_cents": safety_paper_exit_price,
        "safety_rescue_used": safety.rescue_trigger_time is not None,
        "safety_unfilled": safety_unfilled,
        "safety_unfilled_reason": safety.exit_reason if safety_unfilled else None,
        "safety_net_pnl_cents": safety.net_pnl_cents,
        "paper_confirmed_by_actual_fill": paper_confirmed,
        "paper_vs_actual_price_gap_cents": paper_vs_actual_price_gap,
        "paper_vs_actual_time_gap_seconds": paper_vs_actual_time_gap,
        "safety_near_coincidence": safety_near_coincidence,
        "safety_near_coincidence_price_gap_cents": safety_near_coincidence_price_gap,
        "safety_near_coincidence_time_gap_seconds": safety_near_coincidence_time_gap,
        "pnl_delta_cents": safety.net_pnl_cents - actual.net_pnl_cents,
    }


def _fmt_cents(c: float) -> str:
    return f"${c / 100.0:,.2f}"


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _sharpe(values: List[float]) -> float:
    s = _std(values)
    return _mean(values) / s if s > 0 else 0.0


def _compute_delta_drawdown(records: List[Dict[str, Any]]) -> float:
    """Worst running drawdown of the per-trade safety-vs-actual delta series."""
    if not records:
        return 0.0

    def _ts(r: Dict[str, Any]) -> Optional[datetime]:
        for key in ("safety_trigger_time", "actual_exit_time", "settlement_time"):
            v = r.get(key)
            if v:
                return datetime.fromisoformat(v)
        return None

    timed = [(r, _ts(r)) for r in records]
    timed = [(r, t) for r, t in timed if t is not None]
    if not timed:
        return 0.0
    timed.sort(key=lambda x: x[1])

    peak = 0.0
    running = 0.0
    dd = 0.0
    for r, _ in timed:
        running += r["pnl_delta_cents"]
        if running > peak:
            peak = running
        dd = max(dd, peak - running)
    return dd


def _safe_ratio(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _lag1_autocorr(values: List[float]) -> float:
    if len(values) < 3:
        return 0.0
    # Order by the caller; this is a simple lag-1 Pearson estimate.
    x = values[:-1]
    y = values[1:]
    mx = _mean(x)
    my = _mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    denx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    deny = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)


def _effective_sample_size(values: List[float]) -> float:
    """Conservative effective N penalizing serial correlation and concentration."""
    n = len(values)
    if n < 2:
        return 1.0
    rho = _lag1_autocorr(values)
    # AR(1) effective sample size. Clamp rho to [-0.99, 0.99] to avoid blow-ups.
    rho = max(-0.99, min(0.99, rho))
    n_autocorr = max(1.0, n * (1.0 - rho) / (1.0 + rho))
    # Concentration penalty using absolute delta weights (Herfindahl-style).
    total_abs = sum(abs(v) for v in values)
    sum_sq = sum(v * v for v in values)
    n_concentration = max(1.0, total_abs * total_abs / sum_sq) if sum_sq > 0 else 1.0
    return max(1.0, min(n_autocorr, n_concentration))


def _bootstrap_ci(
    values: List[float],
    n_resamples: int = 10000,
    alpha: float = 0.05,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Bootstrap 95% CI for (mean, Sharpe)."""
    if not values:
        return ((0.0, 0.0), (0.0, 0.0))
    n = len(values)
    rng = range(n)
    means = []
    sharpes = []
    for _ in range(n_resamples):
        sample = [values[random.randrange(n)] for _ in rng]
        means.append(_mean(sample))
        sharpes.append(_sharpe(sample))
    means.sort()
    sharpes.sort()
    lo = int(alpha / 2 * n_resamples)
    hi = int((1 - alpha / 2) * n_resamples)
    hi = min(hi, n_resamples - 1)
    return ((means[lo], means[hi]), (sharpes[lo], sharpes[hi]))


def _permutation_paired_test(
    safety_values: List[float],
    actual_values: List[float],
    n_resamples: int = 10000,
) -> float:
    """Two-sided paired permutation p-value for mean(safety - actual) > 0."""
    n = len(safety_values)
    if n < 2 or len(actual_values) != n:
        return 1.0
    observed = _mean([s - a for s, a in zip(safety_values, actual_values)])
    if observed <= 0:
        return 1.0
    count = 0
    for _ in range(n_resamples):
        total = 0.0
        for s, a in zip(safety_values, actual_values):
            if random.random() < 0.5:
                total += s - a
            else:
                total += a - s
        perm_mean = total / n
        if abs(perm_mean) >= observed:
            count += 1
    return count / n_resamples


def _losing_run_stats(records: List[Dict[str, Any]]) -> Tuple[int, float]:
    """Max consecutive negative deltas and worst losing-run total (cents)."""
    sorted_records = sorted(
        records,
        key=lambda r: datetime.fromisoformat(r["entry_time"]) if r.get("entry_time") else datetime.min.replace(tzinfo=timezone.utc),
    )
    max_consec = 0
    max_run = 0.0
    cur_consec = 0
    cur_run = 0.0
    for r in sorted_records:
        d = r["pnl_delta_cents"]
        if d < 0:
            cur_consec += 1
            cur_run += d
        else:
            max_consec = max(max_consec, cur_consec)
            max_run = min(max_run, cur_run)
            cur_consec = 0
            cur_run = 0.0
    max_consec = max(max_consec, cur_consec)
    max_run = min(max_run, cur_run)
    return max_consec, max_run


def _top_n_delta_sum(records: List[Dict[str, Any]], n: int, winners: bool = True) -> float:
    deltas = [r["pnl_delta_cents"] for r in records]
    if winners:
        deltas = [d for d in deltas if d > 0]
    else:
        deltas = [d for d in deltas if d < 0]
    deltas.sort(reverse=winners)
    return sum(deltas[:n])


def print_canary_summary(
    records: List[Dict[str, Any]],
    safety_max_dd_cents: float = 0.0,
    actual_max_dd_cents: float = 0.0,
    delta_max_dd_cents: float = 0.0,
    max_consecutive_negative_deltas: int = 0,
    worst_negative_run_cents: float = 0.0,
    cap_stress_rejected: int = 0,
    regime_stress_captured: bool = False,
) -> None:
    if not records:
        print("\n## Exit-Policy Canary Summary\n\nNo records in this window.")
        return

    total = len(records)
    paper_exits = [r for r in records if r["safety_paper_filled"]]
    actual_exits = [r for r in records if r["actual_exit"]]
    no_eval = [r for r in records if r["actual_no_exit_eval"]]
    confirmed = [r for r in records if r["paper_confirmed_by_actual_fill"]]
    near_coincidence = [r for r in records if r["safety_near_coincidence"]]

    safety_net = sum(r["safety_net_pnl_cents"] for r in records)
    actual_net = sum(r["actual_net_pnl_cents"] for r in records)
    delta = safety_net - actual_net
    deltas = [r["pnl_delta_cents"] for r in records]
    wins = [r for r in records if r["pnl_delta_cents"] > 0]

    # Concentration: contribution of the biggest safety winner trades to the delta.
    top5_winners = _top_n_delta_sum(records, 5, winners=True)
    top10_winners = _top_n_delta_sum(records, 10, winners=True)
    top5_conc = top5_winners / delta if delta > 0 else 0.0
    top10_conc = top10_winners / delta if delta > 0 else 0.0

    # Risk-adjusted: per-trade Sharpe of the delta series.
    delta_sharpe = _sharpe(deltas)
    std = _std(deltas)
    n_eff = _effective_sample_size(deltas)
    t_stat_eff = _mean(deltas) / (std / math.sqrt(n_eff)) if std > 0 else 0.0
    (mean_ci_lo, mean_ci_hi), (sharpe_ci_lo, sharpe_ci_hi) = _bootstrap_ci(deltas)
    perm_p = _permutation_paired_test(
        [r["safety_net_pnl_cents"] for r in records],
        [r["actual_net_pnl_cents"] for r in records],
    )
    # Bonferroni correction for ~4 exit-policy variants evaluated in the replay.
    perm_p_bonferroni = min(1.0, perm_p * 4)
    passes_gate = mean_ci_lo > 0 and sharpe_ci_lo > 0 and perm_p_bonferroni < 0.05

    print("\n## Exit-Policy Canary Summary\n")
    print(f"Round trips tracked:        {total}")
    print(f"Safety paper exits:         {len(paper_exits)}")
    print(f"Production actual exits:    {len(actual_exits)}")
    print(f"  of which no EXIT_EVAL:    {len(no_eval)}")
    print(f"Paper fills confirmed:      {len(confirmed)} / {len(paper_exits)}")
    print(f"Near-coincidence cross-checks: {len(near_coincidence)} / {len(paper_exits)}")
    print(f"Safety net PnL:             {_fmt_cents(safety_net)}")
    print(f"Actual net PnL:             {_fmt_cents(actual_net)}")
    print(f"Delta (safety - actual):    {_fmt_cents(delta)}")
    print(f"Per-trade delta:  median={_fmt_cents(_percentile(deltas, 50))}  "
          f"p10={_fmt_cents(_percentile(deltas, 10))}  "
          f"p90={_fmt_cents(_percentile(deltas, 90))}")
    print(f"Safety wins per-trade:      {len(wins)} / {total} ({100*len(wins)/total:.1f}%)")
    print(f"Delta per-trade Sharpe:     {delta_sharpe:.3f}")
    print(f"Top 5 winner concentration: {top5_conc*100:.1f}% of delta ({_fmt_cents(top5_winners)})")
    print(f"Top 10 winner concentration:{top10_conc*100:.1f}% of delta ({_fmt_cents(top10_winners)})")
    print()
    print(f"Safety max DD:              {_fmt_cents(safety_max_dd_cents)}")
    print(f"Actual max DD:              {_fmt_cents(actual_max_dd_cents)}")
    print(f"Delta max DD:               {_fmt_cents(delta_max_dd_cents)}")
    print(f"Safety PnL / DD:            {_safe_ratio(safety_net, safety_max_dd_cents):.2f}")
    print(f"Actual PnL / DD:            {_safe_ratio(actual_net, actual_max_dd_cents):.2f}")
    print(f"Delta PnL / DD:             {_safe_ratio(delta, delta_max_dd_cents):.2f}")
    print()
    print("Statistical gate:")
    print(f"  Effective sample size:    {n_eff:.1f} (raw {total})")
    print(f"  Effective t-stat:         {t_stat_eff:.2f}")
    print(f"  Mean delta 95% CI:        [{_fmt_cents(mean_ci_lo)}, {_fmt_cents(mean_ci_hi)}]")
    print(f"  Sharpe 95% CI:            [{sharpe_ci_lo:.3f}, {sharpe_ci_hi:.3f}]")
    print(f"  Permutation p (raw):      {perm_p:.4f}")
    print(f"  Permutation p (Bonferroni, k=4): {perm_p_bonferroni:.4f}")
    print(f"  Gate passed:              {passes_gate}")
    print(f"  Regime stress captured:   {regime_stress_captured}  "
          f"(cap_rejected={cap_stress_rejected}, worst_neg_run={_fmt_cents(worst_negative_run_cents)})")
    print()

    if no_eval:
        print("no_exit_eval suspected cause breakdown:")
        cause_counts: Dict[str, int] = {}
        for r in no_eval:
            c = r.get("actual_no_exit_eval_suspected_cause") or "unknown"
            cause_counts[c] = cause_counts.get(c, 0) + 1
        for cause, cnt in sorted(cause_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {cause:<30} {cnt:>4}")
        print()


def run_canary(args: argparse.Namespace) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)

    # Load data sources.
    settlements = _replay.load_settlements(args.settlement_outcomes)
    fills = _replay.load_fills(args.fills_db)
    fills = [f for f in fills if f.created_time >= cutoff]

    exit_evals = _replay.parse_exit_eval_log(args.full_log, since=cutoff)

    if not fills:
        print("[WARN] no fills in lookback; nothing to canary")
        return 0

    # Reconstruct round trips and run the two policy paths.
    round_trips = _replay.reconstruct_round_trips(fills)
    _replay._assign_expected_close_times(round_trips, settlements)

    cap = args.correlation_cap if args.correlation_cap > 0 else None
    safety = _replay.run_strategy(
        "safety_rails", round_trips, exit_evals, settlements,
        SAFETY_EXIT_REASONS, args.fee_model, cap,
    )
    actual_active = _replay.compute_actual_active_result(
        "actual_active", round_trips, settlements, cap,
    )

    # Match actual fills to their nearest EXIT_EVAL trigger so we can tag
    # no_exit_eval fills and confirm paper fills.
    matches, _ = _replay.actual_fill_slippage(actual_active.round_trips, safety.round_trips, exit_evals)
    match_by_key = {_match_key(m): m for m in matches}

    # Build records for the round trips that were accepted under the cap.
    actual_by_key = {_rt_key(rt): rt for rt in actual_active.round_trips}
    safety_by_key = {_rt_key(rt): rt for rt in safety.round_trips}

    records: List[Dict[str, Any]] = []
    for rt in round_trips:
        key = _rt_key(rt)
        actual = actual_by_key.get(key)
        if actual is None:
            # Rejected by the correlated-exposure cap.
            continue
        safety_rt = safety_by_key.get(key)
        if safety_rt is None:
            continue
        match_key = _actual_exit_key(actual)
        match = match_by_key.get(match_key) if match_key is not None else None
        records.append(build_canary_record(actual, safety_rt, match, settlements))

    # Watermark and append-only jsonl.
    watermark_path = args.output_jsonl.with_suffix(".watermark.json")
    last_wm = _parse_watermark(watermark_path) or cutoff
    new_records = [r for r in records if datetime.fromisoformat(r["entry_time"]) > last_wm]

    if new_records:
        args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.output_jsonl.open("a", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, default=str) + "\n")

    if records:
        max_entry = max(datetime.fromisoformat(r["entry_time"]) for r in records)
        _write_watermark(watermark_path, max_entry)

    # Rolling summary.
    deltas = [r["pnl_delta_cents"] for r in records]
    no_eval_causes: Dict[str, int] = {}
    for r in records:
        if r["actual_no_exit_eval"]:
            c = r.get("actual_no_exit_eval_suspected_cause") or "unknown"
            no_eval_causes[c] = no_eval_causes.get(c, 0) + 1

    # Net numbers and drawdowns for risk-adjusted metrics.
    safety_net = sum(r["safety_net_pnl_cents"] for r in records)
    actual_net = sum(r["actual_net_pnl_cents"] for r in records)
    delta = safety_net - actual_net

    safety.max_drawdown_cents = _replay.compute_drawdown(safety.round_trips)
    actual_active.max_drawdown_cents = _replay.compute_drawdown(actual_active.round_trips)
    delta_dd = _compute_delta_drawdown(records)

    # Regime / stress diagnostics.
    max_consec_neg, worst_neg_run = _losing_run_stats(records)
    cap_stress = _replay.run_cap_stress(round_trips, exit_evals, settlements, cap or args.correlation_cap, args.fee_model)
    cap_stress_rejected = cap_stress.get("rejected_positions", 0)
    cap_stress_peak = cap_stress.get("peak_open_notional_cap_usd", 0.0)
    cap_stress_wc_dd = cap_stress.get("worst_case_drawdown_cap_usd", 0.0)
    # Regime stress is a real observed losing run in the live data.  Cap stress is
    # reported separately as a 15m hold-to-expiry "what-if".
    # A "real" drawdown window is at least 3 consecutive losing deltas totaling
    # $3 or more (300 cents) in the live data.
    regime_stress_captured = bool(max_consec_neg >= 3 and abs(worst_neg_run) >= 300)

    top5_winners = _top_n_delta_sum(records, 5, winners=True)
    top10_winners = _top_n_delta_sum(records, 10, winners=True)

    # Statistical gate.
    (mean_ci_lo, mean_ci_hi), (sharpe_ci_lo, sharpe_ci_hi) = _bootstrap_ci(deltas)
    perm_p = _permutation_paired_test(
        [r["safety_net_pnl_cents"] for r in records],
        [r["actual_net_pnl_cents"] for r in records],
    )
    perm_p_bonferroni = min(1.0, perm_p * 4)
    n_eff = _effective_sample_size(deltas)
    std = _std(deltas)
    t_stat_eff = _mean(deltas) / (std / math.sqrt(n_eff)) if std > 0 else 0.0
    passes_gate = mean_ci_lo > 0 and sharpe_ci_lo > 0 and perm_p_bonferroni < 0.05

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": args.lookback_hours,
        "fee_model": args.fee_model,
        "correlation_cap_usd": cap,
        "total_tracked": len(records),
        "new_records_this_run": len(new_records),
        "safety_net_pnl_cents": sum(r["safety_net_pnl_cents"] for r in records),
        "actual_net_pnl_cents": sum(r["actual_net_pnl_cents"] for r in records),
        "safety_paper_exits": sum(1 for r in records if r["safety_paper_filled"]),
        "actual_exits": sum(1 for r in records if r["actual_exit"]),
        "no_exit_eval_count": sum(1 for r in records if r["actual_no_exit_eval"]),
        "no_exit_eval_suspected_causes": no_eval_causes,
        "paper_fills_confirmed": sum(1 for r in records if r["paper_confirmed_by_actual_fill"]),
        "safety_near_coincidence_count": sum(1 for r in records if r["safety_near_coincidence"]),
        "delta_median_cents": _percentile(deltas, 50),
        "delta_p10_cents": _percentile(deltas, 10),
        "delta_p90_cents": _percentile(deltas, 90),
        "safety_beat_actual_count": sum(1 for r in records if r["pnl_delta_cents"] > 0),
        "safety_beat_actual_fraction": sum(1 for r in records if r["pnl_delta_cents"] > 0) / len(records) if records else 0.0,
        "safety_max_drawdown_cents": safety.max_drawdown_cents,
        "actual_max_drawdown_cents": actual_active.max_drawdown_cents,
        "delta_max_drawdown_cents": delta_dd,
        "safety_pnl_per_drawdown": _safe_ratio(safety_net, safety.max_drawdown_cents),
        "actual_pnl_per_drawdown": _safe_ratio(actual_net, actual_active.max_drawdown_cents),
        "delta_pnl_per_drawdown": _safe_ratio(delta, delta_dd),
        "delta_sharpe": _sharpe(deltas),
        "delta_std_cents": _std(deltas),
        "top5_winner_delta_cents": top5_winners,
        "top10_winner_delta_cents": top10_winners,
        "top5_winner_concentration": _safe_ratio(top5_winners, delta),
        "top10_winner_concentration": _safe_ratio(top10_winners, delta),
        "effective_sample_size": n_eff,
        "effective_t_stat": t_stat_eff,
        "delta_mean_ci95_low_cents": mean_ci_lo,
        "delta_mean_ci95_high_cents": mean_ci_hi,
        "delta_sharpe_ci95_low": sharpe_ci_lo,
        "delta_sharpe_ci95_high": sharpe_ci_hi,
        "permutation_p_value_raw": perm_p,
        "permutation_p_value_bonferroni_k4": perm_p_bonferroni,
        "statistical_gate_passed": passes_gate,
        "regime_stress_captured": regime_stress_captured,
        "max_consecutive_negative_deltas": max_consec_neg,
        "worst_negative_run_cents": worst_neg_run,
        "cap_stress_rejected_15m": cap_stress_rejected,
        "cap_stress_peak_notional_usd": cap_stress_peak,
        "cap_stress_worst_case_drawdown_usd": cap_stress_wc_dd,
    }
    with args.output_summary.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print_canary_summary(
        records,
        safety_max_dd_cents=safety.max_drawdown_cents,
        actual_max_dd_cents=actual_active.max_drawdown_cents,
        delta_max_dd_cents=delta_dd,
        max_consecutive_negative_deltas=max_consec_neg,
        worst_negative_run_cents=worst_neg_run,
        cap_stress_rejected=cap_stress_rejected,
        regime_stress_captured=regime_stress_captured,
    )
    print(f"[INFO] wrote {len(new_records)} new records to {args.output_jsonl}")
    print(f"[INFO] wrote summary to {args.output_summary}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fills-db", type=Path, default=Path("data/kalshi_fills.db"))
    parser.add_argument("--full-log", type=Path, default=Path("logs"))
    parser.add_argument("--settlement-outcomes", type=Path, default=Path("logs/settlement_outcomes.jsonl"))
    parser.add_argument("--fee-model", choices=("live", "conservative"), default="live")
    parser.add_argument("--correlation-cap", type=float, default=2.0)
    parser.add_argument("--lookback-hours", type=float, default=6.0,
                        help="Trailing window to load for each canary pass.")
    parser.add_argument("--output-jsonl", type=Path, default=Path("reports/exit_policy_canary.jsonl"))
    parser.add_argument("--output-summary", type=Path, default=Path("reports/exit_policy_canary_summary.json"))
    parser.add_argument("--watch", type=float, default=0.0,
                        help="If >0, re-run every N seconds (continuous canary).")
    args = parser.parse_args(argv)

    if args.watch > 0:
        print(f"[INFO] canary running in watch mode, polling every {args.watch}s")
        while True:
            try:
                run_canary(args)
            except Exception as exc:
                print(f"[ERROR] canary pass failed: {exc}")
            time.sleep(args.watch)
    else:
        return run_canary(args)


if __name__ == "__main__":
    sys.exit(main())
