"""
MERID Centralized Settings Module

Single source of truth for all environment configuration.
Uses Pydantic Settings for type safety and validation.

Usage:
    from merid.settings import settings
    logger.info(settings.MERID_ENV)
"""

from __future__ import annotations

from utils.logger import get_logger
import os
from pathlib import Path
from typing import Optional, Dict
from pydantic import Field, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env absolute path so it loads correctly regardless of CWD
_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")

logger = get_logger("merid.settings")


class AssetCapConfig(BaseModel):
    """Per-asset daily notional limits configuration."""
    max_daily_notional_usd: float
    max_single_trade_usd: float


class Settings(BaseSettings):
    """MERID Settings - Single source of truth for environment configuration."""
    
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ignore unknown env vars for flexibility
    )
    
    # =============================================================================
    # CORE SYSTEM SETTINGS
    # =============================================================================
    MERID_ENV: str = Field(default="development", description="MERID environment")
    MERID_LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    MERID_DEV_ALLOW_WS: bool = Field(default=False, description="Allow WebSocket in dev mode")
    
    # =============================================================================
    # DATABASE SETTINGS
    # =============================================================================
    NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j connection URI")
    NEO4J_USER: str = Field(default="neo4j", description="Neo4j username")
    NEO4J_PASSWORD: Optional[str] = Field(default=None, description="Neo4j password")
    
    # =============================================================================
    # SUPABASE SETTINGS
    # =============================================================================
    SUPABASE_URL: Optional[str] = Field(default=None, description="Supabase project URL")
    SUPABASE_ANON_KEY: Optional[str] = Field(default=None, description="Supabase anonymous key")
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(default=None, description="Supabase service role key")
    
    # =============================================================================
    # EMAIL NOTIFICATIONS
    # =============================================================================
    MY_EMAIL: Optional[str] = Field(default=None, description="Email address for notifications")
    APP_PASSWORD: Optional[str] = Field(default=None, description="Email app password")
    RECEIVER_EMAIL: Optional[str] = Field(default=None, description="Email receiver for notifications")
    
    # =============================================================================
    # TELEGRAM ALERTS
    # =============================================================================
    TELEGRAM_TOKEN: Optional[str] = Field(default=None, description="Telegram bot token")
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None, description="Telegram chat ID")
    
    # =============================================================================
    # MARKET DATA APIS
    # =============================================================================
    MESSARI_API_KEY: Optional[str] = Field(default=None, description="Messari API key")
    ALPHA_VANTAGE_API_KEY: Optional[str] = Field(default=None, description="Alpha Vantage API key")
    POLYGON_API_KEY: Optional[str] = Field(default=None, description="Polygon API key")
    POLYGON_ACCESS_KEY_ID: Optional[str] = Field(default=None, description="Polygon S3 access key ID")
    POLYGON_SECRET_ACCESS_KEY: Optional[str] = Field(default=None, description="Polygon S3 secret access key")
    POLYGON_S3_ENDPOINT: Optional[str] = Field(default=None, description="Polygon S3 endpoint")
    POLYGON_BUCKET: Optional[str] = Field(default=None, description="Polygon S3 bucket")
    NEWS_API_KEY: Optional[str] = Field(default=None, description="NewsAPI key")
    SERPER_API_KEY: Optional[str] = Field(default=None, description="Serper search API key")
    FRED_API_KEY: Optional[str] = Field(default=None, description="FRED economic data API key")
    COINGECKO_API_KEY: Optional[str] = Field(default=None, description="CoinGecko Demo API key (free tier, higher rate limits)")
    COINGECKO_PRO_API_KEY: Optional[str] = Field(default=None, description="CoinGecko Pro API key")
    FINNHUB_API_KEY: Optional[str] = Field(default=None, description="Finnhub API key")
    FINNHUB_SECRET_KEY: Optional[str] = Field(default=None, description="Finnhub secret key")
    THE_GRAPH_API_KEY: Optional[str] = Field(default=None, description="The Graph API key")
    NANSEN_API_KEY: Optional[str] = Field(default=None, description="Nansen analytics API key")
    
    # =============================================================================
    # BLOCKCHAIN & SOLANA
    # =============================================================================
    HELIUS_RPC_URL: Optional[str] = Field(default=None, description="Helius Solana RPC URL")
    
    # =============================================================================
    # AI & MACHINE LEARNING
    # =============================================================================
    HUGGINGFACE_API_KEY: Optional[str] = Field(default=None, description="HuggingFace API key")
    CLAUDE_SONNET_4: Optional[str] = Field(default=None, description="Anthropic Claude API key")
    DEEPSEEK_API_KEY: Optional[str] = Field(default=None, description="DeepSeek API key")
    OLLAMA_API_KEY: Optional[str] = Field(default=None, description="Ollama API key")
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API key")
    OPEN_ROUTER_API_KEY: Optional[str] = Field(default=None, description="OpenRouter API key")
    
    # =============================================================================
    # DATABASE & INFRASTRUCTURE
    # =============================================================================
    MONGODB_URI: Optional[str] = Field(default=None, description="MongoDB connection URI")
    RAILWAY_API_TOKEN: Optional[str] = Field(default=None, description="Railway deployment token")
    REDIS_API_USER_KEY: Optional[str] = Field(default=None, description="Redis Cloud user API key")
    REDIS_API_ACCOUNT_KEY: Optional[str] = Field(default=None, description="Redis Cloud account API key")
    
    # =============================================================================
    # COMMUNICATION (TWILIO)
    # =============================================================================
    TWILIO_SID: Optional[str] = Field(default=None, description="Twilio account SID")
    TWILIO_TOKEN: Optional[str] = Field(default=None, description="Twilio auth token")
    TWILIO_VERIFY_SERVICE_SID: Optional[str] = Field(default=None, description="Twilio Verify service SID")
    TWILIO_PHONE: Optional[str] = Field(default=None, description="Twilio phone number")
    
    # =============================================================================
    # X/TWITTER API
    # =============================================================================
    X_CLIENT_ID: Optional[str] = Field(default=None, description="X Twitter client ID")
    X_CLIENT_SECRET: Optional[str] = Field(default=None, description="X Twitter client secret")
    X_BEARER_TOKEN: Optional[str] = Field(default=None, description="X Twitter bearer token")
    X_API_KEY: Optional[str] = Field(default=None, description="X Twitter API key")
    X_API_SECRET: Optional[str] = Field(default=None, description="X Twitter API secret")
    X_ACCESS_TOKEN: Optional[str] = Field(default=None, description="X Twitter access token")
    X_ACCESS_TOKEN_SECRET: Optional[str] = Field(default=None, description="X Twitter access token secret")
    
    # =============================================================================
    # POLYMARKET INTEGRATION
    # =============================================================================
    POLYMARKET_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Polymarket API key")
    POLYMARKET_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Polymarket API secret")
    POLYMARKET_WALLET_ADDRESS: Optional[str] = Field(default=None, description="Polymarket wallet address")
    POLYMARKET_PRIVATE_KEY: Optional[str] = Field(default=None, description="Polymarket private key")
    
    # =============================================================================
    # CRYPTO EXCHANGE APIS
    # =============================================================================
    BINANCE_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Binance API key")
    BINANCE_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Binance API secret")
    COINBASE_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Coinbase API key")
    COINBASE_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Coinbase API secret")
    COINBASE_CLIENT_API_KEY: Optional[str] = Field(
        default=None, description="Coinbase CDP client API key (alias for CB-ACCESS-KEY)"
    )
    COINBASE_CLIENT_API_SECRET: Optional[str] = Field(
        default=None, description="Coinbase CDP API secret (alias for signing)"
    )
    MERID_COINBASE_API_KEY: Optional[str] = Field(default=None, description="Coinbase API key (MERID prefix)")
    MERID_COINBASE_API_SECRET: Optional[str] = Field(default=None, description="Coinbase API secret (MERID prefix)")
    KRAKEN_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Kraken API key")
    KRAKEN_PRIVATE_KEY: Optional[str] = Field(default=None, description="[LEGACY] Kraken private key")
    OKX_API_KEY: Optional[str] = Field(default=None, description="OKX API key")
    OKX_SECRET_KEY: Optional[str] = Field(default=None, description="OKX secret key")
    OKX_API_KEY_NAME: Optional[str] = Field(default=None, description="OKX API key name")
    OKX_PERMISSIONS: Optional[str] = Field(default=None, description="OKX API permissions")
    BYBIT_API_KEY: Optional[str] = Field(default=None, description="Bybit API key")
    BYBIT_API_SECRET: Optional[str] = Field(default=None, description="Bybit API secret")
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Alpaca API key")
    ALPACA_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Alpaca API secret")
    MERID_ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca API key (MERID prefix)")
    MERID_ALPACA_API_SECRET: Optional[str] = Field(default=None, description="Alpaca API secret (MERID prefix)")
    IBKR_PAPER_TRADING_USERNAME: Optional[str] = Field(default=None, description="[LEGACY] IBKR paper trading username")
    IBKR_PAPER_TRADING_ACCOUNT_NUMBER: Optional[str] = Field(default=None, description="[LEGACY] IBKR paper trading account")
    KALSHI_API_KEY_ID: Optional[str] = Field(default=None, description="Kalshi API key ID")
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default=None, description="Kalshi private key path")
    KALSHI_PRIVATE_KEY_PEM: Optional[str] = Field(default=None, description="Kalshi private key PEM")
    KALSHI_API_HOST: Optional[str] = Field(default=None, description="Kalshi API host override (leave unset to use the URL determined by KALSHI_USE_DEMO/KALSHI_ENV)")
    
    # =============================================================================
    # CFB RTI (Crypto Facilities Benchmarks Real-Time Index) SETTINGS
    # Required for live Kalshi crypto contract settlement reference prices
    # =============================================================================
    MERID_CFB_RTI_ADAPTER: Optional[str] = Field(
        default=None, 
        description="CFB RTI adapter mode: null/disabled/live/simulation/stub. Defaults based on KALSHI_ENV."
    )
    MERID_CFB_RTI_POLL_URL: Optional[str] = Field(
        default=None,
        description="HTTPS JSON endpoint for CFB RTI ticks, or file://path for simulation"
    )
    MERID_CFB_RTI_API_KEY: Optional[str] = Field(
        default=None,
        description="Optional Bearer token for CFB RTI poll URL"
    )
    MERID_CFB_RTI_POLL_INTERVAL: float = Field(
        default=1.0,
        description="Seconds between CFB RTI polls"
    )
    MERID_CFB_RTI_SIMULATE: bool = Field(
        default=False,
        description="Emit synthetic ~1Hz ticks (dev/test only, not official CFB)"
    )
    MERID_ALLOW_NULL_CFB: bool = Field(
        default=False,
        description="Allow null CFB RTI adapter with KALSHI_ENV=live (emergency/dev only)"
    )
    MERID_STRICT_FILL_ID: bool = Field(
        default=True,
        description="Strict fill ID validation: warn when Kalshi fills lack stable IDs"
    )
    MERID_RISK_LIMIT_OVERRIDE: bool = Field(
        default=False,
        description="Operator override to allow live trading when risk limits deviate from bankroll policy (requires explicit acknowledgment)"
    )
    
    # =============================================================================
    # PER-ASSET RISK CAPS (DYNAMIC — computed from bankroll using risk parity)
    # =============================================================================
    # Previous hardcoded values (BTC $4000, ETH $3000, SOL $2000, XRP $1500, DOGE $500)
    # have been replaced with dynamic calculation in DynamicAllocationCalculator.
    # 
    # Set MERID_USE_DYNAMIC_ALLOCATION=false to disable and use static override values.
    # Set MERID_STATIC_ALLOCATION_OVERRIDE='{"BTC":5000,...}' for per-asset static caps.
    MERID_USE_DYNAMIC_ALLOCATION: bool = Field(
        default=True,
        description="Enable dynamic risk-parity based allocation calculation"
    )
    MERID_DYNAMIC_ALLOCATION_STRATEGY: str = Field(
        default="risk_parity",
        description="Allocation strategy: risk_parity, kelly, or equal_weight"
    )
    MERID_MAX_SINGLE_ASSET_PCT: float = Field(
        default=0.40,
        description="Maximum allocation to any single asset (40% default)"
    )
    MERID_MIN_ASSET_PCT: float = Field(
        default=0.05,
        description="Minimum allocation to any active asset (5% default)"
    )
    # Static override for emergency use (JSON dict of asset->caps)
    MERID_STATIC_ALLOCATION_OVERRIDE: Optional[str] = Field(
        default=None,
        description="JSON dict to override dynamic allocation: '{\"BTC\":5000,...}'"
    )
    
    # Legacy field kept for backward compatibility — now computed dynamically
    # Access via get_dynamic_asset_caps() method instead of direct attribute
    _asset_caps_cache: Optional[Dict[str, AssetCapConfig]] = None
    _asset_caps_cache_time: float = 0.0
    
    # =============================================================================
    # GRACEFUL DEGRADATION FLAGS (dev mode convenience)
    # =============================================================================
    # These flags allow suppressing expected warnings in development environments
    # where optional services (Redis, SMTP, X streaming) are intentionally disabled.
    MERID_REDIS_ENABLED: bool = Field(
        default=True,
        description="Enable Redis caching. When False, use in-memory cache without warnings."
    )
    MERID_EMAIL_ENABLED: bool = Field(
        default=True,
        description="Enable SMTP email notifications. When False, skip email without warnings."
    )
    TWITTER_STREAMING_ENABLED: bool = Field(
        default=True,
        description="Enable X/Twitter streaming API. When False, use polling fallback without warnings."
    )
    
    # =============================================================================
    # LOOP LAG MONITOR SETTINGS (event loop health)
    # =============================================================================
    MERID_LOOP_LAG_WARN_MS: float = Field(
        default=100.0,
        description="Loop lag warning threshold in milliseconds (log warning)"
    )
    MERID_LOOP_LAG_DEGRADE_MS: float = Field(
        default=250.0,
        description="Loop lag degradation threshold in milliseconds (reduce limits)"
    )
    MERID_LOOP_LAG_HALT_MS: float = Field(
        default=500.0,
        description="Loop lag halt threshold in milliseconds (kill switch in live mode)"
    )
    MERID_LOOP_LAG_ENABLED: bool = Field(
        default=True,
        description="Enable loop lag monitoring in ExecutionGate"
    )
    
    # =============================================================================
    # PREDICTION MARKET SETTINGS (Kalshi-first)
    # =============================================================================
    KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode: restricts UI/API to 8 canonical Kalshi views")
    MERID_PM_TRADING_MODE: str = Field(default="paper", description="Prediction market mode: paper/live (set MERID_PM_LIVE_ENABLED=true to unlock live)")
    MERID_PM_LIVE_ENABLED: bool = Field(default=False, description="Explicit unlock for live PM trading — must be true for MERID_PM_TRADING_MODE=live to take effect")
    MERID_PM_PROFILE: str = Field(
        default="development",
        description="development | production — production enforces AgentGrid fail-fast and disables CT by policy",
    )
    MERID_ENABLE_KALSHI_CT: bool = Field(
        default=False,
        description="Start KalshiContinuousTrader with the API server (off by default; AgentGrid is the PM stack)",
    )
    MERID_CT_RESEARCH_ALLOW_LOOP: bool = Field(
        default=False,
        description=(
            "Legacy only: allow KalshiContinuousTrader to start/trade when AgentGrid PM is live "
            "and/or MERID_TRADE_MODE=live with MERID_ALLOW_LIVE_TRADES=true"
        ),
    )
    MERID_PM_EXPIRY_FALLBACK_CRYPTO: bool = Field(
        default=True,
        description="Repair missing/stale KX*15M end_date from ticker (America/New_York window end)",
    )
    MERID_PM_SIGNAL_LOG: bool = Field(
        default=True,
        description="Emit [PM_SIGNAL] lines from KalshiStrategy (NO_ACTION at INFO when on)",
    )
    MERID_PM_CYCLE_TRACE_NO_ACTION: bool = Field(
        default=True,
        description="Append no_action_by_reason= rollup to [PM_CYCLE_TRACE] lines",
    )
    MERID_KALSHI_WS_CLIENT: str = Field(
        default="ws",
        description="Kalshi websocket implementation: ws (required for live) or websocket_service (dev only)",
    )
    MERID_PM_MAX_NOTIONAL_PER_MARKET: float = Field(default=500.0, description="Max notional per PM market (USD)")
    MERID_PM_MAX_DAILY_LOSS: float = Field(default=250.0, description="Max daily loss for prediction markets (USD)")
    MERID_PM_MAX_TOTAL_NOTIONAL: float = Field(default=5000.0, description="Max total PM portfolio notional (USD)")
    KALSHI_USE_DEMO: bool = Field(default=True, description="Use Kalshi demo/sandbox API (MUST be explicitly set to False for production)")
    KALSHI_EMAIL: Optional[str] = Field(default=None, description="Kalshi account email")
    KALSHI_PASSWORD: Optional[str] = Field(default=None, description="Kalshi account password")

    # =============================================================================
    # ERROR HANDLING & KILL SWITCH SETTINGS
    # =============================================================================
    MERID_ERROR_THRESHOLD: int = Field(
        default=50,
        description="Number of errors in 1 hour that triggers kill switch (default: 50, raised from 10 for noisy PM agents)",
    )
    MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS: int = Field(
        default=600,
        description="Grace period after startup where ERROR_THRESHOLD kills are suppressed (default: 600s)",
    )
    MERID_ERROR_THRESHOLD_KILL_ENABLED: bool = Field(
        default=True,
        description="Enable ERROR_THRESHOLD kill switch (set to false to suppress in emergencies)",
    )
    MERID_ERROR_SUPPRESS_WS_DISCONNECT: bool = Field(
        default=True,
        description="Suppress WebSocket disconnect errors from kill switch counter (benign client behavior)",
    )
    MERID_ERROR_SUPPRESS_WIN995: bool = Field(
        default=True,
        description="Suppress Windows asyncio WinError 995 from kill switch counter (benign Windows behavior)",
    )
    MERID_ERROR_SUPPRESS_MARKET_STATE: bool = Field(
        default=True,
        description="Suppress 'market closed/not tradeable' errors from kill switch counter (expected behavior)",
    )
    MERID_ERROR_SUPPRESS_LOG_LOW_SEVERITY: bool = Field(
        default=True,
        description="Demote low-severity errors (WS disconnects, market state) to DEBUG level",
    )

    # =============================================================================
    # UNIFIED PIPELINE SETTINGS (multi-venue)
    # =============================================================================
    MERID_TOTAL_CAPITAL_USD: float = Field(default=50000.0, description="Total capital for pipeline risk manager")
    MERID_MAX_PORTFOLIO_NOTIONAL_USD: float = Field(default=50000.0, description="Max portfolio-wide notional")
    MERID_CRYPTO_MAX_NOTIONAL_USD: float = Field(default=25000.0, description="Max crypto domain notional")
    MERID_CRYPTO_MAX_DAILY_LOSS_USD: float = Field(default=1000.0, description="Max crypto daily loss")
    MERID_CRYPTO_ALLOCATION_PCT: float = Field(default=0.50, description="Max crypto capital allocation %")
    MERID_EQUITY_MAX_NOTIONAL_USD: float = Field(default=20000.0, description="Max equity domain notional")
    MERID_EQUITY_MAX_DAILY_LOSS_USD: float = Field(default=500.0, description="Max equity daily loss")
    MERID_EQUITY_ALLOCATION_PCT: float = Field(default=0.40, description="Max equity capital allocation %")

    # =============================================================================
    # TRADING MODE SETTINGS
    # =============================================================================
    # Trading mode: "paper" (simulated), "live" (real money)
    MERID_TRADING_MODE: str = Field(default="paper", description="Trading mode: paper or live")
    
    # Safety interlocks for live trading
    MERID_MAX_ORDER_SIZE_USD: float = Field(default=100.0, description="Maximum single order size in USD")
    MERID_MAX_DAILY_LOSS_USD: float = Field(default=500.0, description="Maximum daily loss before halt")
    MERID_MAX_POSITION_SIZE_USD: float = Field(default=1000.0, description="Maximum position size per market")
    MERID_REQUIRE_CONFIRMATION: bool = Field(default=True, description="Require confirmation for live orders")

    MERID_CRYPTO_EDGE_FLOOR_PROFILE: str = Field(
        default="strict",
        description="strict | medium | relaxed — scales Kalshi crypto tiered min-edge (CT + PM grid)",
    )
    MERID_CRYPTO_MM_CONSENSUS_MODE: str = Field(
        default="full",
        description="full | soft | bypass — swarm/MM consensus gating (FORMING blocks unless soft/bypass)",
    )
    MERID_CRYPTO_SHADOW_EDGE_YES: float = Field(
        default=0.0,
        description="Observability: log SHADOW_EDGE_OBS when edge falls in (min−shadow, min) for YES side",
    )
    MERID_CRYPTO_SHADOW_EDGE_NO: float = Field(
        default=0.0,
        description="Observability: same for NO side",
    )
    MERID_CRYPTO_CONSENSUS_WAIT_TIMEOUT_MS: int = Field(
        default=500,
        description="MM soft mode: brief wait before re-reading consensus (cap 2s in agent loop)",
    )
    MERID_CRYPTO_EDGE_PRODUCTION_PROFILE: str = Field(
        default="modern_tradeable_kalshi_v1",
        description=(
            "Crypto threshold matrix profile: modern_tradeable_kalshi_v1 (production default) uses YAML "
            "'modern_tradeable_kalshi_v1' rows with confidence bands, fee-aware cent edge, and tiered Kelly. "
            "Legacy profiles: 'modern' (deprecated), 'legacy' (emergency fallback)."
        ),
    )
    MERID_CONSENSUS_PATH_LOG: bool = Field(
        default=False,
        description="Emit APPROVED_SIGNAL_CREATED / CONSENSUS_* / EXECUTION_DECISION structured INFO lines",
    )
    MERID_CRYPTO_CONSENSUS_HEALTH_LOG: bool = Field(
        default=True,
        description="Enable loud [CONSENSUS_HEALTH] warnings for stale/leaked-neutral patterns",
    )
    MERID_CRYPTO_CONSENSUS_STALE_AFTER_SIGNAL_SECONDS: float = Field(
        default=120.0,
        description="Health: warn if proposals/signals newer than consensus refresh by this many seconds",
    )
    MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_MIN_SIGNALS: int = Field(
        default=5,
        description="Health: min signals in window to evaluate neutral leak",
    )
    MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_WINDOW_MINUTES: float = Field(
        default=15.0,
        description="Health: rolling window for neutral leak heuristic",
    )
    MERID_CRYPTO_EXECUTION_INVARIANT_LOG: bool = Field(
        default=True,
        description="CT: warn when tradeable>0, orders=0, gate safe_to_trade, live_ok",
    )
    MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE: bool = Field(
        default=True,
        description=(
            "When MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern: LIMITED+warnings may still trade "
            "Kalshi crypto if safe_to_trade was cleared by a non-critical overlay"
        ),
    )

    MERID_CRYPTO_PM_VOL_BRIDGE_ENABLED: bool = Field(
        default=True,
        description=(
            "Feed PM snapshots into Crypto15mIndicatorStack (minute-bucketed) for vol_band → sizing"
        ),
    )
    MERID_CRYPTO_VOL_BANDS_LOG: bool = Field(
        default=False,
        description="Periodic INFO CRYPTO_VOL_BANDS JSON with per-asset band / rv / bars",
    )
    MERID_CRYPTO_VOL_LOW_THRESHOLD: Optional[float] = Field(
        default=None,
        description="Override annualized realized vol below = low band (default: stack 0.15)",
    )
    MERID_CRYPTO_VOL_HIGH_THRESHOLD: Optional[float] = Field(
        default=None,
        description="Override annualized realized vol above = high band (default: stack 1.20)",
    )
    MERID_CRYPTO_VOL_BAND_LOW_SIZE_MULT: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="PM size multiplier when vol band is low",
    )
    MERID_CRYPTO_VOL_BAND_MID_SIZE_MULT: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="PM size multiplier when vol band is mid",
    )
    MERID_CRYPTO_VOL_BAND_HIGH_SIZE_MULT: float = Field(
        default=0.4,
        ge=0.0,
        le=2.0,
        description="PM size multiplier when vol band is high",
    )

    MERID_SWARM_CONFIDENCE_MIN: float = Field(
        default=0.0,
        description="Minimum swarm consensus confidence (0-1) for sentiment-sized orders; 0 disables the gate",
    )
    MERID_HASHTAG_ABUSE_VOLUME_MULT: float = Field(
        default=4.0,
        description="Hashtag mention volume above this multiple of rolling baseline marks signal suspect/quarantine",
    )
    MERID_SENTIMENT_PER_ASSET_CAP_FRACTION: float = Field(
        default=0.25,
        description="Fraction of crypto category notional (divided across five assets) for sentiment-tagged orders",
    )
    
    # Live mode unlock (must be explicitly set to enable live trading)
    MERID_LIVE_TRADING_UNLOCKED: bool = Field(default=False, description="Explicit unlock for live trading")
    
    # =============================================================================
    # MOCK/SIMULATION SETTINGS
    # =============================================================================
    MERID_USE_MOCK_ARB_DATA: bool = Field(default=False, description="Use mock arbitrage data")
    MERID_USE_DEMO_TRADES: bool = Field(default=False, description="Use demo trades")
    MERID_USE_SAMPLE_DATA: bool = Field(default=False, description="Use sample data")
    MERID_USE_MOCK_STREAMS: bool = Field(default=False, description="Use mock WebSocket streams")
    
    # Enable real-time features
    MERID_ENABLE_LIVE_PRICE_FEEDS: bool = Field(default=True, description="Enable live price feeds")
    MERID_ENABLE_REAL_PREDICTION_MARKETS: bool = Field(default=True, description="Enable real prediction markets")
    MERID_ENABLE_REAL_SOLANA_WS: bool = Field(default=True, description="Enable real Solana WebSocket")
    MERID_ENABLE_REAL_NEWS: bool = Field(default=True, description="Enable real news feeds")
    
    # =============================================================================
    # PORTFOLIO RISK SETTINGS (bankroll-driven, was hardcoded in agent_grid_config.py)
    # =============================================================================
    # Base bankroll for portfolio risk calculations (defaults to total capital)
    KALSHI_PORTFOLIO_BANKROLL_CENTS: int = Field(default=50_000_00, description="Portfolio risk bankroll in cents (default $50,000)")
    
    # Portfolio limit percentages of bankroll (replace hardcoded $25K/$2K in agent_grid_config)
    KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT: float = Field(default=0.50, description="Max total notional as % of bankroll (default 50%)")
    KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT: float = Field(default=0.10, description="Max daily loss as % of bankroll (default 10%)")
    KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT: float = Field(default=0.16, description="Max per-asset notional as % of bankroll (default 16%)")
    KALSHI_PORTFOLIO_MAX_MARGIN_UTIL_PCT: float = Field(default=0.75, description="Max margin utilization % (default 75%)")
    KALSHI_PORTFOLIO_CHECK_INTERVAL_S: int = Field(default=30, description="Portfolio risk check interval in seconds")
    KALSHI_DYNAMIC_DAILY_LOSS: bool = Field(default=False, description="Enable aggressive dynamic daily loss bands based on equity/bankroll ratio (production only). Used in kalshi_risk.py — active but disabled.")
    KALSHI_DYNAMIC_STOP_LOSS: bool = Field(default=False, description="Enable dynamic per-cluster stop loss based on equity/bankroll ratio (production only). Used in kalshi_risk.py — active but disabled.")
    KALSHI_DYNAMIC_CONTRACTS: bool = Field(default=False, description="Enable dynamic contract caps based on equity/bankroll ratio (production only). Used in kalshi_risk.py — active but disabled.")
    KALSHI_PORTFOLIO_CLUSTER_STOP_PCT: float = Field(default=0.50, description="Static per-cluster stop loss as fraction of daily loss cap (used when dynamic stop loss disabled)")
    
    # Dynamic contract cap settings
    KALSHI_MAX_CONTRACTS_TOTAL: int = Field(default=5000, description="Hard ceiling for total contracts across all assets/timeframes")
    KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION: float = Field(default=0.35, description="Fraction of total contracts per asset (e.g., 0.35 = 35%)")
    KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION: float = Field(default=0.15, description="Fraction of total contracts per cluster (asset+timeframe)")
    
    # Spot-strike distance settings
    # TODO: Remove KALSHI_SPOT_STRIKE_DISTANCE_DYNAMIC - always False, not used in current agent grid
    KALSHI_SPOT_STRIKE_DISTANCE_DYNAMIC: bool = Field(default=False, description="Enable dynamic spot-strike distance scaling by vol/tenor/regime")
    KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT: float = Field(default=0.85, description="Hard global guard - reject strikes beyond this distance from spot")
    
    # Computed properties for derived USD limits (bankroll * percentage)
    @property
    def kalshi_portfolio_max_notional_cents(self) -> int:
        return int(self.KALSHI_PORTFOLIO_BANKROLL_CENTS * self.KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT)
    
    @property
    def kalshi_portfolio_max_daily_loss_cents(self) -> int:
        return int(self.KALSHI_PORTFOLIO_BANKROLL_CENTS * self.KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT)
    
    @property
    def kalshi_portfolio_max_per_asset_cents(self) -> int:
        return int(self.KALSHI_PORTFOLIO_BANKROLL_CENTS * self.KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT)
    
    # =============================================================================
    # KALSHI RESILIENCE SETTINGS (BUG-1: previously hard-coded module constants)
    # =============================================================================
    KALSHI_BACKOFF_BASE: float = Field(default=2.0, description="Exponential backoff base (seconds)")
    KALSHI_CIRCUIT_FAILURE_THRESHOLD: int = Field(default=10, description="Failures before circuit opens")
    KALSHI_CIRCUIT_RECOVERY_TIMEOUT: float = Field(default=30.0, description="Seconds before circuit tries half-open")
    KALSHI_MAX_CONCURRENT_REQUESTS: int = Field(default=10, description="Max in-flight HTTP requests to Kalshi")
    KALSHI_CONNECT_TIMEOUT: float = Field(default=5.0, description="TCP connect timeout (seconds)")
    KALSHI_READ_TIMEOUT: float = Field(default=15.0, description="HTTP read timeout (seconds)")
    KALSHI_WRITE_TIMEOUT: float = Field(default=10.0, description="HTTP write timeout for order placement (seconds)")
    KALSHI_POOL_TIMEOUT: float = Field(default=5.0, description="Connection pool acquire timeout (seconds)")

    # =============================================================================
    # KALSHI RATE LIMIT SETTINGS (prevents fallback warning)
    # =============================================================================
    KALSHI_MAX_ORDERS_PER_MINUTE: int = Field(default=60, description="Max orders per minute (self-throttle)")
    KALSHI_MAX_ORDERS_PER_HOUR: int = Field(default=1000, description="Max orders per hour (self-throttle)")

    # =============================================================================
    # FEATURE FLAGS (LEGACY/UNUSED - see docs/audit_feature_flags.md Section 18)
    # =============================================================================
    # TODO: Remove PHASE0_ENABLED - superseded by Kalshi-only mode, never enabled
    PHASE0_ENABLED: bool = Field(default=False, description="Enable Phase0 minimal crypto scope")
    # TODO: Remove MERID_ENABLE_CHAINLINK - unused, not on roadmap
    MERID_ENABLE_CHAINLINK: bool = Field(default=False, description="Enable Chainlink integration")
    # TODO: Remove MERID_ENABLE_AUGUR - unused, not on roadmap
    MERID_ENABLE_AUGUR: bool = Field(default=False, description="Enable Augur integration")
    # TODO: Remove MERID_ENABLE_NEWS_AGENT - superseded by social_stream_enabled
    MERID_ENABLE_NEWS_AGENT: bool = Field(default=False, description="Enable news agent")
    # TODO: Remove MERID_ENABLE_WHALE_INTEL - unused, not integrated
    MERID_ENABLE_WHALE_INTEL: bool = Field(default=False, description="Enable whale intelligence")
    # TODO: Remove MERID_ENABLE_POLYMARKET - not integrated, Kalshi is primary venue
    MERID_ENABLE_POLYMARKET: bool = Field(default=False, description="Enable Polymarket integration")
    
    # =============================================================================
    # WEB SERVER SETTINGS
    # =============================================================================
    HOST: str = Field(default="127.0.0.1", description="Server host")
    PORT: int = Field(default=8011, description="Server port")
    RELOAD: bool = Field(default=True, description="Enable auto-reload")
    
    # =============================================================================
    # REDIS/CACHE SETTINGS
    # =============================================================================
    REDIS_URL: Optional[str] = Field(default=None, description="Redis connection URL")
    
    # =============================================================================
    # SECURITY SETTINGS
    # =============================================================================
    SECRET_KEY: Optional[str] = Field(default=None, description="JWT secret key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiration")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Log which env file was loaded
        if hasattr(self.model_config, 'env_file') and self.model_config.env_file:
            env_file = self.model_config.env_file
            if os.path.exists(env_file):
                logger.info(f"Settings loaded from: {env_file}")
            else:
                logger.warning(f"Environment file not found: {env_file}")
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.MERID_ENV.lower() in ("development", "dev", "local")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.MERID_ENV.lower() in ("production", "prod")
    
    @property
    def allow_websocket_dev_mode(self) -> bool:
        """
        Check if WebSocket dev mode (anonymous connections) is allowed.
        
        SAFETY: This is always False in production, regardless of MERID_DEV_ALLOW_WS.
        """
        if self.is_production:
            # NEVER allow dev mode WebSocket bypass in production
            return False
        return self.MERID_DEV_ALLOW_WS
    
    @property
    def is_testing(self) -> bool:
        """Check if running in testing mode."""
        return self.MERID_ENV.lower() in ("testing", "test")
    
    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.MERID_TRADING_MODE.lower() == "paper"
    
    @property
    def is_live_trading(self) -> bool:
        """Check if running in live trading mode (requires explicit unlock)."""
        return (
            self.MERID_TRADING_MODE.lower() == "live" and
            self.MERID_LIVE_TRADING_UNLOCKED
        )
    
    @property
    def is_live_only_mode(self) -> bool:
        """Check if running in live-only mode."""
        return (
            not self.MERID_USE_MOCK_ARB_DATA and
            not self.MERID_USE_DEMO_TRADES and
            not self.MERID_USE_SAMPLE_DATA and
            not self.MERID_USE_MOCK_STREAMS
        )
    
    def validate_live_only_mode(self) -> list[str]:
        """Validate live-only mode configuration."""
        issues = []
        
        if self.MERID_USE_MOCK_ARB_DATA:
            issues.append("MERID_USE_MOCK_ARB_DATA is true - should be false for live-only mode")
        
        if self.MERID_USE_DEMO_TRADES:
            issues.append("MERID_USE_DEMO_TRADES is true - should be false for live-only mode")
        
        if self.MERID_USE_SAMPLE_DATA:
            issues.append("MERID_USE_SAMPLE_DATA is true - should be false for live-only mode")
        
        if self.MERID_USE_MOCK_STREAMS:
            issues.append("MERID_USE_MOCK_STREAMS is true - should be false for live-only mode")
        
        # Check that real-time features are enabled
        if not self.MERID_ENABLE_LIVE_PRICE_FEEDS:
            issues.append("MERID_ENABLE_LIVE_PRICE_FEEDS is false - should be true for live-only mode")
        
        if not self.MERID_ENABLE_REAL_PREDICTION_MARKETS:
            issues.append("MERID_ENABLE_REAL_PREDICTION_MARKETS is false - should be true for live-only mode")
        
        if not self.MERID_ENABLE_REAL_SOLANA_WS:
            issues.append("MERID_ENABLE_REAL_SOLANA_WS is false - should be true for live-only mode")
        
        return issues
    
    def validate_required_for_production(self) -> list[str]:
        """Validate required settings for production environment."""
        if not self.is_production:
            return []
        
        missing = []
        required_vars = [
            "SECRET_KEY",
            "NEO4J_PASSWORD",
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
        ]
        
        for var in required_vars:
            if not getattr(self, var, None):
                missing.append(var)
        
        return missing
    
    def validate_trading_mode(self) -> list[str]:
        """Validate trading mode configuration and safety interlocks."""
        issues = []
        
        # Validate trading mode value
        valid_modes = ("paper", "live")
        if self.MERID_TRADING_MODE.lower() not in valid_modes:
            issues.append(f"MERID_TRADING_MODE must be one of {valid_modes}, got: {self.MERID_TRADING_MODE}")
        
        # Live trading requires explicit unlock
        if self.MERID_TRADING_MODE.lower() == "live":
            if not self.MERID_LIVE_TRADING_UNLOCKED:
                issues.append("Live trading requires MERID_LIVE_TRADING_UNLOCKED=true")
            
            # Validate safety interlocks for live trading
            if self.MERID_MAX_ORDER_SIZE_USD <= 0:
                issues.append("MERID_MAX_ORDER_SIZE_USD must be > 0 for live trading")
            if self.MERID_MAX_DAILY_LOSS_USD <= 0:
                issues.append("MERID_MAX_DAILY_LOSS_USD must be > 0 for live trading")
            if self.MERID_MAX_POSITION_SIZE_USD <= 0:
                issues.append("MERID_MAX_POSITION_SIZE_USD must be > 0 for live trading")
        
        return issues
    
    def get_dynamic_asset_caps(self) -> Dict[str, AssetCapConfig]:
        """Compute dynamic asset caps based on portfolio bankroll.
        
        Replaces hardcoded caps with risk-parity or Kelly-optimal allocations
        that respond to market conditions and portfolio size.
        
        Returns:
            Dict mapping asset -> AssetCapConfig with dynamic daily/single-trade caps
        """
        import time
        import json
        
        # Check cache
        cache_age = time.time() - self._asset_caps_cache_time
        if self._asset_caps_cache is not None and cache_age < 60:  # 1 minute cache
            return self._asset_caps_cache
        
        # Check for static override
        if not self.MERID_USE_DYNAMIC_ALLOCATION:
            if self.MERID_STATIC_ALLOCATION_OVERRIDE:
                try:
                    override = json.loads(self.MERID_STATIC_ALLOCATION_OVERRIDE)
                    caps = {}
                    for asset, cap_usd in override.items():
                        caps[asset] = AssetCapConfig(
                            max_daily_notional_usd=float(cap_usd),
                            max_single_trade_usd=float(cap_usd) * 0.25
                        )
                    return caps
                except Exception:
                    pass
            # Fallback to legacy defaults if static mode but no override
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=4000, max_single_trade_usd=1000),
                "ETH": AssetCapConfig(max_daily_notional_usd=3000, max_single_trade_usd=750),
                "SOL": AssetCapConfig(max_daily_notional_usd=2000, max_single_trade_usd=500),
                "XRP": AssetCapConfig(max_daily_notional_usd=1500, max_single_trade_usd=375),
                "DOGE": AssetCapConfig(max_daily_notional_usd=500, max_single_trade_usd=125),
            }
        
        # Compute dynamic allocations
        try:
            from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
            calculator = get_dynamic_allocation_calculator()
            
            # Get portfolio value from bankroll setting
            portfolio_value = self.KALSHI_PORTFOLIO_BANKROLL_CENTS / 100.0
            
            # Get dynamic caps for all assets
            all_caps = calculator.get_all_caps(portfolio_value, self.MERID_DYNAMIC_ALLOCATION_STRATEGY)
            
            # Convert to AssetCapConfig objects
            caps = {}
            for asset, daily_cap in all_caps.items():
                caps[asset] = AssetCapConfig(
                    max_daily_notional_usd=daily_cap,
                    max_single_trade_usd=daily_cap * 0.25  # 25% of daily as single trade max
                )
            
            # Cache result
            self._asset_caps_cache = caps
            self._asset_caps_cache_time = time.time()
            
            return caps
        except Exception as e:
            logger.warning(f"Dynamic allocation calculation failed: {e}, using fallback")
            # Fallback to conservative defaults
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=2000, max_single_trade_usd=500),
                "ETH": AssetCapConfig(max_daily_notional_usd=1500, max_single_trade_usd=375),
                "SOL": AssetCapConfig(max_daily_notional_usd=1000, max_single_trade_usd=250),
                "XRP": AssetCapConfig(max_daily_notional_usd=750, max_single_trade_usd=188),
                "DOGE": AssetCapConfig(max_daily_notional_usd=250, max_single_trade_usd=63),
            }
    
    def get_asset_cap(self, asset: str) -> AssetCapConfig:
        """Get dynamic cap for a specific asset."""
        caps = self.get_dynamic_asset_caps()
        return caps.get(asset, AssetCapConfig(max_daily_notional_usd=1000, max_single_trade_usd=250))
    
    def validate_venue_credentials(self, venue: str) -> list[str]:
        """Validate credentials for a specific venue."""
        issues = []
        
        if venue.lower() == "kalshi":
            if not self.KALSHI_API_KEY_ID:
                issues.append("KALSHI_API_KEY_ID is required for Kalshi")
            if not self.KALSHI_PRIVATE_KEY_PATH and not self.KALSHI_PRIVATE_KEY_PEM:
                issues.append("KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM is required")
        
        elif venue.lower() == "polymarket":
            if not self.POLYMARKET_API_KEY:
                issues.append("POLYMARKET_API_KEY is required for Polymarket")
            if not self.POLYMARKET_WALLET_ADDRESS:
                issues.append("POLYMARKET_WALLET_ADDRESS is required for Polymarket")
        
        elif venue.lower() == "alpaca":
            if not (self.MERID_ALPACA_API_KEY or self.ALPACA_API_KEY):
                issues.append("MERID_ALPACA_API_KEY or ALPACA_API_KEY is required for Alpaca")
            if not (self.MERID_ALPACA_API_SECRET or self.ALPACA_API_SECRET):
                issues.append("MERID_ALPACA_API_SECRET or ALPACA_API_SECRET is required for Alpaca")
        
        elif venue.lower() in ("coinbase", "coinbase_advanced"):
            if not (
                self.MERID_COINBASE_API_KEY
                or self.COINBASE_CLIENT_API_KEY
                or self.COINBASE_API_KEY
            ):
                issues.append(
                    "MERID_COINBASE_API_KEY, COINBASE_CLIENT_API_KEY, or COINBASE_API_KEY is required for Coinbase"
                )
            if not (
                self.MERID_COINBASE_API_SECRET
                or self.COINBASE_CLIENT_API_SECRET
                or self.COINBASE_API_SECRET
            ):
                issues.append(
                    "MERID_COINBASE_API_SECRET, COINBASE_CLIENT_API_SECRET, or COINBASE_API_SECRET is required for Coinbase"
                )
        
        return issues
    
    def get_dynamic_asset_caps(self) -> Dict[str, AssetCapConfig]:
        """Compute dynamic asset caps based on portfolio bankroll.
        
        Replaces hardcoded caps with risk-parity or Kelly-optimal allocations
        that respond to market conditions and portfolio size.
        
        Returns:
            Dict mapping asset -> AssetCapConfig with dynamic daily/single-trade caps
        """
        import time
        import json
        
        # Check cache
        cache_age = time.time() - self._asset_caps_cache_time
        if self._asset_caps_cache is not None and cache_age < 60:  # 1 minute cache
            return self._asset_caps_cache
        
        # Check for static override
        if not self.MERID_USE_DYNAMIC_ALLOCATION:
            if self.MERID_STATIC_ALLOCATION_OVERRIDE:
                try:
                    override = json.loads(self.MERID_STATIC_ALLOCATION_OVERRIDE)
                    caps = {}
                    for asset, cap_usd in override.items():
                        caps[asset] = AssetCapConfig(
                            max_daily_notional_usd=float(cap_usd),
                            max_single_trade_usd=float(cap_usd) * 0.25
                        )
                    return caps
                except Exception:
                    pass
            # Fallback to legacy defaults if static mode but no override
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=4000, max_single_trade_usd=1000),
                "ETH": AssetCapConfig(max_daily_notional_usd=3000, max_single_trade_usd=750),
                "SOL": AssetCapConfig(max_daily_notional_usd=2000, max_single_trade_usd=500),
                "XRP": AssetCapConfig(max_daily_notional_usd=1500, max_single_trade_usd=375),
                "DOGE": AssetCapConfig(max_daily_notional_usd=500, max_single_trade_usd=125),
            }
        
        # Compute dynamic allocations
        try:
            from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
            calculator = get_dynamic_allocation_calculator()
            
            # Get portfolio value from bankroll setting
            portfolio_value = self.KALSHI_PORTFOLIO_BANKROLL_CENTS / 100.0
            
            # Get dynamic caps for all assets
            all_caps = calculator.get_all_caps(portfolio_value, self.MERID_DYNAMIC_ALLOCATION_STRATEGY)
            
            # Convert to AssetCapConfig objects
            caps = {}
            for asset, daily_cap in all_caps.items():
                caps[asset] = AssetCapConfig(
                    max_daily_notional_usd=daily_cap,
                    max_single_trade_usd=daily_cap * 0.25  # 25% of daily as single trade max
                )
            
            # Cache result
            self._asset_caps_cache = caps
            self._asset_caps_cache_time = time.time()
            
            return caps
        except Exception as e:
            logger.warning(f"Dynamic allocation calculation failed: {e}, using fallback")
            # Fallback to conservative defaults
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=2000, max_single_trade_usd=500),
                "ETH": AssetCapConfig(max_daily_notional_usd=1500, max_single_trade_usd=375),
                "SOL": AssetCapConfig(max_daily_notional_usd=1000, max_single_trade_usd=250),
                "XRP": AssetCapConfig(max_daily_notional_usd=750, max_single_trade_usd=188),
                "DOGE": AssetCapConfig(max_daily_notional_usd=250, max_single_trade_usd=63),
            }
    
    def get_asset_cap(self, asset: str) -> AssetCapConfig:
        """Get dynamic cap for a specific asset."""
        caps = self.get_dynamic_asset_caps()
        return caps.get(asset, AssetCapConfig(max_daily_notional_usd=1000, max_single_trade_usd=250))
    
    def validate_for_go_live(self, venues: list[str] = None) -> dict:
        """
        Comprehensive validation for going live.
        
        Returns dict with:
            - ready: bool - True if all checks pass
            - issues: list[str] - List of issues found
            - warnings: list[str] - Non-blocking warnings
        """
        venues = venues or ["kalshi"]
        issues = []
        warnings = []
        
        # Check trading mode
        issues.extend(self.validate_trading_mode())
        
        # Check venue credentials
        for venue in venues:
            issues.extend(self.validate_venue_credentials(venue))
        
        # Check production requirements
        if self.is_production:
            issues.extend(self.validate_required_for_production())
        
        # Warnings for recommended settings
        if self.MERID_MAX_ORDER_SIZE_USD > 1000:
            warnings.append(f"MERID_MAX_ORDER_SIZE_USD is high ({self.MERID_MAX_ORDER_SIZE_USD})")
        if self.MERID_MAX_DAILY_LOSS_USD > 5000:
            warnings.append(f"MERID_MAX_DAILY_LOSS_USD is high ({self.MERID_MAX_DAILY_LOSS_USD})")
        if not self.MERID_REQUIRE_CONFIRMATION and self.is_live_trading:
            warnings.append("MERID_REQUIRE_CONFIRMATION is disabled for live trading")
        
        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "mode": self.MERID_TRADING_MODE,
            "env": self.MERID_ENV,
        }


# Create global settings instance
settings = Settings()
