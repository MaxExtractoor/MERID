import sqlite3, json

db = sqlite3.connect('file:data/kalshi_fills.db?mode=ro', uri=True, timeout=10)
db.execute('PRAGMA query_only=1')
keep = ('fill_id','order_id','market_ticker','side','action','quantity_cc',
        'yes_price_dollars','no_price_dollars','execution_outcome_side','execution_action',
        'execution_price_cents','canonicalization_state',
        'ingestion_source','fill_source','is_live','unmatched','unmatched_reason',
        'derived_id','side_conflict','side_conflict_reason','exposure_mismatch','client_order_id','created_time')
sel = ','.join(keep)
print('=== all fills on KXSOL15M-26NOV012000 ===')
for r in db.execute(
    f"SELECT {sel} FROM kalshi_fills WHERE market_ticker LIKE '%KXSOL15M-26NOV012000%' "
    "ORDER BY created_time").fetchall():
    print(json.dumps(dict(zip(keep, r)), default=str))
    print('---')

print('=== raw_payload of newest ===')
r = db.execute("SELECT raw_payload FROM kalshi_fills WHERE market_ticker LIKE '%KXSOL15M-26NOV012000%' ORDER BY rowid DESC LIMIT 1").fetchone()
print(r[0][:1500] if r else 'none')

print('=== order attempts for these ===')
db2 = sqlite3.connect('file:data/kalshi_order_attempts.db?mode=ro', uri=True, timeout=10)
for cid in ('merid_c12b3c978ac24e2fa918',):
    row = db2.execute('SELECT status, payload_json FROM order_attempts WHERE client_order_id=?', (cid,)).fetchone()
    print(cid, row[0] if row else 'missing')
    if row: print(row[1][:700])
