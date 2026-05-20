"""
Streaming agents package.

Production autonomous agents that subscribe to event streams.
8 mandatory agents per spec.
"""

from agents.streaming.market_analyst import MarketAnalystAgent
# NewsAnalystAgent moved to legacy (PRODUCTION FIX 2026-05-13)
from agents.streaming.risk_agent import RiskAgent
from agents.streaming.skeptic_agent import SkepticAgent
# SynthesizerAgent moved to legacy (PRODUCTION FIX 2026-05-13)
from agents.streaming.strategy_agent import StrategyAgent
# ArchivistAgent moved to legacy (PRODUCTION FIX 2026-05-13)
# MetaAuditAgent moved to legacy (PRODUCTION FIX 2026-05-13)

__all__ = [
    'MarketAnalystAgent',
    # 'NewsAnalystAgent',  # Moved to legacy
    'RiskAgent',
    'SkepticAgent',
    # 'SynthesizerAgent',  # Moved to legacy
    'StrategyAgent',
    # 'ArchivistAgent',  # Moved to legacy
    # 'MetaAuditAgent',  # Moved to legacy
]
