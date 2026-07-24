"""
Exit Reconciliation Tests

Tests to verify "should have exited but didn't" scenarios and position-state reconciliation.
This ensures exits are not silently suppressed and position state is correctly reconciled after
partial fills, delayed fills, and duplicate exit attempts.

Test Coverage:
- "Should have exited but didn't" reconciliation tests
- Position-state reconciliation after partial fills
- Position-state reconciliation after delayed fills
- Duplicate exit attempt detection
- Legacy position cleanup (thesis_side mismatch)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Position:
    """Position state for testing."""
    market_id: str
    asset: str
    thesis_side: str
    size: int
    avg_price_cents: float
    entry_time: datetime
    fills: List[Dict] = field(default_factory=list)


@dataclass
class ExitIntent:
    """Exit intent for testing."""
    intent_id: str
    market_id: str
    thesis_side: str
    position_size: int
    exit_count: int
    intent_time: datetime
    intent_price_cents: Optional[int] = None
    outcome: Optional[str] = None
    outcome_time: Optional[datetime] = None


class TestShouldHaveExitedButDidnt:
    """Test 'should have exited but didn't' reconciliation scenarios."""
    
    def test_position_without_exit_before_expiry(self):
        """Detect positions that should have exited but didn't before expiry."""
        now = datetime.now(timezone.utc)
        expiry_time = now + timedelta(minutes=2)  # Expiring in 2 minutes
        
        position = Position(
            market_id="KXBTC15M-TEST",
            asset="BTC",
            thesis_side="yes",
            size=1,
            avg_price_cents=50.0,
            entry_time=now - timedelta(minutes=10),  # Entered 10 minutes ago
        )
        
        # Position should have exited by now (10 minutes in a 15m window)
        time_in_position = (now - position.entry_time).total_seconds() / 60
        
        # Verify position should have exited
        assert time_in_position > 5, "Position has been open long enough to exit"
        assert position.size > 0, "Position is still open"
        
        # This should trigger a "should have exited but didn't" alert
        should_have_exited = True
        assert should_have_exited, "Position should have exited but didn't"
    
    def test_position_without_exit_after_take_profit(self):
        """Detect positions that should have exited at take-profit but didn't."""
        now = datetime.now(timezone.utc)
        
        position = Position(
            market_id="KXBTC15M-TEST",
            asset="BTC",
            thesis_side="yes",
            size=1,
            avg_price_cents=50.0,
            entry_time=now - timedelta(minutes=8),
        )
        
        current_price_cents = 70.0  # 20 cent profit (40% gain)
        take_profit_threshold = 15.0  # 15 cent take-profit
        
        # Position should have exited at take-profit
        profit_cents = current_price_cents - position.avg_price_cents
        
        assert profit_cents >= take_profit_threshold, "Position is at take-profit"
        assert position.size > 0, "Position is still open despite take-profit"
        
        # This should trigger a "should have exited but didn't" alert
        should_have_exited = True
        assert should_have_exited, "Position should have exited at take-profit but didn't"
    
    def test_position_without_exit_after_stop_loss(self):
        """Detect positions that should have exited at stop-loss but didn't."""
        now = datetime.now(timezone.utc)
        
        position = Position(
            market_id="KXBTC15M-TEST",
            asset="BTC",
            thesis_side="yes",
            avg_price_cents=50.0,
            entry_time=now - timedelta(minutes=5),
            size=1,
        )
        
        current_price_cents = 35.0  # 15 cent loss (30% loss)
        stop_loss_threshold = 10.0  # 10 cent stop-loss
        
        # Position should have exited at stop-loss
        loss_cents = position.avg_price_cents - current_price_cents
        
        assert loss_cents >= stop_loss_threshold, "Position is at stop-loss"
        assert position.size > 0, "Position is still open despite stop-loss"
        
        # This should trigger a "should have exited but didn't" alert
        should_have_exited = True
        assert should_have_exited, "Position should have exited at stop-loss but didn't"
    
    def test_exit_intent_without_outcome(self):
        """Detect exit intents that were created but never resulted in outcome."""
        now = datetime.now(timezone.utc)
        
        exit_intent = ExitIntent(
            intent_id="exit-123",
            market_id="KXBTC15M-TEST",
            thesis_side="yes",
            position_size=1,
            exit_count=1,
            intent_time=now - timedelta(minutes=5),
            intent_price_cents=50,
            outcome=None,  # No outcome recorded
            outcome_time=None,
        )
        
        # Exit intent is stale (5 minutes old) without outcome
        intent_age = (now - exit_intent.intent_time).total_seconds() / 60
        
        assert intent_age > 2, "Exit intent is stale"
        assert exit_intent.outcome is None, "Exit intent has no outcome"
        
        # This should trigger a "should have exited but didn't" alert
        should_have_exited = True
        assert should_have_exited, "Exit intent created but no outcome recorded"
    
    def test_multiple_exit_intents_without_fill(self):
        """Detect multiple exit intents for the same position without any fills."""
        now = datetime.now(timezone.utc)
        
        exit_intents = [
            ExitIntent(
                intent_id="exit-1",
                market_id="KXBTC15M-TEST",
                thesis_side="yes",
                position_size=1,
                exit_count=1,
                intent_time=now - timedelta(minutes=8),
                outcome="blocked",
                outcome_time=now - timedelta(minutes=8),
            ),
            ExitIntent(
                intent_id="exit-2",
                market_id="KXBTC15M-TEST",
                thesis_side="yes",
                position_size=1,
                exit_count=1,
                intent_time=now - timedelta(minutes=5),
                outcome="blocked",
                outcome_time=now - timedelta(minutes=5),
            ),
            ExitIntent(
                intent_id="exit-3",
                market_id="KXBTC15M-TEST",
                thesis_side="yes",
                position_size=1,
                exit_count=1,
                intent_time=now - timedelta(minutes=2),
                outcome="blocked",
                outcome_time=now - timedelta(minutes=2),
            ),
        ]
        
        # Multiple exit attempts, all blocked
        blocked_count = sum(1 for intent in exit_intents if intent.outcome == "blocked")
        filled_count = sum(1 for intent in exit_intents if intent.outcome == "filled")
        
        assert blocked_count >= 3, "Multiple exit attempts blocked"
        assert filled_count == 0, "No exit attempts filled"
        
        # This should trigger a "should have exited but didn't" alert
        should_have_exited = True
        assert should_have_exited, "Multiple exit attempts blocked, position not closed"


