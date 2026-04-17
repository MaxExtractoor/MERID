"""Tests for the upgraded Betting Layer (Sprint 11).

Covers:
  §1 BookieAgent — pool lifecycle, bet placement, settlement, coherence, health
  §2 BettingEvent — schema, serialization, factory registration
  §3 Betting API — universal endpoints, legacy compat, discovery, agent introspection
  §4 Observability — BettingHealthAlert, BettingCoherenceAlert
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch, MagicMock

from trading.agents.bookie_agent import (
    BookieAgent,
    BettingPool,
    Bet,
    market_id_for_block,
    BINARY_OUTCOMES,
    BLOCK_OUTCOMES,
)


# ══════════════════════════════════════════════════════════════════════
# §1 BookieAgent
# ══════════════════════════════════════════════════════════════════════

class TestMarketIdForBlock(unittest.TestCase):
    """Test the canonical block → market_id helper."""

    def test_basic(self):
        self.assertEqual(market_id_for_block(42), "block:42")

    def test_zero(self):
        self.assertEqual(market_id_for_block(0), "block:0")


class TestBetDataclass(unittest.TestCase):
    """Test Bet dataclass helpers."""

    def test_block_index_property(self):
        bet = Bet(bet_id="b1", user_id="u1", market_id="block:7",
                  prediction="yes", stake_amount=10, odds=2.0, potential_payout=20)
        self.assertEqual(bet.block_index, 7)

    def test_block_index_none_for_non_block(self):
        bet = Bet(bet_id="b1", user_id="u1", market_id="PRED:KALSHI:X",
                  prediction="yes", stake_amount=10, odds=2.0, potential_payout=20)
        self.assertIsNone(bet.block_index)

    def test_calculate_payout(self):
        bet = Bet(bet_id="b1", user_id="u1", market_id="m1",
                  prediction="yes", stake_amount=50, odds=3.0, potential_payout=150)
        self.assertAlmostEqual(bet.calculate_payout(), 150.0)

    def test_to_dict(self):
        bet = Bet(bet_id="b1", user_id="u1", market_id="m1",
                  prediction="yes", stake_amount=10, odds=2.0, potential_payout=20,
                  role="hedging", stated_probability=0.6, implied_probability=0.5)
        d = bet.to_dict()
        self.assertEqual(d["bet_id"], "b1")
        self.assertEqual(d["role"], "hedging")
        self.assertAlmostEqual(d["stated_probability"], 0.6)


class TestBettingPoolDataclass(unittest.TestCase):
    """Test BettingPool dataclass helpers."""

    def test_block_index_property(self):
        pool = BettingPool(market_id="block:99")
        self.assertEqual(pool.block_index, 99)

    def test_block_index_none(self):
        pool = BettingPool(market_id="PRED:X")
        self.assertIsNone(pool.block_index)

    def test_lock_pool(self):
        pool = BettingPool(market_id="m1")
        pool.lock_pool()
        self.assertTrue(pool.locked)
        self.assertIsNotNone(pool.locked_at)

    def test_settle_pool_requires_lock(self):
        pool = BettingPool(market_id="m1")
        with self.assertRaises(ValueError):
            pool.settle_pool("yes")

    def test_settle_pool_double_settle(self):
        pool = BettingPool(market_id="m1")
        pool.lock_pool()
        pool.settle_pool("yes")
        with self.assertRaises(ValueError):
            pool.settle_pool("yes")

    def test_settle_pool_payouts(self):
        pool = BettingPool(market_id="m1", house_cut_pct=10.0)
        pool.bets.append(Bet(bet_id="b1", user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=100, odds=2.0, potential_payout=200))
        pool.bets.append(Bet(bet_id="b2", user_id="u2", market_id="m1",
                             prediction="no", stake_amount=100, odds=2.0, potential_payout=200))
        pool.total_pool = 200
        pool.lock_pool()
        payouts = pool.settle_pool("yes")
        # u1 wins: gets stake back + (100 losing - 10% house) = 100 + 90 = 190
        self.assertIn("u1", payouts)
        self.assertAlmostEqual(payouts["u1"], 190.0)
        self.assertNotIn("u2", payouts)

    def test_to_dict(self):
        pool = BettingPool(market_id="m1", allowed_outcomes=["yes", "no"])
        d = pool.to_dict()
        self.assertEqual(d["market_id"], "m1")
        self.assertEqual(d["allowed_outcomes"], ["yes", "no"])


class TestBookieAgentPoolLifecycle(unittest.TestCase):
    """Test pool create → lock → settle lifecycle."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0, min_bet_amount=1.0, max_bet_amount=10000.0)

    def test_create_pool(self):
        pool = self.agent.create_pool("PRED:TEST:1")
        self.assertIn("PRED:TEST:1", self.agent.pools)
        self.assertEqual(pool.market_id, "PRED:TEST:1")

    def test_create_pool_duplicate(self):
        self.agent.create_pool("PRED:TEST:1")
        with self.assertRaises(ValueError):
            self.agent.create_pool("PRED:TEST:1")

    def test_create_pool_with_outcomes(self):
        pool = self.agent.create_pool("m1", allowed_outcomes=["yes", "no"])
        self.assertEqual(pool.allowed_outcomes, ["yes", "no"])

    def test_create_betting_pool_legacy(self):
        pool = self.agent.create_betting_pool(42)
        self.assertIn("block:42", self.agent.pools)
        self.assertEqual(pool.block_index, 42)

    def test_lock_pool(self):
        self.agent.create_pool("m1")
        self.agent.lock_pool("m1")
        self.assertTrue(self.agent.pools["m1"].locked)

    def test_lock_pool_missing(self):
        with self.assertRaises(ValueError):
            self.agent.lock_pool("nonexistent")

    def test_lock_pool_for_mining_legacy(self):
        self.agent.create_betting_pool(10)
        self.agent.lock_pool_for_mining(10)
        self.assertTrue(self.agent.pools["block:10"].locked)


