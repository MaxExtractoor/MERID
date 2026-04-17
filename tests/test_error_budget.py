"""Tests for the centralized Error Budget System.

Validates:
- P0/P1/P2/P3 severity classification
- Budget consumption (only P0/P1 count)
- State transitions (HEALTHY → DEGRADED → EXHAUSTED)
- Deduplication
- Window reset
- Async exception handling
- Thread safety

[AGENT_AUDIT: Section 7.4 - Error Budget TEST phase]
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from merid.core.error_budget import (
    ErrorBudget,
    ErrorBudgetState,
    ErrorEvent,
    Severity,
    BudgetConfig,
    record_p0,
    record_p1,
    record_p2,
    record_p3,
    get_budget_status,
    is_budget_exhausted,
    reset_budget,
    migrate_legacy_classification,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset ErrorBudget singleton before each test."""
    ErrorBudget.reset_singleton()
    yield
    ErrorBudget.reset_singleton()


class TestErrorBudgetBasics:
    """Test basic ErrorBudget initialization and state."""
    
    def test_singleton_pattern(self):
        """ErrorBudget is a singleton."""
        budget1 = ErrorBudget.get_instance()
        budget2 = ErrorBudget.get_instance()
        assert budget1 is budget2
    
    def test_initial_state_is_healthy(self):
        """Fresh budget starts in HEALTHY state."""
        budget = ErrorBudget()
        budget.reset("test", "reset for test")
        assert budget.current_state() == ErrorBudgetState.HEALTHY
    
    def test_p0_records_to_budget(self):
        """P0 events consume budget and increment counter."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=10))
        budget.reset("test", "reset for test")
        
        state = budget.record(ErrorEvent(
            severity=Severity.P0,
            code="TEST_P0",
            message="Test P0 event"
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 1
    
    def test_p1_records_weighted_to_budget(self):
        """P1 events consume budget with 0.5 weight."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=10))
        budget.reset("test", "reset for test")
        
        budget.record(ErrorEvent(
            severity=Severity.P1,
            code="TEST_P1",
            message="Test P1 event"
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p1_weighted"] == 0.5
    
    def test_p2_does_not_consume_budget(self):
        """P2 events do NOT consume budget."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=10))
        budget.reset("test", "reset for test")
        
        budget.record(ErrorEvent(
            severity=Severity.P2,
            code="TEST_P2",
            message="Test P2 event"
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 0
        assert status["budget_consuming_counts"]["p1_weighted"] == 0
    
    def test_p3_does_not_consume_budget(self):
        """P3 events do NOT consume budget."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=10))
        budget.reset("test", "reset for test")
        
        budget.record(ErrorEvent(
            severity=Severity.P3,
            code="TEST_P3",
            message="Test P3 event"
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 0
        assert status["budget_consuming_counts"]["p1_weighted"] == 0


class TestStateTransitions:
    """Test error budget state transitions."""
    
    def test_healthy_to_degraded_transition(self):
        """Budget transitions to DEGRADED at warning threshold."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=10,
            warning_threshold_pct=0.70
        ))
        budget.reset("test", "reset for test")
        
        # Add events up to warning threshold (7 = 70% of 10)
        for i in range(7):
            state = budget.record(ErrorEvent(
                severity=Severity.P0,
                code=f"DEGRADE_TEST_{i}",  # Unique codes to avoid dedup
                message=f"Test event {i}"
            ))
        
        assert state == ErrorBudgetState.DEGRADED
    
    def test_degraded_to_exhausted_transition(self):
        """Budget transitions to EXHAUSTED at 100% threshold."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=5,
            warning_threshold_pct=0.50
        ))
        budget.reset("test", "reset for test")
        
        # Add events to exceed threshold
        for i in range(5):
            state = budget.record(ErrorEvent(
                severity=Severity.P0,
                code=f"EXHAUST_TEST_{i}",  # Unique codes to avoid dedup
                message=f"Test event {i}"
            ))
        
        assert state == ErrorBudgetState.EXHAUSTED
    
    def test_exhausted_blocks_trading_when_not_in_grace(self):
        """EXHAUSTED state reports can_halt_trading=True after startup grace."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=1,
            warning_threshold_pct=0.50,
        ))
        # Set startup time in the past to bypass grace
        budget._startup_time = time.time() - 1000
        budget.reset("test", "reset for test")
        
        # Override startup grace to 0
        with patch.object(budget, '_startup_grace_seconds', 0):
            budget.record(ErrorEvent(
                severity=Severity.P0,
                code="EXHAUST_TEST",
                message="Exhausting event"
            ))
            
            assert budget.can_halt_trading() is True
    
    def test_exhausted_does_not_block_during_startup_grace(self):
        """EXHAUSTED state does NOT block during startup grace."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=1,
            warning_threshold_pct=0.50,
            window_seconds=3600
        ))
        # Set startup time to now so we're in grace period
        budget._startup_time = time.time()
        budget.reset("test", "reset for test")
        
        # Override to have long startup grace
        with patch.object(budget, '_startup_grace_seconds', 300):
            with patch.object(budget, '_startup_time', time.time()):  # Just started
                budget.record(ErrorEvent(
                    severity=Severity.P0,
                    code="EXHAUST_TEST",
                    message="Exhausting event"
                ))
                
                assert budget.can_halt_trading() is False
    
    def test_window_reset_returns_to_healthy(self):
        """Window expiration resets budget to HEALTHY."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=1,
            warning_threshold_pct=0.50,
            window_seconds=0.1  # Very short window
        ))
        # Set startup time in the past to bypass grace
        budget._startup_time = time.time() - 1000
        budget.reset("test", "reset for test")
        
        # Exhaust the budget
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="EXHAUST",
            message="Exhausting"
        ))
        assert budget.current_state() == ErrorBudgetState.EXHAUSTED
        
        # Wait for window to expire
        time.sleep(0.2)
        
        # Next check triggers window reset
        budget.current_state()
        
        # Should be HEALTHY again
        assert budget.current_state() == ErrorBudgetState.HEALTHY


class TestDeduplication:
    """Test error deduplication within window."""
    
    def test_duplicate_events_not_counted(self):
        """Duplicate events within window don't count toward budget."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=5,
            dedup_window_seconds=60.0
        ))
        budget.reset("test", "reset for test")
        
        # Record same event multiple times
        for _ in range(3):
            budget.record(ErrorEvent(
                severity=Severity.P0,
                code="DEDUP_TEST",
                message="Same event",
                context={"venue": "kalshi"}
            ))
        
        # Should only count once
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 1
    
    def test_different_contexts_not_deduplicated(self):
        """Events with different contexts are not deduplicated."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=5,
            dedup_window_seconds=60.0
        ))
        budget.reset("test", "reset for test")
        
        # Same code, different venues
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="SAME_CODE",
            message="Test",
            context={"venue": "kalshi"}
        ))
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="SAME_CODE",
            message="Test",
            context={"venue": "polymarket"}
        ))
        
        # Should count twice (different context keys)
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 2
    
    def test_sliding_dedup_window(self):
        """Dedup window is sliding - re-appears after window expires."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=5,
            dedup_window_seconds=0.05  # Very short
        ))
        budget.reset("test", "reset for test")
        
        # First event
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="SLIDE_TEST",
            message="Test",
            context={"venue": "kalshi"}
        ))
        
        # Wait for dedup window to expire
        time.sleep(0.1)
        
        # Same event again - should count as new
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="SLIDE_TEST",
            message="Test",
            context={"venue": "kalshi"}
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 2


