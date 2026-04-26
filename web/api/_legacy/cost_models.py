"""
Cost Models API Endpoints - Phase 16

Provides API access to gas estimation, slippage modeling, latency analysis, and MEV risk.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arbitrage.cost_models import (
    get_gas_estimator,
    get_slippage_model,
    get_latency_model,
    get_mev_estimator,
    get_net_profit_calculator,
    ChainType,
    VenueType,
)
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/costs", tags=["costs"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.cost_models")


class GasEstimateRequest(BaseModel):
    chain: str
    operation: str = "uniswap_v3_swap"
    gas_units: Optional[int] = None
    priority_multiplier: float = 1.0


class SlippageEstimateRequest(BaseModel):
    venue: str
    venue_type: str = "cex"
    symbol: str
    side: str
    size_usd: float
    pool_tvl_usd: Optional[float] = None


class LatencyEstimateRequest(BaseModel):
    venue: str
    venue_type: str = "cex"


class MEVRiskRequest(BaseModel):
    chain: str
    size_usd: float
    expected_profit_bps: float
    is_public_mempool: bool = True


class NetProfitRequest(BaseModel):
    gross_profit_usd: float
    size_usd: float
    legs: List[Dict[str, Any]]
    chain: Optional[str] = None


@router.get("/status")
async def get_cost_models_status() -> Dict[str, Any]:
    """Get status of all cost models."""
    return {
        "gas_estimator": {
            "supported_chains": [c.value for c in ChainType],
            "default_operations": list(get_gas_estimator().GAS_UNITS.keys()),
        },
        "slippage_model": {
            "venue_types": [v.value for v in VenueType],
        },
        "latency_model": {
            "venue_types": [v.value for v in VenueType],
        },
        "mev_estimator": {
            "supported_chains": [c.value for c in ChainType],
        },
        "net_profit_calculator": {
            "min_profit_threshold_bps": get_net_profit_calculator().min_profit_threshold_bps,
        },
    }


@router.post("/gas/estimate")
async def estimate_gas(request: GasEstimateRequest) -> Dict[str, Any]:
    """Estimate gas cost for an operation."""
    try:
        chain = ChainType(request.chain)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain: {request.chain}")
    
    if chain == ChainType.SOLANA:
        estimate = get_gas_estimator().estimate_solana(request.gas_units or 200000)
    else:
        estimate = get_gas_estimator().estimate_gas(
            chain=chain,
            operation=request.operation,
            gas_units=request.gas_units,
            priority_multiplier=request.priority_multiplier,
        )
    
    return estimate.to_dict()


@router.post("/gas/update-price")
async def update_gas_price(chain: str, gas_price_gwei: float) -> Dict[str, Any]:
    """Update cached gas price for a chain."""
    try:
        chain_type = ChainType(chain)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain: {chain}")
    
    get_gas_estimator().update_gas_price(chain_type, gas_price_gwei)
    return {"status": "updated", "chain": chain, "gas_price_gwei": gas_price_gwei}


@router.post("/slippage/estimate")
async def estimate_slippage(request: SlippageEstimateRequest) -> Dict[str, Any]:
    """Estimate slippage for a trade."""
    try:
        venue_type = VenueType(request.venue_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid venue type: {request.venue_type}")
    
    model = get_slippage_model()
    
    if venue_type == VenueType.DEX_AMM:
        estimate = model.estimate_amm_slippage(
            venue=request.venue,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            pool_tvl_usd=request.pool_tvl_usd,
        )
    elif venue_type == VenueType.CEX:
        estimate = model.estimate_cex_slippage(
            venue=request.venue,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
        )
    else:
        estimate = model.estimate_orderbook_slippage(
            venue=request.venue,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
        )
    
    return estimate.to_dict()


@router.post("/slippage/update-liquidity")
async def update_liquidity(venue: str, symbol: str, depth_usd: float) -> Dict[str, Any]:
    """Update liquidity depth for a venue/symbol."""
    get_slippage_model().update_liquidity(venue, symbol, depth_usd)
    return {"status": "updated", "venue": venue, "symbol": symbol, "depth_usd": depth_usd}


@router.post("/latency/estimate")
async def estimate_latency(request: LatencyEstimateRequest) -> Dict[str, Any]:
    """Estimate execution latency for a venue."""
    try:
        venue_type = VenueType(request.venue_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid venue type: {request.venue_type}")
    
    estimate = get_latency_model().estimate_latency(request.venue, venue_type)
    return estimate.to_dict()


@router.post("/latency/record")
async def record_latency(venue: str, latency_ms: float) -> Dict[str, Any]:
    """Record observed latency for a venue."""
    get_latency_model().record_latency(venue, latency_ms)
    return {"status": "recorded", "venue": venue, "latency_ms": latency_ms}


@router.post("/mev/estimate")
async def estimate_mev_risk(request: MEVRiskRequest) -> Dict[str, Any]:
    """Estimate MEV extraction risk."""
    try:
        chain = ChainType(request.chain)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain: {request.chain}")
    
    risk = get_mev_estimator().estimate_mev_risk(
        chain=chain,
        size_usd=request.size_usd,
        expected_profit_bps=request.expected_profit_bps,
        is_public_mempool=request.is_public_mempool,
    )
    return risk.to_dict()


@router.post("/net-profit/calculate")
async def calculate_net_profit(request: NetProfitRequest) -> Dict[str, Any]:
    """Calculate net profit after all costs."""
    chain = None
    if request.chain:
        try:
            chain = ChainType(request.chain)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid chain: {request.chain}")
    
    analysis = get_net_profit_calculator().calculate_net_profit(
        gross_profit_usd=request.gross_profit_usd,
        size_usd=request.size_usd,
        legs=request.legs,
        chain=chain,
    )
    return analysis.to_dict()


@router.post("/net-profit/threshold")
async def set_profit_threshold(threshold_bps: float) -> Dict[str, Any]:
    """Set minimum profit threshold."""
    get_net_profit_calculator().min_profit_threshold_bps = threshold_bps
    return {"status": "updated", "min_profit_threshold_bps": threshold_bps}
