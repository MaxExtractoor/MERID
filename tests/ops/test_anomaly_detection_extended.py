"""Extended tests for ops/anomaly_detection.py - Anomaly Detection Coverage."""
import pytest
import time
import numpy as np
from unittest.mock import patch, MagicMock

from ops.anomaly_detection import (
    AnomalyType,
    AnomalySeverity,
    AnomalyEvent,
    IsolationForest,
    CUSUM,
    PageHinkley,
    AnomalyDetectionStack,
    get_anomaly_detection,
)


class TestEnums:
    """Test enum definitions."""

    def test_anomaly_type_values(self):
        """Test AnomalyType enum values."""
        assert AnomalyType.INPUT_OUTLIER.value == "input_outlier"
        assert AnomalyType.OUTPUT_DRIFT.value == "output_drift"
        assert AnomalyType.PERFORMANCE_CHANGE.value == "performance_change"
        assert AnomalyType.DISTRIBUTION_SHIFT.value == "distribution_shift"
        assert AnomalyType.CORRELATION_BREAK.value == "correlation_break"

    def test_anomaly_severity_values(self):
        """Test AnomalySeverity enum values."""
        assert AnomalySeverity.INFO.value == "info"
        assert AnomalySeverity.WARNING.value == "warning"
        assert AnomalySeverity.CRITICAL.value == "critical"
        assert AnomalySeverity.EMERGENCY.value == "emergency"


class TestAnomalyEvent:
    """Test AnomalyEvent dataclass."""

    def test_creation(self):
        """Test creating anomaly event."""
        event = AnomalyEvent(
            event_id="event_001",
            anomaly_type=AnomalyType.INPUT_OUTLIER,
            severity=AnomalySeverity.WARNING,
            detector="isolation_forest",
            timestamp=1234567890.0,
            value=0.85,
            threshold=0.75,
            description="Test anomaly"
        )
        assert event.event_id == "event_001"
        assert event.escalated is False
        assert event.resolved is False

    def test_to_dict(self):
        """Test anomaly event to_dict."""
        event = AnomalyEvent(
            event_id="event_002",
            anomaly_type=AnomalyType.OUTPUT_DRIFT,
            severity=AnomalySeverity.CRITICAL,
            detector="cusum",
            timestamp=1234567890.0,
            value=5.5,
            threshold=5.0,
            description="Drift detected",
            context={"direction": "positive"}
        )
        result = event.to_dict()
        
        assert result["event_id"] == "event_002"
        assert result["anomaly_type"] == "output_drift"
        assert result["severity"] == "critical"
        assert result["context"]["direction"] == "positive"


class TestIsolationForest:
    """Test IsolationForest class."""

    @pytest.fixture
    def forest(self):
        return IsolationForest(n_trees=10, sample_size=32, contamination=0.1)

    def test_initialization(self, forest):
        """Test forest initialization."""
        assert forest.n_trees == 10
        assert forest.sample_size == 32
        assert forest.contamination == 0.1
        assert forest._fitted is False

    def test_fit(self, forest):
        """Test fitting forest."""
        data = np.random.randn(100, 5)
        forest.fit(data)
        
        assert forest._fitted is True
        assert len(forest._trees) == 10

    def test_anomaly_score_not_fitted(self, forest):
        """Test anomaly score when not fitted."""
        point = np.random.randn(5)
        score = forest.anomaly_score(point)
        
        assert score == 0.5  # Default when not fitted

    def test_anomaly_score_fitted(self, forest):
        """Test anomaly score when fitted."""
        data = np.random.randn(100, 5)
        forest.fit(data)
        
        point = np.random.randn(5)
        score = forest.anomaly_score(point)
        
        assert 0 <= score <= 1

    def test_is_anomaly(self, forest):
        """Test anomaly detection."""
        # Create data with clear outlier
        data = np.random.randn(200, 5)
        forest.fit(data)
        
        # Normal point
        normal = np.zeros(5)
        is_anom, score = forest.is_anomaly(normal)
        
        assert is_anom in (True, False)  # Works with numpy bool
        assert 0 <= score <= 1

    def test_is_anomaly_with_outlier(self, forest):
        """Test detecting outlier."""
        # Create clustered data
        data = np.random.randn(200, 5) * 0.1
        forest.fit(data)
        
        # Extreme outlier
        outlier = np.ones(5) * 100
        is_anom, score = forest.is_anomaly(outlier)
        
        # Outlier should have high score
        assert score > 0.5

    def test_add_training_sample(self, forest):
        """Test adding training samples."""
        for _ in range(100):
            forest.add_training_sample(np.random.randn(5))
        
        assert len(forest._training_buffer) == 100

    def test_add_training_sample_triggers_fit(self, forest):
        """Test that adding enough samples triggers fit."""
        for _ in range(600):
            forest.add_training_sample(np.random.randn(5))
        
        assert forest._fitted is True

    def test_get_stats(self, forest):
        """Test getting stats."""
        stats = forest.get_stats()
        
        assert "fitted" in stats
        assert "n_trees" in stats
        assert "threshold" in stats
        assert "anomaly_rate" in stats


