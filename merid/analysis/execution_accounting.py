"""Actual-execution accounting audit (track 1B).

Reconciles the observed trading record end-to-end:

    orders -> fills -> inventory -> exits/settlements -> fees -> net cash P&L

using ``data/kalshi_fills.db`` (canonicalized trusted fills) joined to
``logs/settlement_outcomes.jsonl`` (official resolved_yes).  This is the
execution-value hypothesis artifact — realized net P&L independently of any
forecast score — and the calibration target for the later taker replay.

Conventions (verified against ``fills_ledger._compute_signed_fill_proceeds``
and the production P&L comment at fills_ledger.py:~4821):
  * ``canonical_yes_delta_cc`` — signed YES centi-contracts per fill.
  * ``proceeds_dollars`` — signed cash the exchange booked, NET OF FEE,
    position-aware (pair-mint/complement netting): positive = received,
    negative = paid.  Already includes ``fee_cost`` — do NOT subtract fees
    again (that double-counts).
  * Settlement payout: residual YES position pays ``resolved_yes`` per
    contract; residual NO position (negative YES delta) pays ``1-resolved_yes``.
    Settlement payouts are NOT present as fills, so they are added here.

CLI::

    py -3 -m merid.analysis.execution_accounting \
        --fills-db data/kalshi_fills.db \
        --outcomes logs/settlement_outcomes.jsonl \
        --out reports/execution_accounting_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CC_PER_CONTRACT = 100.0


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def load_settlements(path: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("event_type") != "settlement_outcome":
                continue
            tk = r.get("ticker")
            if tk and r.get("resolved_yes") in (0, 1):
                # keep the LATEST observation (corrections supersede)
                prev = out.get(tk)
                if prev is None or (
                    r.get("observed_at_utc") or ""
                ) >= (prev.get("observed_at_utc") or ""):
                    out[tk] = r
    return out


def iso(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def audit_fills(
    fills: List[Dict[str, Any]],
    settlements: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for fl in fills:
        by_ticker[fl["market_ticker"]].append(fl)

    contracts: List[Dict[str, Any]] = []
    unresolved_tickers: List[str] = []
    for tk, flist in by_ticker.items():
        flist.sort(key=lambda f: (iso(f.get("created_time")) or 0,
                                  f.get("fill_id") or ""))
        yes_cc = 0
        cash = 0.0
        fees = 0.0
        n_fills = len(flist)
        first_ts = iso(flist[0].get("created_time"))
        last_ts = iso(flist[-1].get("created_time"))
        agents = defaultdict(int)
        roles = defaultdict(int)
        flags = {"unmatched": 0, "reconciled0": 0, "side_conflict": 0,
                 "no_yes_delta": 0}
        max_abs_pos_cc = 0
        for f in flist:
            d = f.get("canonical_yes_delta_cc")
            try:
                d = int(d) if d is not None else 0
            except (TypeError, ValueError):
                d = 0
            yes_cc += d
            max_abs_pos_cc = max(max_abs_pos_cc, abs(yes_cc))
            if d == 0:
                flags["no_yes_delta"] += 1
            try:
                cash += float(f.get("proceeds_dollars") or 0.0)
            except (TypeError, ValueError):
                pass
            try:
                fees += float(f.get("fee_cost") or 0.0)
            except (TypeError, ValueError):
                pass
            if f.get("unmatched"):
                flags["unmatched"] += 1
            if f.get("reconciled") == 0:
                flags["reconciled0"] += 1
            if f.get("side_conflict"):
                flags["side_conflict"] += 1
            agents[f.get("agent_id") or "?"] += 1
            roles[f.get("liquidity_role") or "?"] += 1

        settle = settlements.get(tk)
        resolved = settle.get("resolved_yes") if settle else None
        st_ts = iso(settle.get("settlement_timestamp_utc")) if settle else None
        pos_contracts = yes_cc / CC_PER_CONTRACT
        payout = 0.0
        settled = resolved in (0, 1)
        if settled:
            if pos_contracts > 0:
                payout = pos_contracts * float(resolved)
            elif pos_contracts < 0:
                payout = (-pos_contracts) * (1.0 - float(resolved))
        # proceeds_dollars is already net of fees -> net P&L adds payout only.
        net_pnl = cash + payout
        series = tk.split("-")[0].upper()          # e.g. KXBTC15M
        asset = series[2:].replace("15M", "")      # BTC
        contracts.append({
            "ticker": tk,
            "asset": asset,
            "n_fills": n_fills,
            "first_fill_ts": first_ts, "last_fill_ts": last_ts,
            "final_yes_cc": yes_cc,
            "final_pos_contracts": round(pos_contracts, 4),
            "open_at_end": settled and abs(pos_contracts) > 1e-9,
            "max_abs_pos_contracts": round(max_abs_pos_cc / CC_PER_CONTRACT, 4),
            "cash_dollars": round(cash, 6),
            "fees_dollars_field": round(fees, 6),
            "note_fees_already_in_proceeds": True,
            "settlement_payout_dollars": round(payout, 6),
            "resolved_yes": resolved,
            "settled": settled,
            "net_pnl_dollars": round(net_pnl, 6),
            "net_pnl_cents": round(net_pnl * 100.0, 2),
            "agents": dict(agents), "liquidity_roles": dict(roles),
            "flags": flags,
        })
        if not settled:
            unresolved_tickers.append(tk)

    # ---- aggregates --------------------------------------------------------
    def _agg(rows, keyfn):
        g: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"n_contracts": 0, "fills": 0, "cash": 0.0, "fees_field_total": 0.0,
                     "payout": 0.0, "net_pnl": 0.0, "unsettled": 0})
        for r in rows:
            k = keyfn(r)
            a = g[k]
            a["n_contracts"] += 1
            a["fills"] += r["n_fills"]
            a["cash"] += r["cash_dollars"]
            a["fees_field_total"] += r["fees_dollars_field"]
            a["payout"] += r["settlement_payout_dollars"]
            a["net_pnl"] += r["net_pnl_dollars"]
            a["unsettled"] += 0 if r["settled"] else 1
        return {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                    for kk, vv in v.items()} for k, v in sorted(g.items())}

    settled_rows = [r for r in contracts if r["settled"]]
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fills_db": None,
        "n_fills": len(fills),
        "n_contracts": len(contracts),
        "n_settled_contracts": len(settled_rows),
        "n_unsettled_contracts": len(contracts) - len(settled_rows),
        "unsettled_tickers_sample": sorted(unresolved_tickers)[:50],
        "totals": {
            "cash_dollars": round(sum(r["cash_dollars"] for r in contracts), 4),
            "fees_dollars_field_total": round(sum(r["fees_dollars_field"] for r in contracts), 4),
            "settlement_payout_dollars": round(
                sum(r["settlement_payout_dollars"] for r in contracts), 4),
            "net_pnl_dollars": round(
                sum(r["net_pnl_dollars"] for r in contracts), 4),
            "net_pnl_cents": round(
                sum(r["net_pnl_cents"] for r in contracts), 2),
        },
        "by_asset": _agg(contracts, lambda r: r["asset"]),
        "by_agent": _agg(contracts, lambda r: ",".join(sorted(r["agents"]))),
        "settled_only": {
            "n": len(settled_rows),
            "net_pnl_dollars": round(
                sum(r["net_pnl_dollars"] for r in settled_rows), 4),
        },
        "data_quality": {
            "fills_unmatched_flag": sum(r["flags"]["unmatched"] for r in contracts),
            "fills_reconciled0": sum(r["flags"]["reconciled0"] for r in contracts),
            "fills_side_conflict": sum(r["flags"]["side_conflict"] for r in contracts),
            "fills_no_yes_delta": sum(r["flags"]["no_yes_delta"] for r in contracts),
            "contracts_with_residual_position": sum(
                1 for r in contracts if abs(r["final_pos_contracts"]) > 1e-9),
        },
    }
    return {"summary": summary, "contracts": contracts}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fills-db", default="data/kalshi_fills.db")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live-only", action="store_true",
                    help="restrict to is_live=1 fills (production record)")
    args = ap.parse_args(argv)

    conn = _ro(args.fills_db)
    q = "SELECT * FROM kalshi_fills"
    if args.live_only:
        q += " WHERE is_live = 1"
    cols = [d[0] for d in conn.execute("SELECT * FROM kalshi_fills LIMIT 0").description]
    fills = [dict(zip(cols, row)) for row in conn.execute(q)]
    conn.close()
    # Exclude synthetic settlement bookkeeping rows (no proceeds; their
    # yes_delta would phantom-close residual positions before payout calc).
    n_settle = sum(
        1 for f in fills
        if str(f.get("fill_id") or "").startswith("settlement:"))
    fills = [f for f in fills
             if not str(f.get("fill_id") or "").startswith("settlement:")]
    if n_settle:
        print(f"[accounting] excluded {n_settle} settlement bookkeeping rows")

    settlements = load_settlements(args.outcomes)
    rep = audit_fills(fills, settlements)
    rep["summary"]["fills_db"] = args.fills_db
    rep["summary"]["live_only"] = bool(args.live_only)

    text = json.dumps(rep, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    s = rep["summary"]
    print(f"fills={s['n_fills']} contracts={s['n_contracts']} "
          f"settled={s['n_settled_contracts']} unsettled={s['n_unsettled_contracts']}")
    print(f"totals: cash={s['totals']['cash_dollars']:+.2f} "
          f"fees_field={s['totals']['fees_dollars_field_total']:.2f} "
          f"payout={s['totals']['settlement_payout_dollars']:+.2f} "
          f"NET_PNL={s['totals']['net_pnl_dollars']:+.2f} "
          f"({s['totals']['net_pnl_cents']:+.0f}c)")
    print("by_asset:")
    for a, v in s["by_asset"].items():
        print(f"  {a:<6} n={v['n_contracts']:<4} net={v['net_pnl']:+.2f} "
              f"unsettled={v['unsettled']}")
    print("data_quality:", json.dumps(s["data_quality"]))
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
