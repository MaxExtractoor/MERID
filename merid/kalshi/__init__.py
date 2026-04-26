"""merid.kalshi — Consolidated Kalshi integration module.

This is the **single entry point** for all Kalshi prediction-market
functionality in MERID.  It re-exports the canonical client, data models,
risk primitives, and order routing from the implementation layer at
``merid.event_venues.kalshi``, plus crypto-specific helpers that live
directly in this package.

Usage::

    from merid.kalshi import (
        # Client
        KalshiVenueClient, get_kalshi_client, KalshiConfig,
        # Models
        KalshiMarket, KalshiOrder, KalshiPosition, KalshiBalance,
        KalshiOrderBook, KalshiTrade, KalshiOutcome, KalshiMarketState,
        # Order routing
        OrderIntent, OrderResult, route_order, simulate_paper_fill,
        # Risk
        KalshiRiskManager, get_kalshi_risk,
        # Market catalog
        KalshiMarketCatalog, get_market_catalog,
        # WebSocket
        KalshiWebSocket, KalshiWebSocketBridge, get_ws_bridge,
    )

Two product lines share these primitives:
  - **Event markets** (macro, econ, politics) — ``merid.agents.kalshi_event``
  - **Crypto markets** (BTC/ETH ranges, highs) — ``merid.agents.kalshi_crypto``
"""

# ── Client ────────────────────────────────────────────────────────────────
from merid.event_venues.kalshi.client import (
    KalshiVenueClient,
    KalshiSessionError,
    KalshiBusinessError,
    KalshiBusinessReject,
    KalshiTokenBucket,
    KALSHI_RATE_TIERS,
    KALSHI_REJECT_REASONS,
    KALSHI_BUSINESS_REJECT_CAUSES,
    parse_fix,
    handle_fix_reject,
    get_kalshi_client,
)

# ── Data models ───────────────────────────────────────────────────────────
from merid.event_venues.kalshi.models import (
    KalshiBalance,
    KalshiConfig,
    KalshiMarket,
    KalshiOrder,
    KalshiOrderBook,
    KalshiOutcome,
    KalshiPosition,
    KalshiTrade,
)

# ── Order routing ─────────────────────────────────────────────────────────
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    route_order,
    simulate_paper_fill,
    KALSHI_CHANNEL_PRICE,
    KALSHI_CHANNEL_TRADE,
    KALSHI_CHANNEL_ORDERBOOK,
    KALSHI_CHANNEL_ORDER_FILL,
    KALSHI_CHANNEL_ORDER_REJECT,
)

# ── Risk ──────────────────────────────────────────────────────────────────
from merid.event_venues.kalshi.kalshi_risk import (
    KalshiRiskManager,
    KalshiRiskConfig,
    kalshi_fee_cents,
    kelly_size_kalshi,
    dynamic_position_sizes,
    multi_market_kelly_sizes,
    get_kalshi_risk,
    edge_from_prediction,
    kelly_size_from_kalman,
)

# ── Market catalog ────────────────────────────────────────────────────────
from merid.event_venues.kalshi.market_catalog import (
    KalshiMarketCatalog,
    CatalogMarket,
    CatalogSnapshot,
    get_market_catalog,
)

# ── Market state ──────────────────────────────────────────────────────────
from merid.event_venues.kalshi.market_state import (
    KalshiMarketStateStore,
    get_kalshi_market_state_store,
)
from merid.event_venues.kalshi.models import KalshiMarketState

# ── WebSocket ─────────────────────────────────────────────────────────────
from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.ws_bridge import (
    KalshiWebSocketBridge,
    get_ws_bridge,
)

# ── Trading ───────────────────────────────────────────────────────────────
from merid.event_venues.kalshi.trading import KalshiTrader

# ── Backtesting ───────────────────────────────────────────────────────────
from merid.event_venues.kalshi.backtest import (
    MarketSnapshot,
    TradeDecision,
    BacktestState,
    PriceCandle,
    backtest,
    backtest_summary,
    backtest_kalman_strategy,
)

# ── Volume / analytics ────────────────────────────────────────────────────
from merid.event_venues.kalshi.volume_monitor import (
    VolumeMonitor,
    get_volume_monitor,
    Kalman1D,
    PriceKalman,
    tune_kalman_params,
)
from merid.event_venues.kalshi.trade_analytics import (
    compute_vwap,
    detect_large_trades,
)

# ── Crypto-specific helpers (local to this package) ───────────────────────
from merid.kalshi.market_registry import KalshiMarketRegistry, KalshiMarketInfo
from merid.kalshi.kalshi_crypto_intents import (
    KalshiCryptoOpinion,
    build_kalshi_crypto_intent,
    maybe_execute_kalshi_opinion,
)
from merid.kalshi.agent_mode_router import AgentModeRouter, get_agent_mode_router
from merid.kalshi.execution_telemetry import ExecutionTelemetryTracker

