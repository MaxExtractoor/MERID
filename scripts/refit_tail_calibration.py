#!/usr/bin/env python
"""Refit data/probability_tail_calibration.json from observed
(ticker, side, held_price) -> settlement pairs, deduplicated to market
granularity.

Data sources (union):
  * logs/rejected_candidates.jsonl — gate-rejected candidates carry
    (ticker, side, held_price_cents); deduped to (ticker, side, 2c bucket).
  * data/kalshi_fills.db entries — first buy fill per (ticker, side).
  * logs/settlement_outcomes.jsonl — ticker -> winning side.

Produces a REAL per-side PAVA fit for both YES-held and NO-held contracts,
replacing the previous dual-mirror NO curve (no_source=yes_dual).  This lets
the settlement-aligned exit evaluator approve justified NO-side salvage exits
(model_inputs_satisfactory clears when the artifact is not dual-provisional).
"""
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")
from merid.risk.probability.tail_calibrator import _pava_isotonic  # noqa: E402

OUT_PATH = "data/probability_tail_calibration.json"
PRICE_FLOOR = 0.05
PRICE_CAP = 0.99
SIDES = ("yes", "no")


def _load_outcomes(path):
    outcomes = {}
    if not os.path.exists(path):
        return outcomes
    with open(path, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event_type") == "settlement_outcome" and d.get("outcome") in SIDES:
                outcomes[d["ticker"]] = d["outcome"]
    return outcomes


def _iter_rejected(path, outcomes):
    """(ticker, side, held_price) deduped to (ticker, side, 2c bucket)."""
    seen = set()
    if not os.path.exists(path):
        return
    with open(path, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "rejected_candidate":
                continue
            tk, side, hp = d.get("ticker"), (d.get("side") or "").lower(), d.get("held_price_cents")
            if side not in SIDES or hp is None or tk not in outcomes:
                continue
            p = float(hp) / 100.0
            if not (PRICE_FLOOR <= p <= PRICE_CAP):
                continue
            key = (tk, side, int(p * 50))
            if key in seen:
                continue
            seen.add(key)
            yield tk, side, p


def _iter_fills(db_path, outcomes):
    """(ticker, side, held_price) — first buy fill per (ticker, side)."""
    if not os.path.exists(db_path):
        return
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT ticker, action, price_cents FROM fills "
            "WHERE action LIKE 'buy%' ORDER BY ts_ms"
        ).fetchall()
    except Exception:
        rows = []
    con.close()
    seen = set()
    for tk, act, cents in rows:
        side = "yes" if "yes" in str(act) else "no"
        if tk not in outcomes or (tk, side) in seen:
            continue
        seen.add((tk, side))
        p = (cents or 0) / 100.0
        if PRICE_FLOOR <= p <= PRICE_CAP:
            yield tk, side, p


def _fit_side(pairs):
    """PAVA on weighted price buckets -> (knot_xs, knot_ys, n_pairs)."""
    by_p = defaultdict(lambda: [0, 0])
    for p, win in pairs:
        b = round(p, 3)
        by_p[b][0] += 1
        by_p[b][1] += int(win)
    xs = sorted(by_p)
    ys = [by_p[x][1] / by_p[x][0] for x in xs]
    ws = [float(by_p[x][0]) for x in xs]
    kx, ky = _pava_isotonic(xs, ys, ws)
    return [round(v, 4) for v in kx], [round(v, 6) for v in ky], len(pairs)


def main():
    outcomes = _load_outcomes("logs/settlement_outcomes.jsonl")
    print(f"settled tickers: {len(outcomes)}")

    obs = list(_iter_rejected("logs/rejected_candidates.jsonl", outcomes))
    obs += list(_iter_fills("data/kalshi_fills.db", outcomes))
    print(f"total deduped observations: {len(obs)}")

    side_pairs = {"yes": [], "no": []}
    markets = set()
    for tk, side, p in obs:
        side_pairs[side].append((p, outcomes[tk] == side))
        markets.add(tk)

    yes_x, yes_y, n_yes = _fit_side(side_pairs["yes"])
    no_x, no_y, n_no = _fit_side(side_pairs["no"])
    n_total = len({(tk, s) for tk, s, _p in obs})

    artifact = {
        "yes_held_prices": yes_x,
        "yes_actual_probs": yes_y,
        "no_held_prices": no_x,
        "no_actual_probs": no_y,
        "buffer": 0.05,
        "n_trades": n_total,
        "metadata": {
            "source": "rejected_candidates+entry_fills vs settlement_outcomes",
            "fit_method": "per_side_pava_isotonic_regression_weighted",
            "held_side": "both",
            "no_source": "no_held_observations",
            "observation_level": "market_dedup_2c_bucket",
            "n_yes": n_yes,
            "n_no": n_no,
            "n_unique_markets": len(markets),
            "fit_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    with open(OUT_PATH, "w") as f:
        json.dump(artifact, f, indent=1)
    print(f"wrote {OUT_PATH}: yes_knots={len(yes_x)} no_knots={len(no_x)} n_total={n_total}")
    for label, kx, ky in (("YES", yes_x, yes_y), ("NO", no_x, no_y)):
        print(f"--- {label} curve (sampled) ---")
        for i in range(0, len(kx), max(1, len(kx) // 12)):
            print(f"  p={kx[i]:.3f} -> wr={ky[i]:.4f}")
        print(f"  p={kx[-1]:.3f} -> wr={ky[-1]:.4f}")


if __name__ == "__main__":
    main()
