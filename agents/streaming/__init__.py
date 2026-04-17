"""
Streaming agents package.

Production autonomous agents that subscribe to event streams.
8 mandatory agents per spec.
"""

from agents.streaming.market_analyst import MarketAnalystAgent
from agents.streaming.news_analyst import NewsAnalystAgent
from agents.streaming.risk_agent import RiskAgent
from agents.streaming.skeptic_agent import SkepticAgent
from agents.streaming.synthesizer_agent import SynthesizerAgent
from agents.streaming.strategy_agent import StrategyAgent
from agents.streaming.archivist_agent import ArchivistAgent
from agents.streaming.meta_audit_agent import MetaAuditAgent

__all__ = [
    'MarketAnalystAgent',
    'NewsAnalystAgent',
    'RiskAgent',
    'SkepticAgent',
    'SynthesizerAgent',
    'StrategyAgent',
    'ArchivistAgent',
    'MetaAuditAgent'
]
