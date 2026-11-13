"""Counterfactual: below-threshold positive-edge rejections.

Cohort: reject_reason in (*_edge_below_threshold, *_edge_below_lane_floor)
with 0 < net_edge < edge_threshold. Dedupe first-per-(ticker,side), join
settlement, compute hold-to-settle P&L. Bucket asset x side x price band.
"""
import json, collections, sys

REJ = 'logs/rejected_candidates.jsonl'
SET = 'logs/settlement_outcomes.jsonl'

settle = {}
with open(SET, 'r', encoding='utf-8', errors='replace') as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        t = r.get('ticker'); ry = r.get('resolved_yes')
        if t and ry is not None:
            settle[t] = int(ry)
print('settlements:', len(settle), file=sys.stderr)

first = {}
with open(REJ, 'r', encoding='utf-8', errors='replace') as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        rr = r.get('reject_reason') or ''
        if 'edge_below_threshold' not in rr and 'edge_below_lane_floor' not in rr:
            continue
        try:
            nev = float(r.get('net_edge'))
        except Exception:
            continue
        if nev <= 0:
            continue
        t = r.get('ticker'); side = r.get('side')
        if not t or side not in ('yes', 'no'):
            continue
        key = (t, side)
        if key in first:
            continue
        try:
            px = float(r.get('executable_price_cents')
                       if r.get('executable_price_cents') is not None
                       else r.get('held_price_cents'))
            thr = float(r.get('edge_threshold') or r.get('dynamic_threshold'))
        except Exception:
            continue
        if not (0 < px < 100):
            continue
        first[key] = {
            'ticker': t, 'side': side, 'asset': r.get('asset'), 'px': px,
            'net_edge': nev, 'thr': thr, 'tte': r.get('tte_seconds'),
            'reason': rr,
        }
print('unique below-threshold +EV candidates:', len(first), file=sys.stderr)

def band(px):
    b = int(px // 10) * 10
    return f'{b}-{b+9}' if b < 90 else '90+'

cells = collections.defaultdict(list)
tot = collections.defaultdict(lambda: [0, 0.0, 0])
edge_sum = collections.defaultdict(float)
for rec in first.values():
    ry = settle.get(rec['ticker'])
    if ry is None:
        continue
    px = rec['px']
    pnl = ((100.0 - px) if ry == 1 else -px) if rec['side'] == 'yes' \
        else ((100.0 - px) if ry == 0 else -px)
    a = rec['asset'] or '?'
    cells[(a, rec['side'], band(px))].append(pnl)
    t = tot[(a, rec['side'])]
    t[0] += 1; t[1] += pnl; t[2] += 1 if pnl > 0 else 0
    edge_sum[(a, rec['side'])] += rec['net_edge'] * 100  # cents

print('\n=== asset x side settle P&L (cents) ===')
for k in sorted(tot, key=lambda k: -tot[k][1]):
    n, s, w = tot[k]
    print(f'{k[0]:5s} {k[1]:3s} n={n:5d} mean={s/n:+7.2f} sum={s:+9.1f} win%={100*w/n:5.1f} claimedEV_sum={edge_sum[k]:+8.1f}c')

print('\n=== cells n>=20 sorted by mean ===')
rows = []
for k, v in cells.items():
    if len(v) >= 20:
        rows.append((sum(v) / len(v), len(v), k, sum(v)))
rows.sort(reverse=True)
for mean, n, k, s in rows:
    print(f'{k[0]:5s} {k[1]:3s} {k[2]:6s} n={n:5d} mean={mean:+7.2f} sum={s:+9.1f}')
