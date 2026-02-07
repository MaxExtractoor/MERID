#!/usr/bin/env python3
"""
Risk Shadow Mode Database Setup

Creates and initializes the database schema for Risk Shadow Mode data collection.
This script sets up all necessary tables for the shadow mode report generator.

Usage:
    python setup_shadow_database.py
"""

import sqlite3
import sys
from pathlib import Path
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ShadowDatabaseSetup:
    """Sets up the Risk Shadow Mode database schema."""
    
    def __init__(self, db_path: str = "data/risk_shadow.db"):
        self.db_path = db_path
        self.ensure_data_directory()
        
    def ensure_data_directory(self):
        """Ensure the data directory exists."""
        data_dir = Path(self.db_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)
        
    def setup_database(self):
        """Create and initialize all database tables."""
        logger.info(f"Setting up Risk Shadow database at {self.db_path}")
        
        # Connect to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create tables
        self._create_shadow_decisions_table(cursor)
        self._create_shadow_metrics_table(cursor)
        self._create_guardrail_triggers_table(cursor)
        self._create_shadow_impact_table(cursor)
        self._create_shadow_data_quality_table(cursor)
        self._create_outlier_analysis_table(cursor)
        self._create_stress_experiments_table(cursor)
        self._create_system_metrics_table(cursor)
        self._create_reliability_metrics_table(cursor)
        self._create_incidents_table(cursor)
        
        # Create indexes
        self._create_indexes(cursor)
        
        # Commit and close
        conn.commit()
        conn.close()
        
        logger.info("Database setup completed successfully")
        
    def _create_shadow_decisions_table(self, cursor):
        """Create shadow decisions table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shadow_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                shadow_action TEXT NOT NULL,
                actual_action TEXT NOT NULL,
                position_id TEXT,
                instrument TEXT,
                position_size REAL,
                venue TEXT,
                market_volatility REAL,
                risk_var REAL,
                risk_drawdown REAL,
                risk_concentration REAL,
                market_conditions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_shadow_metrics_table(self, cursor):
        """Create shadow metrics table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shadow_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                calculation_latency REAL,
                decision_latency REAL,
                contract_latency REAL,
                cpu_usage REAL,
                memory_usage REAL,
                network_usage REAL,
                storage_usage REAL,
                error_rate REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_guardrail_triggers_table(self, cursor):
        """Create guardrail triggers table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS guardrail_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                guardrail_type TEXT NOT NULL,
                trigger_conditions TEXT,
                response_time REAL,
                is_correct INTEGER,
                false_positive INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_shadow_impact_table(self, cursor):
        """Create shadow impact assessment table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shadow_impact (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actual_pnl REAL,
                shadow_pnl REAL,
                actual_var REAL,
                shadow_var REAL,
                actual_drawdown REAL,
                shadow_drawdown REAL,
                actual_concentration REAL,
                shadow_concentration REAL,
                pnl_impact_pct REAL,
                risk_impact_pct REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_shadow_data_quality_table(self, cursor):
        """Create shadow data quality table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shadow_data_quality (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                data_quality_score REAL,
                missing_data_count INTEGER,
                validation_errors INTEGER,
                completeness_score REAL,
                accuracy_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_outlier_analysis_table(self, cursor):
        """Create outlier analysis table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outlier_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outlier_id TEXT UNIQUE NOT NULL,
                timestamp TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                shadow_action TEXT NOT NULL,
                actual_action TEXT NOT NULL,
                classification TEXT NOT NULL,
                rationale TEXT,
                position_id TEXT,
                instrument TEXT,
                position_size REAL,
                venue TEXT,
                pnl_impact REAL,
                risk_impact REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_stress_experiments_table(self, cursor):
        """Create stress experiments table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stress_experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_name TEXT NOT NULL,
                experiment_date TEXT NOT NULL,
                duration_hours REAL,
                conditions TEXT,
                normal_triggers INTEGER,
                stress_triggers INTEGER,
                normal_alignment REAL,
                stress_alignment REAL,
                normal_impact REAL,
                stress_impact REAL,
                normal_latency REAL,
                stress_latency REAL,
                findings TEXT,
                conclusions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_system_metrics_table(self, cursor):
        """Create system performance metrics table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cpu_usage REAL,
                memory_usage REAL,
                network_usage REAL,
                storage_usage REAL,
                disk_io REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_reliability_metrics_table(self, cursor):
        """Create reliability metrics table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reliability_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                uptime_pct REAL,
                error_rate REAL,
                recovery_time_min REAL,
                data_quality_score REAL,
                availability_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_incidents_table(self, cursor):
        """Create incidents table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                duration_minutes INTEGER,
                impact TEXT,
                resolution TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
    def _create_indexes(self, cursor):
        """Create database indexes for performance."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_shadow_decisions_timestamp ON shadow_decisions(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_shadow_metrics_timestamp ON shadow_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_guardrail_triggers_timestamp ON guardrail_triggers(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_shadow_impact_timestamp ON shadow_impact(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_outlier_analysis_timestamp ON outlier_analysis(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp ON system_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_reliability_metrics_timestamp ON reliability_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(timestamp)"
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
            
    def populate_sample_data(self):
        """Populate with sample data for testing."""
        logger.info("Populating sample data for testing...")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Sample shadow decisions
        sample_decisions = [
            (datetime.now().isoformat(), 'allocation', 'ALLOCATE', 'ALLOCATE', 'pos_001', 'BTC/USD', 5000.0, 'Binance', 0.15, 1000.0, 0.02, 0.25, 'normal_volatility'),
            (datetime.now().isoformat(), 'guardrail', 'BLOCK', 'ALLOW', 'pos_002', 'ETH/USD', 8000.0, 'Coinbase', 0.25, 1500.0, 0.03, 0.40, 'high_volatility'),
            (datetime.now().isoformat(), 'limit', 'RESIZE', 'ALLOW', 'pos_003', 'BTC/USD', 3000.0, 'Kraken', 0.12, 800.0, 0.01, 0.12, 'normal_volatility'),
        ]
        
        for decision in sample_decisions:
            cursor.execute("""
                INSERT INTO shadow_decisions 
                (timestamp, decision_type, shadow_action, actual_action, position_id, instrument, position_size, venue, market_volatility, risk_var, risk_drawdown, risk_concentration, market_conditions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, decision)
        
        # Sample shadow metrics
        sample_metrics = [
            (datetime.now().isoformat(), 45.2, 85.7, 25.3, 65.4, 512.0, 95.2, 0.1, 0.05),
            (datetime.now().isoformat(), 42.8, 82.1, 23.1, 62.1, 498.0, 93.8, 0.05, 0.02),
        ]
        
        for metric in sample_metrics:
            cursor.execute("""
                INSERT INTO shadow_metrics 
                (timestamp, calculation_latency, decision_latency, contract_latency, cpu_usage, memory_usage, network_usage, storage_usage, error_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, metric)
        
        # Sample guardrail triggers
        sample_triggers = [
            (datetime.now().isoformat(), 'concentration', 'position_concentration > 40%', 12.5, 1, 0),
            (datetime.now().isoformat(), 'var', 'var_95 > threshold', 8.3, 1, 0),
            (datetime.now().isoformat(), 'drawdown', 'drawdown > 3%', 15.7, 1, 0),
        ]
        
        for trigger in sample_triggers:
            cursor.execute("""
                INSERT INTO guardrail_triggers 
                (timestamp, guardrail_type, trigger_conditions, response_time, is_correct, false_positive)
                VALUES (?, ?, ?, ?, ?, ?)
            """, trigger)
        
        conn.commit()
        conn.close()
        
        logger.info("Sample data populated successfully")

def main():
    """Main function to set up the database."""
    db = ShadowDatabaseSetup()
    db.setup_database()
    
    # Optionally populate with sample data for testing
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        db.populate_sample_data()
    
    print("Risk Shadow database setup completed!")
    print(f"Database location: {db.db_path}")
    print("Ready for shadow mode data collection")

if __name__ == "__main__":
    main()
