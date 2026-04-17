"""MERID Canonical Agent Roster — Typed, structured agents for the swarm.

15 agent types across 5 categories:
§1 Market & Research: MarketResearchAgent, PredictionMarketAgent, CryptoSignalsAgent
§2 Strategy & Arb: StrategyDesignerAgent, ArbitrageAgent, ExecutionOptimizerAgent
§3 Risk & Capital: RiskManagerAgent, CapitalAllocatorAgent, AnomalyDetectorAgent
§4 Coordination: ConsensusCoordinatorAgent, ExplainabilityAgent, GovernanceAgent
§5 Dev & Ops: OpsRunbookAgent, BacktestAgent
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
