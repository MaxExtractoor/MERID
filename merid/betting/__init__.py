"""MERID Betting — Swarm-driven sports & event betting with aggregated odds.

Layers:
  1. Odds ingestion: OddsAPIClient fetches lines from aggregators (TheOddsAPI etc.)
  2. Event consensus: BettingEventConsensus merges sportsbook + prediction market + swarm
  3. Execution: Paper book + LiveBetPlan with edge/latency guards
  4. Risk & metrics: Brier scores, exposure caps, live vs pre-game tracking
"""

from merid.betting.models import (
    BettingEvent,
    BettingOutcome,
    BookOdds,
    BettingEventConsensus,
    LiveBetPlan,
    SettledBet,
    OddsSnapshot,
    EventState,
    BetStatus,
    MarketType,
)
from merid.betting.store import BettingStore, get_betting_store
from merid.betting.odds_client import OddsAPIClient, get_odds_client

__all__ = [
    "BettingEvent",
    "BettingEventConsensus",
    "BettingOutcome",
    "BettingStore",
    "BetStatus",
    "BookOdds",
    "EventState",
    "LiveBetPlan",
    "MarketType",
    "OddsAPIClient",
    "OddsSnapshot",
    "SettledBet",
    "get_betting_store",
    "get_odds_client",
]
