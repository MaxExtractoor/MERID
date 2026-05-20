"""
MERID Agent Layer - Institutional-Grade Multi-Agent System

Core agents for consensus, analysis, risk management, and execution.

Layer 1-3 of Master Build Directive - AGENT INFRASTRUCTURE

LEAN 15m KALSHI STACK (2026-05-13): Pruned for BTC/ETH/SOL/XRP/DOGE 15-minute trading.
Removed news, sentiment, meta, and synthesis agents - edge comes from microstructure.

Components:
- Core Agents: MarketAnalyst, Skeptic, Risk, Strategy
- Meta Agents: Strategy (trading)
- Optimization: Caching, Profiling, Resource Allocation
"""

import os

from agents.interface import AgentInterface, AgentState, VoteDecision
from agents.base_agent import BaseAgent
from agents.skeptic import Skeptic
from agents.risk import RiskAgent
from agents.strategy_agent import StrategyAgent

# PROFILE-GUARD: Skip reflection layer for kalshi_crypto_15m_v2 (sealed 15m stack doesn't need LLM reflection)
_is_15m_crypto = os.getenv("MERID_PROFILE", "") == "kalshi_crypto_15m_v2"
if not _is_15m_crypto:
    from agents.reflection_layer import ReflectionLayer, Reflection
else:
    # Create stub classes for kalshi_crypto_15m_v2 to prevent import errors
    ReflectionLayer = None
    Reflection = None

from agents.registry import load_agents
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
    """Get core consensus agents for lean 15m Kalshi stack."""
    return [
        Skeptic(agent_id="skeptic-01"),
        RiskAgent(agent_id="risk-01"),
        StrategyAgent(agent_id="strategy-agent-01"),
    ]


__all__ = [
    # Core Interfaces
    "AgentInterface",
    "AgentState",
    "VoteDecision",
    "BaseAgent",
    # Governance Agents
    "Skeptic",
    "RiskAgent",
    "StrategyAgent",
    # Meta Agents
    "ReflectionLayer",
    "Reflection",
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
