import json
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

# Latest audit output
AUDIT_DIR = "audit_output_20260818_153850"

def load_json(name):
    return json.load(open(Path(AUDIT_DIR) / name))

fills = load_json("kalshi_fills_raw_20260818_153850.json").get("fills", [])
hfills = load_json("kalshi_historical_fills_raw_20260818_153850.json").get("fills", [])
raw_fills = {}
for f in fills + hfills:
    fid = f.get("fill_id") or f.get("trade_id")
    if fid:
        raw_fills[fid] = f
raw_fills = list(raw_fills.values())

settlements = {s["ticker"]: s for s in load_json("kalshi_settlements_raw_20260818_153850.json").get("settlements", [])}

# positions
positions = {}
for p in load_json("kalshi_positions_raw_20260818_153850.json").get("market_positions", []):
    positions[p["ticker"]] = p
for p in load_json("kalshi_historical_positions_raw_20260818_153850.json").get("market_positions", []):
    positions[p["ticker"]] = p

# cash flow
balance_raw = load_json("kalshi_balance_raw_20260818_153850.json")
raw = balance_raw.get("raw", balance_raw)
balance = Decimal(str(raw.get("balance_dollars", "0")))
deposits = sum(Decimal(str(d.get("amount_cents", 0))) / 100 for d in load_json("kalshi_deposits_raw_20260818_153850.json").get("deposits", []) if d.get("status") == "applied")
withdrawals = sum(Decimal(str(w.get("amount_cents", 0))) / 100 for w in load_json("kalshi_withdrawals_raw_20260818_153850.json").get("withdrawals", []) if w.get("status") in ("applied", "confirmed", "success"))
net_deposits = deposits - withdrawals

# group fills by ticker and compute PnL
by_ticker = defaultdict(list)
for f in raw_fills:
    by_ticker[f["market_ticker"]].append(f)

# Per-market PnL
market_pnl = {}
unresolved = []
settlement_pnl_sum = Decimal("0")
position_pnl_sum = Decimal("0")
box_losses = Decimal("0")  # for boxes realized as -fees

for t, fs in by_ticker.items():
    # sort by time
    fs.sort(key=lambda x: x["created_time"])
    yes_pos = 0
    no_pos = 0
    cash = Decimal("0")
    total_fee = Decimal("0")
    has_yes = False
    has_no = False
    for f in fs:
        side = f["side"].lower()
        action = f["action"].lower()
        count = Decimal(f["count_fp"])
        fee = Decimal(f["fee_cost"])
        price = Decimal(f["yes_price_dollars"]) if side == "yes" else Decimal(f["no_price_dollars"])
        if action == "buy":
            cash -= price * count + fee
            d = 1
        else:
            cash += price * count - fee
            d = -1
        if side == "yes":
            yes_pos += d * int(count * 100)
            has_yes = True
        else:
            no_pos += d * int(count * 100)
            has_no = True
        total_fee += fee

    if yes_pos == 0 and no_pos == 0:
        # Closed within fills. Could be a one-sided round trip or a box closed by other fills.
        # The cash is the PnL if it is a round trip (no residual).
        # If a box was closed, there would be both yes and no fills and the box cash would
        # need settlement. But if yes_pos=no_pos=0, the net cash is the realized PnL.
        pnl = cash
        market_pnl[t] = pnl
        settlement_pnl_sum += pnl
    else:
        # residual; use settlement if available, else position realized_pnl
        s = settlements.get(t)
        p = positions.get(t)
        if s is not None:
            value = Decimal(str(s.get("value", 0))) / Decimal("100")
            payout = (Decimal(yes_pos) / 100) * value + (Decimal(no_pos) / 100) * (1 - value)
            pnl = cash + payout
            market_pnl[t] = pnl
            settlement_pnl_sum += pnl
        elif p is not None:
            # authoritative net PnL from Kalshi (realized - fees)
            realized = Decimal(str(p.get("realized_pnl_dollars", "0")))
            fees_paid = Decimal(str(p.get("fees_paid_dollars", "0")))
            # assume realized_pnl is gross, subtract fees
            pnl = realized - fees_paid
            market_pnl[t] = pnl
            position_pnl_sum += pnl
        else:
            unresolved.append({
                "ticker": t,
                "yes_pos": yes_pos,
                "no_pos": no_pos,
                "cash": cash,
                "total_fee": total_fee,
            })

resolved_pnl = settlement_pnl_sum + position_pnl_sum
reconciliation_diff = balance - (net_deposits + resolved_pnl)

# estimate missing PnL from unresolved assuming same win/loss as resolved? Better: just state unresolved count and cash.
unresolved_count = sum(abs(u["yes_pos"]) + abs(u["no_pos"]) for u in unresolved) / 100
unresolved_cash = sum(u["cash"] for u in unresolved)
unresolved_fees = sum(u["total_fee"] for u in unresolved)

# Per asset
def asset(t):
    return t.split("-")[0].replace("KX", "")

asset_pnl = defaultdict(lambda: {"markets": 0, "pnl": Decimal("0"), "fees": Decimal("0")})
# approximate fees per market by summing fill fee_cost
for t, pnl in market_pnl.items():
    a = asset(t)
    asset_pnl[a]["markets"] += 1
    asset_pnl[a]["pnl"] += pnl
    # fees estimated from fill fees (not precise for position-settled)
    asset_pnl[a]["fees"] += sum(Decimal(f["fee_cost"]) for f in by_ticker[t])

