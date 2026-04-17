"""
Agent Mesh — CANONICAL production agent orchestration layer.

This is the single source of truth for which agents run in production.
All 8 agents run as independent async tasks, subscribing to event
streams and emitting outputs.  Do NOT use agents/registry.py or
agents/manifest.py for production agent initialization — those are
legacy/reference modules only (see T-004 Zero-Trust Audit).

8 mandatory agents per spec:
1. MarketAnalystAgent  — TA + momentum
2. NewsAnalystAgent    — Narrative impact
3. RiskAgent           — Exposure & liquidation (VETO power)
4. SkepticAgent        — Adversarial check (can force re-round)
5. SynthesizerAgent    — Cross-agent merge
6. StrategyAgent       — Trade structuring
7. ArchivistAgent      — State memory
8. MetaAuditAgent      — Agent performance & trust
"""

from __future__ import annotations

import asyncio
from typing import List, Dict, Any

from agents.streaming import (
    MarketAnalystAgent,
    NewsAnalystAgent,
    RiskAgent,
    SkepticAgent,
    SynthesizerAgent,
    StrategyAgent,
    ArchivistAgent,
    MetaAuditAgent
)
from utils.logger import get_logger

logger = get_logger("agents.mesh")


class AgentMesh:
    """
    Manages the mesh of autonomous streaming agents.
    
    All agents run as independent async tasks,
    subscribing to event streams and emitting outputs.
    
    8 mandatory agents per production spec:
    1. Analyst (Market) - TA + momentum
    2. News Agent - Narrative impact
    3. Risk Agent - Exposure & liquidation (VETO power)
    4. Skeptic - Adversarial check (can force re-round)
    5. Synthesizer - Cross-agent merge
    6. Archivist - State memory
    7. Meta-Audit - Agent performance & trust
    8. Strategy - Trade structuring
    """
    
    def __init__(self):
        self.agents: List = []
        self.running = False
        
    async def initialize(self):
        """Initialize all 8 streaming agents."""
        logger.info("Initializing agent mesh with 8 mandatory agents...")
        
        # Create all 8 mandatory streaming agents
        self.agents = [
            MarketAnalystAgent("market-analyst-01"),      # 1. Analyst
            NewsAnalystAgent("news-analyst-01"),          # 2. News Agent
            RiskAgent("risk-agent-01"),                   # 3. Risk (VETO)
            SkepticAgent("skeptic-agent-01"),             # 4. Skeptic (re-round)
            SynthesizerAgent("synthesizer-agent-01"),     # 5. Synthesizer
            StrategyAgent("strategy-agent-01"),           # 6. Strategy
            ArchivistAgent("archivist-agent-01"),         # 7. Archivist
            MetaAuditAgent("meta-audit-agent-01"),        # 8. Meta-Audit
        ]
        
        logger.info(f"Agent mesh initialized with {len(self.agents)} agents")
    
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
