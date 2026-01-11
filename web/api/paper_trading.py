"""
Paper Trading API Endpoints.

Provides API for simulated trading without real capital.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from trading.paper_trading import get_paper_engine, PaperOrderType
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/paper", tags=["paper_trading"])
logger = get_logger("web.api.paper_trading")


class PaperOrderRequest(BaseModel):
    """Paper order request."""
    user_id: str = Field(..., description="User ID")
    asset: str = Field(..., description="Asset symbol")
    side: str = Field(..., description="long/short for perps, yes/no for predictions")
    size_usd: float = Field(..., gt=0, description="Position size in USD")
    order_type: str = Field("market", description="market, limit, or stop_loss")
    price: Optional[float] = Field(None, description="Limit price (for limit orders)")
    stop_price: Optional[float] = Field(None, description="Stop price (for stop orders)")
    leverage: int = Field(1, ge=1, le=20, description="Leverage (1-20x)")
    market_type: str = Field("perp", description="perp or prediction")
    market_id: Optional[str] = Field(None, description="Market ID for predictions")


@router.post("/orders/place")
async def place_paper_order(request: PaperOrderRequest):
    """
    Place paper trading order.
    
    Simulates order execution without real capital.
    """
    engine = get_paper_engine()
    
    try:
        order = engine.place_order(
            user_id=request.user_id,
            asset=request.asset,
            side=request.side,
            size_usd=request.size_usd,
            order_type=request.order_type,
            price=request.price,
            stop_price=request.stop_price,
            leverage=request.leverage,
            market_type=request.market_type,
            market_id=request.market_id
        )
        
        return {
            "order_id": order.order_id,
            "status": order.status.value,
            "asset": order.asset,
            "side": order.side,
            "size_usd": order.size_usd,
            "fill_price": order.fill_price,
            "filled_size": order.filled_size,
            "leverage": order.leverage,
            "market_type": order.market_type,
            "created_at": order.created_at,
            "filled_at": order.filled_at
        }
    
    except Exception as exc:
        logger.error(f"Paper order placement failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/portfolio/{user_id}")
async def get_paper_portfolio(user_id: str):
    """Get paper trading portfolio."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    return {
        "user_id": portfolio.user_id,
        "starting_balance": portfolio.starting_balance,
        "current_balance": portfolio.current_balance,
        "total_pnl": portfolio.total_pnl,
        "total_trades": portfolio.total_trades,
        "winning_trades": portfolio.winning_trades,
        "losing_trades": portfolio.losing_trades,
        "open_positions": len(portfolio.positions),
        "pending_orders": len(portfolio.orders)
    }


@router.get("/portfolio/{user_id}/stats")
async def get_paper_stats(user_id: str):
    """Get detailed portfolio statistics."""
    engine = get_paper_engine()
    
    try:
        stats = engine.get_portfolio_stats(user_id)
        return stats
    
    except Exception as exc:
        logger.error(f"Failed to get portfolio stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/{user_id}/positions")
async def get_paper_positions(user_id: str):
    """Get open paper positions."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    positions = []
    for pos in portfolio.positions.values():
        # Update P&L
        engine._calculate_position_pnl(pos)
        
        positions.append({
            "position_id": pos.position_id,
            "asset": pos.asset,
            "side": pos.side,
            "size_usd": pos.size_usd,
            "entry_price": pos.entry_price,
            "current_price": pos.current_price,
            "leverage": pos.leverage,
            "unrealized_pnl": pos.unrealized_pnl,
            "unrealized_pnl_pct": (pos.unrealized_pnl / pos.size_usd * 100) if pos.size_usd > 0 else 0,
            "market_type": pos.market_type,
            "opened_at": pos.opened_at
        })
    
    return {
        "positions": positions,
        "total_positions": len(positions)
    }


@router.post("/positions/close")
async def close_paper_position(user_id: str, position_key: str):
    """Close paper position."""
    engine = get_paper_engine()
    
    try:
        pnl = engine.close_position(user_id, position_key)
        
        if pnl is None:
            raise HTTPException(status_code=404, detail="Position not found")
        
        return {
            "status": "closed",
            "position_key": position_key,
            "realized_pnl": pnl
        }
    
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to close position: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/{user_id}/history")
async def get_trade_history(user_id: str, limit: int = 50):
    """Get paper trade history."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    # Get recent trades
    recent_trades = portfolio.trade_history[-limit:]
    
    trades = []
    for order in recent_trades:
        trades.append({
            "order_id": order.order_id,
            "asset": order.asset,
            "side": order.side,
            "size_usd": order.size_usd,
            "fill_price": order.fill_price,
            "leverage": order.leverage,
            "market_type": order.market_type,
            "status": order.status.value,
            "created_at": order.created_at,
            "filled_at": order.filled_at
        })
    
    return {
        "trades": trades,
        "total_trades": len(trades)
    }


@router.post("/portfolio/{user_id}/reset")
async def reset_paper_portfolio(user_id: str):
    """Reset paper portfolio to starting balance."""
    engine = get_paper_engine()
    
    try:
        engine.reset_portfolio(user_id)
        
        return {
            "status": "reset",
            "user_id": user_id,
            "message": "Portfolio reset to starting balance"
        }
    
    except Exception as exc:
        logger.error(f"Failed to reset portfolio: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prices/update")
async def update_paper_prices(prices: dict):
    """
    Update current market prices for paper trading.
    
    Used to simulate real-time price updates.
    """
    engine = get_paper_engine()
    
    try:
        engine.update_prices(prices)
        
        return {
            "status": "updated",
            "prices": prices
        }
    
    except Exception as exc:
        logger.error(f"Failed to update prices: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
