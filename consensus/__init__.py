"""
MERID Consensus Module.

TACo-style consensus engine for multi-agent trading decisions.
"""

from consensus.taco_consensus import (
    TaCoConsensusCoordinator,
    get_consensus_coordinator,
    AgentOpinion,
    TradePlan,
    TradeExecution,
    AgentRole,
    Stance,
    TradeDirection,
    PlanStatus,
    create_opinion_from_vote,
)

__all__ = [
    "TaCoConsensusCoordinator",
    "get_consensus_coordinator",
    "AgentOpinion",
    "TradePlan",
    "TradeExecution",
    "AgentRole",
    "Stance",
    "TradeDirection",
    "PlanStatus",
    "create_opinion_from_vote",
]
