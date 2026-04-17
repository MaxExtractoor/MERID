"""Loop 2 Tests — Social advisory signals, conflicting opinions, incentive ledger.

Covers:
  TestSocialAdvisoryNudge       — social signals shift consensus final score
  TestConflictingOpinions       — agents disagree; consensus resolves correctly
  TestNoisySocialSentiment      — noisy/contradictory social signals are capped
  TestAgentIncentiveLedger      — PnL attribution, accuracy, calibration, edge
  TestTunableWeights            — runtime weight tuning for social sources
"""

import asyncio
import time
import unittest
from unittest.mock import patch

from consensus.consensus_coordinator import (
    AgentVote,
    AgentIncentiveLedger,
    ConsensusConfig,
    ConsensusRound,
    ConsensusState,
    EnhancedConsensusCoordinator,
    SocialSignal,
)


def _run(coro):
    """Helper to run async in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSocialAdvisoryNudge(unittest.TestCase):
    """Social signals should nudge the final consensus score."""

    def setUp(self):
        EnhancedConsensusCoordinator._instance = None
        self.config = ConsensusConfig(
            min_agents_for_quorum=2,
            round_timeout_seconds=9999,
            social_advisory_weights={"twitter": 0.15, "reddit": 0.10},
            social_advisory_max_nudge=0.20,
        )
        self.coord = EnhancedConsensusCoordinator(self.config)
        self.coord.register_agent("bull-1", "research")
        self.coord.register_agent("bull-2", "research")

    def test_bullish_social_nudges_score_up(self):
        """Positive twitter sentiment should increase final_score."""
        # Submit bullish social signal
        self.coord.submit_social_signal(SocialSignal(
            source="twitter", agent_id="twitter-ingestion-01",
            symbol="BTC", score=0.8, confidence=0.9, volume=500,
        ))

        # Run a round with two mildly bullish agents (score 0.6 each)
        async def _run_round():
            await self.coord.start_round("BTC")
            await self.coord.submit_vote("BTC", "bull-1", "approve", 0.6, 0.8, "bullish thesis")
            await self.coord.submit_vote("BTC", "bull-2", "approve", 0.6, 0.8, "confirming")

        _run(_run_round())

        # Round should be decided; check that nudge was applied
        self.assertEqual(len(self.coord._round_history), 1)
        rnd = self.coord._round_history[0]
        # weighted_score = score * confidence * weight = 0.6*0.8*1.0 = 0.48 per agent
        # base consensus = 0.48. Twitter nudge = 0.8*0.9 * 0.15 ≈ +0.108
        # final should be > 0.48
        self.assertGreater(rnd.final_score, 0.48)

    def test_bearish_social_nudges_score_down(self):
        """Negative reddit sentiment should decrease final_score."""
        self.coord.submit_social_signal(SocialSignal(
            source="reddit", agent_id="reddit-ingestion-01",
            symbol="ETH", score=-0.7, confidence=0.8, volume=300,
        ))

        async def _run_round():
            await self.coord.start_round("ETH")
            # Agents are slightly bullish
            await self.coord.submit_vote("ETH", "bull-1", "approve", 0.3, 0.7, "mild bull")
            await self.coord.submit_vote("ETH", "bull-2", "approve", 0.3, 0.7, "mild bull 2")

        _run(_run_round())
        rnd = self.coord._round_history[0]
        # Nudge should pull it below 0.3
        self.assertLess(rnd.final_score, 0.3)

    def test_nudge_capped_at_max(self):
        """Even extreme social scores should be capped at social_advisory_max_nudge."""
        # Submit extreme signals from multiple sources
        for src in ("twitter", "reddit"):
            self.coord.submit_social_signal(SocialSignal(
                source=src, agent_id=f"{src}-01",
                symbol="SOL", score=1.0, confidence=1.0, volume=9999,
            ))

        nudge = self.coord._compute_social_nudge("SOL")
        self.assertLessEqual(nudge, self.config.social_advisory_max_nudge)

    def test_no_signals_no_nudge(self):
        nudge = self.coord._compute_social_nudge("NONEXISTENT")
        self.assertEqual(nudge, 0.0)


class TestConflictingOpinions(unittest.TestCase):
    """Agents disagree — consensus should resolve to flat or the dominant side."""

    def setUp(self):
        EnhancedConsensusCoordinator._instance = None
        self.config = ConsensusConfig(
            min_agents_for_quorum=3,
            round_timeout_seconds=9999,
        )
        self.coord = EnhancedConsensusCoordinator(self.config)
        for aid in ("bull-1", "bear-1", "neutral-1"):
            self.coord.register_agent(aid, "research")

    def test_split_vote_resolves_flat(self):
        """1 bull + 1 bear + 1 abstain => flat."""
        async def _run_round():
            await self.coord.start_round("SPY")
            await self.coord.submit_vote("SPY", "bull-1", "approve", 0.8, 0.9, "bullish")
            await self.coord.submit_vote("SPY", "bear-1", "reject", -0.8, 0.9, "bearish")
            await self.coord.submit_vote("SPY", "neutral-1", "abstain", 0.0, 0.5, "unsure")

        _run(_run_round())
        rnd = self.coord._round_history[0]
        # With opposing votes cancelling, score should be near 0 => flat
        self.assertEqual(rnd.direction, "flat")

    def test_majority_bull_wins(self):
        """2 bulls + 1 bear => score positive, direction long."""
        self.coord.register_agent("bull-2", "research")
        self.config.min_agents_for_quorum = 3

        async def _run_round():
            await self.coord.start_round("AAPL")
            await self.coord.submit_vote("AAPL", "bull-1", "approve", 0.9, 0.9, "strong bull")
            await self.coord.submit_vote("AAPL", "bull-2", "approve", 0.85, 0.85, "bull confirm")
            await self.coord.submit_vote("AAPL", "bear-1", "reject", -0.5, 0.7, "mild bear")

        _run(_run_round())
        rnd = self.coord._round_history[0]
        self.assertGreater(rnd.final_score, 0)

    def test_social_breaks_tie(self):
        """Evenly split agents + bullish social signal => score nudged positive."""
        self.coord.register_agent("bull-2", "research")
        self.coord.register_agent("bear-2", "research")
        self.config.min_agents_for_quorum = 4
        self.config.social_advisory_weights = {"twitter": 0.15}
        self.config.social_advisory_max_nudge = 0.20

        # Strong bullish twitter
        self.coord.submit_social_signal(SocialSignal(
            source="twitter", agent_id="tw-01",
            symbol="LINK", score=0.9, confidence=0.95, volume=1000,
        ))

        async def _run_round():
            await self.coord.start_round("LINK")
            await self.coord.submit_vote("LINK", "bull-1", "approve", 0.7, 0.8, "bull")
            await self.coord.submit_vote("LINK", "bull-2", "approve", 0.7, 0.8, "bull2")
            await self.coord.submit_vote("LINK", "bear-1", "reject", -0.7, 0.8, "bear")
            await self.coord.submit_vote("LINK", "bear-2", "reject", -0.7, 0.8, "bear2")

        _run(_run_round())
        rnd = self.coord._round_history[0]
        # Without social: ~0.0.  With bullish twitter nudge: slightly positive.
        self.assertGreater(rnd.final_score, 0.0)


class TestNoisySocialSentiment(unittest.TestCase):
    """Contradictory social signals should largely cancel out."""

    def setUp(self):
        EnhancedConsensusCoordinator._instance = None
        self.config = ConsensusConfig(
            min_agents_for_quorum=2,
            round_timeout_seconds=9999,
            social_advisory_weights={"twitter": 0.15, "reddit": 0.10},
            social_advisory_max_nudge=0.20,
        )
        self.coord = EnhancedConsensusCoordinator(self.config)
        self.coord.register_agent("a1", "research")
        self.coord.register_agent("a2", "research")

    def test_contradictory_signals_cancel(self):
        """Bullish twitter + bearish reddit => small net nudge."""
        self.coord.submit_social_signal(SocialSignal(
            source="twitter", agent_id="tw",
            symbol="XYZ", score=0.8, confidence=0.9, volume=500,
        ))
        self.coord.submit_social_signal(SocialSignal(
            source="reddit", agent_id="rd",
            symbol="XYZ", score=-0.8, confidence=0.9, volume=500,
        ))
        nudge = self.coord._compute_social_nudge("XYZ")
        # twitter contributes +0.8*0.15=0.12, reddit contributes -0.8*0.10=-0.08
        # net = +0.04, well within cap
        self.assertAlmostEqual(nudge, 0.04, places=2)

    def test_stale_signals_pruned(self):
        """Signals older than TTL should be ignored."""
        old_signal = SocialSignal(
            source="twitter", agent_id="tw",
            symbol="OLD", score=1.0, confidence=1.0, volume=999,
            timestamp=time.time() - 999,  # way beyond TTL
        )
        self.coord._social_signals["OLD"].append(old_signal)
        nudge = self.coord._compute_social_nudge("OLD")
        self.assertEqual(nudge, 0.0)


class TestTunableWeights(unittest.TestCase):
    """Runtime weight tuning for social sources."""

    def setUp(self):
        EnhancedConsensusCoordinator._instance = None
        self.coord = EnhancedConsensusCoordinator(ConsensusConfig())

    def test_set_weight_clamps(self):
        self.coord.set_social_advisory_weight("twitter", 1.5)
        self.assertEqual(self.coord.config.social_advisory_weights["twitter"], 1.0)
        self.coord.set_social_advisory_weight("twitter", -0.5)
        self.assertEqual(self.coord.config.social_advisory_weights["twitter"], 0.0)

    def test_disable_source(self):
        self.coord.set_social_advisory_weight("reddit", 0.0)
        self.coord.submit_social_signal(SocialSignal(
            source="reddit", agent_id="rd",
            symbol="AAA", score=1.0, confidence=1.0, volume=100,
        ))
        nudge = self.coord._compute_social_nudge("AAA")
        self.assertEqual(nudge, 0.0)


class TestAgentIncentiveLedger(unittest.TestCase):
    """Per-agent PnL attribution, accuracy, calibration, edge."""

    def setUp(self):
        self.ledger = AgentIncentiveLedger()

    def _make_round(self, votes):
        """Helper: create a ConsensusRound with given votes."""
        rnd = ConsensusRound(symbol="TEST", state=ConsensusState.DECIDED)
        for agent_id, score, confidence in votes:
            rnd.votes.append(AgentVote(
                agent_id=agent_id, agent_role="research",
                vote="approve" if score > 0 else "reject",
                score=score, confidence=confidence, weight=1.0,
                reasoning="test",
            ))
        return rnd

    def test_correct_call_attributed(self):
        rnd = self._make_round([("agent-a", 0.8, 0.9)])
        self.ledger.record_round_outcome(rnd, realised_direction="long", realised_pnl=100.0)
        self.assertEqual(self.ledger.accuracy("agent-a"), 1.0)
        self.assertEqual(self.ledger.pnl("agent-a"), 100.0)

    def test_incorrect_call(self):
        rnd = self._make_round([("agent-b", 0.8, 0.9)])
        self.ledger.record_round_outcome(rnd, realised_direction="short", realised_pnl=-50.0)
        self.assertEqual(self.ledger.accuracy("agent-b"), 0.0)
        self.assertEqual(self.ledger.pnl("agent-b"), -50.0)

    def test_pnl_split_across_voters(self):
        rnd = self._make_round([
            ("agent-a", 0.8, 0.9),
            ("agent-b", 0.6, 0.7),
        ])
        self.ledger.record_round_outcome(rnd, realised_direction="long", realised_pnl=200.0)
        self.assertEqual(self.ledger.pnl("agent-a"), 100.0)
        self.assertEqual(self.ledger.pnl("agent-b"), 100.0)

    def test_calibration_error_perfect(self):
        """Agent with confidence matching outcomes has low calibration error."""
        rnd = self._make_round([("agent-c", 0.8, 0.8)])
        self.ledger.record_round_outcome(rnd, realised_direction="long")
        # predicted 0.8, outcome 1.0 => error = 0.2
        self.assertAlmostEqual(self.ledger.calibration_error("agent-c"), 0.2, places=2)

    def test_calibration_error_overconfident(self):
        """Overconfident wrong agent has high calibration error."""
        rnd = self._make_round([("agent-d", 0.9, 0.95)])
        self.ledger.record_round_outcome(rnd, realised_direction="short")
        # predicted 0.95, outcome 0.0 => error = 0.95
        self.assertAlmostEqual(self.ledger.calibration_error("agent-d"), 0.95, places=2)

    def test_edge_accumulates_only_on_correct(self):
        rnd1 = self._make_round([("agent-e", 0.8, 0.8)])
        self.ledger.record_round_outcome(rnd1, realised_direction="long")
        # edge = 0.8 - 0.5 = 0.3
        self.assertAlmostEqual(self.ledger.edge("agent-e"), 0.3, places=2)

        rnd2 = self._make_round([("agent-e", 0.8, 0.8)])
        self.ledger.record_round_outcome(rnd2, realised_direction="short")
        # wrong => no edge added
        self.assertAlmostEqual(self.ledger.edge("agent-e"), 0.3, places=2)

    def test_leaderboard(self):
        rnd = self._make_round([
            ("agent-x", 0.9, 0.9),
            ("agent-y", 0.5, 0.6),
        ])
        self.ledger.record_round_outcome(rnd, realised_direction="long", realised_pnl=100.0)
        lb = self.ledger.leaderboard()
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0]["agent_id"], "agent-x")  # higher edge

    def test_summary_unknown_agent(self):
        s = self.ledger.summary("nonexistent")
        self.assertEqual(s["rounds"], 0)

    def test_multiple_rounds_accumulate(self):
        for i in range(5):
            rnd = self._make_round([("agent-f", 0.7, 0.8)])
            direction = "long" if i < 3 else "short"  # 3 correct, 2 wrong
            self.ledger.record_round_outcome(rnd, realised_direction=direction, realised_pnl=10.0)
        self.assertEqual(self.ledger.accuracy("agent-f"), 3 / 5)
        self.assertAlmostEqual(self.ledger.pnl("agent-f"), 50.0, places=2)


if __name__ == "__main__":
    unittest.main()
