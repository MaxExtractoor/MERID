"""Fetch Kalshi historical order records for flagged execution episodes.

Resolves the IOC-exit limit-leg ambiguity flagged by
``merid.analysis.execution_consistency``: ``GET /historical/orders`` returns
canceled/fully-executed orders older than the live cutoff, including the
exchange-side ``yes_price``/``no_price`` actually submitted — the field the
local attempt store does not record for exits.

Read-only; writes a JSONL of matched order records.

    py -3 scripts/fetch_historical_orders.py \
        --report reports/execution_consistency_2026-11-14.json \
        --out reports/historical_orders_2026-11-14.jsonl
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from rti_backfill import _load_env, _signer  # noqa: E402

BASE = "https://external-api.kalshi.com"
# Kalshi signs timestamp+METHOD+full-path-including-/trade-api/v2
SIGN_PREFIX = "/trade-api/v2"


def _get(sign, path: str) -> dict:
    """path is the endpoint path WITHOUT the /trade-api/v2 prefix."""
    full = SIGN_PREFIX + path
    url = BASE + full
    req = urllib.request.Request(url, headers=sign("GET", full))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_orders_for_ticker(sign, ticker: str) -> list[dict]:
    """Page through /historical/orders for one ticker (all statuses)."""
    out = []
    cursor = None
    for _ in range(50):  # safety bound
        path = (f"/historical/orders?ticker={ticker}&limit=200"
                + (f"&cursor={cursor}" if cursor else ""))
        try:
            data = _get(sign, path)
        except Exception as e:
            print(f"  [orders] {ticker} page error: {e}", flush=True)
            break
        orders = data.get("orders") or []
        out.extend(orders)
        cursor = data.get("cursor")
        if not cursor or not orders:
            break
        time.sleep(0.15)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--all-episodes", action="store_true",
                    help="fetch orders for every episode, not just flagged")
    args = ap.parse_args(argv)

    _load_env()
    rep = json.loads(Path(args.report).read_text())
    eps = rep["episodes"]
    if not args.all_episodes:
        eps = [e for e in eps
               if e.get("unverified_semantics") or e["tier"] in ("A", "B")]
    want = {}  # order_id -> ticker
    for e in eps:
        want[e["order_id"]] = e["ticker"]
    tickers = sorted(set(want.values()))
    print(f"[orders] {len(want)} target orders across {len(tickers)} tickers",
          flush=True)

    sign = _signer()
    matched = {}
    for i, tk in enumerate(tickers, 1):
        orders = fetch_orders_for_ticker(sign, tk)
        hits = [o for o in orders if o.get("order_id") in want]
        for o in hits:
            matched[o["order_id"]] = o
        print(f"[orders] {i}/{len(tickers)} {tk}: {len(orders)} orders, "
              f"{len(hits)} matched", flush=True)
        time.sleep(0.2)

    missing = sorted(set(want) - set(matched))
    print(f"[orders] matched {len(matched)}/{len(want)}; "
          f"missing {len(missing)}", flush=True)

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for oid, o in sorted(matched.items()):
            f.write(json.dumps({"target_order_id": oid, "order": o},
                               default=str) + "\n")
        for oid in missing:
            f.write(json.dumps({"target_order_id": oid,
                                "order": None,
                                "note": "not_returned_by_historical_orders"},
                               default=str) + "\n")
    print(f"[orders] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