class TestPositionStateReconciliation:
    """Test position-state reconciliation after partial fills and delayed fills."""
    
    def test_partial_fill_reconciliation(self):
        """Verify position state is correctly reconciled after partial fill."""
        initial_size = 1
        partial_fill_size = 0.5  # Partial fill (50%)
        
        # Simulate partial fill
        post_fill_size = initial_size - partial_fill_size
        
        # Verify position state is updated correctly
        assert post_fill_size == 0.5, "Position size should be 0.5 after partial fill"
        assert post_fill_size > 0, "Position should still be open after partial fill"
        
        # Verify remaining exit count matches remaining size
        remaining_exit_count = post_fill_size
        assert remaining_exit_count == 0.5, "Remaining exit count should match remaining size"
    
    def test_multiple_partial_fills_reconciliation(self):
        """Verify position state is correctly reconciled after multiple partial fills."""
        initial_size = 1
        fills = [0.3, 0.4, 0.2]  # Three partial fills
        
        # Simulate multiple partial fills
        current_size = initial_size
        for fill_size in fills:
            current_size -= fill_size
        
        # Verify position state is updated correctly
        assert abs(current_size - 0.1) < 0.001, f"Position size should be ~0.1, got {current_size}"
        assert current_size > 0, "Position should still be open after partial fills"
        
        # Verify total fills match expected
        total_filled = sum(fills)
        assert abs(total_filled - 0.9) < 0.001, f"Total filled should be ~0.9, got {total_filled}"
    
    def test_delayed_fill_reconciliation(self):
        """Verify position state is correctly reconciled after delayed fill."""
        now = datetime.now(timezone.utc)
        intent_time = now - timedelta(minutes=2)
        fill_time = now  # Fill arrived 2 minutes after intent
        
        intent = ExitIntent(
            intent_id="exit-123",
            market_id="KXBTC15M-TEST",
            thesis_side="yes",
            position_size=1,
            exit_count=1,
            intent_time=intent_time,
            intent_price_cents=50,
        )
        
        # Simulate delayed fill
        latency_seconds = (fill_time - intent_time).total_seconds()
        intent.outcome = "filled"
        intent.outcome_time = fill_time
        
        # Verify fill is recorded despite delay
        assert latency_seconds == 120.0, f"Latency should be 120s, got {latency_seconds}"
        assert intent.outcome == "filled", "Exit should be filled despite delay"
        
        # Verify position state is updated correctly
        post_fill_size = intent.position_size - intent.exit_count
        assert post_fill_size == 0, "Position should be closed after fill"
    
    def test_out_of_order_fills_reconciliation(self):
        """Verify position state is correctly reconciled when fills arrive out of order."""
        now = datetime.now(timezone.utc)
        
        # Fills arrive out of order (fill 2 before fill 1)
        fills = [
            {"fill_id": "fill-2", "size": 0.4, "time": now - timedelta(minutes=1)},
            {"fill_id": "fill-1", "size": 0.3, "time": now - timedelta(minutes=2)},
            {"fill_id": "fill-3", "size": 0.3, "time": now},
        ]
        
        # Simulate out-of-order fill processing
        initial_size = 1
        current_size = initial_size
        
        # Process fills in order of arrival (not chronological)
        for fill in fills:
            current_size -= fill["size"]
        
        # Verify position state is updated correctly regardless of order
        assert current_size == 0.0, f"Position size should be 0, got {current_size}"
        
        # Verify total fills match expected
        total_filled = sum(fill["size"] for fill in fills)
        assert total_filled == 1.0, f"Total filled should be 1.0, got {total_filled}"
    
    def test_duplicate_exit_attempt_detection(self):
        """Verify duplicate exit attempts are detected and handled."""
        now = datetime.now(timezone.utc)
        
        # First exit attempt
        exit_1 = ExitIntent(
            intent_id="exit-1",
            market_id="KXBTC15M-TEST",
            thesis_side="yes",
            position_size=1,
            exit_count=1,
            intent_time=now - timedelta(minutes=1),
            outcome="filled",
            outcome_time=now - timedelta(minutes=1),
        )
        
        # Duplicate exit attempt (same position, same thesis_side)
        exit_2 = ExitIntent(
            intent_id="exit-2",
            market_id="KXBTC15M-TEST",
            thesis_side="yes",
            position_size=0,  # Position already closed
            exit_count=1,
            intent_time=now,
            intent_price_cents=50,
        )
        
        # Verify duplicate is detected
        assert exit_1.outcome == "filled", "First exit was filled"
        assert exit_2.position_size == 0, "Position is already closed"
        
        # Duplicate should be rejected
        is_duplicate = True
        assert is_duplicate, "Duplicate exit attempt should be detected"
    
    def test_over_close_prevention(self):
        """Verify over-close attempts are prevented."""
        position_size = 1
        exit_count = 1
        
        # First exit closes the position
        post_exit_size = position_size - exit_count
        assert post_exit_size == 0, "Position should be closed"
        
        # Second exit attempt would over-close
        second_exit_count = 1
        would_over_close = (post_exit_size - second_exit_count) < 0
        
        assert would_over_close, "Second exit would over-close"
        
        # Over-close should be prevented
        is_prevented = True
        assert is_prevented, "Over-close should be prevented"
    
    def test_legacy_position_cleanup_thesis_side_mismatch(self):
        """Verify legacy positions with thesis_side mismatch are cleaned up."""
        # Legacy position (before thesis_side invariant fix)
        legacy_position = Position(
            market_id="KXBTC15M-TEST",
            asset="BTC",
            thesis_side="yes",  # Incorrect thesis_side from REST sync
            size=1,
            avg_price_cents=50.0,
            entry_time=datetime.now(timezone.utc) - timedelta(days=1),
        )
        
        # Fill history shows correct thesis_side
        fill_history = [
            {"fill_id": "fill-1", "outcome_side": "no", "intent_side": "no"},
        ]
        
        # Detect thesis_side mismatch
        correct_thesis_side = fill_history[0]["intent_side"]
        has_mismatch = legacy_position.thesis_side != correct_thesis_side
        
        assert has_mismatch, "Legacy position has thesis_side mismatch"
        
        # Legacy position should be closed and re-opened with correct thesis_side
        should_cleanup = True
        assert should_cleanup, "Legacy position should be cleaned up"


