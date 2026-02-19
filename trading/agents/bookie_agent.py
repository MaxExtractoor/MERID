"""
Bookie Agent — Universal betting system for any MERID instrument or event.

Handles:
- Bet placement on any market/instrument/event outcome
- Dynamic odds calculation with house edge
- Pool management (create → lock → settle lifecycle)
- Payout distribution
- Anti-cheating mechanisms (lock before outcome)
- Agent role tracking and coherence scoring
- Consensus-store–driven settlement
- Betting health metrics for observability

Backward compatible: block_index pools are a special case of market_id pools
via the canonical key ``block:<N>``.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("trading.agents.bookie")


# ── Outcome types ────────────────────────────────────────────────────

# Standard outcome sets for different market schemas
BINARY_OUTCOMES = ("yes", "no")
BLOCK_OUTCOMES = ("approved", "rejected", "high_confidence", "low_confidence")
# Callers may pass any string; these are just the canonical sets.


def market_id_for_block(block_index: int) -> str:
    """Canonical market_id for a legacy block-index pool."""
    return f"block:{block_index}"


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class Bet:
    """Individual bet on a market outcome."""
    bet_id: str
    user_id: str
    market_id: str
    prediction: str                      # outcome label the user is betting on
    stake_amount: float
    odds: float
    potential_payout: float
    role: str = "directional"            # directional, hedging, market_making, arb
    placed_at: float = field(default_factory=time.time)
    settled: bool = False
    won: Optional[bool] = None
    actual_payout: float = 0.0
    # Coherence tracking
    stated_probability: Optional[float] = None   # agent's opinion prob at bet time
    implied_probability: Optional[float] = None  # 1/odds (fair)

    # Legacy compat
    @property
    def block_index(self) -> Optional[int]:
        if self.market_id.startswith("block:"):
            try:
                return int(self.market_id.split(":", 1)[1])
            except (ValueError, IndexError):
                pass
        return None

    def calculate_payout(self) -> float:
        """Calculate payout if bet wins."""
        return self.stake_amount * self.odds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bet_id": self.bet_id,
            "user_id": self.user_id,
            "market_id": self.market_id,
            "prediction": self.prediction,
            "stake_amount": round(self.stake_amount, 2),
            "odds": round(self.odds, 4),
            "potential_payout": round(self.potential_payout, 2),
            "role": self.role,
            "placed_at": self.placed_at,
            "settled": self.settled,
            "won": self.won,
            "actual_payout": round(self.actual_payout, 2),
            "stated_probability": self.stated_probability,
            "implied_probability": self.implied_probability,
        }


@dataclass
class BettingPool:
    """Betting pool for a specific market/instrument/event."""
    market_id: str
    total_pool: float = 0.0
    house_cut_pct: float = 5.0           # 5% house edge
    allowed_outcomes: List[str] = field(default_factory=list)  # empty = any
    bets: List[Bet] = field(default_factory=list)
    locked: bool = False
    locked_at: Optional[float] = None
    settled: bool = False
    settled_at: Optional[float] = None
    actual_outcome: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    # Legacy compat
    @property
    def block_index(self) -> Optional[int]:
        if self.market_id.startswith("block:"):
            try:
                return int(self.market_id.split(":", 1)[1])
            except (ValueError, IndexError):
                pass
        return None

    def lock_pool(self):
        """Lock pool — no more bets accepted."""
        self.locked = True
        self.locked_at = time.time()
        logger.info("Betting pool locked for %s, total pool: $%.2f", self.market_id, self.total_pool)

    def settle_pool(self, outcome: str) -> Dict[str, float]:
        """Settle pool and calculate payouts."""
        if not self.locked:
            raise ValueError("Cannot settle unlocked pool")
        if self.settled:
            raise ValueError("Pool already settled")

        self.actual_outcome = outcome
        self.settled = True
        self.settled_at = time.time()

        winning_bets = [bet for bet in self.bets if bet.prediction == outcome]
        losing_bets = [bet for bet in self.bets if bet.prediction != outcome]

        total_winning_stakes = sum(bet.stake_amount for bet in winning_bets)
        total_losing_stakes = sum(bet.stake_amount for bet in losing_bets)

        house_take = total_losing_stakes * (self.house_cut_pct / 100)
        distributable_pool = total_losing_stakes - house_take

        payouts: Dict[str, float] = {}
        if total_winning_stakes > 0:
            for bet in winning_bets:
                proportion = bet.stake_amount / total_winning_stakes
                winnings = distributable_pool * proportion
                total_payout = bet.stake_amount + winnings
                bet.won = True
                bet.actual_payout = total_payout
                bet.settled = True
                payouts[bet.user_id] = payouts.get(bet.user_id, 0.0) + total_payout

        for bet in losing_bets:
            bet.won = False
            bet.actual_payout = 0.0
            bet.settled = True

        logger.info(
            "Pool settled for %s: outcome=%s, winners=%d, losers=%d, house_take=$%.2f",
            self.market_id, outcome, len(winning_bets), len(losing_bets), house_take,
        )
        return payouts

    def to_dict(self) -> Dict[str, Any]:
        distribution: Dict[str, float] = {}
        for bet in self.bets:
            distribution[bet.prediction] = distribution.get(bet.prediction, 0.0) + bet.stake_amount
        return {
            "market_id": self.market_id,
            "total_pool": round(self.total_pool, 2),
            "total_bets": len(self.bets),
            "house_cut_pct": self.house_cut_pct,
            "allowed_outcomes": self.allowed_outcomes,
            "locked": self.locked,
            "locked_at": self.locked_at,
            "settled": self.settled,
            "settled_at": self.settled_at,
            "outcome": self.actual_outcome,
            "distribution": distribution,
            "created_at": self.created_at,
        }


class BookieAgent:
    """
    Universal betting agent for any MERID instrument or event.

    Features:
    - Pools keyed by market_id (any string: PRED:KALSHI:*, block:N, slo:*, etc.)
    - Dynamic odds with configurable house edge
    - Lock → settle lifecycle with anti-cheating
    - Consensus-store–driven settlement
    - Agent role tracking (directional, hedging, market_making, arb)
    - Coherence scoring (stated prob vs implied prob)
    - Betting health metrics for observability
    """

    def __init__(
        self,
        house_cut_pct: float = 5.0,
        min_bet_amount: float = 1.0,
        max_bet_amount: float = 10000.0,
    ):
        self.house_cut_pct = house_cut_pct
        self.min_bet_amount = min_bet_amount
        self.max_bet_amount = max_bet_amount

        # market_id → BettingPool
        self.pools: Dict[str, BettingPool] = {}
        self.user_balances: Dict[str, float] = {}
        self.agent_rewards: Dict[str, float] = {}

        self.total_house_earnings = 0.0
        self.total_bets_placed = 0
        self.total_volume = 0.0
        self._settled_count = 0

        logger.info(
            "BookieAgent initialized: house_cut=%.1f%%, min_bet=$%.2f, max_bet=$%.2f",
            house_cut_pct, min_bet_amount, max_bet_amount,
        )

    # ── Legacy compat property ───────────────────────────────────────

    @property
    def betting_pools(self) -> Dict[int, BettingPool]:
        """Legacy dict keyed by block_index for backward compat."""
        out: Dict[int, BettingPool] = {}
        for pool in self.pools.values():
            bi = pool.block_index
            if bi is not None:
                out[bi] = pool
        return out

    # ── Pool lifecycle ───────────────────────────────────────────────

    def create_pool(
        self,
        market_id: str,
        allowed_outcomes: Optional[List[str]] = None,
    ) -> BettingPool:
        """Create a new betting pool for any market/instrument/event."""
        if market_id in self.pools:
            raise ValueError(f"Betting pool already exists for {market_id}")
        pool = BettingPool(
            market_id=market_id,
            house_cut_pct=self.house_cut_pct,
            allowed_outcomes=allowed_outcomes or [],
        )
        self.pools[market_id] = pool
        logger.info("Betting pool created for %s", market_id)
        return pool

    def create_betting_pool(self, block_index: int) -> BettingPool:
        """Legacy: create pool for a block index."""
        return self.create_pool(market_id_for_block(block_index))

    def lock_pool(self, market_id: str) -> None:
        """Lock a pool — no more bets accepted."""
        pool = self._require_pool(market_id)
        pool.lock_pool()

    def lock_pool_for_mining(self, block_index: int) -> None:
        """Legacy: lock pool for a block index."""
        self.lock_pool(market_id_for_block(block_index))

    # ── Bet placement ────────────────────────────────────────────────

    def place_bet(
        self,
        user_id: str,
        market_id: str = "",
        prediction: str = "",
        stake_amount: float = 0.0,
        role: str = "directional",
        stated_probability: Optional[float] = None,
        *,
        block_index: Optional[int] = None,
    ) -> Bet:
        """
        Place a bet on any market outcome.

        Args:
            user_id: bettor identifier (agent or human).
            market_id: universal market key.  If empty, ``block_index`` is used.
            prediction: outcome label the user is betting on.
            stake_amount: amount in USD.
            role: agent role (directional, hedging, market_making, arb).
            stated_probability: agent's opinion probability at bet time (for coherence).
            block_index: legacy shortcut — converted to ``block:<N>``.
        """
        # Legacy compat
        if not market_id and block_index is not None:
            market_id = market_id_for_block(block_index)

        if stake_amount < self.min_bet_amount or stake_amount > self.max_bet_amount:
            raise ValueError(f"Stake amount must be between ${self.min_bet_amount} and ${self.max_bet_amount}")

        pool = self._require_pool(market_id)

        if pool.locked:
            raise ValueError(f"Cannot place bet — pool is locked for {market_id}")

        if pool.allowed_outcomes and prediction not in pool.allowed_outcomes:
            raise ValueError(
                f"Invalid prediction '{prediction}' for {market_id}. "
                f"Allowed: {pool.allowed_outcomes}"
            )

        user_balance = self.user_balances.get(user_id, 0.0)
        if user_balance < stake_amount:
            raise ValueError(f"Insufficient balance: ${user_balance:.2f} < ${stake_amount:.2f}")

        odds = self._calculate_odds(pool, prediction, stake_amount)
        implied_prob = 1.0 / odds if odds > 0 else None
        bet_id = self._generate_bet_id(user_id, market_id, prediction, stake_amount)

        bet = Bet(
            bet_id=bet_id,
            user_id=user_id,
            market_id=market_id,
            prediction=prediction,
            stake_amount=stake_amount,
            odds=odds,
            potential_payout=stake_amount * odds,
            role=role,
            stated_probability=stated_probability,
            implied_probability=implied_prob,
        )

        self.user_balances[user_id] = user_balance - stake_amount
        pool.bets.append(bet)
        pool.total_pool += stake_amount
        self.total_bets_placed += 1
        self.total_volume += stake_amount

        logger.info(
            "Bet placed: user=%s, market=%s, prediction=%s, stake=$%.2f, odds=%.2f, role=%s",
            user_id, market_id, prediction, stake_amount, odds, role,
        )
        return bet

    # ── Settlement ───────────────────────────────────────────────────

    def settle_pool_with_outcome(
        self,
        market_id: str,
        outcome: str,
    ) -> Dict[str, float]:
        """Settle a pool with an explicit outcome string."""
        pool = self._require_pool(market_id)
        payouts = pool.settle_pool(outcome)

        for user_id, payout in payouts.items():
            self.user_balances[user_id] = self.user_balances.get(user_id, 0.0) + payout

        total_stakes = sum(bet.stake_amount for bet in pool.bets)
        total_payouts = sum(payouts.values())
        house_earnings = total_stakes - total_payouts
        self.total_house_earnings += house_earnings
        self._settled_count += 1

        logger.info(
            "Pool settled: market=%s, outcome=%s, payouts=$%.2f, house=$%.2f",
            market_id, outcome, total_payouts, house_earnings,
        )
        return payouts

    def settle_from_consensus(self, market_id: str) -> Dict[str, float]:
        """Settle a pool by reading the resolved outcome from PredictionConsensusStore."""
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
        except Exception as exc:
            raise ValueError(f"Cannot access consensus store: {exc}")

        # Look up resolution
        resolved = store.list_resolved(limit=500)
        match = next((r for r in resolved if r.symbol == market_id), None)
        if match is None:
            raise ValueError(f"No resolved outcome found for {market_id}")

        outcome = "yes" if match.outcome == 1 else "no"
        return self.settle_pool_with_outcome(market_id, outcome)

    def settle_pool(
        self,
        block_index: int = 0,
        consensus_approved: bool = True,
        consensus_confidence: float = 0.5,
        *,
        market_id: str = "",
    ) -> Dict[str, float]:
        """Legacy-compatible settle.  Prefers market_id if given."""
        if market_id:
            # Try consensus-store first, fall back to derived outcome
            try:
                return self.settle_from_consensus(market_id)
            except ValueError:
                pass
            outcome = "yes" if consensus_approved else "no"
            return self.settle_pool_with_outcome(market_id, outcome)

        mid = market_id_for_block(block_index)
        if consensus_approved and consensus_confidence >= 0.75:
            outcome = "high_confidence"
        elif consensus_approved:
            outcome = "approved"
        elif consensus_confidence < 0.5:
            outcome = "low_confidence"
        else:
            outcome = "rejected"
        return self.settle_pool_with_outcome(mid, outcome)

    # ── Agent rewards ────────────────────────────────────────────────

    def reward_agents(
        self,
        block_index: int = 0,
        agent_votes: Optional[Dict[str, bool]] = None,
        reward_pool_pct: float = 10.0,
        *,
        market_id: str = "",
    ):
        """Reward agents for correct consensus participation."""
        if not market_id:
            market_id = market_id_for_block(block_index)
        if agent_votes is None:
            agent_votes = {}

        pool = self.pools.get(market_id)
        if not pool or not pool.settled:
            logger.warning("Cannot reward agents — pool not settled for %s", market_id)
            return

        total_stakes = sum(bet.stake_amount for bet in pool.bets)
        house_earnings = total_stakes * (self.house_cut_pct / 100)
        reward_pool = house_earnings * (reward_pool_pct / 100)

        # For block pools, correct_vote is True if outcome is positive
        correct_vote = pool.actual_outcome in ("approved", "high_confidence", "yes")
        correct_agents = [a for a, v in agent_votes.items() if v == correct_vote]

        if correct_agents:
            reward_per_agent = reward_pool / len(correct_agents)
            for agent_id in correct_agents:
                self.agent_rewards[agent_id] = self.agent_rewards.get(agent_id, 0.0) + reward_per_agent
                logger.info("Agent rewarded: %s, amount=$%.2f for %s", agent_id, reward_per_agent, market_id)

    # ── Balance management ───────────────────────────────────────────

    def deposit(self, user_id: str, amount: float) -> None:
        """Deposit funds to user balance."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.user_balances[user_id] = self.user_balances.get(user_id, 0.0) + amount
        logger.info("Deposit: user=%s, amount=$%.2f, new_balance=$%.2f",
                     user_id, amount, self.user_balances[user_id])

    def withdraw(self, user_id: str, amount: float) -> bool:
        """Withdraw funds from user balance."""
        if amount <= 0:
            return False
        balance = self.user_balances.get(user_id, 0.0)
        if balance < amount:
            logger.warning("Withdrawal failed: insufficient balance")
            return False
        self.user_balances[user_id] = balance - amount
        logger.info("Withdrawal: user=%s, amount=$%.2f, new_balance=$%.2f",
                     user_id, amount, self.user_balances[user_id])
        return True

    # ── Queries ──────────────────────────────────────────────────────

    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user betting statistics across all pools."""
        user_bets: List[Bet] = []
        for pool in self.pools.values():
            user_bets.extend(b for b in pool.bets if b.user_id == user_id)

        total_wagered = sum(b.stake_amount for b in user_bets)
        total_won = sum(b.actual_payout for b in user_bets if b.won)
        settled_bets = [b for b in user_bets if b.settled]
        wins = sum(1 for b in settled_bets if b.won)
        win_rate = (wins / len(settled_bets) * 100) if settled_bets else 0.0

        return {
            "user_id": user_id,
            "balance": self.user_balances.get(user_id, 0.0),
            "total_bets": len(user_bets),
            "total_wagered": round(total_wagered, 2),
            "total_won": round(total_won, 2),
            "net_profit": round(total_won - total_wagered, 2),
            "win_rate_pct": round(win_rate, 2),
        }

    def get_pool_stats(self, market_id: str = "", block_index: Optional[int] = None) -> Dict[str, Any]:
        """Get pool statistics.  Accepts market_id or legacy block_index."""
        if not market_id and block_index is not None:
            market_id = market_id_for_block(block_index)
        pool = self.pools.get(market_id)
        if not pool:
            return {}
        d = pool.to_dict()
        # Legacy compat
        bi = pool.block_index
        if bi is not None:
            d["block_index"] = bi
        return d

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get overall bookie agent performance."""
        active = [p for p in self.pools.values() if not p.settled]
        settled = [p for p in self.pools.values() if p.settled]
        return {
            "total_bets_placed": self.total_bets_placed,
            "total_volume": round(self.total_volume, 2),
            "total_house_earnings": round(self.total_house_earnings, 2),
            "active_pools": len(active),
            "settled_pools": len(settled),
            "total_pools": len(self.pools),
            "total_users": len(self.user_balances),
            "total_agent_rewards": round(sum(self.agent_rewards.values()), 2),
        }

    # ── Agent coherence ──────────────────────────────────────────────

    def get_agent_coherence(self, agent_id: str) -> Dict[str, Any]:
        """Compare an agent's bets against its stated probabilities.

        Returns coherence metrics: how well the agent's betting behaviour
        aligns with its probabilistic opinions.
        """
        agent_bets: List[Bet] = []
        for pool in self.pools.values():
            agent_bets.extend(b for b in pool.bets if b.user_id == agent_id)

        if not agent_bets:
            return {"agent_id": agent_id, "total_bets": 0, "coherence_score": None}

        coherence_scores: List[float] = []
        for bet in agent_bets:
            if bet.stated_probability is not None and bet.implied_probability is not None:
                # 1.0 = perfectly aligned, 0.0 = maximally misaligned
                diff = abs(bet.stated_probability - bet.implied_probability)
                coherence_scores.append(max(0.0, 1.0 - diff))

        avg_coherence = sum(coherence_scores) / len(coherence_scores) if coherence_scores else None
        roles: Dict[str, int] = {}
        for b in agent_bets:
            roles[b.role] = roles.get(b.role, 0) + 1

        return {
            "agent_id": agent_id,
            "total_bets": len(agent_bets),
            "bets_with_coherence": len(coherence_scores),
            "coherence_score": round(avg_coherence, 4) if avg_coherence is not None else None,
            "roles": roles,
            "total_wagered": round(sum(b.stake_amount for b in agent_bets), 2),
            "net_profit": round(
                sum(b.actual_payout for b in agent_bets if b.won)
                - sum(b.stake_amount for b in agent_bets), 2
            ),
        }

    # ── Betting health metrics ───────────────────────────────────────

    def get_betting_health(self) -> Dict[str, Any]:
        """Metrics for observability: pool lifecycle, one-sided pools, house PnL."""
        active_pools = [p for p in self.pools.values() if not p.settled]
        settled_pools = [p for p in self.pools.values() if p.settled]

        # One-sided pool detection
        one_sided_count = 0
        for pool in active_pools:
            if pool.bets:
                predictions: Set[str] = {b.prediction for b in pool.bets}
                if len(predictions) <= 1:
                    one_sided_count += 1

        # Settlement latency (lock → settle)
        settlement_latencies: List[float] = []
        for pool in settled_pools:
            if pool.locked_at and pool.settled_at:
                settlement_latencies.append(pool.settled_at - pool.locked_at)
        avg_settlement_latency = (
            sum(settlement_latencies) / len(settlement_latencies)
            if settlement_latencies else None
        )

        # House PnL trend (positive = house winning)
        house_pnl_positive = self.total_house_earnings >= 0

        return {
            "total_pools": len(self.pools),
            "active_pools": len(active_pools),
            "settled_pools": len(settled_pools),
            "total_bets": self.total_bets_placed,
            "total_volume": round(self.total_volume, 2),
            "house_earnings": round(self.total_house_earnings, 2),
            "house_pnl_positive": house_pnl_positive,
            "one_sided_pools": one_sided_count,
            "avg_settlement_latency_s": round(avg_settlement_latency, 2) if avg_settlement_latency is not None else None,
            "total_users": len(self.user_balances),
        }

    # ── Discovery ────────────────────────────────────────────────────

    def list_active_pools(self) -> List[Dict[str, Any]]:
        """List all active (unlocked, unsettled) pools."""
        return [
            p.to_dict() for p in self.pools.values()
            if not p.locked and not p.settled
        ]

    def list_all_pools(self, include_settled: bool = False) -> List[Dict[str, Any]]:
        """List all pools, optionally including settled ones."""
        return [
            p.to_dict() for p in self.pools.values()
            if include_settled or not p.settled
        ]

    # ── Internal helpers ─────────────────────────────────────────────

    def _require_pool(self, market_id: str) -> BettingPool:
        if market_id not in self.pools:
            raise ValueError(f"No betting pool exists for {market_id}")
        return self.pools[market_id]

    def _calculate_odds(self, pool: BettingPool, prediction: str, stake_amount: float) -> float:
        """Calculate odds based on current pool distribution."""
        prediction_total = sum(b.stake_amount for b in pool.bets if b.prediction == prediction)
        other_total = sum(b.stake_amount for b in pool.bets if b.prediction != prediction)
        prediction_total += stake_amount

        total = prediction_total + other_total
        if total == 0:
            return 2.0

        implied_prob = prediction_total / total
        if implied_prob >= 0.99:
            return 1.01

        fair_odds = 1.0 / implied_prob
        odds_with_edge = fair_odds * (1 - self.house_cut_pct / 100)
        return max(1.01, min(odds_with_edge, 100.0))

    @staticmethod
    def _generate_bet_id(user_id: str, market_id: str, prediction: str, stake: float) -> str:
        """Generate unique bet ID."""
        data = f"{user_id}_{market_id}_{prediction}_{stake}_{time.time()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
