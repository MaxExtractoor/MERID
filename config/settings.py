"""
Centralized Configuration Management for MERID.

Provides environment-based configuration with validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger("config.settings")


class Environment(Enum):
    """Deployment environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str = "localhost"
    port: int = 5432
    name: str = "merid"
    user: str = "merid"
    password: str = ""
    pool_size: int = 10
    
    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "merid"),
            user=os.getenv("DB_USER", "merid"),
            password=os.getenv("DB_PASSWORD", ""),
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        )


@dataclass
class ExchangeConfig:
    """Exchange API configuration."""
    name: str = "coinbase"
    api_key: str = ""
    api_secret: str = ""
    sandbox: bool = True
    rate_limit: float = 1.0
    
    @classmethod
    def from_env(cls, prefix: str = "EXCHANGE") -> "ExchangeConfig":
        return cls(
            name=os.getenv(f"{prefix}_NAME", "coinbase"),
            api_key=os.getenv(f"{prefix}_API_KEY", ""),
            api_secret=os.getenv(f"{prefix}_API_SECRET", ""),
            sandbox=os.getenv(f"{prefix}_SANDBOX", "true").lower() == "true",
            rate_limit=float(os.getenv(f"{prefix}_RATE_LIMIT", "1.0")),
        )


@dataclass
class TradingConfig:
    """Trading configuration."""
    mode: str = "paper"  # paper, live
    initial_capital: float = 100000.0
    max_position_size_usd: float = 10000.0
    max_total_exposure_usd: float = 50000.0
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.04
    slippage_tolerance_pct: float = 0.001
    commission_pct: float = 0.001
    
    @classmethod
    def from_env(cls) -> "TradingConfig":
        return cls(
            mode=os.getenv("TRADING_MODE", "paper"),
            initial_capital=float(os.getenv("TRADING_INITIAL_CAPITAL", "100000")),
            max_position_size_usd=float(os.getenv("TRADING_MAX_POSITION", "10000")),
            max_total_exposure_usd=float(os.getenv("TRADING_MAX_EXPOSURE", "50000")),
            default_stop_loss_pct=float(os.getenv("TRADING_STOP_LOSS_PCT", "0.02")),
            default_take_profit_pct=float(os.getenv("TRADING_TAKE_PROFIT_PCT", "0.04")),
            slippage_tolerance_pct=float(os.getenv("TRADING_SLIPPAGE_PCT", "0.001")),
            commission_pct=float(os.getenv("TRADING_COMMISSION_PCT", "0.001")),
        )


@dataclass
class AgentConfig:
    """Agent mesh configuration."""
    num_agents: int = 8
    consensus_threshold: float = 0.65
    vote_timeout_seconds: float = 30.0
    ollama_host: str = "http://localhost:11434"
    default_model: str = "merid-strategist:latest"
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            num_agents=int(os.getenv("AGENT_NUM_AGENTS", "8")),
            consensus_threshold=float(os.getenv("AGENT_CONSENSUS_THRESHOLD", "0.65")),
            vote_timeout_seconds=float(os.getenv("AGENT_VOTE_TIMEOUT", "30")),
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            default_model=os.getenv("AGENT_DEFAULT_MODEL", "merid-strategist:latest"),
        )


@dataclass
class AlertConfig:
    """Alert system configuration."""
    check_interval_seconds: float = 5.0
    max_alerts_per_symbol: int = 10
    notification_retention_hours: int = 24
    
    @classmethod
    def from_env(cls) -> "AlertConfig":
        return cls(
            check_interval_seconds=float(os.getenv("ALERT_CHECK_INTERVAL", "5")),
            max_alerts_per_symbol=int(os.getenv("ALERT_MAX_PER_SYMBOL", "10")),
            notification_retention_hours=int(os.getenv("ALERT_RETENTION_HOURS", "24")),
        )


@dataclass
class ServerConfig:
    """Web server configuration."""
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = True
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        origins = os.getenv("CORS_ORIGINS", "*").split(",")
        return cls(
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "8001")),
            debug=os.getenv("DEBUG", "true").lower() == "true",
            cors_origins=origins,
        )


@dataclass
class Settings:
    """Main settings container."""
    environment: Environment = Environment.DEVELOPMENT
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    
    # Feature flags
    enable_live_trading: bool = False
    enable_prediction_markets: bool = True
    enable_news_monitoring: bool = True
    enable_backtesting: bool = True
    
    @classmethod
    def from_env(cls) -> "Settings":
        env_str = os.getenv("MERID_ENV", "development").lower()
        try:
            environment = Environment(env_str)
        except ValueError:
            environment = Environment.DEVELOPMENT
        
        return cls(
            environment=environment,
            database=DatabaseConfig.from_env(),
            exchange=ExchangeConfig.from_env(),
            trading=TradingConfig.from_env(),
            agents=AgentConfig.from_env(),
            alerts=AlertConfig.from_env(),
            server=ServerConfig.from_env(),
            enable_live_trading=os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true",
            enable_prediction_markets=os.getenv("ENABLE_PREDICTION_MARKETS", "true").lower() == "true",
            enable_news_monitoring=os.getenv("ENABLE_NEWS_MONITORING", "true").lower() == "true",
            enable_backtesting=os.getenv("ENABLE_BACKTESTING", "true").lower() == "true",
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary (excluding secrets)."""
        return {
            "environment": self.environment.value,
            "trading": {
                "mode": self.trading.mode,
                "initial_capital": self.trading.initial_capital,
                "max_position_size_usd": self.trading.max_position_size_usd,
            },
            "agents": {
                "num_agents": self.agents.num_agents,
                "consensus_threshold": self.agents.consensus_threshold,
                "ollama_host": self.agents.ollama_host,
            },
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "debug": self.server.debug,
            },
            "features": {
                "live_trading": self.enable_live_trading,
                "prediction_markets": self.enable_prediction_markets,
                "news_monitoring": self.enable_news_monitoring,
                "backtesting": self.enable_backtesting,
            },
        }
    
    def validate(self) -> List[str]:
        """Validate settings and return list of warnings."""
        warnings = []
        
        if self.environment == Environment.PRODUCTION:
            if self.server.debug:
                warnings.append("Debug mode enabled in production")
            if "*" in self.server.cors_origins:
                warnings.append("CORS allows all origins in production")
            if not self.exchange.api_key and self.enable_live_trading:
                warnings.append("Live trading enabled but no exchange API key")
        
        if self.trading.mode == "live" and not self.enable_live_trading:
            warnings.append("Trading mode is 'live' but live trading feature is disabled")
        
        return warnings


# Global singleton
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        logger.info(f"Settings loaded for environment: {_settings.environment.value}")
        
        warnings = _settings.validate()
        for warning in warnings:
            logger.warning(f"Config warning: {warning}")
    
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global _settings
    _settings = Settings.from_env()
    logger.info("Settings reloaded")
    return _settings
