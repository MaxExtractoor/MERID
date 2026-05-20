"""
LEGACY MODULE (2026-05-14)

This module contains legacy research agents that are NOT for 15m Kalshi live trading.
These agents are kept for historical reference, backtesting, or research purposes only.

To enable these agents, set MERID_ENABLE_RESEARCH_AGENTS=True in .env or settings.yaml.

Classification:
- PredictionMarketAgentV2: Legacy research agent (non-critical)
- MarketResearchAgent: Legacy research agent (non-critical)
- CryptoSignalsAgent: Legacy research agent (non-critical)

Status: These agents are gated behind MERID_ENABLE_RESEARCH_AGENTS feature flag and
will not be loaded in production without explicit enablement.
"""

IS_LEGACY_MODULE = True
