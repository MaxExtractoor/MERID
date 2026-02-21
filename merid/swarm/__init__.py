"""MERID Swarm — Multi-agent consensus and market mood aggregation."""

from merid.swarm.consensus_aggregator import (
    AgentProposal,
    ConsensusStatus,
    ConsensusView,
    SwarmConsensusAggregator,
    get_consensus_aggregator,
)
from merid.swarm.market_mood_bus import (
    InsightObject,
    MarketMoodBus,
    SentimentConfidence,
    SentimentContext,
    VolatilityRegime,
    get_market_mood_bus,
)

__all__ = [
    "AgentProposal",
    "ConsensusStatus",
    "ConsensusView",
    "SwarmConsensusAggregator",
    "get_consensus_aggregator",
    "InsightObject",
    "MarketMoodBus",
    "SentimentConfidence",
    "SentimentContext",
    "VolatilityRegime",
    "get_market_mood_bus",
]
