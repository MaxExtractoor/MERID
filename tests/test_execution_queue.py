"""Tests for TopEdgeExecutionQueue — state machine and priority enforcement."""

import pytest
import time
import threading
from decimal import Decimal
from queue import Empty

from merid.execution.execution_queue import (
    TopEdgeExecutionQueue,
    ExecutionQueueEntry,
    QueueSubmissionResult,
    QueueAction,
    TickerState,
    get_execution_queue,
    reset_execution_queue,
)


class TestExecutionQueueBasics:
    """Basic queue operations."""

    def test_queue_initialization(self):
        queue = TopEdgeExecutionQueue(max_queue_size=50)
        assert queue._max_size == 50
        assert queue._queue.qsize() == 0

    def test_submit_valid_entry(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        assert result.action == QueueAction.ENQUEUED
        assert result.ticker == "KXBTC-TEST"
        assert result.entry_id is not None
        assert queue._queue.qsize() == 1

    def test_submit_fails_without_risk_ok(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=False,  # Should reject
            recon_ok=True,
            agent_id="test_agent",
        )
        
        assert result.action == QueueAction.REJECTED_RISK
        assert queue._queue.qsize() == 0

    def test_submit_fails_without_recon_ok(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=False,  # Should reject
            agent_id="test_agent",
        )
        
        assert result.action == QueueAction.REJECTED_RECON
        assert queue._queue.qsize() == 0

    def test_submit_fails_with_zero_bankroll(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("0"),  # Should reject
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        assert result.action == QueueAction.REJECTED_BANKROLL
        assert queue._queue.qsize() == 0


class TestPerTickerStateMachine:
    """Per-ticker state machine (IDLE → PENDING → OPEN → IDLE)."""

    def test_ticker_starts_idle(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        state = queue.get_ticker_state("KXBTC-TEST")
        assert state == TickerState.IDLE
        assert queue.is_ticker_available("KXBTC-TEST") is True

    def test_ticker_goes_pending_on_submit(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        state = queue.get_ticker_state("KXBTC-TEST")
        assert state == TickerState.PENDING
        assert queue.is_ticker_available("KXBTC-TEST") is False

    def test_reject_second_submit_while_pending(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        # First submission
        queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_1",
        )
        
        # Second submission should be rejected
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="short",
            size_contracts=5,
            edge=0.20,  # Higher edge but should still be rejected
            confidence=0.9,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_2",
        )
        
        assert result.action == QueueAction.REJECTED_STATE
        assert result.current_ticker_state == TickerState.PENDING

    def test_ticker_goes_open_on_executed(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        # Mark as executed (order accepted by venue)
        queue.mark_executed(result.entry_id, "KXBTC-TEST", success=True)
        
        state = queue.get_ticker_state("KXBTC-TEST")
        assert state == TickerState.OPEN
        assert queue.is_ticker_available("KXBTC-TEST") is False

    def test_ticker_goes_idle_on_rejected_execution(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        # Mark as rejected (order rejected by venue)
        queue.mark_executed(result.entry_id, "KXBTC-TEST", success=False)
        
        state = queue.get_ticker_state("KXBTC-TEST")
        assert state == TickerState.IDLE
        assert queue.is_ticker_available("KXBTC-TEST") is True

    def test_ticker_goes_idle_on_closed(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        queue.mark_executed(result.entry_id, "KXBTC-TEST", success=True)
        queue.mark_closed("KXBTC-TEST", result.entry_id)
        
        state = queue.get_ticker_state("KXBTC-TEST")
        assert state == TickerState.IDLE
        assert queue.is_ticker_available("KXBTC-TEST") is True


class TestPriorityQueue:
    """Priority queue ordering (edge * confidence)."""

    def test_higher_edge_comes_first(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        # Submit lower edge first
        queue.submit(
            ticker="KXBTC-LOW",
            direction="long",
            size_contracts=10,
            edge=0.10,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_low",
        )
        
        # Submit higher edge second (different ticker)
        queue.submit(
            ticker="KXETH-HIGH",
            direction="long",
            size_contracts=10,
            edge=0.25,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_high",
        )
        
        # Higher edge should come out first
        entry = queue.get_next_for_execution(timeout_seconds=1.0)
        assert entry is not None
        assert entry.ticker == "KXETH-HIGH"  # Higher edge
        assert entry.edge == 0.25

    def test_priority_score_calculation(self):
        entry = ExecutionQueueEntry.from_signal(
            ticker="TEST",
            direction="long",
            size_contracts=10,
            edge=0.20,
            confidence=0.80,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test",
        )
        
        # Priority = -(edge * confidence * 1000)
        expected_priority = -(0.20 * 0.80 * 1000.0)  # -160.0
        assert entry.priority_score == expected_priority


class TestMetrics:
    """Metrics and observability."""

    def test_metrics_tracked(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        # Submit some entries
        queue.submit(
            ticker="KXBTC-1",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_1",
        )
        
        queue.submit(
            ticker="KXBTC-2",
            direction="long",
            size_contracts=10,
            edge=0.10,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_2",
        )
        
        # One rejection
        queue.submit(
            ticker="KXBTC-1",  # Same ticker, should reject
            direction="long",
            size_contracts=10,
            edge=0.20,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_3",
        )
        
        metrics = queue.get_metrics()
        
        assert metrics["submissions"]["total"] == 3
        assert metrics["submissions"]["accepted"] == 2
        assert metrics["submissions"]["rejected_state"] == 1
        assert metrics["tickers_not_idle"] == 2


class TestThreadSafety:
    """Thread safety under concurrent access."""

    def test_concurrent_submissions(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        results = []
        threads = []
        
        def submit(ticker):
            result = queue.submit(
                ticker=ticker,
                direction="long",
                size_contracts=10,
                edge=0.15,
                confidence=0.8,
                bankroll_snapshot_usd=Decimal("1000"),
                risk_ok=True,
                recon_ok=True,
                agent_id=f"agent_{ticker}",
            )
            results.append(result)
        
        # Submit from multiple threads
        for i in range(10):
            t = threading.Thread(target=submit, args=(f"TICKER-{i}",))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All should succeed (different tickers)
        accepted = sum(1 for r in results if r.action == QueueAction.ENQUEUED)
        assert accepted == 10
        assert queue._queue.qsize() == 10


class TestCooldown:
    """Rejection cooldown behavior."""

    def test_default_cooldown_values(self):
        """Test that default cooldown values match 15m alignment (2026-07-11)."""
        reset_execution_queue()
        queue = get_execution_queue()
        
        # Verify default cooldown values for 15m market alignment
        assert queue._cooldown_seconds == 5.0, "Default rejection cooldown should be 5s (2026-07-11: reduced from 30s)"
        assert queue._pending_timeout == 15.0, "Default pending timeout should be 15s (2026-07-11: reduced from 30s)"

    def test_cooldown_blocks_reentry(self):
        reset_execution_queue()
        queue = get_execution_queue(
            cooldown_after_rejection_seconds=60.0  # Long cooldown for test
        )
        
        # Submit and fill first entry
        result1 = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_1",
        )
        
        # Try second entry (should be rejected - state=PENDING)
        result2 = queue.submit(
            ticker="KXBTC-TEST",
            direction="short",
            size_contracts=5,
            edge=0.20,
            confidence=0.9,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="agent_2",
        )
        
        assert result2.action == QueueAction.REJECTED_STATE
        
        # Ticker should be in cooldown
        ticker_state = queue._get_ticker_state("KXBTC-TEST")
        assert ticker_state.last_rejection_time is not None
        assert queue.is_ticker_available("KXBTC-TEST") is False


class TestEmergencyReset:
    """Emergency ticker reset."""

    def test_reset_ticker_to_idle(self):
        reset_execution_queue()
        queue = get_execution_queue()
        
        result = queue.submit(
            ticker="KXBTC-TEST",
            direction="long",
            size_contracts=10,
            edge=0.15,
            confidence=0.8,
            bankroll_snapshot_usd=Decimal("1000"),
            risk_ok=True,
            recon_ok=True,
            agent_id="test_agent",
        )
        
        queue.mark_executed(result.entry_id, "KXBTC-TEST", success=True)
        assert queue.get_ticker_state("KXBTC-TEST") == TickerState.OPEN
        
        # Emergency reset
        queue.reset_ticker("KXBTC-TEST")
        
        assert queue.get_ticker_state("KXBTC-TEST") == TickerState.IDLE
        assert queue.is_ticker_available("KXBTC-TEST") is True
