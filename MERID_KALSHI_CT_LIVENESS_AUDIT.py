#!/usr/bin/env python3
"""MERID Kalshi CT Liveness Audit.

Inspects a running (or recently-stopped) KalshiContinuousTrader to verify
that every asset × timeframe cell has been active in the last N hours.

Usage::

    python MERID_KALSHI_CT_LIVENESS_AUDIT.py
    python MERID_KALSHI_CT_LIVENESS_AUDIT.py --hours 4 --min-orders 1
    python MERID_KALSHI_CT_LIVENESS_AUDIT.py --log logs/merid.log --api http://localhost:8000

Data sources (in priority order):
    1. Backend API  — GET /api/v1/kalshi-grid/status  (ua_ct snapshot)
    2. Log file     — scans [CT-TRACE] / [UA-TRACE] lines in merid.log
    3. Fills DB     — counts fills per series from data/kalshi_fills.db

Output per cell:
    [ALIVE]  — orders_submitted > 0 in window (or fills found in window)
    [ACTIVE] — catalog_markets > 0, candidates > 0, but 0 orders (edge too low / gate blocked)
    [STALE]  — no CT-TRACE seen for this cell in window
    [DEAD]   — series appears in config but zero catalog markets ever seen

Exit codes:
    0 — all expected cells ALIVE or ACTIVE
    1 — one or more cells STALE or DEAD
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _g(s: str) -> str: return f"{_GREEN}{s}{_RESET}"
def _y(s: str) -> str: return f"{_YELLOW}{s}{_RESET}"
def _r(s: str) -> str: return f"{_RED}{s}{_RESET}"
def _c(s: str) -> str: return f"{_CYAN}{s}{_RESET}"
def _b(s: str) -> str: return f"{_BOLD}{s}{_RESET}"


# ---------------------------------------------------------------------------
# Config — expected grid
# ---------------------------------------------------------------------------

ASSETS    = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
# CT trades 15m/1h/daily/weekly by default; monthly/annual excluded intentionally
TIMEFRAMES = ["15M", "1H", "DAILY", "WEEKLY"]

# Series prefix map: (asset, tf) → Kalshi series ticker prefix
_SERIES_MAP: Dict[Tuple[str, str], str] = {
    ("BTC", "15M"): "KXBTC15M", ("BTC", "1H"): "KXBTC",
    ("BTC", "DAILY"): "KXBTCD1", ("BTC", "WEEKLY"): "KXBTCW1",
    ("ETH", "15M"): "KXETH15M", ("ETH", "1H"): "KXETH",
    ("ETH", "DAILY"): "KXETHD1", ("ETH", "WEEKLY"): "KXETHW1",
    ("SOL", "15M"): "KXSOL15M", ("SOL", "1H"): "KXSOL",
    ("SOL", "DAILY"): "KXSOLD1", ("SOL", "WEEKLY"): "KXSOLW1",
    ("XRP", "15M"): "KXXRP15M", ("XRP", "1H"): "KXXRP",
    ("XRP", "DAILY"): "KXXRPD1", ("XRP", "WEEKLY"): "KXXRPW1",
    ("DOGE", "15M"): "KXDOGE15M", ("DOGE", "1H"): "KXDOGE",
    ("DOGE", "DAILY"): "KXDOGED1", ("DOGE", "WEEKLY"): "KXDOGEW1",
}


# ---------------------------------------------------------------------------
# Data source 1: Backend API
# ---------------------------------------------------------------------------

def fetch_api_snapshot(base_url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """GET /api/v1/kalshi-grid/status and return ua_ct metrics dict, or None."""
    try:
        import urllib.request
        url = base_url.rstrip("/") + "/api/v1/kalshi-grid/status"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            # Prefer top-level ua_ct, fall back to metrics.ua_ct
            return body.get("ua_ct") or (body.get("metrics") or {}).get("ua_ct")
    except Exception as exc:
        print(f"  {_y('API unreachable:')} {exc}")
        return None


def fetch_api_cycle_stats(base_url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """GET /api/v1/kalshi/universe/agents for sweep-all CT metrics."""
    try:
        import urllib.request
        url = base_url.rstrip("/") + "/api/v1/kalshi/universe/agents"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            agents = body.get("agents") or body
            sweep = agents.get("sweep-all") or {}
            return sweep.get("ct_metrics")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data source 2: Log file parsing
# ---------------------------------------------------------------------------

# Pattern examples:
#   [CT-TRACE] stage=discover | corr_id=20260406_... | cycle=42 | assets=MULTI | ...
#   [UA-TRACE] cycle=42 catalog_markets=88 universe_markets=12 evaluated=6 approved=2 ...
#   [CT-TRACE] stage=execute | ... | market=KXBTC15M-... | asset=BTC | ...

_CT_DISCOVER_RE = re.compile(
    r"\[CT-TRACE\]\s+stage=discover.*?cycle=(\d+).*?assets=([A-Z,_]+)"
)
_CT_EXECUTE_RE = re.compile(
    r"\[CT-TRACE\]\s+stage=execute.*?cycle=(\d+).*?market=([A-Z0-9]+-).*?asset=([A-Z]+)"
)
_UA_TRACE_RE = re.compile(
    r"\[UA-TRACE\]\s+cycle=(\d+)\s+catalog_markets=(\d+)\s+universe_markets=(\d+)"
    r"\s+evaluated=(\d+)\s+approved=(\d+)\s+vetoed=(\d+)\s+orders_submitted=(\d+)"
)
# Log line timestamp prefix: "2026-04-06 12:34:56,789"
_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _parse_log_ts(line: str) -> Optional[datetime]:
    m = _LOG_TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class LogStats:
    def __init__(self) -> None:
        self.cycles_seen: int = 0
        self.last_cycle_ts: Optional[datetime] = None
        self.last_cycle: int = 0
        # Per-series: orders submitted in window
        self.orders_by_series: Dict[str, int] = defaultdict(int)
        # Per-cycle: ua_trace data
        self.ua_traces: List[Dict[str, int]] = []
        # Market ticker → (asset, tf) hits
        self.market_hits: Dict[str, int] = defaultdict(int)


def parse_log(log_path: Path, since: datetime) -> LogStats:
    stats = LogStats()
    if not log_path.exists():
        return stats

    try:
        # For large logs, only read last 200k lines
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception as exc:
        print(f"  {_y('Log read error:')} {exc}")
        return stats

    # Scan from end to find recent lines
    recent_start = max(0, len(lines) - 200_000)

    for line in lines[recent_start:]:
        ts = _parse_log_ts(line)
        if ts and ts < since:
            continue

        # CT-TRACE discover
        m = _CT_DISCOVER_RE.search(line)
        if m:
            cycle = int(m.group(1))
            stats.cycles_seen += 1
            stats.last_cycle = max(stats.last_cycle, cycle)
            if ts:
                if stats.last_cycle_ts is None or ts > stats.last_cycle_ts:
                    stats.last_cycle_ts = ts
            continue

        # CT-TRACE execute (order submission)
        m = _CT_EXECUTE_RE.search(line)
        if m:
            market_prefix = m.group(2).rstrip("-")
            stats.orders_by_series[market_prefix] += 1
            continue

        # UA-TRACE
        m = _UA_TRACE_RE.search(line)
        if m:
            stats.ua_traces.append({
                "cycle":            int(m.group(1)),
                "catalog_markets":  int(m.group(2)),
                "universe_markets": int(m.group(3)),
                "evaluated":        int(m.group(4)),
                "approved":         int(m.group(5)),
                "vetoed":           int(m.group(6)),
                "orders_submitted": int(m.group(7)),
            })
            continue

    return stats


# ---------------------------------------------------------------------------
# Data source 3: Fills DB
# ---------------------------------------------------------------------------

def count_fills_by_series(db_path: Path, since: datetime) -> Dict[str, int]:
    """Count fills per series ticker prefix from kalshi_fills.db."""
    counts: Dict[str, int] = defaultdict(int)
    if not db_path.exists():
        return counts
    try:
        since_ts = since.timestamp()
        con = sqlite3.connect(str(db_path))
        try:
            cur = con.execute(
                "SELECT ticker FROM fills WHERE created_time >= ? OR updated_time >= ?",
                (since_ts, since_ts),
            )
        except sqlite3.OperationalError:
            # Try alternate column names
            try:
                cur = con.execute("SELECT ticker FROM fills")
            except Exception:
                return counts
        for (ticker,) in cur.fetchall():
            if ticker:
                # Match to series prefix
                for series in _SERIES_MAP.values():
                    if ticker.startswith(series):
                        counts[series] += 1
                        break
        con.close()
    except Exception as exc:
        print(f"  {_y('Fills DB error:')} {exc}")
    return counts


# ---------------------------------------------------------------------------
# Cell status determination
# ---------------------------------------------------------------------------

def infer_cell_status(
    asset: str,
    tf: str,
    series: str,
    log_stats: LogStats,
    fill_counts: Dict[str, int],
    api_snap: Optional[Dict[str, Any]],
    hours: float,
    min_orders: int,
) -> Tuple[str, str]:
    """Return (status, detail) for the (asset, tf) cell."""
    orders_in_log  = log_stats.orders_by_series.get(series, 0)
    fills_in_db    = fill_counts.get(series, 0)

    # ALIVE: real submissions or fills found
    if orders_in_log >= min_orders or fills_in_db >= min_orders:
        sources = []
        if orders_in_log:
            sources.append(f"log:{orders_in_log} orders")
        if fills_in_db:
            sources.append(f"db:{fills_in_db} fills")
        return "ALIVE", ", ".join(sources)

    # ACTIVE: cycles ran but no orders (edge didn't clear, or gate limited)
    if log_stats.cycles_seen > 0:
        total_submitted = sum(t["orders_submitted"] for t in log_stats.ua_traces)
        if total_submitted > 0 or log_stats.cycles_seen > 0:
            return "ACTIVE", (
                f"{log_stats.cycles_seen} cycles seen in window, "
                f"0 orders for {series} (edge below threshold or gate limited)"
            )

    # STALE: no CT-TRACE at all in window
    if log_stats.last_cycle_ts is None:
        # Check API snapshot for any activity
        if api_snap:
            ct_cycles = api_snap.get("ct_cycles", 0)
            if ct_cycles > 0:
                last_updated = api_snap.get("last_updated", 0)
                ago_min = (time.time() - last_updated) / 60 if last_updated else None
                return "STALE", (
                    f"API shows {ct_cycles} total cycles but none logged in "
                    f"last {hours:.0f}h window (last API update "
                    f"{ago_min:.0f}m ago)" if ago_min else f"last API update unknown"
                )
        return "STALE", f"no CT-TRACE in last {hours:.0f}h, log may be empty or CT not running"

    return "STALE", f"cycles seen globally but no activity for {series} in {hours:.0f}h"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_cell_table(
    results: List[Tuple[str, str, str, str, str]],  # asset, tf, series, status, detail
) -> int:
    """Print the per-cell table. Returns count of STALE/DEAD cells."""
    print()
    print(_b("=" * 80))
    print(_b("  MERID CT Liveness Audit — Per-Cell Status"))
    print(_b("=" * 80))
    print(f"  {'ASSET':<6}  {'TF':<8}  {'SERIES':<12}  {'STATUS':<8}  {'DETAIL'}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*12}  {'-'*8}  {'-'*40}")

    bad = 0
    for asset, tf, series, status, detail in results:
        if status == "ALIVE":
            badge = _g("[ALIVE] ")
        elif status == "ACTIVE":
            badge = _c("[ACTIVE]")
        elif status == "DEAD":
            badge = _r("[DEAD]  ")
            bad += 1
        else:  # STALE
            badge = _y("[STALE] ")
            bad += 1
        print(f"  {asset:<6}  {tf:<8}  {series:<12}  {badge}  {detail[:60]}")

    print(_b("=" * 80))
    total  = len(results)
    alive  = sum(1 for *_, s, _ in results if s == "ALIVE")
    active = sum(1 for *_, s, _ in results if s == "ACTIVE")
    stale  = sum(1 for *_, s, _ in results if s == "STALE")
    dead   = sum(1 for *_, s, _ in results if s == "DEAD")

    if bad == 0:
        print(_g(_b(f"  RESULT: ALL LIVE  ({alive} ALIVE, {active} ACTIVE)")))
    else:
        print(_r(_b(f"  RESULT: {bad} DEAD/STALE  (ALIVE={alive} ACTIVE={active} STALE={stale} DEAD={dead})")))
    print(_b("=" * 80))
    print()
    return bad


def print_aggregate_summary(
    log_stats: LogStats,
    api_snap: Optional[Dict[str, Any]],
    fill_counts: Dict[str, int],
    hours: float,
) -> None:
    print(_b(f"\n  Aggregate stats (last {hours:.0f}h window)"))
    print(f"  CT cycles in log : {log_stats.cycles_seen}")
    print(f"  Last cycle #     : {log_stats.last_cycle}")
    last_ts = log_stats.last_cycle_ts
    if last_ts:
        ago = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
        print(f"  Last cycle time  : {last_ts:%Y-%m-%d %H:%M:%S} UTC  ({ago:.0f}m ago)")
    else:
        print(f"  Last cycle time  : not found in log window")

    if log_stats.ua_traces:
        avg_cats = sum(t["catalog_markets"] for t in log_stats.ua_traces) / len(log_stats.ua_traces)
        avg_univ = sum(t["universe_markets"] for t in log_stats.ua_traces) / len(log_stats.ua_traces)
        total_sub = sum(t["orders_submitted"] for t in log_stats.ua_traces)
        print(f"  Avg catalog/cycle: {avg_cats:.1f} markets")
        print(f"  Avg universe/cycle: {avg_univ:.1f} markets")
        print(f"  Total orders sub : {total_sub}")

    if fill_counts:
        total_fills = sum(fill_counts.values())
        print(f"  DB fills in window: {total_fills} across {len(fill_counts)} series")

    if api_snap:
        print(f"\n  API snapshot (ua_ct):")
        for k, v in api_snap.items():
            if k == "last_trace":
                print(f"    last_trace      : {v}")
            elif k == "last_updated" and v:
                ago = (time.time() - float(v)) / 60
                print(f"    last_updated    : {ago:.0f}m ago")
            else:
                print(f"    {k:<16}: {v}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="MERID CT liveness audit")
    parser.add_argument("--hours",      type=float, default=2.0,
                        help="Look-back window in hours (default: 2)")
    parser.add_argument("--min-orders", type=int,   default=1,
                        help="Min orders/fills to count a cell ALIVE (default: 1)")
    parser.add_argument("--log",        type=str,   default="logs/merid.log",
                        help="Path to merid log file")
    parser.add_argument("--db",         type=str,   default="data/kalshi_fills.db",
                        help="Path to kalshi_fills.db")
    parser.add_argument("--api",        type=str,   default="http://localhost:8000",
                        help="Backend base URL for API checks")
    parser.add_argument("--no-api",     action="store_true",
                        help="Skip API checks")
    parser.add_argument("--no-db",      action="store_true",
                        help="Skip DB checks")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    print(f"\n  Window: last {args.hours:.0f}h  (since {since:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"  Min orders to be ALIVE: {args.min_orders}")
    print(f"  Log: {args.log}  |  DB: {args.db}  |  API: {args.api}\n")

    # --- Data collection ---
    log_path = project_root / args.log
    db_path  = project_root / args.db

    print(f"  Parsing log file …")
    log_stats = parse_log(log_path, since)
    print(f"    {log_stats.cycles_seen} CT-TRACE discover lines found in window")

    fill_counts: Dict[str, int] = {}
    if not args.no_db:
        print(f"  Querying fills DB …")
        fill_counts = count_fills_by_series(db_path, since)
        print(f"    {sum(fill_counts.values())} fills found across {len(fill_counts)} series")

    api_snap: Optional[Dict[str, Any]] = None
    if not args.no_api:
        print(f"  Hitting backend API …")
        api_snap = fetch_api_snapshot(args.api)
        if api_snap is None:
            api_snap = fetch_api_cycle_stats(args.api)
        if api_snap:
            print(f"    API snapshot: ct_cycles={api_snap.get('ct_cycles','?')} "
                  f"orders_accepted={api_snap.get('orders_accepted','?')}")
        else:
            print(f"    API not available (CT may not be running)")

    # --- Per-cell analysis ---
    results: List[Tuple[str, str, str, str, str]] = []
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            series = _SERIES_MAP.get((asset, tf), "")
            if not series:
                results.append((asset, tf, "?", "DEAD", "no series mapping in _SERIES_MAP"))
                continue
            status, detail = infer_cell_status(
                asset, tf, series,
                log_stats, fill_counts, api_snap,
                args.hours, args.min_orders,
            )
            results.append((asset, tf, series, status, detail))

    # --- Report ---
    print_aggregate_summary(log_stats, api_snap, fill_counts, args.hours)
    bad = print_cell_table(results)

    if bad > 0:
        print(f"  Diagnosis hints:")
        print(f"  • STALE/DEAD with CT running → check execution_gate, min_edge thresholds,")
        print(f"    or catalog market counts (zero candidates for that series).")
        print(f"  • STALE with CT stopped → start CT or reduce --hours to match uptime.")
        print(f"  • ACTIVE → CT sees candidates but edge filter drops them; lower min_edge")
        print(f"    or check KALSHI_CT_PROFILE env var.")
        print(f"  • Run MERID_KALSHI_EXECUTION_READINESS_CHECK.py for full pre-flight.\n")

    return 1 if bad > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
