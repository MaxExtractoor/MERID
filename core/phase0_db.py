"""
MERID Phase 0 Database Schema

Thin persistence layer for Phase 0 experiment using existing Brier/governance database.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime

from core.brier_metrics_db import get_brier_db
from utils.logger import get_logger

logger = get_logger("phase0_db")

class Phase0DB:
    """
    Phase 0 database operations.
    
    Uses existing Brier/governance database with minimal new tables.
    """
    
    def __init__(self):
        self.db = get_brier_db()
    
    def initialize_phase0_tables(self) -> bool:
        """Initialize Phase 0 tables in the existing database."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                # Phase 0 experiment table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS phase0_experiment (
                        experiment_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL CHECK (status IN ('not_started', 'active', 'completed')),
                        start_at TIMESTAMP,
                        end_at TIMESTAMP,
                        constraints TEXT NOT NULL,  -- JSON
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Phase 0 expectations table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS phase0_expectations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        experiment_id TEXT NOT NULL,
                        model_id TEXT NOT NULL,
                        expected_manual_tier TEXT NOT NULL,
                        expected_manual_limits TEXT NOT NULL,  -- JSON
                        expected_binding_thresholds TEXT NOT NULL,  -- JSON
                        rationale TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (experiment_id) REFERENCES phase0_experiment(experiment_id)
                    )
                """)
                
                # Phase 0 weekly decisions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS phase0_weekly_decisions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        experiment_id TEXT NOT NULL,
                        week_number INTEGER NOT NULL,
                        model_id TEXT NOT NULL,
                        scorecard_snapshot TEXT NOT NULL,  -- JSON (GovernanceScorecard)
                        system_recommendation TEXT NOT NULL,
                        human_decision TEXT NOT NULL,
                        decision_reason TEXT NOT NULL,
                        contract_tests_passed BOOLEAN NOT NULL,
                        aligned BOOLEAN NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (experiment_id) REFERENCES phase0_experiment(experiment_id)
                    )
                """)
                
                # Phase 0 scorecard snapshots table (optional - for detailed history)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS phase0_scorecard_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        experiment_id TEXT NOT NULL,
                        week_number INTEGER NOT NULL,
                        model_id TEXT NOT NULL,
                        scorecard_json TEXT NOT NULL,  -- JSON (GovernanceScorecard)
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (experiment_id) REFERENCES phase0_experiment(experiment_id)
                    )
                """)
                
                # Indexes for performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase0_decisions_experiment ON phase0_weekly_decisions(experiment_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase0_decisions_model ON phase0_weekly_decisions(model_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase0_decisions_week ON phase0_weekly_decisions(week_number)")
                
                conn.commit()
                logger.info("Phase 0 tables initialized successfully")
                return True
                
        except Exception as e:
            logger.error(f"Failed to initialize Phase 0 tables: {e}")
            return False
    
    def store_experiment(self, experiment_data: Dict[str, Any]) -> bool:
        """Store experiment record."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO phase0_experiment
                    (experiment_id, status, start_at, end_at, constraints)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    experiment_data["experiment_id"],
                    experiment_data["status"],
                    experiment_data.get("start_at"),
                    experiment_data.get("end_at"),
                    experiment_data["constraints"]
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to store experiment: {e}")
            return False
    
    def get_active_experiment(self) -> Optional[Dict[str, Any]]:
        """Get active experiment."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT experiment_id, status, start_at, end_at, constraints, created_at
                    FROM phase0_experiment
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                
                row = cursor.fetchone()
                if row:
                    return {
                        "experiment_id": row[0],
                        "status": row[1],
                        "start_at": row[2],
                        "end_at": row[3],
                        "constraints": row[4],
                        "created_at": row[5]
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to get active experiment: {e}")
            return None
    
    def update_experiment_status(self, experiment_id: str, status: str, end_at: Optional[datetime] = None) -> bool:
        """Update experiment status."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                if end_at:
                    cursor.execute("""
                        UPDATE phase0_experiment
                        SET status = ?, end_at = ?
                        WHERE experiment_id = ?
                    """, (status, end_at, experiment_id))
                else:
                    cursor.execute("""
                        UPDATE phase0_experiment
                        SET status = ?
                        WHERE experiment_id = ?
                    """, (status, experiment_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to update experiment status: {e}")
            return False
    
    def store_expectation(self, expectation_data: Dict[str, Any]) -> bool:
        """Store pre-trial expectation."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO phase0_expectations
                    (experiment_id, model_id, expected_manual_tier, expected_manual_limits, 
                     expected_binding_thresholds, rationale)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    expectation_data["experiment_id"],
                    expectation_data["model_id"],
                    expectation_data["expected_manual_tier"],
                    expectation_data["expected_manual_limits"],
                    expectation_data["expected_binding_thresholds"],
                    expectation_data["rationale"]
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to store expectation: {e}")
            return False
    
    def get_expectations(self, experiment_id: str) -> List[Dict[str, Any]]:
        """Get expectations for experiment."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT model_id, expected_manual_tier, expected_manual_limits,
                           expected_binding_thresholds, rationale, created_at
                    FROM phase0_expectations
                    WHERE experiment_id = ?
                    ORDER BY model_id
                """, (experiment_id,))
                
                expectations = []
                for row in cursor.fetchall():
                    expectations.append({
                        "model_id": row[0],
                        "expected_manual_tier": row[1],
                        "expected_manual_limits": row[2],
                        "expected_binding_thresholds": row[3],
                        "rationale": row[4],
                        "created_at": row[5]
                    })
                
                return expectations
                
        except Exception as e:
            logger.error(f"Failed to get expectations: {e}")
            return []
    
    def store_weekly_decision(self, decision_data: Dict[str, Any]) -> bool:
        """Store weekly decision."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO phase0_weekly_decisions
                    (experiment_id, week_number, model_id, scorecard_snapshot,
                     system_recommendation, human_decision, decision_reason,
                     contract_tests_passed, aligned)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    decision_data["experiment_id"],
                    decision_data["week_number"],
                    decision_data["model_id"],
                    decision_data["scorecard_snapshot"],
                    decision_data["system_recommendation"],
                    decision_data["human_decision"],
                    decision_data["decision_reason"],
                    decision_data["contract_tests_passed"],
                    decision_data["aligned"]
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to store weekly decision: {e}")
            return False
    
    def get_weekly_decisions(self, experiment_id: str, week_number: Optional[int] = None, 
                           model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get weekly decisions with optional filters."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT week_number, model_id, scorecard_snapshot, system_recommendation,
                           human_decision, decision_reason, contract_tests_passed, aligned, created_at
                    FROM phase0_weekly_decisions
                    WHERE experiment_id = ?
                """
                params = [experiment_id]
                
                if week_number:
                    query += " AND week_number = ?"
                    params.append(week_number)
                
                if model_id:
                    query += " AND model_id = ?"
                    params.append(model_id)
                
                query += " ORDER BY week_number, model_id"
                
                cursor.execute(query, params)
                
                decisions = []
                for row in cursor.fetchall():
                    decisions.append({
                        "week_number": row[0],
                        "model_id": row[1],
                        "scorecard_snapshot": row[2],
                        "system_recommendation": row[3],
                        "human_decision": row[4],
                        "decision_reason": row[5],
                        "contract_tests_passed": row[6],
                        "aligned": row[7],
                        "created_at": row[8]
                    })
                
                return decisions
                
        except Exception as e:
            logger.error(f"Failed to get weekly decisions: {e}")
            return []
    
    def compute_metrics(self, experiment_id: str) -> Dict[str, Any]:
        """Compute experiment metrics from stored decisions."""
        try:
            decisions = self.get_weekly_decisions(experiment_id)
            
            if not decisions:
                return {
                    "decision_alignment_rate": 0.0,
                    "contract_test_compliance_rate": 0.0,
                    "total_decisions": 0
                }
            
            # Calculate alignment rate
            aligned_count = sum(1 for d in decisions if d["aligned"])
            decision_alignment_rate = aligned_count / len(decisions)
            
            # Calculate contract test compliance
            compliant_count = sum(1 for d in decisions if d["contract_tests_passed"])
            contract_test_compliance_rate = compliant_count / len(decisions)
            
            return {
                "decision_alignment_rate": decision_alignment_rate,
                "contract_test_compliance_rate": contract_test_compliance_rate,
                "total_decisions": len(decisions)
            }
            
        except Exception as e:
            logger.error(f"Failed to compute metrics: {e}")
            return {"error": str(e)}
    
    def store_scorecard_snapshot(self, experiment_id: str, week_number: int, 
                               model_id: str, scorecard_json: str) -> bool:
        """Store scorecard snapshot for detailed history."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO phase0_scorecard_snapshots
                    (experiment_id, week_number, model_id, scorecard_json)
                    VALUES (?, ?, ?, ?)
                """, (experiment_id, week_number, model_id, scorecard_json))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to store scorecard snapshot: {e}")
            return False
    
    def get_scorecard_history(self, experiment_id: str, model_id: str) -> List[Dict[str, Any]]:
        """Get scorecard history for a model."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT week_number, scorecard_json, created_at
                    FROM phase0_scorecard_snapshots
                    WHERE experiment_id = ? AND model_id = ?
                    ORDER BY week_number
                """, (experiment_id, model_id))
                
                history = []
                for row in cursor.fetchall():
                    history.append({
                        "week_number": row[0],
                        "scorecard_json": row[1],
                        "created_at": row[2]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"Failed to get scorecard history: {e}")
            return []

# Global Phase 0 DB instance
_phase0_db = Phase0DB()

def get_phase0_db() -> Phase0DB:
    """Get the global Phase 0 DB instance."""
    return _phase0_db
