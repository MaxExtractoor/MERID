"""Threshold-cell promotion compiler (data-only, deterministic, fail-closed).

Turns discovery output into a versioned promotion artifact:

    data/cell_discovery.json
        -> 5-stage gate ->
    data/threshold_cell_candidates.json   (promotion pipeline rows)
    data/threshold_cell_rejections.json   (every non-candidate + reason)
    config/threshold_cells_candidates.yaml (human-review manifest)

No cell reaches the live registry from this script.  APPROVED rows require a
human to copy them into config/threshold_cells_live.yaml — this compiler's
maximum reachable status today is CANDIDATE_PENDING_EXECUTION_FEASIBILITY,
because stage 3 (execution feasibility) is FILL_FEASIBILITY_UNKNOWN until
historical book-touch data or live passive-order attempts prove maker
touchability.

Stages (all five assets, one loop, identical rules):
  S1 statistical   n>=50, LCB10>0, LCB10+1c>0, all folds>0, day_share<=0.5
  S2 domain        20-89c x 120-600s only (tail buckets vetoed upstream too)
  S3 execution     FILL_FEASIBILITY_UNKNOWN -> ceiling CANDIDATE_PENDING_*
  S4 recency       n_eff_21d>=10 AND mean_21d>0 else PENDING_RECENCY_*
  S5 deployment    all prior pass concretely -> APPROVED (unreachable while
                   S3 is UNKNOWN)

Usage:
    python scripts/cell_promotion_compiler.py [--in data/cell_discovery.json]
"""

import argparse
import json
import os
from datetime import datetime, timezone

IN = "data/cell_discovery.json"
OUT_CANDIDATES = "data/threshold_cell_candidates.json"
OUT_REJECTIONS = "data/threshold_cell_rejections.json"
OUT_MANIFEST = "config/threshold_cells_candidates.yaml"

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")

# Stage-1 contract (user-specified): stricter than the discovery print pass.
MIN_N = 50
MIN_DAY_SHARE = 0.5
MIN_N_EFF_21D = 10.0


def _verdict_to_reason(verdict):
    return {
        "EXCLUDED_DOMAIN": "outside 20-89c / 120-600s promotion domain",
        "INSUFFICIENT_SAMPLE": "n < 50 settled markets",
        "CONCENTRATED_SAMPLE": "single UTC day holds >50% of cohort",
        "INSUFFICIENT_POSITIVE_LCB": "LCB10 net P&L <= 0",
        "FAILS_+1C_STRESS": "LCB10 fails under +1c adverse execution",
        "FOLD_INSTABILITY": "chronological fold means disagree",
    }.get(verdict, verdict)


def _bucket_to_cell_id(bucket_key):
    """'BTC|no|40-50|t120_300|cf_taker_ask' -> 'btc_no_40_50_t120_300'."""
    asset, side, px, tt, _mode = bucket_key.split("|")
    plo, phi = px.split("-")
    tlo, thi = tt.lstrip("t").split("_")
    return f"{asset.lower()}_{side}_{plo}_{phi}_t{tlo}_{thi}"


def compile_candidates(discovery, live_registry):
    """Evaluate every bucket row for all five assets through the 5 stages."""
    candidates, rejections = [], []
    for asset in ASSETS:
        rec = (discovery.get("per_asset") or {}).get(asset) or {}
        live_ids = set(live_registry.get(asset) or [])
        for b in rec.get("buckets") or []:
            row = {
                "cell_key": b["bucket"],
                "asset": asset,
                "side": b["bucket"].split("|")[1],
                "price_bucket": b["bucket"].split("|")[2],
                "tte_bucket": b["bucket"].split("|")[3],
                "exec_mode": b["bucket"].split("|")[4],
                "historical_n": b["n"],
                "n_markets": b.get("n_markets"),
                "max_day_share": b.get("max_day_share"),
                "effective_n_7d": b.get("n_eff_7d"),
                "effective_n_21d": b.get("n_eff_21d"),
                "mean_net_cents": b["mean"],
                "mean_7d_cents": b.get("mean_7d"),
                "mean_21d_cents": b.get("mean_21d"),
                "lcb10_cents": b["lcb10"],
                "lcb10_plus_1c_cents": b["lcb10_plus1c"],
                "folds": b.get("folds"),
                "fold_stable": bool(
                    b.get("folds") and all(
                        f is not None and f > 0 for f in b["folds"]
                    )
                ),
                "fill_feasibility": "FILL_FEASIBILITY_UNKNOWN",
                "actual_depth_eligible_rate": None,
                "maker_touchable_rate": None,
                "recent_calibration_residual": None,
                "already_live": _bucket_to_cell_id(b["bucket"]) in live_ids,
                "discovery_verdict": b["verdict"],
            }

            # ---- Stage 2: market-domain eligibility -------------------------
            if not b.get("in_domain"):
                row["promotion_status"] = "REJECTED"
                row["exclusion_reason"] = _verdict_to_reason(b["verdict"])
                row["failed_stage"] = "S2_domain"
                rejections.append(row)
                continue

            # ---- Stage 1: statistical eligibility ---------------------------
            folds_ok = row["fold_stable"]
            s1_fail = None
            if b["n"] < MIN_N:
                s1_fail = "n<50"
            elif (b.get("max_day_share") or 0.0) > MIN_DAY_SHARE:
                s1_fail = "concentrated_sample"
            elif b["lcb10"] <= 0:
                s1_fail = "lcb10<=0"
            elif b["lcb10_plus1c"] <= 0:
                s1_fail = "lcb10+1c<=0"
            elif not folds_ok:
                s1_fail = "fold_instability"
            if s1_fail:
                row["promotion_status"] = "REJECTED"
                row["exclusion_reason"] = (
                    f"S1 statistical: {s1_fail}"
                )
                row["failed_stage"] = "S1_statistical"
                rejections.append(row)
                continue

            # ---- Stage 3: execution feasibility -----------------------------
            # No historical book-touch / maker-fill data wired yet — every
            # passing bucket is capped at pending-feasibility, never APPROVED.
            row["promotion_status"] = "CANDIDATE_PENDING_EXECUTION_FEASIBILITY"
            row["exclusion_reason"] = None
            row["failed_stage"] = "S3_execution_feasibility"

            # ---- Stage 4: recency & calibration -----------------------------
            n21 = b.get("n_eff_21d")
            m21 = b.get("mean_21d")
            if (
                n21 is None or n21 < MIN_N_EFF_21D
                or m21 is None or m21 <= 0
            ):
                row["promotion_status"] = "CANDIDATE_PENDING_RECENCY_AND_CALIBRATION"
                row["failed_stage"] = "S4_recency_calibration"

            # ---- Stage 5: deployment ---------------------------------------
            # Unreachable while S3 == UNKNOWN; documented for completeness.
            candidates.append(row)

    order = lambda r: (r["asset"], -(r["lcb10_cents"] or 0))
    candidates.sort(key=order)
    rejections.sort(key=order)
    return candidates, rejections


