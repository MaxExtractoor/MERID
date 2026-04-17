"""
Legacy agent registry — REFERENCE ONLY (T-004 Zero-Trust Audit).

These 8 non-streaming agents are NOT used in production.  The canonical
production agent initialization is in agents/agent_mesh.py (AgentMesh),
which manages 8 streaming agents as continuous async tasks.

This module is kept for backward-compatible imports and reference.
Do NOT use load_agents() for production orchestration.
"""

from agents.agent_framework import AgentRegistry
import logging

# Global registry instance
_registry = AgentRegistry()


def register_agent(agent):
    """Register an agent with the global registry."""
    _registry.register(agent)


def get_registry():
    """Get the global agent registry."""
    return _registry


def load_agents():
    """LEGACY/REFERENCE: Instantiate 8 non-streaming agents.

    WARNING: These are NOT the production agents.  Production uses
    agents.agent_mesh.AgentMesh which runs 8 streaming agents.
    This function is retained only for tests and reference.
    """
    from utils.logger import get_logger
    logging.getLogger(__name__).warning(
        "load_agents() called — these are LEGACY non-streaming agents. "
        "Production uses agents.agent_mesh.AgentMesh."
    )
    from agents.analyst_gemma import AnalystGemma
    from agents.analyst_llama import AnalystLlama
    from agents.skeptic import Skeptic
    from agents.risk import RiskAgent
    from agents.synthesizer import Synthesizer
    from agents.archivist import Archivist
    from agents.strategy_agent import StrategyAgent
    from agents.meta_agent import MetaAuditAgent

    return [
        AnalystGemma(),
        AnalystLlama(),
        Skeptic(),
        RiskAgent(),
        Synthesizer(),
        Archivist(),
        StrategyAgent(),
        MetaAuditAgent(),
    ]
