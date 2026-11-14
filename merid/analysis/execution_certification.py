"""Independent certification of the execution accounting (P0).

Rebuilds net cash per market WITHOUT ``_compute_signed_fill_proceeds`` or
``_prior_signed_yes_cc``.  The independent path implements the exchange's
position-netting economics from first principles:

    acquiring YES (yes_delta > 0):
        cash = no_price * covered_no  -  yes_price * minted_yes  -  fee
    acquiring NO  (yes_delta < 0):
        cash = yes_price * covered_yes -  no_price * minted_no   -  fee

where ``covered`` closes an existing opposite-side position at the market
leg price and ``minted`` opens new exposure at the market leg price.  This
is algebraically the pair-netting identity (YES+NO=$1) but is implemented
independently of the production helper — agreement is evidence, not
assumption.

Also reports:
  * per-fill divergence stored-proceeds vs independent rebuild;
  * order-invariance: rebuild under shuffled ingestion orders;
  * ordering ambiguity (identical created_time within a market);
  * fee-field vs proceeds-embedded fee reconciliation;
  * live vs non-live split.

CLI::

    py -3 -m merid.analysis.execution_certification \
        --fills-db data/kalshi_fills.db \
        --outcomes logs/settlement_outcomes.jsonl \
        --out reports/execution_certification_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CC = 100.0


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def _ts(s: Optional[str]) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def load_settlements(path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("event_type") == "settlement_outcome" and r.get("ticker"):
                prev = out.get(r["ticker"])
                if prev is None or (r.get("observed_at_utc") or "") >= (
                        prev.get("observed_at_utc") or ""):
                    out[r["ticker"]] = r
    return out


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def independent_fill_cash(
    pos_yes_contracts: float,
    yes_delta_contracts: float,
    yes_price: float,
    no_price: float,
    fee: float,
) -> Tuple[float, float]:
    """(cash, new_pos) under the independent position-netting rule.

    ``pos_yes_contracts`` is signed YES exposure before the fill
    (positive = long YES, negative = long NO).  ``yes_delta_contracts`` is
    the signed YES change.  Returns exchange cash (positive = received,
    net of fee) and the new position.
    """
    d = yes_delta_contracts
    p = pos_yes_contracts
    if d > 0:
        covered = min(max(-p, 0.0), d)
        minted = d - covered
        cash = no_price * covered - yes_price * minted - fee
    elif d < 0:
        covered = min(max(p, 0.0), -d)
        minted = (-d) - covered
        cash = yes_price * covered - no_price * minted - fee
    else:
        cash = -fee
        minted = covered = 0.0
    return cash, p + d


def rebuild_market(
    fills: List[Dict[str, Any]],
    *,
    order: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Rebuild one market's cash/inventory under a given fill order.

    ``order`` permutes fill indices (default: stored order).  Returns per-
    fill independent cash plus totals.  Does NOT read proceeds_dollars.
    """
    idx = order if order is not None else list(range(len(fills)))
    pos = 0.0
    cash = 0.0
    fees = 0.0
    per_fill: List[Dict[str, Any]] = []
    for i in idx:
        f = fills[i]
        ycc = _f(f.get("canonical_yes_delta_cc")) / CC
        yp = _f(f.get("yes_price_dollars"))
        np_ = _f(f.get("no_price_dollars"))
        if np_ == 0.0 and yp > 0.0:
            np_ = 1.0 - yp
        fee = _f(f.get("fee_cost"))
        c, pos = independent_fill_cash(pos, ycc, yp, np_, fee)
        cash += c
        fees += fee
        per_fill.append({
            "i": i, "fill_id": f.get("fill_id"),
            "cash": round(c, 6), "pos_after": round(pos, 4),
            "stored_proceeds": _f(f.get("proceeds_dollars")),
        })
    return {"cash": cash, "fees": fees, "final_pos": pos,
            "per_fill": per_fill}


