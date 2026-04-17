"""
PerformanceAnalytics - Layer 3: Agent Performance Metrics and Analysis

Responsibilities:
- Calculate agent accuracy and performance metrics
- Track confidence calibration
- Identify performance trends
- Generate performance reports
- Detect degradation patterns
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from agents.reflection.core import Reflection, DecisionOutcome
from utils.logger import get_logger

logger = get_logger("reflection.analytics")


@dataclass
class AgentMetrics:
    """Performance metrics for an agent."""
    agent_id: str
    
    # Decision counts
    total_decisions: int = 0
    validated_count: int = 0
    invalidated_count: int = 0
    pending_count: int = 0
    
    # Accuracy metrics
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    
    # Confidence metrics
    avg_confidence: float = 0.0
    confidence_calibration: float = 0.0  # How well confidence matches accuracy
    overconfidence_rate: float = 0.0
    underconfidence_rate: float = 0.0
    
    # Reality gap metrics
    avg_reality_gap: float = 0.0
    min_reality_gap: float = 1.0
    max_reality_gap: float = 0.0
    
    # Decision distribution
    accept_rate: float = 0.0
    reject_rate: float = 0.0
    abstain_rate: float = 0.0
    
    # Temporal metrics
    avg_response_time_ms: float = 0.0
    recent_accuracy_7d: float = 0.0
    recent_accuracy_24h: float = 0.0
    
    # Trend indicators
    accuracy_trend: str = "stable"  # improving/declining/stable
    confidence_trend: str = "stable"
    
    # Metadata
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_id": self.agent_id,
            "decision_counts": {
                "total": self.total_decisions,
                "validated": self.validated_count,
                "invalidated": self.invalidated_count,
                "pending": self.pending_count
            },
            "accuracy_metrics": {
                "accuracy": round(self.accuracy, 4),
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4),
                "f1_score": round(self.f1_score, 4)
            },
            "confidence_metrics": {
                "avg_confidence": round(self.avg_confidence, 4),
                "calibration": round(self.confidence_calibration, 4),
                "overconfidence_rate": round(self.overconfidence_rate, 4),
                "underconfidence_rate": round(self.underconfidence_rate, 4)
            },
            "reality_gap_metrics": {
                "avg": round(self.avg_reality_gap, 4),
                "min": round(self.min_reality_gap, 4),
                "max": round(self.max_reality_gap, 4)
            },
            "decision_distribution": {
                "accept_rate": round(self.accept_rate, 4),
                "reject_rate": round(self.reject_rate, 4),
                "abstain_rate": round(self.abstain_rate, 4)
            },
            "temporal_metrics": {
                "avg_response_time_ms": round(self.avg_response_time_ms, 2),
                "recent_accuracy_7d": round(self.recent_accuracy_7d, 4),
                "recent_accuracy_24h": round(self.recent_accuracy_24h, 4)
            },
            "trends": {
                "accuracy": self.accuracy_trend,
                "confidence": self.confidence_trend
            },
            "last_updated": self.last_updated
        }


class PerformanceAnalytics:
    """
    Analyzes agent performance from reflection data.
    
    Features:
    - Real-time metrics calculation
    - Confidence calibration analysis
    - Trend detection
    - Performance comparison
    - Degradation alerts
    """
    
    def __init__(self):
        self._metrics_cache: Dict[str, AgentMetrics] = {}
        self._cache_ttl = 60.0  # Cache for 60 seconds
        self._calculation_count = 0
        self._start_time = time.time()

        logger.info("PerformanceAnalytics initialized")

    # Helper methods to reduce cyclomatic complexity of calculate_agent_metrics
    def _check_metrics_cache(self, agent_id: str, force_refresh: bool) -> Optional[AgentMetrics]:
        """Check if valid cached metrics exist."""
        if not force_refresh and agent_id in self._metrics_cache:
            cached = self._metrics_cache[agent_id]
            if time.time() - cached.last_updated < self._cache_ttl:
                logger.debug("Returning cached metrics for %s", agent_id)
                return cached
        return None

    def _calculate_basic_counts(self, metrics: AgentMetrics, reflections: List[Reflection]) -> None:
        """Calculate basic decision counts."""
        metrics.total_decisions = len(reflections)
        metrics.validated_count = sum(
            1 for r in reflections if r.outcome == DecisionOutcome.VALIDATED
        )
        metrics.invalidated_count = sum(
            1 for r in reflections if r.outcome == DecisionOutcome.INVALIDATED
        )
        metrics.pending_count = sum(
            1 for r in reflections if r.outcome == DecisionOutcome.PENDING
        )

    def _calculate_accuracy_metrics(self, metrics: AgentMetrics, resolved: List[Reflection]) -> None:
        """Calculate precision, recall, and F1 score."""
        if not resolved:
            return

        metrics.accuracy = metrics.validated_count / len(resolved)

        true_positives = sum(
            1 for r in resolved
            if r.decision == "accept" and r.outcome == DecisionOutcome.VALIDATED
        )
        false_positives = sum(
            1 for r in resolved
            if r.decision == "accept" and r.outcome == DecisionOutcome.INVALIDATED
        )
        false_negatives = sum(
            1 for r in resolved
            if r.decision == "reject" and r.outcome == DecisionOutcome.VALIDATED
        )

        if true_positives + false_positives > 0:
            metrics.precision = true_positives / (true_positives + false_positives)

        if true_positives + false_negatives > 0:
            metrics.recall = true_positives / (true_positives + false_negatives)

        if metrics.precision + metrics.recall > 0:
            metrics.f1_score = 2 * (metrics.precision * metrics.recall) / (metrics.precision + metrics.recall)

    def _calculate_confidence_metrics(self, metrics: AgentMetrics, reflections: List[Reflection], resolved: List[Reflection]) -> None:
        """Calculate confidence calibration metrics."""
        if not reflections:
            return

        metrics.avg_confidence = sum(r.confidence for r in reflections) / len(reflections)

        if not resolved:
            return

        high_conf_reflections = [r for r in resolved if r.confidence > 0.7]
        if high_conf_reflections:
            high_conf_accuracy = sum(
                1 for r in high_conf_reflections
                if r.outcome == DecisionOutcome.VALIDATED
            ) / len(high_conf_reflections)

            expected_accuracy = sum(r.confidence for r in high_conf_reflections) / len(high_conf_reflections)
            metrics.confidence_calibration = 1.0 - abs(high_conf_accuracy - expected_accuracy)

            metrics.overconfidence_rate = sum(
                1 for r in high_conf_reflections
                if r.outcome == DecisionOutcome.INVALIDATED
            ) / len(high_conf_reflections)

        low_conf_reflections = [r for r in resolved if r.confidence < 0.5]
        if low_conf_reflections:
            metrics.underconfidence_rate = sum(
                1 for r in low_conf_reflections
                if r.outcome == DecisionOutcome.VALIDATED
            ) / len(low_conf_reflections)

    def _calculate_gap_metrics(self, metrics: AgentMetrics, resolved: List[Reflection]) -> None:
        """Calculate reality gap metrics."""
        gap_reflections = [r for r in resolved if r.reality_gap is not None]
        if gap_reflections:
            gaps = [r.reality_gap for r in gap_reflections]
            metrics.avg_reality_gap = sum(gaps) / len(gaps)
            metrics.min_reality_gap = min(gaps)
            metrics.max_reality_gap = max(gaps)

    def _calculate_decision_distribution(self, metrics: AgentMetrics, reflections: List[Reflection]) -> None:
        """Calculate accept/reject/abstain rates."""
        if reflections:
            metrics.accept_rate = sum(1 for r in reflections if r.decision == "accept") / len(reflections)
            metrics.reject_rate = sum(1 for r in reflections if r.decision == "reject") / len(reflections)
            metrics.abstain_rate = sum(1 for r in reflections if r.decision == "abstain") / len(reflections)

    def _calculate_temporal_metrics(self, metrics: AgentMetrics, resolved: List[Reflection]) -> None:
        """Calculate 7d and 24h accuracy metrics."""
        now = time.time()
        recent_7d = [r for r in resolved if now - r.decision_timestamp < 7 * 86400]
        recent_24h = [r for r in resolved if now - r.decision_timestamp < 86400]

        if recent_7d:
            metrics.recent_accuracy_7d = sum(
                1 for r in recent_7d if r.outcome == DecisionOutcome.VALIDATED
            ) / len(recent_7d)

        if recent_24h:
            metrics.recent_accuracy_24h = sum(
                1 for r in recent_24h if r.outcome == DecisionOutcome.VALIDATED
            ) / len(recent_24h)

    def calculate_agent_metrics(
        self,
        agent_id: str,
        reflections: List[Reflection],
        force_refresh: bool = False
    ) -> AgentMetrics:
        """
        Calculate comprehensive metrics for an agent.

        Args:
            agent_id: Agent identifier
            reflections: List of agent's reflections
            force_refresh: Force recalculation (ignore cache)

        Returns:
            AgentMetrics with all calculated metrics
        """
        start = time.time()

        # Check cache first
        cached = self._check_metrics_cache(agent_id, force_refresh)
        if cached:
            return cached

        metrics = AgentMetrics(agent_id=agent_id)

        if not reflections:
            self._metrics_cache[agent_id] = metrics
            return metrics

        # Pre-compute resolved list once
        resolved = [r for r in reflections if r.is_resolved()]

        # Delegate to helper methods for each metric category
        self._calculate_basic_counts(metrics, reflections)
        self._calculate_accuracy_metrics(metrics, resolved)
        self._calculate_confidence_metrics(metrics, reflections, resolved)
        self._calculate_gap_metrics(metrics, resolved)
        self._calculate_decision_distribution(metrics, reflections)
        self._calculate_temporal_metrics(metrics, resolved)

        # Trend detection
        metrics.accuracy_trend = self._detect_accuracy_trend(reflections)
        metrics.confidence_trend = self._detect_confidence_trend(reflections)

        # Cache and return
        metrics.last_updated = time.time()
        self._metrics_cache[agent_id] = metrics

        self._calculation_count += 1
        duration_ms = (time.time() - start) * 1000

        logger.debug(
            "Calculated metrics for %s: accuracy=%.2f%% confidence=%.2f gap=%.3f (%.2fms)",
            agent_id, metrics.accuracy * 100, metrics.avg_confidence,
            metrics.avg_reality_gap, duration_ms
        )

        return metrics
    
    def compare_agents(
        self,
        metrics_list: List[AgentMetrics],
        sort_by: str = "accuracy"
    ) -> List[Tuple[str, AgentMetrics]]:
        """
        Compare multiple agents and rank them.
        
        Args:
            metrics_list: List of agent metrics
            sort_by: Metric to sort by (accuracy/f1_score/confidence_calibration)
        
        Returns:
            Sorted list of (agent_id, metrics) tuples
        """
        sort_key_map = {
            "accuracy": lambda m: m.accuracy,
            "f1_score": lambda m: m.f1_score,
            "confidence_calibration": lambda m: m.confidence_calibration,
            "reality_gap": lambda m: -m.avg_reality_gap  # Lower is better
        }
        
        sort_key = sort_key_map.get(sort_by, lambda m: m.accuracy)
        
        sorted_metrics = sorted(
            [(m.agent_id, m) for m in metrics_list],
            key=lambda x: sort_key(x[1]),
            reverse=True
        )
        
        logger.debug("Compared %d agents, sorted by %s", len(metrics_list), sort_by)
        
        return sorted_metrics
    
    def detect_performance_degradation(
        self,
        current_metrics: AgentMetrics,
        historical_metrics: List[AgentMetrics],
        threshold: float = 0.1
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if agent performance has degraded.
        
        Args:
            current_metrics: Current agent metrics
            historical_metrics: Historical metrics for comparison
            threshold: Degradation threshold (0.1 = 10% drop)
        
        Returns:
            Degradation alert dict if detected, None otherwise
        """
        if not historical_metrics:
            return None
        
        # Calculate historical average
        hist_accuracy = sum(m.accuracy for m in historical_metrics) / len(historical_metrics)
        hist_confidence_cal = sum(m.confidence_calibration for m in historical_metrics) / len(historical_metrics)
        
        degradations = []
        
        # Check accuracy degradation
        if hist_accuracy > 0 and current_metrics.accuracy < hist_accuracy * (1 - threshold):
            degradations.append({
                "metric": "accuracy",
                "historical": hist_accuracy,
                "current": current_metrics.accuracy,
                "drop_pct": (hist_accuracy - current_metrics.accuracy) / hist_accuracy * 100
            })
        
        # Check confidence calibration degradation
        if hist_confidence_cal > 0 and current_metrics.confidence_calibration < hist_confidence_cal * (1 - threshold):
            degradations.append({
                "metric": "confidence_calibration",
                "historical": hist_confidence_cal,
                "current": current_metrics.confidence_calibration,
                "drop_pct": (hist_confidence_cal - current_metrics.confidence_calibration) / hist_confidence_cal * 100
            })
        
        if degradations:
            alert = {
                "agent_id": current_metrics.agent_id,
                "timestamp": time.time(),
                "degradations": degradations,
                "severity": "high" if len(degradations) > 1 else "medium"
            }
            
            logger.warning(
                "Performance degradation detected for %s: %d metrics degraded",
                current_metrics.agent_id, len(degradations)
            )
            
            return alert
        
        return None
    
    def _detect_accuracy_trend(self, reflections: List[Reflection]) -> str:
        """Detect accuracy trend over time."""
        resolved = [r for r in reflections if r.is_resolved()]
        if len(resolved) < 10:
            return "stable"
        
        # Split into two halves
        mid = len(resolved) // 2
        first_half = resolved[:mid]
        second_half = resolved[mid:]
        
        first_accuracy = sum(
            1 for r in first_half if r.outcome == DecisionOutcome.VALIDATED
        ) / len(first_half)
        
        second_accuracy = sum(
            1 for r in second_half if r.outcome == DecisionOutcome.VALIDATED
        ) / len(second_half)
        
        diff = second_accuracy - first_accuracy
        
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        else:
            return "stable"
    
    def _detect_confidence_trend(self, reflections: List[Reflection]) -> str:
        """Detect confidence trend over time."""
        if len(reflections) < 10:
            return "stable"
        
        # Split into two halves
        mid = len(reflections) // 2
        first_half = reflections[:mid]
        second_half = reflections[mid:]
        
        first_confidence = sum(r.confidence for r in first_half) / len(first_half)
        second_confidence = sum(r.confidence for r in second_half) / len(second_half)
        
        diff = second_confidence - first_confidence
        
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        else:
            return "stable"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get analytics layer statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "cached_agents": len(self._metrics_cache),
            "total_calculations": self._calculation_count,
            "cache_ttl_seconds": self._cache_ttl,
            "performance": {
                "uptime_seconds": round(uptime, 2),
                "calculations_per_second": round(self._calculation_count / uptime, 2) if uptime > 0 else 0
            }
        }
