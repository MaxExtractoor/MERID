"""
Kelly-VIX SSE Endpoints - FastAPI Server-Sent Events

SSE endpoints for real-time Kelly-VIX backtest results streaming.
"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any, Optional
import asyncio
import json
import logging
import os

from .kelly_vix_state import get_current_kelly_vix_state, get_kelly_vix_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Event bus placeholder - should be injected from main app
event_bus = None

async def kelly_vix_sse_gen(request: Request):
    """
    Server-Sent Events generator for Kelly-VIX backtest results.
    
    Args:
        request: FastAPI request object
        
    Yields:
        SSE formatted data strings
    """
    # Get event bus (should be injected from app)
    global event_bus
    if event_bus is None:
        # Fallback to polling if event bus not available
        logger.warning("Event bus not available, using polling fallback")
        async for data in kelly_vix_polling_gen(request):
            yield data
        return
    
    # Subscribe to event bus
    queue = event_bus.subscribe_async()
    
    try:
        # Send initial state if available
        current_state = get_current_kelly_vix_state()
        if current_state:
            initial_data = {
                "type": "kelly_vix_backtest",
                "payload": current_state.to_dict(),
                "ts": current_state.timestamp,
                "source": "initial_state"
            }
            yield f"data: {json.dumps(initial_data)}\n\n"
        
        # Stream events
        while True:
            if await request.is_disconnected():
                break
            
            try:
                # Wait for event with timeout
                ev = await asyncio.wait_for(queue.get(), timeout=30.0)
                
                # Filter for Kelly-VIX events
                if ev.type == "kelly_vix_backtest":
                    data = {
                        "type": ev.type,
                        "payload": ev.payload,
                        "ts": ev.ts,
                        "source": ev.source
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                heartbeat = {
                    "type": "heartbeat",
                    "ts": asyncio.get_event_loop().time(),
                    "source": "kelly_vix_sse"
                }
                yield f"data: {json.dumps(heartbeat)}\n\n"
                
    except Exception as e:
        logger.error(f"Error in Kelly-VIX SSE generator: {e}")
        error_data = {
            "type": "error",
            "error": str(e),
            "ts": asyncio.get_event_loop().time(),
            "source": "kelly_vix_sse"
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        
    finally:
        # Unsubscribe from event bus
        if event_bus:
            event_bus.unsubscribe_async(queue)

async def kelly_vix_polling_gen(request: Request):
    """
    Polling fallback for Kelly-VIX backtest results when event bus is not available.
    
    Args:
        request: FastAPI request object
        
    Yields:
        SSE formatted data strings
    """
    manager = get_kelly_vix_manager()
    last_state_id = None
    
    while True:
        if await request.is_disconnected():
            break
        
        try:
            current_state = manager.get_current_state()
            
            if current_state:
                state_id = id(current_state)
                
                # Send state if it's new
                if state_id != last_state_id:
                    data = {
                        "type": "kelly_vix_backtest",
                        "payload": current_state.to_dict(),
                        "ts": current_state.timestamp,
                        "source": "polling"
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    last_state_id = state_id
                else:
                    # Send heartbeat
                    heartbeat = {
                        "type": "heartbeat",
                        "ts": asyncio.get_event_loop().time(),
                        "source": "kelly_vix_polling"
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
            
            # Wait before next poll
            await asyncio.sleep(2.0)
            
        except Exception as e:
            logger.error(f"Error in Kelly-VIX polling generator: {e}")
            await asyncio.sleep(5.0)

@router.get("/sse/kelly-vix")
async def kelly_vix_sse(request: Request):
    """
    Server-Sent Events endpoint for Kelly-VIX backtest results.
    
    Args:
        request: FastAPI request object
        
    Returns:
        StreamingResponse with SSE data
    """
    return StreamingResponse(
        kelly_vix_sse_gen(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )

@router.get("/kelly-vix/current")
def get_kelly_vix_current() -> Dict[str, Any]:
    """
    Get current Kelly-VIX backtest state via REST API.
    
    Returns:
        Current backtest state or error
    """
    current_state = get_current_kelly_vix_state()
    
    if current_state is None:
        return {
            "error": "No Kelly-VIX backtest data available",
            "available": False
        }
    
    return {
        "available": True,
        "data": current_state.to_dict()
    }

@router.get("/kelly-vix/status")
def get_kelly_vix_status() -> Dict[str, Any]:
    """
    Get Kelly-VIX backtest system status.
    
    Returns:
        System status information
    """
    manager = get_kelly_vix_manager()
    summary = manager.get_summary()
    
    # Add SSE status
    summary["sse_available"] = event_bus is not None
    
    # Add health status
    if summary["available"]:
        state = manager.get_current_state()
        if state:
            if state.total_return > 0.1:
                health = "excellent"
            elif state.total_return > 0.05:
                health = "good"
            elif state.total_return > 0:
                health = "fair"
            else:
                health = "poor"
            
            summary["health"] = health
            summary["performance"] = {
                "total_return": state.total_return,
                "sharpe_ratio": state.sharpe_ratio,
                "max_drawdown": state.max_drawdown,
                "num_trades": state.num_trades
            }
    else:
        summary["health"] = "unavailable"
    
    return summary

@router.get("/kelly-vix/history")
def get_kelly_vix_history(limit: int = 10) -> Dict[str, Any]:
    """
    Get recent Kelly-VIX backtest history.
    
    Args:
        limit: Number of recent backtests to return
        
    Returns:
        Recent backtest history
    """
    manager = get_kelly_vix_manager()
    history = manager.get_history(limit)
    
    return {
        "limit": limit,
        "count": len(history),
        "backtests": [state.to_dict() for state in history]
    }

@router.post("/kelly-vix/trigger")
def trigger_kelly_vix_backtest(market_ticker: str = "KXBTC15M-EXAMPLE",
                              base_kelly: float = 0.15,
                              vix_lookback: int = 252) -> Dict[str, Any]:
    """
    Trigger a new Kelly-VIX backtest (for testing/demo purposes).
    
    Args:
        market_ticker: Market ticker to backtest
        base_kelly: Base Kelly fraction
        vix_lookback: VIX lookback period
        
    Returns:
        Trigger result
    """
    try:
        # Generate sample backtest data
        import numpy as np
        import time
        import uuid
        
        np.random.seed(42)
        n_trades = 100
        equity = (1 + np.random.normal(0.001, 0.02, n_trades)).cumprod().tolist()
        
        # Calculate metrics
        total_return = (equity[-1] / equity[0]) - 1
        returns = np.diff(equity) / equity[:-1]
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(365 * 24 * 4) if len(returns) > 1 and returns.std() > 0 else 0.0
        
        peak = np.maximum.accumulate(equity)
        drawdown = (np.array(equity) - peak) / peak
        max_drawdown = drawdown.min()
        
        # Create state
        from .kelly_vix_state import KellyVixBacktestState, update_kelly_vix_state
        
        state = KellyVixBacktestState(
            equity_curve=equity,
            base_kelly=base_kelly,
            hybrid_fraction=base_kelly * 0.8,  # Simulated hybrid fraction
            final_capital=equity[-1],
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=0.55,  # Simulated
            num_trades=n_trades,
            backtest_id=str(uuid.uuid4()),
            market_ticker=market_ticker
        )
        
        # Update state
        update_kelly_vix_state(state)
        
        # Publish to event bus if available
        if event_bus:
            from ..core.event_bus import KalshiEvent
            
            event = KalshiEvent(
                type="kelly_vix_backtest",
                payload=state.to_event()["payload"],
                ts=state.timestamp,
                source="kelly_vix_trigger",
            )
            
            event_bus.publish(event)
        
        return {
            "success": True,
            "message": "Kelly-VIX backtest triggered successfully",
            "backtest_id": state.backtest_id,
            "market_ticker": market_ticker,
            "total_return": total_return,
            "sharpe_ratio": sharpe_ratio
        }
        
    except Exception as e:
        logger.error(f"Error triggering Kelly-VIX backtest: {e}")
        return {
            "success": False,
            "error": str(e)
        }

# Example Streamlit client code:
"""
import streamlit as st
import requests
import json
import time

