"""merid.prediction.forecasters — Heterogeneous forecaster models.

Sprint B: Diverse forecasters so consensus has real wisdom-of-crowds value.
Each forecaster produces an independent YES probability + confidence for a
Kalshi market, using different methodologies:

- EdgeModel (existing) — spot-relative + spread + time decay ensemble
- MomentumForecaster  — volume/OI trends, price momentum
- MeanReversionForecaster — orderbook imbalance, mean reversion toward fair value
- MacroRegimeForecaster  — fear/greed, cross-timeframe, volatility regime
- OrderbookForecaster    — bid/ask imbalance, spread compression, depth-weighted FV
- TimeSeriesForecaster   — AR(2) model, EWMA volatility, OU half-life, Hurst exponent
- ExternalSentimentForecaster — news/X sentiment, fear/greed contrarian, divergence

All forecasters are managed by ForecasterRegistry which:
1. Runs each on every market snapshot
2. Logs each forecast to CalibrationStore (Sprint A)
3. Returns an ensemble view the TradingAgent can use
"""

from merid.prediction.forecasters.base import (
    Forecaster,
    ForecastResult,
)
from merid.prediction.forecasters.momentum import MomentumForecaster
from merid.prediction.forecasters.mean_reversion import MeanReversionForecaster
from merid.prediction.forecasters.macro_regime import MacroRegimeForecaster
from merid.prediction.forecasters.orderbook import OrderbookForecaster
from merid.prediction.forecasters.time_series import TimeSeriesForecaster
from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
from merid.prediction.forecasters.registry import (
    ForecasterRegistry,
    EnsembleForecast,
    get_forecaster_registry,
)

__all__ = [
    "Forecaster",
    "ForecastResult",
    "MomentumForecaster",
    "MeanReversionForecaster",
    "MacroRegimeForecaster",
    "OrderbookForecaster",
    "TimeSeriesForecaster",
    "ExternalSentimentForecaster",
    "ForecasterRegistry",
    "EnsembleForecast",
    "get_forecaster_registry",
]
