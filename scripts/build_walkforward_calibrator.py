"""Fit walk-forward asset x TTE calibration for the 15m Bachelier lane.

Reads settled decisions from ``data/decision_audit.db`` and fits one
canonical YES-probability corrector per (asset, tte_bucket):

    p_yes_wf = C_{asset,tte}(p_yes_model) ;  p_no_wf = 1 - p_yes_wf

Method per cell (per sklearn calibration guidance):
    n >= 1000 -> isotonic regression (nonparametric, monotone)
    300 <= n < 1000 -> Platt/logistic on logit(p) (safe small-sample map)
    100 <= n < 300 -> asset-pooled model (hierarchical fallback)
    n < 100 -> identity (insufficient evidence)

Walk-forward honesty:
    * first observation per market only (cluster dedupe)
    * chronological 60/40 split inside each cell: fit on the first 60%,
      accept the cell map only if OOS Brier improves AND OOS log-loss
      does not materially worsen; otherwise the cell ships "identity".

Output: ``data/calibration/walkforward_calibrator.json``

Usage: python scripts/build_walkforward_calibrator.py [--days 14]
"""
import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict

DB = "data/decision_audit.db"
OUT = os.path.join("data", "calibration", "walkforward_calibrator.json")

TTE_EDGES = {"early": (600, float("inf")), "mid": (300, 600), "late": (0, 300)}


def _tte(tte_s):
    if tte_s > 600:
        return "early"
    if tte_s >= 300:
        return "mid"
    return "late"


