"""
MERID Centralized Settings Module

Single source of truth for all environment configuration.
Uses Pydantic Settings for type safety and validation.

Usage:
    from merid.settings import settings
    logger.info(settings.MERID_ENV)

15m Mode Guard:
    This module contains both 15m and legacy settings. When running in 15m mode
    (MERID_RUNTIME_MODE=15m_live), legacy settings should not be used.
    See docs/kalshi_15m_stack.md Section 4.3 for details.
"""

from __future__ import annotations

from utils.logger import get_logger
import os
from pathlib import Path
from typing import Optional, Dict
from pydantic import Field, BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 15m MODE GUARD: Check if we're in 15m mode and log legacy setting access
_RUNTIME_MODE = os.environ.get('MERID_RUNTIME_MODE')
_IS_15M_MODE = _RUNTIME_MODE == '15m_live'

if _IS_15M_MODE:
    logger = get_logger("merid.settings")
    logger.info("[SETTINGS-15M-MODE] Running in 15m live mode - legacy settings should not be used")

# Resolve .env absolute path so it loads correctly regardless of CWD
_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE, override=True)
except ImportError:
    pass  # dotenv not installed, rely on system env vars

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
    MERID_PROFILE: str = Field(default="", description="MERID profile - for kalshi_crypto_15m_v2, must be exactly 'kalshi_crypto_15m_v2'")
    MERID_LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    MERID_DEV_ALLOW_WS: bool = Field(default=False, description="Allow WebSocket in dev mode")
    TRADING_ENABLED: bool = Field(default=False, description="Enable trading logic (agent_grid + 15m loop) - MUST be explicitly set to true in production startup script")
    
    @field_validator('TRADING_ENABLED', mode='before')
    @classmethod
    def parse_trading_enabled(cls, v):
        """Parse TRADING_ENABLED from string to boolean."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'on')
        return bool(v)
    
    # ============================================================================= 
    # PROFILE DETECTION FOR FAKE BANKROLL PROTECTION
    # =============================================================================
    MERID_ALLOW_FAKE_BANKROLL_FOR_TEST: bool = Field(default=False, description="Allow fake bankroll sources in test profiles (DANGEROUS for production)")
    
    # =============================================================================
    # DATABASE SETTINGS
    # =============================================================================
    # PostgreSQL for fills ledger and position tracking (replaces SQLite)
    POSTGRES_HOST: str = Field(default=os.getenv("POSTGRES_HOST", "localhost"), description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=int(os.getenv("POSTGRES_PORT", "5432")), description="PostgreSQL port")
    POSTGRES_USER: str = Field(default=os.getenv("POSTGRES_USER", "merid"), description="PostgreSQL username")
    POSTGRES_PASSWORD: Optional[str] = Field(default=os.getenv("POSTGRES_PASSWORD"), description="PostgreSQL password")
    POSTGRES_DB: str = Field(default=os.getenv("POSTGRES_DB", "merid"), description="PostgreSQL database name")
    
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
    # REMOVED: CoinGecko API keys (replaced with BinanceUS public API)
    # BINANCEUS_API_KEY: Optional[str] = Field(default=None, description="BinanceUS API key (optional, public API works without auth)")
    
    # =============================================================================
    # COINBASE ADVANCED TRADE API (LEGACY - NOT USED IN 15M KALSHI PRODUCTION)
    # =============================================================================
    # COINBASE_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Coinbase Advanced Trade API key")
    # COINBASE_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Coinbase Advanced Trade API secret")
    
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
    # POLYMARKET INTEGRATION (LEGACY - NOT USED IN 15M KALSHI PRODUCTION)
    # =============================================================================
    # POLYMARKET_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Polymarket API key")
    # POLYMARKET_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Polymarket API secret")
    # POLYMARKET_WALLET_ADDRESS: Optional[str] = Field(default=None, description="Polymarket wallet address")
    # POLYMARKET_PRIVATE_KEY: Optional[str] = Field(default=None, description="Polymarket private key")
    
    # =============================================================================
    # CRYPTO EXCHANGE APIS (LEGACY - NOT USED IN 15M KALSHI PRODUCTION)
    # =============================================================================
    # BINANCE_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Binance API key")
    # BINANCE_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Binance API secret")
    # COINBASE_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Coinbase API key")
    # COINBASE_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Coinbase API secret")
    # COINBASE_CLIENT_API_KEY: Optional[str] = Field(
    #     default=None, description="Coinbase CDP client API key (alias for CB-ACCESS-KEY)"
    # )
    # COINBASE_CLIENT_API_SECRET: Optional[str] = Field(
    #     default=None, description="Coinbase CDP API secret (alias for signing)"
    # )
    # MERID_COINBASE_API_KEY: Optional[str] = Field(default=None, description="Coinbase API key (MERID prefix)")
    # MERID_COINBASE_API_SECRET: Optional[str] = Field(default=None, description="Coinbase API secret (MERID prefix)")
    # KRAKEN_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Kraken API key")
    # KRAKEN_PRIVATE_KEY: Optional[str] = Field(default=None, description="[LEGACY] Kraken private key")
    # OKX_API_KEY: Optional[str] = Field(default=None, description="OKX API key")
    # OKX_SECRET_KEY: Optional[str] = Field(default=None, description="OKX secret key")
    # OKX_API_KEY_NAME: Optional[str] = Field(default=None, description="OKX API key name")
    # OKX_PERMISSIONS: Optional[str] = Field(default=None, description="OKX API permissions")
    # BYBIT_API_KEY: Optional[str] = Field(default=None, description="Bybit API key")
    # BYBIT_API_SECRET: Optional[str] = Field(default=None, description="Bybit API secret")
    # ALPACA_API_KEY: Optional[str] = Field(default=None, description="[LEGACY] Alpaca API key")
    # ALPACA_API_SECRET: Optional[str] = Field(default=None, description="[LEGACY] Alpaca API secret")
    # MERID_ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca API key (MERID prefix)")
    # MERID_ALPACA_API_SECRET: Optional[str] = Field(default=None, description="Alpaca API secret (MERID prefix)")
    # IBKR_PAPER_TRADING_USERNAME: Optional[str] = Field(default=None, description="[LEGACY] IBKR paper trading username")
    # IBKR_PAPER_TRADING_ACCOUNT_NUMBER: Optional[str] = Field(default=None, description="[LEGACY] IBKR paper trading account")
    KALSHI_API_KEY_ID: Optional[str] = Field(default=None, description="Kalshi API key ID")
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default=None, description="Kalshi private key path")
    KALSHI_PRIVATE_KEY_PEM: Optional[str] = Field(default=None, description="Kalshi private key PEM")
    KALSHI_API_HOST: Optional[str] = Field(default=None, description="Kalshi API host override (leave unset to use the URL determined by KALSHI_USE_DEMO/KALSHI_ENV)")
    KALSHI_MIN_CLOSE_SECONDS_AGO: Optional[int] = Field(default=None, description="Freshness cutoff for market discovery: only return markets closing after (now - N seconds). None/0 = disabled (return all open markets).")
    
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
    # OLD-HARDWARE FIX (2026-04-28): Raised thresholds for weak hardware + spotty internet
    # =============================================================================
    MERID_LOOP_LAG_WARN_MS: float = Field(
        default=1500.0,
        description="Loop lag warning threshold in milliseconds (was 100, now 1500 for old hardware)"
    )
    # 24/7-SCALPER-FIX: Raised to 10000ms for continuous operation tolerance
    MERID_LOOP_LAG_DEGRADE_MS: float = Field(
        default=10000.0,
        description="Loop lag degradation threshold in milliseconds (was 4000, now 10000 for 24/7 scalping)"
    )
    # 24/7-SCALPER-FIX: Raised to 15000ms - never halt for lag in scalper mode
    MERID_LOOP_LAG_HALT_MS: float = Field(
        default=15000.0,
        description="Loop lag halt threshold in milliseconds (was 8000, now 15000). Never auto-shutdowns."
    )
    MERID_LOOP_LAG_DEGRADED_CONSECUTIVE: int = Field(
        default=5,
        description="Consecutive lag samples above degrade_ms to enter degraded mode"
    )
    MERID_LOOP_LAG_HALT_CONSECUTIVE: int = Field(
        default=10,
        description="Consecutive lag samples above halt_ms to enter halt band"
    )
    MERID_LOOP_LAG_RECOVERY_WINDOW_S: float = Field(
        default=45.0,
        description="Seconds of healthy lag required to reset breach counters"
    )
    MERID_LOOP_LAG_ENABLED: bool = Field(
        default=True,
        description="Enable loop lag monitoring in ExecutionGate"
    )
    
    # =============================================================================
    # SLOW ACTION BUDGET SETTINGS (24/7-SCALPER-FIX)
    # =============================================================================
    # 24/7-SCALPER-FIX: Raised to 12000ms for continuous 15m scalping operation
    MERID_LOOP_SLOW_ACTION_BUDGET_MS: float = Field(
        default=12000.0,
        description="Slow action warning threshold in milliseconds (was 4000, now 12000 for 24/7 scalping)"
    )
    
    # =============================================================================
    # FEED TIMEOUT SETTINGS (OLD-HARDWARE FIX)
    # =============================================================================
    MERID_FEED_NEWS_TIMEOUT_S: float = Field(
        default=4.0,
        description="News feed timeout in seconds (was 1.0, now 4.0 for unreliable networks)"
    )
    MERID_FEED_MACRO_TIMEOUT_S: float = Field(
        default=4.0,
        description="Macro feed timeout in seconds (was 1.0, now 4.0)"
    )
    MERID_FEED_ONCHAIN_TIMEOUT_S: float = Field(
        default=3.0,
        description="On-chain feed timeout in seconds (was 1.0, now 3.0)"
    )
    
    # =============================================================================
    # BANKROLL SERVICE TIMEOUTS (OLD-HARDWARE FIX)
    # =============================================================================
    MERID_BANKROLL_EQUITY_TIMEOUT_S: float = Field(
        default=60.0,
        description="Seconds to wait for equity fetch from Kalshi (was 30, now 60)"
    )
    MERID_BANKROLL_SUMMARY_TIMEOUT_S: float = Field(
        default=30.0,
        description="Seconds to wait for bankroll summary fetch (was 15, now 30)"
    )
    
    # =============================================================================
    # EXECUTION SUBSCRIBER TIMEOUTS (OLD-HARDWARE FIX)
    # =============================================================================
    MERID_EXEC_CB_FAILURE_THRESHOLD: int = Field(
        default=10,
        description="Circuit breaker failure threshold for execution subscriber (was 5, now 10)"
    )
    MERID_MAX_DECISION_AGE_S: float = Field(
        default=45.0,
        description="Max decision age before warning in seconds (was 25, now 45)"
    )
    
    # =============================================================================
    # PREDICTION MARKET SETTINGS (Kalshi-first)
    # =============================================================================
    KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode: restricts UI/API to 8 canonical Kalshi views")
    MERID_PM_TRADING_MODE: str = Field(default="paper", description="Prediction market mode: paper/live (set MERID_PM_LIVE_ENABLED=true to unlock live)")
    MERID_PM_LIVE_ENABLED: bool = Field(default=False, description="Explicit unlock for live PM trading — must be true for MERID_PM_TRADING_MODE=live to take effect")
    MERID_ALLOW_LIVE_TRADES: bool = Field(default=False, description="SAFETY INTERLOCK: Must be explicitly set to True to enable live trading.")
    MERID_PM_PROFILE: str = Field(
        default="baseline",
        description="PM profile: baseline/kalshi-pm-live (controls risk limits and agent set)"
    )
    MERID_ENABLE_KALSHI_CT: bool = Field(
        default=False,
        description="Enable KalshiContinuousTrader (research agent, not for 15m live trading)"
    )
    MERID_ENABLE_RESEARCH_AGENTS: bool = Field(
        default=False,
        description="Enable legacy research agents (PredictionMarketAgentV2, MarketResearchAgent, etc.) - NOT for 15m live trading"
    )
    MERID_LOOP_DRY_RUN: bool = Field(
        default=False,
        description="DRY_RUN mode: loop runs with full logging but no actual order placement (for validation/auditing)"
    )
    MERID_EXECUTION_MODE: str = Field(
        default="normal",
        description="Execution behavior mode: normal (submit real orders), dry_run (log would-submit without placing), simulate (log + simulate fills). NOTE: This is different from TradingMode (live/paper/mock) - this controls order placement behavior, not trading mode."
    )
    MERID_ALLOW_FAKE_DATA: bool = Field(
        default=False,
        description="Allow fake/mock data sources in production - MUST be False for live trading"
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
    KALSHI_MAINTENANCE_DAY: str = Field(
        default="THU",
        description="Day of week for Kalshi maintenance window (e.g., 'THU' for Thursday)"
    )
    KALSHI_MAINTENANCE_START: str = Field(
        default="03:00",
        description="Start time for Kalshi maintenance window in ET (e.g., '03:00' for 3 AM)"
    )
    KALSHI_MAINTENANCE_END: str = Field(
        default="05:00",
        description="End time for Kalshi maintenance window in ET (e.g., '05:00' for 5 AM)"
    )
    KALSHI_MAINTENANCE_TZ: str = Field(
        default="America/New_York",
        description="Timezone for Kalshi maintenance window (e.g., 'America/New_York')"
    )
    # PM limits - FIXED $1 EXPOSURE CAP MODEL (2026-07-17)
    # CRITICAL: Percentage-based allocation caps are DISABLED for 15m crypto stack
    # System uses fixed $1 global exposure cap (MERID_FIXED_EXPOSURE_CAP_USD)
    # via GlobalSlotAllocator. These settings are DEPRECATED for 15m crypto.
    MERID_MAX_RISK_FRACTION_PER_CYCLE: float = Field(
        default=0.0,  # DISABLED - using fixed $1 exposure cap
        description="DEPRECATED: Maximum risk fraction per cycle (DISABLED - using fixed $1 exposure cap)"
    )
    MERID_PM_RISK_PER_EDGE_PCT: float = Field(
        default=0.0,  # 0 = compute from MERID_MAX_RISK_FRACTION_PER_CYCLE / 3
        description="Risk per edge as % of bankroll (0 = cycle_cap / 3)"
    )
    MERID_PM_MAX_NOTIONAL_PER_MARKET: float = Field(
        default=0.0,  # 0 = use MERID_PM_RISK_PER_EDGE_PCT
        description="Max notional per PM market (0 = risk_per_edge_pct of bankroll)"
    )
    MERID_PM_MAX_DAILY_LOSS: float = Field(
        default=0.0,  # 0 = use MERID_MAX_DAILY_LOSS_PCT
        description="Max daily loss for PM (0 = MERID_MAX_DAILY_LOSS_PCT of bankroll)"
    )
    MERID_PM_MAX_TOTAL_NOTIONAL: float = Field(
        default=0.0,  # 0 = 50% of bankroll
        description="Max total PM notional (0 = 50% of bankroll)"
    )
    KALSHI_USE_DEMO: bool = Field(default=False, description="Use Kalshi demo/sandbox API (MUST be explicitly set to True for demo mode, defaults to False for production safety)")
    KALSHI_EMAIL: Optional[str] = Field(default=None, description="Kalshi account email")
    KALSHI_PASSWORD: Optional[str] = Field(default=None, description="Kalshi account password")

    # =============================================================================
    # ERROR HANDLING & KILL SWITCH SETTINGS
    # =============================================================================
    MERID_ERROR_THRESHOLD: int = Field(
        default=50,
        description="Number of errors in 1 hour that triggers kill switch (default: 50, raised from 10 for noisy PM agents)",
    )
    MERID_MAX_DAILY_LOSS_PCT: float = Field(
        default=0.99,
        description="Maximum daily portfolio loss percentage before kill switch triggers (0.99 = 99% disabled for burn-in data collection)"
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
    # ═══════════════════════════════════════════════════════════════════════════
    # CRITICAL: NO DEFAULT — Must be set via env var OR fetched from Kalshi API
    # Default -1 forces fetch from Kalshi balance; if fetch fails, system won't start
    # ═══════════════════════════════════════════════════════════════════════════
    MERID_TOTAL_CAPITAL_USD: float = Field(
        default=-1.0,
        description="Total capital for pipeline risk manager. REQUIRED: Set explicitly or auto-fetched from Kalshi balance."
    )
    # 0 = derive from MERID_TOTAL_CAPITAL_USD (was $50000 hardcoded)
    MERID_MAX_PORTFOLIO_NOTIONAL_USD: float = Field(default=0.0, description="Max portfolio-wide notional (0 = 100% of capital)")
    # 0 = derive from MERID_TOTAL_CAPITAL_USD × MERID_CRYPTO_ALLOCATION_PCT (was $25000/$1000)
    MERID_CRYPTO_MAX_NOTIONAL_USD: float = Field(default=0.0, description="Max crypto domain notional (0 = derive from capital)")
    MERID_CRYPTO_MAX_DAILY_LOSS_USD: float = Field(default=0.0, description="Max crypto daily loss (0 = derive from capital)")
    MERID_CRYPTO_ALLOCATION_PCT: float = Field(default=0.50, description="Max crypto capital allocation %")
    # 0 = derive from MERID_TOTAL_CAPITAL_USD × MERID_EQUITY_ALLOCATION_PCT (was $20000/$500)
    MERID_EQUITY_MAX_NOTIONAL_USD: float = Field(default=0.0, description="Max equity domain notional (0 = derive from capital)")
    MERID_EQUITY_MAX_DAILY_LOSS_USD: float = Field(default=0.0, description="Max equity daily loss (0 = derive from capital)")
    MERID_EQUITY_ALLOCATION_PCT: float = Field(default=0.40, description="Max equity capital allocation %")

    # =============================================================================
    # TRADING MODE SETTINGS
    # =============================================================================
    # Trading mode: "paper" (simulated), "live" (real money)
    MERID_TRADING_MODE: str = Field(default="paper", description="Trading mode: paper or live")
    
    # Safety interlocks for live trading (0 = derive from bankroll %, these are last-line guards)
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # These settings are still used by other profiles (sports, paper, generic prediction)
    MERID_MAX_ORDER_SIZE_USD: float = Field(default=0.0, description="Max single order USD (0 = 1% of bankroll)")
    MERID_MAX_DAILY_LOSS_USD: float = Field(default=0.0, description="Max daily loss halt USD (0 = 5% of bankroll)")
    MERID_MAX_POSITION_SIZE_USD: float = Field(default=0.0, description="Max position USD (0 = 2% of bankroll)")
    MERID_REQUIRE_CONFIRMATION: bool = Field(default=True, description="Require confirmation for live orders")

    MERID_CRYPTO_EDGE_FLOOR_PROFILE: str = Field(
        default="strict",
        description="strict | medium | relaxed — scales Kalshi crypto tiered min-edge (CT + PM grid)",
    )
    MERID_CRYPTO_MM_CONSENSUS_MODE: str = Field(
        default="full",
        description="full | soft — swarm/MM consensus gating. SAFETY: 'bypass' mode is DISABLED. All orders must flow through main execution gate with proper consensus and risk checks.",
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
    # Expiry proximity guards (made configurable from hardcoded values)
    MERID_EXPIRY_GUARD_SECS: float = Field(
        default=90.0,
        description="Hard deadline - no new entries within this many seconds of contract expiry",
    )
    MERID_EXPIRY_CAUTION_SECS: float = Field(
        default=120.0,
        description="Warning threshold for expiry proximity (should be > MERID_EXPIRY_GUARD_SECS)",
    )
    MERID_CONSENSUS_WAIT_MS: float = Field(
        default=500.0,
        description="How long to wait for soft consensus to form (fallback when crypto_edge_runtime unavailable)",
    )
    MERID_CRYPTO_EDGE_PRODUCTION_PROFILE: str = Field(
        default="modern_tradeable_kalshi_v1",
        description=(
            "Crypto threshold matrix profile: modern_tradeable_kalshi_v1 (production default) uses YAML "
            "'modern_tradeable_kalshi_v1' rows with confidence bands, fee-aware cent edge, and tiered Kelly. "
            "Legacy profiles: 'modern' (deprecated), 'legacy' (emergency fallback)."
        ),
    )
    
    # =============================================================================
    # MARKET SELECTION REFACTOR FLAGS (Phase 1: A/B testing)
    # =============================================================================
    USE_CANONICAL_SELECTOR: bool = Field(
        default=False,
        description="Use canonical select_live_markets_by_ts() for market selection (Phase 1: false for comparison logging only)"
    )
    LOG_SELECTOR_COMPARISON: bool = Field(
        default=False,
        description="Log comparison between old and new market selectors for A/B testing (DISABLED - causing catalog empty issues)"
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
    # Base bankroll for portfolio risk calculations — DERIVED from MERID_TOTAL_CAPITAL_USD
    # This ensures the 1-2% max notional sizing is computed from ACTUAL configured capital,
    # not from magic numbers. Default 0 means "derive from MERID_TOTAL_CAPITAL_USD" in __init__.
    KALSHI_PORTFOLIO_BANKROLL_CENTS: int = Field(
        default=0,  # 0 = derive from MERID_TOTAL_CAPITAL_USD in __init__
        description="Portfolio risk bankroll in cents (0 = auto-derive from MERID_TOTAL_CAPITAL_USD)"
    )
    
    # Minimum bankroll fallback - EXPLICIT config to avoid magic numbers in risk calculations
    # When live balance is unavailable, risk system falls back to this minimum (not $100 hardcoded)
    MERID_MIN_BANKROLL_USD: float = Field(
        default=100.0,
        description="Minimum bankroll USD when live balance unavailable (last-resort fallback)"
    )
    
    # Minimum cash required to trade - prevents trading with negligible spendable funds
    MERID_MIN_TRADE_CASH_USD: float = Field(
        default=1.50,
        description="Minimum available cash USD required to place trades (prevents micro-account churn)"
    )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DEPRECATED: Portfolio risk settings now unified in core.settings
    # ═══════════════════════════════════════════════════════════════════════════
    # All portfolio risk settings are now in core.settings (SINGLE SOURCE OF TRUTH):
    #   - MAX_CYCLE_RISK_PCT: 2% per cycle (replaces KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT)
    #   - MAX_TOTAL_RISK_PCT: 5% total cap (replaces KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT)
    #   - DAILY_LOSS_CAP_PCT: 12% daily loss (replaces KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT)
    #   - CLUSTER_STOP_PCT: 6% cluster stop (replaces KALSHI_PORTFOLIO_CLUSTER_STOP_PCT)
    # These legacy fields are kept for backward compatibility but should not be used.
    KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT: float = Field(default=0.50, description="DEPRECATED - use MAX_TOTAL_RISK_PCT from core.settings")
    KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT: float = Field(default=0.20, description="DEPRECATED - use DAILY_LOSS_CAP_PCT from core.settings - CRITICAL FIX: 20% aligned with drawdown halt (was 0.05)")
    KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT: float = Field(default=0.16, description="DEPRECATED - use MAX_CYCLE_RISK_PCT from core.settings")
    KALSHI_PORTFOLIO_MAX_MARGIN_UTIL_PCT: float = Field(default=0.75, description="DEPRECATED - use core.settings")
    KALSHI_PORTFOLIO_CHECK_INTERVAL_S: int = Field(default=30, description="Portfolio risk check interval in seconds")
    KALSHI_PORTFOLIO_CLUSTER_STOP_PCT: float = Field(default=0.50, description="DEPRECATED - use CLUSTER_STOP_PCT from core.settings")
    
    # Dynamic contract cap settings - DERIVED from bankroll (was hardcoded 5000)
    # Formula: 1 contract per $10 of bankroll, min 10, max 10000
    KALSHI_MAX_CONTRACTS_TOTAL: int = Field(default=0, description="Hard ceiling for total contracts (0 = derive from bankroll: 1 per $10)")
    KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION: float = Field(default=0.35, description="Fraction of total contracts per asset (e.g., 0.35 = 35%)")
    KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION: float = Field(default=0.15, description="Fraction of total contracts per cluster (asset+timeframe)")
    
    # Spot-strike guard (used by strike_selector.py)
    KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT: float = Field(default=0.85, description="Hard global guard - reject strikes beyond this distance from spot")
    
    # Risk/Positions Pipeline Feature Flag (Step 1 Guardrail)
    USE_NEW_RISK_PIPELINE: bool = Field(default=True, description="Use new pure-function risk projection pipeline (Step 1 guardrail)")
    # CRYPTO15M CROSS-ASSET RISK ALLOCATOR SETTINGS
    # Production implementation: timeframe-wide budget + per-expiry exposure caps
    # =============================================================================
    # Dynamic contract cap settings - DERIVED from bankroll (was hardcoded 5000)
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # These settings are still used by other profiles (sports, paper, generic prediction)
    # Formula: 1 contract per $10 of bankroll, min 10, max 10000
    KALSHI_MAX_CONTRACTS_TOTAL: int = Field(default=0, description="Hard ceiling for total contracts (0 = derive from bankroll: 1 per $10)")
    KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION: float = Field(default=0.35, description="Fraction of total contracts per asset (e.g., 0.35 = 35%)")
    KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION: float = Field(default=0.15, description="Fraction of total contracts per cluster (asset+timeframe)")
    
    # Per-timeframe crypto 15m contract caps - DERIVED from bankroll
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # These settings are still used by other profiles (sports, paper, generic prediction)
    # Formula: 1 contract per $50 of bankroll for 15m, min 1, max 100
    MAX_CONTRACTS_PER_TF_CRYPTO_15M: int = Field(
        default=0,
        description="Max contracts per 15m timeframe (0 = derive from bankroll: 1 per $50)"
    )
    
    # Markets limit: DERIVED from bankroll (was hardcoded 2)
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # These settings are still used by other profiles (sports, paper, generic prediction)
    # Formula: 1 market per $25 of bankroll, min 2, max 50
    MAX_MARKETS_PER_TF_CRYPTO_15M: int = Field(
        default=0,
        description="Max distinct markets per 15m timeframe (0 = derive from bankroll: 1 per $25)"
    )
    
    # Per-expiry open exposure cap: DERIVED from bankroll (was hardcoded 1)
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # These settings are still used by other profiles (sports, paper, generic prediction)
    # Formula: 1 contract per $100 of bankroll, min 1, max 20
    MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M: int = Field(
        default=0,
        description="Max open contracts per expiry (0 = derive from bankroll: 1 per $100)"
    )
    
    # Budget scaling function: "constant" or "linear" (future: bankroll-driven scaling)
    CONTRACT_BUDGET_SCALE_CRYPTO_15M: str = Field(
        default="constant",
        description="Budget scaling: constant | linear (future: bankroll-driven)"
    )
    
    # Linear scaling factor (contracts per $100 of bankroll, only if linear scaling enabled)
    CONTRACT_BUDGET_SCALE_FACTOR: float = Field(
        default=0.01,
        description="Linear scaling: add this many contracts per $100 bankroll"
    )
    
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
    
    # Dynamic computed properties - Top 3 / 1-2% / 15% aligned
    @property
    def effective_pm_risk_per_edge_pct(self) -> float:
        """Risk per edge: cycle_cap / 3 for Top 3 strategy.
        
        With 3% total cap across 3 edges, each edge gets ~1%.
        """
        if self.MERID_PM_RISK_PER_EDGE_PCT > 0:
            return self.MERID_PM_RISK_PER_EDGE_PCT
        # Default: cycle_cap (3%) divided by 3 edges
        return self.MERID_MAX_RISK_FRACTION_PER_CYCLE / 3.0
    
    @property
    def effective_pm_max_notional_per_market(self) -> float:
        """Max notional per PM market: risk_per_edge_pct of live bankroll."""
        if self.MERID_PM_MAX_NOTIONAL_PER_MARKET > 0:
            return self.MERID_PM_MAX_NOTIONAL_PER_MARKET
        # Use live bankroll from Kalshi API
        bankroll = self._get_live_bankroll_usd()
        return bankroll * self.effective_pm_risk_per_edge_pct
    
    @property
    def effective_pm_max_daily_loss(self) -> float:
        """Max daily loss: MERID_MAX_DAILY_LOSS_PCT of live bankroll (default 15%)."""
        if self.MERID_PM_MAX_DAILY_LOSS > 0:
            return self.MERID_PM_MAX_DAILY_LOSS
        # Use live bankroll from Kalshi API
        bankroll = self._get_live_bankroll_usd()
        return bankroll * self.MERID_MAX_DAILY_LOSS_PCT
    
    @property
    def effective_pm_max_total_notional(self) -> float:
        """Max total PM notional: 50% of live bankroll."""
        if self.MERID_PM_MAX_TOTAL_NOTIONAL > 0:
            return self.MERID_PM_MAX_TOTAL_NOTIONAL
        # Use live bankroll from Kalshi API
        bankroll = self._get_live_bankroll_usd()
        return bankroll * 0.50
    
    def _get_live_bankroll_usd(self) -> float:
        """Get live bankroll from Kalshi API or fallback to configured.
        
        CRITICAL: ONLY uses ACTUAL Kalshi API balance. NO fake fallbacks.
        
        NOTE: Logic duplicated from order_router to avoid circular import.
        NOTE: This is a synchronous method - cannot use async/await.
        Relies on kalshi_risk.get_live_bankroll() which handles async fetching internally.
        """
        # ONLY use actual Kalshi API balance - NO configured fallbacks
        try:
            # Source: Kalshi risk module live bankroll (sync, cached)
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_live_bankroll
                live = get_live_bankroll()
                if live > 0:
                    return live
            except Exception:
                pass
            
            # Note: Direct client.get_balance() is async and cannot be called from sync code.
            # The kalshi_risk module handles async fetching and provides this sync interface.
        except Exception as exc:
            logger.error("[_get_live_bankroll_usd] Failed to fetch actual Kalshi balance: %s", exc)
        
        # FAIL CLOSED: Cannot determine REAL bankroll from API
        raise RuntimeError(
            "Cannot determine ACTUAL Kalshi bankroll from API. "
            "System requires real balance - no configured fallbacks allowed. "
            "Check Kalshi API credentials and connectivity."
        )
    
    @property
    def effective_max_contracts_total(self) -> int:
        """Max total contracts: env-driven or 1 per $10 of live bankroll."""
        if self.KALSHI_MAX_CONTRACTS_TOTAL > 0:
            return self.KALSHI_MAX_CONTRACTS_TOTAL
        # Use live bankroll
        bankroll_usd = self._get_live_bankroll_usd()
        return max(10, min(10000, int(bankroll_usd / 10)))
    
    @property
    def effective_max_contracts_per_tf_15m(self) -> int:
        """Max contracts per 15m: env-driven or 1 per $50 of live bankroll."""
        if self.MAX_CONTRACTS_PER_TF_CRYPTO_15M > 0:
            return self.MAX_CONTRACTS_PER_TF_CRYPTO_15M
        # Use live bankroll
        bankroll_usd = self._get_live_bankroll_usd()
        return max(1, min(100, int(bankroll_usd / 50)))
    
    @property
    def effective_max_markets_per_tf_15m(self) -> int:
        """Max markets per 15m: env-driven or 1 per $25 of live bankroll."""
        if self.MAX_MARKETS_PER_TF_CRYPTO_15M > 0:
            return self.MAX_MARKETS_PER_TF_CRYPTO_15M
        # Use live bankroll
        bankroll_usd = self._get_live_bankroll_usd()
        return max(2, min(50, int(bankroll_usd / 25)))
    
    @property
    def effective_max_open_per_expiry_15m(self) -> int:
        """Max open per expiry: env-driven or 1 per $100 of live bankroll."""
        if self.MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M > 0:
            return self.MAX_OPEN_CONTRACTS_PER_EXPIRY_CRYPTO_15M
        # Use live bankroll
        bankroll_usd = self._get_live_bankroll_usd()
        return max(1, min(20, int(bankroll_usd / 100)))
    
    # =============================================================================
    # KALSHI RESILIENCE SETTINGS (BUG-1: previously hard-coded module constants)
    # OLD-HARDWARE FIX (2026-04-28): Doubled all thresholds and timeouts for weak
    # hardware + spotty internet. Circuit opens after 20 failures (was 10), longer
    # timeouts for slow connections, extended recovery periods.
    # =============================================================================
    KALSHI_BACKOFF_BASE: float = Field(default=2.0, description="Exponential backoff base (seconds)")
    KALSHI_CIRCUIT_FAILURE_THRESHOLD: int = Field(default=20, description="Failures before circuit opens (was 10, now 20)")
    KALSHI_CIRCUIT_RECOVERY_TIMEOUT: float = Field(default=60.0, description="Seconds before circuit tries half-open (was 30, now 60)")
    KALSHI_CIRCUIT_RECOVERY_TIMEOUT: float = Field(default=60.0, description="Seconds before circuit tries half-open (was 30, now 60)")
    KALSHI_MAX_CONCURRENT_REQUESTS: int = Field(default=10, description="Max concurrent HTTP requests to Kalshi API")
    KALSHI_CONNECT_TIMEOUT: float = Field(default=15.0, description="TCP connect timeout (seconds) (was 10, now 15) - BUG-FIX (2026-05-07)")
    KALSHI_READ_TIMEOUT: float = Field(default=45.0, description="HTTP read timeout (seconds) (was 30, now 45) - BUG-FIX (2026-05-07)")
    KALSHI_WRITE_TIMEOUT: float = Field(default=30.0, description="HTTP write timeout for order placement (seconds) (was 20, now 30) - BUG-FIX (2026-05-07)")
    KALSHI_POOL_TIMEOUT: float = Field(default=15.0, description="Connection pool acquire timeout (seconds) (was 10, now 15) - BUG-FIX (2026-05-07)")

    # =============================================================================
    # KALSHI RATE LIMIT SETTINGS (prevents fallback warning)
    # =============================================================================
    # CRITICAL FIX (2026-07-17): Aligned with kalshi_crypto_15m_v2.yaml profile
    # Rate limits are behavioral throttles, not exposure limits ($1 cap is the limit)
    # With $1 cap, realistic max is 0.67-1.33 orders per minute (1-2 positions total, 1-2 entries/exits per 15m cycle)
    # 5/min is generous ceiling (4-7x realistic usage) to prevent spam while allowing legitimate re-submissions
    KALSHI_MAX_ORDERS_PER_MINUTE: int = Field(default=5, description="Max orders per minute (self-throttle) - aligned with profile")
    KALSHI_MAX_ORDERS_PER_HOUR: int = Field(default=50, description="Max orders per hour (self-throttle) - generous ceiling")

    # =============================================================================
    # WEB SERVER SETTINGS
    # =============================================================================
    HOST: str = Field(default=os.getenv("MERID_HOST", "127.0.0.1"), description="Server host")
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
        
        # SAFETY: Validate and reject consensus bypass mode
        if self.MERID_CRYPTO_MM_CONSENSUS_MODE.lower() == "bypass":
            logger.error(
                "[SECURITY] MERID_CRYPTO_MM_CONSENSUS_MODE='bypass' is DISABLED at startup. "
                "All orders must flow through main execution gate with proper consensus and risk checks."
            )
            self.MERID_CRYPTO_MM_CONSENSUS_MODE = "full"
        
        # ═══════════════════════════════════════════════════════════════════════════
        # CAPITAL RESOLUTION: try Kalshi API, fall back gracefully
        # ═══════════════════════════════════════════════════════════════════════════
        # Settings.__init__ runs at import time (synchronously) before the async
        # event loop and Kalshi auth are ready.  If the balance fetch fails (401,
        # network, etc.) we MUST NOT crash — that kills every router that imports
        # `settings`.  FAIL CLOSED with 0 - bankroll_service_v2 will provide live data.
        # NO hardcoded fallbacks permitted - bankroll must come from live Kalshi API.
        if self.MERID_TOTAL_CAPITAL_USD <= 0:
            try:
                kalshi_balance = self._fetch_kalshi_balance()
                if kalshi_balance > 0:
                    self.MERID_TOTAL_CAPITAL_USD = kalshi_balance
                    logger.info(
                        "[RISK_CONFIG] MERID_TOTAL_CAPITAL_USD auto-fetched from Kalshi balance: $%.2f",
                        self.MERID_TOTAL_CAPITAL_USD
                    )
                else:
                    # Fetch returned 0 — API reachable but balance empty or auth failed
                    # FAIL CLOSED: Use 0 - bankroll_service_v2 will provide live data at runtime
                    self.MERID_TOTAL_CAPITAL_USD = 0.0
                    logger.warning(
                        "[RISK_CONFIG] Kalshi balance fetch returned $0. "
                        "Using 0 as placeholder — BankrollService will provide live data at runtime."
                    )
            except Exception as exc:
                # Network/auth not ready at import time — FAIL CLOSED with 0
                # bankroll_service_v2 will provide live data when async loop is ready
                self.MERID_TOTAL_CAPITAL_USD = 0.0
                logger.warning(
                    "[RISK_CONFIG] Kalshi balance fetch failed at startup: %s. "
                    "Using 0 as placeholder — BankrollService will provide live data at runtime.",
                    exc,
                )
        
        # Settings-derived bankroll is DEPRECATED for Kalshi 15m.
        # The SINGLE SOURCE OF TRUTH for Kalshi 15m is bankroll_service_v2.get_equity_for_risk_calc_sync().
        # All Kalshi 15m code must use RiskEnvelopeService, not settings-derived bankroll.
        # This setting remains at 0 to force use of the proper bankroll service.
        self.KALSHI_PORTFOLIO_BANKROLL_CENTS = 0
    
    def _fetch_kalshi_balance(self) -> float:
        """
        Fetch actual account balance from Kalshi API.
        
        Returns:
            Balance in USD as float. Returns 0 if unable to fetch.
        """
        import requests
        from pathlib import Path
        
        # Get Kalshi API credentials
        key_id = os.getenv("KALSHI_API_KEY_ID", "")
        private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
        env = os.getenv("KALSHI_ENV", "demo")
        
        if not key_id or not private_key_path:
            logger.error("[KALSHI_BALANCE_FETCH] Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH")
            return 0.0
        
        try:
            # Load private key
            private_key_data = Path(private_key_path).read_bytes()
            
            # Determine base URL — respect KALSHI_ENV=live and KALSHI_USE_DEMO
            use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() in ("true", "1", "yes")
            is_live = env in ("live", "prod") and not use_demo
            base_url = "https://external-api.kalshi.com/trade-api/v2" if is_live else "https://demo-api.kalshi.co/trade-api/v2"
            
            # Create signature (Kalshi format: timestamp + method + path with v2 prefix)
            timestamp = str(int(__import__('time').time() * 1000))
            path = "/trade-api/v2/portfolio/balance"
            msg_string = timestamp + "GET" + path
            
            # Import cryptography
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            
            private_key = serialization.load_pem_private_key(private_key_data, password=None)
            
            # Detect key type and sign accordingly
            if isinstance(private_key, Ed25519PrivateKey):
                # Ed25519 keys (Kalshi standard) - no padding, pure Ed25519 signing
                signature = private_key.sign(msg_string.encode("utf-8"))
            else:
                # RSA keys (legacy support) - use PSS padding
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                signature = private_key.sign(
                    msg_string.encode("utf-8"),
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                    hashes.SHA256(),
                )
            signature_b64 = __import__('base64').b64encode(signature).decode("utf-8")
            
            # Make request
            headers = {
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-SIGNATURE": signature_b64,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "Accept": "application/json",
            }
            
            # URL uses the base_url which already has /trade-api/v2
            url = f"{base_url}/portfolio/balance"
            # OLD-HARDWARE FIX: Increased from 10s to 30s for slow connections
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            # Kalshi returns balance in cents
            balance_cents = data.get("balance", 0)
            balance_usd = balance_cents / 100.0
            
            logger.info(
                "[KALSHI_BALANCE_FETCH] Successfully fetched Kalshi balance: $%.2f USD (from %s)",
                balance_usd, env
            )
            return balance_usd
            
        except Exception as exc:
            logger.error("[KALSHI_BALANCE_FETCH] Failed to fetch balance: %s", exc)
            return 0.0
    
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
            "POSTGRES_PASSWORD",
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
    
    def validate_15m_production(self) -> list[str]:
        """Validate that legacy settings are not used in 15m Kalshi production mode.
        
        This ensures the production stack uses only Kalshi-specific settings and
        does not accidentally use legacy exchange APIs or research agents.
        """
        issues = []
        
        # Only check if we're in 15m production mode
        if self.MERID_PROFILE != "kalshi_crypto_15m_v2":
            return issues
        
        # Check for legacy research agent flags
        if self.MERID_ENABLE_KALSHI_CT:
            issues.append("MERID_ENABLE_KALSHI_CT is enabled but this is a legacy research agent not for 15m live trading")
        if self.MERID_ENABLE_RESEARCH_AGENTS:
            issues.append("MERID_ENABLE_RESEARCH_AGENTS is enabled but legacy research agents are not for 15m live trading")
        
        # Check for legacy exchange API keys (these are commented out in settings but may still be set in env)
        legacy_apis = [
            ("BINANCE_API_KEY", "Binance"),
            ("COINBASE_API_KEY", "Coinbase"),
            ("KRAKEN_API_KEY", "Kraken"),
            ("ALPACA_API_KEY", "Alpaca"),
            ("POLYMARKET_API_KEY", "Polymarket"),
        ]
        
        for env_var, api_name in legacy_apis:
            if os.getenv(env_var):
                issues.append(f"{env_var} is set but {api_name} is a legacy exchange not used in 15m Kalshi production")
        
        # Check for KALSHI_ENV (should use MERID_KALSHI_ENV only)
        if os.getenv("KALSHI_ENV") and not os.getenv("MERID_KALSHI_ENV"):
            issues.append("KALSHI_ENV is set but should use MERID_KALSHI_ENV for consistency")
        
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
            # Fallback to fixed $1 exposure cap if static mode but no override (2026-07-17)
            # Percentage-based model DISABLED - using fixed $1 exposure cap
            logger.warning(
                "[STATIC_FALLBACK] Using fixed $1 exposure cap (percentage-based model DISABLED)"
            )
            # Use fixed $1 exposure cap from environment variable
            import os
            unified_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "ETH": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "SOL": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "XRP": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "DOGE": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
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
            # CRITICAL: Compute fallback from actual bankroll, NOT hardcoded defaults
            bankroll_usd = self.KALSHI_PORTFOLIO_BANKROLL_CENTS / 100.0
            if bankroll_usd <= 0:
                logger.critical("[PRODUCTION HARDENING] Cannot determine asset caps: bankroll=%s", bankroll_usd)
                raise RuntimeError(
                    "Asset cap calculation failed and bankroll is zero/invalid. "
                    "Cannot proceed without valid bankroll from Kalshi balance."
                )
            
            # Derive caps from bankroll using 0.5% unified cycle risk (aligned with MAX_CYCLE_RISK_PCT)
            # FIX: Changed to fixed $1 exposure cap (2026-07-17)
            # Percentage-based model DISABLED - using fixed $1 exposure cap
            logger.warning(
                "[FALLBACK] Using fixed $1 exposure cap (percentage-based model DISABLED): bankroll=$%.2f", bankroll_usd
            )
            # Use fixed $1 exposure cap from environment variable
            import os
            unified_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "ETH": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "SOL": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "XRP": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "DOGE": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
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
            # Fallback to fixed $1 exposure cap if static mode but no override (2026-07-17)
            # Percentage-based model DISABLED - using fixed $1 exposure cap
            logger.warning(
                "[STATIC_FALLBACK] Using fixed $1 exposure cap (percentage-based model DISABLED)"
            )
            # Use fixed $1 exposure cap from environment variable
            import os
            unified_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "ETH": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "SOL": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "XRP": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "DOGE": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
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
            # CRITICAL: Compute fallback from actual bankroll, NOT hardcoded defaults
            bankroll_usd = self.KALSHI_PORTFOLIO_BANKROLL_CENTS / 100.0
            if bankroll_usd <= 0:
                logger.critical("[PRODUCTION HARDENING] Cannot determine asset caps: bankroll=%s", bankroll_usd)
                raise RuntimeError(
                    "Asset cap calculation failed and bankroll is zero/invalid. "
                    "Cannot proceed without valid bankroll from Kalshi balance."
                )
            
            # Derive caps from bankroll using 0.5% unified cycle risk (aligned with MAX_CYCLE_RISK_PCT)
            # FIX: Changed to fixed $1 exposure cap (2026-07-17)
            # Percentage-based model DISABLED - using fixed $1 exposure cap
            logger.warning(
                "[FALLBACK] Using fixed $1 exposure cap (percentage-based model DISABLED): bankroll=$%.2f", bankroll_usd
            )
            # Use fixed $1 exposure cap from environment variable
            import os
            unified_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
            return {
                "BTC": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "ETH": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "SOL": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "XRP": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
                "DOGE": AssetCapConfig(max_daily_notional_usd=unified_cap, max_single_trade_usd=unified_cap),
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
    
    @property
    def PROFILE_IS_LIVE(self) -> bool:
        """
        Determine if current profile is a live trading profile.
        
        Live profiles require strict bankroll source validation and cannot use fake bankrolls.
        Test profiles may allow fake bankrolls for simulation purposes.
        
        Returns:
            bool: True if this is a live profile, False if test/simulation
        """
        # Explicit test profiles - these can use fake bankrolls
        test_profiles = {
            "kalshi_crypto_test",
            "kalshi_crypto_sim",
            "test_*",
            "sim_*",
            "demo_*",
            "paper_*"
        }
        
        # Explicit live profiles - these CANNOT use fake bankrolls
        live_profiles = {
            "kalshi_crypto_15m_v2",
            "kalshi_crypto_prod",
            "live_*",
            "prod_*",
            "production_*"
        }
        
        profile = self.MERID_PROFILE.lower()
        
        # Check explicit live profiles first
        for live_pattern in live_profiles:
            if live_pattern.endswith("*"):
                if profile.startswith(live_pattern[:-1]):
                    return True
            elif profile == live_pattern:
                return True
        
        # Check explicit test profiles
        for test_pattern in test_profiles:
            if test_pattern.endswith("*"):
                if profile.startswith(test_pattern[:-1]):
                    return False
            elif profile == test_pattern:
                return False
        
        # Default: assume live if not explicitly a test profile
        # This is a safe default - fake bankroll protection will be active
        return True


# Create global settings instance
settings = Settings()

# PROFILE VALIDATION FOR LEAN 15M STACK
# If this module is imported by main_15m_lean, enforce profile constraint
if settings.MERID_PROFILE and settings.MERID_PROFILE != "kalshi_crypto_15m_v2":
    import sys
    import traceback
    # Check if main_15m_lean is in the call stack
    for frame in traceback.extract_stack():
        if "main_15m_lean" in frame.filename:
            raise RuntimeError(
                f"Invalid profile '{settings.MERID_PROFILE}' for main_15m_lean.py. "
                f"Only 'kalshi_crypto_15m_v2' is allowed. "
                f"Set MERID_PROFILE=kalshi_crypto_15m_v2 in .env or environment."
            )