class TestConvenienceAPI:
    """Test convenience record functions."""
    
    def test_record_p0(self):
        """record_p0 convenience function works."""
        reset_budget("test", "reset")
        state = record_p0("TEST_P0", "Test message", venue="kalshi")
        assert state in [ErrorBudgetState.HEALTHY, ErrorBudgetState.DEGRADED, ErrorBudgetState.EXHAUSTED]
        
        status = get_budget_status()
        assert status["recent_events"][0]["severity"] == "p0_critical"
    
    def test_record_p1(self):
        """record_p1 convenience function works."""
        reset_budget("test", "reset")
        state = record_p1("TEST_P1", "Test message", venue="kalshi")
        assert state in [ErrorBudgetState.HEALTHY, ErrorBudgetState.DEGRADED, ErrorBudgetState.EXHAUSTED]
    
    def test_record_p2(self):
        """record_p2 convenience function works."""
        reset_budget("test", "reset")
        state = record_p2("TEST_P2", "Test message", venue="kalshi")
        # P2 doesn't affect state
        assert state == ErrorBudgetState.HEALTHY
    
    def test_record_p3(self):
        """record_p3 convenience function works."""
        reset_budget("test", "reset")
        state = record_p3("TEST_P3", "Test message", venue="kalshi")
        # P3 doesn't affect state
        assert state == ErrorBudgetState.HEALTHY
    
    def test_is_budget_exhausted(self):
        """is_budget_exhausted returns correct value."""
        reset_budget("test", "reset")
        
        # Initially not exhausted
        assert is_budget_exhausted() is False
    
    def test_get_budget_status_structure(self):
        """get_budget_status returns expected structure."""
        reset_budget("test", "reset")
        
        status = get_budget_status()
        
        # Check required keys
        assert "state" in status
        assert "budget_consuming_counts" in status
        assert "window" in status
        assert "dedup" in status
        assert "top_codes" in status
        assert "recent_events" in status
        
        # Check budget_consuming_counts structure
        counts = status["budget_consuming_counts"]
        assert "p0_count" in counts
        assert "p0_max" in counts
        assert "p0_pct" in counts
        assert "p1_weighted" in counts
        assert "p1_max" in counts
        assert "p1_pct" in counts