def _logit(p):
    p = max(1e-6, min(1.0 - 1e-6, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def _brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / max(len(ps), 1)


def _logloss(ps, ys):
    eps = 1e-15
    return -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
                for p, y in zip(ps, ys)) / max(len(ps), 1)


def _fit_platt(xs, ys, iters=50, lr=0.05, l2=1e-3):
    """Tiny 2-param logistic fit on logit(p): sigmoid(a + b*logit(p))."""
    a, b = 0.0, 1.0
    n = max(len(xs), 1)
    xs_l = [_logit(x) for x in xs]
    for _ in range(iters):
        ga = gb = 0.0
        for xl, y in zip(xs_l, ys):
            h = _sigmoid(a + b * xl)
            ga += (h - y)
            gb += (h - y) * xl
        ga = ga / n + l2 * a
        gb = gb / n + l2 * (b - 1.0)  # shrink toward identity slope
        a -= lr * ga
        b -= lr * gb
        b = max(0.05, min(20.0, b))
    return {"method": "platt", "a": a, "b": b}


def _fit_isotonic(xs, ys):
    """PAVA isotonic fit -> monotone step knots [(x_threshold, y)]."""
    from sklearn.isotonic import IsotonicRegression
    import numpy as np
    xs_a = np.asarray(xs, dtype=float)
    ys_a = np.asarray(ys, dtype=float)
    iso = IsotonicRegression(out_of_bounds="clip", increasing=True)
    iso.fit(xs_a, ys_a)
    # Persist as piecewise knots on the sorted-unique x grid, subsampled.
    knots_x = np.unique(np.round(xs_a, 4))
    if len(knots_x) > 60:
        idx = np.linspace(0, len(knots_x) - 1, 60).astype(int)
        knots_x = knots_x[idx]
    knots_y = iso.predict(knots_x)
    return {"method": "isotonic",
            "x": [float(x) for x in knots_x],
            "y": [float(y) for y in knots_y]}


def _predict(model, p):
    if model["method"] == "isotonic":
        xs, ys = model["x"], model["y"]
        if p <= xs[0]:
            return ys[0]
        if p >= xs[-1]:
            return ys[-1]
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= p:
                lo = mid
            else:
                hi = mid
        x0, x1, y0, y1 = xs[lo], xs[hi], ys[lo], ys[hi]
        return y0 + (y1 - y0) * (p - x0) / max(x1 - x0, 1e-12)
    if model["method"] == "platt":
        return _sigmoid(model["a"] + model["b"] * _logit(p))
    return p


def _fit_cell(fit_p, fit_y, pooled):
    n = len(fit_p)
    if n >= 1000:
        return _fit_isotonic(fit_p, fit_y)
    if n >= 300:
        return _fit_platt(fit_p, fit_y)
    if pooled is not None:
        return pooled
    return {"method": "identity"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=14.0)
    args = ap.parse_args()
    since = time.time() - args.days * 86400

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    # Canonical probability = raw model p_yes (pre-cap, pre-anchor).  We fit
    # C(p_raw -> outcome) so the runtime layer corrects the model before the
    # per-side evidence caps bind; fitting post-cap values would conflate
    # model error with the cap's price-cell evidence.
    # Dedupe to ONE observation per (market, tte_bucket): a market may appear
    # once in early, once in mid, once in late — globally-first-per-market
    # would force every cell into "early" since markets are seen at open.
    q = """
    WITH ranked AS (
      SELECT sd.ticker, sd.asset, sd.decision_ts, sd.seconds_to_close AS tte,
             ss.raw_p_yes AS p, o.settled_yes AS y,
             ROW_NUMBER() OVER (
               PARTITION BY sd.ticker,
                 CASE WHEN sd.seconds_to_close > 600 THEN 'early'
                      WHEN sd.seconds_to_close >= 300 THEN 'mid' ELSE 'late' END
               ORDER BY sd.decision_ts
             ) rn
      FROM strategy_decisions sd
      JOIN strategy_decision_snapshots ss ON ss.decision_id = sd.decision_id
      JOIN strategy_decision_outcomes o ON o.decision_id = sd.decision_id
      WHERE o.outcome_status = 'SETTLED'
        AND ss.raw_p_yes IS NOT NULL
        AND sd.decision_ts > ?
    )
    SELECT asset, tte, p, y, ticker FROM ranked WHERE rn=1
    """
    cells = defaultdict(lambda: {"p": [], "y": []})
    n_rows = 0
    for r in db.execute(q, (since,)):
        n_rows += 1
        cells[(r["asset"], _tte(r["tte"] or 0))]["p"].append(float(r["p"]))
        cells[(r["asset"], _tte(r["tte"] or 0))]["y"].append(float(r["y"]))
    print(f"loaded {n_rows} unique-market YES-side observations")

    # Asset-pooled fallback models.
    pooled = {}
    by_asset = defaultdict(lambda: {"p": [], "y": []})
    for (asset, _t), d in cells.items():
        by_asset[asset]["p"].extend(d["p"])
        by_asset[asset]["y"].extend(d["y"])
    for asset, d in by_asset.items():
        if len(d["p"]) >= 300:
            k = int(len(d["p"]) * 0.6)
            pooled[asset] = _fit_platt(d["p"][:k], d["y"][:k])
            pooled[asset]["method"] = "pooled_platt"

    artifact = {
        "version": "walkforward_v1",
        "fitted_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "days": args.days,
        "cells": {},
    }
    print(f"{'cell':18} {'n':>6} {'method':>13} {'brier0':>7} {'brier1':>7} {'ll0':>6} {'ll1':>6} {'accepted':>8}")
    for (asset, tte), d in sorted(cells.items()):
        n = len(d["p"])
        if n < 100:
            artifact["cells"][f"{asset}:{tte}"] = {"method": "identity", "n": n, "reason": "insufficient_n"}
            print(f"{asset}:{tte:6} {n:6d} {'identity':>13}")
            continue
        k = int(n * 0.6)
        fp, fy = d["p"][:k], d["y"][:k]
        tp, ty = d["p"][k:], d["y"][k:]
        model = _fit_cell(fp, fy, pooled.get(asset))
        pred = [_predict(model, p) for p in tp]
        pred = [max(0.01, min(0.99, x)) for x in pred]
        b0, b1 = _brier(tp, ty), _brier(pred, ty)
        l0, l1 = _logloss(tp, ty), _logloss(pred, ty)
        accept = (b1 < b0) and (l1 <= l0 * 1.02)
        key = f"{asset}:{tte}"
        if accept:
            artifact["cells"][key] = dict(model, n=n, n_test=len(tp),
                                          brier_raw=b0, brier_cal=b1,
                                          logloss_raw=l0, logloss_cal=l1)
        else:
            artifact["cells"][key] = {"method": "identity", "n": n,
                                      "reason": "oos_not_improved",
                                      "brier_raw": b0, "brier_cal": b1}
        print(f"{key:18} {n:6d} {model['method']:>13} {b0:7.4f} {b1:7.4f} {l0:6.4f} {l1:6.4f} {str(accept):>8}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(artifact, f, indent=1)
    print(f"\nwrote {OUT}  cells={len(artifact['cells'])}")


if __name__ == "__main__":
    main()
