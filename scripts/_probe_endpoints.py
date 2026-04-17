"""Probe all frontend-referenced API endpoints and classify as OK / STUB / ERR / 404."""
import requests
import json
import sys

BASE = "http://localhost:8011"

ENDPOINTS = [
    # ── Core Dashboard / System ──
    "/api/v1/system/health",
    "/api/v1/system/execution-gate",
    "/api/v1/system/mode-safety",
    "/api/v1/system/pnl-consistency",
    "/api/v1/system/price-feed-staleness",
    "/api/v1/system/session-log",
    "/api/v1/loop/execution/status",
    "/api/v1/loop/tick-log",
    "/api/v1/loop/status",
    "/api/v1/loop/guard/verdicts",
    "/api/v1/telemetry",
    # ── Operator ──
    "/api/v1/operator/summary",
    "/api/v1/operator/kill-switch-status",
    "/api/v1/operator/risk-state",
    "/api/v1/operator/agent-activity",
    "/api/v1/operator/audit-trail",
    "/api/v1/operator/decisions/recent",
    "/api/v1/operator/equity-series",
    "/api/v1/swarm/prime-screen/state",
    # ── Kalshi Deep Integration ──
    "/api/v1/kalshi/balance",
    "/api/v1/kalshi/positions",
    "/api/v1/kalshi/orders",
    "/api/v1/kalshi/fills",
    "/api/v1/kalshi/pnl",
    "/api/v1/kalshi/risk",
    "/api/v1/kalshi/catalog",
    "/api/v1/kalshi/markets",
    "/api/v1/kalshi/health",
    "/api/v1/kalshi/kill-switch",
    "/api/v1/kalshi/edge",
    "/api/v1/kalshi/order-errors",
    "/api/v1/kalshi/sizing-metrics",
    "/api/v1/kalshi/pnl-history",
    "/api/v1/kalshi/volume-changes",
    "/api/v1/kalshi/volume-anomalies",
    "/api/v1/kalshi/volume-alerts",
    "/api/v1/kalshi/liquidity-alerts",
    "/api/v1/kalshi/consensus-signals",
    "/api/v1/kalshi/news-signals",
    "/api/v1/kalshi/publish-pipeline",
    "/api/v1/kalshi/categories",
    "/api/v1/kalshi/favorites",
    "/api/v1/kalshi/risk/events",
    "/api/v1/kalshi/lane/status",
    "/api/v1/kalshi/insights",
    # ── Kalshi Grid ──
    "/api/v1/kalshi-grid/status",
    "/api/v1/kalshi-grid/matrix",
    "/api/v1/kalshi-grid/portfolio",
    "/api/v1/kalshi-grid/fills",
    "/api/v1/kalshi-grid/health",
    "/api/v1/kalshi-grid/session",
    "/api/v1/kalshi-grid/agents",
    "/api/v1/kalshi-grid/sentiment",
    "/api/v1/kalshi-grid/crypto/rti",
    # ── Kalshi Grid Performance ──
    "/api/v1/kalshi-grid/performance/agents",
    "/api/v1/kalshi-grid/performance/summary",
    "/api/v1/kalshi-grid/performance/top",
    "/api/v1/kalshi-grid/performance/calibration",
    "/api/v1/kalshi-grid/performance/execution",
    # ── Risk ──
    "/api/v1/risk/summary",
    "/api/v1/risk/halt-status",
    "/api/v1/risk/staleness",
    "/api/v1/risk/alerts",
    "/api/v1/risk/position-limits",
    # ── Sentiment ──
    "/api/v1/sentiment/assets",
    "/api/v1/sentiment/monitor/status",
    "/api/v1/sentiment/asset/BTC",
    "/api/v1/kalshi/sentiment/bundle/BTC",
    "/api/v1/kalshi/sentiment/lane-snapshot",
    # ── XTF ──
    "/api/v1/xtf/signals",
    "/api/v1/xtf/status",
    # ── Consensus / Mood ──
    "/api/v1/kalshi/consensus/all",
    "/api/v1/kalshi/mood/all",
    "/api/v1/kalshi/mood/fear-greed/BTC",
    # ── Swarm ──
    "/api/v1/kalshi/swarm/critic/history",
    "/api/v1/kalshi/swarm/recalibration",
    "/api/v1/kalshi/swarm/execution/stats",
    # ── Deployment ──
    "/api/v1/kalshi/deployment/status",
    "/api/v1/kalshi/deployment/transitions",
    "/api/v1/kalshi/deployment/auto-promoter/status",
    "/api/v1/kalshi/deployment/auto-promoter/promotions",
    # ── Correlation ──
    "/api/v1/kalshi/correlation/matrix",
    "/api/v1/kalshi/correlation/factor",
    "/api/v1/kalshi/correlation/clusters",
    # ── Prediction Consensus ──
    "/api/v1/prediction/consensus/summary",
    "/api/v1/prediction/consensus/plans",
    "/api/v1/prediction/consensus/opinions",
    "/api/v1/prediction/consensus/debates",
    "/api/v1/prediction/consensus/debate-metrics",
    "/api/v1/prediction/consensus/teams",
    "/api/v1/prediction/consensus/leaderboard",
    "/api/v1/prediction/metrics",
    # ── Metrics / Forecasters ──
    "/api/v1/kalshi/metrics/forecasters",
    "/api/v1/kalshi/metrics/resolver",
    # ── Trade Mode / Reconciliation ──
    "/api/v1/trade-mode",
    "/api/v1/reconciliation/status",
    # ── Audit Trail ──
    "/api/v1/audit-trail/summary",
    "/api/v1/audit-trail/entries",
    # ── Data ──
    "/api/v1/data/freshness",
    # ── Logs ──
    "/api/v1/logs",
    "/api/v1/logs/stats",
    # ── Paper Ladder ──
    "/api/v1/paper-ladder/status",
    # ── Resilience ──
    "/api/v1/resilience/breakers",
    # ── Latency ──
    "/api/metrics/latency",
    # ── Notifications ──
    "/api/v1/notifications",
    "/api/v1/notifications/status",
    "/api/v1/notifications/recent-alerts",
    "/api/v1/notifications/telegram/log",
    # ── Debates ──
    "/debates/alerts",
    "/debates/correlation",
    "/debates/health/overview",
    "/debates/rollups",
    "/debates/historical-contribution",
    # ── UI ──
    "/api/v1/ui/sidebar",
    "/api/v1/ui/mode-indicator",
    # ── Incentives ──
    "/api/v1/incentives/leaderboard",
    "/api/v1/incentives/weight-history",
    # ── Order Groups ──
    "/api/v1/kalshi/order-groups",
    "/api/v1/kalshi/order-groups/dashboard",
    # ── Signals ──
    "/api/v1/signals/alerts/history",
    # ── Explainability ──
    "/api/v1/explainability/decisions",
    # ── Pipeline ──
    "/api/v1/pipeline/venues",
]

results = {"OK": [], "STUB": [], "ERR": [], "404": [], "FAIL": []}

for ep in ENDPOINTS:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=12)
        body = r.text[:500]
        is_stub = '"_stub": true' in body or '"_stub":true' in body
        code = r.status_code
        if code == 404:
            cat = "404"
        elif is_stub:
            cat = "STUB"
        elif code >= 400:
            cat = "ERR"
        else:
            cat = "OK"
        # Show a short snippet
        snippet = body[:100].replace("\n", " ")
        results[cat].append(f"  {code} {ep}  =>  {snippet}")
    except Exception as e:
        results["FAIL"].append(f"  --- {ep}  =>  {e}")

for cat in ["OK", "STUB", "ERR", "404", "FAIL"]:
    items = results[cat]
    print(f"\n{'='*60}")
    print(f" {cat} ({len(items)} endpoints)")
    print(f"{'='*60}")
    for line in items:
        print(line)

print(f"\n\nSUMMARY: OK={len(results['OK'])}  STUB={len(results['STUB'])}  ERR={len(results['ERR'])}  404={len(results['404'])}  FAIL={len(results['FAIL'])}")