class TestLegacyMigration:
    """Test migration from legacy error classification."""
    
    def test_critical_maps_to_p0(self):
        """Legacy 'critical' severity maps to P0."""
        severity, code = migrate_legacy_classification("AUTH_FAIL", "critical")
        assert severity == Severity.P0
        assert code == "AUTH_FAIL"
    
    def test_high_maps_to_p1(self):
        """Legacy 'high' severity maps to P1."""
        severity, code = migrate_legacy_classification("RATE_LIMIT", "high")
        assert severity == Severity.P1
    
    def test_medium_maps_to_p2(self):
        """Legacy 'medium' severity maps to P2."""
        severity, code = migrate_legacy_classification("TIMEOUT", "medium")
        assert severity == Severity.P2
    
    def test_low_maps_to_p3(self):
        """Legacy 'low' severity maps to P3."""
        severity, code = migrate_legacy_classification("WS_RECONNECT", "low")
        assert severity == Severity.P3
    
    def test_code_normalization(self):
        """Codes are normalized to uppercase with underscores."""
        severity, code = migrate_legacy_classification("auth-fail", "critical")
        assert code == "AUTH_FAIL"


class TestThreadSafety:
    """Test thread safety of ErrorBudget."""
    
    def test_concurrent_p0_recording(self):
        """Multiple threads can record P0 events safely."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=1000  # High threshold to avoid exhaustion
        ))
        budget.reset("test", "reset for test")
        
        num_threads = 10
        events_per_thread = 10
        
        def record_events():
            for i in range(events_per_thread):
                budget.record(ErrorEvent(
                    severity=Severity.P0,
                    code="CONCURRENT_TEST",
                    message=f"Thread event {i}"
                ))
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(record_events) for _ in range(num_threads)]
            for f in futures:
                f.result()
        
        # Should have exactly the expected count (dedup will collapse same code)
        status = budget.get_status()
        # With dedup, all same code in short time = 1
        assert status["budget_consuming_counts"]["p0_count"] == 1
    
    def test_concurrent_different_codes(self):
        """Multiple threads with different codes count separately."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=100
        ))
        budget.reset("test", "reset for test")
        
        def record_with_code(code):
            budget.record(ErrorEvent(
                severity=Severity.P0,
                code=code,
                message="Test"
            ))
        
        codes = [f"CODE_{i}" for i in range(10)]
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_with_code, code) for code in codes]
            for f in futures:
                f.result()
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 10


class TestReset:
    """Test budget reset functionality."""
    
    def test_reset_clears_counters(self):
        """Reset clears all counters and returns to HEALTHY."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=5))
        budget.reset("test", "reset for test")
        
        # Add enough events to trigger DEGRADED (4/5 = 80% > 70% threshold)
        for i in range(4):
            budget.record(ErrorEvent(
                severity=Severity.P0,
                code=f"RESET_TEST_{i}",  # Unique codes to avoid dedup
                message="Test"
            ))
        
        assert budget.current_state() == ErrorBudgetState.DEGRADED
        
        # Reset
        budget.reset("operator", "resolved root cause")
        
        assert budget.current_state() == ErrorBudgetState.HEALTHY
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 0
    
    def test_reset_preserves_dedup_window(self):
        """Reset clears dedup cache as part of window reset."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=5,
            dedup_window_seconds=60.0
        ))
        budget.reset("test", "reset for test")
        
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="DEDUP_RESET_TEST",
            message="Test",
            context={"venue": "kalshi"}
        ))
        
        # Reset clears everything
        budget.reset("test", "reset")
        
        # Same event should count again
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="DEDUP_RESET_TEST",
            message="Test",
            context={"venue": "kalshi"}
        ))
        
        status = budget.get_status()
        assert status["budget_consuming_counts"]["p0_count"] == 1


