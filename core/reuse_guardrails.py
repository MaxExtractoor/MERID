"""
MERID Reuse Guardrails - Section 13: Robust Fixes & Non-Reinvention Guardrails

Enforces the "legacy-first" rule: every new feature must declare what 
existing MERID components it reuses. Flags suspicious designs.

Key Rules:
- Every new feature must reuse existing topics, jobs, or adapters
- Refactor-over-rewrite: prefer wrap-and-extend
- Build focused views, not separate apps
- Log and monitor all new integrations
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("core.guardrails")


class ComponentType(str, Enum):
    """Types of MERID components."""
    KAFKA_TOPIC = "kafka_topic"
    FLINK_JOB = "flink_job"
    VENUE_ADAPTER = "venue_adapter"
    API_ENDPOINT = "api_endpoint"
    UI_COMPONENT = "ui_component"
    DATA_SOURCE = "data_source"
    AGENT = "agent"
    SERVICE = "service"


class ReuseStatus(str, Enum):
    """Status of reuse check."""
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    SUSPECT = "suspect"
    REJECTED = "rejected"


@dataclass
class ReusableComponent:
    """A reusable MERID component."""
    component_id: str
    component_type: ComponentType
    name: str
    description: str
    
    # Location
    module_path: str = ""
    topic_name: str = ""
    
    # Schema info
    input_schema: str = ""
    output_schema: str = ""
    
    # Usage stats
    dependent_count: int = 0
    last_used: float = 0.0
    
    # Status
    deprecated: bool = False
    replacement: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_type": self.component_type.value,
            "name": self.name,
            "description": self.description,
            "deprecated": self.deprecated,
            "replacement": self.replacement,
        }


@dataclass
class FeatureProposal:
    """A proposal for a new feature."""
    proposal_id: str
    feature_name: str
    description: str
    proposed_by: str
    
    # What it creates
    new_components: List[str] = field(default_factory=list)
    
    # What it reuses
    reuses_topics: List[str] = field(default_factory=list)
    reuses_jobs: List[str] = field(default_factory=list)
    reuses_adapters: List[str] = field(default_factory=list)
    reuses_endpoints: List[str] = field(default_factory=list)
    reuses_ui: List[str] = field(default_factory=list)
    
    # Review
    status: ReuseStatus = ReuseStatus.NEEDS_REVIEW
    review_notes: List[str] = field(default_factory=list)
    reviewed_by: str = ""
    
    timestamp: float = field(default_factory=time.time)
    
    def total_reused(self) -> int:
        """Total number of components reused."""
        return (
            len(self.reuses_topics) +
            len(self.reuses_jobs) +
            len(self.reuses_adapters) +
            len(self.reuses_endpoints) +
            len(self.reuses_ui)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "feature_name": self.feature_name,
            "status": self.status.value,
            "total_reused": self.total_reused(),
            "new_components": len(self.new_components),
            "review_notes": self.review_notes,
        }


# ============================================
# REUSE INVENTORY
# ============================================

# Existing Kafka topics that should be reused
EXISTING_TOPICS = {
    # Prices
    "prices.spot.*": "Spot price ticks from all venues",
    "prices.perps.*": "Perpetual futures prices",
    "prices.ohlcv.*": "OHLCV candles at various timeframes",
    "prices.fx.*": "FX rates for fiat conversion",
    
    # Order book
    "orderbook.l2.*": "Level 2 order book snapshots",
    "orderbook.l1.*": "Best bid/ask (Level 1)",
    
    # Trades
    "trades.executed.*": "Executed trade events",
    "orders.placed.*": "Order placement events",
    "orders.cancelled.*": "Order cancellation events",
    
    # Agent
    "agent.opinions.*": "Agent trading opinions",
    "agent.heartbeats.*": "Agent health heartbeats",
    "agent.tool_calls.*": "Agent tool invocations",
    
    # Consensus
    "consensus.decisions.*": "Consensus round decisions",
    "consensus.votes.*": "Individual agent votes",
    
    # Risk
    "risk.alerts.*": "Risk alerts by severity",
    "risk.metrics": "Periodic risk metrics snapshot",
    
    # Social/News
    "social.sentiment.*": "Social sentiment by symbol",
    "news.headlines.*": "News headlines with sentiment",
    
    # On-chain
    "onchain.whale_tx.*": "Large on-chain transactions",
    "onchain.defi.*": "DeFi protocol flows",
    
    # Governance
    "governance.kill_switch": "Kill switch events",
    "governance.limit_change": "Risk limit changes",
    
    # Bots
    "telegram.commands.*": "Telegram bot commands",
    "twitter.commands.*": "Twitter bot commands",
    "bots.activity.*": "Bot activity log",
    
    # Alerts
    "alerts.*": "System alerts",
}

# Existing Flink jobs
EXISTING_FLINK_JOBS = {
    "price_aggregator": "Aggregates prices across venues",
    "ohlcv_builder": "Builds OHLCV candles from ticks",
    "sentiment_aggregator": "Aggregates sentiment by symbol",
    "risk_calculator": "Calculates portfolio risk metrics",
    "feature_extractor": "Extracts trading features",
}

# Existing venue adapters
EXISTING_ADAPTERS = {
    "kraken": "Kraken exchange adapter",
    "coinbase": "Coinbase Advanced adapter",
    "binanceus": "Binance US adapter",
    "gemini": "Gemini adapter",
    "kalshi": "Kalshi prediction market adapter",
    "alpaca": "Alpaca broker adapter",
    "ibkr": "Interactive Brokers adapter",
    "paper": "Paper trading simulator",
}

# Existing API endpoints
EXISTING_ENDPOINTS = {
    "/api/v1/trading/orders": "Order management",
    "/api/v1/trading/positions": "Position management",
    "/api/v1/risk/metrics": "Risk metrics",
    "/api/v1/agents/status": "Agent status",
    "/api/v1/consensus/status": "Consensus status",
    "/ws/kafka": "Kafka WebSocket bridge",
}

# Existing UI components
EXISTING_UI_COMPONENTS = {
    "DataTableEnhanced": "Generic data table with sorting/filtering",
    "MetricCard": "Single metric display card",
    "StatusIndicator": "Status badge component",
    "AgentStatusPanel": "Agent status overview",
    "Sidebar": "Main navigation sidebar",
}


# ============================================
# GUARDRAILS ENGINE
# ============================================

class ReuseGuardrails:
    """
    Enforces reuse-first design principles.
    
    Every new feature must:
    1. Declare what existing components it reuses
    2. If nothing reused, design is flagged as suspect
    3. Prefer extending existing components over creating new ones
    """
    
    _instance: Optional["ReuseGuardrails"] = None
    
    def __init__(self):
        self._components: Dict[str, ReusableComponent] = {}
        self._proposals: List[FeatureProposal] = []
        self._load_inventory()
        
        logger.info("ReuseGuardrails initialized")
    
    @classmethod
    def get_instance(cls) -> "ReuseGuardrails":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _load_inventory(self) -> None:
        """Load existing component inventory."""
        # Load topics
        for topic, desc in EXISTING_TOPICS.items():
            self._components[f"topic:{topic}"] = ReusableComponent(
                component_id=f"topic:{topic}",
                component_type=ComponentType.KAFKA_TOPIC,
                name=topic,
                description=desc,
                topic_name=topic,
            )
        
        # Load Flink jobs
        for job, desc in EXISTING_FLINK_JOBS.items():
            self._components[f"flink:{job}"] = ReusableComponent(
                component_id=f"flink:{job}",
                component_type=ComponentType.FLINK_JOB,
                name=job,
                description=desc,
            )
        
        # Load adapters
        for adapter, desc in EXISTING_ADAPTERS.items():
            self._components[f"adapter:{adapter}"] = ReusableComponent(
                component_id=f"adapter:{adapter}",
                component_type=ComponentType.VENUE_ADAPTER,
                name=adapter,
                description=desc,
            )
    
    def check_topic_exists(self, topic_pattern: str) -> bool:
        """Check if a topic pattern exists in inventory."""
        base_topic = topic_pattern.split(".")[0] + ".*"
        return any(
            topic_pattern in t or base_topic in t
            for t in EXISTING_TOPICS.keys()
        )
    
    def find_matching_topics(self, keywords: List[str]) -> List[str]:
        """Find existing topics matching keywords."""
        matches = []
        for topic, desc in EXISTING_TOPICS.items():
            for kw in keywords:
                if kw.lower() in topic.lower() or kw.lower() in desc.lower():
                    matches.append(topic)
                    break
        return matches
    
    def review_proposal(self, proposal: FeatureProposal) -> FeatureProposal:
        """Review a feature proposal for reuse compliance."""
        notes = []
        
        # Check if anything is reused
        if proposal.total_reused() == 0:
            proposal.status = ReuseStatus.SUSPECT
            notes.append("⚠️ SUSPECT: No existing components reused. Design requires review.")
            
            # Suggest possible reuse
            suggestions = self.find_matching_topics(
                proposal.feature_name.lower().split()
            )
            if suggestions:
                notes.append(f"Consider reusing topics: {', '.join(suggestions[:3])}")
        
        # Check for new topics that might duplicate existing
        for new_comp in proposal.new_components:
            if "topic:" in new_comp:
                topic_name = new_comp.replace("topic:", "")
                base = topic_name.split(".")[0]
                
                existing = [t for t in EXISTING_TOPICS if base in t]
                if existing:
                    notes.append(
                        f"⚠️ New topic '{topic_name}' may duplicate: {existing[0]}"
                    )
                    proposal.status = ReuseStatus.NEEDS_REVIEW
        
        # Good reuse pattern
        if proposal.total_reused() >= 2 and proposal.status != ReuseStatus.SUSPECT:
            proposal.status = ReuseStatus.APPROVED
            notes.append(f"✓ Good reuse: {proposal.total_reused()} existing components")
        
        # Check for deprecated components
        for topic in proposal.reuses_topics:
            comp = self._components.get(f"topic:{topic}")
            if comp and comp.deprecated:
                notes.append(
                    f"⚠️ Topic '{topic}' is deprecated. Use '{comp.replacement}' instead."
                )
        
        proposal.review_notes = notes
        self._proposals.append(proposal)
        
        logger.info(
            f"Proposal reviewed: {proposal.feature_name} -> {proposal.status.value}"
        )
        
        return proposal
    
    def get_reuse_report(self) -> Dict[str, Any]:
        """Get report on reuse patterns."""
        approved = sum(1 for p in self._proposals if p.status == ReuseStatus.APPROVED)
        suspect = sum(1 for p in self._proposals if p.status == ReuseStatus.SUSPECT)
        
        return {
            "total_proposals": len(self._proposals),
            "approved": approved,
            "suspect": suspect,
            "needs_review": len(self._proposals) - approved - suspect,
            "reuse_rate": approved / max(1, len(self._proposals)),
            "total_components": len(self._components),
            "topics_count": len(EXISTING_TOPICS),
            "flink_jobs_count": len(EXISTING_FLINK_JOBS),
            "adapters_count": len(EXISTING_ADAPTERS),
        }
    
    def get_component_inventory(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get full inventory of reusable components."""
        inventory = {
            "topics": [],
            "flink_jobs": [],
            "adapters": [],
            "endpoints": [],
            "ui_components": [],
        }
        
        for comp in self._components.values():
            if comp.component_type == ComponentType.KAFKA_TOPIC:
                inventory["topics"].append(comp.to_dict())
            elif comp.component_type == ComponentType.FLINK_JOB:
                inventory["flink_jobs"].append(comp.to_dict())
            elif comp.component_type == ComponentType.VENUE_ADAPTER:
                inventory["adapters"].append(comp.to_dict())
        
        return inventory


