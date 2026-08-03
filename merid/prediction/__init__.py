"""MERID Prediction Market Module — Kalshi-first, US-compliant.

Provides:
- Mode gating (SIM/PAPER/LIVE) with Polymarket blocking
- PredictionMarketModel: implied probabilities, edge, lifecycle
- KalshiStrategy: edge thresholds, time-to-expiry, position sizing
- PredictionMarketRisk: per-market limits, pre-trade checks, kill switch
- API endpoints and alerts for operator dashboard
"""

from merid.prediction.model import (
    ContractState,
    MarketSnapshot,
    PredictionMarketModel,
)
from merid.prediction.risk import (
    PredictionMarketRisk,
    PredictionRiskConfig,
    PreTradeCheck,
)
from merid.prediction.strategy import (
    KalshiStrategy,
    StrategyConfig,
    StrategySignal,
)
from merid.prediction.venue_gate import VenueGate
from merid.prediction.trading_mode import TradingMode
# LEGACY REMOVAL: Debate module deleted - imports removed
# from merid.prediction.debate import (
#     AgentTeam,
#     DebateArgument,
#     DebateBacktester,
#     DebateSession,
#     DebateStore,
#     RewardEntry,
#     RewardParameterSweep,
#     get_debate_store,
# )
from merid.prediction.agent_grid_config import (
    AgentGridConfig,
    get_agent_grid_config,
)
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
from merid.prediction.kalshi_tools import register_kalshi_tools
# CRITICAL FIX (2026-07-17): RollingBuffer for signal generation bias prevention
from merid.prediction.rolling_buffer import (
    RollingBuffer,
    InputDeclaration,
    WarmupCalculator,
    SignalGeneratorWithBuffers,
    create_crypto_signal_generator,
)
#     select_top_edges,
# )

__all__ = [
    # LEGACY REMOVAL: Debate module deleted - removed AgentTeam, DebateArgument, DebateBacktester, DebateSession, DebateStore, RewardEntry, RewardParameterSweep, get_debate_store
    # LEGACY REMOVAL: Consensus module deleted - removed PredictionConsensusStore, PredictionInstrument, PredictionOpinion, PredictionPlan, get_prediction_consensus_store
    # LEGACY REMOVAL: session_guard, agent_grid, trading_agent, social_broadcaster, crypto_top_edge moved to archive/legacy/
    "ContractState",
    "KalshiStrategy",
    "MarketSnapshot",
    "PredictionMarketModel",
    "PredictionMarketRisk",
    "PredictionRiskConfig",
    "PreTradeCheck",
    "StrategyConfig",
    "StrategySignal",
    "TradingMode",
    "VenueGate",
    # "AgentGrid",  # moved to archive/legacy/
    "AgentGridConfig",
    # "KalshiTradingAgent",  # moved to archive/legacy/
    # "SessionGuard",  # moved to archive/legacy/
    # "get_agent_grid",  # moved to archive/legacy/
    "get_agent_grid_config",
    # "get_session_guard",  # moved to archive/legacy/
    "register_kalshi_tools",
    "PortfolioRiskAgent",
    # "KalshiSocialBroadcaster",  # moved to archive/legacy/
    # "get_social_broadcaster",  # moved to archive/legacy/
    # CRITICAL FIX (2026-07-17): RollingBuffer for signal generation bias prevention
    "RollingBuffer",
    "InputDeclaration",
    "WarmupCalculator",
    "SignalGeneratorWithBuffers",
    "create_crypto_signal_generator",
    # Cross-asset top edge arbiter
    # "CandidateSignal",  # moved to archive/legacy/
    # "CrossAssetCycleResult",  # moved to archive/legacy/
    # "CryptoTopEdgeArbiter",  # moved to archive/legacy/
    # "CRYPTO_ASSETS",  # moved to archive/legacy/
    # "MEAN_REVERSION_TIMEFRAMES",  # moved to archive/legacy/
    # "get_crypto_top_edge_arbiter",  # moved to archive/legacy/
    # "reset_crypto_top_edge_arbiter",  # moved to archive/legacy/
    # "select_top_edges",  # moved to archive/legacy/
    # "No Surprises" execution guards - moved to archive/legacy/
]
