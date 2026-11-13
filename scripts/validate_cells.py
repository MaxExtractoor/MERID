"""Validate positive cells: exit-mark P&L (Nov10+) + net_edge distribution."""
import json, sqlite3, collections, statistics, sys

# load first entries
entries = []
with open('scripts/first_entries.jsonl','r',encoding='utf-8') as f:
    for line in f:
        entries.append(json.loads(line))

# settlement map
settled = {}
with open('logs/settlement_outcomes.jsonl','r',encoding='utf-8',errors='replace') as f:
    for line in f:
        try: d=json.loads(line)
        except Exception: continue
        if d.get('ticker') and d.get('outcome'): settled[d['ticker']]=d['outcome']

def pxb(px):
    return '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'

# target cells (positive pockets)
TARGETS = [
    ('no_positive_executable_edge','XRP','yes','10-24'),
    ('no_positive_executable_edge','SOL','yes','10-24'),
    ('no_positive_executable_edge','DOGE','no','10-24'),
    ('no_positive_executable_edge','XRP','no','10-24'),
    ('no_positive_executable_edge','ETH','no','10-24'),
    ('no_eligible_price_band:yes','ETH','yes','0-9'),
    ('no_eligible_price_band:yes','BTC','yes','0-9'),
    ('no_eligible_price_band:yes','DOGE','yes','0-9'),
    ('no_eligible_price_band:yes','XRP','yes','90+'),
    ('no_positive_executable_edge','SOL','no','75-89'),
    ('no_positive_executable_edge','DOGE','yes','25-49'),
    ('no_positive_executable_edge','ETH','no','25-49'),
]

# exit marks from decision_audit (Nov10+ only)
con = sqlite3.connect('file:data/decision_audit.db?mode=ro', uri=True, timeout=300)
cur = con.cursor()
tickers = sorted({v['ticker'] for v in entries})
snaps = collections.defaultdict(list)
B=400
for i in range(0,len(tickers),B):
    chunk=tickers[i:i+B]; ph=','.join('?'*len(chunk))
    for t,stc,yb,nb in cur.execute(f"""
        SELECT d.ticker, d.seconds_to_close, s.yes_bid_cents, s.no_bid_cents
        FROM strategy_decision_snapshots s JOIN strategy_decisions d ON d.decision_id=s.decision_id
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 45 AND 200
        ORDER BY d.ticker, ABS(d.seconds_to_close-120)""", chunk):
        snaps[t].append((abs((stc or 0)-120), yb, nb))
print('snaps loaded:', len(snaps), file=sys.stderr)

def exit_pnl(v):
    for dist,yb,nb in snaps.get(v['ticker'],[]):
        if v['side']=='yes':
            if yb is not None: return yb - v['px']
        else:
            if nb is not None: return nb - v['px']
    return None

def settle_pnl(v):
    o=settled.get(v['ticker'])
    if o is None: return None
    win=(o=='yes') if v['side']=='yes' else (o=='no')
    return (100-v['px']-1.5) if win else (-v['px']-1.5)

print(f'\n{"cell":>58} {"n":>4} {"exit_n":>6} {"exit_mean":>9} {"exit_sum":>8} {"set_mean":>8} {"set_n":>5} {"netEV_med":>9} {"netEV_p25":>8}')
for reason,asset,side,pb in TARGETS:
    vs=[v for v in entries if v['reason']==reason and v['asset']==asset and v['side']==side and pxb(v['px'])==pb]
    if not vs: continue
    ep=[exit_pnl(v) for v in vs]; ep=[x for x in ep if x is not None]
    sp=[settle_pnl(v) for v in vs]; sp=[x for x in sp if x is not None]
    ne=[v['net_edge'] for v in vs if v.get('net_edge') is not None]
    ne=[x*100 for x in ne]  # net_edge is fraction -> cents
    em=f'{statistics.mean(ep):>9.2f}' if ep else f'{"-":>9}'
    es=f'{sum(ep):>8.0f}' if ep else f'{"-":>8}'
    sm=f'{statistics.mean(sp):>8.2f}' if sp else f'{"-":>8}'
    nem=f'{statistics.median(ne):>9.2f}' if ne else '-'
    ne25=f'{sorted(ne)[len(ne)//4]:>8.2f}' if ne else '-'
    print(f'{reason[:30]:<32}{asset:<5}{side:<5}{pb:<6} {len(vs):>4} {len(ep):>6} {em} {es} {sm} {len(sp):>5} {nem} {ne25}')