def get_guardrails() -> ReuseGuardrails:
    """Get the global guardrails instance."""
    return ReuseGuardrails.get_instance()


# ============================================
# FEATURE PROPOSAL HELPERS
# ============================================

def create_feature_proposal(
    feature_name: str,
    description: str,
    proposed_by: str,
    new_components: List[str] = None,
    reuses_topics: List[str] = None,
    reuses_jobs: List[str] = None,
    reuses_adapters: List[str] = None,
) -> FeatureProposal:
    """Create and review a feature proposal."""
    import uuid
    
    proposal = FeatureProposal(
        proposal_id=f"fp_{uuid.uuid4().hex[:12]}",
        feature_name=feature_name,
        description=description,
        proposed_by=proposed_by,
        new_components=new_components or [],
        reuses_topics=reuses_topics or [],
        reuses_jobs=reuses_jobs or [],
        reuses_adapters=reuses_adapters or [],
    )
    
    guardrails = get_guardrails()
    return guardrails.review_proposal(proposal)


def check_design_compliance(feature_name: str, reuses: Dict[str, List[str]]) -> Dict[str, Any]:
    """Quick check for design compliance."""
    total_reused = sum(len(v) for v in reuses.values())
    
    result = {
        "feature": feature_name,
        "compliant": total_reused > 0,
        "total_reused": total_reused,
        "warnings": [],
    }
    
    if total_reused == 0:
        result["warnings"].append(
            "Design does not reuse any existing components - requires justification"
        )
    
    return result
