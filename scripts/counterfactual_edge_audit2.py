"""Deeper counterfactual: calibration + raw settle P&L for rejected cohorts."""
import sqlite3, collections, statistics, sys

DB = 'file:data/decision_audit.db?mode=ro'
SINCE = 1794268800
I = dict(did=0, ticker=1, asset=2, stc=3, side=4, px=5, ev=6, req=7, calp=8,
         gross=9, reqedge=10, peg=11, eeg=12, cfqty=13, cfstatus=14, exe=15,
         lane=16, owner=17, sy=18, cfy=19, cfn=20, ostatus=21, prc=22, dlane=23, dtte=24)

con = sqlite3.connect(DB, uri=True, timeout=300)
cur = con.cursor()
q = """
SELECT se.decision_id, d.ticker, d.asset, d.seconds_to_close, se.side,
       se.executable_entry_price_cents, se.expected_net_ev_cents,
       se.effective_required_c, se.calibrated_probability, se.gross_edge_cents,
       se.required_edge_cents, se.passed_edge_gate, se.effective_edge_gate_passed,
       se.counterfactual_assumed_filled_contracts, se.counterfactual_execution_status,
       se.executable, se.decision_lane, se.admission_owner,
       o.settled_yes, o.counterfactual_yes_pnl_cents, o.counterfactual_no_pnl_cents,
       o.outcome_status, d.primary_reason_code, d.admission_lane, d.seconds_to_close
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

def raw_pnl(r):
    """settle P&L at executable price, ~1.5c taker fee+exit estimate, per contract."""
    px = r[I['px']]
    if px is None: return None
    win = (r[I['sy']] == 1) if r[I['side']] == 'yes' else (r[I['sy']] == 0)
    fee = 1.5
    return (100 - px - fee) if win else (-px - fee)

def model_pnl(r):
    return r[I['cfy']] if r[I['side']] == 'yes' else r[I['cfn']]

def win(r):
    return (r[I['sy']] == 1) if r[I['side']] == 'yes' else (r[I['sy']] == 0)

# ---- 1) calibration: calibrated_probability decile -> realized win rate ----
print('\n=== calibration: model prob bucket -> realized win rate (deduped, fillable only) ===')
cal = collections.defaultdict(list)
for r in best.values():
    if r[I['cfqty']] and r[I['cfqty']] > 0 and r[I['calp']] is not None:
        p = r[I['calp']]
        b = min(int(p*10), 9)
        cal[b].append(win(r))
for b in sorted(cal):
    v = cal[b]
    print(f'p [{b/10:.1f},{(b+1)/10:.1f}): n={len(v):>4} winrate={sum(v)/len(v):.3f}')

# ---- 2) gross_edge vs realized for EV cohorts ----
print('\n=== EV cohort: mean gross_edge vs mean raw settle P&L vs mean model pnl ===')
for lo,hi in [(-1e9,-10),(-10,-5),(-5,-3),(-3,-2),(-2,-1),(-1,-0.5),(-0.5,0),(0,0.5),(0.5,1),(1,2),(2,5),(5,1e9)]:
    v = [r for r in best.values() if lo <= r[I['ev']] < hi and r[I['cfqty']] and r[I['cfqty']]>0]
    if not v: continue
    rp = [raw_pnl(r) for r in v]; mp = [model_pnl(r) for r in v]; ge = [r[I['gross']] for r in v if r[I['gross']] is not None]
    print(f'EV [{lo},{hi}): n={len(v):>4} gross={statistics.mean(ge) if ge else 0:>7.2f} rawPnL={statistics.mean(rp):>7.2f} modelPnL={statistics.mean(mp):>7.2f} win%={100*sum(win(r) for r in v)/len(v):.1f}')

# ---- 3) the hot cohort: EV [-10,0), px 25-89, TTE>=300 ----
print('\n=== hot cohort EV[-10,0) px[25,89] TTE>=300 ===')
hot = [r for r in best.values() if -10 <= r[I['ev']] < 0 and r[I['px']] and 25 <= r[I['px']] < 90 and (r[I['dtte']] or 0) >= 300 and r[I['cfqty']] and r[I['cfqty']]>0]
print('n =', len(hot))
if hot:
    rp=[raw_pnl(r) for r in hot]; mp=[model_pnl(r) for r in hot]
    print(f'rawPnL mean={statistics.mean(rp):.2f} median={statistics.median(rp):.2f} sum={sum(rp):.0f}')
    print(f'modelPnL mean={statistics.mean(mp):.2f} sum={sum(mp):.0f}')
    by = collections.defaultdict(list)
    for r in hot: by[(r[I['asset']],r[I['side']])].append(raw_pnl(r))
    for k in sorted(by):
        v=by[k]; print(f'  {k[0]:>5} {k[1]:>4} n={len(v):>3} mean={statistics.mean(v):>7.2f} sum={sum(v):>7.0f}')

# ---- 4) what actually got ENTERED: win rate + P&L of fills ----
print('\n=== ENTER fills: settlement + capital P&L ===')
q2 = '''SELECT d.admission_lane, d.asset, se.side, se.calibrated_probability,
       o.settled_yes, o.actual_fill_price_cents, o.capital_realized_pnl_cents,
       o.realized_net_pnl_cents, o.actual_exit_price_cents
FROM strategy_decisions d
JOIN strategy_decision_outcomes o ON o.decision_id=d.decision_id
LEFT JOIN strategy_decision_side_ev se ON se.decision_id=d.decision_id AND se.selected=1
WHERE d.decision='ENTER' AND o.outcome_status='SETTLED' AND o.actual_fill_price_cents IS NOT NULL'''
fr = cur.execute(q2).fetchall()
print('n fills with side_ev:', len(fr))
for row in fr[:60]:
    lane, asset, side, calp, sy, fpx, cap, real, xpx = row
    won = (sy==1) if side=='yes' else (sy==0) if side else None
    print(f'  {str(lane):>22} {asset:>4} {str(side):>4} p={calp if calp else 0:.3f} fill={fpx} exit={xpx} settled_yes={sy} won={won} capPnL={cap} realPnL={real}')
