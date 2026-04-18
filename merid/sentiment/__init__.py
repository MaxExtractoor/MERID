"""
MERID Sentiment Package

Unified sentiment analysis for social media (Twitter, Reddit) and
fear/greed indices for trading decisions.

Main exports:
- TwitterSentimentService: Twitter API v2 sentiment with VADER
- RedditSentimentService: Reddit PRAW-based sentiment with VADER
- SentimentBus: Unified interface aggregating all sources
- CFGIClient: Crypto Fear & Greed Index API client
- SentimentBundle: Combined Twitter + Reddit + Fear/Greed signal
- VADER utilities: Signal thresholds, Kalshi adjustments

Usage:
    from merid.sentiment import combine_sentiment, quick_signal
    
    # Get unified SentimentBundle
    bundle = combine_sentiment("BTC")
    >>> print(f"BTC: {bundle.combined:+.2f} ({bundle.vader_signal})")
    
    # Quick VADER signal
    signal = quick_signal(0.35)  # Returns "bullish"
"""

from utils.logger import get_logger

logger = get_logger(__name__)

from merid.sentiment.twitter_fetcher import (
    TwitterSentimentService,
    get_twitter_sentiment_service,
    quick_twitter_sentiment,
    get_btc_kalshi_sentiment,
    TwitterStreamHandler,
    get_twitter_stream_handler,
)

from merid.sentiment.reddit_scraper import (
    RedditSentimentService,
    get_reddit_sentiment_service,
    quick_reddit_sentiment,
    compare_sentiment_sources,
)

from merid.sentiment.sentiment_bus import (
    SentimentBus,
    UnifiedSentiment,
    get_sentiment_bus,
    get_social_context,
    adjust_size_with_fear_greed,
    format_sentiment_for_prompt,
)

from merid.sentiment.cfgi_client import (
    CFGIClient,
    FearGreedData,
    FearGreedRegime,
    get_cfgi_client,
    quick_fg,
    quick_fg_normalized,
    get_fg_regime,
    should_reduce_size,
)

from merid.sentiment.vader_utils import (
    VaderSignal,
    vader_signal,
    vader_confidence,
    vader_to_kalshi_adjustment,
    combine_vader_sources,
    kalshi_agent_sentiment_logic,
    get_sentiment_risk_adjustment,
    format_vader_for_prompt,
    quick_signal,
    is_bullish,
    is_bearish,
    is_strong_signal,
    TRADING_POSITIVE_THRESHOLD,
    TRADING_NEGATIVE_THRESHOLD,
    STRONG_POSITIVE_THRESHOLD,
    STRONG_NEGATIVE_THRESHOLD,
)

from merid.sentiment.sentiment_bundle import (
    SentimentBundle,
    combine_sentiment,
    get_multi_bundle,
    format_bundle_for_prompt,
    decide_btc_15m,
)

# Alias: routes import get_bundle(asset) as the single-asset bundle accessor
get_bundle = combine_sentiment

from merid.sentiment.threshold_optimizer import (
    VaderThresholdOptimizer,
    ThresholdResult,
    quick_optimize,
    run_threshold_optimization,
)


