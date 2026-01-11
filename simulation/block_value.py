"""
Block Value Metrics and Scoring System.

Defines what makes each MERID block valuable to the ecosystem:
- Consensus quality and agent participation
- Oracle alignment (Chainlink, UMA)
- Intelligence quality (news, sentiment, whale signals)
- Network effects (agent evolution, swarm coordination)
- Economic value (arbitrage opportunities, funding optimization)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("simulation.block_value")


@dataclass
class ConsensusMetrics:
    """Metrics measuring consensus quality."""
    confidence: float  # 0.0 - 1.0
    agent_participation: int  # Number of agents that voted
    vote_distribution: Dict[str, int]  # accept/reject/abstain counts
    weighted_consensus: float  # Trust-weighted consensus
    convergence_speed: float  # How quickly agents reached consensus
    dissent_ratio: float  # Ratio of dissenting votes
    
    def quality_score(self) -> float:
        """Calculate overall consensus quality (0-100)."""
        # High confidence, high participation, low dissent = high quality
        confidence_component = self.confidence * 40
        participation_component = min(self.agent_participation / 10, 1.0) * 30
        convergence_component = (1.0 - min(self.convergence_speed, 1.0)) * 15
        dissent_component = (1.0 - self.dissent_ratio) * 15
        
        return confidence_component + participation_component + convergence_component + dissent_component


@dataclass
class OracleAlignmentMetrics:
    """Metrics measuring alignment with external oracles."""
    chainlink_deviation: Optional[float]  # % deviation from Chainlink price
    chainlink_feed_age: Optional[float]  # Seconds since last Chainlink update
    uma_assertion_id: Optional[str]  # UMA assertion ID if proposed
    uma_proposed_price: Optional[float]  # Price proposed to UMA
    oracle_confidence_boost: float  # Confidence boost from oracle alignment
    reality_gap: float  # Gap between swarm prediction and oracle reality
    
    def alignment_score(self) -> float:
        """Calculate oracle alignment quality (0-100)."""
        if self.chainlink_deviation is None:
            return 50.0  # Neutral if no oracle data
        
        # Lower deviation = better alignment
        deviation_component = max(0, 100 - (abs(self.chainlink_deviation) * 1000))
        
        # Fresher data = better
        feed_age_component = 0
        if self.chainlink_feed_age is not None:
            feed_age_component = max(0, 100 - (self.chainlink_feed_age / 60 * 10))
        
        # UMA proposal = additional validation
        uma_component = 20 if self.uma_assertion_id else 0
        
        return (deviation_component * 0.5) + (feed_age_component * 0.3) + uma_component


@dataclass
class IntelligenceMetrics:
    """Metrics measuring intelligence quality gathered for the block."""
    news_items_processed: int
    sentiment_signals: int
    whale_signals: int
    liquidation_events_detected: int
    onchain_insights: int
    cross_venue_arbitrage_opportunities: int
    funding_rate_anomalies: int
    
    def intelligence_score(self) -> float:
        """Calculate intelligence gathering quality (0-100)."""
        # More diverse intelligence = higher score
        total_signals = (
            min(self.news_items_processed, 10) * 5 +
            min(self.sentiment_signals, 5) * 10 +
            min(self.whale_signals, 5) * 15 +
            min(self.liquidation_events_detected, 3) * 10 +
            min(self.onchain_insights, 5) * 10 +
            min(self.cross_venue_arbitrage_opportunities, 3) * 20 +
            min(self.funding_rate_anomalies, 3) * 10
        )
        return min(total_signals, 100.0)


@dataclass
class NetworkEffectMetrics:
    """Metrics measuring network effects and agent evolution."""
    agent_replications: int  # New agents spawned
    agent_terminations: int  # Underperforming agents removed
    charter_evolutions: int  # Agent charters that evolved
    swarm_coordination_events: int  # Successful multi-agent coordination
    reflection_learnings: int  # New learnings recorded
    trust_updates: int  # Agent trust score updates
    
    def network_score(self) -> float:
        """Calculate network effect quality (0-100)."""
        # Active evolution and coordination = healthy network
        evolution_component = min(self.agent_replications + self.charter_evolutions, 5) * 15
        coordination_component = min(self.swarm_coordination_events, 3) * 20
        learning_component = min(self.reflection_learnings, 10) * 3
        health_component = min(self.trust_updates, 10) * 2
        
        return min(evolution_component + coordination_component + learning_component + health_component, 100.0)


@dataclass
class EconomicValueMetrics:
    """Metrics measuring economic value created."""
    total_arbitrage_edge_detected: float  # USD value
    funding_rate_opportunities: float  # Annualized yield %
    liquidation_cascade_predictions: int  # Early warnings issued
    market_inefficiencies_found: int
    expected_value_generated: float  # EV from all opportunities
    
    def economic_score(self) -> float:
        """Calculate economic value quality (0-100)."""
        # Real economic opportunities = high value
        arbitrage_component = min(self.total_arbitrage_edge_detected / 1000, 1.0) * 40
        funding_component = min(self.funding_rate_opportunities * 100, 1.0) * 30
        prediction_component = min(self.liquidation_cascade_predictions, 3) * 10
        inefficiency_component = min(self.market_inefficiencies_found, 5) * 4
        
        return arbitrage_component + funding_component + prediction_component + inefficiency_component


@dataclass
class BlockValueMetrics:
    """
    Comprehensive value metrics for a MERID block.
    
    Defines what makes each block valuable to the ecosystem.
    """
    block_index: int
    timestamp: float
    
    # Core metric categories
    consensus: ConsensusMetrics
    oracle_alignment: OracleAlignmentMetrics
    intelligence: IntelligenceMetrics
    network_effects: NetworkEffectMetrics
    economic_value: EconomicValueMetrics
    
    # Computed fields
    overall_score: float = 0.0
    value_grade: str = ""  # S, A, B, C, D, F
    
    def __post_init__(self):
        """Calculate overall score and grade after initialization."""
        self.overall_score = self.calculate_overall_score()
        self.value_grade = self.calculate_grade()
    
    def calculate_overall_score(self) -> float:
        """
        Calculate weighted overall block value score (0-100).
        
        Weights:
        - Consensus Quality: 30%
        - Oracle Alignment: 25%
        - Intelligence Quality: 20%
        - Network Effects: 15%
        - Economic Value: 10%
        """
        weights = {
            "consensus": 0.30,
            "oracle": 0.25,
            "intelligence": 0.20,
            "network": 0.15,
            "economic": 0.10
        }
        
        score = (
            self.consensus.quality_score() * weights["consensus"] +
            self.oracle_alignment.alignment_score() * weights["oracle"] +
            self.intelligence.intelligence_score() * weights["intelligence"] +
            self.network_effects.network_score() * weights["network"] +
            self.economic_value.economic_score() * weights["economic"]
        )
        
        return round(score, 2)
    
    def calculate_grade(self) -> str:
        """Assign letter grade based on overall score."""
        if self.overall_score >= 90:
            return "S"  # Exceptional
        elif self.overall_score >= 80:
            return "A"  # Excellent
        elif self.overall_score >= 70:
            return "B"  # Good
        elif self.overall_score >= 60:
            return "C"  # Acceptable
        elif self.overall_score >= 50:
            return "D"  # Poor
        else:
            return "F"  # Failed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "block_index": self.block_index,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "value_grade": self.value_grade,
            "consensus": asdict(self.consensus),
            "oracle_alignment": asdict(self.oracle_alignment),
            "intelligence": asdict(self.intelligence),
            "network_effects": asdict(self.network_effects),
            "economic_value": asdict(self.economic_value),
            "breakdown": {
                "consensus_score": self.consensus.quality_score(),
                "oracle_score": self.oracle_alignment.alignment_score(),
                "intelligence_score": self.intelligence.intelligence_score(),
                "network_score": self.network_effects.network_score(),
                "economic_score": self.economic_value.economic_score()
            }
        }
    
    def generate_summary(self) -> str:
        """Generate human-readable summary of block value."""
        lines = [
            f"Block #{self.block_index} Value Assessment",
            f"Overall Score: {self.overall_score}/100 (Grade: {self.value_grade})",
            "",
            "Component Scores:",
            f"  • Consensus Quality: {self.consensus.quality_score():.1f}/100",
            f"    - Confidence: {self.consensus.confidence:.1%}",
            f"    - Participation: {self.consensus.agent_participation} agents",
            f"    - Dissent: {self.consensus.dissent_ratio:.1%}",
            "",
            f"  • Oracle Alignment: {self.oracle_alignment.alignment_score():.1f}/100",
            f"    - Chainlink Deviation: {self.oracle_alignment.chainlink_deviation:.2%}" if self.oracle_alignment.chainlink_deviation else "    - No oracle data",
            f"    - Reality Gap: {self.oracle_alignment.reality_gap:.2%}",
            f"    - UMA Assertion: {self.oracle_alignment.uma_assertion_id or 'None'}",
            "",
            f"  • Intelligence Quality: {self.intelligence.intelligence_score():.1f}/100",
            f"    - News Items: {self.intelligence.news_items_processed}",
            f"    - Whale Signals: {self.intelligence.whale_signals}",
            f"    - Arbitrage Opportunities: {self.intelligence.cross_venue_arbitrage_opportunities}",
            "",
            f"  • Network Effects: {self.network_effects.network_score():.1f}/100",
            f"    - Agent Replications: {self.network_effects.agent_replications}",
            f"    - Reflection Learnings: {self.network_effects.reflection_learnings}",
            f"    - Swarm Coordination: {self.network_effects.swarm_coordination_events}",
            "",
            f"  • Economic Value: {self.economic_value.economic_score():.1f}/100",
            f"    - Arbitrage Edge: ${self.economic_value.total_arbitrage_edge_detected:.2f}",
            f"    - Funding Opportunities: {self.economic_value.funding_rate_opportunities:.2%} APY",
            f"    - Liquidation Predictions: {self.economic_value.liquidation_cascade_predictions}",
        ]
        
        return "\n".join(lines)


def calculate_block_value(
    block_index: int,
    timestamp: float,
    consensus_data: Dict[str, Any],
    oracle_data: Dict[str, Any],
    intelligence_data: Dict[str, Any],
    network_data: Dict[str, Any],
    economic_data: Dict[str, Any]
) -> BlockValueMetrics:
    """
    Calculate comprehensive value metrics for a block.
    
    This is the master function that aggregates all value signals.
    """
    consensus = ConsensusMetrics(
        confidence=consensus_data.get("confidence", 0.0),
        agent_participation=consensus_data.get("agent_participation", 0),
        vote_distribution=consensus_data.get("vote_distribution", {}),
        weighted_consensus=consensus_data.get("weighted_consensus", 0.0),
        convergence_speed=consensus_data.get("convergence_speed", 1.0),
        dissent_ratio=consensus_data.get("dissent_ratio", 0.0)
    )
    
    oracle_alignment = OracleAlignmentMetrics(
        chainlink_deviation=oracle_data.get("chainlink_deviation"),
        chainlink_feed_age=oracle_data.get("chainlink_feed_age"),
        uma_assertion_id=oracle_data.get("uma_assertion_id"),
        uma_proposed_price=oracle_data.get("uma_proposed_price"),
        oracle_confidence_boost=oracle_data.get("oracle_confidence_boost", 0.0),
        reality_gap=oracle_data.get("reality_gap", 0.0)
    )
    
    intelligence = IntelligenceMetrics(
        news_items_processed=intelligence_data.get("news_items_processed", 0),
        sentiment_signals=intelligence_data.get("sentiment_signals", 0),
        whale_signals=intelligence_data.get("whale_signals", 0),
        liquidation_events_detected=intelligence_data.get("liquidation_events_detected", 0),
        onchain_insights=intelligence_data.get("onchain_insights", 0),
        cross_venue_arbitrage_opportunities=intelligence_data.get("cross_venue_arbitrage_opportunities", 0),
        funding_rate_anomalies=intelligence_data.get("funding_rate_anomalies", 0)
    )
    
    network_effects = NetworkEffectMetrics(
        agent_replications=network_data.get("agent_replications", 0),
        agent_terminations=network_data.get("agent_terminations", 0),
        charter_evolutions=network_data.get("charter_evolutions", 0),
        swarm_coordination_events=network_data.get("swarm_coordination_events", 0),
        reflection_learnings=network_data.get("reflection_learnings", 0),
        trust_updates=network_data.get("trust_updates", 0)
    )
    
    economic_value = EconomicValueMetrics(
        total_arbitrage_edge_detected=economic_data.get("total_arbitrage_edge_detected", 0.0),
        funding_rate_opportunities=economic_data.get("funding_rate_opportunities", 0.0),
        liquidation_cascade_predictions=economic_data.get("liquidation_cascade_predictions", 0),
        market_inefficiencies_found=economic_data.get("market_inefficiencies_found", 0),
        expected_value_generated=economic_data.get("expected_value_generated", 0.0)
    )
    
    metrics = BlockValueMetrics(
        block_index=block_index,
        timestamp=timestamp,
        consensus=consensus,
        oracle_alignment=oracle_alignment,
        intelligence=intelligence,
        network_effects=network_effects,
        economic_value=economic_value
    )
    
    logger.info(
        "Block #%d value calculated: Score=%.2f Grade=%s",
        block_index,
        metrics.overall_score,
        metrics.value_grade
    )
    
    return metrics
