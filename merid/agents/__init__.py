"""
MERID Agents Package

LEAN 15m KALSHI STACK (2026-05-13): Pruned for BTC/ETH/SOL/XRP/DOGE trading.
Core agents: StrategyAgent, RiskAgent, SkepticAgent, MarketAnalystAgent.
Deleted agents (moved to legacy/): NewsAnalystAgent, SynthesizerAgent, ArchivistAgent, MetaAuditAgent,
    ConsensusCoordinatorAgent, ExplainabilityAgent, GovernanceAgent.
"""

from merid.agents.base import (
    AgentCategory,
    AgentOutput,
    AgentStatus,
    CanonicalAgent,
    CanonicalAgentRegistry,
    get_canonical_registry,
)
from merid.agents.sports_odds import (
    OddsAwareSportsAgent,
    SportsOddsStrategy,
    get_sports_odds_agent,
)

__all__ = [
    "AgentCategory",
    "AgentOutput",
    "AgentStatus",
    "CanonicalAgent",
    "CanonicalAgentRegistry",
    "get_canonical_registry",
    "OddsAwareSportsAgent",
    "SportsOddsStrategy",
    "get_sports_odds_agent",
]
