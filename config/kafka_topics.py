"""
MERID Kafka Topic Configuration

Defines all Kafka topics used in the MERID streaming architecture.
Topics are organized by domain and include schema information.

Topic naming convention: {domain}.{subdomain}.{symbol}
Examples:
  - prices.kraken.BTCUSD
  - features.kraken.BTCUSD
  - agent.opinions
  - trades.executed
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class TopicDomain(str, Enum):
    """Top-level topic domains."""
    PRICES = "prices"
    FEATURES = "features"
    AGENT = "agent"
    CONSENSUS = "consensus"
    TRADES = "trades"
    RISK = "risk"
    NEWS = "news"
    SENTIMENT = "sentiment"


@dataclass
class TopicConfig:
    """Configuration for a Kafka topic."""
    name: str
    partitions: int
    replication_factor: int
    retention_ms: int  # -1 for infinite
    cleanup_policy: str  # "delete" or "compact"
    description: str
    schema_version: str = "1.0"
    
    def to_rpk_command(self) -> str:
        """Generate rpk command to create this topic."""
        return (
            f"rpk topic create {self.name} "
            f"-p {self.partitions} "
            f"-r {self.replication_factor} "
            f"--config retention.ms={self.retention_ms} "
            f"--config cleanup.policy={self.cleanup_policy}"
        )


# =============================================================================
# TOPIC DEFINITIONS
# =============================================================================

# Price topics - raw tick data from exchanges
PRICE_TOPICS: Dict[str, TopicConfig] = {
    "prices.kraken.BTCUSD": TopicConfig(
        name="prices.kraken.BTCUSD",
        partitions=1,  # Single partition for ordering
        replication_factor=1,
        retention_ms=86400000,  # 24 hours
        cleanup_policy="delete",
        description="Raw BTC/USD ticks from Kraken",
    ),
    "prices.kraken.ETHUSD": TopicConfig(
        name="prices.kraken.ETHUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Raw ETH/USD ticks from Kraken",
    ),
    "prices.kraken.SOLUSD": TopicConfig(
        name="prices.kraken.SOLUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Raw SOL/USD ticks from Kraken",
    ),
    "prices.binance.BTCUSD": TopicConfig(
        name="prices.binance.BTCUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Raw BTC/USD ticks from Binance",
    ),
    "prices.binance.ETHUSD": TopicConfig(
        name="prices.binance.ETHUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Raw ETH/USD ticks from Binance",
    ),
}

# Feature topics - enriched data from Flink
FEATURE_TOPICS: Dict[str, TopicConfig] = {
    "features.kraken.BTCUSD": TopicConfig(
        name="features.kraken.BTCUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,  # 7 days
        cleanup_policy="delete",
        description="Enriched BTC features (OHLCV, volatility, momentum)",
    ),
    "features.kraken.ETHUSD": TopicConfig(
        name="features.kraken.ETHUSD",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Enriched ETH features",
    ),
    "features.late": TopicConfig(
        name="features.late",
        partitions=3,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Late-arriving price events for reprocessing",
    ),
}

# Agent topics - agent outputs and coordination
AGENT_TOPICS: Dict[str, TopicConfig] = {
    "agent.opinions": TopicConfig(
        name="agent.opinions",
        partitions=3,  # Multiple partitions for parallel consumption
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Agent trading opinions (AgentOpinion schema)",
    ),
    "agent.decisions": TopicConfig(
        name="agent.decisions",
        partitions=3,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Final agent decisions for audit trail",
    ),
    "agent.heartbeats": TopicConfig(
        name="agent.heartbeats",
        partitions=1,
        replication_factor=1,
        retention_ms=3600000,  # 1 hour
        cleanup_policy="delete",
        description="Agent health heartbeats",
    ),
}

# Consensus topics - TaCo consensus coordination
CONSENSUS_TOPICS: Dict[str, TopicConfig] = {
    "consensus.trade-plans": TopicConfig(
        name="consensus.trade-plans",
        partitions=1,  # Single partition for ordering
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Proposed trade plans from consensus",
    ),
    "consensus.risk-reviews": TopicConfig(
        name="consensus.risk-reviews",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Risk manager reviews of trade plans",
    ),
}

# Trade topics - execution events
TRADE_TOPICS: Dict[str, TopicConfig] = {
    "trades.intents": TopicConfig(
        name="trades.intents",
        partitions=3,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Trade intent events (before execution)",
    ),
    "trades.executed": TopicConfig(
        name="trades.executed",
        partitions=3,
        replication_factor=1,
        retention_ms=2592000000,  # 30 days
        cleanup_policy="delete",
        description="Executed trade events",
    ),
    "trades.cancelled": TopicConfig(
        name="trades.cancelled",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Cancelled trade events",
    ),
}

# Risk topics - risk management events
RISK_TOPICS: Dict[str, TopicConfig] = {
    "risk.alerts": TopicConfig(
        name="risk.alerts",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="Risk alerts (drawdown, exposure limits)",
    ),
    "risk.metrics": TopicConfig(
        name="risk.metrics",
        partitions=1,
        replication_factor=1,
        retention_ms=2592000000,
        cleanup_policy="delete",
        description="Portfolio risk metrics snapshots",
    ),
}

# News and sentiment topics
NEWS_TOPICS: Dict[str, TopicConfig] = {
    "news.items": TopicConfig(
        name="news.items",
        partitions=1,
        replication_factor=1,
        retention_ms=604800000,
        cleanup_policy="delete",
        description="News items with sentiment scores",
    ),
    "sentiment.social": TopicConfig(
        name="sentiment.social",
        partitions=1,
        replication_factor=1,
        retention_ms=86400000,
        cleanup_policy="delete",
        description="Social media sentiment aggregates",
    ),
}

# =============================================================================
# ALL TOPICS
# =============================================================================

ALL_TOPICS: Dict[str, TopicConfig] = {
    **PRICE_TOPICS,
    **FEATURE_TOPICS,
    **AGENT_TOPICS,
    **CONSENSUS_TOPICS,
    **TRADE_TOPICS,
    **RISK_TOPICS,
    **NEWS_TOPICS,
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_topic(name: str) -> Optional[TopicConfig]:
    """Get topic configuration by name."""
    return ALL_TOPICS.get(name)


def get_topics_by_domain(domain: TopicDomain) -> List[TopicConfig]:
    """Get all topics for a domain."""
    prefix = domain.value + "."
    return [t for name, t in ALL_TOPICS.items() if name.startswith(prefix)]


def get_price_topic(venue: str, symbol: str) -> str:
    """Build price topic name."""
    return f"prices.{venue.lower()}.{symbol}"


def get_feature_topic(venue: str, symbol: str) -> str:
    """Build feature topic name."""
    return f"features.{venue.lower()}.{symbol}"


def generate_init_script() -> str:
    """Generate shell script to create all topics."""
    lines = [
        "#!/bin/bash",
        "# MERID Kafka Topic Initialization",
        "# Generated by config/kafka_topics.py",
        "",
        'BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"',
        "",
        "echo 'Creating MERID Kafka topics...'",
        "",
    ]
    
    for topic in ALL_TOPICS.values():
        lines.append(f"# {topic.description}")
        lines.append(
            f"rpk topic create {topic.name} "
            f"--brokers $BROKERS "
            f"-p {topic.partitions} "
            f"-r {topic.replication_factor}"
        )
        lines.append("")
    
    lines.append("echo 'Topic creation complete!'")
    lines.append("rpk topic list --brokers $BROKERS")
    
    return "\n".join(lines)


# =============================================================================
# CONSUMER GROUP CONFIGURATION
# =============================================================================

CONSUMER_GROUPS = {
    # Flink jobs
    "merid-flink-features": {
        "topics": ["prices.*"],
        "description": "Flink feature computation job",
    },
    "merid-flink-windowed": {
        "topics": ["prices.*"],
        "description": "Flink windowed aggregation job",
    },
    
    # Agent consumers
    "merid-agents-features": {
        "topics": ["features.*"],
        "description": "Agent feature consumption",
    },
    "merid-agents-consensus": {
        "topics": ["agent.opinions", "consensus.*"],
        "description": "Agent consensus coordination",
    },
    
    # Risk consumers
    "merid-risk-monitor": {
        "topics": ["trades.*", "risk.*"],
        "description": "Risk monitoring service",
    },
    
    # Dashboard consumers
    "merid-dashboard": {
        "topics": ["trades.executed", "agent.opinions", "risk.alerts"],
        "description": "Dashboard WebSocket bridge",
    },
}


if __name__ == "__main__":
    print("MERID Kafka Topics\n" + "=" * 50)
    for domain in TopicDomain:
        topics = get_topics_by_domain(domain)
        if topics:
            print(f"\n{domain.value.upper()}")
            for t in topics:
                print(f"  - {t.name} ({t.partitions}p, {t.retention_ms//3600000}h retention)")
    
    print("\n\nInit Script:\n" + "=" * 50)
    print(generate_init_script()[:500] + "...")
