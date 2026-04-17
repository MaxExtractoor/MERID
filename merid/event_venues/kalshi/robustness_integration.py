"""
Integration module for Kalshi Robustness Layer

Provides factory functions and migration helpers to integrate
kalshi_robustness.py with existing Kalshi components.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any, Callable

from merid.event_venues.kalshi.client import KalshiVenueClient, KalshiConfig
from merid.event_venues.kalshi.kalshi_robustness import (
    RobustKalshiClient,
    OrderLifecycleTracker,
    KalshiResilienceManager,
    get_kalshi_resilience_manager,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.robustness_integration")


def create_robust_client(
    config: Optional[KalshiConfig] = None,
    rate_tier: str = "basic",
    **robustness_kwargs
) -> RobustKalshiClient:
    """
    Create a RobustKalshiClient with the given configuration.
    
    This is the recommended way to create a production-ready
    Kalshi client with full resilience features.
    
    Args:
        config: KalshiConfig instance (uses default if None)
        rate_tier: Rate limit tier (basic/advanced/premier/prime)
        **robustness_kwargs: Additional robustness configuration
        
    Returns:
        RobustKalshiClient instance
        
    Example:
        client = create_robust_client(
            config=KalshiConfig(api_key=..., private_key_path=...),
            max_reconnect_attempts=10,
            health_check_interval=30.0
        )
        await client.start()
    """
    def client_factory():
        return KalshiVenueClient(config or KalshiConfig(), rate_tier=rate_tier)
    
    # Default robustness settings
    defaults = {
        "max_reconnect_attempts": 10,
        "reconnect_base_delay": 1.0,
        "reconnect_max_delay": 60.0,
        "health_check_interval": 30.0,
    }
    defaults.update(robustness_kwargs)
    
    return RobustKalshiClient(client_factory, **defaults)


def upgrade_existing_client(
    existing_client: KalshiVenueClient,
    **robustness_kwargs
) -> RobustKalshiClient:
    """
    Wrap an existing KalshiVenueClient with robustness features.
    
    Useful for gradually migrating existing code.
    
    Args:
        existing_client: Existing KalshiVenueClient instance
        **robustness_kwargs: Robustness configuration
        
    Returns:
        RobustKalshiClient wrapping the existing client
    """
    def client_factory():
        return existing_client
    
    defaults = {
        "max_reconnect_attempts": 10,
        "reconnect_base_delay": 1.0,
        "reconnect_max_delay": 60.0,
        "health_check_interval": 30.0,
    }
    defaults.update(robustness_kwargs)
    
    robust_client = RobustKalshiClient(client_factory, **defaults)
    robust_client._client = existing_client  # Use existing client directly
    
    return robust_client


def get_robust_kalshi_client(
    config: Optional[KalshiConfig] = None,
    force_new: bool = False,
    **robustness_kwargs
) -> RobustKalshiClient:
    """
    Get or create a singleton RobustKalshiClient.
    
    This is the recommended entry point for most use cases.
    Automatically manages the client lifecycle.
    
    Args:
        config: KalshiConfig (uses existing or default if None)
        force_new: Force creation of a new client
        **robustness_kwargs: Robustness configuration
        
    Returns:
        RobustKalshiClient singleton
        
    Example:
        client = get_robust_kalshi_client()
        await client.start()
        
        # Use client for operations
        result = await client.place_order(order)
    """
    manager = get_kalshi_resilience_manager()
    
    if manager._robust_client is None or force_new:
        client = create_robust_client(config, **robustness_kwargs)
        manager._robust_client = client
    
    return manager._robust_client


class KalshiClientMigrationHelper:
    """
    Helper class to gradually migrate from KalshiVenueClient to RobustKalshiClient.
    
    Provides compatibility layer and migration detection.
    """
    
    def __init__(self):
        self._migration_stats = {
            "legacy_calls": 0,
            "robust_calls": 0,
            "migrated_files": set(),
        }
    
    def detect_legacy_usage(self, file_path: str, line_number: int, code_line: str) -> None:
        """
        Detect and log usage of legacy client patterns.
        
        Use this during code review to find files that need migration.
        """
        legacy_patterns = [
            "KalshiVenueClient",
            "get_kalshi_client",
            "client.place_order",
            "client.cancel_order",
        ]
        
        for pattern in legacy_patterns:
            if pattern in code_line:
                self._migration_stats["legacy_calls"] += 1
                self._migration_stats["migrated_files"].add(file_path)
                logger.debug(f"Legacy pattern detected: {pattern} at {file_path}:{line_number}")
                return
    
    def get_migration_report(self) -> Dict[str, Any]:
        """Get migration statistics."""
        return {
            "legacy_calls": self._migration_stats["legacy_calls"],
            "robust_calls": self._migration_stats["robust_calls"],
            "files_needing_migration": list(self._migration_stats["migrated_files"]),
            "migration_percentage": (
                self._migration_stats["robust_calls"] /
                max(1, self._migration_stats["legacy_calls"] + self._migration_stats["robust_calls"])
                * 100
            ),
        }


# Convenience re-exports
__all__ = [
    # Core robustness
    "RobustKalshiClient",
    "OrderLifecycleTracker",
    "KalshiResilienceManager",
    "get_kalshi_resilience_manager",
    
    # Integration helpers
    "create_robust_client",
    "upgrade_existing_client",
    "get_robust_kalshi_client",
    "KalshiClientMigrationHelper",
]
