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

__all__ = [
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
]
