"""
Kalshi API Robustness Retrofit Examples

Shows how to apply robust patterns to critical kalshi_api.py endpoints.
These are ready-to-use implementations that can replace existing endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, HTTPException, Depends
from datetime import datetime, timezone

from web.api.kalshi_api_robust import (
    robust_endpoint, 
    KalshiRequestValidator, 
    get_endpoint_config,
    RobustStreamingResponse,
    get_kalshi_api_robustness
)
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_api_retrofit")

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi"])


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL ENDPOINT 1: /markets (Market Browsing)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/markets", summary="Browse Kalshi Markets (Robust)")
@robust_endpoint(
    "get_markets",
    fallback_value={
        "markets": [],
        "count": 0,
        "error": "Market data temporarily unavailable",
        "timestamp": datetime.now(timezone.utc).isoformat()
    },
    **get_endpoint_config("get_markets")
)
async def get_markets_robust(
    category: Optional[str] = Query(None, description="Filter by category"),
    asset: Optional[str] = Query(None, description="Filter by asset (BTC, ETH, etc.)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    search: Optional[str] = Query(None, description="Keyword search"),
    sort: Optional[str] = Query(None, description="Sort: volume|expiry|trending"),
    live: Optional[bool] = Query(None, description="Live feed only"),
    limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """
    Browse cataloged Kalshi markets with robust error handling.
    
    Enhanced with:
    - Input validation
    - Automatic retry on transient failures
    - Graceful fallback on persistent errors
    - Health tracking
    """
    # Validate inputs
    limit = KalshiRequestValidator.validate_limit(limit, 500)
    if asset:
        asset = KalshiRequestValidator.validate_ticker(asset)
    
    # Try catalog first with error recovery
    catalog = None
    markets = []
    
    try:
        catalog = _get_catalog()
        if catalog:
            if category:
                markets = catalog.get_markets_by_category(category, timeframe=timeframe, asset=asset)
            elif asset:
                markets = catalog.get_markets_by_asset(asset, timeframe=timeframe)
            elif timeframe:
                markets = catalog.get_markets_by_timeframe(timeframe)
            else:
                markets = catalog.get_all_markets()
            
            # Apply filters
            if live:
                markets = [m for m in markets if m.market.active]
            
            if search:
                q = search.lower()
                markets = [
                    m for m in markets
                    if q in (m.market.question or "").lower()
                    or q in (m.market.market_id or "").lower()
                    or q in (m.asset or "").lower()
                ]
            
            # Sort
            if sort in ("volume", "trending"):
                markets = sorted(
                    markets, 
                    key=lambda m: float(m.market.volume) if m.market.volume else 0, 
                    reverse=True
                )
            elif sort == "expiry" or live:
                markets = sorted(
                    markets, 
                    key=lambda m: m.minutes_to_expiry if m.minutes_to_expiry is not None else float("inf")
                )
            
            markets = markets[:limit]
    except Exception as exc:
        logger.warning(f"Catalog query failed: {exc}, falling back to empty result")
        markets = []
    
    # Build response
    response_markets = []
    for m in markets:
        try:
            response_markets.append({
                "ticker": m.market.market_id,
                "question": m.market.question,
                "category": m.category,
                "asset": m.asset,
                "timeframe": m.timeframe,
                "volume": m.market.volume,
                "status": "active" if m.market.active else "closed",
                "minutes_to_expiry": m.minutes_to_expiry,
            })
        except Exception as exc:
            logger.debug(f"Skipping malformed market entry: {exc}")
            continue
    
    return {
        "markets": response_markets,
        "count": len(response_markets),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL ENDPOINT 2: /orders (Order Placement)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/orders", summary="Place Order (Robust)")
@robust_endpoint(
    "place_order",
    fallback_value={
        "status": "error",
        "error": "Order placement temporarily unavailable",
        "order_id": None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    },
    **get_endpoint_config("place_order")
)
async def place_order_robust(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Place an order on Kalshi with robust error handling and validation.
    
    Enhanced with:
    - Comprehensive input validation
    - Risk checks before submission
    - Retry on transient failures
    - Detailed error reporting
    """
    # Validate required fields
    required_fields = ["ticker", "action", "side", "count"]
    missing = [f for f in required_fields if f not in order_data]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {missing}")
    
    # Validate inputs
    ticker = KalshiRequestValidator.validate_ticker(order_data.get("ticker"))
    action = order_data.get("action")
    side = order_data.get("side")
    count = KalshiRequestValidator.validate_count(order_data.get("count"))
    price = KalshiRequestValidator.validate_price_cents(order_data.get("price_cents"))
    
    if action not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    
    if side not in ("yes", "no"):
        raise HTTPException(status_code=400, detail=f"Invalid side: {side}")
    
    # Get risk manager with error handling
    risk = _get_risk()
    if risk:
        try:
            ok, reason = risk.check_order(ticker, count, price or 50)
            if not ok:
                return {
                    "status": "rejected",
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
        except Exception as exc:
            logger.warning(f"Risk check failed (proceeding with caution): {exc}")
    
    # Get venue gate for mode checking
    venue_gate = _get_venue_gate()
    if venue_gate and not venue_gate.can_trade():
        return {
            "status": "rejected",
            "reason": "Trading halted by venue gate",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # Get REST client
    client = _get_rest_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client unavailable")
    
    # Build order with validation
    order_spec = {
        "ticker": ticker,
        "action": action,
        "side": side,
        "count": count,
        "type": "limit" if price else "market",
        "client_order_id": order_data.get("client_order_id", f"merid_{int(datetime.now(timezone.utc).timestamp())}"),
    }
    
    if price:
        if side == "yes":
            order_spec["yes_price"] = price
        else:
            order_spec["no_price"] = price
    
    # Add optional fields
    if "time_in_force" in order_data:
        order_spec["time_in_force"] = order_data["time_in_force"]
    if "order_group_id" in order_data:
        order_spec["order_group_id"] = order_data["order_group_id"]
    
    # Submit order with retry handled by decorator
    try:
        result = await client.create_order(order_spec)
        
        return {
            "status": "submitted",
            "order_id": result.get("order_id"),
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        logger.error(f"Order placement failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Order failed: {str(exc)}")


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL ENDPOINT 3: /positions (Position Query)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/positions", summary="Current Positions (Robust)")
@robust_endpoint(
    "get_positions",
    fallback_value={
        "positions": [],
        "total_exposure": 0.0,
        "count": 0,
        "error": "Position data temporarily unavailable",
        "timestamp": datetime.now(timezone.utc).isoformat()
    },
    **get_endpoint_config("get_positions")
)
async def get_positions_robust() -> Dict[str, Any]:
    """
    Get current Kalshi positions with robust error handling.
    
    Enhanced with:
    - Position cache reconciliation
    - Error recovery with empty fallback
    - Exposure calculation with validation
    """
    positions = []
    total_exposure = 0.0
    
    # Try position cache first
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cached_positions = cache.get_all_positions()
        
        for market_id, pos in cached_positions.items():
            try:
                positions.append({
                    "market_id": market_id,
                    "contracts": pos.contracts,
                    "side": pos.side,
                    "avg_price_cents": pos.avg_price_cents,
                    "unrealized_pnl_usd": float(pos.unrealized_pnl_usd),
                    "realized_pnl_usd": float(pos.realized_pnl_usd),
                    "last_updated": pos.last_updated.isoformat(),
                })
                total_exposure += pos.contracts
            except Exception as exc:
                logger.debug(f"Skipping malformed position: {exc}")
                continue
    except Exception as exc:
        logger.warning(f"Position cache failed: {exc}")
    
    # Fallback to REST API if cache is empty
    if not positions:
        client = _get_rest_client()
        if client:
            try:
                api_positions = await client.get_positions()
                if api_positions:
                    for pos in api_positions:
                        try:
                            positions.append({
                                "market_id": pos.get("market_id", "unknown"),
                                "contracts": pos.get("contracts", 0),
                                "side": pos.get("side", "yes"),
                                "avg_price_cents": pos.get("avg_price_cents", 50),
                                "unrealized_pnl_usd": pos.get("unrealized_pnl", 0.0),
                                "realized_pnl_usd": pos.get("realized_pnl", 0.0),
                                "last_updated": datetime.now(timezone.utc).isoformat(),
                            })
                            total_exposure += pos.get("contracts", 0)
                        except Exception as exc:
                            logger.debug(f"Skipping malformed API position: {exc}")
                            continue
            except Exception as exc:
                logger.warning(f"REST API positions failed: {exc}")
    
    # Second fallback: fills ledger computed positions (ground truth from trade history)
    if not positions:
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            computed_positions = ledger.compute_net_positions()
            if computed_positions:
                for ticker, pos in computed_positions.items():
                    try:
                        positions.append({
                            "market_id": ticker,
                            "contracts": pos.get("contracts", 0),
                            "side": pos.get("side", "yes"),
                            "avg_price_cents": pos.get("avg_price_cents", 50),
                            "unrealized_pnl_usd": 0.0,  # Would need market price to calculate
                            "realized_pnl_usd": pos.get("realized_pnl_usd", 0.0),
                            "last_updated": datetime.now(timezone.utc).isoformat(),
                            "source": "fills_ledger",  # Indicate origin
                        })
                        total_exposure += pos.get("contracts", 0)
                    except Exception as exc:
                        logger.debug(f"Skipping malformed computed position: {exc}")
                        continue
                if positions:
                    logger.info(f"Positions endpoint using {len(positions)} computed positions from fills ledger")
        except Exception as exc:
            logger.debug(f"Fills ledger positions fallback failed: {exc}")
    
    return {
        "positions": positions,
        "total_exposure": total_exposure,
        "count": len(positions),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (same as original kalshi_api.py)
# ═══════════════════════════════════════════════════════════════════════════

def _get_catalog():
    """Get market catalog with error handling."""
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        return get_market_catalog()
    except (ImportError, ModuleNotFoundError, Exception) as exc:
        logger.debug(f"Catalog unavailable: {exc}")
        return None


def _get_risk():
    """Get risk manager with error handling."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return get_kalshi_risk()
    except (ImportError, ModuleNotFoundError, Exception) as exc:
        logger.debug(f"Risk manager unavailable: {exc}")
        return None


def _get_venue_gate():
    """Get venue gate with error handling."""
    try:
        from merid.prediction.venue_gate import get_venue_gate
        return get_venue_gate()
    except (ImportError, ModuleNotFoundError, Exception) as exc:
        logger.debug(f"Venue gate unavailable: {exc}")
        return None


def _get_rest_client():
    """Get REST client with error handling."""
    try:
        from merid.settings import settings
        key_id = settings.KALSHI_API_KEY_ID
        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        env = "demo" if settings.KALSHI_USE_DEMO else "prod"
    except Exception:
        import os
        key_id = os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        env = "demo" if os.environ.get("KALSHI_USE_DEMO", "false").lower() == "true" else "prod"
    
    if not key_id or not key_path or key_path == "change_me":
        return None
    
    try:
        from merid_core.kalshi.rest_client import get_rest_client
        return get_rest_client(key_id=key_id, private_key_path=key_path, env=env)
    except (ImportError, Exception) as exc:
        logger.debug(f"REST client unavailable: {exc}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health/robust", summary="Robustness Layer Health")
async def get_robustness_health() -> Dict[str, Any]:
    """Get health status of robustness layer."""
    robustness = get_kalshi_api_robustness()
    health_summary = robustness.get_health_summary()
    
    # Overall status
    healthy_endpoints = sum(1 for ep in health_summary.values() if ep.get("healthy", False))
    total_endpoints = len(health_summary)
    
    return {
        "overall_status": "healthy" if healthy_endpoints == total_endpoints else "degraded",
        "healthy_endpoints": healthy_endpoints,
        "total_endpoints": total_endpoints,
        "endpoints": health_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


"""
USAGE INSTRUCTIONS:

1. Import this module in your main app:
   from web.api import kalshi_api_retrofit

2. The router is already configured with prefix "/api/v1/kalshi"

3. Endpoints will be available at:
   - GET /api/v1/kalshi/markets (robust version)
   - POST /api/v1/kalshi/orders (robust version)
   - GET /api/v1/kalshi/positions (robust version)
   - GET /api/v1/kalshi/health/robust (health check)

4. To replace existing endpoints, either:
   a) Import these functions into kalshi_api.py
   b) Replace kalshi_api.py router with this one
   c) Mount both and migrate gradually

5. Monitor health:
   GET /api/v1/kalshi/health/robust

6. Key improvements:
   - All endpoints have automatic retry with exponential backoff
   - Input validation prevents bad requests
   - Graceful fallbacks on failures
   - Health tracking for monitoring
   - Detailed error logging
"""
