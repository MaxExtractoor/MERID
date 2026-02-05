"""Tests for trading agents bookie_agent module - Batch 34 Coverage."""
import pytest
from unittest.mock import patch
import time

from trading.agents.bookie_agent import (
    Bet,
    BettingPool,
    BookieAgent,
)


class TestBet:
    """Tests for Bet dataclass."""

    @pytest.fixture
    def sample_bet(self):
        return Bet(
            bet_id="bet_123",
            user_id="user_456",
            block_index=100,
            prediction="approved",
            stake_amount=100.0,
            odds=2.0,
            potential_payout=200.0,
        )

    def test_bet_creation(self, sample_bet):
        assert sample_bet.bet_id == "bet_123"
        assert sample_bet.user_id == "user_456"
        assert sample_bet.block_index == 100
        assert sample_bet.prediction == "approved"
        assert sample_bet.stake_amount == 100.0
        assert sample_bet.odds == 2.0
        assert sample_bet.potential_payout == 200.0
        assert sample_bet.settled is False
        assert sample_bet.won is None

    def test_bet_calculate_payout(self, sample_bet):
        payout = sample_bet.calculate_payout()
        assert payout == 200.0  # 100 * 2.0

    def test_bet_default_timestamps(self, sample_bet):
        assert sample_bet.placed_at > 0


class TestBettingPool:
    """Tests for BettingPool dataclass."""

    @pytest.fixture
    def sample_pool(self):
        return BettingPool(block_index=100, house_cut_pct=5.0)

    def test_pool_creation(self, sample_pool):
        assert sample_pool.block_index == 100
        assert sample_pool.total_pool == 0.0
        assert sample_pool.house_cut_pct == 5.0
        assert sample_pool.locked is False
        assert sample_pool.settled is False
        assert sample_pool.bets == []

    def test_lock_pool(self, sample_pool):
        sample_pool.lock_pool()
        assert sample_pool.locked is True

    def test_settle_pool_not_locked(self, sample_pool):
        bet = Bet(
            bet_id="bet_1",
            user_id="user_1",
            block_index=100,
            prediction="approved",
            stake_amount=100.0,
            odds=2.0,
            potential_payout=200.0,
        )
        sample_pool.bets.append(bet)
        sample_pool.total_pool = 100.0
        
        with pytest.raises(ValueError, match="Cannot settle unlocked pool"):
            sample_pool.settle_pool("approved")

    def test_settle_pool_already_settled(self, sample_pool):
        sample_pool.locked = True
        sample_pool.settled = True
        
        with pytest.raises(ValueError, match="Pool already settled"):
            sample_pool.settle_pool("approved")

    def test_settle_pool_with_winner(self, sample_pool):
        # Create bets
        winning_bet = Bet(
            bet_id="bet_1",
            user_id="user_1",
            block_index=100,
            prediction="approved",
            stake_amount=100.0,
            odds=2.0,
            potential_payout=200.0,
        )
        losing_bet = Bet(
            bet_id="bet_2",
            user_id="user_2",
            block_index=100,
            prediction="rejected",
            stake_amount=50.0,
            odds=2.0,
            potential_payout=100.0,
        )
        
        sample_pool.bets = [winning_bet, losing_bet]
        sample_pool.total_pool = 150.0
        sample_pool.locked = True
        
        payouts = sample_pool.settle_pool("approved")
        
        assert sample_pool.settled is True
        assert sample_pool.actual_outcome == "approved"
        assert winning_bet.won is True
        assert losing_bet.won is False
        assert "user_1" in payouts
        assert payouts["user_1"] > 100.0  # Should get back stake + winnings

    def test_settle_pool_all_losers(self, sample_pool):
        losing_bet = Bet(
            bet_id="bet_1",
            user_id="user_1",
            block_index=100,
            prediction="rejected",
            stake_amount=100.0,
            odds=2.0,
            potential_payout=200.0,
        )
        
        sample_pool.bets = [losing_bet]
        sample_pool.total_pool = 100.0
        sample_pool.locked = True
        
        payouts = sample_pool.settle_pool("approved")
        
        assert payouts == {}  # No winners
        assert losing_bet.won is False
        assert losing_bet.actual_payout == 0.0


