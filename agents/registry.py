from agents.analyst_gemma import AnalystGemma
from agents.analyst_llama import AnalystLlama
from agents.skeptic import Skeptic
from agents.risk import RiskAgent
from agents.synthesizer import Synthesizer
from agents.archivist import Archivist
from agents.strategy_agent import StrategyAgent
from agents.meta_agent import MetaAuditAgent

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
