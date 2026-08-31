"""Join rejected candidates to realized settlement outcomes and classify them.

Reads ``logs/rejected_candidates.jsonl`` (emitted by
``merid/prediction/rejection_counterfactual.py``) and
``logs/settlement_outcomes.jsonl``, then for each rejected candidate computes
the counterfactual P&L of having taken the trade:

- If the held side resolved:  gross = 100 - held_price_cents per contract
- Otherwise:                  gross = -held_price_cents per contract
- Net subtracts the recorded entry fee (default ~1.5c when missing).

Classification is always **net of cost** (gross minus entry fee, ~1.5c when
the fee was not recorded): a rejected trade that would have won by less than
its fee is ``saved``, not ``missed``.

- ``missed``         net counterfactual P&L > +1c (wrong rejection)
- ``saved``          net counterfactual P&L < -1c (correct rejection)
- ``flat``           within +/-1c
- ``unclassifiable`` no settlement outcome for the ticker yet (reported
  separately, never folded into saved/missed - a growing bucket biases the split)

Aggregations: rejection gate, held-price bucket, TTE bucket, and
**shortfall band** - how far below the gate the candidate fell (edge gates:
threshold - net_edge in cents; pi*/cost-basis gates: shortfall in probability
points x100).  The rejected set is NOT a random sample: it is everything that
failed the gate, so a high overall missed rate does not justify moving a
threshold.  The decision-relevant slice is the marginal band just below the
threshold (0-1c): evidence to loosen a threshold = the just-below band being
net profitable with confidence, concentrated in a specific price/TTE bucket.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\rejection_counterfactual_report.py
    .\\.venv\\Scripts\\python.exe scripts\\rejection_counterfactual_report.py --min-age-min 30
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_FLAT_EPS_CENTS = 1.0
_DEFAULT_FEE_CENTS = 1.5


def _load_jsonl(path: str):
    if not os.path.exists(path):
        return
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _price_bucket(cents: Optional[float]) -> str:
    if cents is None:
        return "unknown"
    lo = int(cents // 10) * 10
    return f"{lo:02d}-{lo + 9:02d}c"


def _tte_bucket(secs: Optional[float]) -> str:
    if secs is None:
        return "unknown"
    if secs < 180:
        return "<3m"
    if secs < 420:
        return "3-7m"
    if secs < 720:
        return "7-12m"
    return "12-15m"


def _shortfall(d: Dict[str, Any]) -> Optional[float]:
    """How far below the gate the candidate fell, in cents-comparable units.

    Edge gates: (edge_threshold - net_edge) * 100 -> cents of net edge short.
    pi* / cost-basis gates: (pi_star or min_p_selected - model_p) * 100 ->
    probability points short (1 point ~ 1c of break-even probability).
    """
    reason = d.get("reject_reason") or ""
    net_edge = d.get("net_edge")
    threshold = d.get("edge_threshold")
    p = d.get("model_p_selected")
    if net_edge is not None and threshold is not None and "edge_below_threshold" in reason:
        return max(0.0, (float(threshold) - float(net_edge)) * 100.0)
    if p is not None and d.get("pi_star") is not None and reason.startswith("p_selected_below_pi_star"):
        return max(0.0, (float(d["pi_star"]) - float(p)) * 100.0)
    if p is not None and d.get("min_p_selected") is not None and reason.startswith("cost_basis_override"):
        return max(0.0, (float(d["min_p_selected"]) - float(p)) * 100.0)
    return None


def _shortfall_band(shortfall: Optional[float]) -> str:
    if shortfall is None:
        return "n/a"
    if shortfall <= 1.0:
        return "0-1c (marginal)"
    if shortfall <= 2.0:
        return "1-2c"
    if shortfall <= 3.0:
        return "2-3c"
    return "3c+"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rejection counterfactual report")
    ap.add_argument("--candidates", default=os.path.join("logs", "rejected_candidates.jsonl"))
    ap.add_argument("--outcomes", default=os.path.join("logs", "settlement_outcomes.jsonl"))
    ap.add_argument(
        "--min-age-min",
        type=float,
        default=0.0,
        help="Skip candidates newer than this many minutes (market may not have settled)",
    )
    args = ap.parse_args()

    # ticker -> outcome ("yes"/"no")
    outcomes: Dict[str, str] = {}
    for d in _load_jsonl(args.outcomes):
        if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
            outcomes[d["ticker"]] = str(d["outcome"]).lower()

    now = datetime.now(timezone.utc)
    by_reason: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_price_bucket: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_tte_bucket: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_shortfall: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pnl_by_price: Dict[str, float] = collections.defaultdict(float)
    pnl_by_shortfall: Dict[str, float] = collections.defaultdict(float)
    n_by_shortfall: Dict[str, int] = collections.defaultdict(int)
    total = 0
    classified = 0
    total_cf_net_cents = 0.0

    for d in _load_jsonl(args.candidates):
        if d.get("type") != "rejected_candidate":
            continue
        if args.min_age_min > 0 and d.get("event_ts_utc"):
            try:
                ts = datetime.fromisoformat(str(d["event_ts_utc"]).replace("Z", "+00:00"))
                if (now - ts).total_seconds() < args.min_age_min * 60:
                    continue
            except Exception:
                pass
        total += 1
        ticker = d.get("ticker")
        side = (d.get("side") or "").lower()
        held = d.get("held_price_cents")
        fee = d.get("fee_cents") or _DEFAULT_FEE_CENTS

        if not ticker or side not in ("yes", "no") or held is None or ticker not in outcomes:
            label = "unclassifiable"
            cf_net = None
        else:
            won = outcomes[ticker] == side
            gross = (100.0 - float(held)) if won else -float(held)
            cf_net = gross - float(fee)
            if cf_net > _FLAT_EPS_CENTS:
                label = "missed"
            elif cf_net < -_FLAT_EPS_CENTS:
                label = "saved"
            else:
                label = "flat"
            classified += 1
            total_cf_net_cents += cf_net
            pnl_by_price[_price_bucket(held)] += cf_net
            band = _shortfall_band(_shortfall(d))
            pnl_by_shortfall[band] += cf_net
            n_by_shortfall[band] += 1

        by_reason[(d.get("reject_reason") or "unknown").split(":")[0]][label] += 1
        by_price_bucket[_price_bucket(held)][label] += 1
        by_tte_bucket[_tte_bucket(d.get("tte_seconds"))][label] += 1
        by_shortfall[_shortfall_band(_shortfall(d))][label] += 1

    def _render(counter_map, title):
        print(f"\n== {title} ==")
        print(f"{'key':<28} {'saved':>6} {'missed':>6} {'flat':>6} {'unclass':>8}")
        for key in sorted(counter_map):
            c = counter_map[key]
            print(
                f"{key:<28} {c.get('saved', 0):>6} {c.get('missed', 0):>6} "
                f"{c.get('flat', 0):>6} {c.get('unclassifiable', 0):>8}"
            )

    print(f"Rejected candidates: {total}  (classified: {classified})")
    if classified:
        print(
            f"Counterfactual net P&L if ALL rejected trades had been taken: "
            f"{total_cf_net_cents:+.1f}c total, {total_cf_net_cents / classified:+.2f}c/trade"
        )
    _render(by_reason, "By rejection gate")
    _render(by_price_bucket, "By held-price bucket")
    _render(by_tte_bucket, "By time-to-expiry bucket")

    band_order = ["0-1c (marginal)", "1-2c", "2-3c", "3c+", "n/a"]
    _render(
        {k: by_shortfall[k] for k in band_order if k in by_shortfall},
        "By shortfall band (distance below gate)",
    )

    print("\n== Marginal-band net counterfactual P&L (classified candidates only) ==")
    print(f"{'band':<18} {'n':>6} {'net_cents_total':>16} {'net_cents/trade':>16}")
    for band in band_order:
        if band not in n_by_shortfall:
            continue
        n = n_by_shortfall[band]
        tot = pnl_by_shortfall[band]
        print(f"{band:<18} {n:>6} {tot:>16.1f} {tot / n:>16.2f}")
    print(
        "\nThreshold-decision rule: only the '0-1c (marginal)' band informs a "
        "threshold move. Loosen a threshold ONLY if that band is net profitable "
        "with adequate n, concentrated in a specific price/TTE bucket. A positive "
        "deep-below band with a negative marginal band is noise, not signal. "
        "The comparison band is what you currently TAKE (executed fills above the "
        "gate); the question is whether the next slice in adds value."
    )

    print("\n== Counterfactual net P&L by price bucket (cents/contract, all classified) ==")
    for key in sorted(pnl_by_price):
        print(f"{key:<10} {pnl_by_price[key]:+8.1f}c")

    print(
        "\nInterpretation: labels are net-of-cost (gross minus entry fee) - a trade "
        "that would have won by less than its fee is 'saved', not 'missed'. A high "
        "'missed' rate across ALL rejected candidates does NOT justify loosening a "
        "threshold (the rejected set is everything that failed the gate); the "
        "decision-relevant evidence is the marginal shortfall band above. "
        "'unclassifiable' is reported separately and never folded into saved/missed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
