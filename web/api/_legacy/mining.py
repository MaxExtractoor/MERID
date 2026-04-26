"""
Block Mining API Endpoints.

Provides comprehensive mining control and block information.
"""

from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from simulation.mining_engine import MiningEngine
from swarm.spawner import SwarmSpawner
from swarm.performance import performance_ledger
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/mining", tags=["mining"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.mining")

# Global mining engine instance
_mining_engine: Optional[MiningEngine] = None
_mining_in_progress = False
_latest_block: Optional[dict] = None
_latest_value_metrics: Optional[dict] = None
_mining_lock = threading.Lock()  # FPA-06: guards engine singleton + TOCTOU on _mining_in_progress


def get_mining_engine() -> MiningEngine:
    """Get or create mining engine singleton."""
    global _mining_engine
    if _mining_engine is None:
        with _mining_lock:
            if _mining_engine is None:
                spawner = SwarmSpawner(performance_ledger)
                _mining_engine = MiningEngine(spawner=spawner)
    return _mining_engine


class MineBlockRequest(BaseModel):
    """Request to mine a new block."""
    block_index: Optional[int] = Field(None, description="Block index (auto-increments if not provided)")
    previous_hash: Optional[str] = Field(None, description="Previous block hash")
    market_context: Optional[dict] = Field(None, description="Optional market context data")


@router.post("/mine")
async def mine_block(request: MineBlockRequest, background_tasks: BackgroundTasks):
    """
    Mine a new MERID block with comprehensive value assessment.
    
    This is the primary mining endpoint that orchestrates:
    - Intelligence gathering from all sources
    - Agent simulation and consensus
    - Oracle validation (Chainlink, UMA)
    - Block value calculation
    - Proof-of-Useful-Simulation
    """
    global _mining_in_progress, _latest_block, _latest_value_metrics
    
    if _mining_in_progress:
        raise HTTPException(
            status_code=409,
            detail="Mining already in progress. Please wait for current block to complete."
        )
    
    # Determine block index
    block_index = request.block_index
    if block_index is None:
        block_index = (_latest_block["index"] + 1) if _latest_block else 0
    
    # Determine previous hash
    previous_hash = request.previous_hash
    if previous_hash is None:
        previous_hash = _latest_block["hash"] if _latest_block else "0" * 64
    
    # Start mining in background
    _mining_in_progress = True
    
    async def mine_task():
        global _mining_in_progress, _latest_block, _latest_value_metrics
        try:
            engine = get_mining_engine()
            block_data, value_metrics = await engine.mine_block(
                block_index=block_index,
                previous_hash=previous_hash,
                market_context=request.market_context
            )
            
            _latest_block = block_data
            _latest_value_metrics = value_metrics.to_dict()
            
            logger.info(
                "Block #%d mined successfully: Score=%.2f Grade=%s",
                block_index,
                value_metrics.overall_score,
                value_metrics.value_grade
            )
        except Exception as exc:
            logger.error("Mining failed: %s", exc)
        finally:
            _mining_in_progress = False
    
    background_tasks.add_task(mine_task)
    
    return {
        "status": "mining_started",
        "block_index": block_index,
        "message": "Block mining initiated. Use /mining/status to check progress."
    }


@router.get("/status")
async def mining_status():
    """Get current mining status."""
    return {
        "mining_in_progress": _mining_in_progress,
        "latest_block": _latest_block,
        "latest_value_metrics": _latest_value_metrics
    }


@router.get("/blocks/{block_index}")
async def get_block(block_index: int):
    """Get details of a specific block."""
    if _latest_block and _latest_block["index"] == block_index:
        return {
            "block": _latest_block,
            "value_metrics": _latest_value_metrics
        }
    
    raise HTTPException(
        status_code=404,
        detail=f"Block #{block_index} not found"
    )


@router.get("/blocks/latest")
async def get_latest_block():
    """Get the latest mined block."""
    if _latest_block is None:
        raise HTTPException(
            status_code=404,
            detail="No blocks mined yet"
        )
    
    return {
        "block": _latest_block,
        "value_metrics": _latest_value_metrics
    }


@router.get("/value/breakdown")
async def get_value_breakdown():
    """Get detailed value breakdown of latest block."""
    if _latest_value_metrics is None:
        raise HTTPException(
            status_code=404,
            detail="No block value metrics available"
        )
    
    return _latest_value_metrics


@router.get("/difficulty")
async def get_mining_difficulty():
    """Get current mining difficulty settings."""
    engine = get_mining_engine()
    
    return {
        "current_difficulty": engine.current_difficulty,
        "min_confidence_threshold": engine.min_confidence_threshold,
        "difficulty_explanation": {
            "3": "C-grade and below (score < 70)",
            "4": "B-grade (score 70-79)",
            "5": "A-grade (score 80-89)",
            "6": "S-grade (score 90+)"
        }
    }


@router.post("/difficulty")
async def set_mining_difficulty(difficulty: int, min_confidence: float = 0.70):
    """
    Update mining difficulty settings.
    
    Requires admin privileges in production.
    """
    if difficulty < 1 or difficulty > 10:
        raise HTTPException(
            status_code=400,
            detail="Difficulty must be between 1 and 10"
        )
    
    if min_confidence < 0.0 or min_confidence > 1.0:
        raise HTTPException(
            status_code=400,
            detail="Min confidence must be between 0.0 and 1.0"
        )
    
    engine = get_mining_engine()
    engine.current_difficulty = difficulty
    engine.min_confidence_threshold = min_confidence
    
    return {
        "status": "updated",
        "current_difficulty": difficulty,
        "min_confidence_threshold": min_confidence
    }
