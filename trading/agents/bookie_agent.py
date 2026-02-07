"""
Bookie Agent - Manages consensus betting system.

Handles:
- Bet placement on block consensus outcomes
- Odds calculation
- Pool management
- Payout distribution
- Anti-cheating mechanisms
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("trading.agents.bookie")


@dataclass
class Bet:
    """Individual bet on consensus outcome."""
    bet_id: str
    user_id: str
    block_index: int
    prediction: str  # 'approved', 'rejected', 'high_confidence', 'low_confidence'
    stake_amount: float
    odds: float
    potential_payout: float
    placed_at: float = field(default_factory=time.time)
    settled: bool = False
    won: Optional[bool] = None
    actual_payout: float = 0.0
    
    def calculate_payout(self) -> float:
        """Calculate payout if bet wins."""
        return self.stake_amount * self.odds


@dataclass
class BettingPool:
    """Betting pool for a specific block."""
    block_index: int
    total_pool: float = 0.0
    house_cut_pct: float = 5.0  # 5% house edge
    bets: List[Bet] = field(default_factory=list)
    locked: bool = False
    settled: bool = False
    actual_outcome: Optional[str] = None
    
    def lock_pool(self):
        """Lock pool before block mining starts."""
        self.locked = True
        logger.info("Betting pool locked for block #%d, total pool: $%.2f", self.block_index, self.total_pool)
    
    def settle_pool(self, outcome: str) -> Dict[str, float]:
        """Settle pool and calculate payouts."""
        if not self.locked:
            raise ValueError("Cannot settle unlocked pool")
        
        if self.settled:
            raise ValueError("Pool already settled")
        
        self.actual_outcome = outcome
        self.settled = True
        
        # Calculate total winning stakes
        winning_bets = [bet for bet in self.bets if bet.prediction == outcome]
        losing_bets = [bet for bet in self.bets if bet.prediction != outcome]
        
        total_winning_stakes = sum(bet.stake_amount for bet in winning_bets)
        total_losing_stakes = sum(bet.stake_amount for bet in losing_bets)
        
        # House takes cut from losing stakes
        house_take = total_losing_stakes * (self.house_cut_pct / 100)
        distributable_pool = total_losing_stakes - house_take
        
        # Calculate payouts
        payouts = {}
        
        if total_winning_stakes > 0:
            for bet in winning_bets:
                # Proportional payout from losing pool + original stake
                proportion = bet.stake_amount / total_winning_stakes
                winnings = distributable_pool * proportion
                total_payout = bet.stake_amount + winnings
                
                bet.won = True
                bet.actual_payout = total_payout
                payouts[bet.user_id] = payouts.get(bet.user_id, 0.0) + total_payout
        
        for bet in losing_bets:
            bet.won = False
            bet.actual_payout = 0.0
        
        logger.info(
            "Pool settled for block #%d: outcome=%s, winners=%d, losers=%d, house_take=$%.2f",
            self.block_index, outcome, len(winning_bets), len(losing_bets), house_take
        )
        
        return payouts


class BookieAgent:
    """
    Manages consensus betting system with anti-cheating mechanisms.
    
    Features:
    - Bet placement on block outcomes
    - Dynamic odds calculation
    - Pool management
    - Payout distribution
    - Anti-cheating (bets locked before mining)
    - Agent rewards for participation
    """
    
    def __init__(
        self,
        house_cut_pct: float = 5.0,
        min_bet_amount: float = 1.0,
        max_bet_amount: float = 10000.0
    ):
        self.house_cut_pct = house_cut_pct
        self.min_bet_amount = min_bet_amount
        self.max_bet_amount = max_bet_amount
        
        self.betting_pools: Dict[int, BettingPool] = {}
        self.user_balances: Dict[str, float] = {}
        self.agent_rewards: Dict[str, float] = {}
        
        self.total_house_earnings = 0.0
        self.total_bets_placed = 0
        self.total_volume = 0.0
        
        logger.info(
            "BookieAgent initialized: house_cut=%.1f%%, min_bet=$%.2f, max_bet=$%.2f",
            house_cut_pct, min_bet_amount, max_bet_amount
        )
    
    def create_betting_pool(self, block_index: int) -> BettingPool:
        """Create new betting pool for upcoming block."""
        if block_index in self.betting_pools:
            raise ValueError(f"Betting pool already exists for block #{block_index}")
        
        pool = BettingPool(
            block_index=block_index,
            house_cut_pct=self.house_cut_pct
        )
        
        self.betting_pools[block_index] = pool
        
        logger.info("Betting pool created for block #%d", block_index)
        return pool
    
    def place_bet(
        self,
        user_id: str,
        block_index: int,
        prediction: str,
        stake_amount: float
    ) -> Bet:
        """
        Place bet on block consensus outcome.
        
        Anti-cheating: Pool must not be locked (mining hasn't started).
        """
        # Validation
        if stake_amount < self.min_bet_amount or stake_amount > self.max_bet_amount:
            raise ValueError(f"Stake amount must be between ${self.min_bet_amount} and ${self.max_bet_amount}")
        
        if block_index not in self.betting_pools:
            raise ValueError(f"No betting pool exists for block #{block_index}")
        
        pool = self.betting_pools[block_index]
        
        if pool.locked:
            raise ValueError("Cannot place bet - pool is locked (mining in progress)")
        
        # Check user balance
        user_balance = self.user_balances.get(user_id, 0.0)
        if user_balance < stake_amount:
            raise ValueError(f"Insufficient balance: ${user_balance:.2f} < ${stake_amount:.2f}")
        
        # Calculate current odds based on pool distribution
        odds = self._calculate_odds(pool, prediction, stake_amount)
        
        # Create bet
        bet_id = self._generate_bet_id(user_id, block_index, prediction, stake_amount)
        
        bet = Bet(
            bet_id=bet_id,
            user_id=user_id,
            block_index=block_index,
            prediction=prediction,
            stake_amount=stake_amount,
            odds=odds,
            potential_payout=stake_amount * odds
        )
        
        # Deduct from user balance
        self.user_balances[user_id] = user_balance - stake_amount
        
        # Add to pool
        pool.bets.append(bet)
        pool.total_pool += stake_amount
        
        # Update stats
        self.total_bets_placed += 1
        self.total_volume += stake_amount
        
        logger.info(
            "Bet placed: user=%s, block=#%d, prediction=%s, stake=$%.2f, odds=%.2f",
            user_id, block_index, prediction, stake_amount, odds
        )
        
        return bet
    
    def lock_pool_for_mining(self, block_index: int):
        """
        Lock betting pool before mining starts.
        
        Critical anti-cheating mechanism - no bets after mining begins.
        """
        if block_index not in self.betting_pools:
            raise ValueError(f"No betting pool exists for block #{block_index}")
        
        pool = self.betting_pools[block_index]
        pool.lock_pool()
    
    def settle_pool(
        self,
        block_index: int,
        consensus_approved: bool,
        consensus_confidence: float
    ) -> Dict[str, float]:
        """
        Settle betting pool after block is mined.
        
        Determines outcome and distributes payouts.
        """
        if block_index not in self.betting_pools:
            raise ValueError(f"No betting pool exists for block #{block_index}")
        
        pool = self.betting_pools[block_index]
        
        # Determine outcome based on consensus
        if consensus_approved and consensus_confidence >= 0.75:
            outcome = "high_confidence"
        elif consensus_approved:
            outcome = "approved"
        elif consensus_confidence < 0.5:
            outcome = "low_confidence"
        else:
            outcome = "rejected"
        
        # Settle pool
        payouts = pool.settle_pool(outcome)
        
        # Distribute payouts to user balances
        for user_id, payout in payouts.items():
            self.user_balances[user_id] = self.user_balances.get(user_id, 0.0) + payout
        
        # Calculate house earnings
        total_stakes = sum(bet.stake_amount for bet in pool.bets)
        total_payouts = sum(payouts.values())
        house_earnings = total_stakes - total_payouts
        self.total_house_earnings += house_earnings
        
        logger.info(
            "Pool settled: block=#%d, outcome=%s, total_payouts=$%.2f, house_earnings=$%.2f",
            block_index, outcome, total_payouts, house_earnings
        )
        
        return payouts
    
    def reward_agents(
        self,
        block_index: int,
        agent_votes: Dict[str, bool],
        reward_pool_pct: float = 10.0
    ):
        """
        Reward agents for participation in consensus.
        
        Agents that voted correctly get proportional rewards from house cut.
        """
        if block_index not in self.betting_pools:
            return
        
        pool = self.betting_pools[block_index]
        
        if not pool.settled:
            logger.warning("Cannot reward agents - pool not settled yet")
            return
        
        # Calculate reward pool (% of house earnings)
        total_stakes = sum(bet.stake_amount for bet in pool.bets)
        house_earnings = total_stakes * (self.house_cut_pct / 100)
        reward_pool = house_earnings * (reward_pool_pct / 100)
        
        # Determine correct votes based on outcome
        correct_vote = pool.actual_outcome in ["approved", "high_confidence"]
        correct_agents = [agent_id for agent_id, vote in agent_votes.items() if vote == correct_vote]
        
        if correct_agents:
            reward_per_agent = reward_pool / len(correct_agents)
            
            for agent_id in correct_agents:
                self.agent_rewards[agent_id] = self.agent_rewards.get(agent_id, 0.0) + reward_per_agent
                
                logger.info(
                    "Agent rewarded: %s, amount=$%.2f for block #%d",
                    agent_id, reward_per_agent, block_index
                )
    
    def deposit(self, user_id: str, amount: float):
        """Deposit funds to user balance."""
        self.user_balances[user_id] = self.user_balances.get(user_id, 0.0) + amount
        logger.info("Deposit: user=%s, amount=$%.2f, new_balance=$%.2f", 
                   user_id, amount, self.user_balances[user_id])
    
    def withdraw(self, user_id: str, amount: float) -> bool:
        """Withdraw funds from user balance."""
        balance = self.user_balances.get(user_id, 0.0)
        
        if balance < amount:
            logger.warning("Withdrawal failed: insufficient balance")
            return False
        
        self.user_balances[user_id] = balance - amount
        logger.info("Withdrawal: user=%s, amount=$%.2f, new_balance=$%.2f",
                   user_id, amount, self.user_balances[user_id])
        return True
    
    def get_user_stats(self, user_id: str) -> Dict:
        """Get user betting statistics."""
        user_bets = []
        for pool in self.betting_pools.values():
            user_bets.extend([bet for bet in pool.bets if bet.user_id == user_id])
        
        total_wagered = sum(bet.stake_amount for bet in user_bets)
        total_won = sum(bet.actual_payout for bet in user_bets if bet.won)
        win_rate = (sum(1 for bet in user_bets if bet.won) / len(user_bets) * 100) if user_bets else 0.0
        
        return {
            "user_id": user_id,
            "balance": self.user_balances.get(user_id, 0.0),
            "total_bets": len(user_bets),
            "total_wagered": total_wagered,
            "total_won": total_won,
            "net_profit": total_won - total_wagered,
            "win_rate_pct": win_rate
        }
    
    def get_pool_stats(self, block_index: int) -> Dict:
        """Get betting pool statistics."""
        if block_index not in self.betting_pools:
            return {}
        
        pool = self.betting_pools[block_index]
        
        # Calculate distribution by prediction
        distribution = {}
        for bet in pool.bets:
            distribution[bet.prediction] = distribution.get(bet.prediction, 0.0) + bet.stake_amount
        
        return {
            "block_index": block_index,
            "total_pool": pool.total_pool,
            "total_bets": len(pool.bets),
            "locked": pool.locked,
            "settled": pool.settled,
            "distribution": distribution,
            "outcome": pool.actual_outcome
        }
    
    def get_performance_stats(self) -> Dict:
        """Get overall bookie agent performance."""
        return {
            "total_bets_placed": self.total_bets_placed,
            "total_volume": self.total_volume,
            "total_house_earnings": self.total_house_earnings,
            "active_pools": len([p for p in self.betting_pools.values() if not p.settled]),
            "settled_pools": len([p for p in self.betting_pools.values() if p.settled]),
            "total_users": len(self.user_balances),
            "total_agent_rewards": sum(self.agent_rewards.values())
        }
    
    # Helper methods
    
    def _calculate_odds(self, pool: BettingPool, prediction: str, stake_amount: float) -> float:
        """Calculate odds based on current pool distribution."""
        # Calculate current distribution
        prediction_total = sum(bet.stake_amount for bet in pool.bets if bet.prediction == prediction)
        other_total = sum(bet.stake_amount for bet in pool.bets if bet.prediction != prediction)
        
        # Add new stake
        prediction_total += stake_amount
        
        # Calculate implied probability
        total = prediction_total + other_total
        if total == 0:
            return 2.0  # Default odds
        
        implied_prob = prediction_total / total
        
        # Convert to decimal odds (with house edge)
        if implied_prob >= 0.99:
            return 1.01  # Minimum odds
        
        fair_odds = 1.0 / implied_prob
        odds_with_edge = fair_odds * (1 - self.house_cut_pct / 100)
        
        return max(1.01, min(odds_with_edge, 100.0))  # Cap at 100x
    
    def _generate_bet_id(self, user_id: str, block_index: int, prediction: str, stake: float) -> str:
        """Generate unique bet ID."""
        data = f"{user_id}_{block_index}_{prediction}_{stake}_{time.time()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
