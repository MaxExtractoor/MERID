#!/usr/bin/env python3
"""Offline replay: historical 1 Hz RTI ticks → same buffer + view as live MERID.

Reads CSV (ts_unix,price) or JSON list of {"ts":..., "price":...}, replays into
:class:`~merid.data.settlement_rti_buffer.SettlementRTIBuffer`, optionally checks
mean vs Kalshi/CFB ground truth.

Example::

    py scripts/validate_settlement_replay.py --csv ticks.csv --expiry 1700000060 \\
        --ticker KXBTC15M-DEMO --asset BTC --expected-mean 42150.25
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, List, Tuple

from merid.data.settlement_offline import (
    build_view_or_none,
    offline_buffer_from_expiry,
    replay_ticks,
    validate_buffer_vs_ground_truth,
)


def _load_csv(path: Path) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            raise SystemExit("CSV has no header")
        cols = {h.lower().strip(): h for h in r.fieldnames}
        ts_key = cols.get("ts_unix") or cols.get("ts") or cols.get("timestamp")
        px_key = cols.get("price") or cols.get("px") or cols.get("rti")
        if not ts_key or not px_key:
            raise SystemExit(f"CSV needs ts + price columns, got {r.fieldnames}")
        for row in r:
            out.append((float(row[ts_key]), float(row[px_key])))
    return out


def _load_json(path: Path) -> List[Tuple[float, float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        out: List[Tuple[float, float]] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append((float(item[0]), float(item[1])))
            elif isinstance(item, dict):
                ts = item.get("ts") or item.get("ts_unix") or item.get("timestamp")
                px = item.get("price") or item.get("px") or item.get("rti")
                if ts is None or px is None:
                    raise SystemExit(f"JSON object missing ts/price: {item!r}")
                out.append((float(ts), float(px)))
            else:
                raise SystemExit(f"Unexpected JSON row: {item!r}")
        return out
    raise SystemExit("JSON root must be a list")


def _iter_ticks(args: argparse.Namespace) -> Iterable[Tuple[float, float]]:
    if args.csv:
        return _load_csv(Path(args.csv))
    if args.json:
        return _load_json(Path(args.json))
    raise SystemExit("Provide --csv or --json")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", help="CSV with ts_unix,price (or ts,price)")
    p.add_argument("--json", help="JSON array of [ts,price] or objects")
    p.add_argument("--expiry", type=int, required=True, help="Contract expiry epoch seconds")
    p.add_argument("--ticker", required=True, help="Kalshi market ticker (label only)")
    p.add_argument("--asset", default="BTC", help="Asset code, e.g. BTC")
    p.add_argument("--expected-mean", type=float, default=None, help="Official 60s average to verify")
    p.add_argument("--rtol", type=float, default=1e-5)
    p.add_argument("--atol", type=float, default=1e-4)
    args = p.parse_args()

    ticks = list(_iter_ticks(args))
    buf = offline_buffer_from_expiry(args.ticker, args.asset, args.expiry)
    n = replay_ticks(buf, ticks)
    view = build_view_or_none(buf)

    print(f"ingested_ticks_accepted={n} filled_count={buf.filled_count}/60 grade={buf.is_settlement_grade()}")
    print(f"avg_received={buf.avg_received:.8f}")

    if args.expected_mean is not None:
        ok, msg = validate_buffer_vs_ground_truth(
            buf, args.expected_mean, rtol=args.rtol, atol=args.atol
        )
        print(msg)
        if not ok:
            sys.exit(1)

    if view:
        d: dict[str, Any] = view.to_dict()
        d["content_hash"] = view.content_hash[:16] + "..."
        print("settlement_view:", json.dumps(d, indent=2)[:2000])
    elif buf.is_settlement_grade():
        print("error: grade true but build_view_or_none returned None", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
