"""Default adapter registration for the unified trading router."""

from trading.adapters.coinbase import CoinbaseSpotAdapter
from trading.adapters.kalshi import KalshiPredictionAdapter
from trading.adapters.paper import PaperTradingAdapter
from trading.adapters.pumpfun import PumpFunAdapter
from trading.adapters.alpaca import AlpacaEquitiesAdapter

__all__ = [
    "PaperTradingAdapter",
    "CoinbaseSpotAdapter",
    "PumpFunAdapter",
    "KalshiPredictionAdapter",
    "AlpacaEquitiesAdapter",
]
