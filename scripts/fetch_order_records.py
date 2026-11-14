"""Fetch Kalshi order records for flagged execution-consistency episodes.

Resolves the IOC-exit limit ambiguity: the local attempt store records
``requested_limit_cents`` (policy bound) but not the price actually
submitted to the exchange.  ``GET /portfolio/orders`` returns executed,
canceled, and resting orders newer than the historical cutoff with the
true ``yes_price``/``no_price``; ``GET /historical/orders`` covers older
ones.  The cutoff is read live from ``/historical/cutoff``.

Read-only; writes JSONL of matched order records.

    py -3 scripts/fetch_order_records.py \
        --report reports/execution_consistency_2026-11-14.json \
        --out reports/order_records_2026-11-14.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from rti_backfill import _load_env, _signer  # noqa: E402

BASE = "https://external-api.kalshi.com"
SIGN_PREFIX = "/trade-api/v2"


def _get(sign, path: str) -> dict:
    full = SIGN_PREFIX + path.split("?")[0]
    url = BASE + full + ("?" + path.split("?", 1)[1]
                         if "?" in path else "")
    req = urllib.request.Request(url, headers=sign("GET", full))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _orders_endpoint(sign, base_path: str, ticker: str) -> list[dict]:
    out = []
    cursor = None
    for _ in range(50):
        path = (f"{base_path}?ticker={ticker}&limit=200"
                + (f"&cursor={cursor}" if cursor else ""))
        try:
            data = _get(sign, path)
        except Exception as e:
            print(f"  [orders] {ticker} {base_path} page error: {e}",
                  flush=True)
            break
        orders = data.get("orders") or []
        out.extend(orders)
        cursor = data.get("cursor")
        if not cursor or not orders:
            break
        time.sleep(0.15)
    return out


def fetch_ticker_orders(sign, ticker: str) -> list[dict]:
    """All order records for a ticker across live + historical endpoints."""
    out = {}
    for base in ("/portfolio/orders", "/historical/orders"):
        cursor = None
        for _ in range(50):
            path = (f"{base}?ticker={ticker}&limit=200"
                    + (f"&cursor={cursor}" if cursor else ""))
            try:
                data = _get(sign, path)
            except Exception as e:
                print(f"  [orders] {ticker} {base} err: {e}", flush=True)
                break
            orders = data.get("orders") or []
            for o in orders:
                out[o.get("order_id") or id(o)] = o
            cursor = data.get("cursor")
            if not cursor or not orders:
                break
            time.sleep(0.15)
    return list(out.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--all-episodes", action="store_true")
    args = ap.parse_args(argv)

    _load_env()
    rep = json.loads(Path(args.report).read_text())
    eps = rep["episodes"]
    if not args.all_episodes:
        eps = [e for e in eps
               if e.get("unverified_semantics") or e["tier"] in ("A", "B")]
    want = {e["order_id"]: e["ticker"] for e in eps}
    tickers = sorted(set(want.values()))
    print(f"[orders] {len(want)} targets / {len(tickers)} tickers", flush=True)

    sign = _signer()
    matched = {}
    for i, tk in enumerate(tickers, 1):
        orders = fetch_ticker_orders(sign, tk)
        hits = [o for o in orders if o.get("order_id") in want]
        for o in hits:
            matched[o["order_id"]] = o
        print(f"[orders] {i}/{len(tickers)} {tk}: {len(orders)} orders, "
              f"{len(hits)} matched", flush=True)
        time.sleep(0.2)

    missing = sorted(set(want) - set(matched))
    print(f"[orders] matched {len(matched)}/{len(want)}; missing {len(missing)}",
          flush=True)

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for oid in sorted(matched):
            f.write(json.dumps({"target_order_id": oid,
                                "order": matched[oid]}, default=str) + "\n")
        for oid in missing:
            f.write(json.dumps({"target_order_id": oid, "order": None,
                                "note": "not_returned"}, default=str) + "\n")
    print(f"[orders] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
