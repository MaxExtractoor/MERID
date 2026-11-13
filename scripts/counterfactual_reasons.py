"""First-entry counterfactual for NON-edge rejections, sourced from rejected_candidates.jsonl.

For each (ticker, side, canonical_reason): take the EARLIEST rejected record as the
hypothetical entry (price = executable_price_cents), then mark P&L at the T-120s
book exit (from decision_audit snapshots) and at settlement (settlement_outcomes).
"""
import json, sqlite3, collections, statistics, sys, datetime

SINCE = '2026-11-10T00:00:00'
JSONL = 'logs/rejected_candidates.jsonl'

# ---- pass 1: stream JSONL, first record per (ticker, side, reason) ----
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
        reason = d.get('canonical_reason') or d.get('reject_reason') or '?'
        side = d.get('side')
        ticker = d.get('ticker')
        px = d.get('executable_price_cents')
        if px is None: px = d.get('held_price_cents')
        if not ticker or not side or px is None: continue
        key = (ticker, side, reason)
        if key not in first or ts < first[key]['ts']:
            first[key] = dict(ts=ts, ticker=ticker, asset=d.get('asset'), side=side,
                              reason=reason, px=float(px), tte=d.get('tte_seconds'),
                              net_edge=d.get('net_edge'), route=d.get('route'))
print(f'jsonl rows since {SINCE}: {n}; first-entry keys: {len(first)}', file=sys.stderr)

# ---- pass 2: exit marks (T-120 book) + settlement per ticker from decision_audit ----
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
        WHERE d.ticker IN ({ph}) AND d.seconds_to_close BETWEEN 60 AND 160
        ORDER BY d.ticker, ABS(d.seconds_to_close - 120)
    """, chunk):
        if t not in snap: snap[t] = (yb, nb)
    for t, sy in cur.execute(f"""
        SELECT DISTINCT d.ticker, o.settled_yes FROM strategy_decisions d
        JOIN strategy_decision_outcomes o ON o.decision_id=d.decision_id
        WHERE d.ticker IN ({ph}) AND o.outcome_status='SETTLED' AND o.settled_yes IS NOT NULL
    """, chunk):
        settled[t] = sy
print(f'tickers: {len(tickers)} snap={len(snap)} settled={len(settled)}', file=sys.stderr)

def exit_pnl(v):
    if v['ticker'] not in snap: return None
    yb, nb = snap[v['ticker']]
    if v['side'] == 'yes':
        return (yb - v['px']) if yb is not None else None
    # NO: exit at no_bid; entry px is NO ask price already
    return (nb - v['px']) if nb is not None else None

def settle_pnl(v):
    sy = settled.get(v['ticker'])
    if sy is None: return None
    win = (sy == 1) if v['side'] == 'yes' else (sy == 0)
    return (100 - v['px'] - 1.5) if win else (-v['px'] - 1.5)

# ---- aggregate by reason ----
byreason = collections.defaultdict(list)
for v in first.values():
    byreason[v['reason']].append(v)

print(f'\n{"reason":>42} {"n":>5} {"px_med":>6} {"exit_n":>6} {"exit_mean":>9} {"exit_sum":>8} {"set_n":>5} {"set_mean":>8} {"set_sum":>8}')
for reason in sorted(byreason, key=lambda r: -len(byreason[r])):
    vs = byreason[reason]
    pxs = [v['px'] for v in vs if v['px'] is not None]
    ep = [exit_pnl(v) for v in vs]; ep = [x for x in ep if x is not None]
    sp = [settle_pnl(v) for v in vs]; sp = [x for x in sp if x is not None]
    em = f'{statistics.mean(ep):>9.2f}' if ep else f'{"-":>9}'
    es = f'{sum(ep):>8.0f}' if ep else f'{"-":>8}'
    sm = f'{statistics.mean(sp):>8.2f}' if sp else f'{"-":>8}'
    ss = f'{sum(sp):>8.0f}' if sp else f'{"-":>8}'
    pm = f'{statistics.median(pxs):>6.1f}' if pxs else '-'
    print(f'{reason:>42} {len(vs):>5} {pm:>6} {len(ep):>6} {em} {es} {len(sp):>5} {sm} {ss}')

# deep dive on the band-gated reasons
for reason in ['no_eligible_price_band:yes', 'no_eligible_price_band:no',
               'tte_entry_cutoff:yes', 'tte_entry_cutoff:no',
               'yes_edge_below_threshold', 'no_edge_below_threshold',
               'yes_edge_below_lane_floor', 'no_edge_below_lane_floor',
               'cost_basis_override_yes', 'cost_basis_override_no',
               'market_fade_blocked_no', 'bookflow_no_pressure',
               'countertrend_yes_selloff_regime']:
    vs = byreason.get(reason, [])
    if not vs: continue
    print(f'\n=== {reason} (n={len(vs)}) by asset/side ===')
    ba = collections.defaultdict(list)
    for v in vs:
        e = exit_pnl(v); s = settle_pnl(v)
        ba[(v['asset'], v['side'])].append((e, s, v['px']))
    for k in sorted(ba):
        v = ba[k]
        ev = [x[0] for x in v if x[0] is not None]; sv = [x[1] for x in v if x[1] is not None]
        print(f'  {k[0]:>5} {k[1]:>4} n={len(v):>3} exitMean={statistics.mean(ev) if ev else float("nan"):>7.2f} exitSum={sum(ev):>7.0f} setMean={statistics.mean(sv) if sv else float("nan"):>7.2f} setSum={sum(sv):>7.0f} pxMed={statistics.median([x[2] for x in v]):>5.1f}')
