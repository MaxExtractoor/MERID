#!/usr/bin/env python3
"""Poll AgentGrid observability APIs for multi-hour behavioral validation.

Answers: are agents still cycling, seeing markets in window, and blocked only
for understandable reasons (risk_checked, session, catalogue), or is there a
post-startup halt (kill switch, execution gate, silent stall)?

Truth sources (no [AGENT-CYCLE] log tags exist):
  - GET /api/v1/operator/ticks?limit=200   — tick_summary per agent cycle
  - GET /api/v1/operator/ticks/events    — granular events; veto reasons live in
      event=risk_checked, allowed=false, reason=...

Also polls:
  - GET /api/v1/kalshi/risk
  - GET /api/v1/operator/risk-state
  - GET /api/v1/system/execution-gate

Authentication: same as the API server. Set one of:
  - MERID_MONITOR_SESSION_ID + script uses header X-Session-ID
  - MERID_MONITOR_BEARER + script uses Authorization: Bearer <token>
  - --session <id> / --bearer <token>

Production live trading disables dev auth bypass — you need a real session.

Examples:
  set MERID_MONITOR_SESSION_ID=your_session_uuid
  py -3 scripts/monitor_agentgrid_runtime.py --base-url https://your-host --interval 120 --count 30

  py -3 scripts/monitor_agentgrid_runtime.py --base-url http://127.0.0.1:8000 --interval 60 --count 0
  (count 0 = run until Ctrl+C)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("This script requires 'requests' (see requirements.txt).", file=sys.stderr)
    sys.exit(1)


def _headers(args: argparse.Namespace) -> Dict[str, str]:
    h: Dict[str, str] = {"Accept": "application/json"}
    session = args.session or os.getenv("MERID_MONITOR_SESSION_ID", "").strip()
    bearer = args.bearer or os.getenv("MERID_MONITOR_BEARER", "").strip()
    if session:
        h["X-Session-ID"] = session
    elif bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def _get(sess: requests.Session, url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        r = sess.get(url, timeout=45)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:500]}"
        return r.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def _latest_tick_per_agent(ticks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Keep the row with largest ts for each agent_id (buffer is last-N summaries)."""
    best: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    for t in ticks:
        aid = t.get("agent_id")
        if not aid:
            continue
        ts = float(t.get("ts_ended") or t.get("ts") or 0.0)
        prev = best.get(aid)
        if prev is None or ts >= prev[0]:
            best[aid] = (ts, t)
    return {k: v[1] for k, v in best.items()}


def _risk_veto_counts(events: List[Dict[str, Any]]) -> Counter:
    c: Counter = Counter()
    for e in events:
        if e.get("event") != "risk_checked":
            continue
        if e.get("allowed") is True:
            continue
        reason = str(e.get("reason") or "unknown")
        c[reason] += 1
    return c


def _short_gate(g: Optional[Dict[str, Any]]) -> str:
    if not g:
        return "n/a"
    blocked = g.get("blocked")
    reasons = g.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        msg = "; ".join(
            str(x.get("message", x) if isinstance(x, dict) else x) for x in reasons[:3]
        )
        return f"blocked={blocked} reasons={msg[:200]}"
    return f"blocked={blocked}"


