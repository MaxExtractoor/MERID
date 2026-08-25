"""
Forensic trade replay for Kalshi 15M crypto episodes.

Tracks independent long/short YES and NO lots, matches FIFO within each
side, and emits one row per closed episode. Detects reversals, boxes, and
manual-vs-bot attribution.
"""
import csv
import json
from decimal import Decimal
from collections import defaultdict, deque
from pathlib import Path
from datetime import datetime, timezone

AUDIT_DIR = Path("audit_output_20260818_153850")
OUT_DIR = Path(f"audit_output_forensic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_json(name):
    with open(AUDIT_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load_fills():
    live = load_json("kalshi_fills_raw_20260818_153850.json").get("fills", [])
    hist = load_json("kalshi_historical_fills_raw_20260818_153850.json").get("fills", [])
    by_id = {}
    for f in live + hist:
        fid = f.get("fill_id") or f.get("trade_id")
        if fid and fid not in by_id:
            by_id[fid] = f
    return list(by_id.values())


def load_settlements_positions():
    settlements = {s["ticker"]: s for s in load_json("kalshi_settlements_raw_20260818_153850.json").get("settlements", [])}
    positions = {}
    for p in load_json("kalshi_positions_raw_20260818_153850.json").get("market_positions", []):
        positions[p["ticker"]] = p
    for p in load_json("kalshi_historical_positions_raw_20260818_153850.json").get("market_positions", []):
        positions[p["ticker"]] = p
    return settlements, positions


def ts_to_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def source_label(fill: dict) -> str:
    return "bot_taker" if fill.get("is_taker") else "manual_maker"


class LotLedger:
    """Track four independent lot queues: long/short YES and long/short NO."""
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.long_yes = deque()
        self.short_yes = deque()
        self.long_no = deque()
        self.short_no = deque()
        self.events = []
        self.box_flag = False
        self.reversal_flag = False

    def _queue(self, side: str, pos: str):
        return getattr(self, f"{pos}_{side}")

    def _open(self, side: str, pos: str, qty: int, price: Decimal, fee: Decimal, fill: dict):
        q = self._queue(side, pos)
        q.append({
            "side": side,
            "pos": pos,
            "qty": qty,
            "price": price,
            "fee": fee,
            "fill_id": fill.get("fill_id") or fill.get("trade_id"),
            "time": ts_to_dt(fill["created_time"]),
            "source": source_label(fill),
            "is_taker": bool(fill.get("is_taker")),
        })

    def _close_lots(self, side: str, pos: str, qty: int, exit_price: Decimal, exit_fee: Decimal, fill: dict):
        """Close qty cc of lots from the given queue. Returns remaining qty if not enough."""
        q = self._queue(side, pos)
        fill_dt = ts_to_dt(fill["created_time"])
        exit_fill_id = fill.get("fill_id") or fill.get("trade_id")
        exit_source = source_label(fill)
        exit_is_taker = bool(fill.get("is_taker"))
        remaining = qty
        multiplier = 1 if pos == "long" else -1

        # allocate exit fee pro-rata across total lots of this queue
        total_open = sum(l["qty"] for l in q)
        exit_fee_rate = exit_fee / Decimal(total_open) if total_open else Decimal("0")

        while remaining > 0 and q:
            lot = q[0]
            use = min(lot["qty"], remaining)
            lot_fee_alloc = lot["fee"] * (Decimal(use) / Decimal(lot["qty"]))
            lot_exit_fee = exit_fee_rate * use
            gross = multiplier * (exit_price - lot["price"]) * (Decimal(use) / Decimal("100"))
            net = gross - lot_fee_alloc - lot_exit_fee

            self.events.append({
                "market_ticker": self.ticker,
                "asset": self.ticker.split("-")[0].replace("KX", ""),
                "side": side,
                "pos": pos,
                "entry_time": lot["time"].isoformat(),
                "exit_time": fill_dt.isoformat(),
                "hold_seconds": (fill_dt - lot["time"]).total_seconds(),
                "count": use,
                "entry_price": str(lot["price"]),
                "exit_price": str(exit_price),
                "gross_pnl": gross,
                "entry_fee": lot_fee_alloc,
                "exit_fee": lot_exit_fee,
                "net_pnl": net,
                "entry_source": lot["source"],
                "exit_source": exit_source,
                "entry_fill_id": lot["fill_id"],
                "exit_fill_id": exit_fill_id,
                "exit_reason": "bot_taker" if exit_is_taker else "manual_maker",
                "reversal": False,
                "box": False,
                "unresolved_qty": 0,
                "settlement_value": "",
            })

            remaining -= use
            lot["qty"] -= use
            lot["fee"] -= lot_fee_alloc
            if lot["qty"] == 0:
                q.popleft()

        return remaining

    def _handle(self, side: str, action: str, qty: int, price: Decimal, fee: Decimal, fill: dict):
        """Process one fill: open, close, or reverse within the same side."""
        if side not in ("yes", "no"):
            return

        if action == "buy":
            # buying a side first closes any short position on that side
            remaining = self._close_lots(side, "short", qty, price, fee, fill)
            if remaining > 0:
                self._open(side, "long", remaining, price, fee * (Decimal(remaining) / Decimal(qty)) if qty else Decimal("0"), fill)
                # If there were short lots and remaining, this is a reversal short->long
                if remaining != qty:
                    self.reversal_flag = True
        elif action == "sell":
            # selling a side first closes any long position on that side
            remaining = self._close_lots(side, "long", qty, price, fee, fill)
            if remaining > 0:
                self._open(side, "short", remaining, price, fee * (Decimal(remaining) / Decimal(qty)) if qty else Decimal("0"), fill)
                if remaining != qty:
                    self.reversal_flag = True

    def process_fill(self, fill: dict):
        qty = int(Decimal(fill["count_fp"]) * 100)
        side = (fill.get("side") or "").lower()
        action = (fill.get("action") or "").lower()
        if side == "yes":
            price = Decimal(fill["yes_price_dollars"])
        else:
            price = Decimal(fill["no_price_dollars"])
        fee = Decimal(fill.get("fee_cost", "0"))
        self._handle(side, action, qty, price, fee, fill)

    def close_settlement(self, settlement: dict):
        value = Decimal(str(settlement.get("value", 0))) / Decimal("100")
        dt = ts_to_dt(settlement["settled_time"])
        settle_fee = Decimal(settlement.get("fee_cost", "0"))

        # exit prices: long/short YES -> value; long/short NO -> 1 - value
        exits = [
            ("yes", "long", value),
            ("yes", "short", value),
            ("no", "long", 1 - value),
            ("no", "short", 1 - value),
        ]

        for side, pos, exit_price in exits:
            q = self._queue(side, pos)
            total_open = sum(l["qty"] for l in q)
            if not total_open:
                continue
            # allocate settlement fee pro-rata across all open lots of all sides
            # (simplification: distribute entire fee by qty share across the four queues)
            total_all = sum(
                sum(l["qty"] for l in self._queue(s, p))
                for s in ("yes", "no") for p in ("long", "short")
            )
            exit_fee_total = settle_fee * (Decimal(total_open) / Decimal(total_all)) if total_all else Decimal("0")

            while q:
                lot = q.popleft()
                use = lot["qty"]
                multiplier = 1 if pos == "long" else -1
                exit_fee = exit_fee_total * (Decimal(use) / Decimal(total_open)) if total_open else Decimal("0")
                gross = multiplier * (exit_price - lot["price"]) * (Decimal(use) / Decimal("100"))
                net = gross - lot["fee"] - exit_fee

                self.events.append({
                    "market_ticker": self.ticker,
                    "asset": self.ticker.split("-")[0].replace("KX", ""),
                    "side": side,
                    "pos": pos,
                    "entry_time": lot["time"].isoformat(),
                    "exit_time": dt.isoformat(),
                    "hold_seconds": (dt - lot["time"]).total_seconds(),
                    "count": use,
                    "entry_price": str(lot["price"]),
                    "exit_price": str(exit_price),
                    "gross_pnl": gross,
                    "entry_fee": lot["fee"],
                    "exit_fee": exit_fee,
                    "net_pnl": net,
                    "entry_source": lot["source"],
                    "exit_source": "settlement",
                    "entry_fill_id": lot["fill_id"],
                    "exit_fill_id": "",
                    "exit_reason": "settlement",
                    "reversal": self.reversal_flag,
                    "box": False,
                    "unresolved_qty": 0,
                    "settlement_value": str(settlement.get("value", "")),
                })

    def close_position_record(self, pos: dict, last_fill_time: str):
        # Use realized_pnl and fees_paid from position record; cannot split per lot
        realized = Decimal(str(pos.get("realized_pnl_dollars", "0")))
        fees_paid = Decimal(str(pos.get("fees_paid_dollars", "0")))
        net_total = realized - fees_paid
        dt = ts_to_dt(pos.get("last_updated", last_fill_time))

        all_lots = []
        for s in ("yes", "no"):
            for p in ("long", "short"):
                q = self._queue(s, p)
                all_lots.extend(q)
                q.clear()

        total_qty = sum(l["qty"] for l in all_lots)
        for lot in all_lots:
            frac = Decimal(lot["qty"]) / Decimal(total_qty) if total_qty else Decimal("0")
            self.events.append({
                "market_ticker": self.ticker,
                "asset": self.ticker.split("-")[0].replace("KX", ""),
                "side": lot["side"],
                "pos": lot["pos"],
                "entry_time": lot["time"].isoformat(),
                "exit_time": dt.isoformat(),
                "hold_seconds": (dt - lot["time"]).total_seconds(),
                "count": lot["qty"],
                "entry_price": str(lot["price"]),
                "exit_price": "position_record",
                "gross_pnl": "",
                "entry_fee": lot["fee"],
                "exit_fee": fees_paid * frac,
                "net_pnl": net_total * frac,
                "entry_source": lot["source"],
                "exit_source": "position_record",
                "entry_fill_id": lot["fill_id"],
                "exit_fill_id": "",
                "exit_reason": "position_record",
                "reversal": self.reversal_flag,
                "box": False,
                "unresolved_qty": 0,
                "settlement_value": "",
            })

    def close_unresolved(self):
        for s in ("yes", "no"):
            for p in ("long", "short"):
                q = self._queue(s, p)
                while q:
                    lot = q.popleft()
                    self.events.append({
                        "market_ticker": self.ticker,
                        "asset": self.ticker.split("-")[0].replace("KX", ""),
                        "side": lot["side"],
                        "pos": lot["pos"],
                        "entry_time": lot["time"].isoformat(),
                        "exit_time": "",
                        "hold_seconds": "",
                        "count": lot["qty"],
                        "entry_price": str(lot["price"]),
                        "exit_price": "",
                        "gross_pnl": Decimal("0"),
                        "entry_fee": lot["fee"],
                        "exit_fee": Decimal("0"),
                        "net_pnl": -lot["fee"],
                        "entry_source": lot["source"],
                        "exit_source": "",
                        "entry_fill_id": lot["fill_id"],
                        "exit_fill_id": "",
                        "exit_reason": "unresolved",
                        "reversal": self.reversal_flag,
                        "box": False,
                        "unresolved_qty": lot["qty"],
                        "settlement_value": "",
                    })

    def has_both_sides(self) -> bool:
        yes_qty = sum(l["qty"] for l in self.long_yes) + sum(l["qty"] for l in self.short_yes)
        no_qty = sum(l["qty"] for l in self.long_no) + sum(l["qty"] for l in self.short_no)
        return yes_qty > 0 and no_qty > 0


def run():
    fills = load_fills()
    settlements, positions = load_settlements_positions()

    by_ticker = defaultdict(list)
    for f in fills:
        by_ticker[f["market_ticker"]].append(f)

    stats = {
        "total_episodes": 0,
        "total_gross_pnl": Decimal("0"),
        "total_net_pnl": Decimal("0"),
        "total_fees": Decimal("0"),
        "by_exit_reason": defaultdict(lambda: {"count": 0, "gross": Decimal("0"), "net": Decimal("0"), "fees": Decimal("0")}),
        "by_asset": defaultdict(lambda: {"count": 0, "net": Decimal("0"), "fees": Decimal("0")}),
        "by_side_pos": defaultdict(lambda: {"count": 0, "net": Decimal("0"), "fees": Decimal("0")}),
        "by_entry_source": defaultdict(lambda: {"count": 0, "net": Decimal("0"), "fees": Decimal("0")}),
        "by_exit_source_pair": defaultdict(lambda: {"count": 0, "net": Decimal("0"), "fees": Decimal("0")}),
        "reversals": 0,
        "boxes": 0,
        "unresolved_cc": 0,
        "unresolved_markets": 0,
    }

    all_episodes = []
    for ticker in sorted(by_ticker.keys()):
        if not ("15M" in ticker and any(c in ticker for c in ("BTC", "ETH", "SOL", "XRP", "DOGE"))):
            continue

        asset = ticker.split("-")[0].replace("KX", "")
        fs = sorted(by_ticker[ticker], key=lambda x: x["created_time"])
        ledger = LotLedger(ticker)

        for f in fs:
            ledger.process_fill(f)
            if ledger.has_both_sides():
                ledger.box_flag = True

        if settlements.get(ticker):
            ledger.close_settlement(settlements[ticker])
        elif positions.get(ticker):
            ledger.close_position_record(positions[ticker], fs[-1]["created_time"])
        else:
            ledger.close_unresolved()

        for ep in ledger.events:
            all_episodes.append(ep)
            stats["total_episodes"] += 1
            if ep["gross_pnl"] != "":
                stats["total_gross_pnl"] += ep["gross_pnl"]
            stats["total_net_pnl"] += ep["net_pnl"]
            stats["total_fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["total_fees"] += ep["exit_fee"]
            stats["by_exit_reason"][ep["exit_reason"]]["count"] += 1
            if ep["gross_pnl"] != "":
                stats["by_exit_reason"][ep["exit_reason"]]["gross"] += ep["gross_pnl"]
            stats["by_exit_reason"][ep["exit_reason"]]["net"] += ep["net_pnl"]
            stats["by_exit_reason"][ep["exit_reason"]]["fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["by_exit_reason"][ep["exit_reason"]]["fees"] += ep["exit_fee"]
            stats["by_asset"][asset]["count"] += 1
            stats["by_asset"][asset]["net"] += ep["net_pnl"]
            stats["by_asset"][asset]["fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["by_asset"][asset]["fees"] += ep["exit_fee"]
            key = f"{ep['side']}-{ep['pos']}"
            stats["by_side_pos"][key]["count"] += 1
            stats["by_side_pos"][key]["net"] += ep["net_pnl"]
            stats["by_side_pos"][key]["fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["by_side_pos"][key]["fees"] += ep["exit_fee"]

            stats["by_entry_source"][ep["entry_source"]]["count"] += 1
            stats["by_entry_source"][ep["entry_source"]]["net"] += ep["net_pnl"]
            stats["by_entry_source"][ep["entry_source"]]["fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["by_entry_source"][ep["entry_source"]]["fees"] += ep["exit_fee"]

            pair = f"{ep['entry_source']} -> {ep['exit_source']}" if ep["exit_source"] else f"{ep['entry_source']} -> open"
            stats["by_exit_source_pair"][pair]["count"] += 1
            stats["by_exit_source_pair"][pair]["net"] += ep["net_pnl"]
            stats["by_exit_source_pair"][pair]["fees"] += ep["entry_fee"]
            if ep["exit_fee"] != "":
                stats["by_exit_source_pair"][pair]["fees"] += ep["exit_fee"]

        if ledger.reversal_flag:
            stats["reversals"] += 1
        if ledger.box_flag:
            stats["boxes"] += 1
        # unresolved handled in close_unresolved; track totals
        for ep in ledger.events:
            if ep["exit_reason"] == "unresolved":
                stats["unresolved_cc"] += ep["unresolved_qty"]

    # Write CSV
    csv_path = OUT_DIR / "forensic_replay.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "market_ticker", "asset", "side", "pos", "entry_time", "exit_time",
            "hold_seconds", "count", "entry_price", "exit_price",
            "gross_pnl", "entry_fee", "exit_fee", "net_pnl",
            "entry_source", "exit_source", "entry_fill_id", "exit_fill_id",
            "exit_reason", "reversal", "box", "unresolved_qty", "settlement_value",
        ])
        writer.writeheader()
        for ep in all_episodes:
            row = {}
            for k, v in ep.items():
                if isinstance(v, Decimal):
                    row[k] = f"{v:.6f}"
                else:
                    row[k] = str(v) if v is not None else ""
            writer.writerow(row)

    # Summary report
    report_path = OUT_DIR / "forensic_summary.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("KALSHI 15M CRYPTO FORENSIC REPLAY (two-sided FIFO)\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Episodes: {stats['total_episodes']}\n")
        f.write(f"Total gross PnL: ${stats['total_gross_pnl']:.4f}\n")
        f.write(f"Total fees:      ${stats['total_fees']:.4f}\n")
        f.write(f"Total net PnL:   ${stats['total_net_pnl']:.4f}\n")
        f.write(f"Reversal tickers: {stats['reversals']}\n")
        f.write(f"Box tickers:      {stats['boxes']}\n")
        f.write(f"Unresolved cc:    {stats['unresolved_cc']}\n\n")

        f.write("BY EXIT REASON\n")
        f.write("-" * 80 + "\n")
        for reason, v in sorted(stats["by_exit_reason"].items(), key=lambda x: x[1]["net"], reverse=True):
            f.write(f"  {reason:18s}: count={v['count']:5d} gross=${v['gross']:.4f} net=${v['net']:.4f} fees=${v['fees']:.4f}\n")

        f.write("\nBY ASSET\n")
        f.write("-" * 80 + "\n")
        for asset, v in sorted(stats["by_asset"].items(), key=lambda x: x[1]["net"], reverse=True):
            f.write(f"  {asset:10s}: count={v['count']:5d} net=${v['net']:.4f} fees=${v['fees']:.4f}\n")

        f.write("\nBY SIDE/POSITION\n")
        f.write("-" * 80 + "\n")
        for key, v in sorted(stats["by_side_pos"].items(), key=lambda x: x[1]["net"], reverse=True):
            f.write(f"  {key:12s}: count={v['count']:5d} net=${v['net']:.4f} fees=${v['fees']:.4f}\n")

        f.write("\nBY ENTRY SOURCE\n")
        f.write("-" * 80 + "\n")
        for src, v in sorted(stats["by_entry_source"].items(), key=lambda x: x[1]["net"], reverse=True):
            f.write(f"  {src:18s}: count={v['count']:5d} net=${v['net']:.4f} fees=${v['fees']:.4f}\n")

        f.write("\nBY ENTRY -> EXIT SOURCE PAIR\n")
        f.write("-" * 80 + "\n")
        for pair, v in sorted(stats["by_exit_source_pair"].items(), key=lambda x: x[1]["net"], reverse=True):
            f.write(f"  {pair:35s}: count={v['count']:5d} net=${v['net']:.4f} fees=${v['fees']:.4f}\n")

    print(f"Wrote {csv_path} and {report_path}")
    with open(report_path, encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    run()
