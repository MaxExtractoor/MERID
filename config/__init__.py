"""Configuration module for MERID."""

import warnings

# Suppress T-060 deprecation warning - this is the compatibility layer
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="config.settings is deprecated")
    from config.settings import (
        Settings,
        Environment,
        ServerConfig,
        get_settings,
        reload_settings,
    )

__all__ = [
    "Settings",
    "Environment",
    "ServerConfig",
    "get_settings",
    "reload_settings",
]
