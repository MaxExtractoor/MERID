"""
MERID Centralized Settings Module

Single source of truth for all environment configuration.
Uses Pydantic Settings for type safety and validation.

Usage:
    from merid.settings import settings
    print(settings.MERID_ENV)
"""

from __future__ import annotations

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca API key")
    ALPACA_API_SECRET: Optional[str] = Field(default=None, description="Alpaca API secret")
    KALSHI_API_KEY_ID: Optional[str] = Field(default=None, description="Kalshi API key ID")
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = Field(default="change_me", description="Kalshi private key path")
    KALSHI_PRIVATE_KEY_PEM: Optional[str] = Field(default=None, description="Kalshi private key PEM")
    
    # =============================================================================
    # LIVE-ONLY MODE SETTINGS
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
    MERID_ENABLE_CHAINLINK: bool = Field(default=False, description="Enable Chainlink integration")
    MERID_ENABLE_AUGUR: bool = Field(default=False, description="Enable Augur integration")
    MERID_ENABLE_NEWS_AGENT: bool = Field(default=False, description="Enable news agent")
    MERID_ENABLE_WHALE_INTEL: bool = Field(default=False, description="Enable whale intelligence")
    MERID_ENABLE_POLYMARKET: bool = Field(default=True, description="Enable Polymarket integration")
    
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
                print(f"✅ Settings loaded from: {env_file}")
            else:
                print(f"⚠️  Environment file not found: {env_file}")
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.MERID_ENV.lower() in ("development", "dev", "local")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.MERID_ENV.lower() in ("production", "prod")
    
    @property
    def is_testing(self) -> bool:
        """Check if running in testing mode."""
        return self.MERID_ENV.lower() in ("testing", "test")
    
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


# Create global settings instance
settings = Settings()
