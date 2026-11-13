"""Consolidated v2: per-(ticker,side) first rejection; exit marks use closest
T-120 snap WITH the needed bid non-null; full results to CSV; per-day check."""
import json, sqlite3, collections, statistics, sys, csv

SINCE = '2026-10-31T00:00:00'
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
            first[key] = dict(ts=ts, day=ts[:10], ticker=ticker, asset=d.get('asset'),
                              side=side, reason=reason, px=float(px),
                              tte=d.get('tte_seconds'), net_edge=d.get('net_edge'))
print(f'rows={n} keys={len(first)}', file=sys.stderr)

con = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=300)
cur = con.cursor()
tickers = sorted({v['ticker'] for v in first.values()})
snaps = collections.defaultdict(list)   # ticker -> [(dist120, yb, nb)]
settled = {}
B = 400
for i in range(0, len(tickers), B):
    chunk = tickers[i:i+B]
    ph = ','.join('?'*len(chunk))
    for t, stc, yb, nb in cur.execute(f"""
        SELECT d.ticker, d.seconds_to_close, s.yes_bid_cents, s.no_bid_cents
        FROM strategy_decision_snapshots s JOIN strategy_decisions d ON d.decision_id=s.decision_id
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 45 AND 200
        ORDER BY d.ticker, ABS(d.seconds_to_close - 120)
    """, chunk):
        snaps[t].append((abs((stc or 0)-120), yb, nb))
    for t, sy in cur.execute(f"""
        SELECT DISTINCT d.ticker, o.settled_yes FROM strategy_decisions d
        JOIN strategy_decision_outcomes o ON o.decision_id=d.decision_id
        WHERE d.ticker IN ({ph}) AND o.outcome_status='SETTLED' AND o.settled_yes IS NOT NULL
    """, chunk):
        settled[t] = sy
print(f'tickers={len(tickers)} settled={len(settled)}', file=sys.stderr)

def exit_pnl(v):
    for dist, yb, nb in snaps.get(v['ticker'], []):
        if v['side'] == 'yes':
            if yb is not None: return yb - v['px']
        else:
            if nb is not None: return nb - v['px']
    return None

def settle_pnl(v):
    sy = settled.get(v['ticker'])
    if sy is None: return None
    win = (sy == 1) if v['side'] == 'yes' else (sy == 0)
    return (100 - v['px'] - 1.5) if win else (-v['px'] - 1.5)

def pxb(px):
    return '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'

g = collections.defaultdict(list)
for v in first.values():
    v['exit'] = exit_pnl(v); v['settle'] = settle_pnl(v)
    g[(v['reason'], v['asset'], v['side'], pxb(v['px']))].append(v)

out = []
for k, vs in g.items():
    if len(vs) < 6: continue
    ep = [v['exit'] for v in vs if v['exit'] is not None]
    sp = [v['settle'] for v in vs if v['settle'] is not None]
    out.append(dict(reason=k[0], asset=k[1], side=k[2], pxb=k[3], n=len(vs),
                    en=len(ep), em=statistics.mean(ep) if ep else None, es=sum(ep) if ep else None,
                    sn=len(sp), sm=statistics.mean(sp) if sp else None, ss=sum(sp) if sp else None))
out.sort(key=lambda r: -(r['ss'] or -99999))
with open('scripts/cell_results.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

print(f'{"n":>4} {"en":>4} {"exit_mean":>9} {"exit_sum":>8} {"sn":>4} {"set_mean":>8} {"set_sum":>8}  cell')
for r in out[:45]:
    em = f"{r['em']:>9.2f}" if r['em'] is not None else f'{"-":>9}'
    es = f"{r['es']:>8.0f}" if r['es'] is not None else f'{"-":>8}'
    sm = f"{r['sm']:>8.2f}" if r['sm'] is not None else f'{"-":>8}'
    ss = f"{r['ss']:>8.0f}" if r['ss'] is not None else f'{"-":>8}'
    print(f"{r['n']:>4} {r['en']:>4} {em} {es} {r['sn']:>4} {sm} {ss}  {r['reason']:<34} {r['asset']:<5} {r['side']:<4} {r['pxb']}")

# per-day stability for top YES-side no_positive_edge cells
print('\n=== per-day settle P&L: no_positive_executable_edge YES cells ===')
for asset in ['ETH','SOL','BTC','DOGE','XRP']:
    for pb in ['25-49','50-74']:
        vs = [v for v in first.values() if v['reason']=='no_positive_executable_edge'
              and v['asset']==asset and v['side']=='yes' and pxb(v['px'])==pb]
        if len(vs)<5: continue
        byd = collections.defaultdict(list)
        for v in vs:
            if v['settle'] is not None: byd[v['day']].append(v['settle'])
        parts = ' '.join(f'{d[-2:]}:{statistics.mean(x):+.1f}({len(x)})' for d,x in sorted(byd.items()))
        allp = [v['settle'] for v in vs if v['settle'] is not None]
        print(f'{asset} yes {pb}: n={len(vs)} mean={statistics.mean(allp):+.2f} | {parts}')
