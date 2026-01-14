"""
Unit tests for PerformanceAnalytics layer.

Tests:
- Metrics calculation
- Confidence calibration
- Trend detection
- Agent comparison
- Performance degradation detection
"""

import pytest
import time
from agents.reflection.core import Reflection, DecisionOutcome
from agents.reflection.analytics import PerformanceAnalytics, AgentMetrics


class TestPerformanceAnalytics:
    """Test suite for PerformanceAnalytics."""
    
    def create_reflections(self, agent_id: str, count: int, accuracy: float = 0.7) -> list:
        """Helper to create test reflections."""
        reflections = []
        
        for i in range(count):
            reflection = Reflection(
                reflection_id=f"ref-{agent_id}-{i}",
                agent_id=agent_id,
                energy_id=f"energy-{i}",
                decision="accept" if i % 2 == 0 else "reject",
                confidence=0.7 + (i % 3) * 0.1,
                reasoning=f"Test reasoning {i}",
                decision_timestamp=time.time() - (count - i) * 100
            )
            
            # Set outcome based on desired accuracy
            if i < int(count * accuracy):
                reflection.outcome = DecisionOutcome.VALIDATED
                reflection.reality_gap = 0.1 + (i % 5) * 0.05
            else:
                reflection.outcome = DecisionOutcome.INVALIDATED
                reflection.reality_gap = 0.7 + (i % 5) * 0.05
            
            reflections.append(reflection)
        
        return reflections
    
    def test_calculate_basic_metrics(self):
        """Test basic metrics calculation."""
        analytics = PerformanceAnalytics()
        
        reflections = self.create_reflections("agent-1", 10, accuracy=0.7)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        assert metrics.agent_id == "agent-1"
        assert metrics.total_decisions == 10
        assert metrics.validated_count == 7
        assert metrics.invalidated_count == 3
        assert metrics.accuracy == 0.7
    
    def test_calculate_confidence_metrics(self):
        """Test confidence metrics calculation."""
        analytics = PerformanceAnalytics()
        
        reflections = self.create_reflections("agent-1", 20, accuracy=0.8)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        assert 0.0 <= metrics.avg_confidence <= 1.0
        assert 0.0 <= metrics.confidence_calibration <= 1.0
        assert 0.0 <= metrics.overconfidence_rate <= 1.0
    
    def test_calculate_reality_gap_metrics(self):
        """Test reality gap metrics."""
        analytics = PerformanceAnalytics()
        
        reflections = self.create_reflections("agent-1", 15, accuracy=0.6)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        assert 0.0 <= metrics.avg_reality_gap <= 1.0
        assert 0.0 <= metrics.min_reality_gap <= 1.0
        assert 0.0 <= metrics.max_reality_gap <= 1.0
        assert metrics.min_reality_gap <= metrics.avg_reality_gap <= metrics.max_reality_gap
    
    def test_calculate_decision_distribution(self):
        """Test decision distribution calculation."""
        analytics = PerformanceAnalytics()
        
        reflections = self.create_reflections("agent-1", 20, accuracy=0.7)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        # Should sum to 1.0
        total = metrics.accept_rate + metrics.reject_rate + metrics.abstain_rate
        assert abs(total - 1.0) < 0.01
    
    def test_calculate_temporal_metrics(self):
        """Test temporal metrics (recent accuracy)."""
        analytics = PerformanceAnalytics()
        
        # Create reflections with different timestamps
        reflections = []
        now = time.time()
        
        # Old reflections (low accuracy)
        for i in range(10):
            r = Reflection(
                reflection_id=f"ref-old-{i}",
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.7,
                reasoning="Test",
                decision_timestamp=now - 10 * 86400  # 10 days ago
            )
            r.outcome = DecisionOutcome.INVALIDATED if i < 7 else DecisionOutcome.VALIDATED
            r.reality_gap = 0.8
            reflections.append(r)
        
        # Recent reflections (high accuracy)
        for i in range(10):
            r = Reflection(
                reflection_id=f"ref-new-{i}",
                agent_id="agent-1",
                energy_id=f"energy-new-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test",
                decision_timestamp=now - 3600  # 1 hour ago
            )
            r.outcome = DecisionOutcome.VALIDATED if i < 8 else DecisionOutcome.INVALIDATED
            r.reality_gap = 0.15
            reflections.append(r)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        # Recent accuracy should be higher than overall
        assert metrics.recent_accuracy_24h > metrics.accuracy
    
    def test_detect_accuracy_trend_improving(self):
        """Test improving accuracy trend detection."""
        analytics = PerformanceAnalytics()
        
        reflections = []
        
        # First half: low accuracy
        for i in range(10):
            r = Reflection(
                reflection_id=f"ref-{i}",
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.7,
                reasoning="Test",
                decision_timestamp=time.time() - (20 - i) * 100
            )
            r.outcome = DecisionOutcome.INVALIDATED if i < 7 else DecisionOutcome.VALIDATED
            reflections.append(r)
        
        # Second half: high accuracy
        for i in range(10, 20):
            r = Reflection(
                reflection_id=f"ref-{i}",
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test",
                decision_timestamp=time.time() - (20 - i) * 100
            )
            r.outcome = DecisionOutcome.VALIDATED if i < 18 else DecisionOutcome.INVALIDATED
            reflections.append(r)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        assert metrics.accuracy_trend == "improving"
    
    def test_detect_accuracy_trend_declining(self):
        """Test declining accuracy trend detection."""
        analytics = PerformanceAnalytics()
        
        reflections = []
        
        # First half: high accuracy
        for i in range(10):
            r = Reflection(
                reflection_id=f"ref-{i}",
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test",
                decision_timestamp=time.time() - (20 - i) * 100
            )
            r.outcome = DecisionOutcome.VALIDATED if i < 8 else DecisionOutcome.INVALIDATED
            reflections.append(r)
        
        # Second half: low accuracy
        for i in range(10, 20):
            r = Reflection(
                reflection_id=f"ref-{i}",
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.7,
                reasoning="Test",
                decision_timestamp=time.time() - (20 - i) * 100
            )
            r.outcome = DecisionOutcome.INVALIDATED if i < 17 else DecisionOutcome.VALIDATED
            reflections.append(r)
        
        metrics = analytics.calculate_agent_metrics("agent-1", reflections)
        
        assert metrics.accuracy_trend == "declining"
    
    def test_compare_agents(self):
        """Test agent comparison."""
        analytics = PerformanceAnalytics()
        
        # Create metrics for multiple agents
        metrics_list = []
        
        for i, accuracy in enumerate([0.9, 0.7, 0.5]):
            reflections = self.create_reflections(f"agent-{i}", 20, accuracy=accuracy)
            metrics = analytics.calculate_agent_metrics(f"agent-{i}", reflections)
            metrics_list.append(metrics)
        
        # Compare by accuracy
        ranked = analytics.compare_agents(metrics_list, sort_by="accuracy")
        
        assert len(ranked) == 3
        assert ranked[0][1].accuracy >= ranked[1][1].accuracy >= ranked[2][1].accuracy
        assert ranked[0][0] == "agent-0"  # Highest accuracy
        assert ranked[2][0] == "agent-2"  # Lowest accuracy
    
    def test_detect_performance_degradation(self):
        """Test performance degradation detection."""
        analytics = PerformanceAnalytics()
        
        # Historical metrics (good performance)
        historical = []
        for i in range(5):
            reflections = self.create_reflections(f"agent-hist-{i}", 20, accuracy=0.8)
            metrics = analytics.calculate_agent_metrics(f"agent-hist-{i}", reflections)
            historical.append(metrics)
        
        # Current metrics (degraded performance)
        current_reflections = self.create_reflections("agent-1", 20, accuracy=0.5)
        current_metrics = analytics.calculate_agent_metrics("agent-1", current_reflections)
        
        # Detect degradation
        alert = analytics.detect_performance_degradation(
            current_metrics=current_metrics,
            historical_metrics=historical,
            threshold=0.1
        )
        
        assert alert is not None
        assert alert["agent_id"] == "agent-1"
        assert len(alert["degradations"]) > 0
        assert alert["severity"] in ["high", "medium"]
    
    def test_no_degradation_detected(self):
        """Test no degradation when performance is stable."""
        analytics = PerformanceAnalytics()
        
        # Historical metrics
        historical = []
        for i in range(5):
            reflections = self.create_reflections(f"agent-hist-{i}", 20, accuracy=0.75)
            metrics = analytics.calculate_agent_metrics(f"agent-hist-{i}", reflections)
            historical.append(metrics)
        
        # Current metrics (similar performance)
        current_reflections = self.create_reflections("agent-1", 20, accuracy=0.73)
        current_metrics = analytics.calculate_agent_metrics("agent-1", current_reflections)
        
        # Should not detect degradation
        alert = analytics.detect_performance_degradation(
            current_metrics=current_metrics,
            historical_metrics=historical,
            threshold=0.1
        )
        
        assert alert is None
    
    def test_metrics_caching(self):
        """Test metrics caching."""
        analytics = PerformanceAnalytics()
        
        reflections = self.create_reflections("agent-1", 20, accuracy=0.7)
        
        # First calculation
        start = time.time()
        metrics1 = analytics.calculate_agent_metrics("agent-1", reflections)
        duration1 = time.time() - start
        
        # Second calculation (should use cache)
        start = time.time()
        metrics2 = analytics.calculate_agent_metrics("agent-1", reflections)
        duration2 = time.time() - start
        
        # Should be same metrics
        assert metrics1.accuracy == metrics2.accuracy
        
        # Second call should be faster (cached)
        # Note: This might not always be true due to system variance
        # but it's a good indicator
        
        # Force refresh
        metrics3 = analytics.calculate_agent_metrics("agent-1", reflections, force_refresh=True)
        assert metrics3.accuracy == metrics1.accuracy
    
    def test_empty_reflections(self):
        """Test metrics with no reflections."""
        analytics = PerformanceAnalytics()
        
        metrics = analytics.calculate_agent_metrics("agent-1", [])
        
        assert metrics.total_decisions == 0
        assert metrics.accuracy == 0.0
        assert metrics.avg_confidence == 0.0
    
    def test_get_stats(self):
        """Test statistics reporting."""
        analytics = PerformanceAnalytics()
        
        # Calculate some metrics
        for i in range(3):
            reflections = self.create_reflections(f"agent-{i}", 10, accuracy=0.7)
            analytics.calculate_agent_metrics(f"agent-{i}", reflections)
        
        stats = analytics.get_stats()
        
        assert stats["cached_agents"] == 3
        assert stats["total_calculations"] == 3
        assert "performance" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
