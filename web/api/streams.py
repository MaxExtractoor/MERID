"""
WebSocket Streams API.

Provides real-time data streams:
- Live price feeds
- Trade execution stream
- Agent decision stream
- Simulation process stream
- Position updates
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from utils.logger import get_logger
from data.live_price_feed import get_live_price_feed

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = get_logger("web.api.streams")

# Active WebSocket connections
_price_connections: Set[WebSocket] = set()
_trade_connections: Set[WebSocket] = set()
_agent_connections: Set[WebSocket] = set()
_simulation_connections: Set[WebSocket] = set()
_position_connections: Set[WebSocket] = set()


# Price Stream

@router.websocket("/prices")
async def price_stream(websocket: WebSocket):
    """
    Live cryptocurrency price stream.
    
    Sends real-time price updates for major cryptocurrencies.
    """
    await websocket.accept()
    _price_connections.add(websocket)
    
    logger.info("Price stream client connected")
    
    # Get live price feed
    price_feed = get_live_price_feed()
    
    try:
        while True:
            # Get real prices from live feed
            all_prices = price_feed.get_all_prices()
            
            if all_prices:
                prices = {
                    "timestamp": time.time(),
                    "prices": {},
                    "changes_24h": {}
                }
                
                for symbol, price_data in all_prices.items():
                    # Extract base symbol (e.g., BTC from BTC/USDT)
                    base = symbol.split('/')[0]
                    prices["prices"][base] = price_data.price
                    prices["changes_24h"][base] = price_data.change_24h_pct
                
                await websocket.send_json(prices)
            
            await asyncio.sleep(1)  # Update every second
            
    except WebSocketDisconnect:
        _price_connections.discard(websocket)
        logger.info("Price stream client disconnected")
    except Exception as exc:
        logger.error("Price stream error: %s", exc)
        _price_connections.discard(websocket)


# Trade Execution Stream

@router.websocket("/trades")
async def trade_stream(websocket: WebSocket):
    """
    Live trade execution stream.
    
    Sends real-time trade execution updates from ExecutionAgent.
    """
    await websocket.accept()
    _trade_connections.add(websocket)
    
    logger.info("Trade stream client connected")
    
    from trading.agents.execution_agent import get_execution_agent
    execution_agent = get_execution_agent()
    
    try:
        while True:
            # Get recent trades from execution agent
            recent_trades = execution_agent.get_recent_trades(limit=1)
            
            if recent_trades:
                trade = recent_trades[-1]
                await websocket.send_json({
                    "timestamp": time.time(),
                    "trade_id": trade.get('order_id', f"trade_{int(time.time())}"),
                    "asset": trade.get('asset', 'BTC'),
                    "side": trade.get('side', 'long'),
                    "size_usd": trade.get('size_usd', 0),
                    "entry_price": trade.get('fill_price', 0),
                    "status": trade.get('status', 'filled')
                })
            
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        _trade_connections.discard(websocket)
        logger.info("Trade stream client disconnected")
    except Exception as exc:
        logger.error("Trade stream error: %s", exc)
        _trade_connections.discard(websocket)


# Agent Decision Stream

@router.websocket("/agents")
async def agent_stream(websocket: WebSocket):
    """
    Agent decision stream.
    
    Sends real-time agent decisions from AgentOrchestrator.
    """
    await websocket.accept()
    _agent_connections.add(websocket)
    
    logger.info("Agent stream client connected")
    
    from core.agent_orchestrator import get_agent_orchestrator
    orchestrator = get_agent_orchestrator()
    
    try:
        while True:
            # Get recent decisions from orchestrator
            decisions = orchestrator.get_recent_decisions(limit=5)
            
            if decisions:
                # Send most recent decision
                decision = decisions[-1]
                await websocket.send_json({
                    "timestamp": decision.timestamp.isoformat(),
                    "agent_id": f"{decision.agent_role.value}-agent",
                    "agent_type": decision.agent_role.value,
                    "decision": decision.decision_type,
                    "confidence": decision.confidence,
                    "reasoning": decision.reasoning,
                    "data": decision.data
                })
            
            await asyncio.sleep(3)
            
    except WebSocketDisconnect:
        _agent_connections.discard(websocket)
        logger.info("Agent stream client disconnected")
    except Exception as exc:
        logger.error("Agent stream error: %s", exc)
        _agent_connections.discard(websocket)


# Simulation Process Stream

@router.websocket("/simulation")
async def simulation_stream(websocket: WebSocket):
    """
    Real-time simulation stream.
    
    Broadcasts:
    - News being processed
    - Agent analysis and votes
    - Simulation consensus results
    - Final decisions
    """
    await websocket.accept()
    _simulation_connections.add(websocket)
    
    logger.info("Simulation stream client connected")
    
    from core.agent_orchestrator import get_agent_orchestrator
    orchestrator = get_agent_orchestrator()
    
    try:
        while True:
            # Get consensus history
            consensus_history = orchestrator.get_consensus_history(limit=1)
            
            if consensus_history:
                result = consensus_history[-1]
                await websocket.send_json({
                    "timestamp": result.timestamp.isoformat(),
                    "block_index": len(orchestrator.consensus_history),
                    "approved": result.approved,
                    "confidence": result.confidence,
                    "votes_for": result.votes_for,
                    "votes_against": result.votes_against,
                    "participating_agents": [a.value for a in result.participating_agents]
                })
            
            await asyncio.sleep(5)
            
    except WebSocketDisconnect:
        _simulation_connections.discard(websocket)
        logger.info("Simulation stream client disconnected")
    except Exception as exc:
        logger.error("Simulation stream error: %s", exc)
        _simulation_connections.discard(websocket)


# Position Updates Stream

@router.websocket("/positions")
async def position_stream(websocket: WebSocket):
    """
    Position updates stream.
    
    Sends real-time position and P&L updates from paper trading.
    """
    await websocket.accept()
    _position_connections.add(websocket)
    
    logger.info("Position stream client connected")
    
    from trading.paper_trading import get_paper_engine
    from data.live_price_feed import get_live_price_feed
    
    paper_engine = get_paper_engine()
    price_feed = get_live_price_feed()
    
    try:
        while True:
            # Get all portfolios and aggregate positions
            all_positions = []
            total_pnl = 0.0
            
            for user_id, portfolio in paper_engine.portfolios.items():
                for pos_key, position in portfolio.positions.items():
                    # Update with current price
                    symbol = f"{position.asset}/USDT"
                    price_data = price_feed.get_current_price(symbol)
                    if price_data:
                        position.current_price = price_data.price
                    
                    # Calculate P&L
                    pnl = paper_engine._calculate_position_pnl(position)
                    total_pnl += pnl
                    
                    all_positions.append({
                        "position_id": position.position_id,
                        "asset": position.asset,
                        "side": position.side,
                        "size_usd": position.size_usd,
                        "entry_price": position.entry_price,
                        "current_price": position.current_price,
                        "unrealized_pnl": pnl,
                        "unrealized_pnl_pct": (pnl / position.size_usd * 100) if position.size_usd > 0 else 0
                    })
            
            await websocket.send_json({
                "timestamp": time.time(),
                "total_positions": len(all_positions),
                "total_pnl": total_pnl,
                "positions": all_positions
            })
            
            await asyncio.sleep(2)
            
    except WebSocketDisconnect:
        _position_connections.discard(websocket)
        logger.info("Position stream client disconnected")
    except Exception as exc:
        logger.error("Position stream error: %s", exc)
        _position_connections.discard(websocket)


# Broadcast helpers (for use by other modules)

async def broadcast_trade(trade_data: Dict):
    """Broadcast trade execution to all connected clients."""
    disconnected = set()
    
    for websocket in _trade_connections:
        try:
            await websocket.send_json(trade_data)
        except Exception:
            disconnected.add(websocket)
    
    _trade_connections.difference_update(disconnected)


async def broadcast_agent_decision(decision_data: Dict):
    """Broadcast agent decision to all connected clients."""
    disconnected = set()
    
    for websocket in _agent_connections:
        try:
            await websocket.send_json(decision_data)
        except Exception:
            disconnected.add(websocket)
    
    _agent_connections.difference_update(disconnected)


async def broadcast_simulation_update(update_data: Dict):
    """Broadcast simulation update to all connected clients."""
    disconnected = set()
    
    for websocket in _simulation_connections:
        try:
            await websocket.send_json(update_data)
        except Exception:
            disconnected.add(websocket)
    
    _simulation_connections.difference_update(disconnected)


async def broadcast_position_update(position_data: Dict):
    """Broadcast position update to all connected clients."""
    disconnected = set()
    
    for websocket in _position_connections:
        try:
            await websocket.send_json(position_data)
        except Exception:
            disconnected.add(websocket)
    
    _position_connections.difference_update(disconnected)
