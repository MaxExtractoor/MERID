"""
Core Agents - Production-grade agent implementations per MASTER_SPEC v1.0

This module exports all 8 core agents defined in MASTER_SPEC Section 4.1:

| Agent ID | Role | Expertise | Risk Factor |
|----------|------|-----------|-------------|
| market-analyst-01 | Price pattern detection | 0.92 | 0.4 |
| news-analyst-01 | Sentiment analysis | 0.88 | 0.3 |
| risk-agent-01 | Risk assessment | 0.85 | 0.2 |
| skeptic-agent-01 | Adversarial challenge | 0.90 | 0.6 |
| synthesizer-agent-01 | Cross-signal synthesis | 0.87 | 0.4 |
| strategy-agent-01 | Trade strategy | 0.89 | 0.5 |
| archivist-agent-01 | Memory/history | 0.82 | 0.2 |
| meta-audit-agent-01 | System health | 0.86 | 0.3 |

All agents implement AgentInterface and follow the canonical
observe -> analyze -> vote -> reflect lifecycle.
"""

from agents.core.market_analyst import MarketAnalystAgent, get_market_analyst
from agents.core.news_analyst import NewsAnalystAgent, get_news_analyst
from agents.core.risk_agent import RiskAgent, get_risk_agent
from agents.core.skeptic_agent import SkepticAgent, get_skeptic_agent
from agents.core.synthesizer_agent import SynthesizerAgent, get_synthesizer_agent
from agents.core.strategy_agent import StrategyAgent, get_strategy_agent
from agents.core.archivist_agent import ArchivistAgent, get_archivist_agent
from agents.core.meta_audit_agent import MetaAuditAgent, get_meta_audit_agent

__all__ = [
    "MarketAnalystAgent",
    "NewsAnalystAgent",
    "RiskAgent",
    "SkepticAgent",
    "SynthesizerAgent",
    "StrategyAgent",
    "ArchivistAgent",
    "MetaAuditAgent",
    "get_market_analyst",
    "get_news_analyst",
    "get_risk_agent",
    "get_skeptic_agent",
    "get_synthesizer_agent",
    "get_strategy_agent",
    "get_archivist_agent",
    "get_meta_audit_agent",
    "get_all_agents",
    "AGENT_ROSTER",
]

AGENT_ROSTER = {
    "market-analyst-01": {
        "class": MarketAnalystAgent,
        "getter": get_market_analyst,
        "role": "Price pattern detection",
        "expertise": 0.92,
        "risk_factor": 0.4,
    },
    "news-analyst-01": {
        "class": NewsAnalystAgent,
        "getter": get_news_analyst,
        "role": "Sentiment analysis",
        "expertise": 0.88,
        "risk_factor": 0.3,
    },
    "risk-agent-01": {
        "class": RiskAgent,
        "getter": get_risk_agent,
        "role": "Risk assessment",
        "expertise": 0.85,
        "risk_factor": 0.2,
    },
    "skeptic-agent-01": {
        "class": SkepticAgent,
        "getter": get_skeptic_agent,
        "role": "Adversarial challenge",
        "expertise": 0.90,
        "risk_factor": 0.6,
    },
    "synthesizer-agent-01": {
        "class": SynthesizerAgent,
        "getter": get_synthesizer_agent,
        "role": "Cross-signal synthesis",
        "expertise": 0.87,
        "risk_factor": 0.4,
    },
    "strategy-agent-01": {
        "class": StrategyAgent,
        "getter": get_strategy_agent,
        "role": "Trade strategy",
        "expertise": 0.89,
        "risk_factor": 0.5,
    },
    "archivist-agent-01": {
        "class": ArchivistAgent,
        "getter": get_archivist_agent,
        "role": "Memory/history",
        "expertise": 0.82,
        "risk_factor": 0.2,
    },
    "meta-audit-agent-01": {
        "class": MetaAuditAgent,
        "getter": get_meta_audit_agent,
        "role": "System health",
        "expertise": 0.86,
        "risk_factor": 0.3,
    },
}


def get_all_agents():
    """
    Get all core agent instances.
    
    Returns:
        Dict mapping agent_id to agent instance
    """
    return {
        agent_id: info["getter"]()
        for agent_id, info in AGENT_ROSTER.items()
    }
