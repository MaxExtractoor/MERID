"""
Core type definitions for MERID cognitive core.
Immutable data structures for beliefs, data, and decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class AgentType(Enum):
    LOGIC = "logic"
    INTUITION = "intuition"
    ADVERSARIAL = "adversarial"
    MARKET_STRUCTURE = "market_structure"
    SIMULATION = "simulation"
    GOVERNANCE = "governance"


class DataSource(Enum):
    ONCHAIN_ETH = "onchain_eth"
    ONCHAIN_SOL = "onchain_sol"
    ONCHAIN_BASE = "onchain_base"
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    BINANCE = "binance"
    COINBASE = "coinbase"
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    NEWS_RSS = "news_rss"
    MANUAL = "manual"


class DataType(Enum):
    PRICE = "price"
    ODDS = "odds"
    VOLUME = "volume"
    SENTIMENT = "sentiment"
    TX_COUNT = "tx_count"
    LIQUIDITY = "liquidity"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    NEWS_EVENT = "news_event"


@dataclass(frozen=True)
class Datum:
    """
    Normalized data point with decay, confidence, and provenance.
    Immutable to prevent tampering.
    """
    timestamp: datetime
    source: DataSource
    data_type: DataType
    value: Any
    confidence: float  # 0.0-1.0 (source reliability)
    decay_half_life: timedelta  # How fast does this signal decay?
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0,1], got {self.confidence}")
        if self.decay_half_life.total_seconds() <= 0:
            raise ValueError(f"Decay half-life must be positive, got {self.decay_half_life}")
    
    def current_confidence(self, now: datetime) -> float:
        """Calculate confidence after decay."""
        elapsed = (now - self.timestamp).total_seconds()
        half_life_seconds = self.decay_half_life.total_seconds()
        decay_factor = 0.5 ** (elapsed / half_life_seconds)
        return self.confidence * decay_factor


@dataclass(frozen=True)
class BeliefVector:
    """
    Agent's belief about a hypothesis.
    Includes probability, confidence, risk, and dissent notes.
    """
    agent_type: AgentType
    hypothesis: str
    probability: float  # P(hypothesis is true) ∈ [0,1]
    confidence: float  # Confidence in the probability estimate ∈ [0,1]
    risk: float  # Tail risk if hypothesis is wrong ∈ [0,1]
    dissent_notes: str  # Minority opinion, assumptions, warnings
    reasoning: str  # Detailed reasoning (for audit trail)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"Probability must be in [0,1], got {self.probability}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0,1], got {self.confidence}")
        if not 0.0 <= self.risk <= 1.0:
            raise ValueError(f"Risk must be in [0,1], got {self.risk}")


@dataclass
class DistilledOutput:
    """
    Human-readable output from distillation gate.
    Mandatory format for all MERID outputs.
    """
    verdict: str  # ≤5 lines, risk-adjusted recommendation
    confidence: float  # Meta-confidence (0-100%)
    key_drivers: List[str]  # Top 3 factors supporting verdict
    primary_risks: List[str]  # Top 3 risks
    counterfactuals: List[str]  # What if key assumptions are wrong?
    agent_dissent: List[str]  # Preserved minority opinions
    next_decision: str  # What human must decide next
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "key_drivers": self.key_drivers,
            "primary_risks": self.primary_risks,
            "counterfactuals": self.counterfactuals,
            "agent_dissent": self.agent_dissent,
            "next_decision": self.next_decision,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ScenarioResult:
    """
    Result from a single Monte Carlo scenario.
    """
    scenario_id: int
    success: bool
    timeline: float  # Hours to event
    params: Dict[str, float]  # Sampled parameters
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationAnalysis:
    """
    Aggregate analysis of Monte Carlo simulation.
    """
    hypothesis: str
    scenarios_run: int
    success_count: int
    success_rate: float
    avg_timeline: float
    timeline_variance: float
    confidence_interval: Tuple[float, float]  # 95% CI for success rate
    multiverse_variance: float
    recommendation: str


@dataclass
class RiskMetrics:
    """
    Risk analysis metrics.
    """
    kelly_fraction: float  # Recommended position size
    tail_risk: float  # VaR/CVaR estimate
    max_drawdown_estimate: float
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    win_probability: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
