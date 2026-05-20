"""
Agent Metadata Helper

Computes classification, age_bucket, and tag for agents to enable
observability without changing behavior.
"""

from __future__ import annotations

import os
import inspect
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.agents.agent_metadata")


@dataclass
class AgentMetadata:
    """Metadata for an agent."""
    name: str
    classification: str  # prod_15m_core, prod_15m_optional, research_only, remove
    module_path: str
    last_modified: Optional[datetime]
    age_bucket: str  # recent, stale, ancient_experimental
    tag: Optional[str]  # llm_mesh_v1, etc.


# Agent classification mapping (from KALSHI_15M_AGENT_INVENTORY.md)
AGENT_CLASSIFICATION_MAP: Dict[str, str] = {
    # prod_15m_core
    "KalshiTradingAgent": "prod_15m_core",
    "PortfolioRiskAgent": "prod_15m_core",
    "Btc15mAgent": "prod_15m_core",
    "Eth15mAgent": "prod_15m_core",
    "Sol15mAgent": "prod_15m_core",
    "Xrp15mAgent": "prod_15m_core",
    "Doge15mAgent": "prod_15m_core",
    
    # prod_15m_optional
    "KalshiNewsAgent": "prod_15m_optional",
    "SignalFusionAgent": "prod_15m_optional",
    
    # research_only
    "MarketAnalystAgent": "research_only",
    "RiskAgent": "research_only",
    "SkepticAgent": "research_only",
    "StrategyAgent": "research_only",
    "BullAnalyst": "research_only",
    "BearAnalyst": "research_only",
    "RiskManager": "research_only",
    "ExecutionAgent": "research_only",
    "GovernanceAgent": "research_only",
    "CryptoSignalsAgent": "research_only",
    "RiskManagerAgent": "research_only",
    "CapitalAllocatorAgent": "research_only",
    "AnomalyDetectorAgent": "research_only",
    "StrategyDesignerAgent": "research_only",
    "ArbitrageAgent": "research_only",
    "ExecutionOptimizerAgent": "research_only",
    "AgentOrchestrator": "research_only",
    "HybridCanonicalAgent": "research_only",
    "WiredPredictionMarketAgent": "research_only",
    "BandStrategyAgent": "research_only",
    "KalshiUniversalAgent": "research_only",
    "CriticAgent": "research_only",
    "NewsIngestionAgent": "research_only",
    "GovernorAgent": "research_only",
    "HardenedGovernorAgent": "research_only",
    "CryptoPredictionAgent": "research_only",
    "Btc15mMakerAgent": "research_only",
    "ScalperAgent": "research_only",
    
    # remove
    "Skeptic": "remove",
    "RiskAgent": "remove",  # Legacy registry version
    "StrategyAgent": "remove",  # Legacy registry version
    
    # Default
    "default": "research_only",
}


# Agent tag mapping
AGENT_TAG_MAP: Dict[str, Optional[str]] = {
    "MarketAnalystAgent": "llm_mesh_v1",
    "RiskAgent": "llm_mesh_v1",
    "SkepticAgent": "llm_mesh_v1",
    "StrategyAgent": "llm_mesh_v1",
}


def get_age_bucket(last_modified: Optional[datetime]) -> str:
    """Compute age bucket from last modified timestamp.
    
    Args:
        last_modified: Last modified datetime or None
        
    Returns:
        Age bucket: recent, stale, or ancient_experimental
    """
    if last_modified is None:
        return "unknown"
    
    now = datetime.now()
    age = now - last_modified
    
    if age.days < 30:
        return "recent"
    elif age.days < 120:
        return "stale"
    else:
        return "ancient_experimental"


def get_module_mtime(module_path: str) -> Optional[datetime]:
    """Get last modified time for a module file.
    
    Args:
        module_path: Module path (e.g., "merid.agents.btc_15m_agent")
        
    Returns:
        Last modified datetime or None if file not found
    """
    try:
        # Convert module path to file path
        module_file = module_path.replace(".", "/") + ".py"
        
        # Try to find the file relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent
        file_path = project_root / module_file
        
        if file_path.exists():
            mtime = file_path.stat().st_mtime
            return datetime.fromtimestamp(mtime)
        else:
            logger.debug(f"Module file not found: {file_path}")
            return None
    except Exception as e:
        logger.warning(f"Failed to get mtime for {module_path}: {e}")
        return None


