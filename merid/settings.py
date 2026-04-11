"""
MERID Centralized Settings Module

Single source of truth for all environment configuration.
Uses Pydantic Settings for type safety and validation.

Usage:
    from merid.settings import settings
    logger.info(settings.MERID_ENV)
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("merid.settings")


class Settings(BaseSettings):
    """MERID Settings - Single source of truth for environment configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
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
    NEO4J_PASSWORD: str = Field(default="change_me", description="Neo4j password")
    
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
    POLYMARKET_API_KEY: Optional[str] = Field(default=None, description="Polymarket API key")
    POLYMARKET_API_SECRET: Optional[str] = Field(default=None, description="Polymarket API secret")
    POLYMARKET_WALLET_ADDRESS: Optional[str] = Field(default=None, description="Polymarket wallet address")
    POLYMARKET_PRIVATE_KEY: Optional[str] = Field(default=None, description="Polymarket private key")
    
    # =============================================================================
    # CRYPTO EXCHANGE APIS
    # =============================================================================
    BINANCE_API_KEY: Optional[str] = Field(default=None, description="Binance API key")
    BINANCE_API_SECRET: Optional[str] = Field(default=None, description="Binance API secret")
    COINBASE_API_KEY: Optional[str] = Field(default=None, description="Coinbase API key")
    COINBASE_API_SECRET: Optional[str] = Field(default=None, description="Coinbase API secret")
    MERID_COINBASE_API_KEY: Optional[str] = Field(default=None, description="Coinbase API key (MERID prefix)")
    MERID_COINBASE_API_SECRET: Optional[str] = Field(default=None, description="Coinbase API secret (MERID prefix)")
    KRAKEN_API_KEY: Optional[str] = Field(default=None, description="Kraken API key")
    KRAKEN_PRIVATE_KEY: Optional[str] = Field(default=None, description="Kraken private key")
    OKX_API_KEY: Optional[str] = Field(default=None, description="OKX API key")
    OKX_SECRET_KEY: Optional[str] = Field(default=None, description="OKX secret key")
    OKX_API_KEY_NAME: Optional[str] = Field(default=None, description="OKX API key name")
    OKX_PERMISSIONS: Optional[str] = Field(default=None, description="OKX API permissions")
    BYBIT_API_KEY: Optional[str] = Field(default=None, description="Bybit API key")
    BYBIT_API_SECRET: Optional[str] = Field(default=None, description="Bybit API secret")
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca API key")
    ALPACA_API_SECRET: Optional[str] = Field(default=None, description="Alpaca API secret")
    MERID_ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca API key (MERID prefix)")
    MERID_ALPACA_API_SECRET: Optional[str] = Field(default=None, description="Alpaca API secret (MERID prefix)")
    IBKR_PAPER_TRADING_USERNAME: Optional[str] = Field(default=None, description="IBKR paper trading username")
    IBKR_PAPER_TRADING_ACCOUNT_NUMBER: Optional[str] = Field(default=None, description="IBKR paper trading account")
    KALSHI_API_KEY_ID: Optional[str] = Field(default=None, description="Kalshi API key ID")
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default="change_me", description="Kalshi private key path")
    KALSHI_PRIVATE_KEY_PEM: Optional[str] = Field(default=None, description="Kalshi private key PEM")
    KALSHI_API_HOST: Optional[str] = Field(default="https://api.elections.kalshi.com/trade-api/v2", description="Kalshi API host")
    
    # =============================================================================
    # CFB RTI SETTINGS (CF Benchmarks Real-Time Index)
    # =============================================================================
    # Set MERID_CFB_RTI_ENABLED=true only after subscribing to the CF Benchmarks
    # RTI feed.  When false (default), all CFB RTI client code is bypassed and
    # trading runs without the settlement feed.  Re-enable by setting this to true.
    MERID_CFB_RTI_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable CF Benchmarks RTI settlement feed. Default false — set true "
            "after subscribing to the paid CFB RTI feed."
        ),
    )

    # =============================================================================
    # PREDICTION MARKET SETTINGS (Kalshi-first)
    # =============================================================================
    KALSHI_ONLY: bool = Field(default=True, description="Kalshi-only mode: restricts UI/API to 8 canonical Kalshi views")
    MERID_PM_TRADING_MODE: str = Field(default="paper", description="Prediction market mode: paper/live (set MERID_PM_LIVE_ENABLED=true to unlock live)")
    MERID_PM_LIVE_ENABLED: bool = Field(default=False, description="Explicit unlock for live PM trading — must be true for MERID_PM_TRADING_MODE=live to take effect")
    MERID_PM_MAX_NOTIONAL_PER_MARKET: float = Field(default=500.0, description="Max notional per PM market (USD)")
    MERID_PM_MAX_DAILY_LOSS: float = Field(default=250.0, description="Max daily loss for prediction markets (USD)")
    MERID_PM_MAX_TOTAL_NOTIONAL: float = Field(default=5000.0, description="Max total PM portfolio notional (USD)")

    # PM spot feed freshness constants
    # Invariant: 0 < MERID_PM_MAX_SPOT_AGE_SECONDS ≤ MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS
    # If a tick is older than MERID_PM_MAX_SPOT_AGE_SECONDS → status=pm_max_age_exceeded (gate blocks trades).
    # If a tick is older than MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS → status=live_price_feed_unhealthy.
    # 90s PM gate gives ample headroom above the typical ~5s Coinbase poll cadence while
    # still being well below the 120s health-dead threshold, so transient ETH/SOL stalls
    # don't immediately kill trading.
    MERID_PM_MAX_SPOT_AGE_SECONDS: float = Field(
        default=90.0,
        description="Max age (s) of a PM asset spot price before blocking trades (pm_max_age_exceeded)",
    )
    MERID_LIVE_FEED_HEALTH_MAX_AGE_SECONDS: float = Field(
        default=120.0,
        description="Max age (s) before declaring live_price_feed_unhealthy for a PM asset",
    )
    MERID_PM_WARMUP_GRACE_SECONDS: float = Field(
        default=30.0,
        description="Grace period (s) after startup before health checks apply; status=warming_up during this window",
    )
    KALSHI_USE_DEMO: bool = Field(default=False, description="Use Kalshi demo/sandbox API")
    KALSHI_EMAIL: Optional[str] = Field(default=None, description="Kalshi account email")
    KALSHI_PASSWORD: Optional[str] = Field(default=None, description="Kalshi account password")

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

    # Kill-switch error-budget knobs (all configurable via env vars)
    MERID_ERROR_THRESHOLD: int = Field(default=50, description="Max HIGH/CRITICAL errors per hour before halt")
    MERID_DEDUP_WINDOW_SECS: float = Field(default=60.0, description="Seconds within which identical errors are deduplicated")
    MERID_WARN_PCT: float = Field(default=0.70, description="Fraction of error_threshold that triggers Tier-1 WARNING")
    MERID_LIMIT_PCT: float = Field(default=0.90, description="Fraction of error_threshold that triggers Tier-2 LIMITED (reduced size)")
    
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
    # FEATURE FLAGS
    # =============================================================================
    PHASE0_ENABLED: bool = Field(default=False, description="Enable Phase0 minimal crypto scope")
    MERID_ENABLE_CHAINLINK: bool = Field(default=False, description="Enable Chainlink integration")
    MERID_ENABLE_AUGUR: bool = Field(default=False, description="Enable Augur integration")
    MERID_ENABLE_NEWS_AGENT: bool = Field(default=False, description="Enable news agent")
    MERID_ENABLE_WHALE_INTEL: bool = Field(default=False, description="Enable whale intelligence")
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
            "SUPABASE_ANON_KEY"
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
            if not (self.MERID_COINBASE_API_KEY or self.COINBASE_API_KEY):
                issues.append("MERID_COINBASE_API_KEY or COINBASE_API_KEY is required for Coinbase")
            if not (self.MERID_COINBASE_API_SECRET or self.COINBASE_API_SECRET):
                issues.append("MERID_COINBASE_API_SECRET or COINBASE_API_SECRET is required for Coinbase")
        
        return issues
    
    def validate_for_go_live(self, venues: list[str] = None) -> dict:
        """
        Comprehensive validation for going live.
        
        Returns dict with:
            - ready: bool - True if all checks pass
            - issues: list[str] - List of issues found
            - warnings: list[str] - Non-blocking warnings
        """
        venues = venues or ["kalshi", "alpaca", "coinbase_advanced"]
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
