#!/usr/bin/env python3
"""
Deep diagnostic script to investigate why fills are not being tracked in the database.
Audits the entire fills ingestion pipeline from execution to persistence.
"""

import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

def check_fills_database():
    """Check fills database structure and content."""
    db_path = Path('data/kalshi_fills.db')
    
    if not db_path.exists():
        print("ERROR: Fills database does not exist")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check table structure
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print(f"Database tables: {[t[0] for t in tables]}")
    
    # Check row count
    cursor.execute("SELECT COUNT(*) FROM kalshi_fills;")
    count = cursor.fetchone()[0]
    print(f"Total fills in database: {count}")
    
    # Check for any recent fills
    cursor.execute("SELECT * FROM kalshi_fills LIMIT 5;")
    fills = cursor.fetchall()
    
    if fills:
        cursor.execute("PRAGMA table_info(kalshi_fills);")
        columns = [col[1] for col in cursor.fetchall()]
        print("Recent fills:")
        for fill in fills:
            print(f"  {dict(zip(columns, fill))}")
    else:
        print("WARNING: No fills found in database")
    
    conn.close()
    return count > 0

def check_fills_ledger_code():
    """Check fills_ledger.py for potential issues."""
    ledger_path = Path('merid/event_venues/kalshi/fills_ledger.py')
    
    if not ledger_path.exists():
        print("ERROR: fills_ledger.py not found")
        return False
    
    content = ledger_path.read_text(encoding='utf-8', errors='ignore')
    
    # Check for database persistence logic
    has_db_persist = '_persist_queue' in content and '_writer_task' in content
    print(f"Has database persistence logic: {has_db_persist}")
    
    # Check for ingest methods
    has_ingest_http = 'ingest_http_fills' in content
    has_ingest_ws = 'ingest_ws_fill' in content
    print(f"Has ingest_http_fills: {has_ingest_http}")
    print(f"Has ingest_ws_fill: {has_ingest_ws}")
    
    # Check for database write logic
    has_db_write = 'INSERT INTO kalshi_fills' in content or 'INSERT OR REPLACE INTO kalshi_fills' in content or 'UPSERT INTO kalshi_fills' in content
    print(f"Has database write logic: {has_db_write}")
    
    return has_db_persist and has_ingest_http and has_ingest_ws and has_db_write

def check_fills_poller_code():
    """Check fills_poller.py for potential issues."""
    poller_path = Path('merid/event_venues/kalshi/fills_poller.py')
    
    if not poller_path.exists():
        print("ERROR: fills_poller.py not found")
        return False
    
    content = poller_path.read_text(encoding='utf-8', errors='ignore')
    
    # Check for poll loop
    has_poll_loop = '_poll_loop' in content or 'while self._running' in content
    print(f"Has poll loop: {has_poll_loop}")
    
    # Check for ledger integration
    has_ledger_call = 'ingest_http_fills' in content
    print(f"Calls ledger.ingest_http_fills: {has_ledger_call}")
    
    # Check for error handling
    has_error_handling = 'except Exception' in content
    print(f"Has error handling: {has_error_handling}")
    
    return has_poll_loop and has_ledger_call

def check_startup_integration():
    """Check if FillsPoller is started in main_15m_lean.py."""
    main_path = Path('web/main_15m_lean.py')
    
    if not main_path.exists():
        print("ERROR: main_15m_lean.py not found")
        return False
    
    content = main_path.read_text(encoding='utf-8', errors='ignore')
    
    # Check for FillsPoller startup
    has_poller_start = 'get_fills_poller' in content and 'await _fills_poller.start()' in content
    print(f"FillsPoller started in main_15m_lean.py: {has_poller_start}")
    
    # Check if it's marked as non-fatal
    is_non_fatal = 'non-fatal' in content.lower() and 'fills_poller' in content.lower()
    print(f"FillsPoller marked as non-fatal: {is_non_fatal}")
    
    return has_poller_start

def check_ws_bridge_fills():
    """Check if WS bridge handles fills."""
    ws_path = Path('merid/event_venues/kalshi/ws_bridge.py')
    
    if not ws_path.exists():
        print("ERROR: ws_bridge.py not found")
        return False
    
    content = ws_path.read_text(encoding='utf-8', errors='ignore')
    
    # Check for fill handling
    has_fill_handler = 'fill' in content.lower() and 'ingest' in content.lower()
    print(f"WS bridge has fill handling: {has_fill_handler}")
    
    return has_fill_handler

def main():
    print("=" * 80)
    print("FILLS PIPELINE DEEP AUDIT")
    print("=" * 80)
    print()
    
    # Check database
    print("1. Checking fills database...")
    db_ok = check_fills_database()
    print()
    
    # Check fills_ledger code
    print("2. Checking fills_ledger.py...")
    ledger_ok = check_fills_ledger_code()
    print()
    
    # Check fills_poller code
    print("3. Checking fills_poller.py...")
    poller_ok = check_fills_poller_code()
    print()
    
    # Check startup integration
    print("4. Checking startup integration...")
    startup_ok = check_startup_integration()
    print()
    
    # Check WS bridge fills
    print("5. Checking WS bridge fill handling...")
    ws_ok = check_ws_bridge_fills()
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Database has fills: {db_ok}")
    print(f"FillsLedger code complete: {ledger_ok}")
    print(f"FillsPoller code complete: {poller_ok}")
    print(f"Startup integration complete: {startup_ok}")
    print(f"WS bridge fill handling: {ws_ok}")
    print()
    
    if not db_ok:
        print("CRITICAL: Fills database is empty - pipeline not working")
        if not startup_ok:
            print("  -> FillsPoller may not be starting correctly")
        if not poller_ok:
            print("  -> FillsPoller code may be incomplete")
        if not ledger_ok:
            print("  -> FillsLedger code may be incomplete")
        sys.exit(1)
    else:
        print("Fills database has data - pipeline appears working")
        sys.exit(0)

if __name__ == '__main__':
    main()
