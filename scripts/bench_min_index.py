#!/usr/bin/env python3
"""Schema experiment: minimal hot-path indexing vs current book_events schema.

Replays recorded events from the production archive (read-only) into bench
DBs on the same volume, under the same pragmas/batch shape as the live
writer.  Three variants isolate index cost:

  A_current     : production schema (TEXT PK + 3 secondary indexes) = 4 B-trees/row
  B_no_secondary: TEXT PK only (drop the 3 secondary indexes)
  C_rowid_only  : no PK, no indexes (rowid = insertion order)

Each variant: preload PRELOAD events (builds comparable B-tree depth),
then measure MEASURE events in 20k batches.  Variant C then times the
post-seal CREATE INDEX cost for the three deferred indexes.

Same rows, same order, same batch size, same sort key, sequential runs —
the disk is exclusively the bench's between variants.
"""
import json, os, sqlite3, sys, time
from pathlib import Path

PROD_DB = Path("data/kalshi_book_archive.db")
OUT_DIR = Path("reports")
BATCH = 20000
PRELOAD = int(os.getenv("BENCH_PRELOAD", "2000000"))
MEASURE = int(os.getenv("BENCH_MEASURE", "400000"))

COLS = ("archive_event_id, collector_instance_id, connection_id,"
        " subscription_id, market_ticker, message_type, sequence_number,"
        " exchange_timestamp_raw, received_at_utc_ns,"
        " received_at_monotonic_ns, raw_payload, parser_version")
INS = f"INSERT INTO book_events({COLS}) VALUES({','.join('?'*12)})"

DDL_TABLE = """CREATE TABLE book_events(
  archive_event_id TEXT, collector_instance_id TEXT NOT NULL,
  connection_id TEXT NOT NULL, subscription_id INTEGER,
  market_ticker TEXT, message_type TEXT NOT NULL, sequence_number INTEGER,
  exchange_timestamp_raw TEXT, received_at_utc_ns INTEGER NOT NULL,
  received_at_monotonic_ns INTEGER NOT NULL, raw_payload TEXT NOT NULL,
  parser_version TEXT NOT NULL)"""

VARIANTS = {
    "A_current": DDL_TABLE + ";" + """
ALTER TABLE book_events RENAME TO _t;""" + """CREATE TABLE book_events(
  archive_event_id TEXT PRIMARY KEY, collector_instance_id TEXT NOT NULL,
  connection_id TEXT NOT NULL, subscription_id INTEGER,
  market_ticker TEXT, message_type TEXT NOT NULL, sequence_number INTEGER,
  exchange_timestamp_raw TEXT, received_at_utc_ns INTEGER NOT NULL,
  received_at_monotonic_ns INTEGER NOT NULL, raw_payload TEXT NOT NULL,
  parser_version TEXT NOT NULL);
INSERT INTO book_events SELECT * FROM _t; DROP TABLE _t;
CREATE INDEX idx_sid_seq ON book_events(connection_id, subscription_id, sequence_number);
CREATE INDEX idx_ticker_recv ON book_events(market_ticker, received_at_utc_ns);
CREATE INDEX idx_recv ON book_events(received_at_utc_ns);""",
}

# Variant A needs the PK schema from the start — simpler: three explicit DDLs.
VARIANTS = {
    "A_current": """CREATE TABLE book_events(
  archive_event_id TEXT PRIMARY KEY, collector_instance_id TEXT NOT NULL,
  connection_id TEXT NOT NULL, subscription_id INTEGER,
  market_ticker TEXT, message_type TEXT NOT NULL, sequence_number INTEGER,
  exchange_timestamp_raw TEXT, received_at_utc_ns INTEGER NOT NULL,
  received_at_monotonic_ns INTEGER NOT NULL, raw_payload TEXT NOT NULL,
  parser_version TEXT NOT NULL);
CREATE INDEX idx_sid_seq ON book_events(connection_id, subscription_id, sequence_number);
CREATE INDEX idx_ticker_recv ON book_events(market_ticker, received_at_utc_ns);
CREATE INDEX idx_recv ON book_events(received_at_utc_ns);""",
    "B_no_secondary": """CREATE TABLE book_events(
  archive_event_id TEXT PRIMARY KEY, collector_instance_id TEXT NOT NULL,
  connection_id TEXT NOT NULL, subscription_id INTEGER,
  market_ticker TEXT, message_type TEXT NOT NULL, sequence_number INTEGER,
  exchange_timestamp_raw TEXT, received_at_utc_ns INTEGER NOT NULL,
  received_at_monotonic_ns INTEGER NOT NULL, raw_payload TEXT NOT NULL,
  parser_version TEXT NOT NULL);""",
    "C_rowid_only": DDL_TABLE,
}

