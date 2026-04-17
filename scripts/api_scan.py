"""Quick 500-error scanner for MERID API routes."""
import requests, sys, time

base = 'http://127.0.0.1:8000'

# Key routes the frontend actually uses
routes = [
    '/api/health',
    '/api/v1/system/status',
    '/api/v1/system/health',
    '/api/v1/system/execution-gate',
    '/api/v1/system/pnl-consistency',
    '/api/v1/system/mode-safety',
    '/api/v1/system/fresh-start',
    '/api/v1/system/slo',
    '/api/v1/system/symbol-status',
    '/api/v1/system/observability',
    '/api/v1/system/session-log',
    '/api/v1/agents',
    '/api/v1/consensus/status',
    '/api/v1/reflection/summary',
    '/api/v1/reflection/reflections',
    '/api/v1/risk/summary',
    '/api/v1/risk/metrics',
    '/api/v1/risk/halt-status',
    '/api/v1/risk/protections',
    '/api/v1/risk/alerts',
    '/api/v1/risk/position-limits',
    '/api/v1/risk/staleness',
    '/api/v1/kalshi/markets',
    '/api/v1/kalshi/portfolio/summary',
    '/api/v1/kalshi/category-stats',
    '/api/v1/kalshi/leaderboard',
    '/api/v1/prediction/paper/session',
    '/api/v1/prediction/paper/intervals',
    '/api/v1/prediction/debates/active',
    '/api/v1/prediction/debates/history',
    '/api/v1/sentiment/assets',
    '/api/v1/sentiment/news',
    '/api/v1/sentiment/hashtags',
    '/api/v1/sentiment/monitor/status',
    '/api/v1/signals/sentiment',
    '/api/v1/live-feeds/status',
    '/api/v1/operator/dashboard',
    '/api/v1/swarm/status',
    '/api/v1/swarm/health',
    '/api/v1/swarm/stats',
    '/api/v1/swarm/agents',
    '/api/v1/swarm/mode',
    '/api/v1/trade-mode',
    '/api/v1/trade-floor/status',
    '/api/v1/trade-floor/signals',
    '/api/v1/trade-floor/active-trades',
    '/api/v1/resilience/status',
    '/api/v1/resilience/breakers',
    '/api/v1/resilience/venues',
    '/api/v1/ui/sidebar',
    '/api/v1/ui/mode-indicator',
    '/api/v1/ticker',
    '/api/v1/social/feed',
    '/api/v1/tokens/balances',
    '/api/v1/treasury/overview',
    '/api/v1/strategy/leaderboard',
    '/api/v1/xtf/signals',
    '/api/v1/xtf/status',
    '/api/v1/telemetry/metrics',
    '/api/v1/telemetry/sli',
    '/api/v1/pipeline/summary',
    '/api/v1/pipeline/venues',
    '/api/v1/pipeline/leaderboard',
    '/api/v1/observability/events',
    '/api/v1/observability/event-bus/stats',
    '/api/v1/promotion/report',
    '/api/v1/promotion/log',
    '/api/v1/research/markets',
    '/healthz',
    '/readyz',
]

ok = auth = not_found = server_err = timeout = 0
issues = []

for ep in routes:
    try:
        r = requests.get(base + ep, timeout=10)
        c = r.status_code
        if c == 200:
            ok += 1
        elif c == 401:
            auth += 1
        elif c == 404:
            not_found += 1
        elif c == 503:
            d = ''
            try:
                d = r.json().get('detail', '')[:100]
            except Exception:
                pass
            issues.append((c, ep, d))
            print(f"{c} {ep}: {d}")
        elif c >= 500:
            server_err += 1
            d = ''
            try:
                d = r.json().get('detail', '')[:100]
            except Exception:
                d = r.text[:100]
            issues.append((c, ep, d))
            print(f"{c} {ep}: {d}")
        else:
            print(f"{c} {ep}")
    except requests.exceptions.Timeout:
        timeout += 1
        issues.append((0, ep, 'TIMEOUT'))
        print(f"TMO {ep}")
    except Exception as e:
        timeout += 1
        issues.append((0, ep, str(e)[:60]))

print(f"\n=== Results ===")
print(f"200 OK:     {ok}")
print(f"401 Auth:   {auth}")
print(f"404 Not Found: {not_found}")
print(f"500+ Error: {server_err}")
print(f"Timeout:    {timeout}")
print(f"Total:      {len(routes)}")

if issues:
    print(f"\n=== Issues ({len(issues)}) ===")
    for c, p, d in issues:
        tag = str(c) if c else 'TMO'
        print(f"  {tag} {p}: {d}")
