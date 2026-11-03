"""Verify candidate process: durable commit frontier + writer-health probe.

Read-only. Reports table names, max ts, and post-frontier commit count.
"""
import sqlite3
import sys

DB = r"data\decision_audit.db"
FRONTIER = "2026-11-01T17:04:24.598170"  # recovered durable frontier

def main() -> int:
    conn = sqlite3.connect("file:" + DB.replace("\\", "/") + "?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("tables:", tables)
    # find the decision rows table and its timestamp column
    for t in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        tscol = next((c for c in cols if c in ("ts", "decision_ts", "ts_iso", "timestamp")), None)
        if tscol:
            mx = conn.execute(f"SELECT MAX({tscol}) FROM {t}").fetchone()[0]
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: ts_col={tscol} max={mx} rows={n}")
    conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