def settlement_payout(pos_contracts: float, resolved_yes: Optional[int]) -> float:
    if resolved_yes not in (0, 1):
        return 0.0
    if pos_contracts > 0:
        return pos_contracts * float(resolved_yes)
    if pos_contracts < 0:
        return (-pos_contracts) * (1.0 - float(resolved_yes))
    return 0.0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fills-db", default="data/kalshi_fills.db")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument("--shuffles", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20261114)
    args = ap.parse_args(argv)

    conn = _ro(args.fills_db)
    q = ("SELECT fill_id, market_ticker, action, side, execution_action, "
         "execution_outcome_side, canonical_yes_delta_cc, yes_price_dollars, "
         "no_price_dollars, count_fp, quantity_cc, fee_cost, proceeds_dollars, "
         "created_time, entry_or_exit, is_live, side_conflict, unmatched "
         "FROM kalshi_fills")
    if args.live_only:
        q += " WHERE is_live = 1"
    cols = [d[0] for d in conn.execute(q + " LIMIT 0").description]
    rows = [dict(zip(cols, r)) for r in conn.execute(q)]
    conn.close()

    # Settlement bookkeeping rows (fill_id 'settlement:...') are synthetic
    # position-close mirrors written by the ledger — they carry no proceeds
    # and their yes_delta would phantom-close residual positions.  Real
    # settlement cash is added separately via resolved_yes payout.
    n_settle_rows = sum(
        1 for r in rows if str(r.get("fill_id") or "").startswith("settlement:"))
    rows = [r for r in rows
            if not str(r.get("fill_id") or "").startswith("settlement:")]
    print(f"[cert] excluded {n_settle_rows} settlement bookkeeping rows")

    settlements = load_settlements(args.outcomes)

    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["market_ticker"]].append(r)

    rng = random.Random(args.seed)
    report_markets: List[Dict[str, Any]] = []
    totals = {
        "stored_net": 0.0, "indep_net": 0.0, "payout": 0.0,
        "n_markets": 0, "n_live_markets": 0,
        "per_fill_divergences": 0, "max_abs_per_fill_div": 0.0,
        "order_ambiguous_markets": 0,
        "shuffle_max_net_spread": 0.0,
    }
    live_totals = dict(totals)

    for tk, flist in sorted(by_ticker.items()):
        # Authoritative order: exchange created_time, fill_id tiebreak.
        flist.sort(key=lambda f: (_ts(f.get("created_time")),
                                  f.get("fill_id") or ""))
        # ordering ambiguity: identical timestamps within market
        ts_list = [_ts(f.get("created_time")) for f in flist]
        ambiguous = len(set(ts_list)) != len(ts_list)

        rebuild = rebuild_market(flist)
        settle = settlements.get(tk) or {}
        ry = settle.get("resolved_yes")
        ry = int(ry) if ry in (0, 1) else None
        payout = settlement_payout(rebuild["final_pos"], ry)
        stored_cash = sum(_f(f.get("proceeds_dollars")) for f in flist)
        indep_net = rebuild["cash"] + payout
        stored_net = stored_cash + payout

        # per-fill divergence stored vs independent
        max_div = 0.0
        n_div = 0
        for pf in rebuild["per_fill"]:
            div = abs(pf["cash"] - pf["stored_proceeds"])
            if div > 0.005:  # >0.5c
                n_div += 1
                max_div = max(max_div, div)

        # order-invariance: shuffled rebuilds (same fill multiset)
        spread = 0.0
        if len(flist) > 1:
            nets = []
            for _ in range(args.shuffles):
                perm = list(range(len(flist)))
                rng.shuffle(perm)
                rb = rebuild_market(flist, order=perm)
                nets.append(rb["cash"] + settlement_payout(
                    rb["final_pos"], ry))
            spread = max(nets) - min(nets) if nets else 0.0

        is_live = any(f.get("is_live") for f in flist)
        rec = {
            "ticker": tk, "n_fills": len(flist), "is_live": is_live,
            "resolved_yes": ry,
            "final_pos_contracts": round(rebuild["final_pos"], 4),
            "stored_cash": round(stored_cash, 4),
            "indep_cash": round(rebuild["cash"], 4),
            "cash_divergence": round(rebuild["cash"] - stored_cash, 4),
            "payout": round(payout, 4),
            "stored_net": round(stored_net, 4),
            "indep_net": round(indep_net, 4),
            "net_divergence": round(indep_net - stored_net, 4),
            "per_fill_divergences": n_div,
            "max_abs_per_fill_div": round(max_div, 4),
            "order_ambiguous": ambiguous,
            "shuffle_net_spread": round(spread, 4),
            "fees_field_total": round(rebuild["fees"], 4),
        }
        report_markets.append(rec)
        for tgt, live in ((totals, False), (live_totals, True)):
            if live and not is_live:
                continue
            tgt["stored_net"] += stored_net
            tgt["indep_net"] += indep_net
            tgt["payout"] += payout
            tgt["n_markets"] += 1
            tgt["n_live_markets"] += int(is_live)
            tgt["per_fill_divergences"] += n_div
            tgt["max_abs_per_fill_div"] = max(
                tgt["max_abs_per_fill_div"], max_div)
            tgt["order_ambiguous_markets"] += int(ambiguous)
            tgt["shuffle_max_net_spread"] = max(
                tgt["shuffle_max_net_spread"], spread)

    def _clean(d):
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in d.items()}

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fills_db": args.fills_db, "live_only": bool(args.live_only),
        "shuffles": args.shuffles, "seed": args.seed,
        "method": {
            "independent_rule": "position-netting: covered closes opposite "
                                "leg at market price; minted opens at market "
                                "leg price; fee subtracted once",
            "order": "created_time asc, fill_id tiebreak",
            "proceeds_dollars": "stored production field (position-aware, "
                                "net of fee) used only for comparison",
        },
        "all_records": _clean(totals),
        "live_records": _clean(live_totals),
        "markets": report_markets,
    }
    text = json.dumps(out, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    for name, t in (("all", totals), ("live", live_totals)):
        print(f"[{name}] markets={t['n_markets']} "
              f"stored_net={t['stored_net']:+.2f} "
              f"indep_net={t['indep_net']:+.2f} "
              f"divergence={t['indep_net']-t['stored_net']:+.4f} "
              f"fill_divs={t['per_fill_divergences']} "
              f"max_div={t['max_abs_per_fill_div']:.3f} "
              f"ambig={t['order_ambiguous_markets']} "
              f"shuffle_spread={t['shuffle_max_net_spread']:.3f}")
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
