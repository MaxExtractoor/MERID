"""Score the model probability against the book and size from proven edge.

2026-10-14 audit: the decision is only as good as p_model.  This report joins
model observations (executable entry price + p_model per ticker/side/TTE
minute) to settled outcomes and answers, out of sample:

  1. Does p_model beat the market price?  (Brier, and the slope of the
     realized residual (won - price) on the claimed edge (p_model - price):
     1.0 = claimed edge fully real, 0 = noise.)
  2. Above which claimed edge does realized edge turn positive net of fee?
  3. Is that stable across chronological halves?
  4. What stake does fractional Kelly support on the LOWER confidence bound
     of the measured edge, at the current bankroll?  (Zero when unproven.)

Sources (first that exists wins, or pass --obs):
  logs/model_calibration_observations.jsonl  (all sides, artifact-independent)
  logs/empirical_cal_observations.jsonl      (legacy; EPC-cell sides only)

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\model_calibration_report.py
  .\\.venv\\Scripts\\python.exe scripts\\model_calibration_report.py --min-edge-c 4 --since 2026-10-14
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts: str) -> str:
    return os.path.join(ROOT, *parts)


def _jsonl(path: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def taker_fee_c(price_c: float) -> float:
    p = price_c / 100.0
    return math.ceil(7.0 * p * (1.0 - p) * 100.0) / 100.0  # 0.07*P*(1-P) in cents, centicent round-up


def load(obs_path: str, outcomes_path: str, since_ts: float, pick: str):
    out = {}
    for r in _jsonl(outcomes_path):
        if "ticker" in r and "resolved_yes" in r:
            out[r["ticker"]] = int(r["resolved_yes"])
    chosen = {}
    for r in _jsonl(obs_path):
        if float(r.get("ts") or 0) < since_ts:
            continue
        tk, side = r.get("ticker"), r.get("side")
        o = out.get(tk)
        px = r.get("entry_price_cents", r.get("held_price_cents"))
        if o is None or side not in ("yes", "no") or px is None or r.get("p_model") is None:
            continue
        key = (tk, side)
        if pick == "first" and key in chosen:
            continue
        won = 1 if (o == 1) == (side == "yes") else 0
        fee = r.get("fee_cents")
        chosen[key] = {
            "ticker": tk, "side": side, "asset": r.get("asset"), "ts": float(r.get("ts") or 0),
            "p": float(r["p_model"]), "px": float(px) / 100.0, "won": won,
            "tte": r.get("seconds_to_expiry"),
            "fee": (float(fee) if fee is not None else taker_fee_c(float(px))) / 100.0,
        }
    return sorted(chosen.values(), key=lambda x: x["ts"])


def mean_se(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else 0.0), float("inf")
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return m, sd / math.sqrt(n)


def latest_bankroll() -> float | None:
    path = _p("logs", "bankroll_reconciliation.jsonl")
    if not os.path.exists(path):
        return None
    last = None
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 65536))
        for line in f.read().decode("utf-8", "ignore").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            v = r.get("fresh_equity_usd", r.get("internal_equity_usd"))
            if v is not None:
                last = float(v)
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs")
    ap.add_argument("--outcomes", default=_p("logs", "settlement_outcomes.jsonl"))
    ap.add_argument("--since", help="YYYY-MM-DD (UTC) lower bound on observation time")
    ap.add_argument("--pick", choices=("first", "last"), default="last",
                    help="observation per ticker/side to score (last = closest to entry decision)")
    ap.add_argument("--min-edge-c", type=float, default=4.0, help="claimed gross edge threshold (cents)")
    ap.add_argument("--maker", action="store_true", help="score net of zero fee (resting entries)")
    ap.add_argument("--kelly-fraction", type=float, default=0.25)
    ap.add_argument("--max-stake-pct", type=float, default=5.0, help="hard per-trade cap, %% of bankroll")
    ap.add_argument("--bankroll", type=float)
    a = ap.parse_args()

    obs = a.obs or next((p for p in (_p("logs", "model_calibration_observations.jsonl"),
                                     _p("logs", "empirical_cal_observations.jsonl")) if os.path.exists(p)), None)
    if not obs:
        print("no observation file found")
        return 1
    since_ts = 0.0
    if a.since:
        since_ts = datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    xs = load(obs, a.outcomes, since_ts, a.pick)
    print(f"source={os.path.relpath(obs, ROOT)} settled ticker-sides={len(xs)} pick={a.pick}")
    if len(xs) < 30:
        print("insufficient settled observations (<30)")
        return 0

    for x in xs:
        x["fee_eff"] = 0.0 if a.maker else x["fee"]
        x["claim"] = x["p"] - x["px"]
        x["net"] = x["won"] - x["px"] - x["fee_eff"]

    n = len(xs)
    b_mkt = sum((x["px"] - x["won"]) ** 2 for x in xs) / n
    b_mod = sum((x["p"] - x["won"]) ** 2 for x in xs) / n
    mx = sum(x["claim"] for x in xs) / n
    my = sum(x["won"] - x["px"] for x in xs) / n
    var = sum((x["claim"] - mx) ** 2 for x in xs)
    beta = sum((x["claim"] - mx) * (x["won"] - x["px"] - my) for x in xs) / var if var else 0.0
    rsd = math.sqrt(sum((x["won"] - x["px"] - my - beta * (x["claim"] - mx)) ** 2 for x in xs) / max(1, n - 2))
    se_b = rsd / math.sqrt(var) if var else float("inf")
    print(f"\n[1] Brier market={b_mkt:.4f} model={b_mod:.4f} ({'model better' if b_mod < b_mkt else 'MARKET better'})")
    print(f"    residual slope beta={beta:.3f} se={se_b:.3f} t={beta / se_b if se_b else 0:.2f}")

    print(f"\n[2] realized net edge by claimed gross edge ({'maker, no fee' if a.maker else 'net of taker fee'})")
    bk = collections.defaultdict(list)
    for x in xs:
        bk[max(-4, min(6, math.floor(x["claim"] * 100 / 2)))].append(x["net"])
    for k in sorted(bk):
        m, se = mean_se(bk[k])
        lo = "<=" if k == -4 else ""
        hi = "+" if k == 6 else ""
        print(f"    claimed {lo}{k * 2:+3d}..{k * 2 + 2:+3d}c{hi:1s} n={len(bk[k]):5d} realized={m * 100:+6.2f}c  se={se * 100:5.2f}c")

    sel = [x for x in xs if x["claim"] * 100 >= a.min_edge_c]
    print(f"\n[3] claimed edge >= {a.min_edge_c:g}c: n={len(sel)}")
    if len(sel) < 20:
        print("    too few selected observations to assess")
        return 0
    h = len(sel) // 2
    for name, part in (("first half", sel[:h]), ("second half", sel[h:])):
        m, se = mean_se([x["net"] for x in part])
        print(f"    {name:11s} n={len(part):4d} realized={m * 100:+6.2f}c se={se * 100:5.2f}c")
    m, se = mean_se([x["net"] for x in sel])
    lcb = m - 1.96 * se
    print(f"    pooled realized={m * 100:+.2f}c  95% LCB={lcb * 100:+.2f}c  t={m / se if se else 0:.2f}")
    by_asset = collections.defaultdict(list)
    for x in sel:
        by_asset[x["asset"]].append(x["net"])
    print("    by asset: " + "  ".join(f"{k}={sum(v) / len(v) * 100:+.1f}c/{len(v)}" for k, v in sorted(by_asset.items())))

    print("\n[4] sizing (fractional Kelly on the edge LOWER bound)")
    bankroll = a.bankroll if a.bankroll is not None else latest_bankroll()
    avg_cost = sum(x["px"] + x["fee_eff"] for x in sel) / len(sel)
    if lcb <= 0:
        print(f"    95% LCB {lcb * 100:+.2f}c <= 0 -> edge NOT proven; Kelly stake = 0. Keep size at the minimum.")
        return 0
    f_star = lcb / (1.0 - avg_cost)  # binary Kelly: (p - c)/(1 - c) with edge = p - c
    f_use = min(a.kelly_fraction * f_star, a.max_stake_pct / 100.0)
    print(f"    avg all-in cost={avg_cost * 100:.1f}c  full-Kelly on LCB={f_star * 100:.2f}% of bankroll  "
          f"x{a.kelly_fraction:g} -> {f_use * 100:.2f}% (cap {a.max_stake_pct:g}%)")
    if bankroll:
        stake = f_use * bankroll
        print(f"    bankroll=${bankroll:.2f} -> per-trade stake ${stake:.2f} (~{stake / avg_cost:.1f} contracts at {avg_cost * 100:.0f}c)")
        print("    The per-trade stake is a ceiling for MERID_FIXED_EXPOSURE_CAP_USD / contracts per order;"
              " re-run as the bankroll and sample grow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
