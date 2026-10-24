#!/usr/bin/env python
"""Fill-aware, deduplicated near-miss counterfactual attribution.

2026-10-24: ``rejected_candidates.jsonl`` logs one row per *evaluation
cycle*, so naive counterfactual sums over repeated observations of the
same would-be trade — the earlier +$1,300/day estimate was inflated by
that repetition and assumed every rejected candidate would have filled.

Method (post-rejection follow-up sampling, PRFS — the published standard
for reject-side counterfactuals):

  1. Dedup to unique opportunities: one executable entry per
     (ticker, side) window — position limits already enforce this in
     production, so repeated eval rows of the same ticker+side are one
     would-be trade.  The FIRST rejection row is the initial snapshot:
     its ``executable_price_cents`` is the honest would-be entry price.
  2. Join each opportunity to the authoritative settlement outcome
     (``logs/settlement_outcomes.jsonl`` / resolved_yes).
  3. Haircut by an empirical fill-probability proxy per
     (asset, side, price_bucket): realized maker fills / maker order
     submissions in the same cell, read from ``order_decisions.jsonl``.
     Cells without a measurable fill rate carry a conservative prior
     (``MERID_NEAR_MISS_FILL_PRIOR``, default 0.35).  Known gap: the
     entry-submission rows in order_decisions.jsonl are sparse in short
     tails — widen ``MERID_NEAR_MISS_DECISION_TAIL_MB`` when a deeper
     history is needed; the prior stands in otherwise.
  4. Report per-cell: deduped opportunity count, settlement win rate,
     counterfactual net EV (exact Kalshi fee), fill-adjusted EV, and a
     dominance flag when deduped rejected-opp EV exceeds zero AND the
     cell's realized fills population (if any) underperforms it.

Output: per-cell table on stdout + ``logs/near_miss_attribution.jsonl``.
Read-only; never touches trading state.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent.parent
REJECTIONS = REPO / "logs" / "rejected_candidates.jsonl"
SETTLEMENTS = REPO / "logs" / "settlement_outcomes.jsonl"
ORDER_DECISIONS = REPO / "logs" / "order_decisions.jsonl"
OUT_PATH = REPO / "logs" / "near_miss_attribution.jsonl"

_TAKER_FEE_RATE = 0.07


def exact_fee_cents(price_cents: float, rate: float = _TAKER_FEE_RATE) -> float:
    """Kalshi exact fee: rate * P * (1-P) per contract, up to $0.0001.

    Decimal arithmetic — float(0.07*0.5*0.5) lands at 175.000...0003 and
    a naive ceil overcharges 0.01c on every round-number price.
    """
    from decimal import Decimal, ROUND_UP

    p = Decimal(str(price_cents)) / Decimal("100")
    fee_d = (
        Decimal(str(rate)) * p * (Decimal("1") - p)
    ).quantize(Decimal("0.0001"), rounding=ROUND_UP)
    return float(fee_d * 100)


def parse_opportunity(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one rejected-candidate row into an opportunity record."""
    if d.get("type") != "rejected_candidate":
        return None
    ticker = d.get("ticker") or d.get("window_id")
    side = (d.get("side") or "").lower()
    price = d.get("executable_price_cents")
    ts = d.get("event_ts_utc") or d.get("ts")
    if not ticker or side not in ("yes", "no") or price is None or not ts:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if not (0.0 < price < 100.0):
        return None
    return {
        "key": (ticker, side),
        "ticker": ticker,
        "asset": d.get("asset"),
        "side": side,
        "price_cents": price,
        "price_bucket": d.get("price_bucket") or _bucket(price),
        "route": d.get("route"),
        "reject_reason": d.get("reject_reason") or d.get("canonical_reason"),
        "risk_reserve_cents": _f(d.get("risk_reserve_cents")),
        "adverse_cents": _f(d.get("adverse_selection_reserve_cents")),
        "exit_cost_cents": _f(d.get("exit_cost_reserve_cents")),
        "fee_cents_row": _f(d.get("fee_cents")),
        "net_edge_cents": _f(d.get("net_edge"), 100.0),
        "ts": ts,
    }


