"""Settlement counterfactual by fine reject_reason x asset x side x price band.

Uses FIRST rejected record per (ticker, side, reject_reason) as hypothetical entry.
Reports settle P&L (cleanest unbiased outcome) per cohort.
"""
import json, sqlite3, collections, statistics, sys

SINCE = '2026-11-10T00:00:00'
JSONL = 'logs/rejected_candidates.jsonl'

first = {}
n = 0
with open(JSONL, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        if '"rejected_candidate"' not in line: continue
        try: d = json.loads(line)
        except Exception: continue
        ts = d.get('event_ts_utc') or ''
        if ts < SINCE: continue
        n += 1
        reason = d.get('reject_reason') or '?'
        side = d.get('side'); ticker = d.get('ticker')
        px = d.get('executable_price_cents') or d.get('held_price_cents')
        if not ticker or not side or px is None: continue
        key = (ticker, side, reason)
        if key not in first or ts < first[key]['ts']:
            first[key] = dict(ts=ts, ticker=ticker, asset=d.get('asset'), side=side,
                              reason=reason, px=float(px), tte=d.get('tte_seconds'),
                              net_edge=d.get('net_edge'))
print(f'rows={n} keys={len(first)}', file=sys.stderr)

con = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=300)
cur = con.cursor()
tickers = sorted({v['ticker'] for v in first.values()})
settled = {}
B = 400
for i in range(0, len(tickers), B):
    chunk = tickers[i:i+B]
    ph = ','.join('?'*len(chunk))
    for t, sy in cur.execute(f"""
        SELECT DISTINCT d.ticker, o.settled_yes FROM strategy_decisions d
        JOIN strategy_decision_outcomes o ON o.decision_id=d.decision_id
        WHERE d.ticker IN ({ph}) AND o.outcome_status='SETTLED' AND o.settled_yes IS NOT NULL
    """, chunk):
        settled[t] = sy
print(f'settled tickers: {len(settled)}', file=sys.stderr)

def settle_pnl(v):
    sy = settled.get(v['ticker'])
    if sy is None: return None
    win = (sy == 1) if v['side'] == 'yes' else (sy == 0)
    return (100 - v['px'] - 1.5) if win else (-v['px'] - 1.5)

def pxb(px):
    return '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'

# group by (reason, asset, side, priceband)
g = collections.defaultdict(list)
for v in first.values():
    p = settle_pnl(v)
    if p is None: continue
    g[(v['reason'], v['asset'], v['side'], pxb(v['px']))].append(p)

# print cohorts with n>=8 sorted by mean pnl desc (find POSITIVE pockets)
rows = []
for k, v in g.items():
    if len(v) >= 8:
        rows.append((statistics.mean(v), sum(v), len(v), k))
rows.sort(reverse=True)
print(f'\n{"mean":>7} {"sum":>7} {"n":>4}  reason / asset / side / pxband')
for m, s, nn, k in rows[:45]:
    print(f'{m:>7.2f} {s:>7.0f} {nn:>4}  {k[0]:<38} {k[1]:<5} {k[2]:<4} {k[3]}')
print('... most negative ...')
for m, s, nn, k in rows[-15:]:
    print(f'{m:>7.2f} {s:>7.0f} {nn:>4}  {k[0]:<38} {k[1]:<5} {k[2]:<4} {k[3]}')
