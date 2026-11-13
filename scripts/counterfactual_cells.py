"""Consolidated first-entry counterfactual: per (ticker,side) earliest rejection.

Reports BOTH exit-mark (T-120 book) and settlement P&L per
(reason, asset, side, price-band) cell. n>=6 cells only.
"""
import json, sqlite3, collections, statistics, sys

SINCE = '2026-10-31T00:00:00'   # widen window for more samples
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
        key = (ticker, side)
        if key not in first or ts < first[key]['ts']:
            first[key] = dict(ts=ts, ticker=ticker, asset=d.get('asset'), side=side,
                              reason=reason, px=float(px), tte=d.get('tte_seconds'),
                              net_edge=d.get('net_edge'), depth=d.get('depth_for_quantity_cc'))
print(f'rows={n} keys={len(first)}', file=sys.stderr)

con = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=300)
cur = con.cursor()
tickers = sorted({v['ticker'] for v in first.values()})
snap = {}; settled = {}
B = 400
for i in range(0, len(tickers), B):
    chunk = tickers[i:i+B]
    ph = ','.join('?'*len(chunk))
    for t, stc, yb, nb in cur.execute(f"""
        SELECT d.ticker, d.seconds_to_close, s.yes_bid_cents, s.no_bid_cents
        FROM strategy_decision_snapshots s JOIN strategy_decisions d ON d.decision_id=s.decision_id
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 60 AND 170
        ORDER BY d.ticker, ABS(d.seconds_to_close - 120)
    """, chunk):
        if t not in snap: snap[t] = (yb, nb)
    for t, sy in cur.execute(f"""
        SELECT DISTINCT d.ticker, o.settled_yes FROM strategy_decisions d
        JOIN strategy_decision_outcomes o ON o.decision_id=d.decision_id
        WHERE d.ticker IN ({ph}) AND o.outcome_status='SETTLED' AND o.settled_yes IS NOT NULL
    """, chunk):
        settled[t] = sy
print(f'tickers={len(tickers)} snap={len(snap)} settled={len(settled)}', file=sys.stderr)

def exit_pnl(v):
    if v['ticker'] not in snap: return None
    yb, nb = snap[v['ticker']]
    if v['side'] == 'yes':
        return (yb - v['px']) if yb is not None else None
    return (nb - v['px']) if nb is not None else None

def settle_pnl(v):
    sy = settled.get(v['ticker'])
    if sy is None: return None
    win = (sy == 1) if v['side'] == 'yes' else (sy == 0)
    return (100 - v['px'] - 1.5) if win else (-v['px'] - 1.5)

def pxb(px):
    return '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'

g = collections.defaultdict(list)
for v in first.values():
    g[(v['reason'], v['asset'], v['side'], pxb(v['px']))].append(v)

rows = []
for k, vs in g.items():
    ep = [exit_pnl(v) for v in vs]; ep = [x for x in ep if x is not None]
    sp = [settle_pnl(v) for v in vs]; sp = [x for x in sp if x is not None]
    if len(vs) < 6: continue
    rows.append(dict(k=k, n=len(vs), en=len(ep), em=statistics.mean(ep) if ep else None,
                     es=sum(ep) if ep else None, sn=len(sp),
                     sm=statistics.mean(sp) if sp else None, ss=sum(sp) if sp else None))

# sort by settle sum desc — find positive pockets
rows.sort(key=lambda r: -(r['ss'] or -9999))
print(f'\n{"n":>4} {"en":>4} {"exit_mean":>9} {"exit_sum":>8} {"sn":>4} {"set_mean":>8} {"set_sum":>8}  cell')
for r in rows[:50]:
    em = f"{r['em']:>9.2f}" if r['em'] is not None else f'{"-":>9}'
    es = f"{r['es']:>8.0f}" if r['es'] is not None else f'{"-":>8}'
    sm = f"{r['sm']:>8.2f}" if r['sm'] is not None else f'{"-":>8}'
    ss = f"{r['ss']:>8.0f}" if r['ss'] is not None else f'{"-":>8}'
    k = r['k']
    print(f"{r['n']:>4} {r['en']:>4} {em} {es} {r['sn']:>4} {sm} {ss}  {k[0]:<36} {k[1]:<5} {k[2]:<4} {k[3]}")
