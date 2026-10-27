#!/usr/bin/env python3
"""
Check recent fills from Kalshi fills database to verify trade execution.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

def check_recent_fills():
    db_path = Path('data/kalshi_fills.db')
    
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get table schema
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables in database:", [t[0] for t in tables])
    print()
    
    # Get recent fills
    try:
        # Get column names first
        cursor.execute("PRAGMA table_info(kalshi_fills);")
        columns = [col[1] for col in cursor.fetchall()]
        print("Columns:", columns)
        print()
        
        # Try to find timestamp column
        timestamp_col = None
        for col in columns:
            if 'time' in col.lower() or 'date' in col.lower() or 'created' in col.lower():
                timestamp_col = col
                break
        
        if timestamp_col:
            cursor.execute(f"SELECT * FROM kalshi_fills ORDER BY {timestamp_col} DESC LIMIT 5;")
        else:
            cursor.execute("SELECT * FROM kalshi_fills LIMIT 5;")
        fills = cursor.fetchall()
        
        print("Recent fills:")
        print("=" * 80)
        for i, fill in enumerate(fills, 1):
            print(f"Fill {i}:")
            for col, val in zip(columns, fill):
                print(f"  {col}: {val}")
            print()
            
    except Exception as e:
        print(f"Error querying fills: {e}")
    
    conn.close()

if __name__ == '__main__':
    check_recent_fills()
