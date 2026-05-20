"""
Core Agents - Production-grade agent implementations per MASTER_SPEC v1.0

LEAN 15m KALSHI STACK (2026-05-13): Pruned for BTC/ETH/SOL/XRP/DOGE 15-minute trading.
Removed news, sentiment, meta, and synthesis agents - edge comes from microstructure.

| Agent ID | Role | Expertise | Risk Factor |
|----------|------|-----------|-------------|
| market-analyst-01 | Price pattern detection | 0.92 | 0.4 |
| risk-agent-01 | Risk assessment | 0.85 | 0.2 |
| skeptic-agent-01 | Adversarial challenge | 0.90 | 0.6 |
| strategy-agent-01 | Trade strategy | 0.89 | 0.5 |

Removed (moved to legacy/):
- NewsAnalystAgent (news analysis - redundant for 15m microstructure edge)
- SynthesizerAgent (SignalFusionAgent used instead)
- ArchivistAgent (moved to research/offline)
- MetaAuditAgent (overkill for small dedicated agent set)

All agents implement AgentInterface and follow the canonical
observe -> analyze -> vote -> reflect lifecycle.
"""

from agents.core.market_analyst import MarketAnalystAgent, get_market_analyst
from agents.core.risk_agent import RiskAgent, get_risk_agent
from agents.core.skeptic_agent import SkepticAgent, get_skeptic_agent
from agents.core.strategy_agent import StrategyAgent, get_strategy_agent

__all__ = [
    "MarketAnalystAgent",
    "RiskAgent",
    "SkepticAgent",
    "StrategyAgent",
    "get_market_analyst",
    "get_risk_agent",
    "get_skeptic_agent",
    "get_strategy_agent",
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
    "strategy-agent-01": {
        "class": StrategyAgent,
        "getter": get_strategy_agent,
        "role": "Trade strategy",
        "expertise": 0.89,
        "risk_factor": 0.5,
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
