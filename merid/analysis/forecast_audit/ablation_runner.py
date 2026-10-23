"""Frozen paired ablation over same-event forecast envelopes (P1b).

Operates on ``forecast_event`` JSONL records — the single-envelope
production/shadow telemetry where every stage value shares one
``forecast_event_id``.  No minute-bucket or proximity joins: an event's
arms are computed on identical inputs, and its contract close comes from
the venue-authoritative ticker name.

Comparisons (per the versioned experiment manifest): paired Brier loss on
explicit common support — both arm probabilities present AND the outcome
resolved AND the scheduled boundary known.  Positive ``d`` means the LEFT
arm loses less (better forecast), i.e. ``d = L(right) - L(left)``.

Cohorts are reported separately:
  * ``all_completed``      — every event whose probability chain completed
  * ``policy_admitted``    — events the incumbent policy admitted
An admission-conditioned cohort is a *policy* view, never unconditional
forecasting evidence.

Verdicts separate statistical evidence from deployment: every comparison
carries ``evidence_eligible`` + ``statistical_verdict`` +
``deployment_gate_passed=false`` — no production promotion is authorized
by this runner.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from merid.analysis.forecast_audit.bootstrap import (
    block_ids_for_units,
    make_comp_blocks,
    paired_bootstrap,
)
from merid.analysis.forecast_audit.inference import brier, logloss
from merid.analysis.forecast_audit.records import load_official_outcomes

RUNNER_SCHEMA_VERSION = 1

# Arm -> event field carrying its YES-space probability.  ``Q0`` lives only
# in the recorded arms block (it needs the frozen market-only calibrator).
ARM_STAGE_FIELD = {
    "M": "market_anchor_prob_used",
    "R": "raw_p_yes",
    "A": "post_walkforward_p_yes",
    "P": "final_p_yes",
}


def load_forecast_events(path: str | Path) -> tuple:
    """Load + reconcile forecast events.

    Dedupe is on ``record_id`` (retransmission of the same completed
    evaluation is idempotent).  Two envelopes sharing one
    ``forecast_event_id`` but carrying different ``record_id``/``content_hash``
    are CONFLICTS — reported and excluded from scoring, never silently
    first- or last-wins.  Schema-1 records (pre record_id) fall back to
    ``forecast_event_id`` as the dedupe key.

    Returns (events, stats).
    """
    by_record: Dict[str, Dict[str, Any]] = {}
    eval_hashes: Dict[str, str] = {}
    conflicts = malformed = dup = 0
    conflict_ids = set()
    p = Path(path)
    if not p.exists():
        return [], {"malformed": 0, "duplicate_ids": 0,
                    "conflicting_records": 0, "missing_file": True}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(r, dict) or not r.get("forecast_event_id"):
                malformed += 1
                continue
            fid = str(r["forecast_event_id"])
            rid = str(r.get("record_id") or fid)
            ch = r.get("content_hash")
            prev = eval_hashes.get(fid)
            if prev is not None and ch is not None and prev != ch:
                conflicts += 1
                conflict_ids.add(fid)
            eval_hashes.setdefault(fid, ch)
            if rid in by_record:
                dup += 1
                continue
            by_record[rid] = r
    for fid in conflict_ids:
        for rid, r in list(by_record.items()):
            if r.get("forecast_event_id") == fid:
                del by_record[rid]
    return list(by_record.values()), {
        "malformed": malformed,
        "duplicate_ids": dup,
        "conflicting_records": conflicts,
        "conflict_event_ids": sorted(conflict_ids),
    }


def load_opportunity_ledger(path: str | Path) -> Dict[str, Any]:
    """Reconcile the scheduled-opportunity ledger.

    Returns counts by status plus the registration/resolution rows.  A
    registered opportunity with no resolution row after its deadline is
    ``unresolved`` — expected-opportunity accounting never infers a
    completion from silence.
    """
    rows: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return {"rows": 0, "by_status": {}, "unresolved_registrations": 0}
    malformed = 0
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(r, dict):
                rows.append(r)
            else:
                malformed += 1
    registrations: Dict[str, Dict[str, Any]] = {}
    resolutions: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        oid = r.get("opportunity_id")
        if not oid:
            continue
        if r.get("status") == "scheduled":
            registrations[oid] = r
        else:
            resolutions[oid] = r
    by_status: Dict[str, int] = {}
    for r in resolutions.values():
        s = str(r.get("status"))
        by_status[s] = by_status.get(s, 0) + 1
    unresolved = len(set(registrations) - set(resolutions))
    if unresolved:
        by_status["unresolved"] = by_status.get("unresolved", 0) + unresolved
    return {
        "rows": len(rows),
        "malformed": malformed,
        "registrations": len(registrations),
        "resolutions": len(resolutions),
        "unresolved_registrations": unresolved,
        "by_status": by_status,
        "registered_after_target": sum(
            1 for r in registrations.values()
            if r.get("registered_after_target")),
    }


_ATTEMPT_RULES = ("first_attempt", "first_emitted")
_NON_SCORING = ("late", "missed", "unavailable", "invalid_input")


def _ordered(evs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(evs, key=lambda e: e.get("actual_evaluation_ts")
                  or e.get("evaluation_end_ts") or 0.0)


def select_attempts(events: List[Dict[str, Any]],
                    rule: str = "first_attempt") -> tuple:
    """Declared attempt selection, blind to probabilities and outcomes.

    Rules (per (evaluation_source, opportunity_id) group, ordered by
    ``actual_evaluation_ts``):

    ``first_attempt`` — CONSERVATIVE PRIMARY.  Select the chronologically
    first attempt.  If its forecast is unavailable/late the unit is
    flagged ``_excluded`` and counts as unavailable — later successful
    attempts never masquerade as forecasts made at the earlier timestamp.

    ``first_emitted`` — declared SENSITIVITY / operational policy.  Select
    the first attempt with ``opportunity_status == "emitted"`` (all
    attempts are already required to be inside the scheduled delay bound
    at emission; a "late" status means the attempt itself was late).

    Returns (selected, stats) — superseded attempts are counted and their
    statuses preserved in ``superseded_statuses``, not deleted.
    ``first_vs_first_emitted_divergence`` reports where the two rules
    would pick different attempts.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for ev in events:
        key = (ev.get("evaluation_source"), ev.get("opportunity_id"))
        groups.setdefault(key, []).append(ev)
    selected: List[Dict[str, Any]] = []
    superseded = late_excluded = divergence = 0
    superseded_statuses: Dict[str, int] = {}
    for (_src, _oid), evs in groups.items():
        evs = _ordered(evs)
        first = evs[0]
        emitted = next(
            (e for e in evs if e.get("opportunity_status") == "emitted"),
            None)
        if len(evs) > 1 and emitted is not None and emitted is not first:
            divergence += 1
        if rule == "first_emitted":
            ci = evs.index(emitted) if emitted is not None else len(evs) - 1
        else:
            ci = 0
        chosen = dict(evs[ci])
        st = chosen.get("opportunity_status")
        if st in _NON_SCORING:
            chosen["_excluded"] = True
            if st == "late":
                late_excluded += 1
        for i, e in enumerate(evs):
            if i != ci:
                superseded += 1
                s = str(e.get("opportunity_status") or "unrecorded")
                superseded_statuses[s] = superseded_statuses.get(s, 0) + 1
        selected.append(chosen)
    return selected, {
        "rule": rule,
        "superseded_attempts": superseded,
        "superseded_statuses": superseded_statuses,
        "late_excluded": late_excluded,
        "first_vs_first_emitted_divergence": divergence,
    }


