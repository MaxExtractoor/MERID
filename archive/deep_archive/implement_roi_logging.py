#!/usr/bin/env python3
"""
Per-Task ROI Logging Implementation
Non-optional logging for every swarm-handled task
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.roi_logger")

class PerTaskROILogger:
    """Non-optional per-task ROI logging system"""
    
    def __init__(self, db_path: str = "per_task_roi.db"):
        self.db_path = db_path
        self._init_database()
        
    def _init_database(self):
        """Initialize SQLite database with ROI table"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create ROI table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS per_task_roi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                date TEXT NOT NULL,
                task_type TEXT NOT NULL,
                module TEXT,
                risk_level TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                execution_time_seconds REAL NOT NULL,
                human_time_saved_hours REAL NOT NULL,
                defects_found INTEGER DEFAULT 0,
                defects_avoided INTEGER DEFAULT 0,
                human_review_friction REAL DEFAULT 0.0,
                quality_improvement REAL DEFAULT 0.0,
                swarm_topology TEXT NOT NULL,
                agent_count INTEGER NOT NULL,
                tool_count INTEGER NOT NULL,
                enforcement_mode TEXT NOT NULL,
                roi_score REAL NOT NULL,
                cost_savings_usd REAL NOT NULL,
                business_value TEXT NOT NULL,
                incidents INTEGER DEFAULT 0,
                near_misses INTEGER DEFAULT 0,
                rollback_required BOOLEAN DEFAULT FALSE,
                experiment_id TEXT,
                batch_id TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON per_task_roi(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON per_task_roi(task_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_module ON per_task_roi(module)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_level ON per_task_roi(risk_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_swarm_topology ON per_task_roi(swarm_topology)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_experiment_id ON per_task_roi(experiment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_id ON per_task_roi(batch_id)")
        
        conn.commit()
        conn.close()
        
        logger.info(f"ROI database initialized at {self.db_path}")
    
    def log_task(self, task_data: Dict[str, Any]) -> str:
        """Log a completed task (non-optional)"""
        # Validate required fields
        required_fields = [
            'task_id', 'task_type', 'risk_level', 'success',
            'execution_time_seconds', 'human_time_saved_hours',
            'swarm_topology', 'agent_count', 'tool_count',
            'enforcement_mode', 'roi_score', 'cost_savings_usd', 'business_value'
        ]
        
        missing_fields = [field for field in required_fields if field not in task_data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        # Set defaults for optional fields
        defaults = {
            'module': None,
            'defects_found': 0,
            'defects_avoided': 0,
            'human_review_friction': 0.0,
            'quality_improvement': 0.0,
            'incidents': 0,
            'near_misses': 0,
            'rollback_required': False,
            'experiment_id': None,
            'batch_id': None,
            'notes': ''
        }
        
        # Merge with defaults
        log_data = {**defaults, **task_data}
        
        # Add date if not provided
        if 'date' not in log_data:
            log_data['date'] = datetime.now().isoformat()
        
        # Insert into database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO per_task_roi (
                task_id, date, task_type, module, risk_level, success,
                execution_time_seconds, human_time_saved_hours,
                defects_found, defects_avoided, human_review_friction,
                quality_improvement, swarm_topology, agent_count, tool_count,
                enforcement_mode, roi_score, cost_savings_usd, business_value,
                incidents, near_misses, rollback_required,
                experiment_id, batch_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_data['task_id'], log_data['date'], log_data['task_type'], log_data['module'],
            log_data['risk_level'], log_data['success'], log_data['execution_time_seconds'],
            log_data['human_time_saved_hours'], log_data['defects_found'], log_data['defects_avoided'],
            log_data['human_review_friction'], log_data['quality_improvement'], log_data['swarm_topology'],
            log_data['agent_count'], log_data['tool_count'], log_data['enforcement_mode'],
            log_data['roi_score'], log_data['cost_savings_usd'], log_data['business_value'],
            log_data['incidents'], log_data['near_misses'], log_data['rollback_required'],
            log_data['experiment_id'], log_data['batch_id'], log_data['notes']
        ))
        
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Task logged: {log_data['task_id']} (ID: {row_id})")
        return str(row_id)
    
    def get_weekly_summary(self, weeks_back: int = 1) -> Dict[str, Any]:
        """Get weekly summary for checkpoint review"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Calculate date range
        start_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - 
                      timedelta(weeks=weeks_back))
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_tasks,
                SUM(human_time_saved_hours) as total_time_saved,
                AVG(roi_score) as avg_roi_score,
                AVG(quality_improvement) as avg_quality_improvement,
                SUM(cost_savings_usd) as total_cost_savings,
                SUM(defects_avoided) as total_defects_avoided,
                SUM(incidents) as total_incidents,
                SUM(near_misses) as total_near_misses
            FROM per_task_roi
            WHERE date >= ?
        """, (start_date.isoformat(),))
        
        result = cursor.fetchone()
        
        conn.close()
        
        if result and result[0] > 0:
            return {
                'period': f'{weeks_back} weeks',
                'start_date': start_date.isoformat(),
                'total_tasks': result[0],
                'successful_tasks': result[1],
                'success_rate': result[1] / result[0],
                'total_time_saved_hours': result[2] or 0,
                'avg_roi_score': result[3] or 0,
                'avg_quality_improvement': result[4] or 0,
                'total_cost_savings_usd': result[5] or 0,
                'total_defects_avoided': result[6] or 0,
                'total_incidents': result[7] or 0,
                'total_near_misses': result[8] or 0
            }
        else:
            return {
                'period': f'{weeks_back} weeks',
                'start_date': start_date.isoformat(),
                'total_tasks': 0,
                'successful_tasks': 0,
                'success_rate': 0,
                'total_time_saved_hours': 0,
                'avg_roi_score': 0,
                'avg_quality_improvement': 0,
                'total_cost_savings_usd': 0,
                'total_defects_avoided': 0,
                'total_incidents': 0,
                'total_near_misses': 0
            }
    
    def get_task_type_breakdown(self, weeks_back: int = 1) -> Dict[str, Any]:
        """Get breakdown by task type"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - 
                      timedelta(weeks=weeks_back))
        
        cursor.execute("""
            SELECT 
                task_type,
                COUNT(*) as task_count,
                SUM(human_time_saved_hours) as total_time_saved,
                AVG(roi_score) as avg_roi_score,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                AVG(quality_improvement) as avg_quality_improvement
            FROM per_task_roi
            WHERE date >= ?
            GROUP BY task_type
            ORDER BY avg_roi_score DESC
        """, (start_date.isoformat(),))
        
        results = cursor.fetchall()
        
        conn.close()
        
        return {
            'period': f'{weeks_back} weeks',
            'task_types': [
                {
                    'task_type': row[0],
                    'task_count': row[1],
                    'total_time_saved': row[2],
                    'avg_roi_score': row[3],
                    'success_rate': row[4],
                    'avg_quality_improvement': row[5]
                }
                for row in results
            ]
        }
    
    def get_risk_level_breakdown(self, weeks_back: int = 1) -> Dict[str, Any]:
        """Get breakdown by risk level"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - 
                      timedelta(weeks=weeks_back))
        
        cursor.execute("""
            SELECT 
                risk_level,
                COUNT(*) as task_count,
                SUM(human_time_saved_hours) as total_time_saved,
                AVG(roi_score) as avg_roi_score,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                SUM(incidents) as total_incidents,
                SUM(near_misses) as total_near_misses
            FROM per_task_roi
            WHERE date >= ?
            GROUP BY risk_level
            ORDER BY avg_roi_score DESC
        """, (start_date.isoformat(),))
        
        results = cursor.fetchall()
        
        conn.close()
        
        return {
            'period': f'{weeks_back} weeks',
            'risk_levels': [
                {
                    'risk_level': row[0],
                    'task_count': row[1],
                    'total_time_saved': row[2],
                    'avg_roi_score': row[3],
                    'success_rate': row[4],
                    'incidents': row[5],
                    'near_misses': row[6]
                }
                for row in results
            ]
        }
    
    def get_topology_performance(self, weeks_back: int = 1) -> Dict[str, Any]:
        """Get performance by topology"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - 
                      timedelta(weeks=weeks_back))
        
        cursor.execute("""
            SELECT 
                swarm_topology,
                COUNT(*) as task_count,
                SUM(human_time_saved_hours) as total_time_saved,
                AVG(roi_score) as avg_roi_score,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                AVG(quality_improvement) as avg_quality_improvement
            FROM per_task_roi
            WHERE date >= ?
            GROUP BY swarm_topology
            ORDER BY avg_roi_score DESC
        """, (start_date.isoformat(),))
        
        results = cursor.fetchall()
        
        conn.close()
        
        return {
            'period': f'{weeks_back} weeks',
            'topologies': [
                {
                    'topology': row[0],
                    'task_count': row[1],
                    'total_time_saved': row[2],
                    'avg_roi_score': row[3],
                    'success_rate': row[4],
                    'avg_quality_improvement': row[5]
                }
                for row in results
            ]
        }
    
    def get_sql_examples(self) -> list:
        """Get SQL query examples for analysis"""
        return [
            "-- Total ROI by task type (last 4 weeks)",
            "SELECT task_type, COUNT(*) as task_count, AVG(roi_score) as avg_roi, SUM(cost_savings_usd) as total_savings",
            "FROM per_task_roi",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY task_type",
            "ORDER BY avg_roi DESC;",
            "",
            "-- Success rate by risk level (last 4 weeks)",
            "SELECT risk_level, COUNT(*) as task_count, AVG(roi_score) as avg_roi,",
            "       COUNT(*) FILTER (WHERE success = 1) * 100.0 / COUNT(*) as success_rate",
            "FROM per_task_roi",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY risk_level",
            "ORDER BY avg_roi DESC;",
            "",
            "-- Weekly time saved trend (last 8 weeks)",
            "SELECT DATE(date) as week, SUM(human_time_saved_hours) as weekly_time_saved,",
            "       AVG(roi_score) as avg_roi, COUNT(*) as task_count",
            "FROM per_task_roi",
            "WHERE date >= date('now', '-8 weeks')",
            "GROUP BY DATE(date)",
            "ORDER BY week;",
            "",
            "-- Top performing configurations (last 4 weeks)",
            "SELECT swarm_topology, enforcement_mode, AVG(roi_score) as avg_roi,",
            "       AVG(quality_improvement) as avg_quality, COUNT(*) as task_count",
            "FROM per_task_roi",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY swarm_topology, enforcement_mode",
            "HAVING COUNT(*) >= 3",
            "ORDER BY avg_roi DESC;",
            "",
            "-- Incident and near-miss tracking (last 12 weeks)",
            "SELECT DATE(date) as week, SUM(incidents) as incidents, SUM(near_misses) as near_misses,",
            "       COUNT(*) FILTER (WHERE rollback_required = 1) as rollbacks",
            "FROM per_task_roi",
            "WHERE date >= date('now', '-12 weeks')",
            "GROUP BY DATE(date)",
            "ORDER BY week;"
        ]


# Global ROI logger instance
roi_logger = PerTaskROILogger()


def log_swarm_task(task_id: str, task_config: Dict[str, Any], 
                   swarm_metrics: Dict[str, Any], 
                   human_baseline_hours: float) -> str:
    """Log a swarm task (non-optional)"""
    
    # Calculate cost savings ($100/hour assumption)
    cost_savings = human_baseline_hours * 100.0
    
    # Determine business value based on task type and risk
    task_type = task_config.get("type", "unknown")
    risk_level = task_config.get("risk_level", "medium")
    
    if task_type == "testing":
        business_value = "high" if risk_level in ["low", "medium"] else "medium"
    elif task_type == "configuration":
        business_value = "medium" if risk_level == "low" else "low"
    elif task_type == "documentation":
        business_value = "medium"
    else:
        business_value = "medium"
    
    # Log the task
    log_data = {
        "task_id": task_id,
        "task_type": task_type,
        "module": task_config.get("module"),
        "risk_level": risk_level,
        "success": swarm_metrics.get("success", False),
        "execution_time_seconds": swarm_metrics.get("execution_time", 0),
        "human_time_saved_hours": human_baseline_hours - (swarm_metrics.get("execution_time", 0) / 3600),
        "defects_avoided": swarm_metrics.get("defects_avoided", 0),
        "human_review_friction": swarm_metrics.get("human_review_friction", 0.0),
        "quality_improvement": swarm_metrics.get("quality_improvement", 0.0),
        "swarm_topology": swarm_metrics.get("topology", "current_mesh"),
        "agent_count": len(task_config.get("agents", [])),
        "tool_count": sum(len(agent.get("tools", [])) for agent in task_config.get("agents", [])),
        "enforcement_mode": swarm_metrics.get("enforcement_mode", "log_only"),
        "roi_score": swarm_metrics.get("roi_score", 0.0),
        "cost_savings_usd": cost_savings,
        "business_value": business_value,
        "incidents": swarm_metrics.get("incidents", 0),
        "near_misses": swarm_metrics.get("near_misses", 0),
        "rollback_required": swarm_metrics.get("rollback_required", False),
        "experiment_id": swarm_metrics.get("experiment_id"),
        "batch_id": swarm_metrics.get("batch_id"),
        "notes": swarm_metrics.get("notes", "")
    }
    
    return roi_logger.log_task(log_data)


if __name__ == "__main__":
    # Test the logging system
    print("=" * 60)
    print("PER-TASK ROI LOGGING SYSTEM")
    print("=" * 60)
    print("Non-optional logging for every swarm task")
    print()
    
    # Test logging a task
    test_task = {
        "task_id": "test_expansion_quality_1",
        "type": "testing",
        "module": "swarm/quality",
        "risk_level": "medium",
        "agents": [
            {"id": "planner", "tools": ["code_analyzer", "test_planner"]},
            {"id": "implementer", "tools": ["test_generator", "mock_builder"]},
            {"id": "reviewer", "tools": ["test_validator", "quality_checker"]}
        ]
    }
    
    test_metrics = {
        "success": True,
        "execution_time": 600,
        "roi_score": 99.0,
        "quality_improvement": 0.93,
        "defects_avoided": 2,
        "topology": "current_mesh",
        "enforcement_mode": "log_only"
    }
    
    row_id = log_swarm_task("test_expansion_quality_1", test_task, test_metrics, 2.5)
    print(f"✅ Test task logged (ID: {row_id})")
    
    # Test queries
    print()
    print("WEEKLY SUMMARY:")
    print("-" * 30)
    summary = roi_logger.get_weekly_summary(1)
    if summary["total_tasks"] > 0:
        print(f"Tasks: {summary['total_tasks']}")
        print(f"Success Rate: {summary['success_rate']:.1%}")
        print(f"Time Saved: {summary['total_time_saved_hours']:.1f}h")
        print(f"Avg ROI: {summary['avg_roi_score']:.1f}/100")
    else:
        print("No tasks in this period")
    
    print()
    print("SQL EXAMPLES:")
    print("-" * 30)
    for query in roi_logger.get_sql_examples()[:3]:  # Show first 3 examples
        print(query)
        print()
    
    print("✅ ROI logging system ready")
    print("Database: per_task_roi.db")
    print("All swarm tasks will be logged automatically")
