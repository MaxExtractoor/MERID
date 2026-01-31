"""
Trading API Endpoints.

Provides comprehensive trading functionality:
- Arbitrage opportunities
- Trade execution
- Perps trading
- Prediction markets
- Position management
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from trading.agents.arbitrage_agent import ArbitrageAgent, ArbitrageOpportunity
from trading.agents.execution_agent import ExecutionAgent, OrderSide, OrderType
from trading.agents.slippage_agent import SlippageAgent
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])
logger = get_logger("web.api.trading")

# Global agent instances
_arbitrage_agent: Optional[ArbitrageAgent] = None
_execution_agent: Optional[ExecutionAgent] = None
_slippage_agent: Optional[SlippageAgent] = None


def get_arbitrage_agent() -> ArbitrageAgent:
    """Get or create arbitrage agent singleton."""
    global _arbitrage_agent
    if _arbitrage_agent is None:
        _arbitrage_agent = ArbitrageAgent(
            min_spread_bps=10.0,
            max_slippage_bps=5.0,
            min_confidence=0.85
        )
    return _arbitrage_agent


def get_execution_agent() -> ExecutionAgent:
    """Get or create execution agent singleton."""
    global _execution_agent
    if _execution_agent is None:
        _execution_agent = ExecutionAgent(
            default_venue="hyperliquid",
            max_execution_time_ms=500.0
        )
    return _execution_agent


def get_slippage_agent() -> SlippageAgent:
    """Get or create slippage agent singleton."""
    global _slippage_agent
    if _slippage_agent is None:
        _slippage_agent = SlippageAgent(
            max_acceptable_slippage_bps=10.0,
            min_liquidity_ratio=0.1
        )
    return _slippage_agent


# Arbitrage Endpoints

@router.get("/arbitrage/scan")
async def scan_arbitrage_opportunities(
    venues: str = "binance,hyperliquid,dydx",
    assets: str = "BTC,ETH,SOL"
):
    """
    Scan for arbitrage opportunities across venues.
    
    Returns list of detected opportunities with profitability analysis.
    """
    agent = get_arbitrage_agent()
    
    venue_list = venues.split(",")
    asset_list = assets.split(",")
    
    opportunities = await agent.scan_cross_venue_arbitrage(venue_list, asset_list)
    
    return {
        "opportunities": [
            {
                "opportunity_id": opp.opportunity_id,
                "type": opp.type,
                "asset": opp.asset,
                "venue_buy": opp.venue_a,
                "venue_sell": opp.venue_b,
                "price_buy": opp.price_a,
                "price_sell": opp.price_b,
                "spread_bps": opp.spread_bps,
                "net_profit": opp.net_profit,
                "confidence": opp.confidence,
                "expires_at": opp.expires_at
            }
            for opp in opportunities
        ],
        "total_opportunities": len(opportunities)
    }


@router.get("/arbitrage/funding")
async def scan_funding_rate_arbitrage(
    venues: str = "hyperliquid,dydx,binance",
    assets: str = "BTC,ETH"
):
    """
    Scan for funding rate arbitrage opportunities in perp markets.
    """
    agent = get_arbitrage_agent()
    
    venue_list = venues.split(",")
    asset_list = assets.split(",")
    
    opportunities = await agent.scan_funding_rate_arbitrage(venue_list, asset_list)
    
    return {
        "opportunities": [
            {
                "opportunity_id": opp.opportunity_id,
                "asset": opp.asset,
                "venue_long": opp.venue_a,
                "venue_short": opp.venue_b,
                "funding_rate_diff_bps": opp.spread_bps,
                "expected_daily_profit": opp.expected_profit,
                "net_profit": opp.net_profit,
                "confidence": opp.confidence
            }
            for opp in opportunities
        ],
        "total_opportunities": len(opportunities)
    }


@router.post("/arbitrage/execute/{opportunity_id}")
async def execute_arbitrage(
    opportunity_id: str,
    auto_execute: bool = False
):
    """
    Execute arbitrage opportunity.
    
    If auto_execute=True, will automatically execute both legs.
    Otherwise, returns execution plan for manual confirmation.
    """
    agent = get_arbitrage_agent()
    
    # Find opportunity
    opportunity = agent.active_opportunities.get(opportunity_id)
    
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found or expired")
    
    execution = await agent.execute_arbitrage(opportunity, auto_execute=auto_execute)
    
    if not execution:
        raise HTTPException(status_code=400, detail="Execution failed - opportunity no longer valid")
    
    return {
        "execution_id": execution.opportunity_id,
        "status": "executed" if auto_execute else "ready",
        "leg_a_status": execution.leg_a_status,
        "leg_b_status": execution.leg_b_status,
        "actual_profit": execution.actual_profit,
        "execution_time_ms": execution.execution_time_ms
    }


@router.get("/arbitrage/stats")
async def get_arbitrage_stats():
    """Get arbitrage agent performance statistics."""
    agent = get_arbitrage_agent()
    return agent.get_performance_stats()


# Execution Endpoints

class OneClickTradeRequest(BaseModel):
    """One-click trade request."""
    asset: str = Field(..., description="Asset symbol (e.g., BTC, ETH)")
    side: str = Field(..., description="buy or sell")
    size_usd: float = Field(..., gt=0, description="Position size in USD")
    venue: Optional[str] = Field(None, description="Trading venue (default: hyperliquid)")


@router.post("/execute/one-click")
async def execute_one_click_trade(request: OneClickTradeRequest):
    """
    Execute one-click market order with lightning speed.
    
    Optimized for minimal latency (target: <500ms).
    """
    agent = get_execution_agent()
    
    side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
    
    order = await agent.execute_one_click_trade(
        asset=request.asset,
        side=side,
        size_usd=request.size_usd,
        venue=request.venue
    )
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "asset": order.asset,
        "side": order.side.value,
        "size": order.size,
        "fill_price": order.fill_price,
        "filled_size": order.filled_size,
        "execution_time_ms": order.execution_time_ms(),
        "fees": order.fees
    }


class LimitOrderRequest(BaseModel):
    """Limit order request."""
    asset: str
    side: str
    size_usd: float = Field(..., gt=0)
    limit_price: float = Field(..., gt=0)
    venue: Optional[str] = None


@router.post("/execute/limit")
async def execute_limit_order(request: LimitOrderRequest):
    """Execute limit order."""
    agent = get_execution_agent()
    
    side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
    
    order = await agent.execute_limit_order(
        asset=request.asset,
        side=side,
        size_usd=request.size_usd,
        limit_price=request.limit_price,
        venue=request.venue
    )
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "asset": order.asset,
        "side": order.side.value,
        "size": order.size,
        "limit_price": order.price,
        "filled_size": order.filled_size
    }


class StopLossRequest(BaseModel):
    """Stop loss order request."""
    asset: str
    side: str
    size_usd: float = Field(..., gt=0)
    stop_price: float = Field(..., gt=0)
    venue: Optional[str] = None


@router.post("/execute/stop-loss")
async def execute_stop_loss(request: StopLossRequest):
    """Execute stop loss order."""
    agent = get_execution_agent()
    
    side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
    
    order = await agent.execute_stop_loss(
        asset=request.asset,
        side=side,
        size_usd=request.size_usd,
        stop_price=request.stop_price,
        venue=request.venue
    )
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "asset": order.asset,
        "side": order.side.value,
        "size": order.size,
        "stop_price": order.stop_price
    }


@router.delete("/execute/cancel/{order_id}")
async def cancel_order(order_id: str):
    """Cancel pending order."""
    agent = get_execution_agent()
    
    success = await agent.cancel_order(order_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Order not found or already filled/cancelled")
    
    return {"status": "cancelled", "order_id": order_id}


@router.get("/execute/order/{order_id}")
async def get_order_status(order_id: str):
    """Get order status."""
    agent = get_execution_agent()
    
    order = agent.get_order_status(order_id)
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "asset": order.asset,
        "side": order.side.value,
        "size": order.size,
        "filled_size": order.filled_size,
        "fill_price": order.fill_price,
        "execution_time_ms": order.execution_time_ms()
    }


@router.get("/execute/stats")
async def get_execution_stats():
    """Get execution agent performance statistics."""
    agent = get_execution_agent()
    return agent.get_performance_stats()


# Slippage Analysis Endpoints

class SlippageAnalysisRequest(BaseModel):
    """Slippage analysis request."""
    venue: str
    asset: str
    order_size_usd: float = Field(..., gt=0)
    side: str
    urgency: str = Field("normal", description="urgent, normal, or patient")


@router.post("/slippage/analyze")
async def analyze_slippage(request: SlippageAnalysisRequest):
    """
    Analyze expected slippage and recommend execution strategy.
    """
    agent = get_slippage_agent()
    
    # Fetch real order book from exchange
    from data.live_price_feed import get_live_price_feed
    price_feed = get_live_price_feed()
    
    try:
        # Get exchange instance
        if 'binance' in price_feed.exchanges:
            exchange = price_feed.exchanges['binance']
            order_book = exchange.fetch_order_book(f"{request.asset}/USDT")
            
            # Extract bids and asks
            bids = [(bid[0], bid[1]) for bid in order_book['bids'][:10]]
            asks = [(ask[0], ask[1]) for ask in order_book['asks'][:10]]
        else:
            raise Exception("No exchange available")
    except Exception as exc:
        logger.error(f"Failed to fetch order book: {exc}")
        raise HTTPException(status_code=500, detail="Failed to fetch order book data")
    
    order_book = agent.analyze_order_book(
        venue=request.venue,
        asset=request.asset,
        bids=bids,
        asks=asks
    )
    
    strategy = agent.recommend_execution_strategy(
        order_book=order_book,
        order_size_usd=request.order_size_usd,
        side=request.side,
        urgency=request.urgency
    )
    
    return {
        "recommended_strategy": strategy.strategy_type,
        "order_size": strategy.order_size,
        "num_chunks": strategy.num_chunks,
        "time_interval_seconds": strategy.time_interval_seconds,
        "limit_price": strategy.limit_price,
        "expected_slippage_bps": strategy.expected_slippage_bps,
        "confidence": strategy.confidence,
        "order_book": {
            "mid_price": order_book.mid_price,
            "spread_bps": order_book.spread_bps
        }
    }


@router.get("/slippage/stats")
async def get_slippage_stats():
    """Get slippage agent performance statistics."""
    agent = get_slippage_agent()
    return agent.get_performance_stats()


# Perps Trading Endpoints

@router.get("/perps/positions")
async def get_perp_positions(venue: str = "hyperliquid"):
    """Get open perpetual positions from paper trading."""
    from trading.paper_trading import get_paper_engine
    from data.live_price_feed import get_live_price_feed
    
    paper_engine = get_paper_engine()
    price_feed = get_live_price_feed()
    
    # Aggregate all positions from all users
    all_positions = []
    for user_id, portfolio in paper_engine.portfolios.items():
        for pos_key, position in portfolio.positions.items():
            # Update with current price
            symbol = f"{position.asset}/USDT"
            price_data = price_feed.get_current_price(symbol)
            if price_data:
                position.current_price = price_data.price
            
            # Calculate P&L
            pnl = paper_engine._calculate_position_pnl(position)
            
            all_positions.append({
                "position_id": position.position_id,
                "user_id": user_id,
                "asset": position.asset,
                "side": position.side,
                "size_usd": position.size_usd,
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "leverage": position.leverage,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": (pnl / position.size_usd * 100) if position.size_usd > 0 else 0
            })
    
    return {
        "positions": all_positions,
        "total_positions": len(all_positions),
        "total_pnl": 0.0
    }


@router.post("/perps/open")
async def open_perp_position(
    asset: str,
    side: str,
    size_usd: float,
    leverage: int = 1,
    venue: str = "hyperliquid"
):
    """Open perpetual position."""
    # Use execution agent for order placement
    agent = get_execution_agent()
    
    order_side = OrderSide.BUY if side.lower() == "long" else OrderSide.SELL
    
    order = await agent.execute_one_click_trade(
        asset=asset,
        side=order_side,
        size_usd=size_usd * leverage,
        venue=venue
    )
    
    return {
        "position_id": order.order_id,
        "asset": asset,
        "side": side,
        "size_usd": size_usd,
        "leverage": leverage,
        "entry_price": order.fill_price,
        "status": order.status.value
    }


@router.post("/perps/close/{position_id}")
async def close_perp_position(position_id: str, user_id: str):
    """Close perpetual position."""
    from trading.paper_trading import get_paper_engine
    
    paper_engine = get_paper_engine()
    
    try:
        # Close position in paper trading
        result = paper_engine.close_position(user_id, position_id)
        
        if result:
            return {
                "position_id": position_id,
                "status": "closed",
                "realized_pnl": result.get('pnl', 0),
                "close_price": result.get('close_price', 0)
            }
        else:
            raise HTTPException(status_code=404, detail="Position not found")
    except Exception as exc:
        logger.error(f"Failed to close position: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    
    return {
        "position_id": position_id,
        "status": "closed",
        "pnl": 0.0
    }


# Prediction Markets Endpoints

@router.get("/markets/list")
async def list_prediction_markets(
    platform: str = "polymarket",
    category: Optional[str] = None
):
    """List available prediction markets from Polymarket."""
    try:
        from trading.polymarket_adapter import PolymarketAdapter
        
        adapter = PolymarketAdapter()
        markets = adapter.fetch_markets(category=category, limit=limit)
        
        return {
            "markets": markets,
            "total_markets": len(markets)
        }
    except Exception as exc:
        logger.error(f"Failed to fetch markets: {exc}")
        return {
            "markets": [],
            "total_markets": 0
        }


@router.post("/markets/trade")
async def trade_prediction_market(
    market_id: str,
    outcome: str,
    size_usd: float,
    platform: str = "polymarket"
):
    """Execute prediction market trade via paper trading."""
    from trading.paper_trading import get_paper_engine
    import uuid
    
    paper_engine = get_paper_engine()
    
    try:
        # Execute as paper trade
        order_id = str(uuid.uuid4())
        
        # For prediction markets, treat as binary outcome trade
        result = paper_engine.place_order(
            user_id="default_user",
            asset=f"MARKET_{market_id}",
            side="long" if outcome == "yes" else "short",
            size_usd=size_usd,
            order_type="market",
            leverage=1,
            market_type="prediction"
        )
        
        return {
            "trade_id": result['order_id'],
            "market_id": market_id,
            "outcome": outcome,
            "size_usd": size_usd,
            "status": "pending"
        }
    except Exception as exc:
        logger.error(f"Failed to execute market trade: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/markets/positions")
async def get_market_positions(platform: str = "polymarket", user_id: str = "default_user"):
    """Get prediction market positions from paper trading."""
    from trading.paper_trading import get_paper_engine
    
    paper_engine = get_paper_engine()
    
    # Get positions for prediction markets
    positions = []
    if user_id in paper_engine.portfolios:
        portfolio = paper_engine.portfolios[user_id]
        for pos_key, position in portfolio.positions.items():
            if position.market_type == "prediction":
                pnl = paper_engine._calculate_position_pnl(position)
                positions.append({
                    "position_id": position.position_id,
                    "market_id": position.asset.replace("MARKET_", ""),
                    "outcome": "yes" if position.side == "long" else "no",
                    "amount": position.size_usd,
                    "entry_price": position.entry_price,
                    "current_price": position.current_price,
                    "unrealized_pnl": pnl
                })
    
    return {
        "positions": positions,
        "total_positions": len(positions),
        "total_value": 0.0
    }


# Dashboard Integration Endpoints

@router.get("/execution/status")
async def get_execution_status():
    """Get execution engine status for dashboard."""
    agent = get_execution_agent()
    return {
        "status": "ready",
        "open_orders": len(agent.pending_orders) if hasattr(agent, 'pending_orders') else 0,
        "filled_today": getattr(agent, 'filled_today', 0),
        "avg_latency_ms": getattr(agent, 'avg_latency_ms', 0),
        "success_rate": getattr(agent, 'success_rate', 1.0)
    }


@router.get("/portfolio/summary")
async def get_portfolio_summary():
    """Get portfolio summary for dashboard."""
    from trading.paper_trading import get_paper_engine
    
    paper_engine = get_paper_engine()
    
    total_value = 100000.0  # Base capital
    unrealized_pnl = 0.0
    positions = []
    
    for user_id, portfolio in paper_engine.portfolios.items():
        for pos_key, position in portfolio.positions.items():
            pnl = paper_engine._calculate_position_pnl(position)
            unrealized_pnl += pnl
            positions.append({
                "asset": position.asset,
                "side": position.side,
                "size": position.size_usd,
                "pnl": pnl
            })
    
    return {
        "total_value": total_value + unrealized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "positions": positions,
        "position_count": len(positions)
    }


@router.get("/backtest/results")
async def get_backtest_results():
    """Get backtest results for dashboard."""
    # Return empty results - backtests are run on demand
    return {
        "results": [],
        "count": 0,
        "message": "No backtest results available. Run a backtest to see results."
    }


@router.get("/paper/status")
async def get_paper_trading_status():
    """Get paper trading status for dashboard."""
    from trading.paper_trading import get_paper_engine
    
    paper_engine = get_paper_engine()
    
    trades_today = 0
    volume_today = 0.0
    pnl_today = 0.0
    
    for user_id, portfolio in paper_engine.portfolios.items():
        trades_today += len(portfolio.trade_history)
        for trade in portfolio.trade_history:
            volume_today += trade.get('size_usd', 0)
            pnl_today += trade.get('pnl', 0)
    
    return {
        "trades_today": trades_today,
        "volume_today": volume_today,
        "pnl_today": pnl_today,
        "active_positions": sum(len(p.positions) for p in paper_engine.portfolios.values())
    }


@router.get("/mode/set")
async def set_trading_mode(mode: str = "paper"):
    """Set trading mode (paper/hybrid/live).

    Frontend legacy endpoint that now proxies to the TradingModeController so
    the system is explicitly locked to paper trading when requested.
    """
    from trading.mode_controller import get_trading_mode_controller

    valid_modes = ["paper", "hybrid", "live"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid_modes}")

    controller = get_trading_mode_controller()

    if mode != "paper":
        # Keep MERID in paper mode but inform caller why
        return {
            "status": "warning",
            "mode": controller.mode_name,
            "message": f"{mode} mode not enabled. Staying in {controller.mode_name} mode."
        }

    controller.set_mode("paper", changed_by="web.api.trading", reason="Dashboard requested paper mode")
    status = controller.get_status()

    return {
        "status": "success",
        "mode": status["mode"],
        "message": "Trading mode locked to paper",
        "details": {
            "live_approval_required": status["live_approval_required"],
            "spectator_trades": status["spectator_trades_count"],
        }
    }
