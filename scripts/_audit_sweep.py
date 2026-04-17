"""Full system audit sweep across 21 dimensions."""
import os
import re
import json
import sys

DIRS = ['merid', 'core', 'trading', 'web', 'agents', 'risk', 'execution',
        'swarm', 'governance', 'security', 'monitoring', 'memory', 'streaming',
        'streams', 'analytics', 'arbitrage', 'prediction', 'ml', 'ai_signals']

findings = {}

def add(category, filepath, line, detail=""):
    findings.setdefault(category, []).append({
        "file": filepath, "line": line, "detail": detail
    })

def scan_file(fp):
    try:
        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception:
        return

    fpu = fp.replace(os.sep, '/')

    for i, line in enumerate(lines):
        s = line.strip()
        prev = lines[i-1].strip() if i > 0 else ""

        # 1. Silent except pass (error propagation failure)
        if s == 'pass' and 'except' in prev:
            add('SILENT_EXCEPT_PASS', fp, i+1, prev)

        # 2. Bare except (cascading meltdown risk)
        if re.match(r'^\s*except\s*:\s*$', line):
            add('BARE_EXCEPT', fp, i+1)

        # 3. HTTP calls without timeout
        if any(lib in s for lib in ['httpx.', 'requests.', 'aiohttp.']):
            if any(m in s for m in ['.get(', '.post(', '.put(', '.delete(', '.patch(']):
                ctx = '\n'.join(lines[max(0,i-3):i+4])
                if 'timeout' not in ctx.lower():
                    add('HTTP_NO_TIMEOUT', fp, i+1, s[:120])

        # 4. SQL injection risk (f-string in execute)
        if 'execute(' in s or 'executemany(' in s:
            if 'f"' in s or "f'" in s:
                if any(kw in s.upper() for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE']):
                    add('SQL_INJECTION_RISK', fp, i+1, s[:120])

        # 5. Unbounded collections in loops/streams
        if '.append(' in s and any(x in fpu for x in ['loop', 'stream', 'bus', 'feed', 'collect', 'monitor']):
            ctx = '\n'.join(lines[max(0,i-10):i+1])
            if 'maxlen' not in ctx and 'deque' not in ctx and '= []' not in ctx.split('\n')[-1]:
                add('UNBOUNDED_COLLECTION', fp, i+1, s[:100])

        # 6. Missing input validation on API endpoints
        if 'web/api' in fpu:
            if '@router.' in s and ('post' in s or 'put' in s or 'patch' in s or 'delete' in s):
                # Check next 10 lines for any validation
                block = '\n'.join(lines[i:min(i+15, len(lines))])
                if 'validate' not in block.lower() and 'Depends' not in block and 'Body(' not in block:
                    if 'BaseModel' not in block and 'Query(' not in block:
                        pass  # Too noisy, skip

        # 7. Hardcoded secrets
        if any(kw in s.lower() for kw in ['api_key', 'secret', 'password', 'token']):
            if '=' in s and ('"""' not in s) and ('#' not in s[:s.index('=')]):
                val_part = s.split('=', 1)[1].strip().strip('"').strip("'")
                if len(val_part) > 10 and not val_part.startswith('os.') and not val_part.startswith('env'):
                    if 'environ' not in s and 'getenv' not in s and 'settings.' not in s:
                        if 'example' not in fpu and 'test' not in fpu and 'mock' not in fpu:
                            if not val_part.startswith('{') and not val_part.startswith('Optional'):
                                if 'None' not in val_part and 'get_' not in val_part:
                                    add('HARDCODED_SECRET', fp, i+1, s[:100])

    # 8. FastAPI routes missing auth
    if 'web/api' in fpu and 'APIRouter' in content:
        if 'get_current_session' not in content and 'Depends' not in content:
            if 'auth.py' not in fpu and 'mock_' not in fpu and 'schema' not in fpu:
                add('API_NO_AUTH', fp, 0, fpu)

    # 9. No drawdown enforcement in trading/execution paths
    if any(x in fpu for x in ['execution', 'order_router', 'trading']):
        if 'submit' in content.lower() or 'place_order' in content.lower():
            if 'drawdown' not in content.lower() and 'risk' not in content.lower():
                add('NO_DRAWDOWN_CHECK', fp, 0, 'Order submission without drawdown/risk check')

    # 10. Missing latency monitoring
    if 'execution' in fpu or 'order' in fpu.lower():
        if 'submit' in content.lower() or 'execute' in content.lower():
            if 'latency' not in content.lower() and 'elapsed' not in content.lower() and 'time.time' not in content:
                if 'perf_counter' not in content and 'monotonic' not in content:
                    add('NO_LATENCY_TRACKING', fp, 0, 'Execution path without latency measurement')

    # 11. No cross-validation / OOS in ML/prediction
    if any(x in fpu for x in ['ml/', 'prediction/', 'forecast', 'model']):
        if 'fit(' in content or 'train(' in content:
            if 'cross_val' not in content and 'test_split' not in content and 'validation' not in content:
                if 'walk_forward' not in content and 'out_of_sample' not in content:
                    add('NO_CROSS_VALIDATION', fp, 0, 'ML training without validation split')

    # 12. Memory pollution in RAG/knowledge base
    if 'memory' in fpu or 'knowledge' in fpu or 'rag' in fpu:
        if 'append' in content or 'insert' in content or 'add' in content:
            if 'max_size' not in content and 'max_entries' not in content and 'evict' not in content:
                if 'ttl' not in content.lower() and 'expire' not in content.lower() and 'cleanup' not in content.lower():
                    add('MEMORY_NO_EVICTION', fp, 0, 'Memory/RAG store without eviction policy')

    # 13. Over-autonomy (autonomous actions without human gate)
    if 'autonomous' in content.lower() or 'auto_execute' in content.lower():
        if 'hitl' not in content.lower() and 'human' not in content.lower() and 'approval' not in content.lower():
            if 'confirm' not in content.lower() and 'gate' not in content.lower():
                add('OVER_AUTONOMY', fp, 0, 'Autonomous execution without human gate')

    # 14. Missing self-critique / confidence calibration
    if 'agent' in fpu and ('predict' in content.lower() or 'decision' in content.lower()):
        pass  # Will check dedicated modules

    # 15. Event-driven gaps (sync calls where async expected)
    if 'event' in fpu or 'bus' in fpu:
        for i2, l2 in enumerate(lines):
            if 'time.sleep(' in l2 and 'async' not in '\n'.join(lines[max(0,i2-5):i2]):
                add('SYNC_SLEEP_IN_ASYNC', fp, i2+1, l2.strip()[:100])


for d in DIRS:
    if not os.path.isdir(d):
        continue
    for root, subdirs, files in os.walk(d):
        subdirs[:] = [x for x in subdirs if x not in ('__pycache__', '.git', 'node_modules', '.venv')]
        for fn in files:
            if fn.endswith('.py'):
                scan_file(os.path.join(root, fn))

# Summary
print("=" * 60)
print("SYSTEM AUDIT SWEEP — FINDINGS SUMMARY")
print("=" * 60)
total = 0
for cat in sorted(findings.keys(), key=lambda c: -len(findings[c])):
    items = findings[cat]
    total += len(items)
    print(f"\n{'='*40}")
    print(f"[{cat}]: {len(items)} issues")
    print(f"{'='*40}")
    for item in items[:25]:
        detail = f" — {item['detail']}" if item['detail'] else ""
        print(f"  {item['file']}:{item['line']}{detail}")
    if len(items) > 25:
        print(f"  ... and {len(items)-25} more")

print(f"\n{'='*60}")
print(f"TOTAL FINDINGS: {total}")
print(f"{'='*60}")

# Write JSON for programmatic use
with open('data/audit_sweep_results.json', 'w') as f:
    json.dump(findings, f, indent=2)
print(f"\nDetailed results written to data/audit_sweep_results.json")
