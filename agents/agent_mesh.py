"""
Agent Mesh — CANONICAL production agent orchestration layer.

This is the single source of truth for which agents run in production.
All agents run as independent async tasks, subscribing to event
streams and emitting outputs.  Do NOT use agents/registry.py or
agents/manifest.py for production agent initialization — those are
legacy/reference modules only (see T-004 Zero-Trust Audit).

4 active agents (others moved to legacy):
1. MarketAnalystAgent  — TA + momentum
2. RiskAgent           — Exposure & liquidation (VETO power)
3. SkepticAgent        — Adversarial check (can force re-round)
4. StrategyAgent       — Trade structuring

Legacy agents (moved to legacy/agents/):
- NewsAnalystAgent, SynthesizerAgent, ArchivistAgent, MetaAuditAgent
"""

# DEPRECATION NOTICE:
# This module is part of the legacy LLM/mesh risk system.
# It is NOT used in the kalshi_crypto_15m_v2 profile and MUST NOT
# be wired into any production trading or execution path.
LEGACY_EXPERIMENTAL_ONLY = True

from __future__ import annotations

import asyncio
from typing import List, Dict, Any

from agents.streaming import (
    MarketAnalystAgent,
    # NewsAnalystAgent,  # PRODUCTION FIX (2026-05-13): Moved to legacy, commenting out
    RiskAgent,
    SkepticAgent,
    # SynthesizerAgent,  # PRODUCTION FIX (2026-05-13): Moved to legacy, commenting out
    StrategyAgent,
    # ArchivistAgent,  # PRODUCTION FIX (2026-05-13): Moved to legacy, commenting out
    # MetaAuditAgent  # PRODUCTION FIX (2026-05-13): Moved to legacy, commenting out
)
from utils.logger import get_logger

logger = get_logger("agents.mesh")


class AgentMesh:
    """
    Manages the mesh of autonomous streaming agents.
    
    All agents run as independent async tasks,
    subscribing to event streams and emitting outputs.
    
    4 active agents (others moved to legacy):
    1. Analyst (Market) - TA + momentum
    2. Risk Agent - Exposure & liquidation (VETO)
    3. Skeptic - Adversarial check (can force re-round)
    4. Strategy - Trade structuring
    """
    
    def __init__(self):
        self.agents: List = []
        self.running = False
        
    async def initialize(self):
        """Initialize all 4 active streaming agents (others moved to legacy)."""
        # INSTRUMENTATION: Track initialization timing
        import time
        import os
        init_start_ts = time.time()
        
        logger.info("Initializing agent mesh with 4 active agents...")
        
        # Create 4 active streaming agents (others moved to legacy)
        self.agents = [
            MarketAnalystAgent("market-analyst-01"),      # 1. Analyst
            RiskAgent("risk-agent-01"),                   # 2. Risk (VETO)
            SkepticAgent("skeptic-agent-01"),             # 3. Skeptic (re-round)
            StrategyAgent("strategy-agent-01"),           # 4. Strategy
        ]
        
        duration_ms = (time.time() - init_start_ts) * 1000
        logger.info(
            f"Agent mesh initialized with {len(self.agents)} agents "
            f"[AGENT-MESH] init profile={os.environ.get('MERID_PROFILE', 'unknown')} "
            f"agents={len(self.agents)} duration_ms={duration_ms:.2f}"
        )
    
    async def start(self):
        """Start all agents."""
        if self.running:
            logger.warning("Agent mesh already running")
            return
        
        self.running = True
        
        # Start all agents
        for agent in self.agents:
            await agent.start()
        
        logger.info(f"Agent mesh started - {len(self.agents)} agents operational")
    
    async def stop(self):
        """Stop all agents."""
        self.running = False
        
        # Stop all agents
        for agent in self.agents:
            await agent.stop()
        
        logger.info("Agent mesh stopped")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics for all agents."""
        return {
            "total_agents": len(self.agents),
            "running": self.running,
            "agents": [agent.get_metrics() for agent in self.agents]
        }


# Global agent mesh instance
agent_mesh = AgentMesh()


async def start_agent_mesh():
    """Start the global agent mesh."""
    await agent_mesh.initialize()
    await agent_mesh.start()


async def stop_agent_mesh():
    """Stop the global agent mesh."""
    await agent_mesh.stop()
