#!/usr/bin/env python3
"""
Kalshi FIFO Episode Reconciliation

Reconstructs chronological signed-YES inventory from raw Kalshi fills,
matches opening and closing fills with FIFO lots, and produces
realized round-trip PnL, residuals, and cash reconciliation.

Usage:
    python scripts/kalshi_fifo_reconcile.py --fills <raw_fills.json> --output-dir <dir>
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

getcontext().prec = 28

sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("scripts.kalshi_fifo_reconcile")

PROJECT_ROOT = Path(__file__).parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _dollars_to_cents(value: Decimal) -> int:
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class Lot:
    open_fill_id: str
    open_time: str
    ticker: str
    side: int  # +1 long YES, -1 short YES
    open_price: Decimal
    fee_per_contract: Decimal
    remaining_cc: int
    original_cc: int
    client_order_id: Optional[str] = None


@dataclass
class Episode:
    episode_id: str
    ticker: str
    side: int
    open_fill_id: str
    open_time: str
    open_price: Decimal
    close_fill_id: str
    close_time: str
    close_price: Decimal
    quantity_cc: int
    realized_pnl: Decimal
    open_fee: Decimal
    close_fee: Decimal
    total_fees: Decimal
    market_result: Optional[str] = None
    settlement_price: Optional[Decimal] = None


@dataclass
class Residual:
    open_fill_id: str
    open_time: str
    ticker: str
    side: int
    remaining_cc: int
    open_price: Decimal
    fee_per_contract: Decimal
    market_result: Optional[str] = None
    settlement_price: Optional[Decimal] = None
    settlement_pnl: Optional[Decimal] = None
    status: str = "OPEN"


def _canonicalize_fill(fill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert raw Kalshi fill into canonical signed-YES form."""
    try:
        side = str(fill.get("side", "")).lower()
        action = str(fill.get("action", "")).lower()
        count_fp = _to_decimal(fill.get("count_fp", 0))
        qty_cc = int(count_fp * 100)

        if side == "yes" and action == "buy":
            signed_yes_cc = qty_cc
        elif side == "yes" and action == "sell":
            signed_yes_cc = -qty_cc
        elif side == "no" and action == "buy":
            signed_yes_cc = -qty_cc
        elif side == "no" and action == "sell":
            signed_yes_cc = qty_cc
        else:
            logger.warning("Unknown side/action: %s %s in fill %s", side, action, fill.get("fill_id"))
            return None

        price_yes = _to_decimal(fill.get("yes_price_dollars", 0))
        if price_yes < 0 or price_yes > 1:
            logger.warning("Suspicious yes_price: %s in fill %s", price_yes, fill.get("fill_id"))

        fee_cost = _to_decimal(fill.get("fee_cost", 0))
        if qty_cc > 0:
            fee_per_contract = fee_cost / count_fp
        else:
            fee_per_contract = Decimal("0")

        ts = fill.get("ts")
        if not isinstance(ts, int):
            ts = 0

        created_time = fill.get("created_time") or ""

        return {
            "fill_id": str(fill.get("fill_id") or fill.get("trade_id") or ""),
            "trade_id": str(fill.get("trade_id") or fill.get("fill_id") or ""),
            "order_id": str(fill.get("order_id") or ""),
            "client_order_id": str(fill.get("client_order_id" or "")) if fill.get("client_order_id") else None,
            "ticker": str(fill.get("market_ticker") or fill.get("ticker") or ""),
            "created_time": created_time,
            "ts": ts,
            "raw_side": side,
            "raw_action": action,
            "count_fp": count_fp,
            "qty_cc": qty_cc,
            "signed_yes_cc": signed_yes_cc,
            "price_yes": price_yes,
            "fee_cost": fee_cost,
            "fee_per_contract": fee_per_contract,
            "is_taker": fill.get("is_taker"),
            "raw": fill,
        }
    except Exception as e:
        logger.error("Canonicalization failed for fill %s: %s", fill.get("fill_id"), e)
        return None


