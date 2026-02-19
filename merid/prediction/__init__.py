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
from merid.prediction.venue_gate import (
    TradingMode,
    VenueGate,
)
from merid.prediction.consensus import (
    PredictionConsensusStore,
    PredictionInstrument,
    PredictionOpinion,
    PredictionPlan,
    ResolvedMarket,
    get_prediction_consensus_store,
)
from merid.prediction.debate import (
    AgentTeam,
    DebateArgument,
    DebateBacktester,
    DebateSession,
    DebateStore,
    RewardEntry,
    RewardParameterSweep,
    get_debate_store,
)
from merid.prediction.agent_grid_config import (
    AgentGridConfig,
    get_agent_grid_config,
)
from merid.prediction.session_guard import (
    SessionGuard,
    get_session_guard,
)
from merid.prediction.agent_grid import (
    AgentGrid,
    get_agent_grid,
)
from merid.prediction.trading_agent import KalshiTradingAgent
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
from merid.prediction.kalshi_tools import register_kalshi_tools
from merid.prediction.social_broadcaster import (
    KalshiSocialBroadcaster,
    get_social_broadcaster,
)

__all__ = [
    "AgentTeam",
    "ContractState",
    "DebateArgument",
    "DebateBacktester",
    "DebateSession",
    "DebateStore",
    "KalshiStrategy",
    "MarketSnapshot",
    "PredictionConsensusStore",
    "PredictionInstrument",
    "PredictionMarketModel",
    "PredictionMarketRisk",
    "PredictionOpinion",
    "PredictionPlan",
    "PredictionRiskConfig",
    "PreTradeCheck",
    "ResolvedMarket",
    "RewardEntry",
    "RewardParameterSweep",
    "StrategyConfig",
    "StrategySignal",
    "TradingMode",
    "VenueGate",
    "get_debate_store",
    "get_prediction_consensus_store",
    "AgentGrid",
    "AgentGridConfig",
    "KalshiTradingAgent",
    "PortfolioRiskAgent",
    "SessionGuard",
    "get_agent_grid",
    "get_agent_grid_config",
    "get_session_guard",
    "register_kalshi_tools",
    "KalshiSocialBroadcaster",
    "get_social_broadcaster",
]
