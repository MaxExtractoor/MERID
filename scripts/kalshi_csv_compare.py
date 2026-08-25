"""
Cross-check the Kalshi CSV activity export against the API-derived audit.

The CSV contains no explicit buy/sell action, so we match each CSV trade to
an API fill by (ticker, timestamp, yes-price, count, side) and borrow the
API's action to drive signed-YES PnL.  The CSV Price_In_Cents is Kalshi's
displayed YES price for both Yes and No direction trades (No-side trades are
reported at the complementary YES price), so matching uses yes_price_dollars.

Output: audit_output_<ts>/csv_api_comparison.txt
"""
import csv
import json
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone


def clean(s: str) -> str:
    return s.strip().strip('"')


def parse_csv(path: Path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = [clean(fn) for fn in reader.fieldnames]
        for row in reader:
            rows.append({fn: clean(row[ofn]) for fn, ofn in zip(fieldnames, reader.fieldnames)})
    return rows


def is_crypto(ticker: str) -> bool:
    return bool(ticker and ticker.startswith("KX") and any(c in ticker for c in ("BTC", "ETH", "SOL", "XRP", "DOGE")))


def is_sports(title: str, ticker: str) -> bool:
    sports = ["NBA", "NFL", "MLB", "NHL", "UFC", "WTAMATCH", "NCAAB", "NCAAM", "NCAAW",
              "NBAGAME", "NBAMVP", "NBAPTS", "NBASPREAD", "NBATOTAL", "NCAAMBGAME",
              "NCAABBGAME", "NCAAMBSPREAD", "NCAAWBGAME", "NHLGAME", "MLBWORLD"]
    return any(k in f"{title} {ticker}".upper() for k in sports)


def is_manual_crypto(ticker: str) -> bool:
    return is_crypto(ticker) and "15M" not in ticker


def ts_to_dt(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(microsecond=0)
    except Exception:
        return None


def load_api_fills(audit_dir: Path):
    fills = []
    for name in ["kalshi_fills_raw_20260818_153850.json", "kalshi_historical_fills_raw_20260818_153850.json"]:
        p = audit_dir / name
        if p.exists():
            fills.extend(json.load(open(p, encoding="utf-8")).get("fills", []))
    by_id = {}
    for f in fills:
        fid = f.get("fill_id") or f.get("trade_id")
        if fid and fid not in by_id:
            by_id[fid] = f
    return list(by_id.values())


def load_settlements_and_positions(audit_dir: Path):
    settlements = {s["ticker"]: s for s in json.load(open(audit_dir / "kalshi_settlements_raw_20260818_153850.json", encoding="utf-8")).get("settlements", [])}
    positions = {}
    for p in json.load(open(audit_dir / "kalshi_positions_raw_20260818_153850.json", encoding="utf-8")).get("market_positions", []):
        positions[p["ticker"]] = p
    for p in json.load(open(audit_dir / "kalshi_historical_positions_raw_20260818_153850.json", encoding="utf-8")).get("market_positions", []):
        positions[p["ticker"]] = p
    return settlements, positions


def price_cents_from_fill(f: dict) -> int:
    # CSV displays YES price for all trades.
    return int(Decimal(f.get("yes_price_dollars", "0")) * 100)


def signed_delta(side: str, action: str, qty: int) -> int:
    # canonical signed-YES centi-contracts
    if side == "yes" and action == "buy":
        return qty
    if side == "yes" and action == "sell":
        return -qty
    if side == "no" and action == "buy":
        return -qty
    if side == "no" and action == "sell":
        return qty
    return 0


def compute_pnl_for_fills(fills: list, settlements: dict, positions: dict) -> tuple:
    by_ticker = defaultdict(list)
    for f in fills:
        by_ticker[(f.get("market_ticker") or "").upper()].append(f)

    total_pnl = Decimal("0")
    by_source = {"settlement": Decimal("0"), "position": Decimal("0"), "closed_in_fills": Decimal("0")}

    for ticker, fs in by_ticker.items():
        fs.sort(key=lambda x: x.get("created_time", ""))
        yes_pos = 0
        no_pos = 0
        cash = Decimal("0")
        fees = Decimal("0")
        for f in fs:
            side = (f.get("side") or "").lower()
            action = (f.get("action") or "").lower()
            count = Decimal(f.get("count_fp", "0"))
            qty = int(count * 100)
            fee = Decimal(f.get("fee_cost", "0"))
            fees += fee
            p_yes = Decimal(f.get("yes_price_dollars", "0"))
            p_no = Decimal(f.get("no_price_dollars", "0"))
            price = p_yes if side == "yes" else p_no
            d = 1 if action == "buy" else -1
            if side == "yes":
                yes_pos += d * qty
            else:
                no_pos += d * qty
            if action == "buy":
                cash -= price * count + fee
            else:
                cash += price * count - fee

        if yes_pos == 0 and no_pos == 0:
            total_pnl += cash
            by_source["closed_in_fills"] += cash
        else:
            s = settlements.get(ticker)
            p = positions.get(ticker)
            if s is not None:
                value = Decimal(str(s.get("value", 0))) / Decimal("100")
                payout = (Decimal(yes_pos) / 100) * value + (Decimal(no_pos) / 100) * (1 - value)
                pnl = cash + payout
                total_pnl += pnl
                by_source["settlement"] += pnl
            elif p is not None:
                realized = Decimal(str(p.get("realized_pnl_dollars", "0")))
                fees_paid = Decimal(str(p.get("fees_paid_dollars", "0")))
                pnl = realized - fees_paid
                total_pnl += pnl
                by_source["position"] += pnl
    return total_pnl, by_source


def build_api_index(api_fills):
    idx = defaultdict(list)
    for f in api_fills:
        t = ts_to_dt(f.get("created_time", ""))
        if t is None:
            continue
        side = (f.get("side") or "").lower()
        key = (
            (f.get("market_ticker") or "").upper(),
            t,
            price_cents_from_fill(f),
            Decimal(f.get("count_fp", "0")),
            side,
        )
        idx[key].append(f)
    return idx


def parse_price_cents(raw: str) -> int:
    try:
        return int((Decimal(raw) * Decimal("1")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0


def aggregate_csv_trades(rows: list) -> list:
    """Kalshi sometimes splits one fill into 0.99 + 0.01 rows. Aggregate by
    (ticker, second, direction, yes-price-cents) so we can match the API fill."""
    grouped = defaultdict(lambda: {
        "count": Decimal("0"),
        "fee": Decimal("0"),
        "ts": None,
        "ticker": "",
        "side": "",
        "price_cents": 0,
    })
    for r in rows:
        if r.get("type") != "Trade":
            continue
        ticker = (r.get("Market_Ticker") or "").upper()
        side = (r.get("Direction") or "").lower()
        t = ts_to_dt(r.get("Original_Date", ""))
        if t is None:
            continue
        price_cents = parse_price_cents(r.get("Price_In_Cents") or "0")
        key = (ticker, t, side, price_cents)
        g = grouped[key]
        g["count"] += Decimal(r.get("Amount_In_Dollars") or "0")
        g["fee"] += Decimal(r.get("Fee_In_Dollars") or "0")
        g["ts"] = r.get("Original_Date")
        g["ticker"] = ticker
        g["side"] = side
        g["price_cents"] = price_cents

    return [{
        "type": "Trade",
        "Market_Ticker": g["ticker"],
        "Direction": g["side"].capitalize(),
        "Price_In_Cents": str(g["price_cents"]),
        "Amount_In_Dollars": str(g["count"]),
        "Fee_In_Dollars": str(g["fee"]),
        "Original_Date": g["ts"],
    } for g in grouped.values()]


def match_csv_to_api(r: dict, api_idx: dict, api_fills: list):
    ticker = (r.get("Market_Ticker") or "").upper()
    side = (r.get("Direction") or "").lower()
    price_cents = parse_price_cents(r.get("Price_In_Cents") or "0")
    count = Decimal(r.get("Amount_In_Dollars") or "0")
    t = ts_to_dt(r.get("Original_Date", ""))
    if t is None:
        return None

    key = (ticker, t, price_cents, count, side)
    if key in api_idx:
        return api_idx[key][0]

    # Fallback: ignore fractional-cent count differences
    for f in api_fills:
        ft = ts_to_dt(f.get("created_time", ""))
        if ft and (f.get("market_ticker") or "").upper() == ticker and ft == t:
            fp = price_cents_from_fill(f)
            fcount = Decimal(f.get("count_fp", "0"))
            if abs(fp - price_cents) <= 1 and abs(fcount - count) <= Decimal("0.02"):
                return f
    return None


def main():
    csv_path = Path("C:/Users/Chris/Downloads/Kalshi-Recent-Activity-All.csv")
    audit_dir = Path("audit_output_20260818_153850")

    rows = parse_csv(csv_path)
    api_fills = load_api_fills(audit_dir)
    api_idx = build_api_index(api_fills)
    settlements, positions = load_settlements_and_positions(audit_dir)

    # Cash flows
    deposits = sum(Decimal(r.get("Amount_In_Dollars") or "0")
                   for r in rows if r.get("type") == "Deposit" and r.get("Status") == "Applied")
    withdrawals = sum(Decimal(r.get("Amount_In_Dollars") or "0")
                      for r in rows if r.get("type") == "Withdrawal" and r.get("Status") in ("Applied", "Confirmed", "Success"))
    credits = sum(Decimal(r.get("Amount_In_Dollars") or "0")
                  for r in rows if r.get("type") == "Credit")
    csv_fees = sum(Decimal(r.get("Fee_In_Dollars") or "0")
                   for r in rows if r.get("type") == "Trade")

    # Filter to crypto and exclude sports
    crypto_rows = [r for r in rows if is_crypto(r.get("Market_Ticker", ""))]
    non_sports = [r for r in crypto_rows if not is_sports(r.get("Market_Title", ""), r.get("Market_Ticker", ""))]

    # Manual vs bot from CSV (manual = non-15M crypto ticker)
    manual_tickers = set()
    bot_tickers = set()
    for r in non_sports:
        if r.get("type") != "Trade":
            continue
        t = (r.get("Market_Ticker") or "").upper()
        if is_manual_crypto(t):
            manual_tickers.add(t)
        else:
            bot_tickers.add(t)

    # API fills partitioned the same way
    manual_fills = [f for f in api_fills if is_manual_crypto((f.get("market_ticker") or "").upper())]
    bot_fills = [f for f in api_fills if (f.get("market_ticker") or "").upper() in bot_tickers]
    all_crypto_non_sports_fills = [f for f in api_fills if (f.get("market_ticker") or "").upper() in (manual_tickers | bot_tickers)]

    all_pnl, all_src = compute_pnl_for_fills(all_crypto_non_sports_fills, settlements, positions)
    manual_pnl, _ = compute_pnl_for_fills(manual_fills, settlements, positions)
    bot_pnl, _ = compute_pnl_for_fills(bot_fills, settlements, positions)

    # 15M bot vs likely manual-exit splits. Manual exits are often Maker orders on 15M tickers.
    m15_maker = [f for f in bot_fills if f.get("is_taker") is False]
    m15_taker = [f for f in bot_fills if f.get("is_taker") is True]
    m15_maker_pnl, _ = compute_pnl_for_fills(m15_maker, settlements, positions)
    m15_taker_pnl, _ = compute_pnl_for_fills(m15_taker, settlements, positions)

    # CSV-to-API match quality (using aggregated CSV trades)
    aggregated = aggregate_csv_trades(non_sports)
    matched = []
    unmatched = []
    side_mismatches = 0
    price_mismatches = 0
    count_mismatches = 0

    for r in aggregated:
        f = match_csv_to_api(r, api_idx, api_fills)
        if f is None:
            unmatched.append(r)
            continue
        api_side = (f.get("side") or "").lower()
        csv_side = (r.get("Direction") or "").lower()
        if api_side != csv_side:
            side_mismatches += 1
        if abs(price_cents_from_fill(f) - parse_price_cents(r.get("Price_In_Cents") or "0")) > 1:
            price_mismatches += 1
        if abs(Decimal(f.get("count_fp", "0")) - Decimal(r.get("Amount_In_Dollars") or "0")) > Decimal("0.02"):
            count_mismatches += 1
        matched.append((r, f))

    # Balance
    balance = Decimal("0")
    try:
        balance_raw = json.load(open(audit_dir / "kalshi_balance_raw_20260818_153850.json", encoding="utf-8"))
        raw = balance_raw.get("raw", balance_raw)
        balance = Decimal(str(raw.get("balance_dollars", "0")))
    except Exception:
        pass
    net_deposits = deposits - withdrawals
    implied_total_pnl = balance - net_deposits

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(f"audit_output_csv_compare_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "csv_api_comparison.txt"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("KALSHI CSV ACTIVITY vs API AUDIT COMPARISON\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"CSV file: {csv_path}\n")
        f.write(f"Audit dir: {audit_dir}\n\n")

        f.write("CSV ACTIVITY COUNTS\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Total rows:                 {len(rows)}\n")
        f.write(f"  Orders:                     {sum(1 for r in rows if r.get('type') == 'Order')}\n")
        f.write(f"  Trades:                     {sum(1 for r in rows if r.get('type') == 'Trade')}\n")
        f.write(f"  Deposits:                   {sum(1 for r in rows if r.get('type') == 'Deposit')}\n")
        f.write(f"  Withdrawals:                {sum(1 for r in rows if r.get('type') == 'Withdrawal')}\n")
        f.write(f"  Credits:                    {sum(1 for r in rows if r.get('type') == 'Credit')}\n")
        f.write(f"  Crypto rows:                {len(crypto_rows)}\n")
        f.write(f"  Crypto non-sports rows:     {len(non_sports)}\n")
        f.write(f"  Unique crypto tickers:      {len({r.get('Market_Ticker','').upper() for r in non_sports if r.get('type')=='Trade'})}\n")
        f.write(f"  Manual crypto tickers:      {len(manual_tickers)}\n")
        f.write(f"  Bot (15M) crypto tickers:   {len(bot_tickers)}\n\n")

        f.write("CASH FLOW COMPARISON\n")
        f.write("-" * 80 + "\n")
        f.write(f"  CSV deposits:               ${deposits:.4f}\n")
        f.write(f"  CSV withdrawals:            ${withdrawals:.4f}\n")
        f.write(f"  CSV credits:                ${credits:.4f}\n")
        f.write(f"  CSV net deposits:           ${net_deposits:.4f}\n")
        f.write(f"  CSV trade fees:             ${csv_fees:.4f}\n")
        f.write(f"  API balance:                ${balance:.4f}\n")
        f.write(f"  Implied total PnL:          ${implied_total_pnl:.4f}\n\n")

        f.write("PNL (all API crypto non-sports fills, signed-YES model)\n")
        f.write("-" * 80 + "\n")
        f.write(f"  All crypto non-sports:      ${all_pnl:.4f}\n")
        f.write(f"  - Manual crypto:            ${manual_pnl:.4f}\n")
        f.write(f"  - Bot (15M) crypto:         ${bot_pnl:.4f}\n")
        f.write(f"    - 15M Taker (bot):        ${m15_taker_pnl:.4f}\n")
        f.write(f"    - 15M Maker (manual exits): ${m15_maker_pnl:.4f}\n")
        f.write(f"  PnL source - settlements:   ${all_src['settlement']:.4f}\n")
        f.write(f"  PnL source - positions:     ${all_src['position']:.4f}\n")
        f.write(f"  PnL source - closed fills:  ${all_src['closed_in_fills']:.4f}\n")
        f.write(f"  Reconciliation gap:         ${implied_total_pnl - all_pnl:.4f}\n\n")

        f.write("CSV-TO-API MATCH QUALITY\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Aggregated CSV trade legs:  {len(aggregated)}\n")
        f.write(f"  Matched to API fills:       {len(matched)}\n")
        f.write(f"  Unmatched:                  {len(unmatched)}\n")
        f.write(f"  Side mismatches:            {side_mismatches}\n")
        f.write(f"  Price mismatches (>1c):     {price_mismatches}\n")
        f.write(f"  Count mismatches (>0.01):   {count_mismatches}\n\n")

        f.write("UNMATCHED CSV TRADES (first 20)\n")
        f.write("-" * 80 + "\n")
        for r in unmatched[:20]:
            f.write(f"  {r.get('Original_Date',''):24} | {r.get('Market_Ticker',''):35} | "
                    f"{r.get('Direction',''):5} | {r.get('Price_In_Cents',''):5}c | "
                    f"{r.get('Amount_In_Dollars',''):6} | fee ${r.get('Fee_In_Dollars','0'):>7}\n")

        # Manual crypto breakdown
        f.write("\nMANUAL CRYPTO TRADES (tickers not in 15M series)\n")
        f.write("-" * 80 + "\n")
        for t in sorted(manual_tickers)[:30]:
            f.write(f"  {t}\n")

    print(f"Comparison complete. Report: {out_path}")
    with open(out_path, encoding="utf-8") as f:
        print(f.read())


if __name__ == "__main__":
    main()
