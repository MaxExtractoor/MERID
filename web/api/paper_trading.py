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


@router.get("/portfolio/{user_id}/positions")
async def get_paper_positions(user_id: str):
    """Get all open positions for a user."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    positions = []
    for position in portfolio.positions.values():
        positions.append({
            "position_id": position.position_id,
            "asset": position.asset,
            "side": position.side,
            "size_usd": position.size_usd,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "leverage": position.leverage,
            "unrealized_pnl": position.unrealized_pnl,
            "opened_at": position.opened_at,
            "market_type": position.market_type,
            "market_id": position.market_id
        })
    
    return {"positions": positions, "count": len(positions)}


@router.get("/portfolio/{user_id}/orders")
async def get_paper_orders(user_id: str):
    """Get all pending orders for a user."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    orders = []
    for order in portfolio.orders.values():
        orders.append({
            "order_id": order.order_id,
            "asset": order.asset,
            "side": order.side,
            "order_type": order.order_type.value,
            "size_usd": order.size_usd,
            "price": order.price,
            "stop_price": order.stop_price,
            "status": order.status.value,
            "created_at": order.created_at,
            "market_type": order.market_type
        })
    
    return {"orders": orders, "count": len(orders)}


@router.post("/positions/{position_id}/close")
async def close_paper_position(position_id: str, user_id: str):
    """Close a paper trading position."""
    engine = get_paper_engine()
    
    # Find position by ID
    portfolio = engine.get_portfolio(user_id)
    position_key = None
    
    for key, position in portfolio.positions.items():
        if position.position_id == position_id:
            position_key = key
            break
    
    if not position_key:
        raise HTTPException(status_code=404, detail="Position not found")
    
    pnl = engine.close_position(user_id, position_key)
    
    return {
        "position_id": position_id,
        "realized_pnl": pnl,
        "closed_at": portfolio.positions.get(position_key).closed_at if position_key in portfolio.positions else None
    }


@router.post("/orders/{order_id}/cancel")
async def cancel_paper_order(order_id: str, user_id: str):
    """Cancel a pending paper trading order."""
    from trading.paper_trading import PaperOrderStatus
    
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    if order_id not in portfolio.orders:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order = portfolio.orders[order_id]
    order.status = PaperOrderStatus.CANCELLED
    del portfolio.orders[order_id]
    
    return {
        "order_id": order_id,
        "status": "cancelled"
    }


