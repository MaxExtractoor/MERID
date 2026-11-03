import sqlite3, json

c = sqlite3.connect('data/kalshi_fills.db')
c.row_factory = sqlite3.Row
cols = ("fill_id, order_id, client_order_id, ingestion_source, side, action, "
        "execution_price_cents, canonical_leg_price_cents, canonical_position_side, "
        "canonical_position_action, canonical_yes_delta_cc, yes_price_dollars, no_price_dollars")
for r in c.execute(f"SELECT {cols} FROM kalshi_fills WHERE market_ticker='KXSOL15M-26NOV012000-00' AND order_id IS NOT NULL ORDER BY created_time"):
    print(json.dumps(dict(r), indent=None, default=str))
