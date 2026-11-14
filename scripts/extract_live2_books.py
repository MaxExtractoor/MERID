"""One-shot extraction of live2 book-archive evidence for live fill markets.

live2's 71GB WAL forces a ~20min wal-index rebuild per fresh connection, so
this script uses ONE connection for everything: recover once, then copy
archive_coverage / archive_markets / book_events rows for the 111 live-fill
market tickers into a small standalone db for fast repeated analysis.

Read-only against the source; writes only to --out.

    py -3 scripts/extract_live2_books.py --out data/_live2_extract.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

SRC = "data/kalshi_book_archive_live2.db"
FILLS = "data/kalshi_fills.db"


def _live_tickers() -> list[str]:
    c = sqlite3.connect(f"file:{FILLS}?mode=ro", uri=True)
    tk = sorted({r[0] for r in c.execute(
        "SELECT DISTINCT market_ticker FROM kalshi_fills WHERE is_live=1")})
    c.close()
    return tk


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default="data/_live2_extract.db")
    args = ap.parse_args()

    t0 = time.time()
    tickers = _live_tickers()
    print(f"[extract] {len(tickers)} live tickers", flush=True)

    src = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True,
                          timeout=3600)
    print(f"[extract] src connected {time.time()-t0:.0f}s — WAL recovery "
          "may take ~20min on first read", flush=True)

    # warm the wal-index with a trivial read, timed
    tw = time.time()
    src.execute("SELECT COUNT(*) FROM archive_coverage").fetchone()
    print(f"[extract] wal-index ready after {time.time()-tw:.0f}s",
          flush=True)

    out = sqlite3.connect(args.out)
    out.execute("PRAGMA journal_mode=OFF")
    out.execute("PRAGMA synchronous=OFF")
    for t in ("archive_coverage", "archive_markets", "book_events"):
        ddl = src.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()
        if not ddl or not ddl[0]:
            print(f"[extract] missing table {t}", flush=True)
            continue
        out.execute(ddl[0])
    # sessions/alerts are small and useful for provenance
    for t in ("archive_sessions", "archive_alerts"):
        ddl = src.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()
        if ddl and ddl[0]:
            out.execute(ddl[0])

    ph = ",".join("?" * len(tickers))

    def dump(src_t, dst_t, where, params):
        cols = [r[1] for r in src.execute(f"PRAGMA table_info({src_t})")]
        n = 0
        batch = []
        q = f"SELECT {','.join(cols)} FROM {src_t} WHERE {where}"
        for row in src.execute(q, params):
            batch.append(row)
            if len(batch) >= 5000:
                out.executemany(
                    f"INSERT INTO {dst_t} VALUES ({','.join('?'*len(cols))})",
                    batch)
                n += len(batch)
                batch = []
                print(f"[extract] {dst_t}: {n} rows {time.time()-t0:.0f}s",
                      flush=True)
        if batch:
            out.executemany(
                f"INSERT INTO {dst_t} VALUES ({','.join('?'*len(cols))})",
                batch)
            n += len(batch)
        print(f"[extract] {dst_t}: DONE {n} rows", flush=True)
        return n

    dump("archive_coverage", "archive_coverage",
         f"market_ticker IN ({ph})", tickers)
    dump("archive_markets", "archive_markets",
         f"ticker IN ({ph})", tickers)
    dump("book_events", "book_events",
         f"market_ticker IN ({ph})", tickers)
    # sessions + alerts wholesale (small, needed for provenance/dedupe)
    for t in ("archive_sessions", "archive_alerts"):
        try:
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
            rows = src.execute(f"SELECT {','.join(cols)} FROM {t}").fetchall()
            out.executemany(
                f"INSERT INTO {t} VALUES ({','.join('?'*len(cols))})", rows)
            print(f"[extract] {t}: {len(rows)} rows", flush=True)
        except Exception as e:
            print(f"[extract] {t} skipped: {e}", flush=True)

    out.commit()
    for t in ("archive_coverage", "archive_markets", "book_events"):
        try:
            n = out.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"[extract] out {t}: {n}", flush=True)
        except Exception:
            pass
    out.close()
    src.close()
    print(f"[extract] complete in {time.time()-t0:.0f}s -> {args.out}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