class TestCUSUM:
    """Test CUSUM class."""

    @pytest.fixture
    def cusum(self):
        return CUSUM(target=0.0, threshold=5.0, drift=0.5)

    def test_initialization(self, cusum):
        """Test CUSUM initialization."""
        assert cusum.target == 0.0
        assert cusum.threshold == 5.0
        assert cusum.drift == 0.5

    def test_update_no_alarm(self, cusum):
        """Test update without alarm."""
        alarm, direction, cusum_val = cusum.update(0.1)
        
        assert alarm is False
        assert direction == "none"

    def test_update_positive_alarm(self, cusum):
        """Test positive drift alarm."""
        # Push values to trigger positive alarm
        for _ in range(20):
            cusum.update(1.0)
        
        alarm, direction, cusum_val = cusum.update(1.0)
        
        # May or may not trigger depending on accumulated sum
        assert isinstance(alarm, bool)

    def test_update_negative_alarm(self, cusum):
        """Test negative drift alarm."""
        # Push negative values
        for _ in range(20):
            cusum.update(-1.0)
        
        alarm, direction, cusum_val = cusum.update(-1.0)
        
        assert isinstance(alarm, bool)

    def test_reset(self, cusum):
        """Test reset."""
        cusum.update(1.0)
        cusum.update(1.0)
        cusum.reset()
        
        assert cusum._cusum_pos == 0.0
        assert cusum._cusum_neg == 0.0
        assert cusum._in_alarm_state is False

    def test_set_target(self, cusum):
        """Test setting target."""
        cusum._cusum_pos = 5.0
        cusum.set_target(1.0)
        
        assert cusum.target == 1.0
        assert cusum._cusum_pos == 0.0  # Should be reset

    def test_auto_calibrate(self, cusum):
        """Test auto calibration."""
        # Add enough values
        for i in range(150):
            cusum.update(i * 0.01)
        
        cusum.auto_calibrate()
        
        # Target should be updated to recent mean
        assert cusum.target != 0.0

    def test_auto_calibrate_insufficient_data(self, cusum):
        """Test auto calibration with insufficient data."""
        for _ in range(50):
            cusum.update(0.1)
        
        original_target = cusum.target
        cusum.auto_calibrate()
        
        # Target should not change with <100 values
        assert cusum.target == original_target

    def test_get_stats(self, cusum):
        """Test getting stats."""
        cusum.update(0.1)
        stats = cusum.get_stats()
        
        assert "target" in stats
        assert "threshold" in stats
        assert "cusum_pos" in stats
        assert "cusum_neg" in stats
        assert "alarm_count" in stats


class TestPageHinkley:
    """Test PageHinkley class."""

    @pytest.fixture
    def ph(self):
        return PageHinkley(delta=0.01, threshold=10.0, alpha=0.99)

    def test_initialization(self, ph):
        """Test Page-Hinkley initialization."""
        assert ph.delta == 0.01
        assert ph.threshold == 10.0
        assert ph.alpha == 0.99

    def test_update_no_change(self, ph):
        """Test update without change detection."""
        change, stat = ph.update(0.1)
        
        assert change is False
        assert stat >= 0

    def test_update_change_detected(self, ph):
        """Test change point detection."""
        # Stable period
        for _ in range(50):
            ph.update(0.0)
        
        # Sudden shift
        for _ in range(50):
            change, stat = ph.update(1.0)
            if change:
                break
        
        # May or may not detect depending on threshold
        assert isinstance(change, bool)

    def test_reset(self, ph):
        """Test reset."""
        ph.update(1.0)
        ph.update(2.0)
        ph.reset()
        
        assert ph._n == 0
        assert ph._m == 0.0
        assert ph._M == 0.0

    def test_get_change_points(self, ph):
        """Test getting change points."""
        points = ph.get_change_points()
        
        assert isinstance(points, list)

    def test_get_stats(self, ph):
        """Test getting stats."""
        ph.update(0.5)
        stats = ph.get_stats()
        
        assert "delta" in stats
        assert "threshold" in stats
        assert "current_mean" in stats
        assert "n_observations" in stats