class TestBookieAgentBetPlacement(unittest.TestCase):
    """Test bet placement with balance checks, odds, roles, coherence."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0, min_bet_amount=1.0, max_bet_amount=10000.0)
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 1000.0)

    def test_place_bet_basic(self):
        bet = self.agent.place_bet(user_id="u1", market_id="m1",
                                   prediction="yes", stake_amount=100.0)
        self.assertEqual(bet.market_id, "m1")
        self.assertEqual(bet.prediction, "yes")
        self.assertAlmostEqual(bet.stake_amount, 100.0)
        self.assertGreater(bet.odds, 1.0)
        self.assertEqual(self.agent.user_balances["u1"], 900.0)

    def test_place_bet_with_role(self):
        bet = self.agent.place_bet(user_id="u1", market_id="m1",
                                   prediction="yes", stake_amount=50.0, role="hedging")
        self.assertEqual(bet.role, "hedging")

    def test_place_bet_with_stated_probability(self):
        bet = self.agent.place_bet(user_id="u1", market_id="m1",
                                   prediction="yes", stake_amount=50.0,
                                   stated_probability=0.7)
        self.assertAlmostEqual(bet.stated_probability, 0.7)
        self.assertIsNotNone(bet.implied_probability)

    def test_place_bet_insufficient_balance(self):
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="m1",
                                 prediction="yes", stake_amount=5000.0)

    def test_place_bet_below_min(self):
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="m1",
                                 prediction="yes", stake_amount=0.5)

    def test_place_bet_above_max(self):
        self.agent.deposit("u1", 50000.0)
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="m1",
                                 prediction="yes", stake_amount=20000.0)

    def test_place_bet_locked_pool(self):
        self.agent.lock_pool("m1")
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="m1",
                                 prediction="yes", stake_amount=50.0)

    def test_place_bet_invalid_outcome(self):
        self.agent.create_pool("m2", allowed_outcomes=["yes", "no"])
        self.agent.deposit("u1", 1000.0)
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="m2",
                                 prediction="maybe", stake_amount=50.0)

    def test_place_bet_missing_pool(self):
        with self.assertRaises(ValueError):
            self.agent.place_bet(user_id="u1", market_id="nonexistent",
                                 prediction="yes", stake_amount=50.0)

    def test_place_bet_legacy_block_index(self):
        self.agent.create_betting_pool(5)
        bet = self.agent.place_bet(user_id="u1", block_index=5,
                                   prediction="approved", stake_amount=50.0)
        self.assertEqual(bet.market_id, "block:5")

    def test_volume_tracking(self):
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=100.0)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="no", stake_amount=50.0)
        self.assertEqual(self.agent.total_bets_placed, 2)
        self.assertAlmostEqual(self.agent.total_volume, 150.0)


class TestBookieAgentSettlement(unittest.TestCase):
    """Test pool settlement and payout distribution."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0, min_bet_amount=1.0, max_bet_amount=10000.0)
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 1000.0)
        self.agent.deposit("u2", 1000.0)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=100.0)
        self.agent.place_bet(user_id="u2", market_id="m1",
                             prediction="no", stake_amount=100.0)
        self.agent.lock_pool("m1")

    def test_settle_pool_with_outcome(self):
        payouts = self.agent.settle_pool_with_outcome("m1", "yes")
        self.assertIn("u1", payouts)
        self.assertGreater(payouts["u1"], 100.0)  # gets stake back + winnings
        self.assertTrue(self.agent.pools["m1"].settled)

    def test_settle_pool_credits_balances(self):
        bal_before = self.agent.user_balances["u1"]
        payouts = self.agent.settle_pool_with_outcome("m1", "yes")
        bal_after = self.agent.user_balances["u1"]
        self.assertAlmostEqual(bal_after, bal_before + payouts["u1"])

    def test_settle_pool_house_earnings(self):
        self.agent.settle_pool_with_outcome("m1", "yes")
        self.assertGreater(self.agent.total_house_earnings, 0)

    def test_settle_pool_legacy(self):
        agent = BookieAgent(house_cut_pct=5.0)
        agent.create_betting_pool(1)
        agent.deposit("u1", 500)
        agent.deposit("u2", 500)
        agent.place_bet(user_id="u1", block_index=1, prediction="high_confidence", stake_amount=100)
        agent.place_bet(user_id="u2", block_index=1, prediction="rejected", stake_amount=100)
        agent.lock_pool_for_mining(1)
        payouts = agent.settle_pool(block_index=1, consensus_approved=True, consensus_confidence=0.8)
        # outcome = "high_confidence" since approved + confidence >= 0.75
        self.assertIn("u1", payouts)
        self.assertTrue(agent.pools["block:1"].settled)
        self.assertEqual(agent.pools["block:1"].actual_outcome, "high_confidence")

    def test_settle_pool_legacy_low_confidence(self):
        agent = BookieAgent(house_cut_pct=5.0)
        agent.create_betting_pool(2)
        agent.deposit("u1", 500)
        agent.place_bet(user_id="u1", block_index=2, prediction="rejected", stake_amount=100)
        agent.lock_pool_for_mining(2)
        payouts = agent.settle_pool(block_index=2, consensus_approved=False, consensus_confidence=0.6)
        self.assertTrue(agent.pools["block:2"].settled)
        self.assertEqual(agent.pools["block:2"].actual_outcome, "rejected")


