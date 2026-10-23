"""Report assembly for the independent forecast-audit scorer.

Produces one reproducible JSON report across BTC/ETH/SOL/XRP/DOGE answering:

    Does the pre-anchor signal add future information beyond a calibrated
    market baseline, and how much of that benefit survives the production
    probability pipeline?

Comparisons (all in canonical YES space; positive loss-diff favors the
candidate). The fitted comparators (q0/q1) are the incremental-information
test: they ask whether the pre-anchor deviation improves a market baseline
that has already been allowed to correct its own calibration.

Verdicts are issued per comparison — a failed or inconclusive deployed
comparison never overwrites a valid raw-signal finding, and vice versa.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .bootstrap import CompBlocks, block_ids_for_units, make_comp_blocks
from .inference import (
    LOSSES,
    build_fold_plan,
    compute_base_rates,
    compute_fitted_forecasts,
    is_extreme_prob,
    stage_probability,
)
from .bootstrap import paired_bootstrap
from .inference import (
    LABEL_POLICY_GRACE,
    LABEL_POLICY_OBSERVED,
)
from .records import (
    AnchoredStageLog,
    DecisionRow,
    OfficialOutcomes,
    ProbeRun,
    TickerProbe,
    asset_from_ticker,
    count_decision_rows,
    load_anchored_stage,
    load_fill_economics,
    load_official_outcomes,
    probe_horizon_population,
)
from .units import (
    EvalUnit,
    JOIN_ASOF_BOUNDED,
    JOIN_REJECT_FUTURE,
    Population,
    build_population_from_probes,
)

REPORT_SCHEMA_VERSION = 2

# (name, candidate_stage, baseline_stage, audit_question)
COMPARISONS: List[Tuple[str, str, str, str]] = [
    ("q1_vs_q0", "q1", "q0", "pre-anchor incremental information"),
    ("final_vs_mid", "final", "mid", "deployed forecast vs contemporaneous market"),
    ("raw_vs_mid", "raw", "mid", "pre-anchor signal vs market"),
    ("anchwf_vs_raw", "anch_wf", "raw", "anchor+walk-forward benefit"),
    ("final_vs_anchwf", "final", "anch_wf", "post-anchor pipeline effect (EPC/tail/bounds)"),
    ("final_vs_q0", "final", "q0", "deployed vs calibrated market"),
    ("mid_vs_baserate", "mid", "base_rate", "sanity: market vs base rate"),
    ("final_vs_const_half", "final", "const_half", "sanity: deployed vs 0.5"),
]

VERDICT_PASS = "PASS"                    # lower CI bound > 0: candidate improves
VERDICT_FAIL = "FAIL"                    # upper CI bound < 0: candidate harms
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"    # CI spans 0
VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA"
VERDICT_INVALID = "INVALID"


@dataclass
class AuditConfig:
    db_path: str = "data/decision_audit.db"
    model_cal_path: str = "logs/model_calibration_observations.jsonl"
    outcomes_path: str = "logs/settlement_outcomes.jsonl"
    horizons_s: Tuple[float, ...] = (600.0, 300.0, 120.0, 60.0)
    max_age_s: float = 90.0
    n_folds: int = 4
    min_train_n: int = 200
    replicates: int = 2000
    block_lens_s: Tuple[float, ...] = (1800.0, 3600.0, 7200.0, 14400.0)
    primary_block_len_s: float = 3600.0
    seed: int = 20261023
    assets: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")
    min_support: int = 50
    primary_metric: str = "brier"
    since_ts: Optional[float] = None
    until_ts: Optional[float] = None
    # Opt-in scans: the audit DB is multi-GB; row counts and the fill-econ
    # join each cost a full table scan. Off by default so the audit is
    # cheap/safe on the live host.
    include_row_counts: bool = False
    include_econ: bool = False
    # P0 attribution hardening.
    # Historical-training label policy: only labels with documented
    # observed_at_utc availability may train fitted comparators; "grace"
    # (settlement_ts + 300s) is a named sensitivity, never a silent fallback.
    label_policy: str = LABEL_POLICY_OBSERVED
    grace_s: float = 300.0
    # Anchored-stage join bounds (see units.join_anchored for semantics).
    # past_tol bounds how far before decision_ts a record may sit;
    # future_slack covers the same-evaluation emission lag (rec.ts is
    # stamped mid-evaluation, decision_ts at evaluation entry — a small
    # positive bound is a documented timestamp semantic, not support
    # recovery).
    anch_past_tolerance_s: float = 30.0
    anch_future_slack_s: float = 5.0
    export_joins_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def _support_for(
    units: List[EvalUnit],
    cand: str,
    base: str,
    fitted: Dict[int, Any],
    base_rates: Dict[int, float],
    idxs: Sequence[int],
) -> Tuple[List[int], np.ndarray, np.ndarray, np.ndarray]:
    """Common support for one comparison: unit indices where the outcome and
    both probabilities exist; plus the per-unit probability vectors."""
    idx: List[int] = []
    pc: List[float] = []
    pb: List[float] = []
    for i in idxs:
        u = units[i]
        if u.y is None:
            continue
        pc_i = stage_probability(u, cand, fitted.get(i), base_rates.get(i))
        pb_i = stage_probability(u, base, fitted.get(i), base_rates.get(i))
        if pc_i is None or pb_i is None:
            continue
        idx.append(i)
        pc.append(pc_i)
        pb.append(pb_i)
    return idx, np.asarray(pc), np.asarray(pb), np.asarray(
        [units[i].y for i in idx], dtype=float
    )


def _result_to_dict(br: Any) -> Dict[str, Any]:
    """BootstrapResult -> report row (single statistic implementation)."""
    return {
        "n_units": br.n_units,
        "n_blocks": br.n_blocks_used,
        "bs_candidate": br.point_bs_cand,
        "bs_baseline": br.point_bs_base,
        "mean_loss_diff": br.point_mean_d,
        "mean_loss_diff_ci": list(br.ci_d) if br.ci_d else None,
        "bss": br.point_bss,
        "bss_ci": list(br.ci_bss) if br.ci_bss else None,
        "n_requested_draws": br.n_requested_draws,
        "n_valid_loss_draws": br.n_valid_loss_draws,
        "n_empty_support_draws": br.n_empty_support_draws,
        "n_valid_skill_draws": br.n_valid_skill_draws,
        "n_zero_baseline_loss_draws": br.n_zero_baseline_loss_draws,
    }


def _verdict(res: Dict[str, Any], min_support: int) -> str:
    if res["n_units"] < min_support:
        return VERDICT_INSUFFICIENT
    ci = res.get("mean_loss_diff_ci")
    if ci is None:
        return VERDICT_INSUFFICIENT
    if ci[0] > 0:
        return VERDICT_PASS
    if ci[1] < 0:
        return VERDICT_FAIL
    return VERDICT_INCONCLUSIVE


def _integrity_for(
    cand: str,
    base: str,
    units: List[EvalUnit],
    idx: Sequence[int],
    cfg: "AuditConfig",
    assumed_train_labels: int = 0,
) -> Dict[str, Any]:
    """Per-comparison data-integrity status, scoped to what is actually
    scored on this comparison's support.

    Rules: bounded as-of anchored joins -> PROVISIONAL; ambiguous or
    cross-decision-reused joins -> PROVISIONAL reasons; a rejected-future
    intermediate that somehow entered the score -> INVALID; fitted/base-rate
    comparators that ACTUALLY consumed assumed-availability labels ->
    PROVISIONAL (enabling the grace policy without exercising it does not
    downgrade). Unaffected comparisons keep their own status — a bad
    anch_wf join never touches final_vs_mid.

    ``evidence_eligible`` means the result is trustworthy enough to inform
    a release decision — it never authorizes release.
    """
    status = "VALID"
    reasons: List[str] = []
    deps = {cand, base}
    if "anch_wf" in deps:
        sup = [units[i] for i in idx]
        if any(u.anch_join_class == JOIN_REJECT_FUTURE and u.p_anch_wf is not None
               for u in sup):
            status = "INVALID"
            reasons.append("future_intermediate_scored")
        if any(u.anch_join_class == JOIN_ASOF_BOUNDED for u in sup):
            if status != "INVALID":
                status = "PROVISIONAL"
            reasons.append("anch_join_asof_bounded")
        if any(u.anch_ambiguous for u in sup):
            if status != "INVALID":
                status = "PROVISIONAL"
            reasons.append("anch_join_ambiguous")
        if any(u.anch_reused for u in sup):
            if status != "INVALID":
                status = "PROVISIONAL"
            reasons.append("anch_join_reused_across_decisions")
    if deps & {"q0", "q1", "base_rate"}:
        if cfg.label_policy == LABEL_POLICY_GRACE and assumed_train_labels > 0:
            if status != "INVALID":
                status = "PROVISIONAL"
            reasons.append("assumed_training_labels_used")
    return {
        "integrity_status": status,
        "integrity_reasons": reasons,
        "evidence_eligible": status == "VALID",
        "deployment_gate_passed": False,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _git_sha() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def _file_meta(path: str) -> Dict[str, Any]:
    p = Path(path)
    try:
        st = p.stat()
        return {"path": str(p), "exists": True, "size_bytes": st.st_size,
                "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}
    except OSError:
        return {"path": str(p), "exists": False}


def _stage_coverage(units: List[EvalUnit]) -> Dict[str, int]:
    n = len(units)
    return {
        "units": n,
        "p_raw": sum(1 for u in units if u.p_raw is not None),
        "p_final": sum(1 for u in units if u.p_final is not None),
        "m_mid": sum(1 for u in units if u.m_mid is not None),
        "p_anch_wf": sum(1 for u in units if u.p_anch_wf is not None),
        "y": sum(1 for u in units if u.y is not None),
    }


def _integrity_checks(
    units: List[EvalUnit],
    probes: List[TickerProbe],
    official: OfficialOutcomes,
    anchored: AnchoredStageLog,
    fitted: Dict[int, Any],
    cfg: AuditConfig,
) -> Dict[str, Any]:
    # Label agreement: audit-DB outcome vs official export (same-ticker join).
    ledger_labels: Dict[str, int] = {}
    for p in probes:
        if p.ledger_outcome is not None and p.ledger_outcome[0] is not None:
            ledger_labels[p.ticker] = int(p.ledger_outcome[0])
    disagree = [
        t for t, y in ledger_labels.items()
        if t.upper() in official.by_ticker and official.by_ticker[t.upper()].resolved_yes != y
    ]
    # Close_ts cross-check: ledger last-row close vs official settlement_ts.
    close_diffs: List[float] = []
    for p in probes:
        o = official.by_ticker.get(p.ticker.upper())
        if o is not None and o.settlement_ts is not None and p.close_ts_last is not None:
            close_diffs.append(abs(p.close_ts_last - o.settlement_ts))
    # Probabilities must be in [0,1]; count violations + clipped extremes.
    violations = {"p_raw": 0, "p_final": 0, "m_mid": 0, "p_anch_wf": 0}
    extremes = {"p_raw": 0, "p_final": 0, "m_mid": 0, "p_anch_wf": 0}
    for u in units:
        for k, v in (("p_raw", u.p_raw), ("p_final", u.p_final),
                     ("m_mid", u.m_mid), ("p_anch_wf", u.p_anch_wf)):
            if v is None:
                continue
            if not (0.0 <= v <= 1.0):
                violations[k] += 1
            elif is_extreme_prob(v):
                extremes[k] += 1
    return {
        "ledger_vs_official_label_disagreements": {
            "count": len(disagree), "tickers": disagree[:20]},
        "official_corrections_applied": official.corrections,
        "official_malformed_rows": official.malformed,
        "anchored_log_complement_mismatches": anchored.complement_mismatches,
        "prob_range_violations": violations,
        "extreme_prob_counts_clip_eps_1e-6": extremes,
        "ledger_vs_official_close_ts": {
            "n_matched": len(close_diffs),
            "median_abs_diff_s": (
                float(np.median(close_diffs)) if close_diffs else None),
            "max_abs_diff_s": (
                float(max(close_diffs)) if close_diffs else None),
        },
        "fitted_nonconverged_q0": sum(
            1 for f in fitted.values() if f.q0_converged is False),
        "fitted_nonconverged_q1": sum(
            1 for f in fitted.values() if f.q1_converged is False),
    }


def build_report(cfg: AuditConfig, progress: bool = False) -> Dict[str, Any]:
    """Run the full audit and return the JSON-safe report dict."""
    import sys
    import time

    def _log(msg: str, t0: float) -> float:
        if progress:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)
        return time.time()

    t = _log("probing per-ticker horizon snapshots (index seeks only)", time.time())
    probe_run = probe_horizon_population(
        cfg.db_path,
        horizons_s=cfg.horizons_s,
        assets=list(cfg.assets),
        since_close_ts=cfg.since_ts,
        until_close_ts=cfg.until_ts,
        progress_cb=(
            (lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}",
                             file=sys.stderr, flush=True))
            if progress else None),
    )
    probes = probe_run.probes
    t = _log(
        f"probed {len(probes)} tickers "
        f"(universe={probe_run.universe_query}, "
        f"discovered={probe_run.tickers_discovered})", t)
    for w in probe_run.warnings:
        _log(f"WARNING: {w}", t)
    pop_counts = (
        count_decision_rows(cfg.db_path, assets=list(cfg.assets))
        if cfg.include_row_counts else {"skipped": True}
    )
    anchored = load_anchored_stage(cfg.model_cal_path)
    official = load_official_outcomes(cfg.outcomes_path)
    t = _log(
        f"loaded {sum(len(v) for v in anchored.by_key.values())} anchored-stage records, "
        f"{len(official.by_ticker)} official outcomes", t)

    # Ticker universe = ledger tickers + target-series official outcomes
    # whose settlement falls inside the ledger's decision window (outcomes
    # file spans a much longer history; out-of-window tickers are not
    # expected coverage). Asset is resolved from the ticker stem — the
    # single resolver shared with the probe filter — never from a missing
    # outcome `asset` field. The +3600s pad is a discovery allowance only;
    # contract inclusion still requires a valid target-series ticker.
    asset_set = set(cfg.assets)
    if probes:
        lo_ts = min(p.first_decision_ts for p in probes if p.first_decision_ts)
        hi_ts = max(p.last_decision_ts for p in probes if p.last_decision_ts) + 3600.0
    else:
        lo_ts = hi_ts = 0.0
    expected = [
        t for t, o in official.by_ticker.items()
        if asset_from_ticker(t) in asset_set
        and o.settlement_ts is not None
        and lo_ts <= o.settlement_ts <= hi_ts
    ]
    population = build_population_from_probes(
        probes,
        horizons_s=list(cfg.horizons_s),
        max_age_s=cfg.max_age_s,
        anchored=anchored,
        official=official,
        expected_tickers=expected,
        anch_past_tolerance_s=cfg.anch_past_tolerance_s,
        anch_future_slack_s=cfg.anch_future_slack_s,
    )
    scored_units = population.units
    t = _log(f"population built: {len(scored_units)} units / {len(population.entries)} entries", t)

    fitted_plan = build_fold_plan(
        scored_units, n_folds=cfg.n_folds, min_train_n=cfg.min_train_n,
        label_policy=cfg.label_policy)
    fitted, fold_stats = compute_fitted_forecasts(
        scored_units, fitted_plan, n_folds=cfg.n_folds,
        min_train_n=cfg.min_train_n, label_policy=cfg.label_policy)
    base_rates = compute_base_rates(
        scored_units, official, label_policy=cfg.label_policy)
    assumed_train_labels = sum(
        s.get("train_labels_assumed", 0)
        for h in fold_stats.values() for s in h.values())
    t = _log("fitted forecasts + base rates done", t)

    all_idx = list(range(len(scored_units)))
    close_ts_arr = [u.close_ts for u in scored_units]

    # ---- support cache (block-length independent) --------------------------
    # Each comparison's support is its own paired availability mask — losses
    # per support don't depend on block assignment, so compute once and
    # reuse across every block length.
    slices: Dict[str, Sequence[int]] = {"pooled": all_idx}
    horizons = sorted({u.horizon_s for u in scored_units})
    for h in horizons:
        slices[f"horizon_{int(h)}s"] = [i for i in all_idx if scored_units[i].horizon_s == h]
    for a in sorted({u.asset for u in scored_units if u.asset}):
        slices[f"asset_{a}"] = [i for i in all_idx if scored_units[i].asset == a]

    comp_meta: Dict[str, Tuple[str, str, str]] = {
        c[0]: (c[1], c[2], c[3]) for c in COMPARISONS}
    support_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for sname, idxs in slices.items():
        for comp_name, cand, base, question in COMPARISONS:
            idx, pc, pb, y = _support_for(
                scored_units, cand, base, fitted, base_rates, idxs)
            losses: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
            for loss_name, loss_fn in LOSSES.items():
                lc = np.array([loss_fn(a, int(b)) for a, b in zip(pc, y)])
                lb = np.array([loss_fn(a, int(b)) for a, b in zip(pb, y)])
                losses[loss_name] = (lc, lb)
            support_cache[(sname, comp_name)] = {
                "idx": idx, "pc": pc, "pb": pb, "losses": losses,
            }

    # ---- bootstrap: one statistic implementation, shared draws per length --
    results: Dict[str, Any] = {}
    for bl in cfg.block_lens_s:
        t = _log(f"bootstrap block_len={int(bl)}s", t)
        block_of_unit, n_blocks = block_ids_for_units(close_ts_arr, bl)
        comps: Dict[str, Any] = {}
        for (sname, comp_name), sc in support_cache.items():
            for loss_name, (lc, lb) in sc["losses"].items():
                comps[f"{sname}|{comp_name}|{loss_name}"] = make_comp_blocks(
                    block_of_unit, sc["idx"], lb - lc, lc, lb, n_blocks)
        bres = paired_bootstrap(comps, replicates=cfg.replicates, seed=cfg.seed)
        len_res: Dict[str, Any] = {}
        for sname in slices:
            len_res[sname] = {}
            for comp_name in comp_meta:
                sc = support_cache[(sname, comp_name)]
                cand, base, question = comp_meta[comp_name]
                out: Dict[str, Any] = {
                    "question": question,
                    "candidate": cand, "baseline": base,
                    "n_support": len(sc["idx"]),
                    "extreme_probs_cand": int(sum(
                        is_extreme_prob(p) for p in sc["pc"])),
                    "extreme_probs_base": int(sum(
                        is_extreme_prob(p) for p in sc["pb"])),
                }
                for loss_name in LOSSES:
                    br = bres.get(f"{sname}|{comp_name}|{loss_name}")
                    out[loss_name] = (
                        _result_to_dict(br) if br is not None
                        else {"n_units": 0})
                out["statistical_verdict"] = _verdict(
                    out[cfg.primary_metric], cfg.min_support) \
                    if out[cfg.primary_metric].get("n_units") \
                    else VERDICT_INSUFFICIENT
                out.update(_integrity_for(
                    cand, base, scored_units, sc["idx"], cfg,
                    assumed_train_labels=assumed_train_labels))
                len_res[sname][comp_name] = out
        results[f"block_len_{int(bl)}s"] = len_res

    primary = results[f"block_len_{int(cfg.primary_block_len_s)}s"]

    # ---- q1 coefficient diagnostic (encompassing residual) ------------------
    gamma_diag: Dict[str, Any] = {}
    for h in horizons:
        gs = [fitted[i] for i in all_idx
              if scored_units[i].horizon_s == h and fitted.get(i) and fitted[i].gamma is not None]
        if gs:
            gamma_diag[f"horizon_{int(h)}s"] = {
                "n_fits": len(gs),
                "gamma_mean": float(np.mean([g.gamma for g in gs])),
                "gamma_se_mean": float(np.mean([g.gamma_se for g in gs if g.gamma_se is not None]))
                if any(g.gamma_se is not None for g in gs) else None,
                "train_n_mean": float(np.mean([g.train_n_q1 for g in gs])),
            }

    # ---- economics (descriptive only, opt-in full scan) --------------------
    if cfg.include_econ:
        t = _log("economics join (full outcomes scan - opt-in)", t)
        econ_rows = load_fill_economics(
            cfg.db_path, assets=list(cfg.assets))
        econ_status = "ran"
    else:
        econ_rows = []
        econ_status = "not_run"
    econ: Dict[str, Any] = {
        "status": econ_status,
        "note": ("Descriptive fill economics on ENTER decisions with realized "
                 "PnL in the audit DB. Not a forecast verdict; costs are "
                 "actual ledger values, not estimates."
                 + ("" if cfg.include_econ else
                    " NOT RUN: pass --econ to enable (full outcomes-table scan).")),
        "filled_decisions": len(econ_rows) if cfg.include_econ else None,
    }
    if econ_rows:
        pnls = [float(r[1]) for r in econ_rows]
        econ["mean_realized_net_pnl_cents"] = float(np.mean(pnls))
        econ["total_realized_net_pnl_cents"] = float(np.sum(pnls))
        per_asset: Dict[str, List[float]] = {}
        for r in econ_rows:
            per_asset.setdefault(r[0], []).append(float(r[1]))
        econ["by_asset"] = {
            a: {"n": len(v), "mean_cents": float(np.mean(v)), "total_cents": float(np.sum(v))}
            for a, v in sorted(per_asset.items())
        }

    # ---- population accounting ----------------------------------------------
    pop_entries = population.entries
    status_counts: Dict[str, int] = {}
    for e in pop_entries:
        key = e.status if e.reason is None else e.reason
        status_counts[key] = status_counts.get(key, 0) + 1
    per_horizon_pop: Dict[str, Dict[str, int]] = {}
    for e in pop_entries:
        k = f"horizon_{int(e.horizon_s)}s"
        per_horizon_pop.setdefault(k, {})
        kk = e.status if e.reason is None else e.reason
        per_horizon_pop[k][kk] = per_horizon_pop[k].get(kk, 0) + 1

    # ---- coverage waterfall -------------------------------------------------
    tickers_with_units = {u.ticker for u in scored_units}
    by_asset_cov: Dict[str, Dict[str, int]] = {}
    for u in scored_units:
        a = u.asset or "UNKNOWN"
        by_asset_cov.setdefault(a, {"units": 0, "tickers": 0})
        by_asset_cov[a]["units"] += 1
    for u in scored_units:
        a = u.asset or "UNKNOWN"
    ticker_by_asset: Dict[str, set] = {}
    for u in scored_units:
        ticker_by_asset.setdefault(u.asset or "UNKNOWN", set()).add(u.ticker)
    for a, tk in ticker_by_asset.items():
        by_asset_cov[a]["tickers"] = len(tk)
    coverage_waterfall = {
        "tickers_discovered": probe_run.tickers_discovered,
        "tickers_after_target_series_filter": probe_run.tickers_after_asset_filter,
        "tickers_excluded_close_window": probe_run.tickers_excluded_close_window,
        "tickers_probed": len(probes),
        "tickers_in_scope_with_expected": len({e.ticker for e in pop_entries}),
        "tickers_quarantined": len(population.quarantined_tickers),
        "tickers_with_scored_units": len(tickers_with_units),
        "units_scored": len(scored_units),
        "entry_status_counts": status_counts,
        "units_by_asset": by_asset_cov,
    }

    # ---- horizon fidelity: actual TTE / snapshot-age distributions ---------
    def _dist(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"n": 0}
        v = np.asarray(sorted(vals))
        return {
            "n": int(v.size),
            "p50": float(np.percentile(v, 50)),
            "p90": float(np.percentile(v, 90)),
            "p99": float(np.percentile(v, 99)),
            "max": float(v.max()),
        }

    horizon_fidelity: Dict[str, Any] = {}
    for h in horizons:
        uh = [u for u in scored_units if u.horizon_s == h]
        ages = [u.snapshot_offset_s for u in uh if u.snapshot_offset_s is not None]
        ttes = [
            (u.close_ts - u.snapshot_ts) for u in uh
            if u.close_ts is not None and u.snapshot_ts is not None]
        errs = [
            (u.close_ts - u.snapshot_ts) - h for u in uh
            if u.close_ts is not None and u.snapshot_ts is not None]
        horizon_fidelity[f"horizon_{int(h)}s"] = {
            "units": len(uh),
            "nominal_horizon_s": h,
            "snapshot_age_s": _dist(ages),
            "actual_tte_s": _dist(ttes),
            "tte_error_s": _dist(errs),
        }

    # ---- boundary-drift classification --------------------------------------
    b_counts: Dict[str, int] = {}
    b_examples: Dict[str, List[str]] = {}
    for tk, cls in population.boundary_classes.items():
        b_counts[cls] = b_counts.get(cls, 0) + 1
        b_examples.setdefault(cls, []).append(tk)
    boundary_block = {
        "semantics": (
            "Ledger close_ts is reconstructed per decision row "
            "(decision_ts + seconds_to_expiry). Official settlement_timestamp_utc "
            "is Kalshi settlement publication time, never the contract close — "
            "a material negative delta contradicts the boundary and quarantines."
        ),
        "class_counts": b_counts,
        "quarantined_tickers": population.quarantined_tickers,
        "examples": {
            k: {
                "tickers": v[:10],
                "evidence": [population.boundary_evidence.get(t) for t in v[:10]],
            } for k, v in b_examples.items()
        },
    }

    # ---- anchored join evidence + optional export ---------------------------
    anch_join = {
        "join_class_counts": population.anch_join_counts,
        "reused_across_decisions_records": population.anch_reused_records,
        "ambiguous_joins": sum(1 for u in scored_units if u.anch_ambiguous),
        "offset_s_distribution": _dist([
            u.anch_wf_offset_s for u in scored_units
            if u.anch_wf_offset_s is not None]),
        "semantics": (
            "anch_wf records carry no inference-event id; every accepted join "
            "is a bounded as-of match (offset = rec.ts - decision_ts in "
            "[-past_tol, +future_slack]). Affected comparisons are PROVISIONAL."
        ),
    }
    if cfg.export_joins_path:
        join_rows = []
        for u in scored_units:
            join_rows.append({
                "ticker": u.ticker, "asset": u.asset,
                "horizon_s": u.horizon_s,
                "decision_id": u.decision_id,
                "decision_ts": u.snapshot_ts,
                "target_ts": u.target_ts,
                "tte_s": (u.close_ts - u.snapshot_ts)
                if u.close_ts and u.snapshot_ts else None,
                "join_class": u.anch_join_class,
                "offset_s": u.anch_wf_offset_s,
                "n_candidates": u.anch_n_candidates,
                "ambiguous": u.anch_ambiguous,
                "reused_across_decisions": u.anch_reused,
                "p_anch_wf": u.p_anch_wf,
                "p_raw": u.p_raw, "p_final": u.p_final, "m_mid": u.m_mid,
            })
        try:
            with open(cfg.export_joins_path, "w", encoding="utf-8") as jf:
                for jr in join_rows:
                    jf.write(json.dumps(jr) + "\n")
        except OSError as exc:
            _log(f"WARNING: join export failed: {exc}", t)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "git_sha": _git_sha(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "inputs": {
            "decision_audit_db": _file_meta(cfg.db_path),
            "model_calibration_observations": _file_meta(cfg.model_cal_path),
            "settlement_outcomes": _file_meta(cfg.outcomes_path),
        },
        "parameters": {
            "assets": list(cfg.assets),
            "horizons_s": list(cfg.horizons_s),
            "max_age_s": cfg.max_age_s,
            "n_folds": cfg.n_folds,
            "min_train_n": cfg.min_train_n,
            "replicates": cfg.replicates,
            "block_lens_s": list(cfg.block_lens_s),
            "primary_block_len_s": cfg.primary_block_len_s,
            "seed": cfg.seed,
            "min_support": cfg.min_support,
            "primary_metric": cfg.primary_metric,
            "logloss_clip_eps": 1e-6,
            "since_ts": cfg.since_ts,
            "until_ts": cfg.until_ts,
            "label_policy": cfg.label_policy,
            "grace_s": cfg.grace_s if cfg.label_policy == LABEL_POLICY_GRACE else None,
            "anch_past_tolerance_s": cfg.anch_past_tolerance_s,
            "anch_future_slack_s": cfg.anch_future_slack_s,
        },
        "scoring_unit": "ticker x horizon x model_version_id (canonical YES space)",
        "model_version_definition": (
            "sha1(model_version|calibration_version|config_version|build_sha|"
            "policy_epoch)[:12]; code changes that leave these fields unchanged "
            "are invisible — no per-decision code commit is logged beyond build_sha."
        ),
        "stage_definitions": {
            "raw": "strategy_decision_snapshots.raw_p_yes — pre-anchor model probability",
            "anch_wf": ("model_calibration_observations.jsonl p_model (side=yes) — "
                        "post-anchor + walk-forward, pre-EPC/tail; joined on "
                        "(ticker, TTE-minute); coverage-limited to 2026-10-14+"),
            "final": ("strategy_decision_snapshots.calibrated_p_yes — final emitted "
                      "probability (post anchor + WF + EPC + tail caps + bounds)"),
            "mid": "(yes_bid_cents + yes_ask_cents) / 200 — contemporaneous book mid",
            "q0": "logit(q) = a + b*logit(m), same-horizon expanding-window fit",
            "q1": "logit(q) = a + b*logit(m) + g*z, z = logit(raw) - logit(m)",
            "base_rate": "per-asset expanding mean of official outcomes (label-available)",
            "const_half": "0.5",
        },
        "anchor_weight_semantics": (
            "market_anchor_weight is the MARKET weight in "
            "logit blend: sigmoid((1-w)*logit(p_raw) + w*logit(mid)). Verified "
            "numerically against trade_decision.py on 2026-10-23 telemetry."
        ),
        "unavailable_stages": (
            "Pure post-anchor probability and market_anchor_prob are not "
            "persisted anywhere; the anch_wf stage is the nearest logged "
            "intermediate (post-anchor+WF)."
        ),
        "inference_target": (
            "Resampling frozen evaluation predictions quantifies uncertainty in "
            "their observed performance; it does not account for model "
            "training/selection uncertainty upstream of the ledger."
        ),
        "label_policy_semantics": (
            "observed_only: walk-forward training admits a label only when a "
            "documented observed_at_utc precedes the fold boundary; corrections "
            "are applied as-of the boundary (no post-boundary version leaks). "
            "grace: additionally admits labels whose availability is assumed "
            "as settlement_ts + grace_s — declared sensitivity only."
        ),
        "anch_join_semantics": (
            "anch_wf records carry no inference-event id and no model version. "
            "rec.ts is synchronous log-emission time inside the same evaluation; "
            "decision_ts is evaluation-entry time, so same-event offsets are "
            ">= 0 by construction. Accepted joins are bounded as-of matches "
            "(offset in [-tolerance, +slack]) — PROVISIONAL, never VALID. "
            "Future/out-of-tolerance/ambiguous candidates are rejected with a "
            "recorded reason; rejection narrows support but does not taint "
            "comparisons that don't consume the stage."
        ),
        "probe_warnings": probe_run.warnings,
        "probe_universe_query": probe_run.universe_query,
        "asset_mismatch_tickers_quarantined": probe_run.asset_mismatch_tickers,
    }

    verdict_summary = {
        comp: {
            "statistical_verdict": primary["pooled"][comp].get(
                "statistical_verdict"),
            "integrity_status": primary["pooled"][comp].get(
                "integrity_status"),
            "evidence_eligible": primary["pooled"][comp].get(
                "evidence_eligible"),
            "deployment_gate_passed": False,
        }
        for comp, *_ in COMPARISONS
    }

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "manifest": manifest,
        "population": {
            "tickers_in_scope": len({e.ticker for e in pop_entries}),
            "units_scored": len(scored_units),
            "status_counts": status_counts,
            "per_horizon": per_horizon_pop,
            "close_ts_spread_flag_tickers": population.close_ts_spread_tickers,
            "label_source_counts": population.label_source_counts,
            "decision_row_counts": pop_counts,
            "tickers_probed": len(probes),
            "quarantined_tickers": population.quarantined_tickers,
            "coverage_waterfall": coverage_waterfall,
            "selection_note": (
                "Comparisons consuming p_raw / p_anch_wf / p_final are "
                "conditional on the model/admission cohort where those "
                "probabilities were logged — mid/base_rate/const_half "
                "comparisons cover the full scored population. Pairwise "
                "supports differ; read pooled verdicts per comparison, not "
                "as a common cohort."
            ),
            "research_filter": (
                "record_environment='production' AND is_eligible_for_research=1 "
                "(the ledger's own research-population contract)"
            ),
        },
        "stage_coverage": _stage_coverage(scored_units),
        "horizon_fidelity": horizon_fidelity,
        "boundary_classification": boundary_block,
        "anchored_join": anch_join,
        "label_availability": {
            "policy": cfg.label_policy,
            "assumed_training_labels_used": assumed_train_labels,
            "fold_stats": fold_stats,
        },
        "integrity": _integrity_checks(scored_units, probes, official, anchored, fitted, cfg),
        "q1_residual_diagnostic": {
            "definition": "q1 coefficient on z = logit(raw) - logit(mid); "
                          "expanding-window per-horizon fits",
            "by_horizon": gamma_diag,
            "note": ("The 2026-10-14 'residual slope 1.34, t=4.7' figure came "
                     "from a different regression on EPC observations; this "
                     "diagnostic is the encompassing-test analog on the frozen "
                     "evaluation population. Coefficient is a diagnostic; the "
                     "primary evidence is the q1_vs_q0 score improvement."),
        },
        "results": results,
        "primary_results": primary,
        "verdict_summary": verdict_summary,
        "economics": econ,
        "limitations": [
            "Anchored stage (anch_wf) is post-anchor AND post-walk-forward; "
            "pure-anchor attribution is not possible from persisted records.",
            "calibration_version records the tail-calibration artifact; the "
            "walk-forward calibrator artifact version is not logged per row.",
            "model_version_id is config-level; silent code changes without "
            "config/build changes are not distinguishable.",
            "Fold fits reuse all label-available past units; if the production "
            "model itself changed within the window, pooled comparisons mix "
            "versions (grouped by model_version_id in units; not stratified "
            "further in v1).",
            "Block bootstrap intervals quantify evaluation-set uncertainty, "
            "not upstream model-selection uncertainty.",
            "OPEN RECOVERY TASK (tracked separately from this release): "
            "quarantined boundary-contradiction tickers reflect a "
            "ledger close_ts reconstruction defect (last-row close drifts "
            "past the official boundary when decisions log after scheduled "
            "close), not necessarily bad contracts. Recovery = source the "
            "authoritative scheduled boundary (Kalshi expiration_time, or "
            "the venue-encoded close datetime in the ticker name — see "
            "forecast_event.scheduled_close_from_ticker, P1a) and rerun "
            "population selection on pre-boundary observations — do not "
            "repair by clipping the inferred timestamp.",
        ],
    }


def _fmt_verdict_line(name: str, res: Dict[str, Any]) -> str:
    b = res.get("brier") or {}
    md = b.get("mean_loss_diff")
    ci = b.get("mean_loss_diff_ci")
    bss = b.get("bss")
    ci_s = "" if ci is None else f"[{ci[0]:+.5f}, {ci[1]:+.5f}]"
    md_s = "  n/a  " if md is None else f"{md:+.5f}"
    bss_s = "  n/a " if bss is None else f"{bss:+.4f}"
    integ = res.get("integrity_status")
    integ_s = "" if integ in (None, "VALID") else f" [{integ}]"
    return (
        f"  {name:<20} n={b.get('n_units', 0):<6} "
        f"d={md_s} {ci_s:<24} BSS={bss_s} -> {res.get('statistical_verdict')}{integ_s}"
    )


def print_summary(report: Dict[str, Any]) -> None:
    m = report["manifest"]
    print("=" * 78)
    print("MERID FORECAST AUDIT - independent paired scorer")
    print(f"created {m['created_utc']}  seed={m['parameters']['seed']}  "
          f"replicates={m['parameters']['replicates']}  "
          f"block={m['parameters']['primary_block_len_s']}s  "
          f"label_policy={m['parameters'].get('label_policy')}")
    print("=" * 78)
    pop = report["population"]
    print(f"tickers={pop['tickers_in_scope']}  units={pop['units_scored']}  "
          f"status={pop['status_counts']}")
    if pop.get("quarantined_tickers"):
        print(f"quarantined_tickers={len(pop['quarantined_tickers'])}")
    cov = report["stage_coverage"]
    print(f"coverage: raw={cov['p_raw']} final={cov['p_final']} mid={cov['m_mid']} "
          f"anch_wf={cov['p_anch_wf']} y={cov['y']}")
    print("-" * 78)
    print("POOLED (primary block length), brier:")
    for name, res in report["primary_results"]["pooled"].items():
        print(_fmt_verdict_line(name, res))
    print("-" * 78)
    for sname in sorted(report["primary_results"]):
        if not sname.startswith("horizon_"):
            continue
        print(f"{sname}:")
        for name, res in report["primary_results"][sname].items():
            if name == "q1_vs_q0" or name == "final_vs_mid":
                print(_fmt_verdict_line(name, res))
    print("-" * 78)
    print("VERDICTS:", json.dumps(report["verdict_summary"]).replace("\n", " "))
    print("=" * 78)
