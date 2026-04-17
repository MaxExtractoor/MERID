"""
Quality of Work Metrics for MERID Swarm
Measures PR quality, developer efficiency, and defect reduction using existing tracing infrastructure
"""

import time
import json
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

from swarm.tracing.tracer import tracer, SpanType
from utils.logger import get_logger

logger = get_logger("swarm.quality_metrics")


class QualityMetricType(Enum):
    """Types of quality metrics"""
    TEST_COVERAGE = "test_coverage"
    DIFF_SIZE = "diff_size"
    DEFECT_RATE = "defect_rate"
    REVIEW_TIME = "review_time"
    DEVELOPER_EFFICIENCY = "developer_efficiency"
    CODE_COMPLEXITY = "code_complexity"
    SECURITY_VIOLATIONS = "security_violations"
    PERFORMANCE_IMPACT = "performance_impact"


@dataclass
class QualityMetrics:
    """Quality metrics for a task or PR"""
    task_id: str
    timestamp: float
    
    # Code quality metrics
    test_coverage: float = 0.0
    diff_size: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    files_changed: int = 0
    
    # Process metrics
    total_turns: int = 0
    total_tokens: int = 0
    human_interventions: int = 0
    review_time_seconds: float = 0.0
    
    # Quality metrics
    defect_rate: float = 0.0
    security_violations: int = 0
    performance_impact: float = 0.0
    code_complexity: float = 0.0
    
    # Developer efficiency
    developer_efficiency: float = 0.0
    time_to_first_review: float = 0.0
    cycle_time: float = 0.0
    
    # Misalignment correlation
    misalignment_correlation: float = 0.0
    human_correction_count: int = 0


