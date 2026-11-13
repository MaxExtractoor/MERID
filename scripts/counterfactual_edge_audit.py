"""Counterfactual audit: did rejected NO_EDGE candidates have real executable edge?

Joins strategy_decision_side_ev (per-side EV at executable price) with
strategy_decision_outcomes (settled result + per-contract counterfactual P&L).
Dedupes by (ticker, side) keeping the max expected_net_ev row = the moment the
candidate looked best. Uses :taker route rows = pay-the-ask executable price.
"""
import sqlite3, collections, statistics, sys

DB = 'file:data/decision_audit.db?mode=ro'
SINCE = 1794268800  # 2026-11-10T00:00Z

# column indices into the SELECT below
I_DID, I_TICKER, I_ASSET, I_STC, I_SIDE, I_PX, I_EV, I_REQ, I_CALP, I_GROSS = range(10)
I_REQEDGE, I_PEG, I_EEG, I_CFQTY, I_CFSTATUS, I_EXE, I_LANE, I_OWNER = range(10, 18)
I_SY, I_CFY, I_CFN, I_OSTATUS, I_PRC, I_DLANE, I_DTTE = range(18, 25)

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
       o.outcome_status, d.primary_reason_code, d.admission_lane,
       d.seconds_to_close
FROM strategy_decision_side_ev se
JOIN strategy_decisions d ON d.decision_id = se.decision_id
JOIN strategy_decision_outcomes o ON o.decision_id = d.decision_id
WHERE d.decision_ts >= ? AND o.outcome_status = 'SETTLED'
  AND d.ticker != '' AND d.decision_id LIKE '%:taker'
"""
rows = cur.execute(q, (SINCE,)).fetchall()
print(f"raw side_ev rows: {len(rows)}", file=sys.stderr)

# dedupe by (ticker, side): keep row with max expected_net_ev (best-looking moment)
best = {}
for r in rows:
    px, ev = r[I_PX], r[I_EV]
    if px is None or ev is None:
        continue
    key = (r[I_TICKER], r[I_SIDE])
    if key not in best or ev > best[key][I_EV]:
        best[key] = r
print(f"deduped (ticker,side): {len(best)}", file=sys.stderr)

def pnl(r):
    return r[I_CFY] if r[I_SIDE] == 'yes' else r[I_CFN]

BUCKETS = [(-1e18,-10),(-10,-5),(-5,-2),(-2,-1),(-1,-0.5),(-0.5,0),(0,0.5),(0.5,1),(1,2),(2,5),(5,1e18)]
def bname(ev):
    for lo,hi in BUCKETS:
        if lo <= ev < hi: return f'[{lo},{hi})'
    return '?'

agg = collections.defaultdict(list)
for r in best.values():
    agg[bname(r[I_EV])].append(pnl(r))

print('\n=== counterfactual settle P&L (cents/contract) by expected_net_ev bucket ===')
print(f'{"EV bucket":>16} {"n":>6} {"mean":>8} {"median":>8} {"win%":>6} {"sum":>10}')
for lo,hi in BUCKETS:
    b = f'[{lo},{hi})'
    v = agg.get(b, [])
    if not v: continue
    wins = sum(1 for x in v if x and x > 0)
    print(f'{b:>16} {len(v):>6} {statistics.mean(v):>8.2f} {statistics.median(v):>8.2f} {100*wins/len(v):>5.1f}% {sum(v):>10.0f}')

print('\n=== by asset x side (deduped market-sides, best-EV moment) ===')
bas = collections.defaultdict(list)
for r in best.values():
    bas[(r[I_ASSET], r[I_SIDE])].append((r[I_EV], pnl(r)))
for k in sorted(bas):
    v = bas[k]
    evs = [x[0] for x in v]; ps = [x[1] for x in v]
    wins = sum(1 for x in ps if x and x > 0)
    print(f'{k[0]:>5} {k[1]:>4} n={len(v):>5} meanEV={statistics.mean(evs):>7.2f} meanPnL={statistics.mean(ps):>7.2f} win%={100*wins/len(v):>5.1f}')

print('\n=== near-miss EV in [-3,0): by asset/side ===')
nm = collections.defaultdict(list)
for r in best.values():
    if -3 <= r[I_EV] < 0:
        nm[(r[I_ASSET], r[I_SIDE])].append(pnl(r))
tot = []
for k in sorted(nm):
    v = nm[k]; tot += v
    print(f'{k[0]:>5} {k[1]:>4} n={len(v):>4} meanPnL={statistics.mean(v):>7.2f} median={statistics.median(v):>7.2f} sum={sum(v):>8.0f}')
if tot:
    print(f'{"ALL":>9} n={len(tot):>4} meanPnL={statistics.mean(tot):>7.2f} sum={sum(tot):>8.0f}')

print('\n=== near-miss EV in [-3,0): by entry price bucket ===')
pb = collections.defaultdict(list)
for r in best.values():
    if -3 <= r[I_EV] < 0 and r[I_PX] is not None:
        px = r[I_PX]
        b = '0-9' if px<10 else '10-24' if px<25 else '25-49' if px<50 else '50-74' if px<75 else '75-89' if px<90 else '90+'
        pb[b].append(pnl(r))
for b in ['0-9','10-24','25-49','50-74','75-89','90+']:
    v = pb.get(b, [])
    if v:
        print(f'{b:>6} n={len(v):>4} meanPnL={statistics.mean(v):>7.2f} median={statistics.median(v):>7.2f} sum={sum(v):>8.0f}')

print('\n=== near-miss EV in [-3,0): by TTE bucket ===')
tb = collections.defaultdict(list)
for r in best.values():
    if -3 <= r[I_EV] < 0 and r[I_DTTE] is not None:
        t = r[I_DTTE]
        b = '<120' if t<120 else '120-300' if t<300 else '300-600' if t<600 else '600+'
        tb[b].append(pnl(r))
for b in ['<120','120-300','300-600','600+']:
    v = tb.get(b, [])
    if v:
        print(f'{b:>8} n={len(v):>4} meanPnL={statistics.mean(v):>7.2f} median={statistics.median(v):>7.2f} sum={sum(v):>8.0f}')

# calibration: does EV rank-order realized P&L? correlation-ish via bucket means above.
# Also: distribution of best-side EV per ticker (oracle view)
print('\n=== per-ticker best side EV distribution (oracle) ===')
bytick = collections.defaultdict(lambda: [-1e18, None])
for r in best.values():
    t = r[I_TICKER]
    if r[I_EV] > bytick[t][0]:
        bytick[t] = [r[I_EV], pnl(r)]
obe = collections.defaultdict(list)
for t,(ev,p) in bytick.items():
    obe[bname(ev)].append(p)
for lo,hi in BUCKETS:
    b=f'[{lo},{hi})'; v=obe.get(b,[])
    if v:
        wins=sum(1 for x in v if x and x>0)
        print(f'{b:>16} n={len(v):>5} meanPnL={statistics.mean(v):>7.2f} win%={100*wins/len(v):>5.1f}')
