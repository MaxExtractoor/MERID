#!/usr/bin/env python3
"""Ensure strategy_policy_accuracy column exists in per_task_roi_log."""

import sqlite3
from pathlib import Path

DB_PATH = Path("per_task_roi.db")


def ensure_column():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"ROI database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {row[1] for row in conn.execute('PRAGMA table_info(per_task_roi_log)')}
        if 'strategy_policy_accuracy' not in cols:
            conn.execute('ALTER TABLE per_task_roi_log ADD COLUMN strategy_policy_accuracy REAL')
            conn.commit()
            print("strategy_policy_accuracy column added")
        else:
            print("strategy_policy_accuracy column already present")
    finally:
        conn.close()


def main():
    ensure_column()


if __name__ == "__main__":
    main()