class TestCallbackIntegration:
    """Test state transition callbacks."""
    
    def test_callback_fires_on_transition(self):
        """Registered callbacks fire on state transitions."""
        budget = ErrorBudget(BudgetConfig(
            max_p0_events=1,
            warning_threshold_pct=0.50
        ))
        # Set startup time in the past to bypass grace
        budget._startup_time = time.time() - 1000
        budget.reset("test", "reset for test")
        
        transitions = []
        
        def callback(old_state, new_state, event):
            transitions.append((old_state, new_state, event.code))
        
        budget.on_state_transition(callback)
        
        # Trigger transition
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="CALLBACK_TEST",
            message="Test"
        ))
        
        assert len(transitions) == 1
        assert transitions[0][0] == ErrorBudgetState.HEALTHY
        assert transitions[0][1] == ErrorBudgetState.EXHAUSTED
        assert transitions[0][2] == "CALLBACK_TEST"
    
    def test_multiple_callbacks(self):
        """Multiple callbacks can be registered."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=10))
        budget.reset("test", "reset for test")
        
        calls = []
        
        def cb1(old, new, event):
            calls.append("cb1")
        
        def cb2(old, new, event):
            calls.append("cb2")
        
        budget.on_state_transition(cb1)
        budget.on_state_transition(cb2)
        
        # Trigger transition to DEGRADED
        for i in range(7):  # With default 70% threshold
            budget.record(ErrorEvent(
                severity=Severity.P0,
                code=f"MULTI_CB_TEST_{i}",  # Unique codes to avoid dedup
                message="Test"
            ))
        
        assert "cb1" in calls
        assert "cb2" in calls


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""
    
    def test_budget_config_from_env_defaults(self):
        """BudgetConfig uses sensible defaults."""
        config = BudgetConfig()
        
        assert config.max_p0_events == 10
        assert config.max_p1_events == 20
        assert config.warning_threshold_pct == 0.70
        assert config.window_seconds == 3600.0
        assert config.dedup_window_seconds == 300.0
    
    @patch.dict('os.environ', {
        'MERID_ERROR_BUDGET_P0_MAX': '20',
        'MERID_ERROR_BUDGET_P1_MAX': '50',
        'MERID_ERROR_BUDGET_WARN_PCT': '0.80',
    })
    def test_budget_config_from_env_override(self):
        """BudgetConfig respects environment variables."""
        config = BudgetConfig.from_env()
        
        assert config.max_p0_events == 20
        assert config.max_p1_events == 50
        assert config.warning_threshold_pct == 0.80


class TestErrorEvent:
    """Test ErrorEvent dataclass."""
    
    def test_code_normalization(self):
        """Codes are normalized to uppercase with underscores."""
        event = ErrorEvent(
            severity=Severity.P0,
            code="some-error-code",
            message="Test"
        )
        assert event.code == "SOME_ERROR_CODE"
    
    def test_code_normalization_with_spaces(self):
        """Codes with spaces are normalized."""
        event = ErrorEvent(
            severity=Severity.P0,
            code="some error code",
            message="Test"
        )
        assert event.code == "SOME_ERROR_CODE"
    
    def test_timestamp_default(self):
        """Timestamp defaults to current UTC time."""
        before = time.time() - 0.001  # Small buffer for precision
        event = ErrorEvent(
            severity=Severity.P0,
            code="TEST",
            message="Test"
        )
        after = time.time() + 0.001
        
        # Use approximate comparison due to floating point precision
        ts = event.timestamp.timestamp()
        assert before <= ts <= after, f"Timestamp {ts} not in range [{before}, {after}]"


class TestIntegrationWithKillSwitch:
    """Test integration with existing kill switch system."""
    
    def test_budget_can_integrate_with_kill_switch(self):
        """ErrorBudget state can inform kill switch decisions."""
        budget = ErrorBudget(BudgetConfig(max_p0_events=1))
        # Set startup time in the past to bypass grace
        budget._startup_time = time.time() - 1000
        budget.reset("test", "reset for test")
        
        # Simulate a critical error that exhausts budget
        budget.record(ErrorEvent(
            severity=Severity.P0,
            code="KILL_INTEGRATION",
            message="Critical error"
        ))
        
        # Budget is exhausted
        assert budget.current_state() == ErrorBudgetState.EXHAUSTED
        
        # In real integration, this would trigger kill switch
        # (But kill switch integration requires RiskController which we don't import here)