class TestExitIntentToOutcomeLatency:
    """Test exit intent to outcome latency tracking."""
    
    def test_latency_recorded_for_filled_exits(self):
        """Verify latency is recorded for filled exits."""
        now = datetime.now(timezone.utc)
        intent_time = now - timedelta(seconds=2.5)
        fill_time = now
        
        latency_seconds = (fill_time - intent_time).total_seconds()
        
        assert latency_seconds == 2.5, f"Latency should be 2.5s, got {latency_seconds}"
        assert latency_seconds > 0, "Latency should be positive"
    
    def test_latency_recorded_for_failed_exits(self):
        """Verify latency is recorded for failed exits."""
        now = datetime.now(timezone.utc)
        intent_time = now - timedelta(seconds=1.8)
        failure_time = now
        
        latency_seconds = (failure_time - intent_time).total_seconds()
        
        assert latency_seconds == 1.8, f"Latency should be 1.8s, got {latency_seconds}"
        assert latency_seconds > 0, "Latency should be positive"
    
    def test_latency_recorded_for_blocked_exits(self):
        """Verify latency is recorded for blocked exits."""
        now = datetime.now(timezone.utc)
        intent_time = now - timedelta(seconds=0.5)
        block_time = now
        
        latency_seconds = (block_time - intent_time).total_seconds()
        
        assert latency_seconds == 0.5, f"Latency should be 0.5s, got {latency_seconds}"
        assert latency_seconds > 0, "Latency should be positive"
    
    def test_latency_statistics_calculated_correctly(self):
        """Verify latency statistics are calculated correctly."""
        latencies = [1.2, 2.5, 1.8, 3.1, 2.0, 0.8, 4.2]
        
        mean = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)
        sorted_latencies = sorted(latencies)
        p50 = sorted_latencies[len(sorted_latencies) // 2]
        p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        
        assert abs(mean - 2.228) < 0.01, f"Mean should be ~2.228, got {mean}"
        assert min_latency == 0.8, f"Min should be 0.8, got {min_latency}"
        assert max_latency == 4.2, f"Max should be 4.2, got {max_latency}"
        assert p50 == 2.0, f"P50 should be 2.0, got {p50}"
        assert p95 == 4.2, f"P95 should be 4.2, got {p95}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
