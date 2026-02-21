"""
Orders API Endpoint

Provides order management functionality including open orders, order history, and order placement.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException

from utils.logger import get_logger

logger = get_logger("web.api.orders_api")

router = APIRouter(prefix="/api/v1/trading/orders", tags=["orders"])


@router.options("/open")
async def options_open_orders():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/open")
async def get_open_orders() -> Dict[str, Any]:
    """
    Get all open (pending/partially filled) orders.
    
    Returns:
        {
            "orders": [
                {
                    "id": str,
                    "symbol": str,
                    "side": "BUY" | "SELL",
                    "type": "MARKET" | "LIMIT" | "STOP_LOSS",
                    "status": "PENDING" | "PARTIALLY_FILLED",
                    "size": float,
                    "filledSize": float,
                    "remainingSize": float,
                    "price": float,
                    "notional": float,
                    "createdAt": str (ISO timestamp)
                }
            ],
            "meta": {
                "total": int,
                "pending": int,
                "partiallyFilled": int,
                "totalNotional": float
            }
        }
    """
    try:
        from trading.paper_trading import get_paper_engine
        
        paper_engine = get_paper_engine()
        
        # Collect all pending orders from all portfolios
        orders = []
        for user_id, portfolio in paper_engine.portfolios.items():
            for order_id, order in portfolio.orders.items():
                # Only include pending or partially filled orders
                if order.status.value in ["PENDING", "PARTIALLY_FILLED"]:
                    filled_size = getattr(order, 'filled_size', 0) or 0
                    total_size = order.size_usd / (order.fill_price or 1) if hasattr(order, 'fill_price') and order.fill_price else order.size_usd
                    
                    orders.append({
                        "id": order.order_id,
                        "symbol": order.asset,
                        "side": order.side.upper(),
                        "type": order.order_type.value,
                        "status": order.status.value,
                        "size": total_size,
                        "filledSize": filled_size,
                        "remainingSize": total_size - filled_size,
                        "price": order.price or 0,
                        "notional": order.size_usd,
                        "createdAt": order.created_at if hasattr(order, 'created_at') else ""
                    })
        
        # Calculate meta
        meta = {
            "total": len(orders),
            "pending": sum(1 for o in orders if o["status"] == "PENDING"),
            "partiallyFilled": sum(1 for o in orders if o["status"] == "PARTIALLY_FILLED"),
            "totalNotional": sum(o["notional"] for o in orders)
        }
        
        return {
            "orders": orders,
            "meta": meta
        }
        
    except Exception as e:
        logger.error(f"Failed to get open orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))
