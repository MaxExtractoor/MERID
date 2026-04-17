"""Default adapter registration for the unified trading router.

Kalshi-only: Only PaperTradingAdapter is actively used.
Legacy adapters (Coinbase, Alpaca, PumpFun) are preserved in _legacy/ for reference.
"""

from trading.adapters.paper import PaperTradingAdapter

# Side effect: KalshiPredictionAdapter registers itself on import — required for
# MeridLoop/get_adapter("kalshi") in KALSHI_PRIMARY deployments.
import trading.adapters.kalshi  # noqa: F401

# LEGACY: Additional adapters preserved in _legacy folder

__all__ = [
    "PaperTradingAdapter",
]
