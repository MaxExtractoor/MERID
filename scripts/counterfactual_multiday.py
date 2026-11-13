"""Multi-week cell counterfactual: first-entries x settlement outcomes.

Groups by (reason, asset, side, price-band) and by day-week to check stability.
Settlement P&L = (100-px-1.5) win / (-px-1.5) loss per contract (taker fee ~1.5c).
"""
import json, collections, statistics, sys, csv

# settlement map
settled = {}
with open('logs/settlement_outcomes.jsonl','r',encoding='utf-8',errors='replace') as f:
    for line in f:
        try: d=json.loads(line)
        except Exception: continue
        t=d.get('ticker'); o=d.get('outcome')
        if t and o: settled[t]=o
print('settled map:', len(settled), file=sys.stderr)

def pnl(v):
    o = settled.get(v['ticker'])
    if o is None: return None
    win = (o == 'yes') if v['side']=='yes' else (o == 'no')
    return (100 - v['px'] - 1.5) if win else (-v['px'] - 1.5)

def pxb(px):
    return '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'

entries = []
with open('scripts/first_entries.jsonl','r',encoding='utf-8') as f:
    for line in f:
        v = json.loads(line)
        p = pnl(v)
        if p is not None:
            v['pnl'] = p
            entries.append(v)
print('entries with settlement:', len(entries), file=sys.stderr)

# ---- overall by reason ----
print('\n=== by reject_reason (all history) ===')
g = collections.defaultdict(list)
for v in entries: g[v['reason']].append(v['pnl'])
for r in sorted(g, key=lambda k:-len(g[k]))[:20]:
    v=g[r]
    print(f'{r:<42} n={len(v):>5} mean={statistics.mean(v):>7.2f} med={statistics.median(v):>7.2f} sum={sum(v):>9.0f} win%={100*sum(1 for x in v if x>0)/len(v):.1f}')

# ---- cells n>=15 ----
print('\n=== cells n>=15 sorted by mean P&L desc ===')
cells = collections.defaultdict(list)
for v in entries:
    cells[(v['reason'], v['asset'], v['side'], pxb(v['px']))].append(v)
rows=[]
for k,vs in cells.items():
    ps=[v['pnl'] for v in vs]
    if len(ps)<15: continue
    rows.append((statistics.mean(ps), sum(ps), len(ps), k))
rows.sort(reverse=True)
for m,s,n,k in rows[:50]:
    print(f'{m:>7.2f} {s:>8.0f} {n:>4}  {k[0]:<36} {k[1]:<5} {k[2]:<4} {k[3]}')

# ---- weekly stability for top cells ----
print('\n=== weekly stability: selected cells ===')
top_cells = [k for _,_,_,k in rows[:12]]
for k in top_cells:
    wk = collections.defaultdict(list)
    for v in cells[k]:
        wk[v['day'][:7]+'-'+str(int(v['day'][8:10])//7)].append(v['pnl'])
    parts = ' '.join(f'{d}:{statistics.mean(x):+.1f}({len(x)})' for d,x in sorted(wk.items()))
    print(f'{k[0][:30]:<32} {k[1]:<5} {k[2]:<4} {k[3]:<6} | {parts}')