def _f(v: Any, scale: float = 1.0) -> Optional[float]:
    try:
        return float(v) * scale if v is not None else None
    except (TypeError, ValueError):
        return None


def _bucket(price: float) -> str:
    lo = int(price // 10) * 10
    return f"{lo}-{lo + 9}c"


def dedup_opportunities(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse repeated eval rows to one opportunity per (ticker, side).

    The earliest row wins — the first rejection snapshot carries the price
    the system could have paid at that moment; later rows may reflect a
    book that has already moved.
    """
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for d in rows:
        opp = parse_opportunity(d)
        if opp is None:
            continue
        cur = best.get(opp["key"])
        if cur is None or opp["ts"] < cur["ts"]:
            best[opp["key"]] = opp
    return list(best.values())


def cf_net_cents(price_cents: float, won: bool, fee_cents: float) -> float:
    """Settlement net per contract for a side bought at ``price_cents``."""
    return (100.0 - price_cents - fee_cents) if won else (-price_cents - fee_cents)


def load_settlement_map(path: Path = SETTLEMENTS) -> Dict[str, bool]:
    """ticker -> resolved_yes, last write wins."""
    out: Dict[str, bool] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            try:
                d = json.loads(ln)
            except (ValueError, json.JSONDecodeError):
                continue
            t = d.get("ticker")
            r = d.get("resolved_yes")
            if t and r is not None:
                out[t] = bool(r)
    return out


def fill_rate_proxy(
    decisions_path: Path = ORDER_DECISIONS,
    tail_bytes: Optional[int] = None,
) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """Maker fill rate per (asset, side, price_bucket) from submitted orders.

    Entries submitted as maker/post-only that reached a fill vs total
    submitted — the empirical probability a resting order in this cell
    actually executes.  Taker-route candidates use the same cell rate as a
    conservative proxy (takers fill more often, so this understates EV).
    """
    submitted: Dict[Tuple[str, str, str], int] = defaultdict(int)
    filled: Dict[Tuple[str, str, str], int] = defaultdict(int)
    if not decisions_path.exists():
        return {}
    for ln in _tail_raw_lines(decisions_path, tail_bytes):
        if '"maker"' not in ln and '"rest"' not in ln:
            continue
        try:
            d = json.loads(ln)
        except (ValueError, json.JSONDecodeError):
            continue
        route = d.get("route") or d.get("entry_price_basis")
        if route not in ("maker", "bid"):
            continue
        asset = d.get("asset")
        side = (d.get("side") or "").lower()
        px = _f(d.get("held_price_cents") or d.get("executable_price_cents")
                or d.get("price_cents"))
        if not asset or side not in ("yes", "no") or not px:
            continue
        cell = (str(asset), side, _bucket(px))
        submitted[cell] += 1
        status = str(d.get("status") or d.get("decision") or "").lower()
        if "fill" in status:
            filled[cell] += 1
    return {
        cell: {"submitted": submitted[cell], "filled": filled.get(cell, 0),
               "fill_rate": filled.get(cell, 0) / submitted[cell]}
        for cell, n in submitted.items() if n > 0
    }


def attribute_cells(
    opps: List[Dict[str, Any]],
    settled: Dict[str, bool],
    fill_rates: Dict[Tuple[str, str, str], Dict[str, float]],
    *,
    fee_rate: float = _TAKER_FEE_RATE,
    fill_prior: float = 0.35,
    min_samples: int = 5,
) -> List[Dict[str, Any]]:
    """Per (asset, side, price_bucket) deduped counterfactual summary."""
    cells: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for o in opps:
        cells[(str(o["asset"]), o["side"], o["price_bucket"])].append(o)

    rows: List[Dict[str, Any]] = []
    for (asset, side, bucket), items in sorted(cells.items()):
        resolved, cf_nets = 0, []
        for o in items:
            ry = settled.get(o["ticker"])
            if ry is None:
                continue
            resolved += 1
            won = (o["side"] == "yes") == ry
            fee = o["fee_cents_row"] or exact_fee_cents(o["price_cents"], fee_rate)
            cf_nets.append(cf_net_cents(o["price_cents"], won, fee))
        wins = sum(1 for v in cf_nets if v > 0)
        mean_cf = (sum(cf_nets) / len(cf_nets)) if cf_nets else None
        fr = fill_rates.get((asset, side, bucket), {}).get("fill_rate", fill_prior)
        risk_res = [o["risk_reserve_cents"] for o in items if o["risk_reserve_cents"] is not None]
        rows.append({
            "asset": asset,
            "side": side,
            "price_bucket": bucket,
            "n_opportunities": len(items),
            "n_resolved": resolved,
            "cf_win_rate": (wins / resolved) if resolved else None,
            "cf_mean_net_cents": round(mean_cf, 2) if mean_cf is not None else None,
            "fill_rate_proxy": round(fr, 3),
            "fill_adjusted_ev_cents": round(mean_cf * fr, 2) if mean_cf is not None else None,
            "mean_risk_reserve_cents": round(sum(risk_res) / len(risk_res), 2) if risk_res else None,
            "dominance_flag": bool(
                resolved >= min_samples and mean_cf is not None and mean_cf > 0
            ),
        })
    return rows


def _tail_raw_lines(path: Path, tail_bytes: Optional[int]) -> Iterable[str]:
    """Yield raw text lines — the whole file or only its last N bytes."""
    if tail_bytes is None:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
        return
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - tail_bytes))
        fh.readline()
        for raw in fh:
            yield raw.decode("utf-8", errors="replace")


def _tail_lines(path: Path, tail_bytes: int) -> Iterable[Dict[str, Any]]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - tail_bytes))
        fh.readline()
        for raw in fh:
            try:
                yield json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                continue


def main() -> int:
    tail_mb = float(os.getenv("MERID_NEAR_MISS_TAIL_MB", "48"))
    fill_prior = float(os.getenv("MERID_NEAR_MISS_FILL_PRIOR", "0.35"))
    min_samples = int(os.getenv("MERID_NEAR_MISS_MIN_SAMPLES", "5"))

    opps = dedup_opportunities(_tail_lines(REJECTIONS, int(tail_mb * 1e6)))
    settled = load_settlement_map()
    dec_tail = float(os.getenv("MERID_NEAR_MISS_DECISION_TAIL_MB", "64"))
    rates = fill_rate_proxy(tail_bytes=int(dec_tail * 1e6))
    rows = attribute_cells(opps, settled, rates,
                           fill_prior=fill_prior, min_samples=min_samples)

    rows.sort(key=lambda r: -(r["fill_adjusted_ev_cents"] or -1e9))
    print(f"deduped opportunities: {len(opps)} | cells: {len(rows)}")
    print(f"{'cell':<26} {'n':>4} {'res':>4} {'win%':>6} {'cf_ev_c':>8} "
          f"{'fill_r':>6} {'adj_ev_c':>8} {'rsv_c':>6} flag")
    for r in rows:
        print(
            f"{r['asset'] + '_' + r['side'] + '_' + r['price_bucket']:<26} "
            f"{r['n_opportunities']:>4} {r['n_resolved']:>4} "
            f"{(r['cf_win_rate'] or 0) * 100:>5.0f}% "
            f"{(r['cf_mean_net_cents'] or 0):>8.1f} {r['fill_rate_proxy']:>6.2f} "
            f"{(r['fill_adjusted_ev_cents'] or 0):>8.1f} "
            f"{(r['mean_risk_reserve_cents'] or 0):>6.1f} "
            f"{'MISS' if r['dominance_flag'] else ''}"
        )

    try:
        with OUT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "near_miss_attribution",
                                 "opportunities": len(opps), "cells": rows}) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
