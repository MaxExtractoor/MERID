# merid/kalshi/agent_mode_router.py
"""Router for agent opinions based on mode configuration."""

from typing import Optional
from utils.logger import get_logger
from config.agent_modes import (
    get_agent_mode_config, 
    should_route_to_paper, 
    should_route_to_live,
    get_agent_size_multiplier,
    is_agent_enabled
)
from merid.kalshi.paper_portfolio import get_kalshi_paper_portfolio

logger = get_logger("merid.kalshi.agent_mode_router")


class AgentModeRouter:
    """Routes agent opinions to shadow/paper/live based on configuration."""
    
    def __init__(self):
        self.paper_portfolio = get_kalshi_paper_portfolio()
    
    def route_opinion(self, agent_id: str, market_id: str, side: str, 
                     size_contracts: int, confidence: float) -> bool:
        """Route an agent opinion based on its mode configuration."""
        # Check if agent is enabled
        if not is_agent_enabled(agent_id):
            logger.info(f"Agent {agent_id} is disabled, opinion ignored")
            return False
        
        # Get mode configuration
        config = get_agent_mode_config(agent_id)
        
        # Apply size multiplier
        adjusted_contracts = int(size_contracts * get_agent_size_multiplier(agent_id))
        if adjusted_contracts <= 0:
            logger.info(f"Agent {agent_id} size multiplier resulted in zero contracts, opinion ignored")
            return False
        
        # Route based on mode
        if config.mode == "shadow":
            # Shadow mode: record opinion only, no orders
            logger.debug(f"Shadow mode: recording opinion from {agent_id} for {market_id}")
            return True  # Opinion recorded successfully
        
        elif config.mode == "paper":
            # Paper mode: route to paper portfolio
            success = self.paper_portfolio.execute_order(agent_id, market_id, side, adjusted_contracts)
            if success:
                logger.info(f"Paper mode: executed order from {agent_id} for {market_id}")
            return success
        
        elif config.mode == "live":
            # Live mode: route to Kalshi order execution
            try:
                from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
                import asyncio
                
                # Build order intent
                intent = OrderIntent(
                    ticker=market_id,
                    side=side,
                    action="buy" if side.lower() in ("yes", "buy", "long") else "sell",
                    price_cents=0,  # Market order (price determined by venue)
                    count=adjusted_contracts,
                    order_type="market",
                    time_in_force="ioc",
                    source=f"agent_mode_router:{agent_id}",
                    agent_id=agent_id,
                )
                
                # Route order asynchronously
                async def execute_live_order():
                    result = await route_order_async(intent)
                    return result
                
                # Run async order execution
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, execute_live_order())
                            result = future.result()
                    else:
                        result = asyncio.run(execute_live_order())
                    
                    if result and result.has_execution:
                        logger.info(f"Live mode: executed order from {agent_id} for {market_id}")
                        return True
                    else:
                        logger.error(f"Live mode: order failed for {agent_id} on {market_id}: {result.error if result else 'unknown'}")
                        return False
                        
                except Exception as e:
                    logger.error(f"Live mode: order execution error for {agent_id}: {e}")
                    return False
                    
            except ImportError as e:
                logger.error(f"Live mode: order router not available for {agent_id}: {e}")
                return False
        
        else:
            logger.error(f"Unknown mode '{config.mode}' for agent {agent_id}")
            return False
    
    def get_agent_routing_status(self, agent_id: str) -> dict:
        """Get routing status for an agent."""
        config = get_agent_mode_config(agent_id)
        return {
            "agent_id": agent_id,
            "mode": config.mode,
            "size_multiplier": config.size_multiplier,
            "enabled": config.enabled,
            "routing_to": {
                "shadow": config.mode == "shadow",
                "paper": should_route_to_paper(agent_id),
                "live": should_route_to_live(agent_id)
            }
        }


# Singleton
_router: Optional[AgentModeRouter] = None
_router_lock = None


def get_agent_mode_router() -> AgentModeRouter:
    """Return the agent mode router singleton."""
    global _router, _router_lock
    if _router is None:
        if _router_lock is None:
            import threading
            _router_lock = threading.Lock()
        with _router_lock:
            if _router is None:
                _router = AgentModeRouter()
    return _router