def _build_inventory_and_episodes(
    canonical_fills: List[Dict[str, Any]],
    settlements_by_ticker: Dict[str, Dict[str, Any]],
) -> Tuple[List[Episode], List[Residual], List[Dict[str, Any]]]:
    """Run per-ticker FIFO lot matching."""
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in canonical_fills:
        by_ticker[f["ticker"]].append(f)

    for t in by_ticker:
        by_ticker[t].sort(key=lambda x: (x["created_time"] or x["ts"] or "", x["fill_id"]))

    episodes: List[Episode] = []
    residuals: List[Residual] = []
    exceptions: List[Dict[str, Any]] = []
    episode_counter = 0

    for ticker, fills in by_ticker.items():
        position_cc = 0
        open_lots: List[Lot] = []

        for fill in fills:
            delta_cc = fill["signed_yes_cc"]
            pos_before = position_cc
            pos_after = pos_before + delta_cc

            # Detect reversal or partial close
            if pos_before == 0 or (delta_cc > 0 and pos_before > 0) or (delta_cc < 0 and pos_before < 0):
                # Opening / scaling
                if delta_cc == 0:
                    continue
                open_lots.append(
                    Lot(
                        open_fill_id=fill["fill_id"],
                        open_time=fill["created_time"],
                        ticker=ticker,
                        side=1 if delta_cc > 0 else -1,
                        open_price=fill["price_yes"],
                        fee_per_contract=fill["fee_per_contract"],
                        remaining_cc=abs(delta_cc),
                        original_cc=abs(delta_cc),
                        client_order_id=fill["client_order_id"],
                    )
                )
                position_cc = pos_after
                continue

            # Opposite sign: reduce/close or reverse
            close_needed = abs(delta_cc)
            close_side = 1 if pos_before > 0 else -1

            # Close existing lots up to close_needed
            while close_needed > 0 and open_lots:
                lot = open_lots[0]
                if lot.side != close_side:
                    exceptions.append({
                        "ticker": ticker,
                        "fill_id": fill["fill_id"],
                        "fill_time": fill["created_time"],
                        "reason": "first_lot_side_mismatch",
                        "lot_side": lot.side,
                        "close_side": close_side,
                        "position_before": pos_before,
                    })
                    break

                matched_cc = min(lot.remaining_cc, close_needed)
                contracts = Decimal(matched_cc) / Decimal(100)

                # PnL = contracts * (lot.side * (close_price - lot.open_price) - (lot.fee + close_fee))
                open_fee_total = contracts * lot.fee_per_contract
                close_fee_total = contracts * fill["fee_per_contract"]
                pnl = contracts * (lot.side * (fill["price_yes"] - lot.open_price) - (lot.fee_per_contract + fill["fee_per_contract"]))

                episode_counter += 1
                episode = Episode(
                    episode_id=f"{ticker}_{episode_counter:06d}",
                    ticker=ticker,
                    side=lot.side,
                    open_fill_id=lot.open_fill_id,
                    open_time=lot.open_time,
                    open_price=lot.open_price,
                    close_fill_id=fill["fill_id"],
                    close_time=fill["created_time"],
                    close_price=fill["price_yes"],
                    quantity_cc=matched_cc,
                    realized_pnl=pnl,
                    open_fee=open_fee_total,
                    close_fee=close_fee_total,
                    total_fees=open_fee_total + close_fee_total,
                )
                episodes.append(episode)

                lot.remaining_cc -= matched_cc
                close_needed -= matched_cc

                if lot.remaining_cc <= 0:
                    open_lots.pop(0)

            position_cc = pos_after

            # Remaining delta after closing flips to a new lot (reversal)
            if close_needed > 0:
                new_delta = -delta_cc if abs(delta_cc) > abs(pos_before) else delta_cc
                # new_delta is the remaining signed cc in the new direction
                new_delta = pos_after  # residual after close
                if new_delta != 0:
                    open_lots.append(
                        Lot(
                            open_fill_id=fill["fill_id"],
                            open_time=fill["created_time"],
                            ticker=ticker,
                            side=1 if new_delta > 0 else -1,
                            open_price=fill["price_yes"],
                            fee_per_contract=fill["fee_per_contract"],
                            remaining_cc=abs(new_delta),
                            original_cc=abs(new_delta),
                            client_order_id=fill["client_order_id"],
                        )
                    )

        # After all fills, any remaining open lots are residuals
        final_position = sum(lot.side * lot.remaining_cc for lot in open_lots)
        if final_position != position_cc:
            exceptions.append({
                "ticker": ticker,
                "reason": "position_tracking_mismatch",
                "computed_position_cc": position_cc,
                "lot_sum_cc": final_position,
            })

        for lot in open_lots:
            settlement = settlements_by_ticker.get(ticker)
            market_result = None
            settlement_price = None
            settlement_pnl = None
            status = "OPEN"

            if settlement:
                market_result = str(settlement.get("market_result", "")).lower()
                value = settlement.get("value")
                if value is not None:
                    settlement_price = _to_decimal(value) / Decimal("100")
                # PnL: long -> s - p - fee; short -> p - s - fee
                contracts = Decimal(lot.remaining_cc) / Decimal(100)
                if lot.side == 1:
                    settlement_pnl = contracts * (settlement_price - lot.open_price - lot.fee_per_contract)
                else:
                    settlement_pnl = contracts * (lot.open_price - settlement_price - lot.fee_per_contract)
                status = "SETTLED"

            residuals.append(
                Residual(
                    open_fill_id=lot.open_fill_id,
                    open_time=lot.open_time,
                    ticker=ticker,
                    side=lot.side,
                    remaining_cc=lot.remaining_cc,
                    open_price=lot.open_price,
                    fee_per_contract=lot.fee_per_contract,
                    market_result=market_result,
                    settlement_price=settlement_price,
                    settlement_pnl=settlement_pnl,
                    status=status,
                )
            )

    return episodes, residuals, exceptions


