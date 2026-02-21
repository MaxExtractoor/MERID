#!/usr/bin/env python3
"""
Initialize ROI Database
Create database with ROI schema
"""

import sys
import sqlite3
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.init_roi_db")

def initialize_roi_database():
    """Initialize ROI database with schema"""
    print("=" * 70)
    print("INITIALIZE ROI DATABASE")
    print("=" * 70)
    
    db_path = "per_task_roi.db"
    
    print(f"Creating database: {db_path}")
    print()
    
    try:
        # Create database with schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS per_task_roi_log (
                task_id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                task_type TEXT NOT NULL,
                module TEXT,
                risk_level TEXT NOT NULL,
                complexity TEXT,
                success BOOLEAN NOT NULL,
                execution_time_seconds REAL NOT NULL,
                swarm_topology TEXT NOT NULL,
                agent_count INTEGER NOT NULL,
                tool_count INTEGER NOT NULL,
                enforcement_mode TEXT NOT NULL,
                human_baseline_hours REAL NOT NULL,
                human_time_saved_hours REAL NOT NULL,
                token_cost REAL,
                infra_cost_usd REAL,
                cost_savings_usd REAL NOT NULL,
                quality_improvement REAL NOT NULL,
                defects_found INTEGER NOT NULL,
                defects_avoided INTEGER NOT NULL,
                human_review_friction REAL NOT NULL,
                slo_compliance TEXT NOT NULL,
                slo_violations TEXT NOT NULL,
                business_value TEXT NOT NULL,
                impact_score REAL NOT NULL,
                roi_score REAL NOT NULL,
                revenue_impact_usd REAL,
                risk_reduction_usd REAL,
                experiment_id TEXT,
                batch_id TEXT,
                run_id TEXT NOT NULL,
                human_verified BOOLEAN NOT NULL,
                evidence_links TEXT,
                notes TEXT,
                incidents INTEGER NOT NULL,
                near_misses INTEGER NOT NULL,
                rollback_required BOOLEAN NOT NULL,
                rollback_time_hours REAL
            )
        """)
        
        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_date ON per_task_roi_log(date)",
            "CREATE INDEX IF NOT EXISTS idx_task_type ON per_task_roi_log(task_type)",
            "CREATE INDEX IF NOT EXISTS idx_module ON per_task_roi_log(module)",
            "CREATE INDEX IF NOT EXISTS idx_risk_level ON per_task_roi_log(risk_level)",
            "CREATE INDEX IF NOT EXISTS idx_success ON per_task_roi_log(success)",
            "CREATE INDEX IF NOT EXISTS idx_experiment_id ON per_task_roi_log(experiment_id)",
            "CREATE INDEX IF NOT EXISTS idx_batch_id ON per_task_roi_log(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_run_id ON per_task_roi_log(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_business_value ON per_task_roi_log(business_value)",
            "CREATE INDEX IF NOT EXISTS idx_slo_compliance ON per_task_roi_log(slo_compliance)"
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
        
        conn.commit()
        
        # Verify table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='per_task_roi_log'
        """)
        
        table_exists = cursor.fetchone()
        
        if table_exists:
            print("✅ Database initialized successfully")
            print(f"✅ Table created: per_task_roi_log")
            
            # Get table info
            cursor.execute("PRAGMA table_info(per_task_roi_log)")
            columns = cursor.fetchall()
            print(f"✅ Columns: {len(columns)}")
            
            conn.close()
            
            print()
            print("=" * 70)
            print("ROI DATABASE INITIALIZATION COMPLETE")
            print(f"Database: {db_path}")
            print("Ready for task runner integration")
            print("=" * 70)
            
            return True
        else:
            print("❌ Table creation failed")
            conn.close()
            return False
            
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        return False

if __name__ == "__main__":
    initialize_roi_database()
