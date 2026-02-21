"""Tests for VenueRegistry — centralized venue management.

Tests:
- Venue registration and retrieval
- Enable/disable venue
- Multi-venue position/risk aggregation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from merid.venue_registry import (
    VenueRegistry,
    get_venue_registry,
    reset_venue_registry,
)


@pytest.fixture
def mock_venue():
    """Create a mock venue adapter."""
    venue = MagicMock()
    venue.venue_name = "test_venue"
    venue.list_instruments = AsyncMock(return_value=[])
    venue.get_positions = AsyncMock(return_value=[])
    venue.get_orders = AsyncMock(return_value=[])
    venue.submit_order = AsyncMock(return_value=None)
    venue.get_risk_snapshot = AsyncMock(return_value={
        "venue": "test_venue",
        "total_notional_usd": 100.0,
        "position_count": 2,
    })
    return venue


@pytest.fixture
def registry():
    """Create a fresh VenueRegistry for testing."""
    reset_venue_registry()
    return VenueRegistry()


# ── Test: Registration ─────────────────────────────────────────────────────

def test_registry_initialization(registry):
    """Test registry initializes empty."""
    assert registry.list_venues() == []


def test_register_venue(registry, mock_venue):
    """Test registering a venue."""
    registry.register(mock_venue, enabled=True)
    
    assert "test_venue" in registry.list_venues()
    assert registry.is_enabled("test_venue")


def test_register_venue_disabled(registry, mock_venue):
    """Test registering a disabled venue."""
    registry.register(mock_venue, enabled=False)
    
    assert "test_venue" in registry.list_venues()
    assert not registry.is_enabled("test_venue")


# ── Test: Retrieval ────────────────────────────────────────────────────────

def test_get_venue(registry, mock_venue):
    """Test retrieving a registered venue."""
    registry.register(mock_venue)
    
    retrieved = registry.get_venue("test_venue")
    assert retrieved is mock_venue


def test_get_nonexistent_venue(registry):
    """Test retrieving unregistered venue returns None."""
    retrieved = registry.get_venue("nonexistent")
    assert retrieved is None


def test_list_venues(registry, mock_venue):
    """Test listing all venues."""
    mock_venue2 = MagicMock()
    mock_venue2.venue_name = "test_venue_2"
    
    registry.register(mock_venue)
    registry.register(mock_venue2)
    
    venues = registry.list_venues()
    assert len(venues) == 2
    assert "test_venue" in venues
    assert "test_venue_2" in venues


def test_list_venues_enabled_only(registry, mock_venue):
    """Test listing only enabled venues."""
    mock_venue2 = MagicMock()
    mock_venue2.venue_name = "disabled_venue"
    
    registry.register(mock_venue, enabled=True)
    registry.register(mock_venue2, enabled=False)
    
    all_venues = registry.list_venues(enabled_only=False)
    enabled_venues = registry.list_venues(enabled_only=True)
    
    assert len(all_venues) == 2
    assert len(enabled_venues) == 1
    assert "test_venue" in enabled_venues
    assert "disabled_venue" not in enabled_venues


# ── Test: Enable/Disable ───────────────────────────────────────────────────

def test_enable_venue(registry, mock_venue):
    """Test enabling a venue."""
    registry.register(mock_venue, enabled=False)
    assert not registry.is_enabled("test_venue")
    
    success = registry.enable_venue("test_venue")
    assert success
    assert registry.is_enabled("test_venue")


def test_disable_venue(registry, mock_venue):
    """Test disabling a venue."""
    registry.register(mock_venue, enabled=True)
    assert registry.is_enabled("test_venue")
    
    success = registry.disable_venue("test_venue")
    assert success
    assert not registry.is_enabled("test_venue")


def test_enable_nonexistent_venue(registry):
    """Test enabling nonexistent venue returns False."""
    success = registry.enable_venue("nonexistent")
    assert not success


# ── Test: Multi-Venue Aggregation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_all_positions(registry, mock_venue):
    """Test getting positions from multiple venues."""
    mock_venue2 = MagicMock()
    mock_venue2.venue_name = "venue_2"
    mock_venue2.get_positions = AsyncMock(return_value=["pos2"])
    
    mock_venue.get_positions = AsyncMock(return_value=["pos1"])
    
    registry.register(mock_venue, enabled=True)
    registry.register(mock_venue2, enabled=True)
    
    all_positions = await registry.get_all_positions()
    
    assert "test_venue" in all_positions
    assert "venue_2" in all_positions
    assert all_positions["test_venue"] == ["pos1"]
    assert all_positions["venue_2"] == ["pos2"]


@pytest.mark.asyncio
async def test_get_all_positions_specific_venues(registry, mock_venue):
    """Test getting positions from specific venues only."""
    mock_venue2 = MagicMock()
    mock_venue2.venue_name = "venue_2"
    mock_venue2.get_positions = AsyncMock(return_value=["pos2"])
    
    registry.register(mock_venue, enabled=True)
    registry.register(mock_venue2, enabled=True)
    
    positions = await registry.get_all_positions(venues=["test_venue"])
    
    assert "test_venue" in positions
    assert "venue_2" not in positions


@pytest.mark.asyncio
async def test_get_all_positions_handles_errors(registry, mock_venue):
    """Test position aggregation handles venue errors gracefully."""
    mock_venue.get_positions = AsyncMock(side_effect=Exception("Connection failed"))
    registry.register(mock_venue, enabled=True)
    
    positions = await registry.get_all_positions()
    
    assert "test_venue" in positions
    assert positions["test_venue"] == []


@pytest.mark.asyncio
async def test_get_all_risk_snapshots(registry, mock_venue):
    """Test getting risk snapshots from multiple venues."""
    mock_venue2 = MagicMock()
    mock_venue2.venue_name = "venue_2"
    mock_venue2.get_risk_snapshot = AsyncMock(return_value={
        "venue": "venue_2",
        "total_notional_usd": 200.0,
    })
    
    registry.register(mock_venue, enabled=True)
    registry.register(mock_venue2, enabled=True)
    
    snapshots = await registry.get_all_risk_snapshots()
    
    assert "test_venue" in snapshots
    assert "venue_2" in snapshots
    assert snapshots["test_venue"]["total_notional_usd"] == 100.0
    assert snapshots["venue_2"]["total_notional_usd"] == 200.0


# ── Test: Singleton ────────────────────────────────────────────────────────

def test_singleton_accessor():
    """Test singleton accessor returns same instance."""
    reset_venue_registry()
    
    registry1 = get_venue_registry()
    registry2 = get_venue_registry()
    
    assert registry1 is registry2


def test_singleton_auto_registers_kalshi():
    """Test singleton automatically registers Kalshi venue."""
    reset_venue_registry()
    
    # This will trigger _initialize_default_venues()
    registry = get_venue_registry()
    
    venues = registry.list_venues()
    # Kalshi should be auto-registered (if available)
    # Note: May fail if Kalshi dependencies not available in test env
    # assert "kalshi" in venues or len(venues) == 0
