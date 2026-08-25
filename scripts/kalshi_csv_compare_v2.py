"""
Cross-check Kalshi CSV activity export against the API fill/audit data.
Since the CSV does not contain an explicit buy/sell action, we match each
CSV trade to the API fills by (ticker, time, price, count, side) and use
the API's action to reconstruct signed-YES exposure and PnL.
"""
import csv
import json
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone


def clean(s: str) -> str:
    return s.strip().strip('"')


def is_crypto(ticker: str) -> bool:
    return bool(ticker and ticker.startswith("KX") and any(c in ticker for c in ("BTC", "ETH", "SOL", "XRP", "DOGE")))


def is_sports(title: str, ticker: str) -> bool:
    sports = ["NBA", "NFL", "MLB", "NHL", "UFC", "WTAMATCH", "NCAAB", "NCAAM", "NCAAW",
              "NBAGAME", "NBAMVP", "NBAPTS", "NBASPREAD", "NBATOTAL", "NCAAMBGAME",
              "NCAABBGAME", "NCAAMBSPREAD", "NCAAWBGAME", "NHLGAME", "MLBWORLD"]
    text = f"{title} {ticker}".upper()
    return any(k in text for k in sports)


def is_manual_crypto(ticker: str) -> bool:
    return is_crypto(ticker) and "15M" not in ticker


