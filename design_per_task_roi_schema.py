#!/usr/bin/env python3
"""
Per-Task ROI Schema Design
Structured logging for swarm task ROI tracking
"""

import sys
import json
from datetime import datetime
from typing import Dict, Any, List

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.roi_schema")

def design_per_task_roi_schema():
    """Design and document the per-task ROI schema"""
    print("=" * 70)
    print("PER-TASK ROI SCHEMA DESIGN")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Purpose: Structured logging for swarm task ROI tracking")
    print()
    
    print("SCHEMA DESIGN PRINCIPLES:")
    print("-" * 50)
    print("1. One row per completed swarm task")
    print("2. All fields required for complete analysis")
    print("3. Aggregates cleanly to weekly/quarter views")
    print("4. Links to evidence and governance")
    print("5. Supports both automated and human-verified data")
    print()
    
    # Core schema definition
    schema = {
        "table_name": "per_task_roi_log",
        "description": "One row per completed swarm task with full ROI and impact data",
        "primary_key": "task_id",
        
        "fields": {
            # Task identification
            "task_id": {
                "type": "TEXT",
                "required": True,
                "description": "Unique identifier for the task",
                "example": "test_expansion_quality_2_2025-01-25_001"
            },
            "date": {
                "type": "TEXT",
                "required": True,
                "description": "ISO date when task was completed",
                "example": "2025-01-25T16:50:43"
            },
            "task_type": {
                "type": "TEXT",
                "required": True,
                "description": "Type of task performed",
                "enum": ["test_expansion", "config_refactor", "documentation", "safety_check", "experiment", "other"],
                "example": "test_expansion"
            },
            "module": {
                "type": "TEXT",
                "required": False,
                "description": "Module or component affected",
                "example": "swarm/quality"
            },
            "risk_level": {
                "type": "TEXT",
                "required": True,
                "description": "Risk level of the task",
                "enum": ["low", "medium", "high", "critical"],
                "example": "low"
            },
            "complexity": {
                "type": "TEXT",
                "required": False,
                "description": "Task complexity level",
                "enum": ["low", "medium", "high", "variable"],
                "example": "medium"
            },
            
            # Execution metrics
            "success": {
                "type": "BOOLEAN",
                "required": True,
                "description": "Whether the task completed successfully",
                "example": True
            },
            "execution_time_seconds": {
                "type": "REAL",
                "required": True,
                "description": "Total execution time in seconds",
                "example": 600.0
            },
            "swarm_topology": {
                "type": "TEXT",
                "required": True,
                "description": "Swarm topology used",
                "enum": ["current_mesh", "shallow_hierarchy", "star", "ring", "experimental"],
                "example": "current_mesh"
            },
            "agent_count": {
                "type": "INTEGER",
                "required": True,
                "description": "Number of agents in the swarm",
                "example": 3
            },
            "tool_count": {
                "type": "INTEGER",
                "required": True,
                "description": "Total tools used across all agents",
                "example": 8
            },
            "enforcement_mode": {
                "type": "TEXT",
                "required": True,
                "description": "Watchdog enforcement mode",
                "enum": ["log_only", "warn", "block"],
                "example": "log_only"
            },
            
            # Cost metrics
            "human_baseline_hours": {
                "type": "REAL",
                "required": True,
                "description": "Estimated human time to complete task",
                "example": 2.5
            },
            "human_time_saved_hours": {
                "type": "REAL",
                "required": True,
                "description": "Human hours saved by swarm execution",
                "example": 2.33
            },
            "token_cost": {
                "type": "REAL",
                "required": False,
                "description": "Total tokens consumed",
                "example": 15000.0
            },
            "infra_cost_usd": {
                "type": "REAL",
                "required": False,
                "description": "Infrastructure cost in USD",
                "example": 0.05
            },
            "cost_savings_usd": {
                "type": "REAL",
                "required": True,
                "description": "Total cost savings in USD ($100/hour)",
                "example": 233.0
            },
            
            # Quality and SLO metrics
            "quality_improvement": {
                "type": "REAL",
                "required": True,
                "description": "Quality improvement score (-1 to 1)",
                "example": 0.93
            },
            "defects_found": {
                "type": "INTEGER",
                "required": True,
                "description": "Number of defects found/avoided",
                "example": 2
            },
            "defects_avoided": {
                "type": "INTEGER",
                "required": True,
                "description": "Number of defects avoided",
                "example": 2
            },
            "human_review_friction": {
                "type": "REAL",
                "required": True,
                "description": "Human review effort required (0-1 scale)",
                "example": 0.1
            },
            "slo_compliance": {
                "type": "TEXT",
                "required": True,
                "description": "SLO compliance status",
                "enum": ["green", "yellow", "red"],
                "example": "green"
            },
            "slo_violations": {
                "type": "TEXT",
                "required": True,
                "description": "JSON array of SLO violations",
                "example": '[]'
            },
            
            # Business impact
            "business_value": {
                "type": "TEXT",
                "required": True,
                "description": "Business value category",
                "enum": ["high", "medium", "low", "experimental"],
                "example": "high"
            },
            "impact_score": {
                "type": "REAL",
                "required": True,
                "description": "Business impact score (0-100)",
                "example": 85.0
            },
            "roi_score": {
                "type": "REAL",
                "required": True,
                "description": "Overall ROI score (0-100)",
                "example": 99.0
            },
            "revenue_impact_usd": {
                "type": "REAL",
                "required": False,
                "description": "Direct revenue impact in USD",
                "example": 0.0
            },
            "risk_reduction_usd": {
                "type": "REAL",
                "required": False,
                "description": "Risk reduction value in USD",
                "example": 500.0
            },
            
            # Governance and evidence
            "experiment_id": {
                "type": "TEXT",
                "required": False,
                "description": "Experiment ID if part of experiment",
                "example": "topology_exp_001"
            },
            "batch_id": {
                "type": "TEXT",
                "required": False,
                "description": "Batch ID for grouped tasks",
                "example": "week6_batch_1"
            },
            "run_id": {
                "type": "TEXT",
                "required": True,
                "description": "Unique run identifier",
                "example": "run_2025_01_25_001"
            },
            "human_verified": {
                "type": "BOOLEAN",
                "required": True,
                "description": "Whether results were human-verified",
                "example": True
            },
            "evidence_links": {
                "type": "TEXT",
                "required": False,
                "description": "JSON array of evidence links",
                "example": '["dashboard_url", "diff_url"]'
            },
            "notes": {
                "type": "TEXT",
                "required": False,
                "description": "Additional notes or observations",
                "example": "Standard test expansion task"
            },
            
            # Incident tracking
            "incidents": {
                "type": "INTEGER",
                "required": True,
                "description": "Number of incidents caused",
                "example": 0
            },
            "near_misses": {
                "type": "INTEGER",
                "required": True,
                "description": "Number of near-misses",
                "example": 0
            },
            "rollback_required": {
                "type": "BOOLEAN",
                "required": True,
                "description": "Whether rollback was required",
                "example": False
            },
            "rollback_time_hours": {
                "type": "REAL",
                "required": False,
                "description": "Time spent on rollback if required",
                "example": 0.0
            }
        },
        
        "indexes": [
            "CREATE INDEX idx_date ON per_task_roi_log(date)",
            "CREATE INDEX idx_task_type ON per_task_roi_log(task_type)",
            "CREATE INDEX idx_module ON per_task_roi_log(module)",
            "CREATE INDEX idx_risk_level ON per_task_roi_log(risk_level)",
            "CREATE INDEX idx_success ON per_task_roi_log(success)",
            "CREATE INDEX idx_experiment_id ON per_task_roi_log(experiment_id)",
            "CREATE INDEX idx_batch_id ON per_task_roi_log(batch_id)",
            "CREATE INDEX idx_run_id ON per_task_roi_log(run_id)",
            "CREATE INDEX idx_business_value ON per_task_roi_log(business_value)",
            "CREATE INDEX idx_slo_compliance ON per_task_roi_log(slo_compliance)"
        ],
        
        "constraints": [
            "PRIMARY KEY (task_id)",
            "CHECK (human_time_saved_hours >= 0)",
            "CHECK (quality_improvement >= -1 AND quality_improvement <= 1)",
            "CHECK (defects_found >= 0)",
            "CHECK (defects_avoided >= 0)",
            "CHECK (human_review_friction >= 0 AND human_review_friction <= 1)",
            "CHECK (impact_score >= 0 AND impact_score <= 100)",
            "CHECK (roi_score >= 0 AND roi_score <= 100)",
            "CHECK (incidents >= 0)",
            "CHECK (near_misses >= 0)",
            "CHECK (rollback_time_hours >= 0)"
        ]
    }
    
    print("CORE SCHEMA:")
    print("-" * 50)
    print(f"Table: {schema['table_name']}")
    print(f"Primary Key: {schema['primary_key']}")
    print(f"Total Fields: {len(schema['fields'])}")
    print()
    
    # Group fields by category
    field_groups = {
        "Identification": ["task_id", "date", "task_type", "module", "risk_level", "complexity"],
        "Execution": ["success", "execution_time_seconds", "swarm_topology", "agent_count", "tool_count", "enforcement_mode"],
        "Cost": ["human_baseline_hours", "human_time_saved_hours", "token_cost", "infra_cost_usd", "cost_savings_usd"],
        "Quality": ["quality_improvement", "defects_found", "defects_avoided", "human_review_friction", "slo_compliance", "slo_violations"],
        "Business": ["business_value", "impact_score", "roi_score", "revenue_impact_usd", "risk_reduction_usd"],
        "Governance": ["experiment_id", "batch_id", "run_id", "human_verified", "evidence_links", "notes"],
        "Incidents": ["incidents", "near_misses", "rollback_required", "rollback_time_hours"]
    }
    
    for group, fields in field_groups.items():
        print(f"{group}:")
        for field in fields:
            field_info = schema["fields"][field]
            print(f"  • {field}: {field_info['type']} - {field_info['description']}")
        print()
    
    print("AGGREGATION EXAMPLES:")
    print("-" * 50)
    
    aggregation_examples = [
        {
            "name": "Weekly Summary",
            "sql": """
                SELECT 
                    DATE(date) as week,
                    COUNT(*) as task_count,
                    SUM(human_time_saved_hours) as total_hours_saved,
                    AVG(roi_score) as avg_roi,
                    AVG(quality_improvement) as avg_quality,
                    SUM(cost_savings_usd) as total_cost_savings,
                    COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate
                FROM per_task_roi_log
                WHERE date >= date('now', '-7 days')
                GROUP BY DATE(date)
                ORDER BY week DESC
            """,
            "description": "Weekly overview of swarm performance"
        },
        {
            "name": "Task Type Performance",
            "sql": """
                SELECT 
                    task_type,
                    COUNT(*) as task_count,
                    AVG(human_time_saved_hours) as avg_hours_saved,
                    AVG(roi_score) as avg_roi,
                    AVG(quality_improvement) as avg_quality,
                    SUM(cost_savings_usd) as total_savings,
                    COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate
                FROM per_task_roi_log
                WHERE date >= date('now', '-30 days')
                GROUP BY task_type
                ORDER BY avg_roi DESC
            """,
            "description": "Performance by task type"
        },
        {
            "name": "Risk Level Analysis",
            "sql": """
                SELECT 
                    risk_level,
                    COUNT(*) as task_count,
                    AVG(human_time_saved_hours) as avg_hours_saved,
                    SUM(incidents) as total_incidents,
                    SUM(near_misses) as total_near_misses,
                    COUNT(*) FILTER (WHERE rollback_required = true) * 100.0 / COUNT(*) as rollback_rate
                FROM per_task_roi_log
                WHERE date >= date('now', '-30 days')
                GROUP BY risk_level
                ORDER BY risk_level
            """,
            "description": "Risk analysis with incident tracking"
        },
        {
            "name": "Quarter Goal Progress",
            "sql": """
                SELECT 
                    strftime('%Y-%m', date) as month,
                    SUM(human_time_saved_hours) as monthly_hours_saved,
                    AVG(roi_score) as avg_roi,
                    SUM(cost_savings_usd) as monthly_cost_savings,
                    COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate,
                    SUM(incidents) as monthly_incidents
                FROM per_task_roi_log
                WHERE date >= date('now', '-3 months')
                GROUP BY strftime('%Y-%m', date)
                ORDER BY month DESC
            """,
            "description": "Quarter goal tracking"
        },
        {
            "name": "Experiment Performance",
            "sql": """
                SELECT 
                    experiment_id,
                    COUNT(*) as task_count,
                    AVG(roi_score) as avg_roi,
                    AVG(quality_improvement) as avg_quality,
                    SUM(human_time_saved_hours) as total_hours_saved,
                    COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate
                FROM per_task_roi_log
                WHERE experiment_id IS NOT NULL
                GROUP BY experiment_id
                ORDER BY avg_roi DESC
            """,
            "description": "Experiment A/B testing results"
        }
    ]
    
    for i, example in enumerate(aggregation_examples, 1):
        print(f"{i}. {example['name']}:")
        print(f"   SQL: {example['sql'].strip()}")
        print(f"   Description: {example['description']}")
        print()
    
    # Create implementation example
    print("IMPLEMENTATION EXAMPLE:")
    print("-" * 50)
    
    implementation_example = {
        "task_id": "test_expansion_quality_2_2025-01-25_001",
        "date": "2025-01-25T16:50:43",
        "task_type": "test_expansion",
        "module": "swarm/quality",
        "risk_level": "low",
        "complexity": "medium",
        "success": True,
        "execution_time_seconds": 600.0,
        "swarm_topology": "current_mesh",
        "agent_count": 3,
        "tool_count": 8,
        "enforcement_mode": "log_only",
        "human_baseline_hours": 2.5,
        "human_time_saved_hours": 2.33,
        "token_cost": 15000.0,
        "infra_cost_usd": 0.05,
        "cost_savings_usd": 233.0,
        "quality_improvement": 0.93,
        "defects_found": 2,
        "defects_avoided": 2,
        "human_review_friction": 0.1,
        "slo_compliance": "green",
        "slo_violations": "[]",
        "business_value": "high",
        "impact_score": 85.0,
        "roi_score": 99.0,
        "revenue_impact_usd": 0.0,
        "risk_reduction_usd": 500.0,
        "experiment_id": None,
        "batch_id": "week6_batch_1",
        "run_id": "run_2025_01_25_001",
        "human_verified": True,
        "evidence_links": '["dashboard_url", "diff_url"]',
        "notes": "Standard test expansion task for quality module",
        "incidents": 0,
        "near_misses": 0,
        "rollback_required": False,
        "rollback_time_hours": 0.0
    }
    
    print("Example Row:")
    print(json.dumps(implementation_example, indent=2))
    print()
    
    # Integration points
    print("INTEGRATION POINTS:")
    print("-" * 50)
    
    integration_points = [
        {
            "component": "Task Runner",
            "action": "Auto-log completed tasks",
            "trigger": "After task completion",
            "data_source": "Task execution metrics"
        },
        {
            "component": "ROI Tracker",
            "action": "Calculate ROI scores",
            "trigger": "During task completion",
            "data_source": "Task metrics + baseline estimates"
        },
        {
            "component": "Weekly Review",
            "action": "Generate weekly summary",
            "trigger": "Friday reviews",
            "data_source": "Aggregated ROI data"
        },
        {
            "component": "Quarter Checkpoint",
            "action": "Generate quarter reports",
            "trigger": "Quarter-end reviews",
            "data_source": "3-month ROI data"
        },
        {
            "component": "Dashboard",
            "action": "Display real-time metrics",
            "trigger": "Dashboard loads",
            "data_source": "Recent ROI data"
        }
    ]
    
    for point in integration_points:
        print(f"• {point['component']}: {point['action']}")
        print(f"  Trigger: {point['trigger']}")
        print(f"  Data: {point['data_source']}")
        print()
    
    # Save schema
    with open("per_task_roi_schema.json", 'w') as f:
        json.dump(schema, f, indent=2)
    
    print("✅ Schema saved to per_task_roi_schema.json")
    
    # Create SQL schema file
    sql_schema = f"""
-- Per-Task ROI Table Schema
-- Generated: {datetime.now().isoformat()}

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
);

-- Indexes for performance
{chr(10).join(schema['indexes'])};

-- Constraints for data integrity
{chr(10).join(schema['constraints'])};
"""
    
    with open("per_task_roi_schema.sql", 'w') as f:
        f.write(sql_schema)
    
    print("✅ SQL schema saved to per_task_roi_schema.sql")
    
    print()
    print("=" * 70)
    print("PER-TASK ROI SCHEMA COMPLETE")
    print("Status: Ready for implementation")
    print("Next: Integrate with task runner and ROI tracker")
    print("=" * 70)
    
    return schema

if __name__ == "__main__":
    design_per_task_roi_schema()
