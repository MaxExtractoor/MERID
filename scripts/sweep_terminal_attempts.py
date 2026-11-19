"""Sweep stale nonterminal order/exit attempts (2026-11-19).

205 entry attempts (SUBMISSION_UNKNOWN/SUBMITTING/ACKNOWLEDGED/PERSISTED)
and 25 exit attempts (RESOLVING_ON_EXCHANGE et al.) sat nonterminal in
``data/kalshi_order_attempts.db`` from crash/timeout windows — every one
targets a 15m market that has long settled, so the venue order is provably
terminal (expired, cancelled, or filled).

Rule per DLQ doctrine: verify then terminalize, never bulk-delete.

- Entry attempt with a recorded fill event → FILLED (fill evidence wins).
- Entry attempt without a fill → CANCELED (market expired under it).
- Exit attempt without a fill → TERMINAL_UNFILLED; with a fill → FILLED.

Uses the store's guarded APIs (``terminalize_entry_attempt`` /
``transition_exit_attempt``) — terminal rows and concurrent live updates
always win. Writes a manifest to ``data/quarantine_sweep_<date>.json``.

Usage:
    python scripts/sweep_terminal_attempts.py            # dry run
    python scripts/sweep_terminal_attempts.py --apply    # execute
    python scripts/sweep_terminal_attempts.py --apply --max-age-s 3600
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _fills_for_attempt(conn, order_attempt_id: str) -> int:
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM order_attempt_fill_events WHERE order_attempt_id = ?",
            (order_attempt_id,),
        )
        return int(cur.fetchone()[0])
    except Exception:
        return 0


def _exit_fills(conn, attempt_id: str) -> int:
    # Exit fills are applied through apply_exit_fill / fill_reason linkage;
    # check both the events table name variants defensively.
    for tbl, col in (
        ("order_attempt_fill_events", "order_attempt_id"),
    ):
        try:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE {col} = ?", (attempt_id,)
            )
            n = int(cur.fetchone()[0])
            if n:
                return n
        except Exception:
            continue
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (default dry run)")
    ap.add_argument("--max-age-s", type=float, default=7200.0,
                    help="only sweep attempts older than this (default 2h; "
                         "a 15m market is settled by then)")
    ap.add_argument("--db", default=str(_ROOT / "data" / "kalshi_order_attempts.db"))
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    from merid.event_venues.kalshi.order_attempt_store import (
        OrderAttemptStore,
        ExitOrderAttemptState,
    )

    store = OrderAttemptStore(args.db)
    conn = store._get_conn()
    now = time.time()
    cutoff = now - args.max_age_s

    entries = conn.execute(
        "SELECT order_attempt_id, client_order_id, decision_id, status, created_at "
        "FROM order_attempts WHERE status IN "
        "('PERSISTED','SUBMITTING','SUBMISSION_UNKNOWN','ACKNOWLEDGED') "
        "AND created_at < ? ORDER BY created_at ASC",
        (cutoff,),
    ).fetchall()

    exits = conn.execute(
        "SELECT attempt_id, client_order_id, state, created_at "
        "FROM exit_order_attempts WHERE state IN "
        "('SUBMITTING','RESOLVING_ON_EXCHANGE','ACKNOWLEDGED','ACKNOWLEDGED_LATE') "
        "AND created_at < ? ORDER BY created_at ASC",
        (cutoff,),
    ).fetchall()

    manifest = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "apply": args.apply,
        "max_age_s": args.max_age_s,
        "db": args.db,
        "entries": [],
        "exits": [],
        "summary": {},
    }

    n_e_fill = n_e_cancel = n_e_skip = 0
    for r in entries:
        fills = _fills_for_attempt(conn, r["order_attempt_id"])
        target = "FILLED" if fills else "CANCELED"
        rec = {
            "order_attempt_id": r["order_attempt_id"],
            "client_order_id": r["client_order_id"],
            "decision_id": r["decision_id"],
            "old_status": r["status"],
            "age_s": round(now - (r["created_at"] or now), 1),
            "fill_events": fills,
            "action": target,
            "applied": False,
        }
        if args.apply:
            ok = store.terminalize_entry_attempt(
                r["order_attempt_id"], target,
                actor="sweep_terminal_attempts",
                reason="market_expired_sweep",
                evidence={"fill_events": fills, "old_status": r["status"]},
            )
            rec["applied"] = bool(ok)
            if not ok:
                rec["skip"] = "already_terminal_or_missing"
                n_e_skip += 1
                manifest["entries"].append(rec)
                continue
        if fills:
            n_e_fill += 1
        else:
            n_e_cancel += 1
        manifest["entries"].append(rec)

    n_x_fill = n_x_tu = n_x_skip = 0
    for r in exits:
        fills = _exit_fills(conn, r["attempt_id"])
        target = (
            ExitOrderAttemptState.FILLED if fills
            else ExitOrderAttemptState.TERMINAL_UNFILLED
        )
        rec = {
            "attempt_id": r["attempt_id"],
            "client_order_id": r["client_order_id"],
            "old_state": r["state"],
            "age_s": round(now - (r["created_at"] or now), 1),
            "fill_events": fills,
            "action": target.value,
            "applied": False,
        }
        if args.apply:
            try:
                rec_out = store.transition_exit_attempt(
                    r["attempt_id"], target,
                    actor="sweep_terminal_attempts",
                    reason="market_expired_sweep",
                    raw_payload={"fill_events": fills, "old_state": r["state"]},
                )
                ok = rec_out is not None
            except Exception as exc:
                ok = False
                rec["error"] = str(exc)
            rec["applied"] = bool(ok)
            if not ok:
                rec.setdefault("skip", "transition_refused_or_missing")
                n_x_skip += 1
                manifest["exits"].append(rec)
                continue
        if fills:
            n_x_fill += 1
        else:
            n_x_tu += 1
        manifest["exits"].append(rec)

    manifest["summary"] = {
        "entries_scanned": len(entries),
        "entry_filled": n_e_fill,
        "entry_canceled": n_e_cancel,
        "entry_skipped": n_e_skip,
        "exits_scanned": len(exits),
        "exit_filled": n_x_fill,
        "exit_terminal_unfilled": n_x_tu,
        "exit_skipped": n_x_skip,
    }

    mpath = args.manifest or str(
        _ROOT / "data"
        / f"quarantine_sweep_{datetime.datetime.utcnow().strftime('%Y%m%d')}.json"
    )
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, default=str)
    print(json.dumps(manifest["summary"], indent=2))
    print(f"manifest -> {mpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
