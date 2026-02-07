"""
Betting API Endpoints.

Provides consensus betting functionality:
- Bet placement on block outcomes
- Pool management
- Payout distribution
- User statistics
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from trading.agents.bookie_agent import BookieAgent
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/betting", tags=["betting"])
logger = get_logger("web.api.betting")

# Global bookie agent instance
_bookie_agent: Optional[BookieAgent] = None


def get_bookie_agent() -> BookieAgent:
    """Get or create bookie agent singleton."""
    global _bookie_agent
    if _bookie_agent is None:
        _bookie_agent = BookieAgent(
            house_cut_pct=5.0,
            min_bet_amount=1.0,
            max_bet_amount=10000.0
        )
    return _bookie_agent


class PlaceBetRequest(BaseModel):
    """Bet placement request."""
    user_id: str = Field(..., description="User ID")
    block_index: int = Field(..., description="Block index to bet on")
    prediction: str = Field(..., description="Prediction: approved, rejected, high_confidence, low_confidence")
    stake_amount: float = Field(..., gt=0, description="Stake amount in USD")


@router.post("/place")
async def place_bet(request: PlaceBetRequest):
    """
    Place bet on block consensus outcome.
    
    Pool must not be locked (mining hasn't started yet).
    """
    agent = get_bookie_agent()
    
    try:
        bet = agent.place_bet(
            user_id=request.user_id,
            block_index=request.block_index,
            prediction=request.prediction,
            stake_amount=request.stake_amount
        )
        
        return {
            "bet_id": bet.bet_id,
            "user_id": bet.user_id,
            "block_index": bet.block_index,
            "prediction": bet.prediction,
            "stake_amount": bet.stake_amount,
            "odds": bet.odds,
            "potential_payout": bet.potential_payout,
            "placed_at": bet.placed_at
        }
    
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pools/{block_index}/create")
async def create_betting_pool(block_index: int):
    """Create new betting pool for upcoming block."""
    agent = get_bookie_agent()
    
    try:
        pool = agent.create_betting_pool(block_index)
        
        return {
            "block_index": pool.block_index,
            "total_pool": pool.total_pool,
            "house_cut_pct": pool.house_cut_pct,
            "locked": pool.locked,
            "status": "created"
        }
    
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pools/{block_index}/lock")
async def lock_betting_pool(block_index: int):
    """
    Lock betting pool before mining starts.
    
    Critical anti-cheating mechanism.
    """
    agent = get_bookie_agent()
    
    try:
        agent.lock_pool_for_mining(block_index)
        
        return {
            "block_index": block_index,
            "status": "locked",
            "message": "Pool locked - no more bets accepted"
        }
    
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pools/{block_index}/settle")
async def settle_betting_pool(
    block_index: int,
    consensus_approved: bool,
    consensus_confidence: float
):
    """
    Settle betting pool after block is mined.
    
    Determines outcome and distributes payouts.
    """
    agent = get_bookie_agent()
    
    try:
        payouts = agent.settle_pool(
            block_index=block_index,
            consensus_approved=consensus_approved,
            consensus_confidence=consensus_confidence
        )
        
        return {
            "block_index": block_index,
            "status": "settled",
            "total_payouts": sum(payouts.values()),
            "winners": len(payouts),
            "payouts": payouts
        }
    
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pools/{block_index}")
async def get_pool_info(block_index: int):
    """Get betting pool information."""
    agent = get_bookie_agent()
    
    stats = agent.get_pool_stats(block_index)
    
    if not stats:
        raise HTTPException(status_code=404, detail="Pool not found")
    
    return stats


@router.get("/pools/active")
async def get_active_pools():
    """Get all active (unlocked) betting pools."""
    agent = get_bookie_agent()
    
    active_pools = [
        agent.get_pool_stats(block_index)
        for block_index, pool in agent.betting_pools.items()
        if not pool.locked and not pool.settled
    ]
    
    return {
        "active_pools": active_pools,
        "total_active": len(active_pools)
    }


@router.get("/user/{user_id}/stats")
async def get_user_betting_stats(user_id: str):
    """Get user betting statistics."""
    agent = get_bookie_agent()
    
    stats = agent.get_user_stats(user_id)
    
    return stats


@router.get("/user/{user_id}/balance")
async def get_user_balance(user_id: str):
    """Get user balance."""
    agent = get_bookie_agent()
    
    balance = agent.user_balances.get(user_id, 0.0)
    
    return {
        "user_id": user_id,
        "balance": balance
    }


class DepositRequest(BaseModel):
    """Deposit request."""
    user_id: str
    amount: float = Field(..., gt=0)


@router.post("/deposit")
async def deposit_funds(request: DepositRequest):
    """Deposit funds to user balance."""
    agent = get_bookie_agent()
    
    agent.deposit(request.user_id, request.amount)
    
    return {
        "user_id": request.user_id,
        "deposited": request.amount,
        "new_balance": agent.user_balances.get(request.user_id, 0.0)
    }


class WithdrawRequest(BaseModel):
    """Withdraw request."""
    user_id: str
    amount: float = Field(..., gt=0)


@router.post("/withdraw")
async def withdraw_funds(request: WithdrawRequest):
    """Withdraw funds from user balance."""
    agent = get_bookie_agent()
    
    success = agent.withdraw(request.user_id, request.amount)
    
    if not success:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    return {
        "user_id": request.user_id,
        "withdrawn": request.amount,
        "new_balance": agent.user_balances.get(request.user_id, 0.0)
    }


@router.get("/leaderboard")
async def get_betting_leaderboard(limit: int = 10):
    """Get betting leaderboard by net profit."""
    agent = get_bookie_agent()
    
    # Calculate net profit for all users
    user_stats = []
    for user_id in agent.user_balances.keys():
        stats = agent.get_user_stats(user_id)
        user_stats.append(stats)
    
    # Sort by net profit
    leaderboard = sorted(user_stats, key=lambda x: x["net_profit"], reverse=True)[:limit]
    
    return {
        "leaderboard": leaderboard,
        "total_users": len(user_stats)
    }


@router.get("/stats")
async def get_betting_stats():
    """Get overall betting system statistics."""
    agent = get_bookie_agent()
    
    return agent.get_performance_stats()


@router.post("/agents/reward/{block_index}")
async def reward_agents_for_block(
    block_index: int,
    agent_votes: dict,
    reward_pool_pct: float = 10.0
):
    """
    Reward agents for participation in consensus.
    
    Agents that voted correctly get proportional rewards.
    """
    agent = get_bookie_agent()
    
    agent.reward_agents(
        block_index=block_index,
        agent_votes=agent_votes,
        reward_pool_pct=reward_pool_pct
    )
    
    return {
        "block_index": block_index,
        "status": "agents_rewarded",
        "total_agent_rewards": sum(agent.agent_rewards.values())
    }


@router.get("/agents/rewards")
async def get_agent_rewards():
    """Get agent reward statistics."""
    agent = get_bookie_agent()
    
    return {
        "agent_rewards": agent.agent_rewards,
        "total_rewards": sum(agent.agent_rewards.values())
    }
