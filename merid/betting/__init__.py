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
from merid.betting.live_sports import (
    LiveBettingEngine,
    LiveOddsEngine,
    SportsBettingManager,
    SportsForecastEngine,
    SportsInstrumentBridge,
    SportsOddsFeed,
    QuestEngine,
    get_sports_betting_manager,
)
from merid.betting.optic_odds import (
    OpticOddsClient,
    OpticOddsPoller,
    OddsSnapshotStore,
    get_optic_odds_client,
    get_optic_odds_poller,
    get_snapshot_store,
)
from merid.betting.live_odds_cache import (
    LiveOddsCache,
    LiveOddsCacheManager,
    OddsLatencyTracker,
    OddsPushManager,
    get_live_odds_cache_manager,
)
from merid.betting.sports_debate import (
    SportsDebateCoordinator,
    SportsDebateSession,
    SportsDebateLiftTracker,
    get_sports_debate_coordinator,
)
from merid.betting.anomaly_detection import (
    AnomalyEngine,
    AnomalyRecord,
    AnomalyType,
    AnomalySeverity,
    get_anomaly_engine,
)

__all__ = [
    "BettingEvent",
    "BettingEventConsensus",
    "BettingOutcome",
    "BettingStore",
    "BetStatus",
    "BookOdds",
    "EventState",
    "LiveBetPlan",
    "LiveBettingEngine",
    "LiveOddsEngine",
    "MarketType",
    "OddsAPIClient",
    "OddsSnapshot",
    "QuestEngine",
    "SettledBet",
    "SportsBettingManager",
    "SportsForecastEngine",
    "SportsInstrumentBridge",
    "SportsOddsFeed",
    "get_betting_store",
    "get_odds_client",
    "get_sports_betting_manager",
    "OpticOddsClient",
    "OpticOddsPoller",
    "OddsSnapshotStore",
    "get_optic_odds_client",
    "get_optic_odds_poller",
    "get_snapshot_store",
    "LiveOddsCache",
    "LiveOddsCacheManager",
    "OddsLatencyTracker",
    "OddsPushManager",
    "get_live_odds_cache_manager",
    "SportsDebateCoordinator",
    "SportsDebateSession",
    "SportsDebateLiftTracker",
    "get_sports_debate_coordinator",
    "AnomalyEngine",
    "AnomalyRecord",
    "AnomalyType",
    "AnomalySeverity",
    "get_anomaly_engine",
]
