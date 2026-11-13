"""Extract first-rejection record per (ticker,side) from rejected_candidates files.

Processes files oldest->newest; within each file lines are chronological, so the
first occurrence of a key wins. Uses orjson for speed on the 12GB archive.
Output: scripts/first_entries.jsonl  (one JSON per line)
"""
import orjson, sys, os

FILES = [
    'logs/rejected_candidates.jsonl.20261111-pre-rotation',
    'logs/rejected_candidates.jsonl.20261113-105344',
    'logs/rejected_candidates.jsonl',
]
OUT = 'scripts/first_entries.jsonl'
SINCE = '2026-10-25T00:00:00'   # keep ~3 weeks

first = {}
for path in FILES:
    if not os.path.exists(path):
        print('missing', path, file=sys.stderr); continue
    n = kept = 0
    with open(path, 'rb') as f:
        for line in f:
            n += 1
            if b'"rejected_candidate"' not in line: continue
            try:
                d = orjson.loads(line)
            except Exception:
                continue
            ts = d.get('event_ts_utc') or ''
            if ts < SINCE: continue
            side = d.get('side'); ticker = d.get('ticker')
            px = d.get('executable_price_cents')
            if px is None: px = d.get('held_price_cents')
            if not ticker or not side or px is None: continue
            key = (ticker, side)
            if key in first: continue
            first[key] = {
                'ts': ts, 'day': ts[:10], 'ticker': ticker, 'asset': d.get('asset'),
                'side': side, 'reason': d.get('reject_reason') or '?',
                'canonical': d.get('canonical_reason'), 'px': float(px),
                'tte': d.get('tte_seconds'), 'net_edge': d.get('net_edge'),
                'depth': d.get('depth_for_quantity_cc'), 'route': d.get('route'),
                'p_sel': d.get('model_p_selected'),
            }
            kept += 1
    print(f'{path}: lines={n} new_keys={kept} total={len(first)}', file=sys.stderr)

with open(OUT, 'w', encoding='utf-8') as f:
    for v in first.values():
        f.write(orjson.dumps(v).decode() + '\n')
print(f'wrote {len(first)} -> {OUT}', file=sys.stderr)