def _write_manifest(candidates, path):
    """Human-review manifest of pending candidates — NOT a live registry."""
    lines = [
        "# Threshold-cell promotion candidates — REVIEW ONLY.",
        "# Rows here are NOT live.  Promote by copying an approved row into",
        "# config/threshold_cells_live.yaml and filling its approval block.",
        "# Generated by scripts/cell_promotion_compiler.py",
        f"generated_at: \"{datetime.now(timezone.utc).isoformat()}\"",
        "candidates:",
    ]
    for r in candidates:
        plo, phi = r["price_bucket"].split("-")
        tlo, thi = r["tte_bucket"].lstrip("t").split("_")
        cid = (
            f"{r['asset'].lower()}_{r['side']}_{plo}_{phi}_t{tlo}_{thi}"
        )
        lines += [
            f"  - cell_id: {cid}",
            f"    asset: {r['asset']}",
            f"    side: \"{r['side']}\"",
            f"    price_min_cents: {plo}",
            f"    price_max_cents: {phi}",
            f"    tte_min_seconds: {tlo}",
            f"    tte_max_seconds: {thi}",
            f"    promotion_status: {r['promotion_status']}",
            f"    historical_n: {r['historical_n']}",
            f"    lcb10_cents: {r['lcb10_cents']}",
            f"    mean_net_cents: {r['mean_net_cents']}",
            f"    folds: {r['folds']}",
            f"    fill_feasibility: {r['fill_feasibility']}",
        ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _load_live_registry(path="config/threshold_cells_live.yaml"):
    import yaml
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {a: [] for a in ASSETS}
    out = {a: [] for a in ASSETS}
    for row in data.get("cells") or []:
        a = str(row.get("asset", "")).upper()
        if a in out:
            out[a].append(str(row.get("cell_id")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=IN)
    ap.add_argument("--out-candidates", default=OUT_CANDIDATES)
    ap.add_argument("--out-rejections", default=OUT_REJECTIONS)
    ap.add_argument("--out-manifest", default=OUT_MANIFEST)
    ap.add_argument("--registry", default="config/threshold_cells_live.yaml")
    args = ap.parse_args()

    with open(args.inp, "r", encoding="utf-8") as f:
        discovery = json.load(f)
    live_registry = _load_live_registry(args.registry)

    candidates, rejections = compile_candidates(discovery, live_registry)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": args.inp,
        "promotion_contract": (
            "S1 n>=50 & lcb10>0 & lcb10+1c>0 & folds>0 & day_share<=0.5 | "
            "S2 20-89c x 120-600s | S3 execution feasibility (UNKNOWN today) | "
            "S4 n_eff_21d>=10 & mean_21d>0 | S5 explicit approval -> live yaml"
        ),
        "per_cell": candidates,
    }
    with open(args.out_candidates, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    with open(args.out_rejections, "w", encoding="utf-8") as f:
        json.dump({"per_cell": rejections}, f, indent=1)
    _write_manifest(candidates, args.out_manifest)

    print(f"\n== promotion compiler ==")
    print(f"candidates: {len(candidates)}  rejections: {len(rejections)}")
    for r in candidates:
        print(f"  {r['cell_key']:48} lcb={r['lcb10_cents']:>+7.2f} "
              f"{r['promotion_status']}")
    rej_by = {}
    for r in rejections:
        rej_by[r["failed_stage"]] = rej_by.get(r["failed_stage"], 0) + 1
    for stage, n in sorted(rej_by.items()):
        print(f"  rejected@{stage}: {n}")
    print(f"wrote {args.out_candidates}, {args.out_rejections}, "
          f"{args.out_manifest}")


if __name__ == "__main__":
    main()
