"""Loop 4 tests — UI components, Feedback Scheduler, Kalshi Edge Cases.

Covers:
  1. Feedback scheduler (round/time triggers, dry-run, logging)
  2. Preview ledger feedback (audit mode)
  3. Weight history tracking
  4. Kalshi settlement edge cases (voided, partial fill, manual adjustments)
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List

from consensus.consensus_coordinator import (
    AgentIncentiveLedger,
    ConsensusConfig,
    ConsensusRound,
    EnhancedConsensusCoordinator,
    SocialSignal,
    AgentVote,
    get_consensus_coordinator,
)
from consensus.feedback_scheduler import (
    LedgerFeedbackScheduler,
    FeedbackScheduleConfig,
    start_feedback_scheduler,
    get_feedback_scheduler,
)


def _run(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_coordinator(**kw) -> EnhancedConsensusCoordinator:
    """Create a fresh coordinator, resetting the singleton."""
    EnhancedConsensusCoordinator._instance = None
    cfg = ConsensusConfig(**kw)
    return EnhancedConsensusCoordinator(cfg)


# =====================================================================
# 1. Feedback Scheduler Tests
# =====================================================================


class TestFeedbackScheduler(unittest.TestCase):
    """Test LedgerFeedbackScheduler triggers and logging."""

    def setUp(self):
        self.coord = _make_coordinator()
        # Register agents
        for aid in ["a1", "a2", "a3"]:
            self.coord._agent_reliability[aid] = 1.0
        self.config = FeedbackScheduleConfig(
            rounds_interval=5,
            time_interval_seconds=0,  # Disable time trigger for tests
            dry_run=False,
        )
        self.scheduler = LedgerFeedbackScheduler(self.coord, self.config)

    def tearDown(self):
        if hasattr(self.scheduler, 'stop'):
            self.scheduler.stop()
        EnhancedConsensusCoordinator._instance = None

    def test_reconciliation_counting(self):
        """Scheduler should count reconciliations toward round trigger."""
        for _ in range(4):
            self.scheduler.record_reconciliation()
        self.assertEqual(self.scheduler._reconciled_count, 4)

    def test_round_trigger_fires(self):
        """Feedback should trigger after N reconciliations."""
        # Populate some data
        for i in range(10):
            rnd = ConsensusRound(round_id=f"trig-{i}", symbol="BTC")
            rnd.votes = [AgentVote(
                agent_id="a1", agent_role="analyst", vote="approve",
                score=0.6, confidence=0.8, weight=1.0, reasoning="test"
            )]
            rnd.status = "completed"
            self.coord._round_history.append(rnd)
            self.coord.incentive_ledger.record_round_outcome(rnd, "long", 10.0)

        # Record reconciliations to trigger
        for _ in range(5):
            self.scheduler.record_reconciliation()

        # Should trigger on next check
        triggered = _run(self.scheduler._check_and_trigger())
        # Verify it reset the counter
        self.assertEqual(self.scheduler._reconciled_count, 0)

    def test_dry_run_mode(self):
        """Dry-run mode should preview but not apply changes."""
        self.config.dry_run = True
        scheduler = LedgerFeedbackScheduler(self.coord, self.config)
        
        # Populate data
        for i in range(10):
            rnd = ConsensusRound(round_id=f"dry-{i}", symbol="BTC")
            rnd.votes = [AgentVote(
                agent_id="a1", agent_role="analyst", vote="approve",
                score=0.6, confidence=0.8, weight=1.0, reasoning="test"
            )]
            rnd.status = "completed"
            self.coord._round_history.append(rnd)
            self.coord.incentive_ledger.record_round_outcome(rnd, "long", 10.0)

        # Trigger feedback
        scheduler.record_reconciliation()
        _run(scheduler._execute_feedback())

        # Check history shows dry_run mode
        history = scheduler.get_feedback_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["mode"], "dry_run")

    def test_scheduler_status(self):
        """Scheduler should report its status correctly."""
        status = self.scheduler.get_status()
        self.assertIn("running", status)
        self.assertIn("dry_run", status)
        self.assertIn("reconciled_since_last", status)
        self.assertEqual(status["dry_run"], False)


# =====================================================================
# 2. Preview Ledger Feedback Tests
# =====================================================================


class TestPreviewLedgerFeedback(unittest.TestCase):
    """Test preview_ledger_feedback dry-run functionality."""

    def setUp(self):
        self.coord = _make_coordinator()
        for aid in ["a1", "a2"]:
            self.coord._agent_reliability[aid] = 1.0

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    def _populate_agent(self, agent_id: str, correct: int, incorrect: int):
        """Simulate rounds for an agent."""
        for i in range(correct + incorrect):
            rnd = ConsensusRound(round_id=f"preview-{agent_id}-{i}", symbol="BTC")
            is_correct = i < correct
            score = 0.5 if is_correct else -0.5
            rnd.votes = [AgentVote(
                agent_id=agent_id, agent_role="analyst", vote="approve",
                score=score, confidence=0.7, weight=1.0, reasoning="test"
            )]
            rnd.status = "completed"
            self.coord._round_history.append(rnd)
            direction = "long" if is_correct else "short"
            self.coord.incentive_ledger.record_round_outcome(rnd, "long", 10.0 if is_correct else -10.0)

    def test_preview_returns_detailed_info(self):
        """Preview should return detailed weight change preview."""
        self._populate_agent("a1", correct=8, incorrect=2)  # 80% accuracy

        preview = self.coord.preview_ledger_feedback(min_rounds=5)
        self.assertEqual(len(preview), 1)
        
        p = preview[0]
        self.assertEqual(p["agent_id"], "a1")
        self.assertIn("current_weight", p)
        self.assertIn("target_weight", p)
        self.assertIn("new_weight", p)
        self.assertIn("delta", p)
        self.assertIn("accuracy", p)
        self.assertIn("calibration_error", p)
        self.assertIn("rounds", p)

    def test_preview_does_not_apply_changes(self):
        """Preview should not modify actual weights."""
        self._populate_agent("a1", correct=8, incorrect=2)
        original_weight = self.coord._agent_reliability["a1"]

        # Run preview multiple times
        for _ in range(3):
            self.coord.preview_ledger_feedback(min_rounds=5)

        # Weight should be unchanged
        self.assertEqual(self.coord._agent_reliability["a1"], original_weight)

    def test_preview_shows_increases_and_decreases(self):
        """Preview should show both increases and decreases correctly."""
        # Good agent
        self._populate_agent("a1", correct=9, incorrect=1)
        # Bad agent
        self._populate_agent("a2", correct=2, incorrect=8)

        preview = self.coord.preview_ledger_feedback(min_rounds=5)
        self.assertEqual(len(preview), 2)

        deltas = {p["agent_id"]: p["delta"] for p in preview}
        # Good agent should increase
        self.assertGreater(deltas["a1"], 0)
        # Bad agent should decrease
        self.assertLess(deltas["a2"], 0)


# =====================================================================
# 3. Weight History Tracking Tests
# =====================================================================


class TestWeightHistoryTracking(unittest.TestCase):
    """Test weight adjustment history tracking."""

    def setUp(self):
        self.coord = _make_coordinator()
        for aid in ["a1", "a2"]:
            self.coord._agent_reliability[aid] = 1.0

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    def _populate_agent(self, agent_id: str, correct: int, incorrect: int):
        for i in range(correct + incorrect):
            rnd = ConsensusRound(round_id=f"hist-{agent_id}-{i}", symbol="BTC")
            is_correct = i < correct
            score = 0.5 if is_correct else -0.5
            rnd.votes = [AgentVote(
                agent_id=agent_id, agent_role="analyst", vote="approve",
                score=score, confidence=0.7, weight=1.0, reasoning="test"
            )]
            rnd.status = "completed"
            self.coord._round_history.append(rnd)
            self.coord.incentive_ledger.record_round_outcome(rnd, "long", 10.0 if is_correct else -10.0)

    def test_weight_adjustments_recorded(self):
        """Weight adjustments should be recorded to history."""
        self._populate_agent("a1", correct=8, incorrect=2)

        # Apply feedback
        self.coord.apply_ledger_feedback(min_rounds=5)

        # Check history was recorded
        history = getattr(self.coord, '_weight_adjustment_history', [])
        self.assertGreater(len(history), 0)

        entry = history[0]
        self.assertEqual(entry["agent_id"], "a1")
        self.assertIn("old_weight", entry)
        self.assertIn("new_weight", entry)
        self.assertIn("delta", entry)
        self.assertIn("timestamp", entry)

    def test_weight_history_api_endpoint(self):
        """Weight history should be accessible via API."""
        self._populate_agent("a1", correct=8, incorrect=2)
        self.coord.apply_ledger_feedback(min_rounds=5)

        history = getattr(self.coord, '_weight_adjustment_history', [])
        # Simulate API response format
        response = {"history": history[-50:], "count": len(history)}
        
        self.assertEqual(response["count"], 1)
        self.assertEqual(len(response["history"]), 1)


# =====================================================================
# 4. Kalshi Settlement Edge Cases Tests
# =====================================================================


class TestKalshiSettlementEdgeCases(unittest.TestCase):
    """Test Kalshi reconciler edge case handling."""

    def setUp(self):
        self.coord = _make_coordinator()
        rnd = ConsensusRound(round_id="edge-r1", symbol="BTC")
        rnd.votes = [AgentVote(
            agent_id="a1", agent_role="analyst", vote="approve",
            score=0.7, confidence=0.8, weight=1.0, reasoning="bull"
        )]
        rnd.status = "completed"
        self.coord._round_history.append(rnd)

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_voided_market_skipped(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "edge-r1", "realised_direction": "long", "realised_pnl": 100.0,
             "settlement_type": "voided"},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        # Voided markets should be skipped
        self.assertEqual(count, 0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_partial_fill_proportional_pnl(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "edge-r1", "realised_direction": "long", "realised_pnl": 100.0,
             "settlement_type": "partial_fill", "fill_ratio": 0.5},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 1)
        # PnL should be proportional (50% of 100 = 50)
        self.assertEqual(self.coord.incentive_ledger.pnl("a1"), 50.0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_manual_adjustment_attributed(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "edge-r1", "realised_direction": "long", "realised_pnl": 75.0,
             "settlement_type": "manual", "original_pnl": 50.0, 
             "adjustment_reason": "Correction", "adjusted_by": "operator"},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 1)
        # Adjusted PnL should be used
        self.assertEqual(self.coord.incentive_ledger.pnl("a1"), 75.0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_mixed_settlements(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        # Add another round
        rnd2 = ConsensusRound(round_id="edge-r2", symbol="ETH")
        rnd2.votes = [AgentVote(
            agent_id="a2", agent_role="analyst", vote="approve",
            score=0.6, confidence=0.7, weight=1.0, reasoning="up"
        )]
        rnd2.status = "completed"
        self.coord._round_history.append(rnd2)

        settled = [
            {"round_id": "edge-r1", "realised_direction": "long", "realised_pnl": 100.0,
             "settlement_type": "voided"},  # Skipped
            {"round_id": "edge-r2", "realised_direction": "long", "realised_pnl": 50.0,
             "settlement_type": "normal"},  # Counted
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 1)
        self.assertEqual(self.coord.incentive_ledger.pnl("a2"), 50.0)
        # a1 should have no PnL (voided)
        self.assertEqual(self.coord.incentive_ledger.pnl("a1"), 0.0)


if __name__ == "__main__":
    unittest.main()
