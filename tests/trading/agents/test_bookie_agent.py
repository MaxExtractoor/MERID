"""Tests for trading/agents/bookie_agent.py - Coverage improvement."""

import pytest
import time
from unittest.mock import patch

from trading.agents.bookie_agent import (
    Bet,
    BettingPool,
    BookieAgent,
)


# =============================================================================
# Bet Tests
# =============================================================================

class TestBet:
    """Test Bet dataclass."""
    
    def test_bet_creation(self):
        """Test Bet creation with required fields."""
        bet = Bet(
            bet_id="bet_123",
            user_id="user_1",
            block_index=100,
            prediction="approved",
            stake_amount=100.0,
            odds=2.0,
            potential_payout=200.0
        )
        
        assert bet.bet_id == "bet_123"
        assert bet.user_id == "user_1"
        assert bet.block_index == 100
        assert bet.prediction == "approved"
        assert bet.stake_amount == 100.0
        assert bet.odds == 2.0
        assert bet.potential_payout == 200.0
        assert bet.settled is False
        assert bet.won is None
        assert bet.actual_payout == 0.0
    
    def test_bet_calculate_payout(self):
        """Test Bet.calculate_payout method."""
        bet = Bet(
            bet_id="bet_123",
            user_id="user_1",
            block_index=100,
            prediction="approved",
            stake_amount=100.0,
            odds=2.5,
            potential_payout=250.0
        )
        
        payout = bet.calculate_payout()
        assert payout == 250.0  # 100 * 2.5


# =============================================================================
# BettingPool Tests
# =============================================================================

class TestBettingPool:
    """Test BettingPool dataclass."""
    
    def test_pool_creation(self):
        """Test BettingPool creation."""
        pool = BettingPool(block_index=100)
        
        assert pool.block_index == 100
        assert pool.total_pool == 0.0
        assert pool.house_cut_pct == 5.0
        assert pool.bets == []
        assert pool.locked is False
        assert pool.settled is False
        assert pool.actual_outcome is None
    
    def test_lock_pool(self):
        """Test BettingPool.lock_pool method."""
        pool = BettingPool(block_index=100)
        pool.lock_pool()
        
        assert pool.locked is True
    
    def test_settle_pool_unlocked_raises(self):
        """Test settling unlocked pool raises error."""
        pool = BettingPool(block_index=100)
        
        with pytest.raises(ValueError, match="Cannot settle unlocked pool"):
            pool.settle_pool("approved")
    
    def test_settle_pool_already_settled_raises(self):
        """Test settling already settled pool raises error."""
        pool = BettingPool(block_index=100)
        pool.lock_pool()
        pool.settle_pool("approved")
        
        with pytest.raises(ValueError, match="Pool already settled"):
            pool.settle_pool("approved")
    
    def test_settle_pool_with_winners(self):
        """Test settling pool with winning bets."""
        pool = BettingPool(block_index=100)
        
        # Add bets
        winning_bet = Bet(
            bet_id="w1", user_id="winner", block_index=100,
            prediction="approved", stake_amount=100.0, odds=2.0, potential_payout=200.0
        )
        losing_bet = Bet(
            bet_id="l1", user_id="loser", block_index=100,
            prediction="rejected", stake_amount=100.0, odds=2.0, potential_payout=200.0
        )
        
        pool.bets = [winning_bet, losing_bet]
        pool.total_pool = 200.0
        pool.lock_pool()
        
        payouts = pool.settle_pool("approved")
        
        assert pool.settled is True
        assert pool.actual_outcome == "approved"
        assert winning_bet.won is True
        assert losing_bet.won is False
        assert "winner" in payouts
        assert payouts["winner"] > 100.0  # Winner gets stake + winnings
    
    def test_settle_pool_no_winners(self):
        """Test settling pool with no winning bets."""
        pool = BettingPool(block_index=100)
        
        losing_bet = Bet(
            bet_id="l1", user_id="loser", block_index=100,
            prediction="rejected", stake_amount=100.0, odds=2.0, potential_payout=200.0
        )
        
        pool.bets = [losing_bet]
        pool.total_pool = 100.0
        pool.lock_pool()
        
        payouts = pool.settle_pool("approved")
        
        assert payouts == {}
        assert losing_bet.won is False


# =============================================================================
# BookieAgent Tests
# =============================================================================

class TestBookieAgentInit:
    """Test BookieAgent initialization."""
    
    def test_default_init(self):
        """Test default initialization."""
        agent = BookieAgent()
        
        assert agent.house_cut_pct == 5.0
        assert agent.min_bet_amount == 1.0
        assert agent.max_bet_amount == 10000.0
        assert agent.betting_pools == {}
        assert agent.user_balances == {}
        assert agent.total_house_earnings == 0.0
        assert agent.total_bets_placed == 0
    
    def test_custom_init(self):
        """Test custom initialization."""
        agent = BookieAgent(
            house_cut_pct=10.0,
            min_bet_amount=5.0,
            max_bet_amount=5000.0
        )
        
        assert agent.house_cut_pct == 10.0
        assert agent.min_bet_amount == 5.0
        assert agent.max_bet_amount == 5000.0