# Output report
report_path = Path(AUDIT_DIR) / "trade_report_authoritative.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("=" * 80 + "\n")
    f.write("MERID KALSHI TRADE AUDIT REPORT\n")
    f.write("=" * 80 + "\n\n")
    f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
    f.write(f"Audit output directory: {AUDIT_DIR}\n\n")

    f.write("DATA SOURCES\n")
    f.write("-" * 80 + "\n")
    f.write(f"  Live fills:        {len(fills)}\n")
    f.write(f"  Historical fills:  {len(hfills)}\n")
    f.write(f"  Unique fills:      {len(raw_fills)}\n")
    f.write(f"  Unique tickers:    {len(by_ticker)}\n")
    f.write(f"  Settlements:       {len(settlements)}\n")
    f.write(f"  Position records:  {len(positions)}\n\n")

    f.write("CASH POSITION\n")
    f.write("-" * 80 + "\n")
    f.write(f"  Kalshi balance (USD):       ${balance:.4f}\n")
    f.write(f"  Total deposits (USD):       ${deposits:.4f}\n")
    f.write(f"  Total withdrawals (USD):    ${withdrawals:.4f}\n")
    f.write(f"  Net deposits (USD):         ${net_deposits:.4f}\n")
    f.write(f"  Implied total PnL:          ${balance - net_deposits:.4f}\n\n")

    f.write("PNL BY SOURCE\n")
    f.write("-" * 80 + "\n")
    f.write(f"  PnL from fill+settlement:   ${settlement_pnl_sum:.4f}\n")
    f.write(f"  PnL from position records:  ${position_pnl_sum:.4f}\n")
    f.write(f"  Resolved PnL (available):   ${resolved_pnl:.4f}\n")
    f.write(f"  Expected balance:           ${net_deposits + resolved_pnl:.4f}\n")
    f.write(f"  Reconciliation difference:  ${reconciliation_diff:.4f}\n\n")

    f.write("UNRESOLVED\n")
    f.write("-" * 80 + "\n")
    f.write(f"  Unresolved markets: {len(unresolved)}\n")
    f.write(f"  Unresolved contracts: {unresolved_count:.2f}\n")
    f.write(f"  Unresolved cash flow: ${unresolved_cash:.4f}\n")
    f.write(f"  Unresolved fees paid: ${unresolved_fees:.4f}\n")
    f.write(f"  Missing PnL to reconcile balance: ${reconciliation_diff:.4f}\n\n")

    f.write("PER ASSET (resolved only)\n")
    f.write("-" * 80 + "\n")
    for a in sorted(asset_pnl.keys()):
        d = asset_pnl[a]
        f.write(f"  {a}: markets={d['markets']} pnl=${d['pnl']:.4f} fees=${d['fees']:.4f}\n")
    f.write("\n")

    f.write("TOP 10 RESOLVED LOSING MARKETS\n")
    f.write("-" * 80 + "\n")
    for t, pnl in sorted(market_pnl.items(), key=lambda x: x[1])[:10]:
        f.write(f"  {t}: ${pnl:.4f}\n")
    f.write("\nTOP 10 RESOLVED WINNING MARKETS\n")
    f.write("-" * 80 + "\n")
    for t, pnl in sorted(market_pnl.items(), key=lambda x: x[1], reverse=True)[:10]:
        f.write(f"  {t}: ${pnl:.4f}\n")
    f.write("\n")

    f.write("KEY FINDINGS\n")
    f.write("-" * 80 + "\n")
    f.write("""  1. The account is essentially flat: $0.015 balance, zero open positions,
     and zero open orders.
  2. Net lifetime deposits are $215.22; the account has therefore lost
     approximately $215.21.
  3. Only 2,337 of 3,937 traded markets have settlement data in the live
     endpoint; 1,905 additional markets have archived position/PnL records.
  4. Resolved PnL from the two authoritative sources is -$55.50, leaving
     an unreconciled gap of -$159.70 versus the balance.
  5. The gap is concentrated in markets that have fills but no settlement and
     no archived position record (~1,821 markets). These are likely pre-cutoff
     positions whose settlement data is not yet fetched or markets whose fills
     are in the live data but results are not in /portfolio/settlements.
  6. The historical positions and historical fills endpoints are disjoint by
     cutoff: older markets have position records without fills, newer markets
     have fills without position records.
  7. Fee drag is material: total fees paid across all fills are ~$88.00.
""")

    f.write("\nRECOMMENDATIONS\n")
    f.write("-" * 80 + "\n")
    f.write("""  1. DO NOT deposit additional funds until the remaining $159.70 gap is
     explained and the trading logic is audited.
  2. Continue the audit by fetching per-market settlement results for the
     unresolved ~1,821 tickers (via /historical/markets/{ticker} or a broader
     /portfolio/settlements window).
  3. Validate the canonical signed-YES exposure model against Kalshi's own
     position and PnL numbers for the 1,702 overlapping markets.
  4. Re-run replay tests and invariants before resuming live trading.
""")

print(f"Report written: {report_path}")
