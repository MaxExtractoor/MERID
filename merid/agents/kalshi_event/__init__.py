"""merid.agents.kalshi_event — General (non-crypto) Kalshi event strategy agents.

Handles macro, economics, politics, climate, sports, tech, culture, science,
and financial event contracts on Kalshi.  All agents use the shared Kalshi
client and risk primitives from ``merid.kalshi``.

Agents:
  - OddsAwareSportsAgent — sports event contracts with sportsbook odds blending
  - MarketResearchAgent  — macro/news-driven thesis generation (from research.py)
  - StrategyDesignerAgent — translates research into executable strategy configs

Domain-specific features:
  - Macro calendar awareness (FOMC, CPI, NFP, etc.)
  - Sports odds ingestion and consensus blending
  - Political event polling integration
"""

from merid.agents.sports_odds import (
    OddsAwareSportsAgent,
    SportsOddsStrategy,
    get_sports_odds_agent,
)
from merid.agents.research import (
    MarketResearchAgent,
    PredictionMarketAgentV2 as PredictionMarketAgent,
)
from merid.agents.strategy import (
    StrategyDesignerAgent,
)

# Shared event helpers
from merid.kalshi import (
    is_crypto_market,
    market_domain,
    KALSHI_EVENT_CATEGORIES,
)


def is_event_market(ticker: str) -> bool:
    """Return True if ticker belongs to a non-crypto Kalshi event market."""
    return not is_crypto_market(ticker)


EVENT_AGENTS = {
    "sports_odds": OddsAwareSportsAgent,
    "market_research": MarketResearchAgent,
    "prediction_market": PredictionMarketAgent,
    "strategy_designer": StrategyDesignerAgent,
}

__all__ = [
    "OddsAwareSportsAgent",
    "SportsOddsStrategy",
    "get_sports_odds_agent",
    "MarketResearchAgent",
    "PredictionMarketAgent",
    "StrategyDesignerAgent",
    "EVENT_AGENTS",
    "is_event_market",
    "KALSHI_EVENT_CATEGORIES",
    "market_domain",
]
