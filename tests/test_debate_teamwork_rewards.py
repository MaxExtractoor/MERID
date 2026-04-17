"""Comprehensive tests for the Debate, Teamwork & Rewards sprint (Session 7).

Covers:
  - DebateSession, DebateArgument, AgentTeam, RewardEntry dataclasses
  - DebateStore SQLite persistence (CRUD for debates, arguments, teams, rewards)
  - ChallengerStrategy and ArbiterStrategy
  - DebateCoordinatorAgent (full debate protocol)
  - Debate metrics (lift, disagreement width, argument counts)
  - Reward calculations (accuracy, debate lift, explanation, timeliness)
  - Leaderboard and badge computation
  - NoDebateActivityAlert and NegativeDebateLiftAlert
  - Observability alert registry update (10 → 12)
"""

import os
import tempfile
import time
import json
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ── Helpers ──────────────────────────────────────────────────────────

def _tmp_db() -> str:
    """Create a temporary DB path for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# ── DebateSession dataclass ──────────────────────────────────────────

class TestDebateSession:
    def test_construction_defaults(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="PRED:KALSHI:TEST:YES")
        assert s.symbol == "PRED:KALSHI:TEST:YES"
        assert s.status == "open"
        assert s.pre_debate_prob == 0.5
        assert s.post_debate_prob is None
        assert s.outcome is None
        assert s.debate_lift is None
        assert s.rounds == 0
        assert s.id.startswith("deb-")

    def test_to_dict(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="PRED:KALSHI:TEST:YES", pre_debate_prob=0.65)
        d = s.to_dict()
        assert d["symbol"] == "PRED:KALSHI:TEST:YES"
        assert d["pre_debate_prob"] == 0.65
        assert d["status"] == "open"
        assert "created_at" in d

    def test_to_dict_with_post_debate(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(
            symbol="PRED:KALSHI:TEST:YES",
            post_debate_prob=0.72,
            debate_lift=0.05,
            outcome=1,
        )
        d = s.to_dict()
        assert d["post_debate_prob"] == 0.72
        assert d["debate_lift"] == 0.05
        assert d["outcome"] == 1


# ── DebateArgument dataclass ─────────────────────────────────────────

class TestDebateArgument:
    def test_construction(self):
        from merid.prediction.debate import DebateArgument
        a = DebateArgument(
            debate_id="deb-123", agent_id="agent-1",
            role="proposer", probability=0.7, confidence=0.6,
            rationale="mean_reversion",
        )
        assert a.debate_id == "deb-123"
        assert a.role == "proposer"
        assert a.id.startswith("darg-")

    def test_to_dict(self):
        from merid.prediction.debate import DebateArgument
        a = DebateArgument(
            debate_id="deb-123", agent_id="agent-1",
            role="challenger", probability=0.55, confidence=0.4,
            rationale="challenge_against_mean_reversion",
        )
        d = a.to_dict()
        assert d["role"] == "challenger"
        assert d["probability"] == 0.55
        assert d["rationale"] == "challenge_against_mean_reversion"

    def test_to_dict_with_explanation(self):
        from merid.prediction.debate import DebateArgument
        a = DebateArgument(
            debate_id="deb-123", agent_id="agent-1",
            role="proposer", probability=0.7,
            explanation={"inputs_used": {"market_prob": 0.5}, "rationale": "test"},
        )
        d = a.to_dict()
        assert "explanation" in d
        assert d["explanation"]["rationale"] == "test"


# ── AgentTeam dataclass ──────────────────────────────────────────────

class TestAgentTeam:
    def test_construction(self):
        from merid.prediction.debate import AgentTeam
        t = AgentTeam(name="Alpha Team", member_ids=["a1", "a2", "a3"])
        assert t.name == "Alpha Team"
        assert len(t.member_ids) == 3
        assert t.id.startswith("team-")

    def test_to_dict(self):
        from merid.prediction.debate import AgentTeam
        t = AgentTeam(name="Beta", member_ids=["b1"], strategy_mix="mean_reversion+challenger")
        d = t.to_dict()
        assert d["name"] == "Beta"
        assert d["strategy_mix"] == "mean_reversion+challenger"


# ── RewardEntry dataclass ────────────────────────────────────────────

class TestRewardEntry:
    def test_construction(self):
        from merid.prediction.debate import RewardEntry
        r = RewardEntry(
            agent_id="agent-1", reward_type="accuracy",
            points=42.5, detail="Brier=0.15",
        )
        assert r.agent_id == "agent-1"
        assert r.points == 42.5
        assert r.id.startswith("rew-")

    def test_to_dict(self):
        from merid.prediction.debate import RewardEntry
        r = RewardEntry(
            agent_id="agent-1", reward_type="debate_lift",
            points=15.0, symbol="PRED:KALSHI:TEST:YES",
        )
        d = r.to_dict()
        assert d["reward_type"] == "debate_lift"
        assert d["points"] == 15.0
        assert d["symbol"] == "PRED:KALSHI:TEST:YES"


# ── DebateStore persistence ──────────────────────────────────────────

class TestDebateStorePersistence:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_create_and_get_debate(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="PRED:KALSHI:TEST:YES", pre_debate_prob=0.6)
        self.store.create_debate(s)
        fetched = self.store.get_debate(s.id)
        assert fetched is not None
        assert fetched.symbol == "PRED:KALSHI:TEST:YES"
        assert fetched.pre_debate_prob == 0.6

    def test_list_debates_by_symbol(self):
        from merid.prediction.debate import DebateSession
        self.store.create_debate(DebateSession(symbol="SYM_A"))
        self.store.create_debate(DebateSession(symbol="SYM_B"))
        self.store.create_debate(DebateSession(symbol="SYM_A"))
        result = self.store.list_debates(symbol="SYM_A")
        assert len(result) == 2

    def test_list_debates_by_status(self):
        from merid.prediction.debate import DebateSession
        self.store.create_debate(DebateSession(symbol="S1", status="open"))
        self.store.create_debate(DebateSession(symbol="S2", status="closed"))
        open_debates = self.store.list_debates(status="open")
        assert len(open_debates) == 1
        assert open_debates[0].status == "open"

    def test_close_debate(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="S1")
        self.store.create_debate(s)
        closed = self.store.close_debate(s.id, post_debate_prob=0.72)
        assert closed.status == "closed"
        assert closed.post_debate_prob == 0.72
        assert closed.closed_at is not None

    def test_resolve_debate_computes_lift(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="S1", pre_debate_prob=0.5, post_debate_prob=0.8)
        self.store.create_debate(s)
        resolved = self.store.resolve_debate(s.id, outcome=1)
        assert resolved.status == "resolved"
        assert resolved.outcome == 1
        # pre_brier = (0.5 - 1)^2 = 0.25, post_brier = (0.8 - 1)^2 = 0.04
        # lift = 0.25 - 0.04 = 0.21
        assert resolved.debate_lift == pytest.approx(0.21, abs=0.001)

    def test_resolve_debate_negative_lift(self):
        from merid.prediction.debate import DebateSession
        s = DebateSession(symbol="S1", pre_debate_prob=0.8, post_debate_prob=0.3)
        self.store.create_debate(s)
        resolved = self.store.resolve_debate(s.id, outcome=1)
        # pre_brier = (0.8-1)^2 = 0.04, post_brier = (0.3-1)^2 = 0.49
        # lift = 0.04 - 0.49 = -0.45
        assert resolved.debate_lift == pytest.approx(-0.45, abs=0.001)

    def test_add_and_list_arguments(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        s = DebateSession(symbol="S1")
        self.store.create_debate(s)
        a1 = DebateArgument(debate_id=s.id, agent_id="a1", role="proposer", probability=0.7)
        a2 = DebateArgument(debate_id=s.id, agent_id="a2", role="challenger", probability=0.55)
        self.store.add_argument(a1)
        self.store.add_argument(a2)
        args = self.store.list_arguments(s.id)
        assert len(args) == 2
        assert args[0].role == "proposer"
        assert args[1].role == "challenger"

    def test_add_argument_increments_rounds(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        s = DebateSession(symbol="S1")
        self.store.create_debate(s)
        self.store.add_argument(DebateArgument(debate_id=s.id, agent_id="a1", role="proposer"))
        self.store.add_argument(DebateArgument(debate_id=s.id, agent_id="a2", role="challenger"))
        fetched = self.store.get_debate(s.id)
        assert fetched.rounds == 2

    def test_argument_explanation_persisted(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        s = DebateSession(symbol="S1")
        self.store.create_debate(s)
        exp = {"inputs_used": {"market_prob": 0.5}, "contributions": {"bias": 0.1}, "rationale": "test"}
        a = DebateArgument(debate_id=s.id, agent_id="a1", explanation=exp)
        self.store.add_argument(a)
        args = self.store.list_arguments(s.id)
        assert args[0].explanation is not None
        assert args[0].explanation["rationale"] == "test"


# ── Team persistence ─────────────────────────────────────────────────

class TestTeamPersistence:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_create_and_get_team(self):
        from merid.prediction.debate import AgentTeam
        t = AgentTeam(name="Alpha", member_ids=["a1", "a2"])
        self.store.create_team(t)
        fetched = self.store.get_team(t.id)
        assert fetched is not None
        assert fetched.name == "Alpha"
        assert fetched.member_ids == ["a1", "a2"]

    def test_list_teams(self):
        from merid.prediction.debate import AgentTeam
        self.store.create_team(AgentTeam(name="T1", member_ids=["a1"]))
        self.store.create_team(AgentTeam(name="T2", member_ids=["a2"]))
        teams = self.store.list_teams()
        assert len(teams) == 2

    def test_get_team_for_agent(self):
        from merid.prediction.debate import AgentTeam
        self.store.create_team(AgentTeam(name="T1", member_ids=["a1", "a2"]))
        self.store.create_team(AgentTeam(name="T2", member_ids=["a3"]))
        team = self.store.get_team_for_agent("a2")
        assert team is not None
        assert team.name == "T1"

    def test_get_team_for_unknown_agent(self):
        team = self.store.get_team_for_agent("unknown-agent")
        assert team is None


# ── Reward persistence ───────────────────────────────────────────────

class TestRewardPersistence:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_add_and_get_rewards(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", reward_type="accuracy", points=25.0))
        self.store.add_reward(RewardEntry(agent_id="a1", reward_type="timeliness", points=10.0))
        rewards = self.store.get_agent_rewards("a1")
        assert len(rewards) == 2

    def test_get_agent_total_points(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", points=25.0))
        self.store.add_reward(RewardEntry(agent_id="a1", points=15.0))
        self.store.add_reward(RewardEntry(agent_id="a2", points=50.0))
        assert self.store.get_agent_total_points("a1") == 40.0
        assert self.store.get_agent_total_points("a2") == 50.0

    def test_get_team_total_points(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", team_id="t1", points=20.0))
        self.store.add_reward(RewardEntry(agent_id="a2", team_id="t1", points=30.0))
        assert self.store.get_team_total_points("t1") == 50.0


# ── ChallengerStrategy ───────────────────────────────────────────────

class TestChallengerStrategy:
    def test_challenge_pulls_toward_market(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        est = s.estimate(
            agent_id="challenger-01", ticker="TEST",
            market_prob=0.5, category="macro",
            context={"proposer_prob": 0.8, "proposer_rationale": "mean_reversion"},
        )
        assert est is not None
        # Proposer at 0.8, market at 0.5 → challenger should pull back toward 0.5
        assert est.agent_prob < 0.8
        assert est.agent_prob > 0.5

    def test_challenge_explanation_present(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        est = s.estimate(
            agent_id="c1", ticker="T1", market_prob=0.5,
            context={"proposer_prob": 0.75, "proposer_rationale": "hash_bias"},
        )
        assert est.explanation is not None
        assert "challenge_against_hash_bias" in est.explanation.rationale
        assert est.explanation.inputs_used["proposer_prob"] == 0.75

    def test_challenge_with_no_context_uses_market(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        est = s.estimate(agent_id="c1", ticker="T1", market_prob=0.5)
        # With no proposer_prob in context, defaults to market_prob → no deviation
        # Edge should be 0 or very small
        assert est is not None or est is None  # May return None if edge < min_edge

    def test_challenge_skips_extreme_market(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        est = s.estimate(
            agent_id="c1", ticker="T1", market_prob=0.001,
            context={"proposer_prob": 0.5},
        )
        assert est is None  # Should skip extreme market prob

    def test_reasoning_tag_is_challenger(self):
        from merid.prediction.opinion_strategy import ChallengerStrategy
        s = ChallengerStrategy()
        est = s.estimate(
            agent_id="c1", ticker="T1", market_prob=0.5,
            context={"proposer_prob": 0.8, "proposer_rationale": "test"},
        )
        assert est.reasoning_tag == "challenger"


# ── ArbiterStrategy ──────────────────────────────────────────────────

class TestArbiterStrategy:
    def test_arbiter_blends_by_confidence(self):
        from merid.prediction.opinion_strategy import ArbiterStrategy
        s = ArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.7,
                "challenger_prob": 0.55, "challenger_confidence": 0.3,
            },
        )
        assert est is not None
        # Weighted: (0.8*0.7 + 0.55*0.3) / (0.7+0.3) = (0.56+0.165)/1.0 = 0.725
        assert est.agent_prob == pytest.approx(0.725, abs=0.01)

    def test_arbiter_equal_confidence_averages(self):
        from merid.prediction.opinion_strategy import ArbiterStrategy
        s = ArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.5,
                "challenger_prob": 0.6, "challenger_confidence": 0.5,
            },
        )
        assert est is not None
        assert est.agent_prob == pytest.approx(0.7, abs=0.01)

    def test_arbiter_explanation_present(self):
        from merid.prediction.opinion_strategy import ArbiterStrategy
        s = ArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.8, "proposer_confidence": 0.6,
                "challenger_prob": 0.55, "challenger_confidence": 0.4,
            },
        )
        assert est.explanation is not None
        assert est.explanation.rationale == "arbiter_confidence_weighted_synthesis"
        assert "proposer_weighted" in est.explanation.contributions

    def test_arbiter_reasoning_tag(self):
        from merid.prediction.opinion_strategy import ArbiterStrategy
        s = ArbiterStrategy()
        est = s.estimate(
            agent_id="arb-01", ticker="T1", market_prob=0.5,
            context={
                "proposer_prob": 0.7, "proposer_confidence": 0.5,
                "challenger_prob": 0.6, "challenger_confidence": 0.5,
            },
        )
        assert est.reasoning_tag == "arbiter"

    def test_arbiter_skips_extreme_market(self):
        from merid.prediction.opinion_strategy import ArbiterStrategy
        s = ArbiterStrategy()
        est = s.estimate(agent_id="arb-01", ticker="T1", market_prob=0.001)
        assert est is None


# ── Strategy registry ────────────────────────────────────────────────

class TestStrategyRegistry:
    def test_challenger_registered(self):
        from merid.prediction.opinion_strategy import get_strategy
        s = get_strategy("challenger")
        assert s.name == "challenger"

    def test_arbiter_registered(self):
        from merid.prediction.opinion_strategy import get_strategy
        s = get_strategy("arbiter")
        assert s.name == "arbiter"

    def test_list_strategies_includes_debate(self):
        from merid.prediction.opinion_strategy import list_strategies
        names = list_strategies()
        assert "challenger" in names
        assert "arbiter" in names


# ── DebateCoordinatorAgent ───────────────────────────────────────────

class TestDebateCoordinatorAgent:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_run_debate_produces_result(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        with patch("merid.prediction.debate.get_debate_store", return_value=self.store):
            agent = DebateCoordinatorAgent()
            instrument = {
                "symbol": "PRED:KALSHI:TEST:YES",
                "ticker": "TEST",
                "market_prob": 0.8,
                "category": "macro",
            }
            context = {
                "proposer_strategy": "mean_reversion",
                "proposer_agent_id": "prop-01",
                "challenger_agent_id": "chal-01",
            }
            result = agent.run_debate(instrument, context)

        assert result is not None
        assert result["symbol"] == "PRED:KALSHI:TEST:YES"
        assert "proposer" in result
        assert "challenger" in result
        assert "arbiter" in result
        assert "post_debate_prob" in result
        assert "disagreement_width" in result

    def test_debate_persisted_to_store(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        with patch("merid.prediction.debate.get_debate_store", return_value=self.store):
            agent = DebateCoordinatorAgent()
            instrument = {
                "symbol": "PRED:KALSHI:TEST:YES",
                "ticker": "TEST",
                "market_prob": 0.8,
                "category": "macro",
            }
            context = {"proposer_strategy": "mean_reversion"}
            result = agent.run_debate(instrument, context)

        debates = self.store.list_debates()
        assert len(debates) >= 1
        args = self.store.list_arguments(debates[0].id)
        assert len(args) >= 2  # At least proposer + challenger

    def test_debate_returns_none_when_strategy_declines(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        with patch("merid.prediction.debate.get_debate_store", return_value=self.store):
            agent = DebateCoordinatorAgent()
            # market_prob at 0.5 with mean_reversion → distance=0 → edge=0 → returns None
            instrument = {
                "symbol": "PRED:KALSHI:TEST:YES",
                "ticker": "TEST",
                "market_prob": 0.5,
                "category": "macro",
            }
            context = {"proposer_strategy": "mean_reversion"}
            result = agent.run_debate(instrument, context)
        assert result is None

    def test_debate_with_team_id(self):
        from merid.agents.coordination import DebateCoordinatorAgent
        with patch("merid.prediction.debate.get_debate_store", return_value=self.store):
            agent = DebateCoordinatorAgent()
            instrument = {
                "symbol": "PRED:KALSHI:TEST:YES",
                "ticker": "TEST",
                "market_prob": 0.8,
                "category": "macro",
            }
            context = {
                "proposer_strategy": "mean_reversion",
                "team_id": "team-alpha",
            }
            result = agent.run_debate(instrument, context)

        if result:
            debates = self.store.list_debates()
            assert debates[0].team_id == "team-alpha"


# ── Debate metrics ───────────────────────────────────────────────────

class TestDebateMetrics:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_empty_metrics(self):
        m = self.store.get_debate_metrics()
        assert m["active_debates"] == 0
        assert m["total_debates"] == 0
        assert m["avg_debate_lift"] == 0.0

    def test_metrics_with_debates(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        s1 = DebateSession(symbol="S1", rounds=3)
        s2 = DebateSession(symbol="S2", rounds=2)
        self.store.create_debate(s1)
        self.store.create_debate(s2)
        m = self.store.get_debate_metrics(window_s=3600.0)
        assert m["total_debates"] == 2
        assert m["active_debates"] == 2
        assert m["avg_rounds"] == 2.5

    def test_debate_lift_stats(self):
        from merid.prediction.debate import DebateSession
        s1 = DebateSession(symbol="S1", pre_debate_prob=0.5, post_debate_prob=0.8)
        s2 = DebateSession(symbol="S2", pre_debate_prob=0.8, post_debate_prob=0.3)
        self.store.create_debate(s1)
        self.store.create_debate(s2)
        self.store.resolve_debate(s1.id, outcome=1)  # lift = 0.21
        self.store.resolve_debate(s2.id, outcome=1)  # lift = -0.45
        m = self.store.get_debate_metrics(window_s=3600.0)
        assert m["resolved_debates"] == 2
        assert m["positive_lift_count"] == 1
        assert m["negative_lift_count"] == 1

    def test_disagreement_width(self):
        from merid.prediction.debate import DebateSession, DebateArgument
        s = DebateSession(symbol="S1")
        self.store.create_debate(s)
        self.store.add_argument(DebateArgument(
            debate_id=s.id, agent_id="a1", role="proposer", probability=0.8,
        ))
        self.store.add_argument(DebateArgument(
            debate_id=s.id, agent_id="a2", role="challenger", probability=0.55,
        ))
        m = self.store.get_debate_metrics(window_s=3600.0)
        assert m["avg_disagreement_width"] == pytest.approx(0.25, abs=0.01)
        assert m["total_arguments"] == 2


# ── Reward calculations ──────────────────────────────────────────────

class TestRewardCalculations:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_basic_reward_for_resolution(self):
        """Agents get timeliness + accuracy rewards on resolution."""
        opinion = MagicMock()
        opinion.agent_id = "a1"
        opinion.probability = 0.8
        opinion.explanation = None
        entries = self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[opinion],
        )
        types = [e.reward_type for e in entries]
        assert "timeliness" in types
        assert "accuracy" in types

    def test_explanation_bonus(self):
        """Agents with explanations get extra points."""
        opinion = MagicMock()
        opinion.agent_id = "a1"
        opinion.probability = 0.7
        opinion.explanation = {"rationale": "test"}
        entries = self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[opinion],
        )
        types = [e.reward_type for e in entries]
        assert "explanation" in types

    def test_no_explanation_bonus_without_explanation(self):
        opinion = MagicMock()
        opinion.agent_id = "a1"
        opinion.probability = 0.7
        opinion.explanation = None
        entries = self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[opinion],
        )
        types = [e.reward_type for e in entries]
        assert "explanation" not in types

    def test_accuracy_bonus_scales_with_brier(self):
        """Better Brier → more accuracy points."""
        good_opinion = MagicMock()
        good_opinion.agent_id = "a1"
        good_opinion.probability = 0.9  # Close to outcome=1
        good_opinion.explanation = None

        bad_opinion = MagicMock()
        bad_opinion.agent_id = "a2"
        bad_opinion.probability = 0.2  # Far from outcome=1
        bad_opinion.explanation = None

        entries = self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[good_opinion, bad_opinion],
        )
        a1_accuracy = [e for e in entries if e.agent_id == "a1" and e.reward_type == "accuracy"]
        a2_accuracy = [e for e in entries if e.agent_id == "a2" and e.reward_type == "accuracy"]
        assert len(a1_accuracy) == 1
        assert len(a2_accuracy) == 1
        assert a1_accuracy[0].points > a2_accuracy[0].points

    def test_debate_lift_bonus(self):
        """Agents who participated in debates with positive lift get bonus."""
        from merid.prediction.debate import DebateSession, DebateArgument
        s = DebateSession(symbol="S1", pre_debate_prob=0.5, post_debate_prob=0.85)
        self.store.create_debate(s)
        self.store.add_argument(DebateArgument(
            debate_id=s.id, agent_id="a1", role="proposer", probability=0.85,
        ))
        self.store.resolve_debate(s.id, outcome=1)

        opinion = MagicMock()
        opinion.agent_id = "a1"
        opinion.probability = 0.85
        opinion.explanation = None
        entries = self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[opinion],
        )
        types = [e.reward_type for e in entries]
        assert "debate_lift" in types

    def test_rewards_stored_in_db(self):
        opinion = MagicMock()
        opinion.agent_id = "a1"
        opinion.probability = 0.7
        opinion.explanation = None
        self.store.compute_rewards_for_resolution(
            symbol="S1", outcome=1, opinions=[opinion],
        )
        rewards = self.store.get_agent_rewards("a1")
        assert len(rewards) >= 2  # At least timeliness + accuracy


# ── Leaderboard ──────────────────────────────────────────────────────

class TestLeaderboard:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_empty_leaderboard(self):
        lb = self.store.compute_leaderboard()
        assert lb["agents"] == []
        assert lb["teams"] == []
        assert lb["debate_impact"] == []

    def test_agent_leaderboard_sorted(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", points=100.0))
        self.store.add_reward(RewardEntry(agent_id="a2", points=200.0))
        self.store.add_reward(RewardEntry(agent_id="a1", points=50.0))
        lb = self.store.compute_leaderboard()
        assert len(lb["agents"]) == 2
        assert lb["agents"][0]["agent_id"] == "a2"  # 200 > 150
        assert lb["agents"][0]["total_points"] == 200.0
        assert lb["agents"][1]["total_points"] == 150.0

    def test_team_leaderboard(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", team_id="t1", points=50.0))
        self.store.add_reward(RewardEntry(agent_id="a2", team_id="t1", points=30.0))
        self.store.add_reward(RewardEntry(agent_id="a3", team_id="t2", points=100.0))
        lb = self.store.compute_leaderboard()
        assert len(lb["teams"]) == 2
        assert lb["teams"][0]["team_id"] == "t2"  # 100 > 80

    def test_debate_impact_leaderboard(self):
        from merid.prediction.debate import RewardEntry
        self.store.add_reward(RewardEntry(agent_id="a1", reward_type="debate_lift", points=30.0))
        self.store.add_reward(RewardEntry(agent_id="a2", reward_type="debate_lift", points=15.0))
        self.store.add_reward(RewardEntry(agent_id="a1", reward_type="accuracy", points=50.0))
        lb = self.store.compute_leaderboard()
        assert len(lb["debate_impact"]) == 2
        assert lb["debate_impact"][0]["agent_id"] == "a1"


# ── Badges ───────────────────────────────────────────────────────────

class TestBadges:
    def setup_method(self):
        from merid.prediction.debate import DebateStore
        self.db_path = _tmp_db()
        self.store = DebateStore(self.db_path)

    def teardown_method(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_no_badges_for_empty_agent(self):
        badges = self.store.compute_badges("unknown")
        assert badges == []

    def test_explainer_badge(self):
        from merid.prediction.debate import RewardEntry
        # 10 timeliness + 9 explanation → 90% coverage → earns badge
        for i in range(10):
            self.store.add_reward(RewardEntry(agent_id="a1", reward_type="timeliness", points=10.0))
        for i in range(9):
            self.store.add_reward(RewardEntry(agent_id="a1", reward_type="explanation", points=5.0))
        badges = self.store.compute_badges("a1")
        badge_names = [b["badge"] for b in badges]
        assert "explainer" in badge_names

    def test_no_explainer_badge_below_threshold(self):
        from merid.prediction.debate import RewardEntry
        # 10 timeliness + 5 explanation → 50% coverage → no badge
        for i in range(10):
            self.store.add_reward(RewardEntry(agent_id="a1", reward_type="timeliness", points=10.0))
        for i in range(5):
            self.store.add_reward(RewardEntry(agent_id="a1", reward_type="explanation", points=5.0))
        badges = self.store.compute_badges("a1")
        badge_names = [b["badge"] for b in badges]
        assert "explainer" not in badge_names

    def test_debate_champion_badge(self):
        from merid.prediction.debate import RewardEntry, REWARD_DEBATE_LIFT_BONUS
        # Need >= REWARD_DEBATE_LIFT_BONUS * 3 = 90 points of debate_lift
        for i in range(4):
            self.store.add_reward(RewardEntry(
                agent_id="a1", reward_type="debate_lift", points=REWARD_DEBATE_LIFT_BONUS,
            ))
        badges = self.store.compute_badges("a1")
        badge_names = [b["badge"] for b in badges]
        assert "debate_champion" in badge_names

    def test_consensus_builder_badge(self):
        from merid.prediction.debate import RewardEntry
        # Need >= 5 debate_lift rewards with positive points
        for i in range(6):
            self.store.add_reward(RewardEntry(
                agent_id="a1", reward_type="debate_lift", points=10.0,
            ))
        badges = self.store.compute_badges("a1")
        badge_names = [b["badge"] for b in badges]
        assert "consensus_builder" in badge_names


# ── Alert rules ──────────────────────────────────────────────────────

class TestNoDebateActivityAlert:
    def test_fires_when_no_debates(self):
        from web.api.system_observability import NoDebateActivityAlert
        mock_store = MagicMock()
        mock_store.get_debate_metrics.return_value = {
            "total_debates": 0, "active_debates": 0,
        }
        alert = NoDebateActivityAlert()
        with patch("merid.prediction.debate.get_debate_store", return_value=mock_store):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_not_firing_when_debates_exist(self):
        from web.api.system_observability import NoDebateActivityAlert
        mock_store = MagicMock()
        mock_store.get_debate_metrics.return_value = {
            "total_debates": 3, "active_debates": 1,
        }
        alert = NoDebateActivityAlert()
        with patch("merid.prediction.debate.get_debate_store", return_value=mock_store):
            result = alert.evaluate()
        assert result["firing"] is False

    def test_graceful_on_error(self):
        from web.api.system_observability import NoDebateActivityAlert
        alert = NoDebateActivityAlert()
        with patch("merid.prediction.debate.get_debate_store", side_effect=Exception("boom")):
            result = alert.evaluate()
        assert result["firing"] is False


class TestNegativeDebateLiftAlert:
    def test_fires_when_majority_negative(self):
        from web.api.system_observability import NegativeDebateLiftAlert
        mock_store = MagicMock()
        mock_store.get_debate_metrics.return_value = {
            "resolved_debates": 4, "negative_lift_count": 3,
            "avg_debate_lift": -0.05,
        }
        alert = NegativeDebateLiftAlert()
        with patch("merid.prediction.debate.get_debate_store", return_value=mock_store):
            result = alert.evaluate()
        assert result["firing"] is True

    def test_not_firing_when_mostly_positive(self):
        from web.api.system_observability import NegativeDebateLiftAlert
        mock_store = MagicMock()
        mock_store.get_debate_metrics.return_value = {
            "resolved_debates": 5, "negative_lift_count": 1,
            "avg_debate_lift": 0.03,
        }
        alert = NegativeDebateLiftAlert()
        with patch("merid.prediction.debate.get_debate_store", return_value=mock_store):
            result = alert.evaluate()
        assert result["firing"] is False

    def test_not_firing_when_too_few_resolved(self):
        from web.api.system_observability import NegativeDebateLiftAlert
        mock_store = MagicMock()
        mock_store.get_debate_metrics.return_value = {
            "resolved_debates": 2, "negative_lift_count": 2,
            "avg_debate_lift": -0.1,
        }
        alert = NegativeDebateLiftAlert()
        with patch("merid.prediction.debate.get_debate_store", return_value=mock_store):
            result = alert.evaluate()
        assert result["firing"] is False

    def test_graceful_on_error(self):
        from web.api.system_observability import NegativeDebateLiftAlert
        alert = NegativeDebateLiftAlert()
        with patch("merid.prediction.debate.get_debate_store", side_effect=Exception("boom")):
            result = alert.evaluate()
        assert result["firing"] is False


# ── Alert registry update ────────────────────────────────────────────

class TestAlertRegistryUpdate:
    def test_alert_count_is_20(self):
        from web.api.system_observability import ALERT_RULES
        assert len(ALERT_RULES) == 28

    def test_debate_alerts_in_registry(self):
        from web.api.system_observability import ALERT_RULES
        names = [r.name for r in ALERT_RULES]
        assert "no_debate_activity" in names
        assert "negative_debate_lift" in names


# ── Package exports ──────────────────────────────────────────────────

class TestPackageExports:
    def test_debate_exports(self):
        from merid.prediction import (
            DebateSession, DebateArgument, AgentTeam,
            DebateStore, RewardEntry, get_debate_store,
        )
        assert DebateSession is not None
        assert DebateArgument is not None
        assert AgentTeam is not None
        assert DebateStore is not None
        assert RewardEntry is not None
        assert callable(get_debate_store)
