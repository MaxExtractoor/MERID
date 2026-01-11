"""
Referral Program API Endpoints.

Manages referral codes, tracking, and rewards.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth.user_manager import user_manager
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/referrals", tags=["referrals"])
logger = get_logger("web.api.referrals")


class ReferralStats(BaseModel):
    """Referral statistics response."""
    user_id: str
    referral_code: str
    total_referrals: int
    referred_by: Optional[str]


@router.get("/{user_id}/stats")
async def get_referral_stats(user_id: str) -> ReferralStats:
    """
    Get referral statistics for a user.
    
    Returns:
    - User's unique referral code
    - Total number of successful referrals
    - Who referred this user (if applicable)
    """
    user = user_manager.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return ReferralStats(
        user_id=user.user_id,
        referral_code=user.referral_code,
        total_referrals=user.total_referrals,
        referred_by=user.referred_by
    )


@router.get("/{user_id}/code")
async def get_referral_code(user_id: str):
    """Get user's unique referral code."""
    user = user_manager.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "user_id": user.user_id,
        "referral_code": user.referral_code,
        "share_url": f"https://merid.io/signup?ref={user.referral_code}"
    }


@router.get("/{user_id}/referrals")
async def get_user_referrals(user_id: str, limit: int = 50):
    """
    Get list of users referred by this user.
    
    In production, this would query a database.
    For now, returns summary statistics.
    """
    user = user_manager.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "user_id": user.user_id,
        "total_referrals": user.total_referrals,
        "referral_code": user.referral_code,
        "message": "Detailed referral list coming soon"
    }


@router.get("/leaderboard")
async def referral_leaderboard(limit: int = 20):
    """
    Get referral leaderboard.
    
    Shows top users by number of successful referrals.
    """
    # Get all users and sort by referral count
    all_users = [user for user in user_manager._users.values() if user.is_active]
    all_users.sort(key=lambda u: u.total_referrals, reverse=True)
    
    leaderboard = []
    for idx, user in enumerate(all_users[:limit], 1):
        leaderboard.append({
            "rank": idx,
            "username": user.username,
            "total_referrals": user.total_referrals,
            "user_id": user.user_id
        })
    
    return {
        "leaderboard": leaderboard,
        "total_users": len(all_users)
    }


@router.post("/validate/{referral_code}")
async def validate_referral_code(referral_code: str):
    """
    Validate a referral code.
    
    Returns referrer information if code is valid.
    """
    # Check if code exists
    user_id = user_manager._referral_to_user.get(referral_code)
    
    if not user_id:
        raise HTTPException(status_code=404, detail="Invalid referral code")
    
    user = user_manager.get_user(user_id)
    
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Invalid referral code")
    
    return {
        "valid": True,
        "referral_code": referral_code,
        "referrer": {
            "username": user.username,
            "user_id": user.user_id,
            "total_referrals": user.total_referrals
        }
    }