def display_kelly_vix_sse():
    st.subheader("Kelly-VIX Backtest Results (Real-time)")
    
    # Create placeholder for updates
    placeholder = st.empty()
    
    # SSE client simulation
    api_base = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", f"http://localhost:{os.getenv('MERID_PORT', '8011')}"))
    
    try:
        response = requests.get(f"{api_base}/sse/kelly-vix", stream=True, timeout=10)
        
        if response.status_code == 200:
            st.success("Connected to Kelly-VIX SSE stream")
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])  # Remove 'data: ' prefix
                            
                            if data.get('type') == 'kelly_vix_backtest':
                                payload = data.get('payload', {})
                                
                                with placeholder.container():
                                    st.write(f"**Backtest ID:** {payload.get('backtest_id', 'N/A')}")
                                    st.write(f"**Market:** {payload.get('market_ticker', 'N/A')}")
                                    st.write(f"**Total Return:** {payload.get('total_return', 0):.2%}")
                                    st.write(f"**Sharpe Ratio:** {payload.get('sharpe_ratio', 0):.2f}")
                                    st.write(f"**Max Drawdown:** {payload.get('max_drawdown', 0):.2%}")
                                    st.write(f"**Trades:** {payload.get('num_trades', 0)}")
                                    st.write(f"**Last Updated:** {time.strftime('%H:%M:%S', time.localtime(data.get('ts', time.time())))}")
                                    
                                    # Plot equity curve if available
                                    equity = payload.get('equity_curve', [])
                                    if equity:
                                        st.line_chart(equity)
                            
                            elif data.get('type') == 'heartbeat':
                                st.write(f"💓 Heartbeat - {time.strftime('%H:%M:%S')}")
                            
                            elif data.get('type') == 'error':
                                st.error(f"Error: {data.get('error', 'Unknown error')}")
                                
                        except json.JSONDecodeError:
                            st.write(f"Raw data: {line}")
                            
        else:
            st.error(f"Failed to connect: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        st.error(f"SSE connection error: {e}")

# In Streamlit app:
# display_kelly_vix_sse()
"""
