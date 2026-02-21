"""
4-Week Checkpoint Schema and Data Collection
Minimal per-task ROI logging for aggregate analysis
"""

import sys
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

sys.path.append('.')
sys.path.append('swarm')

@dataclass
class PerTaskROI:
    """Per-task ROI logging schema"""
    task_id: str
    date: str
    task_type: str  # "test_expansion", "config_refactor", "documentation", etc.
    module: Optional[str]  # Module or component name
    risk_level: str  # "low", "medium", "high", "critical"
    
    # Performance metrics
    success: bool
    execution_time_seconds: float
    human_time_saved_hours: float
    
    # Quality metrics
    defects_avoided: int
    human_review_friction: float  # 0-1 scale, higher = more friction
    quality_improvement: float  # -1 to 1 scale
    
    # Swarm configuration
    swarm_topology: str  # "current_mesh", "shallow_hierarchy", etc.
    agent_count: int
    tool_count: int
    enforcement_mode: str  # "none", "log_only", "warn", "block"
    
    # Business impact
    roi_score: float  # 0-100 scale
    cost_savings_usd: float  # $100/hour assumption
    business_value: str  # "low", "medium", "high", "critical"
    
    # Incident tracking
    incidents: int
    near_misses: int
    rollback_required: bool
    
    # Metadata
    experiment_id: Optional[str]  # If part of an experiment
    batch_id: Optional[str]     # If part of a scaling batch
    notes: str