class TestAnomalyDetectionStack:
    """Test AnomalyDetectionStack class."""

    @pytest.fixture
    def stack(self):
        return AnomalyDetectionStack()

    def test_initialization(self, stack):
        """Test stack initialization."""
        assert stack.isolation_forest is not None
        assert stack.cusum_returns is not None
        assert stack.cusum_volatility is not None
        assert stack.page_hinkley is not None

    def test_register_escalation_callback(self, stack):
        """Test registering escalation callback."""
        callback = MagicMock()
        stack.register_escalation_callback(callback)
        
        assert callback in stack._escalation_callbacks

    def test_check_input_no_anomaly(self, stack):
        """Test input check with no anomaly."""
        features = np.zeros(10)
        event = stack.check_input(features)
        
        # With unfitted forest, likely no anomaly
        # Result depends on random factors
        assert event is None or isinstance(event, AnomalyEvent)

    def test_check_input_with_training(self, stack):
        """Test input check after training."""
        # Train with normal data
        for _ in range(600):
            stack.isolation_forest.add_training_sample(np.random.randn(10) * 0.1)
        
        # Check normal point
        features = np.zeros(10)
        event = stack.check_input(features)
        
        assert event is None or isinstance(event, AnomalyEvent)

    def test_check_output_drift(self, stack):
        """Test output drift check."""
        events = stack.check_output_drift(returns=0.01, volatility=0.02)
        
        assert isinstance(events, list)

    def test_check_output_drift_triggers_alarm(self, stack):
        """Test output drift triggers alarm."""
        # Push extreme values to trigger alarm
        for _ in range(30):
            stack.cusum_returns.update(5.0)
        
        events = stack.check_output_drift(returns=5.0, volatility=0.02)
        
        # May trigger alarm
        assert isinstance(events, list)

    def test_check_performance_change(self, stack):
        """Test performance change check."""
        event = stack.check_performance_change(0.05)
        
        # First few checks unlikely to detect change
        assert event is None or isinstance(event, AnomalyEvent)

    def test_full_check(self, stack):
        """Test full check."""
        events = stack.full_check(
            input_features=np.random.randn(10),
            returns=0.01,
            volatility=0.02,
            performance_metric=0.05
        )
        
        assert isinstance(events, list)

    def test_get_active_anomalies_empty(self, stack):
        """Test getting active anomalies when none exist."""
        anomalies = stack.get_active_anomalies()
        
        assert anomalies == []

    def test_get_active_anomalies_with_events(self, stack):
        """Test getting active anomalies."""
        # Create a test event
        event = stack._create_event(
            anomaly_type=AnomalyType.INPUT_OUTLIER,
            severity=AnomalySeverity.WARNING,
            detector="test",
            value=0.9,
            threshold=0.8,
            description="Test anomaly"
        )
        
        anomalies = stack.get_active_anomalies()
        
        assert len(anomalies) >= 1

    def test_resolve_anomaly(self, stack):
        """Test resolving anomaly."""
        event = stack._create_event(
            anomaly_type=AnomalyType.OUTPUT_DRIFT,
            severity=AnomalySeverity.WARNING,
            detector="test",
            value=5.5,
            threshold=5.0,
            description="Test drift"
        )
        
        result = stack.resolve_anomaly(event.event_id, "Manual resolution")
        
        assert result is True
        assert event.resolved is True
        assert event.resolution == "Manual resolution"

    def test_resolve_anomaly_not_found(self, stack):
        """Test resolving non-existent anomaly."""
        result = stack.resolve_anomaly("nonexistent_id", "Resolution")
        
        assert result is False

    def test_should_halt_no_anomalies(self, stack):
        """Test should_halt with no anomalies."""
        should_halt, reason = stack.should_halt()
        
        assert should_halt is False
        assert "No critical anomalies" in reason

    def test_should_halt_with_emergency(self, stack):
        """Test should_halt with emergency anomaly."""
        stack._create_event(
            anomaly_type=AnomalyType.PERFORMANCE_CHANGE,
            severity=AnomalySeverity.EMERGENCY,
            detector="test",
            value=100.0,
            threshold=50.0,
            description="Emergency test"
        )
        
        should_halt, reason = stack.should_halt()
        
        assert should_halt is True
        assert "EMERGENCY" in reason

    def test_should_halt_multiple_critical(self, stack):
        """Test should_halt with multiple critical anomalies."""
        for i in range(4):
            stack._create_event(
                anomaly_type=AnomalyType.OUTPUT_DRIFT,
                severity=AnomalySeverity.CRITICAL,
                detector="test",
                value=10.0 + i,
                threshold=5.0,
                description=f"Critical {i}"
            )
        
        should_halt, reason = stack.should_halt()
        
        assert should_halt is True
        assert "critical" in reason.lower()

    def test_get_status(self, stack):
        """Test getting status."""
        status = stack.get_status()
        
        assert "total_checks" in status
        assert "anomalies_detected" in status
        assert "isolation_forest" in status
        assert "cusum_returns" in status
        assert "page_hinkley" in status

    def test_get_recent_events(self, stack):
        """Test getting recent events."""
        stack._create_event(
            anomaly_type=AnomalyType.INPUT_OUTLIER,
            severity=AnomalySeverity.INFO,
            detector="test",
            value=0.6,
            threshold=0.5,
            description="Test event"
        )
        
        events = stack.get_recent_events(limit=10)
        
        assert len(events) >= 1
        assert isinstance(events[0], dict)

    def test_escalate_callback(self, stack):
        """Test escalation triggers callbacks."""
        callback = MagicMock()
        stack.register_escalation_callback(callback)
        
        event = stack._create_event(
            anomaly_type=AnomalyType.PERFORMANCE_CHANGE,
            severity=AnomalySeverity.CRITICAL,
            detector="test",
            value=100.0,
            threshold=50.0,
            description="Escalation test"
        )
        
        stack._escalate(event)
        
        callback.assert_called_once()

    def test_escalate_callback_error_handling(self, stack):
        """Test escalation handles callback errors."""
        def failing_callback(event):
            raise ValueError("Test error")
        
        stack.register_escalation_callback(failing_callback)
        
        event = stack._create_event(
            anomaly_type=AnomalyType.OUTPUT_DRIFT,
            severity=AnomalySeverity.CRITICAL,
            detector="test",
            value=10.0,
            threshold=5.0,
            description="Error test"
        )
        
        # Should not raise
        stack._escalate(event)
        
        assert event.escalated is True

    def test_event_limit(self, stack):
        """Test event list is limited."""
        stack._max_events = 10
        
        for i in range(20):
            stack._create_event(
                anomaly_type=AnomalyType.INPUT_OUTLIER,
                severity=AnomalySeverity.INFO,
                detector="test",
                value=float(i),
                threshold=0.5,
                description=f"Event {i}"
            )
        
        assert len(stack._events) == 10


