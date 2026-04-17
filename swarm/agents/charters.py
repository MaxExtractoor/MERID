from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(Enum):
    ARBITRAGE_HUNTER = "arbitrage_hunter"
    REALITY_VALIDATOR = "reality_validator"
    SENTIMENT_SCOUT = "sentiment_scout"
    LIQUIDATION_PREDICTOR = "liquidation_predictor"
    CROSS_VENUE_TRACKER = "cross_venue_tracker"
    FUNDING_OPTIMIZER = "funding_optimizer"


@dataclass
class AgentCharter:
    role: AgentRole
    name: str
    description: str
    primary_objective: str
    key_metrics: List[str]
    evolution_triggers: Dict[str, float]
    decay_rate: float = 0.02
    spawn_conditions: Dict[str, Any] = field(default_factory=dict)
    expertise_domains: List[str] = field(default_factory=list)
    risk_tolerance: float = 0.5
    active: bool = True
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


ARBITRAGE_HUNTER = AgentCharter(
    role=AgentRole.ARBITRAGE_HUNTER,
    name="ArbSeeker-α",
    description="Detects and prioritizes price discrepancies across Polymarket, Augur, and Hyperliquid perps",
    primary_objective="Maximize detected arbitrage edge value while minimizing execution risk",
    key_metrics=["total_edge_detected", "successful_executions", "false_positive_rate"],
    evolution_triggers={"total_edge_detected": 50000.0, "false_positive_rate": 0.3},
    spawn_conditions={"arbitrage_gap": 0.05, "confidence": 0.72},
    expertise_domains=["polymarket", "augur", "hyperliquid", "cross_venue"],
    risk_tolerance=0.7,
)

REALITY_VALIDATOR = AgentCharter(
    role=AgentRole.REALITY_VALIDATOR,
    name="TruthGuard-β",
    description="Compares swarm consensus against Chainlink oracles and on-chain outcomes",
    primary_objective="Maximize long-term accuracy of reality alignment",
    key_metrics=["validation_accuracy", "oracle_gap_reduction", "resolution_correctness"],
    evolution_triggers={"validation_accuracy": 0.92, "resolution_correctness": 0.95},
    spawn_conditions={"oracle_gap": 0.06, "confidence": 0.8},
    decay_rate=0.01,
    expertise_domains=["chainlink", "onchain", "resolution"],
    risk_tolerance=0.3,
)

SENTIMENT_SCOUT = AgentCharter(
    role=AgentRole.SENTIMENT_SCOUT,
    name="MoodReader-γ",
    description="Monitors news, social volume, whale flows, and sentiment extremes",
    primary_objective="Detect sentiment divergences that precede price moves",
    key_metrics=["sentiment_lead_time", "divergence_capture_rate", "whale_confluence_hits"],
    evolution_triggers={"divergence_capture_rate": 0.65},
    spawn_conditions={"news_intensity": 3, "confidence": 0.65},
    expertise_domains=["news", "whale", "social", "sentiment"],
    risk_tolerance=0.6,
)

LIQUIDATION_PREDICTOR = AgentCharter(
    role=AgentRole.LIQUIDATION_PREDICTOR,
    name="CascadeWatcher-δ",
    description="Predicts and flags impending liquidation cascades on Hyperliquid",
    primary_objective="Early warning accuracy on large liquidation events",
    key_metrics=["cascade_prediction_accuracy", "lead_time_hours", "false_alarm_rate"],
    evolution_triggers={"cascade_prediction_accuracy": 0.80},
    spawn_conditions={"liquidation_events": 2, "confidence": 0.6},
    expertise_domains=["hyperliquid", "liquidations", "leverage"],
    risk_tolerance=0.8,
)

CROSS_VENUE_TRACKER = AgentCharter(
    role=AgentRole.CROSS_VENUE_TRACKER,
    name="FlowMapper-ε",
    description="Tracks institutional money movement across CEXs, ETFs, and on-chain wallets",
    primary_objective="Identify sustained accumulation/distribution patterns",
    key_metrics=["flow_detection_accuracy", "accumulation_lead_time", "institution_confluence"],
    evolution_triggers={"flow_detection_accuracy": 0.75},
    spawn_conditions={"hybrid": 1, "confidence": 0.7},
    expertise_domains=["onchain", "etf", "cex", "whale"],
    risk_tolerance=0.4,
)

FUNDING_OPTIMIZER = AgentCharter(
    role=AgentRole.FUNDING_OPTIMIZER,
    name="RateHunter-ζ",
    description="Optimizes perpetual positions based on funding rate arbitrage and convergence",
    primary_objective="Maximize annualized funding yield with controlled risk",
    key_metrics=["annualized_yield", "drawdown", "sharpe_ratio"],
    evolution_triggers={"annualized_yield": 0.15, "sharpe_ratio": 1.5},
    spawn_conditions={"funding_rate": 0.0006, "confidence": 0.68},
    expertise_domains=["hyperliquid", "funding", "perps"],
    risk_tolerance=0.75,
)

CHARTER_REGISTRY: Dict[str, AgentCharter] = {
    charter.role.value: charter
    for charter in (
        ARBITRAGE_HUNTER,
        REALITY_VALIDATOR,
        SENTIMENT_SCOUT,
        LIQUIDATION_PREDICTOR,
        CROSS_VENUE_TRACKER,
        FUNDING_OPTIMIZER,
    )
}