def get_threshold_status() -> dict:
    """Return current VADER threshold optimization status across all tracked assets.

    Delegates to VaderThresholdOptimizer if a cached run exists, otherwise
    returns an empty status dict so the endpoint degrades gracefully.
    """
    from datetime import datetime, timezone
    try:
        from merid.sentiment.threshold_optimizer import VaderThresholdOptimizer
        opt = VaderThresholdOptimizer()
        top = opt.get_top_results(1) if opt.results else []
        if top:
            best = top[0]
            return {
                "assets": {
                    "BTC": {
                        "pos_th": round(best.pos_th, 3),
                        "neg_th": round(best.neg_th, 3),
                        "sharpe": round(best.sharpe, 3),
                        "trades": best.trades,
                    }
                },
                "last_optimized": datetime.now(timezone.utc).isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as _ote:
        logger.debug("sentiment threshold optimization skipped: %s", _ote)
    return {
        "assets": {},
        "last_optimized": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

from merid.sentiment.fibonacci_smoothing import (
    fib_blend,
    fib_smooth_series,
    fib_smooth_sentiment_data,
    quick_fib_smooth,
    FIB_WEIGHTS,
)

from merid.sentiment.technical_indicators import (
    rsi,
    sma,
    ema,
    add_technical_indicators,
    get_tech_signal,
    quick_rsi,
    quick_sma,
)

from merid.sentiment.tech_sent_combined import (
    TechSentSignal,
    generate_tech_sent_signal,
    tech_sent_signal_series,
    signal_to_position,
    quick_tech_sent_check,
)

from merid.sentiment.sentiment_risk import (
    SentimentRiskConfig,
    SentimentRiskManager,
    check_sentiment_trade_allowed,
)

from merid.sentiment.sentiment_regime import (
    SentimentRegime,
    RegimeState,
    RiskCaps,
    SentimentRegimeEngine,
    get_sentiment_regime_engine,
    quick_regime_check,
    get_current_risk_caps,
)

from merid.sentiment.btc_risk_dial import (
    BTCRiskDial,
    BTCSentimentRiskDial,
    get_btc_risk_dial,
    quick_risk_check,
    scale_btc_size,
)

from merid.sentiment.crypto_risk_dial import (
    CryptoRiskDialConfig,
    MultiAssetSentimentRiskDial,
    get_crypto_risk_dial,
    quick_crypto_risk_check,
    scale_crypto_size,
    ASSET_BEHAVIORAL_CONFIG,
)

from merid.sentiment.behavioral_exploitation import (
    BehavioralPattern,
    MarketMicrostructure,
    SentimentContext,
    BehavioralSignal,
    LongshotBiasDetector,
    PanicVolatilityExploiter,
    AffirmationBiasExploiter,
    DelayedInformationProcessor,
    LossAversionMonitor,
    HypeCycleDetector,
    RecencyBiasDetector,
    SocialDesirabilityBiasDetector,
    EmotionBiasDetector,
    NarrativeMomentumDetector,
    BehavioralExploitationEngine,
    get_behavioral_engine,
    quick_behavioral_check,
)

from merid.sentiment.sentiment_gating import (
    GatingCriteria,
    GatingDecision,
    SentimentGatingLayer,
    get_sentiment_gating_layer,
    quick_gate_check,
    apply_sentiment_confirmation,
)

from merid.sentiment.sentiment_stops import (
    StopAdjustment,
    SentimentStopRules,
    get_sentiment_stop_rules,
    check_sentiment_stops,
)

from merid.sentiment.kalshi_arbitrage_bot import (
    ArbOpportunity,
    KalshiArbitrageBot,
    quick_arb_scan,
    find_best_arb,
)

from merid.sentiment.news_sentiment import (
    NewsSentimentResult,
    KalshiNewsSentiment,
    quick_news_sentiment,
    quick_crypto_news_sentiment,
)

from merid.sentiment.sentiment_risk_engine import (
    SentimentState,
    RiskCaps as EngineRiskCaps,
    PositionSize,
    SentimentRiskEngine,
    quick_sentiment_risk,
    quick_size_with_sentiment,
)

from merid.sentiment.kalshi_correlation import (
    CorrelatedPair,
    KalshiCorrelationDetector,
    quick_corr_check,
    check_overlap,
)

from merid.sentiment.kalshi_sentiment_backtest import (
    BacktestResult,
    KalshiSentimentBacktester,
    quick_sentiment_backtest,
    compare_sentiment_vs_fixed,
)

from merid.sentiment.fg_filter import (
    FGFilterResult,
    KalshiFGFilter,
    get_fg_filter,
    fg_filter_trade,
    fg_adjust_prob,
)

from merid.sentiment.sentiment_rotation import (
    SectorSentiment,
    RotationPlan,
    SentimentSectorRotator,
    quick_sector_rotation,
    rank_sectors_by_sentiment,
)

from merid.sentiment.fib_retracement import (
    FibLevels,
    FibSentimentStrategy,
    fib_retracements,
    add_fib_to_df,
    get_fib_signal,
    quick_fib_levels,
    quick_fib_signal,
    FIB_LEVELS,
)

from merid.sentiment.markov_regime import (
    RegimeState,
    RegimeInfo,
    SimpleFGMarkov,
    MarkovSentimentRiskAdapter,
    quick_markov_regime,
    get_markov_risk_mult,
)

from merid.sentiment.live_correlation_bot import (
    BotConfig,
    BotStats,
    LiveCorrelationBot,
    run_correlation_bot,
    quick_scan,
)

__all__ = [
    # Services
    "TwitterSentimentService",
    "RedditSentimentService",
    "SentimentBus",
    "CFGIClient",
    "TwitterStreamHandler",
    "VaderThresholdOptimizer",
    "SentimentRegimeEngine",
    "BTCSentimentRiskDial",
    "MultiAssetSentimentRiskDial",
    "SentimentGatingLayer",
    "SentimentStopRules",
    "BehavioralExploitationEngine",
    "LongshotBiasDetector",
    "PanicVolatilityExploiter",
    "AffirmationBiasExploiter",
    "DelayedInformationProcessor",
    "LossAversionMonitor",
    "HypeCycleDetector",
    "RecencyBiasDetector",
    "SocialDesirabilityBiasDetector",
    "EmotionBiasDetector",
    "NarrativeMomentumDetector",
    
    # New modules
    "KalshiArbitrageBot",
    "ArbOpportunity",
    "KalshiNewsSentiment",
    "NewsSentimentResult",
    "SentimentRiskEngine",
    "SentimentState",
    "RiskCaps",
    "EngineRiskCaps",
    "PositionSize",
    "KalshiCorrelationDetector",
    "CorrelatedPair",
    "KalshiSentimentBacktester",
    "BacktestResult",
    "KalshiFGFilter",
    "FGFilterResult",
    "SentimentSectorRotator",
    "SectorSentiment",
    "RotationPlan",
    "FibLevels",
    "FibSentimentStrategy",
    "RegimeState",
    "RegimeInfo",
    "SimpleFGMarkov",
    "MarkovSentimentRiskAdapter",
    "BotConfig",
    "BotStats",
    "LiveCorrelationBot",
    
    # Data classes
    "SentimentBundle",
    "UnifiedSentiment",
    "FearGreedData",
    "FearGreedRegime",
    "VaderSignal",
    "ThresholdResult",
    "TechSentSignal",
    "SentimentRiskConfig",
    "SentimentRegime",
    "RegimeState",
    "BTCRiskDial",
    "CryptoRiskDialConfig",
    "BehavioralPattern",
    "MarketMicrostructure",
    "SentimentContext",
    "BehavioralSignal",
    "GatingCriteria",
    "GatingDecision",
    "StopAdjustment",
    
    # Singleton accessors
    "get_twitter_sentiment_service",
    "get_reddit_sentiment_service",
    "get_sentiment_bus",
    "get_cfgi_client",
    "get_twitter_stream_handler",
    "get_sentiment_regime_engine",
    "get_btc_risk_dial",
    "get_crypto_risk_dial",
    "get_behavioral_engine",
    "get_sentiment_gating_layer",
    "get_sentiment_stop_rules",
    
    # Core functions
    "combine_sentiment",
    "get_bundle",
    "get_threshold_status",
    "get_multi_bundle",
    "format_bundle_for_prompt",
    "decide_btc_15m",
    "quick_signal",
    "quick_twitter_sentiment",
    "quick_reddit_sentiment",
    "quick_fg",
    "quick_fg_normalized",
    "quick_optimize",
    "quick_regime_check",
    "get_current_risk_caps",
    "quick_risk_check",
    "scale_btc_size",
    "quick_crypto_risk_check",
    "scale_crypto_size",
    "quick_behavioral_check",
    "quick_gate_check",
    "apply_sentiment_confirmation",
    "check_sentiment_stops",
    
    # Arbitrage
    "quick_arb_scan",
    "find_best_arb",
    
    # News sentiment
    "quick_news_sentiment",
    "quick_crypto_news_sentiment",
    
    # Unified risk engine
    "quick_sentiment_risk",
    "quick_size_with_sentiment",
    
    # Correlation
    "quick_corr_check",
    "check_overlap",
    
    # Backtest
    "quick_sentiment_backtest",
    "compare_sentiment_vs_fixed",
    
    # FG Filter
    "fg_filter_trade",
    "fg_adjust_prob",
    
    # Sector Rotation
    "quick_sector_rotation",
    "rank_sectors_by_sentiment",
    
    # Fibonacci retracements
    "fib_retracements",
    "add_fib_to_df",
    "get_fib_signal",
    "quick_fib_levels",
    "quick_fib_signal",
    
    # Markov regime
    "quick_markov_regime",
    "get_markov_risk_mult",
    
    # Live correlation bot
    "run_correlation_bot",
    "quick_scan",
    
    # Fibonacci smoothing
    "fib_blend",
    "fib_smooth_series",
    "fib_smooth_sentiment_data",
    "quick_fib_smooth",
    
    # Technical indicators
    "rsi",
    "sma",
    "ema",
    "add_technical_indicators",
    "get_tech_signal",
    "quick_rsi",
    "quick_sma",
    
    # Tech + Sent combined
    "generate_tech_sent_signal",
    "tech_sent_signal_series",
    "signal_to_position",
    "quick_tech_sent_check",
    
    # Risk management
    "check_sentiment_trade_allowed",
    
    # Utilities
    "get_social_context",
    "adjust_size_with_fear_greed",
    "format_sentiment_for_prompt",
    "compare_sentiment_sources",
    "get_fg_regime",
    "should_reduce_size",
    "vader_signal",
    "vader_confidence",
    "vader_to_kalshi_adjustment",
    "combine_vader_sources",
    "kalshi_agent_sentiment_logic",
    "get_sentiment_risk_adjustment",
    "format_vader_for_prompt",
    "is_bullish",
    "is_bearish",
    "is_strong_signal",
    "run_threshold_optimization",
    
    # Constants
    "TRADING_POSITIVE_THRESHOLD",
    "TRADING_NEGATIVE_THRESHOLD",
    "STRONG_POSITIVE_THRESHOLD",
    "STRONG_NEGATIVE_THRESHOLD",
    "FIB_WEIGHTS",
    "FIB_LEVELS",
    "ASSET_BEHAVIORAL_CONFIG",
]
