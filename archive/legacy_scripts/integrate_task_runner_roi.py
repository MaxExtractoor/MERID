#!/usr/bin/env python3
"""
Task Runner ROI Integration
Auto-log completed tasks to per_task_roi_log table
"""

import sys
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.task_runner_roi")

class TaskRunnerROIIntegration:
    """Integration for auto-logging completed tasks to ROI database"""
    
    def __init__(self, db_path: str = "per_task_roi.db"):
        self.db_path = db_path
        self.schema_path = Path("per_task_roi_schema.json")
        self.sql_schema_path = Path("per_task_roi_schema.sql")
        self._ensure_database()
    
    def _ensure_database(self):
        """Ensure database and schema exist"""
        if not Path(self.db_path).exists():
            self._create_database()
    
    def _create_database(self):
        """Create database with ROI schema"""
        logger.info("Creating ROI database with schema")
        
        # Load SQL schema
        if self.sql_schema_path.exists():
            with self.sql_schema_path.open('r') as f:
                schema_sql = f.read()
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Execute schema
            cursor.executescript(schema_sql)
            conn.commit()
            conn.close()
            
            logger.info(f"ROI database created at {self.db_path}")
        else:
            raise FileNotFoundError(f"Schema file not found: {self.sql_schema_path}")
    
    def log_task_completion(self, task_config: Dict[str, Any], 
                          execution_metrics: Dict[str, Any],
                          roi_calculations: Dict[str, Any],
                          context: Optional[Dict[str, Any]] = None) -> str:
        """
        Log a completed task to the ROI database
        
        Args:
            task_config: Task configuration (type, module, risk, complexity)
            execution_metrics: Execution results (success, time, agents, tools, SLOs)
            roi_calculations: ROI calculations (hours saved, costs, scores)
            context: Additional context (experiment_id, batch_id, run_id)
        
        Returns:
            task_id: Unique identifier for the logged task
        """
        # Generate task ID
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        task_type = task_config.get("type", "unknown")
        module = task_config.get("module", "unknown").replace("/", "_")
        task_id = f"{task_type}_{module}_{timestamp}_{execution_metrics.get('run_number', 1)}"
        
        # Build ROI row
        roi_row = {
            # Task identification
            "task_id": task_id,
            "date": datetime.now().isoformat(),
            "task_type": task_type,
            "module": task_config.get("module"),
            "risk_level": task_config.get("risk_level", "medium"),
            "complexity": task_config.get("complexity", "medium"),
            
            # Execution metrics
            "success": execution_metrics.get("success", False),
            "execution_time_seconds": execution_metrics.get("execution_time_seconds", 0.0),
            "swarm_topology": execution_metrics.get("swarm_topology", "current_mesh"),
            "agent_count": execution_metrics.get("agent_count", 0),
            "tool_count": execution_metrics.get("tool_count", 0),
            "enforcement_mode": execution_metrics.get("enforcement_mode", "log_only"),
            
            # Cost metrics
            "human_baseline_hours": roi_calculations.get("human_baseline_hours", 0.0),
            "human_time_saved_hours": roi_calculations.get("human_time_saved_hours", 0.0),
            "token_cost": roi_calculations.get("token_cost", 0.0),
            "infra_cost_usd": roi_calculations.get("infra_cost_usd", 0.0),
            "cost_savings_usd": roi_calculations.get("cost_savings_usd", 0.0),
            
            # Quality metrics
            "quality_improvement": roi_calculations.get("quality_improvement", 0.0),
            "defects_found": roi_calculations.get("defects_found", 0),
            "defects_avoided": roi_calculations.get("defects_avoided", 0),
            "human_review_friction": roi_calculations.get("human_review_friction", 0.0),
            "slo_compliance": execution_metrics.get("slo_compliance", "green"),
            "slo_violations": json.dumps(execution_metrics.get("slo_violations", [])),
            
            # Business impact
            "business_value": roi_calculations.get("business_value", "medium"),
            "impact_score": roi_calculations.get("impact_score", 50.0),
            "roi_score": roi_calculations.get("roi_score", 50.0),
            "revenue_impact_usd": roi_calculations.get("revenue_impact_usd", 0.0),
            "risk_reduction_usd": roi_calculations.get("risk_reduction_usd", 0.0),
            
            # Governance
            "experiment_id": context.get("experiment_id") if context else None,
            "batch_id": context.get("batch_id") if context else None,
            "run_id": context.get("run_id", f"run_{datetime.now().strftime('%Y_%m_%d')}_{execution_metrics.get('run_number', 1)}"),
            "human_verified": roi_calculations.get("human_verified", False),
            "evidence_links": json.dumps(roi_calculations.get("evidence_links", [])),
            "notes": roi_calculations.get("notes", ""),
            
            # Incident tracking
            "incidents": execution_metrics.get("incidents", 0),
            "near_misses": execution_metrics.get("near_misses", 0),
            "rollback_required": execution_metrics.get("rollback_required", False),
            "rollback_time_hours": execution_metrics.get("rollback_time_hours", 0.0)
        }
        
        # Validate required fields
        self._validate_roi_row(roi_row)
        
        # Insert into database
        self._insert_roi_row(roi_row)
        
        logger.info(f"Task logged to ROI database: {task_id}")
        return task_id
    
    def _validate_roi_row(self, roi_row: Dict[str, Any]):
        """Validate ROI row has all required fields"""
        required_fields = [
            "task_id", "date", "task_type", "risk_level", "success",
            "execution_time_seconds", "swarm_topology", "agent_count", "tool_count",
            "enforcement_mode", "human_baseline_hours", "human_time_saved_hours",
            "cost_savings_usd", "quality_improvement", "defects_found",
            "defects_avoided", "human_review_friction", "slo_compliance",
            "slo_violations", "business_value", "impact_score", "roi_score",
            "run_id", "human_verified", "incidents", "near_misses", "rollback_required"
        ]
        
        missing_fields = [field for field in required_fields if field not in roi_row or roi_row[field] is None]
        
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        # Validate constraints
        if roi_row["human_time_saved_hours"] < 0:
            raise ValueError("human_time_saved_hours must be >= 0")
        
        if not (-1 <= roi_row["quality_improvement"] <= 1):
            raise ValueError("quality_improvement must be between -1 and 1")
        
        if not (0 <= roi_row["impact_score"] <= 100):
            raise ValueError("impact_score must be between 0 and 100")
        
        if not (0 <= roi_row["roi_score"] <= 100):
            raise ValueError("roi_score must be between 0 and 100")
    
    def _insert_roi_row(self, roi_row: Dict[str, Any]):
        """Insert ROI row into database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build INSERT statement
        columns = list(roi_row.keys())
        placeholders = ["?" for _ in columns]
        values = list(roi_row.values())
        
        sql = f"""
            INSERT INTO per_task_roi_log ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
        """
        
        try:
            cursor.execute(sql, values)
            conn.commit()
            logger.debug(f"ROI row inserted: {roi_row['task_id']}")
        except sqlite3.IntegrityError as e:
            logger.error(f"Integrity error inserting ROI row: {e}")
            raise
        except sqlite3.Error as e:
            logger.error(f"Database error inserting ROI row: {e}")
            raise
        finally:
            conn.close()
    
    def get_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get summary for a specific task"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM per_task_roi_log WHERE task_id = ?
        """, (task_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, row))
        
        return None
    
    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent tasks"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM per_task_roi_log 
            ORDER BY date DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        conn.close()
        
        return [dict(zip(columns, row)) for row in rows]