class ROIAggregator:
    """Aggregates per-task ROI data for analysis"""
    
    def __init__(self):
        self.tasks: List[PerTaskROI] = []
        self.checkpoint_data: Dict[str, Any] = {}
        
    def log_task(self, task_data: Dict[str, Any]):
        """Log a completed task"""
        # Convert to PerTaskROI format
        roi_task = PerTaskROI(
            task_id=task_data.get("task_id", ""),
            date=task_data.get("date", datetime.now().isoformat()),
            task_type=task_data.get("task_type", "unknown"),
            module=task_data.get("module"),
            risk_level=task_data.get("risk_level", "medium"),
            
            success=task_data.get("success", False),
            execution_time_seconds=task_data.get("execution_time_seconds", 0),
            human_time_saved_hours=task_data.get("human_time_saved_hours", 0),
            
            defects_avoided=task_data.get("defects_avoided", 0),
            human_review_friction=task_data.get("human_review_friction", 0.0),
            quality_improvement=task_data.get("quality_improvement", 0.0),
            
            swarm_topology=task_data.get("swarm_topology", "current_mesh"),
            agent_count=task_data.get("agent_count", 0),
            tool_count=task_data.get("tool_count", 0),
            enforcement_mode=task_data.get("enforcement_mode", "log_only"),
            
            roi_score=task_data.get("roi_score", 0.0),
            cost_savings_usd=task_data.get("cost_savings_usd", 0.0),
            business_value=task_data.get("business_value", "medium"),
            
            incidents=task_data.get("incidents", 0),
            near_misses=task_data.get("near_misses", 0),
            rollback_required=task_data.get("rollback_required", False),
            
            experiment_id=task_data.get("experiment_id"),
            batch_id=task_data.get("batch_id"),
            notes=task_data.get("notes", "")
        )
        
        self.tasks.append(roi_task)
        
        # Save to file
        self._save_task_log()
    
    def _save_task_log(self):
        """Save task log to file"""
        # Convert to serializable format
        task_log = [
            {
                "task_id": task.task_id,
                "date": task.date,
                "task_type": task.task_type,
                "module": task.module,
                "risk_level": task.risk_level,
                "success": task.success,
                "execution_time_seconds": task.execution_time_seconds,
                "human_time_saved_hours": task.human_time_saved_hours,
                "defects_avoided": task.defects_avoided,
                "human_review_friction": task.human_review_friction,
                "quality_improvement": task.quality_improvement,
                "swarm_topology": task.swarm_topology,
                "agent_count": task.agent_count,
                "tool_count": task.tool_count,
                "enforcement_mode": task.enforcement_mode,
                "roi_score": task.roi_score,
                "cost_savings_usd": task.cost_savings_usd,
                "business_value": task.business_value,
                "incidents": task.incidents,
                "near_misses": task.near_misses,
                "rollback_required": task.rollback_required,
                "experiment_id": task.experiment_id,
                "batch_id": task.batch_id,
                "notes": task.notes
            }
            for task in self.tasks
        ]
        
        with open("per_task_roi_log.json", 'w') as f:
            json.dump(task_log, f, indent=2)
    
    def generate_4week_checkpoint(self) -> Dict[str, Any]:
        """Generate 4-week checkpoint summary"""
        if not self.tasks:
            return {"error": "No tasks to analyze"}
        
        # Time range (last 4 weeks)
        four_weeks_ago = datetime.now().timestamp() - (4 * 7 * 24 * 60 * 60)
        recent_tasks = [t for t in self.tasks if datetime.fromisoformat(t.date).timestamp() >= four_weeks_ago]
        
        if not recent_tasks:
            return {"error": "No tasks in 4-week window"}
        
        # Calculate aggregates
        total_tasks = len(recent_tasks)
        successful_tasks = sum(1 for t in recent_tasks if t.success)
        total_time_saved = sum(t.human_time_saved_hours for t in recent_tasks)
        total_cost_savings = sum(t.cost_savings_usd for t in recent_tasks)
        total_defects_avoided = sum(t.defects_avoided for t in recent_tasks)
        total_incidents = sum(t.incidents for t in recent_tasks)
        total_near_misses = sum(t.near_misses for t in recent_tasks)
        
        # Averages
        avg_roi_score = sum(t.roi_score for t in recent_tasks) / len(recent_tasks)
        avg_quality_improvement = sum(t.quality_improvement for t in recent_tasks) / len(recent_tasks)
        avg_human_review_friction = sum(t.human_review_friction for t in recent_tasks) / len(recent_tasks)
        
        # By task type
        task_type_stats = {}
        for task in recent_tasks:
            task_type = task.task_type
            if task_type not in task_type_stats:
                task_type_stats[task_type] = {
                    "count": 0,
                    "total_time_saved": 0,
                    "total_cost_savings": 0,
                    "avg_roi_score": 0,
                    "success_rate": 0,
                    "avg_quality_improvement": 0
                }
            
            task_type_stats[task_type]["count"] += 1
            task_type_stats[task_type]["total_time_saved"] += task.human_time_saved_hours
            task_type_stats[task_type]["total_cost_savings"] += task.cost_savings_usd
            task_type_stats[task_type]["avg_roi_score"] += task.roi_score
            task_type_stats[task_type]["success_rate"] += 1 if task.success else 0
            task_type_stats[task_type]["avg_quality_improvement"] += task.quality_improvement
        
        # Calculate averages for task types
        for task_type, stats in task_type_stats.items():
            if stats["count"] > 0:
                stats["avg_roi_score"] /= stats["count"]
                stats["success_rate"] /= stats["count"]
                stats["avg_quality_improvement"] /= stats["count"]
        
        # By risk level
        risk_stats = {}
        for task in recent_tasks:
            risk = task.risk_level
            if risk not in risk_stats:
                risk_stats[risk] = {
                    "count": 0,
                    "total_time_saved": 0,
                    "total_cost_savings": 0,
                    "avg_roi_score": 0,
                    "success_rate": 0,
                    "incidents": 0,
                    "near_misses": 0
                }
            
            risk_stats[risk]["count"] += 1
            risk_stats[risk]["total_time_saved"] += task.human_time_saved_hours
            risk_stats[risk]["total_cost_savings"] += task.cost_savings_usd
            risk_stats[risk]["avg_roi_score"] += task.roi_score
            risk_stats[risk]["success_rate"] += 1 if task.success else 0
            risk_stats[risk]["incidents"] += task.incidents
            risk_stats[risk]["near_misses"] += task.near_misses
        
        # Calculate averages for risk levels
        for risk, stats in risk_stats.items():
            if stats["count"] > 0:
                stats["avg_roi_score"] /= stats["count"]
                stats["success_rate"] /= stats["count"]
        
        # By topology
        topology_stats = {}
        for task in recent_tasks:
            topology = task.swarm_topology
            if topology not in topology_stats:
                topology_stats[topology] = {
                    "count": 0,
                    "total_time_saved": 0,
                    "total_cost_savings": 0,
                    "avg_roi_score": 0,
                    "success_rate": 0
                }
            
            topology_stats[topology]["count"] += 1
            topology_stats[topology]["total_time_saved"] += task.human_time_saved_hours
            topology_stats[topology]["total_cost_savings"] += task.cost_savings_usd
            topology_stats[topology]["avg_roi_score"] += task.roi_score
            topology_stats[topology]["success_rate"] += 1 if task.success else 0
        
        # Calculate averages for topologies
        for topology, stats in topology_stats.items():
            if stats["count"] > 0:
                stats["avg_roi_score"] /= stats["count"]
                stats["success_rate"] /= stats["count"]
        
        # Generate recommendations
        recommendations = []
        
        # Scaling recommendations
        if avg_roi_score > 85 and success_rate > 0.9:
            recommendations.append("✅ Strong performance - scale all successful patterns")
        elif avg_roi_score > 70:
            recommendations.append("⚠️  Good performance - scale cautiously, monitor closely")
        else:
            recommendations.append("❌ Performance issues - optimize before scaling")
        
        # Risk recommendations
        if risk_stats.get("high", {}).get("incidents", 0) > 0:
            recommendations.append("❌ High-risk tasks had incidents - review approach")
        if risk_stats.get("critical", {}).get("incidents", 0) > 0:
            recommendations.append("🚨 CRITICAL - Stop high-risk experiments immediately")
        
        # Quality recommendations
        if avg_quality_improvement < 0:
            recommendations.append("❌ Quality regression detected - investigate immediately")
        elif avg_quality_improvement < 0.1:
            recommendations.append("⚠️  Quality flat - focus on improvements")
        
        # Topology recommendations
        if topology_stats.get("shallow_hierarchy", {}).get("avg_roi_score", 0) > 80:
            recommendations.append("✅ Shallow hierarchy showing promise - consider larger experiments")
        elif topology_stats.get("current_mesh", {}).get("avg_roi_score", 0) < 60:
            recommendations.append("⚠️  Current mesh underperforming - investigate")
        
        # Create checkpoint data
        checkpoint_data = {
            "checkpoint_date": datetime.now().isoformat(),
            "period": "4_weeks",
            "summary": {
                "total_tasks": total_tasks,
                "successful_tasks": successful_tasks,
                "success_rate": successful_tasks / total_tasks,
                "total_time_saved_hours": total_time_saved,
                "total_cost_savings_usd": total_cost_savings,
                "avg_roi_score": avg_roi_score,
                "avg_quality_improvement": avg_quality_improvement,
                "total_defects_avoided": total_defects_avoided,
                "total_incidents": total_incidents,
                "total_near_misses": total_near_misses,
                "avg_human_review_friction": avg_human_review_friction
            },
            "by_task_type": task_type_stats,
            "by_risk_level": risk_stats,
            "by_topology": topology_stats,
            "recommendations": recommendations,
            "scaling_decisions": {
                "continue_scaling": avg_roi_score > 70 and success_rate > 0.9,
                "expand_config_scope": risk_stats.get("low", {}).get("success_rate", 0) == 1.0,
                "try_new_topology": topology_stats.get("shallow_hierarchy", {}).get("avg_roi_score", 0) > 80,
                "focus_on_quality": avg_quality_improvement < 0.1
            }
        }
        
        self.checkpoint_data = checkpoint_data
        
        # Save checkpoint
        with open("4week_checkpoint.json", 'w') as f:
            json.dump(checkpoint_data, f, indent=2)
        
        return checkpoint_data
    
    def get_sql_query_examples(self) -> List[str]:
        """Get example SQL queries for aggregate analysis"""
        return [
            "-- Total ROI by task type",
            "SELECT task_type, COUNT(*) as task_count, AVG(roi_score) as avg_roi, SUM(cost_savings_usd) as total_savings",
            "FROM per_task_roi_log",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY task_type",
            "ORDER BY avg_roi DESC;",
            "",
            "-- Success rate by risk level",
            "SELECT risk_level, COUNT(*) as task_count, AVG(roi_score) as avg_roi, COUNT(*) FILTER (WHERE success = true) * 100.0 / COUNT(*) as success_rate",
            "FROM per_task_roi_log",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY risk_level",
            "ORDER BY avg_roi DESC;",
            "",
            "-- Quality trends over time",
            "SELECT DATE(date) as day, AVG(quality_improvement) as avg_quality, AVG(human_review_friction) as avg_friction",
            "FROM per_task_roi_log",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY DATE(date)",
            "ORDER BY day;",
            "",
            "-- Top performing configurations",
            "SELECT swarm_topology, enforcement_mode, AVG(roi_score) as avg_roi, AVG(quality_improvement) as avg_quality",
            "FROM per_task_roi_log",
            "WHERE date >= date('now', '-4 weeks')",
            "GROUP BY swarm_topology, enforcement_mode",
            "ORDER BY avg_roi DESC;"
        ]