class TestBookieAgentCreatePool:
    """Test create_betting_pool method."""
    
    def test_create_pool(self):
        """Test creating a betting pool."""
        agent = BookieAgent()
        pool = agent.create_betting_pool(100)
        
        assert pool.block_index == 100
        assert 100 in agent.betting_pools
    
    def test_create_duplicate_pool_raises(self):
        """Test creating duplicate pool raises error."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        
        with pytest.raises(ValueError, match="already exists"):
            agent.create_betting_pool(100)


class TestBookieAgentPlaceBet:
    """Test place_bet method."""
    
    def test_place_bet_success(self):
        """Test successful bet placement."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        
        bet = agent.place_bet(
            user_id="user_1",
            block_index=100,
            prediction="approved",
            stake_amount=100.0
        )
        
        assert bet.user_id == "user_1"
        assert bet.stake_amount == 100.0
        assert agent.user_balances["user_1"] == 900.0
        assert agent.total_bets_placed == 1
        assert agent.total_volume == 100.0
    
    def test_place_bet_stake_too_low(self):
        """Test bet with stake below minimum."""
        agent = BookieAgent(min_bet_amount=10.0)
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        
        with pytest.raises(ValueError, match="Stake amount must be between"):
            agent.place_bet("user_1", 100, "approved", 5.0)
    
    def test_place_bet_stake_too_high(self):
        """Test bet with stake above maximum."""
        agent = BookieAgent(max_bet_amount=100.0)
        agent.create_betting_pool(100)
        agent.deposit("user_1", 10000.0)
        
        with pytest.raises(ValueError, match="Stake amount must be between"):
            agent.place_bet("user_1", 100, "approved", 500.0)
    
    def test_place_bet_no_pool(self):
        """Test bet on nonexistent pool."""
        agent = BookieAgent()
        agent.deposit("user_1", 1000.0)
        
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.place_bet("user_1", 100, "approved", 100.0)
    
    def test_place_bet_pool_locked(self):
        """Test bet on locked pool."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.lock_pool_for_mining(100)
        agent.deposit("user_1", 1000.0)
        
        with pytest.raises(ValueError, match="pool is locked"):
            agent.place_bet("user_1", 100, "approved", 100.0)
    
    def test_place_bet_insufficient_balance(self):
        """Test bet with insufficient balance."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 50.0)
        
        with pytest.raises(ValueError, match="Insufficient balance"):
            agent.place_bet("user_1", 100, "approved", 100.0)


class TestBookieAgentLockPool:
    """Test lock_pool_for_mining method."""
    
    def test_lock_pool(self):
        """Test locking a pool."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.lock_pool_for_mining(100)
        
        assert agent.betting_pools[100].locked is True
    
    def test_lock_nonexistent_pool(self):
        """Test locking nonexistent pool raises error."""
        agent = BookieAgent()
        
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.lock_pool_for_mining(100)


class TestBookieAgentSettlePool:
    """Test settle_pool method."""
    
    def test_settle_pool_high_confidence(self):
        """Test settling with high confidence outcome."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "high_confidence", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.8)
        
        assert agent.betting_pools[100].actual_outcome == "high_confidence"
    
    def test_settle_pool_approved(self):
        """Test settling with approved outcome."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=True, consensus_confidence=0.6)
        
        assert agent.betting_pools[100].actual_outcome == "approved"
    
    def test_settle_pool_low_confidence(self):
        """Test settling with low confidence outcome."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "low_confidence", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=False, consensus_confidence=0.3)
        
        assert agent.betting_pools[100].actual_outcome == "low_confidence"
    
    def test_settle_pool_rejected(self):
        """Test settling with rejected outcome."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "rejected", 100.0)
        agent.lock_pool_for_mining(100)
        
        payouts = agent.settle_pool(100, consensus_approved=False, consensus_confidence=0.6)
        
        assert agent.betting_pools[100].actual_outcome == "rejected"
    
    def test_settle_nonexistent_pool(self):
        """Test settling nonexistent pool raises error."""
        agent = BookieAgent()
        
        with pytest.raises(ValueError, match="No betting pool exists"):
            agent.settle_pool(100, True, 0.8)


class TestBookieAgentRewardAgents:
    """Test reward_agents method."""
    
    def test_reward_agents(self):
        """Test rewarding agents for correct votes."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        agent.lock_pool_for_mining(100)
        agent.settle_pool(100, True, 0.8)
        
        agent_votes = {"agent_1": True, "agent_2": False}
        agent.reward_agents(100, agent_votes)
        
        assert "agent_1" in agent.agent_rewards
        assert agent.agent_rewards["agent_1"] > 0
    
    def test_reward_agents_no_pool(self):
        """Test rewarding with nonexistent pool does nothing."""
        agent = BookieAgent()
        agent.reward_agents(100, {"agent_1": True})
        
        assert agent.agent_rewards == {}
    
    def test_reward_agents_unsettled_pool(self):
        """Test rewarding with unsettled pool does nothing."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.reward_agents(100, {"agent_1": True})
        
        assert agent.agent_rewards == {}


class TestBookieAgentDeposit:
    """Test deposit method."""
    
    def test_deposit(self):
        """Test depositing funds."""
        agent = BookieAgent()
        agent.deposit("user_1", 500.0)
        
        assert agent.user_balances["user_1"] == 500.0
    
    def test_deposit_multiple(self):
        """Test multiple deposits."""
        agent = BookieAgent()
        agent.deposit("user_1", 500.0)
        agent.deposit("user_1", 300.0)
        
        assert agent.user_balances["user_1"] == 800.0


class TestBookieAgentWithdraw:
    """Test withdraw method."""
    
    def test_withdraw_success(self):
        """Test successful withdrawal."""
        agent = BookieAgent()
        agent.deposit("user_1", 500.0)
        
        result = agent.withdraw("user_1", 200.0)
        
        assert result is True
        assert agent.user_balances["user_1"] == 300.0
    
    def test_withdraw_insufficient_balance(self):
        """Test withdrawal with insufficient balance."""
        agent = BookieAgent()
        agent.deposit("user_1", 100.0)
        
        result = agent.withdraw("user_1", 200.0)
        
        assert result is False
        assert agent.user_balances["user_1"] == 100.0
    
    def test_withdraw_no_balance(self):
        """Test withdrawal from user with no balance."""
        agent = BookieAgent()
        
        result = agent.withdraw("user_1", 100.0)
        
        assert result is False


class TestBookieAgentGetUserStats:
    """Test get_user_stats method."""
    
    def test_get_user_stats_no_bets(self):
        """Test getting stats for user with no bets."""
        agent = BookieAgent()
        agent.deposit("user_1", 500.0)
        
        stats = agent.get_user_stats("user_1")
        
        assert stats["user_id"] == "user_1"
        assert stats["balance"] == 500.0
        assert stats["total_bets"] == 0
        assert stats["win_rate_pct"] == 0.0
    
    def test_get_user_stats_with_bets(self):
        """Test getting stats for user with bets."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        
        stats = agent.get_user_stats("user_1")
        
        assert stats["total_bets"] == 1
        assert stats["total_wagered"] == 100.0


