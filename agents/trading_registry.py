"""
Trading Agents Loader for Kalshi Operations

This module loads trading-specific agents for the Kalshi core,
ensuring we don't load generic chat agents for market operations.
"""

from typing import List
from utils.logger import get_logger

logger = get_logger("agents.trading_registry")


def load_trading_agents() -> List:
    """
    Load trading-specific agents for Kalshi 15m crypto operations.

    LEAN 15m KALSHI STACK (2026-05-13): Pruned for BTC/ETH/SOL/XRP/DOGE trading.
    Only Skeptic, RiskAgent, and StrategyAgent - edge comes from microstructure.

    Returns:
        List of trading agent instances
    """
    try:
        from agents.skeptic import Skeptic
        from agents.risk import RiskAgent
        from agents.strategy_agent import StrategyAgent

        trading_agents = [
            Skeptic(agent_id="skeptic-01"),
            RiskAgent(agent_id="risk-01"),
            StrategyAgent(agent_id="strategy-agent-01"),
        ]

        logger.info("Loaded %d trading agents for Kalshi operations (lean 15m stack)", len(trading_agents))
        for agent in trading_agents:
            logger.info("  • %s (%s)", agent.agent_id, type(agent).__name__)

        return trading_agents

    except ImportError as exc:
        logger.warning("Trading agents not available, using fallback: %s", exc)
        return _load_fallback_agents()


def _load_fallback_agents() -> List:
    """Load all base agents as a last-resort fallback."""
    try:
        from agents.registry import load_agents
        agents = load_agents()
        logger.info("Using %d fallback agents for Kalshi operations", len(agents))
        return agents
    except Exception as exc:
        logger.error("Failed to load fallback agents: %s", exc)
        return []


def validate_trading_agents(agents: List) -> bool:
    """
    Validate that loaded agents are suitable for trading operations.
    
    Args:
        agents: List of agent instances
        
    Returns:
        True if agents are suitable, False otherwise
    """
    if not agents:
        logger.error("No agents loaded for trading operations")
        return False
    
    # Check for essential agent types
    agent_types = [type(agent).__name__ for agent in agents]
    essential_types = ['RiskAgent', 'Skeptic']

    has_essential = any(
        essential_type in agent_types
        for essential_type in essential_types
    )

    if not has_essential:
        logger.warning("Missing essential agent types (RiskAgent, Skeptic)")
        logger.info("Available agent types: %s", agent_types)
        return False

    logger.info("Trading agents validated with essential types present")
    return True


# Export the main function
__all__ = ['load_trading_agents', 'validate_trading_agents']
