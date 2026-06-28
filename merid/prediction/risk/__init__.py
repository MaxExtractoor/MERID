"""merid.prediction.risk — prediction market risk + shared Kalshi risk engine.

Re-exports everything from the original ``risk.py`` module (now
``_prediction_risk.py``) so that existing imports such as::

    from merid.prediction.risk import PredictionMarketRisk

continue to work unchanged.  Also exports the new shared Kalshi risk engine.
"""

# ── Original prediction-market risk layer (was risk.py) ───────────────
from merid.prediction.risk._prediction_risk import (  # noqa: F401
    CategoryLimit,
    CycleCapConfig,
    CycleCapTracker,
    DailyPnL,
    MarketExposure,
    PredictionMarketRisk,
    PredictionRiskConfig,
    PreTradeCheck,
    RiskAction,
    get_prediction_risk,
)

# ── Shared Kalshi risk engine (deprecated - moved to archive/legacy/) ──
# KalshiRiskConfig and KalshiRiskEngine moved to archive/legacy/ during 15m stack cleanup
# Use merid.event_venues.kalshi.kalshi_risk for venue-level risk configuration

# ── Fear/Greed, Volatility & Sizing — Canonical Types ─────────────────
from merid.prediction.risk.sentiment_vol_types import (  # noqa: F401
    FearGreedRegime,
    VolatilityRegime,
    UncertaintyRegime,
    SentimentScalar,
    VolatilityScalar,
    SizingMultiplier,
    SentimentVolConfig,
    get_sentiment_vol_config,
    compute_sentiment_regime,
    compute_volatility_regime,
    compute_uncertainty_regime,
    compute_sizing_multiplier,
    create_sentiment_scalar,
    create_volatility_scalar,
)

# ── Fear/Greed, Volatility & Sizing — Centralized Service ────────────
from merid.prediction.risk.sentiment_vol_service import (  # noqa: F401
    SentimentVolService,
    get_sentiment_vol_service,
    get_current_sentiment,
    get_current_volatility,
    get_current_sizing_multiplier,
    feed_price_update,
    feed_sentiment_update,
    should_reduce_position_size,
    explain_sizing_for_position,
)

# ── Fee schedule re-export (single source in position_sizer) ──────────
from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents  # noqa: F401
