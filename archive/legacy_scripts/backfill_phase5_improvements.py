#!/usr/bin/env python3
"""Backfill Phase 5 execution tuning improvement metrics."""

import sqlite3
from pathlib import Path

DB_PATH = Path("per_task_roi.db")


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Ensure latency/reliability improvement columns exist."""
    cur = conn.execute("PRAGMA table_info(per_task_roi_log)")
    existing = {row[1] for row in cur.fetchmany(200)}
    if "latency_improvement" not in existing:
        conn.execute("ALTER TABLE per_task_roi_log ADD COLUMN latency_improvement REAL")
    if "reliability_improvement" not in existing:
        conn.execute("ALTER TABLE per_task_roi_log ADD COLUMN reliability_improvement REAL")


def backfill_phase5() -> int:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"ROI database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_columns(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE per_task_roi_log
               SET latency_improvement = COALESCE(latency_improvement, 0.096),
                   reliability_improvement = COALESCE(reliability_improvement, 0.048)
             WHERE batch_id = 'phase5_execution_tuning'
            """
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main():
    updated = backfill_phase5()
    print(f"Rows updated: {updated}")


if __name__ == "__main__":
    main()
