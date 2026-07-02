"""
Agent grid + signal path probe.

This diagnostic inspects the live agent grid to check if agents are operating
on the correct markets and have access to required data (spot, MD).
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from merid.prediction.agent_grid_15m import get_agent_grid
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from data.unified_spot_service import get_unified_spot_service
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


async def check_agent_grid_and_signals() -> Dict[str, Any]:
    """
    Check agent grid and signal path health.
    
    Returns:
        Dict with diagnostic results including:
        - Per-asset agent status
        - Whether agents see current market, spot, and MD
        - Last signal times
    """
    now_utc = datetime.now(timezone.utc)
    
    # Get agent grid (singleton from running server)
    try:
        agent_grid = get_agent_grid()
        grid_available = agent_grid is not None
    except Exception as e:
        agent_grid = None
        grid_available = False
    
    # Get market state store
    state_store = get_kalshi_market_state_store()
    all_md_states = state_store.get_all()
    
    # Get spot service
    spot_service = get_unified_spot_service()
    
    results = {
        "timestamp": now_utc.isoformat(),
        "agent_grid_available": grid_available,
        "assets": {},
        "summary": {
            "total_assets": len(ACTIVE_CRYPTO_ASSETS),
            "agents_loaded": 0,
            "agents_see_market": 0,
            "agents_see_spot": 0,
            "agents_see_md": 0,
            "agents_healthy": 0
        }
    }
    
    if not grid_available:
        results["summary"]["error"] = "Agent grid not available"
        return results
    
    for asset in ACTIVE_CRYPTO_ASSETS:
        agent_name = f"{asset.upper()}_15M"
        asset_result = {
            "agent_loaded": False,
            "agent_name": agent_name,
            "sees_market_id": None,
            "sees_spot": False,
            "sees_md": False,
            "last_signal_time": None,
            "market_id": None,
            "spot_price": None,
            "md_book_init": False,
            "md_age_seconds": None,
            "health_status": "UNKNOWN"
        }
        
        try:
            # Try to get the agent from the grid
            # LeanAgentGrid15m stores agents in _agents list, not get_agent method
            agent = None
            if hasattr(agent_grid, '_agents'):
                for a in agent_grid._agents:
                    if hasattr(a, 'config') and hasattr(a.config, 'name') and a.config.name == agent_name:
                        agent = a
                        break
            if agent:
                asset_result["agent_loaded"] = True
                results["summary"]["agents_loaded"] += 1
                
                # Check if agent sees a current market
                if hasattr(agent, 'current_market_id'):
                    asset_result["sees_market_id"] = agent.current_market_id
                    asset_result["market_id"] = agent.current_market_id
                    if agent.current_market_id:
                        results["summary"]["agents_see_market"] += 1
                
                # Check if agent has current spot
                if hasattr(agent, 'current_spot_price'):
                    asset_result["spot_price"] = agent.current_spot_price
                    if agent.current_spot_price:
                        asset_result["sees_spot"] = True
                        results["summary"]["agents_see_spot"] += 1
                
                # Check if agent sees healthy MD
                if hasattr(agent, 'md_healthy'):
                    asset_result["sees_md"] = agent.md_healthy
                    if agent.md_healthy:
                        results["summary"]["agents_see_md"] += 1
                
                # Check last signal time
                if hasattr(agent, 'last_signal_time'):
                    asset_result["last_signal_time"] = agent.last_signal_time
                
                # Determine overall health
                if asset_result["sees_market_id"] and asset_result["sees_spot"] and asset_result["sees_md"]:
                    asset_result["health_status"] = "HEALTHY"
                    results["summary"]["agents_healthy"] += 1
                elif asset_result["agent_loaded"]:
                    asset_result["health_status"] = "DEGRADED"
                else:
                    asset_result["health_status"] = "UNHEALTHY"
            else:
                asset_result["health_status"] = "NOT_LOADED"
        except Exception as e:
            asset_result["health_status"] = f"ERROR: {str(e)}"
        
        # Cross-check with market state store
        if asset_result["market_id"]:
            state = all_md_states.get(asset_result["market_id"])
            if state:
                asset_result["md_book_init"] = state.book_initialized if hasattr(state, 'book_initialized') else False
                
                last_update = None
                if hasattr(state, 'last_book_update_ts') and state.last_book_update_ts:
                    last_update = state.last_book_update_ts
                elif hasattr(state, 'last_update_ts') and state.last_update_ts:
                    last_update = state.last_update_ts
                
                if last_update:
                    asset_result["md_age_seconds"] = time.monotonic() - last_update
        
        # Cross-check with spot service
        try:
            spot_data = await spot_service.get_spot_price(asset)
            if spot_data and spot_data.get('price'):
                asset_result["spot_price"] = spot_data.get('price')
                if not asset_result["sees_spot"]:
                    asset_result["sees_spot"] = True
                    results["summary"]["agents_see_spot"] += 1
        except Exception as e:
            pass  # Spot check failed, but agent might still have cached spot
        
        results["assets"][asset] = asset_result
    
    return results


if __name__ == "__main__":
    # Run standalone for testing
    import json
    result = asyncio.run(check_agent_grid_and_signals())
    print(json.dumps(result, indent=2))
