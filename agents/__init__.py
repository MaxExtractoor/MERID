"""
MERID Agent Layer - Institutional-Grade Multi-Agent System

Core agents for consensus, analysis, risk management, and execution.
"""

from agents.interface import AgentInterface, AgentState, VoteDecision
from agents.base_agent import BaseAgent
from agents.analyst_gemma import AnalystGemma
from agents.analyst_llama import AnalystLlama
from agents.skeptic import Skeptic
from agents.risk import RiskAgent
from agents.synthesizer import Synthesizer
from agents.archivist import Archivist
from agents.strategy_agent import StrategyAgent
from agents.meta_agent import MetaAuditAgent
from agents.reflection_layer import ReflectionLayer, Reflection
from agents.registry import load_agents
from agents.twitter_agent import TwitterAgent
from agents.telegram_agent import TelegramAgent
from agents.news_monitor_agent import NewsMonitorAgent


def get_all_agents():
    """Get all registered agents."""
    return load_agents()


def get_core_agents():
    """Get core consensus agents."""
    return [
        AnalystGemma(agent_id="analyst-gemma-01"),
        AnalystLlama(agent_id="analyst-llama-01"),
        Skeptic(agent_id="skeptic-01"),
        RiskAgent(agent_id="risk-01"),
        Synthesizer(agent_id="synthesizer-01"),
        Archivist(agent_id="archivist-01"),
        StrategyAgent(agent_id="strategy-agent-01"),
        MetaAuditAgent(agent_id="meta-audit-01"),
    ]


__all__ = [
    "AgentInterface",
    "AgentState",
    "VoteDecision",
    "BaseAgent",
    "AnalystGemma",
    "AnalystLlama",
    "Skeptic",
    "RiskAgent",
    "Synthesizer",
    "Archivist",
    "StrategyAgent",
    "MetaAuditAgent",
    "ReflectionLayer",
    "Reflection",
    "load_agents",
    "TwitterAgent",
    "TelegramAgent",
    "NewsMonitorAgent",
    "get_all_agents",
    "get_core_agents",
]
