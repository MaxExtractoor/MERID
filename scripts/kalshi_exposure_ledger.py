"""
Per-fill and per-order exposure ledger for Kalshi fills.

Produces three linked views:
- Native contract inventory (raw YES and NO units) before/after each fill/order.
- Economic YES exposure E = Y - N before/after.
- Cash-flow ledger for reconciliation.

Also computes expected economic delta from the fill's action/side and compares
it to the actual delta to detect side/action inversions.
"""
import csv
import json
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

AUDIT_DIR = Path("audit_output_20260818_153850")
OUT_DIR = Path(f"audit_output_forensic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_fills():
    live = json.load(open(AUDIT_DIR / "kalshi_fills_raw_20260818_153850.json", encoding="utf-8")).get("fills", [])
    hist = json.load(open(AUDIT_DIR / "kalshi_historical_fills_raw_20260818_153850.json", encoding="utf-8")).get("fills", [])
    by_id = {}
    for f in live + hist:
        fid = f.get("fill_id") or f.get("trade_id")
        if fid and fid not in by_id:
            by_id[fid] = f
    return list(by_id.values())


def ts_to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def native_delta(side: str, action: str, qty: int) -> tuple:
    """Return (yes_delta, no_delta) in centi-contracts for the fill."""
    # Native contract inventory: each fill only mutates the side it trades.
    if side == "yes":
        return (qty, 0) if action == "buy" else (-qty, 0)
    else:
        return (0, qty) if action == "buy" else (0, -qty)


def economic_delta(side: str, action: str, qty: int) -> int:
    """Signed YES exposure delta: + long YES / short NO, - long NO / short YES."""
    if side == "yes" and action == "buy":
        return qty
    if side == "yes" and action == "sell":
        return -qty
    if side == "no" and action == "buy":
        return -qty
    if side == "no" and action == "sell":
        return qty
    return 0


def run():
    fills = load_fills()

    # Group fills by ticker and order
    by_ticker = defaultdict(list)
    by_order = defaultdict(list)
    for f in fills:
        by_ticker[f["market_ticker"]].append(f)
        by_order[f.get("order_id", "")].append(f)

    fill_rows = []
    order_rows = []

    # Aggregate by order
    for order_id, fs in by_order.items():
        fs.sort(key=lambda x: x["created_time"])
        first = fs[0]
        ticker = first["market_ticker"]
        side = (first.get("side") or "").lower()
        action = (first.get("action") or "").lower()
        is_taker = all(f.get("is_taker") for f in fs)
        book_side = " | ".join({str(f.get("book_side")) for f in fs})
        count = sum(int(Decimal(f["count_fp"]) * 100) for f in fs)
        fee = sum(Decimal(f.get("fee_cost", "0")) for f in fs)
        # average fill price weighted by count
        if side == "yes":
            prices = [Decimal(f["yes_price_dollars"]) * int(Decimal(f["count_fp"]) * 100) for f in fs]
        else:
            prices = [Decimal(f["no_price_dollars"]) * int(Decimal(f["count_fp"]) * 100) for f in fs]
        avg_price = sum(prices) / Decimal(count) if count else Decimal("0")

        order_rows.append({
            "order_id": order_id,
            "market_ticker": ticker,
            "first_fill_time": fs[0]["created_time"],
            "last_fill_time": fs[-1]["created_time"],
            "fill_count": len(fs),
            "side": side,
            "action": action,
            "count_cc": count,
            "avg_price_dollars": avg_price,
            "total_fee": fee,
            "is_taker": is_taker,
            "book_side": book_side,
            "fill_ids": " ".join(str(f.get("fill_id") or f.get("trade_id")) for f in fs),
        })

    # Compute native/economic exposure per ticker, fill by fill
    # We need both fill-level and order-level.
    # Start with fill-level, then aggregate to order.

    for ticker, fs in sorted(by_ticker.items()):
        if not ("15M" in ticker and any(c in ticker for c in ("BTC", "ETH", "SOL", "XRP", "DOGE"))):
            continue

        fs.sort(key=lambda x: x["created_time"])
        yes_qty = 0
        no_qty = 0

        for f in fs:
            side = (f.get("side") or "").lower()
            action = (f.get("action") or "").lower()
            count_cc = int(Decimal(f["count_fp"]) * 100)

            yes_before = yes_qty
            no_before = no_qty
            exposure_before = yes_before - no_before

            yes_d, no_d = native_delta(side, action, count_cc)
            yes_qty += yes_d
            no_qty += no_d

            yes_after = yes_qty
            no_after = no_qty
            exposure_after = yes_after - no_after
            actual_economic_delta = exposure_after - exposure_before
            expected_economic_delta = economic_delta(side, action, count_cc)
            delta_mismatch = actual_economic_delta - expected_economic_delta

            fill_rows.append({
                "fill_id": f.get("fill_id") or f.get("trade_id"),
                "order_id": f.get("order_id", ""),
                "market_ticker": ticker,
                "created_time": f["created_time"],
                "side": side,
                "action": action,
                "count_cc": count_cc,
                "yes_price_dollars": f["yes_price_dollars"],
                "no_price_dollars": f["no_price_dollars"],
                "fee_cost": f.get("fee_cost", "0"),
                "is_taker": f.get("is_taker", False),
                "book_side": f.get("book_side", ""),
                "native_yes_before": yes_before,
                "native_no_before": no_before,
                "native_yes_after": yes_after,
                "native_no_after": no_after,
                "economic_exposure_before": exposure_before,
                "economic_exposure_after": exposure_after,
                "actual_economic_delta_cc": actual_economic_delta,
                "expected_economic_delta_cc": expected_economic_delta,
                "delta_mismatch_cc": delta_mismatch,
                "flattened": 1 if exposure_before != 0 and exposure_after == 0 else 0,
                "reversal": 1 if (exposure_before != 0 and exposure_after != 0 and
                                  ((exposure_before > 0 and exposure_after < 0) or
                                   (exposure_before < 0 and exposure_after > 0))) else 0,
                "box_after": 1 if yes_after > 0 and no_after > 0 else 0,
                "short_box_after": 1 if yes_after < 0 and no_after < 0 else 0,
                "origin": "unknown",  # no client_order_id / decision log
            })

    # Compute order-level exposure rows (native/economic before and after order execution)
    # Recompute by applying order net deltas in time order per ticker.
    order_exposure_rows = []
    by_ticker_order = defaultdict(list)
    for r in order_rows:
        by_ticker_order[r["market_ticker"]].append(r)

    for ticker, orders in by_ticker_order.items():
        if not ("15M" in ticker and any(c in ticker for c in ("BTC", "ETH", "SOL", "XRP", "DOGE"))):
            continue
        orders.sort(key=lambda r: r["first_fill_time"])
        yes_qty = 0
        no_qty = 0
        for o in orders:
            side = o["side"]
            action = o["action"]
            count = o["count_cc"]

            yes_before = yes_qty
            no_before = no_qty
            exposure_before = yes_before - no_before

            yes_d, no_d = native_delta(side, action, count)
            yes_qty += yes_d
            no_qty += no_d

            yes_after = yes_qty
            no_after = no_qty
            exposure_after = yes_after - no_after
            actual_delta = exposure_after - exposure_before
            expected_delta = economic_delta(side, action, count)

            o["native_yes_before"] = yes_before
            o["native_no_before"] = no_before
            o["native_yes_after"] = yes_after
            o["native_no_after"] = no_after
            o["economic_exposure_before"] = exposure_before
            o["economic_exposure_after"] = exposure_after
            o["actual_economic_delta_cc"] = actual_delta
            o["expected_economic_delta_cc"] = expected_delta
            o["delta_mismatch_cc"] = actual_delta - expected_delta
            o["flattened"] = 1 if exposure_before != 0 and exposure_after == 0 else 0
            o["reversal"] = 1 if (exposure_before != 0 and exposure_after != 0 and
                                  ((exposure_before > 0 and exposure_after < 0) or
                                   (exposure_before < 0 and exposure_after > 0))) else 0
            o["box_after"] = 1 if yes_after > 0 and no_after > 0 else 0
            o["short_box_after"] = 1 if yes_after < 0 and no_after < 0 else 0
            o["origin"] = "unknown"
            order_exposure_rows.append(o)

    # Write fill-level ledger
    fill_csv = OUT_DIR / "forensic_replay.csv"
    with open(fill_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "fill_id", "order_id", "market_ticker", "created_time",
            "side", "action", "count_cc", "yes_price_dollars", "no_price_dollars",
            "fee_cost", "is_taker", "book_side",
            "native_yes_before", "native_no_before", "native_yes_after", "native_no_after",
            "economic_exposure_before", "economic_exposure_after",
            "actual_economic_delta_cc", "expected_economic_delta_cc", "delta_mismatch_cc",
            "flattened", "reversal", "box_after", "short_box_after", "origin",
        ])
        writer.writeheader()
        for r in fill_rows:
            writer.writerow({k: str(v) for k, v in r.items()})

    # Write order-level ledger
    order_csv = OUT_DIR / "forensic_order_ledger.csv"
    with open(order_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "market_ticker", "first_fill_time", "last_fill_time", "fill_count",
            "side", "action", "count_cc", "avg_price_dollars", "total_fee", "is_taker", "book_side",
            "native_yes_before", "native_no_before", "native_yes_after", "native_no_after",
            "economic_exposure_before", "economic_exposure_after",
            "actual_economic_delta_cc", "expected_economic_delta_cc", "delta_mismatch_cc",
            "flattened", "reversal", "box_after", "short_box_after", "origin", "fill_ids",
        ])
        writer.writeheader()
        for r in order_exposure_rows:
            writer.writerow({k: str(v) for k, v in r.items()})

    # Aggregate summary
    stats = {
        "fills": len(fill_rows),
        "orders": len(order_exposure_rows),
        "tickers": len({r["market_ticker"] for r in fill_rows}),
        "fills_with_mismatch": sum(1 for r in fill_rows if r["delta_mismatch_cc"] != 0),
        "orders_with_mismatch": sum(1 for o in order_exposure_rows if o["delta_mismatch_cc"] != 0),
        "fills_flattened": sum(r["flattened"] for r in fill_rows),
        "orders_flattened": sum(o["flattened"] for o in order_exposure_rows),
        "fills_reversal": sum(r["reversal"] for r in fill_rows),
        "orders_reversal": sum(o["reversal"] for o in order_exposure_rows),
        "fills_box": sum(r["box_after"] for r in fill_rows),
        "orders_box": sum(o["box_after"] for o in order_exposure_rows),
        "fills_short_box": sum(r["short_box_after"] for r in fill_rows),
        "orders_short_box": sum(o["short_box_after"] for o in order_exposure_rows),
        "orders_1_fill": sum(1 for o in order_exposure_rows if o["fill_count"] == 1),
        "orders_multi_fill": sum(1 for o in order_exposure_rows if o["fill_count"] > 1),
    }

    # Economic exposure state at end of each ticker
    final_exposure = {}
    for r in fill_rows:
        final_exposure[r["market_ticker"]] = r["economic_exposure_after"]

    summary_path = OUT_DIR / "forensic_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("KALSHI 15M CRYPTO EXPOSURE LEDGER (per fill and per order)\n")
        f.write("=" * 80 + "\n\n")
        f.write("AGGREGATION DIAGNOSTICS\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Unique tickers:              {stats['tickers']}\n")
        f.write(f"  Total fills:                 {stats['fills']}\n")
        f.write(f"  Total orders:                {stats['orders']}\n")
        f.write(f"  1-fill orders:               {stats['orders_1_fill']}\n")
        f.write(f"  Multi-fill orders:           {stats['orders_multi_fill']}\n")
        f.write(f"  Avg fills/order:             {stats['fills'] / stats['orders']:.2f}\n\n")

        f.write("INVARIANT CHECKS\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Fills with delta mismatch (actual != expected): {stats['fills_with_mismatch']}\n")
        f.write(f"  Orders with delta mismatch:                    {stats['orders_with_mismatch']}\n")
        f.write(f"  Fills that flatten exposure:                   {stats['fills_flattened']}\n")
        f.write(f"  Orders that flatten exposure:                  {stats['orders_flattened']}\n")
        f.write(f"  Fills that reverse exposure sign:              {stats['fills_reversal']}\n")
        f.write(f"  Orders that reverse exposure sign:             {stats['orders_reversal']}\n")
        f.write(f"  Fills leaving a long YES/NO box:               {stats['fills_box']}\n")
        f.write(f"  Orders leaving a long box:                     {stats['orders_box']}\n")
        f.write(f"  Fills leaving a short YES/NO box:              {stats['fills_short_box']}\n")
        f.write(f"  Orders leaving a short box:                    {stats['orders_short_box']}\n\n")

        f.write("FINAL ECONOMIC EXPOSURE PER TICKER (non-zero only)\n")
        f.write("-" * 80 + "\n")
        for t, e in sorted(final_exposure.items(), key=lambda x: abs(x[1]), reverse=True)[:20]:
            if e != 0:
                f.write(f"  {t:45s}: E = {e:6d} cc\n")

        f.write("\nFILES\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Fill-level ledger:  {fill_csv}\n")
        f.write(f"  Order-level ledger: {order_csv}\n")

    print(f"Wrote {fill_csv}, {order_csv}, {summary_path}")
    with open(summary_path, encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    run()
