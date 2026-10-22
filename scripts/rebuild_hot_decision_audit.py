#!/usr/bin/env python3
"""Rebuild data/decision_audit.db as a hot-only DB containing the last N days.

Why this exists: archiving-by-delete on the 27GB ledger means every removed
row rewrites parent/child B-trees plus ~15 secondary indexes (observed: multi-
hour single-day transactions).  Rebuild-by-copy is the inverse -- one
INSERT..SELECT per table into a fresh file with indexes deferred until after
the bulk load.  ~15-40 min instead of days.

Steps: create fresh DB -> copy rows >= cutoff (parents keyed by decision_ts,
children by decision_id membership, heartbeats/gaps by created_at) -> recreate
indexes -> carry over PRAGMA user_version (ledger backfill gate) -> optionally
--swap: checkpoint+rename the old DB into data/archive/ and rename the new
file into place.  Run with the server STOPPED.

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


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def rebuild(db_path: Path, out_path: Path, days: float, dry: bool) -> int:
    cutoff = time.time() - days * 86400.0
    print(f"[rebuild] cutoff={_utc(cutoff)} ({days}d)  dry_run={dry}", flush=True)

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

    new.execute(f"ATTACH DATABASE ? AS src", (str(db_path),))
    new.execute("PRAGMA busy_timeout = 300000")

    t0 = time.time()
    # Parents first (children have no declared FKs, but keep logical order).
    new.execute(
        f"INSERT INTO {PARENT} SELECT * FROM src.{PARENT} WHERE decision_ts >= ?",
        (cutoff,),
    )
    new.commit()
    print(f"[rebuild] {PARENT}: copied {new.total_changes:,} "
          f"({time.time()-t0:.0f}s)", flush=True)

    for t in CHILDREN:
        t1 = time.time()
        before = new.total_changes
        # EXISTS against the NEW db's PK-indexed parents (already copied):
        # one sequential scan of the source child + one index probe per row.
        # The IN-subquery on src.parents materialises 626k ids and stalls
        # (observed: PageIn wait, zero IO progress).
        new.execute(
            f"INSERT INTO {t} SELECT s.* FROM src.{t} s WHERE EXISTS "
            f"(SELECT 1 FROM {PARENT} p WHERE p.decision_id = s.decision_id)",
        )
        new.commit()
        print(f"[rebuild] {t}: copied {new.total_changes-before:,} "
              f"({time.time()-t1:.0f}s)", flush=True)

    for t in TS_TABLES:
        if t in COPY_ALL:
            cond, params = "1", ()
        else:
            cond, params = "created_at >= ?", (cutoff,)
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
    # Fold the old WAL into the main file before moving it.
    try:
        con = sqlite3.connect(str(db_path), timeout=120)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
    except Exception as exc:
        print(f"[swap] WARNING: live checkpoint failed ({exc}); moving anyway",
              flush=True)

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
