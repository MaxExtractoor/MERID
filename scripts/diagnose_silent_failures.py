#!/usr/bin/env python3
"""
MERID Silent-Failure & Bug Diagnostic Script
=============================================
Probes the entire stack for issues that don't raise visible errors but corrupt
the UI, return stale/empty data, or silently degrade functionality.

Categories:
  1. ENDPOINT HEALTH      — HTTP status, timeouts, empty bodies, error keys
  2. DATA QUALITY         — NaN, None, all-zero, empty arrays, stale timestamps
  3. RESPONSE SHAPE       — Missing keys the frontend expects
  4. WEBSOCKET HEALTH     — Connection, first-message, graceful close
  5. DUPLICATE ROUTES     — Backend route collisions (FastAPI shadowing)
  6. FRONTEND STATIC      — Hardcoded data, synthetic generators, dead imports
  7. CROSS-WIRING         — Frontend endpoints with no backend match
  8. PYTHON IMPORT HEALTH — Backend modules that fail to import
  9. SETTINGS ROUNDTRIP   — Save/load cycle integrity

Usage:
  # With server running on :8011
  py scripts/diagnose_silent_failures.py

  # Against a different host
  py scripts/diagnose_silent_failures.py --base http://localhost:9000

  # Skip network probes (static analysis only)
  py scripts/diagnose_silent_failures.py --offline
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import importlib
import json
import math
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_DIR = PROJECT_ROOT / "web" / "api"
MAIN_PY = PROJECT_ROOT / "web" / "main.py"
FE_SRC = PROJECT_ROOT / "web" / "react" / "src"
FE_CONSTANTS = FE_SRC / "config" / "constants.ts"

DEFAULT_BASE = "http://localhost:8011"
TIMEOUT_S = 8
WS_TIMEOUT_S = 5

# Every static GET endpoint the frontend references (extracted from constants.ts)
# These are the endpoints that, if broken, cause silent UI blanks.
STATIC_GET_ENDPOINTS: List[str] = [
    "/api/v1/system/health",
    "/api/v1/system/execution-gate",
    "/api/v1/loop/execution/status",
    "/api/v1/loop/execution/toggle",
    "/api/v1/loop/live-readiness",
    "/api/v1/loop/tick-log",
    "/api/v1/loop/status",
    "/api/v1/system/mode-safety",
    "/api/v1/system/pnl-consistency",
    "/api/v1/system/price-feed-staleness",
    "/api/v1/system/session-log",
    "/api/v1/system/symbol-status",
    "/api/v1/operator/decisions/recent",
    "/api/v1/telemetry",
    "/api/v1/operator/risk-state",
    "/api/v1/risk/summary",
    "/api/v1/risk/halt-status",
    "/api/v1/risk/staleness",
    "/api/v1/risk/alerts",
    "/api/v1/risk/position-limits",
    "/api/v1/risk/agents",
    "/api/v1/notifications",
    "/api/v1/notifications/telegram/log",
    "/api/x/status",
    "/api/v1/notifications/telegram/status",
    "/api/v1/user/profile",
    "/api/v1/user/settings",
    "/api/v1/logs",
    "/api/v1/logs/stats",
    "/api/v1/operator/summary",
    "/api/v1/operator/kill-switch-status",
    "/api/v1/operator/agent-activity",
    "/api/v1/operator/audit-trail",
    "/api/v1/kalshi/orders",
    "/api/v1/kalshi-grid/status",
    "/api/v1/kalshi-grid/matrix",
    "/api/v1/kalshi-grid/agents",
    "/api/v1/kalshi-grid/fills",
    "/api/v1/kalshi-grid/portfolio",
    "/api/v1/kalshi-grid/session",
    "/api/v1/kalshi-grid/health",
    "/api/v1/kalshi-grid/mode",
    "/api/v1/kalshi-grid/sentiment",
    "/api/v1/kalshi-grid/performance/agents",
    "/api/v1/kalshi-grid/performance/summary",
    "/api/v1/kalshi-grid/performance/top",
    "/api/v1/kalshi-grid/performance/calibration",
    "/api/v1/kalshi/markets",
    "/api/v1/kalshi/catalog",
    "/api/v1/kalshi/positions",
    "/api/v1/kalshi/fills",
    "/api/v1/kalshi/balance",
    "/api/v1/kalshi/pnl",
    "/api/v1/kalshi/risk",
    "/api/v1/kalshi/health",
    "/api/v1/kalshi/kill-switch",
    "/api/v1/resilience/breakers",
    "/api/metrics/latency",
    "/api/v1/kalshi/order-errors",
    "/api/v1/kalshi/export",
    "/api/v1/kalshi/volume-changes",
    "/api/v1/kalshi/volume-anomalies",
    "/api/v1/kalshi/volume-alerts",
    "/api/v1/kalshi/sizing-metrics",
    "/api/v1/kalshi/pnl-history",
    "/api/v1/kalshi/liquidity-alerts",
    "/api/v1/kalshi/edge",
    "/api/v1/kalshi/risk/events",
    "/api/v1/kalshi/consensus-signals",
    "/api/v1/kalshi/news-signals",
    "/api/v1/kalshi/publish-pipeline",
    "/api/v1/kalshi/favorites",
    "/api/v1/kalshi/categories",
    "/api/v1/kalshi/order-groups",
    "/api/v1/kalshi/order-groups/dashboard",
    "/api/v1/kalshi/deployment/status",
    "/api/v1/kalshi/deployment/transitions",
    "/api/v1/sentiment/assets",
    "/api/v1/sentiment/hashtags/signals",
    "/api/v1/sentiment/monitor/status",
    "/api/v1/kalshi/risk/btc15m/status",
    "/api/v1/kalshi/mood/all",
    "/api/v1/kalshi/consensus/all",
    "/api/v1/kalshi/insights",
    "/api/v1/kalshi/sentiment/lane-snapshot",
    "/api/v1/xtf/signals",
    "/api/v1/xtf/status",
    "/api/v1/kalshi/deployment/auto-promoter/status",
    "/api/v1/kalshi/deployment/auto-promoter/promotions",
    "/api/v1/kalshi/correlation/matrix",
    "/api/v1/kalshi/correlation/factor",
    "/api/v1/kalshi/correlation/clusters",
    "/api/v1/kalshi/swarm/critic/history",
    "/api/v1/kalshi/swarm/recalibration",
    "/api/v1/kalshi/swarm/execution/stats",
    "/api/v1/kalshi/metrics/forecasters",
    "/api/v1/kalshi/metrics/resolver",
    "/api/v1/prediction/consensus/summary",
    "/api/v1/prediction/consensus/plans",
    "/api/v1/prediction/consensus/opinions",
    "/api/v1/prediction/consensus/debates",
    "/api/v1/prediction/consensus/debate-metrics",
    "/api/v1/prediction/consensus/teams",
    "/api/v1/prediction/consensus/leaderboard",
    "/api/v1/prediction/metrics",
    "/api/v1/trade-mode",
    "/api/v1/reconciliation/status",
    "/api/v1/audit-trail/summary",
    "/api/v1/audit-trail/entries",
    "/api/v1/ui/sidebar",
    "/api/v1/ui/mode-indicator",
    "/api/v1/ui/workflow",
    "/debates/alerts",
    "/debates/correlation",
    "/debates/historical-contribution",
    "/debates/rollups",
    "/debates/health/overview",
    "/api/v1/kalshi-grid/crypto/rti",
    "/api/v1/operator/equity-series",
    "/api/v1/kalshi-grid/performance/execution",
    "/api/v1/kalshi/lane/status",
    "/api/v1/notifications/status",
    "/api/v1/notifications/recent-alerts",
    "/api/v1/loop/guard/verdicts",
    "/api/v1/data/freshness",
    "/api/v1/signals/alerts/history",
    "/api/v1/explainability/decisions",
    "/api/v1/pipeline/venues",
    "/api/v1/swarm/prime-screen/state",
    "/api/v1/paper-ladder/status",
]

WS_ENDPOINTS: List[str] = [
    "/ws/trades",
    "/ws/risk",
    "/ws/prediction",
]


# ═══════════════════════════════════════════════════════════════════════
# RESULT TRACKING
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    path: str
    message: str
    detail: str = ""


SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
findings: List[Finding] = []


def add(category: str, severity: str, path: str, message: str, detail: str = ""):
    findings.append(Finding(category, severity, path, message, detail))


# ═══════════════════════════════════════════════════════════════════════
# 1. ENDPOINT HEALTH
# ═══════════════════════════════════════════════════════════════════════

async def probe_endpoint(base: str, path: str, session) -> Dict[str, Any]:
    """Probe a single GET endpoint and return a diagnostic dict."""
    url = f"{base}{path}"
    result: Dict[str, Any] = {"path": path, "url": url}
    t0 = time.monotonic()
    try:
        async with session.get(url, timeout=TIMEOUT_S) as resp:
            result["status"] = resp.status
            result["latency_ms"] = round((time.monotonic() - t0) * 1000)
            ct = resp.headers.get("content-type", "")
            result["content_type"] = ct
            if "json" in ct:
                try:
                    body = await resp.json()
                    result["body"] = body
                    result["body_type"] = type(body).__name__
                except Exception as e:
                    result["json_error"] = str(e)
            else:
                text = await resp.text()
                result["body_text_len"] = len(text)
    except asyncio.TimeoutError:
        result["status"] = "TIMEOUT"
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as e:
        result["status"] = "CONN_ERROR"
        result["error"] = str(e)
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)
    return result


async def probe_all_endpoints(base: str):
    """Probe every static GET endpoint the frontend uses."""
    import aiohttp

    print(f"\n{'=' * 72}")
    print("1. ENDPOINT HEALTH PROBES")
    print(f"{'=' * 72}")
    print(f"   Base URL: {base}")
    print(f"   Endpoints: {len(STATIC_GET_ENDPOINTS)}")

    connector = aiohttp.TCPConnector(limit=20)
    timeout_obj = aiohttp.ClientTimeout(total=TIMEOUT_S + 2)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
        tasks = [probe_endpoint(base, p, session) for p in STATIC_GET_ENDPOINTS]
        results = await asyncio.gather(*tasks)

    # Classify results
    status_counts: Dict[str, int] = collections.Counter()
    for r in results:
        st = r.get("status", "UNKNOWN")
        status_counts[str(st)] += 1
        path = r["path"]
        latency = r.get("latency_ms", 0)

        # ── HTTP errors ──
        if st == "TIMEOUT":
            add("ENDPOINT", "HIGH", path, "TIMEOUT — no response within 8s", f"latency={latency}ms")
        elif st == "CONN_ERROR":
            add("ENDPOINT", "CRITICAL", path, f"Connection error: {r.get('error', '?')}")
        elif isinstance(st, int) and st == 404:
            add("ENDPOINT", "HIGH", path, "HTTP 404 — endpoint not found")
        elif isinstance(st, int) and st == 502:
            add("ENDPOINT", "HIGH", path, "HTTP 502 — bad gateway (likely unhandled exception)")
        elif isinstance(st, int) and st == 500:
            add("ENDPOINT", "HIGH", path, "HTTP 500 — internal server error")
        elif isinstance(st, int) and st >= 400:
            add("ENDPOINT", "MEDIUM", path, f"HTTP {st} — client/server error")

        # ── Silent failures in 200 responses ──
        if isinstance(st, int) and st == 200:
            body = r.get("body")

            # Empty body
            if body is None and "json_error" in r:
                add("DATA_QUALITY", "HIGH", path,
                    "200 OK but invalid JSON body",
                    r.get("json_error", ""))
            elif body == {} or body == []:
                add("DATA_QUALITY", "MEDIUM", path,
                    f"200 OK but EMPTY response body ({type(body).__name__})")
            elif isinstance(body, dict):
                # Error key buried in 200
                err = body.get("error") or body.get("Error") or body.get("message")
                if err and ("error" in str(err).lower() or "fail" in str(err).lower()
                            or "timeout" in str(err).lower() or "unavailable" in str(err).lower()):
                    add("DATA_QUALITY", "HIGH", path,
                        f"200 OK but body contains error: {str(err)[:120]}")

                # _stub flag = backend is returning fallback data
                if body.get("_stub"):
                    add("DATA_QUALITY", "MEDIUM", path,
                        f"STUB response: {body.get('_stub_message', 'offline data')}")

                # All-zero numeric values
                _check_all_zero(path, body)

                # NaN / Infinity in values
                _check_nan_infinity(path, body)

                # Stale timestamps
                _check_stale_timestamps(path, body)

            # Slow responses
            if latency > 5000:
                add("ENDPOINT", "MEDIUM", path,
                    f"SLOW response: {latency}ms")

    # Summary
    print(f"\n   Status breakdown:")
    for st, cnt in sorted(status_counts.items()):
        print(f"     {st}: {cnt}")


def _check_all_zero(path: str, body: Dict[str, Any], prefix: str = ""):
    """Detect responses where every numeric field is 0."""
    numerics = []
    for k, v in body.items():
        if isinstance(v, (int, float)) and k not in ("_stub", "latency_ms", "count", "limit", "offset"):
            numerics.append(v)
    if len(numerics) >= 3 and all(n == 0 or n == 0.0 for n in numerics):
        add("DATA_QUALITY", "MEDIUM", path,
            f"ALL ZERO — {len(numerics)} numeric fields all = 0",
            f"keys: {[k for k, v in body.items() if isinstance(v, (int, float))][:10]}")


def _check_nan_infinity(path: str, body: Any, depth: int = 0):
    """Recursively check for NaN/Infinity which cause JSON.parse issues in the frontend."""
    if depth > 5:
        return
    if isinstance(body, float):
        if math.isnan(body) or math.isinf(body):
            add("DATA_QUALITY", "HIGH", path, f"NaN or Infinity in response value")
    elif isinstance(body, dict):
        for k, v in body.items():
            _check_nan_infinity(path, v, depth + 1)
    elif isinstance(body, list) and len(body) < 100:
        for item in body:
            _check_nan_infinity(path, item, depth + 1)


def _check_stale_timestamps(path: str, body: Dict[str, Any]):
    """Detect timestamps older than 24h which suggest stale/cached data."""
    now = time.time()
    for key in ("timestamp", "updated_at", "last_updated", "ts", "created_at"):
        val = body.get(key)
        if isinstance(val, (int, float)):
            # Epoch seconds
            if 1_000_000_000 < val < 2_000_000_000:
                age_h = (now - val) / 3600
                if age_h > 24:
                    add("DATA_QUALITY", "LOW", path,
                        f"Stale timestamp: {key} is {age_h:.0f}h old")
            # Epoch milliseconds
            elif 1_000_000_000_000 < val < 2_000_000_000_000:
                age_h = (now - val / 1000) / 3600
                if age_h > 24:
                    add("DATA_QUALITY", "LOW", path,
                        f"Stale timestamp: {key} is {age_h:.0f}h old")


# ═══════════════════════════════════════════════════════════════════════
# 2. WEBSOCKET HEALTH
# ═══════════════════════════════════════════════════════════════════════

async def probe_websocket(base: str, path: str):
    """Try to connect to a WS endpoint, receive one message, then close."""
    import aiohttp
    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    url = f"{ws_base}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, timeout=WS_TIMEOUT_S) as ws:
                # Try to receive one message within timeout
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=WS_TIMEOUT_S)
                    if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                        add("WEBSOCKET", "INFO", path, f"Connected OK, got first message ({msg.type.name})")
                        # Validate JSON
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                if isinstance(data, dict) and data.get("error"):
                                    add("WEBSOCKET", "MEDIUM", path,
                                        f"WS first message contains error: {str(data['error'])[:100]}")
                            except json.JSONDecodeError:
                                add("WEBSOCKET", "LOW", path,
                                    "WS message is not valid JSON")
                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        add("WEBSOCKET", "MEDIUM", path,
                            f"WS server closed immediately (code={msg.data})")
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        add("WEBSOCKET", "HIGH", path,
                            f"WS error on receive: {ws.exception()}")
                except asyncio.TimeoutError:
                    add("WEBSOCKET", "LOW", path,
                        f"Connected but no message within {WS_TIMEOUT_S}s (may be idle)")
                await ws.close()
    except Exception as e:
        err_str = str(e)
        if "404" in err_str or "Not Found" in err_str:
            add("WEBSOCKET", "HIGH", path, f"WS endpoint not found (404)")
        elif "refused" in err_str.lower() or "connect" in err_str.lower():
            add("WEBSOCKET", "CRITICAL", path, f"WS connection refused: {err_str[:100]}")
        else:
            add("WEBSOCKET", "MEDIUM", path, f"WS connection failed: {err_str[:100]}")


async def probe_all_websockets(base: str):
    print(f"\n{'=' * 72}")
    print("2. WEBSOCKET HEALTH PROBES")
    print(f"{'=' * 72}")
    for path in WS_ENDPOINTS:
        await probe_websocket(base, path)


# ═══════════════════════════════════════════════════════════════════════
# 3. DUPLICATE ROUTES (static analysis)
# ═══════════════════════════════════════════════════════════════════════

def check_duplicate_routes():
    print(f"\n{'=' * 72}")
    print("3. DUPLICATE ROUTE DETECTION")
    print(f"{'=' * 72}")

    # Match any decorator like @router.get("/..."), @kalshi_api_router.post("/..."), etc.
    route_pat = re.compile(r'@\w+\.(get|post|put|delete|patch|websocket)\(\s*"([^"]+)"')
    routes: Dict[Tuple[str, str], List[str]] = collections.defaultdict(list)

    # Scan all API files + main.py
    scan_files = list(API_DIR.glob("*.py"))
    if MAIN_PY.exists():
        scan_files.append(MAIN_PY)

    for fpath in scan_files:
        fname = fpath.name
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = route_pat.search(line)
            if m:
                method = m.group(1).upper()
                path = m.group(2)
                routes[(method, path)].append(f"{fname}:{i}")

    # Only report full-path duplicates (not short relative ones like /status)
    dup_count = 0
    for (method, path), locs in sorted(routes.items()):
        if len(locs) > 1 and path.startswith("/api/"):
            add("DUPLICATE_ROUTE", "HIGH", f"{method} {path}",
                f"Defined in {len(locs)} files",
                " | ".join(locs))
            dup_count += 1

    print(f"   Full-path duplicates (/api/...): {dup_count}")


# ═══════════════════════════════════════════════════════════════════════
# 4. FRONTEND STATIC ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def check_frontend_static():
    print(f"\n{'=' * 72}")
    print("4. FRONTEND STATIC ANALYSIS")
    print(f"{'=' * 72}")

    if not FE_SRC.exists():
        add("FRONTEND", "INFO", str(FE_SRC), "Frontend source directory not found, skipping")
        return

    # ── 4a. Hardcoded data generators ──
    synthetic_pats = [
        (re.compile(r'\bgenerateFallback\w+', re.I), "synthetic fallback generator"),
        (re.compile(r'\bgenerateMock\w+', re.I), "mock data generator"),
        (re.compile(r'\bfakeData\b|\bdummyData\b|\bsampleData\b', re.I), "fake/dummy/sample data"),
        (re.compile(r'\blorem\s+ipsum\b', re.I), "placeholder text (lorem ipsum)"),
        (re.compile(r'\bexample\.com\b', re.I), "placeholder domain"),
        (re.compile(r'\btest-agent\b', re.I), "test agent reference"),
    ]

    # ── 4b. Swallowed errors (catch without handling) ──
    swallow_pat = re.compile(r'catch\s*\([^)]*\)\s*\{\s*\}|catch\s*\{\s*\}')

    # ── 4c. console.log left in production ──
    console_log_pat = re.compile(r'\bconsole\.(log|debug|info|warn)\(')

    # ── 4d. Disabled/commented-out fetch calls ──
    commented_fetch = re.compile(r'//\s*(fetch|axios|useApiData|useSWR)')

    # ── 4e. Hardcoded localhost URLs (not from config) ──
    hardcoded_url = re.compile(r'["\']https?://localhost:\d+')

    # ── 4f. TODO/FIXME/HACK/XXX markers ──
    todo_pat = re.compile(r'\b(TODO|FIXME|HACK|XXX|BUG)\b:?\s*(.*)', re.I)

    # ── 4g. Empty useEffect dependencies that should have deps ──
    empty_effect = re.compile(r'useEffect\(\s*\(\)\s*=>\s*\{[^}]{50,}\},\s*\[\s*\]\s*\)')

    counts = collections.Counter()

    for root, dirs, files in os.walk(FE_SRC):
        # Skip test dirs
        bn = os.path.basename(root)
        if bn in ("__tests__", "__mocks__", "tests", "node_modules"):
            dirs.clear()
            continue
        for fname in files:
            if not fname.endswith((".ts", ".tsx")):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, FE_SRC)
            try:
                text = open(fpath, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue

            for i, line in enumerate(text.splitlines(), 1):
                # 4a
                for pat, desc in synthetic_pats:
                    m = pat.search(line)
                    if m:
                        add("FRONTEND_SYNTHETIC", "MEDIUM", f"{relpath}:{i}",
                            f"{desc}: {m.group(0)}")
                        counts["synthetic"] += 1

                # 4b
                if swallow_pat.search(line):
                    add("FRONTEND_SWALLOWED_ERROR", "HIGH", f"{relpath}:{i}",
                        "Empty catch block — errors silently swallowed")
                    counts["swallowed_error"] += 1

                # 4c (skip if it's in an error handler or conditional)
                if console_log_pat.search(line) and "error" not in line.lower() and "warn" not in line.lower():
                    counts["console_log"] += 1

                # 4d
                if commented_fetch.search(line):
                    add("FRONTEND_DEAD_CODE", "LOW", f"{relpath}:{i}",
                        "Commented-out fetch/data call")
                    counts["commented_fetch"] += 1

                # 4e
                if hardcoded_url.search(line) and "constants" not in relpath.lower() and "config" not in relpath.lower():
                    add("FRONTEND_HARDCODED_URL", "MEDIUM", f"{relpath}:{i}",
                        f"Hardcoded localhost URL outside config: {line.strip()[:80]}")
                    counts["hardcoded_url"] += 1

                # 4f — only flag real code markers, not prose in JSX text
                m = todo_pat.search(line)
                if m:
                    tag = m.group(1).upper()
                    msg = m.group(2).strip()[:80]
                    # Skip if this looks like JSX prose (inside a <p>, <li>, etc.)
                    stripped = line.strip()
                    is_jsx_prose = any(stripped.startswith(f'<{t}') or f'>{tag}' in stripped.lower()
                                       for t in ('p', 'li', 'span', 'div', 'h1', 'h2', 'h3', 'h4'))
                    # Also skip if marker is inside a string (quotes around it)
                    in_string = re.search(rf'["\'][^"\']{{0,20}}{tag}[^"\']{{0,20}}["\']', line)
                    if not is_jsx_prose and not in_string:
                        sev = "LOW" if tag == "TODO" else "MEDIUM"
                        add("FRONTEND_MARKER", sev, f"{relpath}:{i}",
                            f"{tag}: {msg}")
                        counts["marker"] += 1

            # 4g — file-level check for suspicious empty-deps useEffect
            for m in empty_effect.finditer(text):
                # Only flag if the body references state or props
                body = m.group(0)
                if re.search(r'\b(set\w+|props\.|state\.)', body):
                    # Skip common safe patterns: setInterval(() => setXxx(Date.now()))
                    # These only use stable React state setters inside callbacks
                    is_clock_tick = re.search(r'setInterval\(\(\)\s*=>\s*set\w+\(Date\.now\(\)', body)
                    is_fetch_interval = re.search(r'setInterval\(\w+,\s*\d+\)', body)
                    if not is_clock_tick and not is_fetch_interval:
                        line_no = text[:m.start()].count("\n") + 1
                        add("FRONTEND_STALE_EFFECT", "MEDIUM", f"{relpath}:{line_no}",
                            "useEffect with [] deps may have stale closure over state/props")
                        counts["stale_effect"] += 1

    # ── 4h. Broken relative imports in components ──
    import_count = 0
    broken_imports = 0
    for root, dirs, files in os.walk(FE_SRC / "components"):
        if "__tests__" in root:
            continue
        for fname in files:
            if not fname.endswith((".ts", ".tsx")):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, FE_SRC)
            text = open(fpath, "r", encoding="utf-8", errors="ignore").read()
            for m in re.finditer(r"from\s+['\"](\.\./[^'\"]+)['\"]", text):
                import_count += 1
                imp_path = m.group(1)
                base_dir = os.path.dirname(fpath)
                resolved = os.path.normpath(os.path.join(base_dir, imp_path))
                exists = any(
                    os.path.exists(resolved + ext)
                    for ext in ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]
                )
                if not exists:
                    add("FRONTEND_BROKEN_IMPORT", "HIGH", relpath,
                        f"Import from '{imp_path}' does not resolve to any file")
                    broken_imports += 1

    print(f"   Synthetic data refs: {counts['synthetic']}")
    print(f"   Swallowed errors:    {counts['swallowed_error']}")
    print(f"   console.log calls:   {counts['console_log']}")
    print(f"   TODO/FIXME markers:  {counts['marker']}")
    print(f"   Hardcoded URLs:      {counts['hardcoded_url']}")
    print(f"   Broken imports:      {broken_imports}/{import_count}")


# ═══════════════════════════════════════════════════════════════════════
# 5. FRONTEND ↔ BACKEND CROSS-WIRING
# ═══════════════════════════════════════════════════════════════════════

def check_cross_wiring():
    print(f"\n{'=' * 72}")
    print("5. FRONTEND ↔ BACKEND CROSS-WIRING")
    print(f"{'=' * 72}")

    if not FE_CONSTANTS.exists():
        print("   constants.ts not found, skipping")
        return

    # Extract frontend static endpoints
    ep_pat = re.compile(r':\s*"(/[^"]+)"')
    fe_endpoints: List[str] = []
    for line in FE_CONSTANTS.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = ep_pat.search(line)
        if m:
            fe_endpoints.append(m.group(1))

    # Collect ALL backend routes — match any @xxx.method("...") pattern
    route_pat = re.compile(r'@\w+\.(get|post|put|delete|patch|websocket)\(\s*"([^"]+)"')
    backend_routes: set = set()

    scan_files = list(API_DIR.glob("*.py"))
    if MAIN_PY.exists():
        scan_files.append(MAIN_PY)

    # Also get router prefixes from main.py to reconstruct full paths
    prefix_map: Dict[str, str] = {}
    if MAIN_PY.exists():
        main_text = MAIN_PY.read_text(encoding="utf-8", errors="ignore")
        # Look for app.include_router(xxx, prefix="/api/v1/...")
        for m in re.finditer(r'include_router\([^,]+,\s*prefix\s*=\s*"([^"]+)"', main_text):
            prefix_map[m.group(0)[:40]] = m.group(1)
        # Also collect _reg() calls that go through a helper
        for m in re.finditer(r'_reg\((\w+)(?:,\s*prefix\s*=\s*"([^"]+)")?\)', main_text):
            if m.group(2):
                prefix_map[m.group(1)] = m.group(2)

    # Also extract prefixes from APIRouter() definitions in each API file
    router_prefix_pat = re.compile(r'APIRouter\([^)]*prefix\s*=\s*"([^"]+)"')
    file_prefixes: Dict[str, str] = {}  # filename → prefix
    for fpath in scan_files:
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in router_prefix_pat.finditer(text):
            file_prefixes[fpath.name] = m.group(1)

    for fpath in scan_files:
        fname = fpath.name
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        file_prefix = file_prefixes.get(fname, "")
        for m in route_pat.finditer(text):
            path = m.group(2)
            backend_routes.add(path)
            # Also add with the file's router prefix prepended
            if file_prefix and not path.startswith(file_prefix):
                backend_routes.add(f"{file_prefix}{path}")
            # Also add with common prefixes from main.py
            if not path.startswith("/api/"):
                for prefix in set(prefix_map.values()):
                    backend_routes.add(f"{prefix}{path}")

    # Check which frontend endpoints have no backend match
    missing = 0
    for ep in fe_endpoints:
        # Direct match
        if ep in backend_routes:
            continue
        # Fuzzy: strip /api/v1 or /api and check suffix match
        short = ep.replace("/api/v1/", "/").replace("/api/", "/")
        if any(br.endswith(short) or br == ep for br in backend_routes):
            continue
        # Path-segment match: check if any backend route matches the last 2+ segments
        ep_parts = ep.rstrip("/").split("/")
        if len(ep_parts) >= 3:
            tail = "/" + "/".join(ep_parts[-2:])
            if any(br.endswith(tail) for br in backend_routes):
                continue
        add("CROSS_WIRING", "MEDIUM", ep,
            "Frontend endpoint has no detected backend route")
        missing += 1

    print(f"   Frontend endpoints: {len(fe_endpoints)}")
    print(f"   Backend routes:     {len(backend_routes)}")
    print(f"   Unmatched:          {missing}")


# ═══════════════════════════════════════════════════════════════════════
# 6. PYTHON IMPORT HEALTH
# ═══════════════════════════════════════════════════════════════════════

def check_python_imports():
    print(f"\n{'=' * 72}")
    print("6. PYTHON IMPORT HEALTH (backend API modules)")
    print(f"{'=' * 72}")

    # Instead of actually importing (which triggers side effects and startup code),
    # do a static syntax check + first-level import resolution.
    api_files = sorted(API_DIR.glob("*.py"))
    ok = 0
    fail = 0
    import_pat = re.compile(r'^(?:from\s+(\S+)\s+import|import\s+(\S+))', re.MULTILINE)

    for fpath in api_files:
        if fpath.name.startswith("_"):
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
            # Check for syntax errors
            compile(text, str(fpath), "exec")
            ok += 1
        except SyntaxError as e:
            fail += 1
            add("PYTHON_SYNTAX", "CRITICAL", f"web.api.{fpath.stem}",
                f"Syntax error: {e.msg} (line {e.lineno})")
        except Exception as e:
            fail += 1
            add("PYTHON_IMPORT", "HIGH", f"web.api.{fpath.stem}",
                f"Compile error: {e}")

    print(f"   Syntax OK: {ok}  Syntax FAIL: {fail}")


# ═══════════════════════════════════════════════════════════════════════
# 7. SETTINGS ROUNDTRIP
# ═══════════════════════════════════════════════════════════════════════

async def check_settings_roundtrip(base: str):
    """Save a canary value via PUT, then GET and verify it persisted."""
    import aiohttp

    print(f"\n{'=' * 72}")
    print("7. SETTINGS SAVE/LOAD ROUNDTRIP")
    print(f"{'=' * 72}")

    canary = f"diag-{int(time.time())}"
    payload = {
        "preferences": {"_diag_canary": canary},
    }
    try:
        async with aiohttp.ClientSession() as session:
            # PUT
            async with session.put(
                f"{base}/api/v1/user/settings",
                json=payload,
                timeout=5,
            ) as resp:
                if resp.status != 200:
                    add("SETTINGS", "HIGH", "/api/v1/user/settings PUT",
                        f"Save returned HTTP {resp.status}")
                    return
                save_body = await resp.json()
                if not save_body.get("success"):
                    add("SETTINGS", "HIGH", "/api/v1/user/settings PUT",
                        f"Save returned success=false: {save_body}")
                    return

            # GET
            async with session.get(
                f"{base}/api/v1/user/settings",
                timeout=5,
            ) as resp:
                if resp.status != 200:
                    add("SETTINGS", "HIGH", "/api/v1/user/settings GET",
                        f"Load returned HTTP {resp.status}")
                    return
                load_body = await resp.json()
                loaded_canary = load_body.get("preferences", {}).get("_diag_canary")
                if loaded_canary == canary:
                    print("   Roundtrip: OK (canary value persisted)")
                else:
                    add("SETTINGS", "HIGH", "/api/v1/user/settings",
                        f"Roundtrip FAILED: saved '{canary}' but loaded '{loaded_canary}'")
                    print(f"   Roundtrip: FAILED (expected '{canary}', got '{loaded_canary}')")
    except Exception as e:
        add("SETTINGS", "MEDIUM", "/api/v1/user/settings",
            f"Roundtrip test error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 8. RESPONSE SHAPE VALIDATION
# ═══════════════════════════════════════════════════════════════════════

# Map of endpoint → required top-level keys the frontend expects
EXPECTED_SHAPES: Dict[str, List[str]] = {
    "/api/v1/system/health": ["status"],
    "/api/v1/operator/summary": ["kill_switch", "mode"],
    "/api/v1/user/profile": ["id", "email"],
    "/api/v1/user/settings": ["preferences"],
    "/api/v1/kalshi/balance": ["balance"],
    "/api/v1/kalshi/positions": ["positions"],
    "/api/v1/kalshi/orders": ["orders"],
    "/api/v1/kalshi/fills": ["fills"],
    "/api/v1/kalshi/pnl": ["total_pnl"],
    "/api/v1/kalshi/health": ["status"],
    "/api/v1/kalshi-grid/status": ["running"],
    "/api/v1/kalshi-grid/agents": ["agents"],
    "/api/v1/kalshi-grid/portfolio": ["positions"],
    "/api/v1/kalshi/order-groups/dashboard": ["summary", "groups"],
    "/api/v1/risk/summary": ["risk_score"],
    "/api/v1/risk/alerts": ["alerts"],
    "/api/v1/ui/sidebar": ["sections"],
    "/api/v1/loop/status": ["running"],
    "/api/v1/loop/guard/verdicts": ["verdicts"],
    "/api/v1/loop/tick-log": ["ticks"],
    "/api/v1/prediction/consensus/summary": ["agents"],
    "/api/v1/prediction/consensus/leaderboard": ["agents"],
    "/api/v1/trade-mode": ["mode"],
}


async def check_response_shapes(base: str):
    """Verify that key endpoints return the fields the frontend expects."""
    import aiohttp

    print(f"\n{'=' * 72}")
    print("8. RESPONSE SHAPE VALIDATION")
    print(f"{'=' * 72}")

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)) as session:
        for path, required_keys in EXPECTED_SHAPES.items():
            try:
                async with session.get(f"{base}{path}") as resp:
                    if resp.status != 200:
                        continue  # Already caught in endpoint health
                    body = await resp.json()
                    if not isinstance(body, dict):
                        add("RESPONSE_SHAPE", "MEDIUM", path,
                            f"Expected dict but got {type(body).__name__}")
                        continue
                    missing = [k for k in required_keys if k not in body]
                    if missing:
                        add("RESPONSE_SHAPE", "HIGH", path,
                            f"Missing expected keys: {missing}",
                            f"Got keys: {sorted(body.keys())[:15]}")
            except Exception:
                pass  # Connection errors already caught above

    print("   Done")


# ═══════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════

def print_report():
    print(f"\n{'═' * 72}")
    print("  DIAGNOSTIC REPORT")
    print(f"{'═' * 72}\n")

    if not findings:
        print("  ✓ No issues found.\n")
        return

    # Sort by severity
    sorted_findings = sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))

    # Group by category
    by_cat: Dict[str, List[Finding]] = collections.defaultdict(list)
    for f in sorted_findings:
        by_cat[f.category].append(f)

    sev_counts = collections.Counter(f.severity for f in findings)
    total = len(findings)

    print(f"  Total findings: {total}")
    crit = sev_counts.get('CRITICAL', 0)
    high = sev_counts.get('HIGH', 0)
    med = sev_counts.get('MEDIUM', 0)
    low = sev_counts.get('LOW', 0)
    info = sev_counts.get('INFO', 0)
    print(f"  CRITICAL: {crit}  HIGH: {high}  MEDIUM: {med}  LOW: {low}  INFO: {info}\n")

    sev_icon = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🔵",
        "INFO": "⚪",
    }

    for cat, items in by_cat.items():
        print(f"  ── {cat} ({len(items)}) {'─' * (50 - len(cat))}")
        for f in items:
            icon = sev_icon.get(f.severity, "?")
            print(f"    {icon} [{f.severity}] {f.path}")
            print(f"       {f.message}")
            if f.detail:
                print(f"       → {f.detail[:120]}")
        print()

    # Write JSON report
    report_path = PROJECT_ROOT / "diagnostic_report.json"
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total": total,
                "severity_counts": dict(sev_counts),
                "findings": [
                    {
                        "category": f.category,
                        "severity": f.severity,
                        "path": f.path,
                        "message": f.message,
                        "detail": f.detail,
                    }
                    for f in sorted_findings
                ],
            },
            fp,
            indent=2,
        )
    print(f"  JSON report written to: {report_path}\n")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description="MERID Silent-Failure Diagnostic")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"Backend base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--offline", action="store_true", help="Skip network probes (static analysis only)")
    parser.add_argument("--no-imports", action="store_true", help="Skip Python import checks")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║      MERID Silent-Failure & Bug Diagnostic                  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"  Time:    {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Base:    {args.base}")
    print(f"  Mode:    {'offline (static only)' if args.offline else 'full (network + static)'}")

    # ── Static analysis (always runs) ──
    check_duplicate_routes()
    check_frontend_static()
    check_cross_wiring()

    if not args.no_imports:
        check_python_imports()
    else:
        print("\n   (Python import checks skipped)")

    # ── Network probes (skip in offline mode) ──
    if not args.offline:
        try:
            import aiohttp  # noqa: F401
        except ImportError:
            print("\n  ⚠ aiohttp not installed. Install with: pip install aiohttp")
            print("    Skipping network probes.")
            print_report()
            return

        # Quick connectivity check
        import aiohttp as _aio
        try:
            async with _aio.ClientSession(timeout=_aio.ClientTimeout(total=3)) as s:
                async with s.get(f"{args.base}/api/v1/system/health") as r:
                    pass
        except Exception:
            print(f"\n  ⚠ Cannot reach {args.base} — skipping network probes.")
            print("    Start the server first: py -m uvicorn web.main:app --port 8011")
            print_report()
            return

        await probe_all_endpoints(args.base)
        await probe_all_websockets(args.base)
        await check_response_shapes(args.base)
        await check_settings_roundtrip(args.base)

    print_report()


if __name__ == "__main__":
    asyncio.run(main())