class TestBookieAgent:
    """Tests for BookieAgent class."""

    @pytest.fixture
    def agent(self):
        return BookieAgent(house_cut_pct=5.0, min_bet_amount=1.0, max_bet_amount=10000.0)

    def test_initialization(self, agent):
        assert agent.house_cut_pct == 5.0
        assert agent.min_bet_amount == 1.0
        assert agent.max_bet_amount == 10000.0
        assert agent.total_house_earnings == 0.0
        assert agent.total_bets_placed == 0
        assert agent.total_volume == 0.0
        assert agent.betting_pools == {}
        assert agent.user_balances == {}

    def test_create_betting_pool(self, agent):
        pool = agent.create_betting_pool(100)
        assert pool.block_index == 100
        assert 100 in agent.betting_pools

    def test_create_betting_pool_duplicate(self, agent):
        agent.create_betting_pool(100)
        with pytest.raises(ValueError, match="already exists"):
            agent.create_betting_pool(100)

    def test_deposit(self, agent):
        agent.deposit("user_1", 1000.0)
        assert agent.user_balances["user_1"] == 1000.0

    def test_withdraw_success(self, agent):
        agent.deposit("user_1", 1000.0)
        result = agent.withdraw("user_1", 500.0)
        assert result is True
        assert agent.user_balances["user_1"] == 500.0

    def test_withdraw_insufficient_funds(self, agent):
        agent.deposit("user_1", 100.0)
        result = agent.withdraw("user_1", 500.0)
        assert result is False
        assert agent.user_balances["user_1"] == 100.0

    def test_place_bet_success(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        
        bet = agent.place_bet("user_1", 100, "approved", 100.0)
        
        assert bet.user_id == "user_1"
        assert bet.block_index == 100
        assert bet.prediction == "approved"
        assert bet.stake_amount == 100.0
        assert agent.user_balances["user_1"] == 900.0
        assert agent.total_bets_placed == 1
        assert agent.total_volume == 100.0

    def test_place_bet_invalid_amount(self, agent):
        agent.create_betting_pool(100)
        
        with pytest.raises(ValueError, match="Stake amount must be"):
            agent.place_bet("user_1", 100, "approved", 0.5)  # Below minimum

    def test_place_bet_no_pool(self, agent):
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.place_bet("user_1", 100, "approved", 100.0)

    def test_place_bet_locked_pool(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.lock_pool_for_mining(100)
        
        with pytest.raises(ValueError, match="pool is locked"):
            agent.place_bet("user_1", 100, "approved", 100.0)

    def test_place_bet_insufficient_balance(self, agent):
        agent.deposit("user_1", 50.0)
        agent.create_betting_pool(100)
        
        with pytest.raises(ValueError, match="Insufficient balance"):
            agent.place_bet("user_1", 100, "approved", 100.0)

    def test_lock_pool_for_mining(self, agent):
        agent.create_betting_pool(100)
        agent.lock_pool_for_mining(100)
        assert agent.betting_pools[100].locked is True

    def test_lock_pool_no_pool(self, agent):
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.lock_pool_for_mining(100)

    def test_settle_pool_high_confidence(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "high_confidence", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.8)
        
        assert agent.betting_pools[100].settled is True
        assert agent.betting_pools[100].actual_outcome == "high_confidence"

    def test_settle_pool_approved(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.6)
        
        assert agent.betting_pools[100].actual_outcome == "approved"

    def test_settle_pool_rejected(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "rejected", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=False, consensus_confidence=0.6)
        
        assert agent.betting_pools[100].actual_outcome == "rejected"

    def test_settle_pool_low_confidence(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "low_confidence", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=False, consensus_confidence=0.3)
        
        assert agent.betting_pools[100].actual_outcome == "low_confidence"

    def test_settle_pool_no_pool(self, agent):
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.8)

    def test_reward_agents(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.8)
        
        agent_votes = {"agent_1": True, "agent_2": False}
        agent.reward_agents(100, agent_votes, reward_pool_pct=10.0)
        
        # agent_1 voted correctly (True matches approved outcome)
        assert agent.agent_rewards.get("agent_1", 0.0) > 0.0
        # agent_2 voted incorrectly
        assert agent.agent_rewards.get("agent_2", 0.0) == 0.0

    def test_reward_agents_pool_not_settled(self, agent):
        agent.create_betting_pool(100)
        # Don't settle the pool
        
        agent_votes = {"agent_1": True}
        agent.reward_agents(100, agent_votes)  # Should not raise, just log warning
        assert agent.agent_rewards == {}

    def test_reward_agents_no_pool(self, agent):
        agent_votes = {"agent_1": True}
        agent.reward_agents(100, agent_votes)  # Should return early
        assert agent.agent_rewards == {}

    def test_get_user_stats_no_bets(self, agent):
        stats = agent.get_user_stats("user_1")
        assert stats["user_id"] == "user_1"
        assert stats["balance"] == 0.0
        assert stats["total_bets"] == 0
        assert stats["total_wagered"] == 0.0
        assert stats["win_rate_pct"] == 0.0

    def test_get_user_stats_with_bets(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        bet = agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.8)
        
        stats = agent.get_user_stats("user_1")
        assert stats["total_bets"] == 1
        assert stats["total_wagered"] == 100.0

    def test_get_pool_stats_existing(self, agent):
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        
        stats = agent.get_pool_stats(100)
        assert stats["block_index"] == 100
        assert stats["total_pool"] == 100.0
        assert stats["total_bets"] == 1
        assert stats["locked"] is False

    def test_get_pool_stats_nonexistent(self, agent):
        stats = agent.get_pool_stats(999)
        assert stats == {}

    def test_get_performance_stats_empty(self, agent):
        stats = agent.get_performance_stats()
        assert stats["total_bets_placed"] == 0
        assert stats["total_volume"] == 0.0
        assert stats["total_house_earnings"] == 0.0
        assert stats["active_pools"] == 0
        assert stats["settled_pools"] == 0
        assert stats["total_users"] == 0
        assert stats["total_agent_rewards"] == 0.0

    def test_get_performance_stats_with_activity(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        agent.settle_pool(100, consensus_approved=False, consensus_confidence=0.3)
        
        stats = agent.get_performance_stats()
        assert stats["total_bets_placed"] == 1
        assert stats["total_volume"] == 100.0
        assert stats["total_users"] == 1
        assert stats["settled_pools"] == 1

    def test_calculate_odds_empty_pool(self, agent):
        pool = BettingPool(block_index=100)
        odds = agent._calculate_odds(pool, "approved", 100.0)
        # When pool is empty and we add stake, prediction_total = stake, other = 0
        # So implied_prob = 1.0, fair_odds = 1.0, with edge = 0.95, capped at 1.01
        assert odds == 1.01  # Minimum odds due to 100% implied probability

    def test_calculate_odds_with_bets(self, agent):
        agent.deposit("user_1", 1000.0)
        agent.create_betting_pool(100)
        agent.place_bet("user_1", 100, "approved", 100.0)
        
        pool = agent.betting_pools[100]
        odds = agent._calculate_odds(pool, "rejected", 50.0)
        
        assert odds > 1.01  # Should be higher than minimum
        assert odds <= 100.0  # Should be capped

    def test_generate_bet_id(self, agent):
        bet_id_1 = agent._generate_bet_id("user_1", 100, "approved", 100.0)
        bet_id_2 = agent._generate_bet_id("user_2", 101, "rejected", 200.0)
        
        assert len(bet_id_1) == 16
        assert len(bet_id_2) == 16
        assert bet_id_1 != bet_id_2  # Should be unique due to different parameters
