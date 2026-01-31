from agents.analyst_gemma import AnalystGemma
from agents.analyst_llama import AnalystLlama
from agents.skeptic import Skeptic
from agents.risk import RiskAgent
from agents.synthesizer import Synthesizer
from agents.archivist import Archivist
from agents.strategy_agent import StrategyAgent
from agents.meta_agent import MetaAuditAgent
from agents.agent_framework import AgentRegistry

# Global registry instance
_registry = AgentRegistry()

def register_agent(agent):
    """Register an agent with the global registry."""
    _registry.register(agent)

def get_registry():
    """Get the global agent registry."""
    return _registry

def load_agents():
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
