#!/usr/bin/env python3
"""Inspect ROI database schema."""

import sqlite3
from pathlib import Path

DB_PATH = Path("per_task_roi.db")

def inspect_schema():
    if not DB_PATH.exists():
        print("❌ Database not found")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(per_task_roi_log)")
    columns = cursor.fetchall()
    
    print("ROI Database Schema:")
    print("=" * 50)
    for col in columns:
        print(f"{col[1]} ({col[2]})")
    
    conn.close()

if __name__ == "__main__":
    inspect_schema()
