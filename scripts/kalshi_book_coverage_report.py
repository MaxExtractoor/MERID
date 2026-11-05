#!/usr/bin/env python
"""Coverage report for the Kalshi 15m orderbook archive.

Reads ``data/kalshi_book_archive.db`` (written by
``scripts/kalshi_book_archiver.py``) and prints, per market ticker and
session, the reconstructible interval: snapshot boundary → last contiguous
event, gap ledger, and what fraction of the market's open→close window the
archive actually covers.

A market is "fully covered" only when coverage starts at/before its open
AND ends at/after its close with zero gaps — anything less is reported
explicitly (late discovery, gapped, truncated), never silently assumed.

Usage:
    python scripts/kalshi_book_coverage_report.py [--db PATH] [--hours 24]
        [--json] [--ticker KXBTC15M-...]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_DB = _REPO_ROOT / "data" / "kalshi_book_archive.db"


def _ns_to_s(v):
    return v / 1e9 if v else None


def _fmt(ts_s):
    if ts_s is None:
        return "-"
    return time.strftime("%m-%d %H:%M:%S", time.gmtime(ts_s))


def report(db_path: str, hours: float, ticker: str | None) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cutoff_ns = int((time.time() - hours * 3600) * 1e9)

    q = (
        "SELECT c.*, s.connect_utc_ns, s.disconnect_utc_ns,"
        " s.disconnect_reason"
        " FROM archive_coverage c"
        " LEFT JOIN archive_sessions s ON s.connection_id = c.connection_id"
        " WHERE c.subscribed_utc_ns >= ?"
    )
    args = [cutoff_ns]
    if ticker:
        q += " AND c.market_ticker = ?"
        args.append(ticker)
    q += " ORDER BY c.market_ticker, c.subscribed_utc_ns"
    rows = con.execute(q, args).fetchall()

    sessions = con.execute(
        "SELECT * FROM archive_sessions WHERE connect_utc_ns >= ?"
        " ORDER BY connect_utc_ns",
        (cutoff_ns,),
    ).fetchall()
    alerts = con.execute(
        "SELECT code, COUNT(*) AS n, MAX(ts_utc_ns) AS last"
        " FROM archive_alerts WHERE ts_utc_ns >= ? GROUP BY code",
        (cutoff_ns,),
    ).fetchall()
    ev = con.execute(
        "SELECT COUNT(*) FROM book_events WHERE received_at_utc_ns >= ?",
        (cutoff_ns,),
    ).fetchone()[0]

    # Retention pruning deletes raw events but keeps coverage rows: a
    # segment's claimed valid window can therefore outlive the data that
    # backed it. Bound every claim by what is actually still retained so
    # pruned intervals can never read as reconstructible.
    retained = {}
    for r in con.execute(
        "SELECT connection_id, subscription_id, market_ticker,"
        " MIN(received_at_utc_ns) AS mn, MAX(received_at_utc_ns) AS mx"
        " FROM book_events"
        " GROUP BY connection_id, subscription_id, market_ticker"
    ):
        retained[(r["connection_id"], r["subscription_id"],
                  r["market_ticker"])] = (r["mn"], r["mx"])

    markets = {}
    for r in rows:
        m = markets.setdefault(r["market_ticker"], {
            "ticker": r["market_ticker"],
            "open_ts": r["market_open_ts"],
            "close_ts": r["market_close_ts"],
            "segments": [],
        })
        m["open_ts"] = m["open_ts"] or r["market_open_ts"]
        m["close_ts"] = m["close_ts"] or r["market_close_ts"]
        ret = retained.get(
            (r["connection_id"], r["subscription_id"], r["market_ticker"])
        )
        ret_from = _ns_to_s(ret[0]) if ret else None
        ret_to = _ns_to_s(ret[1]) if ret else None
        # Pruned if the claimed valid window starts before the earliest
        # event still retained for this stream (1s slack for boundaries).
        valid_from_s = r["valid_from_utc_ns"] / 1e9 if r["valid_from_utc_ns"] else None
        pruned = (
            valid_from_s is not None
            and (ret_from is None or ret_from - valid_from_s > 1.0)
        )
        m["segments"].append({
            "retained_from_s": ret_from,
            "retained_to_s": ret_to,
            "pruned": pruned,
            "coverage_id": r["coverage_id"],
            "sid": r["subscription_id"],
            "state": r["state"],
            "state_detail": r["state_detail"],
            "valid_from_s": _ns_to_s(r["valid_from_utc_ns"]),
            "valid_to_s": _ns_to_s(r["valid_to_utc_ns"]),
            "events": r["event_count"],
            "snapshots": r["snapshot_count"],
            "deltas": r["delta_count"],
            "pre_snapshot_deltas": r["pre_snapshot_deltas"],
            "gaps": json.loads(r["gaps"] or "[]"),
            "discovery_late": bool(r["discovery_late"]),
            "last_seq": r["last_seq"],
            "session_disconnect_reason": r["disconnect_reason"],
        })

    # Coverage fraction per market: union of [valid_from, valid_to] over
    # the open→close window (or open→now for live windows).
    now_s = time.time()
    out_markets = []
    for m in sorted(markets.values(), key=lambda x: x["ticker"]):
        open_s, close_s = m["open_ts"], m["close_ts"]
        win_lo = open_s or 0.0
        win_hi = close_s or now_s
        union = 0.0
        cur_lo = cur_hi = None
        for seg in sorted(
            m["segments"], key=lambda s: s["valid_from_s"] or 0
        ):
            lo, hi = seg["valid_from_s"], seg["valid_to_s"]
            if lo is None or hi is None:
                continue
            lo = max(lo, win_lo)
            hi = min(hi, win_hi)
            if hi <= lo:
                continue
            if cur_lo is None:
                cur_lo, cur_hi = lo, hi
            elif lo <= cur_hi:
                cur_hi = max(cur_hi, hi)
            else:
                union += cur_hi - cur_lo
                cur_lo, cur_hi = lo, hi
        if cur_lo is not None:
            union += cur_hi - cur_lo
        win_len = (win_hi - win_lo) if win_hi > win_lo else None
        frac = (union / win_len) if win_len else None
        gaps_total = sum(len(s["gaps"]) for s in m["segments"])
        if frac is None:
            verdict = "NO_COVERAGE"
        elif gaps_total == 0 and frac >= 0.999:
            verdict = "FULL"
        elif gaps_total == 0:
            verdict = "PARTIAL"
        else:
            verdict = "GAPPED"
        out_markets.append({
            **m,
            "window": {"open_s": win_lo, "close_s": win_hi},
            "covered_s": round(union, 1),
            "coverage_frac": round(frac, 4) if frac is not None else None,
            "verdict": verdict,
        })

    return {
        "db": db_path,
        "hours": hours,
        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
        "events_in_window": ev,
        "sessions": [
            {
                "connection_id": s["connection_id"],
                "connect_s": _ns_to_s(s["connect_utc_ns"]),
                "disconnect_s": _ns_to_s(s["disconnect_utc_ns"]),
                "reason": s["disconnect_reason"],
                "msgs": s["msgs_received"],
            }
            for s in sessions
        ],
        "alert_counts": {a["code"]: a["n"] for a in alerts},
        "markets": out_markets,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rep = report(args.db, args.hours, args.ticker)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0

    print(
        f"book-archive coverage  db={rep['db']}  last {rep['hours']}h  "
        f"events={rep['events_in_window']}"
    )
    print("sessions:")
    for s in rep["sessions"]:
        print(
            f"  {s['connection_id']}  {_fmt(s['connect_s'])} -> "
            f"{_fmt(s['disconnect_s'])}  reason={s['reason']}  msgs={s['msgs']}"
        )
    if rep["alert_counts"]:
        print("alerts: " + "  ".join(
            f"{k}={v}" for k, v in sorted(rep["alert_counts"].items())
        ))
    print("markets:")
    print(
        f"  {'ticker':<26} {'verdict':<12} {'cov%':>6} {'covered':>9} "
        f"{'window':>18} {'segments':>8} gaps"
    )
    for m in rep["markets"]:
        win = (
            f"{_fmt(m['window']['open_s'])}-{_fmt(m['window']['close_s'])}"
            if m["window"]["open_s"]
            else "-"
        )
        frac = (
            f"{m['coverage_frac'] * 100:5.1f}%"
            if m["coverage_frac"] is not None
            else "  -  "
        )
        ngaps = sum(len(s["gaps"]) for s in m["segments"])
        print(
            f"  {m['ticker']:<26} {m['verdict']:<12} {frac:>6} "
            f"{m['covered_s']:>8.0f}s {win:>18} {len(m['segments']):>8} "
            f"{ngaps}"
        )
        for s in m["segments"]:
            detail = f" ({s['state_detail']})" if s["state_detail"] else ""
            late = " LATE-DISCOVERY" if s["discovery_late"] else ""
            pruned = (
                f" PRUNED-DATA(retained {_fmt(s['retained_from_s'])}"
                f"->{_fmt(s['retained_to_s'])})"
                if s["pruned"]
                else ""
            )
            print(
                f"      seg sid={s['sid']} {s['state']}{detail}{late}{pruned} "
                f"valid {_fmt(s['valid_from_s'])} -> {_fmt(s['valid_to_s'])} "
                f"snap={s['snapshots']} deltas={s['deltas']} "
                f"gaps={len(s['gaps'])}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