# Global aggregator instance
roi_aggregator = ROIAggregator()


def generate_4week_checkpoint():
    """Generate the 4-week checkpoint"""
    print("=" * 70)
    print("4-WEEK CHECKPOINT")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Purpose: Aggregate analysis for scaling decisions")
    print()
    
    checkpoint = roi_aggregator.generate_4week_checkpoint()
    
    if "error" in checkpoint:
        print(f"❌ Error: {checkpoint['error']}")
        return
    
    print("4-WEEK SUMMARY:")
    print("-" * 40)
    summary = checkpoint["summary"]
    
    print(f"Total Tasks: {summary['total_tasks']}")
    print(f"Success Rate: {summary['success_rate']:.1%}")
    print(f"Time Saved: {summary['total_time_saved_hours']:.1f} hours")
    print(f"Cost Savings: ${summary['total_cost_savings_usd']:,.0f}")
    print(f"Average ROI: {summary['avg_roi_score']:.1f}/100")
    print(f"Quality Improvement: {summary['avg_quality_improvement']:+.2f}")
    print(f"Defects Avoided: {summary['total_defects_avoided']}")
    print(f"Incidents: {summary['total_incidents']}")
    print(f"Near Misses: {summary['total_near_misses']}")
    
    print()
    print("BY TASK TYPE:")
    print("-" * 40)
    for task_type, stats in checkpoint["by_task_type"].items():
        print(f"{task_type}:")
        print(f"  Tasks: {stats['count']}")
        print(f"  Time Saved: {stats['total_time_saved']:.1f}h")
        print(f"  Cost Savings: ${stats['total_cost_savings']:,.0f}")
        print(f"  ROI: {stats['avg_roi_score']:.1f}/100")
        print(f"  Success: {stats['success_rate']:.1%}")
        print(f"  Quality: {stats['avg_quality_improvement']:+.2f}")
        print()
    
    print("BY RISK LEVEL:")
    print("-" * 40)
    for risk, stats in checkpoint["by_risk_level"].items():
        print(f"{risk}:")
        print(f"  Tasks: {stats['count']}")
        print(f"  Time Saved: {stats['total_time_saved']:.1f}h")
        print(f"  ROI: {stats['avg_roi_score']:.1f}/100")
        print(f"  Success: {stats['success_rate']:.1%}")
        print(f"  Incidents: {stats['incidents']}")
        print(f"  Near Misses: {stats['near_misses']}")
        print()
    
    print("BY TOPOLOGY:")
    print("-" * 40)
    for topology, stats in checkpoint["by_topology"].items():
        print(f"{topology}:")
        print(f"  Tasks: {stats['count']}")
        print(f"  Time Saved: {stats['total_time_saved']:.1f}h")
        print(f"  ROI: {stats['avg_roi_score']:.1f}/100")
        print(f"  Success: {stats['success_rate']:.1%}")
        print()
    
    print("RECOMMENDATIONS:")
    print("-" * 40)
    for i, rec in enumerate(checkpoint["recommendations"], 1):
        print(f"{i}. {rec}")
    
    print()
    print("SCALING DECISIONS:")
    print("-" * 40)
    decisions = checkpoint["scaling_decisions"]
    print(f"Continue Scaling: {'✅ YES' if decisions['continue_scaling'] else '❌ NO'}")
    print(f"Expand Config Scope: {'✅ YES' if decisions['expand_config_scope'] else '❌ NO'}")
    print(f"Try New Topology: {'✅ YES' if decisions['try_new_topology'] else '❌ NO'}")
    print(f"Focus on Quality: {'✅ YES' if decisions['focus_on_quality'] else '❌ NO'}")
    
    print()
    print("SQL QUERY EXAMPLES:")
    print("-" * 40)
    queries = roi_aggregator.get_sql_query_examples()
    for query in queries:
        print(query)
        print()
    
    print("=" * 70)
    print("4-WEEK CHECKPOINT COMPLETE")
    print("Ready for scaling decisions")
    print("=" * 70)
    
    return checkpoint


if __name__ == "__main__":
    generate_4week_checkpoint()
