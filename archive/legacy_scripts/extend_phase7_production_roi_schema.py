#!/usr/bin/env python3
"""Extend Phase 7 Production ROI Schema with P&L and Risk Metrics."""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("per_task_roi.db")

def extend_phase7_roi_schema():
    """Add production-specific columns to ROI database for Phase 7."""
    
    if not DB_PATH.exists():
        print("❌ ROI database not found")
        return False
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Check existing columns
    cursor.execute("PRAGMA table_info(per_task_roi_log)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    # Production-specific columns to add
    production_columns = [
        ("real_pnl_usd", "REAL"),
        ("unrealized_pnl_usd", "REAL"), 
        ("daily_pnl_usd", "REAL"),
        ("cumulative_pnl_usd", "REAL"),
        ("max_drawdown_percent", "REAL"),
        ("current_drawdown_percent", "REAL"),
        ("slippage_bps", "REAL"),
        ("execution_latency_ms", "REAL"),
        ("decision_latency_ms", "REAL"),
        ("error_rate_percent", "REAL"),
        ("position_concentration", "REAL"),
        ("venue_success_rate", "REAL"),
        ("order_success_rate", "REAL"),
        ("kill_switch_triggered", "BOOLEAN"),
        ("kill_switch_reason", "TEXT"),
        ("production_constraints_met", "BOOLEAN"),
        ("slo_compliance_percent", "REAL"),
        ("error_budget_used_percent", "REAL"),
        ("burn_rate", "REAL"),
        ("risk_limit_breached", "BOOLEAN"),
        ("capital_utilization_percent", "REAL")
    ]
    
    # Add missing columns
    added_columns = []
    for column_name, column_type in production_columns:
        if column_name not in existing_columns:
            try:
                alter_sql = f"ALTER TABLE per_task_roi_log ADD COLUMN {column_name} {column_type}"
                cursor.execute(alter_sql)
                added_columns.append(column_name)
                print(f"✅ Added column: {column_name}")
            except sqlite3.Error as e:
                print(f"❌ Failed to add {column_name}: {e}")
        else:
            print(f"✓ Column already exists: {column_name}")
    
    # Create production metrics summary table
    create_summary_sql = """
    CREATE TABLE IF NOT EXISTS phase7_production_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        run_date TEXT NOT NULL,
        total_tasks INTEGER,
        successful_tasks INTEGER,
        total_hours_saved REAL,
        average_roi REAL,
        total_pnl_usd REAL,
        max_drawdown_percent REAL,
        avg_decision_latency_ms REAL,
        avg_execution_latency_ms REAL,
        error_rate_percent REAL,
        slo_compliance_percent REAL,
        error_budget_used_percent REAL,
        kill_switch_triggered BOOLEAN,
        production_gates_passed BOOLEAN,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(batch_id, run_date)
    )
    """
    
    try:
        cursor.execute(create_summary_sql)
        print("✅ Production summary table ready")
    except sqlite3.Error as e:
        print(f"❌ Failed to create summary table: {e}")
    
    # Create SLO breach tracking table
    create_slo_breach_sql = """
    CREATE TABLE IF NOT EXISTS phase7_slo_breaches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        slo_type TEXT NOT NULL,
        threshold_value REAL,
        actual_value REAL,
        breach_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        severity TEXT,
        resolved BOOLEAN DEFAULT FALSE,
        resolution_timestamp TIMESTAMP,
        notes TEXT
    )
    """
    
    try:
        cursor.execute(create_slo_breach_sql)
        print("✅ SLO breach tracking table ready")
    except sqlite3.Error as e:
        print(f"❌ Failed to create SLO breach table: {e}")
    
    # Create kill switch event log
    create_kill_switch_sql = """
    CREATE TABLE IF NOT EXISTS phase7_kill_switch_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        trigger_value REAL,
        threshold_value REAL,
        event_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        lane_halted BOOLEAN DEFAULT TRUE,
        recovery_actions TEXT,
        recovery_timestamp TIMESTAMP,
        resolved BOOLEAN DEFAULT FALSE,
        notes TEXT
    )
    """
    
    try:
        cursor.execute(create_kill_switch_sql)
        print("✅ Kill switch event table ready")
    except sqlite3.Error as e:
        print(f"❌ Failed to create kill switch table: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Phase 7 ROI schema extension complete")
    print(f"Added {len(added_columns)} new production columns")
    print(f"Created 3 new production tracking tables")
    
    return True

def validate_production_schema():
    """Validate that production schema is properly configured."""
    
    if not DB_PATH.exists():
        print("❌ ROI database not found")
        return False
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Check required production columns
    required_columns = [
        "real_pnl_usd", "daily_pnl_usd", "max_drawdown_percent",
        "execution_latency_ms", "decision_latency_ms", "error_rate_percent",
        "kill_switch_triggered", "slo_compliance_percent", "error_budget_used_percent"
    ]
    
    cursor.execute("PRAGMA table_info(per_task_roi_log)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    missing_columns = [col for col in required_columns if col not in existing_columns]
    
    if missing_columns:
        print(f"❌ Missing required production columns: {missing_columns}")
        return False
    
    # Check production tables exist
    required_tables = [
        "phase7_production_summary",
        "phase7_slo_breaches", 
        "phase7_kill_switch_events"
    ]
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = [row[0] for row in cursor.fetchall()]
    
    missing_tables = [table for table in required_tables if table not in existing_tables]
    
    if missing_tables:
        print(f"❌ Missing required production tables: {missing_tables}")
        return False
    
    conn.close()
    print("✅ Production schema validation passed")
    return True

def backfill_phase7_production_data():
    """Backfill existing Phase 7 data with production metrics."""
    
    if not DB_PATH.exists():
        print("❌ ROI database not found")
        return False
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Fetch Phase 7 tasks that need production metrics backfill
    query = """
        SELECT task_id, notes
        FROM per_task_roi_log
        WHERE batch_id = 'phase7_production_combined'
        AND (real_pnl_usd IS NULL OR daily_pnl_usd IS NULL)
    """
    
    cursor.execute(query)
    tasks = cursor.fetchall()
    
    if not tasks:
        print("✅ No Phase 7 tasks need backfilling")
        conn.close()
        return True
    
    updated = 0
    for task_id, notes in tasks:
        try:
            # Parse production metrics from notes
            real_pnl = 0.0
            daily_pnl = 0.0
            max_drawdown = 0.0
            execution_latency = 0.0
            decision_latency = 0.0
            error_rate = 0.0
            concentration = 0.0
            
            if notes:
                # Extract metrics from notes string
                import re
                
                # Extract P&L
                pnl_match = re.search(r'pnl_impact=\$(\d+\.?\d*)', notes)
                if pnl_match:
                    real_pnl = float(pnl_match.group(1))
                    if '-' in notes.split('pnl_impact=')[1].split('$')[1]:
                        real_pnl = -real_pnl
                
                # Extract daily P&L
                daily_pnl_match = re.search(r'daily_pnl=\$(\d+\.?\d*)', notes)
                if daily_pnl_match:
                    daily_pnl = float(daily_pnl_match.group(1))
                    if '-' in notes.split('daily_pnl=')[1].split('$')[1]:
                        daily_pnl = -daily_pnl
                
                # Extract drawdown
                drawdown_match = re.search(r'drawdown=(\d+\.?\d*)%', notes)
                if drawdown_match:
                    max_drawdown = float(drawdown_match.group(1)) / 100.0
                
                # Extract latencies
                decision_match = re.search(r'decision_latency=(\d+)ms', notes)
                if decision_match:
                    decision_latency = float(decision_match.group(1))
                
                execution_match = re.search(r'execution_latency=(\d+)ms', notes)
                if execution_match:
                    execution_latency = float(execution_match.group(1))
                
                # Extract concentration
                conc_match = re.search(r'concentration=(\d+\.?\d*)%', notes)
                if conc_match:
                    concentration = float(conc_match.group(1)) / 100.0
            
            # Update production columns
            update_sql = """
                UPDATE per_task_roi_log
                SET 
                    real_pnl_usd = ?,
                    daily_pnl_usd = ?,
                    max_drawdown_percent = ?,
                    execution_latency_ms = ?,
                    decision_latency_ms = ?,
                    error_rate_percent = ?,
                    position_concentration = ?,
                    slo_compliance_percent = ?,
                    error_budget_used_percent = ?
                WHERE task_id = ?
            """
            
            # Calculate SLO compliance (simplified)
            slo_compliance = 100.0 if error_rate <= 0.1 and execution_latency <= 200 and decision_latency <= 100 else 95.0
            
            cursor.execute(update_sql, (
                real_pnl,
                daily_pnl, 
                max_drawdown,
                execution_latency,
                decision_latency,
                error_rate,
                concentration,
                slo_compliance,
                error_rate * 100,  # Simplified error budget usage
                task_id
            ))
            
            updated += 1
            print(f"✅ Backfilled production metrics for {task_id}")
            
        except Exception as e:
            print(f"❌ Failed to backfill {task_id}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Backfilled {updated} Phase 7 tasks with production metrics")
    return True

def main():
    """Main execution function."""
    print("=" * 60)
    print("PHASE 7 PRODUCTION ROI SCHEMA EXTENSION")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Extend schema
    if not extend_phase7_roi_schema():
        print("❌ Schema extension failed")
        return False
    
    # Validate schema
    if not validate_production_schema():
        print("❌ Schema validation failed")
        return False
    
    # Backfill existing data
    if not backfill_phase7_production_data():
        print("❌ Data backfill failed")
        return False
    
    print("\n✅ Phase 7 production ROI schema ready")
    print("Next: Generate Phase 7 completion report with production metrics")
    return True

if __name__ == "__main__":
    main()