def parse_csv(path: Path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = [clean(fn) for fn in reader.fieldnames]
        for row in reader:
            r = {fn: clean(row[ofn]) for fn, ofn in zip(fieldnames, reader.fieldnames)}
            rows.append(r)
    return rows


def load_api_fills(audit_dir: Path):
    fills = []
    for name in ["kalshi_fills_raw_20260818_153850.json", "kalshi_historical_fills_raw_20260818_153850.json"]:
        p = audit_dir / name
        if p.exists():
            data = json.load(open(p))
            fills.extend(data.get("fills", []))
    # dedupe
    by_id = {}
    for f in fills:
        fid = f.get("fill_id") or f.get("trade_id")
        if fid:
            by_id[fid] = f
    return list(by_id.values())


def to_api_key(ticker: str, ts: str, price_cents: int, count: Decimal, side: str) -> tuple:
    # API created_time is ISO with microseconds; CSV Original_Date is ISO with Z
    # Normalize to nearest second for matching
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        t = t.replace(microsecond=0)
    except Exception:
        t = None
    # side: CSV Direction Yes/No -> API yes/no
    s = side.lower() if side else ""
    return (ticker, t, price_cents, count, s)


def build_api_index(api_fills):
    idx = defaultdict(list)
    for f in api_fills:
        ts = f.get("created_time", "")
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            t = t.replace(microsecond=0)
        except Exception:
            t = None
        side = (f.get("side") or "").lower()
        try:
            price_cents = int(Decimal(f.get("yes_price_dollars", "0")) * 100) if side == "yes" else int(Decimal(f.get("no_price_dollars", "0")) * 100)
        except Exception:
            price_cents = 0
        count = Decimal(f.get("count_fp", "0"))
        key = (f.get("market_ticker", "").upper(), t, price_cents, count, side)
        idx[key].append(f)
    return idx


def canonical_delta(side: str, action: str, count: Decimal) -> int:
    qty = int(count * 100)
    if side == "yes" and action == "buy":
        return qty
    if side == "yes" and action == "sell":
        return -qty
    if side == "no" and action == "buy":
        return -qty
    if side == "no" and action == "sell":
        return qty
    return 0


def main():
    csv_path = Path("C:/Users/Chris/Downloads/Kalshi-Recent-Activity-All.csv")
    audit_dir = Path("audit_output_20260818_153850")

    rows = parse_csv(csv_path)
    api_fills = load_api_fills(audit_dir)
    api_idx = build_api_index(api_fills)

    # stats
    n_orders = sum(1 for r in rows if r.get("type") == "Order")
    n_trades = sum(1 for r in rows if r.get("type") == "Trade")
    n_deposits = sum(1 for r in rows if r.get("type") == "Deposit")
    n_withdrawals = sum(1 for r in rows if r.get("type") == "Withdrawal")
    n_credits = sum(1 for r in rows if r.get("type") == "Credit")

    deposits = sum(Decimal(r.get("Amount_In_Dollars") or "0") for r in rows if r.get("type") == "Deposit" and r.get("Status") == "Applied")
    withdrawals = sum(Decimal(r.get("Amount_In_Dollars") or "0") for r in rows if r.get("type") == "Withdrawal" and r.get("Status") in ("Applied", "Confirmed", "Success"))
    credits = sum(Decimal(r.get("Amount_In_Dollars") or "0") for r in rows if r.get("type") == "Credit")
    csv_fees = sum(Decimal(r.get("Fee_In_Dollars") or "0") for r in rows if r.get("type") == "Trade")

    # crypto rows
    crypto = [r for r in rows if is_crypto(r.get("Market_Ticker", ""))]
    non_sports = [r for r in crypto if not is_sports(r.get("Market_Title", ""), r.get("Market_Ticker", ""))]
    manual = [r for r in non_sports if is_manual_crypto(r.get("Market_Ticker", ""))]

    # match trades to API fills
    matched = 0
    unmatched = []
    side_mismatches = 0
    price_mismatches = 0
    count_mismatches = 0
    matched_trades = []

    for r in non_sports:
        if r.get("type") != "Trade":
            continue
        ticker = r.get("Market_Ticker", "").upper()
        side = r.get("Direction", "").lower()
        price_cents = int(r.get("Price_In_Cents") or 0)
        count = Decimal(r.get("Amount_In_Dollars") or "0")
        ts = r.get("Original_Date", "")
        key = to_api_key(ticker, ts, price_cents, count, side)
        candidates = api_idx.get(key, [])
        # fallback ignoring count (fraction/rounding) and side (inversion?)
        if not candidates:
            # try without count and side
            for f in api_fills:
                fts = f.get("created_time", "")
                try:
                    ft = datetime.fromisoformat(fts.replace("Z", "+00:00")).replace(microsecond=0)
                except Exception:
                    continue
                if f.get("market_ticker", "").upper() == ticker and ft == key[1]:
                    candidates.append(f)
        if not candidates:
            unmatched.append(r)
            continue
        f = candidates[0]
        matched += 1
        api_side = (f.get("side") or "").lower()
        if api_side != side:
            side_mismatches += 1
        # compare price
        api_price = Decimal(f.get("yes_price_dollars" if api_side == "yes" else "no_price_dollars", "0"))
        csv_price = Decimal(price_cents) / 100
        if abs(api_price - csv_price) > Decimal("0.0001"):
            price_mismatches += 1
        # compare count
        api_count = Decimal(f.get("count_fp", "0"))
        if abs(api_count - count) > Decimal("0.0001"):
            count_mismatches += 1
        matched_trades.append((r, f))

    # compute PnL from matched trades using API action
    by_ticker = defaultdict(list)
    for r, f in matched_trades:
        ticker = f.get("market_ticker", "").upper()
        side = (f.get("side") or "").lower()
        action = (f.get("action") or "").lower()
        count = Decimal(f.get("count_fp", "0"))
        fee = Decimal(f.get("fee_cost", "0"))
        p_yes = Decimal(f.get("yes_price_dollars", "0"))
        p_no = Decimal(f.get("no_price_dollars", "0"))
        p = p_yes if side == "yes" else p_no
        delta = canonical_delta(side, action, count)
        by_ticker[ticker].append({
            "created_time": f.get("created_time"),
            "delta": delta,
            "price_yes": p_yes,
            "price": p,
            "fee": fee,
        })

    # Load settlements and positions
    settlements = {s["ticker"]: s for s in json.load(open(audit_dir / "kalshi_settlements_raw_20260818_153850.json")).get("settlements", [])}
    positions = {}
    for p in json.load(open(audit_dir / "kalshi_positions_raw_20260818_153850.json")).get("market_positions", []):
        positions[p["ticker"]] = p
    for p in json.load(open(audit_dir / "kalshi_historical_positions_raw_20260818_153850.json")).get("market_positions", []):
        positions[p["ticker"]] = p

    total_pnl = Decimal("0")
    for ticker, fs in by_ticker.items():
        fs.sort(key=lambda x: x["created_time"])
        yes_pos = sum(x["delta"] for x in fs)
        cash = Decimal("0")
        for x in fs:
            # cash flow: if delta > 0 (long YES/short NO buy?), use action to determine sign
            # But we have delta only. We can use actual leg price and delta sign.
            # delta > 0 means long YES or short NO. For a buy, cash = -price*count - fee.
            # For a sell, cash = +price*count - fee.
            # The delta sign alone doesn't tell buy/sell for NO side.
            # We need the actual action. Reconstruct from fill.
            pass
