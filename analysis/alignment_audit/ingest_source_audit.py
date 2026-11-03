import sqlite3, json

c = sqlite3.connect('data/kalshi_fills.db')
c.row_factory = sqlite3.Row

print("== fills by ingestion_source ==")
for r in c.execute(
    "SELECT ingestion_source, COUNT(*) n, SUM(side_conflict) sc, SUM(exposure_mismatch) em "
    "FROM kalshi_fills GROUP BY ingestion_source ORDER BY n DESC"
):
    print(dict(r))

print("\n== websocket-sourced fills: labels vs delta ==")
for r in c.execute(
    "SELECT market_ticker, side, action, execution_outcome_side, execution_action, "
    "canonical_position_side, canonical_position_action, canonical_yes_delta_cc, "
    "side_conflict, exposure_mismatch, canonicalization_state, unmatched "
    "FROM kalshi_fills WHERE ingestion_source='websocket' ORDER BY created_time DESC LIMIT 25"
):
    print(json.dumps(dict(r), default=str))