def get_agent_metadata(
    agent_name: str,
    module_path: Optional[str] = None
) -> AgentMetadata:
    """Get metadata for an agent.
    
    Args:
        agent_name: Name of the agent class
        module_path: Optional module path (auto-detected if None)
        
    Returns:
        AgentMetadata with classification, age_bucket, tag
    """
    # Get classification
    classification = AGENT_CLASSIFICATION_MAP.get(agent_name, AGENT_CLASSIFICATION_MAP["default"])
    
    # Get tag
    tag = AGENT_TAG_MAP.get(agent_name)
    
    # Get module path if not provided
    if module_path is None:
        try:
            # Try to get module from class name
            # This is a simple heuristic - may not work for all cases
            if agent_name.startswith("Btc15m"):
                module_path = "merid.agents.btc_15m_agent"
            elif agent_name.startswith("Eth15m"):
                module_path = "merid.agents.eth_15m_agent"
            elif agent_name.startswith("Sol15m"):
                module_path = "merid.agents.sol_15m_agent"
            elif agent_name.startswith("Xrp15m"):
                module_path = "merid.agents.xrp_15m_agent"
            elif agent_name.startswith("Doge15m"):
                module_path = "merid.agents.doge_15m_agent"
            elif agent_name == "KalshiTradingAgent":
                module_path = "merid.prediction.trading_agent"
            elif agent_name == "PortfolioRiskAgent":
                module_path = "merid.prediction.portfolio_risk_agent"
            elif agent_name == "MarketAnalystAgent":
                module_path = "agents.core.market_analyst"
            elif agent_name == "RiskAgent":
                module_path = "agents.core.risk_agent"
            elif agent_name == "SkepticAgent":
                module_path = "agents.core.skeptic_agent"
            elif agent_name == "StrategyAgent":
                module_path = "agents.core.strategy_agent"
            else:
                module_path = "unknown"
        except Exception:
            module_path = "unknown"
    
    # Get last modified time
    last_modified = None
    if module_path and module_path != "unknown":
        last_modified = get_module_mtime(module_path)
    
    # Get age bucket
    age_bucket = get_age_bucket(last_modified)
    
    return AgentMetadata(
        name=agent_name,
        classification=classification,
        module_path=module_path or "unknown",
        last_modified=last_modified,
        age_bucket=age_bucket,
        tag=tag
    )


def get_agent_metadata_from_instance(agent_instance: object) -> AgentMetadata:
    """Get metadata from an agent instance.
    
    Args:
        agent_instance: Agent instance
        
    Returns:
        AgentMetadata
    """
    agent_name = agent_instance.__class__.__name__
    
    # Get module path from instance
    module_path = None
    try:
        module_path = agent_instance.__class__.__module__
    except Exception:
        pass
    
    return get_agent_metadata(agent_name, module_path)


def log_agent_metadata_summary(agents: list) -> None:
    """Log a summary of agent metadata.
    
    Args:
        agents: List of agent instances
    """
    profile = os.environ.get('MERID_PROFILE', 'unknown')
    logger.info(f"[AGENT-METADATA-SUMMARY] profile={profile} total_agents={len(agents)}")
    
    # Count by classification
    classification_counts = {}
    age_bucket_counts = {}
    
    for agent in agents:
        metadata = get_agent_metadata_from_instance(agent)
        classification_counts[metadata.classification] = classification_counts.get(metadata.classification, 0) + 1
        age_bucket_counts[metadata.age_bucket] = age_bucket_counts.get(metadata.age_bucket, 0) + 1
    
    # Log classification counts
    for classification, count in classification_counts.items():
        logger.info(f"[AGENT-METADATA-SUMMARY] classification={classification} count={count}")
    
    # Log age bucket counts
    for age_bucket, count in age_bucket_counts.items():
        logger.info(f"[AGENT-METADATA-SUMMARY] age_bucket={age_bucket} count={count}")


def scan_for_ancient_agents(agents: list) -> None:
    """Scan for ancient_experimental agents and log warnings.
    
    Args:
        agents: List of agent instances
    """
    profile = os.environ.get('MERID_PROFILE', 'unknown')
    
    for agent in agents:
        metadata = get_agent_metadata_from_instance(agent)
        
        if (metadata.classification in ('research_only', 'remove') and 
            metadata.age_bucket == 'ancient_experimental'):
            logger.warning(
                f"[AGENT-AGE-SCAN] WARN: ancient_experimental agent registered "
                f"name={metadata.name} module={metadata.module_path} "
                f"last_modified={metadata.last_modified} "
                f"classification={metadata.classification} "
                f"profile={profile}"
            )
