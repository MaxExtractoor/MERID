#!/usr/bin/env python3
"""
MERID Swarm ROI Tracker
Tracks user-visible improvements and developer productivity gains
"""

import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

sys.path.append('.')
sys.path.append('swarm')

from swarm.integration.task_runner import task_runner
from swarm.quality.metrics_collector import quality_collector
from swarm.operations.cadence import operations_cadence
from utils.logger import get_logger

logger = get_logger("swarm.roi_tracker")


class ImprovementType(Enum):
    """Types of user-visible improvements"""
    TEST_EXPANSION = "test_expansion"
    CONFIG_REFACTOR = "config_refactor"
    SECURITY_HARDENING = "security_hardening"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    DOCUMENTATION_IMPROVEMENT = "documentation_improvement"
    DEPENDENCY_UPDATES = "dependency_updates"


class ProductivityMetric(Enum):
    """Developer productivity metrics"""
    CODE_REVIEW_TIME = "code_review_time"
    BUG_FIX_TIME = "bug_fix_time"
    FEATURE_DEVELOPMENT_TIME = "feature_development_time"
    DEPLOYMENT_TIME = "deployment_time"
    INCIDENT_RESOLUTION_TIME = "incident_resolution_time"


@dataclass
class ROITask:
    """Task with ROI tracking"""
    task_id: str
    improvement_type: ImprovementType
    description: str
    baseline_metrics: Dict[str, float]
    swarm_metrics: Dict[str, float]
    human_time_saved_hours: float
    quality_improvement_score: float
    roi_score: float
    timestamp: float


