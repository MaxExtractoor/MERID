"""
MERID Agent Layer - Institutional-Grade Multi-Agent System

Core agents for consensus, analysis, risk management, and execution.

Layer 1-3 of Master Build Directive - AGENT INFRASTRUCTURE

Components:
- Core Agents: Analysts, Skeptic, Risk, Synthesizer
- Meta Agents: Archivist, Strategy, Meta-Audit
- Optimization: Caching, Profiling, Resource Allocation
- Social Agents: Twitter, Telegram, News Monitor
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
from agents.fast_prediction_arbitrage_analyst import register_fast_agent
from agents.optimization import (
    AgentOptimizer,
    get_agent_optimizer,
    OptimizedCache,
    CacheStrategy,
    AgentProfiler,
    BatchOptimizer,
    ResourceAllocator,
    ComputeBudget,
    cached,
    profiled,
    budget_limited,
)


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
    # Core Interfaces
    "AgentInterface",
    "AgentState",
    "VoteDecision",
    "BaseAgent",
    # Analyst Agents
    "AnalystGemma",
    "AnalystLlama",
    # Governance Agents
    "Skeptic",
    "RiskAgent",
    "Synthesizer",
    # Meta Agents
    "Archivist",
    "StrategyAgent",
    "MetaAuditAgent",
    "ReflectionLayer",
    "Reflection",
    # Social Agents
    "TwitterAgent",
    "TelegramAgent",
    "NewsMonitorAgent",
    # Registry
    "load_agents",
    "get_all_agents",
    "get_core_agents",
    # Optimization
    "AgentOptimizer",
    "get_agent_optimizer",
    "OptimizedCache",
    "CacheStrategy",
    "AgentProfiler",
    "BatchOptimizer",
    "ResourceAllocator",
    "ComputeBudget",
    "cached",
    "profiled",
    "budget_limited",
]

# Register the fast agent for experiments
try:
    register_fast_agent()
except Exception as e:
    print(f"Warning: Could not register fast agent: {e}")