class QualityMetricsCollector:
    """Collects and analyzes quality metrics using tracing data"""
    
    def __init__(self):
        self.metrics_history: List[QualityMetrics] = []
        self.pr_metrics: Dict[str, QualityMetrics] = {}
        
    def collect_from_trace(self, trace_id: str) -> QualityMetrics:
        """Collect quality metrics from trace data"""
        spans = tracer.get_trace(trace_id)
        if not spans:
            return None
        
        # Find task root span
        task_span = None
        for span in spans:
            if span.span_type == SpanType.TASK_ROOT:
                task_span = span
                break
        
        if not task_span:
            return None
        
        # Initialize metrics
        metrics = QualityMetrics(
            task_id=task_span.trace_id,
            timestamp=task_span.start_time
        )
        
        # Collect metrics from spans
        for span in spans:
            if span.span_type == SpanType.AGENT_EXECUTION:
                self._collect_agent_metrics(span, metrics)
            elif span.span_type == SpanType.TOOL_CALL:
                self._collect_tool_metrics(span, metrics)
        
        # Calculate derived metrics
        self._calculate_derived_metrics(metrics)
        
        return metrics
    
    def _collect_agent_metrics(self, span, metrics: QualityMetrics):
        """Collect metrics from agent execution spans"""
        # Extract agent role from tags
        agent_role = span.tags.get("agent_role", "unknown")
        
        # Count turns
        if "turn_number" in span.tags:
            turn_num = span.tags["turn_number"]
            metrics.total_turns = max(metrics.total_turns, turn_num)
        
        # Count tokens
        if "tokens_used" in span.tags:
            metrics.total_tokens += span.tags["tokens_used"]
        
        # Track human interventions
        if "human_intervention" in span.tags:
            metrics.human_interventions += 1
        
        # Track review time
        if "review_time_seconds" in span.tags:
            metrics.review_time_seconds += span.tags["review_time_seconds"]
        
        # Track code quality metrics
        if "test_coverage" in span.tags:
            metrics.test_coverage = max(metrics.test_coverage, span.tags["test_coverage"])
        
        if "diff_size" in span.tags:
            metrics.diff_size += span.tags["diff_size"]
        
        if "lines_added" in span.tags:
            metrics.lines_added += span.tags["lines_added"]
        
        if "lines_removed" in span.tags:
            metrics.lines_removed += span.tags["lines_removed"]
        
        if "files_changed" in span.tags:
            metrics.files_changed += span.tags["files_changed"]
        
        # Track defects
        if "defects_found" in span.tags:
            defects = span.tags["defects_found"]
            if metrics.total_turns > 0:
                metrics.defect_rate = defects / metrics.total_turns
        
        # Track security violations
        if "security_violations" in span.tags:
            metrics.security_violations += span.tags["security_violations"]
        
        # Track performance impact
        if "performance_impact" in span.tags:
            metrics.performance_impact = max(metrics.performance_impact, 
                                                span.tags["performance_impact"])
        
        # Track code complexity
        if "cyclomatic_complexity" in span.tags:
            metrics.code_complexity = max(metrics.code_complexity, 
                                             span.tags["cyclomatic_complexity"])
    
    def _collect_tool_metrics(self, span, metrics: QualityMetrics):
        """Collect metrics from tool call spans"""
        tool_name = span.tags.get("tool_name", "unknown")
        
        # Track retry attempts
        if "retry_count" in span.tags:
            retry_count = span.tags["retry_count"]
            # This would be used with enhanced watchdog for per-tool retry caps
            pass
        
        # Track tool-specific quality metrics
        if tool_name == "security_scanner":
            if "vulnerabilities_found" in span.tags:
                metrics.security_violations += span.tags["vulnerabilities_found"]
        
        if tool_name == "performance_profiler":
            if "performance_regression" in span.tags:
                metrics.performance_impact = max(metrics.performance_impact,
                                                span.tags["performance_regression"])
    
    def _calculate_derived_metrics(self, metrics: QualityMetrics):
        """Calculate derived quality metrics"""
        # Calculate net code change
        net_code_change = metrics.lines_added - metrics.lines_removed
        
        # Calculate developer efficiency (tokens per turn)
        if metrics.total_turns > 0:
            metrics.developer_efficiency = metrics.total_tokens / metrics.total_turns
        
        # Calculate cycle time
        if task_span := self._find_task_span(metrics.task_id):
            metrics.cycle_time = task_span.end_time - task_span.start_time if task_span.end_time else 0
        
        # Calculate time to first review
        if metrics.review_time_seconds > 0 and metrics.total_turns > 0:
            metrics.time_to_first_review = metrics.review_time_seconds / metrics.total_turns
        
        # Calculate misalignment correlation (placeholder - would need correlation analysis)
        # This would correlate misalignment scores with human corrections
        metrics.misalignment_correlation = 0.0  # Would be calculated from historical data
    
    def _find_task_span(self, task_id: str):
        """Find the task root span for a given task ID"""
        # This would need to be implemented to find spans by trace_id
        return None
    
    def analyze_quality_trends(self, window_size: int = 100) -> Dict[str, Any]:
        """Analyze quality trends over time"""
        if len(self.metrics_history) < window_size:
            return {"error": "Insufficient data for trend analysis"}
        
        recent_metrics = self.metrics_history[-window_size:]
        
        # Calculate averages and trends
        avg_coverage = sum(m.test_coverage for m in recent_metrics) / len(recent_metrics)
        avg_defect_rate = sum(m.defect_rate for m in recent_metrics) / len(recent_metrics)
        avg_efficiency = sum(m.developer_efficiency for m in recent_metrics) / len(recent_metrics)
        
        # Calculate trends (simple linear trend)
        if len(recent_metrics) >= 2:
            coverage_trend = (recent_metrics[-1].test_coverage - recent_metrics[0].test_coverage) / len(recent_metrics)
            defect_trend = (recent_metrics[-1].defect_rate - recent_metrics[0].defect_rate) / len(recent_metrics)
            efficiency_trend = (recent_metrics[-1].developer_efficiency - recent_metrics[0].developer_efficiency) / len(recent_metrics)
        else:
            coverage_trend = 0
            defect_trend = 0
            efficiency_trend = 0
        
        return {
            "window_size": window_size,
            "period": {
                "start": recent_metrics[0].timestamp,
                "end": recent_metrics[-1].timestamp
            },
            "averages": {
                "test_coverage": avg_coverage,
                "defect_rate": avg_defect_rate,
                "developer_efficiency": avg_efficiency,
                "cycle_time": sum(m.cycle_time for m in recent_metrics) / len(recent_metrics),
                "review_time": sum(m.review_time_seconds for m in recent_metrics) / len(recent_metrics)
            },
            "trends": {
                "test_coverage_trend": coverage_trend,
                "defect_rate_trend": defect_trend,
                "developer_efficiency_trend": efficiency_trend
            },
            "quality_score": self._calculate_quality_score(avg_coverage, avg_defect_rate, avg_efficiency)
        }
    
    def _calculate_quality_score(self, coverage: float, defect_rate: float, efficiency: float) -> float:
        """Calculate overall quality score (0-100)"""
        # Weight the different components
        coverage_weight = 0.3
        defect_weight = 0.4
        efficiency_weight = 0.3
        
        # Normalize metrics (higher is better for coverage and efficiency, lower for defects)
        normalized_coverage = min(coverage, 1.0)  # Coverage is already 0-1
        normalized_defect = max(0, 1 - defect_rate)  # Invert defect rate so higher is better
        normalized_efficiency = min(efficiency / 100, 1.0)  # Assume 100 tokens/turn as max efficiency
        
        score = (normalized_coverage * coverage_weight + 
                normalized_defect * defect_weight + 
                normalized_efficiency * efficiency_weight) * 100
        
        return score
    
    def correlate_misalignment_with_corrections(self) -> Dict[str, float]:
        """Correlate misalignment scores with human corrections"""
        if len(self.metrics_history) < 10:
            return {"error": "Insufficient data for correlation analysis"}
        
        # Extract misalignment scores and human corrections
        misalignment_scores = []
        human_corrections = []
        
        for metrics in self.metrics_history:
            # This would need to be populated from actual misalignment data
            # For now, we'll use placeholder logic
            pass
        
        # Calculate correlation coefficient
        if len(misalignment_scores) > 1 and len(human_corrections) > 1:
            correlation = self._calculate_correlation(misalignment_scores, human_corrections)
        else:
            correlation = 0.0
        
        return {
            "correlation_coefficient": correlation,
            "sample_size": len(misalignment_scores),
            "interpretation": self._interpret_correlation(correlation)
        }
    
    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient"""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(a * b for a, b in zip(x, y))
        sum_x2 = sum(a * a for a in x)
        sum_y2 = sum(b * b for b in y)
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)) ** 0.5
        
        if denominator == 0:
            return 0.0
        
        return numerator / denominator
    
    def _interpret_correlation(self, correlation: float) -> str:
        """Interpret correlation coefficient"""
        abs_correlation = abs(correlation)
        
        if abs_correlation >= 0.7:
            return "Strong correlation"
        elif abs_correlation >= 0.3:
            return "Moderate correlation"
        elif abs_correlation >= 0.1:
            return "Weak correlation"
        else:
            return "No correlation"
    
    def get_quality_recommendations(self) -> List[str]:
        """Get quality improvement recommendations based on current metrics"""
        if len(self.metrics_history) < 5:
            return ["Insufficient data for recommendations"]
        
        recent_metrics = self.metrics_history[-5:]
        
        avg_coverage = sum(m.test_coverage for m in recent_metrics) / len(recent_metrics)
        avg_defect_rate = sum(m.defect_rate for m in recent_metrics) / len(recent_metrics)
        avg_efficiency = sum(m.developer_efficiency for m in recent_metrics) / len(recent_metrics)
        
        recommendations = []
        
        # Coverage recommendations
        if avg_coverage < 0.8:
            recommendations.append("Increase test coverage - target >80%")
        elif avg_coverage < 0.9:
            recommendations.append("Good test coverage, consider targeting >90%")
        
        # Defect rate recommendations
        if avg_defect_rate > 0.1:
            recommendations.append("High defect rate detected - implement better code review")
        elif avg_defect_rate > 0.05:
            recommendations.append("Moderate defect rate - consider additional quality gates")
        
        # Efficiency recommendations
        if avg_efficiency < 50:
            recommendations.append("Low developer efficiency - investigate tooling or process issues")
        elif avg_efficiency < 80:
            recommendations.append("Moderate efficiency - consider optimization opportunities")
        
        # Security recommendations
        total_violations = sum(m.security_violations for m in recent_metrics)
        if total_violations > 0:
            recommendations.append("Security violations detected - implement security scanning")
        
        # Performance recommendations
        avg_performance = sum(m.performance_impact for m in recent_metrics) / len(recent_metrics)
        if avg_performance > 0.1:
            recommendations.append("Performance regressions detected - implement performance testing")
        
        if not recommendations:
            recommendations.append("Quality metrics look good - continue current practices")
        
        return recommendations


# Global quality metrics collector
quality_collector = QualityMetricsCollector()