def _to_json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return _to_json_safe(obj.__dict__)
    return str(obj)


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_settlements(settlements_path: Path) -> Dict[str, Dict[str, Any]]:
    data = _load_json(settlements_path)
    result: Dict[str, Dict[str, Any]] = {}
    for s in data.get("settlements", []):
        ticker = s.get("ticker") or s.get("market_ticker")
        if ticker:
            result[ticker] = s
    return result


def _load_cash_flows(path: Path) -> Decimal:
    data = _load_json(path)
    total_cents = 0
    for item in data.get("deposits", data.get("withdrawals", [])):
        status = str(item.get("status", "")).lower()
        if status not in ("applied", "confirmed", "success"):
            continue
        amount = item.get("amount_cents", 0)
        if not isinstance(amount, int):
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = 0
        total_cents += amount
    return Decimal(total_cents) / Decimal("100")


def main():
    parser = argparse.ArgumentParser(description="FIFO episode reconstruction and cash reconciliation")
    parser.add_argument("--fills", type=str, required=True, help="Path to kalshi_fills_raw_*.json")
    parser.add_argument("--historical-fills", type=str, default=None, help="Path to kalshi_historical_fills_raw_*.json (merged with --fills)")
    parser.add_argument("--positions", type=str, default=None, help="Path to kalshi_positions_raw_*.json")
    parser.add_argument("--balance", type=str, default=None, help="Path to kalshi_balance_raw_*.json")
    parser.add_argument("--deposits", type=str, default=None, help="Path to kalshi_deposits_raw_*.json")
    parser.add_argument("--withdrawals", type=str, default=None, help="Path to kalshi_withdrawals_raw_*.json")
    parser.add_argument("--settlements", type=str, default=None, help="Path to kalshi_settlements_raw_*.json")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    ts = _ts_str()
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = PROJECT_ROOT / f"audit_output_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("FIFO reconciliation starting. Output: %s", output_dir)

    # Load and canonicalize fills (live + historical)
    fills_data = _load_json(Path(args.fills))
    raw_fills = fills_data.get("fills", [])
    logger.info("Loaded %d raw fills", len(raw_fills))

    if args.historical_fills:
        hist_data = _load_json(Path(args.historical_fills))
        hist_fills = hist_data.get("fills", [])
        logger.info("Loaded %d historical fills", len(hist_fills))
        raw_fills = raw_fills + hist_fills

    canonical_fills: List[Dict[str, Any]] = []
    dup_check: set = set()
    for raw in raw_fills:
        fill_id = raw.get("fill_id") or raw.get("trade_id")
        if not fill_id:
            logger.warning("Fill without id: %s", raw)
            continue
        if fill_id in dup_check:
            logger.warning("Duplicate fill_id skipped: %s", fill_id)
            continue
        dup_check.add(fill_id)
        c = _canonicalize_fill(raw)
        if c:
            canonical_fills.append(c)

    logger.info("Canonicalized %d unique fills", len(canonical_fills))

    # Load settlements
    settlements_by_ticker: Dict[str, Dict[str, Any]] = {}
    if args.settlements:
        settlements_by_ticker = _load_settlements(Path(args.settlements))
        logger.info("Loaded %d settlements", len(settlements_by_ticker))

    # Build inventory and match FIFO
    episodes, residuals, exceptions = _build_inventory_and_episodes(canonical_fills, settlements_by_ticker)
    logger.info("Built %d episodes, %d residuals, %d exceptions", len(episodes), len(residuals), len(exceptions))

    # Summaries
    total_realized_pnl = sum(e.realized_pnl for e in episodes)
    total_fees = sum(e.total_fees for e in episodes)
    residual_settlement_pnl = sum((r.settlement_pnl or Decimal("0")) for r in residuals)
    residual_open_cc = sum(r.remaining_cc for r in residuals if r.status == "OPEN")

    # Cash reconciliation
    balance_usd = Decimal("0")
    if args.balance:
        balance_data = _load_json(Path(args.balance))
        raw = balance_data.get("raw", {})
        balance_usd = _to_decimal(raw.get("balance_dollars", 0))

    deposits_usd = Decimal("0")
    withdrawals_usd = Decimal("0")
    if args.deposits:
        deposits_usd = _load_cash_flows(Path(args.deposits))
    if args.withdrawals:
        withdrawals_usd = _load_cash_flows(Path(args.withdrawals))
    net_deposits = deposits_usd - withdrawals_usd

    expected_balance_from_trades = net_deposits + total_realized_pnl + residual_settlement_pnl
    reconciliation_diff = balance_usd - expected_balance_from_trades

    reconciliation = {
        "generated_at": _now_iso(),
        "kalshi_balance_usd": str(balance_usd),
        "total_deposits_usd": str(deposits_usd),
        "total_withdrawals_usd": str(withdrawals_usd),
        "net_deposits_usd": str(net_deposits),
        "fifo_realized_pnl_usd": str(total_realized_pnl),
        "residual_settlement_pnl_usd": str(residual_settlement_pnl),
        "expected_balance_from_trades_usd": str(expected_balance_from_trades),
        "reconciliation_difference_usd": str(reconciliation_diff),
        "residual_open_contracts_cc": residual_open_cc,
        "residual_open_markets": len([r for r in residuals if r.status == "OPEN"]),
    }

    # Per-asset breakdown
    by_asset: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"episodes": 0, "realized_pnl": Decimal("0"), "fees": Decimal("0"), "wins": 0, "losses": 0})
    for e in episodes:
        asset = e.ticker.split("-")[0].replace("KX", "") if e.ticker.startswith("KX") else "UNKNOWN"
        by_asset[asset]["episodes"] += 1
        by_asset[asset]["realized_pnl"] += e.realized_pnl
        by_asset[asset]["fees"] += e.total_fees
        if e.realized_pnl > 0:
            by_asset[asset]["wins"] += 1
        elif e.realized_pnl < 0:
            by_asset[asset]["losses"] += 1

    # Write JSON artifacts
    episode_report_path = output_dir / f"episode_report_fifo_{ts}.json"
    episode_report = {
        "generated_at": _now_iso(),
        "method": "FIFO",
        "fill_source": str(Path(args.fills)),
        "totals": _to_json_safe({
            "episodes": len(episodes),
            "realized_pnl_usd": total_realized_pnl,
            "total_fees_usd": total_fees,
            "residual_settlement_pnl_usd": residual_settlement_pnl,
            "residual_open_markets": len([r for r in residuals if r.status == "OPEN"]),
            "residual_open_contracts_cc": residual_open_cc,
        }),
        "by_asset": _to_json_safe(dict(by_asset)),
        "episodes": _to_json_safe(episodes),
        "residuals": _to_json_safe(residuals),
    }
    _safe_json_dump(episode_report_path, episode_report)
    logger.info("Wrote episode report: %s", episode_report_path)

    reconciliation_path = output_dir / f"reconciliation_{ts}.json"
    _safe_json_dump(reconciliation_path, reconciliation)
    logger.info("Wrote reconciliation: %s", reconciliation_path)

    exceptions_path = output_dir / f"position_reconstruction_exceptions_{ts}.json"
    exception_report = {
        "generated_at": _now_iso(),
        "total_exceptions": len(exceptions),
        "exceptions": _to_json_safe(exceptions),
    }
    _safe_json_dump(exceptions_path, exception_report)
    logger.info("Wrote exceptions: %s", exceptions_path)

    # Human-readable txt report
    txt_path = output_dir / f"episode_report_fifo_{ts}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("FIFO EPISODE RECONCILIATION\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Generated: {reconciliation['generated_at']}\n")
        f.write(f"Method: FIFO per-ticker signed-YES lots\n")
        f.write(f"Fill source: {args.fills}\n\n")

        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Total fills: {len(raw_fills)}\n")
        f.write(f"  Unique canonical fills: {len(canonical_fills)}\n")
        f.write(f"  FIFO episodes: {len(episodes)}\n")
        f.write(f"  Realized PnL: ${total_realized_pnl:.4f}\n")
        f.write(f"  Total fees paid: ${total_fees:.4f}\n")
        f.write(f"  Residual settlement PnL: ${residual_settlement_pnl:.4f}\n")
        f.write(f"  Residual open contracts (centi): {residual_open_cc}\n")
        f.write(f"  Residual open markets: {len([r for r in residuals if r.status == 'OPEN'])}\n")
        f.write(f"  Position reconstruction exceptions: {len(exceptions)}\n\n")

        f.write("CASH RECONCILIATION\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Kalshi balance: ${balance_usd:.4f}\n")
        f.write(f"  Total deposits: ${deposits_usd:.4f}\n")
        f.write(f"  Total withdrawals: ${withdrawals_usd:.4f}\n")
        f.write(f"  Net deposits: ${net_deposits:.4f}\n")
        f.write(f"  Expected balance (net deposits + realized + residual): ${expected_balance_from_trades:.4f}\n")
        f.write(f"  Reconciliation difference: ${reconciliation_diff:.4f}\n\n")

        f.write("BY ASSET\n")
        f.write("-" * 80 + "\n")
        for asset in sorted(by_asset.keys()):
            d = by_asset[asset]
            win_rate = 0.0
            total_closed = d["wins"] + d["losses"]
            if total_closed > 0:
                win_rate = d["wins"] / total_closed * 100
            f.write(f"{asset}:\n")
            f.write(f"  Episodes: {d['episodes']}\n")
            f.write(f"  Realized PnL: ${d['realized_pnl']:.4f}\n")
            f.write(f"  Fees: ${d['fees']:.4f}\n")
            f.write(f"  Wins: {d['wins']}, Losses: {d['losses']}\n")
            f.write(f"  Win rate: {win_rate:.1f}%\n\n")

        f.write("TOP 20 LOSING EPISODES\n")
        f.write("-" * 80 + "\n")
        for e in sorted(episodes, key=lambda x: x.realized_pnl)[:20]:
            f.write(f"{e.open_time} -> {e.close_time} | {e.ticker} | qty={e.quantity_cc}cc | "
                    f"open=${e.open_price:.4f} close=${e.close_price:.4f} | "
                    f"PnL=${e.realized_pnl:.4f} | fees=${e.total_fees:.4f}\n")

        f.write("\nTOP 20 WINNING EPISODES\n")
        f.write("-" * 80 + "\n")
        for e in sorted(episodes, key=lambda x: x.realized_pnl, reverse=True)[:20]:
            f.write(f"{e.open_time} -> {e.close_time} | {e.ticker} | qty={e.quantity_cc}cc | "
                    f"open=${e.open_price:.4f} close=${e.close_price:.4f} | "
                    f"PnL=${e.realized_pnl:.4f} | fees=${e.total_fees:.4f}\n")

        f.write("\n" + "=" * 80 + "\n")

    logger.info("Wrote human-readable report: %s", txt_path)
    print(f"RECONCILED. Output in {output_dir}")


if __name__ == "__main__":
    main()
