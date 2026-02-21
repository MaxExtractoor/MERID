"""
Tests for swarm/mev_rewards.py — MEVRewardSystem.

Covers:
- MEV classification (safe/neutral/harmful)
- Action recording and actor stats
- Health score calculation
- Reward calculation and distribution
- Reward pools
- Health metrics
- Badges and tiers
"""

import unittest
from decimal import Decimal

from swarm.mev_rewards import (
    ActorStats,
    HealthMetrics,
    MEVAction,
    MEVCategory,
    MEVRewardSystem,
    MEVType,
    RewardPool,
)


class TestMEVClassification(unittest.TestCase):
    """MEV action classification."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_sandwich_is_harmful(self):
        cat = self.system.classify_mev_action(
            MEVType.SANDWICH, Decimal("0"), 0.0
        )
        self.assertEqual(cat, MEVCategory.HARMFUL)

    def test_frontrun_negative_impact_is_harmful(self):
        cat = self.system.classify_mev_action(
            MEVType.FRONTRUN, Decimal("-100"), 0.0
        )
        self.assertEqual(cat, MEVCategory.HARMFUL)

    def test_arbitrage_with_spread_improvement_is_safe(self):
        cat = self.system.classify_mev_action(
            MEVType.ARBITRAGE, Decimal("0"), 5.0
        )
        self.assertEqual(cat, MEVCategory.SAFE)

    def test_liquidation_is_safe(self):
        cat = self.system.classify_mev_action(
            MEVType.LIQUIDATION, Decimal("0"), 0.0
        )
        self.assertEqual(cat, MEVCategory.SAFE)

    def test_backrun_non_negative_is_safe(self):
        cat = self.system.classify_mev_action(
            MEVType.BACKRUN, Decimal("0"), 0.0
        )
        self.assertEqual(cat, MEVCategory.SAFE)

    def test_arbitrage_no_spread_improvement_is_neutral(self):
        cat = self.system.classify_mev_action(
            MEVType.ARBITRAGE, Decimal("0"), 0.0
        )
        self.assertEqual(cat, MEVCategory.NEUTRAL)

    def test_frontrun_non_negative_is_neutral(self):
        cat = self.system.classify_mev_action(
            MEVType.FRONTRUN, Decimal("10"), 0.0
        )
        self.assertEqual(cat, MEVCategory.NEUTRAL)


class TestActionRecording(unittest.TestCase):
    """Recording MEV actions."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_record_action(self):
        action = self.system.record_mev_action(
            actor_id="bot-1",
            mev_type=MEVType.ARBITRAGE,
            block_number=12345,
            transaction_hash="0xabc",
            profit_usd=Decimal("100"),
            spread_improvement_bps=5.0,
        )
        self.assertEqual(action.actor_id, "bot-1")
        self.assertEqual(action.mev_type, MEVType.ARBITRAGE)
        self.assertEqual(action.mev_category, MEVCategory.SAFE)
        self.assertGreater(action.health_score, 0)
        self.assertEqual(len(self.system._mev_actions), 1)

    def test_record_harmful_action(self):
        action = self.system.record_mev_action(
            actor_id="bot-2",
            mev_type=MEVType.SANDWICH,
            block_number=12346,
            transaction_hash="0xdef",
            profit_usd=Decimal("50"),
            user_impact_usd=Decimal("-200"),
        )
        self.assertEqual(action.mev_category, MEVCategory.HARMFUL)
        self.assertLess(action.health_score, 0)

    def test_multiple_actions_tracked(self):
        for i in range(5):
            self.system.record_mev_action(
                actor_id="bot-1",
                mev_type=MEVType.ARBITRAGE,
                block_number=12345 + i,
                transaction_hash=f"0x{i:04x}",
                profit_usd=Decimal("10"),
                spread_improvement_bps=1.0,
            )
        self.assertEqual(len(self.system._mev_actions), 5)


