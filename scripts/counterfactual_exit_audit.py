"""Exit-policy-aware counterfactual: mark rejected candidates at the T-120s closeout.

For each deduped (ticker, side) near-miss candidate (max-EV moment, taker price),
find the book snapshot closest to seconds_to_close=120 and compute the P&L the
position would have shown at the mandatory pre-settlement closeout:
  held YES: exit at yes_bid(T-120)  -> pnl = yes_bid_exit - yes_ask_entry
  held NO:  exit at no_bid(T-120)   -> pnl = no_bid_exit - no_ask_entry
Compare vs hold-to-settlement P&L.
"""
import sqlite3, collections, statistics, sys

DB = 'file:data/decision_audit.db?mode=ro'
SINCE = 1794268800
I = dict(did=0, ticker=1, asset=2, stc=3, side=4, px=5, ev=6, calp=7,
         gross=8, reqedge=9, peg=10, cfqty=11, sy=12, cfy=13, cfn=14, dtte=15)

con = sqlite3.connect(DB, uri=True, timeout=300)
cur = con.cursor()
q = """
SELECT se.decision_id, d.ticker, d.asset, d.seconds_to_close, se.side,
       se.executable_entry_price_cents, se.expected_net_ev_cents,
       se.calibrated_probability, se.gross_edge_cents,
       se.required_edge_cents, se.passed_edge_gate,
       se.counterfactual_assumed_filled_contracts,
       o.settled_yes, o.counterfactual_yes_pnl_cents, o.counterfactual_no_pnl_cents,
       d.seconds_to_close
FROM strategy_decision_side_ev se
JOIN strategy_decisions d ON d.decision_id = se.decision_id
JOIN strategy_decision_outcomes o ON o.decision_id = d.decision_id
WHERE d.decision_ts >= ? AND o.outcome_status = 'SETTLED'
  AND d.ticker != '' AND d.decision_id LIKE '%:taker'
"""
rows = cur.execute(q, (SINCE,)).fetchall()

best = {}
for r in rows:
    if r[I['px']] is None or r[I['ev']] is None: continue
    k = (r[I['ticker']], r[I['side']])
    if k not in best or r[I['ev']] > best[k][I['ev']]: best[k] = r
print(f'deduped: {len(best)}', file=sys.stderr)

# T-120s book snapshots per ticker
tickers = sorted({r[I['ticker']] for r in best.values()})
snap = {}
B = 400
for i in range(0, len(tickers), B):
    chunk = tickers[i:i+B]
    ph = ','.join('?'*len(chunk))
    for t, stc, yb, ya, nb, na in cur.execute(f"""
        SELECT d.ticker, d.seconds_to_close, s.yes_bid_cents, s.yes_ask_cents,
               s.no_bid_cents, s.no_ask_cents
        FROM strategy_decision_snapshots s JOIN strategy_decisions d ON d.decision_id=s.decision_id
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 100 AND 145
        ORDER BY d.ticker, ABS(d.seconds_to_close - 120)
    """, chunk):
        if t not in snap:  # first row per ticker = closest to 120
            snap[t] = (yb, ya, nb, na, stc)
print(f'tickers with T-120 snap: {len(snap)}', file=sys.stderr)

def exit_pnl(r):
    """P&L cents/contract if entered at this row's taker price, exited at T-120 book."""
    t = r[I['ticker']]
    if t not in snap: return None
    yb, ya, nb, na, stc = snap[t]
    px = r[I['px']]
    if px is None: return None
    if r[I['side']] == 'yes':
        if yb is None: return None
        # bought YES at ask px; sell YES at bid yb
        return yb - px
    else:
        if nb is None: return None
        # bought NO at ask px (=100-yb_entry); sell NO at bid nb
        return nb - px

def settle_pnl(r):
    return r[I['cfy']] if r[I['side']] == 'yes' else r[I['cfn']]

# cohorts of interest
cohorts = {
    'ALL deduped': lambda r: True,
    'EV[-10,0) px[25,89] TTE>=300': lambda r: -10 <= r[I['ev']] < 0 and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300,
    'EV[-10,0) px[25,89] anyTTE': lambda r: -10 <= r[I['ev']] < 0 and r[I['px']] and 25 <= r[I['px']] < 90,
    'EV[-3,0) px[25,89] TTE>=300': lambda r: -3 <= r[I['ev']] < 0 and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300,
    'EV[-3,0) NO px[25,89] TTE>=300': lambda r: -3 <= r[I['ev']] < 0 and r[I['side']]=='no' and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300,
    'EV[2,5) structural-blocked': lambda r: 2 <= r[I['ev']] < 5,
    'EV[-5,-2) px[25,89] TTE>=300': lambda r: -5 <= r[I['ev']] < -2 and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300,
}

print(f'\n{"cohort":>38} {"n":>5} {"exitPnL_mean":>12} {"exitPnL_med":>11} {"exit_sum":>9} {"settle_mean":>11} {"settle_sum":>10} {"win%@exit":>9}')
for name, f in cohorts.items():
    sel = [r for r in best.values() if f(r) and r[I['cfqty']] and r[I['cfqty']] > 0]
    ep = [exit_pnl(r) for r in sel]; ep = [x for x in ep if x is not None]
    sp = [settle_pnl(r) for r in sel]; sp = [x for x in sp if x is not None]
    if not ep: 
        print(f'{name:>38} {len(sel):>5}  (no exit marks)')
        continue
    wins = sum(1 for x in ep if x > 0)
    print(f'{name:>38} {len(ep):>5} {statistics.mean(ep):>12.2f} {statistics.median(ep):>11.2f} {sum(ep):>9.0f} {statistics.mean(sp) if sp else 0:>11.2f} {sum(sp) if sp else 0:>10.0f} {100*wins/len(ep):>8.1f}%')

# by asset/side for the main hot cohort
print('\n=== EV[-10,0) px[25,89] TTE>=300 by asset/side: EXIT pnl ===')
hot = [r for r in best.values() if -10 <= r[I['ev']] < 0 and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300 and r[I['cfqty']] and r[I['cfqty']]>0]
by = collections.defaultdict(list)
for r in hot:
    e = exit_pnl(r)
    if e is not None: by[(r[I['asset']], r[I['side']])].append(e)
for k in sorted(by):
    v = by[k]
    print(f'  {k[0]:>5} {k[1]:>4} n={len(v):>3} mean={statistics.mean(v):>7.2f} med={statistics.median(v):>7.2f} sum={sum(v):>7.0f}')

# same but settle for comparison
print('\n=== same cohort: SETTLE pnl ===')
bys = collections.defaultdict(list)
for r in hot:
    p = settle_pnl(r)
    if p is not None: bys[(r[I['asset']], r[I['side']])].append(p)
for k in sorted(bys):
    v = bys[k]
    print(f'  {k[0]:>5} {k[1]:>4} n={len(v):>3} mean={statistics.mean(v):>7.2f} med={statistics.median(v):>7.2f} sum={sum(v):>7.0f}')
