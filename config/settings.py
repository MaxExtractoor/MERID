from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional


class _StubLogger:
    def info(self, *args, **kwargs): ...
    def warning(self, *args, **kwargs): ...
    def error(self, *args, **kwargs): ...


logger = _StubLogger()


class Environment(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class ServerConfig:
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
    environment: Environment = Environment.DEVELOPMENT
    server: ServerConfig = field(default_factory=ServerConfig)
    enable_prediction_markets: bool = True
    enable_prediction_market_stub: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        env_str = os.getenv("MERID_ENV", "development").lower()
        try:
            environment = Environment(env_str)
        except ValueError:
            environment = Environment.DEVELOPMENT

        stub_env = os.getenv("ENABLE_PREDICTION_MARKET_STUB")
        if stub_env is None:
            stub_enabled = environment == Environment.DEVELOPMENT
        else:
            stub_enabled = stub_env.lower() == "true"

        return cls(
            environment=environment,
            server=ServerConfig.from_env(),
            enable_prediction_markets=os.getenv("ENABLE_PREDICTION_MARKETS", "true").lower() == "true",
            enable_prediction_market_stub=stub_enabled,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment.value,
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "debug": self.server.debug,
            },
            "features": {
                "prediction_markets": self.enable_prediction_markets,
                "prediction_market_stub": self.enable_prediction_market_stub,
            },
        }

    def validate(self) -> List[str]:
        warnings: List[str] = []
        if self.environment == Environment.PRODUCTION and self.server.debug:
            warnings.append("Debug mode enabled in production")
        return warnings


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        logger.info(f"Settings loaded for environment: {_settings.environment.value}")
        for w in _settings.validate():
            logger.warning(f"Config warning: {w}")
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings.from_env()
    logger.info("Settings reloaded")
    return _settings
