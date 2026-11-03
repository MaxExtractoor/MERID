"""Read-only schema inventory for MERID durable stores.

Opens every DB with mode=ro + query_only so a live writer is never blocked.
Writes a schema dump + table rowcounts to audit_output_alignment_20261101/.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"
DBS = [
    "data/decision_audit.db",
    "data/kalshi_order_attempts.db",
    "data/kalshi_fills.db",
    "data/trade_attribution_fact.db",
    "data/cf_rti_ticks.db",
    "data/calibration.db",
    "data/signals.db",
    "data/kalshi_15m_audit.db",
]


def ro(db_rel: str) -> sqlite3.Connection:
    p = (ROOT / db_rel).resolve()
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=1")
    return con


def main() -> None:
    OUT.mkdir(exist_ok=True)
    report = {}
    for db_rel in DBS:
        p = ROOT / db_rel
        if not p.exists():
            report[db_rel] = {"missing": True}
            continue
        con = ro(db_rel)
        tables = {}
        fast = (ROOT / db_rel).stat().st_size < 500 * 1024 * 1024
        for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            n = "skipped_big_db"
            if fast:
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception as e:  # noqa: BLE001
                    n = f"err:{e}"
            cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
            tables[t] = {"rows": n, "cols": [c[1] + ":" + c[2] for c in cols]}
        idx = con.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()
        ddl = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"
        ).fetchall()
        report[db_rel] = {
            "tables": tables,
            "indexes": [{"name": i[0], "table": i[1], "sql": i[2]} for i in idx],
            "ddl": {d[0]: d[1] for d in ddl},
        }
        con.close()
    (OUT / "schema_inventory.json").write_text(json.dumps(report, indent=2, default=str))
    # Console summary
    for db, rep in report.items():
        print(f"=== {db} ===")
        if rep.get("missing"):
            print("  MISSING")
            continue
        for t, meta in rep["tables"].items():
            print(f"  {t:<52} {meta['rows']}")


if __name__ == "__main__":
    sys.exit(main())