def arm_probability(event: Dict[str, Any], arm: str) -> Optional[float]:
    """YES-space probability for an ablation arm; None when unavailable."""
    if arm == "Q0":
        v = (event.get("arms") or {}).get("Q0")
    else:
        field = ARM_STAGE_FIELD.get(arm)
        v = event.get(field) if field else (event.get("arms") or {}).get(arm)
    if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0:
        return float(v)
    return None


def build_units(
    events: List[Dict[str, Any]],
    outcomes_by_ticker: Dict[str, Any],
    *,
    horizons: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Join events to official outcomes; keep units with a resolved label.

    The outcome is keyed by ticker — for forecast-event units the ticker is
    identity-verified (the event's own ``market_ticker``), and the outcome
    label is the latest official record, same as the P0 scorer.
    """
    hset = set(int(h) for h in horizons) if horizons else None
    units: List[Dict[str, Any]] = []
    for ev in events:
        if ev.get("_excluded"):
            continue  # late/all-attempts-failed opportunities: diagnostic only
        h = ev.get("scheduled_horizon_s")
        if hset is not None and ev.get("evaluation_source") == "scheduled_shadow":
            if h not in hset:
                continue
        ticker = ev.get("market_ticker")
        oc = outcomes_by_ticker.get(str(ticker).upper()) if ticker else None
        if oc is None or oc.resolved_yes not in (0, 1):
            continue
        units.append({
            "event": ev,
            "ticker": ticker,
            "asset": ev.get("asset"),
            "horizon_s": int(h) if isinstance(h, (int, float)) else None,
            "close_ts": ev.get("scheduled_contract_close_ts"),
            "y": int(oc.resolved_yes),
            "admitted": str(ev.get("admission_result") or "") == "enter",
            "completed": ev.get("forecast_availability") == "available",
            "source": ev.get("evaluation_source"),
        })
    return units


def weighted_primary_statistic(
    units: List[Dict[str, Any]],
    *,
    left: str = "P",
    right: str = "A",
    horizon_weights: Optional[Dict[int, float]] = None,
    loss_fn=brier,
    block_len_s: float = 3600.0,
    replicates: int = 2000,
    seed: int = 0,
    ci: float = 0.95,
) -> Dict[str, Any]:
    """Fixed horizon-weighted paired-difference estimand (primary).

    Delta = sum_h w_h * mean_{S_h}( L(right) - L(left) ), where S_h is the
    eligible first-attempt common-support set at horizon h.  Positive means
    the LEFT arm (production stack) forecasts better.  This is NOT the
    pooled mean — horizons carry fixed weights independent of emission
    frequency.

    Bootstrap: shared calendar-block draws (contiguous close_ts blocks);
    each draw recomputes the per-horizon mean then combines with fixed
    weights.  A draw lacking support at ANY required horizon is counted
    unsupported — never renormalized over remaining horizons.
    """
    from .bootstrap import block_ids_for_units, shared_draws
    weights = {int(h): float(w)
               for h, w in (horizon_weights or {}).items() if w > 0}
    by_h: Dict[int, List[int]] = {h: [] for h in weights}
    d_vals: List[float] = []
    close_ts: List[Optional[float]] = []
    unit_h: List[Optional[int]] = []
    for i, u in enumerate(units):
        h = u.get("horizon_s")
        ev = u.get("event") or {}
        lp, la = _arm(ev, left), _arm(ev, right)
        ok = (h in weights and u.get("completed") and lp is not None
              and la is not None and u.get("close_ts") is not None)
        d = (loss_fn(la, u["y"]) - loss_fn(lp, u["y"])) if ok else None
        d_vals.append(float(d) if d is not None else float("nan"))
        close_ts.append(u.get("close_ts"))
        unit_h.append(int(h) if ok else None)
        if ok:
            by_h[int(h)].append(i)

    support = {h: len(idxs) for h, idxs in by_h.items()}
    point: Optional[float] = None
    per_h_point: Dict[str, Any] = {}
    for h, idxs in by_h.items():
        if idxs:
            per_h_point[str(h)] = {
                "n": len(idxs),
                "mean_d": float(np.nanmean([d_vals[i] for i in idxs])),
            }
        else:
            per_h_point[str(h)] = {"n": 0, "mean_d": None}
    if all(idxs for idxs in by_h.values()):
        point = float(sum(weights[h] * per_h_point[str(h)]["mean_d"]
                          for h in weights))

    block_of, n_blocks = block_ids_for_units(close_ts, block_len_s)
    result: Dict[str, Any] = {
        "point": point,
        "per_horizon": per_h_point,
        "support_by_horizon": support,
        "weights": {str(h): weights[h] for h in weights},
        "n_blocks": n_blocks,
        "replicates": replicates,
        "ci_level": ci,
        "ci": None,
        "valid_draws": 0,
        "unsupported_draws": replicates,
        "statistic": "fixed_horizon_weighted_paired_diff",
        "note": ("positive = LEFT arm better; a draw missing support at "
                 "any required horizon is unsupported, never renormalized"),
    }
    if n_blocks == 0 or point is None:
        return result

    import numpy as _np
    draws = shared_draws(n_blocks, replicates, seed)
    h_sums, h_counts = {}, {}
    for h, idxs in by_h.items():
        b = _np.array([block_of[i] for i in idxs], dtype=_np.int64)
        d = _np.array([d_vals[i] for i in idxs])
        h_counts[h] = _np.bincount(b, minlength=n_blocks).astype(_np.float64)
        h_sums[h] = _np.bincount(b, weights=d, minlength=n_blocks)
    wdraws = _np.zeros(replicates)
    supported = _np.ones(replicates, dtype=bool)
    for h in weights:
        denom = draws @ h_counts[h]
        ok_h = denom > 0
        supported &= ok_h
        means = _np.full(replicates, _np.nan)
        means[ok_h] = (draws @ h_sums[h])[ok_h] / denom[ok_h]
        wdraws = wdraws + weights[h] * means
        # nan propagates for horizons with no support in a draw
    valid = supported & ~_np.isnan(wdraws)
    n_valid = int(valid.sum())
    result["valid_draws"] = n_valid
    result["unsupported_draws"] = int(replicates - n_valid)
    if n_valid:
        a = (1.0 - ci) / 2.0
        vs = wdraws[valid]
        result["ci"] = [float(_np.percentile(vs, 100 * a)),
                        float(_np.percentile(vs, 100 * (1 - a)))]
        result["draw_mean"] = float(vs.mean())
    return result


def _arm(ev: Dict[str, Any], name: str) -> Optional[float]:
    """Arm value: explicit ``arms`` entry, else the matching stage field."""
    arms = ev.get("arms") or {}
    v = arms.get(name)
    if isinstance(v, (int, float)):
        return float(v)
    stage = {"P": "final_p_yes", "A": "post_walkforward_p_yes",
             "M": "market_anchor_prob_used", "R": "raw_p_yes",
             "Q0": None}.get(name)
    v = ev.get(stage) if stage else None
    return float(v) if isinstance(v, (int, float)) else None


def _loss(fn, p, y):
    return fn(float(p), int(y))


def run_comparisons(
    units: List[Dict[str, Any]],
    *,
    comparisons: List[List[str]],
    loss_name: str,
    block_len_s: float,
    replicates: int,
    seed: int,
    mwe: float,
    cohort: str,
) -> Dict[str, Any]:
    """Paired comparisons on explicit common support for one cohort."""
    if cohort == "policy_admitted":
        units = [u for u in units if u["admitted"]]
    elif cohort == "all_completed":
        units = [u for u in units if u["completed"]]
    loss_fn = {"brier": brier, "logloss": logloss}[loss_name]
    if not units:
        return {
            name: {"n": 0, "statistical_verdict": "INSUFFICIENT",
                   "evidence_eligible": False}
            for left, right in comparisons
            for name in (f"{left}_vs_{right}",)
        }

    close_ts = [u["close_ts"] for u in units]
    block_of, n_blocks = block_ids_for_units(close_ts, block_len_s)
    comps = {}
    support_stats: Dict[str, Dict[str, int]] = {}
    for left, right in comparisons:
        name = f"{left}_vs_{right}"
        idx, d, lc, lb = [], [], [], []
        n_left_missing = n_right_missing = 0
        for i, u in enumerate(units):
            pl = arm_probability(u["event"], left)
            pr = arm_probability(u["event"], right)
            if pl is None:
                n_left_missing += 1
            if pr is None:
                n_right_missing += 1
            if pl is None or pr is None:
                continue
            idx.append(i)
            lc.append(_loss(loss_fn, pl, u["y"]))
            lb.append(_loss(loss_fn, pr, u["y"]))
            d.append(lb[-1] - lc[-1])
        comps[name] = make_comp_blocks(
            block_of, idx,
            np.asarray(d, dtype=np.float64),
            np.asarray(lc, dtype=np.float64),
            np.asarray(lb, dtype=np.float64),
            n_blocks)
        support_stats[name] = {
            "n_support": len(idx),
            "n_left_missing": n_left_missing,
            "n_right_missing": n_right_missing,
        }

    results = paired_bootstrap(comps, replicates=replicates, seed=seed)
    out: Dict[str, Any] = {}
    for name, res in results.items():
        d = res.point_mean_d
        ci = res.ci_d
        if res.n_units == 0 or d is None or ci is None:
            verdict = "INSUFFICIENT"
        elif ci[0] > mwe:
            verdict = "PASS"          # left arm beats right by > MWE
        elif ci[1] < 0.0:
            verdict = "FAIL"          # left arm is worse than right
        else:
            verdict = "INCONCLUSIVE"
        out[name] = {
            "n": res.n_units,
            "n_blocks_used": res.n_blocks_used,
            "mean_loss_diff_left_minus_right_benefit": round(d, 6)
            if d is not None else None,
            "ci95": [round(c, 6) for c in ci] if ci else None,
            "point_bs_left": res.point_bs_cand,
            "point_bs_right": res.point_bs_base,
            "support": support_stats.get(name),
            "replicate_accounting": {
                "requested": res.n_requested_draws,
                "valid_loss": res.n_valid_loss_draws,
                "empty_support": res.n_empty_support_draws,
                "valid_skill": res.n_valid_skill_draws,
                "zero_baseline_loss": res.n_zero_baseline_loss_draws,
            },
            "statistical_verdict": verdict,
            "evidence_eligible": verdict != "INSUFFICIENT",
            "deployment_gate_passed": False,
        }
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Frozen paired ablation over forecast events (P1b).")
    ap.add_argument("--events", default="logs/forecast_events.jsonl")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--manifest", default=None,
                    help="Versioned experiment manifest (defaults baked in "
                         "when absent).")
    ap.add_argument("--loss", default=None)
    ap.add_argument("--block-len-s", type=float, default=None)
    ap.add_argument("--replicates", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--min-effect", type=float, default=None)
    ap.add_argument("--horizons", default=None,
                    help="Comma list; shadow events outside are excluded.")
    ap.add_argument("--opportunities",
                    default="logs/forecast_opportunities.jsonl")
    ap.add_argument("--attempt-rule", choices=sorted(_ATTEMPT_RULES),
                    default="first_attempt",
                    help="first_attempt = conservative primary (unavailable "
                         "forecasts count as unavailable); first_emitted = "
                         "declared sensitivity")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    cfg: Dict[str, Any] = {}
    if args.manifest:
        cfg = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    loss_name = args.loss or cfg.get("primary_metric", "brier")
    block_len = args.block_len_s or cfg.get("block_len_s", 3600.0)
    replicates = args.replicates or cfg.get("bootstrap_replicates", 2000)
    seed = args.seed or cfg.get("seed", 20261023)
    mwe = args.min_effect if args.min_effect is not None else cfg.get(
        "minimum_worthwhile_effect", 0.0)
    horizons = (
        [int(h) for h in args.horizons.split(",")] if args.horizons
        else cfg.get("horizons_s")
    )
    comparisons = cfg.get("comparisons", [
        ["P", "A"], ["P", "M"], ["A", "R"], ["Q0", "M"], ["R", "M"],
    ])

    t0 = time.time()
    events, estats = load_forecast_events(args.events)
    events, sel_stats = select_attempts(events, rule=args.attempt_rule)
    opp_ledger = load_opportunity_ledger(args.opportunities)
    outcomes = load_official_outcomes(args.outcomes)
    units = build_units(events, outcomes.by_ticker, horizons=horizons)

    waterfall = {
        "registered_opportunities": opp_ledger.get("registrations"),
        "registered_after_target": opp_ledger.get("registered_after_target"),
        "resolved_by_status": opp_ledger.get("by_status"),
        "selected_units": len(units),
        "units_with_both_P_and_A": sum(
            1 for u in units
            if _arm(u["event"], "P") is not None
            and _arm(u["event"], "A") is not None),
        "policy_admitted": sum(1 for u in units if u["admitted"]),
        "note": ("common-support conditioning: P_vs_A describes only the "
                 "units where BOTH stages were produced — not every timely "
                 "event is part of the primary comparison"),
    }
    report = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "title": ("Conditional-cohort forecast ablation — scheduled "
                  "opportunities reaching the production evaluation hook "
                  "(conditional_on_reaching_eval_hook); NOT an "
                  "all-opportunity estimate"),
        "generated_ts": time.time(),
        "config": {
            "loss": loss_name, "block_len_s": block_len,
            "replicates": replicates, "seed": seed,
            "minimum_worthwhile_effect": mwe,
            "horizons_s": horizons,
            "manifest": args.manifest,
        },
        "population": {
            "events_total": len(events),
            "malformed": estats.get("malformed"),
            "duplicate_ids": estats.get("duplicate_ids"),
            "conflicting_records": estats.get("conflicting_records"),
            "conflict_event_ids": estats.get("conflict_event_ids"),
            "attempt_selection": sel_stats,
            "coverage_waterfall": waterfall,
            "opportunity_ledger": opp_ledger,
            "units_with_outcome": len(units),
            "completed": sum(1 for u in units if u["completed"]),
            "admitted": sum(1 for u in units if u["admitted"]),
            "by_source": _counts(units, "source"),
            "by_horizon": _counts(units, "horizon_s"),
        },
        "primary_comparison": cfg.get("primary_comparison", "P_vs_A"),
        "note": ("d = L(right) - L(left); positive means the LEFT arm "
                 "forecasts better. PASS requires CI lo > MWE; FAIL means "
                 "left arm worse (CI hi < 0); deployment_gate_passed is "
                 "always false — evidence informs, never authorizes."),
    }
    pe = cfg.get("primary_estimand") or {}
    pw = pe.get("weights") or {}
    horizon_weights = {int(h): float(w) for h, w in pw.items()} if pw else None
    if horizon_weights:
        prim = cfg.get("primary_comparison", "P_vs_A")
        report["primary_estimand"] = weighted_primary_statistic(
            units,
            left=prim.split("_vs_")[0], right=prim.split("_vs_")[-1],
            horizon_weights=horizon_weights,
            loss_fn={"brier": brier, "logloss": logloss}[loss_name],
            block_len_s=block_len, replicates=replicates, seed=seed,
            ci=0.95)
        report["primary_estimand"]["comparison"] = prim
        report["primary_estimand"]["weights_rule"] = pe.get("weights_rule")
    for cohort in ("all_completed", "policy_admitted"):
        report[cohort] = run_comparisons(
            units, comparisons=comparisons, loss_name=loss_name,
            block_len_s=block_len, replicates=replicates, seed=seed,
            mwe=mwe, cohort=cohort)
    report["runtime_s"] = round(time.time() - t0, 1)

    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text if not args.out else f"wrote {args.out}")
    return 0


def _counts(units: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for u in units:
        out[str(u.get(key))] = out.get(str(u.get(key)), 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
