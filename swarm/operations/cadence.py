#!/usr/bin/env python3
"""
MERID Swarm Operations Cadence
Weekly swarm review and SLO monitoring system
"""

import sys
import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from swarm.ci.reliability_monitor import CIReliabilityMonitor
from swarm.quality.metrics_collector import quality_collector
from utils.logger import get_logger

logger = get_logger("swarm.operations_cadence")


@dataclass
class SwarmSLOs:
    """Service Level Objectives for MERID Swarm"""
    success_rate_min: float = 0.90
    avg_cascade_size_max: float = 2.0
    avg_branching_factor_max: float = 1.2
    quality_score_min: float = 0.80
    misalignment_max: float = 1.0
    retry_index_max: float = 2.0
    
    def check_compliance(self, metrics: Dict[str, Any]) -> Dict[str, bool]:
        """Check if metrics meet SLOs"""
        return {
            "success_rate": metrics.get("success_rate", 0) >= self.success_rate_min,
            "cascade_size": metrics.get("avg_cascade_size", 0) <= self.avg_cascade_size_max,
            "branching_factor": metrics.get("avg_branching_factor", 0) <= self.avg_branching_factor_max,
            "quality_score": metrics.get("quality_score", 0) >= self.quality_score_min,
            "misalignment": metrics.get("avg_misalignment", 0) <= self.misalignment_max,
            "retry_index": metrics.get("avg_retry_index", 0) <= self.retry_index_max
        }
    
    def calculate_slo_score(self, metrics: Dict[str, Any]) -> float:
        """Calculate overall SLO score (0-100)"""
        compliance = self.check_compliance(metrics)
        
        # Weight the SLOs
        weights = {
            "success_rate": 0.3,
            "cascade_size": 0.2,
            "branching_factor": 0.15,
            "quality_score": 0.2,
            "misalignment": 0.1,
            "retry_index": 0.05
        }
        
        score = 0
        for slo, compliant in compliance.items():
            if compliant:
                score += weights[slo] * 100
            else:
                # Partial credit based on how far from threshold
                if slo == "success_rate":
                    actual = metrics.get("success_rate", 0)
                    score += (actual / self.success_rate_min) * weights[slo] * 100
                elif slo == "cascade_size":
                    actual = metrics.get("avg_cascade_size", 0)
                    score += max(0, (1 - actual / self.avg_cascade_size_max)) * weights[slo] * 100
                elif slo == "branching_factor":
                    actual = metrics.get("avg_branching_factor", 0)
                    score += max(0, (1 - actual / self.avg_branching_factor_max)) * weights[slo] * 100
                elif slo == "quality_score":
                    actual = metrics.get("quality_score", 0)
                    score += (actual / self.quality_score_min) * weights[slo] * 100
                elif slo == "misalignment":
                    actual = metrics.get("avg_misalignment", 0)
                    score += max(0, (1 - actual / self.misalignment_max)) * weights[slo] * 100
                elif slo == "retry_index":
                    actual = metrics.get("avg_retry_index", 0)
                    score += max(0, (1 - actual / self.retry_index_max)) * weights[slo] * 100
        
        return min(100, score)


@dataclass
class SwarmChangelogEntry:
    """Entry in swarm changelog"""
    date: str
    type: str  # "agent_change", "prompt_update", "infrastructure", "incident"
    description: str
    impact: str  # "improved", "degraded", "neutral"
    metrics_before: Optional[Dict[str, Any]] = None
    metrics_after: Optional[Dict[str, Any]] = None


