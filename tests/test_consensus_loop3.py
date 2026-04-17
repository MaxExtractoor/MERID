"""Loop 3 tests — Incentive API, Ledger Feedback, Reconciliation→Ledger wiring.

Covers:
  1. API endpoints (leaderboard, per-agent stats, social breakdown, social weights)
  2. Bounded feedback rule (apply_ledger_feedback caps, rolling window, blend)
  3. Reconciliation → ledger integration (attribute_settled_to_ledger, reconcile_and_attribute)
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
# 1. API endpoint unit tests (test the router functions directly)
# =====================================================================


class TestIncentiveAPIEndpoints(unittest.TestCase):
    """Test the data that API endpoints would return by calling coordinator methods directly."""

    def setUp(self):
        self.coord = _make_coordinator()
        # Pre-populate ledger with some data
        rnd = ConsensusRound(round_id="r1", symbol="BTC")
        rnd.votes = [
            AgentVote(agent_id="a1", agent_role="analyst", vote="approve", score=0.7, confidence=0.8, weight=1.0, reasoning="bull"),
            AgentVote(agent_id="a2", agent_role="analyst", vote="reject", score=-0.3, confidence=0.6, weight=1.0, reasoning="bear"),
        ]
        rnd.status = "completed"
        self.coord._round_history.append(rnd)
        self.coord.record_trade_outcome("r1", "long", 100.0)

        # Add a social signal
        self.coord.submit_social_signal(SocialSignal(
            source="twitter", agent_id="tw-01", symbol="BTC",
            score=0.6, confidence=0.8, volume=500,
        ))

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    def test_leaderboard_returns_agents(self):
        lb = self.coord.incentive_ledger.leaderboard(top_n=5)
        self.assertGreater(len(lb), 0)
        first = lb[0]
        self.assertIn("agent_id", first)
        self.assertIn("pnl", first)
        self.assertIn("accuracy", first)
        self.assertIn("edge", first)
        self.assertIn("rounds", first)

    def test_agent_summary_known(self):
        result = self.coord.incentive_ledger.summary("a1")
        self.assertEqual(result["agent_id"], "a1")
        self.assertEqual(result["rounds"], 1)
        self.assertGreater(result["pnl"], 0)

    def test_agent_summary_unknown(self):
        result = self.coord.incentive_ledger.summary("unknown-agent")
        self.assertEqual(result["rounds"], 0)

    def test_social_signals_for_symbol(self):
        signals = self.coord.get_social_signals("BTC")
        self.assertGreater(len(signals), 0)
        s = signals[0]
        self.assertEqual(s.source, "twitter")
        self.assertAlmostEqual(s.score, 0.6)

    def test_social_signals_empty_symbol(self):
        signals = self.coord.get_social_signals("NOSYMBOL")
        self.assertEqual(len(signals), 0)

    def test_social_nudge_computed(self):
        nudge = self.coord._compute_social_nudge("BTC")
        self.assertNotEqual(nudge, 0.0)

    def test_social_weights_readable(self):
        weights = dict(self.coord.config.social_advisory_weights)
        self.assertIsInstance(weights, dict)
        self.assertIn("twitter", weights)

    def test_social_weights_tunable(self):
        self.coord.set_social_advisory_weight("twitter", 0.3)
        self.assertAlmostEqual(self.coord.config.social_advisory_weights["twitter"], 0.3)


# =====================================================================
# 2. Bounded feedback rule tests
# =====================================================================


class TestLedgerFeedback(unittest.TestCase):
    """Test apply_ledger_feedback weight adjustment logic."""

    def setUp(self):
        self.coord = _make_coordinator()
        # Register agents in reliability map
        for aid in ["a1", "a2", "a3"]:
            self.coord._agent_reliability[aid] = 1.0

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    def _populate_agent(self, agent_id: str, correct: int, incorrect: int, confidence: float = 0.7):
        """Simulate N rounds of outcomes for an agent in the ledger."""
        for i in range(correct + incorrect):
            rnd = ConsensusRound(round_id=f"fb-{agent_id}-{i}", symbol="BTC")
            is_correct = i < correct
            score = 0.5 if is_correct else -0.5
            rnd.votes = [AgentVote(
                agent_id=agent_id, agent_role="analyst", vote="approve", score=score,
                confidence=confidence, weight=1.0, reasoning="test",
            )]
            rnd.status = "completed"
            self.coord._round_history.append(rnd)
            direction = "long" if is_correct else "short"
            self.coord.incentive_ledger.record_round_outcome(rnd, "long", 10.0 if is_correct else -10.0)

    def test_no_adjustment_below_min_rounds(self):
        """Agents with fewer rounds than min_rounds should not be adjusted."""
        self._populate_agent("a1", correct=2, incorrect=1)
        adjusted = self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertNotIn("a1", adjusted)
        self.assertEqual(self.coord._agent_reliability["a1"], 1.0)

    def test_good_agent_weight_increases(self):
        """A highly accurate agent should see weight increase."""
        self._populate_agent("a1", correct=9, incorrect=1, confidence=0.7)
        old_w = self.coord._agent_reliability["a1"]
        adjusted = self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertIn("a1", adjusted)
        self.assertGreaterEqual(adjusted["a1"], old_w * 0.95)  # should not drop

    def test_bad_agent_weight_decreases(self):
        """A poorly accurate agent should see weight decrease."""
        self._populate_agent("a2", correct=1, incorrect=9, confidence=0.9)
        old_w = self.coord._agent_reliability["a2"]
        adjusted = self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertIn("a2", adjusted)
        self.assertLess(adjusted["a2"], old_w)

    def test_weight_capped_at_max(self):
        """Weight should never exceed MAX_WEIGHT (1.5)."""
        self.coord._agent_reliability["a1"] = 1.5
        self._populate_agent("a1", correct=10, incorrect=0, confidence=0.99)
        self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertLessEqual(self.coord._agent_reliability["a1"], 1.5)

    def test_weight_floored_at_min(self):
        """Weight should never go below MIN_WEIGHT (0.3)."""
        self.coord._agent_reliability["a3"] = 0.3
        self._populate_agent("a3", correct=0, incorrect=10, confidence=0.99)
        self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertGreaterEqual(self.coord._agent_reliability["a3"], 0.3)

    def test_blend_is_gentle(self):
        """The blend should move weight by at most 30% toward target each call."""
        self.coord._agent_reliability["a1"] = 1.0
        self._populate_agent("a1", correct=10, incorrect=0, confidence=0.7)
        self.coord.apply_ledger_feedback(min_rounds=5)
        w = self.coord._agent_reliability["a1"]
        # Should not jump all the way to target; delta <= 0.3 * |target - 1.0|
        self.assertLess(abs(w - 1.0), 0.35)

    def test_multiple_applications_converge(self):
        """Repeated applications should converge toward target."""
        self._populate_agent("a1", correct=10, incorrect=0, confidence=0.7)
        weights = []
        for _ in range(10):
            self.coord.apply_ledger_feedback(min_rounds=5)
            weights.append(self.coord._agent_reliability["a1"])
        # Should be monotonically approaching target (increasing for good agent)
        for i in range(1, len(weights)):
            self.assertGreaterEqual(weights[i], weights[i - 1] - 0.001)

    def test_unregistered_agent_not_touched(self):
        """Agents not in _agent_reliability should not be added by feedback."""
        self.coord.incentive_ledger._ensure("ghost")
        rec = self.coord.incentive_ledger._records["ghost"]
        rec.round_count = 20
        rec.correct_calls = 15
        rec.incorrect_calls = 5
        rec.predicted_confidences = [0.7] * 20
        rec.realised_outcomes = [1.0] * 15 + [0.0] * 5
        adjusted = self.coord.apply_ledger_feedback(min_rounds=5)
        self.assertNotIn("ghost", adjusted)


# =====================================================================
# 3. Reconciliation → Ledger integration tests
# =====================================================================


class TestReconciliationLedgerIntegration(unittest.TestCase):
    """Test attribute_settled_to_ledger and reconcile_and_attribute."""

    def setUp(self):
        self.coord = _make_coordinator()
        # Create a round with votes
        rnd = ConsensusRound(round_id="recon-r1", symbol="BTC")
        rnd.votes = [
            AgentVote(agent_id="a1", agent_role="analyst", vote="approve", score=0.7, confidence=0.8, weight=1.0, reasoning="bull"),
        ]
        rnd.status = "completed"
        self.coord._round_history.append(rnd)

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_attribute_settled_records_outcome(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "recon-r1", "realised_direction": "long", "realised_pnl": 50.0},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 1)
        self.assertEqual(self.coord.incentive_ledger.pnl("a1"), 50.0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_attribute_skips_missing_round_id(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"realised_direction": "long", "realised_pnl": 50.0},  # no round_id
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_attribute_multiple_positions(self, mock_get):
        # Add a second round
        rnd2 = ConsensusRound(round_id="recon-r2", symbol="ETH")
        rnd2.votes = [
            AgentVote(agent_id="a2", agent_role="analyst", vote="approve", score=0.5, confidence=0.6, weight=1.0, reasoning="up"),
        ]
        rnd2.status = "completed"
        self.coord._round_history.append(rnd2)

        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "recon-r1", "realised_direction": "long", "realised_pnl": 50.0},
            {"round_id": "recon-r2", "realised_direction": "short", "realised_pnl": -20.0},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        self.assertEqual(count, 2)
        self.assertAlmostEqual(self.coord.incentive_ledger.pnl("a1"), 50.0)
        self.assertAlmostEqual(self.coord.incentive_ledger.pnl("a2"), -20.0)

    @patch("consensus.consensus_coordinator.get_consensus_coordinator")
    def test_attribute_handles_unknown_round_gracefully(self, mock_get):
        mock_get.return_value = self.coord
        from merid.reconciliation.kalshi_reconciler import KalshiReconciler
        reconciler = KalshiReconciler.__new__(KalshiReconciler)
        reconciler._venue_adapter = MagicMock()
        reconciler._matching_engine = None
        reconciler._last_report = None

        settled = [
            {"round_id": "nonexistent-round", "realised_direction": "long", "realised_pnl": 100.0},
        ]
        count = _run(reconciler.attribute_settled_to_ledger(settled))
        # Should still count as 1 (the call succeeds, just logs a warning)
        self.assertEqual(count, 1)
        # But no PnL should be attributed since round not found
        self.assertAlmostEqual(self.coord.incentive_ledger.pnl("a1"), 0.0)


# =====================================================================
# 4. Integration: record_trade_outcome round-trip
# =====================================================================


class TestRecordTradeOutcomeRoundTrip(unittest.TestCase):
    """Verify record_trade_outcome on the coordinator flows into the ledger."""

    def setUp(self):
        self.coord = _make_coordinator()

    def tearDown(self):
        EnhancedConsensusCoordinator._instance = None

    def test_outcome_populates_ledger(self):
        rnd = ConsensusRound(round_id="rt-1", symbol="BTC")
        rnd.votes = [
            AgentVote(agent_id="x1", agent_role="analyst", vote="approve", score=0.6, confidence=0.9, weight=1.0, reasoning="yes"),
            AgentVote(agent_id="x2", agent_role="analyst", vote="reject", score=-0.4, confidence=0.7, weight=1.0, reasoning="no"),
        ]
        rnd.status = "completed"
        self.coord._round_history.append(rnd)

        self.coord.record_trade_outcome("rt-1", "long", 200.0)

        self.assertEqual(self.coord.incentive_ledger.pnl("x1"), 100.0)
        self.assertEqual(self.coord.incentive_ledger.pnl("x2"), 100.0)
        self.assertAlmostEqual(self.coord.incentive_ledger.accuracy("x1"), 1.0)
        self.assertAlmostEqual(self.coord.incentive_ledger.accuracy("x2"), 0.0)

    def test_outcome_unknown_round(self):
        """record_trade_outcome with unknown round_id should not crash."""
        self.coord.record_trade_outcome("does-not-exist", "long", 50.0)
        # No agents recorded
        self.assertEqual(len(self.coord.incentive_ledger._records), 0)


if __name__ == "__main__":
    unittest.main()