class TestActorStats(unittest.TestCase):
    """Actor statistics tracking."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_stats_created_on_first_action(self):
        self.system.record_mev_action(
            actor_id="new-bot", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("10"), spread_improvement_bps=1.0,
        )
        stats = self.system.get_actor_stats("new-bot")
        self.assertIsNotNone(stats)
        self.assertEqual(stats.total_actions, 1)
        self.assertEqual(stats.safe_actions, 1)

    def test_stats_accumulate(self):
        # Safe action
        self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("100"), spread_improvement_bps=5.0,
        )
        # Harmful action
        self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.SANDWICH,
            block_number=2, transaction_hash="0x2",
            profit_usd=Decimal("50"), user_impact_usd=Decimal("-200"),
        )
        stats = self.system.get_actor_stats("bot-1")
        self.assertEqual(stats.total_actions, 2)
        self.assertEqual(stats.safe_actions, 1)
        self.assertEqual(stats.harmful_actions, 1)
        self.assertEqual(stats.total_profit_usd, Decimal("150"))

    def test_nonexistent_actor_returns_none(self):
        self.assertIsNone(self.system.get_actor_stats("ghost"))


class TestHealthScore(unittest.TestCase):
    """Health score calculation."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_safe_category_positive_score(self):
        score = self.system._calculate_health_score(
            MEVCategory.SAFE, Decimal("10"), 5.0, Decimal("1000"), 2.0
        )
        self.assertGreater(score, 0)

    def test_harmful_category_negative_score(self):
        score = self.system._calculate_health_score(
            MEVCategory.HARMFUL, Decimal("-100"), 0.0, Decimal("0"), 0.0
        )
        self.assertLess(score, 0)

    def test_score_clamped_to_range(self):
        # Max positive
        score = self.system._calculate_health_score(
            MEVCategory.SAFE, Decimal("1000"), 100.0, Decimal("1000000"), 100.0
        )
        self.assertLessEqual(score, 1.0)
        # Max negative
        score = self.system._calculate_health_score(
            MEVCategory.HARMFUL, Decimal("-1000"), 0.0, Decimal("0"), 0.0
        )
        self.assertGreaterEqual(score, -1.0)

    def test_neutral_category_base_zero(self):
        score = self.system._calculate_health_score(
            MEVCategory.NEUTRAL, Decimal("0"), 0.0, Decimal("0"), 0.0
        )
        self.assertEqual(score, 0.0)


class TestRewardCalculation(unittest.TestCase):
    """Reward calculation."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_safe_action_positive_reward(self):
        action = self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("1000"), spread_improvement_bps=10.0,
        )
        result = self.system.calculate_reward(action.action_id)
        self.assertGreater(result.total_reward, Decimal("0"))
        self.assertGreater(result.base_reward, Decimal("0"))

    def test_harmful_action_no_positive_reward(self):
        action = self.system.record_mev_action(
            actor_id="bot-2", mev_type=MEVType.SANDWICH,
            block_number=2, transaction_hash="0x2",
            profit_usd=Decimal("500"), user_impact_usd=Decimal("-1000"),
        )
        result = self.system.calculate_reward(action.action_id)
        self.assertLessEqual(result.total_reward, Decimal("0"))

    def test_base_reward_is_10pct_of_profit(self):
        action = self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.LIQUIDATION,
            block_number=3, transaction_hash="0x3",
            profit_usd=Decimal("200"),
        )
        result = self.system.calculate_reward(action.action_id)
        self.assertEqual(result.base_reward, Decimal("20"))

    def test_nonexistent_action_raises(self):
        with self.assertRaises(ValueError):
            self.system.calculate_reward("nonexistent")


class TestRewardDistribution(unittest.TestCase):
    """Reward distribution from pools."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_distribute_rewards(self):
        action = self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("1000"), spread_improvement_bps=5.0,
        )
        pool_id = list(self.system._reward_pools.keys())[0]
        rewards = self.system.distribute_rewards(pool_id, [action.action_id])
        self.assertIn("bot-1", rewards)
        self.assertGreater(rewards["bot-1"], Decimal("0"))

    def test_distribute_updates_pool_balance(self):
        action = self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("500"), spread_improvement_bps=5.0,
        )
        pool_id = list(self.system._reward_pools.keys())[0]
        pool = self.system._reward_pools[pool_id]
        initial_remaining = pool.remaining
        self.system.distribute_rewards(pool_id, [action.action_id])
        self.assertLess(pool.remaining, initial_remaining)

    def test_distribute_nonexistent_pool_raises(self):
        with self.assertRaises(ValueError):
            self.system.distribute_rewards("nonexistent", [])

    def test_distribute_skips_unknown_actions(self):
        pool_id = list(self.system._reward_pools.keys())[0]
        rewards = self.system.distribute_rewards(pool_id, ["unknown_1", "unknown_2"])
        self.assertEqual(len(rewards), 0)

    def test_multi_actor_distribution(self):
        a1 = self.system.record_mev_action(
            actor_id="bot-1", mev_type=MEVType.ARBITRAGE,
            block_number=1, transaction_hash="0x1",
            profit_usd=Decimal("100"), spread_improvement_bps=5.0,
        )
        a2 = self.system.record_mev_action(
            actor_id="bot-2", mev_type=MEVType.LIQUIDATION,
            block_number=2, transaction_hash="0x2",
            profit_usd=Decimal("200"),
        )
        pool_id = list(self.system._reward_pools.keys())[0]
        rewards = self.system.distribute_rewards(pool_id, [a1.action_id, a2.action_id])
        self.assertEqual(len(rewards), 2)
        self.assertIn("bot-1", rewards)
        self.assertIn("bot-2", rewards)