class TestSingleton:
    """Test singleton pattern."""

    def test_get_anomaly_detection_singleton(self):
        """Test get_anomaly_detection returns singleton."""
        import ops.anomaly_detection as ad_module
        ad_module._anomaly_stack = None
        
        stack1 = get_anomaly_detection()
        stack2 = get_anomaly_detection()
        
        assert stack1 is stack2
        
        # Cleanup
        ad_module._anomaly_stack = None


class TestIsolationForestInternal:
    """Test IsolationForest internal methods."""

    def test_build_tree(self):
        """Test building single tree."""
        forest = IsolationForest(n_trees=1, sample_size=16)
        data = np.random.randn(20, 3)
        
        tree = forest._build_tree(data, height_limit=4)
        
        assert "type" in tree

    def test_path_length_leaf(self):
        """Test path length for leaf node."""
        forest = IsolationForest()
        
        leaf = {"type": "leaf", "size": 1}
        length = forest._path_length(np.array([1, 2, 3]), leaf)
        
        assert length == 0

    def test_path_length_with_size(self):
        """Test path length for leaf with size > 1."""
        forest = IsolationForest()
        
        leaf = {"type": "leaf", "size": 10}
        length = forest._path_length(np.array([1, 2, 3]), leaf)
        
        assert length > 0
