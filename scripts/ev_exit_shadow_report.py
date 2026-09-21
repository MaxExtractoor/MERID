"""EV-exit shadow replay report.

Joins ``logs/exit_evaluations.jsonl`` (evaluations + legacy-outcome
annotations) to ``logs/exit_counterfactuals.jsonl`` (settlement outcomes)
by canonical ``market_pk`` and prints the promotion table used to decide
whether the settlement-aligned EV gate may advance to a narrow canary.

A discretionary exit policy only "wins" if it improves post-cost,
settlement-aware outcomes — not if it merely sells more positions.

Usage:
    python scripts/ev_exit_shadow_report.py [--logs-dir logs] [--asset BTC]
        [--reason stop_loss] [--csv]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SELL = "SELL_SIGNALLED"
HOLD_DECISIONS = {
    "HOLD_SELL_VALUE_INFERIOR",
    "HOLD_PERSISTENCE_NOT_MET",
    "HOLD_OUTSIDE_CANARY_SCOPE",
}
INSUFFICIENT = "HOLD_DATA_INSUFFICIENT"
NEAR_SETTLE = "HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED"
UNKNOWN = "BLOCK_UNKNOWN_REASON"
BYPASS_OP = "BYPASS_OPERATIONAL"
BYPASS_EM = "BYPASS_EMERGENCY"

PRICE_BUCKETS = [(0, 10), (10, 25), (25, 50), (50, 75), (75, 90), (90, 101)]


def _f(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return float(statistics.median(vals)) if vals else None


def _bucket(price_cents: Optional[float]) -> str:
    if price_cents is None:
        return "unknown"
    for lo, hi in PRICE_BUCKETS:
        if lo <= price_cents < hi:
            return f"{lo}-{hi if hi <= 100 else 100}c"
    return "unknown"


def _asset(market_key: str, eval_asset: str = "") -> str:
    if eval_asset:
        return eval_asset.upper()
    series = str(market_key or "").split("-")[0].upper()
    m = re.match(r"KX([A-Z]+?)15M", series)
    if m:
        return m.group(1)
    m = re.match(r"KX([A-Z]+)", series)
    return m.group(1) if m else "UNKNOWN"


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _load_evaluations(path: Path) -> List[Dict[str, Any]]:
    """Eval rows with legacy_outcome annotations folded onto them."""
    evals: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in _load_jsonl(path):
        rtype = row.get("record_type", "evaluation")
        if rtype == "legacy_outcome":
            ev = by_id.get(row.get("evaluation_id"))
            if ev is not None:
                ev["legacy_would_approve"] = row.get("legacy_would_approve")
            continue
        evals.append(row)
        eid = row.get("evaluation_id")
        if eid:
            by_id[eid] = row
    return evals


def _settled_outcome(cf: Dict[str, Any]) -> Optional[float]:
    """1.0 when the held side settled at $1, else 0.0; None if unknown."""
    side = str(cf.get("held_side") or "").lower()
    outcome = str(cf.get("settlement_outcome") or "").lower()
    if side in ("yes", "no") and outcome in ("yes", "no"):
        return 1.0 if side == outcome else 0.0
    price = _f(cf.get("settlement_price_cents"))
    if price is not None:
        return 1.0 if price >= 99.5 else 0.0
    return None


def _brier_ece(pairs: List[Tuple[float, float]]) -> Tuple[Optional[float], Optional[float]]:
    """(brier, ece) over (p_calibrated_0_1, outcome_0_1) pairs."""
    pts = [(p, o) for p, o in pairs if p is not None and o is not None]
    if not pts:
        return None, None
    brier = sum((p - o) ** 2 for p, o in pts) / len(pts)
    buckets: Dict[int, List[Tuple[float, float]]] = defaultdict(list)
    for p, o in pts:
        buckets[min(9, int(p * 10))].append((p, o))
    ece = sum(
        (len(v) / len(pts))
        * abs(sum(p for p, _ in v) / len(v) - sum(o for _, o in v) / len(v))
        for v in buckets.values()
    )
    return brier, ece


def _fmt(v: Optional[float], nd: int = 2) -> str:
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--asset", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    logs = Path(args.logs_dir)
    evals = _load_evaluations(logs / "exit_evaluations.jsonl")
    cfs = _load_jsonl(logs / "exit_counterfactuals.jsonl")
    cf_by_market: Dict[str, Dict[str, Any]] = {}
    for cf in cfs:
        cf_by_market[str(cf.get("market_pk") or "")] = cf

    if not evals:
        print("No exit evaluations found — shadow window has no data yet.")
        return 0

    if args.asset:
        evals = [e for e in evals if _asset(e.get("market_key", ""), e.get("asset", "")) == args.asset.upper()]
    if args.reason:
        evals = [e for e in evals if e.get("canonical_reason") == args.reason]

    # Segment: (asset, held_side, reason, price_bucket, rti_phase)
    segments: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for e in evals:
        price = _f(e.get("bid_cents"))
        if price is None:
            price = _f(e.get("p_held_calibrated_cents"))
        key = (
            _asset(e.get("market_key", ""), e.get("asset", "")),
            str(e.get("held_side") or "?"),
            str(e.get("canonical_reason") or "?"),
            _bucket(price),
            str(e.get("rti_phase") or "unknown"),
        )
        segments[key].append(e)

    header = [
        "asset", "side", "reason", "price_bucket", "rti_phase",
        "evals", "legacy_appr", "ev_sell", "ev_hold", "insuff", "near_settle",
        "net_sell_c", "cons_hold_c", "legacy_pnl_c", "hold_pnl_c",
        "oppty_cost_c", "win_rate", "brier", "ece",
        "book_age_ms", "rti_age_ms", "insuff_rate",
    ]
    rows: List[List[str]] = []

    for key in sorted(segments):
        rows_e = segments[key]
        n = len(rows_e)
        n_legacy = sum(1 for e in rows_e if e.get("legacy_would_approve") is True)
        n_sell = sum(1 for e in rows_e if e.get("decision") == SELL)
        n_hold = sum(1 for e in rows_e if e.get("decision") in HOLD_DECISIONS)
        n_insuff = sum(1 for e in rows_e if e.get("decision") == INSUFFICIENT)
        n_near = sum(1 for e in rows_e if e.get("decision") == NEAR_SETTLE)

        net_sell = [_f(e.get("net_sell_value_cents")) for e in rows_e]
        cons_hold = [_f(e.get("conservative_hold_cents")) for e in rows_e]

        # Join to settlement counterfactuals for realized/counterfactual P&L
        legacy_pnls: List[float] = []
        hold_pnls: List[float] = []
        outcomes: List[float] = []
        cal_pairs: List[Tuple[float, float]] = []
        for e in rows_e:
            cf = cf_by_market.get(str(e.get("market_key") or ""))
            if cf is None:
                continue
            outcome = _settled_outcome(cf)
            actual = _f(cf.get("actual_pnl_cents"))
            hold = _f(cf.get("hold_to_settlement_pnl_cents"))
            if actual is not None:
                legacy_pnls.append(actual)
            if hold is not None:
                hold_pnls.append(hold)
            if outcome is not None:
                outcomes.append(outcome)
                p = _f(e.get("p_held_calibrated_cents"))
                if p is None:
                    p = _f(e.get("model_prob_cents"))
                if p is not None:
                    cal_pairs.append((p / 100.0, outcome))

        # Exit opportunity cost: per settled market, what holding would have
        # earned beyond what the (shadowed or actual) exit produced.
        oppty: List[float] = []
        seg_markets = {e.get("market_key") for e in rows_e}
        for mkey in seg_markets:
            cf = cf_by_market.get(str(mkey or ""))
            if cf is None:
                continue
            delta = _f(cf.get("counterfactual_delta_cents"))
            if delta is not None:
                oppty.append(delta)

        win = sum(outcomes) / len(outcomes) if outcomes else None
        brier, ece = _brier_ece(cal_pairs)
        book_age = _median([_f(e.get("quote_age_ms")) for e in rows_e])
        rti_age = _median([_f(e.get("rti_age_ms")) for e in rows_e])

        rows.append([
            key[0], key[1], key[2], key[3], key[4],
            str(n), str(n_legacy), str(n_sell), str(n_hold), str(n_insuff), str(n_near),
            _fmt(statistics.mean([v for v in net_sell if v is not None]) if any(v is not None for v in net_sell) else None),
            _fmt(statistics.mean([v for v in cons_hold if v is not None]) if any(v is not None for v in cons_hold) else None),
            _fmt(statistics.mean(legacy_pnls) if legacy_pnls else None),
            _fmt(statistics.mean(hold_pnls) if hold_pnls else None),
            _fmt(statistics.mean(oppty) if oppty else None),
            f"{win * 100:.1f}%" if win is not None else "-",
            _fmt(brier, 4), _fmt(ece, 4),
            _fmt(book_age, 0), _fmt(rti_age, 0),
            _fmt(n_insuff / n * 100, 1),
        ])

    if args.csv:
        print(",".join(header))
        for r in rows:
            print(",".join(r))
    else:
        widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
        print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
        print("  ".join("-" * w for w in widths))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(header))))

    # Global rollup
    n = len(evals)
    settled = len(cf_by_market)
    print(f"\nGLOBAL evals={n} settled_markets={settled} "
          f"sell={sum(1 for e in evals if e.get('decision') == SELL)} "
          f"hold={sum(1 for e in evals if e.get('decision') in HOLD_DECISIONS)} "
          f"insufficient={sum(1 for e in evals if e.get('decision') == INSUFFICIENT)} "
          f"near_settle={sum(1 for e in evals if e.get('decision') == NEAR_SETTLE)} "
          f"unknown={sum(1 for e in evals if e.get('decision') == UNKNOWN)} "
          f"bypass_op={sum(1 for e in evals if e.get('decision') == BYPASS_OP)} "
          f"bypass_em={sum(1 for e in evals if e.get('decision') == BYPASS_EM)} "
          f"legacy_approved={sum(1 for e in evals if e.get('legacy_would_approve') is True)}")

    # Top blocker reasons
    blockers: Dict[str, int] = defaultdict(int)
    for e in evals:
        if e.get("decision") == INSUFFICIENT:
            for b in str(e.get("detail") or "").split(";"):
                if b:
                    blockers[b.split(":")[0]] += 1
    if blockers:
        print("BLOCKERS " + " ".join(f"{k}={v}" for k, v in sorted(blockers.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
