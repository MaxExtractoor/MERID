"""First-entry-per-market counterfactual (unbiased).

For each (ticker, side): scan taker decision rows chronologically, find the FIRST
row meeting the cohort predicate, treat its executable price as the entry, then
mark P&L at (a) T-120s book exit and (b) settlement. This simulates a bounded
lane entering at first opportunity — no cherry-picking.
"""
import sqlite3, collections, statistics, sys

DB = 'file:data/decision_audit.db?mode=ro'
SINCE = 1794268800
# cols: 0 did,1 ticker,2 asset,3 dts,4 stc,5 side,6 px,7 ev,8 calp,9 gross,
#       10 reqedge,11 cfqty,12 cfstatus,13 sy,14 cfy,15 cfn,16 lane,17 owner
I = dict(did=0, ticker=1, asset=2, dts=3, stc=4, side=5, px=6, ev=7, calp=8,
         gross=9, reqedge=10, cfqty=11, cfstatus=12, sy=13, cfy=14, cfn=15,
         lane=16, owner=17)

con = sqlite3.connect(DB, uri=True, timeout=300)
cur = con.cursor()
q = """
SELECT se.decision_id, d.ticker, d.asset, d.decision_ts, d.seconds_to_close, se.side,
       se.executable_entry_price_cents, se.expected_net_ev_cents,
       se.calibrated_probability, se.gross_edge_cents,
       se.required_edge_cents, se.counterfactual_assumed_filled_contracts,
       se.counterfactual_execution_status,
       o.settled_yes, o.counterfactual_yes_pnl_cents, o.counterfactual_no_pnl_cents,
       se.decision_lane, se.admission_owner
FROM strategy_decision_side_ev se
JOIN strategy_decisions d ON d.decision_id = se.decision_id
JOIN strategy_decision_outcomes o ON o.decision_id = d.decision_id
WHERE d.decision_ts >= ? AND o.outcome_status = 'SETTLED'
  AND d.ticker != '' AND d.decision_id LIKE '%:taker'
ORDER BY d.ticker, d.decision_ts
"""
rows = cur.execute(q, (SINCE,)).fetchall()
print(f'rows: {len(rows)}', file=sys.stderr)

# group by (ticker, side), keep chronological
bykey = collections.defaultdict(list)
for r in rows:
    if r[I['px']] is None or r[I['ev']] is None: continue
    if not (r[I['cfqty']] and r[I['cfqty']] > 0): continue
    bykey[(r[I['ticker']], r[I['side']])].append(r)

# T-120s (or closest in 60-160) exit book per ticker
tickers = sorted({k[0] for k in bykey})
snap = {}
B = 400
for i in range(0, len(tickers), B):
    chunk = tickers[i:i+B]
    ph = ','.join('?'*len(chunk))
    for t, stc, yb, ya, nb, na in cur.execute(f"""
        SELECT d.ticker, d.seconds_to_close, s.yes_bid_cents, s.yes_ask_cents,
               s.no_bid_cents, s.no_ask_cents
        FROM strategy_decision_snapshots s JOIN strategy_decisions d ON d.decision_id=s.decision_id
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 60 AND 160
        ORDER BY d.ticker, ABS(d.seconds_to_close - 120)
    """, chunk):
        if t not in snap:
            snap[t] = (yb, nb)
print(f'tickers w/ exit snap: {len(snap)}', file=sys.stderr)

def exit_pnl(r):
    t = r[I['ticker']]
    if t not in snap: return None
    yb, nb = snap[t]
    px = r[I['px']]
    if r[I['side']] == 'yes':
        return (yb - px) if yb is not None else None
    return (nb - px) if nb is not None else None

def settle_pnl(r):
    return r[I['cfy']] if r[I['side']] == 'yes' else r[I['cfn']]

# cohort predicates evaluated PER-TICK; first match = entry
def mkpred(evlo, evhi, plo, phi, ttemin, ttemax, side=None):
    def f(r):
        if side and r[I['side']] != side: return False
        if not (evlo <= r[I['ev']] < evhi): return False
        if r[I['px']] is None or not (plo <= r[I['px']] < phi): return False
        t = r[I['stc']] or 0
        if not (ttemin <= t <= ttemax): return False
        return True
    return f

COHORTS = [
    ('hot: EV[-10,0) px25-89 TTE300-840', mkpred(-10,0,25,90,300,840)),
    ('tight: EV[-3,0) px25-89 TTE300-840', mkpred(-3,0,25,90,300,840)),
    ('tight NO: EV[-3,0) px25-89 TTE300-840', mkpred(-3,0,25,90,300,840,'no')),
    ('mid: EV[-5,-1) px25-89 TTE300-840', mkpred(-5,-1,25,90,300,840)),
    ('wide: EV[-10,0) px10-89 TTE300-840', mkpred(-10,0,10,90,300,840)),
    ('late: EV[-10,0) px25-89 TTE120-300', mkpred(-10,0,25,90,120,300)),
    ('cheap: EV[-10,0) px5-25 TTE300-840', mkpred(-10,0,5,25,300,840)),
    ('exp: EV[0,3) px25-89 TTE300-840', mkpred(0,3,25,90,300,840)),
]

print(f'\n{"cohort":>44} {"entries":>7} {"exit_n":>6} {"exit_mean":>9} {"exit_med":>8} {"exit_sum":>8} {"exit_win%":>8} {"set_mean":>8} {"set_sum":>8}')
for name, pred in COHORTS:
    entries = []
    for (t, s), rs in bykey.items():
        for r in rs:  # chronological
            if pred(r):
                entries.append(r); break
    ep = [exit_pnl(r) for r in entries]; epv = [x for x in ep if x is not None]
    sp = [settle_pnl(r) for r in entries]; sp = [x for x in sp if x is not None]
    em = statistics.mean(epv) if epv else float('nan')
    es = sum(epv)
    sm = statistics.mean(sp) if sp else float('nan')
    ss = sum(sp)
    ew = 100*sum(1 for x in epv if x>0)/len(epv) if epv else float('nan')
    print(f'{name:>44} {len(entries):>7} {len(epv):>6} {em:>9.2f} {statistics.median(epv) if epv else 0:>8.2f} {es:>8.0f} {ew:>7.1f}% {sm:>8.2f} {ss:>8.0f}')

# hot cohort detail by asset/side (first-entry)
print('\n=== hot cohort first-entries by asset/side ===')
pred = COHORTS[0][1]
by = collections.defaultdict(list)
for (t, s), rs in bykey.items():
    for r in rs:
        if pred(r):
            e = exit_pnl(r); sp = settle_pnl(r)
            by[(r[I['asset']], r[I['side']])].append((e, sp, r[I['px']], r[I['ev']]))
            break
for k in sorted(by):
    v = by[k]
    evs = [x[1] for x in v if x[1] is not None]; epx = [x[0] for x in v if x[0] is not None]
    print(f'  {k[0]:>5} {k[1]:>4} n={len(v):>3} exitMean={statistics.mean(epx) if epx else float("nan"):>7.2f} exitSum={sum(epx):>7.0f} settleMean={statistics.mean(evs) if evs else float("nan"):>7.2f} settleSum={sum(evs):>7.0f}')
