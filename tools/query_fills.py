import sqlite3
import json
import sys
from decimal import Decimal

db = 'C:/Dev/MERID/data/kalshi_fills.db'
conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
c = conn.cursor()

# recent 20 fills
c.execute("""SELECT fill_id, market_ticker, side, action, count_fp, yes_price_dollars, no_price_dollars, proceeds_dollars, fee_cost, created_time,
                        canonical_position_side, canonical_position_action, canonical_leg_price_cents, quantity_cc, is_exit
             FROM kalshi_fills ORDER BY created_time DESC LIMIT 30""")
rows = c.fetchall()
for r in rows:
    (fill_id, ticker, side, action, count_fp, yes_price, no_price, proceeds, fee, ts,
     canonical_side, canonical_action, leg_price, qty_cc, is_exit) = r
    print(f"{ts} | {ticker} | ledger={side}/{action} can={canonical_side}/{canonical_action} | count={count_fp} qty_cc={qty_cc} leg={leg_price} | yes={yes_price} no={no_price} proceeds={proceeds} fee={fee} exit={is_exit} | fill={fill_id}")

# show columns for ticker containing 26AUG262200 (the current session / expiry)
print("\n--- 22:00 expiry fills ---")
c.execute("""SELECT fill_id, market_ticker, side, action, count_fp, yes_price_dollars, no_price_dollars, proceeds_dollars, fee_cost, created_time,
                        canonical_position_side, canonical_position_action, canonical_leg_price_cents, quantity_cc, is_exit
             FROM kalshi_fills WHERE market_ticker LIKE '%26AUG262200%' ORDER BY created_time DESC""")
for r in c.fetchall():
    print(r)

conn.close()
