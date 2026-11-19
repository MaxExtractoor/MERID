#!/usr/bin/env python3
"""Fit and freeze the lead-lag shadow models for prospective capture.

Reads the offline screen's dataset.jsonl (recv/deployable arm), reproduces
the screen's feature vector EXACTLY (imports _feat_vector from the screen
runner to prevent spec drift), fits the preregistered model set on ALL
feature-complete rows, and exports a self-contained JSON artifact that the
live shadow emitter consumes with pure-Python dot-product inference (no
sklearn in the trading path).

Model set (frozen per MERID_LEAD_LAG_SHADOW_LANE_DESIGN + capture directive):
  p_shadow_btc_final    p0=p_cal lane incumbent + BTC+own+controls+market
  p_shadow_btc_raw      p0=p_raw settlement prob   + BTC+own+controls+market
  p_shadow_nobtc_final  p0=p_cal                   + own+controls+market
  p_control_final       p0=p_cal recalibration only
  p_control_raw         p0=p_raw recalibration only

Prospective data is the true holdout; no internal split is reserved.

Usage:
    .venv\\Scripts\\python.exe scripts\\fit_leadlag_shadow_models.py \
        --dataset analysis/leadlag_screen_2026-11-12/dataset.jsonl \
        --out merid/prediction/leadlag_shadow_model_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import the screen runner for the canonical feature function.
_spec = importlib.util.spec_from_file_location(
    "leadlag_screen", ROOT / "scripts" / "leadlag_feasibility_screen.py")
screen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screen)

RTI_HORIZONS_S = screen.RTI_HORIZONS_S
TARGET_ASSETS = screen.TARGET_ASSETS
MAX_EVAL_AGE_S = screen.MAX_EVAL_AGE_S
EPS = screen.EPS

FEATURE_NAMES = (
    ["logit_p0"]
    + [f"btc_ret_{int(h)}s_x1e4" for h in RTI_HORIZONS_S]
    + [f"own_ret_{int(h)}s_x1e4" for h in RTI_HORIZONS_S]
    + ["zscore", "tte_frac", "in_window", "eval_age_frac",
       "yes_mid_logit", "yes_mid_missing"]
    + [f"asset_{a}" for a in TARGET_ASSETS]
)

# (model_key, p0_key, include_btc, include_own, include_market)
MODEL_SPECS = [
    ("p_shadow_btc_final",   "p_cal", True,  True,  True),
    ("p_shadow_btc_raw",     "p_raw",  True,  True,  True),
    ("p_shadow_nobtc_final", "p_cal", False, True,  True),
    ("p_shadow_nobtc_raw",   "p_raw",  False, True,  True),
    ("p_control_final",      "p_cal", None,  None,  None),   # logit(p0) only
    ("p_control_raw",        "p_raw",  None,  None,  None),
]


def _load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        for k in list(r.keys()):
            if "_ret_" in k:
                r[k] = {float(h): v for h, v in (r[k] or {}).items()}
        rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--anchor", default="recv",
                    help="feature arm (recv = deployable receipt-time)")
    args = ap.parse_args()

    from sklearn.linear_model import LogisticRegression

    rows = _load_rows(Path(args.dataset))
    print(f"loaded {len(rows)} rows")

    fitted = {}
    train_meta = {}
    for mkey, p0_key, ib, io, im in MODEL_SPECS:
        xs, ys = [], []
        for r in rows:
            rr = dict(r)
            rr["_p0"] = r.get(p0_key)
            if p0_key is None:
                # recalibration-only control: single logit feature
                if rr["_p0"] is None:
                    continue
                x = [screen._logit(rr["_p0"])]
            else:
                x = screen._feat_vector(rr, args.anchor, ib, io, im)
                if x is None:
                    continue
            xs.append(x)
            ys.append(int(r["y"]))
        if len(xs) < 30:
            print(f"[skip] {mkey}: only {len(xs)} usable rows")
            continue
        X = np.array(xs, dtype=float)
        y = np.array(ys, dtype=float)
        if p0_key is None:
            clf = LogisticRegression(C=1.0, max_iter=1000).fit(X, y)
        else:
            clf = LogisticRegression(C=0.5, max_iter=2000).fit(X, y)
        coef = [float(c) for c in clf.coef_[0]]
        intercept = float(clf.intercept_[0])
        fitted[mkey] = {
            "kind": "logit_only" if p0_key is None else "full",
            "p0_key": p0_key,
            "include_btc": ib, "include_own": io, "include_market": im,
            "coef": coef, "intercept": intercept,
            "n_features": len(coef),
            "n_train": len(xs),
            "train_ll": float(
                -np.mean(y * np.log(np.clip(clf.predict_proba(X)[:, 1], EPS, 1 - EPS))
                         + (1 - y) * np.log(np.clip(1 - clf.predict_proba(X)[:, 1], EPS, 1 - EPS)))),
        }
        train_meta[mkey] = {
            "n": len(xs), "days": sorted({r["day_utc"] for r in rows
                                          if r.get("y") is not None}),
        }
        print(f"[fit] {mkey}: n={len(xs)} features={len(coef)} "
              f"train_ll={fitted[mkey]['train_ll']:.4f}")

    # canonical spec hash — covers feature names/order, horizons, assets,
    # model definitions, and coefficients so any drift is detectable.
    canon = {
        "feature_names": list(FEATURE_NAMES),
        "horizons_s": list(RTI_HORIZONS_S),
        "target_assets": list(TARGET_ASSETS),
        "anchor": args.anchor,
        "max_eval_age_s": MAX_EVAL_AGE_S,
        "eps": EPS,
        "models": {k: {"coef": v["coef"], "intercept": v["intercept"],
                       "p0_key": v["p0_key"], "kind": v["kind"],
                       "include_btc": v["include_btc"],
                       "include_own": v["include_own"],
                       "include_market": v["include_market"]}
                   for k, v in fitted.items()},
    }
    model_hash = hashlib.sha256(
        json.dumps(canon, sort_keys=True).encode()).hexdigest()

    artifact = {
        "artifact_type": "leadlag_shadow_model",
        "model_version": "leadlag-shadow-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_dataset": str(args.dataset),
        "anchor": args.anchor,
        "feature_names": list(FEATURE_NAMES),
        "horizons_s": list(RTI_HORIZONS_S),
        "target_assets": list(TARGET_ASSETS),
        "max_eval_age_s": MAX_EVAL_AGE_S,
        "eps": EPS,
        "n_train_rows": len(rows),
        "train_meta": train_meta,
        "model_hash": model_hash,
        "models": {k: {kk: vv for kk, vv in v.items() if kk != "train_ll"}
                   for k, v in fitted.items()},
        "train_logloss": {k: v["train_ll"] for k, v in fitted.items()},
        "semantics": {
            "p0_cal": "decision.p_yes_calibrated (lane-relative incumbent)",
            "p0_raw": "decision.p_yes_raw (settlement-adjusted raw / "
                      "p_settle_raw when settlement path active)",
            "eval_age_s": "feature_age_ms/1000 at eval time (live analog of "
                          "screen checkpoint staleness)",
            "returns": "log returns from FeatureSnapshot rti_returns "
                       "(receipt-time by construction), x1e4 scaling",
            "yes_mid_prob": "(yes_bid+yes_ask)/200 cents->prob",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"[done] wrote {out} hash={model_hash[:16]} models={len(fitted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
