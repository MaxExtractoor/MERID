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
            # Live mode: route to real Kalshi venue
            # TODO: Integrate with actual Kalshi order execution
            logger.warning(f"Live mode not yet implemented for {agent_id} - opinion ignored")
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