# Integration wrapper for task runner
def log_task_completion(task_config: Dict[str, Any], 
                      execution_metrics: Dict[str, Any],
                      roi_calculations: Dict[str, Any],
                      context: Optional[Dict[str, Any]] = None) -> str:
    """
    Convenience function for task runner to log completion
    
    Args:
        task_config: Task configuration
        execution_metrics: Execution results
        roi_calculations: ROI calculations
        context: Additional context
    
    Returns:
        task_id: Unique identifier for the logged task
    """
    integration = TaskRunnerROIIntegration()
    return integration.log_task_completion(
        task_config, execution_metrics, roi_calculations, context
    )

# Example usage
def example_usage():
    """Example of how to use the integration"""
    
    # Task configuration
    task_config = {
        "type": "test_expansion",
        "module": "swarm/quality",
        "risk_level": "low",
        "complexity": "medium"
    }
    
    # Execution metrics (from task runner)
    execution_metrics = {
        "success": True,
        "execution_time_seconds": 600.0,
        "swarm_topology": "current_mesh",
        "agent_count": 3,
        "tool_count": 8,
        "enforcement_mode": "log_only",
        "slo_compliance": "green",
        "slo_violations": [],
        "incidents": 0,
        "near_misses": 0,
        "rollback_required": False,
        "rollback_time_hours": 0.0,
        "run_number": 1
    }
    
    # ROI calculations (from ROI tracker)
    roi_calculations = {
        "human_baseline_hours": 2.5,
        "human_time_saved_hours": 2.33,
        "token_cost": 15000.0,
        "infra_cost_usd": 0.05,
        "cost_savings_usd": 233.0,
        "quality_improvement": 0.93,
        "defects_found": 2,
        "defects_avoided": 2,
        "human_review_friction": 0.1,
        "business_value": "high",
        "impact_score": 85.0,
        "roi_score": 99.0,
        "revenue_impact_usd": 0.0,
        "risk_reduction_usd": 500.0,
        "human_verified": True,
        "evidence_links": ["dashboard_url", "diff_url"],
        "notes": "Standard test expansion task for quality module"
    }
    
    # Context
    context = {
        "experiment_id": None,
        "batch_id": "week6_batch_1",
        "run_id": "run_2025_01_25_001"
    }
    
    # Log the task
    task_id = log_task_completion(task_config, execution_metrics, roi_calculations, context)
    print(f"Task logged: {task_id}")
    
    # Get recent tasks
    recent = TaskRunnerROIIntegration().get_recent_tasks(5)
    print(f"Recent tasks: {len(recent)}")

if __name__ == "__main__":
    example_usage()
