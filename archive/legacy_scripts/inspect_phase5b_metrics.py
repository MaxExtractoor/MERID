#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('per_task_roi.db')
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT task_id, latency_improvement, reliability_improvement FROM per_task_roi_log WHERE batch_id=?",
    ('phase5b_execution_tuning',)
).fetchall()
for row in rows:
    print(row['task_id'], row['latency_improvement'], row['reliability_improvement'])
conn.close()
