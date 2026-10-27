#!/usr/bin/env python3
"""Join pinned-fav maker-shadow records to settlement outcomes.

Reads ``logs/pinned_fav_maker_shadow.jsonl`` (emitted by
``merid/prediction/pinned_fav_maker_shadow.py``, observe-only) and
``logs/settlement_outcomes.jsonl``, then scores what the sub-MAKER_LO
band would have earned had a post-only bid filled at each recorded
own-side bid:

- win:  gross = 100 - entry_price_cents per contract
- loss: gross = -entry_price_cents per contract
- net = gross - maker_fee_est_cents (recorded at emit time)

Two views:

- **eval-level**: every deduplicated record is one observation.
- **episode-level**: one row per (ticker, side, entry cent) keeping the
  LAST record — closest-in-time to settlement, the price most likely
  still resting — so a price parked for 10 minutes does not count 10x.

The decision-relevant slice is ``would_qualify == true`` in the shadow
band below the live floor (``in_live_band == false``): that is the cohort
a lower ``MERID_PINNED_FAV_MAKER_LO`` would actually admit.  The
``in_live_band`` rows are the control arm for the current 90-91c edge.

Promotion evidence = the sub-floor shadow bucket being net-positive with
a bootstrap 95% lower CI above zero AND n >= 30 episodes.  A bucket that
is net-negative with a 95% upper CI below zero is falsification-grade
evidence to keep the floor.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\pinned_fav_maker_shadow_report.py
    .\\.venv\\Scripts\\python.exe scripts\\pinned_fav_maker_shadow_report.py --min-age-min 5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

_SHADOW_PATH = os.path.join("logs", "pinned_fav_maker_shadow.jsonl")
_SETTLE_PATH = os.path.join("logs", "settlement_outcomes.jsonl")
_BOOTSTRAP = 2000
_SEED = 42
_MIN_N = 30


def _load_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    if not os.path.exists(path):
        return
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _settlements(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rec in _load_jsonl(path) or []:
        t = rec.get("ticker") or rec.get("market_ticker")
        oc = rec.get("outcome")
        if t and oc:
            out[str(t)] = str(oc).lower()
    return out


def _pnl_cents(rec: Dict[str, Any], outcome: str) -> Optional[float]:
    side = (rec.get("side") or "").lower()
    px = rec.get("entry_price_cents")
    if side not in ("yes", "no") or px is None:
        return None
    px = float(px)
    fee = rec.get("maker_fee_est_cents")
    fee = float(fee) if fee is not None else 0.0
    gross = (100.0 - px) if outcome == side else -px
    return gross - fee


def _bucket(px: float) -> str:
    p = int(math.floor(px))
    if p <= 84:
        return "<=84c"
    if p <= 87:
        return "85-87c"
    if p <= 89:
        return "88-89c"
    if p <= 91:
        return "90-91c"
    return ">=92c"


def _agg(records: List[float]) -> Dict[str, Any]:
    n = len(records)
    if not n:
        return {"n": 0}
    wins = sum(1 for x in records if x > 0)
    mean = sum(records) / n
    rng = random.Random(_SEED)
    means = sorted(
        sum(rng.choice(records) for _ in range(n)) / n
        for _ in range(_BOOTSTRAP)
    )
    lo_ci = means[int(0.05 * _BOOTSTRAP)]
    hi_ci = means[int(0.95 * _BOOTSTRAP)]
    return {
        "n": n,
        "win_pct": round(100.0 * wins / n, 1),
        "ev_cents": round(mean, 2),
        "ci95_lo": round(lo_ci, 2),
        "ci95_hi": round(hi_ci, 2),
        "verdict": (
            "PROMOTE_EVIDENCE" if (n >= _MIN_N and lo_ci > 0)
            else "FALSIFYING" if (n >= _MIN_N and hi_ci < 0)
            else "INSUFFICIENT"
        ),
    }


def _print_table(title: str, groups: Dict[str, List[float]]) -> None:
    print(f"\n== {title} ==")
    print(f"{'bucket':<24} {'n':>5} {'win%':>6} {'EV/ct':>8} {'CI95lo':>7} {'CI95hi':>7}  verdict")
    for key in sorted(groups):
        s = _agg(groups[key])
        if s["n"] == 0:
            continue
        print(
            f"{key:<24} {s['n']:>5} {s['win_pct']:>5.1f}% "
            f"{s['ev_cents']:>7.2f}c {s['ci95_lo']:>6.2f}c {s['ci95_hi']:>6.2f}c  {s['verdict']}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow", default=_SHADOW_PATH)
    ap.add_argument("--settlements", default=_SETTLE_PATH)
    ap.add_argument("--min-age-min", type=float, default=0.0)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    settle = _settlements(args.settlements)
    now = datetime.now(timezone.utc)

    eval_rows: List[Dict[str, Any]] = []
    unresolved = 0
    for rec in _load_jsonl(args.shadow) or []:
        if rec.get("type") != "pinned_fav_maker_shadow":
            continue
        if rec.get("locked_book"):
            continue  # a post-only bid cannot fill into a locked book
        ticker = rec.get("ticker")
        outcome = settle.get(str(ticker)) if ticker else None
        if not outcome:
            unresolved += 1
            continue
        if args.min_age_min > 0:
            try:
                ts = datetime.fromisoformat(
                    str(rec.get("event_ts_utc", "")).replace("Z", "+00:00")
                )
                if (now - ts).total_seconds() < args.min_age_min * 60:
                    continue
            except Exception:
                pass
        pnl = _pnl_cents(rec, outcome)
        if pnl is None:
            continue
        eval_rows.append({**rec, "cf_pnl_cents": pnl, "outcome": outcome})

    # Episode-level: one row per (ticker, side, entry cent), latest record wins.
    episodes: Dict[tuple, Dict[str, Any]] = {}
    for r in eval_rows:
        key = (
            r.get("ticker"),
            r.get("side"),
            int(round(float(r.get("entry_price_cents") or 0))),
        )
        prev = episodes.get(key)
        if prev is None or str(r.get("event_ts_utc")) > str(prev.get("event_ts_utc")):
            episodes[key] = r
    ep_rows = list(episodes.values())

    def _group(rows: List[Dict[str, Any]], fn) -> Dict[str, List[float]]:
        g: Dict[str, List[float]] = defaultdict(list)
        for r in rows:
            g[fn(r)].append(float(r["cf_pnl_cents"]))
        return g

    print(f"shadow_records_scored={len(eval_rows)} unresolved={unresolved} "
          f"episodes={len(ep_rows)}")

    for label, rows in (("EVAL-LEVEL", eval_rows), ("EPISODE-LEVEL", ep_rows)):
        _print_table(
            f"{label} — price bucket x cohort",
            _group(rows, lambda r: (
                f"{_bucket(float(r['entry_price_cents']))} "
                f"{'live' if r.get('in_live_band') else 'shadow'} "
                f"{'Q' if r.get('would_qualify') else 'x'}"
            )),
        )
        _print_table(
            f"{label} — by asset (would-qualify rows only)",
            _group(
                [r for r in rows if r.get("would_qualify")],
                lambda r: (
                    f"{r.get('asset','?')} "
                    f"{_bucket(float(r['entry_price_cents']))} "
                    f"{'live' if r.get('in_live_band') else 'shadow'}"
                ),
            ),
        )
        _print_table(
            f"{label} — gate-failure decomposition (shadow band only)",
            _group(
                [r for r in rows if not r.get("in_live_band")],
                lambda r: "WOULD_QUALIFY" if r.get("would_qualify") else (
                    "blocked:" + ",".join(
                        g for g in (
                            "tte" if not r.get("gate_tte_pass") else "",
                            "pin" if not r.get("gate_min_p_pass") else "",
                            "ev" if not r.get("gate_min_ev_pass") else "",
                            "moneyness" if not r.get("gate_moneyness_pass") else "",
                            "dailycap" if not r.get("gate_daily_cap_pass") else "",
                        ) if g
                    )
                ),
            ),
        )

    if args.json_out:
        summary = {
            "scored": len(eval_rows),
            "unresolved": unresolved,
            "episodes": len(ep_rows),
            "by_bucket": {
                k: _agg(v)
                for k, v in _group(
                    ep_rows,
                    lambda r: (
                        f"{_bucket(float(r['entry_price_cents']))} "
                        f"{'live' if r.get('in_live_band') else 'shadow'} "
                        f"{'Q' if r.get('would_qualify') else 'x'}"
                    ),
                ).items()
            },
        }
        with open(args.json_out, "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
