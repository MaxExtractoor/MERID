"""
Market Assertion API

Endpoints for registering and managing market data assertions.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import time

from market.assertion_source import get_market_assertion_source
from utils.logger import get_logger

logger = get_logger("web.api.market_assertions")
router = APIRouter(prefix="/api/v1/market", tags=["market-assertions"])


class MarketDataPoint(BaseModel):
    """Single market data point."""
    symbol: str = Field(..., description="Trading symbol")
    price: float = Field(..., gt=0, description="Current price")
    volume: float = Field(..., ge=0, description="Trading volume")
    source: str = Field(default="api", description="Data source")


class MarketDataBatch(BaseModel):
    """Batch of market data points."""
    market_data: List[MarketDataPoint] = Field(..., description="Market data points")
    source: str = Field(default="batch", description="Batch source")


class MarketAssertionResponse(BaseModel):
    """Response for market assertion operations."""
    status: str
    message: str
    assertions_registered: int = 0
    blind_spots_before: List[str] = []
    blind_spots_after: List[str] = []
    timestamp: float


@router.post("/assertions/register")
async def register_market_assertion(market_data: MarketDataPoint):
    """Register a single market data assertion."""
    try:
        source = get_market_assertion_source()
        
        # Get blind spots before
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Update market data
        source.update_market_data(
            symbol=market_data.symbol,
            price=market_data.price,
            volume=market_data.volume,
            source=market_data.source
        )
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return MarketAssertionResponse(
            status="success",
            message=f"Market assertion registered for {market_data.symbol}",
            assertions_registered=1,
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering market assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/assertions/batch")
async def register_market_assertions_batch(batch: MarketDataBatch):
    """Register multiple market data assertions."""
    try:
        source = get_market_assertion_source()
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Convert to list format
        market_data_list = [
            {
                "symbol": data.symbol,
                "price": data.price,
                "volume": data.volume,
                "source": batch.source
            }
            for data in batch.market_data
        ]
        
        # Register batch
        source.register_batch_market_data(market_data_list)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return MarketAssertionResponse(
            status="success",
            message=f"Batch registered {len(market_data_list)} market assertions",
            assertions_registered=len(market_data_list),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error registering market assertions batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assertions")
async def get_market_assertions():
    """Get all market assertions."""
    try:
        source = get_market_assertion_source()
        assertions = source.get_market_assertions()
        
        return {
            "status": "success",
            "domain": "market",
            "assertions": assertions,
            "count": len(assertions),
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting market assertions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blind-spots")
async def get_market_blind_spots():
    """Get current blind spots and market domain status."""
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Get registry status (contains blind spots)
        registry_status = registry.get_registry_status(current_time, auditor.regime_entropy)
        
        # Get market-specific assertions
        market_assertions = registry.get_assertions_by_domain("market")
        valid_market_assertions = sum(1 for a in market_assertions if a.status.value == "valid")
        
        return {
            "status": "success",
            "domain": "market",
            "blind_spots": registry_status["blind_spots"],
            "market_in_blind_spots": "market" in registry_status["blind_spots"],
            "total_market_assertions": len(market_assertions),
            "valid_market_assertions": valid_market_assertions,
            "system_mode": auditor.get_system_state()["mode"],
            "primary_reason": auditor.get_system_state().get("blind_reason", "none"),
            "timestamp": current_time
        }
        
    except Exception as e:
        logger.error(f"Error getting market blind spots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/demo-data")
async def load_demo_market_data():
    """Load demo market data to reduce blind spots."""
    try:
        source = get_market_assertion_source()
        
        # Enhanced demo market data for production threshold (5+ assertions)
        demo_data = [
            {"symbol": "BTC/USD", "price": 45000.0, "volume": 1000000.0, "source": "demo"},
            {"symbol": "ETH/USD", "price": 3000.0, "volume": 500000.0, "source": "demo"},
            {"symbol": "SOL/USD", "price": 120.0, "volume": 200000.0, "source": "demo"},
            {"symbol": "MATIC/USD", "price": 0.85, "volume": 800000.0, "source": "demo"},
            {"symbol": "AVAX/USD", "price": 35.0, "volume": 150000.0, "source": "demo"},
            {"symbol": "DOT/USD", "price": 8.5, "volume": 300000.0, "source": "demo"},
            {"symbol": "LINK/USD", "price": 15.0, "volume": 250000.0, "source": "demo"}
        ]
        
        # Get blind spots before
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        # Get registry status (contains blind_spots)
        registry_status_before = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_before = registry_status_before["blind_spots"]
        
        # Register demo data
        source.register_batch_market_data(demo_data)
        
        # Get blind spots after
        registry_status_after = registry.get_registry_status(current_time, auditor.regime_entropy)
        blind_spots_after = registry_status_after["blind_spots"]
        
        return MarketAssertionResponse(
            status="success",
            message=f"Loaded {len(demo_data)} demo market assertions",
            assertions_registered=len(demo_data),
            blind_spots_before=blind_spots_before,
            blind_spots_after=blind_spots_after,
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"Error loading demo market data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
