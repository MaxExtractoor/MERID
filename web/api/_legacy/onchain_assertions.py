"""
Onchain Assertion API

Endpoints for registering and managing onchain data assertions.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import time

from onchain.assertion_source import get_onchain_assertion_source
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.onchain_assertions")
router = APIRouter(prefix="/api/v1/onchain", tags=["onchain-assertions"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class OnchainDataPoint(BaseModel):
    """Single onchain data point."""
    chain_id: str = Field(..., description="Blockchain identifier")
    block_number: int = Field(..., ge=0, description="Block number")
    block_hash: str = Field(..., description="Block hash")
    source: str = Field(default="rpc", description="Data source")


class OnchainDataBatch(BaseModel):
    """Batch of onchain data points."""
    onchain_data: List[OnchainDataPoint] = Field(..., description="Onchain data points")
    source: str = Field(default="batch", description="Batch source")


class OnchainAssertionResponse(BaseModel):
    """Response for onchain assertion operations."""
    status: str
    message: str
    assertions_registered: int = 0
    blind_spots_before: List[str] = []
    blind_spots_after: List[str] = []
    timestamp: float


@router.post("/assertions/register")
async def register_onchain_assertion(onchain_data: OnchainDataPoint):
    """Register a single onchain data assertion."""
    try:
        source = get_onchain_assertion_source()
        
        # Get blind spots before
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Update onchain data
        source.update_onchain_state(
            chain_id=onchain_data.chain_id,
            block_number=onchain_data.block_number,
            block_hash=onchain_data.block_hash,
            source=onchain_data.source
        )
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return OnchainAssertionResponse(
            status="success",
            message=f"Onchain assertion registered for {onchain_data.chain_id}",
            assertions_registered=1,
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering onchain assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/batch")
async def register_onchain_assertions_batch(batch: OnchainDataBatch):
    """Register multiple onchain data assertions."""
    try:
        source = get_onchain_assertion_source()
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Convert to list format
        onchain_data_list = [
            {
                "chain_id": data.chain_id,
                "block_number": data.block_number,
                "block_hash": data.block_hash,
                "source": batch.source
            }
            for data in batch.onchain_data
        ]
        
        # Register batch
        source.register_batch_onchain_data(onchain_data_list)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return OnchainAssertionResponse(
            status="success",
            message=f"Batch registered {len(onchain_data_list)} onchain assertions",
            assertions_registered=len(onchain_data_list),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering onchain assertions batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions")
async def get_onchain_assertions():
    """Get all onchain assertions."""
    try:
        source = get_onchain_assertion_source()
        assertions = source.get_onchain_assertions()
        
        return {
            "status": "success",
            "domain": "onchain",
            "assertions": assertions,
            "count": len(assertions),
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting onchain assertions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blind-spots")
async def get_onchain_blind_spots():
    """Get current blind spots and onchain domain status."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind spots)
        registry_status = registry.get_registry_status(current_time, auditor.regime_entropy)
        
        # Get onchain-specific assertions
        onchain_assertions = registry.get_assertions_by_domain("onchain")
        valid_onchain_assertions = sum(1 for a in onchain_assertions if a.status.value == "valid")
        
        return {
            "status": "success",
            "domain": "onchain",
            "blind_spots": registry_status["blind_spots"],
            "onchain_in_blind_spots": "onchain" in registry_status["blind_spots"],
            "total_onchain_assertions": len(onchain_assertions),
            "valid_onchain_assertions": valid_onchain_assertions,
            "system_mode": auditor.get_system_state()["mode"],
            "primary_reason": auditor.get_system_state().get("blind_reason", "none"),
            "timestamp": current_time
        }
        
    except Exception as e:
        logger.error(f"Error getting onchain blind spots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demo-data")
async def load_demo_onchain_data():
    """Load demo onchain data to reduce blind spots."""
    try:
        source = get_onchain_assertion_source()
        
        # Demo onchain data for production threshold (5+ assertions)
        demo_data = [
            {"chain_id": "ethereum", "block_number": 18500000, "block_hash": "0x1234567890abcdef1234567890abcdef1234567890ab", "source": "demo"},
            {"chain_id": "polygon", "block_number": 45000000, "block_hash": "0x567890abcdef1234567890abcdef1234567890ab", "source": "demo"},
            {"chain_id": "arbitrum", "block_number": 12345678, "block_hash": "0x9abcdef1234567890abcdef1234567890ab", "source": "demo"},
            {"chain_id": "optimism", "block_number": 98765432, "block_hash": "0xdef1234567890abcdef1234567890ab", "source": "demo"},
            {"chain_id": "base", "block_number": 87654321, "block_hash": "0xcba4567890abcdef1234567890abcdef", "source": "demo"},
            {"chain_id": "bsc", "block_number": 34567890, "block_hash": "0xabc1234567890abcdef1234567890ab", "source": "demo"},
            {"chain_id": "avalanche", "block_number": 23456789, "block_hash": "0xbcd234567890abcdef1234567890ab", "source": "demo"}
        ]
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Register demo data
        source.register_batch_onchain_data(demo_data)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return OnchainAssertionResponse(
            status="success",
            message=f"Loaded {len(demo_data)} demo onchain assertions",
            assertions_registered=len(demo_data),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error loading demo onchain data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
