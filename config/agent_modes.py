# config/agent_modes.py
"""Per-agent mode and size multiplier configuration."""

from typing import Dict, Any
import os
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("config.agent_modes")


@dataclass
class AgentModeConfig:
    """Configuration for a single agent's mode and sizing."""
    mode: str  # "shadow", "paper", "live"
    size_multiplier: float = 1.0
    enabled: bool = True


# Default agent mode configurations
DEFAULT_AGENT_MODES: Dict[str, AgentModeConfig] = {
    "btc_15m_regime": AgentModeConfig(mode="shadow", size_multiplier=1.0),
    "eth_15m_regime": AgentModeConfig(mode="shadow", size_multiplier=1.0),
    "sol_15m_regime": AgentModeConfig(mode="shadow", size_multiplier=1.0),
    "xrp_15m_regime": AgentModeConfig(mode="shadow", size_multiplier=1.0),
    "btc_1h_regime": AgentModeConfig(mode="shadow", size_multiplier=1.0),
}


def get_agent_mode_config(agent_id: str) -> AgentModeConfig:
    """Get mode configuration for an agent, with environment variable override."""
    # Check for environment variable override
    mode_env_key = f"{agent_id.upper()}_MODE"
    size_env_key = f"{agent_id.upper()}_SIZE_MULTIPLIER"
    enabled_env_key = f"{agent_id.upper()}_ENABLED"
    
    # Start with default
    config = DEFAULT_AGENT_MODES.get(agent_id, AgentModeConfig(mode="shadow"))
    
    # Apply environment overrides
    if mode_env_key in os.environ:
        config.mode = os.environ[mode_env_key].lower()
        logger.info(f"Agent {agent_id} mode overridden to {config.mode} from env")
    
    if size_env_key in os.environ:
        try:
            config.size_multiplier = float(os.environ[size_env_key])
            logger.info(f"Agent {agent_id} size multiplier overridden to {config.size_multiplier} from env")
        except ValueError:
            logger.warning(f"Invalid size multiplier for {agent_id}: {os.environ[size_env_key]}")
    
    if enabled_env_key in os.environ:
        config.enabled = os.environ[enabled_env_key].lower() in ("true", "1", "yes")
        logger.info(f"Agent {agent_id} enabled overridden to {config.enabled} from env")
    
    return config


def get_all_agent_modes() -> Dict[str, AgentModeConfig]:
    """Get mode configurations for all agents."""
    return {
        agent_id: get_agent_mode_config(agent_id)
        for agent_id in DEFAULT_AGENT_MODES.keys()
    }


def set_agent_mode(agent_id: str, mode: str, size_multiplier: float = 1.0) -> None:
    """Set mode configuration for an agent (for runtime updates)."""
    if agent_id in DEFAULT_AGENT_MODES:
        DEFAULT_AGENT_MODES[agent_id].mode = mode
        DEFAULT_AGENT_MODES[agent_id].size_multiplier = size_multiplier
        logger.info(f"Updated {agent_id} mode to {mode} with size multiplier {size_multiplier}")
    else:
        logger.warning(f"Unknown agent ID: {agent_id}")


def is_agent_enabled(agent_id: str) -> bool:
    """Check if an agent is enabled."""
    config = get_agent_mode_config(agent_id)
    return config.enabled


def should_route_to_paper(agent_id: str) -> bool:
    """Check if agent orders should route to paper portfolio."""
    config = get_agent_mode_config(agent_id)
    return config.mode == "paper"


def should_route_to_live(agent_id: str) -> bool:
    """Check if agent orders should route to live Kalshi."""
    config = get_agent_mode_config(agent_id)
    return config.mode == "live"


def get_agent_size_multiplier(agent_id: str) -> float:
    """Get size multiplier for an agent."""
    config = get_agent_mode_config(agent_id)
    return config.size_multiplier