def _short_risk_state(d: Optional[Dict[str, Any]]) -> str:
    if not d:
        return "n/a"
    return (
        f"can_trade={d.get('can_trade')} cb={d.get('circuit_breaker_state', d.get('cb_state', '?'))}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Poll MERID AgentGrid tick + risk APIs.")
    p.add_argument("--base-url", default=os.getenv("MERID_MONITOR_BASE_URL", "http://127.0.0.1:8000").rstrip("/"))
    p.add_argument("--interval", type=float, default=120.0, help="Seconds between polls (default 120).")
    p.add_argument(
        "--count",
        type=int,
        default=30,
        help="Number of polls (0 = infinite until Ctrl+C).",
    )
    p.add_argument("--session", default="", help="X-Session-ID value (or set MERID_MONITOR_SESSION_ID).")
    p.add_argument("--bearer", default="", help="Bearer token (or set MERID_MONITOR_BEARER).")
    p.add_argument("--tick-limit", type=int, default=200)
    p.add_argument("--event-limit", type=int, default=500)
    args = p.parse_args()

    hdrs = _headers(args)
    if "X-Session-ID" not in hdrs and not hdrs.get("Authorization"):
        print(
            "Warning: no session/bearer — requests will 401 if the server requires auth.\n"
            "Set MERID_MONITOR_SESSION_ID or --session / MERID_MONITOR_BEARER.",
            file=sys.stderr,
        )

    base = args.base_url
    urls = {
        "ticks": f"{base}/api/v1/operator/ticks?limit={args.tick_limit}",
        "events": f"{base}/api/v1/operator/ticks/events?limit={args.event_limit}",
        "risk": f"{base}/api/v1/kalshi/risk",
        "risk_state": f"{base}/api/v1/operator/risk-state",
        "gate": f"{base}/api/v1/system/execution-gate",
    }

    sess = requests.Session()
    sess.headers.update(hdrs)

    prev_cycle: Dict[str, int] = {}
    stall_count: Dict[str, int] = {}
    poll_idx = 0
    while True:
        poll_idx += 1
        ts_wall = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"\n{'=' * 72}\nPoll #{poll_idx}  {ts_wall}Z local\n{'=' * 72}")

        ticks_j, err = _get(sess, urls["ticks"])
        if err:
            print(f"  ticks ERROR: {err}")
        else:
            ticks = ticks_j.get("ticks") or []
            stats = ticks_j.get("stats") or {}
            print(f"  tick_bus stats: {json.dumps(stats, default=str)}")
            by_ag = _latest_tick_per_agent(ticks)
            print(f"  agents in buffer (latest summary each): {len(by_ag)}")
            missing = sorted(set(prev_cycle.keys()) - set(by_ag.keys()))
            if missing and poll_idx > 1:
                print(
                    "  note: these agents had prior cycles but no row in this buffer (FIFO evicted or quiet): "
                    + ", ".join(missing[:20])
                    + (" ..." if len(missing) > 20 else "")
                )
            for aid in sorted(by_ag.keys()):
                row = by_ag[aid]
                cyc = int(row.get("cycle_number") or 0)
                prev = prev_cycle.get(aid, cyc)
                dc = cyc - prev
                prev_cycle[aid] = cyc
                if dc <= 0 and poll_idx > 1:
                    stall_count[aid] = stall_count.get(aid, 0) + 1
                else:
                    stall_count[aid] = 0
                stall_note = f" STALL×{stall_count[aid]}" if stall_count[aid] >= 2 else ""

                print(
                    f"    {aid:40} cycle={cyc:5} Δ={dc:+4}  "
                    f"mr/mw={row.get('markets_resolved')}/{row.get('markets_in_window')}  "
                    f"ord/fill={row.get('orders_submitted')}/{row.get('fills_confirmed')}  "
                    f"risk_blk={row.get('risk_blocked')}  err={row.get('error') or '-'}"
                    f"{stall_note}"
                )

        ev_j, err = _get(sess, urls["events"])
        if err:
            print(f"  events ERROR: {err}")
        else:
            events = ev_j.get("events") or []
            vetoes = _risk_veto_counts(events)
            if vetoes:
                top = vetoes.most_common(12)
                print("  risk_checked (allowed=false) in recent event buffer:")
                for reason, n in top:
                    print(f"    {n:4}  {reason[:120]}")
            else:
                print("  risk_checked vetoes: none in recent event buffer")

        rj, err = _get(sess, urls["risk"])
        print(f"  kalshi/risk: {'ERROR ' + err if err else json.dumps(rj, default=str)[:400]}")

        sj, err = _get(sess, urls["risk_state"])
        print(f"  operator/risk-state: {'ERROR ' + err if err else _short_risk_state(sj)}")

        gj, err = _get(sess, urls["gate"])
        print(f"  system/execution-gate: {'ERROR ' + err if err else _short_gate(gj)}")

        if args.count and poll_idx >= args.count:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