class TestBookieAgentBalanceManagement(unittest.TestCase):
    """Test deposit and withdraw."""

    def setUp(self):
        self.agent = BookieAgent()

    def test_deposit(self):
        self.agent.deposit("u1", 500.0)
        self.assertAlmostEqual(self.agent.user_balances["u1"], 500.0)

    def test_deposit_negative(self):
        with self.assertRaises(ValueError):
            self.agent.deposit("u1", -10.0)

    def test_withdraw(self):
        self.agent.deposit("u1", 500.0)
        result = self.agent.withdraw("u1", 200.0)
        self.assertTrue(result)
        self.assertAlmostEqual(self.agent.user_balances["u1"], 300.0)

    def test_withdraw_insufficient(self):
        self.agent.deposit("u1", 100.0)
        result = self.agent.withdraw("u1", 200.0)
        self.assertFalse(result)

    def test_withdraw_negative(self):
        result = self.agent.withdraw("u1", -10.0)
        self.assertFalse(result)


class TestBookieAgentQueries(unittest.TestCase):
    """Test user stats, pool stats, performance stats."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0)
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 1000.0)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=100.0)

    def test_get_user_stats(self):
        stats = self.agent.get_user_stats("u1")
        self.assertEqual(stats["user_id"], "u1")
        self.assertEqual(stats["total_bets"], 1)
        self.assertAlmostEqual(stats["total_wagered"], 100.0)

    def test_get_user_stats_empty(self):
        stats = self.agent.get_user_stats("unknown")
        self.assertEqual(stats["total_bets"], 0)

    def test_get_pool_stats_by_market_id(self):
        stats = self.agent.get_pool_stats(market_id="m1")
        self.assertEqual(stats["market_id"], "m1")
        self.assertEqual(stats["total_bets"], 1)

    def test_get_pool_stats_by_block_index(self):
        self.agent.create_betting_pool(7)
        stats = self.agent.get_pool_stats(block_index=7)
        self.assertEqual(stats["market_id"], "block:7")
        self.assertEqual(stats["block_index"], 7)

    def test_get_pool_stats_missing(self):
        stats = self.agent.get_pool_stats(market_id="nonexistent")
        self.assertEqual(stats, {})

    def test_get_performance_stats(self):
        perf = self.agent.get_performance_stats()
        self.assertEqual(perf["total_bets_placed"], 1)
        self.assertGreater(perf["total_volume"], 0)
        self.assertEqual(perf["total_pools"], 1)

    def test_legacy_betting_pools_property(self):
        self.agent.create_betting_pool(42)
        legacy = self.agent.betting_pools
        self.assertIn(42, legacy)
        self.assertEqual(legacy[42].market_id, "block:42")


class TestBookieAgentCoherence(unittest.TestCase):
    """Test agent coherence scoring."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0)
        self.agent.create_pool("m1")
        self.agent.deposit("agent1", 1000.0)

    def test_coherence_no_bets(self):
        report = self.agent.get_agent_coherence("agent1")
        self.assertEqual(report["total_bets"], 0)
        self.assertIsNone(report["coherence_score"])

    def test_coherence_with_stated_prob(self):
        self.agent.place_bet(user_id="agent1", market_id="m1",
                             prediction="yes", stake_amount=50.0,
                             stated_probability=0.5)
        report = self.agent.get_agent_coherence("agent1")
        self.assertEqual(report["total_bets"], 1)
        self.assertIsNotNone(report["coherence_score"])

    def test_coherence_roles(self):
        self.agent.place_bet(user_id="agent1", market_id="m1",
                             prediction="yes", stake_amount=50.0,
                             role="hedging", stated_probability=0.5)
        report = self.agent.get_agent_coherence("agent1")
        self.assertIn("hedging", report["roles"])


