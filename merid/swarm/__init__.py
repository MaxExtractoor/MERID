"""MERID Swarm — Multi-agent consensus and market mood aggregation."""

from merid.swarm.consensus_aggregator import (
    AgentProposal,
    ConsensusStatus,
    ConsensusView,
    SwarmConsensusAggregator,
    get_consensus_aggregator,
    neutral_consensus_view,
)

# REMOVED: MarketMoodBus imports - sentiment components not used in 15m stack

__all__ = [
    "AgentProposal",
    "ConsensusStatus",
    "ConsensusView",
    "SwarmConsensusAggregator",
    "get_consensus_aggregator",
    "neutral_consensus_view",
]
