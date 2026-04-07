"""Venue Registry — Centralized venue management for MERID.

Maintains a registry of all trading venues (crypto exchanges, prediction markets)
and provides unified access for the main loop, reconciliation, and risk management.

Usage::

    registry = get_venue_registry()
    venues = registry.list_venues()
    kalshi = registry.get_venue("kalshi")
    positions = await kalshi.get_positions()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from utils.logger import get_logger

logger = get_logger("merid.venue_registry")


class VenueProtocol(Protocol):
    """Protocol that all venue adapters must implement."""

    @property
    def venue_name(self) -> str:
        """Return venue identifier (e.g., 'kalshi', 'coinbase')."""
        ...

    async def list_instruments(self, **kwargs) -> List[Any]:
        """List available instruments/markets."""
        ...

    async def get_positions(self) -> List[Any]:
        """Get current positions."""
        ...

    async def get_orders(self, status: Optional[str] = None) -> List[Any]:
        """Get current orders."""
        ...

    async def submit_order(self, order: Any) -> Any:
        """Submit an order."""
        ...

    async def get_risk_snapshot(self) -> Dict[str, Any]:
        """Get risk metrics."""
        ...


class VenueRegistry:
    """Registry of all trading venues."""

    def __init__(self):
        self._venues: Dict[str, VenueProtocol] = {}
        self._enabled_venues: Dict[str, bool] = {}
        logger.info("VenueRegistry initialized")

    def register(self, venue: VenueProtocol, enabled: bool = True) -> None:
        """Register a venue adapter.
        
        Args:
            venue: Venue adapter implementing VenueProtocol
            enabled: Whether venue is enabled for trading
        """
        name = venue.venue_name
        self._venues[name] = venue
        self._enabled_venues[name] = enabled
        logger.info(f"Registered venue: {name} (enabled={enabled})")

    def get_venue(self, name: str) -> Optional[VenueProtocol]:
        """Get a venue adapter by name.
        
        Args:
            name: Venue identifier (e.g., "kalshi", "coinbase")
            
        Returns:
            Venue adapter or None if not found
        """
        return self._venues.get(name)

    def list_venues(self, enabled_only: bool = False) -> List[str]:
        """List all registered venues.
        
        Args:
            enabled_only: Only return enabled venues
            
        Returns:
            List of venue names
        """
        if enabled_only:
            return [name for name, enabled in self._enabled_venues.items() if enabled]
        return list(self._venues.keys())

    def is_enabled(self, name: str) -> bool:
        """Check if a venue is enabled.
        
        Args:
            name: Venue identifier
            
        Returns:
            True if venue is enabled
        """
        return self._enabled_venues.get(name, False)

    def enable_venue(self, name: str) -> bool:
        """Enable a venue.
        
        Args:
            name: Venue identifier
            
        Returns:
            True if venue was found and enabled
        """
        if name in self._venues:
            self._enabled_venues[name] = True
            logger.info(f"Enabled venue: {name}")
            return True
        return False

    def disable_venue(self, name: str) -> bool:
        """Disable a venue.
        
        Args:
            name: Venue identifier
            
        Returns:
            True if venue was found and disabled
        """
        if name in self._venues:
            self._enabled_venues[name] = False
            logger.warning(f"Disabled venue: {name}")
            return True
        return False

    async def get_all_positions(self, venues: Optional[List[str]] = None, kalshi_only: bool = False) -> Dict[str, List[Any]]:
        """Get positions from multiple venues.
        
        Args:
            venues: List of venue names (default: all enabled venues)
            kalshi_only: If True, only return Kalshi positions (ignores venues param)
            
        Returns:
            Dict mapping venue name to list of positions
        """
        from merid.settings import settings
        
        # Enforce KALSHI_ONLY mode from settings
        if settings.KALSHI_ONLY or kalshi_only:
            venues = ["kalshi"]
        elif venues is None:
            venues = self.list_venues(enabled_only=True)

        result = {}
        for venue_name in venues:
            venue = self.get_venue(venue_name)
            if venue:
                try:
                    positions = await venue.get_positions()
                    result[venue_name] = positions
                except Exception as exc:
                    logger.error(f"Failed to get positions from {venue_name}: {exc}")
                    result[venue_name] = []

        return result

    async def get_all_risk_snapshots(self, venues: Optional[List[str]] = None, kalshi_only: bool = False) -> Dict[str, Dict[str, Any]]:
        """Get risk snapshots from multiple venues.
        
        Args:
            venues: List of venue names (default: all enabled venues)
            kalshi_only: If True, only return Kalshi risk data (ignores venues param)
            
        Returns:
            Dict mapping venue name to risk snapshot
        """
        from merid.settings import settings
        
        # Enforce KALSHI_ONLY mode from settings
        if settings.KALSHI_ONLY or kalshi_only:
            venues = ["kalshi"]
        elif venues is None:
            venues = self.list_venues(enabled_only=True)

        result = {}
        for venue_name in venues:
            venue = self.get_venue(venue_name)
            if venue:
                try:
                    snapshot = await venue.get_risk_snapshot()
                    result[venue_name] = snapshot
                except Exception as exc:
                    logger.error(f"Failed to get risk snapshot from {venue_name}: {exc}")
                    result[venue_name] = {}

        return result


# ── Singleton ─────────────────────────────────────────────────────────────

_registry: Optional[VenueRegistry] = None


def get_venue_registry() -> VenueRegistry:
    """Get or create the singleton VenueRegistry."""
    global _registry
    if _registry is None:
        _registry = VenueRegistry()
        _initialize_default_venues()
    return _registry


def _initialize_default_venues() -> None:
    """Register default venues at startup."""
    registry = get_venue_registry()

    # Register Kalshi
    try:
        from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
        kalshi = get_kalshi_venue_adapter()  # reads mode from settings (MERID_PM_LIVE_ENABLED)
        registry.register(kalshi, enabled=True)
    except Exception as exc:
        logger.warning(f"Failed to register Kalshi venue: {exc}")

    # Future: Register crypto exchanges, other prediction markets
    # try:
    #     from merid.event_venues.coinbase.venue_adapter import get_coinbase_venue_adapter
    #     coinbase = get_coinbase_venue_adapter()
    #     registry.register(coinbase, enabled=True)
    # except Exception as exc:
    #     logger.warning(f"Failed to register Coinbase venue: {exc}")


def reset_venue_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    _registry = None
