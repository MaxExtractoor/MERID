"""Deep audit — fills cohort + round-trips FIRST (small DB), live audit LAST.

One-shot script. Read-only everywhere.
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

AUDIT = Path(r"C:\Dev\MERID\data\decision_audit.db")
FILLS = Path(r"C:\Dev\MERID\data\kalshi_fills.db")

conn2 = sqlite3.connect(f"file:{FILLS.as_posix()}?mode=ro", uri=True, timeout=15)
c2 = conn2.cursor()

print("########## 1. Entry-buy price bands by month ##########")
for r in c2.execute("""
    SELECT substr(created_time,1,7) mo,
           CASE WHEN execution_price_cents < 30 THEN 'a_<30'
                WHEN execution_price_cents < 60 THEN 'b_30-60'
                WHEN execution_price_cents < 80 THEN 'c_60-80'
                WHEN execution_price_cents < 93 THEN 'd_80-93'
                ELSE 'e_93+' END band,
           COUNT(*) n, ROUND(SUM(proceeds_dollars),2) cash
    FROM kalshi_fills
    WHERE action='buy' AND COALESCE(entry_or_exit,'entry')='entry'
    GROUP BY mo, band ORDER BY mo, band"""):
    print(r)

print("\n########## 2. Fills by asset x action ##########")
for r in c2.execute("""
    SELECT CASE WHEN market_ticker LIKE 'KXBTC%' THEN 'BTC'
                WHEN market_ticker LIKE 'KXETH%' THEN 'ETH'
                WHEN market_ticker LIKE 'KXSOL%' THEN 'SOL'
                WHEN market_ticker LIKE 'KXXRP%' THEN 'XRP'
                WHEN market_ticker LIKE 'KXDOGE%' THEN 'DOGE'
                ELSE '?' END asset,
           action, COUNT(*), ROUND(SUM(proceeds_dollars),2)
    FROM kalshi_fills GROUP BY asset, action ORDER BY asset, action"""):
    print(r)

print("\n########## 3. Round-trip net per ticker ##########")
pos = defaultdict(list)
for tkr, action, price, proceeds, ts, eo in c2.execute(
        "SELECT market_ticker, action, execution_price_cents, proceeds_dollars, "
        "created_time, entry_or_exit FROM kalshi_fills ORDER BY created_time"):
    pos[tkr].append((action, price, proceeds, ts, eo))
wins = losses = 0
rt_pnl = 0.0
for tkr, legs in pos.items():
    net = sum(p for _,_,p,_,_ in legs)
    buys = sum(1 for a,_,_,_,eo in legs if a=='buy')
    sells = sum(1 for a,_,_,_,eo in legs if a=='sell')
    if buys and sells:
        rt_pnl += net
        if net > 0: wins += 1
        else: losses += 1
        if abs(net) > 0.10:
            print(f"  {tkr}: net={net:+.2f} ({buys}b/{sells}s)")
print(f"closed-ticker net cash={rt_pnl:+.2f} wins={wins} losses={losses}")
conn2.close()

print("\n########## 4. LIVE DB (indexed decision_ts bounds, immutable) ##########")
try:
    conn = sqlite3.connect(f"file:{AUDIT.as_posix()}?mode=ro&immutable=1", uri=True, timeout=30)
    c = conn.cursor()
    print("bounds:", c.execute(
        "SELECT MIN(decision_ts), MAX(decision_ts) FROM strategy_decisions").fetchone())
    # outcome_status counts — outcomes table is 1:1 with decisions; scan once
    print("outcome_status:", c.execute(
        "SELECT outcome_status, COUNT(*), ROUND(SUM(realized_net_pnl_cents)/100.0,2) "
        "FROM strategy_decision_outcomes GROUP BY 1").fetchall())
    conn.close()
except Exception as e:
    print("LIVE DB ERR:", e)