class TestRewardPools(unittest.TestCase):
    """Reward pool management."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_default_pool_created(self):
        self.assertGreater(len(self.system._reward_pools), 0)

    def test_create_custom_pool(self):
        pool = self.system.create_reward_pool(
            pool_name="Custom Pool",
            initial_balance=Decimal("50000"),
            safe_mev_share=0.8,
            health_weight=0.6,
        )
        self.assertIn(pool.pool_id, self.system._reward_pools)
        self.assertEqual(pool.total_balance, Decimal("50000"))
        self.assertEqual(pool.remaining, Decimal("50000"))
        self.assertEqual(pool.safe_mev_share, 0.8)


class TestHealthMetrics(unittest.TestCase):
    """Protocol health metrics."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_update_health_metrics(self):
        metrics = self.system.update_health_metrics(
            average_depth_usd=Decimal("500000"),
            average_spread_bps=5.0,
            average_slippage_bps=2.0,
            failure_rate=0.005,
            liquidation_quality_score=0.9,
        )
        self.assertEqual(metrics.average_depth_usd, Decimal("500000"))
        self.assertEqual(metrics.average_spread_bps, 5.0)
        self.assertGreater(metrics.overall_health_score, 0)

    def test_partial_update(self):
        self.system.update_health_metrics(average_spread_bps=3.0)
        metrics = self.system.get_health_metrics()
        self.assertEqual(metrics.average_spread_bps, 3.0)

    def test_overall_health_high_quality(self):
        metrics = self.system.update_health_metrics(
            average_depth_usd=Decimal("200000"),
            average_spread_bps=5.0,
            average_slippage_bps=2.0,
            failure_rate=0.005,
            liquidation_quality_score=1.0,
        )
        self.assertGreaterEqual(metrics.overall_health_score, 0.8)

    def test_overall_health_low_quality(self):
        metrics = self.system.update_health_metrics(
            average_depth_usd=Decimal("1000"),
            average_spread_bps=50.0,
            average_slippage_bps=20.0,
            failure_rate=0.1,
            liquidation_quality_score=0.0,
        )
        self.assertLessEqual(metrics.overall_health_score, 0.2)


class TestBadges(unittest.TestCase):
    """Badge awards."""

    def setUp(self):
        self.system = MEVRewardSystem()

    def test_safe_mev_specialist_badge(self):
        """100 safe actions awards 'safe_mev_specialist' badge."""
        for i in range(100):
            self.system.record_mev_action(
                actor_id="grinder", mev_type=MEVType.ARBITRAGE,
                block_number=i, transaction_hash=f"0x{i:04x}",
                profit_usd=Decimal("1"), spread_improvement_bps=1.0,
            )
        stats = self.system.get_actor_stats("grinder")
        self.assertIn("safe_mev_specialist", stats.badges)

    def test_no_badge_under_threshold(self):
        """99 safe actions does not award badge."""
        for i in range(99):
            self.system.record_mev_action(
                actor_id="almost", mev_type=MEVType.ARBITRAGE,
                block_number=i, transaction_hash=f"0x{i:04x}",
                profit_usd=Decimal("1"), spread_improvement_bps=1.0,
            )
        stats = self.system.get_actor_stats("almost")
        self.assertNotIn("safe_mev_specialist", stats.badges)


if __name__ == "__main__":
    unittest.main()
