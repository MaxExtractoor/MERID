"""
Mock API endpoints for trading arena
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
import time
import random

router = APIRouter()

# Mock data stores
mock_arena_status = {}
mock_participants = []
mock_leaderboard = []
mock_events = []

@router.get("/status")
async def get_arena_status():
    """Get arena status"""
    return {
        "status": "active",
        "name": "Trading Arena Competition",
        "current_round": random.randint(1, 10),
        "time_remaining": f"{random.randint(1, 60)}:00",
        "total_participants": len(mock_participants),
        "active_participants": len([p for p in mock_participants if p.get("active", True)]),
        "total_trades": random.randint(100, 1000),
        "prize_pool": random.randint(10000, 100000)
    }

@router.get("/arenas")
async def get_arenas():
    """Get available arenas"""
    return [
        {
            "id": "arena_1",
            "name": "Main Arena",
            "description": "Primary trading competition arena"
        },
        {
            "id": "arena_2", 
            "name": "Practice Arena",
            "description": "Practice trading arena"
        }
    ]

@router.get("/participants")
async def get_participants():
    """Get arena participants"""
    # Generate mock participants if empty
    if not mock_participants:
        mock_participants.extend([
            {
                "id": f"participant_{i}",
                "name": f"Trader {i+1}",
                "rank": i + 1,
                "pnl": random.uniform(-1000, 5000),
                "trade_count": random.randint(10, 100),
                "win_rate": random.uniform(0.3, 0.8),
                "active": random.choice([True, False])
            }
            for i in range(6)
        ])
    
    return {"participants": mock_participants}

@router.get("/leaderboard")
async def get_leaderboard():
    """Get arena leaderboard"""
    # Generate mock leaderboard if empty
    if not mock_leaderboard:
        mock_leaderboard.extend([
            {
                "rank": i + 1,
                "trader_name": f"Trader {i+1}",
                "pnl": random.uniform(-1000, 5000),
                "trade_count": random.randint(10, 100),
                "win_rate": random.uniform(0.3, 0.8)
            }
            for i in range(10)
        ])
        
        # Sort by PnL
        mock_leaderboard.sort(key=lambda x: x["pnl"], reverse=True)
    
    return {"leaderboard": mock_leaderboard}

@router.get("/{arena_id}")
async def get_arena_details(arena_id: str):
    """Get specific arena details"""
    return {
        "id": arena_id,
        "name": "Main Arena",
        "status": "active",
        "current_round": random.randint(1, 10),
        "time_remaining": f"{random.randint(1, 60)}:00",
        "duration": "2 hours",
        "model": "default",
        "scenario": "competition",
        "current_step": random.randint(0, 100),
        "total_steps": 100,
        "elapsed": f"{random.randint(1, 7200)}s"
    }

@router.get("/{arena_id}/events")
async def get_arena_events(arena_id: str, limit: int = 20):
    """Get events for a specific arena"""
    return {
        "events": [
            {
                "type": random.choice(["trade", "position", "rank_change", "elimination"]),
                "title": f"Arena Event {i+1}",
                "description": f"Mock event {i+1} for arena {arena_id}",
                "timestamp": time.time() - random.randint(0, 3600),
                "participant": f"Trader {random.randint(1, 10)}",
                "arena_id": arena_id
            }
            for i in range(limit)
        ]
    }

@router.get("/{arena_id}/status")
async def get_arena_status_details(arena_id: str):
    """Get detailed arena status"""
    return {
        "status": "active",
        "name": "Main Arena",
        "current_round": random.randint(1, 10),
        "time_remaining": f"{random.randint(1, 60)}:00",
        "total_participants": len(mock_participants),
        "active_participants": len([p for p in mock_participants if p.get("active", True)]),
        "total_trades": random.randint(100, 1000),
        "prize_pool": random.randint(10000, 100000),
        "connections": random.randint(5, 20),
        "data_rate": f"{random.randint(10, 100)} msgs/sec"
    }
