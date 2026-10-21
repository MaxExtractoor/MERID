"""Archive + prune old rows from data/decision_audit.db.

The decision-audit DB is append-only research/telemetry (the order-of-record
ledgers — fills, attempts, positions — live elsewhere).  Live consumers only
need the trailing evidence window (~5h): the evidence exporter queries
``o.settled_at >= now - MERID_LIVE_EVIDENCE_WINDOW_HOURS``; markouts, regime
state, lane counters, and cell authority live in JSON state files.  Beyond
that horizon the rows serve research/calibration only.

Retention policy (see repo notes):
  * hot  — ``--days`` trailing days stay in the live DB (default 7, one full
    evidence halflife + margin).
  * warm — older rows move to ``data/archive/decision_audit_YYYYMM.db``
    monthly SQLite files (attachable for research any time).
  * cold — ``--gzip`` additionally compresses each finished archive month.

Deleting frees pages onto SQLite's freelist, which new writes reuse — the
file stops growing without a VACUUM.  ``--vacuum`` performs a one-time
compact (rewrites the file; needs downtime and ~1x free disk).

Chunks by decision_ts day, and inside each day by decision_id batches, so
transactions stay short against the live WAL writer.  Idempotent: INSERTs
are OR IGNORE on the archive's PKs and deletes are range-bounded, so a
re-run or interrupted run is safe to repeat.

Usage:
    python scripts/archive_decision_audit.py --dry-run
    python scripts/archive_decision_audit.py --days 7
    python scripts/archive_decision_audit.py --days 7 --gzip
    python scripts/archive_decision_audit.py --vacuum   # compact only
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MAIN_TABLES = (
    # (table, parent-fk col or own ts col).  Children move by decision_id
    # membership of the parent's chunk set — keeps the family consistent.
    ("strategy_decision_side_ev", "decision_id"),
    ("strategy_decision_events", "decision_id"),
    ("strategy_decision_outcomes", "decision_id"),
    ("strategy_decision_snapshots", "decision_id"),
)
PARENT_TABLE = "strategy_decisions"
HEARTBEAT_TABLE = "decision_audit_heartbeats"
DAY = 86400.0


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _month_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _create_like(con: sqlite3.Connection, src_con: sqlite3.Connection,
                 table: str) -> None:
    row = src_con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row and row[0]:
        con.execute(row[0])
    # Carry the source indexes so the archive stays research-queryable —
    # same SELECT performance contract as the live DB.
    for (sql,) in src_con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND tbl_name=? AND sql IS NOT NULL", (table,),
    ).fetchall():
        try:
            con.execute(sql)
        except sqlite3.OperationalError:
            pass  # index already exists on a reopened archive file


def _chunks_of_ids(ids: list, n: int):
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _day_bounds(con: sqlite3.Connection, cutoff: float):
    row = con.execute(
        f"SELECT MIN(decision_ts) FROM {PARENT_TABLE} WHERE decision_ts < ?",
        (cutoff,),
    ).fetchone()
    if not row or row[0] is None:
        return
    start = int(row[0] // DAY) * DAY
    while start < cutoff:
        yield start, min(start + DAY, cutoff)
        start += DAY


def archive(db_path: Path, archive_dir: Path, days: int, chunk_ids: int,
            gzip_out: bool, dry_run: bool, manifest: dict) -> int:
    con = sqlite3.connect(str(db_path), timeout=60)
    con.execute("PRAGMA busy_timeout = 60000")
    con.execute("PRAGMA journal_mode = WAL")
    cutoff = time.time() - days * DAY
    print(f"[archive] cutoff={_utc(cutoff)} ({days}d) dry_run={dry_run}",
          flush=True)

    total_old = con.execute(
        f"SELECT COUNT(*) FROM {PARENT_TABLE} WHERE decision_ts < ?",
        (cutoff,),
    ).fetchone()[0]
    print(f"[archive] parent rows older than cutoff: {total_old}", flush=True)
    if dry_run:
        for a, b in _day_bounds(con, cutoff):
            n = con.execute(
                f"SELECT COUNT(*) FROM {PARENT_TABLE} "
                "WHERE decision_ts >= ? AND decision_ts < ?", (a, b),
            ).fetchone()[0]
            print(f"  {_utc(a)}..{_utc(b)}: {n} decisions -> "
                  f"{_month_of(a)} archive", flush=True)
        if _table_exists(con, HEARTBEAT_TABLE):
            n = con.execute(
                f"SELECT COUNT(*) FROM {HEARTBEAT_TABLE} WHERE created_at < ?",
                (cutoff,),
            ).fetchone()[0]
            print(f"  heartbeats older than cutoff: {n}", flush=True)
        con.close()
        return 0

    moved = {t: 0 for t, _ in MAIN_TABLES}
    moved[PARENT_TABLE] = 0
    archive_dir.mkdir(parents=True, exist_ok=True)

    acon: sqlite3.Connection | None = None
    cur_month: str | None = None

    def _open_month(m: str) -> sqlite3.Connection:
        nonlocal acon, cur_month
        if acon is not None and cur_month == m:
            return acon
        if acon is not None:
            acon.commit()
            acon.close()
        path = archive_dir / f"decision_audit_{m}.db"
        acon = sqlite3.connect(str(path), timeout=60)
        acon.execute("PRAGMA journal_mode = WAL")
        acon.execute("PRAGMA busy_timeout = 60000")
        # Read rows straight out of the source DB — the archive writer owns
        # the transfer so the main connection only ever DELETEs.
        acon.execute("ATTACH DATABASE ? AS src", (str(db_path),))
        for t, _ in MAIN_TABLES:
            if not _table_exists(acon, t):
                _create_like(acon, con, t)
        if not _table_exists(acon, PARENT_TABLE):
            _create_like(acon, con, PARENT_TABLE)
        acon.commit()
        cur_month = m
        print(f"[archive] month={m} -> {path}", flush=True)
        return acon

    for a, b in _day_bounds(con, cutoff):
        month = _month_of(a)
        ac = _open_month(month)
        ids = [r[0] for r in con.execute(
            f"SELECT decision_id FROM {PARENT_TABLE} "
            "WHERE decision_ts >= ? AND decision_ts < ?", (a, b)).fetchall()]
        day_moved = {t: 0 for t in moved}
        for batch in _chunks_of_ids(ids, chunk_ids):
            marks = ",".join("?" for _ in batch)
            try:
                # Copy first (archive commits), then delete (main commits) —
                # an interruption leaves rows in both places, never neither.
                for t, col in MAIN_TABLES:
                    day_moved[t] += max(ac.execute(
                        f"INSERT OR IGNORE INTO [{t}] "
                        f"SELECT * FROM src.[{t}] WHERE {col} IN ({marks})",
                        batch,
                    ).rowcount, 0)
                ac.execute(
                    f"INSERT OR IGNORE INTO {PARENT_TABLE} "
                    f"SELECT * FROM src.{PARENT_TABLE} "
                    f"WHERE decision_id IN ({marks})", batch)
                ac.commit()

                con.execute("BEGIN IMMEDIATE")
                for t, col in MAIN_TABLES:
                    con.execute(
                        f"DELETE FROM {t} WHERE {col} IN ({marks})",
                        batch)
                day_moved[PARENT_TABLE] += max(con.execute(
                    f"DELETE FROM {PARENT_TABLE} WHERE decision_id IN "
                    f"({marks})", batch).rowcount, 0)
                con.commit()
            except Exception:
                con.rollback()
                ac.rollback()
                raise
        for t in moved:
            moved[t] += day_moved[t]
        print(f"[archive] {_utc(a)[:10]}: moved {day_moved[PARENT_TABLE]}"
              f" decisions (+{sum(day_moved[t] for t,_ in MAIN_TABLES)}"
              " child rows)", flush=True)
        # Reclaim WAL growth between days so the file does not balloon
        # during a long prune against the live writer.
        try:
            con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    if acon is not None:
        acon.commit()
        acon.close()

    # Heartbeats: same retention, keyed by created_at.
    if _table_exists(con, HEARTBEAT_TABLE):
        try:
            n = con.execute(
                f"DELETE FROM {HEARTBEAT_TABLE} WHERE created_at < ?",
                (cutoff,)).rowcount
            con.commit()
            print(f"[archive] heartbeats pruned: {n}", flush=True)
        except Exception as e:
            print(f"[archive] heartbeat prune skipped: {e}", flush=True)

    # Collapse the prune's WAL frames back into the main file — a TRUNCATE
    # checkpoint succeeds cleanly when the writer is stopped; PASSIVE
    # fallback otherwise.
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        try:
            con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    manifest.update({
        "cutoff_ts": cutoff, "cutoff_utc": _utc(cutoff), "days": days,
        "moved": moved, "finished_utc": _utc(time.time()),
    })
    con.close()

    if gzip_out:
        for p in sorted(archive_dir.glob("decision_audit_*.db")):
            gz = p.with_suffix(p.suffix + ".gz")
            if gz.exists():
                continue
            print(f"[archive] gzip {p.name} -> {gz.name}", flush=True)
            with open(p, "rb") as f_in, gzip.open(gz, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out, 1024 * 1024)
    return 0


def vacuum(db_path: Path) -> int:
    print("[vacuum] rewriting DB — blocks writers, needs ~filesize free "
          "space. Ctrl-C aborts safely (original file kept).", flush=True)
    t0 = time.time()
    con = sqlite3.connect(str(db_path), timeout=120)
    con.execute("VACUUM")
    con.close()
    print(f"[vacuum] done in {time.time()-t0:.0f}s -> "
          f"{db_path.stat().st_size/1e9:.2f}GB", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/decision_audit.db")
    ap.add_argument("--archive-dir", default="data/archive")
    ap.add_argument("--days", type=float, default=7.0,
                    help="hot retention window (default 7d)")
    ap.add_argument("--chunk-ids", type=int, default=5000,
                    help="decision_ids per transaction")
    ap.add_argument("--gzip", action="store_true",
                    help="gzip archive months after writing")
    ap.add_argument("--vacuum", action="store_true",
                    help="VACUUM the live DB after pruning (offline)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--manifest", default="data/archive/MANIFEST.json")
    args = ap.parse_args()

    db_path = Path(args.db)
    manifest = {"tool": "archive_decision_audit", "db": str(db_path),
                "started_utc": _utc(time.time())}
    rc = archive(db_path, Path(args.archive_dir), args.days,
                 args.chunk_ids, args.gzip, args.dry_run, manifest)
    if rc:
        return rc
    if args.vacuum and not args.dry_run:
        return vacuum(db_path)

    mpath = Path(args.manifest)
    if not args.dry_run:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, indent=2))
        print(f"[archive] manifest -> {mpath}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
