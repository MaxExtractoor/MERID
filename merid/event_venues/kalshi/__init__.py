"""Kalshi venue package for MERID."""

from typing import Any

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
from merid.event_venues.kalshi.models import (
    KalshiBalance,
    KalshiMarket,
    KalshiOrder,
    KalshiOrderBook,
    KalshiOutcome,
    KalshiPosition,
    KalshiTrade,
)
from merid.event_venues.kalshi.kalshi_config import KalshiConfig
from merid.event_venues.kalshi.trading import KalshiTrader
from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.market_catalog import (
    KalshiMarketCatalog,
    CatalogMarket,
    CatalogSnapshot,
    get_market_catalog,
)
from merid.event_venues.kalshi.kalshi_15m_time import (
    UTCWindow,
    utc_to_et,
    et_to_utc,
    get_current_utc_window,
    get_next_utc_window,
    get_previous_utc_window,
    compute_minutes_to_expiry,
)
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
    get_live_bankroll,
    get_live_bankroll_async,
)

# CRITICAL FIX (2026-07-17): Continuous position reconciliation
from merid.event_venues.kalshi.continuous_reconciliation import (
    ContinuousReconciler,
    PositionMismatch,
    ReconciliationAction,
    get_continuous_reconciler,
)

# LEGACY: Old bankroll service moved to legacy/
# Use bankroll_service_v2 instead
# from merid.event_venues.kalshi.legacy.bankroll_service import ...

# NEW v2 modules - preferred
from merid.event_venues.kalshi.types import (
    BalanceState,
    RawVenueBalance,
    InternalBankroll,
    BalanceSuccess,
    BalanceTemporaryError,
    BalancePermanentError,
    BalanceResult,
)
from merid.event_venues.kalshi.client_v2 import KalshiClientV2
# CRITICAL FIX: Make bankroll service imports lazy to prevent import-time race conditions
# These imports were causing bankroll service initialization during KalshiVenueClient import
# which led to timeouts before explicit bankroll initialization in startup sequence
def _lazy_import_bankroll_service_v2():
    """Lazy import wrapper for bankroll_service_v2 to prevent import-time initialization."""
    from merid.event_venues.kalshi.bankroll_service_v2 import (
        BankrollServiceV2,
        BankrollSummary,
        get_bankroll_service,
        get_equity_for_risk_calc_sync,
        get_summary_sync,
    )
    return BankrollServiceV2, BankrollSummary, get_bankroll_service, get_equity_for_risk_calc_sync, get_summary_sync

# Make these available at module level but lazily loaded
def get_BankrollServiceV2():
    return _lazy_import_bankroll_service_v2()[0]

def get_BankrollSummary():
    return _lazy_import_bankroll_service_v2()[1]

def get_bankroll_service(*args, **kwargs):
    return _lazy_import_bankroll_service_v2()[2](*args, **kwargs)

def get_equity_for_risk_calc_sync(*args, **kwargs):
    return _lazy_import_bankroll_service_v2()[3](*args, **kwargs)

def get_summary_sync(*args, **kwargs):
    return _lazy_import_bankroll_service_v2()[4](*args, **kwargs)
from merid.event_venues.kalshi.signal_router import (
    AgentSignal,
    SignalRouter,
    get_signal_router,
    subscribe_to_signals,
    submit_signal,
)
# CRITICAL FIX: Make risk_policy imports lazy to prevent import-time bankroll service initialization
# risk_policy imports BankrollSummary from bankroll_service_v2 at module level, which triggers bankroll service
def _lazy_import_risk_policy():
    """Lazy import wrapper for risk_policy to prevent import-time bankroll initialization."""
    from merid.event_venues.kalshi.risk_policy import (
        KalshiRiskPolicy,
        RiskAllowance,
        get_default_policy,
        check_trade_allowed,
    )
    return KalshiRiskPolicy, RiskAllowance, get_default_policy, check_trade_allowed

# Make these available at module level but lazily loaded
def get_KalshiRiskPolicy():
    return _lazy_import_risk_policy()[0]

def get_RiskAllowance():
    return _lazy_import_risk_policy()[1]

def get_default_policy(*args, **kwargs):
    return _lazy_import_risk_policy()[2](*args, **kwargs)

def get_check_trade_allowed(*args, **kwargs):
    return _lazy_import_risk_policy()[3](*args, **kwargs)
from merid.event_venues.kalshi.ws_bridge import (
    KalshiWebSocketBridge,
    get_ws_bridge,
)
from merid.event_venues.kalshi.backtest import (
    MarketSnapshot,
    TradeDecision,
    BacktestState,
    PriceCandle,
    backtest,
    backtest_summary,
    backtest_kalman_strategy,
)
from merid.event_venues.kalshi.volume_monitor import (
    VolumeMonitor,
    get_volume_monitor,
    make_telegram_sink,
    make_discord_sink,
    Kalman1D,
    PriceKalman,
    tune_kalman_params,
    KALSHI_ADVANCED_API_FORM,
)
from merid.event_venues.kalshi.trade_analytics import (
    compute_vwap,
    detect_large_trades,
)
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
from merid.event_venues.kalshi.crypto_series import (
    list_crypto_series,
    fetch_markets_batch,
    CRYPTO_FREQUENCIES,
    CRYPTO_SERIES_PREFIXES,
    FREQUENCY_SUFFIXES,
    CryptoSeries,
    MarketInfo,
    invalidate_crypto_series_cache,
    get_cache_stats,
)