class ROITracker:
    """Tracks ROI of swarm improvements"""
    
    def __init__(self):
        self.completed_tasks: List[ROITask] = []
        self.productivity_baseline: Dict[str, float] = {}
        self.roi_history: List[Dict[str, Any]] = []
        
        # Load existing data
        self._load_roi_data()
        self._establish_productivity_baseline()
        
        logger.info("ROI Tracker initialized")
    
    def track_improvement_task(self, task_config: Dict[str, Any], 
                             improvement_type: ImprovementType,
                             expected_human_time_saved: float) -> ROITask:
        """Track a swarm improvement task and calculate ROI"""
        logger.info(f"Tracking improvement task: {task_config['task_id']}")
        
        # Run task with swarm
        start_time = time.time()
        try:
            swarm_metrics = task_runner.execute_task(task_config)
            swarm_success = True
        except Exception as e:
            logger.error(f"Swarm task failed: {e}")
            swarm_metrics = self._create_failure_metrics(task_config['task_id'])
            swarm_success = False
        
        execution_time = time.time() - start_time
        
        # Get baseline metrics (what this would take without swarm)
        baseline_metrics = self._estimate_baseline_metrics(task_config, improvement_type)
        
        # Calculate quality improvement
        quality_improvement = self._calculate_quality_improvement(
            baseline_metrics, swarm_metrics, improvement_type
        )
        
        # Calculate ROI score
        roi_score = self._calculate_roi_score(
            expected_human_time_saved, execution_time, quality_improvement, swarm_success
        )
        
        # Create ROI task
        roi_task = ROITask(
            task_id=task_config['task_id'],
            improvement_type=improvement_type,
            description=task_config.get('description', ''),
            baseline_metrics=baseline_metrics,
            swarm_metrics={
                "success": swarm_success,
                "execution_time": execution_time,
                "turns": getattr(swarm_metrics, 'total_turns', 0),
                "tokens": getattr(swarm_metrics, 'total_tokens', 0),
                "cascade_size": getattr(swarm_metrics, 'cascade_size', 0)
            },
            human_time_saved_hours=expected_human_time_saved,
            quality_improvement_score=quality_improvement,
            roi_score=roi_score,
            timestamp=time.time()
        )
        
        self.completed_tasks.append(roi_task)
        self._save_roi_data()
        
        logger.info(f"Task {task_config['task_id']} ROI: {roi_score:.2f}")
        
        return roi_task
    
    def _create_failure_metrics(self, task_id: str) -> Any:
        """Create failure metrics object"""
        return type('obj', (object,), {
            'task_id': task_id,
            'success': False,
            'total_turns': 0,
            'total_tokens': 0,
            'cascade_size': 0
        })()
    
    def _estimate_baseline_metrics(self, task_config: Dict[str, Any], 
                                 improvement_type: ImprovementType) -> Dict[str, float]:
        """Estimate baseline metrics (what this would take without swarm)"""
        # Baseline estimates based on improvement type and complexity
        complexity = task_config.get('complexity', 'medium')
        
        baseline_estimates = {
            ImprovementType.TEST_EXPANSION: {
                "low": {"human_hours": 2.0, "quality_score": 0.6},
                "medium": {"human_hours": 4.0, "quality_score": 0.5},
                "high": {"human_hours": 8.0, "quality_score": 0.4}
            },
            ImprovementType.CONFIG_REFACTOR: {
                "low": {"human_hours": 1.5, "quality_score": 0.7},
                "medium": {"human_hours": 3.0, "quality_score": 0.6},
                "high": {"human_hours": 6.0, "quality_score": 0.5}
            },
            ImprovementType.SECURITY_HARDENING: {
                "low": {"human_hours": 3.0, "quality_score": 0.8},
                "medium": {"human_hours": 6.0, "quality_score": 0.7},
                "high": {"human_hours": 12.0, "quality_score": 0.6}
            },
            ImprovementType.PERFORMANCE_OPTIMIZATION: {
                "low": {"human_hours": 2.5, "quality_score": 0.6},
                "medium": {"human_hours": 5.0, "quality_score": 0.5},
                "high": {"human_hours": 10.0, "quality_score": 0.4}
            },
            ImprovementType.DOCUMENTATION_IMPROVEMENT: {
                "low": {"human_hours": 1.0, "quality_score": 0.7},
                "medium": {"human_hours": 2.0, "quality_score": 0.6},
                "high": {"human_hours": 4.0, "quality_score": 0.5}
            },
            ImprovementType.DEPENDENCY_UPDATES: {
                "low": {"human_hours": 1.5, "quality_score": 0.8},
                "medium": {"human_hours": 3.0, "quality_score": 0.7},
                "high": {"human_hours": 6.0, "quality_score": 0.6}
            }
        }
        
        return baseline_estimates.get(improvement_type, {}).get(
            complexity, {"human_hours": 3.0, "quality_score": 0.6}
        )
    
    def _calculate_quality_improvement(self, baseline: Dict[str, float], 
                                      swarm_metrics: Any, 
                                      improvement_type: ImprovementType) -> float:
        """Calculate quality improvement score"""
        if not swarm_metrics.success:
            return -0.5  # Penalty for failure
        
        baseline_quality = baseline.get("quality_score", 0.6)
        
        # Quality factors based on swarm performance
        swarm_quality_factors = []
        
        # Success rate
        swarm_quality_factors.append(1.0)  # Successful execution
        
        # Efficiency (fewer turns is better)
        turns = getattr(swarm_metrics, 'total_turns', 0)
        if turns <= 3:
            swarm_quality_factors.append(0.9)
        elif turns <= 6:
            swarm_quality_factors.append(0.7)
        else:
            swarm_quality_factors.append(0.5)
        
        # No cascades
        cascade_size = getattr(swarm_metrics, 'cascade_size', 0)
        if cascade_size == 0:
            swarm_quality_factors.append(1.0)
        elif cascade_size <= 1:
            swarm_quality_factors.append(0.8)
        else:
            swarm_quality_factors.append(0.6)
        
        # Average swarm quality
        swarm_quality = sum(swarm_quality_factors) / len(swarm_quality_factors)
        
        # Improvement calculation
        improvement = (swarm_quality - baseline_quality) / baseline_quality if baseline_quality > 0 else 0
        
        return max(-1.0, min(1.0, improvement))
    
    def _calculate_roi_score(self, human_time_saved: float, 
                             execution_time: float, 
                             quality_improvement: float, 
                             success: bool) -> float:
        """Calculate ROI score (0-100)"""
        if not success:
            return 0.0
        
        # Time savings component (60% weight)
        time_savings_value = human_time_saved / max(0.1, execution_time / 3600)  # Convert to hours
        time_score = min(1.0, time_savings_value / 10) * 60  # Normalize to 0-60
        
        # Quality improvement component (30% weight)
        quality_score = (quality_improvement + 1) * 15  # Convert -1 to 1 range to 0-30
        
        # Success component (10% weight)
        success_score = 10 if success else 0
        
        return time_score + quality_score + success_score
    
    def run_productivity_experiment(self, experiment_name: str,
                                   tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run productivity experiment comparing swarm vs human baseline"""
        logger.info(f"Running productivity experiment: {experiment_name}")
        
        experiment_results = {
            "experiment_name": experiment_name,
            "timestamp": datetime.now().isoformat(),
            "tasks": [],
            "productivity_gains": {},
            "quality_impact": {},
            "roi_summary": {}
        }
        
        total_human_time_saved = 0
        total_quality_improvement = 0
        total_roi_score = 0
        successful_tasks = 0
        
        for task_config in tasks:
            # Determine improvement type from task
            improvement_type = self._infer_improvement_type(task_config)
            
            # Estimate human time saved
            baseline = self._estimate_baseline_metrics(task_config, improvement_type)
            human_time_saved = baseline.get("human_hours", 3.0)
            
            # Track task
            roi_task = self.track_improvement_task(
                task_config, improvement_type, human_time_saved
            )
            
            experiment_results["tasks"].append({
                "task_id": roi_task.task_id,
                "improvement_type": roi_task.improvement_type.value,
                "human_time_saved": roi_task.human_time_saved_hours,
                "roi_score": roi_task.roi_score,
                "quality_improvement": roi_task.quality_improvement_score,
                "success": roi_task.swarm_metrics["success"]
            })
            
            # Accumulate totals
            if roi_task.swarm_metrics["success"]:
                total_human_time_saved += roi_task.human_time_saved_hours
                total_quality_improvement += roi_task.quality_improvement_score
                total_roi_score += roi_task.roi_score
                successful_tasks += 1
        
        # Calculate experiment metrics
        experiment_results["productivity_gains"] = {
            "total_human_time_saved_hours": total_human_time_saved,
            "avg_time_saved_per_task": total_human_time_saved / len(tasks),
            "total_tasks": len(tasks),
            "successful_tasks": successful_tasks,
            "success_rate": successful_tasks / len(tasks)
        }
        
        experiment_results["quality_impact"] = {
            "avg_quality_improvement": total_quality_improvement / len(tasks),
            "positive_improvements": len([t for t in experiment_results["tasks"] if t["quality_improvement"] > 0]),
            "negative_impact": len([t for t in experiment_results["tasks"] if t["quality_improvement"] < 0])
        }
        
        experiment_results["roi_summary"] = {
            "avg_roi_score": total_roi_score / len(tasks),
            "total_roi_score": total_roi_score,
            "roi_per_hour_saved": total_roi_score / max(1, total_human_time_saved)
        }
        
        # Save experiment
        self.roi_history.append(experiment_results)
        self._save_roi_data()
        
        return experiment_results
    
    def _infer_improvement_type(self, task_config: Dict[str, Any]) -> ImprovementType:
        """Infer improvement type from task configuration"""
        task_type = task_config.get("type", "analysis")
        description = task_config.get("description", "").lower()
        
        # Simple inference based on keywords
        if "test" in description or task_type == "testing":
            return ImprovementType.TEST_EXPANSION
        elif "config" in description or "configuration" in description:
            return ImprovementType.CONFIG_REFACTOR
        elif "security" in description or "vulnerability" in description:
            return ImprovementType.SECURITY_HARDENING
        elif "performance" in description or "optimization" in description:
            return ImprovementType.PERFORMANCE_OPTIMIZATION
        elif "doc" in description or "documentation" in description:
            return ImprovementType.DOCUMENTATION_IMPROVEMENT
        elif "dependency" in description or "package" in description:
            return ImprovementType.DEPENDENCY_UPDATES
        else:
            return ImprovementType.CONFIG_REFACTOR  # Default
    
    def _establish_productivity_baseline(self):
        """Establish baseline productivity metrics"""
        self.productivity_baseline = {
            "avg_code_review_time_hours": 2.0,
            "avg_bug_fix_time_hours": 4.0,
            "avg_feature_development_time_hours": 8.0,
            "avg_deployment_time_hours": 1.5,
            "avg_incident_resolution_time_hours": 3.0
        }
    
    def get_productivity_impact(self) -> Dict[str, Any]:
        """Calculate overall productivity impact of swarm"""
        if not self.completed_tasks:
            return {"error": "No completed tasks to analyze"}
        
        # Calculate time savings
        total_time_saved = sum(task.human_time_saved_hours for task in self.completed_tasks)
        avg_time_saved_per_task = total_time_saved / len(self.completed_tasks)
        
        # Calculate quality impact
        quality_improvements = [task.quality_improvement_score for task in self.completed_tasks]
        avg_quality_improvement = sum(quality_improvements) / len(quality_improvements)
        positive_quality_impact = len([q for q in quality_improvements if q > 0])
        
        # Calculate ROI
        roi_scores = [task.roi_score for task in self.completed_tasks]
        avg_roi_score = sum(roi_scores) / len(roi_scores)
        
        # Calculate improvement type breakdown
        improvement_breakdown = {}
        for task in self.completed_tasks:
            imp_type = task.improvement_type.value if hasattr(task.improvement_type, 'value') else str(task.improvement_type)
            if imp_type not in improvement_breakdown:
                improvement_breakdown[imp_type] = {"count": 0, "total_time_saved": 0, "total_roi": 0, "avg_roi": 0}
            
            improvement_breakdown[imp_type]["count"] += 1
            improvement_breakdown[imp_type]["total_time_saved"] += task.human_time_saved_hours
            improvement_breakdown[imp_type]["total_roi"] += task.roi_score
        
        # Calculate averages per improvement type
        for imp_type, data in improvement_breakdown.items():
            type_tasks = [t for t in self.completed_tasks if (t.improvement_type.value if hasattr(t.improvement_type, 'value') else str(t.improvement_type)) == imp_type]
            if type_tasks:
                data["avg_roi"] = sum(t.roi_score for t in type_tasks) / len(type_tasks)
                data["avg_time_saved"] = data["total_time_saved"] / data["count"]
        
        return {
            "total_tasks_completed": len(self.completed_tasks),
            "total_human_time_saved_hours": total_time_saved,
            "avg_time_saved_per_task_hours": avg_time_saved_per_task,
            "avg_quality_improvement": avg_quality_improvement,
            "positive_quality_impact_percentage": (positive_quality_impact / len(quality_improvements)) * 100,
            "avg_roi_score": avg_roi_score,
            "improvement_type_breakdown": improvement_breakdown,
            "productivity_baseline": self.productivity_baseline,
            "roi_per_hour_saved": sum(roi_scores) / max(1, total_time_saved)
        }
    
    def generate_roi_report(self) -> Dict[str, Any]:
        """Generate comprehensive ROI report"""
        productivity_impact = self.get_productivity_impact()
        
        if "error" in productivity_impact:
            return productivity_impact
        
        # Calculate monthly projections
        monthly_projection = {
            "estimated_monthly_time_saved": productivity_impact["total_human_time_saved_hours"] * 4,  # Assuming weekly
            "estimated_monthly_roi_score": productivity_impact["avg_roi_score"] * len(self.completed_tasks) * 4,
            "estimated_monthly_cost_savings": productivity_impact["total_human_time_saved_hours"] * 4 * 100  # $100/hour assumption
        }
        
        # Generate recommendations
        recommendations = []
        
        if productivity_impact["avg_roi_score"] > 70:
            recommendations.append("Excellent ROI - expand swarm usage to more task types")
        elif productivity_impact["avg_roi_score"] > 50:
            recommendations.append("Good ROI - continue current usage patterns")
        else:
            recommendations.append("Low ROI - investigate optimization opportunities")
        
        if productivity_impact["positive_quality_impact_percentage"] > 70:
            recommendations.append("Strong quality improvements - maintain current approach")
        elif productivity_impact["positive_quality_impact_percentage"] < 50:
            recommendations.append("Quality concerns - review prompt and role optimization")
        
        # Best performing improvement types
        improvement_breakdown = productivity_impact["improvement_type_breakdown"]
        best_types = sorted(improvement_breakdown.items(), 
                          key=lambda x: x[1]["avg_roi"], 
                          reverse=True)[:3]
        
        return {
            "summary": productivity_impact,
            "monthly_projections": monthly_projection,
            "recommendations": recommendations,
            "best_performing_improvements": best_types,
            "experiment_history": self.roi_history[-5:],  # Last 5 experiments
            "next_optimizations": self._suggest_next_optimizations(improvement_breakdown)
        }
    
    def _suggest_next_optimizations(self, improvement_breakdown: Dict[str, Any]) -> List[str]:
        """Suggest next optimization opportunities"""
        suggestions = []
        
        # Find underperforming areas
        for imp_type, data in improvement_breakdown.items():
            if data["avg_roi"] < 30:
                suggestions.append(f"Optimize {imp_type} - current ROI is low ({data['avg_roi']:.1f})")
        
        # Find high-opportunity areas
        for imp_type, data in improvement_breakdown.items():
            if data["avg_roi"] > 70 and data["count"] < 3:
                suggestions.append(f"Expand {imp_type} - high ROI with limited usage")
        
        if not suggestions:
            suggestions.append("Current performance is good - focus on scaling successful patterns")
        
        return suggestions
    
    def _load_roi_data(self):
        """Load existing ROI data"""
        try:
            with open("swarm_roi_data.json", 'r') as f:
                data = json.load(f)
                self.completed_tasks = [
                    ROITask(**task) for task in data.get("completed_tasks", [])
                ]
                self.roi_history = data.get("roi_history", [])
        except Exception as e:
            logger.warning(f"Failed to load ROI data: {e}")
    
    def _save_roi_data(self):
        """Save ROI data to file"""
        data = {
            "last_updated": datetime.now().isoformat(),
            "completed_tasks": [
                {
                    "task_id": task.task_id,
                    "improvement_type": task.improvement_type.value if hasattr(task.improvement_type, 'value') else str(task.improvement_type),
                    "description": task.description,
                    "baseline_metrics": task.baseline_metrics,
                    "swarm_metrics": task.swarm_metrics,
                    "human_time_saved_hours": task.human_time_saved_hours,
                    "quality_improvement_score": task.quality_improvement_score,
                    "roi_score": task.roi_score,
                    "timestamp": task.timestamp
                }
                for task in self.completed_tasks
            ],
            "roi_history": self.roi_history
        }
        
        with open("swarm_roi_data.json", 'w') as f:
            json.dump(data, f, indent=2)


# Global ROI tracker instance
roi_tracker = ROITracker()