# ── Macro overlay (Phase 3) ───────────────────────────────────────────────
from merid.kalshi.macro_models import (
    MacroCategory,
    MacroRegime,
    VolatilityRegime,
    MacroState,
    MacroMarketState,
    MacroConvictionScore,
    AssetMacroSensitivity,
    DEFAULT_ASSET_SENSITIVITIES,
)
from merid.kalshi.macro_overlay import (
    KalshiMacroOverlay,
    MacroConvictionScorer,
    get_kalshi_macro_overlay,
    reset_kalshi_macro_overlay,
)

# ── Category helpers ──────────────────────────────────────────────────────
KALSHI_CRYPTO_TICKERS = {"KXBTC", "KXETH", "KXSOL", "KXDOGE", "KXXRP"}

KALSHI_EVENT_CATEGORIES = frozenset({
    "economics", "macro", "politics", "climate", "sports",
    "tech", "culture", "science", "financials", "other",
})

KALSHI_CRYPTO_CATEGORIES = frozenset({"crypto"})


def is_crypto_market(ticker: str) -> bool:
    """Return True if ticker belongs to a Kalshi crypto market."""
    prefix = ticker.split("-")[0] if "-" in ticker else ticker
    return prefix.upper() in KALSHI_CRYPTO_TICKERS


def market_domain(ticker: str) -> str:
    """Return 'crypto' or 'event' for a given Kalshi ticker."""
    return "crypto" if is_crypto_market(ticker) else "event"


__all__ = [
    # Client
    "KalshiVenueClient", "get_kalshi_client", "KalshiConfig",
    "KalshiSessionError", "KalshiBusinessError", "KalshiBusinessReject",
    "KalshiTokenBucket", "KALSHI_RATE_TIERS",
    "KALSHI_REJECT_REASONS", "KALSHI_BUSINESS_REJECT_CAUSES",
    "parse_fix", "handle_fix_reject",
    # Models
    "KalshiMarket", "KalshiOrder", "KalshiPosition", "KalshiBalance",
    "KalshiOrderBook", "KalshiTrade", "KalshiOutcome",
    # Order routing
    "OrderIntent", "OrderResult", "route_order", "simulate_paper_fill",
    "KALSHI_CHANNEL_PRICE", "KALSHI_CHANNEL_TRADE", "KALSHI_CHANNEL_ORDERBOOK",
    "KALSHI_CHANNEL_ORDER_FILL", "KALSHI_CHANNEL_ORDER_REJECT",
    # Risk
    "KalshiRiskManager", "KalshiRiskConfig", "get_kalshi_risk",
    "kalshi_fee_cents", "kelly_size_kalshi",
    "dynamic_position_sizes", "multi_market_kelly_sizes",
    "edge_from_prediction", "kelly_size_from_kalman",
    # Catalog
    "KalshiMarketCatalog", "CatalogMarket", "CatalogSnapshot", "get_market_catalog",
    # Market state
    "KalshiMarketState", "KalshiMarketStateStore", "get_kalshi_market_state_store",
    # WebSocket
    "KalshiWebSocket", "KalshiWebSocketBridge", "get_ws_bridge",
    # Trading
    "KalshiTrader",
    # Backtest
    "MarketSnapshot", "TradeDecision", "BacktestState", "PriceCandle",
    "backtest", "backtest_summary", "backtest_kalman_strategy",
    # Volume / analytics
    "VolumeMonitor", "get_volume_monitor", "Kalman1D", "PriceKalman",
    "tune_kalman_params", "compute_vwap", "detect_large_trades",
    # Crypto-specific
    "KalshiMarketRegistry", "KalshiMarketInfo",
    "KalshiCryptoOpinion", "build_kalshi_crypto_intent",
    "maybe_execute_kalshi_opinion",
    "AgentModeRouter", "get_agent_mode_router",
    "ExecutionTelemetryTracker",
    # Category helpers
    "KALSHI_CRYPTO_TICKERS", "KALSHI_EVENT_CATEGORIES", "KALSHI_CRYPTO_CATEGORIES",
    "is_crypto_market", "market_domain",
    # Macro overlay (Phase 3)
    "KalshiMacroOverlay", "get_kalshi_macro_overlay", "reset_kalshi_macro_overlay",
    "MacroConvictionScorer", "MacroCategory", "MacroRegime", "VolatilityRegime",
    "MacroState", "MacroMarketState", "MacroConvictionScore",
    "AssetMacroSensitivity", "DEFAULT_ASSET_SENSITIVITIES",
]