__all__ = [
    # Core v1 client
    "KalshiVenueClient",
    "KalshiSessionError",
    "KalshiBusinessError",
    "KalshiTokenBucket",
    "KALSHI_RATE_TIERS",
    "KalshiBusinessReject",
    "KalshiWebSocket",
    "KalshiTrader",
    "get_kalshi_client",
    "KalshiConfig",
    "KalshiMarket",
    "KalshiOutcome",
    "KalshiOrder",
    "KalshiOrderBook",
    "KalshiPosition",
    "KalshiTrade",
    "KalshiBalance",
    "KalshiMarketCatalog",
    "CatalogMarket",
    "CatalogSnapshot",
    "get_market_catalog",
    "KalshiRiskManager",
    "KalshiRiskConfig",
    "kalshi_fee_cents",
    "kelly_size_kalshi",
    "dynamic_position_sizes",
    "multi_market_kelly_sizes",
    "get_kalshi_risk",
    "get_live_bankroll",
    "get_live_bankroll_async",
    "KalshiWebSocketBridge",
    "get_ws_bridge",
    "MarketSnapshot",
    "TradeDecision",
    "BacktestState",
    "backtest",
    "backtest_summary",
    "VolumeMonitor",
    "get_volume_monitor",
    "make_telegram_sink",
    "make_discord_sink",
    "Kalman1D",
    "PriceKalman",
    "KALSHI_ADVANCED_API_FORM",
    "KALSHI_REJECT_REASONS",
    "KALSHI_BUSINESS_REJECT_CAUSES",
    "parse_fix",
    "handle_fix_reject",
    "tune_kalman_params",
    "compute_vwap",
    "detect_large_trades",
    "edge_from_prediction",
    "kelly_size_from_kalman",
    "PriceCandle",
    "backtest_kalman_strategy",
    "OrderIntent",
    "OrderResult",
    "route_order",
    "simulate_paper_fill",
    "KALSHI_CHANNEL_PRICE",
    "KALSHI_CHANNEL_TRADE",
    "KALSHI_CHANNEL_ORDERBOOK",
    "KALSHI_CHANNEL_ORDER_FILL",
    "KALSHI_CHANNEL_ORDER_REJECT",
    "list_crypto_series",
    "fetch_markets_batch",
    "CRYPTO_FREQUENCIES",
    "CRYPTO_SERIES_PREFIXES",
    "FREQUENCY_SUFFIXES",
    "CryptoSeries",
    "MarketInfo",
    "invalidate_crypto_series_cache",
    "get_cache_stats",
    # NEW v2 modules
    "BalanceState",
    "RawVenueBalance",
    "InternalBankroll",
    "BalanceSuccess",
    "BalanceTemporaryError",
    "BalancePermanentError",
    "BalanceResult",
    "KalshiClientV2",
    "BankrollServiceV2",
    "BankrollSummary",
    "get_equity_for_risk_calc_sync",
    "get_summary_sync",
    "AgentSignal",
    "SignalRouter",
    "get_signal_router",
    "subscribe_to_signals",
    "submit_signal",
    "KalshiRiskPolicy",
    "RiskAllowance",
    "get_default_policy",
    "check_trade_allowed",
]


# 2026-08-27: Map the names in __all__ that are lazily loaded to their import
# tuples so `from merid.event_venues.kalshi import X` works for these exports.
_KALSHI_RISK_LAZY_MAP = {
    "KalshiRiskManager": 0,
    "KalshiRiskConfig": 1,
    "kalshi_fee_cents": 2,
    "kelly_size_kalshi": 3,
    "dynamic_position_sizes": 4,
    "multi_market_kelly_sizes": 5,
    "get_kalshi_risk": 6,
    "edge_from_prediction": 7,
    "kelly_size_from_kalman": 8,
    "get_live_bankroll": 9,
    "get_live_bankroll_async": 10,
}

_BANKROLL_LAZY_MAP = {
    "BankrollServiceV2": 0,
    "BankrollSummary": 1,
    "get_bankroll_service": 2,
    "get_equity_for_risk_calc_sync": 3,
    "get_summary_sync": 4,
}

_RISK_POLICY_LAZY_MAP = {
    "KalshiRiskPolicy": 0,
    "RiskAllowance": 1,
    "get_default_policy": 2,
    "check_trade_allowed": 3,
}


def __getattr__(name: str) -> Any:
    if name in _KALSHI_RISK_LAZY_MAP:
        return _lazy_import_kalshi_risk()[_KALSHI_RISK_LAZY_MAP[name]]
    if name in _BANKROLL_LAZY_MAP:
        return _lazy_import_bankroll_service_v2()[_BANKROLL_LAZY_MAP[name]]
    if name in _RISK_POLICY_LAZY_MAP:
        return _lazy_import_risk_policy()[_RISK_POLICY_LAZY_MAP[name]]
    raise AttributeError(f"module 'merid.event_venues.kalshi' has no attribute {name!r}")