@router.get("/portfolio/{user_id}/stats")
async def get_paper_stats(user_id: str):
    """Get detailed portfolio statistics and performance analytics."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    # Calculate win rate
    total_closed = portfolio.winning_trades + portfolio.losing_trades
    win_rate = (portfolio.winning_trades / total_closed * 100) if total_closed > 0 else 0
    
    # Calculate average win/loss
    winning_pnl = sum(order.fill_price * order.filled_size for order in portfolio.trade_history 
                     if hasattr(order, 'fill_price') and order.fill_price and 
                     (order.fill_price - (order.price or 0)) > 0)
    losing_pnl = sum(order.fill_price * order.filled_size for order in portfolio.trade_history 
                    if hasattr(order, 'fill_price') and order.fill_price and 
                    (order.fill_price - (order.price or 0)) < 0)
    
    avg_win = winning_pnl / portfolio.winning_trades if portfolio.winning_trades > 0 else 0
    avg_loss = abs(losing_pnl) / portfolio.losing_trades if portfolio.losing_trades > 0 else 0
    
    # Calculate ROI
    roi = (portfolio.total_pnl / portfolio.starting_balance * 100) if portfolio.starting_balance > 0 else 0
    
    # Calculate max drawdown (simplified)
    max_balance = portfolio.starting_balance
    max_drawdown = 0
    for i, order in enumerate(portfolio.trade_history):
        if hasattr(order, 'fill_price') and order.fill_price:
            # Estimate balance at this point
            estimated_balance = portfolio.starting_balance + sum(
                o.fill_price * o.filled_size for o in portfolio.trade_history[:i+1]
                if hasattr(o, 'fill_price') and o.fill_price
            )
            max_balance = max(max_balance, estimated_balance)
            drawdown = (max_balance - estimated_balance) / max_balance * 100 if max_balance > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
    
    # Calculate Sharpe ratio (simplified - assumes daily returns)
    if len(portfolio.trade_history) > 1:
        returns = []
        for order in portfolio.trade_history:
            if hasattr(order, 'fill_price') and order.fill_price:
                ret = (order.fill_price - (order.price or order.fill_price)) / order.fill_price
                returns.append(ret)
        
        if returns:
            import statistics
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0
            sharpe_ratio = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
    
    return {
        "user_id": user_id,
        "portfolio_value": portfolio.current_balance,
        "total_pnl": portfolio.total_pnl,
        "roi_percent": round(roi, 2),
        "total_trades": portfolio.total_trades,
        "winning_trades": portfolio.winning_trades,
        "losing_trades": portfolio.losing_trades,
        "win_rate_percent": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
        "max_drawdown_percent": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "open_positions": len(portfolio.positions),
        "pending_orders": len(portfolio.orders)
    }


@router.get("/analytics/performance")
async def get_performance_analytics(user_id: str = "default"):
    """Get comprehensive performance analytics across all users or specific user."""
    engine = get_paper_engine()
    
    if user_id != "default":
        # Single user analytics
        return await get_paper_stats(user_id)
    
    # Aggregate analytics across all users
    all_stats = []
    for uid in engine.portfolios.keys():
        stats = await get_paper_stats(uid)
        all_stats.append(stats)
    
    if not all_stats:
        return {
            "total_users": 0,
            "aggregate_pnl": 0,
            "avg_roi": 0,
            "avg_win_rate": 0,
            "total_trades": 0
        }
    
    return {
        "total_users": len(all_stats),
        "aggregate_pnl": sum(s["total_pnl"] for s in all_stats),
        "avg_roi": sum(s["roi_percent"] for s in all_stats) / len(all_stats),
        "avg_win_rate": sum(s["win_rate_percent"] for s in all_stats) / len(all_stats),
        "total_trades": sum(s["total_trades"] for s in all_stats),
        "users": all_stats
    }


@router.get("/analytics/leaderboard")
async def get_leaderboard(metric: str = "roi", limit: int = 10):
    """Get leaderboard of top performers."""
    engine = get_paper_engine()
    
    leaderboard = []
    for user_id in engine.portfolios.keys():
        stats = await get_paper_stats(user_id)
        leaderboard.append(stats)
    
    # Sort by requested metric
    metric_map = {
        "roi": "roi_percent",
        "pnl": "total_pnl",
        "win_rate": "win_rate_percent",
        "sharpe": "sharpe_ratio",
        "trades": "total_trades"
    }
    
    sort_key = metric_map.get(metric, "roi_percent")
    leaderboard.sort(key=lambda x: x.get(sort_key, 0), reverse=True)
    
    return {
        "metric": metric,
        "leaderboard": leaderboard[:limit],
        "total_users": len(leaderboard)
    }


@router.get("/history/{user_id}")
async def get_trade_history(user_id: str, limit: int = 50):
    """Get trade history for a user."""
    engine = get_paper_engine()
    portfolio = engine.get_portfolio(user_id)
    
    trades = []
    for order in portfolio.trade_history[-limit:]:
        trades.append({
            "order_id": order.order_id,
            "asset": order.asset,
            "side": order.side,
            "order_type": order.order_type.value,
            "size_usd": order.size_usd,
            "fill_price": order.fill_price,
            "filled_size": order.filled_size,
            "leverage": order.leverage,
            "created_at": order.created_at,
            "filled_at": order.filled_at,
            "market_type": order.market_type
        })
    
    return {
        "trades": trades,
        "count": len(trades),
        "total_history": len(portfolio.trade_history)
    }


@router.get("/global-stats")
async def get_global_stats():
    """Get global paper trading statistics."""
    try:
        engine = get_paper_engine()
        stats = engine.get_global_stats()
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


# ── Convenience routes (no user_id) for frontend dashboard ────────────
# Frontend expects /api/v1/paper-trading/{portfolio,positions,orders}

paper_trading_convenience_router = APIRouter(
    prefix="/api/v1/paper-trading", tags=["paper_trading"]
)

_DEFAULT_USER = "default"


@paper_trading_convenience_router.get("/portfolio")
async def get_default_portfolio():
    """Get paper trading portfolio for default user (dashboard convenience)."""
    try:
        engine = get_paper_engine()
        portfolio = engine.get_portfolio(_DEFAULT_USER)
        total_closed = portfolio.winning_trades + portfolio.losing_trades
        win_rate = (portfolio.winning_trades / total_closed) if total_closed > 0 else 0.0
        return {
            "portfolio": {
                "equity": portfolio.current_balance,
                "cash": portfolio.current_balance - sum(
                    p.size_usd for p in portfolio.positions.values()
                ),
                "total_pnl": portfolio.total_pnl,
                "daily_pnl": 0.0,
                "positions_count": len(portfolio.positions),
                "domains": {},
                "win_rate": win_rate,
                "total_trades": portfolio.total_trades,
            },
            "pnl_history": [],
            "equity_curve": [],
        }
    except Exception as exc:
        logger.error(f"Default portfolio fetch failed: {exc}")
        return {
            "portfolio": {
                "equity": 100000.0, "cash": 100000.0, "total_pnl": 0.0,
                "daily_pnl": 0.0, "positions_count": 0, "domains": {},
                "win_rate": 0.0, "total_trades": 0,
            },
            "pnl_history": [], "equity_curve": [],
        }


@paper_trading_convenience_router.get("/positions")
async def get_default_positions():
    """Get paper trading positions for default user (dashboard convenience)."""
    try:
        engine = get_paper_engine()
        portfolio = engine.get_portfolio(_DEFAULT_USER)
        positions = []
        for pos in portfolio.positions.values():
            try:
                engine._calculate_position_pnl(pos)
            except Exception as exc:
                logger.debug(f"Position PnL calc error (ignored): {exc}")
            positions.append({
                "symbol": pos.asset,
                "domain": getattr(pos, "market_type", "crypto"),
                "side": pos.side,
                "size": pos.size_usd,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "pnl_pct": (pos.unrealized_pnl / pos.size_usd * 100) if pos.size_usd > 0 else 0,
                "opened_at": pos.opened_at,
            })
        return {"positions": positions}
    except Exception as exc:
        logger.error(f"Default positions fetch failed: {exc}")
        return {"positions": []}


@paper_trading_convenience_router.get("/orders")
async def get_default_orders():
    """Get paper trading orders for default user (dashboard convenience)."""
    try:
        engine = get_paper_engine()
        portfolio = engine.get_portfolio(_DEFAULT_USER)
        orders = []
        for order in portfolio.orders.values():
            orders.append({
                "id": order.order_id,
                "symbol": order.asset,
                "side": order.side,
                "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
                "size": order.size_usd,
                "price": order.price,
                "status": order.status.value if hasattr(order.status, "value") else str(order.status),
                "created_at": order.created_at,
                "filled_at": getattr(order, "filled_at", None),
            })
        return {"orders": orders}
    except Exception as exc:
        logger.error(f"Default orders fetch failed: {exc}")
        return {"orders": []}