class SwarmOperationsCadence:
    """Weekly swarm review and operations cadence"""
    
    def __init__(self):
        self.slos = SwarmSLOs()
        self.ci_monitor = CIReliabilityMonitor()
        self.changelog: List[SwarmChangelogEntry] = []
        self.review_history: List[Dict[str, Any]] = []
        
        # Load existing data
        self._load_changelog()
        self._load_review_history()
        
        logger.info("Swarm Operations Cadence initialized")
    
    def run_weekly_review(self) -> Dict[str, Any]:
        """Run weekly swarm review"""
        logger.info("Starting weekly swarm review")
        
        review_date = datetime.now().isoformat()
        
        # Collect current metrics
        current_metrics = self._collect_current_metrics()
        
        # Check SLO compliance
        slo_compliance = self.slos.check_compliance(current_metrics)
        slo_score = self.slos.calculate_slo_score(current_metrics)
        
        # Analyze trends
        trends = self._analyze_trends(current_metrics)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(current_metrics, slo_compliance, trends)
        
        # Create review report
        review_report = {
            "date": review_date,
            "current_metrics": current_metrics,
            "slo_compliance": slo_compliance,
            "slo_score": slo_score,
            "trends": trends,
            "recommendations": recommendations,
            "action_items": self._generate_action_items(slo_compliance, recommendations)
        }
        
        # Save review
        self.review_history.append(review_report)
        self._save_review_history()
        
        # Log summary
        self._log_review_summary(review_report)
        
        return review_report
    
    def _collect_current_metrics(self) -> Dict[str, Any]:
        """Collect current swarm metrics"""
        # Run CI reliability check
        ci_passed = self.ci_monitor.run_ci_checks("weekly_ci_report.json")
        
        # Load CI report
        try:
            with open("weekly_ci_report.json", 'r') as f:
                ci_report = json.load(f)
            ci_metrics = ci_report["metrics"]
        except:
            ci_metrics = {
                "success_rate": 0.0,
                "avg_cascade_size": 0.0,
                "avg_branching_factor": 0.0,
                "avg_misalignment": 0.0,
                "avg_retry_index": 0.0
            }
        
        # Get quality metrics
        quality_trends = quality_collector.analyze_quality_trends(window_size=20)
        quality_metrics = {
            "quality_score": quality_trends.get("quality_score", 0.0) / 100,  # Convert to 0-1 scale
            "test_coverage": quality_trends.get("averages", {}).get("test_coverage", 0.0),
            "defect_rate": quality_trends.get("averages", {}).get("defect_rate", 0.0),
            "developer_efficiency": quality_trends.get("averages", {}).get("developer_efficiency", 0.0)
        }
        
        # Combine metrics
        combined_metrics = {
            "success_rate": ci_metrics["success_rate"],
            "avg_cascade_size": ci_metrics["avg_cascade_size"],
            "avg_branching_factor": ci_metrics["avg_branching_factor"],
            "avg_misalignment": ci_metrics["avg_misalignment"],
            "avg_retry_index": ci_metrics["avg_retry_index"],
            "quality_score": quality_metrics["quality_score"],
            "test_coverage": quality_metrics["test_coverage"],
            "defect_rate": quality_metrics["defect_rate"],
            "developer_efficiency": quality_metrics["developer_efficiency"]
        }
        
        return combined_metrics
    
    def _analyze_trends(self, current_metrics: Dict[str, Any]) -> Dict[str, str]:
        """Analyze metric trends"""
        if len(self.review_history) < 2:
            return {"status": "insufficient_data"}
        
        previous_review = self.review_history[-2]
        previous_metrics = previous_review["current_metrics"]
        
        trends = {}
        
        # Compare key metrics
        for metric in ["success_rate", "avg_cascade_size", "avg_branching_factor", 
                      "quality_score", "test_coverage", "defect_rate"]:
            
            current = current_metrics.get(metric, 0)
            previous = previous_metrics.get(metric, 0)
            
            if metric in ["success_rate", "quality_score", "test_coverage"]:
                # Higher is better
                if current > previous * 1.05:  # 5% improvement
                    trends[metric] = "improving"
                elif current < previous * 0.95:  # 5% degradation
                    trends[metric] = "degrading"
                else:
                    trends[metric] = "stable"
            else:
                # Lower is better
                if current < previous * 0.95:  # 5% improvement
                    trends[metric] = "improving"
                elif current > previous * 1.05:  # 5% degradation
                    trends[metric] = "degrading"
                else:
                    trends[metric] = "stable"
        
        return trends
    
    def _generate_recommendations(self, metrics: Dict[str, Any], 
                                compliance: Dict[str, bool], 
                                trends: Dict[str, str]) -> List[str]:
        """Generate recommendations based on metrics and trends"""
        recommendations = []
        
        # SLO compliance recommendations
        if not compliance["success_rate"]:
            recommendations.append("URGENT: Success rate below SLO - investigate agent failures")
        
        if not compliance["cascade_size"]:
            recommendations.append("Cascade size above SLO - review failure containment")
        
        if not compliance["quality_score"]:
            recommendations.append("Quality score below SLO - focus on code quality improvements")
        
        # Trend-based recommendations
        if trends.get("success_rate") == "degrading":
            recommendations.append("Success rate trending down - review recent changes")
        
        if trends.get("quality_score") == "degrading":
            recommendations.append("Quality score trending down - review prompt/role changes")
        
        if trends.get("defect_rate") == "degrading":
            recommendations.append("Defect rate increasing - strengthen code review process")
        
        # Performance recommendations
        if metrics["developer_efficiency"] < 50:
            recommendations.append("Low developer efficiency - investigate tooling issues")
        
        if metrics["test_coverage"] < 0.8:
            recommendations.append("Test coverage below target - improve test generation")
        
        if not recommendations:
            recommendations.append("All metrics look good - continue current practices")
        
        return recommendations
    
    def _generate_action_items(self, compliance: Dict[str, bool], 
                            recommendations: List[str]) -> List[str]:
        """Generate specific action items"""
        action_items = []
        
        # Critical SLO breaches trigger hardening sprints
        critical_breaches = [slo for slo, compliant in compliance.items() if not compliant]
        
        if critical_breaches:
            action_items.append(f"TRIGGER HARDENING SPRINT for SLO breaches: {', '.join(critical_breaches)}")
        
        # Quality improvements
        if not compliance.get("quality_score", True):
            action_items.append("Launch quality improvement initiative - focus on highest defect areas")
        
        # Trend investigations
        if "degrading" in recommendations:
            action_items.append("Investigate degrading trends - review recent agent/prompt changes")
        
        # Process improvements
        if len(recommendations) > 3:
            action_items.append("Schedule swarm process review - too many improvement areas")
        
        return action_items
    
    def add_changelog_entry(self, entry_type: str, description: str, 
                          impact: str, metrics_before: Optional[Dict[str, Any]] = None,
                          metrics_after: Optional[Dict[str, Any]] = None):
        """Add entry to swarm changelog"""
        entry = SwarmChangelogEntry(
            date=datetime.now().isoformat(),
            type=entry_type,
            description=description,
            impact=impact,
            metrics_before=metrics_before,
            metrics_after=metrics_after
        )
        
        self.changelog.append(entry)
        self._save_changelog()
        
        logger.info(f"Added changelog entry: {entry_type} - {description}")
    
    def get_recent_changelog(self, days: int = 7) -> List[SwarmChangelogEntry]:
        """Get recent changelog entries"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        recent_entries = []
        for entry in self.changelog:
            entry_date = datetime.fromisoformat(entry.date)
            if entry_date >= cutoff_date:
                recent_entries.append(entry)
        
        return recent_entries
    
    def _log_review_summary(self, review_report: Dict[str, Any]):
        """Log review summary"""
        slo_score = review_report["slo_score"]
        compliance_count = sum(review_report["slo_compliance"].values())
        
        logger.info(f"=== WEEKLY SWARM REVIEW SUMMARY ===")
        logger.info(f"SLO Score: {slo_score:.1f}/100")
        logger.info(f"SLO Compliance: {compliance_count}/6")
        logger.info(f"Recommendations: {len(review_report['recommendations'])}")
        logger.info(f"Action Items: {len(review_report['action_items'])}")
        
        if review_report['action_items']:
            logger.info("ACTION ITEMS:")
            for item in review_report['action_items']:
                logger.info(f"  - {item}")
    
    def _load_changelog(self):
        """Load existing changelog"""
        changelog_file = Path("swarm_changelog.json")
        if changelog_file.exists():
            try:
                with open(changelog_file, 'r') as f:
                    data = json.load(f)
                    self.changelog = [
                        SwarmChangelogEntry(**entry) for entry in data.get("entries", [])
                    ]
            except Exception as e:
                logger.warning(f"Failed to load changelog: {e}")
    
    def _save_changelog(self):
        """Save changelog to file"""
        changelog_file = Path("swarm_changelog.json")
        
        data = {
            "last_updated": datetime.now().isoformat(),
            "entries": [
                {
                    "date": entry.date,
                    "type": entry.type,
                    "description": entry.description,
                    "impact": entry.impact,
                    "metrics_before": entry.metrics_before,
                    "metrics_after": entry.metrics_after
                }
                for entry in self.changelog
            ]
        }
        
        with open(changelog_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_review_history(self):
        """Load existing review history"""
        history_file = Path("swarm_review_history.json")
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    self.review_history = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load review history: {e}")
    
    def _save_review_history(self):
        """Save review history to file"""
        history_file = Path("swarm_review_history.json")
        
        with open(history_file, 'w') as f:
            json.dump(self.review_history, f, indent=2)
    
    def export_operations_report(self, filename: str = "swarm_operations_report.json"):
        """Export comprehensive operations report"""
        report = {
            "generated_at": datetime.now().isoformat(),
            "slos": {
                "success_rate_min": self.slos.success_rate_min,
                "avg_cascade_size_max": self.slos.avg_cascade_size_max,
                "avg_branching_factor_max": self.slos.avg_branching_factor_max,
                "quality_score_min": self.slos.quality_score_min,
                "misalignment_max": self.slos.misalignment_max,
                "retry_index_max": self.slos.retry_index_max
            },
            "recent_changelog": [
                {
                    "date": entry.date,
                    "type": entry.type,
                    "description": entry.description,
                    "impact": entry.impact
                }
                for entry in self.get_recent_changelog(days=30)
            ],
            "review_history": self.review_history[-10:] if self.review_history else [],
            "current_status": self._collect_current_metrics()
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Operations report exported to {filename}")


# Global operations cadence instance
operations_cadence = SwarmOperationsCadence()
