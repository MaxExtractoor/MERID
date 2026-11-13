"""Counterfactual: band-rejected candidates with positive net_edge.

For each unique (ticker, side) first rejection where reject_reason is
no_eligible_price_band:* and net_edge >= MIN_EV, join settlement outcome and
compute hold-to-settle P&L in cents. Also bucket by asset/side/price-band/TTE.
"""
import json, collections, sys

REJ = 'logs/rejected_candidates.jsonl'
SET = 'logs/settlement_outcomes.jsonl'
MIN_EV = 0.03  # net_edge units appear to be dollars/contract -> 3c floor

# ---- load settlements ----
settle = {}
with open(SET, 'r', encoding='utf-8', errors='replace') as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        t = r.get('ticker')
        ry = r.get('resolved_yes')
        if t and ry is not None:
            settle[t] = int(ry)
print('settlements loaded:', len(settle), file=sys.stderr)

# ---- first band-rejection per (ticker,side) with net_edge>=MIN_EV ----
first = {}
allrows = []
with open(REJ, 'r', encoding='utf-8', errors='replace') as f:
    for ln in f:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        rr = r.get('reject_reason') or ''
        if not rr.startswith('no_eligible_price_band'):
            continue
        try:
            nev = float(r.get('net_edge'))
        except Exception:
            continue
        if nev < MIN_EV:
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
        except Exception:
            continue
        if not (0 < px < 100):
            continue
        rec = {
            'ticker': t, 'side': side, 'asset': r.get('asset'),
            'px': px, 'net_edge': nev,
            'tte': r.get('tte_seconds'), 'p': r.get('model_p_selected'),
            'reason': rr,
        }
        first[key] = rec
        allrows.append(rec)

print('unique band-rejected +EV candidates:', len(first), file=sys.stderr)

# ---- join settlement, compute P&L ----
def band(px):
    b = int(px // 10) * 10
    return f'{b}-{b+9}' if b < 90 else '90+'

cells = collections.defaultdict(list)
tot = collections.defaultdict(lambda: [0, 0.0, 0])  # n, sum_pnl, wins
for rec in allrows:
    ry = settle.get(rec['ticker'])
    if ry is None:
        continue
    px = rec['px']
    if rec['side'] == 'yes':
        pnl = (100.0 - px) if ry == 1 else -px
    else:
        pnl = (100.0 - px) if ry == 0 else -px
    a = rec['asset'] or '?'
    key = (a, rec['side'], band(px))
    cells[key].append(pnl)
    t = tot[(a, rec['side'])]
    t[0] += 1; t[1] += pnl; t[2] += 1 if pnl > 0 else 0

print('\n=== by asset x side (settle P&L, cents) ===')
for k in sorted(tot, key=lambda k: -tot[k][1]):
    n, s, w = tot[k]
    print(f'{k[0]:5s} {k[1]:3s} n={n:5d} mean={s/n:+7.2f} sum={s:+9.1f} win%={100*w/n:5.1f}')

print('\n=== top cells asset x side x band (n>=15) ===')
rows = []
for k, v in cells.items():
    if len(v) < 15:
        continue
    rows.append((sum(v) / len(v), len(v), k, sum(v)))
rows.sort(reverse=True)
for mean, n, k, s in rows[:25]:
    print(f'{k[0]:5s} {k[1]:3s} {k[2]:6s} n={n:5d} mean={mean:+7.2f} sum={s:+9.1f}')
print('\n=== worst cells ===')
for mean, n, k, s in rows[-15:]:
    print(f'{k[0]:5s} {k[1]:3s} {k[2]:6s} n={n:5d} mean={mean:+7.2f} sum={s:+9.1f}')