POSTSEAL_INDEXES = [
    ("idx_sid_seq", "CREATE INDEX idx_sid_seq ON book_events(connection_id, subscription_id, sequence_number)"),
    ("idx_ticker_recv", "CREATE INDEX idx_ticker_recv ON book_events(market_ticker, received_at_utc_ns)"),
    ("idx_recv", "CREATE INDEX idx_recv ON book_events(received_at_utc_ns)"),
]


def pragmas(c):
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA cache_size=-1048576")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA mmap_size=536870912")
    c.execute("PRAGMA wal_autocheckpoint=0")


def wal_mb(db):
    w = Path(str(db) + "-wal")
    return round(w.stat().st_size / 1e6, 1) if w.exists() else 0.0


def load_rows(n):
    src = sqlite3.connect(f"file:{PROD_DB}?mode=ro", uri=True)
    rows = src.execute(f"SELECT {COLS} FROM book_events ORDER BY rowid LIMIT {n}").fetchall()
    src.close()
    return rows


def run_variant(name, ddl, rows, preload_n, measure_n):
    db = Path(f"data/_bench_{name}.db")
    for suf in ("", "-wal", "-shm"):
        p = Path(str(db) + suf)
        if p.exists():
            p.unlink()
    c = sqlite3.connect(str(db))
    pragmas(c)
    c.executescript(ddl)

    t0 = time.perf_counter()
    i = 0
    while i < preload_n:
        b = [tuple(r) for r in rows[i:i + BATCH]]
        b.sort(key=lambda r: (r[4] or "", r[8]))
        c.execute("BEGIN IMMEDIATE")
        c.executemany(INS, b)
        c.execute("COMMIT")
        i += len(b)
    preload_s = time.perf_counter() - t0

    lat = []
    t0 = time.perf_counter()
    while i < preload_n + measure_n:
        b = [tuple(r) for r in rows[i:i + BATCH]]
        b.sort(key=lambda r: (r[4] or "", r[8]))
        bt = time.perf_counter()
        c.execute("BEGIN IMMEDIATE")
        c.executemany(INS, b)
        c.execute("COMMIT")
        lat.append(time.perf_counter() - bt)
        i += len(b)
    measure_s = time.perf_counter() - t0

    res = {
        "variant": name,
        "preload_events": preload_n,
        "preload_s": round(preload_s, 1),
        "preload_ev_s": round(preload_n / preload_s),
        "measure_events": measure_n,
        "measure_s": round(measure_s, 1),
        "measure_ev_s": round(measure_n / measure_s),
        "batch_ms_median": round(sorted(lat)[len(lat) // 2] * 1000, 1),
        "batch_ms_p95": round(sorted(lat)[int(len(lat) * .95)] * 1000, 1),
        "batch_ms_max": round(max(lat) * 1000, 1),
        "db_mb": round(db.stat().st_size / 1e6, 1),
        "wal_mb": wal_mb(db),
    }

    if name == "C_rowid_only":
        idx = {}
        for nm, sql in POSTSEAL_INDEXES:
            t = time.perf_counter()
            c.execute(sql)
            idx[nm] = round(time.perf_counter() - t, 1)
        res["postseal_index_s"] = idx
        res["db_mb_after_index"] = round(db.stat().st_size / 1e6, 1)
    c.close()
    return res


def main():
    Path("data").mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)
    total = PRELOAD + MEASURE
    print(f"loading {total} rows from production DB (ro)...", flush=True)
    rows = load_rows(total)
    print(f"loaded {len(rows)}; replaying identical order per variant", flush=True)

    out = {
        "bench": "book_events minimal-index experiment",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workload": {
            "source": "production archive replay, rowid order",
            "rows_total": len(rows),
            "preload": PRELOAD, "measure": MEASURE, "batch": BATCH,
            "pragmas": "WAL sync=NORMAL cache=1GB mmap=512MB autocheckpoint=0",
            "note": "bench scale ~2.4M rows; production table is 8.6M+ — "
                    "index costs at production depth are higher still",
        },
        "results": [],
    }
    for name, ddl in VARIANTS.items():
        print(f"--- {name} ---", flush=True)
        r = run_variant(name, ddl, rows, PRELOAD, MEASURE)
        print(json.dumps(r, indent=2), flush=True)
        out["results"].append(r)

    ts = time.strftime("%Y%m%d_%H%M%S")
    f = OUT_DIR / f"bench_min_index_{ts}.json"
    f.write_text(json.dumps(out, indent=2))
    print(f"wrote {f}")


if __name__ == "__main__":
    sys.exit(main())
