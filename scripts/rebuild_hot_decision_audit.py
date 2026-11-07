#!/usr/bin/env python3
"""Rebuild data/decision_audit.db as a hot-only DB containing the last N days.

Why this exists: archiving-by-delete on the 27GB ledger means every removed
row rewrites parent/child B-trees plus ~15 secondary indexes (observed: multi-
hour single-day transactions).  Rebuild-by-copy is the inverse -- one
INSERT..SELECT per table into a fresh file with indexes deferred until after
the bulk load.  ~15-40 min instead of days.

Copy method (2026-11-07): rowid-tail cutoffs.  All audit rows are appended in
decision order by the single writer, so rowid tracks decision_ts within write
-queue skew.  Rather than scanning each 5M-row child table and probing
per-row (the EXISTS plan, which read the full ~20GB), the boundary is found
by binary-searching each child's rowid against the parent's decision_ts
(~25 point lookups), then copying ``WHERE rowid >= cut - margin`` -- a pure
sequential tail scan of only the in-window rows.  The timestamp pad plus a
fixed rowid margin guarantees over-inclusion: ordering skew can only add
rows, never drop in-window ones.

Steps: create fresh DB -> copy rows >= cutoff (all tables by rowid tail;
heartbeats by created_at; gaps in full) -> recreate indexes -> carry over
PRAGMA user_version (ledger backfill gate) -> optionally --swap:
checkpoint+rename the old DB into data/archive/ and rename the new file into
place.  Run with the server STOPPED.

  python scripts/rebuild_hot_decision_audit.py --days 7
  python scripts/rebuild_hot_decision_audit.py --days 7 --swap
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PARENT = "strategy_decisions"
CHILDREN = [
    "strategy_decision_snapshots",
    "strategy_decision_side_ev",
    "strategy_decision_outcomes",
    "strategy_decision_events",
]
TS_TABLES = ["decision_audit_heartbeats", "decision_audit_gaps"]
# Keep gap records regardless of age -- the table is a small audit-integrity
# map, not per-cycle telemetry.
COPY_ALL = ["decision_audit_gaps"]
# Extra rowids subtracted from each probed boundary: absorbs write-queue
# reordering between decision_ts and insert order (and orphan/NULL probes).
ROWID_MARGIN = 50000


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def _probe_parent_ts(conn: sqlite3.Connection, table: str, rid: int):
    """decision_ts of the parent row for `table`.rowid=rid (None if orphan)."""
    row = conn.execute(
        f"SELECT d.decision_ts FROM src.{table} c "
        f"LEFT JOIN src.{PARENT} d ON d.decision_id = c.decision_id "
        f"WHERE c.rowid = ?",
        (rid,),
    ).fetchone()
    return row[0] if row else None


def _child_rowid_cutoff(conn: sqlite3.Connection, table: str, pad_ts: float) -> int:
    """Smallest rowid in child `table` whose parent decision_ts >= pad_ts.

    Binary search over rowid: ~log2(N) point lookups instead of a table scan.
    Orphan probes (NULL parent) are treated as in-window so the boundary can
    only move left -- over-inclusion is safe, a dropped row is not.
    """
    hi = conn.execute(f"SELECT max(rowid) FROM src.{table}").fetchone()[0] or 0
    if hi == 0:
        return 1
    lo = 1
    ts = _probe_parent_ts(conn, table, lo)
    if ts is None or ts >= pad_ts:
        return 1  # oldest row already in-window: copy everything
    while lo < hi:
        mid = (lo + hi) // 2
        ts = _probe_parent_ts(conn, table, mid)
        if ts is None or ts >= pad_ts:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _parent_rowid_cutoff(conn: sqlite3.Connection, pad_ts: float) -> int:
    """First parent rowid whose decision_ts >= pad_ts (one index probe)."""
    row = conn.execute(
        f"SELECT rowid FROM src.{PARENT} INDEXED BY idx_decisions_ts "
        f"WHERE decision_ts >= ? LIMIT 1",
        (pad_ts,),
    ).fetchone()
    return row[0] if row else 1


def rebuild(db_path: Path, out_path: Path, days: float, dry: bool) -> int:
    cutoff = time.time() - days * 86400.0
    # Boundary probes run 24h behind the semantic cutoff so rowid/decision_ts
    # skew can only ever over-include rows.
    pad_ts = cutoff - 86400.0
    print(f"[rebuild] cutoff={_utc(cutoff)} ({days}d) pad={_utc(pad_ts)} "
          f"dry_run={dry}", flush=True)

    src = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, timeout=300,
    )
    keep = src.execute(
        f"SELECT COUNT(*) FROM {PARENT} WHERE decision_ts >= ?", (cutoff,)
    ).fetchone()[0]
    print(f"[rebuild] parents to keep: {keep:,}", flush=True)
    if dry:
        print("[rebuild] dry-run: no files written", flush=True)
        src.close()
        return 0

    table_ddl = dict(src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'"
    ).fetchall())
    index_sql = [r[0] for r in src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall()]
    user_version = src.execute("PRAGMA user_version").fetchone()[0]
    table_cols = {
        name: [r[1] for r in src.execute(f"PRAGMA table_info({name})")]
        for name in table_ddl
    }

    if out_path.exists():
        out_path.unlink()
    new = sqlite3.connect(str(out_path))
    # Bulk-load pragmas: no journal, no sync, huge cache.  The file is
    # disposable until the swap; a crash just means re-run.
    new.execute("PRAGMA journal_mode = OFF")
    new.execute("PRAGMA synchronous = OFF")
    # ~256MB cache: big enough to keep hot pages, small enough that a 16GB
    # box with ~3GB free never page-thrashes (observed stall at -2000000).
    new.execute("PRAGMA cache_size = -256000")
    for name, ddl in table_ddl.items():
        new.execute(ddl)
    new.commit()

    new.execute("ATTACH DATABASE ? AS src", (str(db_path),))
    new.execute("PRAGMA busy_timeout = 300000")

    def _copy_tail(table: str, rid_cut: int) -> int:
        cols = ", ".join(f'"{c}"' for c in table_cols[table])
        new.execute(
            f'INSERT INTO {table} ("rowid", {cols}) '
            f"SELECT rowid, * FROM src.{table} WHERE rowid >= ?",
            (rid_cut,),
        )
        new.commit()
        return new.total_changes

    t0 = time.time()
    before = new.total_changes
    p_cut = _parent_rowid_cutoff(new, pad_ts)
    _copy_tail(PARENT, max(1, p_cut - ROWID_MARGIN))
    print(f"[rebuild] {PARENT}: copied {new.total_changes - before:,} "
          f"(rowid>={p_cut}-{ROWID_MARGIN}, {time.time()-t0:.0f}s)", flush=True)

    for t in CHILDREN:
        t1 = time.time()
        before = new.total_changes
        cut = _child_rowid_cutoff(new, t, pad_ts)
        _copy_tail(t, max(1, cut - ROWID_MARGIN))
        print(f"[rebuild] {t}: copied {new.total_changes - before:,} "
              f"(rowid>={cut}-{ROWID_MARGIN}, {time.time()-t1:.0f}s)",
              flush=True)

    for t in TS_TABLES:
        if t in COPY_ALL:
            cond, params = "1", ()
        else:
            cond, params = "created_at >= ?", (pad_ts,)
        t1 = time.time()
        before = new.total_changes
        new.execute(f"INSERT INTO {t} SELECT * FROM src.{t} WHERE {cond}", params)
        new.commit()
        print(f"[rebuild] {t}: copied {new.total_changes-before:,} "
              f"({time.time()-t1:.0f}s)", flush=True)

    # Indexes AFTER bulk load -- building them per-row during insert is what
    # makes delete-based archiving slow.
    t1 = time.time()
    for sql in index_sql:
        new.execute(sql)
    new.commit()
    print(f"[rebuild] {len(index_sql)} indexes built ({time.time()-t1:.0f}s)",
          flush=True)

    new.execute(f"PRAGMA user_version = {user_version}")
    new.commit()
    new.execute("PRAGMA journal_mode = WAL")
    try:
        new.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass  # empty WAL / transient table lock — file is already consistent
    new.commit()
    new.execute("DETACH DATABASE src")
    new.close()
    src.close()
    print(f"[rebuild] done in {time.time()-t0:.0f}s -> "
          f"{out_path} ({out_path.stat().st_size/1e9:.2f}GB)", flush=True)
    return 0


def swap(db_path: Path, out_path: Path, archive_dir: Path) -> int:
    """Rename live -> archive_dir/decision_audit_legacy_<date>.db, new -> live."""
    # Fold the old WAL into the main file before moving it.  A pinned reader
    # (e.g. a stale ad-hoc query) can starve the checkpoint; if frames remain
    # un-checkpointed, deleting -wal would silently discard the newest
    # committed audit rows -- abort instead of "moving anyway".
    try:
        con = sqlite3.connect(str(db_path), timeout=120)
        con.execute("PRAGMA busy_timeout = 30000")
        for _ in range(3):
            row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row and row[0] == 0 and row[1] == row[2]:
                break
            time.sleep(2)
        con.close()
    except Exception as exc:
        print(f"[swap] live checkpoint error: {exc}", flush=True)
    wal = Path(str(db_path) + "-wal")
    if wal.exists() and wal.stat().st_size > 32:
        print(
            f"[swap] ABORT: {wal.name} still holds "
            f"{wal.stat().st_size:,} un-checkpointed bytes -- a reader is "
            "pinning it. Close stray connections and re-run with --swap.",
            flush=True,
        )
        return 1

    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d", time.gmtime())
    legacy = archive_dir / f"decision_audit_legacy_{stamp}.db"
    i = 0
    while legacy.exists():
        i += 1
        legacy = archive_dir / f"decision_audit_legacy_{stamp}_{i}.db"

    os.replace(db_path, legacy)
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    os.replace(out_path, db_path)
    for suffix in ("-wal", "-shm"):
        p = Path(str(out_path) + suffix)
        if p.exists():
            p.unlink()
    print(f"[swap] live -> {legacy}", flush=True)
    print(f"[swap] {out_path.name} -> {db_path}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/decision_audit.db")
    ap.add_argument("--out", default="data/decision_audit_new.db")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--swap", action="store_true",
                    help="move old DB to data/archive/ and install the new one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path, out_path = Path(args.db), Path(args.out)
    if not (args.swap and out_path.exists()):
        # Skip the rebuild only when --swap is asked to reuse a finished
        # rebuild (resume path).
        rc = rebuild(db_path, out_path, args.days, args.dry_run)
        if rc:
            return rc
    if args.swap and not args.dry_run:
        return swap(db_path, out_path, Path("data/archive"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
