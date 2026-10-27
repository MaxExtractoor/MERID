#!/usr/bin/env python3
"""Check recent errors in the last hour."""

import json
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
one_hour_ago = now - timedelta(hours=1)

error_count = 0
recent_errors = []

with open('C:\\Dev\\MERID\\logs\\full.log', 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            level = data.get('level', '')
            if level in ('ERROR', 'CRITICAL'):
                ts_str = data.get('ts', '')
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        if ts > one_hour_ago:
                            error_count += 1
                            recent_errors.append(data)
                    except:
                        pass
        except:
            pass

print(f'Total ERROR/CRITICAL in last hour: {error_count}')
print()
print('All errors in last hour:')
print('=' * 80)
for i, err in enumerate(recent_errors, 1):
    ts = err.get('ts', 'N/A')
    level = err.get('level', 'N/A')
    logger = err.get('logger', 'N/A')
    msg = err.get('message', 'N/A')[:150]
    print(f'{i}. {ts}')
    print(f'   Level: {level}')
    print(f'   Logger: {logger}')
    print(f'   Message: {msg}')
    print('-' * 80)
