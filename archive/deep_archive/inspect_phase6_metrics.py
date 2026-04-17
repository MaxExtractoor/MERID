#!/usr/bin/env python3
"""Inspect Phase 6 metrics in ROI database."""

import sqlite3
from pathlib import Path

DB_PATH = Path("per_task_roi.db")
BATCH_ID = "phase6_joint_lane"

def inspect_phase6_metrics():
    if not DB_PATH.exists():
        print("❌ Database not found")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    query = """
        SELECT 
            task_id,
            task_type,
            latency_improvement,
            reliability_improvement,
            strategy_policy_accuracy,
            notes
        FROM per_task_roi_log
        WHERE batch_id = ?
        ORDER BY date
    """
    
    cursor.execute(query, (BATCH_ID,))
    rows = cursor.fetchall()
    
    print("Phase 6 Metrics:")
    print("=" * 80)
    for row in rows:
        print(f"{row[0]}")
        print(f"  Type: {row[1]}")
        print(f"  Latency: {row[2]}")
        print(f"  Reliability: {row[3]}")
        print(f"  Strategy Accuracy: {row[4]}")
        print(f"  Notes: {row[5][:100]}...")
        print()
    
    conn.close()

if __name__ == "__main__":
    inspect_phase6_metrics()