class TestBookieAgentHealth(unittest.TestCase):
    """Test betting health metrics."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=5.0)

    def test_health_empty(self):
        health = self.agent.get_betting_health()
        self.assertEqual(health["total_pools"], 0)
        self.assertEqual(health["one_sided_pools"], 0)

    def test_health_one_sided_detection(self):
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 500)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=50)
        health = self.agent.get_betting_health()
        self.assertEqual(health["one_sided_pools"], 1)

    def test_health_not_one_sided(self):
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 500)
        self.agent.deposit("u2", 500)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=50)
        self.agent.place_bet(user_id="u2", market_id="m1",
                             prediction="no", stake_amount=50)
        health = self.agent.get_betting_health()
        self.assertEqual(health["one_sided_pools"], 0)

    def test_health_settlement_latency(self):
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 500)
        self.agent.deposit("u2", 500)
        self.agent.place_bet(user_id="u1", market_id="m1",
                             prediction="yes", stake_amount=50)
        self.agent.place_bet(user_id="u2", market_id="m1",
                             prediction="no", stake_amount=50)
        self.agent.lock_pool("m1")
        # Verify locked_at is set
        self.assertIsNotNone(self.agent.pools["m1"].locked_at)
        self.agent.settle_pool_with_outcome("m1", "yes")
        # Verify settled_at is set
        self.assertIsNotNone(self.agent.pools["m1"].settled_at)
        health = self.agent.get_betting_health()
        # avg_settlement_latency_s should be a float >= 0
        self.assertIsNotNone(health["avg_settlement_latency_s"])
        self.assertGreaterEqual(health["avg_settlement_latency_s"], 0.0)


class TestBookieAgentDiscovery(unittest.TestCase):
    """Test list_active_pools and list_all_pools."""

    def setUp(self):
        self.agent = BookieAgent()

    def test_list_active_pools_empty(self):
        self.assertEqual(self.agent.list_active_pools(), [])

    def test_list_active_pools(self):
        self.agent.create_pool("m1")
        self.agent.create_pool("m2")
        active = self.agent.list_active_pools()
        self.assertEqual(len(active), 2)

    def test_list_active_excludes_locked(self):
        self.agent.create_pool("m1")
        self.agent.lock_pool("m1")
        active = self.agent.list_active_pools()
        self.assertEqual(len(active), 0)

    def test_list_all_pools(self):
        self.agent.create_pool("m1")
        self.agent.create_pool("m2")
        self.agent.deposit("u1", 500)
        self.agent.place_bet(user_id="u1", market_id="m1", prediction="yes", stake_amount=10)
        self.agent.lock_pool("m1")
        self.agent.settle_pool_with_outcome("m1", "yes")
        # m1 settled, m2 active
        all_pools = self.agent.list_all_pools(include_settled=False)
        self.assertEqual(len(all_pools), 1)
        all_pools_incl = self.agent.list_all_pools(include_settled=True)
        self.assertEqual(len(all_pools_incl), 2)


class TestBookieAgentRewards(unittest.TestCase):
    """Test agent reward distribution."""

    def setUp(self):
        self.agent = BookieAgent(house_cut_pct=10.0)
        self.agent.create_pool("m1")
        self.agent.deposit("u1", 500)
        self.agent.deposit("u2", 500)
        self.agent.place_bet(user_id="u1", market_id="m1", prediction="yes", stake_amount=100)
        self.agent.place_bet(user_id="u2", market_id="m1", prediction="no", stake_amount=100)
        self.agent.lock_pool("m1")
        self.agent.settle_pool_with_outcome("m1", "yes")

    def test_reward_agents_correct(self):
        self.agent.reward_agents(market_id="m1", agent_votes={"a1": True, "a2": False})
        self.assertGreater(self.agent.agent_rewards.get("a1", 0), 0)
        self.assertEqual(self.agent.agent_rewards.get("a2", 0), 0)

    def test_reward_agents_legacy(self):
        agent = BookieAgent(house_cut_pct=10.0)
        agent.create_betting_pool(1)
        agent.deposit("u1", 500)
        agent.place_bet(user_id="u1", block_index=1, prediction="approved", stake_amount=100)
        agent.lock_pool_for_mining(1)
        agent.settle_pool(block_index=1, consensus_approved=True, consensus_confidence=0.6)
        agent.reward_agents(block_index=1, agent_votes={"a1": True})
        self.assertGreater(agent.agent_rewards.get("a1", 0), 0)

    def test_reward_agents_unsettled_pool(self):
        agent = BookieAgent()
        agent.create_pool("m2")
        agent.reward_agents(market_id="m2", agent_votes={"a1": True})
        self.assertEqual(agent.agent_rewards.get("a1", 0), 0)


# ══════════════════════════════════════════════════════════════════════
# §2 BettingEvent schema
# ══════════════════════════════════════════════════════════════════════

class TestBettingEventSchema(unittest.TestCase):
    """Test BettingEvent dataclass and factory registration."""

    def test_create_betting_event(self):
        from merid.rewards.events import BettingEvent
        evt = BettingEvent(
            action="bet_placed",
            market_id="PRED:TEST:1",
            bet_id="b123",
            prediction="yes",
            stake_amount=100.0,
            odds=2.5,
            role="directional",
        )
        self.assertEqual(evt.action, "bet_placed")
        self.assertEqual(evt.market_id, "PRED:TEST:1")

    def test_betting_event_to_dict(self):
        from merid.rewards.events import BettingEvent
        evt = BettingEvent(
            action="pool_settled",
            market_id="m1",
            prediction="yes",
            stake_amount=50.0,
            odds=1.8,
            payout=90.0,
            net_profit=40.0,
            won=True,
            coherence_score=0.85,
        )
        d = evt.to_dict()
        self.assertEqual(d["action"], "pool_settled")
        self.assertEqual(d["market_id"], "m1")
        self.assertAlmostEqual(d["coherence_score"], 0.85)

    def test_betting_event_category(self):
        from merid.rewards.events import BettingEvent, EventCategory
        evt = BettingEvent(action="bet_placed", market_id="m1")
        self.assertEqual(evt.category, EventCategory.BETTING.value)

    def test_event_factory_roundtrip(self):
        from merid.rewards.events import BettingEvent, event_from_dict
        evt = BettingEvent(
            action="bet_placed",
            market_id="m1",
            bet_id="b1",
            prediction="yes",
            stake_amount=100.0,
            odds=2.0,
        )
        d = evt.to_dict()
        restored = event_from_dict(d)
        self.assertIsInstance(restored, BettingEvent)
        self.assertEqual(restored.action, "bet_placed")
        self.assertEqual(restored.market_id, "m1")


# ══════════════════════════════════════════════════════════════════════
# §3 Betting API endpoints
# ══════════════════════════════════════════════════════════════════════

class TestBettingAPI(unittest.TestCase):
    """Test REST API endpoints via FastAPI TestClient."""

    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.api.betting import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _reset_bookie(self):
        import web.api.betting as mod
        mod._bookie_agent = None

    def setUp(self):
        self._reset_bookie()

    def tearDown(self):
        self._reset_bookie()

    # ── Pool lifecycle ────────────────────────────────────────────────

    def test_create_market_pool(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/markets/PRED:TEST:1/create", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["market_id"], "PRED:TEST:1")
        self.assertEqual(data["status"], "created")

    def test_create_market_pool_duplicate(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.post("/api/v1/betting/markets/m1/create", json={})
        self.assertEqual(resp.status_code, 400)

    def test_lock_market_pool(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.post("/api/v1/betting/markets/m1/lock")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "locked")

    def test_lock_missing_pool(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/markets/nonexistent/lock")
        self.assertEqual(resp.status_code, 400)

    # ── Bet placement ─────────────────────────────────────────────────

    def test_place_bet_universal(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        resp = client.post("/api/v1/betting/place", json={
            "user_id": "u1", "market_id": "m1",
            "prediction": "yes", "stake_amount": 50,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["market_id"], "m1")
        self.assertEqual(data["prediction"], "yes")

    def test_place_bet_legacy_block_index(self):
        client = self._get_client()
        client.post("/api/v1/betting/pools/5/create")
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        resp = client.post("/api/v1/betting/place", json={
            "user_id": "u1", "block_index": 5,
            "prediction": "approved", "stake_amount": 50,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["market_id"], "block:5")

    def test_place_bet_no_market_id(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/place", json={
            "user_id": "u1", "prediction": "yes", "stake_amount": 50,
        })
        self.assertEqual(resp.status_code, 400)

    # ── Settlement ────────────────────────────────────────────────────

    def test_settle_with_explicit_outcome(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "market_id": "m1",
            "prediction": "yes", "stake_amount": 50,
        })
        client.post("/api/v1/betting/markets/m1/lock")
        resp = client.post("/api/v1/betting/markets/m1/settle", json={"outcome": "yes"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "settled")
        self.assertEqual(resp.json()["outcome"], "yes")

    def test_settle_no_params(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/markets/m1/lock")
        resp = client.post("/api/v1/betting/markets/m1/settle", json={})
        self.assertEqual(resp.status_code, 400)

    # ── Market info ───────────────────────────────────────────────────

    def test_get_market_pool_info(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.get("/api/v1/betting/markets/m1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["market_id"], "m1")

    def test_get_market_pool_not_found(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/markets/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_get_market_bets(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "market_id": "m1",
            "prediction": "yes", "stake_amount": 50,
        })
        resp = client.get("/api/v1/betting/markets/m1/bets")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    # ── Discovery ─────────────────────────────────────────────────────

    def test_discover_markets(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.get("/api/v1/betting/discover")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total_active_pools"], 1)

    def test_active_pools(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.get("/api/v1/betting/pools/active")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_active"], 1)

    def test_all_pools(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        resp = client.get("/api/v1/betting/pools/all")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 1)

    # ── User endpoints ────────────────────────────────────────────────

    def test_user_stats_with_positions(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "market_id": "m1",
            "prediction": "yes", "stake_amount": 50,
        })
        resp = client.get("/api/v1/betting/user/u1/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_bets"], 1)
        self.assertIn("open_positions", data)
        self.assertEqual(len(data["open_positions"]), 1)

    def test_user_balance(self):
        client = self._get_client()
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 250})
        resp = client.get("/api/v1/betting/user/u1/balance")
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(resp.json()["balance"], 250.0)

    def test_deposit(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 100})
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(resp.json()["new_balance"], 100.0)

    def test_withdraw(self):
        client = self._get_client()
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 200})
        resp = client.post("/api/v1/betting/withdraw", json={"user_id": "u1", "amount": 50})
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(resp.json()["new_balance"], 150.0)

    def test_withdraw_insufficient(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/withdraw", json={"user_id": "u1", "amount": 50})
        self.assertEqual(resp.status_code, 400)

    def test_leaderboard(self):
        client = self._get_client()
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 100})
        resp = client.get("/api/v1/betting/leaderboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("leaderboard", resp.json())

    # ── Agent introspection ───────────────────────────────────────────

    def test_agent_rewards(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/agents/rewards")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("agent_rewards", resp.json())

    def test_agent_coherence(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/agents/agent1/coherence")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("coherence_score", resp.json())

    def test_reward_agents_universal(self):
        client = self._get_client()
        client.post("/api/v1/betting/markets/m1/create", json={})
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "market_id": "m1",
            "prediction": "yes", "stake_amount": 50,
        })
        client.post("/api/v1/betting/markets/m1/lock")
        client.post("/api/v1/betting/markets/m1/settle", json={"outcome": "yes"})
        resp = client.post("/api/v1/betting/agents/reward", json={
            "market_id": "m1", "agent_votes": {"a1": True},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "agents_rewarded")

    def test_reward_agents_no_market(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/agents/reward", json={
            "agent_votes": {"a1": True},
        })
        self.assertEqual(resp.status_code, 400)

    # ── System ────────────────────────────────────────────────────────

    def test_stats(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("house_cut_pct", data)
        self.assertIn("total_bets_placed", data)

    def test_health(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total_pools", data)
        self.assertIn("one_sided_pools", data)

    # ── Legacy block-index endpoints ──────────────────────────────────

    def test_legacy_create_pool(self):
        client = self._get_client()
        resp = client.post("/api/v1/betting/pools/42/create")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["block_index"], 42)
        self.assertIn("market_id", data)

    def test_legacy_lock_pool(self):
        client = self._get_client()
        client.post("/api/v1/betting/pools/42/create")
        resp = client.post("/api/v1/betting/pools/42/lock")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "locked")

    def test_legacy_settle_pool(self):
        client = self._get_client()
        client.post("/api/v1/betting/pools/42/create")
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "block_index": 42,
            "prediction": "approved", "stake_amount": 50,
        })
        client.post("/api/v1/betting/pools/42/lock")
        resp = client.post("/api/v1/betting/pools/42/settle?consensus_approved=true&consensus_confidence=0.8")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "settled")

    def test_legacy_get_pool_info(self):
        client = self._get_client()
        client.post("/api/v1/betting/pools/42/create")
        resp = client.get("/api/v1/betting/pools/42")
        self.assertEqual(resp.status_code, 200)

    def test_legacy_get_pool_not_found(self):
        client = self._get_client()
        resp = client.get("/api/v1/betting/pools/999")
        self.assertEqual(resp.status_code, 404)

    def test_legacy_reward_agents(self):
        client = self._get_client()
        client.post("/api/v1/betting/pools/42/create")
        client.post("/api/v1/betting/deposit", json={"user_id": "u1", "amount": 500})
        client.post("/api/v1/betting/place", json={
            "user_id": "u1", "block_index": 42,
            "prediction": "approved", "stake_amount": 50,
        })
        client.post("/api/v1/betting/pools/42/lock")
        client.post("/api/v1/betting/pools/42/settle?consensus_approved=true&consensus_confidence=0.6")
        resp = client.post("/api/v1/betting/agents/reward/42?reward_pool_pct=10")
        self.assertEqual(resp.status_code, 200)


# ══════════════════════════════════════════════════════════════════════
# §4 Observability alerts
# ══════════════════════════════════════════════════════════════════════

class TestBettingHealthAlert(unittest.TestCase):
    """Test BettingHealthAlert evaluation."""

    def test_not_firing_empty(self):
        from web.api.system_observability import BettingHealthAlert
        with patch("web.api.betting.get_bookie_agent") as mock:
            agent = BookieAgent()
            mock.return_value = agent
            alert = BettingHealthAlert()
            result = alert.evaluate()
            self.assertFalse(result["firing"])

    def test_fires_on_one_sided_pools(self):
        from web.api.system_observability import BettingHealthAlert
        with patch("web.api.betting.get_bookie_agent") as mock:
            agent = BookieAgent()
            for i in range(4):
                agent.create_pool(f"m{i}")
                agent.deposit(f"u{i}", 500)
                agent.place_bet(user_id=f"u{i}", market_id=f"m{i}",
                                prediction="yes", stake_amount=50)
            mock.return_value = agent
            alert = BettingHealthAlert()
            result = alert.evaluate()
            self.assertTrue(result["firing"])
            self.assertGreater(result["detail"]["one_sided_pools"], 2)


class TestBettingCoherenceAlert(unittest.TestCase):
    """Test BettingCoherenceAlert evaluation."""

    def test_not_firing_no_data(self):
        from web.api.system_observability import BettingCoherenceAlert
        with patch("web.api.betting.get_bookie_agent") as mock:
            agent = BookieAgent()
            mock.return_value = agent
            alert = BettingCoherenceAlert()
            result = alert.evaluate()
            self.assertFalse(result["firing"])

    def test_not_firing_high_coherence(self):
        from web.api.system_observability import BettingCoherenceAlert
        with patch("web.api.betting.get_bookie_agent") as mock:
            agent = BookieAgent(house_cut_pct=5.0)
            agent.create_pool("m1")
            agent.deposit("a1", 5000)
            # Place bets with high coherence (stated prob close to implied)
            for i in range(6):
                agent.place_bet(user_id="a1", market_id="m1",
                                prediction="yes", stake_amount=10,
                                stated_probability=0.5)
            mock.return_value = agent
            alert = BettingCoherenceAlert()
            result = alert.evaluate()
            # Coherence should be high, so not firing
            self.assertFalse(result["firing"])


class TestAlertRegistryCount(unittest.TestCase):
    """Verify the alert registry has the expected count after adding betting alerts."""

    def test_alert_count(self):
        from web.api.system_observability import ALERT_RULES
        # 20 base + 2 betting + 3 sports/live + 3 sports integration = 28
        self.assertEqual(len(ALERT_RULES), 28)


if __name__ == "__main__":
    unittest.main()