class TestBookieAgentGetPoolStats:
    """Test get_pool_stats method."""
    
    def test_get_pool_stats_nonexistent(self):
        """Test getting stats for nonexistent pool."""
        agent = BookieAgent()
        
        stats = agent.get_pool_stats(100)
        
        assert stats == {}
    
    def test_get_pool_stats(self):
        """Test getting pool statistics."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        
        stats = agent.get_pool_stats(100)
        
        assert stats["block_index"] == 100
        assert stats["total_pool"] == 100.0
        assert stats["total_bets"] == 1
        assert stats["locked"] is False


class TestBookieAgentGetPerformanceStats:
    """Test get_performance_stats method."""
    
    def test_get_performance_stats(self):
        """Test getting performance statistics."""
        agent = BookieAgent()
        agent.create_betting_pool(100)
        agent.deposit("user_1", 1000.0)
        agent.place_bet("user_1", 100, "approved", 100.0)
        
        stats = agent.get_performance_stats()
        
        assert stats["total_bets_placed"] == 1
        assert stats["total_volume"] == 100.0
        assert stats["active_pools"] == 1
        assert stats["total_users"] == 1


class TestBookieAgentCalculateOdds:
    """Test _calculate_odds helper method."""
    
    def test_calculate_odds_empty_pool(self):
        """Test odds calculation with empty pool."""
        agent = BookieAgent()
        pool = BettingPool(block_index=100)
        
        odds = agent._calculate_odds(pool, "approved", 100.0)
        
        # When pool is empty, implied_prob = 1.0, so odds are capped at minimum
        assert odds == 1.01  # Minimum odds
    
    def test_calculate_odds_with_existing_bets(self):
        """Test odds calculation with existing bets."""
        agent = BookieAgent()
        pool = BettingPool(block_index=100)
        
        # Add existing bet on same prediction
        existing_bet = Bet(
            bet_id="b1", user_id="u1", block_index=100,
            prediction="approved", stake_amount=100.0, odds=2.0, potential_payout=200.0
        )
        pool.bets.append(existing_bet)
        
        odds = agent._calculate_odds(pool, "approved", 100.0)
        
        # Odds should be lower since more people betting on same outcome
        assert odds < 2.0


class TestBookieAgentGenerateBetId:
    """Test _generate_bet_id helper method."""
    
    def test_generate_unique_ids(self):
        """Test that bet IDs are unique."""
        agent = BookieAgent()
        
        id1 = agent._generate_bet_id("user_1", 100, "approved", 100.0)
        
        # Small delay to ensure different timestamp
        time.sleep(0.01)
        id2 = agent._generate_bet_id("user_1", 100, "approved", 100.0)
        
        assert id1 != id2
        assert len(id1) == 16
        assert len(id2) == 16
