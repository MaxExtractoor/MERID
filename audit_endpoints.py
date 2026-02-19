"""
MERID Golden Audit Suite v2 — standing regression + SLO baseline.

Run modes:
  python audit_endpoints.py              # full audit (sequential + concurrency)
  python audit_endpoints.py --fast       # sequential only, skip concurrency
  python audit_endpoints.py --json       # output JSON report to stdout

Checks:
  1. Sequential endpoint sweep: status, latency, stub detection, shape validation
  2. Concurrency profile: N parallel requests to heavy endpoints
  3. Latency persistence: writes per-endpoint latency to data/audit_latency.json
  4. SLO budget: per-section latency targets
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8011"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LATENCY_FILE = os.path.join(DATA_DIR, "audit_latency.json")

# ── SLO budgets (max acceptable latency in ms per section) ──────────
SLO_BUDGETS = {
    "Portfolio": 2000,
    "Trading": 2000,
    "Agents": 500,
    "Risk": 500,
    "Health": 500,
    "Wallet": 3000,
    "Prediction": 1000,
    "PredConsensus": 1000,
    "Consensus": 500,
    "Betting": 500,
    "Flow": 1000,
    "Signal": 2000,
    "Operator": 500,
    "TradeFloor": 500,
    "DevSwarm": 1000,
    "Infra": 500,
}

# ── Shape validators ────────────────────────────────────────────────
def _shape_portfolio(data):
    """Validate portfolio summary shape."""
    issues = []
    if not isinstance(data, dict):
        return ["Not a dict"]
    for k in ("equity", "dailyPnl", "totalValue"):
        if k not in data:
            issues.append(f"Missing field: {k}")
        elif not isinstance(data[k], (int, float)):
            issues.append(f"{k} not numeric: {type(data[k]).__name__}")
    return issues

def _shape_pred_consensus(data):
    """Validate prediction consensus summary shape."""
    issues = []
    if not isinstance(data, dict):
        return ["Not a dict"]
    for k in ("symbols", "count"):
        if k not in data:
            issues.append(f"Missing field: {k}")
    if "symbols" in data and isinstance(data["symbols"], list):
        for i, sym in enumerate(data["symbols"][:3]):
            for fld in ("symbol", "category", "market_prob"):
                if fld not in sym:
                    issues.append(f"symbols[{i}] missing {fld}")
    if "_stub" in data and data["_stub"]:
        issues.append("STUB response")
    return issues

def _shape_pred_metrics(data):
    """Validate prediction metrics shape."""
    issues = []
    if not isinstance(data, dict):
        return ["Not a dict"]
    for k in ("brier", "universe", "plans"):
        if k not in data:
            issues.append(f"Missing field: {k}")
    if "universe" in data and isinstance(data["universe"], dict):
        if data["universe"].get("active_instruments", 0) == 0:
            issues.append("No active instruments")
    return issues

def _shape_agents(data):
    """Validate agents list shape."""
    issues = []
    if not isinstance(data, list):
        return ["Not a list"]
    for i, agent in enumerate(data[:3]):
        for fld in ("id", "name", "role", "status"):
            if fld not in agent:
                issues.append(f"agents[{i}] missing {fld}")
    return issues

def _shape_health(data):
    """Validate system health shape (v1 returns list of components, v2 returns dict)."""
    issues = []
    if isinstance(data, list):
        # v1 format: array of component health objects
        if len(data) == 0:
            issues.append("Empty component list")
        for i, comp in enumerate(data[:3]):
            if isinstance(comp, dict) and "name" not in comp and "component" not in comp:
                issues.append(f"components[{i}] missing name/component field")
        return issues
    if isinstance(data, dict):
        if "status" not in data and "overall_status" not in data:
            issues.append("Missing status field")
        return issues
    return ["Unexpected type: " + type(data).__name__]

def _shape_signal_metrics(data):
    """Validate signal metrics shape."""
    issues = []
    if not isinstance(data, dict):
        return ["Not a dict"]
    for k in ("store", "arb", "drift"):
        if k not in data:
            issues.append(f"Missing field: {k}")
    if "_latency_ms" in data and data["_latency_ms"] > 5000:
        issues.append(f"Internal latency {data['_latency_ms']}ms exceeds 5s target")
    return issues


# ── Endpoint registry ───────────────────────────────────────────────
# (section, label, path, slo_group, shape_fn_or_None, skip_in_fast)
ENDPOINTS = [
    # §1 Portfolio & Trading
    ("Portfolio", "Portfolio Summary", "/api/v1/portfolio/summary", "Portfolio", _shape_portfolio, False),
    ("Trading", "Positions", "/api/v1/positions", "Trading", None, False),
    ("Trading", "Positions Summary", "/api/v1/positions/summary", "Trading", None, False),
    ("Trading", "Orders", "/api/v1/orders", "Trading", None, False),
    ("Trading", "Orders Summary", "/api/v1/orders/summary", "Trading", None, False),
    ("Trading", "Fills", "/api/v1/fills", "Trading", None, False),
    ("Trading", "Trading Summary", "/api/trading/summary", "Trading", None, False),

    # §2 Agents
    ("Agents", "Agent Fleet", "/api/v1/agents", "Agents", _shape_agents, False),
    ("Agents", "Agent Summary", "/api/agents/summary", "Agents", None, False),
    ("Agents", "Agent Charters", "/api/v1/charters", "Agents", None, False),

    # §3 Risk & Health
    ("Risk", "Risk Metrics", "/api/v1/risk/metrics", "Risk", None, False),
    ("Risk", "Risk PnL", "/api/risk/pnl-summary", "Risk", None, False),
    ("Risk", "Risk Exposure", "/api/risk/exposure", "Risk", None, False),
    ("Risk", "Risk Limits", "/api/risk/limits", "Risk", None, False),
    ("Risk", "Risk Protections", "/api/risk/protections", "Risk", None, False),
    ("Risk", "Risk Alerts", "/api/v1/risk/alerts", "Risk", None, False),
    ("Health", "Health v1", "/api/v1/system/health", "Health", _shape_health, False),
    ("Health", "Health v2", "/api/system/health", "Health", None, False),
    ("Health", "Version", "/api/system/version", "Health", None, False),
    ("Health", "Components", "/api/system/components", "Health", None, False),

    # §4 Wallet
    ("Wallet", "Balances", "/api/v1/wallet/balances", "Wallet", None, False),

    # §5 Prediction Markets
    ("Prediction", "US Compliant", "/api/v1/us-compliant/prediction-markets", "Prediction", None, False),
    ("Prediction", "Pred Positions", "/api/v1/prediction-markets/positions", "Prediction", None, False),

    # §6 Prediction Consensus
    ("PredConsensus", "Summary", "/api/v1/prediction/consensus/summary", "PredConsensus", _shape_pred_consensus, False),
    ("PredConsensus", "Opinions", "/api/v1/prediction/consensus/opinions", "PredConsensus", None, False),
    ("PredConsensus", "Plans", "/api/v1/prediction/consensus/plans", "PredConsensus", None, False),
    ("PredConsensus", "Instruments", "/api/v1/prediction/consensus/instruments", "PredConsensus", None, False),
    ("PredConsensus", "Pred Metrics", "/api/v1/prediction/metrics", "PredConsensus", _shape_pred_metrics, False),

    # §7 TaCo Consensus
    ("Consensus", "Summary", "/api/v1/consensus/summary", "Consensus", None, False),
    ("Consensus", "Metrics", "/api/v1/consensus/metrics", "Consensus", None, False),
    ("Consensus", "Recent", "/api/v1/consensus/recent", "Consensus", None, False),
    ("Consensus", "Debate", "/api/v1/consensus/debate/latest", "Consensus", None, False),

    # §8 Betting Consensus
    ("Betting", "Summary", "/api/v1/betting/consensus/summary", "Betting", None, False),
    ("Betting", "Events", "/api/v1/betting/consensus/events", "Betting", None, False),
    ("Betting", "Plans", "/api/v1/betting/consensus/plans", "Betting", None, False),
    ("Betting", "Metrics", "/api/v1/betting/consensus/metrics", "Betting", None, False),

    # §9 Flow Radar
    ("Flow", "Radar", "/api/v1/flow/radar", "Flow", None, False),
    ("Flow", "Tokens", "/api/v1/flow/tokens", "Flow", None, False),
    ("Flow", "Entities", "/api/v1/flow/entities", "Flow", None, False),
    ("Flow", "Events", "/api/v1/flow/events", "Flow", None, False),
    ("Flow", "Plans", "/api/v1/flow/plans", "Flow", None, False),
    ("Flow", "Sniper Status", "/api/v1/flow/sniper/status", "Flow", None, False),
    ("Flow", "Sniper Fills", "/api/v1/flow/sniper/fills", "Flow", None, False),
    ("Flow", "Risk", "/api/v1/flow/risk", "Flow", None, False),
    ("Flow", "Metrics", "/api/v1/flow/metrics", "Flow", None, False),

    # §10 Signal Layer (exclude path-param-only endpoints)
    ("Signal", "Macro", "/api/v1/signal-layer/macro", "Signal", None, False),
    ("Signal", "Arbs", "/api/v1/signal-layer/arbs", "Signal", None, False),
    ("Signal", "Arb Plans", "/api/v1/signal-layer/arb-plans", "Signal", None, False),
    ("Signal", "Drift", "/api/v1/signal-layer/drift", "Signal", None, False),
    ("Signal", "CQI", "/api/v1/signal-layer/cqi", "Signal", None, False),
    ("Signal", "Metrics", "/api/v1/signal-layer/metrics", "Signal", _shape_signal_metrics, False),
    ("Signal", "Decay Configs", "/api/v1/signal-layer/decay-configs", "Signal", None, False),

    # §11 API & Research
    ("Infra", "API Status", "/api/v1/api/status", "Infra", None, False),
    ("Infra", "Backtest Results", "/api/v1/research/backtest/results", "Infra", None, False),
    ("Infra", "Prime Status", "/api/prime/status", "Infra", None, False),

    # §12 Operator
    ("Operator", "Audit Trail", "/api/operator/audit-trail", "Operator", None, False),
    ("Operator", "System Status", "/api/operator/system/status", "Operator", None, False),

    # §13 Trade Floor
    ("TradeFloor", "Status", "/api/v1/trade-floor/status", "TradeFloor", None, False),
    ("TradeFloor", "Active Trades", "/api/v1/trade-floor/active-trades", "TradeFloor", None, False),
    ("TradeFloor", "Signals", "/api/v1/trade-floor/signals", "TradeFloor", None, False),

    # §14 Dev Swarm
    ("DevSwarm", "Status", "/api/dev-swarm/status", "DevSwarm", None, False),
    ("DevSwarm", "Agents", "/api/dev-swarm/agents", "DevSwarm", None, False),

    # §15 Infrastructure
    ("Infra", "Blockchain Health", "/api/v1/blockchain/health", "Infra", None, False),
    ("Infra", "Sentiment", "/api/v1/signals/sentiment", "Infra", None, False),
    ("Infra", "Decisions", "/api/v1/system/decisions/recent", "Infra", None, False),
    ("Infra", "Logs", "/api/v1/logs", "Infra", None, False),
    ("Infra", "Notifications", "/api/v1/notifications", "Infra", None, False),
    ("Infra", "Notif Stats", "/api/v1/notifications/stats", "Infra", None, False),
]


# ── Single-endpoint test ────────────────────────────────────────────
def test_endpoint(section, label, path, slo_group, shape_fn):
    """Test a single endpoint. Returns result dict."""
    issues = []
    is_stub = False
    status_code = 0
    latency_ms = 0
    data = None

    try:
        t0 = time.monotonic()
        req = urllib.request.Request(f"{BASE}{path}")
        resp = urllib.request.urlopen(req, timeout=20)
        latency_ms = int((time.monotonic() - t0) * 1000)
        status_code = resp.status
        body = resp.read().decode("utf-8", errors="replace")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            issues.append("Not valid JSON")

        if isinstance(data, dict):
            if data.get("_stub"):
                is_stub = True
                issues.append(f"STUB: {data.get('_stub_message', '')[:60]}")
            if data.get("data_mode") == "offline":
                is_stub = True
                issues.append("DATA_MODE=offline")

        # Shape validation
        if shape_fn and data is not None:
            shape_issues = shape_fn(data)
            issues.extend(shape_issues)

        # SLO check
        budget = SLO_BUDGETS.get(slo_group, 3000)
        if latency_ms > budget:
            issues.append(f"SLO breach: {latency_ms}ms > {budget}ms budget")

    except urllib.error.HTTPError as e:
        status_code = e.code
        try:
            body = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            body = ""
        issues.append(f"HTTP {status_code}: {body[:80]}")
    except Exception as e:
        issues.append(f"ERROR: {str(e)[:80]}")

    if status_code == 200 and not is_stub and not issues:
        verdict = "PASS"
    elif status_code == 200 and (is_stub or issues):
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "section": section,
        "label": label,
        "path": path,
        "slo_group": slo_group,
        "status": status_code,
        "latency_ms": latency_ms,
        "is_stub": is_stub,
        "verdict": verdict,
        "issues": issues,
    }


# ── Concurrency profile test ────────────────────────────────────────
CONCURRENCY_TARGETS = [
    ("/api/v1/portfolio/summary", 5),
    ("/api/v1/prediction/consensus/summary", 5),
    ("/api/v1/signal-layer/metrics", 3),
    ("/api/system/health", 10),
]

def run_concurrency_test():
    """Fire N parallel requests at heavy endpoints, measure p50/p95."""
    print("\n--- CONCURRENCY PROFILE ---")
    concurrency_results = []

    for path, n in CONCURRENCY_TARGETS:
        latencies = []

        def _fire(_):
            t0 = time.monotonic()
            try:
                resp = urllib.request.urlopen(f"{BASE}{path}", timeout=20)
                resp.read()
                return int((time.monotonic() - t0) * 1000)
            except Exception:
                return -1

        with ThreadPoolExecutor(max_workers=n) as pool:
            futs = [pool.submit(_fire, i) for i in range(n)]
            for f in as_completed(futs):
                lat = f.result()
                if lat >= 0:
                    latencies.append(lat)

        if latencies:
            latencies.sort()
            p50 = latencies[len(latencies) // 2]
            p95 = latencies[int(len(latencies) * 0.95)]
            worst = latencies[-1]
            failures = n - len(latencies)
            verdict = "PASS" if worst < 5000 and failures == 0 else "WARN"
            print(f"  {verdict:>4}  {path:<50} n={n}  p50={p50}ms  p95={p95}ms  max={worst}ms  fail={failures}")
            concurrency_results.append({
                "path": path, "n": n, "p50": p50, "p95": p95,
                "max": worst, "failures": failures, "verdict": verdict,
            })
        else:
            print(f"  FAIL  {path:<50} n={n}  ALL REQUESTS FAILED")
            concurrency_results.append({
                "path": path, "n": n, "p50": 0, "p95": 0,
                "max": 0, "failures": n, "verdict": "FAIL",
            })

    return concurrency_results


# ── Latency persistence ─────────────────────────────────────────────
def persist_latencies(results):
    """Append current run's latencies to a rolling JSON file."""
    os.makedirs(DATA_DIR, exist_ok=True)

    history = []
    if os.path.exists(LATENCY_FILE):
        try:
            with open(LATENCY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []

    # Keep last 100 runs
    if len(history) >= 100:
        history = history[-99:]

    run = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": {r["path"]: r["latency_ms"] for r in results if r["status"] == 200},
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r["verdict"] == "PASS"),
            "warn": sum(1 for r in results if r["verdict"] == "WARN"),
            "fail": sum(1 for r in results if r["verdict"] == "FAIL"),
            "avg_latency_ms": int(
                sum(r["latency_ms"] for r in results if r["status"] == 200)
                / max(1, sum(1 for r in results if r["status"] == 200))
            ),
        },
    }
    history.append(run)

    with open(LATENCY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    # Show regression warning if avg latency increased >30% from previous run
    if len(history) >= 2:
        prev_avg = history[-2]["summary"]["avg_latency_ms"]
        curr_avg = run["summary"]["avg_latency_ms"]
        if prev_avg > 0 and curr_avg > prev_avg * 1.3:
            print(f"\n  WARNING LATENCY REGRESSION: avg {prev_avg}ms -> {curr_avg}ms (+{((curr_avg/prev_avg)-1)*100:.0f}%)")


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    fast_mode = "--fast" in sys.argv
    json_mode = "--json" in sys.argv

    print(f"MERID Golden Audit Suite v2 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base: {BASE}  Mode: {'fast' if fast_mode else 'full'}")
    print(f"{'='*80}")

    # Phase 1: Sequential endpoint sweep
    results = []
    for section, label, path, slo_group, shape_fn, skip_fast in ENDPOINTS:
        if fast_mode and skip_fast:
            continue
        r = test_endpoint(section, label, path, slo_group, shape_fn)
        results.append(r)

        tag = {"PASS": "  OK ", "WARN": "WARN ", "FAIL": "FAIL "}[r["verdict"]]
        stub = " [STUB]" if r["is_stub"] else ""
        iss = f"  ({'; '.join(r['issues'])})" if r["issues"] else ""
        print(f"  {tag} {r['status']:>3} {r['latency_ms']:>5}ms  {label:<25} {path}{stub}{iss}")

    # Phase 2: Concurrency profile
    concurrency_results = []
    if not fast_mode:
        concurrency_results = run_concurrency_test()

    # Phase 3: Summary
    passes = [r for r in results if r["verdict"] == "PASS"]
    warns = [r for r in results if r["verdict"] == "WARN"]
    fails = [r for r in results if r["verdict"] == "FAIL"]
    stubs = [r for r in results if r["is_stub"]]

    ok_results = [r for r in results if r["status"] == 200]
    avg_lat = sum(r["latency_ms"] for r in ok_results) / max(1, len(ok_results))

    print(f"\n{'='*80}")
    print(f"AUDIT SUMMARY: {len(results)} endpoints")
    print(f"  PASS: {len(passes)}  |  WARN: {len(warns)}  |  FAIL: {len(fails)}  |  STUBS: {len(stubs)}")
    print(f"  Avg latency: {avg_lat:.0f}ms")

    # SLO summary per section
    slo_groups = {}
    for r in results:
        g = r["slo_group"]
        slo_groups.setdefault(g, []).append(r)

    print(f"\n  SLO Budget Status:")
    for group, group_results in sorted(slo_groups.items()):
        budget = SLO_BUDGETS.get(group, 3000)
        max_lat = max((r["latency_ms"] for r in group_results), default=0)
        breaches = sum(1 for r in group_results if r["latency_ms"] > budget)
        status = "OK" if breaches == 0 else f"BREACH({breaches})"
        print(f"    {group:<20} budget={budget:>5}ms  max={max_lat:>5}ms  {status}")

    if fails:
        print(f"\n--- FAILURES ({len(fails)}) ---")
        for r in fails:
            print(f"  {r['label']:<25} {r['path']}")
            for i in r["issues"]:
                print(f"    -> {i}")

    if stubs:
        print(f"\n--- STUBS ({len(stubs)}) ---")
        for r in stubs:
            print(f"  {r['label']:<25} {r['path']}")

    # Phase 4: Persist latencies
    persist_latencies(results)
    print(f"\nLatency history saved to {LATENCY_FILE}")

    # Phase 5: UI Manifest cross-validation
    manifest_delta = {"missing_from_audit": [], "missing_from_manifest": []}
    try:
        from merid.ui_views_manifest import all_api_paths as manifest_api_paths, coverage_report
        audit_paths = {ep[2] for ep in ENDPOINTS}
        manifest_paths = set(manifest_api_paths())
        missing_from_audit = sorted(manifest_paths - audit_paths)
        missing_from_manifest = sorted(audit_paths - manifest_paths)
        manifest_delta = {
            "missing_from_audit": missing_from_audit,
            "missing_from_manifest": missing_from_manifest,
        }
        cov = coverage_report()
        print(f"\n--- UI MANIFEST CROSS-CHECK ---")
        print(f"  Manifest: {cov['total_views']} views, {cov['total_components']} components, {cov['total_unique_apis']} APIs")
        print(f"  Audit registry: {len(audit_paths)} APIs")
        if missing_from_audit:
            print(f"  In manifest, NOT in audit ({len(missing_from_audit)}):")
            for p in missing_from_audit:
                print(f"    + {p}")
        if missing_from_manifest:
            print(f"  In audit, NOT in manifest ({len(missing_from_manifest)}):")
            for p in missing_from_manifest:
                print(f"    - {p}")
        if not missing_from_audit and not missing_from_manifest:
            print(f"  Coverage: FULL — manifest and audit are in sync")
    except ImportError:
        print(f"\n  (UI manifest cross-check skipped — merid.ui_views_manifest not found)")

    # JSON output
    if json_mode:
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "concurrency": concurrency_results,
            "manifest_delta": manifest_delta,
            "summary": {
                "total": len(results),
                "pass": len(passes),
                "warn": len(warns),
                "fail": len(fails),
                "stubs": len(stubs),
                "avg_latency_ms": int(avg_lat),
            },
        }
        print(json.dumps(report, indent=2))

    # Exit code: 1 if any true failures
    sys.exit(1 if fails else 0)

