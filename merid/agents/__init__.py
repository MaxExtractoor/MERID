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

# Sports odds module moved to legacy - import with graceful fallback
try:
    from merid.agents.sports_odds import (
        OddsAwareSportsAgent,
        SportsOddsStrategy,
        get_sports_odds_agent,
    )
    _sports_odds_available = True
except ImportError:
    _sports_odds_available = False
    OddsAwareSportsAgent = None
    SportsOddsStrategy = None
    get_sports_odds_agent = None

__all__ = [
    "AgentCategory",
    "AgentOutput",
    "AgentStatus",
    "CanonicalAgent",
    "CanonicalAgentRegistry",
    "get_canonical_registry",
]

# Only add sports odds exports if available
if _sports_odds_available:
    __all__.extend([
        "OddsAwareSportsAgent",
        "SportsOddsStrategy",
        "get_sports_odds_agent",
    ])
